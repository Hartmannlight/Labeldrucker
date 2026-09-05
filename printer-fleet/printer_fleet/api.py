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
from fastapi.responses import JSONResponse
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
    service = DeliveryService(repo)
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

    @app.middleware("http")
    async def service_boundary(request: Request, call_next):
        supplied_id = request.headers.get("X-Correlation-ID", "")
        correlation_id = (
            supplied_id
            if re.fullmatch(r"[A-Za-z0-9._:-]{1,128}", supplied_id)
            else str(uuid.uuid4())
        )
        if request.url.path.startswith("/v1/") and api_token:
            authorization = request.headers.get("Authorization", "")
            expected = f"Bearer {api_token}"
            if not secrets.compare_digest(authorization, expected):
                return JSONResponse(
                    status_code=401,
                    content={"detail": "Invalid PrinterFleet service credential"},
                    headers={"X-Correlation-ID": correlation_id},
                )
        response = await call_next(request)
        response.headers["X-Correlation-ID"] = correlation_id
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

    @app.get("/v1/printers")
    def list_printers() -> list[dict[str, Any]]:
        return [catalog_view(printer) for printer in repo.list_printers()]

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
        try:
            return app.state.status_service.read(repo.get_printer(printer_id))
        except KeyError:
            raise HTTPException(status_code=404, detail="Printer not found") from None
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        except (OSError, RuntimeError) as exc:
            raise HTTPException(status_code=502, detail=str(exc)) from exc

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
