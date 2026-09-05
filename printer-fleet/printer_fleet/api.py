from __future__ import annotations

import base64
from contextlib import asynccontextmanager
import os
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field
import yaml

from .domain import DeliveryConflict, FleetError, PrintArtifact, RegistryConflict
from .repository import FleetRepository
from .service import DeliveryService


class ArtifactRequest(BaseModel):
    mime_type: str
    payload_base64: str
    checksum: str
    description: str = "PrintHub job"


class DeliveryRequest(BaseModel):
    printer_id: str
    idempotency_key: str = Field(min_length=1, max_length=255)
    artifact: ArtifactRequest


class PrinterPatchRequest(BaseModel):
    revision: int = Field(ge=1)
    settings: dict[str, Any]


def create_app(repository: FleetRepository | None = None) -> FastAPI:
    repo = repository or FleetRepository(os.getenv("PRINTER_FLEET_DATABASE", "/data/fleet.sqlite3"))
    service = DeliveryService(repo)

    @asynccontextmanager
    async def lifespan(_app: FastAPI):
        repo.initialize()
        seed_path = os.getenv("PRINTER_FLEET_SEED_PATH")
        if seed_path and not repo.list_printers() and Path(seed_path).exists():
            document = yaml.safe_load(Path(seed_path).read_text(encoding="utf-8")) or {}
            for printer in document.get("printers", []):
                repo.put_printer(printer)
        yield

    app = FastAPI(title="PrinterFleet API", version="0.1.0", lifespan=lifespan)
    app.state.repository = repo
    app.state.delivery_service = service

    def catalog_view(printer: dict[str, Any]) -> dict[str, Any]:
        return {key: value for key, value in printer.items() if key != "connection"}

    @app.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/v1/printers")
    def list_printers() -> list[dict[str, Any]]:
        return [catalog_view(printer) for printer in repo.list_printers()]

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
