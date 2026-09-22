from __future__ import annotations

import asyncio
import base64
from contextlib import asynccontextmanager, suppress
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import secrets
import sqlite3
import uuid

from fastapi import Depends, FastAPI, Header, Query, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field
from starlette.exceptions import HTTPException

from .protocol import B1Protocol, Page
from .transports import connect

MIME = "application/vnd.printhub.raster-page+json"
MAX_BODY = 12_000_000


def now():
    return datetime.now(timezone.utc).isoformat()


class Settings(BaseModel):
    token: str = Field(min_length=24)
    data_dir: Path = Path("./niimbot-data")
    service_id: str = Field(default="niimbot-b1-service", min_length=1, max_length=255)
    transport: str = "serial"
    address: str = ""
    width_mm: float = Field(default=40, ge=25.4 / 203, le=48)
    height_mm: float = Field(default=30, ge=25.4 / 203, le=300)
    density: int = Field(default=3, ge=1, le=5)
    label_type: int = Field(default=1, ge=1, le=3)

    @classmethod
    def from_env(cls):
        values = {name: os.environ[f"NIIMBOT_{name.upper()}"] for name in cls.model_fields
                  if f"NIIMBOT_{name.upper()}" in os.environ}
        token_file = os.getenv("NIIMBOT_TOKEN_FILE")
        if token_file:
            if "token" in values:
                raise ValueError("Configure only NIIMBOT_TOKEN or NIIMBOT_TOKEN_FILE")
            values["token"] = Path(token_file).read_text(encoding="utf-8").strip()
        result = cls(**values)
        if result.transport not in ("serial", "ble") or not result.address:
            raise ValueError("Set NIIMBOT_TRANSPORT (serial/ble) and NIIMBOT_ADDRESS")
        if any(c.isspace() for c in result.token):
            raise ValueError("NIIMBOT token must not contain whitespace")
        return result

    @property
    def revision(self):
        content = f"{self.width_mm}:{self.height_mm}:{self.density}:{self.label_type}"
        return hashlib.sha256(content.encode()).hexdigest()[:20]


class Artifact(BaseModel):
    model_config = ConfigDict(extra="forbid")
    mime_type: str
    sha256: str = Field(pattern="^[a-fA-F0-9]{64}$")
    data_base64: str = Field(max_length=1_000_000)


class Submit(BaseModel):
    model_config = ConfigDict(extra="forbid")
    idempotency_key: str = Field(min_length=1, max_length=255)
    description: str | None = Field(default=None, max_length=1000)
    media_revision: str | None = None
    copies: int = Field(default=1, ge=1, le=999)
    reprint_of: str | None = None
    artifacts: list[Artifact] = Field(min_length=1, max_length=25)
    options: dict = Field(default_factory=dict)


class ServiceError(Exception):
    def __init__(self, status, code, message):
        self.status, self.code, self.message = status, code, message


def decode(artifact: Artifact, settings: Settings) -> Page:
    if artifact.mime_type != MIME:
        raise ValueError("NIIMBOT accepts only neutral raster pages")
    raw = base64.b64decode(artifact.data_base64, validate=True)
    if hashlib.sha256(raw).hexdigest() != artifact.sha256.lower():
        raise ValueError("Artifact checksum mismatch")
    doc = json.loads(raw)
    if not isinstance(doc, dict):
        raise ValueError("Raster must be an object")
    for field in ("version", "copies", "dpi", "width_px", "height_px"):
        if type(doc.get(field)) is not int:
            raise ValueError(f"Raster {field} must be an integer")
    if doc["version"] != 1 or doc["copies"] != 1 or doc["dpi"] != 203:
        raise ValueError("B1 requires raster v1, 203 dpi, page copies=1")
    if doc["width_px"] != round(settings.width_mm * 203 / 25.4) or doc["height_px"] != round(settings.height_mm * 203 / 25.4):
        raise ValueError("Raster dimensions must match configured loaded media")
    return Page(doc["width_px"], doc["height_px"], base64.b64decode(doc["black_bits_base64"], validate=True))


class Store:
    """SQLite transactions persist the job, payloads and idempotency together."""

    def __init__(self, path):
        self.db = sqlite3.connect(path)
        self.db.execute("PRAGMA journal_mode=WAL")
        self.db.execute("PRAGMA synchronous=FULL")
        self.db.execute("CREATE TABLE IF NOT EXISTS jobs (seq INTEGER PRIMARY KEY, id TEXT UNIQUE, key TEXT UNIQUE, hash TEXT, state TEXT, document TEXT, request TEXT)")
        self.db.commit()

    def get(self, job_id):
        row = self.db.execute("SELECT document FROM jobs WHERE id=?", (job_id,)).fetchone()
        if not row:
            raise ServiceError(404, "not_found", "Job not found")
        return json.loads(row[0])

    def save(self, job):
        job["updated_at"] = now()
        with self.db:
            self.db.execute("UPDATE jobs SET state=?, document=? WHERE id=?", (job["state"], json.dumps(job), job["id"]))

    def recover(self):
        for (document,) in self.db.execute("SELECT document FROM jobs WHERE state='transmitting'").fetchall():
            job = json.loads(document)
            job.update(state="outcome_unknown", error="Service stopped during device transfer; inspect labels before reprinting")
            self.save(job)

    def submit(self, request: Submit, settings: Settings):
        if request.options:
            raise ServiceError(400, "unsupported_options", "No per-job vendor options are supported")
        if len(request.artifacts) * request.copies > 999:
            raise ServiceError(400, "job_limit", "At most 999 labels per job")
        canonical = request.model_dump(exclude={"idempotency_key", "description"})
        canonical["printer_id"] = "b1"
        canonical["artifacts"] = [{"mime_type": a.mime_type, "sha256": a.sha256.lower()} for a in request.artifacts]
        digest = hashlib.sha256(json.dumps(canonical, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
        with self.db:
            existing = self.db.execute("SELECT hash, document FROM jobs WHERE key=?", (request.idempotency_key,)).fetchone()
            if existing:
                if existing[0] != digest:
                    raise ServiceError(409, "idempotency_conflict", "Key already identifies another job")
                return json.loads(existing[1])
            try:
                pages = [decode(artifact, settings) for artifact in request.artifacts]
            except (ValueError, TypeError, KeyError) as exc:
                raise ServiceError(400, "invalid_raster", str(exc)) from exc
            job = dict(id=str(uuid.uuid4()), printer_id="b1", state="queued", created_at=now(), updated_at=now(),
                       idempotency_key=request.idempotency_key, request_sha256=digest,
                       device_payload_bytes=sum(len(p.bits) for p in pages) * request.copies,
                       bytes_transferred=0, delivery_attempts=0, label_count=len(pages) * request.copies,
                       error=None, reprint_of=request.reprint_of)
            self.db.execute("INSERT INTO jobs(id,key,hash,state,document,request) VALUES(?,?,?,?,?,?)",
                            (job["id"], request.idempotency_key, digest, job["state"], json.dumps(job), request.model_dump_json()))
        return job


async def process_next(store: Store, settings: Settings, connector=connect):
    row = store.db.execute("SELECT id, request FROM jobs WHERE state='queued' ORDER BY seq LIMIT 1").fetchone()
    if not row:
        return False
    job = store.get(row[0])
    request = Submit.model_validate_json(row[1])
    if request.media_revision and request.media_revision != settings.revision:
        job.update(state="held", error="media_revision_changed")
        store.save(job)
        return True
    try:
        pages = [decode(a, settings) for a in request.artifacts]
    except (ValueError, TypeError, KeyError):
        job.update(state="held", error="media_profile_changed")
        store.save(job)
        return True
    job.update(state="transmitting", delivery_attempts=job["delivery_attempts"] + 1)
    store.save(job)  # Durable before connecting; crash recovery never replays it.
    protocol = None
    try:
        async with connector(settings.transport, settings.address) as transport:
            protocol = B1Protocol(transport)
            await protocol.print_pages(pages, request.copies, density=settings.density, label_type=settings.label_type)
        job.update(state="completed_observed", error=None)
    except asyncio.CancelledError:
        job.update(state="outcome_unknown", error="Service stopped during transfer; inspect labels")
        raise
    except Exception as exc:
        job.update(state="outcome_unknown" if protocol and protocol.print_started else "failed",
                   error=f"{type(exc).__name__}: {exc}" or "Device communication failed")
    finally:
        job["bytes_transferred"] = protocol.bytes_sent if protocol else 0
        store.save(job)
    return True


def create_app(settings: Settings | None = None, *, connector=connect, run_worker=True):
    @asynccontextmanager
    async def lifespan(app):
        app.state.settings = settings or Settings.from_env()
        cfg = app.state.settings
        cfg.data_dir.mkdir(parents=True, exist_ok=True)
        # One process owns the hardware and recovery. OS releases this lock after a crash.
        import portalocker
        with portalocker.Lock(str(cfg.data_dir / "owner.lock"), timeout=0):
            store = Store(cfg.data_dir / "jobs.sqlite3")
            app.state.store = store
            store.recover()

            async def worker():
                while True:
                    await process_next(store, cfg, connector)
                    await asyncio.sleep(0.2)
            task = asyncio.create_task(worker()) if run_worker else None
            app.state.worker = task
            try:
                yield
            finally:
                if task:
                    task.cancel()
                    with suppress(asyncio.CancelledError):
                        await task
                store.db.close()

    app = FastAPI(title="NIIMBOT B1 print service", version="0.1.0", lifespan=lifespan)

    @app.exception_handler(ServiceError)
    async def error_handler(_request, exc):
        return JSONResponse(status_code=exc.status, content={"error": {"code": exc.code, "message": exc.message, "details": {}}})

    @app.exception_handler(RequestValidationError)
    async def validation_error(_request, _exc):
        # Do not echo submitted image data or credentials in validation errors.
        return JSONResponse(status_code=422, content={"error": {
            "code": "invalid_request", "message": "Request does not match the print-service schema", "details": {}}})

    @app.exception_handler(HTTPException)
    async def http_error(_request, exc):
        return JSONResponse(status_code=exc.status_code, content={"error": {
            "code": "not_found" if exc.status_code == 404 else "http_error", "message": str(exc.detail), "details": {}}})

    @app.middleware("http")
    async def body_limit(request: Request, call_next):
        if request.method in ("POST", "PUT"):
            chunks, size = [], 0
            async for chunk in request.stream():
                size += len(chunk)
                if size > MAX_BODY:
                    return JSONResponse(status_code=413, content={"error": {"code": "job_limit", "message": "Request too large", "details": {}}})
                chunks.append(chunk)
            request._body = b"".join(chunks)
        return await call_next(request)

    async def authorize(authorization: str | None = Header(default=None)):
        expected = "Bearer " + app.state.settings.token
        if not secrets.compare_digest((authorization or "").encode(), expected.encode()):
            raise ServiceError(401, "unauthorized", "A valid service token is required")

    auth = [Depends(authorize)]

    @app.get("/healthz")
    async def health():
        task = app.state.worker
        if task and task.done():
            raise ServiceError(503, "worker_stopped", "Print worker is not running")
        return {"status": "ok"}

    @app.get("/v2/service", dependencies=auth)
    async def service():
        return dict(protocol={"name": "printhub-print-service", "major": 2, "minor": 0},
                    service_id=app.state.settings.service_id, service_type="niimbot", display_name="NIIMBOT B1",
                    version="0.1.0", capabilities=["catalog", "jobs", "idempotency_lookup"],
                    limits={"max_request_bytes": MAX_BODY, "max_artifacts": 25, "max_labels": 999})

    def printer_document():
        cfg = app.state.settings
        return dict(id="b1", service_id=cfg.service_id, display_name="NIIMBOT B1", device_family="niimbot",
                    enabled=True, accepted_mime_types=[MIME],
                    capabilities={"status_probe": False, "media": False, "device_configuration": False, "queue_control": False, "cancel": True},
                    profile={"resolution_dpi": 203, "max_width_dots": 384, "max_length_dots": round(300 * 203 / 25.4)},
                    status={"ready": {"state": "unknown", "source": "not_probed"}}, observed_at=now(),
                    media={"revision": cfg.revision, "state": {"remaining_labels": None, "source": "configuration", "media": {
                        "display_name": "Configured B1 labels", "width_mm": cfg.width_mm, "height_mm": cfg.height_mm,
                        "color": {"name": "white", "hex": "#ffffff"}}}})

    def require_printer(printer_id):
        if printer_id != "b1":
            raise ServiceError(404, "not_found", "Printer not found")

    @app.get("/v2/printers", dependencies=auth)
    async def printers():
        return {"items": [printer_document()], "next_cursor": None}

    @app.get("/v2/printers/{printer_id}", dependencies=auth)
    async def printer(printer_id: str):
        require_printer(printer_id)
        return printer_document()

    @app.post("/v2/printers/{printer_id}/jobs", dependencies=auth, status_code=202)
    async def submit(printer_id: str, request: Submit):
        require_printer(printer_id)
        return app.state.store.submit(request, app.state.settings)

    @app.get("/v2/jobs/by-idempotency/{key:path}", dependencies=auth)
    async def by_key(key: str):
        row = app.state.store.db.execute("SELECT document FROM jobs WHERE key=?", (key,)).fetchone()
        if not row:
            raise ServiceError(404, "not_found", "Job not found")
        return json.loads(row[0])

    @app.get("/v2/jobs/{job_id}", dependencies=auth)
    async def job(job_id: str):
        return app.state.store.get(job_id)

    @app.get("/v2/jobs", dependencies=auth)
    async def jobs(cursor: int = Query(default=0, ge=0), limit: int = Query(default=50, ge=1, le=200),
                   printer_id: str | None = None, state: str | None = None):
        if printer_id is not None:
            require_printer(printer_id)
        rows = app.state.store.db.execute("SELECT seq, document FROM jobs WHERE seq>? AND (? IS NULL OR state=?) ORDER BY seq LIMIT ?",
                                         (cursor, state, state, limit)).fetchall()
        return {"items": [json.loads(row[1]) for row in rows], "next_cursor": rows[-1][0] if len(rows) == limit else None}

    @app.post("/v2/jobs/{job_id}/cancel", dependencies=auth)
    async def cancel(job_id: str):
        store = app.state.store
        job = store.get(job_id)
        if job["state"] == "cancelled":
            return job
        if job["state"] not in ("queued", "held"):
            raise ServiceError(409, "cannot_cancel", "Device transfer may already have started")
        job.update(state="cancelled", error=None)
        store.save(job)
        return job

    return app
