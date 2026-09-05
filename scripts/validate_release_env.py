from __future__ import annotations

import argparse
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


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate an immutable production release environment")
    parser.add_argument("env_file", type=Path)
    args = parser.parse_args()
    try:
        errors = validate(read_env(args.env_file))
    except (OSError, ValueError) as exc:
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
