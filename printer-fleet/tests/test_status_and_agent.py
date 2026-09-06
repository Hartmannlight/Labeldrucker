from __future__ import annotations

import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
import socket
import threading

from printer_fleet.agent import PrintAgentClient, PrintAgentTransport
from printer_fleet.domain import (
    DeliveryState,
    DevicePayload,
    PrintArtifact,
    TransportReceipt,
)
from printer_fleet.repository import FleetRepository
from printer_fleet.service import DeliveryService
from printer_fleet.status import PrinterStatusService


class FakeAgentClient:
    def __init__(self):
        self.submissions = []

    def submit(self, connection, payload, *, description):
        self.submissions.append((connection, payload, description))
        return TransportReceipt(
            bytes_accepted=len(payload.payload),
            state=DeliveryState.TRANSPORT_ACCEPTED,
            downstream_job_id="agent-job-1",
            downstream_state="queued",
        )

    def snapshot(self, connection):
        assert connection["agent_id"] == "edge-1"
        return {
            "identity": {"model": {"value": "ZD421"}},
            "status": {"ready": {"value": True}},
            "jobs": {"last_job_state": "completed"},
        }


class LostFirstResponseAgent(BaseHTTPRequestHandler):
    jobs: dict[str, dict[str, object]] = {}
    submissions = 0

    def _json(self, data: object) -> None:
        body = json.dumps({"data": data, "error": None}).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:  # noqa: N802
        if self.path == "/v1/agent":
            self._json({"agent_id": "edge-1"})
            return
        if self.path == "/v1/jobs/agent-job-1":
            job = dict(next(iter(type(self).jobs.values())))
            job["state"] = "transport_accepted"
            self._json(job)
            return
        self.send_error(404)

    def do_POST(self) -> None:  # noqa: N802
        if self.path != "/v1/printers/usb-zebra/jobs":
            self.send_error(404)
            return
        length = int(self.headers.get("Content-Length", "0"))
        payload = self.rfile.read(length)
        key = self.headers["X-Idempotency-Key"]
        type(self).submissions += 1
        job = type(self).jobs.setdefault(
            key,
            {"id": "agent-job-1", "state": "queued", "bytes": len(payload)},
        )
        if type(self).submissions == 1:
            self.connection.shutdown(socket.SHUT_RDWR)
            self.connection.close()
            return
        self._json(job)

    def log_message(self, _format: str, *_args: object) -> None:
        return


class ActiveAgent(BaseHTTPRequestHandler):
    terminal_state = "queued"

    def _json(self, data: object) -> None:
        body = json.dumps({"data": data, "error": None}).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:  # noqa: N802
        if self.path == "/v1/agent":
            self._json({"agent_id": "edge-1"})
            return
        if self.path == "/v1/jobs/agent-job-active":
            self._json(
                {
                    "id": "agent-job-active",
                    "state": type(self).terminal_state,
                    "bytes": 17,
                    "error": "device outcome could not be established"
                    if type(self).terminal_state == "outcome_unknown"
                    else None,
                }
            )
            return
        self.send_error(404)

    def do_POST(self) -> None:  # noqa: N802
        length = int(self.headers.get("Content-Length", "0"))
        self.rfile.read(length)
        self._json({"id": "agent-job-active", "state": "queued", "bytes": 17})

    def log_message(self, _format: str, *_args: object) -> None:
        return


def test_print_agent_transport_preserves_downstream_reference():
    client = FakeAgentClient()
    receipt = PrintAgentTransport(client).send(
        DevicePayload(
            "application/zpl",
            b"^XA^XZ",
            idempotency_key="fleet-delivery-1",
        ),
        {
            "connection": {
                "base_url": "http://edge:8080",
                "printer_id": "usb-zebra",
                "agent_id": "edge-1",
            }
        },
    )
    assert receipt.downstream_job_id == "agent-job-1"
    assert receipt.state is DeliveryState.TRANSPORT_ACCEPTED
    assert client.submissions[0][2] == "PrinterFleet delivery"
    assert client.submissions[0][1].idempotency_key == "fleet-delivery-1"


def test_lost_agent_response_retries_without_creating_a_second_agent_job(
    tmp_path: Path,
):
    LostFirstResponseAgent.jobs = {}
    LostFirstResponseAgent.submissions = 0
    server = ThreadingHTTPServer(("127.0.0.1", 0), LostFirstResponseAgent)
    server_thread = threading.Thread(target=server.serve_forever, daemon=True)
    server_thread.start()
    repository = FleetRepository(tmp_path / "fleet.sqlite3")
    repository.initialize()
    repository.put_printer(
        {
            "id": "agent-zebra",
            "driver": "zpl",
            "connection": {
                "protocol": "print_agent",
                "base_url": f"http://127.0.0.1:{server.server_port}",
                "printer_id": "usb-zebra",
                "agent_id": "edge-1",
                "timeout_ms": 1000,
            },
            "enabled": True,
        }
    )
    service = DeliveryService(repository, retry_delay_seconds=0)
    artifact = PrintArtifact("application/zpl", b"^XA^FDonce^FS^XZ")
    try:
        queued = service.submit(
            printer_id="agent-zebra",
            idempotency_key="fleet-agent/once",
            artifact=artifact,
            declared_checksum=artifact.checksum,
        )
        first = service.process_due()[0]
        second = service.process_due()[0]
    finally:
        server.shutdown()
        server.server_close()
        server_thread.join(timeout=2)

    assert queued["state"] == "queued"
    assert first["state"] == "retry_scheduled"
    assert second["state"] == "transport_accepted"
    assert second["downstream_job_id"] == "agent-job-1"
    assert LostFirstResponseAgent.submissions == 2
    assert list(LostFirstResponseAgent.jobs) == ["fleet-agent/once"]


def test_print_agent_never_promotes_an_active_job_to_transport_accepted():
    ActiveAgent.terminal_state = "queued"
    server = ThreadingHTTPServer(("127.0.0.1", 0), ActiveAgent)
    server_thread = threading.Thread(target=server.serve_forever, daemon=True)
    server_thread.start()
    try:
        receipt = PrintAgentClient(poll_interval_seconds=0.01).submit(
            {
                "base_url": f"http://127.0.0.1:{server.server_port}",
                "printer_id": "usb-zebra",
                "agent_id": "edge-1",
                "timeout_ms": 100,
            },
            DevicePayload("application/zpl", b"^XA^FDonce^FS^XZ"),
            description="honest active state",
        )
    finally:
        server.shutdown()
        server.server_close()
        server_thread.join(timeout=2)

    assert receipt.state is DeliveryState.UNCONFIRMED
    assert receipt.bytes_accepted == 0
    assert receipt.downstream_job_id == "agent-job-active"
    assert receipt.downstream_state == "queued"
    assert receipt.detail == "PrintAgent job remained active beyond the delivery timeout"


def test_print_agent_maps_explicit_unknown_outcome_without_retrying():
    ActiveAgent.terminal_state = "outcome_unknown"
    server = ThreadingHTTPServer(("127.0.0.1", 0), ActiveAgent)
    server_thread = threading.Thread(target=server.serve_forever, daemon=True)
    server_thread.start()
    try:
        receipt = PrintAgentClient(poll_interval_seconds=0.01).submit(
            {
                "base_url": f"http://127.0.0.1:{server.server_port}",
                "printer_id": "usb-zebra",
                "agent_id": "edge-1",
                "timeout_ms": 1000,
            },
            DevicePayload("application/zpl", b"^XA^FDonce^FS^XZ"),
            description="honest uncertain state",
        )
    finally:
        server.shutdown()
        server.server_close()
        server_thread.join(timeout=2)

    assert receipt.state is DeliveryState.UNCONFIRMED
    assert receipt.downstream_state == "outcome_unknown"
    assert receipt.detail == "device outcome could not be established"


def test_agent_status_is_normalized_without_exposing_connection():
    result = PrinterStatusService(FakeAgentClient()).read(
        {
            "id": "zebra-1",
            "enabled": True,
            "capabilities": {"supports_status": True},
            "connection": {
                "protocol": "print_agent",
                "agent_id": "edge-1",
            },
        }
    )
    assert result["normalized"]["summary"]["model"] == "ZD421"
    assert result["normalized"]["summary"]["ready"] is True
    assert "connection" not in result


def test_raw_status_queries_are_normalized(monkeypatch):
    responses = {
        "~HS": "ready,0",
        "~HD": "HEAD=closed",
        "~HI": "ZD421,V1,8,512KB",
        "~HQES": "ERRORS: none",
    }
    monkeypatch.setattr(
        "printer_fleet.status._query_raw",
        lambda _printer, command: responses[command],
    )
    result = PrinterStatusService().read(
        {
            "id": "zebra-raw",
            "enabled": True,
            "capabilities": {"supports_status": True},
            "connection": {"protocol": "raw_tcp", "host": "printer"},
        }
    )
    assert result["normalized"]["summary"]["model"] == "ZD421"
    assert result["raw"]["host_status"] == "ready,0"
