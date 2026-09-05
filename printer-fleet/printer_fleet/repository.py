from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime, timezone
import json
from pathlib import Path
import sqlite3
from typing import Any, Iterator, Mapping
import uuid

from .domain import DeliveryConflict, DeliveryState, RegistryConflict


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class FleetRepository:
    """SQLite adapter; callers depend on methods, not database tables."""

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)

    @contextmanager
    def _connection(self) -> Iterator[sqlite3.Connection]:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        connection = sqlite3.connect(self.path, timeout=10)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        try:
            yield connection
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    def initialize(self) -> None:
        with self._connection() as db:
            db.executescript(
                """
                CREATE TABLE IF NOT EXISTS printers (
                    id TEXT PRIMARY KEY,
                    revision INTEGER NOT NULL,
                    payload_json TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS deliveries (
                    id TEXT PRIMARY KEY,
                    idempotency_key TEXT NOT NULL UNIQUE,
                    request_hash TEXT NOT NULL,
                    printer_id TEXT NOT NULL REFERENCES printers(id),
                    printer_snapshot_json TEXT NOT NULL,
                    artifact_checksum TEXT NOT NULL,
                    artifact_mime_type TEXT NOT NULL,
                    state TEXT NOT NULL,
                    bytes_accepted INTEGER NOT NULL DEFAULT 0,
                    error TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS delivery_events (
                    sequence INTEGER PRIMARY KEY AUTOINCREMENT,
                    delivery_id TEXT NOT NULL REFERENCES deliveries(id),
                    state TEXT NOT NULL,
                    detail TEXT,
                    occurred_at TEXT NOT NULL
                );
                """
            )

    def list_printers(self) -> list[dict[str, Any]]:
        with self._connection() as db:
            rows = db.execute("SELECT payload_json, revision FROM printers ORDER BY id").fetchall()
        return [self._printer(row) for row in rows]

    def get_printer(self, printer_id: str) -> dict[str, Any]:
        with self._connection() as db:
            row = db.execute(
                "SELECT payload_json, revision FROM printers WHERE id = ?", (printer_id,)
            ).fetchone()
        if row is None:
            raise KeyError(printer_id)
        return self._printer(row)

    @staticmethod
    def _printer(row: sqlite3.Row) -> dict[str, Any]:
        printer = json.loads(row["payload_json"])
        printer["registry"] = {"revision": row["revision"]}
        return printer

    @staticmethod
    def _delivery(row: sqlite3.Row) -> dict[str, Any]:
        delivery = dict(row)
        delivery["printer_snapshot"] = json.loads(delivery.pop("printer_snapshot_json"))
        return delivery

    def put_printer(self, printer: Mapping[str, Any]) -> dict[str, Any]:
        printer_id = str(printer.get("id", "")).strip()
        if not printer_id:
            raise ValueError("Printer id is required")
        payload = dict(printer)
        payload.pop("registry", None)
        now = _now()
        with self._connection() as db:
            current = db.execute("SELECT revision FROM printers WHERE id = ?", (printer_id,)).fetchone()
            if current:
                raise RegistryConflict(f"Printer already exists: {printer_id}")
            revision = 1
            db.execute(
                """INSERT INTO printers(id, revision, payload_json, created_at, updated_at)
                   VALUES (?, ?, ?, ?, ?)""",
                (printer_id, revision, json.dumps(payload, sort_keys=True), now, now),
            )
        return self.get_printer(printer_id)

    def patch_printer(
        self,
        printer_id: str,
        settings: Mapping[str, Any],
        expected_revision: int,
    ) -> dict[str, Any]:
        current = self.get_printer(printer_id)
        revision = int((current.get("registry") or {})["revision"])
        if revision != expected_revision:
            raise RegistryConflict(
                f"Printer revision changed: expected {expected_revision}, current {revision}"
            )
        updated = dict(current)
        updated.pop("registry", None)
        for key, value in settings.items():
            if key in {"id", "registry"}:
                raise ValueError(f"Printer field cannot be patched: {key}")
            updated[key] = value
        # The update is guarded again in the write transaction to prevent a
        # read/modify/write race between concurrent API requests.
        now = _now()
        with self._connection() as db:
            result = db.execute(
                """UPDATE printers SET revision = revision + 1, payload_json = ?, updated_at = ?
                   WHERE id = ? AND revision = ?""",
                (json.dumps(updated, sort_keys=True), now, printer_id, expected_revision),
            )
            if result.rowcount != 1:
                raise RegistryConflict("Printer was modified concurrently")
        return self.get_printer(printer_id)

    def create_delivery(
        self,
        *,
        idempotency_key: str,
        request_hash: str,
        printer_id: str,
        printer_snapshot: Mapping[str, Any],
        artifact_checksum: str,
        artifact_mime_type: str,
    ) -> tuple[dict[str, Any], bool]:
        now = _now()
        with self._connection() as db:
            existing = db.execute(
                "SELECT * FROM deliveries WHERE idempotency_key = ?", (idempotency_key,)
            ).fetchone()
            if existing:
                if existing["request_hash"] != request_hash:
                    raise DeliveryConflict("Idempotency key was reused for another delivery")
                return self._delivery(existing), False
            delivery_id = str(uuid.uuid4())
            db.execute(
                """INSERT INTO deliveries(
                   id, idempotency_key, request_hash, printer_id, printer_snapshot_json, artifact_checksum,
                   artifact_mime_type, state, created_at, updated_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    delivery_id,
                    idempotency_key,
                    request_hash,
                    printer_id,
                    json.dumps(dict(printer_snapshot), sort_keys=True),
                    artifact_checksum,
                    artifact_mime_type,
                    DeliveryState.QUEUED.value,
                    now,
                    now,
                ),
            )
            db.execute(
                "INSERT INTO delivery_events(delivery_id, state, occurred_at) VALUES (?, ?, ?)",
                (delivery_id, DeliveryState.QUEUED.value, now),
            )
            row = db.execute("SELECT * FROM deliveries WHERE id = ?", (delivery_id,)).fetchone()
        return self._delivery(row), True

    def transition(
        self,
        delivery_id: str,
        state: DeliveryState,
        *,
        bytes_accepted: int = 0,
        detail: str | None = None,
    ) -> dict[str, Any]:
        now = _now()
        with self._connection() as db:
            db.execute(
                """UPDATE deliveries SET state = ?, bytes_accepted = ?, error = ?, updated_at = ?
                   WHERE id = ?""",
                (
                    state.value,
                    bytes_accepted,
                    detail if state is DeliveryState.FAILED else None,
                    now,
                    delivery_id,
                ),
            )
            db.execute(
                """INSERT INTO delivery_events(delivery_id, state, detail, occurred_at)
                   VALUES (?, ?, ?, ?)""",
                (delivery_id, state.value, detail, now),
            )
            row = db.execute("SELECT * FROM deliveries WHERE id = ?", (delivery_id,)).fetchone()
        if row is None:
            raise KeyError(delivery_id)
        return self._delivery(row)

    def get_delivery(self, delivery_id: str) -> dict[str, Any]:
        with self._connection() as db:
            row = db.execute("SELECT * FROM deliveries WHERE id = ?", (delivery_id,)).fetchone()
            if row is None:
                raise KeyError(delivery_id)
            events = db.execute(
                """SELECT sequence, state, detail, occurred_at FROM delivery_events
                   WHERE delivery_id = ? ORDER BY sequence""",
                (delivery_id,),
            ).fetchall()
        result = self._delivery(row)
        result["events"] = [dict(event) for event in events]
        return result
