# API compatibility matrix

Status: pre-stable migration contract, 5 September 2026

This matrix prevents convenience proxies from becoming permanent ownership.
`v1` names a contract generation; it does not yet claim a stable `1.0.0`
product release. A compatibility route may be removed only after every listed
consumer has moved and the integrated release manifest pins those revisions.

## Authoritative contracts

| Producer | Contract | Authoritative responsibility | Current consumers |
| --- | --- | --- | --- |
| PrintHub | HTTP `/v1/templates`, `/v1/renders/*`, `/v1/print-jobs`, document jobs | templates, preflight, preview, page policy and logical jobs | Studio, SDK, IPP gateway, Thingdex |
| PrinterFleet | HTTP `/v1/printers`, `/v1/deliveries` with bounded ID filtering, `/v1/agents`, maintenance and audit APIs | physical catalog, site policy, queues, transport and device administration | PrintHub and Fleet Console |
| PrintAgent | HTTP `/v1/agent`, `/v1/drivers`, `/v1/printers/*` | site-local discovery and opaque device-payload delivery | PrinterFleet only |
| Thingdex | `PrintIntent` outbox and signed PrintHub status inbox | inventory intent and business status projection | Thingdex worker, PrintHub event sink |
| IPP gateway | driverless IPP printer; PrintHub document API downstream | protocol translation and IPP job/status mapping only | CUPS and desktop applications |

Drivers are not platform contracts. Zebra ZPL, RAW TCP, serial bridges and a
future Niimbot payload remain behind PrinterFleet/PrintAgent driver interfaces.
Adding a driver must not change the Thingdex, IPP or PrintHub contracts.

## Migration-only surface

There is no migration-only live API or transport surface. Legacy registry
spellings are inputs to the offline `printer_fleet.legacy_import` command only;
they are rejected by live Fleet configuration and delivery. Old PrintAgent
installations must be upgraded before Fleet discovery.

PrintHub's read-only printer selection and printer-targeted logical print routes
may remain as document-domain conveniences. They must return Fleet snapshots and
must never regain endpoint addresses, device credentials, discovery or physical
retry ownership.

Retired on 2026-09-05:

- Direct `POST /v1/printers/{id}/prints/template` submission. Thingdex, Studio
  and the SDK now create durable `/v1/print-jobs`; inline Studio drafts are
  immutable job snapshots.
- PrintHub printer mutation, registry import/export, ZebraTamer discovery,
  device status and raw-ZPL submission. Fleet Console and the PrinterFleet API
  now own those workflows; PrintHub's Fleet adapter exposes only catalog reads
  and immutable artifact delivery.
- PrintHub's `LegacyFleetAdapter`, writable local printer registry, discovery
  loop and in-process RAW/agent transports. Existing YAML, JSON and SQLite
  registries migrate offline with `python -m printer_fleet.legacy_import`;
  every supported deployment now includes PrinterFleet.
- Runtime aliases `raw9100` and `zebra_tamer`, legacy `_zpl-agent._tcp` and
  `_zpl-printer._tcp` advertisements, and the global
  `PRINTER_FLEET_API_TOKEN`. Deployments use `raw_tcp`, `print_agent`,
  `_print-agent._tcp`, `_print-agent-printer._tcp` and scoped structured
  credentials. Old registry spellings remain accepted only by the offline
  migration command.

## Stable-release gate

The first stable compatibility bill of materials requires:

1. Contract and generated-client checks against the exact OpenAPI artifacts.
2. SQLite-to-PostgreSQL migration and PostgreSQL backup/restore rehearsal.
3. Failure injection for unreachable/slow printers, process restart, ambiguous
   socket outcomes, agent disconnect and downstream recovery.
4. CUPS PDF/PostScript/PWG Raster acceptance including held A4-to-label jobs.
5. Recorded real Zebra acceptance for RAW 9100 and, where supported, a
   transparent serial-over-TCP bridge and PrintAgent-connected device.
6. A manifest containing only component revisions that passed those gates.

Niimbot B1 hardware acceptance is intentionally outside the first stable Zebra
release. Its driver slot and raster contract are reserved, but its wire protocol
must not be declared supported without representative hardware and media tests.

The evidence template and destructive-test limits are defined in
[`../acceptance/REAL_PRINTER_ACCEPTANCE.md`](../acceptance/REAL_PRINTER_ACCEPTANCE.md).
