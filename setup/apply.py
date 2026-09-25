"""Apply the setup manifest once after PrintHub becomes healthy."""

from __future__ import annotations

import hashlib
import json
import math
import os
from pathlib import Path
import re
import sys
import tempfile
import time
from typing import Any, Callable
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


ID_PATTERN = re.compile(r"[A-Za-z0-9_-]{1,80}\Z")
RequestFn = Callable[[str, str, str | None, dict[str, Any] | None, bool], Any]


def request_json(method: str, url: str, token: str | None = None,
                 body: dict[str, Any] | None = None, allow_404: bool = False) -> Any:
    headers = {"Accept": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    data = None
    if body is not None:
        headers["Content-Type"] = "application/json"
        data = json.dumps(body).encode("utf-8")
    try:
        with urlopen(Request(url, data=data, headers=headers, method=method), timeout=20) as response:
            raw = response.read()
            return json.loads(raw) if raw else {}
    except HTTPError as exc:
        if allow_404 and exc.code == 404:
            return None
        detail = exc.read(400).decode("utf-8", "replace")
        raise RuntimeError(f"{method} {url}: HTTP {exc.code}: {detail}") from exc
    except URLError as exc:
        raise RuntimeError(f"{method} {url}: Dienst nicht erreichbar: {exc.reason}") from exc


def validate_manifest(payload: Any) -> list[dict[str, Any]]:
    if not isinstance(payload, dict) or payload.get("version") != 1 or not isinstance(payload.get("printers"), list):
        raise ValueError("Ungültiges PrintHub-Installationsmanifest")
    printers = payload["printers"]
    if len(printers) > 20:
        raise ValueError("Maximal 20 Drucker im Installationsmanifest")
    ids: set[str] = set()
    queues: set[str] = set()
    for printer in printers:
        if not isinstance(printer, dict):
            raise ValueError("Druckereintrag muss ein Objekt sein")
        printer_id = printer.get("id")
        if not isinstance(printer_id, str) or not ID_PATTERN.fullmatch(printer_id) or printer_id in ids:
            raise ValueError(f"Ungültige oder doppelte Drucker-ID: {printer_id}")
        ids.add(printer_id)
        if not isinstance(printer.get("display_name"), str) or not 0 < len(printer["display_name"].strip()) <= 200:
            raise ValueError(f"Ungültiger Anzeigename für {printer_id}")
        if printer.get("service") not in {"default", "usb-local"}:
            raise ValueError(f"Unbekannter Druckdienst für {printer_id}")
        if printer.get("transport") not in {"tcp", "char_device"}:
            raise ValueError(f"Unbekannte Verbindung für {printer_id}")
        if printer["transport"] == "tcp":
            if printer["service"] != "default" or not isinstance(printer.get("tcp_host"), str) or not printer["tcp_host"]:
                raise ValueError(f"TCP-Adresse fehlt für {printer_id}")
            port = printer.get("tcp_port")
            if isinstance(port, bool) or not isinstance(port, int) or not 1 <= port <= 65535:
                raise ValueError(f"Ungültiger TCP-Port für {printer_id}")
        elif printer["service"] != "usb-local" or not isinstance(printer.get("device"), str) or not printer["device"].startswith("/dev/"):
            raise ValueError(f"USB-Gerätepfad fehlt für {printer_id}")
        if isinstance(printer.get("dpi"), bool) or not isinstance(printer.get("dpi"), int) or not 100 <= printer["dpi"] <= 1200:
            raise ValueError(f"Ungültige DPI für {printer_id}")
        media = printer.get("media")
        if not isinstance(media, dict) or any(
            isinstance(media.get(key), bool) or not isinstance(media.get(key), (int, float)) or not 0 < media[key] <= 1000
            for key in ("width_mm", "height_mm")
        ):
            raise ValueError(f"Ungültige Mediengröße für {printer_id}")
        if (not isinstance(media.get("display_name"), str) or not 0 < len(media["display_name"].strip()) <= 200
                or media.get("tracking") not in {"gap", "black_mark", "continuous"}
                or media.get("print_technology") not in {"direct_thermal", "thermal_transfer"}):
            raise ValueError(f"Ungültige Medienangaben für {printer_id}")
        quantity = media.get("labels_available_at_load")
        if isinstance(quantity, bool) or not isinstance(quantity, int) or not 0 <= quantity <= 10_000_000:
            raise ValueError(f"Ungültiger Rollenbestand für {printer_id}")
        ipp = printer.get("ipp")
        if ipp is not None:
            queue = ipp.get("queue_id") if isinstance(ipp, dict) else None
            if not isinstance(queue, str) or not ID_PATTERN.fullmatch(queue) or queue in queues:
                raise ValueError(f"Ungültige oder doppelte IPP-Freigabe-ID: {queue}")
            if not isinstance(ipp.get("display_name"), str) or not 0 < len(ipp["display_name"].strip()) <= 200:
                raise ValueError(f"Ungültiger IPP-Anzeigename für {printer_id}")
            queues.add(queue)
    return printers


def zebra_config(printer: dict[str, Any]) -> dict[str, Any]:
    media = printer["media"]
    required_width = math.ceil(float(media["width_mm"]) * int(printer["dpi"]) / 25.4)
    return {
        "id": printer["id"], "display_name": printer["display_name"],
        "enabled": True, "transport": printer["transport"], "driver": "zpl",
        "tcp_host": printer.get("tcp_host"), "tcp_port": printer.get("tcp_port", 9100),
        "device": printer.get("device", ""),
        "device_profile": {
            "resolution_dpi": printer["dpi"],
            "max_width_dots": max(832, required_width),
            "max_length_dots": 32000, "max_speed_ips": 6,
            "max_offset_dots": 64,
            "thermal_transfer": media["print_technology"] == "thermal_transfer",
            "peel_off": False, "cutter": False,
        },
    }


def media_config(printer: dict[str, Any]) -> dict[str, Any]:
    media = printer["media"]
    return {
        "display_name": media["display_name"], "product_number": None,
        "manufacturer": None, "description": None,
        "width_mm": media["width_mm"], "height_mm": media["height_mm"],
        "gap_mm": None, "corner_radius_mm": None,
        "black_mark_width_mm": None, "black_mark_height_mm": None,
        "core_diameter_mm": None, "outer_diameter_mm": None,
        "shape": "rectangle", "tracking": media["tracking"],
        "print_technology": media["print_technology"],
        "color": {"name": "White", "hex": "#ffffff", "description": None},
        "material": None, "surface": None, "transparent": None,
        "thermal_coating": None, "thickness_micrometers": None,
        "adhesive": None, "liner": None, "ribbon": None,
        "preferred_settings": {}, "labels_available_at_load": media["labels_available_at_load"],
        "nominal_full_roll_labels": None, "low_warning_threshold": 10,
        "custom": {},
    }


def write_stamp(path: Path, digest: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(prefix=".install-", dir=path.parent)
    try:
        with os.fdopen(descriptor, "w", encoding="ascii") as handle:
            handle.write(digest + "\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def apply(manifest_path: Path, stamp_path: Path, admin_token: str, zebra_token: str,
          request: RequestFn = request_json, printhub_url: str = "http://printhub:8000",
          zebra_url: str = "http://zebratamer:8080",
          usb_url: str = "http://zebratamer-usb:8080") -> bool:
    if not manifest_path.exists():
        print("Kein Installationsmanifest vorhanden; config-apply übersprungen.")
        return False
    raw = manifest_path.read_bytes()
    digest = hashlib.sha256(raw).hexdigest()
    printers = validate_manifest(json.loads(raw))
    if stamp_path.exists() and stamp_path.read_text(encoding="ascii").strip() == digest:
        print("Installationsmanifest wurde bereits angewendet.")
        return False
    service_urls = {"default": zebra_url.rstrip("/"), "usb-local": usb_url.rstrip("/")}
    printhub_url = printhub_url.rstrip("/")
    for printer in printers:
        printer_id = printer["id"]
        service = printer["service"]
        base = service_urls[service]
        existing = request("GET", f"{base}/v2/printers/{printer_id}", zebra_token, None, True)
        if existing is None:
            request("POST", f"{base}/v2/extensions/zebra/printers/{printer_id}",
                    zebra_token, zebra_config(printer), False)
            print(f"Drucker {printer_id} angelegt.")
        else:
            print(f"Drucker {printer_id} vorhanden; Einstellungen bleiben erhalten.")

        public = None
        for attempt in range(10):
            catalog = request("GET", f"{printhub_url}/v1/printers", None, None, False)
            public = next((item for item in catalog.get("printers", [])
                           if item.get("service_connection_id") == service
                           and item.get("service_printer_id") == printer_id), None)
            if public:
                break
            if attempt < 9:
                time.sleep(0.5)
        if not public:
            raise RuntimeError(f"Drucker {printer_id} erscheint nicht im PrintHub-Katalog")
        if not (public.get("media") or {}).get("loaded"):
            request("PUT", f"{printhub_url}/v1/printer-services/{service}/printers/{printer_id}/media",
                    admin_token, media_config(printer), False)
            print(f"Medien für {printer_id} gesetzt.")
        else:
            print(f"Medien für {printer_id} vorhanden; Rolle bleibt erhalten.")

        ipp = printer.get("ipp")
        if ipp:
            shares = request("GET", f"{printhub_url}/v1/ipp-shares", None, None, False)
            existing_queue = next((item for item in shares.get("items", [])
                                   if item.get("queue_id") == ipp["queue_id"]), None)
            if existing_queue is None:
                share = request("PUT", f"{printhub_url}/v1/ipp-shares/{ipp['queue_id']}",
                                admin_token, {"printer_id": public["id"],
                                              "display_name": ipp["display_name"], "enabled": True}, False)
                print(f"IPP-Freigabe {ipp['queue_id']} angelegt: Port {share['port']}.")
            else:
                if existing_queue.get("printer_id") != public["id"]:
                    raise RuntimeError(
                        f"IPP-Freigabe {ipp['queue_id']} zeigt bereits auf einen anderen Drucker; "
                        "bitte in Studio prüfen"
                    )
                print(f"IPP-Freigabe {ipp['queue_id']} vorhanden; sie bleibt erhalten.")
    write_stamp(stamp_path, digest)
    print("Installationsmanifest erfolgreich angewendet.")
    return True


def main() -> None:
    manifest = Path(os.getenv("PRINTHUB_SETUP_MANIFEST", "/config/printhub-install.json"))
    stamp = Path(os.getenv("PRINTHUB_SETUP_STAMP", "/data/setup/install-manifest.sha256"))
    if not manifest.exists():
        print("Kein Installationsmanifest vorhanden; config-apply übersprungen.")
        return
    try:
        admin_token = Path("/run/printhub-secrets/printhub-admin-token").read_text(encoding="utf-8").strip()
        zebra_token = Path("/run/printhub-secrets/zebratamer-token").read_text(encoding="utf-8").strip()
        apply(manifest, stamp, admin_token, zebra_token)
    except (OSError, ValueError, RuntimeError) as exc:
        print(f"config-apply fehlgeschlagen: {exc}", file=sys.stderr)
        raise SystemExit(1) from None


if __name__ == "__main__":
    main()
