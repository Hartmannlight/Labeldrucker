from __future__ import annotations

from printer_fleet.worker_main import main


def test_worker_database_health_check(tmp_path, monkeypatch):
    monkeypatch.setenv("PRINTER_FLEET_DATABASE", str(tmp_path / "fleet.sqlite3"))
    monkeypatch.delenv("PRINTER_FLEET_DATABASE_URL", raising=False)
    monkeypatch.delenv("PRINTER_FLEET_DATABASE_URL_FILE", raising=False)

    assert main(["--check"]) == 0
