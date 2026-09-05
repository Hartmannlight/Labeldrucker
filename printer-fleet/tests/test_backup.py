from __future__ import annotations

import json
from pathlib import Path

import pytest

from printer_fleet.backup import create_backup, restore_backup, verify_backup
from printer_fleet.repository import FleetRepository


@pytest.fixture
def database(tmp_path: Path) -> Path:
    path = tmp_path / "fleet.sqlite3"
    repository = FleetRepository(path)
    repository.initialize()
    repository.put_printer(
        {
            "id": "zebra-1",
            "site_id": "warehouse",
            "driver": "zpl",
            "connection": {"protocol": "raw_tcp", "host": "printer.example"},
        }
    )
    return path


def test_backup_is_consistent_verifiable_and_restorable(database: Path, tmp_path: Path) -> None:
    backup = tmp_path / "backups" / "fleet.sqlite3"
    manifest = create_backup(database, backup)

    verified = verify_backup(backup, manifest)
    restored = tmp_path / "restored" / "fleet.sqlite3"
    restore_backup(backup, restored, manifest)

    assert verified["format"] == "printer-fleet-sqlite-backup-v1"
    assert verified["schemaVersion"] == 1
    assert verified["counts"]["printers"] == 1
    assert FleetRepository(restored).get_printer("zebra-1")["site_id"] == "warehouse"


def test_backup_and_restore_never_overwrite_existing_files(database: Path, tmp_path: Path) -> None:
    backup = tmp_path / "fleet.backup.sqlite3"
    create_backup(database, backup)
    with pytest.raises(FileExistsError, match="overwrite backup"):
        create_backup(database, backup)

    target = tmp_path / "existing.sqlite3"
    target.write_bytes(b"operator data")
    with pytest.raises(FileExistsError, match="overwrite Fleet database"):
        restore_backup(backup, target)
    assert target.read_bytes() == b"operator data"


def test_modified_backup_fails_before_restore(database: Path, tmp_path: Path) -> None:
    backup = tmp_path / "fleet.backup.sqlite3"
    manifest_path = create_backup(database, backup)
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["checksum"] = "sha256:" + "0" * 64
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

    with pytest.raises(ValueError, match="checksum"):
        verify_backup(backup, manifest_path)
