from __future__ import annotations

import hashlib
import json
from typing import Any

from .domain import DeliveryState, PrintArtifact
from .drivers import DriverRegistry
from .repository import FleetRepository
from .transports import TransportRegistry


class DeliveryService:
    def __init__(
        self,
        repository: FleetRepository,
        *,
        drivers: DriverRegistry | None = None,
        transports: TransportRegistry | None = None,
    ) -> None:
        self.repository = repository
        self.drivers = drivers or DriverRegistry()
        self.transports = transports or TransportRegistry()

    def deliver(
        self,
        *,
        printer_id: str,
        idempotency_key: str,
        artifact: PrintArtifact,
        declared_checksum: str,
    ) -> dict[str, Any]:
        if declared_checksum != artifact.checksum:
            raise ValueError("Artifact checksum does not match payload")
        printer = self.repository.get_printer(printer_id)
        if not printer.get("enabled", True):
            raise ValueError("Printer is disabled")
        request_hash = hashlib.sha256(
            json.dumps(
                {
                    "printer_id": printer_id,
                    "checksum": artifact.checksum,
                    "mime_type": artifact.mime_type,
                    "description": artifact.description,
                },
                sort_keys=True,
            ).encode("utf-8")
        ).hexdigest()
        delivery, created = self.repository.create_delivery(
            idempotency_key=idempotency_key,
            request_hash=request_hash,
            printer_id=printer_id,
            printer_snapshot={
                key: printer[key]
                for key in ("id", "driver", "media", "alignment", "capabilities")
                if key in printer
            },
            artifact_checksum=artifact.checksum,
            artifact_mime_type=artifact.mime_type,
        )
        if not created:
            return delivery

        delivery_id = delivery["id"]
        try:
            self.repository.transition(delivery_id, DeliveryState.CONNECTING)
            driver = self.drivers.get(str(printer["driver"]))
            device_payload = driver.encode(artifact, printer)
            self.repository.transition(delivery_id, DeliveryState.TRANSMITTING)
            protocol = str((printer.get("connection") or {})["protocol"])
            receipt = self.transports.get(protocol).send(device_payload, printer)
            return self.repository.transition(
                delivery_id,
                receipt.state,
                bytes_accepted=receipt.bytes_accepted,
            )
        except Exception as exc:
            self.repository.transition(delivery_id, DeliveryState.FAILED, detail=str(exc))
            raise
