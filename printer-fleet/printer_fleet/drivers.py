from __future__ import annotations

import base64
import json
from typing import Any, Mapping

from .domain import DevicePayload, PrintArtifact, UnsupportedDriver
from .ports import DeviceDriver


class ZplDriver:
    RASTER_MIME_TYPE = "application/vnd.printhub.raster-page+json"

    def encode(self, artifact: PrintArtifact, printer: Mapping[str, Any]) -> DevicePayload:
        copies_override: int | None = None
        if artifact.mime_type == "application/zpl":
            zpl = artifact.payload.decode("utf-8")
        elif artifact.mime_type == self.RASTER_MIME_TYPE:
            zpl, copies_override = self._encode_raster(artifact.payload)
        else:
            raise UnsupportedDriver(f"ZPL driver cannot encode {artifact.mime_type}")
        payload = self._apply_settings(zpl, printer, copies_override=copies_override)
        return DevicePayload(
            content_type="application/zpl",
            payload=payload.encode("utf-8"),
            description=artifact.description,
            idempotency_key=artifact.idempotency_key,
        )

    @staticmethod
    def _encode_raster(payload: bytes) -> tuple[str, int]:
        try:
            document = json.loads(payload)
            if not isinstance(document, dict):
                raise ValueError("artifact root must be an object")
            if document.get("version") != 1:
                raise ValueError("unsupported version")
            width = int(document["width_px"])
            height = int(document["height_px"])
            dpi = int(document["dpi"])
            copies = int(document["copies"])
            packed = base64.b64decode(document["black_bits_base64"], validate=True)
        except (KeyError, TypeError, ValueError, UnicodeDecodeError) as exc:
            raise UnsupportedDriver("Invalid prepared raster artifact") from exc
        if not 1 <= width <= 20000 or not 1 <= height <= 20000:
            raise UnsupportedDriver("Prepared raster dimensions are out of range")
        if not 1 <= dpi <= 2400 or not 1 <= copies <= 999:
            raise UnsupportedDriver("Prepared raster settings are out of range")
        bytes_per_row = (width + 7) // 8
        expected = bytes_per_row * height
        if len(packed) != expected:
            raise UnsupportedDriver("Prepared raster byte count does not match its dimensions")
        hexadecimal = packed.hex().upper()
        zpl = (
            "^XA\n"
            f"^PW{width}\n"
            f"^LL{height}\n"
            "^FO0,0\n"
            f"^GFA,{expected},{expected},{bytes_per_row},{hexadecimal}\n"
            "^FS\n"
            "^XZ\n"
        )
        return zpl, copies

    @classmethod
    def _apply_settings(
        cls,
        zpl: str,
        printer: Mapping[str, Any],
        *,
        copies_override: int | None,
    ) -> str:
        settings = cls._settings(printer, copies_override=copies_override)
        if not settings:
            return zpl
        block = "\n".join(settings) + "\n"
        if "^XA" not in zpl:
            return f"^XA{block}{zpl}\n^XZ\n"
        parts = zpl.split("^XA")
        return parts[0] + "".join(
            f"^XA{block}{part.lstrip(chr(10))}" for part in parts[1:]
        )

    @staticmethod
    def _settings(
        printer: Mapping[str, Any],
        *,
        copies_override: int | None,
    ) -> list[str]:
        zpl = printer.get("zpl") or {}
        defaults = printer.get("defaults") or {}
        settings: list[str] = []
        if "darkness" in zpl:
            settings.append(f"^MD{int(zpl['darkness'])}")
        if "print_speed" in zpl:
            settings.append(f"^PR{int(zpl['print_speed'])}")
        if zpl.get("print_mode"):
            modes = {
                "tear_off": "T",
                "peel_off": "P",
                "rewind": "R",
                "cutter": "C",
                "delayed_cut": "D",
                "applicator": "A",
            }
            try:
                settings.append(f"^MM{modes[str(zpl['print_mode']).strip().lower()]}")
            except KeyError as exc:
                raise UnsupportedDriver("Unsupported ZPL print mode") from exc
        copies = copies_override if copies_override is not None else defaults.get("copies")
        if copies is not None:
            copies_value = int(copies)
            if not 1 <= copies_value <= 999:
                raise UnsupportedDriver("ZPL copies must be between 1 and 999")
            settings.append(f"^PQ{copies_value}")
        if "rotation" in defaults:
            rotations = {0: "N", 90: "R", 180: "I", 270: "B"}
            try:
                settings.append(f"^FW{rotations[int(defaults['rotation'])]}")
            except (KeyError, TypeError, ValueError) as exc:
                raise UnsupportedDriver("Unsupported ZPL rotation") from exc
        return settings


class DriverRegistry:
    def __init__(self, drivers: Mapping[str, DeviceDriver] | None = None) -> None:
        self._drivers = dict(drivers or {"zpl": ZplDriver()})

    def get(self, name: str) -> DeviceDriver:
        try:
            return self._drivers[name]
        except KeyError:
            raise UnsupportedDriver(f"Unsupported printer driver: {name}") from None
