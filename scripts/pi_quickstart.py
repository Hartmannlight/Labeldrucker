#!/usr/bin/env python3
"""Prepare a reconnect-safe PrintHub quickstart on Debian/Raspberry Pi OS."""

from __future__ import annotations

import argparse
from dataclasses import dataclass
import json
import os
from pathlib import Path
import re
import secrets
import shutil
import subprocess
import sys
from urllib.error import URLError
from urllib.request import Request, urlopen

try:
    import grp
except ImportError:  # pragma: no cover - Windows can render/test but cannot install.
    grp = None  # type: ignore[assignment]


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_SYSFS = Path("/sys/bus/usb/devices")
SAFE_ID = re.compile(r"[^a-zA-Z0-9_-]+")


@dataclass(frozen=True)
class UsbPrinter:
    path: Path
    vendor_id: int
    product_id: int
    serial: str
    manufacturer: str
    product: str

    @property
    def label(self) -> str:
        name = " ".join(value for value in (self.manufacturer, self.product) if value)
        return f"{name or 'USB printer'} ({self.vendor_id:04x}:{self.product_id:04x}, {self.serial or 'no serial'})"


def _read(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8").strip()
    except OSError:
        return ""


def discover_usb_printers(sysfs_root: Path = DEFAULT_SYSFS) -> list[UsbPrinter]:
    devices: list[UsbPrinter] = []
    if not sysfs_root.is_dir():
        return devices
    for path in sorted(sysfs_root.iterdir()):
        vendor = _read(path / "idVendor")
        product = _read(path / "idProduct")
        if not vendor or not product:
            continue
        device_class = _read(path / "bDeviceClass").lower()
        interface_paths = list(sysfs_root.glob(f"{path.name}:*"))
        # The nested form is also convenient for portable test fixtures.
        interface_paths.extend((path / "interfaces").glob("*"))
        interface_is_printer = any(
            _read(interface / "bInterfaceClass").lower() == "07"
            for interface in interface_paths
        )
        if device_class != "07" and not interface_is_printer:
            continue
        devices.append(
            UsbPrinter(
                path=path,
                vendor_id=int(vendor, 16),
                product_id=int(product, 16),
                serial=_read(path / "serial"),
                manufacturer=_read(path / "manufacturer"),
                product=_read(path / "product"),
            )
        )
    return devices


def choose_device(devices: list[UsbPrinter], index: int | None) -> UsbPrinter:
    if not devices:
        raise RuntimeError("No USB printer-class device was found")
    if index is not None:
        if index < 1 or index > len(devices):
            raise RuntimeError(f"--device must be between 1 and {len(devices)}")
        return devices[index - 1]
    if len(devices) == 1:
        return devices[0]
    choices = "\n".join(f"  {number}: {device.label}" for number, device in enumerate(devices, 1))
    raise RuntimeError(f"Multiple USB printers found; rerun with --device NUMBER:\n{choices}")


def toml_string(value: str) -> str:
    return '"' + value.replace("\\", "\\\\").replace('"', '\\"') + '"'


def printer_slug(device: UsbPrinter) -> str:
    raw = device.product or f"usb-{device.vendor_id:04x}-{device.product_id:04x}"
    return SAFE_ID.sub("-", raw.strip()).strip("-").lower() or "usb-printer"


def existing_assignment(path: Path, key: str) -> str | None:
    if not path.is_file():
        return None
    prefix = f"{key}="
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.startswith(prefix):
            return line[len(prefix) :]
    return None


def existing_toml_string(path: Path, key: str) -> str | None:
    if not path.is_file():
        return None
    match = re.search(rf"(?m)^{re.escape(key)}\s*=\s*\"([^\"]+)\"\s*$", path.read_text(encoding="utf-8"))
    return match.group(1) if match else None


def configured_agent_printer_id(path: Path) -> str | None:
    """Return the configured Agent printer ID instead of deriving a new one."""
    return existing_toml_string(path, "id")


def render_agent_config(device: UsbPrinter, token: str, *, printer_id: str) -> str:
    serial_line = f"usb_serial = {toml_string(device.serial)}\n" if device.serial else ""
    return f'''listen = "0.0.0.0:8080"
data_dir = "/var/lib/zpl-agent"
storage_mode = "full"
webui_enabled = true
admin_token = {toml_string(token)}
mdns_enabled = false
poll_interval_secs = 30
capability_poll_interval_secs = 300
reconnect_debounce_secs = 5
hardware_counters = "prefer"

[[printers]]
id = {toml_string(printer_id)}
display_name = {toml_string(device.product or "USB label printer")}
device = ""
transport = "usb_bulk"
driver = "zpl"
model_hint = {toml_string(device.product or "USB label printer")}
usb_vendor_id = {device.vendor_id}
usb_product_id = {device.product_id}
{serial_line}first_byte_timeout_ms = 5000
idle_timeout_ms = 500
write_timeout_ms = 30000

[printers.device_profile]
resolution_dpi = 203
max_width_dots = 832
max_length_dots = 32000
max_speed_ips = 6
max_offset_dots = 64
thermal_transfer = false
peel_off = false
cutter = false
'''


def render_env(*, service_token: str, admin_token: str, usb_gid: int, printer_id: str) -> str:
    return f'''COMPOSE_PROJECT_NAME=printhub
PRINTHUB_FLEET_API_TOKEN={service_token}
PRINTER_FLEET_ADMIN_TOKEN={admin_token}
PRINTHUB_API_BIND=127.0.0.1
PRINTHUB_API_PORT=8001
PRINTHUB_STUDIO_BIND=0.0.0.0
PRINTHUB_STUDIO_PORT=8088
PRINTER_FLEET_CONSOLE_BIND=0.0.0.0
PRINTER_FLEET_CONSOLE_PORT=8089
PRINTHUB_PUBLIC_HOST=printhub.local
PRINTER_FLEET_AGENT_URLS=http://print-agent:8080
PRINTER_FLEET_MEDIA_MISMATCH_TOLERANCE_MM=1.0
PRINT_AGENT_CONFIG_SOURCE=./state/print-agent.toml
PRINT_AGENT_UID=999
PRINT_AGENT_USB_GID={usb_gid}
PRINT_AGENT_PORT=8090
PRINTHUB_IPP_PORT=8631
PRINTHUB_IPP_BIND=0.0.0.0
PRINTHUB_IPP_ADVERTISED_HOST=printhub.local
PRINTHUB_IPP_NAME=PrintHub Label Printer
PRINTHUB_IPP_PRINTER_ID={printer_id}
PRINTHUB_MAX_LABELS_PER_JOB=25
TZ=Europe/Berlin
'''


def render_udev_rule(device: UsbPrinter, group: str) -> str:
    matches = [
        'SUBSYSTEM=="usb"',
        f'ATTR{{idVendor}}=="{device.vendor_id:04x}"',
        f'ATTR{{idProduct}}=="{device.product_id:04x}"',
    ]
    if device.serial:
        matches.append(f'ATTR{{serial}}=="{device.serial}"')
    return ", ".join(matches + [f'GROUP="{group}"', 'MODE="0660"']) + "\n"


def render_avahi_service(*, port: int = 8631) -> str:
    return f'''<?xml version="1.0" standalone="no"?>
<!DOCTYPE service-group SYSTEM "avahi-service.dtd">
<service-group>
  <name>PrintHub Label Printer</name>
  <service>
    <type>_ipp._tcp</type>
    <port>{port}</port>
    <txt-record>rp=ipp/print</txt-record>
    <txt-record>pdl=application/pdf,image/png,image/jpeg,image/pwg-raster,image/urf</txt-record>
    <txt-record>ty=PrintHub Label Printer</txt-record>
    <txt-record>note=Managed by PrintHub</txt-record>
  </service>
</service-group>
'''


def atomic_write(path: Path, content: str, mode: int = 0o600) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(content, encoding="utf-8")
    temporary.chmod(mode)
    temporary.replace(path)


def ensure_group(name: str) -> int:
    if grp is None:
        raise RuntimeError("Linux group management is only available on Linux")
    try:
        return grp.getgrnam(name).gr_gid
    except KeyError:
        subprocess.run(["groupadd", "--system", name], check=True)
        return grp.getgrnam(name).gr_gid


def require_root() -> None:
    if not hasattr(os, "geteuid") or os.geteuid() != 0:
        raise RuntimeError("--install-host must be run as root (use sudo)")


def duplicate_ipp_services(
    directory: Path, *, port: int = 8631, managed_name: str = "printhub-ipp.service"
) -> list[Path]:
    if not directory.is_dir():
        return []
    duplicates = []
    for path in directory.glob("*.service"):
        if path.name == managed_name:
            continue
        content = _read(path)
        if "<type>_ipp._tcp</type>" in content and f"<port>{port}</port>" in content:
            duplicates.append(path)
    return sorted(duplicates)


def install_host_files(state_dir: Path, *, reload_services: bool) -> None:
    require_root()
    avahi_directory = Path("/etc/avahi/services")
    service = _read(state_dir / "host" / "printhub-ipp.service")
    port_match = re.search(r"<port>(\d+)</port>", service)
    if not port_match:
        raise RuntimeError("Generated Avahi service has no valid port")
    port = int(port_match.group(1))
    duplicates = duplicate_ipp_services(avahi_directory, port=port)
    if duplicates:
        names = ", ".join(str(path) for path in duplicates)
        raise RuntimeError(
            f"Another IPP announcement already owns port {port}: {names}. "
            "Disable it explicitly before installing PrintHub discovery."
        )
    shutil.copyfile(state_dir / "host" / "70-printhub-usb.rules", "/etc/udev/rules.d/70-printhub-usb.rules")
    shutil.copyfile(state_dir / "host" / "printhub-ipp.service", avahi_directory / "printhub-ipp.service")
    if reload_services:
        subprocess.run(["udevadm", "control", "--reload-rules"], check=True)
        subprocess.run(["udevadm", "trigger", "--subsystem-match=usb"], check=True)
        subprocess.run(["systemctl", "restart", "avahi-daemon"], check=True)


def secure_agent_config(path: Path, *, group_id: int) -> None:
    """Allow only the local owner and the container's mapped USB group to read."""
    require_root()
    owner_id = int(os.getenv("SUDO_UID", "0"))
    os.chown(path, owner_id, group_id)
    path.chmod(0o640)


def _api_data(url: str, *, method: str = "GET") -> object:
    request = Request(url, method=method, data=b"" if method == "POST" else None)
    with urlopen(request, timeout=5) as response:
        payload = json.load(response)
    if isinstance(payload, dict) and "data" in payload:
        return payload["data"]
    return payload


def _ipp_attribute(tag: int, name: str, value: str) -> bytes:
    encoded_name = name.encode("ascii")
    encoded_value = value.encode("utf-8")
    return (
        bytes([tag])
        + len(encoded_name).to_bytes(2, "big")
        + encoded_name
        + len(encoded_value).to_bytes(2, "big")
        + encoded_value
    )


def ipp_get_printer_attributes(
    host: str, port: int, *, advertised_host: str
) -> None:
    """Perform a real IPP Get-Printer-Attributes operation without CUPS tools."""
    printer_uri = f"ipp://{advertised_host}:{port}/ipp/print"
    payload = (
        bytes.fromhex("0200000b00000001")
        + bytes([0x01])
        + _ipp_attribute(0x47, "attributes-charset", "utf-8")
        + _ipp_attribute(0x48, "attributes-natural-language", "en")
        + _ipp_attribute(0x45, "printer-uri", printer_uri)
        + bytes([0x03])
    )
    request = Request(
        f"http://{host}:{port}/ipp/print",
        data=payload,
        method="POST",
        headers={"Content-Type": "application/ipp"},
    )
    with urlopen(request, timeout=5) as response:
        body = response.read()
    if len(body) < 8 or body[:2] not in {b"\x01\x01", b"\x02\x00"}:
        raise RuntimeError("IPP endpoint returned a malformed response")
    status = int.from_bytes(body[2:4], "big")
    if status > 0x00FF:
        raise RuntimeError(f"IPP Get-Printer-Attributes failed with status 0x{status:04x}")


def check_installation(
    device: UsbPrinter, environment: Path, agent_config: Path
) -> bool:
    printer_id = existing_assignment(environment, "PRINTHUB_IPP_PRINTER_ID")
    agent_device_id = configured_agent_printer_id(agent_config)
    if not printer_id:
        raise RuntimeError("deploy/quickstart.env is missing PRINTHUB_IPP_PRINTER_ID")
    if not agent_device_id:
        raise RuntimeError("PrintAgent configuration is missing a printer ID")
    agent_port = int(existing_assignment(environment, "PRINT_AGENT_PORT") or "8090")
    api_port = int(existing_assignment(environment, "PRINTHUB_API_PORT") or "8001")
    ipp_port = int(existing_assignment(environment, "PRINTHUB_IPP_PORT") or "8631")
    advertised_host = (
        existing_assignment(environment, "PRINTHUB_IPP_ADVERTISED_HOST")
        or "printhub.local"
    )
    checks: list[tuple[str, bool, str]] = [
        ("USB detected", True, device.label),
    ]
    try:
        printers = _api_data(f"http://127.0.0.1:{agent_port}/v1/printers")
        ids = [str(item.get("id")) for item in printers if isinstance(item, dict)] if isinstance(printers, list) else []
        checks.append(("Agent running", agent_device_id in ids, f"reported devices: {', '.join(ids) or 'none'}"))
        configuration = _api_data(
            f"http://127.0.0.1:{agent_port}/v1/printers/{agent_device_id}/configuration"
        )
        media_ready = bool(
            isinstance(configuration, dict)
            and ((configuration.get("media") or {}).get("state") or {}).get("media")
        )
        checks.append(("Media configured", media_ready, "PrintAgent media ledger"))
        _api_data(
            f"http://127.0.0.1:{agent_port}/v1/printers/{agent_device_id}/probe",
            method="POST",
        )
        checks.append(("Device connection", True, "non-printing probe completed"))
    except (OSError, ValueError) as exc:
        checks.append(("Agent/device API", False, str(exc)))
    try:
        printer = _api_data(f"http://127.0.0.1:{api_port}/v1/printers/{printer_id}")
        checks.append(("Fleet registration", isinstance(printer, dict), printer_id))
    except (OSError, ValueError) as exc:
        checks.append(("Fleet registration", False, str(exc)))
    try:
        ipp_get_printer_attributes(
            "127.0.0.1", ipp_port, advertised_host=advertised_host
        )
        checks.append(("IPP functional", True, f"Get-Printer-Attributes on :{ipp_port}"))
    except (OSError, RuntimeError, URLError) as exc:
        checks.append(("IPP reachable", False, str(exc)))
    for name, passed, detail in checks:
        print(f"[{'OK' if passed else 'FAIL'}] {name}: {detail}")
    print("[MANUAL] Test label: transport acceptance and visible output are separate confirmations")
    return all(passed for _, passed, _ in checks)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sysfs-root", type=Path, default=DEFAULT_SYSFS)
    parser.add_argument("--device", type=int, help="1-based device number when multiple printers are attached")
    parser.add_argument("--state-dir", type=Path, default=ROOT / "deploy" / "state")
    parser.add_argument("--usb-group", default="printhub-usb")
    parser.add_argument("--usb-gid", type=int, help="existing host group GID (created automatically with --install-host)")
    parser.add_argument("--list", action="store_true", help="list detected USB printers without changing files")
    parser.add_argument("--check", action="store_true", help="verify USB, Agent, media, Fleet and IPP without printing")
    parser.add_argument("--install-host", action="store_true", help="install udev and Avahi files; requires root")
    parser.add_argument(
        "--reconfigure",
        action="store_true",
        help="explicitly replace existing site configuration while retaining tokens",
    )
    parser.add_argument("--no-reload", action="store_true", help="install host files without reloading udev/Avahi")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    try:
        devices = discover_usb_printers(args.sysfs_root)
        if args.list:
            if not devices:
                print("No USB printer-class device was found")
                return 1
            for number, detected in enumerate(devices, 1):
                print(f"{number}: {detected.label}")
            return 0
        device = choose_device(devices, args.device)
        environment = ROOT / "deploy" / "quickstart.env"
        agent_config = args.state_dir / "print-agent.toml"
        if args.check:
            return 0 if check_installation(device, environment, agent_config) else 1
        gid = args.usb_gid
        if gid is None:
            gid = ensure_group(args.usb_group) if args.install_host else 999
        existing_printer_id = configured_agent_printer_id(agent_config)
        printer_id = existing_printer_id or printer_slug(device)
        if agent_config.exists() != environment.exists() and not args.reconfigure:
            raise RuntimeError(
                "Site configuration is incomplete; restore both quickstart.env and "
                "print-agent.toml or use --reconfigure explicitly"
            )
        agent_token = existing_toml_string(agent_config, "admin_token") or secrets.token_urlsafe(32)
        service_token = existing_assignment(environment, "PRINTHUB_FLEET_API_TOKEN") or secrets.token_urlsafe(32)
        admin_token = existing_assignment(environment, "PRINTER_FLEET_ADMIN_TOKEN") or secrets.token_urlsafe(32)
        if not agent_config.exists() or args.reconfigure:
            atomic_write(
                agent_config,
                render_agent_config(device, agent_token, printer_id=printer_id),
            )
        if not environment.exists() or args.reconfigure:
            atomic_write(
                environment,
                render_env(
                    service_token=service_token,
                    admin_token=admin_token,
                    usb_gid=gid,
                    printer_id=printer_id,
                ),
            )
        configured_gid = int(
            existing_assignment(environment, "PRINT_AGENT_USB_GID") or str(gid)
        )
        if configured_gid != gid:
            raise RuntimeError(
                f"quickstart.env maps USB group {configured_gid}, but host group "
                f"{args.usb_group!r} is {gid}; correct the site configuration "
                "before starting containers"
            )
        ipp_port = int(existing_assignment(environment, "PRINTHUB_IPP_PORT") or "8631")
        udev_rule = args.state_dir / "host" / "70-printhub-usb.rules"
        avahi_service = args.state_dir / "host" / "printhub-ipp.service"
        if not udev_rule.exists() or args.reconfigure:
            atomic_write(udev_rule, render_udev_rule(device, args.usb_group), 0o644)
        if not avahi_service.exists() or args.reconfigure:
            atomic_write(avahi_service, render_avahi_service(port=ipp_port), 0o644)
        if args.install_host:
            secure_agent_config(agent_config, group_id=gid)
            install_host_files(args.state_dir, reload_services=not args.no_reload)
            if os.getenv("SUDO_UID") and os.getenv("SUDO_GID"):
                os.chown(
                    environment,
                    int(os.environ["SUDO_UID"]),
                    int(os.environ["SUDO_GID"]),
                )
            environment.chmod(0o600)
    except (OSError, RuntimeError, subprocess.CalledProcessError) as exc:
        print(f"Setup failed: {exc}", file=sys.stderr)
        return 1
    print(f"Configured {device.label}")
    print("Next: docker compose --env-file deploy/quickstart.images.env --env-file deploy/quickstart.env -f deploy/compose.quickstart.yaml --profile usb-agent --profile ipp up -d")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
