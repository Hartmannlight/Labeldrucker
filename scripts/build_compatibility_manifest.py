from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
from typing import Any, Mapping

try:
    from .validate_release_env import IMMUTABLE_IMAGE
    from .validate_hardware_acceptance import acceptance_reference, load_and_validate
except ImportError:  # Direct script execution adds scripts/, not the repository root.
    from validate_release_env import IMMUTABLE_IMAGE
    from validate_hardware_acceptance import acceptance_reference, load_and_validate


SCHEMA_VERSION = 2
COMPONENTS = {
    "printerFleet": (
        "PRINTER_FLEET_IMAGE",
        "https://github.com/Hartmannlight/Labeldrucker",
        "PLATFORM_SOURCE_REVISION",
    ),
    "fleetConsole": (
        "PRINTER_FLEET_CONSOLE_IMAGE",
        "https://github.com/Hartmannlight/Labeldrucker",
        "PLATFORM_SOURCE_REVISION",
    ),
    "printHub": (
        "PRINTHUB_IMAGE",
        "https://github.com/Hartmannlight/PrintHub-ZPL-ll",
        "PRINTHUB_SOURCE_REVISION",
    ),
    "ippGateway": (
        "PRINTHUB_IPP_IMAGE",
        "https://github.com/Hartmannlight/Labeldrucker",
        "PLATFORM_SOURCE_REVISION",
    ),
    "studio": (
        "PRINTHUB_STUDIO_IMAGE",
        "https://github.com/Hartmannlight/LabelArchitect",
        "STUDIO_SOURCE_REVISION",
    ),
    "thingdex": (
        "THINGDEX_IMAGE",
        "https://github.com/Hartmannlight/Thingdex",
        "THINGDEX_SOURCE_REVISION",
    ),
}
CONTRACTS = {
    "printHubApi": "v1",
    "printerFleetApi": "v1",
    "printAgentApi": "v1",
    "thingdexApi": "v1",
}
SIGNER_WORKFLOWS = {
    "printerFleet": "Hartmannlight/Labeldrucker/.github/workflows/container-release.yml",
    "fleetConsole": "Hartmannlight/Labeldrucker/.github/workflows/container-release.yml",
    "printHub": "Hartmannlight/PrintHub-ZPL-ll/.github/workflows/container-release.yml",
    "ippGateway": "Hartmannlight/Labeldrucker/.github/workflows/container-release.yml",
    "studio": "Hartmannlight/LabelArchitect/.github/workflows/container-release.yml",
    "thingdex": "Hartmannlight/Thingdex/.github/workflows/publish-image.yml",
}
_RELEASE = re.compile(r"v\d+\.\d+\.\d+")
_REVISION = re.compile(r"[0-9a-f]{40}")


def build_manifest(
    values: Mapping[str, str],
    hardware_acceptance: Mapping[str, Any],
) -> dict[str, Any]:
    release = values.get("COMPATIBILITY_RELEASE", "")
    if not _RELEASE.fullmatch(release):
        raise ValueError("COMPATIBILITY_RELEASE must be an exact vMAJOR.MINOR.PATCH")

    components: dict[str, Any] = {}
    for name, (image_key, repository, revision_key) in COMPONENTS.items():
        image = values.get(image_key, "")
        match = IMMUTABLE_IMAGE.fullmatch(image)
        if not match or match.group(1) == "0" * 64:
            raise ValueError(f"{image_key} must contain a real immutable image digest")
        revision = values.get(revision_key, "")
        if not _REVISION.fullmatch(revision):
            raise ValueError(f"{revision_key} must be a lowercase 40-character Git revision")
        components[name] = {
            "image": image,
            "source": {"repository": repository, "revision": revision},
        }

    postgres = values.get("POSTGRES_IMAGE", "")
    match = IMMUTABLE_IMAGE.fullmatch(postgres)
    if not match or match.group(1) == "0" * 64:
        raise ValueError("POSTGRES_IMAGE must contain a real immutable image digest")
    components["postgres"] = {"image": postgres, "source": {"kind": "upstream"}}
    return {
        "schemaVersion": SCHEMA_VERSION,
        "release": release,
        "contracts": CONTRACTS,
        "components": components,
        "hardwareAcceptance": dict(hardware_acceptance),
    }


def verify_images(manifest: Mapping[str, Any]) -> None:
    required = {("linux", "amd64"), ("linux", "arm64")}
    for name, component in manifest["components"].items():
        reference = component["image"]
        expected = reference.rsplit("@", 1)[1]
        raw = subprocess.check_output(
            [
                "docker",
                "buildx",
                "imagetools",
                "inspect",
                reference,
                "--format",
                "{{json .Manifest}}",
            ],
            text=True,
        )
        image_manifest = json.loads(raw)
        if image_manifest.get("digest") != expected:
            raise RuntimeError(f"Registry digest mismatch for {name}")
        platforms = {
            (entry.get("platform", {}).get("os"), entry.get("platform", {}).get("architecture"))
            for entry in image_manifest.get("manifests", [])
        }
        if not required <= platforms:
            raise RuntimeError(f"{name} image is not available for linux/amd64 and linux/arm64")


def verify_attestations(manifest: Mapping[str, Any]) -> None:
    for name, signer_workflow in SIGNER_WORKFLOWS.items():
        component = manifest["components"][name]
        repository = component["source"]["repository"].removeprefix("https://github.com/")
        subprocess.run(
            [
                "gh",
                "attestation",
                "verify",
                f"oci://{component['image']}",
                "--repo",
                repository,
                "--source-digest",
                component["source"]["revision"],
                "--signer-workflow",
                signer_workflow,
                "--deny-self-hosted-runners",
            ],
            check=True,
        )


def write_manifest(manifest: Mapping[str, Any], output_path: Path) -> None:
    encoded = (json.dumps(manifest, indent=2, sort_keys=True) + "\n").encode("utf-8")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_bytes(encoded)
    checksum = hashlib.sha256(encoded).hexdigest()
    output_path.with_suffix(output_path.suffix + ".sha256").write_text(
        f"{checksum}  {output_path.name}\n",
        encoding="utf-8",
    )


def main() -> int:
    parser = argparse.ArgumentParser(description="Build a Print Platform compatibility manifest")
    parser.add_argument("--output", type=Path, default=Path("release/compatibility.json"))
    parser.add_argument("--hardware-acceptance", type=Path, required=True)
    parser.add_argument("--verify-images", action="store_true")
    parser.add_argument("--verify-attestations", action="store_true")
    args = parser.parse_args()
    acceptance_path = args.hardware_acceptance.resolve()
    repository_root = Path.cwd().resolve()
    if not acceptance_path.is_relative_to(repository_root):
        raise ValueError("Hardware acceptance must be a file in the checked-out repository")
    acceptance, acceptance_bytes = load_and_validate(
        acceptance_path,
        expected_release=os.environ.get("COMPATIBILITY_RELEASE", ""),
        expected_platform_revision=os.environ.get("PLATFORM_SOURCE_REVISION", ""),
    )
    manifest = build_manifest(
        os.environ,
        acceptance_reference(acceptance, acceptance_bytes),
    )
    if args.verify_images:
        verify_images(manifest)
    if args.verify_attestations:
        verify_attestations(manifest)
    write_manifest(manifest, args.output)
    evidence_output = args.output.parent / manifest["hardwareAcceptance"]["file"]
    evidence_output.write_bytes(acceptance_bytes)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
