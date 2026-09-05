# PrinterFleet

PrinterFleet is the physical-delivery boundary of the printing platform. It
owns printer endpoints, device capabilities, delivery records, drivers and
transports. It deliberately does not own templates, inventory data or document
layout.

For new non-development deployments, mount a JSON credential document and set
`PRINTER_FLEET_CREDENTIALS_FILE`. Each credential declares a stable principal,
one or more `admin`, `observer` or `submitter` roles, and explicit site IDs or
the single global `*` scope. `PRINTER_FLEET_CREDENTIALS_JSON` is available for
secret-injection systems that cannot mount files. The legacy
`PRINTER_FLEET_API_TOKEN` still maps to a global administrator during migration;
combining legacy and structured credentials fails startup.

All `/v1/*` requests require a recognized bearer credential when authentication
is configured; `/health` remains open for orchestration. Every response carries
`X-Correlation-ID`, preserving a valid caller-supplied value or generating one
at the boundary. The authentication interface is independent from the bearer
adapter so a later OIDC verifier can produce the same `FleetPrincipal` without
changing route authorization.

Mutating requests and rejected API calls are recorded durably in Fleet's own
`audit_records` table without request bodies, artifact bytes or credentials.
Authorized operators can inspect the bounded journal through
`GET /v1/audit-records?limit=100`. `PRINTER_FLEET_API_CALLER_ID` names the
current service principal and defaults to `printhub`.

`GET /metrics` exposes Prometheus text gauges for registered printers and
delivery records grouped by their authoritative current state. It is protected
by the same service credential whenever API authentication is enabled.

The first vertical slice supports ZPL artifacts over `raw_tcp`, the legacy
`raw9100` spelling and `serial_over_tcp`. A successful socket write is recorded
as `transport_accepted`, never as a confirmed physical print.

Registry writes normalize RAW TCP to port 9100 and a bounded timeout. A
`serial_over_tcp` endpoint must declare its real bridge port explicitly. Fleet
rejects unknown protocols, malformed hosts, out-of-range ports and agent URLs
containing embedded credentials before configuration becomes authoritative.

Printer records, capability/media snapshots, immutable artifact bytes, ordered
delivery events and PrintAgent observations are stored in Fleet's database.
Transient delivery failures use bounded exponential retry. If Fleet restarts
while an outcome could already have reached a device, the delivery becomes
`unconfirmed` and is not automatically resent.

Delivery is FIFO and strictly serialized for each physical printer. Different
printers are processed concurrently, so one slow or unavailable endpoint does
not stop the rest of the fleet. Set `PRINTER_FLEET_MAX_PARALLEL_PRINTERS` to the
maximum number of device endpoints a Fleet process may contact at once; the
default is `4`. Database claims preserve the per-printer exclusion when more
than one API request or worker process competes for work.

Deliveries and status/maintenance traffic also share a durable per-printer
operation lease. Fleet returns HTTP 409 for a status query while that device is
transmitting instead of risking command bytes being interleaved with a print
stream. Only the lease owner can release it, and abandoned leases expire after
a bounded interval.

Operators can persistently pause and resume an individual printer queue through
`POST /v1/printers/{id}/pause` and `POST /v1/printers/{id}/resume`. Pausing
rejects new submissions and leaves already queued work untouched until resume;
it does not claim to recall a job that may already be in flight at the physical
device. The pause reason and timestamp are exposed in the printer's `control`
object and survive service restarts.

The `print_agent` transport is the vendor-neutral successor to the compatible
`zebra_tamer` alias. It forwards device payloads and a stable idempotency key to
an edge agent. Direct Ethernet printers remain connected to Fleet itself and do
not require an agent.

Important API groups:

- `/v1/printers` owns the physical catalog and revision-checked configuration.
- `/v1/deliveries` durably accepts immutable artifacts and exposes site-scoped,
  filterable state history (`printer_id`, `state`, and a bounded `limit`).
- `/v1/agents` discovers and registers devices reachable through PrintAgent.
- `/v1/printer-registry/import` performs an atomic add-only configuration import.

Every printer has a `site_id` (`default` when omitted). Catalog and delivery
lookups are filtered by the authenticated principal's sites and use not-found
responses across the boundary. Only a global administrator can inspect global
metrics, audit records, agents or full registry import/export. A normal PrintHub
credential needs `observer` plus `submitter` only for its assigned sites.

This directory incubates an independently deployable service. It is intended
to become its own repository once its v1 contract is stable.

## Backup and restore

Create a transactionally consistent online backup without stopping Fleet:

```sh
python -m printer_fleet.backup backup \
  --database /data/fleet.sqlite3 \
  --output /backup/fleet-2026-09-05.sqlite3
```

The command refuses existing output paths and writes a companion manifest with
the schema version, record counts, size and SHA-256 checksum. Verify it before
and after copying to independent storage:

```sh
python -m printer_fleet.backup verify \
  --backup /backup/fleet-2026-09-05.sqlite3
```

Restore only while Fleet is stopped, and always to a new path:

```sh
python -m printer_fleet.backup restore \
  --backup /backup/fleet-2026-09-05.sqlite3 \
  --target /data/fleet-restored.sqlite3
```

Restore verifies the manifest and SQLite integrity before atomically creating
the target. It never overwrites an existing database. Fleet records an explicit
schema version, migrates version 1 databases forward to version 2 with
persistent printer controls, and refuses databases created by newer software
rather than silently downgrading them.
