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

A Niimbot service should accept the neutral raster envelope and own Bluetooth,
packet framing, pairing and hardware observations. PrintHub will render a
filled template through the configured renderer before dispatch. Do not add
Niimbot commands, Bluetooth or invented Zebra-style configuration to ZebraTamer.

Run the shared schema fixtures against both ZebraTamer and the raster-only test
service. Add lost-response, offline, slow and unknown-outcome cases before
claiming compatibility.
