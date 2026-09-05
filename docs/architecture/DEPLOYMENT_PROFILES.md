# Deployment profiles

The source-based root `compose.yaml` is the development profile. It intentionally
builds checked-out repositories and may include the printer emulator. It is not
a production release artifact.

Production uses `deploy/compose.standalone.yaml`. It contains no `build`, source
mount or package-install step. PrintHub and PrinterFleet always start; IPP and
Studio are explicit optional profiles:

```sh
docker compose --env-file /run/secrets/printhub-release.env \
  -f deploy/compose.standalone.yaml --profile ipp --profile studio up -d
```

Thingdex is an independent overlay rather than a mandatory PrintHub dependency:

```sh
docker compose --env-file /run/secrets/thingdex-release.env \
  -f deploy/compose.standalone.yaml \
  -f deploy/compose.integrated.yaml \
  --profile ipp --profile studio up -d
```

The integrated overlay has one short-lived migration owner. API and print worker
wait for it, then run with migrations disabled. The worker does not depend on a
healthy PrintHub container, so a PrintHub outage cannot prevent Thingdex from
starting or accepting inventory changes.

PrinterFleet needs network reachability to its managed printers, not a physical
USB connection to the container host. A Zebra Ethernet/WLAN endpoint is normally
configured as `raw_tcp` on port 9100. A transparent RS232-to-Ethernet bridge is
configured as `serial_over_tcp` with its actual port. Deploy a PrintAgent only
for USB, Bluetooth, local serial or a site network that is intentionally not
routable from the central Fleet service.

Every production image value must be an OCI reference pinned by digest. Tags may
be published for humans, but never belong in a deployed release environment.
Create the environment from `deploy/.env.production.example`, inject secrets from
the site's secret manager, and validate it before Compose:

```sh
python scripts/validate_release_env.py /run/secrets/thingdex-release.env \
  --manifest /run/releases/compatibility.json
```

Production Fleet authentication is file-mounted. The Fleet container receives
the complete principal document; PrintHub receives only its matching token in a
different secret file. The validator requires that this token maps to exactly
one principal with `observer` and `submitter`, explicit sites and no `admin`
role. Copy the examples under `deploy/secrets/` to ignored deployment-specific
paths and replace every placeholder before validation. The legacy global Fleet
token remains development/migration compatibility and is not used by the
production Compose profile.

`deploy/compatibility.example.json` defines the release bill-of-materials shape.
The Compatibility Release workflow accepts only exact source revisions and
digest-pinned images, verifies that every image is a native amd64/arm64 index,
and verifies each project image's GitHub provenance against its declared source
repository, commit and signer workflow. It then emits a deterministic manifest,
checksum and signed GitHub artifact attestation. The deployment validator rejects
an environment whose image values differ from that manifest. The all-zero
digests and `replace-me` secrets are deliberate fail-closed placeholders, not
runnable defaults.

`printer-fleet` and `printhub-ipp` are released by the root repository's
container pipeline because their source currently lives here. The pipeline
builds and smoke-tests native amd64 and arm64 candidates, scans them, exports
SBOMs, publishes exactly those tested archives, creates a multi-architecture
index and attaches GitHub build-provenance and SBOM attestations. Immutable
source/run tags are never overwritten. PrintHub and Studio retain the same
two-stage release pattern in their owning repositories.

Production IPP deliberately disables mDNS and runs from container start as UID
10002 with all Linux capabilities dropped. Add its explicit `ipp://` URL to
CUPS. The source-based development profile may start as root solely to launch
D-Bus and Avahi, then its PID 1 drops permanently to UID 10002 before accepting
jobs. This keeps discovery convenience out of the production privilege model.

State is isolated in service-owned volumes. Back up `printhub_data`,
`printer_fleet_data`, `ipp_spool` when IPP is enabled, and `thingdex_postgres`
before upgrades. Restore testing and signature verification are release gates,
not optional operational advice.
