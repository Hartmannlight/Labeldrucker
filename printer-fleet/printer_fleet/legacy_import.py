from __future__ import annotations

import argparse
import json
from pathlib import Path
import sqlite3
from typing import Any, Mapping

import yaml

from .configuration import normalize_printer


_PROTOCOL_ALIASES = {
    "raw9100": "raw_tcp",
    "zebra_tamer": "print_agent",
    "driver_agent": "print_agent",
}


def migrate_printer(printer: Mapping[str, Any]) -> dict[str, Any]:
    migrated = dict(printer)
    migrated.pop("registry", None)
    migrated.pop("discovery", None)
    migrated.pop("zebra_tamer", None)
    connection = dict(migrated.get("connection") or {})
    protocol = str(connection.get("protocol") or "").strip()
    connection["protocol"] = _PROTOCOL_ALIASES.get(protocol, protocol)
    if connection["protocol"] == "print_agent" and not connection.get("agent_id"):
        raise ValueError(
            f"Printer {migrated.get('id') or '<unknown>'} has no stable agent_id; "
            "discover and register it in PrinterFleet instead of guessing identity"
        )
    migrated["connection"] = connection
    return normalize_printer(migrated)


def migrate_document(document: Mapping[str, Any]) -> dict[str, Any]:
    if document.get("config_version") != 1 or not isinstance(document.get("printers"), list):
        raise ValueError("Legacy registry requires config_version 1 and a printers list")
    printers = [migrate_printer(item) for item in document["printers"] if isinstance(item, Mapping)]
    if len(printers) != len(document["printers"]):
        raise ValueError("Every legacy printer must be an object")
    ids = [printer["id"] for printer in printers]
    if len(ids) != len(set(ids)):
        raise ValueError("Legacy printer ids must be unique")
    return {"config_version": 1, "printers": printers}


def load_legacy_registry(path: Path) -> dict[str, Any]:
    suffix = path.suffix.lower()
    if suffix in {".yaml", ".yml"}:
        document = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    elif suffix == ".json":
        document = json.loads(path.read_text(encoding="utf-8"))
    else:
        uri = f"{path.resolve().as_uri()}?mode=ro"
        with sqlite3.connect(uri, uri=True) as database:
            columns = {
                str(row[1]) for row in database.execute("PRAGMA table_info(printers)")
            }
            if "config" not in columns:
                raise ValueError("Not a supported legacy PrintHub registry database")
            rows = database.execute("SELECT config FROM printers ORDER BY rowid").fetchall()
        document = {
            "config_version": 1,
            "printers": [json.loads(str(row[0])) for row in rows],
        }
    if not isinstance(document, Mapping):
        raise ValueError("Legacy registry root must be an object")
    return migrate_document(document)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Convert a legacy PrintHub printer registry for PrinterFleet import."
    )
    parser.add_argument("--source", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    if args.output.exists():
        raise SystemExit(f"Refusing to overwrite existing output: {args.output}")
    document = load_legacy_registry(args.source)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(document, indent=2) + "\n", encoding="utf-8")
    print(f"Migrated {len(document['printers'])} printers to {args.output}")


if __name__ == "__main__":
    main()
