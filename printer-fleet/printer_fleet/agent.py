from __future__ import annotations

import json
from typing import Any, Mapping
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse
from urllib.request import Request, urlopen

from .domain import DeliveryState, DevicePayload, TransportReceipt


class PrintAgentClient:
    """Vendor-neutral client compatible with current ZebraTamer v1 endpoints."""

    @staticmethod
    def _base_url(connection: Mapping[str, Any]) -> str:
        value = str(connection.get("base_url") or "").strip().rstrip("/")
        parsed = urlparse(value)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            raise ValueError("PrintAgent connection.base_url must be an HTTP(S) URL")
        return value

    @staticmethod
    def _printer_id(connection: Mapping[str, Any]) -> str:
        value = str(connection.get("printer_id") or "").strip()
        if not value:
            raise ValueError("PrintAgent connection.printer_id is required")
        return value

    @staticmethod
    def _timeout(connection: Mapping[str, Any]) -> float:
        return max(0.1, int(connection.get("timeout_ms", 10_000)) / 1000)

    def _request(
        self,
        connection: Mapping[str, Any],
        path: str,
        *,
        method: str = "GET",
        data: bytes | None = None,
        headers: Mapping[str, str] | None = None,
    ) -> Any:
        request = Request(
            f"{self._base_url(connection)}{path}",
            method=method,
            data=data,
            headers=dict(headers or {"Accept": "application/json"}),
        )
        try:
            with urlopen(request, timeout=self._timeout(connection)) as response:
                payload = json.loads(response.read().decode("utf-8"))
        except (HTTPError, URLError, TimeoutError, json.JSONDecodeError) as exc:
            raise RuntimeError(f"PrintAgent request failed: {exc}") from exc
        if not isinstance(payload, dict):
            raise RuntimeError("PrintAgent returned an invalid response envelope")
        error = payload.get("error")
        if error:
            message = error.get("message") if isinstance(error, dict) else str(error)
            raise RuntimeError(message or "PrintAgent request failed")
        return payload.get("data")

    def verify_identity(self, connection: Mapping[str, Any]) -> None:
        expected = connection.get("agent_id")
        if not expected:
            return
        info = self._request(connection, "/v1/agent")
        if not isinstance(info, dict) or info.get("agent_id") != expected:
            raise RuntimeError("PrintAgent identity mismatch")

    def inspect(self, base_url: str) -> dict[str, Any]:
        connection = {"base_url": base_url, "timeout_ms": 2000}
        info = self._request(connection, "/v1/agent")
        printers = self._request(connection, "/v1/printers")
        if not isinstance(info, dict) or not isinstance(printers, list):
            raise RuntimeError("PrintAgent returned invalid discovery data")
        agent_id = str(info.get("agent_id") or "").strip()
        if not agent_id:
            raise RuntimeError("PrintAgent must expose a stable agent_id")
        devices = [device for device in printers if isinstance(device, dict) and device.get("id")]
        if len({str(device["id"]) for device in devices}) != len(devices):
            raise RuntimeError("PrintAgent returned duplicate printer ids")
        return {
            "id": agent_id,
            "base_url": self._base_url(connection),
            "available": True,
            "info": info,
            "printers": devices,
        }

    def configuration(
        self, base_url: str, agent_id: str, printer_id: str
    ) -> dict[str, Any]:
        connection = {
            "base_url": base_url,
            "agent_id": agent_id,
            "printer_id": printer_id,
            "timeout_ms": 3000,
        }
        self.verify_identity(connection)
        data = self._request(connection, f"/v1/printers/{printer_id}/configuration")
        if not isinstance(data, dict):
            raise RuntimeError("PrintAgent returned invalid configuration data")
        return data

    def submit(
        self,
        connection: Mapping[str, Any],
        payload: DevicePayload,
        *,
        description: str,
    ) -> TransportReceipt:
        self.verify_identity(connection)
        data = self._request(
            connection,
            f"/v1/printers/{self._printer_id(connection)}/jobs",
            method="POST",
            data=payload.payload,
            headers={
                "Content-Type": payload.content_type,
                "X-Print-Origin": "printer-fleet",
                "X-Print-Description": payload.description or description,
                **(
                    {"X-Idempotency-Key": payload.idempotency_key}
                    if payload.idempotency_key
                    else {}
                ),
            },
        )
        if not isinstance(data, dict) or not data.get("id"):
            raise RuntimeError("PrintAgent did not return a job id")
        downstream_state = str(data.get("state") or "queued")
        state = (
            DeliveryState.CONFIRMED
            if downstream_state.lower() in {"completed", "confirmed", "printed"}
            else DeliveryState.TRANSPORT_ACCEPTED
        )
        return TransportReceipt(
            bytes_accepted=int(data.get("bytes") or len(payload.payload)),
            state=state,
            downstream_job_id=str(data["id"]),
            downstream_state=downstream_state,
        )

    def snapshot(self, connection: Mapping[str, Any]) -> dict[str, Any]:
        self.verify_identity(connection)
        data = self._request(
            connection,
            f"/v1/printers/{self._printer_id(connection)}/snapshot",
        )
        if not isinstance(data, dict):
            raise RuntimeError("PrintAgent returned an invalid printer snapshot")
        return data


class PrintAgentTransport:
    def __init__(self, client: PrintAgentClient | None = None) -> None:
        self.client = client or PrintAgentClient()

    def send(self, payload: DevicePayload, printer: Mapping[str, Any]) -> TransportReceipt:
        return self.client.submit(
            printer.get("connection") or {},
            payload,
            description="PrinterFleet delivery",
        )
