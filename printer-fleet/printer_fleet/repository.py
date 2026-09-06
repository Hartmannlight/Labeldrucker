from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import sqlite3
from typing import Any, Collection, Iterator, Mapping
import uuid

from .configuration import normalize_printer
from .domain import DeliveryConflict, DeliveryState, RegistryConflict


CURRENT_SCHEMA_VERSION = 3


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
            schema_version = int(db.execute("PRAGMA user_version").fetchone()[0])
            if schema_version > CURRENT_SCHEMA_VERSION:
                raise RuntimeError(
                    f"Fleet database schema {schema_version} is newer than supported "
                    f"version {CURRENT_SCHEMA_VERSION}"
                )
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
                    route_snapshot_json TEXT,
                    artifact_checksum TEXT NOT NULL,
                    artifact_mime_type TEXT NOT NULL,
                    artifact_payload BLOB,
                    artifact_description TEXT NOT NULL DEFAULT 'PrintHub job',
                    state TEXT NOT NULL,
                    attempt_count INTEGER NOT NULL DEFAULT 0,
                    max_attempts INTEGER NOT NULL DEFAULT 3,
                    next_attempt_at TEXT,
                    downstream_job_id TEXT,
                    downstream_state TEXT,
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
                CREATE TABLE IF NOT EXISTS agents (
                    id TEXT PRIMARY KEY,
                    base_url TEXT NOT NULL UNIQUE,
                    available INTEGER NOT NULL,
                    payload_json TEXT NOT NULL,
                    last_seen_at TEXT,
                    last_error TEXT,
                    updated_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS agent_devices (
                    agent_id TEXT NOT NULL REFERENCES agents(id) ON DELETE CASCADE,
                    device_id TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    observed_at TEXT NOT NULL,
                    PRIMARY KEY(agent_id, device_id)
                );
                CREATE TABLE IF NOT EXISTS printer_observations (
                    printer_id TEXT PRIMARY KEY REFERENCES printers(id) ON DELETE CASCADE,
                    media_json TEXT,
                    alignment_json TEXT,
                    capabilities_json TEXT,
                    source TEXT NOT NULL,
                    observed_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS printer_operation_leases (
                    printer_id TEXT PRIMARY KEY REFERENCES printers(id) ON DELETE CASCADE,
                    owner TEXT NOT NULL,
                    kind TEXT NOT NULL,
                    acquired_at TEXT NOT NULL,
                    expires_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS printer_controls (
                    printer_id TEXT PRIMARY KEY REFERENCES printers(id) ON DELETE CASCADE,
                    paused INTEGER NOT NULL DEFAULT 0,
                    reason TEXT,
                    updated_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS audit_records (
                    id TEXT PRIMARY KEY,
                    correlation_id TEXT NOT NULL,
                    actor TEXT NOT NULL,
                    method TEXT NOT NULL,
                    path TEXT NOT NULL,
                    status_code INTEGER NOT NULL,
                    occurred_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS audit_records_time_idx
                    ON audit_records(occurred_at, id);
                """
            )
            self._ensure_delivery_columns(db)
            if schema_version < 3:
                self._canonicalize_protocol_aliases(db)
            db.execute(f"PRAGMA user_version = {CURRENT_SCHEMA_VERSION}")

    @staticmethod
    def _canonicalize_protocol_aliases(db) -> None:
        aliases = {"raw9100": "raw_tcp", "zebra_tamer": "print_agent", "driver_agent": "print_agent"}

        def migrate_payload(encoded: str | None) -> str | None:
            if encoded is None:
                return None
            payload = json.loads(encoded)
            connection = payload.get("connection") or {}
            protocol = str(connection.get("protocol") or "")
            canonical = aliases.get(protocol)
            if canonical:
                connection["protocol"] = canonical
                payload["connection"] = connection
            return json.dumps(payload, sort_keys=True)

        for row in db.execute("SELECT id, payload_json FROM printers").fetchall():
            migrated = migrate_payload(row["payload_json"])
            if migrated != row["payload_json"]:
                db.execute(
                    "UPDATE printers SET payload_json = ? WHERE id = ?",
                    (migrated, row["id"]),
                )
        for row in db.execute(
            "SELECT id, route_snapshot_json FROM deliveries WHERE route_snapshot_json IS NOT NULL"
        ).fetchall():
            migrated = migrate_payload(row["route_snapshot_json"])
            if migrated != row["route_snapshot_json"]:
                db.execute(
                    "UPDATE deliveries SET route_snapshot_json = ? WHERE id = ?",
                    (migrated, row["id"]),
                )

    def append_audit_record(
        self,
        *,
        correlation_id: str,
        actor: str,
        method: str,
        path: str,
        status_code: int,
    ) -> None:
        with self._connection() as db:
            db.execute(
                """INSERT INTO audit_records(
                       id, correlation_id, actor, method, path, status_code, occurred_at
                   ) VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (
                    str(uuid.uuid4()),
                    correlation_id,
                    actor,
                    method,
                    path,
                    status_code,
                    _now(),
                ),
            )

    def list_audit_records(self, *, limit: int = 100) -> list[dict[str, Any]]:
        with self._connection() as db:
            rows = db.execute(
                """SELECT id, correlation_id, actor, method, path, status_code, occurred_at
                   FROM audit_records ORDER BY occurred_at DESC, id DESC LIMIT ?""",
                (limit,),
            ).fetchall()
        return [dict(row) for row in rows]

    def metrics_snapshot(self) -> dict[str, Any]:
        with self._connection() as db:
            printer_count = int(
                db.execute("SELECT COUNT(*) AS count FROM printers").fetchone()["count"]
            )
            rows = db.execute(
                "SELECT state, COUNT(*) AS count FROM deliveries GROUP BY state"
            ).fetchall()
        return {
            "printers": printer_count,
            "deliveries": {str(row["state"]): int(row["count"]) for row in rows},
        }

    @staticmethod
    def _ensure_delivery_columns(db: sqlite3.Connection) -> None:
        """Forward-only compatibility for databases created by the first slice."""
        existing = {
            row["name"] for row in db.execute("PRAGMA table_info(deliveries)").fetchall()
        }
        additions = {
            "route_snapshot_json": "TEXT",
            "artifact_payload": "BLOB",
            "artifact_description": "TEXT NOT NULL DEFAULT 'PrintHub job'",
            "attempt_count": "INTEGER NOT NULL DEFAULT 0",
            "max_attempts": "INTEGER NOT NULL DEFAULT 3",
            "next_attempt_at": "TEXT",
            "downstream_job_id": "TEXT",
            "downstream_state": "TEXT",
        }
        for name, declaration in additions.items():
            if name not in existing:
                db.execute(f"ALTER TABLE deliveries ADD COLUMN {name} {declaration}")

    def list_printers(self) -> list[dict[str, Any]]:
        with self._connection() as db:
            ids = [row["id"] for row in db.execute("SELECT id FROM printers ORDER BY id").fetchall()]
        return [self.get_printer(str(printer_id)) for printer_id in ids]

    @staticmethod
    def _try_acquire_operation(
        db: sqlite3.Connection,
        *,
        printer_id: str,
        kind: str,
        now: str,
        expires_at: str,
    ) -> str | None:
        db.execute(
            "DELETE FROM printer_operation_leases WHERE printer_id = ? AND expires_at <= ?",
            (printer_id, now),
        )
        owner = str(uuid.uuid4())
        result = db.execute(
            """INSERT OR IGNORE INTO printer_operation_leases(
                   printer_id, owner, kind, acquired_at, expires_at
               ) VALUES (?, ?, ?, ?, ?)""",
            (printer_id, owner, kind, now, expires_at),
        )
        return owner if result.rowcount == 1 else None

    def acquire_printer_operation(
        self,
        printer_id: str,
        *,
        kind: str,
        lease_seconds: float = 300,
    ) -> str | None:
        if lease_seconds <= 0 or lease_seconds > 900:
            raise ValueError("lease_seconds must be greater than 0 and at most 900")
        now_value = datetime.now(timezone.utc)
        now = now_value.isoformat()
        expires_at = (now_value + timedelta(seconds=lease_seconds)).isoformat()
        with self._connection() as db:
            db.execute("BEGIN IMMEDIATE")
            exists = db.execute("SELECT 1 FROM printers WHERE id = ?", (printer_id,)).fetchone()
            if exists is None:
                raise KeyError(printer_id)
            return self._try_acquire_operation(
                db,
                printer_id=printer_id,
                kind=kind,
                now=now,
                expires_at=expires_at,
            )

    def release_printer_operation(self, printer_id: str, owner: str) -> None:
        with self._connection() as db:
            db.execute(
                "DELETE FROM printer_operation_leases WHERE printer_id = ? AND owner = ?",
                (printer_id, owner),
            )

    def export_printers(self) -> dict[str, Any]:
        with self._connection() as db:
            rows = db.execute(
                "SELECT payload_json FROM printers ORDER BY id"
            ).fetchall()
        printers = [json.loads(row["payload_json"]) for row in rows]
        return {"config_version": 1, "printers": printers}

    def import_printers(self, document: Mapping[str, Any]) -> None:
        if document.get("config_version") != 1 or not isinstance(document.get("printers"), list):
            raise ValueError("Printer import requires config_version 1 and a printers list")
        incoming = [dict(item) for item in document["printers"] if isinstance(item, Mapping)]
        if len(incoming) != len(document["printers"]):
            raise ValueError("Every imported printer must be an object")
        ids = [str(item.get("id") or "").strip() for item in incoming]
        if any(not printer_id for printer_id in ids) or len(set(ids)) != len(ids):
            raise ValueError("Imported printer ids must be present and unique")
        now = _now()
        with self._connection() as db:
            for printer_id, printer in zip(ids, incoming):
                printer.pop("registry", None)
                printer = normalize_printer(printer)
                existing = db.execute(
                    "SELECT payload_json FROM printers WHERE id = ?", (printer_id,)
                ).fetchone()
                encoded = json.dumps(printer, sort_keys=True)
                if existing and existing["payload_json"] != encoded:
                    raise RegistryConflict(f"Imported printer conflicts with existing id: {printer_id}")
                if not existing:
                    db.execute(
                        """INSERT INTO printers(id, revision, payload_json, created_at, updated_at)
                           VALUES (?, 1, ?, ?, ?)""",
                        (printer_id, encoded, now, now),
                    )

    def get_printer(self, printer_id: str) -> dict[str, Any]:
        with self._connection() as db:
            row = db.execute(
                """SELECT p.payload_json, p.revision, o.media_json, o.alignment_json,
                          o.capabilities_json, o.source, o.observed_at,
                          c.paused, c.reason AS pause_reason, c.updated_at AS control_updated_at
                   FROM printers p LEFT JOIN printer_observations o ON o.printer_id = p.id
                   LEFT JOIN printer_controls c ON c.printer_id = p.id
                   WHERE p.id = ?""",
                (printer_id,),
            ).fetchone()
        if row is None:
            raise KeyError(printer_id)
        return self._printer(row)

    @staticmethod
    def _printer(row: sqlite3.Row) -> dict[str, Any]:
        printer = json.loads(row["payload_json"])
        printer["registry"] = {"revision": row["revision"]}
        if "observed_at" in row.keys() and row["observed_at"]:
            for field in ("media", "alignment", "capabilities"):
                encoded = row[f"{field}_json"]
                if encoded is not None:
                    printer[field] = json.loads(encoded)
            printer["observation"] = {
                "source": row["source"],
                "observed_at": row["observed_at"],
            }
        if "paused" in row.keys():
            printer["control"] = {
                "paused": bool(row["paused"]) if row["paused"] is not None else False,
                "reason": row["pause_reason"],
                "updated_at": row["control_updated_at"],
            }
        return printer

    def set_printer_paused(
        self,
        printer_id: str,
        *,
        paused: bool,
        reason: str | None = None,
    ) -> dict[str, Any]:
        self.get_printer(printer_id)
        normalized_reason = str(reason).strip() if reason is not None else None
        if normalized_reason and len(normalized_reason) > 500:
            raise ValueError("Pause reason must not exceed 500 characters")
        now = _now()
        with self._connection() as db:
            db.execute(
                """INSERT INTO printer_controls(printer_id, paused, reason, updated_at)
                   VALUES (?, ?, ?, ?)
                   ON CONFLICT(printer_id) DO UPDATE SET
                       paused=excluded.paused, reason=excluded.reason,
                       updated_at=excluded.updated_at""",
                (printer_id, int(paused), normalized_reason if paused else None, now),
            )
        return self.get_printer(printer_id)

    @staticmethod
    def _delivery(row: sqlite3.Row) -> dict[str, Any]:
        delivery = dict(row)
        delivery["printer_snapshot"] = json.loads(delivery.pop("printer_snapshot_json"))
        delivery.pop("route_snapshot_json", None)
        delivery.pop("artifact_payload", None)
        return delivery

    @staticmethod
    def _delivery_internal(row: sqlite3.Row) -> dict[str, Any]:
        delivery = FleetRepository._delivery(row)
        raw = dict(row)
        delivery["_artifact_payload"] = bytes(raw["artifact_payload"])
        delivery["_route_snapshot"] = json.loads(raw["route_snapshot_json"])
        return delivery

    def put_printer(self, printer: Mapping[str, Any]) -> dict[str, Any]:
        printer_id = str(printer.get("id", "")).strip()
        if not printer_id:
            raise ValueError("Printer id is required")
        payload = dict(printer)
        payload.pop("registry", None)
        payload = normalize_printer(payload)
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
        with self._connection() as db:
            row = db.execute(
                "SELECT payload_json, revision FROM printers WHERE id = ?", (printer_id,)
            ).fetchone()
        if row is None:
            raise KeyError(printer_id)
        current = json.loads(row["payload_json"])
        revision = int(row["revision"])
        if revision != expected_revision:
            raise RegistryConflict(
                f"Printer revision changed: expected {expected_revision}, current {revision}"
            )
        updated = dict(current)
        for key, value in settings.items():
            if key in {"id", "registry"}:
                raise ValueError(f"Printer field cannot be patched: {key}")
            updated[key] = value
        updated = normalize_printer(updated)
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

    def record_printer_observation(
        self,
        printer_id: str,
        *,
        media: Mapping[str, Any] | None,
        alignment: Mapping[str, Any] | None,
        capabilities: Mapping[str, Any] | None,
        source: str,
    ) -> dict[str, Any]:
        self.get_printer(printer_id)
        now = _now()
        with self._connection() as db:
            db.execute(
                """INSERT INTO printer_observations(
                   printer_id, media_json, alignment_json, capabilities_json, source, observed_at)
                   VALUES (?, ?, ?, ?, ?, ?)
                   ON CONFLICT(printer_id) DO UPDATE SET
                   media_json=excluded.media_json, alignment_json=excluded.alignment_json,
                   capabilities_json=excluded.capabilities_json, source=excluded.source,
                   observed_at=excluded.observed_at""",
                (
                    printer_id,
                    json.dumps(dict(media), sort_keys=True) if media is not None else None,
                    json.dumps(dict(alignment), sort_keys=True) if alignment is not None else None,
                    json.dumps(dict(capabilities), sort_keys=True) if capabilities is not None else None,
                    source,
                    now,
                ),
            )
        return self.get_printer(printer_id)

    def record_agent(self, observation: Mapping[str, Any]) -> dict[str, Any]:
        agent_id = str(observation["id"])
        base_url = str(observation["base_url"])
        printers = list(observation.get("printers") or [])
        payload = {key: value for key, value in observation.items() if key != "printers"}
        now = _now()
        with self._connection() as db:
            existing_url = db.execute(
                "SELECT id FROM agents WHERE base_url = ? AND id != ?", (base_url, agent_id)
            ).fetchone()
            if existing_url:
                raise RegistryConflict("Agent endpoint is already bound to another identity")
            db.execute(
                """INSERT INTO agents(id, base_url, available, payload_json, last_seen_at, updated_at)
                   VALUES (?, ?, 1, ?, ?, ?)
                   ON CONFLICT(id) DO UPDATE SET base_url=excluded.base_url, available=1,
                   payload_json=excluded.payload_json, last_seen_at=excluded.last_seen_at,
                   last_error=NULL, updated_at=excluded.updated_at""",
                (agent_id, base_url, json.dumps(payload, sort_keys=True), now, now),
            )
            db.execute("DELETE FROM agent_devices WHERE agent_id = ?", (agent_id,))
            for device in printers:
                db.execute(
                    """INSERT INTO agent_devices(agent_id, device_id, payload_json, observed_at)
                       VALUES (?, ?, ?, ?)""",
                    (agent_id, str(device["id"]), json.dumps(device, sort_keys=True), now),
                )
        return self.get_agent(agent_id)

    def mark_agent_unavailable(self, base_url: str, error: str) -> None:
        with self._connection() as db:
            db.execute(
                """UPDATE agents SET available=0, last_error=?, updated_at=? WHERE base_url=?""",
                (error, _now(), base_url),
            )

    def get_agent(self, agent_id: str) -> dict[str, Any]:
        with self._connection() as db:
            agent = db.execute("SELECT * FROM agents WHERE id = ?", (agent_id,)).fetchone()
            if agent is None:
                raise KeyError(agent_id)
            devices = db.execute(
                "SELECT device_id, payload_json, observed_at FROM agent_devices WHERE agent_id=? ORDER BY device_id",
                (agent_id,),
            ).fetchall()
            registered = db.execute("SELECT id, payload_json FROM printers").fetchall()
        registered_ids: dict[str, str] = {}
        for row in registered:
            printer = json.loads(row["payload_json"])
            connection = printer.get("connection") or {}
            if connection.get("agent_id") == agent_id and connection.get("printer_id"):
                registered_ids[str(connection["printer_id"])] = str(row["id"])
        result = json.loads(agent["payload_json"])
        result.update(
            id=agent["id"],
            base_url=agent["base_url"],
            available=bool(agent["available"]),
            last_seen_at=agent["last_seen_at"],
            error=agent["last_error"],
        )
        result["printers"] = []
        for device in devices:
            payload = json.loads(device["payload_json"])
            payload["registered_id"] = registered_ids.get(str(device["device_id"]))
            payload["observed_at"] = device["observed_at"]
            result["printers"].append(payload)
        return result

    def list_agents(self) -> list[dict[str, Any]]:
        with self._connection() as db:
            ids = [row["id"] for row in db.execute("SELECT id FROM agents ORDER BY id").fetchall()]
        return [self.get_agent(str(agent_id)) for agent_id in ids]

    def get_agent_device(self, agent_id: str, device_id: str) -> tuple[dict[str, Any], dict[str, Any]]:
        agent = self.get_agent(agent_id)
        device = next(
            (item for item in agent["printers"] if str(item.get("id")) == device_id),
            None,
        )
        if device is None:
            raise KeyError(device_id)
        return agent, device

    def create_delivery(
        self,
        *,
        idempotency_key: str,
        request_hash: str,
        printer_id: str,
        printer_snapshot: Mapping[str, Any],
        route_snapshot: Mapping[str, Any],
        artifact_checksum: str,
        artifact_mime_type: str,
        artifact_payload: bytes,
        artifact_description: str,
        max_attempts: int,
        accepted_at: str | None = None,
    ) -> tuple[dict[str, Any], bool]:
        now = accepted_at or _now()
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
                   id, idempotency_key, request_hash, printer_id, printer_snapshot_json,
                   route_snapshot_json, artifact_checksum, artifact_mime_type,
                   artifact_payload, artifact_description, state, max_attempts,
                   next_attempt_at, created_at, updated_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    delivery_id,
                    idempotency_key,
                    request_hash,
                    printer_id,
                    json.dumps(dict(printer_snapshot), sort_keys=True),
                    json.dumps(dict(route_snapshot), sort_keys=True),
                    artifact_checksum,
                    artifact_mime_type,
                    artifact_payload,
                    artifact_description,
                    DeliveryState.QUEUED.value,
                    max_attempts,
                    now,
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

    def list_due_delivery_ids(self, *, now: str, limit: int = 20) -> list[str]:
        with self._connection() as db:
            rows = db.execute(
                """WITH pending AS (
                       SELECT id, printer_id, created_at,
                              ROW_NUMBER() OVER (
                                  PARTITION BY printer_id ORDER BY created_at, id
                              ) AS printer_position
                       FROM deliveries
                       WHERE state IN (?, ?)
                         AND artifact_payload IS NOT NULL
                   )
                   SELECT pending.id
                   FROM pending
                   JOIN deliveries current ON current.id = pending.id
                   LEFT JOIN printer_controls control ON control.printer_id = pending.printer_id
                   WHERE pending.printer_position = 1
                     AND COALESCE(control.paused, 0) = 0
                     AND (current.next_attempt_at IS NULL OR current.next_attempt_at <= ?)
                     AND NOT EXISTS (
                         SELECT 1 FROM deliveries active
                         WHERE active.printer_id = pending.printer_id
                           AND active.state IN (?, ?)
                     )
                   ORDER BY pending.created_at, pending.id
                   LIMIT ?""",
                (
                    DeliveryState.QUEUED.value,
                    DeliveryState.RETRY_SCHEDULED.value,
                    now,
                    DeliveryState.CONNECTING.value,
                    DeliveryState.TRANSMITTING.value,
                    limit,
                ),
            ).fetchall()
        return [str(row["id"]) for row in rows]

    def list_deliveries(
        self,
        *,
        delivery_ids: Collection[str] | None = None,
        printer_id: str | None = None,
        printer_ids: Collection[str] | None = None,
        state: str | None = None,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        clauses: list[str] = []
        parameters: list[Any] = []
        if delivery_ids is not None:
            selected = sorted(set(delivery_ids))
            if not selected:
                return []
            clauses.append(f"id IN ({','.join('?' for _ in selected)})")
            parameters.extend(selected)
        if printer_id:
            clauses.append("printer_id = ?")
            parameters.append(printer_id)
        elif printer_ids is not None:
            allowed = sorted(set(printer_ids))
            if not allowed:
                return []
            clauses.append(f"printer_id IN ({','.join('?' for _ in allowed)})")
            parameters.extend(allowed)
        if state:
            clauses.append("state = ?")
            parameters.append(state)
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        parameters.append(limit)
        with self._connection() as db:
            rows = db.execute(
                f"""SELECT * FROM deliveries {where}
                    ORDER BY created_at DESC, id DESC LIMIT ?""",
                parameters,
            ).fetchall()
        return [self._delivery(row) for row in rows]

    def recover_interrupted_deliveries(self) -> int:
        """Fail closed when a crash makes the physical outcome unknowable."""
        now = _now()
        detail = "PrinterFleet restarted during physical delivery; outcome is unknown"
        with self._connection() as db:
            rows = db.execute(
                "SELECT id FROM deliveries WHERE state IN (?, ?)",
                (DeliveryState.CONNECTING.value, DeliveryState.TRANSMITTING.value),
            ).fetchall()
            for row in rows:
                db.execute(
                    """UPDATE deliveries SET state=?, error=?, next_attempt_at=NULL, updated_at=?
                       WHERE id=?""",
                    (DeliveryState.UNCONFIRMED.value, detail, now, row["id"]),
                )
                db.execute(
                    """INSERT INTO delivery_events(delivery_id, state, detail, occurred_at)
                       VALUES (?, ?, ?, ?)""",
                    (row["id"], DeliveryState.UNCONFIRMED.value, detail, now),
                )
        return len(rows)

    def claim_delivery(
        self,
        delivery_id: str,
        *,
        now: str,
        lease_expires_at: str | None = None,
    ) -> dict[str, Any] | None:
        with self._connection() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute("SELECT * FROM deliveries WHERE id = ?", (delivery_id,)).fetchone()
            if row is None:
                raise KeyError(delivery_id)
            if row["state"] not in {
                DeliveryState.QUEUED.value,
                DeliveryState.RETRY_SCHEDULED.value,
            }:
                return None
            if row["artifact_payload"] is None:
                return None
            if row["next_attempt_at"] and row["next_attempt_at"] > now:
                return None
            blocking = db.execute(
                """SELECT 1 FROM deliveries
                   WHERE printer_id = ? AND id != ?
                     AND artifact_payload IS NOT NULL
                     AND (
                         state IN (?, ?)
                         OR (
                             state IN (?, ?)
                             AND (created_at < ? OR (created_at = ? AND id < ?))
                         )
                     )
                   LIMIT 1""",
                (
                    row["printer_id"],
                    delivery_id,
                    DeliveryState.CONNECTING.value,
                    DeliveryState.TRANSMITTING.value,
                    DeliveryState.QUEUED.value,
                    DeliveryState.RETRY_SCHEDULED.value,
                    row["created_at"],
                    row["created_at"],
                    delivery_id,
                ),
            ).fetchone()
            if blocking is not None:
                return None
            expires_at = lease_expires_at or (
                datetime.fromisoformat(now) + timedelta(minutes=5)
            ).isoformat()
            operation_owner = self._try_acquire_operation(
                db,
                printer_id=str(row["printer_id"]),
                kind="delivery",
                now=now,
                expires_at=expires_at,
            )
            if operation_owner is None:
                return None
            db.execute(
                """UPDATE deliveries
                   SET state = ?, attempt_count = attempt_count + 1,
                       next_attempt_at = NULL, updated_at = ?
                   WHERE id = ?""",
                (DeliveryState.CONNECTING.value, now, delivery_id),
            )
            db.execute(
                """INSERT INTO delivery_events(delivery_id, state, occurred_at)
                   VALUES (?, ?, ?)""",
                (delivery_id, DeliveryState.CONNECTING.value, now),
            )
            claimed = db.execute("SELECT * FROM deliveries WHERE id = ?", (delivery_id,)).fetchone()
        result = self._delivery_internal(claimed)
        result["_operation_owner"] = operation_owner
        return result

    def transition(
        self,
        delivery_id: str,
        state: DeliveryState,
        *,
        bytes_accepted: int = 0,
        detail: str | None = None,
        next_attempt_at: str | None = None,
        downstream_job_id: str | None = None,
        downstream_state: str | None = None,
    ) -> dict[str, Any]:
        now = _now()
        with self._connection() as db:
            db.execute(
                """UPDATE deliveries SET state = ?, bytes_accepted = ?, error = ?,
                   next_attempt_at = ?, downstream_job_id = ?, downstream_state = ?,
                   updated_at = ?
                   WHERE id = ?""",
                (
                    state.value,
                    bytes_accepted,
                    detail
                    if state
                    in {
                        DeliveryState.FAILED,
                        DeliveryState.RETRY_SCHEDULED,
                        DeliveryState.UNCONFIRMED,
                    }
                    else None,
                    next_attempt_at,
                    downstream_job_id,
                    downstream_state,
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
