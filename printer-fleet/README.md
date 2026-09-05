# PrinterFleet

PrinterFleet is the physical-delivery boundary of the printing platform. It
owns printer endpoints, device capabilities, delivery records, drivers and
transports. It deliberately does not own templates, inventory data or document
layout.

Set `PRINTER_FLEET_API_TOKEN` in non-development deployments. When configured,
all `/v1/*` requests require the matching bearer token; `/health` remains open
for orchestration. Every response carries `X-Correlation-ID`, preserving a
valid caller-supplied value or generating one at the boundary.

Mutating requests and rejected API calls are recorded durably in Fleet's own
`audit_records` table without request bodies, artifact bytes or credentials.
Authorized operators can inspect the bounded journal through
`GET /v1/audit-records?limit=100`. `PRINTER_FLEET_API_CALLER_ID` names the
current service principal and defaults to `printhub`.

The first vertical slice supports ZPL artifacts over `raw_tcp`, the legacy
`raw9100` spelling and `serial_over_tcp`. A successful socket write is recorded
as `transport_accepted`, never as a confirmed physical print.

Printer records, capability/media snapshots, immutable artifact bytes, ordered
delivery events and PrintAgent observations are stored in Fleet's database.
Transient delivery failures use bounded exponential retry. If Fleet restarts
while an outcome could already have reached a device, the delivery becomes
`unconfirmed` and is not automatically resent.

The `print_agent` transport is the vendor-neutral successor to the compatible
`zebra_tamer` alias. It forwards device payloads and a stable idempotency key to
an edge agent. Direct Ethernet printers remain connected to Fleet itself and do
not require an agent.

Important API groups:

- `/v1/printers` owns the physical catalog and revision-checked configuration.
- `/v1/deliveries` durably accepts immutable artifacts and exposes state history.
- `/v1/agents` discovers and registers devices reachable through PrintAgent.
- `/v1/printer-registry/import` performs an atomic add-only configuration import.

This directory incubates an independently deployable service. It is intended
to become its own repository once its v1 contract is stable.
