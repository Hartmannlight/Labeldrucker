# Development

Only these submodules are required for the standalone product:

```bash
git submodule update --init components/PrintHub-ZPL-ll components/printhub-sdk components/LabelArchitect components/ZebraTamer
```

The Zebra emulator is optional for the demo profile. Thingdex repositories are
optional API consumers and are not referenced by the product Compose or release
matrix.

## Build and test from the repository root

For native development, install Python 3.11+, Poetry, Node.js 22.23.2+ with
npm, and a Rust toolchain. ZebraTamer's build also needs `pkg-config` and libusb
development headers (Debian/Ubuntu: `libusb-1.0-0-dev`). Native PrintHub also
needs `libdmtx0b`, `libcups2`, `poppler-utils` and `ghostscript` for barcode and
document/raster paths; these are provided by its Docker runtime image.
Python 3.11 is the
NIIMBOT package minimum; use the versions in root CI when reproducing its run.
Studio imports `@printhub/sdk` from the sibling directory, so install/build the
SDK before testing Studio. Subshells below keep every command rooted correctly.

```bash
docker compose config --quiet
docker compose -f compose.yaml -f compose.demo.yaml --profile demo config --quiet
(cd components/ZebraTamer && cargo fmt -- --check && cargo test --locked)
(cd components/PrintHub-ZPL-ll && poetry install && poetry run pytest)
(cd components/printhub-sdk && npm ci && npm test && npm run check:generated && npm run typecheck && npm run build)
(cd components/LabelArchitect && npm ci && npm test && npm run build)
python3 -m unittest discover -s setup/tests -v
(cd components/PrintHub-ZPL-ll && poetry run python -m pip install '../../services/niimbot[test]' && PYTHONPATH=../.. poetry run python -m pytest ../../tools/test_product_tools.py ../../tools/test_niimbot_pipeline.py ../../services/niimbot/tests)
```

The setup suite exists but is not invoked by the current root CI workflow;
run it explicitly. See the [documentation review](DOCUMENTATION_REVIEW.md).

To build the four core images locally, run `docker compose build` after
initializing the four product submodules above. A demo additionally needs
`components/ZPL-II-Printer-Emulator` and the two simulator builds in the
[README demo instructions](../README.md#start-without-a-physical-printer).
Published core images do not require their source submodules to run.
Use a separate Compose project/data set for tests that create jobs or media.

## Adding another printer family

Implement the v2 contract in
`components/PrintHub-ZPL-ll/docs/PRINT_SERVICE_PROTOCOL_V2.md`. A generic
service exposes stable identity, printer catalog, accepted MIME types, durable
idempotent jobs and honest states. Vendor configuration belongs behind optional
capabilities and must return a clear unsupported response elsewhere.

The implemented B1 service in `services/niimbot` accepts the neutral raster
envelope and owns USB/BLE, framing and hardware observations. Run its independent
tests with `python -m pip install './services/niimbot[test]'` then
`python -m pytest services/niimbot/tests`. See [NIIMBOT setup](NIIMBOT.md).
With both PrintHub and the NIIMBOT package installed in the test environment,
`python -m pytest tools/test_niimbot_pipeline.py` checks the PNG-to-device-queue
path and job reconciliation without hardware or a ZPL renderer.
Do not add Niimbot commands or invented Zebra-style configuration to ZebraTamer.

Run the shared schema fixtures against both ZebraTamer and the raster-only test
service. Add lost-response, offline, slow and unknown-outcome cases before
claiming compatibility.
