from __future__ import annotations

import argparse
import base64
import hashlib
import json
import os
from pathlib import Path
import sqlite3
from typing import Any, Iterable, Sequence

import psycopg
from psycopg import sql
from psycopg.rows import dict_row

from .postgres_repository import PostgresFleetRepository, _SCHEMA_LOCK_ID
from .repository import CURRENT_SCHEMA_VERSION


TABLES: tuple[tuple[str, tuple[str, ...], tuple[str, ...]], ...] = (
    ("printers", ("id", "revision", "payload_json", "created_at", "updated_at"), ("id",)),
    (
        "deliveries",
        (
            "id", "idempotency_key", "request_hash", "printer_id",
            "printer_snapshot_json", "route_snapshot_json", "artifact_checksum",
            "artifact_mime_type", "artifact_payload", "artifact_description", "state",
            "attempt_count", "max_attempts", "next_attempt_at", "downstream_job_id",
            "downstream_state", "bytes_accepted", "error", "created_at", "updated_at",
        ),
        ("id",),
    ),
    (
        "delivery_events", ("sequence", "delivery_id", "state", "detail", "occurred_at"),
        ("sequence",),
    ),
    (
        "agents",
        ("id", "base_url", "available", "payload_json", "last_seen_at", "last_error", "updated_at"),
        ("id",),
    ),
    ("agent_devices", ("agent_id", "device_id", "payload_json", "observed_at"), ("agent_id", "device_id")),
    (
        "printer_observations",
        ("printer_id", "media_json", "alignment_json", "capabilities_json", "source", "observed_at"),
        ("printer_id",),
    ),
    (
        "printer_operation_leases",
        ("printer_id", "owner", "kind", "acquired_at", "expires_at"), ("printer_id",),
    ),
    ("printer_controls", ("printer_id", "paused", "reason", "updated_at"), ("printer_id",)),
    (
        "audit_records",
        ("id", "correlation_id", "actor", "method", "path", "status_code", "occurred_at"),
        ("id",),
    ),
)


def _portable(value: Any) -> Any:
    if isinstance(value, (bytes, bytearray, memoryview)):
        return {"base64": base64.b64encode(bytes(value)).decode("ascii")}
    return value


def _fingerprint(rows: Iterable[Sequence[Any]]) -> str:
    digest = hashlib.sha256()
    for row in rows:
        encoded = json.dumps([_portable(value) for value in row], separators=(",", ":"))
        digest.update(encoded.encode("utf-8"))
        digest.update(b"\n")
    return f"sha256:{digest.hexdigest()}"


def _sqlite_rows(
    db: sqlite3.Connection, table: str, columns: tuple[str, ...], order: tuple[str, ...]
) -> list[tuple[Any, ...]]:
    names = ", ".join(columns)
    ordering = ", ".join(order)
    return [tuple(row) for row in db.execute(f"SELECT {names} FROM {table} ORDER BY {ordering}")]


def _postgres_rows(
    db: psycopg.Connection[Any], table: str, columns: tuple[str, ...], order: tuple[str, ...]
) -> list[tuple[Any, ...]]:
    query = sql.SQL("SELECT {} FROM {} ORDER BY {}").format(
        sql.SQL(", ").join(map(sql.Identifier, columns)),
        sql.Identifier(table),
        sql.SQL(", ").join(map(sql.Identifier, order)),
    )
    return [tuple(row[column] for column in columns) for row in db.execute(query).fetchall()]


def migrate_sqlite_to_postgres(source: Path, database_url: str) -> dict[str, Any]:
    """Copy a stopped SQLite Fleet database into an empty PostgreSQL schema."""
    if not source.is_file():
        raise FileNotFoundError(source)
    PostgresFleetRepository(database_url).initialize()
    with sqlite3.connect(source, timeout=10) as source_db:
        source_db.execute("PRAGMA foreign_keys = ON")
        source_db.execute("BEGIN IMMEDIATE")
        version = int(source_db.execute("PRAGMA user_version").fetchone()[0])
        if version != CURRENT_SCHEMA_VERSION:
            raise RuntimeError(
                f"Source schema must be version {CURRENT_SCHEMA_VERSION}, found {version}"
            )
        source_rows = {
            table: _sqlite_rows(source_db, table, columns, order)
            for table, columns, order in TABLES
        }
        with psycopg.connect(database_url, row_factory=dict_row) as target_db:
            target_db.execute("SELECT pg_advisory_xact_lock(%s)", (_SCHEMA_LOCK_ID,))
            populated = {
                table: int(target_db.execute(
                    sql.SQL("SELECT COUNT(*) AS count FROM {}").format(sql.Identifier(table))
                ).fetchone()["count"])
                for table, _columns, _order in TABLES
            }
            if any(populated.values()):
                raise RuntimeError("PostgreSQL migration target must be empty")
            for table, columns, _order in TABLES:
                insert = sql.SQL("INSERT INTO {} ({}) VALUES ({})").format(
                    sql.Identifier(table),
                    sql.SQL(", ").join(map(sql.Identifier, columns)),
                    sql.SQL(", ").join(sql.Placeholder() for _ in columns),
                )
                if source_rows[table]:
                    target_db.executemany(insert, source_rows[table])
            target_db.execute(
                """SELECT setval(
                       pg_get_serial_sequence('delivery_events', 'sequence'),
                       COALESCE(MAX(sequence), 1), COUNT(*) > 0)
                   FROM delivery_events"""
            )
            verification: dict[str, Any] = {}
            for table, columns, order in TABLES:
                target_rows = _postgres_rows(target_db, table, columns, order)
                source_hash = _fingerprint(source_rows[table])
                target_hash = _fingerprint(target_rows)
                if source_hash != target_hash:
                    raise RuntimeError(f"Migration verification failed for table {table}")
                verification[table] = {"rows": len(target_rows), "sha256": source_hash}
    return {"schema_version": CURRENT_SCHEMA_VERSION, "tables": verification}


def main() -> None:
    parser = argparse.ArgumentParser(description="Offline SQLite to PostgreSQL Fleet migration")
    parser.add_argument("--source", required=True, type=Path)
    target = parser.add_mutually_exclusive_group()
    target.add_argument("--target-url")
    target.add_argument("--target-url-file", type=Path)
    args = parser.parse_args()
    target_url = args.target_url or os.getenv("PRINTER_FLEET_DATABASE_URL", "").strip()
    if args.target_url_file:
        target_url = args.target_url_file.read_text(encoding="utf-8").strip()
    if not target_url:
        parser.error(
            "provide --target-url, --target-url-file, or PRINTER_FLEET_DATABASE_URL"
        )
    print(json.dumps(migrate_sqlite_to_postgres(args.source, target_url), sort_keys=True))


if __name__ == "__main__":
    main()
