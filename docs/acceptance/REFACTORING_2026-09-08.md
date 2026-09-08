# Refactoring acceptance — 2026-09-08

Status: simulator-tested implementation candidate. Physical-device, real-LAN
and released ARM64 acceptance remain open because no printer, Pi or clean LAN
client was available during implementation. The obsolete root `ipp-gateway/`
copy was removed; the only IPP implementation and build context is now the
canonical copy in the PrintHub repository.

## Automated evidence

- ZebraTamer: Rust formatting and 35 unit tests, including TCP, raster,
  persistence, identity, scoped authorization and queue recovery.
- PrintHub: 155 passed tests (159 optional Labelary comparison cases skipped), OpenAPI
  artifact equality, service registry,
  immutable jobs, IPP shares, document/raster processing and failure injection.
- IPP gateway: 21 tests (included in the PrintHub total). Two runtime queues on ports 8631 and
  8632 both passed CUPS `get-printer-attributes.test`.
- Studio: 2 architecture tests, TypeScript check and production Vite build.
- Published TypeScript SDK: 3 runtime/boundary tests, generated-schema check,
  typecheck and production build.
- Product tools: 3 tests for SQLite/versioned-JSON Fleet migration and
  checksum-verified backup/restore.
- Compose: standard, demo and USB-overlay configurations parsed. All four
  candidate containers passed bounded health and non-root process checks.

## Hardware-free end-to-end evidence

- Six isolated services became healthy without Fleet or Thingdex: PrintHub,
  Studio, ZebraTamer, IPP gateway, virtual RAW-9100 Zebra and the neutral raster
  service.
- Zebra template job `948ff517-82d6-4c21-b58f-3a67fa1cda85` transferred 8,454
  bytes and reached `transport_accepted`. Reusing its idempotency key returned
  the same logical and downstream job and produced no second 8,454-byte output.
- Raster template job `40f7cd87-e2c9-428e-8ed9-902e8b5603b7` reached
  `confirmed` and wrote one PNG. PDF job
  `4e4885e0-a123-4e01-9184-ffcc54cceb85` rendered one page, reached `confirmed`
  and wrote a separate PNG. Reusing the template key returned the same IDs.
- An IPP PDF submitted to the raster queue passed CUPS `print-job.test` and was
  deliberately held by PrintHub because its 50 x 50 mm page did not match the
  loaded 50.05 x 25.02 mm medium. This demonstrates pre-output media guarding.
- A second IPP PDF was submitted with the explicit `fit` policy to the paused
  Zebra queue. Standard CUPS `cancel-current-job.test` changed the local job to
  `processing-to-stop-point`; the gateway detected that state without a signal,
  cancelled PrintHub job `e1e53e77-2505-4cef-aac1-fc66d765c417` and downstream
  ZebraTamer job `a193c32b-3283-40aa-a6b3-743b8e642d7f`, and IPP finished as
  `canceled` with `job-canceled-by-user`.
- The common administrative path paused and resumed the ZebraTamer queue and
  returned the persisted states `true` and `false` respectively. The same path
  ran the allowlisted `calibrate-media` action and USB discovery returned a
  valid empty result on a host with no forwarded USB printer.
- Printer display name and default selection survived a PrintHub restart.
  Template jobs `01a5d52b-ba37-4fd7-87c8-7f75544ccc1b` (native Zebra) and
  `7039eea6-8e28-481a-af07-07d1f315756f` (neutral raster) reached
  `transport_accepted` and simulated `confirmed` respectively. Reusing the
  native idempotency key returned the same logical job.
- Two newly created IPP queues passed capability probes. A PostScript label sent
  through the raster queue completed and produced the durable mapping from IPP
  UUID to PrintHub job `37ccb49c-7191-4a0d-80ce-5230e3d820e3` and downstream
  job `b28d2ced-c15d-4387-baff-ddf8bc926943` in the IPP spool.
- Zebra template job `21c99d0b-4202-460c-8b1d-b3c6389587b0` explicitly selected
  whole-label raster output, reached `transport_accepted`, and delivered one
  20,059-byte rendered label to the RAW-9100 emulator.
- A clean copied product directory containing no component sources started all
  four product services healthy with `docker compose up --no-build`; this uses
  exactly the candidate image tags consumed by the release package.

During this run two defects were found and fixed: repeated TCP query sessions
now reconnect safely, and raw service state `completed_observed` now maps to
PrintHub `confirmed` instead of the ambiguous `unconfirmed` state. The final
audit additionally fixed the central maintenance route names, a cancellation
race before downstream dispatch, missing durable IPP correlation and a stale
generated SDK contract.

## Hardware acceptance still required before a production release

- Real Ethernet Zebra: model/firmware, TCP queries, dimensions, barcode,
  copies, reconnect and partial-transfer handling.
- Real USB Zebra or remote Pi: stable device selection, permissions, queries,
  restart and media accounting.
- Real 64-bit Pi: released ARM64 images and USB path.
- Real OS and CUPS/ipptool LAN clients: discovery/direct URI, two queues, holds,
  cancellation and status behavior.
- Native AMD64 and ARM64 release images pulled by digest from a clean host.

These items are deliberately not marked passed. Simulator acceptance proves
protocol and orchestration behavior, not physical paper output or LAN multicast.
