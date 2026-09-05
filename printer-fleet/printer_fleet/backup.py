from __future__ import annotations

import argparse
from contextlib import closing
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import sqlite3
import tempfile
from typing import Any


REQUIRED_TABLES = {
    "printers",
    "deliveries",
    "delivery_events",
    "agents",
    "agent_devices",
    "printer_observations",
    "printer_operation_leases",
    "audit_records",
}


def _connect_readonly(path: Path) -> sqlite3.Connection:
    return sqlite3.connect(f"{path.resolve().as_uri()}?mode=ro", uri=True)


def _checksum(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while chunk := stream.read(1024 * 1024):
            digest.update(chunk)
    return f"sha256:{digest.hexdigest()}"


def inspect_database(path: Path) -> dict[str, Any]:
    if not path.is_file():
        raise ValueError(f"Fleet database does not exist: {path}")
    with closing(_connect_readonly(path)) as database:
        integrity = str(database.execute("PRAGMA integrity_check").fetchone()[0])
        if integrity != "ok":
            raise ValueError(f"Fleet database integrity check failed: {integrity}")
        tables = {
            str(row[0])
            for row in database.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()
        }
        missing = REQUIRED_TABLES - tables
        if missing:
            raise ValueError(f"Fleet database is missing tables: {', '.join(sorted(missing))}")
        counts = {
            table: int(database.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0])
            for table in ("printers", "deliveries", "delivery_events", "audit_records")
        }
        schema_version = int(database.execute("PRAGMA user_version").fetchone()[0])
    return {
        "schemaVersion": schema_version,
        "counts": counts,
        "sizeBytes": path.stat().st_size,
        "checksum": _checksum(path),
    }


def create_backup(database_path: Path, output_path: Path) -> Path:
    manifest_path = output_path.with_suffix(output_path.suffix + ".manifest.json")
    if output_path.exists() or manifest_path.exists():
        raise FileExistsError(f"Refusing to overwrite backup: {output_path}")
    if not database_path.is_file():
        raise ValueError(f"Fleet database does not exist: {database_path}")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with closing(_connect_readonly(database_path)) as source, closing(
        sqlite3.connect(output_path)
    ) as destination:
        source.backup(destination)
    details = inspect_database(output_path)
    manifest = {
        "format": "printer-fleet-sqlite-backup-v1",
        "createdAt": datetime.now(timezone.utc).isoformat(),
        "database": output_path.name,
        **details,
    }
    manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return manifest_path


def verify_backup(backup_path: Path, manifest_path: Path | None = None) -> dict[str, Any]:
    selected_manifest = manifest_path or backup_path.with_suffix(
        backup_path.suffix + ".manifest.json"
    )
    document = json.loads(selected_manifest.read_text(encoding="utf-8"))
    if document.get("format") != "printer-fleet-sqlite-backup-v1":
        raise ValueError("Unsupported Fleet backup manifest format")
    if document.get("database") != backup_path.name:
        raise ValueError("Fleet backup manifest names another database")
    details = inspect_database(backup_path)
    for field in ("schemaVersion", "counts", "sizeBytes", "checksum"):
        if document.get(field) != details[field]:
            raise ValueError(f"Fleet backup manifest mismatch: {field}")
    return document


def restore_backup(backup_path: Path, target_path: Path, manifest_path: Path | None = None) -> None:
    verify_backup(backup_path, manifest_path)
    if target_path.exists():
        raise FileExistsError(f"Refusing to overwrite Fleet database: {target_path}")
    target_path.parent.mkdir(parents=True, exist_ok=True)
    temporary_name: str | None = None
    try:
        with tempfile.NamedTemporaryFile(
            prefix=f".{target_path.name}.",
            suffix=".restore",
            dir=target_path.parent,
            delete=False,
        ) as temporary:
            temporary_name = temporary.name
        temporary_path = Path(temporary_name)
        with closing(_connect_readonly(backup_path)) as source, closing(
            sqlite3.connect(temporary_path)
        ) as target:
            source.backup(target)
        inspect_database(temporary_path)
        if target_path.exists():
            raise FileExistsError(f"Refusing to overwrite Fleet database: {target_path}")
        os.link(temporary_path, target_path)
        temporary_path.unlink()
        temporary_name = None
    finally:
        if temporary_name:
            Path(temporary_name).unlink(missing_ok=True)


def main() -> int:
    os.umask(0o077)
    parser = argparse.ArgumentParser(description="Back up or restore PrinterFleet state")
    subparsers = parser.add_subparsers(dest="command", required=True)
    backup = subparsers.add_parser("backup")
    backup.add_argument("--database", type=Path, required=True)
    backup.add_argument("--output", type=Path, required=True)
    verify = subparsers.add_parser("verify")
    verify.add_argument("--backup", type=Path, required=True)
    verify.add_argument("--manifest", type=Path)
    restore = subparsers.add_parser("restore")
    restore.add_argument("--backup", type=Path, required=True)
    restore.add_argument("--manifest", type=Path)
    restore.add_argument("--target", type=Path, required=True)
    args = parser.parse_args()
    if args.command == "backup":
        print(create_backup(args.database, args.output))
    elif args.command == "verify":
        print(json.dumps(verify_backup(args.backup, args.manifest), sort_keys=True))
    else:
        restore_backup(args.backup, args.target, args.manifest)
        print(args.target)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
