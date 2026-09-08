# Releases and release candidates

A push to `main` runs the full tests and security gates, then publishes the
exact tested AMD64 and ARM64 images to GHCR:

- `ghcr.io/hartmannlight/zebratamer:latest`
- `ghcr.io/hartmannlight/printhub:latest`
- `ghcr.io/hartmannlight/printhub-studio:latest`
- `ghcr.io/hartmannlight/printhub-ipp:latest`

Every run also retains an immutable `sha-<commit>-r<run>-<attempt>` tag and a
digest artifact. Stable `vMAJOR.MINOR.PATCH` tags are created only from an
exact tag reachable from `main`. The workflow publishes SBOM/provenance
attestations and promotes the already-tested digest rather than rebuilding it.
For repeatable production rollout, pin image digests or immutable tags in
`.env`; `latest` is the convenient default for a fresh installation.

The ZebraTamer repository additionally publishes a native ARM64 systemd bundle
for small Pis. It is preferable to a container on a 500 MB print-server Pi.

## Manually downloadable candidate package

The manual `Release Candidate Package` workflow first runs the complete CI and
native AMD64/ARM64 container matrix. It then places the product files under
`product/` and the exact tested image archives under `images/`.

On the target host, unpack the downloaded artifact and verify all image
archives from its root directory. Then select the four archives for the target
architecture and load them before starting the product:

```bash
sha256sum -c product/candidate-images.sha256
docker load -i images/zebratamer-candidate-amd64/image.tar
docker load -i images/printhub-candidate-amd64/image.tar
docker load -i images/printhub-studio-candidate-amd64/image.tar
docker load -i images/printhub-ipp-candidate-amd64/image.tar
cd product
docker compose --env-file .env.images up -d --no-build
```

Use the corresponding `arm64` directories on a 64-bit Pi.
The candidate archives remain local to this downloadable package. Normal
main-branch releases are published to GHCR by the automatic container workflow.

The USB overlay is included in the package. Copy
`config/print-agent.toml.example` to `config/zebratamer.usb.toml`, set the exact
USB identity and stable device path as described in `INSTALLATION.md`, then
start it with the USB profile in addition to the base file:

```bash
docker compose --env-file .env.images -f compose.yaml -f compose.usb.yaml --profile usb up -d --no-build
```

A release is not a hardware-certified production release until the open
physical checks in `acceptance/REFACTORING_2026-09-08.md` have been completed.
