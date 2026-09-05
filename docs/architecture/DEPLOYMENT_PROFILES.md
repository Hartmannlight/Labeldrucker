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

Every production image value must be an OCI reference pinned by digest. Tags may
be published for humans, but never belong in a deployed release environment.
Create the environment from `deploy/.env.production.example`, inject secrets from
the site's secret manager, and validate it before Compose:

```sh
python scripts/validate_release_env.py /run/secrets/thingdex-release.env
```

`deploy/compatibility.example.json` defines the release bill-of-materials shape.
Release automation must resolve its image variables to the same digests, attach
the source revisions and sign both images and manifest. The all-zero digests and
`replace-me` secrets are deliberate fail-closed placeholders, not runnable
defaults.

State is isolated in service-owned volumes. Back up `printhub_data`,
`printer_fleet_data`, `ipp_spool` when IPP is enabled, and `thingdex_postgres`
before upgrades. Restore testing and signature verification are release gates,
not optional operational advice.
