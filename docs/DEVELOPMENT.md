# Development

Only these submodules are required for the standalone product:

```bash
git submodule update --init components/PrintHub-ZPL-ll components/printhub-sdk components/LabelArchitect components/ZebraTamer
```

The Zebra emulator is optional for the demo profile. Thingdex repositories are
optional API consumers and are not referenced by the product Compose or release
matrix.

Useful checks:

```bash
docker compose config --quiet
docker compose -f compose.yaml -f compose.demo.yaml --profile demo config --quiet
docker run --rm -v "$PWD/components/ZebraTamer:/work" -w /work rust:1-bookworm cargo test --locked
cd components/PrintHub-ZPL-ll && poetry run pytest
cd components/LabelArchitect && npm test && npm run build
python -m pytest tools/test_product_tools.py
```

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
