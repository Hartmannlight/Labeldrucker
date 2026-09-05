# USB development hardware run - 2026-09-05

Status: development evidence only; not valid for a stable compatibility release

This run exercised a Zebra USB path while the implementation was still an
uncommitted candidate. It documents defects found with physical media and the
corresponding fixes. Stable evidence must repeat the applicable checklist with
published image digests, the exact committed platform revision and an
independent reviewer.

## Equipment and isolation

- Printer: Zebra LP 2824 Plus (ZPL), firmware `V61.17.5Z`, serial suffix `3718`
- Media: user-confirmed white 50 x 25 mm gap labels, direct thermal
- Resolution: configured and device-reported 203 dpi / 8 dots per mm
- Host path: Windows -> usbipd-win -> Docker Desktop Linux VM -> PrintAgent
  `usb_bulk`
- Container: UID/GID 999, read-only root filesystem, all capabilities dropped,
  `no-new-privileges`, one exact USB device node, not privileged
- USB implementation: printer-class bulk endpoints through dynamically linked
  `libusb-1.0.so.0`

The complete USB serial, local admin token, device address and unrestricted raw
printer responses are intentionally excluded.

## Observations

1. A direct Agent smoke job produced exactly one physical label. Status,
   firmware, hardware identity and configuration queries worked over the USB
   bulk IN and OUT endpoints.
2. PrinterFleet discovered agent `acceptance-pc`, registered its device as
   `zebra-lp2824-usb`, and exposed only the public media/capability projection to
   PrintHub.
3. PrintHub job `b7346e9c-3f79-44b4-926f-4ba54e8deb21` reached Fleet delivery
   `6c715fdb-d413-4f48-8ec8-16ac20f42d95`, which reported
   `transport_accepted`. The uniquely marked physical label was printed once.
4. Both the direct job and the independent prepared-raster job were clipped at
   the bottom. Live `^HH` output showed a device label length of only 79 dots,
   despite the 25 mm stock requiring about 200 printable dots.
5. PrinterFleet initially rejected `calibrate-media` for `print_agent`. The
   maintenance service was corrected to use the registered transport and the
   canonical `application/zpl` MIME type while retaining the fixed driver-owned
   command allowlist and per-printer operation lease.
6. Fleet-issued `calibrate-media` was accepted once. The printer then reported
   212 dots, consistent with a 25 mm label plus its gap.
7. Post-calibration jobs exposed a device-specific alignment offset. User
   measurements were used with revision-checked typed Agent configuration; no
   template or device-independent raster contract was changed. The initial
   alignment run used `LEFT POSITION +10`, `LABEL TOP +4`. The revision-bound
   control run below showed that a smaller horizontal correction was still
   required; the currently verified active values are `LEFT POSITION +6`,
   `LABEL TOP +4`.
8. The final uniquely marked control label printed once with every border
   visible. User-measured white margins were 0.6 mm left, 1.35 mm right, 1.3 mm
   top and 1.0 mm bottom. The largest deviation from the mean is about 0.4 mm,
   or roughly three device dots, so no further manual correction was applied.

## Correlation and remaining gates

Additional alignment job IDs are:

- `7f8646fb-647d-4922-9b46-a6290279b285`
- `c1d3e73d-3428-4d5c-ab1c-a9b1bee2a0f6`
- `fe60d2d4-92aa-4b61-aa60-e1d6b4e72839`

The operator confirmed the final alignment result. Still required for stable
evidence are power-cycle persistence, queue isolation,
Fleet/Agent response-loss idempotency, USB disconnect ambiguity, media-change
refresh, CUPS/browser output, color/dither output, A4 hold/fit, sanitized visual
evidence and independent review. Direct RAW TCP and serial-over-TCP require
separate representative hardware and cannot inherit this USB result.

## Revision-bound control run

After the implementation and CI fixes were published, the PrintAgent was rebuilt
from the exact ZebraTamer revision
`1ccaace73fc66bb53dd0045efaa83725eb6943f6`. Its `/v1/agent` response reported
that revision after container replacement, and a Fleet status request reached
the USB printer bidirectionally and reported it ready. Container isolation
remained UID/GID 999, read-only root filesystem, all capabilities dropped,
`no-new-privileges`, and one exact USB device node.

At `2026-09-05T15:52:38Z`, a uniquely marked 50 x 25 mm control job was sent
through the current platform working tree at revision
`04b4eb02a5e02a48217be87244b94e1b3d1aa35b`:

- PrintHub job: `b7426009-f430-4812-b2b3-2d86faeca946`
- Fleet delivery: `15755600-1f02-480b-bfbc-11b3a5a3ddc4`
- PrintAgent job: `1cb38394-2373-45b9-99d8-0421cdbeaa10`
- Final software state: `transport_accepted`
- Marker: `CANDIDATE 04B4` / `AGENT 1CCA`

The idempotency chain resolved to exactly one Agent job. The operator confirmed
that exactly one physical label was produced and that its vertical alignment was
correct. The left border was clipped while the right white margin was about
2 mm, so the horizontal alignment did not pass and this control run is not
promoted to stable-release evidence.

## Horizontal comparison run

The active and saved device configuration was read back as `LEFT POSITION +10`
and `LABEL TOP +4`. Based on the measured right margin, a revision-checked typed
configuration update changed only `LEFT POSITION` to `+6`, corresponding to a
0.5 mm movement to the right at 8 dots/mm. Readback reported
`save_sent_active_verified`, `LEFT POSITION +6` and the unchanged
`LABEL TOP +4`.

A geometrically identical, uniquely marked comparison job was then submitted:

- PrintHub job: `91888339-8527-4c41-b3af-4fd543d8fe71`
- Fleet delivery: `92e760a1-f9ff-4a51-9eea-37c0eab78137`
- PrintAgent job: `ce19d679-4d2c-4ac5-9912-73a00214a4fb`
- Final software state: `transport_accepted`
- Marker: `HSHIFT +6` / `04B4 / 1CCA`

The software correlation again resolves to one Agent job. The operator confirmed
the physical comparison label: the right white margin is approximately 1 mm and
the rest of the alignment, including the previously clipped left border and the
unchanged vertical axis, is correct. The device-specific alignment therefore
passes this development run at `LEFT POSITION +6`, `LABEL TOP +4`. This does not
replace the remaining stable-release gates listed above.
