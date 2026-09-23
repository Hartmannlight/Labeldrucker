# Installation and printer setup

## Standard server or PC

1. Install Docker Engine and Compose v2.
2. Copy the repository's Compose and `config/` files, and copy `.env.example`
   to `.env`. Published images need no submodules or local build. Initialize
   submodules only for development or an intentional local build.
3. Resolve the setup questions below, fill in `.env`, then run
   `docker compose config --quiet` and `docker compose up -d` (include the USB
   overlay below when needed).
4. Open `http://localhost:8088` locally, or the configured server address and
   Studio port from a LAN client, and select **Printers**.
5. Obtain the generated admin token with the command in the root README. It is
   stored only in browser session storage after entry.
6. Add an Ethernet Zebra with a stable IP/DNS name and port `9100`.
7. Set the actual DPI and loaded label dimensions before printing.

The local ZebraTamer service is connected automatically on first start. Its
printer list starts empty and later UI edits survive restarts. The TOML file is
only a first-start seed.

## Setup questions for installers and agents

Before the first server installation, ask the user about any unanswered choices
in this table. Reuse answers already provided; inspect the host for technical
facts such as available devices, ports and group IDs. Ask the remaining questions
together, record the choices in `.env` and the relevant configuration, then
apply them in one setup pass. Do not silently interpret the local defaults as
the user's desired server configuration.

| Ask the user | Configuration or action |
| --- | --- |
| Local access only, or which LAN address and web ports? | Set `PRINTHUB_STUDIO_BIND/PORT`, `ZEBRATAMER_BIND/PORT` and, if direct API access is wanted, `PRINTHUB_API_BIND/PORT`. Studio proxies its API requests, so direct API publication is not required for Studio. |
| Which printer, connected by Ethernet, USB or a remote print service? | Register the printer/service. For Ethernet obtain its address and RAW port (normally 9100). For USB identify the actual host device, configure the USB overlay and device permissions. |
| What DPI and loaded label width/height does each printer use? | Configure the printer and media in Studio; do not infer label stock from the model alone. |
| Should Ubuntu or other clients print through IPP, and is automatic discovery wanted? | Set `PRINTHUB_IPP_BIND` and a client-resolvable `PRINTHUB_IPP_HOSTNAME`; create the share in Studio. Test the direct URI and discovery separately. |
| May Labelary generate saved library thumbnails from template layouts and sample data? | Set `ZPLGRID_ENABLE_LABELARY_TEMPLATES` independently. Offer this even if previews with real data are declined. |
| May Labelary render previews containing entered data? | Set `ZPLGRID_ENABLE_LABELARY_API` for Studio PNG previews; separately set `ZPLGRID_ENABLE_LABELARY_PREVIEW` if API draft previews are used. See the exact distinction below. |
| Will ZPL templates be printed as rendered images or to raster-only printers? | Explain that this printing path also sends resolved label content to Labelary, independently of the preview switches. Native Zebra ZPL and local PDF/image printing avoid that renderer. |
| Use generated credentials, or is there an existing credential requirement? | Default to the generated, separate PrintHub admin and ZebraTamer service tokens. For custom credentials, validate each service's requirements before applying them; short PINs are not suitable. Do not silently replace or unify existing tokens. |

Read generated credentials locally when needed (do not commit them or include
them in an installation report):

```bash
docker compose run --rm --no-deps bootstrap cat /secrets/printhub-admin-token
docker compose run --rm --no-deps bootstrap cat /secrets/zebratamer-token
```

After startup, check `docker compose ps`, open Studio and any requested
ZebraTamer UI from an actual client, verify the printer/media and create the
requested IPP shares. Healthy containers alone do not prove LAN reachability.
If a published port is unreachable, inspect the effective Compose configuration,
Docker port mappings and host listeners before changing firewall rules. The
default internal Docker network needs particular attention when diagnosing
host-port publication on the target Docker version. Do not equate "reachable
from this LAN" with a request to create new firewall restrictions.

Confirm the requested saved and interactive previews separately with harmless
sample data. For IPP, test the direct URI first. Container mDNS may not reach
the LAN; if automatic discovery was requested, configure and verify the host's
Avahi advertisement for the actual share address, port and `/ipp/print` path.
Record any remaining host setup explicitly instead of reporting the installation
complete merely because Compose started.

## Labelary

The preview switches are already independent. All default to `0` for an
unattended start; an installer must ask about the two data-use cases above.
`ZPLGRID_ENABLE_LABELARY_API` is **not a master switch**.

| Variable | What setting it to `1` enables | Content sent to Labelary |
| --- | --- | --- |
| `ZPLGRID_ENABLE_LABELARY_TEMPLATES` | Generate and store the library thumbnail when creating or updating a template | Layout and `sample_data`, with resolved macros |
| `ZPLGRID_ENABLE_LABELARY_API` | PNG render endpoint (`POST /v1/renders/png`), used by Studio Quick print and designer previews | Layout and the variables supplied for the preview, potentially real entered data |
| `ZPLGRID_ENABLE_LABELARY_PREVIEW` | Preview requested with `return_preview=true` when creating an API draft | Layout and resolved draft variables |

For **saved template thumbnails only**, use:

```dotenv
ZPLGRID_ENABLE_LABELARY_TEMPLATES=1
ZPLGRID_ENABLE_LABELARY_API=0
ZPLGRID_ENABLE_LABELARY_PREVIEW=0
```

This keeps the template library illustrated without enabling previews of filled
forms. Use non-sensitive sample data: sample values and literal text in a
template can still contain private information. Viewing a stored thumbnail
serves the saved image rather than making another Labelary request.

If previews with entered data are also wanted, enable
`ZPLGRID_ENABLE_LABELARY_API=1`; enable `ZPLGRID_ENABLE_LABELARY_PREVIEW=1`
as well when API clients request draft previews. To disable generation of saved
thumbnails independently, set only `ZPLGRID_ENABLE_LABELARY_TEMPLATES=0`.
Changing the switch alone does not remove already stored images; saving a
template while thumbnail generation is disabled removes that template's image.

Apply changed `.env` values with `docker compose up -d printhub` (with the same
overlays/profiles used for installation); a simple restart does not reload the
container environment. Existing templates without an image need to be opened
and saved again after enabling thumbnails. A renderer failure can prevent that
save; check the error rather than assuming a thumbnail was generated.

Native Zebra template output and local PDF/image rasterization do not require
Labelary. Template-to-raster **printing** uses Labelary independently of these
three preview switches, including when all are `0`; they are not a global
external-rendering prohibition. A raster-only target needs this conversion.
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
