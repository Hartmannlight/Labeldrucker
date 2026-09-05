from __future__ import annotations

import os
from pathlib import Path

from .ports import FleetRepositoryPort
from .repository import FleetRepository


def repository_from_environment() -> FleetRepositoryPort:
    """Select exactly one persistence adapter at the process boundary."""
    inline_url = os.getenv("PRINTER_FLEET_DATABASE_URL", "").strip()
    url_file = os.getenv("PRINTER_FLEET_DATABASE_URL_FILE", "").strip()
    if inline_url and url_file:
        raise RuntimeError(
            "Set either PRINTER_FLEET_DATABASE_URL or PRINTER_FLEET_DATABASE_URL_FILE, not both"
        )
    database_url = (
        Path(url_file).read_text(encoding="utf-8").strip() if url_file else inline_url
    )
    if url_file and not database_url:
        raise RuntimeError("PRINTER_FLEET_DATABASE_URL_FILE must not be empty")
    sqlite_path = os.getenv("PRINTER_FLEET_DATABASE", "").strip()
    if database_url and sqlite_path:
        raise RuntimeError(
            "PostgreSQL URL configuration and PRINTER_FLEET_DATABASE are mutually exclusive"
        )
    if database_url:
        if not database_url.startswith(("postgresql://", "postgres://")):
            raise RuntimeError("PRINTER_FLEET_DATABASE_URL must be a PostgreSQL URL")
        from .postgres_repository import PostgresFleetRepository

        return PostgresFleetRepository(database_url)
    return FleetRepository(sqlite_path or "/data/fleet.sqlite3")
