from __future__ import annotations

import base64
from contextlib import asynccontextmanager
import os
from pathlib import Path
import re
import secrets
from typing import Any
import uuid

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse, PlainTextResponse
from pydantic import BaseModel, Field
import yaml

from .domain import DeliveryConflict, FleetError, PrintArtifact, RegistryConflict
from .discovery import AgentDiscoveryService
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


class AgentDiscoveryRequest(BaseModel):
    urls: list[str] = Field(default_factory=list)


class AgentPrinterRegistrationRequest(BaseModel):
    public_id: str = Field(min_length=1, max_length=120)
    name: str | None = Field(default=None, max_length=200)


def create_app(repository: FleetRepository | None = None) -> FastAPI:
    repo = repository or FleetRepository(os.getenv("PRINTER_FLEET_DATABASE", "/data/fleet.sqlite3"))
    service = DeliveryService(
        repo,
        max_parallel_printers=int(os.getenv("PRINTER_FLEET_MAX_PARALLEL_PRINTERS", "4")),
    )
    status_service = PrinterStatusService()
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

    @asynccontextmanager
    async def lifespan(_app: FastAPI):
        repo.initialize()
        repo.recover_interrupted_deliveries()
        seed_path = os.getenv("PRINTER_FLEET_SEED_PATH")
        if seed_path and not repo.list_printers() and Path(seed_path).exists():
            document = yaml.safe_load(Path(seed_path).read_text(encoding="utf-8")) or {}
            for printer in document.get("printers", []):
                repo.put_printer(printer)
        worker.start()
        discovery_worker.start()
        try:
            yield
        finally:
            discovery_worker.stop()
            worker.stop()

    app = FastAPI(title="PrinterFleet API", version="0.1.0", lifespan=lifespan)
    api_token = os.getenv("PRINTER_FLEET_API_TOKEN", "").strip()
    caller_id = os.getenv("PRINTER_FLEET_API_CALLER_ID", "printhub").strip() or "printhub"

    @app.middleware("http")
    async def service_boundary(request: Request, call_next):
        supplied_id = request.headers.get("X-Correlation-ID", "")
        correlation_id = (
            supplied_id
            if re.fullmatch(r"[A-Za-z0-9._:-]{1,128}", supplied_id)
            else str(uuid.uuid4())
        )
        protected = request.url.path.startswith("/v1/") or request.url.path == "/metrics"
        if protected and api_token:
            authorization = request.headers.get("Authorization", "")
            expected = f"Bearer {api_token}"
            if not secrets.compare_digest(authorization, expected):
                response = JSONResponse(
                    status_code=401,
                    content={"detail": "Invalid PrinterFleet service credential"},
                    headers={"X-Correlation-ID": correlation_id},
                )
            else:
                response = await call_next(request)
        else:
            response = await call_next(request)
        response.headers["X-Correlation-ID"] = correlation_id
        if request.url.path.startswith("/v1/") and (
            request.method not in {"GET", "HEAD", "OPTIONS"} or response.status_code >= 400
        ):
            repo.append_audit_record(
                correlation_id=correlation_id,
                actor=caller_id if response.status_code != 401 else "anonymous",
                method=request.method,
                path=request.url.path,
                status_code=response.status_code,
            )
        return response

    app.state.repository = repo
    app.state.delivery_service = service
    app.state.status_service = status_service
    app.state.discovery_service = discovery_service

    def catalog_view(printer: dict[str, Any]) -> dict[str, Any]:
        return {key: value for key, value in printer.items() if key != "connection"}

    @app.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/metrics", response_class=PlainTextResponse)
    def metrics() -> str:
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
    def list_printers() -> list[dict[str, Any]]:
        return [catalog_view(printer) for printer in repo.list_printers()]

    @app.get("/v1/audit-records")
    def list_audit_records(limit: int = 100) -> list[dict[str, Any]]:
        if limit < 1 or limit > 500:
            raise HTTPException(status_code=422, detail="limit must be between 1 and 500")
        return repo.list_audit_records(limit=limit)

    @app.get("/v1/printer-registry/export")
    def export_printers() -> dict[str, Any]:
        return repo.export_printers()

    @app.post("/v1/printer-registry/import")
    def import_printers(document: dict[str, Any]) -> dict[str, Any]:
        try:
            repo.import_printers(document)
            return repo.export_printers()
        except RegistryConflict as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.get("/v1/printers/{printer_id}")
    def get_printer(printer_id: str) -> dict[str, Any]:
        try:
            return catalog_view(repo.get_printer(printer_id))
        except KeyError:
            raise HTTPException(status_code=404, detail="Printer not found") from None

    @app.put("/v1/printers/{printer_id}")
    def put_printer(printer_id: str, printer: dict[str, Any]) -> dict[str, Any]:
        if printer.get("id", printer_id) != printer_id:
            raise HTTPException(status_code=400, detail="Printer id must match path")
        printer["id"] = printer_id
        try:
            return repo.put_printer(printer)
        except RegistryConflict as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.patch("/v1/printers/{printer_id}")
    def patch_printer(printer_id: str, request: PrinterPatchRequest) -> dict[str, Any]:
        try:
            return repo.patch_printer(printer_id, request.settings, request.revision)
        except KeyError:
            raise HTTPException(status_code=404, detail="Printer not found") from None
        except RegistryConflict as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.get("/v1/printers/{printer_id}/status")
    def get_printer_status(printer_id: str) -> dict[str, Any]:
        operation_owner: str | None = None
        try:
            printer = repo.get_printer(printer_id)
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

    @app.get("/v1/agents")
    def list_agents() -> list[dict[str, Any]]:
        return repo.list_agents()

    @app.post("/v1/agents/discover")
    def discover_agents(request: AgentDiscoveryRequest) -> dict[str, Any]:
        try:
            return app.state.discovery_service.discover(request.urls)
        except (ValueError, RegistryConflict) as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc

    @app.post("/v1/agents/{agent_id}/printers/{device_id}/register")
    def register_agent_printer(
        agent_id: str,
        device_id: str,
        request: AgentPrinterRegistrationRequest,
    ) -> dict[str, Any]:
        try:
            return app.state.discovery_service.register(
                agent_id=agent_id,
                device_id=device_id,
                public_id=request.public_id,
                name=request.name,
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
    def create_delivery(request: DeliveryRequest) -> dict[str, Any]:
        try:
            payload = base64.b64decode(request.artifact.payload_base64, validate=True)
            return app.state.delivery_service.deliver(
                printer_id=request.printer_id,
                idempotency_key=request.idempotency_key,
                artifact=PrintArtifact(
                    mime_type=request.artifact.mime_type,
                    payload=payload,
                    description=request.artifact.description,
                ),
                declared_checksum=request.artifact.checksum,
                max_attempts=request.max_attempts,
            )
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=f"Not found: {exc.args[0]}") from None
        except DeliveryConflict as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        except (ValueError, FleetError) as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        except Exception as exc:
            raise HTTPException(status_code=502, detail=str(exc)) from exc

    @app.get("/v1/deliveries/{delivery_id}")
    def get_delivery(delivery_id: str) -> dict[str, Any]:
        try:
            return repo.get_delivery(delivery_id)
        except KeyError:
            raise HTTPException(status_code=404, detail="Delivery not found") from None

    return app


app = create_app()
