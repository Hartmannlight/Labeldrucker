from __future__ import annotations

from printer_fleet.discovery import AgentDiscoveryService
from printer_fleet.repository import FleetRepository


class FakeAgentClient:
    def __init__(self) -> None:
        self.available = True
        self.width_mm = 50

    def inspect(self, base_url):
        if not self.available:
            raise RuntimeError("offline")
        return {
            "id": "edge-berlin-1",
            "base_url": base_url.rstrip("/"),
            "available": True,
            "info": {"version": "1.0"},
            "printers": [
                {
                    "id": "usb-zebra",
                    "display_name": "Shipping Zebra",
                    "model": "ZD421",
                    "vendor": "Zebra",
                    "driver": "zpl",
                }
            ],
        }

    def configuration(self, base_url, agent_id, printer_id):
        assert (base_url, agent_id, printer_id) == (
            "http://edge:8080",
            "edge-berlin-1",
            "usb-zebra",
        )
        return {
            "media": {
                "state": {
                    "media": {
                        "width_mm": self.width_mm,
                        "height_mm": 30,
                        "color": {"name": "White", "hex": "#ffffff"},
                        "print_technology": "thermal_transfer",
                    }
                }
            },
            "device": {"profile": {"resolution_dpi": 300}},
        }


def test_discovery_and_registration_are_fleet_owned_and_durable(tmp_path):
    database = tmp_path / "fleet.sqlite3"
    repository = FleetRepository(database)
    repository.initialize()
    client = FakeAgentClient()
    discovery = AgentDiscoveryService(repository, client)

    observed = discovery.discover(["http://edge:8080/"])
    assert observed["agents"][0]["printers"][0]["registered_id"] is None
    registered = discovery.register(
        agent_id="edge-berlin-1",
        device_id="usb-zebra",
        public_id="shipping-zebra",
    )
    assert registered["connection"]["protocol"] == "print_agent"
    assert registered["media"]["loaded"]["width_mm"] == 50
    assert registered["registry"]["revision"] == 1

    client.width_mm = 62
    discovery.discover()
    refreshed = repository.get_printer("shipping-zebra")
    assert refreshed["media"]["loaded"]["width_mm"] == 62
    assert refreshed["registry"]["revision"] == 1
    assert refreshed["observation"]["source"] == "print_agent"

    exported = repository.export_printers()["printers"][0]
    assert exported["media"]["loaded"]["width_mm"] == 50
    assert "observation" not in exported

    patched = repository.patch_printer(
        "shipping-zebra", {"name": "Updated name"}, expected_revision=1
    )
    assert patched["name"] == "Updated name"
    assert patched["media"]["loaded"]["width_mm"] == 62
    assert patched["registry"]["revision"] == 2
    exported = repository.export_printers()["printers"][0]
    assert exported["media"]["loaded"]["width_mm"] == 50

    restarted = FleetRepository(database)
    restarted.initialize()
    saved_agent = restarted.get_agent("edge-berlin-1")
    assert saved_agent["printers"][0]["registered_id"] == "shipping-zebra"


def test_offline_agent_remains_registered_and_is_marked_unavailable(tmp_path):
    repository = FleetRepository(tmp_path / "fleet.sqlite3")
    repository.initialize()
    client = FakeAgentClient()
    discovery = AgentDiscoveryService(repository, client)
    discovery.discover(["http://edge:8080"])

    client.available = False
    result = discovery.discover()

    assert result["agents"][0]["available"] is False
    saved = repository.get_agent("edge-berlin-1")
    assert saved["available"] is False
    assert saved["printers"][0]["id"] == "usb-zebra"
