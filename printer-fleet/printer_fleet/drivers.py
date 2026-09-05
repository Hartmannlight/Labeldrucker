from __future__ import annotations

from typing import Any, Mapping

from .domain import DevicePayload, PrintArtifact, UnsupportedDriver
from .ports import DeviceDriver


class ZplDriver:
    def encode(self, artifact: PrintArtifact, _printer: Mapping[str, Any]) -> DevicePayload:
        if artifact.mime_type != "application/zpl":
            raise UnsupportedDriver(f"ZPL driver cannot encode {artifact.mime_type}")
        return DevicePayload(
            content_type="application/zpl",
            payload=artifact.payload,
            description=artifact.description,
            idempotency_key=artifact.idempotency_key,
        )


class DriverRegistry:
    def __init__(self, drivers: Mapping[str, DeviceDriver] | None = None) -> None:
        self._drivers = dict(drivers or {"zpl": ZplDriver()})

    def get(self, name: str) -> DeviceDriver:
        try:
            return self._drivers[name]
        except KeyError:
            raise UnsupportedDriver(f"Unsupported printer driver: {name}") from None
