# Releases and release candidates

The `Container Release` workflow runs on pushes to `main`, `v*` tags and manual
dispatch. Its reusable CI must succeed before publication. CI covers component
tests, product-tool/NIIMBOT tests, native container smoke/security gates and the
demo integration path; the existing setup suite is currently omitted. A
successful publication promotes the tested AMD64 and ARM64 images to GHCR:

- `ghcr.io/hartmannlight/zebratamer:latest`
- `ghcr.io/hartmannlight/printhub:latest`
- `ghcr.io/hartmannlight/printhub-studio:latest`
- `ghcr.io/hartmannlight/printhub-ipp:latest`

Every successful publication also retains an immutable `sha-<commit>-r<run>-<attempt>` tag and a
digest artifact. Stable `vMAJOR.MINOR.PATCH` tags are created only from an
exact tag reachable from `main`. The workflow publishes SBOM/provenance
attestations and promotes the already-tested digest rather than rebuilding it.
`latest` moves only for a successful main-branch run whose commit is still the
current remote main head; a version-tag run does not update it. Workflow files
describe the release process, not proof that a particular run or registry pull
succeeded. For repeatable production rollout, pin image digests or immutable tags in
`.env`; `latest` is the convenient default for a fresh installation.

The ZebraTamer repository additionally publishes a native ARM64 systemd bundle
for small Pis. It is preferable to a container on a 500 MB print-server Pi.

## Manually downloadable candidate package

The `package` job of `Container Release` runs after reusable CI succeeds. It
places copied product files under `product/` and the four core components'
tested AMD64/ARM64 image archives under `images/`. Its uploaded artifact is
named `printhub-product-candidate`; there is no separate workflow named
`Release Candidate Package` in this revision.

**Current packaging gap:** the job does not copy `setup/`, although Compose
mounts that directory for both the setup wizard and `config-apply`. Studio and
IPP wait for `config-apply`, so the package is not a complete fresh-install
bundle as assembled. It also omits the NIIMBOT overlay/service sources and
several documents linked by the copied README. The demo file is included, but
simulator images and sources are not. See the
[review](DOCUMENTATION_REVIEW.md#implementation-gaps) for exact source references.

On the target host, unpack the downloaded artifact and verify all image
archives from its root directory. Then select the four archives for the target
architecture and load them before starting the product:

```bash
sha256sum -c product/candidate-images.sha256
docker load -i images/zebratamer-candidate-amd64/image.tar
docker load -i images/printhub-candidate-amd64/image.tar
docker load -i images/printhub-studio-candidate-amd64/image.tar
docker load -i images/printhub-ipp-candidate-amd64/image.tar
```

Use the corresponding `arm64` directories on a 64-bit Pi.

Until packaging is corrected, obtain the missing installer from the exact root
revision recorded in the artifact. From the artifact root:

```bash
git clone --no-checkout https://github.com/Hartmannlight/Labeldrucker.git release-source
git -C release-source checkout --detach "$(cat product/root-revision.txt)"
cp -R release-source/setup product/setup
cd product
docker compose --env-file .env.images --profile setup run --rm --no-deps setup
docker compose --env-file .env --env-file .env.images config --quiet
docker compose --env-file .env --env-file .env.images up -d --no-build
```

The wizard writes `.env` and the installation manifest. Supply **both** env
files afterwards: an explicit `--env-file .env.images` alone replaces automatic
loading of `.env`, and the image-tag file contains no installer settings.
The later `.env.images` overrides only the four image tags. This repair needs
source access; the currently assembled artifact alone is not an offline
fresh-install solution. Keep the repaired installer with the installation.

The candidate archives remain local to this downloadable package. Successful
main-branch releases are published to GHCR by the same workflow. Build demo
simulators separately from matching source if a demo is needed.

The USB overlay is included in the package. Copy
`config/print-agent.toml.example` to `config/zebratamer.usb.toml`, set the exact
USB identity and stable device path as described in `INSTALLATION.md`, then
start it with the USB profile in addition to the base file:

```bash
docker compose --env-file .env --env-file .env.images -f compose.yaml -f compose.usb.yaml --profile usb up -d --no-build
```

For an Ethernet Zebra, include the outbound-network overlay from
[installation](INSTALLATION.md#ethernet-zebra-and-outbound-networking) as well.
See the dated acceptance records for coverage: the simulator report is not a
hardware certification, and the Pi 3A report accepts one specific native
USB-Zebra topology. Neither certifies all current images, LAN/IPPs or NIIMBOT.
