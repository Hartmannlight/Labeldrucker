#!/usr/bin/env python3
from __future__ import annotations

import json
import os
from pathlib import Path
import shutil
import socket
import subprocess
import sys
import time
from typing import Any
from urllib.error import URLError
from urllib.parse import quote
from urllib.request import urlopen

try:
    import pwd
except ModuleNotFoundError:  # pragma: no cover - only used by Windows unit tests
    pwd = None  # type: ignore[assignment]


APP_UID = 10002
DEFAULT_OUTPUT_FORMAT = "application/pdf"


def start_discovery_services() -> None:
    """Start the local DNS-SD dependency, then leave it to its own low-privilege user."""
    Path("/run/dbus").mkdir(parents=True, exist_ok=True)
    Path("/run/dbus/pid").unlink(missing_ok=True)
    Path("/run/avahi-daemon/pid").unlink(missing_ok=True)
    subprocess.run(["dbus-uuidgen", "--ensure"], check=True)
    subprocess.run(["dbus-daemon", "--system", "--fork"], check=True)
    subprocess.run(["avahi-daemon", "--daemonize", "--no-chroot"], check=True)


def drop_privileges(*paths: Path) -> None:
    if pwd is None:
        raise RuntimeError("Privilege dropping requires a POSIX runtime")
    account = pwd.getpwuid(APP_UID)
    for path in paths:
        os.chown(path, account.pw_uid, account.pw_gid)
    os.setgroups([])
    os.setgid(account.pw_gid)
    os.setuid(account.pw_uid)
    # Compose starts the development profile as root so that Avahi can be
    # initialized. Keep the environment consistent after switching users;
    # CUPS uses HOME to locate and create its TLS credentials.
    os.environ["HOME"] = account.pw_dir
    os.environ["USER"] = account.pw_name
    os.environ["LOGNAME"] = account.pw_name


def prepare_runtime_privileges(*paths: Path) -> None:
    mdns_enabled = os.getenv("PRINTHUB_IPP_MDNS_ENABLED", "1") == "1"
    if mdns_enabled:
        if os.geteuid() != 0:
            raise RuntimeError("mDNS mode requires root only during guarded startup")
        start_discovery_services()
    if os.geteuid() == 0:
        drop_privileges(*paths)


def start_container_proxy(port: str) -> subprocess.Popen[bytes] | None:
    """Expose a loopback-bound ippeveprinter on the container network interface."""
    bind_address = os.getenv("PRINTHUB_IPP_CONTAINER_BIND", "").strip()
    if not bind_address:
        bind_address = socket.gethostbyname(socket.gethostname())
    if bind_address.startswith("127."):
        return None
    proxy = subprocess.Popen(
        [sys.executable, "/app/tcp_proxy.py", bind_address, port, "127.0.0.1", port]
    )
    time.sleep(0.1)
    if proxy.poll() is not None:
        raise RuntimeError(f"IPP container proxy failed to bind {bind_address}:{port}")
    return proxy


def fetch_printer(api_url: str, printer_id: str, *, attempts: int = 60) -> dict[str, Any]:
    url = f"{api_url.rstrip('/')}/v1/printers/{quote(printer_id, safe='')}"
    last_error: Exception | None = None
    for _ in range(attempts):
        try:
            with urlopen(url, timeout=3) as response:
                payload = json.load(response)
            if not isinstance(payload, dict):
                raise RuntimeError("PrintHub returned an invalid printer response")
            return payload
        except (OSError, ValueError, URLError) as exc:
            last_error = exc
            time.sleep(1)
    raise RuntimeError(f"PrintHub printer {printer_id!r} is unavailable: {last_error}")


def media_name(width_mm: float, height_mm: float) -> str:
    def number(value: float) -> str:
        return f"{value:.2f}".rstrip("0").rstrip(".")

    return f"custom_{number(width_mm)}x{number(height_mm)}mm"


def _ppd_text(value: object) -> str:
    return (
        str(value)
        .encode("ascii", errors="replace")
        .decode("ascii")
        .replace("\\", "\\\\")
        .replace('"', '\\"')
        .replace("\r", " ")
        .replace("\n", " ")
    )


def build_ppd(printer: dict[str, Any]) -> str:
    loaded = (printer.get("media") or {}).get("loaded") or {}
    alignment = printer.get("alignment") or {}
    try:
        width_mm = float(loaded["width_mm"])
        height_mm = float(loaded["height_mm"])
        dpi = int(alignment["dpi"])
    except (KeyError, TypeError, ValueError) as exc:
        raise RuntimeError("The IPP printer needs loaded media and a configured resolution") from exc
    if width_mm <= 0 or height_mm <= 0 or dpi <= 0:
        raise RuntimeError("The IPP printer media dimensions and resolution must be positive")
    make = _ppd_text(printer.get("vendor", "PrintHub"))
    model = _ppd_text(printer.get("model", printer.get("name", "Label Printer")))
    make_model = f"{make} {model}"
    width_points = width_mm * 72.0 / 25.4
    height_points = height_mm * 72.0 / 25.4
    return f'''*PPD-Adobe: "4.3"
*FormatVersion: "4.3"
*FileVersion: "1.0"
*LanguageVersion: English
*LanguageEncoding: ISOLatin1
*PCFileName: "PRINTHUB.PPD"
*Manufacturer: "{make}"
*Product: "({model})"
*ModelName: "{make_model}"
*ShortNickName: "{make_model}"
*NickName: "{make_model} - PrintHub IPP Gateway"
*PSVersion: "(3010.000) 0"
*LanguageLevel: "3"
*ColorDevice: False
*DefaultColorSpace: Gray
*FileSystem: False
*Throughput: "1"
*TTRasterizer: Type42
*cupsVersion: 2.4
*cupsFilter2: "application/vnd.cups-pdf application/pdf 0 -"
*cupsManualCopies: True
*OpenUI *PageSize/Label size: PickOne
*OrderDependency: 10 AnySetup *PageSize
*DefaultPageSize: Label
*PageSize Label/{width_mm:g} x {height_mm:g} mm: "<</PageSize[{width_points:.3f} {height_points:.3f}]>>setpagedevice"
*CloseUI: *PageSize
*OpenUI *PageRegion/Label size: PickOne
*OrderDependency: 10 AnySetup *PageRegion
*DefaultPageRegion: Label
*PageRegion Label/{width_mm:g} x {height_mm:g} mm: "<</PageSize[{width_points:.3f} {height_points:.3f}]>>setpagedevice"
*CloseUI: *PageRegion
*DefaultImageableArea: Label
*ImageableArea Label: "0 0 {width_points:.3f} {height_points:.3f}"
*DefaultPaperDimension: Label
*PaperDimension Label: "{width_points:.3f} {height_points:.3f}"
*OpenUI *Resolution/Resolution: PickOne
*OrderDependency: 20 AnySetup *Resolution
*DefaultResolution: {dpi}dpi
*Resolution {dpi}dpi/{dpi} dpi: "<</HWResolution[{dpi} {dpi}]>>setpagedevice"
*CloseUI: *Resolution
*OpenUI *InputSlot/Media source: PickOne
*OrderDependency: 30 AnySetup *InputSlot
*DefaultInputSlot: Main
*InputSlot Main/Main: "<</MediaPosition 0>>setpagedevice"
*CloseUI: *InputSlot
'''


def build_ipp_command(
    executable: str,
    *,
    ppd_path: Path,
    spool_dir: Path,
    tls_dir: Path,
    hostname: str,
    port: str,
    service_name: str,
) -> list[str]:
    return [
        executable,
        "--no-web-forms",
        "-F",
        DEFAULT_OUTPUT_FORMAT,
        "-P",
        str(ppd_path),
        "-c",
        "/app/submit_job.py",
        "-d",
        str(spool_dir),
        "-K",
        str(tls_dir),
        "-n",
        hostname,
        "-p",
        port,
        service_name,
    ]


def main() -> None:
    api_url = os.getenv("PRINTHUB_API_URL", "http://printhub:8000")
    printer_id = os.getenv("PRINTHUB_IPP_PRINTER_ID", "virtual-zebra")
    printer = fetch_printer(api_url, printer_id)
    runtime_dir = Path(os.getenv("PRINTHUB_IPP_RUNTIME_DIR", "/run/printhub-ipp"))
    spool_dir = Path(os.getenv("PRINTHUB_IPP_SPOOL_DIR", "/var/spool/printhub-ipp"))
    tls_dir = Path(os.getenv("PRINTHUB_IPP_TLS_DIR", "/var/lib/printhub-ipp/tls"))
    runtime_dir.mkdir(parents=True, exist_ok=True)
    spool_dir.mkdir(parents=True, exist_ok=True)
    tls_dir.mkdir(parents=True, exist_ok=True)
    tls_dir.chmod(0o700)
    ppd_path = runtime_dir / "printer.ppd"
    ppd_path.write_text(build_ppd(printer), encoding="ascii")

    prepare_runtime_privileges(runtime_dir, spool_dir, tls_dir, ppd_path)

    executable = shutil.which("ippeveprinter")
    if executable is None:
        raise RuntimeError("ippeveprinter is not installed")
    port = os.getenv("PRINTHUB_IPP_PORT", "8631")
    hostname = os.getenv("PRINTHUB_IPP_HOSTNAME", socket.gethostname())
    service_name = os.getenv("PRINTHUB_IPP_NAME", f"PrintHub - {printer.get('name', printer_id)}")
    start_container_proxy(port)
    command = build_ipp_command(
        executable,
        ppd_path=ppd_path,
        spool_dir=spool_dir,
        tls_dir=tls_dir,
        hostname=hostname,
        port=port,
        service_name=service_name,
    )
    os.execv(executable, command)


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print(f"IPP gateway startup failed: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc
