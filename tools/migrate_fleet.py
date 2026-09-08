#!/usr/bin/env python3
"""Offline, dry-run-first migration from PrinterFleet data."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sqlite3
import tempfile
from typing import Any


OPEN_STATES = {"receiving", "queued", "connecting", "transmitting", "retry_scheduled", "unconfirmed", "outcome_unknown"}


def read_sqlite(path: Path) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    uri = f"{path.resolve().as_uri()}?mode=ro"
    with sqlite3.connect(uri, uri=True) as database:
        database.row_factory = sqlite3.Row
        tables = {row[0] for row in database.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        if "printers" not in tables:
            raise ValueError("Fleet database has no printers table")
        columns = {row[1] for row in database.execute("PRAGMA table_info(printers)")}
        payload_column = "payload_json" if "payload_json" in columns else "config" if "config" in columns else None
        if payload_column is None:
            raise ValueError("Unsupported Fleet printers table")
        printers = [json.loads(row[0]) for row in database.execute(f"SELECT {payload_column} FROM printers ORDER BY rowid")]
        deliveries = [dict(row) for row in database.execute("SELECT * FROM deliveries ORDER BY created_at, id")] if "deliveries" in tables else []
    return printers, deliveries


def read_document(path: Path) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    if path.suffix.lower() in {".sqlite", ".sqlite3", ".db"}:
        return read_sqlite(path)
    if path.suffix.lower() == ".json":
        document = json.loads(path.read_text(encoding="utf-8"))
    else:
        try:
            import yaml
        except ImportError as exc:
            raise ValueError("PyYAML is required for YAML; a Fleet JSON export also works") from exc
        document = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    if not isinstance(document, dict) or not isinstance(document.get("printers"), list):
        raise ValueError("Printer export must contain a printers list")
    deliveries = document.get("deliveries", [])
    if not isinstance(deliveries, list):
        raise ValueError("Printer export deliveries must be a list")
    return (
        [dict(item) for item in document["printers"]],
        [dict(item) for item in deliveries],
    )


def zebra_config(printer: dict[str, Any]) -> dict[str, Any] | None:
    connection = printer.get("connection") or {}
    if str(connection.get("protocol") or "").lower() not in {"raw_tcp", "raw9100"}:
        return None
    alignment = printer.get("alignment") or {}
    capabilities = printer.get("capabilities") or {}
    return {
        "id": str(printer["id"]), "display_name": str(printer.get("name") or printer["id"]),
        "enabled": bool(printer.get("enabled", True)), "device": "", "transport": "tcp",
        "usb_vendor_id": None, "usb_product_id": None, "usb_serial": None,
        "tcp_host": str(connection.get("host") or ""), "tcp_port": int(connection.get("port") or 9100),
        "connect_timeout_ms": int(connection.get("timeout_ms") or 3000), "driver": "zpl", "model_hint": printer.get("model"),
        "device_profile": {"resolution_dpi": alignment.get("dpi"), "max_width_dots": int(capabilities.get("max_width_dots") or 20000), "max_length_dots": int(capabilities.get("max_length_dots") or 20000), "max_speed_ips": int(capabilities.get("max_speed_ips") or 6), "max_offset_dots": int(capabilities.get("max_offset_dots") or 64), "thermal_transfer": bool(capabilities.get("thermal_transfer", False)), "peel_off": bool(capabilities.get("peel_off", False)), "cutter": bool(capabilities.get("supports_cut", False))},
        "first_byte_timeout_ms": 3000, "idle_timeout_ms": 300, "write_timeout_ms": 30000, "max_response_bytes": 1048576,
    }


def migration_plan(printers: list[dict[str, Any]], deliveries: list[dict[str, Any]]) -> dict[str, Any]:
    direct = [item for printer in printers if (item := zebra_config(printer)) is not None]
    remote, conflicts = [], []
    for printer in printers:
        connection = printer.get("connection") or {}; protocol = str(connection.get("protocol") or "").lower()
        if protocol in {"print_agent", "zebra_tamer", "driver_agent"}:
            if not connection.get("agent_id") and not connection.get("base_url"):
                conflicts.append({"printer_id": printer.get("id"), "reason": "agent identity and URL missing"})
            remote.append({"public_printer_id": printer.get("id"), "agent_id": connection.get("agent_id"), "base_url": connection.get("base_url"), "local_printer_id": connection.get("printer_id")})
        elif protocol not in {"raw_tcp", "raw9100"}:
            conflicts.append({"printer_id": printer.get("id"), "reason": f"unsupported connection protocol {protocol!r}"})
    archived, manual = [], []
    for delivery in deliveries:
        record = {key: value for key, value in delivery.items() if key != "artifact_payload"}; record["legacy_source"] = "printer_fleet"; archived.append(record)
        if str(delivery.get("state") or "").lower() in OPEN_STATES:
            manual.append({"delivery_id": delivery.get("id"), "state": delivery.get("state"), "action": "reconcile_manually_never_auto_requeue"})
    return {"format": "printhub-fleet-migration-v1", "summary": {"printers": len(printers), "direct_tcp": len(direct), "remote_agent": len(remote), "deliveries": len(deliveries), "manual_reconciliation": len(manual), "conflicts": len(conflicts)}, "zebratamer_printers": direct, "remote_service_mappings": remote, "manual_reconciliation": manual, "conflicts": conflicts, "legacy_deliveries": archived, "safety": "No printer was contacted and no legacy delivery was enqueued."}


def atomic_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=path.parent, delete=False) as handle:
        json.dump(value, handle, ensure_ascii=False, indent=2, sort_keys=True); handle.write("\n"); temporary = Path(handle.name)
    temporary.replace(path)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__); parser.add_argument("source", type=Path); parser.add_argument("--output-dir", type=Path); parser.add_argument("--apply", action="store_true", help="write artifacts; default is dry-run"); args = parser.parse_args()
    printers, deliveries = read_document(args.source); plan = migration_plan(printers, deliveries)
    if not args.apply:
        print(json.dumps(plan, ensure_ascii=False, indent=2, sort_keys=True)); return
    if args.output_dir is None: raise SystemExit("--apply requires --output-dir")
    if args.output_dir.exists() and any(args.output_dir.iterdir()): raise SystemExit("Refusing to write into a non-empty output directory")
    atomic_json(args.output_dir / "migration-report.json", plan); atomic_json(args.output_dir / "zebratamer-printers.json", plan["zebratamer_printers"]); atomic_json(args.output_dir / "legacy-deliveries.json", plan["legacy_deliveries"])
    print(f"Wrote reviewed migration artifacts to {args.output_dir}")


if __name__ == "__main__": main()
