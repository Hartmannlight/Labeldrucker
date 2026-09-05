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


def test_newer_database_fails_closed_without_downgrade(tmp_path: Path) -> None:
    path = tmp_path / "future.sqlite3"
    with sqlite3.connect(path) as database:
        database.execute(f"PRAGMA user_version = {CURRENT_SCHEMA_VERSION + 1}")

    with pytest.raises(RuntimeError, match="newer than supported"):
        FleetRepository(path).initialize()

    with sqlite3.connect(path) as database:
        assert database.execute("PRAGMA user_version").fetchone()[0] == CURRENT_SCHEMA_VERSION + 1
