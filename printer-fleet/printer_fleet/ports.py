from __future__ import annotations

from typing import Any, Mapping, Protocol

from .domain import DevicePayload, PrintArtifact, TransportReceipt


class DeviceDriver(Protocol):
    def encode(self, artifact: PrintArtifact, printer: Mapping[str, Any]) -> DevicePayload: ...


class DeviceTransport(Protocol):
    def send(self, payload: DevicePayload, printer: Mapping[str, Any]) -> TransportReceipt: ...
