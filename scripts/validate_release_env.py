from __future__ import annotations

import argparse
import json
from pathlib import Path
import re


IMAGE_KEYS = (
    "PRINTER_FLEET_IMAGE",
    "PRINTHUB_IMAGE",
    "PRINTHUB_IPP_IMAGE",
    "PRINTHUB_STUDIO_IMAGE",
    "THINGDEX_IMAGE",
    "POSTGRES_IMAGE",
)
SECRET_KEYS = (
    "POSTGRES_PASSWORD",
    "THINGDEX_DATABASE_URL",
    "THINGDEX_PRINT_ADMIN_TOKEN",
    "THINGDEX_PRINTHUB_EVENT_SECRET",
    "PRINTHUB_API_TOKEN",
    "PRINTER_FLEET_API_TOKEN",
)
IMMUTABLE_IMAGE = re.compile(r"^\S+@sha256:([0-9a-f]{64})$")


def read_env(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    for line_number, raw in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if "=" not in line:
            raise ValueError(f"{path}:{line_number}: expected KEY=VALUE")
        key, value = line.split("=", 1)
        values[key.strip()] = value.strip()
    return values


def validate(values: dict[str, str]) -> list[str]:
    errors: list[str] = []
    for key in IMAGE_KEYS:
        value = values.get(key, "")
        match = IMMUTABLE_IMAGE.fullmatch(value)
        if not match:
            errors.append(f"{key} must be an image reference pinned with @sha256:<64 hex>")
        elif match.group(1) == "0" * 64:
            errors.append(f"{key} still contains the example digest")
    for key in SECRET_KEYS:
        value = values.get(key, "")
        if not value or value == "replace-me":
            errors.append(f"{key} must be injected with a non-example secret")
    return errors


def validate_manifest(values: dict[str, str], document: object) -> list[str]:
    errors: list[str] = []
    if not isinstance(document, dict):
        return ["Compatibility manifest must be a JSON object"]
    if document.get("schemaVersion") != 1:
        errors.append("Compatibility manifest schemaVersion must be 1")
        return errors
    components = document.get("components")
    if not isinstance(components, dict):
        return ["Compatibility manifest components must be an object"]
    names = {
        "PRINTER_FLEET_IMAGE": "printerFleet",
        "PRINTHUB_IMAGE": "printHub",
        "PRINTHUB_IPP_IMAGE": "ippGateway",
        "PRINTHUB_STUDIO_IMAGE": "studio",
        "THINGDEX_IMAGE": "thingdex",
        "POSTGRES_IMAGE": "postgres",
    }
    for key, name in names.items():
        component = components.get(name)
        manifest_image = component.get("image") if isinstance(component, dict) else None
        if manifest_image != values.get(key):
            errors.append(f"{key} does not match compatibility manifest component {name}")
    return errors


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate an immutable production release environment")
    parser.add_argument("env_file", type=Path)
    parser.add_argument("--manifest", type=Path)
    args = parser.parse_args()
    try:
        values = read_env(args.env_file)
        errors = validate(values)
        if args.manifest:
            document = json.loads(args.manifest.read_text(encoding="utf-8"))
            errors.extend(validate_manifest(values, document))
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(exc)
        return 2
    if errors:
        for error in errors:
            print(f"ERROR: {error}")
        return 1
    print("Release environment uses immutable images and non-example secrets")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
