from __future__ import annotations

import pytest

from printer_fleet.domain import TransportReceipt, UnsupportedDriver
from printer_fleet.maintenance import PrinterMaintenanceService
from printer_fleet.transports import TransportRegistry


class RecordingTransport:
    def __init__(self) -> None:
        self.payloads = []

    def send(self, payload, printer):
        self.payloads.append((payload, printer))
        return TransportReceipt(bytes_accepted=len(payload.payload))


@pytest.mark.parametrize(
    ("action", "expected"),
    [
        ("print-configuration", b"~WC\n"),
        ("print-network-configuration", b"~WL\n"),
        ("calibrate-media", b"~JC\n"),
    ],
)
def test_zebra_maintenance_actions_are_fixed_and_explicit(action, expected):
    transport = RecordingTransport()
    service = PrinterMaintenanceService(
        transports=TransportRegistry({"raw_tcp": transport})
    )

    result = service.execute(
        {
            "id": "zebra-1",
            "driver": "zpl",
            "connection": {"protocol": "raw_tcp", "host": "printer.example"},
        },
        action,
    )

    assert transport.payloads[0][0].payload == expected
    assert result["action"] == action
    assert result["moves_media"] is True
    assert result["state"] == "transport_accepted"


def test_arbitrary_or_non_zebra_maintenance_is_rejected_before_transport():
    transport = RecordingTransport()
    service = PrinterMaintenanceService(
        transports=TransportRegistry({"raw_tcp": transport})
    )
    printer = {
        "id": "zebra-1",
        "driver": "zpl",
        "connection": {"protocol": "raw_tcp", "host": "printer.example"},
    }

    with pytest.raises(ValueError, match="Unsupported Zebra maintenance action"):
        service.execute(printer, "~JUN")
    with pytest.raises(UnsupportedDriver):
        service.execute({**printer, "driver": "niimbot-b1"}, "calibrate-media")
    assert transport.payloads == []
