# Installation and printer setup

## Standard server or PC

1. Install Docker Engine and Compose v2.
2. Initialize the product submodules shown in the root README.
3. Run `docker compose up -d`.
4. Open `http://localhost:8088` and select **Printers**.
5. Obtain the generated admin token with the command in the root README. It is
   stored only in browser session storage after entry.
6. Add an Ethernet Zebra with a stable IP/DNS name and port `9100`.
7. Set the actual DPI and loaded label dimensions before printing.

The local ZebraTamer service is connected automatically on first start. Its
printer list starts empty and later UI edits survive restarts. The TOML file is
only a first-start seed.

## Labelary

Native Zebra template output and local PDF/image rasterization do not require
Labelary. A raster-only target needs template-to-image rendering; enable it in
`.env` with `ZPLGRID_ENABLE_LABELARY_API=1` and the corresponding preview and
template flags. This sends ZPL content to the configured external renderer.
For a Zebra that advertises both formats, **Print format → Rendered image** in
Quick print applies the same whole-label raster path deliberately; **Automatic**
continues to prefer native ZPL. A forced format that the selected service does
not advertise is rejected before any device I/O.

## Memory-constrained 64-bit Raspberry Pi with USB Zebra

For a Pi with roughly 500 MB RAM that only owns the USB printer, run
ZebraTamer natively under systemd. Do not install the complete Docker stack on
that Pi. Download the ARM64 native bundle from the ZebraTamer release, verify
its SHA-256 file, unpack it, and review `config.toml`. Configure a stable
`agent_id`, the exact printer ID, `transport = "char_device"`, and
`char_device = "/dev/usb/lp0"`. Then install:

```bash
chmod +x install-local.sh
sudo ./install-local.sh
systemctl is-active zpl-agent
curl --fail http://127.0.0.1:8080/healthz
```

The installer creates the dedicated `zpl-agent` account, gives it only the
required `lp` supplementary group, installs the Zebra-scoped udev rule,
validates configuration before replacement, enables restart handling, and
keeps the prior binary as `/usr/local/bin/zpl-agent.previous`. Register
`http://PI_ADDRESS:8080` as a print service in the central Studio. Read the
generated service token locally with `sudo cat /etc/zpl-agent/token`; never
store it in Git or paste it into logs.

This layout was exercised on a 64-bit Raspberry Pi 3 Model A with 415 MiB
visible RAM and a Zebra LP 2824 Plus. The running agent used about 6 MiB RSS;
see `acceptance/PI3A_USB_2026-09-08.md` for the complete evidence.

## Docker on a 64-bit Raspberry Pi with USB Zebra

On a larger 64-bit Linux Pi, the same stack can run in Docker. Copy
`config/print-agent.toml.example` to `config/zebratamer.usb.toml`, enter the
exact USB identity there, set `ZEBRATAMER_USB_DEVICE` to a stable host device
path, and start the USB overlay:

```bash
docker compose -f compose.yaml -f compose.usb.yaml --profile usb up -d
```

For `char_device`, use the actual printer-class node such as `/dev/usb/lp0` or
a udev-created stable link and use the same path inside the container. For
`usb_bulk`, pass the matching `/dev/bus/usb/BUS/DEVICE` node and configure
vendor ID, product ID and preferably the exact serial; the bus address itself
is not a stable identity and may require updating after physical reconnect.
Grant only the required node and ensure its host permissions allow UID 999.
Do not run the complete stack privileged. Docker Desktop on Windows does not
expose USB printers automatically; Ethernet setup needs no device forwarding.

The overlay registers this second ZebraTamer instance with PrintHub as
`usb-local`. The normal Ethernet-capable ZebraTamer remains available, so USB
mode does not silently replace another service.

## Remote Pi running ZebraTamer only in Docker

Load the matching ZebraTamer image from the release candidate first (see
`RELEASE.md`). Copy `deploy/zebratamer-remote.compose.yaml` and
`deploy/zebratamer-remote.toml` to the Pi, create a random token file as
`secrets/zebratamer-token` (`mkdir -p secrets && umask 077 && openssl rand
-hex 32 > secrets/zebratamer-token`), and run:

```bash
docker compose -f zebratamer-remote.compose.yaml up -d
```

In the main Studio, connect `http://PI_ADDRESS:8080` as a print service and use
that token. The main server requires no USB access and the Pi requires no
PrintHub or Thingdex installation.

## IPP

Create one share per selected printer in Studio. The shown URI has the form
`ipp://HOST:PORT/ipp/print`; ports 8631–8650 are stable. Replace `localhost`
with an address resolvable and reachable by the client. Docker mDNS behavior
depends on the host network, so the direct URI is the supported fallback.

For LAN access, change only the relevant `*_BIND` values in `.env` and put the
web endpoints behind an authenticated TLS reverse proxy. Raw administrative or
print APIs must not be exposed anonymously.
