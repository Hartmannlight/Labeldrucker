import asyncio
import base64
from contextlib import asynccontextmanager
import hashlib
import json
from pathlib import Path

from fastapi.testclient import TestClient
import jsonschema
import pytest
from urllib.parse import quote

from niimbot_service.app import MIME, Settings, Store, Submit, create_app, process_next
from test_protocol import Printer

TOKEN = "niimbot-test-token-with-32-characters"
HEADERS = {"Authorization": "Bearer " + TOKEN}


def request(key="example", **fields):
    page = dict(version=1, width_px=8, height_px=8, dpi=203, copies=1,
                black_bits_base64=base64.b64encode(b"\x80" * 8).decode())
    page.update(fields)
    raw = json.dumps(page).encode()
    return dict(idempotency_key=key, copies=1, artifacts=[dict(mime_type=MIME,
                data_base64=base64.b64encode(raw).decode(), sha256=hashlib.sha256(raw).hexdigest())])


@pytest.fixture
def cfg(tmp_path):
    return Settings(token=TOKEN, data_dir=tmp_path, width_mm=1, height_mm=1, address="test")


def test_catalog_contract_auth_idempotency_cancel_and_restart(cfg):
    schema_dir = Path(__file__).resolve().parents[3] / "components/PrintHub-ZPL-ll/contracts/print-service-v2"
    with TestClient(create_app(cfg, run_worker=False)) as client:
        assert client.get("/v2/printers").status_code == 401
        for route, schema in [("/v2/service", "service"), ("/v2/printers/b1", "printer")]:
            response = client.get(route, headers=HEADERS)
            assert response.status_code == 200
            jsonschema.validate(response.json(), json.loads((schema_dir / f"{schema}.schema.json").read_text()))
        assert client.get("/v2/printers/other", headers=HEADERS).status_code == 404
        body = request()
        first = client.post("/v2/printers/b1/jobs", json=body, headers=HEADERS)
        assert first.status_code == 202
        job = first.json()
        jsonschema.validate(job, json.loads((schema_dir / "job.schema.json").read_text()))
        repeat = client.post("/v2/printers/b1/jobs", json=body, headers=HEADERS)
        assert repeat.json() == job
        assert client.get("/v2/jobs/by-idempotency/example", headers=HEADERS).json() == job
        body["copies"] = 2
        assert client.post("/v2/printers/b1/jobs", json=body, headers=HEADERS).status_code == 409
        assert client.post(f"/v2/jobs/{job['id']}/cancel", headers=HEADERS).json()["state"] == "cancelled"
        assert client.get("/v2/jobs/not-a-uuid", headers=HEADERS).status_code == 404
    with TestClient(create_app(cfg, run_worker=False)) as client:
        assert client.post("/v2/printers/b1/jobs", json=request(), headers=HEADERS).json()["state"] == "cancelled"


@pytest.mark.parametrize("changes", [{"dpi": 300}, {"copies": 2}, {"width_px": 385}, {"height_px": 0}, {"width_px": 8.0}, {"version": True}, {"black_bits_base64": "bad!"}])
def test_rejects_invalid_raster_before_queueing(cfg, changes):
    with TestClient(create_app(cfg, run_worker=False)) as client:
        response = client.post("/v2/printers/b1/jobs", headers=HEADERS, json=request(**changes))
        assert response.status_code == 400
        assert client.get("/v2/jobs", headers=HEADERS).json()["items"] == []


def test_checksum_and_unknown_options(cfg):
    with TestClient(create_app(cfg, run_worker=False)) as client:
        for mutate in (lambda body: body["artifacts"][0].update(sha256="0" * 64), lambda body: body.update(options={"zpl": "ignored?"})):
            body = request(); mutate(body)
            assert client.post("/v2/printers/b1/jobs", json=body, headers=HEADERS).status_code == 400


def test_validation_and_unsupported_routes_use_contract_errors(cfg):
    with TestClient(create_app(cfg, run_worker=False)) as client:
        invalid = client.post("/v2/printers/b1/jobs", json={"data_base64": "private"}, headers=HEADERS)
        assert invalid.status_code == 422
        assert invalid.json()["error"]["code"] == "invalid_request"
        assert "private" not in invalid.text
        unsupported = client.post("/v2/printers/b1/queue/pause", headers=HEADERS)
        assert unsupported.status_code == 404
        assert unsupported.json()["error"]["code"] == "not_found"


def test_media_change_and_crash_are_never_replayed(cfg):
    store = Store(cfg.data_dir / "jobs.sqlite3")
    stale = store.submit(Submit(**request(), media_revision="old"), cfg)
    async def run():
        await process_next(store, cfg)
        assert store.get(stale["id"])["state"] == "held"
    asyncio.run(run())
    job = store.submit(Submit(**request("crashed")), cfg)
    job["state"] = "transmitting"; store.save(job); store.db.close()
    recovered = Store(cfg.data_dir / "jobs.sqlite3")
    recovered.recover()
    assert recovered.get(job["id"])["state"] == "outcome_unknown"
    assert not asyncio.run(process_next(recovered, cfg))
    recovered.db.close()


@pytest.mark.parametrize("failure,expected", [(None, "completed_observed"), ("offline", "failed"), ("partial", "outcome_unknown")])
def test_worker_evidence_and_no_physical_retry(cfg, failure, expected):
    store = Store(cfg.data_dir / "jobs.sqlite3")
    submitted = store.submit(Submit(**request()), cfg)
    async def run():
        peer = Printer()
        @asynccontextmanager
        async def connector(*_args):
            if failure == "offline":
                raise OSError("offline")
            if failure == "partial":
                original = peer.write
                async def fail(raw):
                    if raw[2] == 0x85:
                        raise OSError("disconnected during row transfer")
                    await original(raw)
                peer.write = fail
            yield peer
        await process_next(store, cfg, connector)
        result = store.get(submitted["id"])
        assert result["state"] == expected
        assert result["delivery_attempts"] == 1
        before = len(peer.commands)
        assert not await process_next(store, cfg, connector)
        assert len(peer.commands) == before
        assert store.submit(Submit(**request()), cfg)["id"] == submitted["id"]
    asyncio.run(run())
    store.db.close()


def test_body_limit(cfg):
    with TestClient(create_app(cfg, run_worker=False)) as client:
        response = client.post("/v2/printers/b1/jobs", headers=HEADERS, content=b" " * 12_000_001)
        assert response.status_code == 413


@pytest.mark.parametrize("key", ["simple", "a-job/artifact-v1", "a-job/retry/an-attempt", "a/key with spaces#?%"])
def test_idempotency_lookup_accepts_complete_encoded_key(cfg, key):
    with TestClient(create_app(cfg, run_worker=False)) as client:
        job = client.post("/v2/printers/b1/jobs", json=request(key), headers=HEADERS).json()
        found = client.get("/v2/jobs/by-idempotency/" + quote(key, safe=""), headers=HEADERS)
        assert found.status_code == 200
        assert found.json() == job
        assert client.get("/v2/jobs/" + job["id"], headers=HEADERS).json() == job


def test_lost_response_resolves_original_job_even_after_media_change(cfg):
    store = Store(cfg.data_dir / "jobs.sqlite3")
    job = store.submit(Submit(**request()), cfg)
    changed = cfg.model_copy(update={"width_mm": 40})
    assert store.submit(Submit(**request()), changed) == job
    store.db.close()


def test_queue_cancel_does_not_touch_hardware_and_transmitting_cannot_cancel(cfg):
    with TestClient(create_app(cfg, run_worker=False)) as client:
        queued = client.post("/v2/printers/b1/jobs", json=request(), headers=HEADERS).json()
        assert client.post(f"/v2/jobs/{queued['id']}/cancel", headers=HEADERS).status_code == 200
        running = client.post("/v2/printers/b1/jobs", json=request("running"), headers=HEADERS).json()
        # Mutate through the app event loop, as production endpoints do.
        async def mark_transmitting():
            running["state"] = "transmitting"
            client.app.state.store.save(running)
        client.portal.call(mark_transmitting)
        assert client.post(f"/v2/jobs/{running['id']}/cancel", headers=HEADERS).status_code == 409
