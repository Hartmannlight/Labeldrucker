from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
import sys
from typing import Any, Mapping


SCHEMA_VERSION = 1
TRANSPORTS = {"raw_tcp", "serial_over_tcp", "print_agent"}
SCENARIOS = {
    "public_catalog_boundary",
    "maintenance_serialization",
    "queue_isolation",
    "disconnect_ambiguity",
    "media_change",
    "cups_browser",
    "color_dither",
    "a4_hold_fit",
}
OUTCOMES = {"pass", "fail", "not_tested"}
REVISION = re.compile(r"[0-9a-f]{40}")
RELEASE = re.compile(r"v\d+\.\d+\.\d+")
SENSITIVE_KEY_PARTS = ("token", "password", "secret", "credential", "private_key")


def _mapping(value: Any, path: str, errors: list[str]) -> Mapping[str, Any]:
    if not isinstance(value, dict):
        errors.append(f"{path} must be an object")
        return {}
    return value


def _reject_unknown_keys(
    value: Mapping[str, Any], allowed: set[str], path: str, errors: list[str]
) -> None:
    unknown = set(value) - allowed
    if unknown:
        errors.append(f"{path} contains unsupported fields: {', '.join(sorted(unknown))}")


def _required_text(value: Any, path: str, errors: list[str], *, maximum: int = 200) -> str:
    if not isinstance(value, str) or not value.strip():
        errors.append(f"{path} must be non-empty text")
        return ""
    text = value.strip()
    if len(text) > maximum:
        errors.append(f"{path} must not exceed {maximum} characters")
    return text


def _utc_timestamp(value: Any, path: str, errors: list[str]) -> str:
    text = _required_text(value, path, errors)
    if not text:
        return ""
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        errors.append(f"{path} must be an ISO-8601 timestamp")
        return text
    if parsed.tzinfo is None or parsed.utcoffset() != timezone.utc.utcoffset(parsed):
        errors.append(f"{path} must be in UTC")
    return text


def _reject_sensitive_keys(value: Any, path: str, errors: list[str]) -> None:
    if isinstance(value, dict):
        for key, child in value.items():
            normalized = str(key).lower().replace("-", "_")
            if any(part in normalized for part in SENSITIVE_KEY_PARTS):
                errors.append(f"{path}.{key} is not permitted in sanitized evidence")
            _reject_sensitive_keys(child, f"{path}.{key}", errors)
    elif isinstance(value, list):
        for index, child in enumerate(value):
            _reject_sensitive_keys(child, f"{path}[{index}]", errors)


def _string_list(value: Any, path: str, errors: list[str], *, https: bool = False) -> None:
    if not isinstance(value, list) or not value:
        errors.append(f"{path} must be a non-empty list")
        return
    if len(value) > 50:
        errors.append(f"{path} must not contain more than 50 entries")
    for index, item in enumerate(value):
        text = _required_text(item, f"{path}[{index}]", errors, maximum=500)
        if https and text and not text.startswith("https://"):
            errors.append(f"{path}[{index}] must be an HTTPS URL")


def validation_errors(
    document: Any,
    *,
    expected_release: str | None = None,
    expected_platform_revision: str | None = None,
) -> list[str]:
    errors: list[str] = []
    root = _mapping(document, "acceptance", errors)
    _reject_unknown_keys(
        root,
        {
            "schemaVersion",
            "release",
            "platformRevision",
            "testedAt",
            "reviewedAt",
            "tester",
            "reviewer",
            "scenarios",
            "transports",
            "deviations",
            "issues",
        },
        "acceptance",
        errors,
    )
    _reject_sensitive_keys(root, "acceptance", errors)
    if root.get("schemaVersion") != SCHEMA_VERSION:
        errors.append(f"schemaVersion must be {SCHEMA_VERSION}")

    release = _required_text(root.get("release"), "release", errors)
    if release and not RELEASE.fullmatch(release):
        errors.append("release must be an exact vMAJOR.MINOR.PATCH")
    if expected_release is not None and release != expected_release:
        errors.append("release does not match the requested compatibility release")

    revision = _required_text(root.get("platformRevision"), "platformRevision", errors)
    if revision and not REVISION.fullmatch(revision):
        errors.append("platformRevision must be a lowercase 40-character Git revision")
    if expected_platform_revision is not None and revision != expected_platform_revision:
        errors.append("platformRevision does not match the tested platform candidate")

    tested_at = _utc_timestamp(root.get("testedAt"), "testedAt", errors)
    reviewed_at = _utc_timestamp(root.get("reviewedAt"), "reviewedAt", errors)
    tester = _mapping(root.get("tester"), "tester", errors)
    reviewer = _mapping(root.get("reviewer"), "reviewer", errors)
    _reject_unknown_keys(tester, {"name", "site"}, "tester", errors)
    _reject_unknown_keys(reviewer, {"name"}, "reviewer", errors)
    tester_name = _required_text(tester.get("name"), "tester.name", errors)
    _required_text(tester.get("site"), "tester.site", errors)
    reviewer_name = _required_text(reviewer.get("name"), "reviewer.name", errors)
    if tester_name and reviewer_name and tester_name == reviewer_name:
        errors.append("tester and reviewer must be different people")
    if tested_at and reviewed_at:
        try:
            if datetime.fromisoformat(reviewed_at.replace("Z", "+00:00")) < datetime.fromisoformat(
                tested_at.replace("Z", "+00:00")
            ):
                errors.append("reviewedAt must not be earlier than testedAt")
        except ValueError:
            pass
    if "deviations" in root:
        _string_list(root["deviations"], "deviations", errors)
    if "issues" in root:
        _string_list(root["issues"], "issues", errors, https=True)

    scenarios = _mapping(root.get("scenarios"), "scenarios", errors)
    missing_scenarios = SCENARIOS - set(scenarios)
    if missing_scenarios:
        errors.append(f"scenarios missing: {', '.join(sorted(missing_scenarios))}")
    for name, outcome in scenarios.items():
        if name not in SCENARIOS:
            errors.append(f"unsupported scenario: {name}")
        if outcome not in OUTCOMES:
            errors.append(f"scenarios.{name} has an unsupported outcome")
        elif outcome != "pass":
            errors.append(f"scenarios.{name} must pass before stable release")

    transports = _mapping(root.get("transports"), "transports", errors)
    unknown_transports = set(transports) - TRANSPORTS
    if unknown_transports:
        errors.append(f"unsupported transports: {', '.join(sorted(unknown_transports))}")
    advertised: list[str] = []
    for name, raw_record in transports.items():
        record = _mapping(raw_record, f"transports.{name}", errors)
        _reject_unknown_keys(
            record,
            {
                "advertised",
                "outcome",
                "reason",
                "printer",
                "media",
                "connectionSummary",
                "reportedState",
                "auditCorrelationIds",
                "printHubJobIds",
                "fleetDeliveryIds",
                "evidence",
            },
            f"transports.{name}",
            errors,
        )
        is_advertised = record.get("advertised")
        if not isinstance(is_advertised, bool):
            errors.append(f"transports.{name}.advertised must be boolean")
            is_advertised = False
        outcome = record.get("outcome")
        if outcome not in OUTCOMES:
            errors.append(f"transports.{name}.outcome has an unsupported value")
        if is_advertised:
            advertised.append(name)
            if outcome != "pass":
                errors.append(f"advertised transport {name} must pass")
            printer = _mapping(record.get("printer"), f"transports.{name}.printer", errors)
            _reject_unknown_keys(
                printer,
                {"manufacturer", "model", "firmware", "serialSuffix"},
                f"transports.{name}.printer",
                errors,
            )
            for field in ("manufacturer", "model", "firmware", "serialSuffix"):
                maximum = 12 if field == "serialSuffix" else 100
                _required_text(
                    printer.get(field), f"transports.{name}.printer.{field}", errors, maximum=maximum
                )
            media = _mapping(record.get("media"), f"transports.{name}.media", errors)
            _reject_unknown_keys(
                media,
                {"widthMm", "heightMm", "tracking", "color", "technology", "dpi"},
                f"transports.{name}.media",
                errors,
            )
            for field in ("tracking", "color", "technology"):
                _required_text(media.get(field), f"transports.{name}.media.{field}", errors)
            for field in ("widthMm", "heightMm", "dpi"):
                value = media.get(field)
                if isinstance(value, bool) or not isinstance(value, (int, float)) or value <= 0:
                    errors.append(f"transports.{name}.media.{field} must be positive")
            _required_text(
                record.get("connectionSummary"),
                f"transports.{name}.connectionSummary",
                errors,
            )
            if record.get("reportedState") != "transport_accepted":
                errors.append(
                    f"transports.{name}.reportedState must preserve honest transport_accepted semantics"
                )
            for field in ("auditCorrelationIds", "printHubJobIds", "fleetDeliveryIds"):
                _string_list(record.get(field), f"transports.{name}.{field}", errors)
            _string_list(record.get("evidence"), f"transports.{name}.evidence", errors, https=True)
        elif outcome == "pass":
            errors.append(f"transport {name} cannot pass while not advertised")
        elif outcome in {"fail", "not_tested"}:
            _required_text(record.get("reason"), f"transports.{name}.reason", errors)
    if not advertised:
        errors.append("at least one transport must be advertised and pass")
    return errors


def load_and_validate(
    path: Path,
    *,
    expected_release: str,
    expected_platform_revision: str,
) -> tuple[dict[str, Any], bytes]:
    encoded = path.read_bytes()
    document = json.loads(encoded)
    errors = validation_errors(
        document,
        expected_release=expected_release,
        expected_platform_revision=expected_platform_revision,
    )
    if errors:
        raise ValueError("Hardware acceptance failed:\n- " + "\n- ".join(errors))
    return document, encoded


def acceptance_reference(document: Mapping[str, Any], encoded: bytes) -> dict[str, Any]:
    supported = sorted(
        name
        for name, record in document["transports"].items()
        if record.get("advertised") is True
    )
    return {
        "schemaVersion": SCHEMA_VERSION,
        "file": "hardware-acceptance.json",
        "sha256": hashlib.sha256(encoded).hexdigest(),
        "supportedTransports": supported,
        "testedAt": document["testedAt"],
        "reviewedAt": document["reviewedAt"],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate sanitized real-printer acceptance")
    parser.add_argument("path", type=Path)
    parser.add_argument("--release", required=True)
    parser.add_argument("--platform-revision", required=True)
    args = parser.parse_args()
    try:
        document, encoded = load_and_validate(
            args.path,
            expected_release=args.release,
            expected_platform_revision=args.platform_revision,
        )
    except (OSError, json.JSONDecodeError, ValueError) as exc:
        print(str(exc), file=sys.stderr)
        return 1
    reference = acceptance_reference(document, encoded)
    print("Hardware acceptance passed for " + ", ".join(reference["supportedTransports"]))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
