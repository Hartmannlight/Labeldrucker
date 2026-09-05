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
9. A later PrintAgent container restart preserved the hardened runtime and the
   exact USB device mapping. The restarted Agent reported the same pinned build,
   rediscovered one printer and read the saved device configuration as
   `LEFT POSITION +6`, `LABEL TOP +4`, 212-dot label length and 400-dot print
   width. PrinterFleet completed a new bidirectional status request and reported
   the Zebra ready. This verifies container-restart recovery only; the printer
   itself remained powered and a physical power-cycle persistence test is still
   required.

## Correlation and remaining gates

Additional alignment job IDs are:

- `7f8646fb-647d-4922-9b46-a6290279b285`
- `c1d3e73d-3428-4d5c-ab1c-a9b1bee2a0f6`
- `fe60d2d4-92aa-4b61-aa60-e1d6b4e72839`

The operator confirmed the final alignment result. Still required for stable
evidence are power-cycle persistence, queue isolation,
Fleet/Agent response-loss idempotency, USB disconnect ambiguity, media-change
refresh, a filtered browser-dialog print, color/dither output, A4 fit release,
sanitized visual evidence and independent review. Direct RAW TCP
and serial-over-TCP require separate representative hardware and cannot inherit
this USB result.

## PrintAgent container restart recovery

The existing PrintAgent container was restarted without changing its image,
configuration volume or USB mapping. It returned with exit code 0 and retained
UID/GID 999, a read-only root filesystem, all capabilities dropped,
`no-new-privileges` and exactly one mapped USB device. Its identity endpoint
reported Agent `acceptance-pc`, storage mode `full` and the exact ZebraTamer
revision `1ccaace73fc66bb53dd0045efaa83725eb6943f6`.

After startup, an authenticated device readback reported `LEFT POSITION +6`,
`LABEL TOP +4`, a 212-dot label length and a 400-dot print width. A separate
PrinterFleet status operation reached the device and normalized it as ready,
model `Zebra LP 2824 Plus`. No print job was submitted during this check. This
is evidence for application/container restart recovery, not for persistence
across printer power loss, USB detachment or an ambiguous in-flight delivery.

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

## Docker IPP and PDF run

The IPP gateway was recreated in the existing Compose project with only
`PRINTHUB_IPP_PRINTER_ID=zebra-lp2824-usb` changed. The PrintAgent remained
running. The official CUPS `get-printer-attributes.test` passed, and the gateway
advertised the live Fleet media as 50 x 25 mm, 203 dpi and monochrome. Its
document formats included PDF, PostScript, JPEG, PWG Raster and Apple Raster.
A probe from a separate container also reached the host-published port 8631 and
received valid IPP capabilities. This proves Docker network and published-port
reachability.

A deterministic, one-page 50 x 25 mm PDF with the marker `IPP PDF` /
`50 x 25 mm` was rendered at 203 dpi and visually checked before submission.
Its SHA-256 is
`e6f3d4ec4f00a7bcb946f17e1714e48e28be11070bd3ca029475f9d1470f8f77`.
The two-step CUPS `ipptool` Print-Job/Get-Job-Attributes test passed and produced
one correlated software path:

- PrintHub job: `17102d63-fefb-4acc-9d38-11aed9d609c5`
- Fleet delivery: `4f9acf5f-6f4b-476a-866b-91667385a1fd`
- PrintAgent job: `1993c6fd-672d-4586-990a-2fcf08842ad6`
- Final Fleet and Agent state: `transport_accepted`
- Fleet attempts: 1

The operator confirmed that exactly one physical label was produced and that
its appearance and alignment were correct. This passes the label-sized PDF
portion of the development IPP run. It does not substitute for a filtered
Chrome print, color/dither comparison or explicit A4 `fit` release.

The existing A4 fixture, SHA-256
`0ee5f9667653cafe6ae5cacdae98b7f8f1be08b673333e1d6e4f364de5505874`,
was then submitted through the same IPP endpoint with the safe `hold` policy.
PrintHub job `59d06eea-a27f-4977-b562-efb9a3ca85bc` reports `held` with the
explicit 210 x 297 mm versus 50 x 25 mm warning. It has no bytes sent, Fleet
delivery or Agent job, proving that the mismatch did not reach the device. A
deliberate `fit` release and its physical result remain untested.

An additional ephemeral Debian CUPS instance then added the gateway with the
documented `lpadmin -m everywhere` flow. This exposed a startup defect for
non-`localhost` gateway names: Compose mapped the configured name only to IPv4
loopback, while `ippeveprinter` also required an IPv6 listener. Source and
production Compose now map the configured name to both `127.0.0.1` and `::1`,
and the production profile passes `PRINTHUB_IPP_HOSTNAME` through explicitly.
The corrected gateway became healthy with a custom DNS name; CUPS created its
driverless PPD and exposed `50x25mm.Borderless` and grayscale-only output.

CUPS job `printhub-label-3` sent the original A4 PDF through `lp -o raw`.
PrintHub job `c0984a88-abf9-4486-8a34-765cd05dfeaf` was again held with no bytes,
Fleet delivery or Agent job. This verifies a real CUPS queue and preserves the
platform-side A4 safety decision. A normal filtered Chrome job remains open
because desktop CUPS may transform its input before the gateway receives it.
