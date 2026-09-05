# IPP and raster printing architecture

Status: accepted

## Goal

PrintHub can be installed as a normal driverless IPP printer in CUPS and used
from applications such as Chrome. PDF, PostScript, PWG/Apple Raster and image
input share one device-independent raster pipeline. Hardware-specific encoders and transports
remain replaceable so a future Niimbot B1 implementation does not fork document
handling, scaling, preview or job persistence.

## Boundaries

```text
Chrome / CUPS
      │ IPP Everywhere (PDF, PostScript, PWG/Apple Raster, JPEG)
      ▼
IPP gateway ── maps ticket + forwards original ──► Document job API
                                                        │
                persistent source + ticket + state      ▼
                                          document preparation
                                             ┌────────┴────────┐
                                             │ common pipeline │
                                             │ size policy     │
                                             │ grayscale       │
                                             │ dithering       │
                                             │ preview         │
                                             └────────┬────────┘
                                                      │ versioned 1-bit artifact
                                                      ▼
                                                PrinterFleet worker
                                             ┌────────┴────────┐
                                             ▼                 ▼
                                        Zebra driver     future Niimbot driver
                                             │                 │
                                      raw_tcp / bridge      PrintAgent
```

The gateway owns only IPP protocol details, capability advertisement and ticket
mapping. PrintHub owns PDF/PostScript/PWG decoding, durable job state,
loaded-media validation and printing policy. The prepared page crosses the
service boundary as `application/vnd.printhub.raster-page+json`. Fleet drivers
alone turn it into a device payload; transports only deliver that payload. No
driver may independently resize a page or invent its own preview.

## Invariants

- PrinterFleet and its observed media snapshot are authoritative for loaded
  width, height, DPI and label color.
- Physical page dimensions travel with every raster page; pixel dimensions are
  not treated as a physical size.
- `hold` is the default for a page/media mismatch. The original job is retained
  and no bytes reach hardware until an operator explicitly chooses `fit` or
  `fill`.
- `fit` preserves the full page and adds unused label area. `fill` preserves the
  aspect ratio and crops centrally. Stretching is never implicit.
- Every document page becomes one label. Job copies travel in the prepared
  artifact and are applied by the selected Fleet driver.
- Color and transparency are flattened to the physical media color for preview,
  converted to grayscale, then reduced to one bit. Photo mode uses
  Floyd-Steinberg dithering; text/graphics default to a hard threshold.
- A dispatched job's saved preview is generated from the exact one-bit raster
  used by the encoder. A held mismatch stores the exact `fit` proposal; the UI
  warns that choosing `fill` can crop edge content.
- Source byte, page, pixel and decoded-image limits are enforced before
  expensive processing. IPP is loopback-only by default because the gateway
  does not currently authenticate clients.
- Every advertised transport is operational. In particular, advertising
  `ipps://` and `uri-security-supported=tls` requires usable server credentials;
  capability discovery must never promise a TLS path that job submission cannot
  use.

## Extension point for Niimbot B1

The Fleet registry accepts a non-ZPL `driver`, opaque `driver_options`, and the
generic `print_agent` connection. A Niimbot implementation should add:

1. a Fleet/agent driver that consumes the existing prepared-raster contract and
   compresses its one-bit bitmap into the B1 protocol payload;
2. a PrintAgent transport that owns Bluetooth/USB connection,
   framing, retries and device status;
3. capability/media discovery in that agent;
4. contract tests using captured protocol fixtures, without changing the IPP
   gateway or common raster service.

Until those adapters exist, selecting `niimbot_b1` fails explicitly instead of
silently routing a binary payload through a ZPL transport.

## Operational model

The current IPP gateway publishes one configured PrintHub printer. It reads the
Fleet-backed medium snapshot at startup for CUPS capabilities and PrintHub reads
it again for every job before validation. Restart the gateway after changing a roll so
already open print dialogs can refresh their advertised media. A future gateway
supervisor may republish capabilities automatically; this does not affect the
raster or driver contracts.

The gateway owns a dedicated persistent TLS volume and passes its directory to
`ippeveprinter` explicitly. Development startup may begin as root solely to
initialize D-Bus/Avahi, then changes UID, GID and the process identity
environment together before CUPS starts. This avoids an invalid mixed identity
where the unprivileged process searches for credentials below `/root`. The
private credential directory is mode `0700`, and keeping the volume across
container replacement preserves the endpoint identity. Production deployments
should replace the generated development identity with managed credentials and
an authenticated network boundary.

The bundled CUPS 2.4 `ippeveprinter` is configured from a generated internal
PPD because that version cannot combine its attribute-file mode with a custom
document-format list without duplicating IPP attributes. The PPD is never
offered to clients: the public queue remains driverless and passes the standard
IPP conformance check.

The persistent document job stores the unchanged source document separately
from its manifest. Retrying or releasing reconverts that source against the
current authoritative media. Idempotency keys prevent a CUPS retry from
printing the same submission twice. Converter binaries belong to the PrintHub
runtime; the IPP image contains no PDF, PostScript or PWG conversion policy.
