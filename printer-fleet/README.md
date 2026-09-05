# PrinterFleet

PrinterFleet is the physical-delivery boundary of the printing platform. It
owns printer endpoints, device capabilities, delivery records, drivers and
transports. It deliberately does not own templates, inventory data or document
layout.

For new non-development deployments, mount a JSON credential document and set
`PRINTER_FLEET_CREDENTIALS_FILE`. Each credential declares a stable principal,
one or more `admin`, `observer` or `submitter` roles, and explicit site IDs or
the single global `*` scope. `PRINTER_FLEET_CREDENTIALS_JSON` is available for
secret-injection systems that cannot mount files. The former global
`PRINTER_FLEET_API_TOKEN` is rejected at startup because it granted PrintHub
administrative access to every site.

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

The Zebra driver accepts native `application/zpl` and the device-independent
`application/vnd.printhub.raster-page+json` contract. It creates ZPL only in the
Fleet worker, then sends it through `raw_tcp`, `serial_over_tcp` or
`print_agent`. A successful socket write is recorded as `transport_accepted`,
never as a confirmed physical print.

Registry writes normalize RAW TCP to port 9100 and a bounded timeout. A
`serial_over_tcp` endpoint must declare its real bridge port explicitly. Fleet
rejects unknown protocols, malformed hosts, out-of-range ports and agent URLs
containing embedded credentials before configuration becomes authoritative.

Printer records, capability/media snapshots, immutable artifact bytes, ordered
delivery events and PrintAgent observations are stored in Fleet's database.
Transient delivery failures use bounded exponential retry. If Fleet restarts
while an outcome could already have reached a device, the delivery becomes
`unconfirmed` and is not automatically resent.

`POST /v1/deliveries` only validates and durably queues an artifact before
returning HTTP 202. It never opens a printer connection in the request path.
`GET /v1/deliveries` accepts repeated `delivery_id` query parameters, capped at
100 IDs per request, so upstream logical-job services can reconcile a bounded
set of deliveries without N+1 calls. Site scoping is applied after the ID
filter; knowing a delivery ID never bypasses tenant visibility.
The delivery worker is the normal owner of device I/O, so printer latency and
outages do not consume API requests. The embedded worker is enabled by default
for a compact single-container deployment and can be disabled with
`PRINTER_FLEET_DELIVERY_WORKER_ENABLED=0` when API and worker processes are
operated separately. Start the dedicated process from the same image with
`python -m printer_fleet.worker_main`; `--check` performs its database readiness
probe. Only the delivery-owning process performs interrupted-job recovery, so an
independent API restart cannot change an active delivery to `unconfirmed`.

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

The `print_agent` transport forwards device payloads and a stable idempotency
key to an edge agent. Direct Ethernet printers remain connected to Fleet itself
and do not require an agent. Legacy protocol spellings are accepted only by the
offline migration tool, never by the live delivery path.

Important API groups:

- `/v1/printers` owns the physical catalog and revision-checked configuration.
- `/v1/printers/{id}/maintenance/{action}` exposes only allowlisted,
  driver-owned operator actions; it never accepts arbitrary command bytes.
- `/v1/deliveries` durably accepts immutable artifacts and exposes site-scoped,
  filterable state history (`printer_id`, `state`, and a bounded `limit`).
- `/v1/agents` discovers and registers devices reachable through PrintAgent.
- `/v1/printer-registry/import` performs an atomic add-only configuration import.

Every printer has a `site_id` (`default` when omitted). Catalog and delivery
lookups are filtered by the authenticated principal's sites and use not-found
responses across the boundary. Only a global administrator can inspect global
metrics, audit records, agents or full registry import/export. A normal PrintHub
credential needs `observer` plus `submitter` only for its assigned sites.

The initial ZPL maintenance allowlist contains `print-configuration` (`~WC`),
`print-network-configuration` (`~WL`) and `calibrate-media` (`~JC`). All require
a site administrator, share the printer's operation lease with deliveries and
status, and are audit logged. These actions can move label stock; `~JC` also
recalibrates media and ribbon sensors. The same allowlisted command is delivered
through the printer's registered transport, including `print_agent`; no raw
command endpoint is exposed. A successful transport write is still reported
only as `transport_accepted`. The commands follow Zebra's official
[host-status command reference](https://docs.zebra.com/us/en/printers/software/zpl-pg/advanced-techniques/host-status-commands.html)
and [media calibration reference](https://docs.zebra.com/us/en/printers/software/zpl-pg/zpl-commands/~jc2.html).

This directory incubates an independently deployable service. It is intended
to become its own repository once its v1 contract is stable.

Delivery orchestration and PrintAgent discovery depend on structural repository
ports, not on a concrete database. The API composition root selects SQLite
through `PRINTER_FLEET_DATABASE` or PostgreSQL through
`PRINTER_FLEET_DATABASE_URL` / `_FILE`. SQLite is the compact single-node
option; PostgreSQL is the production option. Both preserve atomic idempotency,
oldest-job-per-printer claims, operation leases and ordered events without
changing the HTTP or driver contracts.

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

## PostgreSQL production and SQLite cutover

Production Compose uses a dedicated `fleet-postgres` database with separate
ownership from Thingdex. Its URL and password are mounted as deployment
secrets. Fleet serializes schema initialization with a PostgreSQL advisory lock
and refuses schemas created by newer software.

For an existing SQLite installation, stop every Fleet API/worker process before
cutover. Point the migration at an empty PostgreSQL Fleet schema; the command
holds the SQLite writer lock, imports every authoritative table in one target
transaction, compares row counts and SHA-256 content fingerprints, and commits
only after verification succeeds:

```sh
python -m printer_fleet.migrate \
  --source /data/fleet.sqlite3 \
  --target-url-file /run/secrets/printer_fleet_database_url
```

The tool refuses non-current SQLite schemas and non-empty targets. Keep the
source backup until the new deployment has passed its acceptance window; do
not enable dual writes. PostgreSQL backups use the normal platform tooling,
for example `pg_dump --format=custom`, and must be restore-tested on an
independent database on the operator's backup schedule.

## Legacy PrintHub registry import

PrintHub no longer embeds a physical registry or device transport. Convert an
old YAML/JSON export or its former SQLite registry offline:

```sh
python -m printer_fleet.legacy_import \
  --source /backup/printers.sqlite3 \
  --output /backup/printer-fleet-import.json
```

The command never modifies the source and refuses to overwrite its output. It
normalizes `raw9100` to `raw_tcp` and old agent protocol names to
`print_agent`. An agent record without a stable `agent_id` fails closed and
must be rediscovered. Import the result through the authenticated Fleet
registry API. Protect both files because physical endpoint details are
sensitive configuration.
