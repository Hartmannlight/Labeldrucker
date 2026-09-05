from __future__ import annotations

from pathlib import Path
import socket
import threading
import base64
import json
from datetime import datetime, timedelta, timezone

import pytest

from printer_fleet.domain import (
    DeliveryConflict,
    PrinterPaused,
    PrintArtifact,
    RegistryConflict,
    TransportReceipt,
    UnsupportedDriver,
)
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


class FailingTransport:
    def send(self, _payload, _printer):
        raise OSError("printer is temporarily unreachable")


class CoordinatedTransport:
    def __init__(self, parties: int) -> None:
        self.barrier = threading.Barrier(parties)
        self.printers: list[str] = []
        self.lock = threading.Lock()

    def send(self, payload, printer):
        with self.lock:
            self.printers.append(str(printer["id"]))
        self.barrier.wait(timeout=2)
        return TransportReceipt(bytes_accepted=len(payload.payload))


class OneBlockedPrinterTransport:
    def __init__(self) -> None:
        self.slow_started = threading.Event()
        self.release_slow = threading.Event()
        self.fast_completed = threading.Event()

    def send(self, payload, printer):
        if printer["id"] == "zebra-1":
            self.slow_started.set()
            if not self.release_slow.wait(timeout=2):
                raise TimeoutError("test did not release slow printer")
        else:
            self.fast_completed.set()
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


def queue_delivery(
    repository: FleetRepository,
    *,
    printer_id: str,
    key: str,
) -> dict:
    artifact = PrintArtifact("application/zpl", f"^XA^FD{key}^FS^XZ".encode())
    delivery, _created = repository.create_delivery(
        idempotency_key=key,
        request_hash=f"request-{key}",
        printer_id=printer_id,
        printer_snapshot={"id": printer_id, "driver": "zpl"},
        route_snapshot=repository.get_printer(printer_id),
        artifact_checksum=artifact.checksum,
        artifact_mime_type=artifact.mime_type,
        artifact_payload=artifact.payload,
        artifact_description=artifact.description,
        max_attempts=3,
    )
    return delivery


def test_list_deliveries_filters_by_exact_delivery_ids(repository):
    first = queue_delivery(repository, printer_id="zebra-1", key="batch/first")
    second = queue_delivery(repository, printer_id="zebra-1", key="batch/second")
    queue_delivery(repository, printer_id="zebra-1", key="batch/unrelated")

    selected = repository.list_deliveries(
        delivery_ids={first["id"], second["id"], "missing-delivery"}
    )

    assert {delivery["id"] for delivery in selected} == {first["id"], second["id"]}


def test_delivery_is_durable_idempotent_and_honest(repository):
    transport = RecordingTransport()
    service = DeliveryService(
        repository,
        transports=TransportRegistry({"raw_tcp": transport}),
    )
    artifact = PrintArtifact("application/zpl", b"^XA^XZ", "test")

    first = service.submit(
        printer_id="zebra-1",
        idempotency_key="job-1/attempt-1",
        artifact=artifact,
        declared_checksum=artifact.checksum,
    )
    second = service.submit(
        printer_id="zebra-1",
        idempotency_key="job-1/attempt-1",
        artifact=artifact,
        declared_checksum=artifact.checksum,
    )

    assert first["state"] == "queued"
    assert second["id"] == first["id"]
    assert service.process_due()[0]["state"] == "transport_accepted"
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
    service.submit(
        printer_id="zebra-1",
        idempotency_key="same-key",
        artifact=first,
        declared_checksum=first.checksum,
    )
    with pytest.raises(DeliveryConflict):
        service.submit(
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
        service.submit(
            printer_id="zebra-1",
            idempotency_key="bad-checksum",
            artifact=artifact,
            declared_checksum="sha256:wrong",
        )
    assert transport.payloads == []


def test_payload_survives_restart_and_retry_is_claimed_once(repository):
    current = [datetime(2026, 9, 5, tzinfo=timezone.utc)]
    artifact = PrintArtifact("application/zpl", b"^XA^FDdurable^FS^XZ")
    first_service = DeliveryService(
        repository,
        transports=TransportRegistry({"raw_tcp": FailingTransport()}),
        retry_delay_seconds=1,
        now=lambda: current[0],
    )

    queued = first_service.submit(
        printer_id="zebra-1",
        idempotency_key="durable/1",
        artifact=artifact,
        declared_checksum=artifact.checksum,
    )
    assert queued["state"] == "queued"
    scheduled = first_service.process_due()[0]
    assert scheduled["state"] == "retry_scheduled"
    assert scheduled["attempt_count"] == 1
    assert "artifact_payload" not in scheduled
    status_owner = repository.acquire_printer_operation("zebra-1", kind="status")
    assert status_owner is not None
    repository.release_printer_operation("zebra-1", status_owner)

    accepting = RecordingTransport()
    restarted = DeliveryService(
        repository,
        transports=TransportRegistry({"raw_tcp": accepting}),
        retry_delay_seconds=1,
        now=lambda: current[0],
    )
    assert restarted.process_due() == []
    current[0] += timedelta(seconds=2)
    completed = restarted.process_due()

    assert len(completed) == 1
    assert completed[0]["state"] == "transport_accepted"
    assert completed[0]["attempt_count"] == 2
    assert accepting.payloads == [artifact.payload]
    assert restarted.process_due() == []


def test_due_work_is_fifo_per_printer_and_parallel_across_printers(repository):
    repository.put_printer(
        {
            "id": "zebra-2",
            "driver": "zpl",
            "connection": {"protocol": "raw_tcp", "host": "printer-2", "port": 9100},
            "enabled": True,
        }
    )
    first = queue_delivery(repository, printer_id="zebra-1", key="zebra-1/first")
    second = queue_delivery(repository, printer_id="zebra-1", key="zebra-1/second")
    other = queue_delivery(repository, printer_id="zebra-2", key="zebra-2/first")

    due = repository.list_due_delivery_ids(
        now=datetime.now(timezone.utc).isoformat(),
        limit=20,
    )
    assert due == [first["id"], other["id"]]

    transport = CoordinatedTransport(parties=2)
    service = DeliveryService(
        repository,
        transports=TransportRegistry({"raw_tcp": transport}),
        max_parallel_printers=2,
    )
    completed = service.process_due()

    assert {item["state"] for item in completed} == {"transport_accepted"}
    assert set(transport.printers) == {"zebra-1", "zebra-2"}
    assert repository.get_delivery(second["id"])["state"] == "queued"


def test_slow_printer_does_not_block_another_printer_delivery(repository):
    repository.put_printer(
        {
            "id": "zebra-2",
            "driver": "zpl",
            "connection": {"protocol": "raw_tcp", "host": "printer-2", "port": 9100},
            "enabled": True,
        }
    )
    queue_delivery(repository, printer_id="zebra-1", key="slow/first")
    queue_delivery(repository, printer_id="zebra-2", key="fast/first")
    transport = OneBlockedPrinterTransport()
    service = DeliveryService(
        repository,
        transports=TransportRegistry({"raw_tcp": transport}),
        max_parallel_printers=2,
    )

    worker = threading.Thread(target=service.process_due)
    worker.start()
    assert transport.slow_started.wait(timeout=1)
    assert transport.fast_completed.wait(timeout=1)
    transport.release_slow.set()
    worker.join(timeout=2)

    assert not worker.is_alive()


def test_claim_rejects_overlap_and_out_of_order_work_for_one_printer(repository):
    first = queue_delivery(repository, printer_id="zebra-1", key="same/first")
    second = queue_delivery(repository, printer_id="zebra-1", key="same/second")
    now = datetime.now(timezone.utc).isoformat()

    assert repository.claim_delivery(second["id"], now=now) is None
    assert repository.claim_delivery(first["id"], now=now) is not None
    assert repository.claim_delivery(second["id"], now=now) is None


def test_external_printer_operation_defers_delivery(repository):
    delivery = queue_delivery(repository, printer_id="zebra-1", key="maintenance/queued")
    owner = repository.acquire_printer_operation("zebra-1", kind="status")
    assert owner is not None
    transport = RecordingTransport()
    service = DeliveryService(
        repository,
        transports=TransportRegistry({"raw_tcp": transport}),
    )

    deferred = service.process_due()

    assert deferred == [repository.get_delivery(delivery["id"])]
    assert deferred[0]["state"] == "queued"
    assert transport.payloads == []
    repository.release_printer_operation("zebra-1", "not-the-owner")
    assert repository.acquire_printer_operation("zebra-1", kind="other") is None
    repository.release_printer_operation("zebra-1", owner)
    assert service.process_due()[0]["state"] == "transport_accepted"


def test_paused_queue_rejects_new_work_and_resumes_existing_fifo_work(repository):
    queued = queue_delivery(repository, printer_id="zebra-1", key="paused/queued")
    repository.set_printer_paused("zebra-1", paused=True, reason="Media change")
    service = DeliveryService(
        repository,
        transports=TransportRegistry({"raw_tcp": RecordingTransport()}),
    )
    artifact = PrintArtifact("application/zpl", b"^XA^FDnew^FS^XZ")

    with pytest.raises(PrinterPaused, match="paused"):
        service.submit(
            printer_id="zebra-1",
            idempotency_key="paused/new",
            artifact=artifact,
            declared_checksum=artifact.checksum,
        )
    assert service.process_due() == []
    assert repository.get_delivery(queued["id"])["state"] == "queued"

    repository.set_printer_paused("zebra-1", paused=False)
    completed = service.process_due()
    assert completed[0]["id"] == queued["id"]
    assert completed[0]["state"] == "transport_accepted"


def test_paused_control_survives_repository_restart(repository):
    repository.set_printer_paused("zebra-1", paused=True, reason="Operator maintenance")

    restarted = FleetRepository(repository.path)
    restarted.initialize()

    assert restarted.get_printer("zebra-1")["control"] == {
        "paused": True,
        "reason": "Operator maintenance",
        "updated_at": repository.get_printer("zebra-1")["control"]["updated_at"],
    }


@pytest.mark.parametrize("workers", [0, 65])
def test_parallel_printer_limit_is_bounded(repository, workers):
    with pytest.raises(ValueError, match="between 1 and 64"):
        DeliveryService(repository, max_parallel_printers=workers)


def test_delivery_stops_after_configured_attempt_limit(repository):
    current = [datetime(2026, 9, 5, tzinfo=timezone.utc)]
    artifact = PrintArtifact("application/zpl", b"^XA^XZ")
    service = DeliveryService(
        repository,
        transports=TransportRegistry({"raw_tcp": FailingTransport()}),
        retry_delay_seconds=0,
        now=lambda: current[0],
    )
    queued = service.submit(
        printer_id="zebra-1",
        idempotency_key="limited/1",
        artifact=artifact,
        declared_checksum=artifact.checksum,
        max_attempts=2,
    )
    assert queued["state"] == "queued"
    first = service.process_due()[0]
    assert first["state"] == "retry_scheduled"

    final = service.process_due()[0]
    assert final["state"] == "failed"
    assert final["attempt_count"] == 2
    assert service.process_due() == []


def test_printer_import_is_atomic_on_conflict(repository):
    original = repository.export_printers()
    conflicting = dict(original["printers"][0])
    conflicting["name"] = "Overwrite"
    with pytest.raises(RegistryConflict):
        repository.import_printers(
            {
                "config_version": 1,
                "printers": [
                    {
                        "id": "new-printer",
                        "driver": "zpl",
                        "connection": {"protocol": "raw_tcp", "host": "new"},
                    },
                    conflicting,
                ],
            }
        )
    assert repository.export_printers() == original


def test_restart_marks_in_flight_delivery_unconfirmed_instead_of_retrying(repository):
    artifact = PrintArtifact("application/zpl", b"^XA^XZ")
    delivery, _created = repository.create_delivery(
        idempotency_key="crashed/1",
        request_hash="request-hash",
        printer_id="zebra-1",
        printer_snapshot={"id": "zebra-1", "driver": "zpl"},
        route_snapshot=repository.get_printer("zebra-1"),
        artifact_checksum=artifact.checksum,
        artifact_mime_type=artifact.mime_type,
        artifact_payload=artifact.payload,
        artifact_description=artifact.description,
        max_attempts=3,
    )
    claimed = repository.claim_delivery(delivery["id"], now=datetime.now(timezone.utc).isoformat())
    assert claimed["state"] == "connecting"

    assert repository.recover_interrupted_deliveries() == 1
    recovered = repository.get_delivery(delivery["id"])
    assert recovered["state"] == "unconfirmed"
    assert repository.list_due_delivery_ids(now=datetime.now(timezone.utc).isoformat()) == []


@pytest.mark.parametrize("protocol", ["raw_tcp", "serial_over_tcp"])
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


def test_zpl_driver_encodes_device_independent_raster_and_job_copies():
    artifact = PrintArtifact(
        "application/vnd.printhub.raster-page+json",
        json.dumps(
            {
                "version": 1,
                "width_px": 8,
                "height_px": 1,
                "dpi": 203,
                "copies": 2,
                "black_bits_base64": base64.b64encode(b"\xa5").decode("ascii"),
            }
        ).encode("ascii"),
    )

    payload = ZplDriver().encode(
        artifact,
        {"defaults": {"copies": 1, "rotation": 90}, "zpl": {"darkness": 8}},
    )

    assert payload.content_type == "application/zpl"
    assert payload.payload.decode("ascii") == (
        "^XA^MD8\n^PQ2\n^FWR\n"
        "^PW8\n^LL1\n^FO0,0\n^GFA,1,1,1,A5\n^FS\n^XZ\n"
    )


def test_zpl_driver_rejects_malformed_prepared_raster():
    artifact = PrintArtifact(
        "application/vnd.printhub.raster-page+json",
        b'{"version":1,"width_px":8,"height_px":2,"dpi":203,"copies":1,"black_bits_base64":"/w=="}',
    )

    with pytest.raises(UnsupportedDriver, match="byte count"):
        ZplDriver().encode(artifact, {})


def test_zpl_driver_rejects_non_object_prepared_raster():
    artifact = PrintArtifact(
        "application/vnd.printhub.raster-page+json",
        b"[]",
    )

    with pytest.raises(UnsupportedDriver, match="Invalid prepared raster artifact"):
        ZplDriver().encode(artifact, {})
