from __future__ import annotations

import base64
import hashlib

from fastapi.testclient import TestClient

from printer_fleet.api import create_app
from printer_fleet.domain import TransportReceipt
from printer_fleet.repository import FleetRepository
from printer_fleet.service import DeliveryService
from printer_fleet.transports import TransportRegistry


class AcceptingTransport:
    def send(self, payload, _printer):
        return TransportReceipt(bytes_accepted=len(payload.payload))


def test_api_catalog_and_delivery(tmp_path, monkeypatch):
    monkeypatch.setenv("PRINTER_FLEET_MDNS_ENABLED", "0")
    repository = FleetRepository(tmp_path / "fleet.sqlite3")
    app = create_app(repository)
    app.state.delivery_service = DeliveryService(
        repository,
        transports=TransportRegistry({"raw_tcp": AcceptingTransport()}),
    )
    with TestClient(app) as client:
        printer = {
            "id": "zebra-1",
            "driver": "zpl",
            "connection": {"protocol": "raw_tcp", "host": "unused"},
            "enabled": True,
        }
        assert client.put("/v1/printers/zebra-1", json=printer).status_code == 200
        catalog_printer = client.get("/v1/printers/zebra-1").json()
        assert catalog_printer["registry"]["revision"] == 1
        assert "connection" not in catalog_printer
        patched = client.patch(
            "/v1/printers/zebra-1",
            json={"revision": 1, "settings": {"name": "Packing line"}},
        )
        assert patched.status_code == 200
        assert patched.json()["name"] == "Packing line"
        assert patched.json()["registry"]["revision"] == 2
        assert client.patch(
            "/v1/printers/zebra-1",
            json={"revision": 1, "settings": {"name": "Stale edit"}},
        ).status_code == 409
        payload = b"^XA^XZ"
        response = client.post(
            "/v1/deliveries",
            json={
                "printer_id": "zebra-1",
                "idempotency_key": "api-job/1",
                "artifact": {
                    "mime_type": "application/zpl",
                    "payload_base64": base64.b64encode(payload).decode("ascii"),
                    "checksum": f"sha256:{hashlib.sha256(payload).hexdigest()}",
                },
            },
        )
        assert response.status_code == 202, response.text
        assert response.json()["state"] == "transport_accepted"


def test_service_token_and_correlation_id_protect_v1_api(tmp_path, monkeypatch):
    monkeypatch.setenv("PRINTER_FLEET_MDNS_ENABLED", "0")
    monkeypatch.setenv("PRINTER_FLEET_API_TOKEN", "fleet-secret")
    app = create_app(FleetRepository(tmp_path / "protected.sqlite3"))

    with TestClient(app) as client:
        denied = client.get("/v1/printers")
        assert denied.status_code == 401
        assert denied.headers["X-Correlation-ID"]
        assert client.get("/health").status_code == 200

        accepted = client.get(
            "/v1/printers",
            headers={
                "Authorization": "Bearer fleet-secret",
                "X-Correlation-ID": "thingdex-print-123",
            },
        )
        assert accepted.status_code == 200
        assert accepted.headers["X-Correlation-ID"] == "thingdex-print-123"

        created = client.put(
            "/v1/printers/audited",
            headers={
                "Authorization": "Bearer fleet-secret",
                "X-Correlation-ID": "audit-123",
            },
            json={
                "id": "audited",
                "driver": "zpl",
                "connection": {"protocol": "raw_tcp", "host": "printer.test"},
            },
        )
        assert created.status_code == 200
        audit = client.get(
            "/v1/audit-records",
            headers={"Authorization": "Bearer fleet-secret"},
        ).json()
        assert any(
            record["correlation_id"] == "audit-123"
            and record["path"] == "/v1/printers/audited"
            and record["status_code"] == 200
            for record in audit
        )
        assert any(record["actor"] == "anonymous" and record["status_code"] == 401 for record in audit)

        assert client.get("/metrics").status_code == 401
        metrics = client.get(
            "/metrics", headers={"Authorization": "Bearer fleet-secret"}
        )
        assert metrics.status_code == 200
        assert "printer_fleet_printers 1" in metrics.text


def test_registry_rejects_invalid_network_endpoint_before_persisting(tmp_path, monkeypatch):
    monkeypatch.setenv("PRINTER_FLEET_MDNS_ENABLED", "0")
    app = create_app(FleetRepository(tmp_path / "validation.sqlite3"))

    with TestClient(app) as client:
        response = client.put(
            "/v1/printers/serial-zebra",
            json={
                "id": "serial-zebra",
                "driver": "zpl",
                "connection": {
                    "protocol": "serial_over_tcp",
                    "host": "bridge.example",
                },
            },
        )

        assert response.status_code == 400
        assert "explicit connection.port" in response.json()["detail"]
        assert client.get("/v1/printers/serial-zebra").status_code == 404
