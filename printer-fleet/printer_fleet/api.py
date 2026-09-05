from __future__ import annotations

import base64
from contextlib import asynccontextmanager
import os
from pathlib import Path
import re
from typing import Any
import uuid

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse, PlainTextResponse
from pydantic import BaseModel, Field
import yaml

from .auth import BearerCredentialAuthenticator, FleetAuthenticator, FleetPrincipal
from .domain import (
    DeliveryConflict,
    DeliveryState,
    FleetError,
    PrinterPaused,
    PrintArtifact,
    RegistryConflict,
)
from .discovery import AgentDiscoveryService
from .maintenance import PrinterMaintenanceService
from .repository import FleetRepository
from .service import DeliveryService
from .worker import AgentDiscoveryWorker, DeliveryWorker
from .status import PrinterStatusService


class ArtifactRequest(BaseModel):
    mime_type: str
    payload_base64: str
    checksum: str
    description: str = "PrintHub job"


class DeliveryRequest(BaseModel):
    printer_id: str
    idempotency_key: str = Field(min_length=1, max_length=255)
    artifact: ArtifactRequest
    max_attempts: int = Field(default=3, ge=1, le=10)


class PrinterPatchRequest(BaseModel):
    revision: int = Field(ge=1)
    settings: dict[str, Any]


class PausePrinterRequest(BaseModel):
    reason: str | None = Field(default=None, max_length=500)


class AgentDiscoveryRequest(BaseModel):
    urls: list[str] = Field(default_factory=list)


class AgentPrinterRegistrationRequest(BaseModel):
    public_id: str = Field(min_length=1, max_length=120)
    name: str | None = Field(default=None, max_length=200)


def create_app(
    repository: FleetRepository | None = None,
    authenticator: FleetAuthenticator | None = None,
) -> FastAPI:
    repo = repository or FleetRepository(os.getenv("PRINTER_FLEET_DATABASE", "/data/fleet.sqlite3"))
    auth = authenticator or BearerCredentialAuthenticator.from_environment()
    service = DeliveryService(
        repo,
        max_parallel_printers=int(os.getenv("PRINTER_FLEET_MAX_PARALLEL_PRINTERS", "4")),
    )
    status_service = PrinterStatusService()
    maintenance_service = PrinterMaintenanceService()
    discovery_service = AgentDiscoveryService(
        repo,
        discover_mdns=os.getenv("PRINTER_FLEET_MDNS_ENABLED", "1") == "1",
    )
    worker = DeliveryWorker(
        service,
        interval_seconds=float(os.getenv("PRINTER_FLEET_WORKER_INTERVAL_SECONDS", "1")),
    )
    discovery_worker = AgentDiscoveryWorker(
        discovery_service,
        interval_seconds=float(os.getenv("PRINTER_FLEET_DISCOVERY_INTERVAL_SECONDS", "30")),
    )
    delivery_worker_enabled = os.getenv("PRINTER_FLEET_DELIVERY_WORKER_ENABLED", "1") == "1"

    @asynccontextmanager
    async def lifespan(_app: FastAPI):
        repo.initialize()
        repo.recover_interrupted_deliveries()
        seed_path = os.getenv("PRINTER_FLEET_SEED_PATH")
        if seed_path and not repo.list_printers() and Path(seed_path).exists():
            document = yaml.safe_load(Path(seed_path).read_text(encoding="utf-8")) or {}
            for printer in document.get("printers", []):
                repo.put_printer(printer)
        if delivery_worker_enabled:
            worker.start()
        discovery_worker.start()
        try:
            yield
        finally:
            discovery_worker.stop()
            if delivery_worker_enabled:
                worker.stop()

    app = FastAPI(title="PrinterFleet API", version="0.1.0", lifespan=lifespan)

    @app.middleware("http")
    async def service_boundary(request: Request, call_next):
        supplied_id = request.headers.get("X-Correlation-ID", "")
        correlation_id = (
            supplied_id
            if re.fullmatch(r"[A-Za-z0-9._:-]{1,128}", supplied_id)
            else str(uuid.uuid4())
        )
        protected = request.url.path.startswith("/v1/") or request.url.path == "/metrics"
        principal = auth.authenticate(request.headers.get("Authorization", ""))
        if protected and principal is None:
            response = JSONResponse(
                status_code=401,
                content={"detail": "Invalid PrinterFleet service credential"},
                headers={"X-Correlation-ID": correlation_id},
            )
        else:
            request.state.fleet_principal = principal
            response = await call_next(request)
        response.headers["X-Correlation-ID"] = correlation_id
        if request.url.path.startswith("/v1/") and (
            request.method not in {"GET", "HEAD", "OPTIONS"} or response.status_code >= 400
        ):
            repo.append_audit_record(
                correlation_id=correlation_id,
                actor=principal.id if principal is not None else "anonymous",
                method=request.method,
                path=request.url.path,
                status_code=response.status_code,
            )
        return response

    app.state.repository = repo
    app.state.delivery_service = service
    app.state.status_service = status_service
    app.state.maintenance_service = maintenance_service
    app.state.discovery_service = discovery_service

    def request_principal(request: Request) -> FleetPrincipal:
        principal = getattr(request.state, "fleet_principal", None)
        if not isinstance(principal, FleetPrincipal):
            raise HTTPException(status_code=401, detail="Authentication required")
        return principal

    def require_roles(request: Request, *roles: str) -> FleetPrincipal:
        principal = request_principal(request)
        if not principal.has_any_role(*roles):
            raise HTTPException(status_code=403, detail="Fleet role is not permitted")
        return principal

    def require_global_admin(request: Request) -> FleetPrincipal:
        principal = request_principal(request)
        if not principal.is_global_admin:
            raise HTTPException(status_code=403, detail="Global Fleet administrator required")
        return principal

    def scoped_printer(request: Request, printer_id: str, *roles: str) -> dict[str, Any]:
        principal = require_roles(request, *roles)
        try:
            printer = repo.get_printer(printer_id)
        except KeyError:
            raise HTTPException(status_code=404, detail="Printer not found") from None
        if not principal.allows_site(str(printer.get("site_id") or "default")):
            raise HTTPException(status_code=404, detail="Printer not found")
        return printer

    def catalog_view(printer: dict[str, Any]) -> dict[str, Any]:
        return {key: value for key, value in printer.items() if key != "connection"}

    @app.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/metrics", response_class=PlainTextResponse)
    def metrics(request: Request) -> str:
        require_global_admin(request)
        snapshot = repo.metrics_snapshot()
        lines = [
            "# HELP printer_fleet_printers Registered physical printers.",
            "# TYPE printer_fleet_printers gauge",
            f"printer_fleet_printers {snapshot['printers']}",
            "# HELP printer_fleet_deliveries Delivery records by current state.",
            "# TYPE printer_fleet_deliveries gauge",
        ]
        lines.extend(
            f'printer_fleet_deliveries{{state="{state}"}} {count}'
            for state, count in sorted(snapshot["deliveries"].items())
        )
        return "\n".join(lines) + "\n"

    @app.get("/v1/printers")
    def list_printers(request: Request) -> list[dict[str, Any]]:
        principal = require_roles(request, "observer", "submitter")
        return [
            catalog_view(printer)
            for printer in repo.list_printers()
            if principal.allows_site(str(printer.get("site_id") or "default"))
        ]

    @app.get("/v1/audit-records")
    def list_audit_records(request: Request, limit: int = 100) -> list[dict[str, Any]]:
        require_global_admin(request)
        if limit < 1 or limit > 500:
            raise HTTPException(status_code=422, detail="limit must be between 1 and 500")
        return repo.list_audit_records(limit=limit)

    @app.get("/v1/printer-registry/export")
    def export_printers(request: Request) -> dict[str, Any]:
        require_global_admin(request)
        return repo.export_printers()

    @app.post("/v1/printer-registry/import")
    def import_printers(document: dict[str, Any], request: Request) -> dict[str, Any]:
        require_global_admin(request)
        try:
            repo.import_printers(document)
            return repo.export_printers()
        except RegistryConflict as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.get("/v1/printers/{printer_id}")
    def get_printer(printer_id: str, request: Request) -> dict[str, Any]:
        return catalog_view(scoped_printer(request, printer_id, "observer", "submitter"))

    @app.put("/v1/printers/{printer_id}")
    def put_printer(printer_id: str, printer: dict[str, Any], request: Request) -> dict[str, Any]:
        principal = require_roles(request, "admin")
        if printer.get("id", printer_id) != printer_id:
            raise HTTPException(status_code=400, detail="Printer id must match path")
        printer["id"] = printer_id
        if not principal.allows_site(str(printer.get("site_id") or "default")):
            raise HTTPException(status_code=403, detail="Printer site is not permitted")
        try:
            return repo.put_printer(printer)
        except RegistryConflict as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.patch("/v1/printers/{printer_id}")
    def patch_printer(
        printer_id: str,
        payload: PrinterPatchRequest,
        request: Request,
    ) -> dict[str, Any]:
        principal = require_roles(request, "admin")
        try:
            current = scoped_printer(request, printer_id, "admin")
            target_site = str(payload.settings.get("site_id", current.get("site_id") or "default"))
            if not principal.allows_site(target_site):
                raise HTTPException(status_code=403, detail="Printer site is not permitted")
            return repo.patch_printer(printer_id, payload.settings, payload.revision)
        except KeyError:
            raise HTTPException(status_code=404, detail="Printer not found") from None
        except RegistryConflict as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.post("/v1/printers/{printer_id}/pause")
    def pause_printer(
        printer_id: str,
        payload: PausePrinterRequest,
        request: Request,
    ) -> dict[str, Any]:
        scoped_printer(request, printer_id, "admin")
        try:
            return catalog_view(
                repo.set_printer_paused(printer_id, paused=True, reason=payload.reason)
            )
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    @app.post("/v1/printers/{printer_id}/resume")
    def resume_printer(printer_id: str, request: Request) -> dict[str, Any]:
        scoped_printer(request, printer_id, "admin")
        return catalog_view(repo.set_printer_paused(printer_id, paused=False))

    @app.get("/v1/printers/{printer_id}/status")
    def get_printer_status(printer_id: str, request: Request) -> dict[str, Any]:
        operation_owner: str | None = None
        try:
            printer = scoped_printer(request, printer_id, "observer")
            timeout_ms = int((printer.get("connection") or {}).get("timeout_ms", 3000))
            operation_owner = repo.acquire_printer_operation(
                printer_id,
                kind="status",
                lease_seconds=max(30, min(600, timeout_ms / 1000 * 5)),
            )
            if operation_owner is None:
                raise HTTPException(status_code=409, detail="Printer is busy")
            return app.state.status_service.read(printer)
        except KeyError:
            raise HTTPException(status_code=404, detail="Printer not found") from None
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        except (OSError, RuntimeError) as exc:
            raise HTTPException(status_code=502, detail=str(exc)) from exc
        finally:
            if operation_owner is not None:
                repo.release_printer_operation(printer_id, operation_owner)

    @app.post("/v1/printers/{printer_id}/maintenance/{action}")
    def run_printer_maintenance(
        printer_id: str,
        action: str,
        request: Request,
    ) -> dict[str, Any]:
        operation_owner: str | None = None
        try:
            printer = scoped_printer(request, printer_id, "admin")
            timeout_ms = int((printer.get("connection") or {}).get("timeout_ms", 3000))
            operation_owner = repo.acquire_printer_operation(
                printer_id,
                kind=f"maintenance:{action}",
                lease_seconds=max(30, min(900, timeout_ms / 1000 * 5)),
            )
            if operation_owner is None:
                raise HTTPException(status_code=409, detail="Printer is busy")
            return app.state.maintenance_service.execute(printer, action)
        except KeyError:
            raise HTTPException(status_code=404, detail="Printer not found") from None
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        except FleetError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        except (OSError, RuntimeError) as exc:
            raise HTTPException(status_code=502, detail=str(exc)) from exc
        finally:
            if operation_owner is not None:
                repo.release_printer_operation(printer_id, operation_owner)

    @app.get("/v1/agents")
    def list_agents(request: Request) -> list[dict[str, Any]]:
        require_global_admin(request)
        return repo.list_agents()

    @app.post("/v1/agents/discover")
    def discover_agents(payload: AgentDiscoveryRequest, request: Request) -> dict[str, Any]:
        require_global_admin(request)
        try:
            return app.state.discovery_service.discover(payload.urls)
        except (ValueError, RegistryConflict) as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc

    @app.post("/v1/agents/{agent_id}/printers/{device_id}/register")
    def register_agent_printer(
        agent_id: str,
        device_id: str,
        payload: AgentPrinterRegistrationRequest,
        request: Request,
    ) -> dict[str, Any]:
        require_global_admin(request)
        try:
            return app.state.discovery_service.register(
                agent_id=agent_id,
                device_id=device_id,
                public_id=payload.public_id,
                name=payload.name,
            )
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=f"Not found: {exc.args[0]}") from None
        except RegistryConflict as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        except RuntimeError as exc:
            raise HTTPException(status_code=502, detail=str(exc)) from exc

    @app.post("/v1/deliveries", status_code=202)
    def create_delivery(payload_request: DeliveryRequest, request: Request) -> dict[str, Any]:
        scoped_printer(request, payload_request.printer_id, "submitter")
        try:
            payload = base64.b64decode(payload_request.artifact.payload_base64, validate=True)
            return app.state.delivery_service.submit(
                printer_id=payload_request.printer_id,
                idempotency_key=payload_request.idempotency_key,
                artifact=PrintArtifact(
                    mime_type=payload_request.artifact.mime_type,
                    payload=payload,
                    description=payload_request.artifact.description,
                ),
                declared_checksum=payload_request.artifact.checksum,
                max_attempts=payload_request.max_attempts,
            )
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=f"Not found: {exc.args[0]}") from None
        except DeliveryConflict as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        except PrinterPaused as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        except (ValueError, FleetError) as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        except Exception as exc:
            raise HTTPException(status_code=502, detail=str(exc)) from exc

    @app.get("/v1/deliveries")
    def list_deliveries(
        request: Request,
        printer_id: str | None = None,
        state: str | None = None,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        principal = require_roles(request, "observer", "submitter")
        if limit < 1 or limit > 500:
            raise HTTPException(status_code=422, detail="limit must be between 1 and 500")
        if state is not None and state not in {item.value for item in DeliveryState}:
            raise HTTPException(status_code=422, detail="Unknown delivery state")
        if printer_id:
            scoped_printer(request, printer_id, "observer", "submitter")
        allowed_printer_ids = None
        if "*" not in principal.sites:
            allowed_printer_ids = {
                str(printer["id"])
                for printer in repo.list_printers()
                if principal.allows_site(str(printer.get("site_id") or "default"))
            }
        deliveries = repo.list_deliveries(
            printer_id=printer_id,
            printer_ids=allowed_printer_ids,
            state=state,
            limit=limit,
        )
        return deliveries

    @app.get("/v1/deliveries/{delivery_id}")
    def get_delivery(delivery_id: str, request: Request) -> dict[str, Any]:
        principal = require_roles(request, "observer", "submitter")
        try:
            delivery = repo.get_delivery(delivery_id)
        except KeyError:
            raise HTTPException(status_code=404, detail="Delivery not found") from None
        printer = repo.get_printer(str(delivery["printer_id"]))
        if not principal.allows_site(str(printer.get("site_id") or "default")):
            raise HTTPException(status_code=404, detail="Delivery not found")
        return delivery

    return app


app = create_app()
