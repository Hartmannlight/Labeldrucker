# Documentation review — 2026-10-09

Reviewed root commit `e95393d42832eedb75823124e76f6b8d8bdfe69e` and the
component revisions recorded by its Git submodule entries. This review checks
documentation against source, configuration and workflow definitions. It does
not certify running containers, registry availability or physical hardware.

## Corrected documentation

| Finding | Correction | Evidence |
| --- | --- | --- |
| README demo command assumes simulator images already exist. | Initialize the two needed submodules, build only the simulators, then start with published core images. | [Demo Compose](../compose.demo.yaml): defaults `candidate:virtual-zebra` / `candidate:raster-test`; [README](../README.md#start-without-a-physical-printer). |
| Copied-file installation omits installer sources. | Require `setup/` and `.env.example` alongside Compose and `config/`. Distinguish a socket-free container from the host daemon needed to start it. | [Base Compose](../compose.yaml): setup and config-apply mounts; [installation](INSTALLATION.md). |
| Base ZebraTamer cannot normally reach real LAN printers through its isolated network. | Explain the missing outbound route and provide a local network-overlay recipe. | [Base Compose](../compose.yaml): ZebraTamer has only `backend`, whose `internal` value is true; [Docker network reference](https://docs.docker.com/reference/compose-file/networks/#internal). |
| Network overview says only PrintHub gets renderer egress. | Distinguish base and demo: the emulator also joins egress, and PrintHub can call AI/remote services through it. | [Base](../compose.yaml) and [demo](../compose.demo.yaml) networks. |
| Native USB instructions use `char_device` as a TOML key. | Use `transport = "char_device"` and `device = "/dev/usb/lp0"`. | [Pinned ZebraTamer config](https://github.com/Hartmannlight/ZebraTamer/blob/e538a0887c94d2e883b97d34f4e5db3d17cdb3e2/src/config.rs): `PrinterConfig.device` and transport validation. |
| Installation says a thumbnail renderer error can block template save. | Valid templates save with `preview_warning`; document regeneration and preservation on regeneration failure. | [Pinned PrintHub API](https://github.com/Hartmannlight/PrintHub-ZPL-ll/blob/483a3c2be665dd845bcfbb03d39340fc640b1d92/zplgrid/api.py): create/update and preview-regeneration handlers. |
| AI guide implies the draft always gets a thumbnail, even with previews disabled. | Explain that the one-time image requires `ZPLGRID_ENABLE_LABELARY_TEMPLATES`, while the draft itself remains usable without it. | Same API: `generate_template_with_ai`. |
| Labelary defaults are described without the demo override. | Explain the three forced demo values and the emulator's independent external renderer. | [Demo Compose](../compose.demo.yaml) and [pinned emulator](https://github.com/Hartmannlight/ZPL-II-Printer-Emulator/blob/eb931a2e9bc3e1b12db96f1f927abad9198289a2/zpl_printer_emulator/app.py). |
| Release guide names a workflow absent from this revision. | Name `Container Release`, its `package` job and `printhub-product-candidate` artifact. | [Release workflow](../.github/workflows/container-release.yml). |
| Candidate startup assumes a complete package and loads only image variables. | Describe the missing installer, recovery from `root-revision.txt`, and both `.env` / `.env.images` files. | Same package job and [candidate image env](../deploy/candidate-images.env); [release instructions](RELEASE.md). |
| NIIMBOT guide makes a timeless assertion that published core images lack the feature and builds every service unnecessarily. | Require compatible core images; build the local NIIMBOT service explicitly, and explain submodules for full source builds. | [USB overlay](../compose.niimbot-usb.yaml), root release matrix, [pinned Studio](https://github.com/Hartmannlight/LabelArchitect/blob/9570329b71a4270d6d1e21690a4a920f327b3aa0/src/ui/RasterDesigner.tsx). Registry image contents were not inspected. |
| Development commands drift into the wrong directory and omit dependency/SDK setup. | Use scoped subshells, install dependencies and build the sibling SDK first; add the existing setup suite. | [Root CI](../.github/workflows/ci.yml) and [pinned Studio package](https://github.com/Hartmannlight/LabelArchitect/blob/9570329b71a4270d6d1e21690a4a920f327b3aa0/package.json). |
| Backup scope covers only base volumes/workers. | Include optional/remote device queues and local installation configuration; explain what the archive tool actually collects. | [Backup tool](../tools/backup_product.py), [USB](../compose.usb.yaml), [NIIMBOT](../compose.niimbot-usb.yaml), [demo](../compose.demo.yaml). |
| Ownership and completion are hard to distinguish. | Add a project/boundary table, runtime diagram, queue sequence and rendering-path table to README; distinguish receipt from physical evidence. | [Pinned v2 contract](https://github.com/Hartmannlight/PrintHub-ZPL-ll/blob/483a3c2be665dd845bcfbb03d39340fc640b1d92/docs/PRINT_SERVICE_PROTOCOL_V2.md) and [NIIMBOT implementation](../services/niimbot/niimbot_service/app.py). |
| Historical planning/acceptance can be read as current status. | Mark dated records as historical and link the current runtime overview. Preserve recorded results and revisions. | [Acceptance](acceptance/REFACTORING_2026-09-08.md), [Pi acceptance](acceptance/PI3A_USB_2026-09-08.md), [planning](REFACTORING_ARBEITSPAKETE.md). |

## Implementation gaps

These remain source/configuration issues; the documentation now exposes them
and provides workarounds where possible.

1. **Fresh candidate packages omit a required installer.** The release job
   copies neither `setup/wizard.py` nor `setup/apply.py`. `config-apply` is a
   dependency of Studio and IPP. Fix the package file set, and add a smoke test
   that installs from the assembled `product/` directory rather than from the
   full checkout. The package also omits some linked docs, NIIMBOT files and
   demo build sources/images. [Evidence](../.github/workflows/container-release.yml).
2. **Ethernet setup does not add a route for ZebraTamer.** The wizard accepts
   a LAN address, but the base service remains on an internal-only network.
   The documented overlay is a workaround, not a change to the base file.
   Add/test a supported Ethernet network arrangement.
   [Evidence](../compose.yaml), [wizard](../setup/wizard.py).
3. **Installer tests are absent from root CI.** `setup/tests/test_setup.py`
   exists, but `.github/workflows/ci.yml` neither runs that suite nor performs
   a fresh assembled-package install. Include those checks before describing
   release validation as complete. [Evidence](../.github/workflows/ci.yml).
4. **Moving core `latest` tags are not a reproducible component set.** A
   checkout pins source submodules, while a normal runtime resolves image tags
   independently. Record all four image digests together for a rollout; a
   source review alone cannot establish which code a local image contains.
   [Evidence](../compose.yaml), [release promotion](../pipeline/release_component.py).
5. **Related repositories retain migration-era instructions.** The pinned
   inventory overview still describes Fleet/direct PrintHub-to-printer paths;
   the emulator README shows an obsolete PrintHub-local printer YAML; the
   ZebraTamer README starts with historical PrintAgent terminology. These
   submodule documents were inspected but not rewritten by changing their
   pinned revisions. The root README now documents the stack actually assembled
   here. Future corrections belong in those repositories and need updated
   root pins after validation.

## Source revisions and verification limits

| Component | Reviewed pinned revision |
| --- | --- |
| PrintHub-ZPL-ll | `483a3c2be665dd845bcfbb03d39340fc640b1d92` |
| LabelArchitect / Studio | `9570329b71a4270d6d1e21690a4a920f327b3aa0` |
| ZebraTamer | `e538a0887c94d2e883b97d34f4e5db3d17cdb3e2` |
| printhub-sdk | `7fa3c7e87fb3192f412b35971157768c45234f2d` |
| ZPL-II-Printer-Emulator | `eb931a2e9bc3e1b12db96f1f927abad9198289a2` |
| Thingdex | `24cfb434a2131439e615d922a2e29f407706b8dd` |
| Thingdex-Home-Inventory | `a07c133cbde2317510a6f976bd260fc35ca61f13` |

Checks for this documentation change: parse the base, demo, USB and NIIMBOT
Compose definitions; parse the documented LAN overlay; run the existing setup
suite; check local Markdown links/anchors, shell-example syntax and diff
whitespace. Component code was read at the pinned revisions via the GitHub
connector because direct Git network access was restricted.

Docker daemon access is unavailable in this environment. Container builds,
fresh candidate installation, live LAN/IPP behavior and physical print tests
were not executed. Mermaid diagrams use GitHub's native Markdown renderer;
they were checked structurally, not rendered in a browser here.
