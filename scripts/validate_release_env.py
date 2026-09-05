from __future__ import annotations

import argparse
import json
from pathlib import Path
import re


IMAGE_KEYS = (
    "PRINTER_FLEET_IMAGE",
    "PRINTER_FLEET_CONSOLE_IMAGE",
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
)
SECRET_FILE_KEYS = (
    "PRINTER_FLEET_POSTGRES_PASSWORD_SOURCE",
    "PRINTER_FLEET_DATABASE_URL_SOURCE",
    "PRINTER_FLEET_CREDENTIALS_SOURCE",
    "PRINTHUB_FLEET_TOKEN_SOURCE",
)
IMMUTABLE_IMAGE = re.compile(r"^\S+@sha256:([0-9a-f]{64})$")
SHA256 = re.compile(r"[0-9a-f]{64}")


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
    for key in SECRET_FILE_KEYS:
        value = values.get(key, "")
        if not value or "example" in Path(value).name.lower():
            errors.append(f"{key} must reference a non-example secret file")
    return errors


def validate_fleet_credentials(values: dict[str, str], *, base_directory: Path) -> list[str]:
    credentials_path = Path(values.get("PRINTER_FLEET_CREDENTIALS_SOURCE", ""))
    token_path = Path(values.get("PRINTHUB_FLEET_TOKEN_SOURCE", ""))
    if not credentials_path.is_absolute():
        credentials_path = base_directory / credentials_path
    if not token_path.is_absolute():
        token_path = base_directory / token_path
    document = json.loads(credentials_path.read_text(encoding="utf-8"))
    token = token_path.read_text(encoding="utf-8").strip()
    if len(token) < 16 or "replace" in token.lower() or any(char.isspace() for char in token):
        return ["PrintHub Fleet token file must contain one non-example token"]
    credentials = document.get("credentials") if isinstance(document, dict) else None
    if not isinstance(credentials, list):
        return ["Fleet credentials file must contain a credentials list"]
    matching = [item for item in credentials if isinstance(item, dict) and item.get("token") == token]
    if len(matching) != 1:
        return ["PrintHub Fleet token must match exactly one Fleet credential"]
    principal = matching[0]
    roles = set(principal.get("roles") or [])
    sites = principal.get("sites")
    errors: list[str] = []
    if not {"observer", "submitter"} <= roles or "admin" in roles:
        errors.append("PrintHub Fleet credential must have observer and submitter but not admin")
    if not isinstance(sites, list) or not sites or "*" in sites:
        errors.append("PrintHub Fleet credential must declare explicit non-global sites")
    return errors


def validate_manifest(values: dict[str, str], document: object) -> list[str]:
    errors: list[str] = []
    if not isinstance(document, dict):
        return ["Compatibility manifest must be a JSON object"]
    if document.get("schemaVersion") != 2:
        errors.append("Compatibility manifest schemaVersion must be 2")
        return errors
    acceptance = document.get("hardwareAcceptance")
    if not isinstance(acceptance, dict):
        errors.append("Compatibility manifest hardwareAcceptance must be an object")
    else:
        if acceptance.get("schemaVersion") != 1:
            errors.append("Hardware acceptance reference schemaVersion must be 1")
        if acceptance.get("file") != "hardware-acceptance.json":
            errors.append("Hardware acceptance reference must use hardware-acceptance.json")
        digest = acceptance.get("sha256")
        if not isinstance(digest, str) or not SHA256.fullmatch(digest) or digest == "0" * 64:
            errors.append("Hardware acceptance reference requires a real SHA-256 digest")
        transports = acceptance.get("supportedTransports")
        if not isinstance(transports, list) or not transports:
            errors.append("Hardware acceptance must advertise at least one passing transport")
    components = document.get("components")
    if not isinstance(components, dict):
        return ["Compatibility manifest components must be an object"]
    names = {
        "PRINTER_FLEET_IMAGE": "printerFleet",
        "PRINTER_FLEET_CONSOLE_IMAGE": "fleetConsole",
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
        if not any(key in error for error in errors for key in SECRET_FILE_KEYS):
            errors.extend(
                validate_fleet_credentials(values, base_directory=args.env_file.parent)
            )
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
