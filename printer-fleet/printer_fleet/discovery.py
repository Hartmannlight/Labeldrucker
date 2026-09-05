from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
import os
import time
from typing import Any, Iterable

from .agent import PrintAgentClient
from .repository import FleetRepository


class AgentDiscoveryService:
    def __init__(
        self,
        repository: FleetRepository,
        client: PrintAgentClient | None = None,
        discover_mdns: bool = False,
    ) -> None:
        self.repository = repository
        self.client = client or PrintAgentClient()
        self.discover_mdns = discover_mdns

    @staticmethod
    def _mdns_urls(timeout_seconds: float = 0.8) -> list[str]:
        try:
            from zeroconf import ServiceBrowser, ServiceListener, Zeroconf
        except ImportError:
            return []
        found: list[str] = []

        class Listener(ServiceListener):
            def add_service(self, zeroconf, service_type, name):
                info = zeroconf.get_service_info(service_type, name, timeout=800)
                if info is None:
                    return
                for address in info.parsed_scoped_addresses():
                    host = f"[{address}]" if ":" in address else address
                    url = f"http://{host}:{info.port}"
                    if url not in found:
                        found.append(url)

            def update_service(self, zeroconf, service_type, name):
                self.add_service(zeroconf, service_type, name)

            def remove_service(self, _zeroconf, _service_type, _name):
                return

        try:
            zeroconf = Zeroconf()
        except OSError:
            return []
        try:
            listener = Listener()
            ServiceBrowser(zeroconf, "_print-agent._tcp.local.", listener)
            ServiceBrowser(zeroconf, "_zpl-agent._tcp.local.", listener)
            time.sleep(timeout_seconds)
        finally:
            zeroconf.close()
        return found

    def discover(self, extra_urls: Iterable[str] = ()) -> dict[str, Any]:
        configured = os.getenv("PRINTER_FLEET_AGENT_URLS", "").split(",")
        known = [agent["base_url"] for agent in self.repository.list_agents()]
        urls: list[str] = []
        discovered = self._mdns_urls() if self.discover_mdns else []
        for raw in [*known, *configured, *extra_urls, *discovered]:
            url = str(raw).strip().rstrip("/")
            if url and url not in urls:
                urls.append(url)

        def inspect(url: str) -> dict[str, Any]:
            try:
                return self.client.inspect(url)
            except Exception as exc:
                self.repository.mark_agent_unavailable(url, str(exc))
                return {"base_url": url, "available": False, "error": str(exc), "printers": []}

        with ThreadPoolExecutor(max_workers=4) as pool:
            observations = list(pool.map(inspect, urls))
        results = []
        identities: set[str] = set()
        for observation in observations:
            if not observation.get("available"):
                results.append(observation)
                continue
            agent_id = str(observation["id"])
            if agent_id in identities:
                continue
            identities.add(agent_id)
            recorded = self.repository.record_agent(observation)
            for device in recorded["printers"]:
                registered_id = device.get("registered_id")
                if not registered_id:
                    continue
                try:
                    configuration = self.client.configuration(
                        recorded["base_url"], agent_id, str(device["id"])
                    )
                    media, alignment, capabilities = self._observation(configuration)
                    self.repository.record_printer_observation(
                        str(registered_id),
                        media=media,
                        alignment=alignment,
                        capabilities=capabilities,
                        source="print_agent",
                    )
                except (KeyError, TypeError, ValueError, RuntimeError):
                    pass
            results.append(self.repository.get_agent(agent_id))
        return {"agents": results}

    @staticmethod
    def _observation(
        configuration: dict[str, Any],
    ) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
        media_state = (configuration.get("media") or {}).get("state") or {}
        definition = media_state.get("media") or {}
        device_data = configuration.get("device") or {}
        observation = device_data.get("observation") or {}
        profile = device_data.get("profile") or {}
        dpi = observation.get("resolution_dpi") or profile.get("resolution_dpi")
        if not definition or not dpi:
            raise ValueError("Configure loaded media and resolution in PrintAgent first")
        color = definition.get("color") or {}
        media = {
            "loaded": {
                "width_mm": float(definition["width_mm"]),
                "height_mm": float(definition["height_mm"]),
                "color": color.get("name") or "white",
                "color_hex": color.get("hex"),
                "type": definition.get("print_technology") or "thermal",
            },
            "authority": {"source": "print_agent", "state": "loaded"},
            "agent_state": media_state,
        }
        alignment = {"dpi": int(dpi), "offset_x_mm": 0, "offset_y_mm": 0}
        capabilities = {
            "supports_status": True,
            "supports_graphics": True,
            "supports_cut": bool(profile.get("cutter", False)),
        }
        return media, alignment, capabilities

    def register(
        self,
        *,
        agent_id: str,
        device_id: str,
        public_id: str,
        name: str | None = None,
    ) -> dict[str, Any]:
        agent, device = self.repository.get_agent_device(agent_id, device_id)
        if device.get("registered_id"):
            return self.repository.get_printer(str(device["registered_id"]))
        configuration = self.client.configuration(agent["base_url"], agent_id, device_id)
        media, alignment, capabilities = self._observation(configuration)
        printer = {
            "id": public_id,
            "name": name or device.get("display_name") or device_id,
            "model": device.get("model") or "PrintAgent device",
            "vendor": device.get("vendor") or "Unknown",
            "driver": device.get("driver") or "zpl",
            "connection": {
                "protocol": "print_agent",
                "base_url": agent["base_url"],
                "agent_id": agent_id,
                "printer_id": device_id,
                "timeout_ms": 10000,
            },
            "media": media,
            "alignment": alignment,
            "defaults": {"copies": 1, "rotation": 0},
            "capabilities": capabilities,
            "enabled": True,
        }
        created = self.repository.put_printer(printer)
        return self.repository.record_printer_observation(
            public_id,
            media=media,
            alignment=alignment,
            capabilities=capabilities,
            source="print_agent",
        )
