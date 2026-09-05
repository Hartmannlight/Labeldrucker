from __future__ import annotations

import json
import sqlite3

import pytest

from printer_fleet.legacy_import import load_legacy_registry, migrate_document


def _raw_printer() -> dict:
    return {
        "id": "zebra-1",
        "driver": "zpl",
        "connection": {"protocol": "raw9100", "host": "zebra.local"},
    }


def test_migrates_legacy_protocol_and_strips_runtime_metadata(tmp_path):
    source = tmp_path / "printers.yml"
    source.write_text(
        "config_version: 1\n"
        "printers:\n"
        "  - id: zebra-1\n"
        "    driver: zpl\n"
        "    connection:\n"
        "      protocol: raw9100\n"
        "      host: zebra.local\n"
        "    registry: {revision: 2}\n",
        encoding="utf-8",
    )

    migrated = load_legacy_registry(source)

    printer = migrated["printers"][0]
    assert printer["connection"]["protocol"] == "raw_tcp"
    assert printer["connection"]["port"] == 9100
    assert "registry" not in printer


def test_reads_legacy_printhub_sqlite_registry(tmp_path):
    source = tmp_path / "printers.sqlite3"
    with sqlite3.connect(source) as database:
        database.execute("CREATE TABLE printers (config TEXT NOT NULL)")
        database.execute("INSERT INTO printers VALUES (?)", (json.dumps(_raw_printer()),))

    migrated = load_legacy_registry(source)

    assert migrated["printers"][0]["id"] == "zebra-1"
    assert migrated["printers"][0]["connection"]["protocol"] == "raw_tcp"


def test_refuses_to_guess_missing_print_agent_identity():
    printer = {
        "id": "usb-zebra",
        "driver": "zpl",
        "connection": {
            "protocol": "zebra_tamer",
            "base_url": "http://agent:8080",
            "printer_id": "local-zebra",
        },
    }

    with pytest.raises(ValueError, match="stable agent_id"):
        migrate_document({"config_version": 1, "printers": [printer]})
