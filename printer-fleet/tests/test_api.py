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


def test_api_catalog_and_delivery(tmp_path):
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
