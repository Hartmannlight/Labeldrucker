from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
import hashlib
import json
from datetime import datetime, timedelta, timezone
from typing import Any, Callable

from .domain import DeliveryState, FleetError, PrintArtifact
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
        retry_delay_seconds: float = 2.0,
        max_parallel_printers: int = 4,
        now: Callable[[], datetime] | None = None,
    ) -> None:
        self.repository = repository
        self.drivers = drivers or DriverRegistry()
        self.transports = transports or TransportRegistry()
        self.retry_delay_seconds = retry_delay_seconds
        if not 1 <= max_parallel_printers <= 64:
            raise ValueError("max_parallel_printers must be between 1 and 64")
        self.max_parallel_printers = max_parallel_printers
        self._now = now or (lambda: datetime.now(timezone.utc))

    def deliver(
        self,
        *,
        printer_id: str,
        idempotency_key: str,
        artifact: PrintArtifact,
        declared_checksum: str,
        max_attempts: int = 3,
    ) -> dict[str, Any]:
        if declared_checksum != artifact.checksum:
            raise ValueError("Artifact checksum does not match payload")
        if not 1 <= max_attempts <= 10:
            raise ValueError("max_attempts must be between 1 and 10")
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
            route_snapshot=printer,
            artifact_checksum=artifact.checksum,
            artifact_mime_type=artifact.mime_type,
            artifact_payload=artifact.payload,
            artifact_description=artifact.description,
            max_attempts=max_attempts,
            accepted_at=self._now().isoformat(),
        )
        if not created:
            return delivery

        return self.process_delivery(str(delivery["id"]))

    def process_delivery(self, delivery_id: str) -> dict[str, Any]:
        now = self._now()
        claimed = self.repository.claim_delivery(delivery_id, now=now.isoformat())
        if claimed is None:
            return self.repository.get_delivery(delivery_id)

        printer = claimed["_route_snapshot"]
        artifact = PrintArtifact(
            mime_type=str(claimed["artifact_mime_type"]),
            payload=claimed["_artifact_payload"],
            description=str(claimed["artifact_description"]),
            idempotency_key=str(claimed["idempotency_key"]),
        )
        try:
            driver = self.drivers.get(str(printer["driver"]))
            device_payload = driver.encode(artifact, printer)
            self.repository.transition(delivery_id, DeliveryState.TRANSMITTING)
            protocol = str((printer.get("connection") or {})["protocol"])
            receipt = self.transports.get(protocol).send(device_payload, printer)
            return self.repository.transition(
                delivery_id,
                receipt.state,
                bytes_accepted=receipt.bytes_accepted,
                downstream_job_id=receipt.downstream_job_id,
                downstream_state=receipt.downstream_state,
            )
        except (ValueError, FleetError) as exc:
            return self.repository.transition(
                delivery_id, DeliveryState.FAILED, detail=str(exc)
            )
        except (OSError, RuntimeError) as exc:
            attempt = int(claimed["attempt_count"])
            maximum = int(claimed["max_attempts"])
            if attempt >= maximum:
                return self.repository.transition(
                    delivery_id, DeliveryState.FAILED, detail=str(exc)
                )
            delay = self.retry_delay_seconds * (2 ** (attempt - 1))
            retry_at = now + timedelta(seconds=delay)
            return self.repository.transition(
                delivery_id,
                DeliveryState.RETRY_SCHEDULED,
                detail=str(exc),
                next_attempt_at=retry_at.isoformat(),
            )
        except Exception as exc:
            return self.repository.transition(
                delivery_id, DeliveryState.FAILED, detail=f"Unexpected delivery error: {exc}"
            )
        finally:
            self.repository.release_printer_operation(
                str(claimed["printer_id"]),
                str(claimed["_operation_owner"]),
            )

    def process_due(self, *, limit: int = 20) -> list[dict[str, Any]]:
        now = self._now().isoformat()
        delivery_ids = self.repository.list_due_delivery_ids(now=now, limit=limit)
        if len(delivery_ids) < 2 or self.max_parallel_printers == 1:
            return [self.process_delivery(delivery_id) for delivery_id in delivery_ids]
        with ThreadPoolExecutor(
            max_workers=min(self.max_parallel_printers, len(delivery_ids)),
            thread_name_prefix="printer-fleet-device",
        ) as executor:
            return list(executor.map(self.process_delivery, delivery_ids))
