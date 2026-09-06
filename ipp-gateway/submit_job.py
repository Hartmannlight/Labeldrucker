#!/usr/bin/env python3
from __future__ import annotations

import base64
import hashlib
import json
import os
from pathlib import Path
import sys
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


SUPPORTED_CONTENT_TYPES = {
    "application/pdf",
    "application/postscript",
    "image/jpeg",
    "image/png",
    "image/pwg-raster",
    "image/urf",
}


def api_request(path: str, *, payload: dict[str, Any]) -> dict[str, Any]:
    base_url = os.getenv("PRINTHUB_API_URL", "http://printhub:8000").rstrip("/")
    body = json.dumps(payload).encode("utf-8")
    request = Request(
        f"{base_url}{path}",
        data=body,
        headers={"Accept": "application/json", "Content-Type": "application/json"},
        method="POST",
    )
    token = os.getenv("PRINTHUB_IPP_API_TOKEN")
    if token:
        request.add_header("Authorization", f"Bearer {token}")
    try:
        with urlopen(request, timeout=120) as response:
            result = json.load(response)
    except HTTPError as exc:
        detail = exc.read(16_384).decode("utf-8", errors="replace")
        raise RuntimeError(f"PrintHub rejected the job ({exc.code}): {detail}") from exc
    except (OSError, ValueError, URLError) as exc:
        raise RuntimeError(f"PrintHub request failed: {exc}") from exc
    if not isinstance(result, dict):
        raise RuntimeError("PrintHub returned an invalid response")
    return result


def detect_content_type(path: Path) -> str:
    configured = os.getenv("CONTENT_TYPE", "").split(";", 1)[0].strip().lower()
    if configured in SUPPORTED_CONTENT_TYPES:
        return configured
    start = path.read_bytes()[:16]
    signatures = (
        (b"%PDF-", "application/pdf"),
        (b"%!", "application/postscript"),
        (b"\x89PNG\r\n\x1a\n", "image/png"),
        (b"\xff\xd8", "image/jpeg"),
        (b"RaS2", "image/pwg-raster"),
        (b"RaS3", "image/pwg-raster"),
        (b"RaSt", "image/pwg-raster"),
        (b"UNIRAST", "image/urf"),
    )
    for signature, mime_type in signatures:
        if start.startswith(signature):
            return mime_type
    raise RuntimeError(f"Unsupported print document format: {configured or 'unknown'}")


def selected_scaling() -> str:
    requested = os.getenv("IPP_PRINT_SCALING", "").strip().lower()
    if requested in {"fit", "fill"}:
        return requested
    fallback = os.getenv("PRINTHUB_IPP_MISMATCH_POLICY", "hold").strip().lower()
    return fallback if fallback in {"hold", "fit", "fill"} else "hold"


def selected_content_optimize() -> str:
    value = os.getenv("IPP_PRINT_CONTENT_OPTIMIZE", "auto").strip().lower()
    if value in {"text", "graphics", "photo"}:
        return value
    quality = os.getenv("IPP_PRINT_QUALITY", "normal").strip().lower()
    if quality == "high":
        return "photo"
    if quality == "draft":
        return "text"
    return "auto"


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
    document = path.read_bytes()
    maximum_bytes = max(
        1, int(os.getenv("PRINTHUB_IPP_MAX_DOCUMENT_BYTES", str(32 * 1024 * 1024)))
    )
    if not document or len(document) > maximum_bytes:
        raise RuntimeError(f"IPP document must contain between 1 and {maximum_bytes} bytes")
    printer_id = os.getenv("PRINTHUB_IPP_PRINTER_ID", "virtual-zebra")
    queue_id = os.getenv("PRINTHUB_IPP_QUEUE_ID", printer_id)
    copies = max(1, min(999, int(os.getenv("IPP_COPIES", "1"))))
    result = api_request(
        "/v1/print-jobs/documents",
        payload={
            "printer_id": printer_id,
            "mime_type": detect_content_type(path),
            "data_base64": base64.b64encode(document).decode("ascii"),
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
    pages = int(result.get("page_count") or 0)
    print(f"INFO: PrintHub job {result.get('id')} is {status}", file=sys.stderr)
    if status == "held":
        print("ATTR: job-state-reasons=job-hold-until-specified", file=sys.stderr)
    if pages:
        print(f"ATTR: job-impressions={pages}", file=sys.stderr)


if __name__ == "__main__":
    try:
        main(sys.argv)
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc
