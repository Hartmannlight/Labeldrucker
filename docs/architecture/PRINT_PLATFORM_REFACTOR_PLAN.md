# Print platform refactor plan

Status: active
Created: 2026-09-05
Scope: Thingdex ecosystem, standalone PrintHub, IPP ingress and printer fleet

## Approach

Refactor the early-beta system into independently deployable bounded contexts
without attempting a big-bang rewrite. Keep a runnable vertical printing path
after every phase, introduce versioned contracts before moving ownership, and
remove compatibility code once every caller has migrated.

The number of repositories is not an optimization target. Repository and
container boundaries follow ownership, security, failure isolation and release
requirements. Production deployments consume immutable images instead of
building sibling repositories or Git submodules.

## Scope

- In:
  - Separate inventory intent, document preparation and physical delivery.
  - Introduce a central, vendor-neutral PrinterFleet service.
  - Support direct network printers without an edge computer.
  - Retain an optional edge agent for USB, Bluetooth and isolated networks.
  - Make ZPL and future Niimbot output replaceable device drivers.
  - Make IPP a thin optional ingress into PrintHub.
  - Replace synchronous Thingdex printing with a durable asynchronous connector.
  - Define standalone, integrated and development deployment profiles.
  - Add versioned contracts, observability, security and migration gates.
- Out for the first implementation cycle:
  - Kubernetes-specific manifests and cloud-provider infrastructure.
  - Purchasing or reverse-engineering a Niimbot B1 before hardware is available.
  - Removing all beta endpoints before replacement consumers exist.
  - Choosing a specific enterprise identity provider.

## Architectural invariants

1. Thingdex and PrintHub start and preserve their own data when the other is
   unavailable.
2. PrintHub owns templates, document preparation, preview and logical print
   jobs; it does not own physical printer credentials or transports.
3. PrinterFleet owns physical printers, capabilities, media state, routing,
   delivery attempts and device protocols; it does not own templates or
   inventory entities.
4. IPP translates protocol semantics and submits PrintHub jobs; it does not
   implement scaling, dithering, routing or device delivery.
5. A PrintAgent is optional. PrinterFleet connects directly to reachable
   Ethernet/WLAN printers, including RAW TCP and serial-over-TCP targets.
6. Agents never call Thingdex. Device and media events flow through
   PrinterFleet and PrintHub integration contracts.
7. Services do not share database tables or filesystem state. Every cross-
   service operation is versioned, authenticated and idempotent.
8. A successful socket write is not reported as a confirmed physical print.

## Target bounded contexts

| Context | Owns | Must not own |
| --- | --- | --- |
| Thingdex | Inventory, locations, label automation and data bindings | Templates, printer addresses, rendering, device status |
| PrintHub | Templates, source documents, preflight, preview, logical jobs | USB/Bluetooth, RAW TCP, SNMP, physical retries |
| IPP Gateway | CUPS queues, IPP attributes, document upload, IPP status mapping | Rendering policy, printer registry, device protocols |
| PrinterFleet | Printer registry, capabilities, media, routing, deliveries, drivers | Inventory objects, templates, document design |
| PrintAgent | Local USB/Bluetooth/serial access and agent-side drivers | Global routing, templates, Thingdex integration |
| Studio | PrintHub user interface and designer | Authoritative server data |
| Thingdex Home Inventory | Release bill of materials, deployment and system docs | Product business logic |

## Target data flow

```text
Thingdex outbox ────────────────┐
PrintHub API ───────────────────┼──> PrintHub job + source document
Chrome/CUPS -> IPP Gateway ─────┘              |
                                                v
                              preflight / scale / raster / preview
                                                |
                                                v
                                  immutable PrintArtifact
                                                |
                                                v
                                         PrinterFleet
                                      /       |       \
                              RAW TCP     IPP device    PrintAgent
                              / serial       |          USB/Bluetooth
                             Zebra        printer       Niimbot
```

## Contract model

### Thingdex to PrintHub: PrintIntent

- Carries an idempotency key, source entity reference and source version.
- Refers to an immutable template revision or logical print profile.
- Contains resolved business data, never ZPL or printer credentials.
- Is written to a Thingdex transactional outbox with the inventory change.

### PrintHub to PrinterFleet: DeliveryRequest

- Carries one immutable artifact and its checksum.
- Carries media/capability requirements and either a logical destination or an
  explicit printer override.
- Uses a stable idempotency key derived from the PrintHub job and attempt.
- Is accepted durably before PrintHub considers submission successful.

### PrinterFleet to PrintHub: DeliveryEvent

- Uses an immutable event ID and monotonically ordered attempt sequence.
- Distinguishes `transport_accepted`, `confirmed`, `unconfirmed`, `failed` and
  `retry_scheduled`.
- Includes observed device/media snapshots without making PrintHub their source
  of truth.

### PrintHub to Thingdex: IntegrationEvent

- Reports logical job state and inventory-relevant media consumption only.
- Is signed and replay-safe.
- Never exposes device credentials or requires Thingdex to call an agent.

## Canonical document stages

```text
SourceDocument
  -> PreparedDocument (page boxes, target medium, fit/fill/hold decision)
  -> RasterDocument or device-neutral layout
  -> PrintArtifact (versioned MIME type + checksum)
  -> DevicePayload (created by PrinterFleet/agent driver)
```

The boundary deliberately keeps device encoding out of the core document
model. A ZPL driver may use native text/barcode operations when possible and a
raster fallback otherwise. A Niimbot driver consumes the same prepared raster
and applies its own compression and transport framing.

## Job ownership and states

PrintHub logical jobs:

```text
accepted -> preparing -> held | ready_for_delivery -> submitted
         -> failed | cancelled
```

PrinterFleet deliveries:

```text
queued -> connecting -> transmitting -> transport_accepted
      -> confirmed | unconfirmed | failed | retry_scheduled
```

Only PrinterFleet retries physical delivery. PrintHub retries submission only
until PrinterFleet durably accepts the idempotent request. This prevents two
independent retry loops from producing duplicate labels.

## Repository and image direction

- Rename `PrintHub-ZPL-ll` to `PrintHub` after package-level compatibility is in
  place. It remains independently usable outside Thingdex.
- Keep PrinterFleet and PrintAgent independently releasable. They may initially
  share a source repository if that improves driver contract testing, but they
  remain separate deployables.
- Keep the IPP gateway independently deployable even if its source temporarily
  lives beside PrintHub.
- Treat SDKs as generated contract artifacts; do not share internal domain
  classes across service boundaries.
- Keep the printer emulator a development tool and consume a pinned image in
  release deployments.
- Turn `Thingdex-Home-Inventory` into the canonical integration distribution
  with pinned image digests and a compatibility manifest.
- Retire the `Labeldrucker` integration repository after standalone Compose and
  IPP sources have moved to their owning products.

## Action items

- [x] 1. Record target boundaries, invariants, contracts, state ownership and
  migration gates in this plan.
- [x] 2. Introduce explicit PrintHub ports for document preparation, fleet
  capabilities and artifact delivery; place the current registry and transports
  behind a temporary legacy adapter without changing external behavior.
- [x] 3. Implement PrinterFleet with durable printer registry, capability/media
  snapshots, delivery records and direct `raw_tcp` and `serial_over_tcp`
  transports. Model delivery confirmation honestly.
- [x] 4. Move physical printer CRUD, discovery, RAW 9100, Zebra status and
  delivery retries from PrintHub to PrinterFleet. Keep a time-limited PrintHub
  compatibility facade for existing Studio and SDK clients.
- [x] 5. Evolve ZebraTamer into a vendor-neutral PrintAgent protocol. Keep direct
  network printers server-side and add agent-side Zebra plus Niimbot driver
  slots for USB/Bluetooth/serial devices.
- [x] 6. Thin the IPP gateway so it only advertises capabilities, receives
  documents, maps IPP tickets and reports PrintHub state. Move PDF/PostScript
  policy and raster decisions into PrintHub.
- [ ] 7. Replace Thingdex synchronous label calls with a transactional outbox,
  idempotent PrintHub connector and replay-safe status inbox. Remove every
  direct ZebraTamer/PrintAgent to Thingdex dependency.
- [ ] 8. Replace production sibling builds and Git submodules with signed,
  immutable component images, a compatibility manifest and standalone,
  integrated and development Compose profiles.
- [ ] 9. Add enterprise controls: OIDC-ready identities, service credentials,
  signed events, tenant/site scoping, audit records, correlation IDs, metrics,
  resource limits, backups and PostgreSQL migration paths.
- [ ] 10. Run contract, migration, failure-injection and real-device acceptance
  suites; remove beta compatibility endpoints; publish the first stable API and
  deployment compatibility matrix.

## Validation gates

- Standalone PrintHub accepts API and IPP jobs while Thingdex is absent.
- Thingdex creates and edits inventory while PrintHub is absent, then delivers
  queued intents exactly once after recovery.
- PrinterFleet sends directly to a network RAW-9100 emulator without an agent.
- An agent can disconnect during a job and resume without duplicate printing.
- A socket-accepted but unconfirmed job is never displayed as physically
  confirmed.
- A4-to-label mismatch remains held until an explicit policy is selected.
- Printer media changes invalidate stale routing decisions safely.
- A Niimbot driver can be added without changing Thingdex, IPP or PrintHub job
  contracts.
- Every production container runs non-root where its protocol permits, has
  readiness/health checks, resource limits and no embedded secrets.
- The integrated release installs from pinned images without local source trees
  or network access to package registries during startup.

## Migration safety

- Preserve current public IDs and job records during ownership moves.
- Export and verify registry/job backups before every irreversible schema move.
- Dual-read only during bounded migration windows; never maintain indefinite
  writable copies of printer or job state in two services.
- Add compatibility endpoints before moving consumers, then delete them in the
  next declared breaking release.
- Keep the current Compose stack as the executable regression baseline until
  the new vertical path passes the same PDF, IPP, held-job and virtual-printer
  tests.

## Open questions and working defaults

- Product name: use `PrinterFleet` as a working name until branding is chosen.
- Persistence: start with SQLite for a single-node vertical slice, but define a
  repository interface and migrations compatible with PostgreSQL before 1.0.
- Niimbot: reserve the driver contract now; implement and validate the wire
  protocol only when a real B1 and representative label media are available.

## Implementation log

### 2026-09-05: Fleet boundary and first vertical slice

- PrintHub now depends on `PrinterFleetPort`, `PrinterCatalogPort` and
  `ArtifactDeliveryPort` rather than calling RAW TCP or ZebraTamer from document
  preparation. The existing registry/transports remain behind
  `LegacyFleetAdapter` for bounded compatibility.
- `HttpPrinterFleetAdapter` implements the same boundary using the versioned
  `/v1/printers` and `/v1/deliveries` contract.
- A separately packaged and separately containerized `printer-fleet` service
  now persists printer snapshots, idempotent delivery requests and ordered
  delivery events in its own SQLite database.
- ZPL encoding and TCP delivery are independent adapters. `raw_tcp`, the legacy
  `raw9100` spelling and `serial_over_tcp` are supported without an edge agent.
- Compose routes PrintHub delivery through PrinterFleet. PrintHub's old printer
  administration endpoints are now a temporary compatibility facade over the
  Fleet port for list, get, create and revision-checked patch operations. Agent
  discovery, vendor status and import/export still need migration in action 4.
- Stable PrintHub jobs derive delivery idempotency keys from the logical job,
  physical attempt and page. Preparation/hold attempts are counted separately,
  so releasing a held A4-to-label job cannot accidentally skip delivery attempt
  identity.
- Automated status: PrinterFleet unit/API tests and the complete PrintHub suite
  pass. The Docker end-to-end build is pending because the local Docker Desktop
  Linux engine did not become responsive during this run.

### 2026-09-05: Physical ownership migration

- PrinterFleet now owns revision-checked printer writes, atomic import/export,
  durable PrintAgent observations, explicit device registration and physical
  status queries. Existing PrintHub URLs delegate to Fleet when configured and
  remain local only in legacy standalone mode.
- Configured printer data and observed media/capability state are persisted
  separately. Rediscovery updates the catalog view without changing an
  administrative registry revision or contaminating configuration exports.
- The ZebraTamer-specific network boundary is represented as the vendor-neutral
  `print_agent` transport; `zebra_tamer` remains a compatibility alias. Agent
  identity is verified before status or delivery and downstream job references
  are retained in the Fleet delivery.
- Delivery payloads are stored before physical I/O. A database claim prevents
  concurrent sends, transient failures receive bounded exponential retries and
  retry state survives a process restart.
- A restart during `connecting` or `transmitting` becomes `unconfirmed` instead
  of being retried automatically. PrintAgent submissions carry the Fleet
  idempotency key, while non-acknowledging RAW TCP remains deliberately
  conservative because its physical outcome cannot be proven.

### 2026-09-05: PrintAgent compatibility foundation

- ZebraTamer is now pinned as an integration submodule and advertises the new
  `_print-agent._tcp.local.` service beside its legacy DNS-SD name.
- Agent printers declare an explicit driver and the service identifies as
  PrintAgent while retaining the existing binary and v1 compatibility surface.
- Fleet idempotency is propagated to the agent. The agent persists the key and
  content checksum, returns the original job for identical submissions and
  rejects conflicting reuse. This Rust change still requires Cargo or Docker
  compilation because neither runtime was available on the current host.
- The versioned PrintAgent contract and the future Niimbot raster/driver split
  are recorded in `docs/architecture/PRINT_AGENT_PROTOCOL.md`.
- A driver-descriptor endpoint declares accepted device-payload MIME types.
  ZPL is executable and the Niimbot B1 contract is reserved but fails closed;
  it cannot be configured until an agent build contains the tested encoder and
  hardware implementation.
- Automated status after this slice: all 16 PrinterFleet tests and all 117
  active PrintHub tests pass; 159 optional PrintHub tests remain skipped by
  their existing environment markers. Compose configuration validates. Rust
  compilation and Docker end-to-end execution remain pending because Cargo is
  absent and the local Docker engine is not responsive.

### 2026-09-05: Thin IPP ingress

- The gateway now forwards the unchanged PDF, PostScript, image, PWG Raster or
  Apple Raster payload with a mapped IPP ticket to PrintHub's document-job API.
  It no longer rasterizes, chooses target DPI, enforces page mismatch policy or
  creates normalized page uploads.
- PrintHub durably stores the original source document before processing and
  owns page inspection, conversion, page limits, fit/fill/hold, grayscale,
  dithering and preview. Held source documents are reconverted when released.
- Poppler, Ghostscript and libcups move to the PrintHub runtime. The IPP image
  retains only the packages required to publish and receive IPP jobs.

### 2026-09-05: Asynchronous Thingdex integration

- Thingdex now records a versioned `PrintIntent` in the same PostgreSQL
  transaction as the inventory mutation. Ordinary inventory writes therefore
  remain available while PrintHub is offline.
- A separate worker claims outbox rows with a lease, submits them with stable
  idempotency keys and applies bounded retries. Operator retries start a fresh
  bounded attempt budget rather than creating a second logical intent.
- PrintHub status updates enter Thingdex through an HMAC-authenticated,
  replay-safe inbox with immutable event IDs and monotonically increasing
  sequences. PrintAgent has no Thingdex dependency. A durable PrintHub event
  outbox still has to be connected before this action is complete.
- Print intent administration is a fail-closed bearer-protected API and omits
  the captured variable payload from its responses.
- The PrintHub OpenAPI export now resolves the checked-out application rather
  than an installed package, and the TypeScript SDK exposes the document-job
  contract generated from that canonical schema.
- The Thingdex integration distribution starts API and print worker separately
  and wires PrintHub to PrinterFleet. Production image pinning and release
  compatibility metadata remain action 8.
- Automated status: six database-independent outbox tests, OpenAPI drift check,
  complete offline Alembic SQL generation and strict documentation build pass.
  The latest full suite has 6 passing and 23 PostgreSQL-dependent skipped tests;
  a live PostgreSQL and Docker run remains pending on this host.

### 2026-09-05: Production deployment boundary

- Source-building Compose remains explicitly a development profile. A new
  standalone production definition contains only immutable image variables;
  the optional Thingdex definition overlays PostgreSQL, one migration owner,
  API and outbox worker without introducing a runtime source dependency.
- IPP and Studio are opt-in production profiles. Service data stays in isolated
  volumes, host ports bind to loopback by default, and core services receive
  capability drops, no-new-privileges, PID and memory limits.
- A fail-closed release validator rejects mutable tags, all-zero example
  digests and example secrets. The compatibility-manifest shape records API
  generations and exact image references.
- PrintHub now runs as its previously created UID 10001. Thingdex migration
  ownership is configurable so the API/migrator can run Alembic once while the
  worker never races it.
- Compose structure validates for standalone and integrated profiles. Action 8
  remains open until CI publishes and signs real component digests and a real
  compatibility manifest; action 9 remains open for identity, audit, metrics,
  scoping and backup/restore automation.

### 2026-09-05: Authenticated Fleet boundary

- PrinterFleet can require a constant-time-checked bearer service credential
  for every `/v1/*` operation while leaving only its health probe public.
- PrintHub injects that credential exclusively in its Fleet HTTP adapter. It
  also supplies a correlation ID on every catalog and delivery call;
  PrinterFleet preserves valid upstream IDs and returns one on both successful
  and rejected requests.
- Development Compose exercises the protected boundary with an explicit local
  token. Production Compose requires a deployment secret and the release
  validator rejects an example value.
- Seventeen PrinterFleet tests and four focused PrintHub adapter tests pass.
  OIDC workload identities, metrics and site/tenant policy remain part of
  action 9.
- Fleet stores mutating calls and rejected access attempts in a durable audit
  journal with actor, status and correlation ID. Request payloads, credentials
  and print artifacts are deliberately excluded from audit rows.
- Fleet exports authenticated Prometheus gauges for registered printers and
  durable deliveries by current state, calculated directly from its database
  rather than maintained as a second in-memory source of truth.
