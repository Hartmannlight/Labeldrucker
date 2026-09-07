from __future__ import annotations

from pathlib import Path

import yaml
import scripts.pi_quickstart as quickstart

from scripts.pi_quickstart import (
    choose_device,
    configured_agent_printer_id,
    discover_usb_printers,
    duplicate_ipp_services,
    existing_assignment,
    existing_toml_string,
    ipp_get_printer_attributes,
    render_agent_config,
    render_avahi_service,
    render_env,
    render_udev_rule,
    require_root,
    secure_agent_config,
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
    assert "<port>8631</port>" in service
    assert "<port>18631</port>" in render_avahi_service(port=18631)


def test_linux_root_check_uses_os_geteuid(monkeypatch) -> None:
    monkeypatch.setattr(quickstart.os, "geteuid", lambda: 0, raising=False)
    require_root()


def test_agent_config_is_owner_and_container_group_readable(monkeypatch) -> None:
    config = Path("print-agent.toml")
    ownership = []
    modes = []
    monkeypatch.setattr(quickstart.os, "geteuid", lambda: 0, raising=False)
    monkeypatch.setenv("SUDO_UID", "1000")
    monkeypatch.setattr(
        quickstart.os,
        "chown",
        lambda path, uid, gid: ownership.append((path, uid, gid)),
        raising=False,
    )
    monkeypatch.setattr(Path, "chmod", lambda path, mode: modes.append((path, mode)))

    secure_agent_config(config, group_id=987)

    assert ownership == [(config, 1000, 987)]
    assert modes == [(config, 0o640)]


def test_quickstart_compose_is_pull_only_and_has_one_mdns_owner() -> None:
    compose = yaml.safe_load((ROOT / "deploy" / "compose.quickstart.yaml").read_text(encoding="utf-8"))
    services = compose["services"]

    assert all("build" not in service for service in services.values())
    assert services["printer-fleet"]["environment"]["PRINTER_FLEET_DATABASE"] == "/data/fleet.sqlite3"
    assert services["print-agent"]["volumes"][0] == "/dev/bus/usb:/dev/bus/usb"
    assert services["print-agent"]["device_cgroup_rules"] == ["c 189:* rmw"]
    assert "network_mode" not in services["ipp-gateway"]
    assert services["ipp-gateway"]["networks"] == ["backend"]
    assert services["ipp-gateway"]["ports"] == [
        "${PRINTHUB_IPP_BIND:-0.0.0.0}:${PRINTHUB_IPP_PORT:-8631}:8631"
    ]
    assert services["ipp-gateway"]["environment"]["PRINTHUB_IPP_MDNS_ENABLED"] == "1"
    assert "PRINTHUB_IPP_CONTAINER_BIND" not in services["ipp-gateway"]["environment"]
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
    assert configured_agent_printer_id(fixtures / "print-agent.toml") == "existing-zebra"


def test_ipp_check_sends_get_printer_attributes(monkeypatch) -> None:
    response = bytes.fromhex("020000000000000103")

    class Reply:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return None

        def read(self):
            return response

    def fake_open(request, timeout):
        assert request.headers["Content-type"] == "application/ipp"
        assert request.data[:4] == bytes.fromhex("0200000b")
        assert b"printer-uri" in request.data
        assert timeout == 5
        return Reply()

    monkeypatch.setattr("scripts.pi_quickstart.urlopen", fake_open)
    ipp_get_printer_attributes("127.0.0.1", 8631, advertised_host="printhub.local")


def test_duplicate_host_ipp_announcement_is_detected() -> None:
    fixtures = ROOT / "tests" / "fixtures" / "avahi"

    assert [path.name for path in duplicate_ipp_services(fixtures)] == ["old-ipp.service"]
