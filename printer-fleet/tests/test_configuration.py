from __future__ import annotations

import pytest

from printer_fleet.configuration import normalize_printer


def test_raw_tcp_defaults_are_normalized_at_registry_boundary() -> None:
    printer = normalize_printer(
        {
            "id": "shipping-zebra",
            "driver": "zpl",
            "connection": {"protocol": "raw_tcp", "host": "192.0.2.10"},
        }
    )

    assert printer["connection"] == {
        "protocol": "raw_tcp",
        "host": "192.0.2.10",
        "port": 9100,
        "timeout_ms": 5000,
    }
    assert printer["site_id"] == "default"


def test_serial_bridge_requires_its_actual_tcp_port() -> None:
    with pytest.raises(ValueError, match="explicit connection.port"):
        normalize_printer(
            {
                "id": "legacy-zebra",
                "driver": "zpl",
                "connection": {
                    "protocol": "serial_over_tcp",
                    "host": "serial-bridge.example",
                },
            }
        )


@pytest.mark.parametrize(
    ("connection", "message"),
    [
        ({"protocol": "raw_tcp", "host": "http://printer"}, "IP address or hostname"),
        ({"protocol": "raw_tcp", "host": "printer", "port": 70000}, "between 1 and 65535"),
        ({"protocol": "shell", "host": "printer"}, "Unsupported"),
        ({"protocol": "raw9100", "host": "printer"}, "Unsupported"),
        (
            {
                "protocol": "zebra_tamer",
                "base_url": "http://edge:8080",
                "agent_id": "edge-1",
                "printer_id": "usb-zebra",
            },
            "Unsupported",
        ),
        (
            {
                "protocol": "print_agent",
                "base_url": "http://user:secret@edge:8080",
                "agent_id": "edge-1",
                "printer_id": "usb-zebra",
            },
            "must not contain credentials",
        ),
    ],
)
def test_unsafe_or_ambiguous_endpoints_are_rejected(connection, message) -> None:
    with pytest.raises(ValueError, match=message):
        normalize_printer(
            {
                "id": "test-printer",
                "driver": "zpl",
                "connection": connection,
            }
        )


def test_agent_identity_is_required() -> None:
    with pytest.raises(ValueError, match="connection.agent_id"):
        normalize_printer(
            {
                "id": "usb-zebra",
                "driver": "zpl",
                "connection": {
                    "protocol": "print_agent",
                    "base_url": "https://edge.example",
                    "printer_id": "local-zebra",
                },
            }
        )
