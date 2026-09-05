from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
import hashlib


class DeliveryState(str, Enum):
    QUEUED = "queued"
    CONNECTING = "connecting"
    TRANSMITTING = "transmitting"
    TRANSPORT_ACCEPTED = "transport_accepted"
    CONFIRMED = "confirmed"
    UNCONFIRMED = "unconfirmed"
    FAILED = "failed"
    RETRY_SCHEDULED = "retry_scheduled"


@dataclass(frozen=True)
class PrintArtifact:
    mime_type: str
    payload: bytes
    description: str = "PrintHub job"
    idempotency_key: str | None = None

    @property
    def checksum(self) -> str:
        return f"sha256:{hashlib.sha256(self.payload).hexdigest()}"


@dataclass(frozen=True)
class DevicePayload:
    content_type: str
    payload: bytes
    description: str = "PrinterFleet delivery"
    idempotency_key: str | None = None


@dataclass(frozen=True)
class TransportReceipt:
    bytes_accepted: int
    state: DeliveryState = DeliveryState.TRANSPORT_ACCEPTED
    downstream_job_id: str | None = None
    downstream_state: str | None = None


class FleetError(RuntimeError):
    pass


class DeliveryConflict(FleetError):
    pass


class RegistryConflict(FleetError):
    pass


class UnsupportedDriver(FleetError):
    pass


class UnsupportedTransport(FleetError):
    pass
