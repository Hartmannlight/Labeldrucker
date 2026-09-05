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
                                                      │ 1-bit page
                                      ┌───────────────┴───────────────┐
                                      ▼                               ▼
                                 ZPL encoder                  future Niimbot encoder
                                      │                               │
                              raw9100/ZebraTamer              driver-agent transport
```

The gateway owns only IPP protocol details, capability advertisement and ticket
mapping. PrintHub owns PDF/PostScript/PWG decoding, durable job state,
loaded-media validation and printing policy. Drivers only
turn an already prepared monochrome page into a device artifact. Backends only
deliver that artifact. No driver may independently resize a page or invent its
own preview.

## Invariants

- The printer registry or its dynamic media source is authoritative for loaded
  width, height, DPI and label color.
- Physical page dimensions travel with every raster page; pixel dimensions are
  not treated as a physical size.
- `hold` is the default for a page/media mismatch. The original job is retained
  and no bytes reach hardware until an operator explicitly chooses `fit` or
  `fill`.
- `fit` preserves the full page and adds unused label area. `fill` preserves the
  aspect ratio and crops centrally. Stretching is never implicit.
- Every document page becomes one label. Copies are applied by the selected
  printer backend.
- Color and transparency are flattened to the physical media color for preview,
  converted to grayscale, then reduced to one bit. Photo mode uses
  Floyd-Steinberg dithering; text/graphics default to a hard threshold.
- A dispatched job's saved preview is generated from the exact one-bit raster
  used by the encoder. A held mismatch stores the exact `fit` proposal; the UI
  warns that choosing `fill` can crop edge content.
- Source byte, page, pixel and decoded-image limits are enforced before
  expensive processing. IPP is loopback-only by default because the gateway
  does not currently authenticate clients.

## Extension point for Niimbot B1

The registry accepts a non-ZPL `driver`, opaque `driver_options`, and the
generic `driver_agent` connection. A Niimbot implementation should add:

1. a `RasterDriver` that compresses the prepared one-bit bitmap into the B1
   protocol artifact;
2. a `PrinterBackend` for the driver agent that owns Bluetooth/USB connection,
   framing, retries and device status;
3. capability/media discovery in that agent;
4. contract tests using captured protocol fixtures, without changing the IPP
   gateway or common raster service.

Until those adapters exist, selecting `niimbot_b1` fails explicitly instead of
silently routing a binary payload through a ZPL transport.

## Operational model

The current IPP gateway publishes one configured PrintHub printer. It reads the
loaded medium at startup for CUPS capabilities and the backend reads it again
for every job before validation. Restart the gateway after changing a roll so
already open print dialogs can refresh their advertised media. A future gateway
supervisor may republish capabilities automatically; this does not affect the
raster or driver contracts.

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
