from __future__ import annotations

from pathlib import Path
import socket
import threading

import pytest

from printer_fleet.domain import DeliveryConflict, PrintArtifact, TransportReceipt
from printer_fleet.drivers import ZplDriver
from printer_fleet.ports import DeviceTransport
from printer_fleet.repository import FleetRepository
from printer_fleet.service import DeliveryService
from printer_fleet.transports import TransportRegistry


class RecordingTransport(DeviceTransport):
    def __init__(self) -> None:
        self.payloads: list[bytes] = []

    def send(self, payload, _printer):
        self.payloads.append(payload.payload)
        return TransportReceipt(bytes_accepted=len(payload.payload))


@pytest.fixture
def repository(tmp_path: Path) -> FleetRepository:
    repository = FleetRepository(tmp_path / "fleet.sqlite3")
    repository.initialize()
    repository.put_printer(
        {
            "id": "zebra-1",
            "driver": "zpl",
            "connection": {"protocol": "raw_tcp", "host": "printer", "port": 9100},
            "enabled": True,
        }
    )
    return repository


def test_delivery_is_durable_idempotent_and_honest(repository):
    transport = RecordingTransport()
    service = DeliveryService(
        repository,
        transports=TransportRegistry({"raw_tcp": transport}),
    )
    artifact = PrintArtifact("application/zpl", b"^XA^XZ", "test")

    first = service.deliver(
        printer_id="zebra-1",
        idempotency_key="job-1/attempt-1",
        artifact=artifact,
        declared_checksum=artifact.checksum,
    )
    second = service.deliver(
        printer_id="zebra-1",
        idempotency_key="job-1/attempt-1",
        artifact=artifact,
        declared_checksum=artifact.checksum,
    )

    assert first["state"] == "transport_accepted"
    assert second["id"] == first["id"]
    assert transport.payloads == [b"^XA^XZ"]
    stored = repository.get_delivery(first["id"])
    assert stored["printer_snapshot"]["driver"] == "zpl"
    assert "connection" not in stored["printer_snapshot"]
    assert [event["state"] for event in stored["events"]] == [
        "queued",
        "connecting",
        "transmitting",
        "transport_accepted",
    ]


def test_idempotency_key_cannot_be_reused_for_another_payload(repository):
    transport = RecordingTransport()
    service = DeliveryService(repository, transports=TransportRegistry({"raw_tcp": transport}))
    first = PrintArtifact("application/zpl", b"first")
    second = PrintArtifact("application/zpl", b"second")
    service.deliver(
        printer_id="zebra-1",
        idempotency_key="same-key",
        artifact=first,
        declared_checksum=first.checksum,
    )
    with pytest.raises(DeliveryConflict):
        service.deliver(
            printer_id="zebra-1",
            idempotency_key="same-key",
            artifact=second,
            declared_checksum=second.checksum,
        )


def test_checksum_mismatch_is_rejected_before_delivery(repository):
    transport = RecordingTransport()
    service = DeliveryService(repository, transports=TransportRegistry({"raw_tcp": transport}))
    artifact = PrintArtifact("application/zpl", b"payload")
    with pytest.raises(ValueError, match="checksum"):
        service.deliver(
            printer_id="zebra-1",
            idempotency_key="bad-checksum",
            artifact=artifact,
            declared_checksum="sha256:wrong",
        )
    assert transport.payloads == []


@pytest.mark.parametrize("protocol", ["raw_tcp", "raw9100", "serial_over_tcp"])
def test_tcp_transports_send_the_exact_device_payload(protocol):
    received = bytearray()
    listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    listener.bind(("127.0.0.1", 0))
    listener.listen(1)
    port = listener.getsockname()[1]

    def receive_once():
        connection, _address = listener.accept()
        with connection:
            while chunk := connection.recv(1024):
                received.extend(chunk)
        listener.close()

    worker = threading.Thread(target=receive_once)
    worker.start()
    artifact = PrintArtifact("application/zpl", b"^XA^FO1,1^FDfleet^FS^XZ")
    payload = ZplDriver().encode(artifact, {})
    receipt = TransportRegistry().get(protocol).send(
        payload,
        {
            "connection": {
                "protocol": protocol,
                "host": "127.0.0.1",
                "port": port,
                "timeout_ms": 1000,
            }
        },
    )
    worker.join(timeout=2)

    assert not worker.is_alive()
    assert bytes(received) == artifact.payload
    assert receipt.state.value == "transport_accepted"
