from __future__ import annotations

from typing import Any, Collection, Mapping, Protocol

from .domain import DeliveryState, DevicePayload, PrintArtifact, TransportReceipt


class DeviceDriver(Protocol):
    def encode(self, artifact: PrintArtifact, printer: Mapping[str, Any]) -> DevicePayload: ...


class DeviceTransport(Protocol):
    def send(self, payload: DevicePayload, printer: Mapping[str, Any]) -> TransportReceipt: ...


class DeliveryRepository(Protocol):
    """Persistence boundary required by delivery orchestration."""

    def get_printer(self, printer_id: str) -> dict[str, Any]: ...

    def create_delivery(
        self,
        *,
        idempotency_key: str,
        request_hash: str,
        printer_id: str,
        printer_snapshot: Mapping[str, Any],
        route_snapshot: Mapping[str, Any],
        artifact_checksum: str,
        artifact_mime_type: str,
        artifact_payload: bytes,
        artifact_description: str,
        max_attempts: int,
        accepted_at: str | None = None,
    ) -> tuple[dict[str, Any], bool]: ...

    def get_delivery(self, delivery_id: str) -> dict[str, Any]: ...

    def claim_delivery(self, delivery_id: str, *, now: str) -> dict[str, Any] | None: ...

    def transition(
        self,
        delivery_id: str,
        state: DeliveryState,
        *,
        bytes_accepted: int = 0,
        detail: str | None = None,
        next_attempt_at: str | None = None,
        downstream_job_id: str | None = None,
        downstream_state: str | None = None,
    ) -> dict[str, Any]: ...

    def list_due_delivery_ids(self, *, now: str, limit: int = 20) -> list[str]: ...

    def release_printer_operation(self, printer_id: str, owner: str) -> None: ...


class AgentRepository(Protocol):
    """Persistence boundary required by PrintAgent discovery and enrollment."""

    def list_agents(self) -> list[dict[str, Any]]: ...

    def mark_agent_unavailable(self, base_url: str, error: str) -> None: ...

    def record_agent(self, payload: Mapping[str, Any]) -> dict[str, Any]: ...

    def get_agent(self, agent_id: str) -> dict[str, Any]: ...

    def get_agent_device(
        self, agent_id: str, device_id: str
    ) -> tuple[dict[str, Any], dict[str, Any]]: ...

    def get_printer(self, printer_id: str) -> dict[str, Any]: ...

    def put_printer(self, printer: Mapping[str, Any]) -> dict[str, Any]: ...

    def record_printer_observation(
        self,
        printer_id: str,
        *,
        media: Mapping[str, Any],
        alignment: Mapping[str, Any],
        capabilities: Mapping[str, Any],
        source: str,
    ) -> dict[str, Any]: ...


class FleetRepositoryPort(DeliveryRepository, AgentRepository, Protocol):
    """Complete persistence contract used by the Fleet composition root."""

    def initialize(self) -> None: ...

    def recover_interrupted_deliveries(self) -> int: ...

    def list_printers(self) -> list[dict[str, Any]]: ...

    def export_printers(self) -> dict[str, Any]: ...

    def import_printers(self, document: Mapping[str, Any]) -> None: ...

    def patch_printer(
        self, printer_id: str, settings: Mapping[str, Any], expected_revision: int
    ) -> dict[str, Any]: ...

    def set_printer_paused(
        self, printer_id: str, *, paused: bool, reason: str | None = None
    ) -> dict[str, Any]: ...

    def acquire_printer_operation(
        self, printer_id: str, *, kind: str, lease_seconds: float = 300
    ) -> str | None: ...

    def list_deliveries(
        self,
        *,
        printer_id: str | None = None,
        printer_ids: Collection[str] | None = None,
        state: str | None = None,
        limit: int = 100,
    ) -> list[dict[str, Any]]: ...

    def append_audit_record(
        self,
        *,
        correlation_id: str,
        actor: str,
        method: str,
        path: str,
        status_code: int,
    ) -> None: ...

    def list_audit_records(self, *, limit: int = 100) -> list[dict[str, Any]]: ...

    def metrics_snapshot(self) -> dict[str, Any]: ...
