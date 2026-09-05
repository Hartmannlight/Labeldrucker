from __future__ import annotations

import base64
import hashlib

from fastapi.testclient import TestClient

from printer_fleet.api import create_app
from printer_fleet.auth import BearerCredentialAuthenticator, FleetPrincipal
from printer_fleet.domain import TransportReceipt
from printer_fleet.repository import FleetRepository
from printer_fleet.service import DeliveryService
from printer_fleet.transports import TransportRegistry


class AcceptingTransport:
    def send(self, payload, _printer):
        return TransportReceipt(bytes_accepted=len(payload.payload))


class UnexpectedStatusService:
    def read(self, _printer):
        raise AssertionError("Busy printers must not receive a status command")


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


def test_status_query_does_not_interleave_with_an_active_operation(tmp_path, monkeypatch):
    monkeypatch.setenv("PRINTER_FLEET_MDNS_ENABLED", "0")
    repository = FleetRepository(tmp_path / "operations.sqlite3")
    app = create_app(repository)
    app.state.status_service = UnexpectedStatusService()

    with TestClient(app) as client:
        created = client.put(
            "/v1/printers/network-zebra",
            json={
                "id": "network-zebra",
                "driver": "zpl",
                "connection": {"protocol": "raw_tcp", "host": "printer.example"},
                "capabilities": {"supports_status": True},
            },
        )
        assert created.status_code == 200
        owner = repository.acquire_printer_operation("network-zebra", kind="delivery")
        assert owner is not None

        response = client.get("/v1/printers/network-zebra/status")

        assert response.status_code == 409
        assert response.json()["detail"] == "Printer is busy"
        repository.release_printer_operation("network-zebra", owner)


def test_roles_and_sites_limit_catalog_delivery_and_administration(tmp_path, monkeypatch):
    monkeypatch.setenv("PRINTER_FLEET_MDNS_ENABLED", "0")
    repository = FleetRepository(tmp_path / "scopes.sqlite3")
    authenticator = BearerCredentialAuthenticator(
        [
            (
                "global-admin-token",
                FleetPrincipal("fleet-admin", frozenset({"admin"}), frozenset({"*"})),
            ),
            (
                "berlin-submit-token",
                FleetPrincipal(
                    "printhub-berlin",
                    frozenset({"submitter"}),
                    frozenset({"berlin"}),
                ),
            ),
            (
                "berlin-admin-token",
                FleetPrincipal(
                    "operator-berlin",
                    frozenset({"admin"}),
                    frozenset({"berlin"}),
                ),
            ),
        ]
    )
    app = create_app(repository, authenticator)
    app.state.delivery_service = DeliveryService(
        repository,
        transports=TransportRegistry({"raw_tcp": AcceptingTransport()}),
    )

    def headers(token):
        return {"Authorization": f"Bearer {token}"}

    with TestClient(app) as client:
        for printer_id, site in (("berlin-zebra", "berlin"), ("paris-zebra", "paris")):
            response = client.put(
                f"/v1/printers/{printer_id}",
                headers=headers("global-admin-token"),
                json={
                    "id": printer_id,
                    "site_id": site,
                    "driver": "zpl",
                    "connection": {"protocol": "raw_tcp", "host": f"{printer_id}.example"},
                },
            )
            assert response.status_code == 200

        visible = client.get(
            "/v1/printers",
            headers=headers("berlin-submit-token"),
        ).json()
        assert [printer["id"] for printer in visible] == ["berlin-zebra"]
        assert client.get(
            "/v1/printers/paris-zebra",
            headers=headers("berlin-submit-token"),
        ).status_code == 404
        assert client.put(
            "/v1/printers/not-allowed",
            headers=headers("berlin-submit-token"),
            json={
                "driver": "zpl",
                "connection": {"protocol": "raw_tcp", "host": "printer.example"},
            },
        ).status_code == 403

        payload = b"^XA^XZ"
        accepted = client.post(
            "/v1/deliveries",
            headers=headers("berlin-submit-token"),
            json={
                "printer_id": "berlin-zebra",
                "idempotency_key": "scoped/1",
                "artifact": {
                    "mime_type": "application/zpl",
                    "payload_base64": base64.b64encode(payload).decode("ascii"),
                    "checksum": f"sha256:{hashlib.sha256(payload).hexdigest()}",
                },
            },
        )
        assert accepted.status_code == 202
        paris = client.post(
            "/v1/deliveries",
            headers=headers("global-admin-token"),
            json={
                "printer_id": "paris-zebra",
                "idempotency_key": "scoped/paris",
                "artifact": {
                    "mime_type": "application/zpl",
                    "payload_base64": base64.b64encode(payload).decode("ascii"),
                    "checksum": f"sha256:{hashlib.sha256(payload).hexdigest()}",
                },
            },
        )
        assert paris.status_code == 202
        visible_deliveries = client.get(
            "/v1/deliveries?limit=1&state=transport_accepted",
            headers=headers("berlin-submit-token"),
        )
        assert visible_deliveries.status_code == 200
        assert [item["printer_id"] for item in visible_deliveries.json()] == ["berlin-zebra"]
        assert client.get(
            "/v1/deliveries?state=not-a-state",
            headers=headers("berlin-submit-token"),
        ).status_code == 422
        assert client.get(
            "/v1/deliveries?printer_id=paris-zebra",
            headers=headers("berlin-submit-token"),
        ).status_code == 404

        paused = client.post(
            "/v1/printers/berlin-zebra/pause",
            headers=headers("berlin-admin-token"),
            json={"reason": "Label roll replacement"},
        )
        assert paused.status_code == 200
        assert paused.json()["control"]["paused"] is True
        assert paused.json()["control"]["reason"] == "Label roll replacement"
        rejected_while_paused = client.post(
            "/v1/deliveries",
            headers=headers("berlin-submit-token"),
            json={
                "printer_id": "berlin-zebra",
                "idempotency_key": "scoped/paused",
                "artifact": {
                    "mime_type": "application/zpl",
                    "payload_base64": base64.b64encode(payload).decode("ascii"),
                    "checksum": f"sha256:{hashlib.sha256(payload).hexdigest()}",
                },
            },
        )
        assert rejected_while_paused.status_code == 409
        assert client.post(
            "/v1/printers/berlin-zebra/resume",
            headers=headers("berlin-admin-token"),
        ).json()["control"]["paused"] is False
        assert client.post(
            "/v1/deliveries",
            headers=headers("berlin-submit-token"),
            json={
                "printer_id": "paris-zebra",
                "idempotency_key": "scoped/2",
                "artifact": {
                    "mime_type": "application/zpl",
                    "payload_base64": base64.b64encode(payload).decode("ascii"),
                    "checksum": f"sha256:{hashlib.sha256(payload).hexdigest()}",
                },
            },
        ).status_code == 404

        assert client.get(
            "/v1/audit-records",
            headers=headers("berlin-admin-token"),
        ).status_code == 403
        assert client.get(
            "/metrics",
            headers=headers("berlin-admin-token"),
        ).status_code == 403
