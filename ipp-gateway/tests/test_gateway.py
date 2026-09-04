from __future__ import annotations

import importlib.util
import ctypes
import os
from pathlib import Path
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
pwg_raster = load_module("ipp_gateway_pwg_raster", "pwg_raster.py")


class GatewayTests(unittest.TestCase):
    def test_cups_page_header_matches_libcups_abi(self) -> None:
        self.assertEqual(ctypes.sizeof(pwg_raster.CupsPageHeader2), 1796)

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

    def test_pdf_info_preserves_page_dimensions(self) -> None:
        count, sizes = submit_job.parse_pdf_info(
            "Pages:           2\n"
            "Page 1 size:     141.732 x 141.732 pts\n"
            "Page 2 size:     595.276 x 841.89 pts\n"
        )
        self.assertEqual(count, 2)
        self.assertAlmostEqual(sizes[0][0], 50.0, places=2)
        self.assertAlmostEqual(sizes[0][1], 50.0, places=2)
        self.assertAlmostEqual(sizes[1][0], 210.0, places=2)
        self.assertAlmostEqual(sizes[1][1], 297.0, places=2)

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


if __name__ == "__main__":
    unittest.main()
