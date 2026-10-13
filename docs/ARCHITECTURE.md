# Architecture

The product separates content orchestration from device ownership.

See the [README diagrams and project map](../README.md#projects-and-responsibilities)
for runtime connections, ownership boundaries and job acknowledgements.
Studio uses its nginx `/api` proxy to reach PrintHub. IPP clients reach the
separate gateway, which reads PrintHub's share registry, submits documents and
polls logical job status. Optional Thingdex requests arrive from its outbox
worker; neither Thingdex nor its database is part of the product stack.

PrintHub persists the exact artifact before crossing the service boundary. It
chooses native ZPL when supported and otherwise renders the template to the
neutral one-bit raster envelope. A lost or ambiguous HTTP response is resolved
with the same dispatch key and identical payload. An explicit retry after a
proven failed delivery uses a new attempt key with the stored artifacts; an
unknown physical outcome is not automatically replayed. A changed request under
an existing idempotency key is a conflict.

Every print service owns its local printers, hardware configuration, observed
state and physical queue. Its stable service identity plus the local printer ID
forms the stable physical identity used by PrintHub's persisted public-ID
mapping. A `connection_id` identifies the configured service connection and is
not the same field as the service's persistent `service_id`. Consequently,
two services can each have a local printer named `default`.

ZebraTamer contains Zebra-specific queries, configuration, media accounting,
maintenance commands and transports. It accepts both ZPL and neutral raster
jobs. It is equally suitable beside PrintHub on a server for Ethernet printers
and by itself on a small Pi attached over USB.

IPP is an input adapter owned by the PrintHub repository but released as a
separate image because it needs CUPS/Avahi runtime packages. One gateway watches
PrintHub's persistent share registry and manages multiple stable TCP ports.

The base `backend` network is internal. PrintHub also joins `renderer-egress`
for Labelary, the optional AI provider and reachable remote print services.
In the demo, the virtual Zebra joins both networks so it can call Labelary.
The base ZebraTamer joins only `backend`: real Ethernet printers need an
[additional outbound network](INSTALLATION.md#ethernet-zebra-and-outbound-networking).
Services sharing `backend` can communicate without that additional network.

PrintHub admin tokens and print-service tokens are separate; neither is
compiled into Studio. The operator enters the admin token for administrative
requests; Studio stores it in session storage. Service credentials remain
server-side. This is not a user-account or multi-tenant authorization system.
External network access is a deployment decision, not a consequence of
setting only a printer's IP address.

Studio's optional Image designer owns a versioned bitmap design (millimetre
coordinates, text, embedded PNG/JPEG, rectangles). It renders directly on a
browser canvas at the selected printer's DPI and sends PNG to the existing
PrintHub raster-job API. This path does not compile or render ZPL. Designs can
be exported/imported as JSON; the last draft is also saved in browser storage.
These designs are separate from the server's ZPL template library.

The B1 service lives in `services/niimbot`. Transport, binary framing and job
persistence are separated. A single worker and an OS process lock serialize
device access. SQLite stores the whole immutable job before HTTP acceptance;
restart recovery marks interrupted transfers `outcome_unknown`. Device page
counters and progress confirm completion. Catalog readiness stays unknown
between jobs; configured label dimensions are not represented as RFID evidence.

## Demo and persistence boundaries

The emulator receives ZPL through TCP 9100 and renders it using Labelary.
Its recent jobs and rendered images are held in memory, with no Compose data
volume. It does not implement Zebra status/configuration queries or validate
real calibration, flash persistence or paper output. The raster test service
implements the neutral print-service API and writes simulated output to its
`raster_test_data` volume. Its completion state describes that simulation.

PrintHub owns logical jobs/artifacts and the catalog in `printhub_data`.
ZebraTamer owns device jobs, identity, configuration and media in
`zebratamer_data` (or `zebratamer_usb_data` for the USB instance). NIIMBOT owns
its SQLite queue in `niimbot_data`. The gateway owns spool, job mappings and
TLS identity in its two volumes. `printhub_secrets` holds bootstrap credentials;
PrintHub also persists registered connection credentials under its data tree.
See [backup scope](OPERATIONS.md#data-ownership).
