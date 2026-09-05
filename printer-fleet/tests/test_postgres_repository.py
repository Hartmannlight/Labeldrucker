from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
import os
from pathlib import Path

import psycopg
import pytest

from printer_fleet.domain import DeliveryConflict, DeliveryState, PrintArtifact
from printer_fleet.migrate import TABLES, migrate_sqlite_to_postgres
from printer_fleet.postgres_repository import PostgresFleetRepository
from printer_fleet.repository import CURRENT_SCHEMA_VERSION, FleetRepository


POSTGRES_URL = os.getenv("PRINTER_FLEET_TEST_POSTGRES_URL")
pytestmark = pytest.mark.skipif(not POSTGRES_URL, reason="PostgreSQL test URL is not configured")


def _empty_postgres() -> PostgresFleetRepository:
    assert POSTGRES_URL
    repository = PostgresFleetRepository(POSTGRES_URL)
    repository.initialize()
    tables = ", ".join(table for table, _columns, _order in reversed(TABLES))
    with psycopg.connect(POSTGRES_URL) as db:
        db.execute(f"TRUNCATE TABLE {tables} RESTART IDENTITY CASCADE")
    return repository


def _printer() -> dict:
    return {
        "id": "zebra-1",
        "site_id": "warehouse",
        "driver": "zpl",
        "connection": {"protocol": "raw_tcp", "host": "printer", "port": 9100},
        "enabled": True,
    }


def _queue(repository, key: str, accepted_at: str | None = None):
    artifact = PrintArtifact("application/zpl", f"^XA^FD{key}^FS^XZ".encode())
    return repository.create_delivery(
        idempotency_key=key,
        request_hash=f"request-{key}",
        printer_id="zebra-1",
        printer_snapshot={"id": "zebra-1", "driver": "zpl"},
        route_snapshot=repository.get_printer("zebra-1"),
        artifact_checksum=artifact.checksum,
        artifact_mime_type=artifact.mime_type,
        artifact_payload=artifact.payload,
        artifact_description="contract test",
        max_attempts=3,
        accepted_at=accepted_at,
    )


def test_postgres_preserves_registry_queue_lease_and_event_contracts():
    repository = _empty_postgres()
    repository.initialize()
    assert repository.put_printer(_printer())["registry"]["revision"] == 1
    assert repository.patch_printer("zebra-1", {"name": "Packing"}, 1)["registry"]["revision"] == 2
    repository.set_printer_paused("zebra-1", paused=True, reason="media")
    assert repository.get_printer("zebra-1")["control"]["paused"] is True
    repository.set_printer_paused("zebra-1", paused=False)

    first, created = _queue(repository, "same-key", "2026-09-05T10:00:00+00:00")
    duplicate, duplicate_created = _queue(repository, "same-key", "2026-09-05T10:00:00+00:00")
    second, _ = _queue(repository, "second-key", "2026-09-05T10:00:01+00:00")
    assert created is True and duplicate_created is False and duplicate["id"] == first["id"]
    with pytest.raises(DeliveryConflict):
        repository.create_delivery(
            idempotency_key="same-key", request_hash="different", printer_id="zebra-1",
            printer_snapshot={"id": "zebra-1"}, route_snapshot=repository.get_printer("zebra-1"),
            artifact_checksum="sha256:different", artifact_mime_type="application/zpl",
            artifact_payload=b"different", artifact_description="conflict", max_attempts=3,
        )

    now = "2026-09-05T12:00:00+00:00"
    assert repository.claim_delivery(second["id"], now=now) is None
    claimed = repository.claim_delivery(first["id"], now=now)
    assert claimed and claimed["_artifact_payload"].startswith(b"^XA")
    repository.transition(first["id"], DeliveryState.TRANSMITTING)
    repository.transition(first["id"], DeliveryState.TRANSPORT_ACCEPTED, bytes_accepted=10)
    repository.release_printer_operation("zebra-1", claimed["_operation_owner"])
    assert [event["state"] for event in repository.get_delivery(first["id"])["events"]] == [
        "queued", "connecting", "transmitting", "transport_accepted"
    ]
    assert repository.claim_delivery(second["id"], now=now) is not None


def test_postgres_idempotency_is_atomic_under_concurrency():
    repository = _empty_postgres()
    repository.put_printer(_printer())
    with ThreadPoolExecutor(max_workers=8) as pool:
        results = list(pool.map(lambda _index: _queue(repository, "parallel-key"), range(8)))
    assert len({delivery["id"] for delivery, _created in results}) == 1
    assert sum(created for _delivery, created in results) == 1


def test_offline_sqlite_cutover_copies_and_verifies_all_fleet_state(tmp_path: Path):
    target = _empty_postgres()
    source_path = tmp_path / "fleet.sqlite3"
    source = FleetRepository(source_path)
    source.initialize()
    source.put_printer(_printer())
    source.set_printer_paused("zebra-1", paused=True, reason="cutover")
    source.record_printer_observation(
        "zebra-1", media={"width_mm": 50}, alignment={"x": 1},
        capabilities={"color": False}, source="agent-1",
    )
    source.record_agent(
        {"id": "agent-1", "base_url": "http://agent:9191", "printers": [{"id": "usb-1"}]}
    )
    source.append_audit_record(
        correlation_id="migration-test", actor="admin", method="POST",
        path="/v1/printers", status_code=201,
    )
    delivery, _ = _queue(source, "migrate-key")
    claimed = source.claim_delivery(delivery["id"], now=datetime.now(timezone.utc).isoformat())
    source.transition(delivery["id"], DeliveryState.TRANSMITTING)
    source.release_printer_operation("zebra-1", claimed["_operation_owner"])

    report = migrate_sqlite_to_postgres(source_path, POSTGRES_URL)

    assert report["schema_version"] == CURRENT_SCHEMA_VERSION
    assert report["tables"]["deliveries"]["rows"] == 1
    assert report["tables"]["delivery_events"]["rows"] == 3
    assert target.get_printer("zebra-1")["control"]["reason"] == "cutover"
    assert target.get_agent("agent-1")["printers"][0]["id"] == "usb-1"
    assert target.get_delivery(delivery["id"])["state"] == "transmitting"
    with pytest.raises(RuntimeError, match="target must be empty"):
        migrate_sqlite_to_postgres(source_path, POSTGRES_URL)
