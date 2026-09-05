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
| PrinterFleet | HTTP `/v1/printers`, `/v1/deliveries`, `/v1/agents`, maintenance and audit APIs | physical catalog, site policy, queues, transport and device administration | PrintHub; future Fleet Console |
| PrintAgent | HTTP `/v1/agent`, `/v1/drivers`, `/v1/printers/*` | site-local discovery and opaque device-payload delivery | PrinterFleet only |
| Thingdex | `PrintIntent` outbox and signed PrintHub status inbox | inventory intent and business status projection | Thingdex worker, PrintHub event sink |
| IPP gateway | driverless IPP printer; PrintHub document API downstream | protocol translation and IPP job/status mapping only | CUPS and desktop applications |

Drivers are not platform contracts. Zebra ZPL, RAW TCP, serial bridges and a
future Niimbot payload remain behind PrinterFleet/PrintAgent driver interfaces.
Adding a driver must not change the Thingdex, IPP or PrintHub contracts.

## Migration-only surface

| Compatibility surface | Replacement | Known consumers | Removal gate |
| --- | --- | --- | --- |
| PrintHub printer CRUD, registry import/export and ZebraTamer discovery routes | PrinterFleet API plus a separately deployed Fleet Console | current Studio printer screen and `printhub-sdk` printer administration client | Fleet Console provides the operator workflow; Studio and SDK releases no longer call these routes |
| PrintHub `LegacyFleetAdapter` and local writable printer registry | `HttpPrinterFleetAdapter` | compact source profile and rollback baseline | migration/export acceptance passes and every supported deployment includes PrinterFleet |
| `zebra_tamer` connection protocol and `_zpl-agent._tcp` discovery name | `print_agent` and `_print-agent._tcp` | existing agent installations and stored registries | PrintAgent migration tool rewrites configuration and the release matrix contains no legacy agent |
| `raw9100` protocol name | `raw_tcp` with default port 9100 | existing PrintHub registry exports and examples | registry migration rewrites every stored route and rollback no longer consumes the old format |
| PrintHub direct `/v1/printers/{id}/prints/template` submission | canonical durable `/v1/print-jobs` | current Thingdex connector and SDK | Thingdex and SDK use canonical job creation and preserve idempotency/status behavior |
| global `PRINTER_FLEET_API_TOKEN` | structured credentials file and later OIDC verifier | development and migration-only installations | credential migration is documented and no production profile accepts the global token |

PrintHub's read-only printer selection and printer-targeted logical print routes
may remain as document-domain conveniences. They must return Fleet snapshots and
must never regain endpoint addresses, device credentials, discovery or physical
retry ownership.

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
