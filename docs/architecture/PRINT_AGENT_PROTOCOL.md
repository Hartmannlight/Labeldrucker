# PrintAgent protocol v1

Status: compatibility-first draft

## Purpose

PrintAgent gives PrinterFleet controlled access to printers that cannot be
reached directly from the central service. Typical examples are USB, Bluetooth
and local serial devices. Network printers remain direct PrinterFleet targets.

The protocol is device-neutral. ZebraTamer's current `/v1` API is the first
compatible implementation and keeps its existing executable and URLs during
migration.

## Trust and ownership

- PrinterFleet owns global printer identity, routing, physical delivery attempts
  and retry policy.
- PrintAgent owns local device access, device-specific framing and the last
  locally observed hardware/media state.
- PrintAgent never contacts Thingdex or renders business templates.
- Fleet supplies an immutable `DevicePayload`; an agent never chooses scaling,
  dithering or page layout.
- Agent admin/configuration APIs require authentication. Production transport
  must use authenticated TLS or a protected site network.

## Discovery

Agents advertise `_print-agent._tcp.local.`. `GET /v1/agent` returns a stable
`agent_id`; endpoint changes are accepted only after that identity matches.

`GET /v1/printers` returns stable agent-local IDs plus at least:

```json
{
  "id": "usb-zebra",
  "display_name": "Shipping Zebra",
  "driver": "zpl",
  "transport": "char_device"
}
```

Fleet combines `agent_id` and the local ID into a globally unique physical
identity. Discovery observes devices but never registers an unknown device
without an explicit operator action.

`GET /v1/drivers` exposes each compiled driver, its accepted MIME types and
whether it is available. Reserved descriptors are not executable: configuring
one fails startup validation until the implementation is part of that agent
build. This prevents arbitrary binary data from being written through a
nominal driver name.

## Delivery

Fleet submits bytes to `POST /v1/printers/{local_id}/jobs` with:

- `Content-Type`: device-payload MIME type.
- `X-Idempotency-Key`: stable Fleet delivery identity.
- `X-Print-Origin`: `printer-fleet`.
- `X-Print-Description`: audit-safe description without inventory secrets.

Current MIME type:

- `application/zpl` for the Zebra driver.

Reserved future MIME types:

- `application/vnd.printhub.niimbot-b1-raster+v1` for an already prepared,
  monochrome raster plus versioned framing metadata.
- `application/vnd.printhub.device-payload+v1` only when a future driver contract
  needs a generic envelope; opaque `application/octet-stream` is not accepted by
  default.

An identical idempotency key, printer and checksum returns the original agent
job. Reusing a key for different content or a different device returns HTTP 409.
This rule survives agent restarts. Fleet retains the returned agent job ID and
state as downstream evidence.

## State semantics

- `queued`: durably accepted by the agent, not yet sent to hardware.
- `writing`: bytes are being transferred; interruption has an unknown outcome.
- `transport_accepted`: the operating-system/device transport accepted bytes.
- `completed_observed`: hardware evidence confirms completion.
- `failed`: no bytes could have reached the device.
- `outcome_unknown`: bytes may have reached the device; automatic retry is
  forbidden unless an operator accepts duplicate risk.

Fleet maps agent `queued` or `transport_accepted` to its own
`transport_accepted` boundary while preserving the downstream state separately.
It reports `confirmed` only for explicit hardware evidence.

## Driver boundary

Each agent printer declares one driver. A driver validates its MIME type,
decodes the versioned payload and creates device-specific frames. A transport
only moves those frames to USB, Bluetooth or serial hardware.

For Niimbot B1 this means:

1. PrintHub produces the same prepared monochrome raster used for preview and
   Zebra raster fallback.
2. PrinterFleet selects a Niimbot-capable destination and creates the versioned
   Niimbot raster artifact.
3. The agent's `niimbot_b1` driver performs compression, packet framing and
   device negotiation.
4. A USB/Bluetooth transport sends frames and reports conservative evidence.

Thingdex, IPP and PrintHub contracts do not change when that driver is added.

## Compatibility and versioning

- New fields are additive within v1; incompatible semantics require `/v2` or a
  new vendor MIME version.
- Live protocol and DNS-SD aliases have been removed. Upgrade old agents before
  discovery and convert stored registry entries with
  `python -m printer_fleet.legacy_import`.
