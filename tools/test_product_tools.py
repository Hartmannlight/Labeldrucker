from __future__ import annotations

import json
from pathlib import Path
import sqlite3

import pytest

from tools import backup_product, migrate_fleet


def test_migration_preserves_ids_and_never_requeues_uncertain_jobs(tmp_path: Path) -> None:
    database = tmp_path / "fleet.sqlite"
    with sqlite3.connect(database) as connection:
        connection.execute("CREATE TABLE printers (payload_json TEXT NOT NULL)")
        connection.execute(
            "CREATE TABLE deliveries (id TEXT, state TEXT, created_at TEXT, artifact_payload BLOB)"
        )
        connection.execute(
            "INSERT INTO printers VALUES (?)",
            (
                json.dumps(
                    {
                        "id": "shipping",
                        "name": "Shipping",
                        "connection": {"protocol": "raw_tcp", "host": "10.0.0.8"},
                        "alignment": {"dpi": 203},
                    }
                ),
            ),
        )
        connection.execute(
            "INSERT INTO deliveries VALUES (?, ?, ?, ?)",
            ("delivery-1", "transmitting", "2026-01-01T00:00:00Z", b"secret payload"),
        )
    printers, deliveries = migrate_fleet.read_document(database)
    plan = migrate_fleet.migration_plan(printers, deliveries)
    assert plan["zebratamer_printers"][0]["id"] == "shipping"
    assert plan["zebratamer_printers"][0]["tcp_port"] == 9100
    assert plan["manual_reconciliation"][0]["action"].endswith("never_auto_requeue")
    assert "artifact_payload" not in plan["legacy_deliveries"][0]


def test_versioned_json_export_keeps_postgres_delivery_history(tmp_path: Path) -> None:
    export = tmp_path / "fleet-export.json"
    export.write_text(
        json.dumps(
            {
                "format": "printer-fleet-export-v1",
                "printers": [
                    {
                        "id": "remote",
                        "connection": {
                            "protocol": "print_agent",
                            "agent_id": "stable-agent",
                            "printer_id": "local",
                        },
                    }
                ],
                "deliveries": [
                    {
                        "id": "delivery-from-postgres",
                        "state": "outcome_unknown",
                        "created_at": "2026-01-01T00:00:00Z",
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    printers, deliveries = migrate_fleet.read_document(export)
    plan = migrate_fleet.migration_plan(printers, deliveries)

    assert plan["remote_service_mappings"][0]["agent_id"] == "stable-agent"
    assert plan["legacy_deliveries"][0]["id"] == "delivery-from-postgres"
    assert plan["manual_reconciliation"][0]["delivery_id"] == "delivery-from-postgres"


def test_backup_round_trip_and_refuses_overwrite(tmp_path: Path) -> None:
    source = tmp_path / "source"
    source.mkdir()
    (source / "identity").write_text("stable-id", encoding="utf-8")
    (source / "nested").mkdir()
    (source / "nested" / "job.json").write_text('{"state":"queued"}', encoding="utf-8")
    archive = tmp_path / "backup.tar.gz"
    backup_product.create_backup(archive, [("zebratamer", source)])
    restored = tmp_path / "restored"
    backup_product.restore_backup(archive, restored)
    assert (restored / "data" / "zebratamer" / "identity").read_text() == "stable-id"
    assert json.loads(
        (restored / "data" / "zebratamer" / "nested" / "job.json").read_text()
    ) == {"state": "queued"}
    with pytest.raises(ValueError, match="non-empty"):
        backup_product.restore_backup(archive, restored)
