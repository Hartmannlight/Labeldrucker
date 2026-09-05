# PrinterFleet control plane

Status: target architecture

## Purpose

PrinterFleet is the central authority for physical printers. A printer does not
need to be attached to the Linux or container host. If the host can route to an
Ethernet/WLAN printer or a transparent RS232-to-Ethernet bridge, Fleet talks to
that endpoint directly. RAW/JetDirect defaults to TCP port 9100; the port remains
configurable for bridges and non-default printer setups.

PrintHub remains a document service. It prepares and previews jobs, then hands a
durable immutable artifact plus requirements to Fleet. It neither stores device
credentials nor implements vendor maintenance commands.

## Runtime pieces

```text
PrintHub ---> PrinterFleet API ---> durable per-printer queues ---> drivers
                    ^                                      /        |       \
                    |                              Zebra TCP   TCP bridge   agent
             Fleet Console                           :9100      :config    local I/O
```

`PrinterFleet API` and its delivery workers form one product and ship from the
same image. The compact development profile co-locates them; production runs two
processes so device latency and worker restarts are isolated from the control
plane. They use separate modules, database transactions and worker leases, so
the deployment split does not introduce another service contract. The API
transaction ends after the immutable artifact is durably queued; only a delivery
worker opens the normal printer connection. Fleet Console is a separate static
web image.
PrintAgent is a separate process installed only where direct network reachability
is impossible or where USB, Bluetooth or local serial access is required.

## Ownership limits

Fleet owns:

- sites, printers, endpoints, credentials and trust relationships;
- declared and observed capabilities, loaded media and health snapshots;
- routing, per-printer queues, attempts, retry policy and outcome evidence;
- device drivers, transport sessions and audited maintenance operations;
- central operator APIs for discovery, configuration, pause/resume, test prints,
  diagnostics and firmware metadata.

Fleet does not own templates, source PDFs, business data, label composition,
page-fitting policy or inventory entities. Large source documents remain in
PrintHub; Fleet receives only the prepared immutable artifact required for a
delivery.

## Direct Zebra and serial-bridge support

The Zebra network driver uses the physical endpoint directly. Job submission,
status queries and configuration commands share a per-printer coordinator so a
status request cannot interleave bytes with a print stream. A successful socket
write means `transport_accepted`, never confirmed paper output. Confirmation is
reported only when the selected device protocol provides trustworthy evidence.

`raw_tcp` models a network printer, with port 9100 as its default.
`serial_over_tcp` models a transparent bridge and requires explicit serial
assumptions such as flow control to be represented as endpoint metadata even
when the bridge exposes only a byte stream. These are different connection
profiles despite sharing a TCP transport implementation.

Maintenance is a driver capability, never an arbitrary byte tunnel exposed to
operators. The first ZPL allowlist can print the printer and network
configuration labels or initiate media calibration. Every action requires site
administration, is audit logged, and acquires the same per-printer operation
lease as delivery and status. Media-moving/calibrating effects are explicit in
the action metadata; potentially destructive reset, flash and object-deletion
commands are not exposed.

Vendor-neutral Fleet records hold common capabilities and state. Zebra-specific
settings live in versioned driver configuration. Future Niimbot behavior is
implemented behind another driver and, when Bluetooth/USB is required, executed
by PrintAgent. Neither case changes PrintHub or Thingdex contracts.

## Enterprise topology

A company normally runs one logical Fleet control plane and assigns printers to
sites. Directly reachable printers need no local computer. A site agent or later
site gateway is added only across a routing or hardware boundary. The central
service remains authoritative; agents cache only the minimum durable job and
device state needed for safe delivery.

Each printer has an independent leased queue. Slow or offline devices therefore
do not block other printers. Administrative commands require narrower operator
permissions than job submission, are correlated and audited, and are serialized
with delivery for the same device. Network credentials and vendor secrets never
cross into PrintHub, Thingdex or browser storage.

Authentication resolves into a transport-independent Fleet principal with
roles and allowed sites. Structured bearer credentials implement that contract
first; an OIDC verifier can replace the authenticator without changing domain or
route policy. Site filtering is enforced server-side for catalogs, deliveries
and status. Cross-site misses return not-found, while global audit, metrics,
agent enrollment and registry transfer require a global administrator.

Catalog projection is role-aware. Fleet administrators receive the complete
physical record needed by Fleet Console. Observer and submitter identities such
as PrintHub receive an explicit allowlist containing identity, loaded media,
alignment, capabilities and operational control state. Connections,
vendor-driver settings, defaults, dynamic observation URLs and raw agent state
never cross that boundary.

## Evolution rule

Keep the API and worker in one Fleet image and bounded context, but run the
production worker as a separate process for scaling and failure isolation. Do
not create a second HTTP service contract merely to obtain that process split.
Keep Fleet Console and PrintAgent separate because they have different trust,
release and deployment boundaries.

Persistence follows the same boundary rule. Delivery orchestration and agent
discovery consume narrow repository ports; the composition root chooses SQLite
for compact deployments and PostgreSQL for production. Both implement atomic
idempotency insertion, oldest-per-printer claims, device leases and state/event
writes. Migration uses one authoritative writer: verify a source backup, stop
acceptance, import and compare records, then switch the API and workers together.
Indefinite dual-write is forbidden.
