from __future__ import annotations

import importlib.util
import base64
import contextlib
import io
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

    def test_ipp_server_advertises_a_windows_renderable_default_pdl(self) -> None:
        command = entrypoint.build_ipp_command(
            "/usr/sbin/ippeveprinter",
            ppd_path=Path("/run/printer.ppd"),
            spool_dir=Path("/var/spool/jobs"),
            tls_dir=Path("/var/lib/printhub-ipp/tls"),
            hostname="printer.example.test",
            port="8631",
            service_name="PrintHub Label",
        )

        output_option = command.index("-F")
        self.assertEqual(command[output_option + 1], "application/pdf")
        ppd_option = command.index("-P")
        self.assertEqual(Path(command[ppd_option + 1]), Path("/run/printer.ppd"))
        self.assertNotIn("-a", command)
        self.assertNotIn("-f", command)

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

    def test_non_mdns_mode_does_not_claim_to_support_ippeveprinter(self) -> None:
        with patch.dict(os.environ, {"PRINTHUB_IPP_MDNS_ENABLED": "0"}, clear=True):
            with self.assertRaisesRegex(RuntimeError, "requires a local DNS-SD service"):
                entrypoint.prepare_runtime_privileges(Path("runtime"))

    def test_mdns_mode_fails_closed_when_startup_is_not_root(self) -> None:
        with (
            patch.dict(os.environ, {"PRINTHUB_IPP_MDNS_ENABLED": "1"}, clear=True),
            patch.object(entrypoint.os, "geteuid", return_value=10002, create=True),
        ):
            with self.assertRaisesRegex(RuntimeError, "mDNS mode requires root"):
                entrypoint.prepare_runtime_privileges(Path("runtime"))

    def test_ppd_reports_exact_loaded_label_and_pdf_output(self) -> None:
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
        self.assertIn('*cupsPrintQuality Draft/Text - no dithering: ""', ppd)
        self.assertIn('*cupsPrintQuality High/Photo - dithering: ""', ppd)
        self.assertIn('*ColorDevice: False', ppd)
        self.assertIn(
            '*cupsFilter2: "application/vnd.cups-pdf application/pdf 0 -"', ppd
        )

    def test_ppd_refresh_changes_only_when_loaded_media_changes(self) -> None:
        printer = {
            "name": "Workshop",
            "vendor": "Zebra",
            "model": "GK420t",
            "media": {"loaded": {"width_mm": 60, "height_mm": 30}},
            "alignment": {"dpi": 203},
        }
        with unittest.mock.patch.object(Path, "write_text"), unittest.mock.patch.object(
            Path, "replace"
        ):
            first, changed = entrypoint.write_ppd_if_changed(
                Path("printer.ppd"), printer, None
            )
            same, unchanged = entrypoint.write_ppd_if_changed(
                Path("printer.ppd"), printer, first
            )
            printer["media"]["loaded"]["height_mm"] = 40
            updated, media_changed = entrypoint.write_ppd_if_changed(
                Path("printer.ppd"), printer, first
            )

        self.assertTrue(changed)
        self.assertFalse(unchanged)
        self.assertEqual(first, same)
        self.assertTrue(media_changed)
        self.assertNotEqual(first, updated)
        self.assertIn("60 x 40 mm", updated)

    def test_chrome_acceptance_fixture_declares_one_exact_label_page(self) -> None:
        fixture = (ROOT / "tests" / "fixtures" / "chrome-label-50x25.html").read_text(
            encoding="utf-8"
        )
        self.assertIn("size: 50mm 25mm", fixture)
        self.assertIn("width: 50mm", fixture)
        self.assertIn("height: 25mm", fixture)
        self.assertNotIn("<script", fixture.lower())

    def test_ipp_reports_label_limit_hold_without_overriding_it(self) -> None:
        fixture = ROOT / "tests" / "fixtures" / "label-50mm.pdf"
        response = {
            "id": "job-1",
            "status": "held",
            "hold_reason": "label_limit_exceeded",
            "requested_labels": 100,
            "max_labels": 25,
            "page_count": 100,
        }
        output = io.StringIO()
        with (
            patch.object(submit_job, "api_request", return_value=response) as request,
            patch.dict(os.environ, {"CONTENT_TYPE": "application/pdf"}, clear=True),
            contextlib.redirect_stderr(output),
        ):
            submit_job.main(["submit_job.py", str(fixture)])

        self.assertFalse(request.call_args.kwargs["payload"].get("override_label_limit"))
        self.assertIn("job-state-reasons=job-hold-until-specified", output.getvalue())
        self.assertIn("100 requested, maximum 25", output.getvalue())

    def test_chrome_photo_fixture_is_exact_self_contained_landscape_page(self) -> None:
        fixture = (
            ROOT / "tests" / "fixtures" / "chrome-photo-50x25-landscape.html"
        ).read_text(encoding="utf-8")
        self.assertIn("size: 50mm 25mm", fixture)
        self.assertIn("width: 50mm", fixture)
        self.assertIn("height: 25mm", fixture)
        self.assertIn("C6 CHROME HIGH · LANDSCAPE", fixture)
        self.assertIn('<linearGradient id="gray"', fixture)
        self.assertIn('<linearGradient id="color"', fixture)
        self.assertIn('<radialGradient id="photo"', fixture)
        self.assertNotIn("<script", fixture.lower())
        self.assertNotIn('src="http', fixture.lower())
        self.assertNotIn('href="http', fixture.lower())

    def test_scaling_defaults_to_hold_but_honors_explicit_ipp_choice(self) -> None:
        with patch.dict(os.environ, {}, clear=True):
            self.assertEqual(submit_job.selected_scaling(), "hold")
        with patch.dict(os.environ, {"IPP_PRINT_SCALING": "fit"}, clear=True):
            self.assertEqual(submit_job.selected_scaling(), "fit")
        with patch.dict(os.environ, {"PRINTHUB_IPP_MISMATCH_POLICY": "fill"}, clear=True):
            self.assertEqual(submit_job.selected_scaling(), "fill")

    def test_standard_ipp_quality_selects_image_optimization(self) -> None:
        with patch.dict(os.environ, {"IPP_PRINT_QUALITY": "draft"}, clear=True):
            self.assertEqual(submit_job.selected_content_optimize(), "text")
        with patch.dict(os.environ, {"IPP_PRINT_QUALITY": "normal"}, clear=True):
            self.assertEqual(submit_job.selected_content_optimize(), "auto")
        with patch.dict(os.environ, {"IPP_PRINT_QUALITY": "high"}, clear=True):
            self.assertEqual(submit_job.selected_content_optimize(), "photo")
        with patch.dict(
            os.environ,
            {"IPP_PRINT_QUALITY": "draft", "IPP_PRINT_CONTENT_OPTIMIZE": "graphics"},
            clear=True,
        ):
            self.assertEqual(submit_job.selected_content_optimize(), "graphics")

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
