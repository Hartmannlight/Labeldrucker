"""Integration across the real PrintHub raster API, HTTP adapter and B1 queue."""
import base64
from contextlib import asynccontextmanager
import io
from urllib.parse import urlsplit

from fastapi.testclient import TestClient
from PIL import Image
import pytest
from fastapi import HTTPException

from niimbot_service.app import Settings, create_app, process_next
from niimbot_service.protocol import B1Protocol
from zplgrid import api
from zplgrid.printer_services.http import HttpPrintServiceAdapter


@pytest.mark.parametrize("retry_offline", [False, True])
def test_image_job_reaches_b1_queue_without_zpl_and_reconciles(tmp_path, monkeypatch, retry_offline):
    token = "pipeline-test-token-with-32-characters"
    settings = Settings(token=token, data_dir=tmp_path / "device", address="test", width_mm=1, height_mm=1)
    monkeypatch.setenv("ZPLGRID_PRINT_JOBS_DIR", str(tmp_path / "printhub"))
    monkeypatch.setenv("PRINTHUB_BACKGROUND_JOBS", "0")
    monkeypatch.setenv("ZPLGRID_ENABLE_LABELARY_API", "0")
    monkeypatch.setenv("ZPLGRID_ENABLE_LABELARY_PREVIEW", "0")
    captured = []

    @asynccontextmanager
    async def connector(*_args):
        yield object()

    async def device_print(_self, pages, copies, **_kwargs):
        captured.append((pages, copies))
        if retry_offline and len(captured) == 1:
            raise OSError("Offline before print start")

    monkeypatch.setattr(B1Protocol, "print_pages", device_print)
    with TestClient(create_app(settings, run_worker=False)) as service:
        def http_request(method, url, **kwargs):
            kwargs.pop("timeout", None)
            return service.request(method, urlsplit(url).path, **kwargs)

        monkeypatch.setattr("zplgrid.printer_services.http.requests.request", http_request)
        adapter = HttpPrintServiceAdapter("http://niimbot", api_token=token)
        printer = adapter.get_printer("b1")
        monkeypatch.setattr(api, "_get_printer", lambda _: printer)
        monkeypatch.setattr(api, "_printer_services", lambda: adapter)
        image = Image.new("RGB", (8, 8), "white")
        image.putpixel((0, 0), (0, 0, 0))
        image.putpixel((7, 7), (0, 0, 0))
        png = io.BytesIO(); image.save(png, format="PNG")
        body = api.RasterPrintJobCreateRequest(printer_id="b1", copies=2, dither="none",
                idempotency_key="image-designer-pipeline", pages=[api.RasterPageRequest(
                    mime_type="image/png", data_base64=base64.b64encode(png.getvalue()).decode(), width_mm=1, height_mm=1)])
        job = api.create_raster_print_job(body)
        assert job.status == "queued"
        assert job.downstream_job_state == "queued"
        assert service.portal.call(process_next, service.app.state.store, settings, connector)
        if retry_offline:
            assert api.get_print_job(job.id).status == "failed"
            retried = api.retry_print_job(job.id)
            assert retried.downstream_job_id != job.downstream_job_id
            with pytest.raises(HTTPException) as duplicate_retry:
                api.retry_print_job(job.id)
            assert duplicate_retry.value.status_code == 409
            headers = {"Authorization": "Bearer " + token}
            old = service.get("/v2/jobs/" + job.downstream_job_id, headers=headers).json()
            new = service.get("/v2/jobs/" + retried.downstream_job_id, headers=headers).json()
            assert old["state"] == "failed"
            assert new["idempotency_key"] != old["idempotency_key"]
            assert service.portal.call(process_next, service.app.state.store, settings, connector)
        pages, copies = captured[0]
        assert copies == 2
        assert pages[0].width == pages[0].height == 8
        assert pages[0].bits == b"\x80" + bytes(6) + b"\x01"
        observed = api.get_print_job(job.id)
        assert observed.downstream_job_state == "completed_observed"
        repeated = api.create_raster_print_job(body)
        assert repeated.id == job.id
        assert not service.portal.call(process_next, service.app.state.store, settings, connector)
        assert len(captured) == (2 if retry_offline else 1)
