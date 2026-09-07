from __future__ import annotations

from pathlib import Path

import yaml

from scripts.pi_quickstart import (
    choose_device,
    discover_usb_printers,
    duplicate_ipp_services,
    existing_assignment,
    existing_toml_string,
    render_agent_config,
    render_avahi_service,
    render_env,
    render_udev_rule,
)


ROOT = Path(__file__).resolve().parents[1]


SYSFS = ROOT / "tests" / "fixtures" / "usb-sysfs"


def test_usb_discovery_selects_printer_interface_and_stable_identity() -> None:
    printers = discover_usb_printers(SYSFS)

    assert len(printers) == 1
    assert choose_device(printers, None).serial == "GK42-123"
    config = render_agent_config(printers[0], "a" * 32, printer_id="gk420t")
    assert 'transport = "usb_bulk"' in config
    assert "webui_enabled = true" in config
    assert "usb_vendor_id = 2655" in config
    assert "usb_product_id = 163" in config
    assert 'usb_serial = "GK42-123"' in config
    assert "/dev/usb/lp" not in config


def test_host_assets_centralize_permissions_and_ipp_announcement() -> None:
    printer = discover_usb_printers(SYSFS)[0]

    rule = render_udev_rule(printer, "printhub-usb")
    service = render_avahi_service()

    assert 'ATTR{idVendor}=="0a5f"' in rule
    assert 'ATTR{serial}=="GK42-123"' in rule
    assert 'GROUP="printhub-usb"' in rule
    assert service.count("<_ipp._tcp>") == 0
    assert service.count("<type>_ipp._tcp</type>") == 1
    assert "rp=ipp/print" in service


def test_quickstart_compose_is_pull_only_and_has_one_mdns_owner() -> None:
    compose = yaml.safe_load((ROOT / "deploy" / "compose.quickstart.yaml").read_text(encoding="utf-8"))
    services = compose["services"]

    assert all("build" not in service for service in services.values())
    assert services["printer-fleet"]["environment"]["PRINTER_FLEET_DATABASE"] == "/data/fleet.sqlite3"
    assert services["print-agent"]["volumes"][0] == "/dev/bus/usb:/dev/bus/usb"
    assert services["print-agent"]["device_cgroup_rules"] == ["c 189:* rmw"]
    assert services["ipp-gateway"]["network_mode"] == "host"
    assert services["ipp-gateway"]["environment"]["PRINTHUB_IPP_MDNS_ENABLED"] == "0"
    assert services["ipp-gateway"]["environment"]["PRINTHUB_IPP_NAME"] == "${PRINTHUB_IPP_NAME:-PrintHub Label Printer}"


def test_generated_environment_connects_optional_agent_without_media_in_name() -> None:
    environment = render_env(
        service_token="service",
        admin_token="admin",
        usb_gid=987,
        printer_id="gk420t",
    )

    assert "PRINTER_FLEET_AGENT_URLS=http://print-agent:8080" in environment
    assert "PRINT_AGENT_USB_GID=987" in environment
    assert "PRINTHUB_IPP_NAME=PrintHub Label Printer" in environment
    assert "60x30" not in environment


def test_existing_secrets_are_reused() -> None:
    fixtures = ROOT / "tests" / "fixtures"
    assert existing_assignment(fixtures / "quickstart.env", "PRINTHUB_FLEET_API_TOKEN") == "keep-me"
    assert existing_toml_string(fixtures / "print-agent.toml", "admin_token") == "also-keep-me"


def test_duplicate_host_ipp_announcement_is_detected() -> None:
    fixtures = ROOT / "tests" / "fixtures" / "avahi"

    assert [path.name for path in duplicate_ipp_services(fixtures)] == ["old-ipp.service"]
