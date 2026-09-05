from __future__ import annotations

import importlib.util
import base64
import os
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]


def load_module(name: str, filename: str):
    spec = importlib.util.spec_from_file_location(name, ROOT / filename)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


entrypoint = load_module("ipp_gateway_entrypoint", "entrypoint.py")
submit_job = load_module("ipp_gateway_submit", "submit_job.py")


class GatewayTests(unittest.TestCase):
    def test_ipp_server_uses_explicit_persistent_tls_directory(self) -> None:
        command = entrypoint.build_ipp_command(
            "/usr/sbin/ippeveprinter",
            ppd_path=Path("/run/printer.ppd"),
            spool_dir=Path("/var/spool/jobs"),
            tls_dir=Path("/var/lib/printhub-ipp/tls"),
            hostname="printer.example.test",
            port="8631",
            service_name="PrintHub Label",
        )
        key_option = command.index("-K")
        self.assertEqual(
            Path(command[key_option + 1]), Path("/var/lib/printhub-ipp/tls")
        )

    def test_privilege_drop_updates_identity_environment_for_cups_tls(self) -> None:
        account = SimpleNamespace(
            pw_uid=10002,
            pw_gid=10002,
            pw_dir="/home/appuser",
            pw_name="appuser",
        )
        with (
            patch.object(entrypoint, "pwd") as pwd_module,
            patch.object(entrypoint.os, "chown", create=True),
            patch.object(entrypoint.os, "setgroups", create=True),
            patch.object(entrypoint.os, "setgid", create=True),
            patch.object(entrypoint.os, "setuid", create=True),
            patch.dict(
                entrypoint.os.environ,
                {"HOME": "/root", "USER": "root", "LOGNAME": "root"},
                clear=True,
            ),
        ):
            pwd_module.getpwuid.return_value = account
            entrypoint.drop_privileges(Path("tls"))
            self.assertEqual(entrypoint.os.environ["HOME"], "/home/appuser")
            self.assertEqual(entrypoint.os.environ["USER"], "appuser")
            self.assertEqual(entrypoint.os.environ["LOGNAME"], "appuser")

    def test_production_mode_runs_without_root_or_discovery_daemons(self) -> None:
        with (
            patch.dict(os.environ, {"PRINTHUB_IPP_MDNS_ENABLED": "0"}, clear=True),
            patch.object(entrypoint.os, "geteuid", return_value=10002, create=True),
            patch.object(entrypoint, "start_discovery_services") as discovery,
            patch.object(entrypoint, "drop_privileges") as drop,
        ):
            entrypoint.prepare_runtime_privileges(Path("runtime"))
        discovery.assert_not_called()
        drop.assert_not_called()

    def test_mdns_mode_fails_closed_when_startup_is_not_root(self) -> None:
        with (
            patch.dict(os.environ, {"PRINTHUB_IPP_MDNS_ENABLED": "1"}, clear=True),
            patch.object(entrypoint.os, "geteuid", return_value=10002, create=True),
        ):
            with self.assertRaisesRegex(RuntimeError, "mDNS mode requires root"):
                entrypoint.prepare_runtime_privileges(Path("runtime"))

    def test_ppd_reports_exact_loaded_label(self) -> None:
        ppd = entrypoint.build_ppd(
            {
                "name": "Workshop",
                "vendor": "Zebra",
                "model": "GX420d",
                "media": {"loaded": {"width_mm": 50, "height_mm": 50}},
                "alignment": {"dpi": 203},
            }
        )
        self.assertIn('*PageSize Label/50 x 50 mm:', ppd)
        self.assertIn('*PaperDimension Label: "141.732 141.732"', ppd)
        self.assertIn('*DefaultResolution: 203dpi', ppd)
        self.assertIn('*Resolution 203dpi/203 dpi:', ppd)
        self.assertIn('*ColorDevice: False', ppd)

    def test_chrome_acceptance_fixture_declares_one_exact_label_page(self) -> None:
        fixture = (ROOT / "tests" / "fixtures" / "chrome-label-50x25.html").read_text(
            encoding="utf-8"
        )
        self.assertIn("size: 50mm 25mm", fixture)
        self.assertIn("width: 50mm", fixture)
        self.assertIn("height: 25mm", fixture)
        self.assertNotIn("<script", fixture.lower())

    def test_scaling_defaults_to_hold_but_honors_explicit_ipp_choice(self) -> None:
        with patch.dict(os.environ, {}, clear=True):
            self.assertEqual(submit_job.selected_scaling(), "hold")
        with patch.dict(os.environ, {"IPP_PRINT_SCALING": "fit"}, clear=True):
            self.assertEqual(submit_job.selected_scaling(), "fit")
        with patch.dict(os.environ, {"PRINTHUB_IPP_MISMATCH_POLICY": "fill"}, clear=True):
            self.assertEqual(submit_job.selected_scaling(), "fill")

    def test_job_file_selection_requires_an_existing_file(self) -> None:
        job = Path(__file__)
        self.assertEqual(submit_job.find_job_file(["submit", "7", str(job)]), job)
        with self.assertRaisesRegex(RuntimeError, "readable job file"):
            submit_job.find_job_file(["submit", "missing"])

    def test_apple_raster_is_detected_for_driverless_clients(self) -> None:
        job = ROOT / "tests" / "fixtures" / "sample.urf"
        with patch.dict(os.environ, {}, clear=True):
            self.assertEqual(submit_job.detect_content_type(job), "image/urf")

    def test_postscript_is_detected_for_the_ppd_compatibility_path(self) -> None:
        job = ROOT / "tests" / "fixtures" / "label-50mm.ps"
        with patch.dict(os.environ, {}, clear=True):
            self.assertEqual(submit_job.detect_content_type(job), "application/postscript")

    def test_idempotency_uses_global_job_uuid_or_content_safe_fallback(self) -> None:
        first = ROOT / "tests" / "test_gateway.py"
        second = ROOT / "tests" / "print-job.test"
        with patch.dict(os.environ, {"IPP_JOB_UUID": "urn:uuid:abc"}, clear=True):
            self.assertEqual(submit_job.idempotency_key(first, "queue"), "ipp:queue:urn:uuid:abc")
        with patch.dict(os.environ, {"IPP_JOB_ID": "1"}, clear=True):
            self.assertNotEqual(
                submit_job.idempotency_key(first, "queue"),
                submit_job.idempotency_key(second, "queue"),
            )

    def test_gateway_forwards_original_document_and_ticket(self) -> None:
        job = ROOT / "tests" / "fixtures" / "label-50mm.pdf"
        accepted = {"id": "job-1", "status": "queued", "page_count": None}
        with (
            patch.dict(
                os.environ,
                {
                    "CONTENT_TYPE": "application/pdf",
                    "PRINTHUB_IPP_PRINTER_ID": "shipping",
                    "IPP_PRINT_SCALING": "fit",
                },
                clear=True,
            ),
            patch.object(submit_job, "api_request", return_value=accepted) as request,
        ):
            submit_job.main(["submit", str(job)])
        (path,) = request.call_args.args
        payload = request.call_args.kwargs["payload"]
        self.assertEqual(path, "/v1/print-jobs/documents")
        self.assertEqual(payload["printer_id"], "shipping")
        self.assertEqual(payload["mime_type"], "application/pdf")
        self.assertEqual(payload["scaling"], "fit")
        self.assertEqual(base64.b64decode(payload["data_base64"]), job.read_bytes())


if __name__ == "__main__":
    unittest.main()
