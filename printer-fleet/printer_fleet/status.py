from __future__ import annotations

import socket
from typing import Any, Mapping

from .agent import PrintAgentClient


def _query_raw(printer: Mapping[str, Any], command: str) -> str:
    connection = printer.get("connection") or {}
    host = str(connection.get("host") or "").strip()
    port = int(connection.get("port", 9100))
    timeout = max(0.1, int(connection.get("timeout_ms", 3000)) / 1000)
    if not host:
        raise ValueError("Printer connection.host is required")
    chunks: list[bytes] = []
    with socket.create_connection((host, port), timeout=timeout) as stream:
        stream.settimeout(timeout)
        stream.sendall((command.strip() + "\n").encode("utf-8"))
        while True:
            try:
                chunk = stream.recv(4096)
            except socket.timeout:
                break
            if not chunk:
                break
            chunks.append(chunk)
    return b"".join(chunks).decode("utf-8", errors="replace").replace("\x02", "").replace("\x03", "").strip()


def _parse_identification(raw: str) -> dict[str, Any]:
    parts = [part.strip() for part in raw.split(",") if part.strip()]
    return {
        "model": parts[0] if len(parts) > 0 else None,
        "firmware": parts[1] if len(parts) > 1 else None,
        "dpmm": parts[2] if len(parts) > 2 else None,
        "memory": parts[3] if len(parts) > 3 else None,
    }


class PrinterStatusService:
    def __init__(self, agent_client: PrintAgentClient | None = None) -> None:
        self.agent_client = agent_client or PrintAgentClient()

    def read(self, printer: Mapping[str, Any]) -> dict[str, Any]:
        if not printer.get("enabled", True):
            raise ValueError("Printer is disabled")
        if not (printer.get("capabilities") or {}).get("supports_status", False):
            raise ValueError("Printer status is not supported")
        connection = printer.get("connection") or {}
        protocol = str(connection.get("protocol") or "")
        if protocol == "print_agent":
            snapshot = self.agent_client.snapshot(connection)
            summary = {
                "model": ((snapshot.get("identity") or {}).get("model") or {}).get("value"),
                "firmware": ((snapshot.get("identity") or {}).get("firmware") or {}).get("value"),
                "ready": ((snapshot.get("status") or {}).get("ready") or {}).get("value"),
                "media_out": ((snapshot.get("status") or {}).get("media_out") or {}).get("value"),
                "head_open": ((snapshot.get("status") or {}).get("head_open") or {}).get("value"),
                "job_state": (snapshot.get("jobs") or {}).get("last_job_state"),
            }
            return {
                "printer_id": printer["id"],
                "raw": {},
                "parsed": snapshot,
                "normalized": {"summary": summary, "agent_snapshot": snapshot},
            }
        if protocol not in {"raw_tcp", "serial_over_tcp"}:
            raise ValueError(f"Printer status is unsupported for transport: {protocol}")
        commands = {
            "host_status": "~HS",
            "host_diagnostic": "~HD",
            "host_identification": "~HI",
            "host_inventory": "~HQES",
        }
        raw = {name: _query_raw(printer, command) for name, command in commands.items()}
        identification = _parse_identification(raw["host_identification"])
        return {
            "printer_id": printer["id"],
            "raw": raw,
            "parsed": {
                "host_status": [line.split(",") for line in raw["host_status"].splitlines() if line],
                "host_identification": identification,
            },
            "normalized": {"summary": identification},
        }
