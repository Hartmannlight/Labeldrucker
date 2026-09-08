# Operations, backup and migration

## Data ownership

The named volumes `printhub_data`, `zebratamer_data`, `ipp_gateway_spool`,
`ipp_gateway_tls` and `printhub_secrets` are one consistency set. They contain
logical jobs, immutable artifacts, service identity, physical queue state, IPP
identity/spool data and credentials. Do not copy a live queue piecemeal.

For a consistent backup, stop job intake, let active transfers settle, run
`docker compose stop studio ipp-gateway printhub zebratamer`, copy each volume
to host directories, and archive those directories with:

```bash
python tools/backup_product.py create printhub-backup.tar.gz \
  --source printhub=backup-input/printhub \
  --source zebratamer=backup-input/zebratamer \
  --source ipp-spool=backup-input/ipp-spool \
  --source ipp-tls=backup-input/ipp-tls \
  --source secrets=backup-input/secrets
```

The archive contains a versioned manifest and SHA-256 for every file. Treat it
as a secret. Restore verifies every checksum and refuses a non-empty target:

```bash
python tools/backup_product.py restore printhub-backup.tar.gz restored
```

Copy the verified `restored/data/NAME` trees into empty replacement volumes,
then start ZebraTamer, PrintHub, IPP and Studio in that order. Never restore an
old active queue blindly after the new system has accepted jobs; reconcile and
hold all ambiguous deliveries first.

## Fleet migration

Stop old job intake and old workers, then make a database-level backup. Run the
importer without `--apply` first:

```bash
python tools/migrate_fleet.py fleet.sqlite3 > migration-dry-run.json
```

After reviewing conflicts and the manual-reconciliation list:

```bash
python tools/migrate_fleet.py fleet.sqlite3 --apply --output-dir migrated
```

For a PostgreSQL-backed Fleet, first create an offline, versioned JSON export
with top-level `format`, `printers` and `deliveries` fields using the old
installation's export/backup environment. Pass that JSON file to the same
command. PrintHub does not need a PostgreSQL driver or a live old database; the
importer preserves delivery history from both SQLite and JSON sources.

The tool never contacts hardware. Direct RAW-9100 targets become ZebraTamer
printer seeds; remote agent mappings retain public IDs and expected identities.
Known legacy delivery metadata is archived without artifact payloads. Receiving,
queued, transmitting, retrying and unknown legacy deliveries are never enqueued
automatically. Review device settings before applying them: relative `^MD` and
absolute `~SD`, for example, are not interchangeable.

The output directory must be empty. Import the reviewed printer records once,
connect remote services in Studio, compare IDs/media, and only then start new
workers. There is no dual-write mode.

## Updates and uncertain jobs

Back up first, pull/build one tested component set, then run `docker compose up
-d`. Stable volumes preserve identities. A normal retry is available only for
proven failures. `unconfirmed` means bytes may already have reached hardware;
inspect the printer and use **Reprint deliberately** to create a new audited job.

IPP-to-PrintHub mappings are stored below the IPP spool volume under
`mappings/QUEUE/`. They contain IPP job identity, PrintHub job identity and the
last observed state, but no document body. Include them in backup/restore; they
preserve correlation and idempotency across gateway restarts.

By default the per-job IPP helper remains alive while PrintHub reports
`queued`, `processing` or `waiting_for_service`. This prevents an IPP client
from seeing a completed job merely because a short polling window elapsed. A
client cancellation terminates the helper and is forwarded to PrintHub; if
device transmission is already unsafe to cancel, the resulting error remains
visible instead of triggering a replacement print. The optional
`PRINTHUB_IPP_STATUS_WAIT_SECONDS` is intended only for bounded diagnostics: an
expired positive limit fails the IPP command and never reports completion.
