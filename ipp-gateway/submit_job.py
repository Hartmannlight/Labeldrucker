#!/usr/bin/env python3
from __future__ import annotations

import base64
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import quote
from urllib.request import Request, urlopen


PDF_PAGE_SIZE = re.compile(r"^Page\s+(\d+)\s+size:\s+([0-9.]+)\s+x\s+([0-9.]+)\s+pts", re.MULTILINE)
PDF_PAGE_COUNT = re.compile(r"^Pages:\s+(\d+)\s*$", re.MULTILINE)


def api_request(path: str, *, payload: dict[str, Any] | None = None) -> dict[str, Any]:
    base_url = os.getenv("PRINTHUB_API_URL", "http://printhub:8000").rstrip("/")
    body = json.dumps(payload).encode("utf-8") if payload is not None else None
    request = Request(
        f"{base_url}{path}",
        data=body,
        headers={"Accept": "application/json", **({"Content-Type": "application/json"} if body else {})},
        method="POST" if body else "GET",
    )
    token = os.getenv("PRINTHUB_IPP_API_TOKEN")
    if token:
        request.add_header("Authorization", f"Bearer {token}")
    try:
        with urlopen(request, timeout=120 if body else 5) as response:
            result = json.load(response)
    except HTTPError as exc:
        detail = exc.read(16_384).decode("utf-8", errors="replace")
        raise RuntimeError(f"PrintHub rejected the job ({exc.code}): {detail}") from exc
    except (OSError, ValueError, URLError) as exc:
        raise RuntimeError(f"PrintHub request failed: {exc}") from exc
    if not isinstance(result, dict):
        raise RuntimeError("PrintHub returned an invalid response")
    return result


def printer_target(printer_id: str) -> tuple[float, float, int]:
    printer = api_request(f"/v1/printers/{quote(printer_id, safe='')}")
    loaded = (printer.get("media") or {}).get("loaded") or {}
    alignment = printer.get("alignment") or {}
    try:
        return float(loaded["width_mm"]), float(loaded["height_mm"]), int(alignment["dpi"])
    except (KeyError, TypeError, ValueError) as exc:
        raise RuntimeError("PrintHub has no current media size or resolution for this printer") from exc


def parse_pdf_info(output: str) -> tuple[int, list[tuple[float, float]]]:
    count_match = PDF_PAGE_COUNT.search(output)
    if count_match is None:
        raise RuntimeError("pdfinfo did not report a page count")
    count = int(count_match.group(1))
    sizes_by_page = {
        int(page): (float(width) * 25.4 / 72.0, float(height) * 25.4 / 72.0)
        for page, width, height in PDF_PAGE_SIZE.findall(output)
    }
    sizes = [sizes_by_page[index] for index in range(1, count + 1) if index in sizes_by_page]
    if len(sizes) != count:
        raise RuntimeError("pdfinfo did not report every PDF page size")
    return count, sizes


def _run(command: list[str], *, timeout: int) -> subprocess.CompletedProcess[str]:
    try:
        return subprocess.run(
            command,
            check=True,
            capture_output=True,
            text=True,
            timeout=timeout,
            env={**os.environ, "LC_ALL": "C"},
        )
    except subprocess.TimeoutExpired as exc:
        raise RuntimeError(f"Document conversion timed out: {command[0]}") from exc
    except subprocess.CalledProcessError as exc:
        message = (exc.stderr or exc.stdout or str(exc)).strip()
        raise RuntimeError(f"Document conversion failed: {message}") from exc


def rasterize_pdf(path: Path, *, dpi: int, output_dir: Path) -> list[dict[str, Any]]:
    maximum_pages = max(1, int(os.getenv("PRINTHUB_IPP_MAX_PAGES", "100")))
    summary = _run(["pdfinfo", str(path)], timeout=15).stdout
    count_match = PDF_PAGE_COUNT.search(summary)
    if count_match is None:
        raise RuntimeError("pdfinfo did not report a page count")
    page_count = int(count_match.group(1))
    if page_count > maximum_pages:
        raise RuntimeError(f"Document has {page_count} pages; the configured maximum is {maximum_pages}")
    details = _run(
        ["pdfinfo", "-f", "1", "-l", str(page_count), str(path)],
        timeout=20,
    ).stdout
    _, sizes = parse_pdf_info(details)
    prefix = output_dir / "page"
    _run(
        [
            "pdftocairo",
            "-png",
            "-r",
            str(dpi),
            "-f",
            "1",
            "-l",
            str(page_count),
            str(path),
            str(prefix),
        ],
        timeout=max(60, page_count * 10),
    )
    files = sorted(
        output_dir.glob("page-*.png"),
        key=lambda item: int(item.stem.rsplit("-", 1)[-1]),
    )
    if len(files) != page_count:
        raise RuntimeError("PDF rasterization produced an unexpected number of pages")
    pages: list[dict[str, Any]] = []
    for file, (width_mm, height_mm) in zip(files, sizes, strict=True):
        pages.append(
            {
                "mime_type": "image/png",
                "data_base64": base64.b64encode(file.read_bytes()).decode("ascii"),
                "width_mm": width_mm,
                "height_mm": height_mm,
            }
        )
    return pages


def rasterize_postscript(path: Path, *, dpi: int, output_dir: Path) -> list[dict[str, Any]]:
    pdf_path = output_dir / "converted.pdf"
    _run(
        [
            "gs",
            "-q",
            "-dSAFER",
            "-dBATCH",
            "-dNOPAUSE",
            "-sDEVICE=pdfwrite",
            f"-sOutputFile={pdf_path}",
            str(path),
        ],
        timeout=60,
    )
    return rasterize_pdf(pdf_path, dpi=dpi, output_dir=output_dir)


def detect_content_type(path: Path) -> str:
    configured = os.getenv("CONTENT_TYPE", "").split(";", 1)[0].strip().lower()
    if configured in {"application/pdf", "application/postscript", "image/png", "image/jpeg", "image/pwg-raster", "image/urf"}:
        return configured
    start = path.read_bytes()[:16]
    if start.startswith(b"%PDF-"):
        return "application/pdf"
    if start.startswith(b"%!"):
        return "application/postscript"
    if start.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    if start.startswith(b"\xff\xd8"):
        return "image/jpeg"
    if start.startswith((b"RaS2", b"RaS3", b"RaSt")):
        return "image/pwg-raster"
    if start.startswith(b"UNIRAST"):
        return "image/urf"
    raise RuntimeError(f"Unsupported print document format: {configured or 'unknown'}")


def selected_scaling() -> str:
    requested = os.getenv("IPP_PRINT_SCALING", "").strip().lower()
    if requested in {"fit", "fill"}:
        return requested
    fallback = os.getenv("PRINTHUB_IPP_MISMATCH_POLICY", "hold").strip().lower()
    return fallback if fallback in {"hold", "fit", "fill"} else "hold"


def selected_content_optimize() -> str:
    value = os.getenv("IPP_PRINT_CONTENT_OPTIMIZE", "auto").strip().lower()
    return value if value in {"auto", "text", "graphics", "photo"} else "auto"


def find_job_file(arguments: list[str]) -> Path:
    for argument in reversed(arguments[1:]):
        path = Path(argument)
        if path.is_file():
            return path
    raise RuntimeError("ippeveprinter did not provide a readable job file")


def idempotency_key(path: Path, queue_id: str) -> str:
    job_uuid = os.getenv("IPP_JOB_UUID", "").strip()
    if job_uuid:
        return f"ipp:{queue_id}:{job_uuid}"
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    local_job_id = os.getenv("IPP_JOB_ID", "no-id").strip() or "no-id"
    return f"ipp:{queue_id}:{local_job_id}:{digest}"


def main(arguments: list[str]) -> None:
    path = find_job_file(arguments)
    printer_id = os.getenv("PRINTHUB_IPP_PRINTER_ID", "virtual-zebra")
    width_mm, height_mm, dpi = printer_target(printer_id)
    content_type = detect_content_type(path)
    if content_type in {"application/pdf", "application/postscript"}:
        with tempfile.TemporaryDirectory(prefix="printhub-ipp-") as temporary:
            output_dir = Path(temporary)
            pages = (
                rasterize_pdf(path, dpi=dpi, output_dir=output_dir)
                if content_type == "application/pdf"
                else rasterize_postscript(path, dpi=dpi, output_dir=output_dir)
            )
    elif content_type in {"image/pwg-raster", "image/urf"}:
        from pwg_raster import read_pwg_raster

        pages = [
            {
                "mime_type": page["mime_type"],
                "data_base64": base64.b64encode(page["data"]).decode("ascii"),
                "width_mm": page["width_mm"],
                "height_mm": page["height_mm"],
            }
            for page in read_pwg_raster(path)
        ]
    else:
        pages = [
            {
                "mime_type": content_type,
                "data_base64": base64.b64encode(path.read_bytes()).decode("ascii"),
                "width_mm": width_mm,
                "height_mm": height_mm,
            }
        ]
    maximum_bytes = max(1, int(os.getenv("PRINTHUB_IPP_MAX_ENCODED_BYTES", str(48 * 1024 * 1024))))
    if sum(len(page["data_base64"]) for page in pages) > maximum_bytes:
        raise RuntimeError("Rasterized document exceeds the configured upload limit")

    queue_id = os.getenv("PRINTHUB_IPP_QUEUE_ID", printer_id)
    copies = max(1, min(999, int(os.getenv("IPP_COPIES", "1"))))
    result = api_request(
        "/v1/print-jobs/raster",
        payload={
            "printer_id": printer_id,
            "pages": pages,
            "copies": copies,
            "scaling": selected_scaling(),
            "content_optimize": selected_content_optimize(),
            "dither": "auto",
            "idempotency_key": idempotency_key(path, queue_id),
            "origin": "ipp",
        },
    )
    status = str(result.get("status") or "unknown")
    if status == "failed":
        raise RuntimeError(str(result.get("error") or "PrintHub failed the print job"))
    print(f"INFO: PrintHub job {result.get('id')} is {status}", file=sys.stderr)
    print(f"ATTR: job-impressions={len(pages)} job-impressions-completed={len(pages)}", file=sys.stderr)


if __name__ == "__main__":
    try:
        main(sys.argv)
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc
