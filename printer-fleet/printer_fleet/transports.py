from __future__ import annotations

import socket
from typing import Any, Mapping

from .domain import DevicePayload, TransportReceipt, UnsupportedTransport
from .ports import DeviceTransport
from .agent import PrintAgentTransport


class RawTcpTransport:
    """Send an opaque device payload to a printer or serial-to-TCP bridge."""

    def send(self, payload: DevicePayload, printer: Mapping[str, Any]) -> TransportReceipt:
        connection = printer.get("connection") or {}
        host = str(connection["host"])
        port = int(connection.get("port", 9100))
        timeout = float(connection.get("timeout_ms", 5000)) / 1000
        with socket.create_connection((host, port), timeout=timeout) as stream:
            stream.sendall(payload.payload)
        # RAW TCP has no end-to-end acknowledgement from the print engine.
        return TransportReceipt(bytes_accepted=len(payload.payload))


class TransportRegistry:
    def __init__(self, transports: Mapping[str, DeviceTransport] | None = None) -> None:
        raw = RawTcpTransport()
        agent = PrintAgentTransport()
        self._transports = dict(
            transports
            or {
                "raw_tcp": raw,
                "raw9100": raw,
                "serial_over_tcp": raw,
                "print_agent": agent,
                "zebra_tamer": agent,
            }
        )

    def get(self, protocol: str) -> DeviceTransport:
        try:
            return self._transports[protocol]
        except KeyError:
            raise UnsupportedTransport(f"Unsupported printer transport: {protocol}") from None
