"""Behavioral checks for the one-shot installer without Docker or a printer."""

from __future__ import annotations

import json
from pathlib import Path
import shutil
import unittest
from contextlib import contextmanager
from uuid import uuid4

from setup import apply as installer
from setup import wizard

TEMP_ROOT = Path(__file__).resolve().parents[2] / "test-tmp"
TEMP_ROOT.mkdir(exist_ok=True)


@contextmanager
def test_directory():
    root = TEMP_ROOT / f"setup-{uuid4().hex}"
    root.mkdir()
    try:
        yield root
    finally:
        shutil.rmtree(root)


class WizardTests(unittest.TestCase):
    def test_guided_install_writes_configuration_and_keeps_unrelated_values(self) -> None:
        with test_directory() as root:
            (root / ".env.example").write_text("TZ=UTC\nCUSTOM_SETTING=keep\n", encoding="utf-8")
            answers = iter([
                "", "j", "", "", "",  # project, LAN, bind, port, timezone
                "", "", "", "", "192.0.2.10", "", "",  # first printer, TCP, id, name, host, port, DPI
                "", "", "", "250", "", "", "j", "",  # size, stock, tracking, thermal, IPP, queue
                "n", "", "print.example.test", "j", "n", "n", "j", "openai/gpt-4o-mini", "",
            ])
            messages: list[str] = []
            io = wizard.Prompts(ask=lambda _: str(next(answers)),
                                secret=lambda _: "secret-key", say=messages.append)
            self.assertTrue(wizard.run(root, io))
            env = wizard.read_env(root / ".env")
            self.assertEqual(env["CUSTOM_SETTING"], "keep")
            self.assertEqual(env["PRINTHUB_STUDIO_BIND"], "0.0.0.0")
            self.assertEqual(env["PRINTHUB_IPP_HOSTNAME"], "print.example.test")
            self.assertEqual(env["PRINTHUB_AI_API_KEY"], "secret-key")
            self.assertEqual(env["PRINTHUB_AI_MODEL"], "openai/gpt-4o-mini")
            self.assertEqual(env["ZPLGRID_ENABLE_LABELARY_TEMPLATES"], "1")
            self.assertEqual(env["ZPLGRID_ENABLE_LABELARY_API"], "0")
            self.assertNotIn("secret-key", "\n".join(messages))
            manifest = json.loads((root / "config" / "printhub-install.json").read_text(encoding="utf-8"))
            self.assertEqual(manifest["printers"][0]["media"]["labels_available_at_load"], 250)
            self.assertEqual(manifest["printers"][0]["ipp"]["queue_id"], "zebra-1")

    def test_cancellation_changes_nothing(self) -> None:
        with test_directory() as root:
            (root / ".env.example").write_text("TZ=UTC\n", encoding="utf-8")
            answers = iter(["", "n", "", "", "n", "n", "n", "n", "n", "n"])
            io = wizard.Prompts(ask=lambda _: next(answers), secret=lambda _: "", say=lambda _: None)
            self.assertFalse(wizard.run(root, io))
            self.assertFalse((root / ".env").exists())
            self.assertFalse((root / "config" / "printhub-install.json").exists())

    def test_usb_install_writes_overlay_config(self) -> None:
        with test_directory() as root:
            (root / ".env.example").write_text("TZ=UTC\n", encoding="utf-8")
            answers = iter([
                "", "n", "", "", "", "2", "", "", "/dev/usb/lp0", "",
                "", "", "", "100", "", "", "n", "n", "n", "n", "n", "n", "",
            ])
            io = wizard.Prompts(ask=lambda _: next(answers), secret=lambda _: "", say=lambda _: None)
            self.assertTrue(wizard.run(root, io))
            self.assertEqual(wizard.read_env(root / ".env")["ZEBRATAMER_USB_DEVICE"], "/dev/usb/lp0")
            self.assertTrue((root / "config" / "zebratamer.usb.toml").is_file())
            manifest = json.loads((root / "config" / "printhub-install.json").read_text(encoding="utf-8"))
            self.assertEqual(manifest["printers"][0]["service"], "usb-local")


def sample_printer(printer_id: str = "zebra-1") -> dict:
    return {
        "id": printer_id, "display_name": "Zebra", "service": "default",
        "transport": "tcp", "tcp_host": "192.0.2.10", "tcp_port": 9100,
        "device": "", "dpi": 203,
        "media": {"display_name": "50 x 25", "width_mm": 50.0,
                  "height_mm": 25.0, "labels_available_at_load": 250,
                  "tracking": "gap", "print_technology": "direct_thermal"},
        "ipp": {"queue_id": printer_id, "display_name": "Zebra"},
    }


class ApplyTests(unittest.TestCase):
    def test_first_application_then_repeat_preserves_existing_state(self) -> None:
        with test_directory() as root:
            manifest = root / "manifest.json"
            stamp = root / "stamp.txt"
            manifest.write_text(json.dumps({"version": 1, "printers": [sample_printer()]}), encoding="utf-8")
            printers: dict[str, dict] = {}
            shares: dict[str, dict] = {}
            calls: list[tuple[str, str]] = []

            def request(method: str, url: str, token: str | None, body: dict | None,
                        allow_404: bool) -> dict | None:
                calls.append((method, url))
                if url.endswith("/v2/printers/zebra-1"):
                    return printers.get("zebra-1")
                if url.endswith("/v2/extensions/zebra/printers/zebra-1"):
                    printers["zebra-1"] = {"id": "zebra-1", "media": {"loaded": None}}
                    return {"printer": body}
                if url.endswith("/v1/printers"):
                    return {"printers": [{"id": "zebra-1", "service_connection_id": "default",
                                         "service_printer_id": "zebra-1", "media": printers["zebra-1"]["media"]}]}
                if url.endswith("/v1/printer-services/default/printers/zebra-1/media"):
                    printers["zebra-1"]["media"] = {"loaded": {"remaining_labels": 250}}
                    return printers["zebra-1"]["media"]
                if url.endswith("/v1/ipp-shares"):
                    return {"items": list(shares.values())}
                if url.endswith("/v1/ipp-shares/zebra-1"):
                    shares["zebra-1"] = {"queue_id": "zebra-1", "port": 8631, **(body or {})}
                    return shares["zebra-1"]
                raise AssertionError((method, url))

            self.assertTrue(installer.apply(manifest, stamp, "admin", "zebra", request=request))
            self.assertEqual(printers["zebra-1"]["media"]["loaded"]["remaining_labels"], 250)
            self.assertEqual(shares["zebra-1"]["port"], 8631)
            first_calls = len(calls)
            self.assertFalse(installer.apply(manifest, stamp, "admin", "zebra", request=request))
            self.assertEqual(len(calls), first_calls)
            manifest.write_text(json.dumps({"version": 1, "printers": [sample_printer()]}, indent=2), encoding="utf-8")
            self.assertTrue(installer.apply(manifest, stamp, "admin", "zebra", request=request))
            self.assertEqual(len([item for item in calls if item[0] == "PUT"]), 2)
            self.assertEqual(len([item for item in calls if item[0] == "POST"]), 1)
            shares["zebra-1"]["printer_id"] = "another-printer"
            manifest.write_text(json.dumps({"version": 1, "printers": [sample_printer()]}, indent=4), encoding="utf-8")
            with self.assertRaisesRegex(RuntimeError, "anderen Drucker"):
                installer.apply(manifest, stamp, "admin", "zebra", request=request)

    def test_invalid_manifest_is_rejected_before_requests(self) -> None:
        payload = {"version": 1, "printers": [sample_printer(), sample_printer()]}
        with self.assertRaises(ValueError):
            installer.validate_manifest(payload)


if __name__ == "__main__":
    unittest.main()
