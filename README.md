# PrintHub Label Printing

This repository assembles a standalone label-printing product:

- **Studio** edits templates, starts jobs and manages printers.
- **PrintHub** renders content, owns logical jobs and IPP shares.
- **ZebraTamer** is the Zebra driver and durable physical queue for USB,
  character-device and Ethernet/RAW-9100 printers.
- **IPP Gateway** exposes selected PrintHub printers to operating systems.
- **NIIMBOT service** optionally drives a B1 via USB serial or Bluetooth LE.
- **Image designer** creates bitmap labels from text, PNG/JPEG images and shapes,
  with local monochrome preview and direct raster printing, without ZPL/Labelary.

Thingdex is an optional API client. It is not required to install, build, start
or use the product. NIIMBOT uses the same raster print-service contract without
adding vendor behavior to ZebraTamer. See [B1 setup](docs/NIIMBOT.md).

## Start

Requirements: Docker Engine with Compose v2. The published AMD64/ARM64 images
are the defaults, so a normal installation needs only this repository's Compose
and configuration files.

For a new server, first copy `.env.example` to `.env` and follow the
[setup questions](docs/INSTALLATION.md#setup-questions-for-installers-and-agents).
An installation agent must ask about missing choices before configuring the
server, including **stored template previews and previews with entered data
separately**. Labelary remains opt-in; do not silently skip that question.
`docker compose up -d` starts the services, but does not configure LAN access,
USB device permissions, printers, label stock or operating-system print shares.

```bash
docker compose up -d
```

Initialize the four product submodules only when building or developing the
images locally:

```bash
git submodule update --init components/PrintHub-ZPL-ll components/printhub-sdk components/LabelArchitect components/ZebraTamer
docker compose build
```

Open [http://localhost:8088](http://localhost:8088). The empty first start is
intentional: go to **Printers**, enter the PrintHub admin token, and add an
Ethernet Zebra or connect another print service. Read the generated token with:

```bash
docker compose run --rm --no-deps bootstrap cat /secrets/printhub-admin-token
```

The API is at [http://localhost:8001/docs](http://localhost:8001/docs) and the
standalone ZebraTamer UI at [http://localhost:8082/ui/](http://localhost:8082/ui/).
All web ports bind to loopback by default.

For a hardware-free demonstration:

```bash
docker compose -f compose.yaml -f compose.demo.yaml --profile demo up -d
```

This adds a virtual RAW-9100 Zebra and a raster-only conformance service. It
does not pretend to be a real Niimbot driver.

## Documentation

- [Installation and printer setup](docs/INSTALLATION.md)
- [Architecture](docs/ARCHITECTURE.md)
- [Operations, backup and migration](docs/OPERATIONS.md)
- [Release candidate installation](docs/RELEASE.md)
- [Development and print-service extension](docs/DEVELOPMENT.md)
- [Current acceptance evidence](docs/acceptance/REFACTORING_2026-09-08.md)
- [Raspberry Pi 3A USB hardware acceptance](docs/acceptance/PI3A_USB_2026-09-08.md)
- [Completion audit by work package](docs/implementation/COMPLETION_AUDIT_2026-09-08.md)
- [Detailed refactoring work packages](docs/REFACTORING_ARBEITSPAKETE.md)

The stack intentionally distinguishes `transport_accepted` from a physically
confirmed label. An `unconfirmed` result is never retried automatically; use
the explicit reprint action only after checking the printer.
