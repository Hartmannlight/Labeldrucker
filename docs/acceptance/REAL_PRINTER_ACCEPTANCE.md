# Real-printer acceptance

Status: required before the first stable hardware release

Emulators prove protocol framing and state transitions, but cannot prove media
feeding, print density, sensor behavior, bridge buffering or whether a socket
write produced paper. Complete this record for every supported hardware path and
attach it to the compatibility release; do not store credentials or unrestricted
device logs in the evidence.

## Record under test

- Platform compatibility manifest and image digests:
- Printer manufacturer, model, serial suffix and firmware:
- Connection: direct Ethernet/WLAN RAW 9100, serial-over-TCP, or PrintAgent:
- PrintAgent version and host OS, when applicable:
- Media width, height, tracking, color and print technology:
- Configured and device-reported DPI:
- Tester, site and UTC time:

Use expendable test media and an isolated test printer. Record explicit operator
approval before calibration because it moves media. Do not test reset, firmware,
flash-write or arbitrary-command behavior through the platform.

## Common acceptance

1. Register the printer in PrinterFleet and verify that PrintHub receives only
   its public capability/media snapshot, never endpoint credentials.
2. Print a configuration label through the allowlisted maintenance action.
   Confirm site-admin authorization, audit correlation and serialization with
   the printer queue.
3. Submit a uniquely marked 50 x 50 mm label. Match PrintHub job ID, Fleet
   delivery ID and the physical label. RAW TCP success must remain
   `transport_accepted`, not `confirmed`.
4. Submit two jobs to this printer and one to another printer. Make this endpoint
   unreachable until the other printer finishes; restore it and verify FIFO,
   bounded retry and no duplicate physical label.
5. Interrupt connectivity after transmission begins. Verify the affected job is
   `unconfirmed` whenever paper outcome cannot be proven and is not automatically
   resent.
6. Change the loaded-media declaration. Verify stale selection/preflight data is
   rejected or refreshed before a subsequent delivery.

## Direct network Zebra

- Verify the exact endpoint and configured timeout; use `raw_tcp`, whose default
  is port 9100.
- Print text, a barcode/2D code and a dithered photograph. Inspect quiet zones,
  scan reliability, density and orientation on physical media.
- Query supported Zebra status and run only the allowlisted configuration-label
  and media-calibration actions. Confirm command bytes never interleave with a
  print stream.

## Transparent serial-over-TCP bridge

- Record the bridge model, TCP port, baud rate, data/parity/stop bits and flow
  control configured on the bridge.
- Use `serial_over_tcp` with the explicit port. Repeat the common print and
  connectivity tests, including a payload larger than one bridge buffer.
- Power-cycle the bridge between jobs and verify recovery without reordering or
  duplicating labels.

If no supported bridge is available, mark this path `not tested`; do not infer it
from the shared TCP implementation.

## PrintAgent-connected Zebra

- Verify stable agent and local printer IDs before submission.
- Disconnect the Fleet-to-agent network after the agent accepts a job but before
  Fleet receives the response. Restore it and verify the repeated idempotency key
  resolves to the original agent job and one physical label.
- Restart PrintAgent with queued and in-progress work. Verify persisted state and
  honest ambiguous-outcome handling.
- Disconnect and reconnect the USB/local-serial device. Verify other Fleet
  printers and the central administration API remain available.

## CUPS and browser path

1. Add the IPP endpoint with `lpadmin -m everywhere` and print from Chrome.
2. Verify the dialog advertises the current label media, monochrome output and
   supported resolution.
3. Print a label-sized PDF and compare the stored preview with the physical
   output.
4. Print a color image using document and photo optimization; compare threshold
   and dithering behavior.
5. Submit A4 to a 50 x 50 mm target. Confirm it is held without device traffic,
   inspect the fit preview, then release it explicitly with `fit`. Repeat `fill`
   only when intentional cropping is acceptable.

## Result

- Outcome per applicable section: pass / fail / not tested
- Fleet audit correlation IDs (no tokens):
- PrintHub/Fleet job IDs:
- Sanitized photographs or scan results:
- Deviations and issue links:
- Tester signature and date:
- Reviewer signature and date:

A release passes hardware acceptance only when every advertised transport has a
`pass`. An unavailable Zebra, bridge or PrintAgent path stays unsupported in the
compatibility matrix. Niimbot B1 requires its own future protocol and media
record and is not covered by a Zebra result.

## Machine-readable stable-release gate

Copy `hardware-acceptance.example.json`, keep it in this repository and replace
every placeholder with sanitized results from the exact tested candidate. The
JSON deliberately fails validation until every common scenario and every
advertised transport passes. It rejects sensitive field names, non-HTTPS
evidence references, self-review and ambiguous delivery-state claims. Do not
include unrestricted device logs.

Validate it before dispatching a stable release:

```powershell
python scripts/validate_hardware_acceptance.py `
  release/acceptance/v1.0.0.json `
  --release v1.0.0 `
  --platform-revision FULL_TESTED_CANDIDATE_COMMIT
```

The Compatibility Release workflow requires both that repository-relative file
and the candidate source revision. It verifies that the evidence names the same
release and candidate, embeds its SHA-256 digest and advertised transports in
the signed compatibility manifest, and publishes the sanitized record beside
the manifest. The workflow commit may be newer than the tested candidate; this
avoids the impossible requirement that a hardware record already exist inside
the commit whose images were tested.
