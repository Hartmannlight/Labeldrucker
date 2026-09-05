from __future__ import annotations

from pathlib import Path
import sqlite3

import pytest

from printer_fleet.repository import CURRENT_SCHEMA_VERSION, FleetRepository


def test_initialize_versions_new_and_legacy_databases(tmp_path: Path) -> None:
    path = tmp_path / "fleet.sqlite3"
    FleetRepository(path).initialize()

    with sqlite3.connect(path) as database:
        assert database.execute("PRAGMA user_version").fetchone()[0] == CURRENT_SCHEMA_VERSION


def test_version_one_database_migrates_printer_controls_without_data_loss(tmp_path: Path) -> None:
    path = tmp_path / "version-one.sqlite3"
    with sqlite3.connect(path) as database:
        database.execute(
            """CREATE TABLE printers (
                   id TEXT PRIMARY KEY,
                   revision INTEGER NOT NULL,
                   payload_json TEXT NOT NULL,
                   created_at TEXT NOT NULL,
                   updated_at TEXT NOT NULL
               )"""
        )
        database.execute(
            """INSERT INTO printers VALUES (
                   'legacy-zebra', 1,
                   '{"id":"legacy-zebra","driver":"zpl","connection":{"protocol":"raw_tcp","host":"legacy.example"}}',
                   '2026-09-05T00:00:00+00:00', '2026-09-05T00:00:00+00:00'
               )"""
        )
        database.execute("PRAGMA user_version = 1")

    repository = FleetRepository(path)
    repository.initialize()

    assert repository.get_printer("legacy-zebra")["control"]["paused"] is False
    with sqlite3.connect(path) as database:
        assert database.execute("PRAGMA user_version").fetchone()[0] == 2
        assert database.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='printer_controls'"
        ).fetchone() == ("printer_controls",)


def test_newer_database_fails_closed_without_downgrade(tmp_path: Path) -> None:
    path = tmp_path / "future.sqlite3"
    with sqlite3.connect(path) as database:
        database.execute(f"PRAGMA user_version = {CURRENT_SCHEMA_VERSION + 1}")

    with pytest.raises(RuntimeError, match="newer than supported"):
        FleetRepository(path).initialize()

    with sqlite3.connect(path) as database:
        assert database.execute("PRAGMA user_version").fetchone()[0] == CURRENT_SCHEMA_VERSION + 1
