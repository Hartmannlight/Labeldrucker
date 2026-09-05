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
3. PrinterFleet is the central printer control plane. It owns physical printers,
   capabilities, media state, routing, delivery attempts, vendor maintenance
   operations and device protocols; it does not own templates, page layout or
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
| PrinterFleet | Printer registry, sites, capabilities, media, routing, queues, deliveries, drivers and device administration | Inventory objects, templates, source documents, page layout |
| PrintAgent | Local USB/Bluetooth/serial access and agent-side drivers | Global routing, templates, Thingdex integration |
| PrintHub Studio | Template, preview and job user interface | Physical printer administration |
| Fleet Console | Operator interface over the PrinterFleet API | Rendering, templates, inventory data |
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
                              immutable prepared artifact
                                                |
                                                v
                                         PrinterFleet
                                /          |             \
                    Zebra RAW TCP   serial-over-TCP      PrintAgent
                       port 9100      bridge:any port     USB/Bluetooth
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

Network reachability, not physical attachment to the application host, decides
whether an agent is needed. A central Fleet instance connects directly to a
printer IP or transparent RS232-to-Ethernet bridge. Port 9100 is the default for
RAW/JetDirect, but every endpoint is configurable because serial bridges often
use another port. The optional agent is reserved for transports the Fleet host
cannot reach directly or for site-network segmentation.

Device administration follows the same rule. Zebra-specific status and safe
configuration commands for reachable network printers run in a Fleet driver;
they are not routed through PrintHub and do not require an agent. The Fleet API
is the authority and a separately deployable Fleet Console provides the
central, ZebraTamer-like operator experience without coupling that UI to the
document-preparation service. See `PRINTER_FLEET_CONTROL_PLANE.md`.

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
- Keep Fleet Console independently releasable as a static client of the
  PrinterFleet API. Its existence must not make the Fleet API or worker depend
  on a browser-facing process.
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
- [x] 7. Replace Thingdex synchronous label calls with a transactional outbox,
  idempotent PrintHub connector and replay-safe status inbox. Remove every
  direct ZebraTamer/PrintAgent to Thingdex dependency.
- [x] 8. Replace production sibling builds and Git submodules with signed,
  immutable component images, a compatibility manifest and standalone,
  integrated and development Compose profiles.
- [x] 9. Add enterprise controls: OIDC-ready identities, service credentials,
  signed events, tenant/site scoping, audit records, correlation IDs, metrics,
  resource limits, backups and PostgreSQL migration paths.
- [ ] 10. Qualify and publish the first stable platform release.
  - [x] Run the cross-component contract suite against the pinned component
    revisions.
  - [x] Run database migration, backup/restore and failure-injection suites.
  - [x] Remove migration-only PrintHub device-administration endpoints and
    runtime protocol aliases after their consumers have migrated.
  - [x] Publish candidate multi-architecture images with SBOM and provenance
    attestations for both supported CPU architectures.
  - [ ] Record independently reviewed acceptance against at least one real
    Zebra transport for the exact candidate revision. Every transport claimed
    by the release must have its own passing record.
  - [ ] Dispatch the stable Compatibility Release using that checked-in
    hardware record, then verify the signed API/deployment compatibility
    manifest and its immutable image digests.

## Validation gates

- Standalone PrintHub accepts API and IPP jobs while Thingdex is absent.
- Thingdex creates and edits inventory while PrintHub is absent, then delivers
  queued intents exactly once after recovery.
- PrinterFleet sends directly to a network RAW-9100 emulator without an agent.
- PrinterFleet sends to a configurable serial-over-TCP port without an agent.
- One unreachable or slow printer cannot block another printer's queue.
- Vendor maintenance commands are authorized, audited and serialized with jobs
  for the affected device.
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
  sequences. PrintAgent has no Thingdex dependency.
- Print intent administration is a fail-closed bearer-protected API and omits
  the captured variable payload from its responses.
- The PrintHub OpenAPI export now resolves the checked-out application rather
  than an installed package, and the TypeScript SDK exposes the document-job
  contract generated from that canonical schema.
- The Thingdex integration distribution starts API and print worker separately
  and wires PrintHub to PrinterFleet. Production image pinning and release
  compatibility metadata were completed by the first attested `v0.1.0` bill of
  materials described below.
- Automated status: outbox tests, OpenAPI drift check, Alembic migrations,
  strict documentation build and the complete PostgreSQL-backed suite pass.
  Native amd64 and arm64 candidate images also pass PostgreSQL runtime smoke,
  non-root, vulnerability, secret, misconfiguration and SBOM gates in CI.

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
- Compose structure validates for standalone and integrated profiles. Signed
  immutable component images and the first compatibility manifest now close
  action 8; action 9 remains open for production PostgreSQL Fleet persistence
  and its rehearsed migration path.

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

### 2026-09-05: Durable PrintHub status events

- Thingdex includes its immutable outbox ID as `origin_reference` when it
  submits a PrintHub job. PrintHub validates it as a UUID before creating any
  integration event and never infers identity from an idempotency-key format.
- Every externally visible job-state transition receives a monotonically
  increasing per-job sequence and a deterministic UUID. PrintHub writes the
  event before advancing the stored sequence, making a crash repeat the same
  event rather than lose it or invent a new identity.
- A separate worker claims persisted events with an expiring lease, signs the
  exact canonical JSON body with HMAC-SHA256 and applies bounded exponential
  retries. A crash after HTTP acceptance can only cause an at-least-once
  duplicate, which Thingdex's event journal treats as a successful no-op.
- Partial callback configuration fails PrintHub startup. Standalone PrintHub
  keeps the integration disabled; both development and production Thingdex
  overlays configure the URL and shared secret explicitly.
- Automated status: 125 PrintHub tests pass with 159 optional tests skipped,
  seven Thingdex outbox tests pass, the generated TypeScript SDK contract is
  current, strict Thingdex documentation builds, and both integrated Compose
  profiles validate.

### 2026-09-05: Root-owned image release gates

- PrinterFleet and the IPP gateway now have the same test-before-publish model
  as PrintHub and Studio: native amd64/arm64 candidates, runtime smoke tests,
  fail-closed vulnerability/secret scanning, SBOM export, immutable platform
  tags, a validated multiarch index and GitHub provenance/SBOM attestations.
- Release code refuses non-main/non-semver sources and existing immutable tags.
  Unit tests cover the platform matrix, digest policy, ref restriction and
  security gate; the combined root suite has 30 passing tests.
- The IPP production profile no longer requires startup capabilities. mDNS is
  disabled there and PID 1 starts as UID 10002. Development can explicitly run
  the entrypoint as root for D-Bus/Avahi initialization, after which it drops
  permanently to UID 10002.
- Thingdex now uses the same tested-candidate, multiarch publication, SBOM and
  provenance-attestation pattern as the other released services.

### 2026-09-05: Central Fleet control plane clarification

- PrinterFleet is explicitly the central physical-printer control plane, not an
  optional adapter hidden behind PrintHub. It directly manages reachable Zebra
  Ethernet/WLAN printers and transparent serial bridges; no Linux-attached
  device or site agent is required for these paths.
- RAW/JetDirect keeps port 9100 as a default rather than a fixed assumption.
  Serial-over-TCP remains a distinct connection profile with an explicit port
  and bridge metadata even though its current byte transport is shared.
- ZebraTamer-like central operations belong to versioned Fleet drivers and the
  Fleet API. A separately deployable Fleet Console can expose those operations
  without adding physical administration to PrintHub Studio.
- Fleet API and delivery workers may initially share one container because they
  belong to one bounded context and one transactional data model. Their module,
  lease and queue boundaries still permit later worker scaling without changing
  the public contract.
- Thingdex now also builds native amd64/arm64 candidates from locked
  dependencies, smoke-tests them with PostgreSQL, scans them and publishes only
  the exact tested archives with SBOM and provenance attestations.

### 2026-09-05: Per-printer delivery scheduling

- Fleet now selects only the oldest pending delivery for each physical printer.
  A database-serialized claim rejects overlapping or out-of-order sends even
  when concurrent API requests or worker processes compete.
- The worker processes different printer heads concurrently with a bounded
  thread pool. A slow network Zebra therefore cannot block unrelated devices,
  while bytes for one device remain strictly FIFO.
- `PRINTER_FLEET_MAX_PARALLEL_PRINTERS` configures the per-process endpoint
  concurrency and fails closed outside the range 1–64. Development and
  production Compose expose the same setting with a conservative default of 4.
- Registry writes now normalize direct RAW TCP defaults and reject ambiguous
  bridge ports, malformed hosts, embedded agent URL credentials, unsafe
  timeouts and unknown protocols before a configuration becomes authoritative.
- Deliveries and Zebra status operations now acquire the same durable
  per-printer lease. Concurrent status receives a busy response instead of
  inserting query commands into an active print stream; only the owner releases
  a lease and an abandoned lease expires conservatively.
- The complete PrinterFleet suite has 31 passing tests, including coordinated
  concurrency, claim-order, registry-boundary and operation-exclusion coverage.

### 2026-09-05: Attested compatibility bill of materials

- A root-owned Compatibility Release workflow assembles independently released
  component digests into one deterministic versioned manifest instead of
  rebuilding sibling repositories.
- The gate resolves every digest as a native linux/amd64 and linux/arm64 index.
  For project-owned images it also verifies GitHub provenance against the exact
  source repository, source commit and pinned signer workflow before assembly.
- The manifest and checksum receive their own GitHub artifact attestation. The
  production environment validator can require exact equality between all six
  image variables and this signed bill of materials.
- Compatibility Release `v0.1.0` (GitHub Actions run `33950121168`) verified and
  assembled the first real component set. Its deterministic manifest checksum
  is `742c40be60136f2bbfaf1d26c1798c6c03e1644849ea5e5da418d2f471ee516e`;
  the downloaded checksum and the manifest's GitHub build-provenance
  attestation were independently verified after publication. This closes
  action 8.

### 2026-09-05: Fleet principals and site boundaries

- Fleet authentication now resolves credentials through an injectable
  authenticator port into a stable principal containing roles and allowed site
  IDs. This keeps route policy unchanged when bearer credentials are later
  replaced by an OIDC verifier.
- Structured credentials support separate `submitter`, `observer` and `admin`
  roles. Printer catalogs, delivery submission/history and status are filtered
  by site; cross-site identifiers return not-found rather than leaking fleet
  membership.
- Global metrics, audit history, agent enrollment and registry transfer require
  a global administrator. PrintHub can operate with only observe/submit access
  to its assigned sites.
- The single global token remains as a migration-only compatibility adapter and
  cannot be configured together with structured credentials. The complete Fleet
  suite now has 37 passing tests.

### 2026-09-05: Least-privilege production Fleet secrets

- Production Compose no longer shares a global Fleet administrator token with
  PrintHub. Fleet receives its structured credential document through one
  mounted secret; PrintHub receives only its own token through another.
- The PrintHub Fleet adapter supports a token file and fails startup when file
  and inline sources are combined. The release validator proves that the token
  matches exactly one non-admin principal with observe/submit roles and explicit
  sites.
- Example secret files are committed only as fail-closed templates; matching
  deployment-specific files are ignored. Six focused PrintHub adapter tests and
  55 combined platform tests pass, and production Compose validates.

### 2026-09-05: Fleet backup and schema safety

- Fleet now creates transactionally consistent online SQLite backups through
  the SQLite backup API and emits a manifest containing schema generation,
  bounded record counts, file size and SHA-256 checksum.
- Verification checks both database integrity and every manifest fact. Restore
  re-verifies the source, builds a temporary database and atomically creates a
  new target; it refuses to overwrite operator data.
- The database records schema generation 1 and fails closed when opened by
  software older than the stored generation. This replaces silent ad-hoc
  downgrade behavior with the first explicit migration boundary.
- All 42 Fleet tests pass, including Windows restore locking, tamper detection,
  non-overwrite and future-schema regressions. At this milestone, scheduled
  off-host backups and a PostgreSQL repository implementation remained open;
  both were completed by the later PostgreSQL and deployment work below.

### 2026-09-05: Durable queue administration

- Fleet exposes a site-scoped delivery inventory with printer, state and bounded
  result filters. Authorization is applied in the database selection before the
  limit, so jobs from another site cannot hide visible work or leak identifiers.
- Site administrators can persistently pause and resume one physical printer.
  A pause rejects new work, prevents workers from claiming queued deliveries and
  preserves the queue for FIFO continuation after resume. It deliberately does
  not imply cancellation of a transmission that may already have reached the
  printer.
- Pause state, operator reason and timestamp live in Fleet's authoritative
  database rather than process memory. Schema generation 2 migrates existing
  generation-1 databases forward and includes controls in verified backups.
- All 45 Fleet tests pass, including API role/site policy, migration, restart,
  pause/resume and queued-work regressions. At this milestone, richer operator
  workflows, retention policy and production database scaling remained open;
  the action-9 controls were subsequently completed below.

### 2026-09-05: Asynchronous Fleet acceptance boundary

- Fleet delivery submission now commits the immutable artifact and returns HTTP
  202 in `queued` state without opening a device connection in the API request.
  PrintHub therefore depends only on durable Fleet acceptance, not port-9100
  latency or reachability.
- The delivery worker is the sole normal device-I/O path. It remains enabled in
  the compact single-container profile, while an explicit switch permits API
  and worker process separation later without another service contract.
- Fleet API tests prove zero transport calls before the response and successful
  worker delivery afterward. The PrintHub contract test accepts `queued` as the
  authoritative receipt instead of assuming immediate socket acceptance.

### 2026-09-05: Fleet persistence ports

- Delivery orchestration and PrintAgent discovery now depend on narrow
  structural repository ports. SQLite remains a composition-root adapter rather
  than an application-service dependency.
- The PostgreSQL migration contract explicitly requires atomic idempotency,
  oldest-per-printer claims, device leases and ordered state/event writes. The
  cutover uses one writer and a verified stop/import/compare/switch sequence;
  indefinite dual-write is excluded.
- This established the implementation seam. The PostgreSQL adapter and automated
  migration rehearsal described below subsequently passed the same repository
  contract suite.

### 2026-09-05: PostgreSQL Fleet implementation

- The composition root now selects SQLite for compact local deployments or a
  dedicated PostgreSQL adapter from an inline/file-backed database URL. The
  complete API depends on `FleetRepositoryPort`, not either adapter class.
- PostgreSQL initialization is versioned and advisory-lock serialized. Queue
  creation uses atomic conflict handling; claims use row locks plus the durable
  per-printer lease, preserving FIFO and excluding overlapping device I/O.
- The offline cutover copies all Fleet-owned tables from a current SQLite
  database into an empty PostgreSQL target in one transaction. Counts and
  canonical SHA-256 fingerprints are compared before commit; indefinite dual
  writes are deliberately unsupported.
- CI now provisions PostgreSQL and exercises registry revisions, pause state,
  concurrent idempotency, FIFO claims, ordered events, leases and the complete
  SQLite-to-PostgreSQL migration rehearsal. Production Compose gives Fleet a
  database and credentials separate from Thingdex.
- The remote PostgreSQL suite and production container gate passed in
  [CI run 33951140893](https://github.com/Hartmannlight/Labeldrucker/actions/runs/33951140893).
  That gate also creates a custom-format `pg_dump`, restores it into a fresh
  database and compares authoritative table counts.
- [Container Release run 33951140966](https://github.com/Hartmannlight/Labeldrucker/actions/runs/33951140966)
  passed native amd64/arm64 build, runtime smoke, vulnerability scan, SBOM
  attestation and multi-architecture publication. The verified Fleet image is
  `ghcr.io/hartmannlight/printer-fleet@sha256:0bba2ad0d19f883294de7828f9af56a214fd7c6f83f90c0c39723eeac25b2e49`.
  Together with the documented off-host backup schedule and restore runbook,
  this closes action 9.

### 2026-09-05: Allowlisted Zebra maintenance

- Fleet now owns an explicit driver-scoped maintenance service instead of
  exposing arbitrary ZPL administration bytes. The initial Zebra allowlist is
  configuration label, network configuration label and media calibration,
  following Zebra's published `~WC`, `~WL` and `~JC` definitions.
- Each operation requires a site administrator, is captured by the Fleet audit
  boundary and competes for the same durable device lease as status and print
  delivery. Busy devices return HTTP 409 without interleaving bytes.
- Responses identify media-moving effects and retain honest
  `transport_accepted` semantics. Fifty Fleet tests cover fixed command bytes,
  arbitrary-command rejection, driver rejection, role policy, auditing and
  lease exclusion.

### 2026-09-05: Production Fleet process isolation

- The production profile now runs the Fleet HTTP control plane and physical
  delivery loop as separate processes from the same immutable image. They share
  the Fleet database contract, not in-process state; the compact development
  profile may still embed the worker.
- Interrupted-delivery recovery belongs exclusively to the delivery process.
  Restarting the API can no longer mark a job owned by a live worker as
  `unconfirmed`.
- A deterministic failure-injection test blocks one printer transport while a
  second printer completes. The worker has its own database readiness probe and
  the production Compose definition validates with the split enabled.
- This starts action 10. Automated release gates still need the full cross-repo
  contract matrix, removal of migration-only aliases, and recorded real-device
  acceptance before the first stable release.

### 2026-09-05: Cross-component integration gate

- A dedicated Linux workflow checks out the exact submodule revisions and builds
  the complete source platform rather than smoke-testing images in isolation.
- The gate uses CUPS `ipptool` to inspect driverless capabilities, sends a real
  50 x 50 mm PDF through IPP, and verifies PrintHub's durable document job.
- It then proves that an A4 page is held without transmission, explicitly
  releases the same job with `fit`, and requires both payloads to arrive through
  PrinterFleet at the RAW-9100 Zebra emulator.
- [Platform Integration run 33952391884](https://github.com/Hartmannlight/Labeldrucker/actions/runs/33952391884)
  passed the complete gate with the pinned subrepository revisions.
- Failure output is limited to container state; unfiltered application logs are
  not uploaded. Real-device and agent-disconnect acceptance remain manual gates.

### 2026-09-05: Lost PrintAgent response handling

- A protocol-level failure-injection test now lets PrintAgent accept and persist
  a job, then drops the first HTTP response. Fleet schedules a bounded retry with
  the identical idempotency key; the simulated agent returns the existing job
  instead of creating a second physical print.
- The recovered Fleet delivery retains the single downstream job ID and honest
  `transport_accepted` state. Real hardware disconnect timing remains part of
  the manual acceptance gate.
- Action 10 remains open: Studio and SDK still consume the migration-only
  PrintHub printer-administration facade, a Fleet Console does not yet replace
  that workflow, and no real Zebra/bridge/PrintAgent acceptance record exists.

### 2026-09-05: Thingdex canonical job contract

- Thingdex's durable outbox worker is now the only runtime print submission
  path and is contract-tested against `POST /v1/print-jobs` with its stable
  idempotency key and immutable intent reference.
- The unused synchronous helper, including its fallback to the migration-only
  `/v1/printers/{id}/prints/template` endpoint, has been removed. Inventory
  requests continue to commit without contacting PrintHub.
- Thingdex is therefore no longer a consumer blocking removal of direct
  template submission.
- PrintHub's canonical job accepts either a stored template ID or an immutable
  inline template snapshot. Studio uses the snapshot form for unsaved drafts,
  the SDK no longer exposes direct template submission, and the legacy HTTP
  route has been removed from the public OpenAPI contract.

### 2026-09-05: Canonical path release verification

- Studio now uses a pinned minimal nginx runtime with a project-owned non-root
  main configuration. This removes distribution-specific PID and HTTP include
  assumptions while keeping runtime configuration generation explicit.
- [Studio Container Release run 33954352045](https://github.com/Hartmannlight/LabelArchitect/actions/runs/33954352045)
  passed source checks, CodeQL-adjacent security gates, native amd64/arm64
  runtime smoke tests, vulnerability scans, SBOM/provenance attestations and
  multi-architecture publication. The separate
  [CodeQL run 33954351887](https://github.com/Hartmannlight/LabelArchitect/actions/runs/33954351887)
  also passed.
- [Platform CI run 33954365889](https://github.com/Hartmannlight/Labeldrucker/actions/runs/33954365889)
  passed the root service suite, PostgreSQL backup/restore rehearsal, Compose
  validation and native Fleet/IPP container gates.
- [Platform Integration run 33954365770](https://github.com/Hartmannlight/Labeldrucker/actions/runs/33954365770)
  passed driverless capability discovery, a 50 x 50 mm PDF job, explicit
  release of an A4-to-label hold and delivery of both jobs through PrinterFleet
  to the RAW-9100 emulator.
- [Platform Container Release run 33954365974](https://github.com/Hartmannlight/Labeldrucker/actions/runs/33954365974)
  passed native validation and published attested multi-architecture Fleet and
  IPP images.
- Action 10 remains open deliberately: migration-only printer administration
  still needs replacement by Fleet Console, remaining aliases require a stable
  breaking release, and Zebra, serial-bridge and PrintAgent acceptance must be
  recorded against real hardware.

### 2026-09-05: Fleet Console and Studio boundary cut

- The separately deployable Fleet Console now administers physical printers,
  direct RAW-9100 and serial-over-TCP endpoints, queues, status, allowlisted
  maintenance, PrintAgent discovery and the Fleet audit trail. Its operator
  credential remains browser-memory-only and its same-origin proxy preserves
  the authorization boundary.
- PrintHub Studio no longer contains physical discovery, configuration, status
  or maintenance code. Its former printer screen is now a logical job review
  screen; old `/#/printers` bookmarks land on `/#/jobs`, and an explicit
  browser-facing runtime URL opens Fleet Console.
- The curated PrintHub SDK printer client is restricted to read-only selection
  snapshots. An architecture test prevents reintroduction of PrintHub printer
  administration methods.
- Source builds, Studio and SDK tests, production Compose validation and a
  non-root Studio container smoke test pass locally. The matching Studio
  container release, CodeQL and SDK CI gates also pass publicly.
- After those consumer gates passed, PrintHub removed printer mutation,
  registry import/export, ZebraTamer discovery, device-status and raw-ZPL
  routes from its public OpenAPI contract. Its Fleet port now contains only
  read-only capability snapshots and immutable artifact delivery. The complete
  PrintHub suite reports 127 passed tests and the built non-root container
  returns 404 for the retired route.
- Public verification passed in the
  [Studio Container Release](https://github.com/Hartmannlight/LabelArchitect/actions/runs/33956046157),
  [PrintHub Container Release](https://github.com/Hartmannlight/PrintHub-ZPL-ll/actions/runs/33956650624),
  [PrintHub CodeQL](https://github.com/Hartmannlight/PrintHub-ZPL-ll/actions/runs/33956650185),
  [SDK CI](https://github.com/Hartmannlight/printhub-sdk/actions/runs/33956626803)
  and [SDK CodeQL](https://github.com/Hartmannlight/printhub-sdk/actions/runs/33956626838)
  runs.
- Action 10 remains open for the deliberate stable breaking release and recorded
  Zebra, serial-bridge and PrintAgent hardware acceptance.

### 2026-09-05: Device-independent artifact and legacy Fleet removal

- PrintHub now emits `application/vnd.printhub.raster-page+json` after sizing,
  scaling and dithering. The immutable contract carries one-bit row-major pixels,
  resolution and job copies, but no transport or vendor endpoint.
- PrinterFleet's Zebra driver validates that contract, generates ZPL `^GF` and
  applies device-specific settings only after its worker claims the delivery.
  This is the shared prepared-raster seam for a future Niimbot driver.
- PrintHub's local physical registry, discovery worker, RAW TCP code,
  ZebraTamer client and `LegacyFleetAdapter` have been removed. Missing Fleet
  configuration now fails printer operations explicitly with HTTP 503 while
  document editing and persistence remain independent.
- `python -m printer_fleet.legacy_import` converts old PrintHub YAML, JSON or
  SQLite registries without mutating the source. Protocol aliases are
  normalized and ambiguous agent identities fail closed.
- The checked-in PrintHub OpenAPI document is regenerated and protected by an
  exact artifact-to-application regression test.
- Runtime protocol, discovery and global-authentication aliases have also been
  removed after adding the offline registry migration. Action 10 now remains
  open for stable version publication and recorded real-hardware acceptance.
- Fleet catalog responses are now role-aware: administrative clients retain the
  complete device record, while PrintHub's observer/submitter identity receives
  only a strict capability and loaded-media projection. Docker verification
  proves that connection data, Zebra settings and internal observation URLs do
  not reach PrintHub.
- The rebuilt Docker stack held an A4 PDF targeting a 50 x 50 mm label without
  device traffic. Explicit `fit` release then stored the prepared-raster MIME
  artifact in PrinterFleet, reached `transport_accepted`, and produced exactly
  one RAW TCP job in the virtual Zebra.

### 2026-09-05: Fail-closed real-hardware release evidence

- The stable Compatibility Release can no longer be assembled from image
  digests alone. It requires a sanitized, machine-readable and independently
  reviewed hardware record for the exact tested platform candidate.
- Every common scenario and every transport advertised by that release must be
  `pass`. Unsupported or unavailable serial bridge and PrintAgent paths remain
  explicitly unadvertised rather than being inferred from emulator coverage.
- Compatibility-manifest schema version 2 contains the evidence digest,
  review/test timestamps and exact supported-transport list; the evidence file
  is published beside the attested manifest.
- The candidate revision is now an explicit release input. This avoids a
  circular provenance requirement when evidence is committed only after the
  candidate images have undergone physical testing.
- Action 10 remains open only for filling that record with real Zebra evidence
  and intentionally dispatching the first stable compatibility release.

### 2026-09-05: Docker Desktop USB hardware path

- PrintAgent now supports an explicit `usb_bulk` transport selected by USB VID,
  PID and optional serial identity. It discovers only printer-class bulk
  endpoints, fails closed on ambiguous devices and keeps the existing
  character-device transport for native Linux installations.
- The Docker Desktop profile passes only the resolved USB device node to a
  non-root UID/GID 999 process. Its root filesystem is read-only, all Linux
  capabilities are dropped and `no-new-privileges` is enabled; neither PrintHub
  nor PrinterFleet receives host-device access.
- The runtime links Debian's `libusb-1.0.so.0` dynamically. A real Zebra LP 2824
  Plus was identified bidirectionally at 203 dpi through USB/IP from Windows to
  Docker Desktop; firmware, hardware identity and status queries completed.
- PrinterFleet discovered and registered the agent device, and PrintHub exposed
  only its public 50 x 25 mm media/capability projection. Multiple uniquely
  marked one-page raster jobs traversed PrintHub -> PrinterFleet -> PrintAgent
  -> USB with a single physical label per job and honest
  `transport_accepted` state.
- The run found and fixed a real control-plane gap: allowlisted Zebra
  maintenance was restricted to direct TCP despite `print_agent` already being
  a registered transport. Maintenance now uses the same transport registry and
  canonical `application/zpl` contract. A Fleet-issued media calibration changed
  the erroneous device-reported length from 79 to 212 dots for the loaded
  25 mm gap labels.
- User-observed alignment exposed persistent device offsets independently of
  raster preparation. Typed, revision-checked Agent configuration was used to
  read back and save the device calibration without putting offsets into
  templates. Final visual measurement, power-cycle persistence, disconnect
  ambiguity, CUPS/browser, color/dither and independent review remain open; no
  stable compatibility release is authorized by this development run alone.

### 2026-09-05: Revision-bound USB control run

- The PrintAgent development image was rebuilt with the exact pinned ZebraTamer
  revision embedded instead of the non-auditable `unknown` build identifier.
  After replacement, its identity API reported `1ccaace73fc66bb53dd0045efaa83725eb6943f6`.
- PrinterFleet then completed a fresh bidirectional status request to the USB
  Zebra and reported it ready. The narrow device mapping and hardened runtime
  settings remained unchanged.
- A uniquely marked 50 x 25 mm job traversed the current platform revision
  `04b4eb02a5e02a48217be87244b94e1b3d1aa35b` through PrintHub, Fleet and one
  idempotently identified Agent job. Every software boundary ended in honest
  `transport_accepted` state.
- The operator confirmed exactly one physical label and correct vertical
  alignment. Its left border was clipped and the right white margin was about
  2 mm, so horizontal alignment failed. A revision-checked device-only
  correction changed `LEFT POSITION` from `+10` to `+6` while retaining
  `LABEL TOP +4`; one uniquely marked comparison job reached
  `transport_accepted`. The operator measured an approximately 1 mm right
  margin and confirmed that the rest of the alignment was correct, so the
  corrected device-specific alignment passes this development run.
- Stable evidence remains gated on the other declared hardware scenarios,
  published candidate digests and a different human reviewer.

### 2026-09-05: Docker IPP/PDF hardware path

- The running IPP gateway was pointed at the Fleet-owned USB Zebra without
  changing PrintHub, Fleet or Agent responsibility boundaries. It advertised
  the observed 50 x 25 mm media, 203 dpi and monochrome mode, and passed the
  official CUPS printer-attributes test.
- A second container reached the host-published IPP port, proving the Docker
  ingress path used by a local CUPS client. A temporary Debian CUPS instance
  subsequently created a driverless queue with `lpadmin -m everywhere`; its
  generated queue exposed the loaded 50 x 25 mm medium and monochrome output.
- A verified 50 x 25 mm PDF traversed IPP, PrintHub, PrinterFleet and PrintAgent
  in one attempt and ended in `transport_accepted`; physical confirmation is
  pending.
- An A4 PDF submitted through the same endpoint was held with an explicit
  210 x 297 mm versus 50 x 25 mm mismatch and created no Fleet delivery or
  Agent job. A second submission through the actual CUPS queue with `lp -o raw`
  produced the same safe result. The explicit `fit` release and a normal
  filtered Chrome print remain separate physical tests.
- The real CUPS setup exposed a custom-hostname startup defect that loopback
  testing had hidden. `ippeveprinter` opens IPv4 and IPv6 listeners, while the
  development Compose profile mapped custom names only to IPv4 loopback and the
  production profile did not pass the hostname through. Both profiles now map
  the configured name to `127.0.0.1` and `::1`; production passes it explicitly,
  and CI boots the integration platform with a non-default hostname.

### 2026-09-05: PrintAgent restart recovery

- Restarting the hardened PrintAgent container preserved its exact image,
  non-root identity, read-only root filesystem, dropped capabilities,
  `no-new-privileges` setting and single-device USB mapping.
- The restarted Agent reported the pinned ZebraTamer revision, rediscovered the
  USB printer and read back the saved 50 x 25 mm device settings (`LEFT
  POSITION +6`, `LABEL TOP +4`, 212-dot length and 400-dot width).
- PrinterFleet subsequently reached the Zebra bidirectionally and reported it
  ready. No label was emitted by the restart verification.
- This closes only the container-restart recovery check. Physical printer power
  cycling, USB disconnect ambiguity and in-flight response loss remain explicit
  manual gates for action 10.
