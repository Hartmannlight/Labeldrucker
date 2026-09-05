from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping, Protocol

from .domain import DevicePayload, UnsupportedDriver
from .ports import DeviceTransport
from .transports import TransportRegistry


@dataclass(frozen=True)
class MaintenanceCommand:
    payload: bytes
    description: str
    moves_media: bool


class MaintenanceProvider(Protocol):
    def build(self, action: str) -> MaintenanceCommand: ...


class ZplMaintenanceProvider:
    _COMMANDS = {
        "print-configuration": MaintenanceCommand(
            b"~WC\n",
            "Print Zebra configuration label",
            True,
        ),
        "print-network-configuration": MaintenanceCommand(
            b"~WL\n",
            "Print Zebra network configuration label",
            True,
        ),
        "calibrate-media": MaintenanceCommand(
            b"~JC\n",
            "Calibrate Zebra media and ribbon sensors",
            True,
        ),
    }

    def build(self, action: str) -> MaintenanceCommand:
        try:
            return self._COMMANDS[action]
        except KeyError:
            raise ValueError(f"Unsupported Zebra maintenance action: {action}") from None


class MaintenanceProviderRegistry:
    def __init__(self, providers: Mapping[str, MaintenanceProvider] | None = None) -> None:
        self._providers = dict(providers or {"zpl": ZplMaintenanceProvider()})

    def get(self, driver: str) -> MaintenanceProvider:
        try:
            return self._providers[driver]
        except KeyError:
            raise UnsupportedDriver(
                f"Printer driver does not support maintenance actions: {driver}"
            ) from None


class PrinterMaintenanceService:
    def __init__(
        self,
        *,
        providers: MaintenanceProviderRegistry | None = None,
        transports: TransportRegistry | None = None,
    ) -> None:
        self.providers = providers or MaintenanceProviderRegistry()
        self.transports = transports or TransportRegistry()

    def execute(self, printer: Mapping[str, Any], action: str) -> dict[str, Any]:
        if not printer.get("enabled", True):
            raise ValueError("Printer is disabled")
        command = self.providers.get(str(printer.get("driver") or "")).build(action)
        connection = printer.get("connection") or {}
        protocol = str(connection.get("protocol") or "")
        if protocol not in {"raw_tcp", "serial_over_tcp"}:
            raise ValueError(
                f"Maintenance action is unsupported for transport: {protocol}"
            )
        transport: DeviceTransport = self.transports.get(protocol)
        receipt = transport.send(
            DevicePayload(
                content_type="application/vnd.zebra-zpl",
                payload=command.payload,
                description=command.description,
            ),
            printer,
        )
        return {
            "printer_id": printer["id"],
            "action": action,
            "description": command.description,
            "moves_media": command.moves_media,
            "state": receipt.state.value,
            "bytes_accepted": receipt.bytes_accepted,
        }
