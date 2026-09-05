from __future__ import annotations

from collections.abc import Mapping
import re
from typing import Any
from urllib.parse import urlsplit


_IDENTIFIER = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,119}")
_DRIVER = re.compile(r"[a-z][a-z0-9_]{0,63}")
_TCP_PROTOCOLS = {"raw_tcp", "raw9100", "serial_over_tcp"}
_AGENT_PROTOCOLS = {"print_agent", "zebra_tamer"}


def _integer(value: object, *, field: str, minimum: int, maximum: int) -> int:
    if isinstance(value, bool):
        raise ValueError(f"{field} must be an integer")
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        raise ValueError(f"{field} must be an integer") from None
    if parsed < minimum or parsed > maximum:
        raise ValueError(f"{field} must be between {minimum} and {maximum}")
    return parsed


def _host(value: object) -> str:
    host = str(value or "").strip()
    if (
        not host
        or len(host) > 253
        or "://" in host
        or any(character.isspace() or character in "/\\" for character in host)
    ):
        raise ValueError("connection.host must be an IP address or hostname")
    return host


def _agent_url(value: object) -> str:
    url = str(value or "").strip().rstrip("/")
    parsed = urlsplit(url)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise ValueError("connection.base_url must be an absolute HTTP(S) URL")
    if parsed.username or parsed.password or parsed.query or parsed.fragment:
        raise ValueError("connection.base_url must not contain credentials, query or fragment")
    return url


def normalize_printer(printer: Mapping[str, Any]) -> dict[str, Any]:
    """Validate and normalize a persisted physical-printer configuration."""
    normalized = dict(printer)
    printer_id = str(normalized.get("id") or "").strip()
    if not _IDENTIFIER.fullmatch(printer_id):
        raise ValueError("Printer id must be a portable 1-120 character identifier")
    normalized["id"] = printer_id

    driver = str(normalized.get("driver") or "").strip()
    if not _DRIVER.fullmatch(driver):
        raise ValueError("Printer driver must be a lowercase identifier")
    normalized["driver"] = driver
    if "enabled" in normalized and not isinstance(normalized["enabled"], bool):
        raise ValueError("Printer enabled must be a boolean")

    connection_value = normalized.get("connection")
    if not isinstance(connection_value, Mapping):
        raise ValueError("Printer connection must be an object")
    connection = dict(connection_value)
    protocol = str(connection.get("protocol") or "").strip()
    if protocol not in _TCP_PROTOCOLS | _AGENT_PROTOCOLS:
        raise ValueError(f"Unsupported printer connection protocol: {protocol or '<empty>'}")
    connection["protocol"] = protocol
    connection["timeout_ms"] = _integer(
        connection.get("timeout_ms", 5000),
        field="connection.timeout_ms",
        minimum=100,
        maximum=120000,
    )

    if protocol in _TCP_PROTOCOLS:
        connection["host"] = _host(connection.get("host"))
        if protocol == "serial_over_tcp" and "port" not in connection:
            raise ValueError("serial_over_tcp requires an explicit connection.port")
        connection["port"] = _integer(
            connection.get("port", 9100),
            field="connection.port",
            minimum=1,
            maximum=65535,
        )
    else:
        connection["base_url"] = _agent_url(connection.get("base_url"))
        for field in ("agent_id", "printer_id"):
            value = str(connection.get(field) or "").strip()
            if not value:
                raise ValueError(f"connection.{field} is required for {protocol}")
            connection[field] = value

    normalized["connection"] = connection
    return normalized
