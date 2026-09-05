from __future__ import annotations

from printer_fleet.agent import PrintAgentTransport
from printer_fleet.domain import DeliveryState, DevicePayload, TransportReceipt
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
