from __future__ import annotations

from pathlib import Path
import json

import pytest
import yaml

from scripts.release_component import release_context
from scripts.build_compatibility_manifest import (
    SIGNER_WORKFLOWS,
    build_manifest,
    verify_attestations,
    verify_images,
    write_manifest,
)
from scripts.security_gate import findings
from scripts.validate_release_env import (
    IMAGE_KEYS,
    SECRET_FILE_KEYS,
    SECRET_KEYS,
    validate,
    validate_fleet_credentials,
    validate_manifest,
)


ROOT = Path(__file__).resolve().parents[1]


def test_workflows_parse_and_candidate_matrix_covers_native_platforms() -> None:
    workflows = {
        path.name: yaml.safe_load(path.read_text(encoding="utf-8"))
        for path in (ROOT / ".github" / "workflows").glob("*.yml")
    }
    assert set(workflows) == {
        "ci.yml",
        "compatibility-release.yml",
        "container-gate.yml",
        "container-release.yml",
    }
    candidates = workflows["container-gate.yml"]["jobs"]["candidate"]["strategy"]["matrix"]["include"]
    combinations = {(item["component"], item["arch"], item["runner"]) for item in candidates}
    assert combinations == {
        ("printer-fleet", "amd64", "ubuntu-24.04"),
        ("printer-fleet", "arm64", "ubuntu-24.04-arm"),
        ("printhub-ipp", "amd64", "ubuntu-24.04"),
        ("printhub-ipp", "arm64", "ubuntu-24.04-arm"),
    }


def test_release_context_rejects_non_release_refs(monkeypatch) -> None:
    monkeypatch.setenv("IMAGE", "ghcr.io/example/printer-fleet")
    monkeypatch.setenv("COMPONENT", "printer-fleet")
    monkeypatch.setenv("GITHUB_SHA", "a" * 40)
    monkeypatch.setenv("GITHUB_REF", "refs/heads/feature")
    with pytest.raises(RuntimeError, match="restricted"):
        release_context()


def test_release_environment_requires_real_digests_and_secrets() -> None:
    valid = {key: f"registry.example/{key.lower()}@sha256:{'1' * 64}" for key in IMAGE_KEYS}
    valid.update({key: "injected-secret" for key in SECRET_KEYS})
    valid.update({key: f"C:/secrets/{key.lower()}" for key in SECRET_FILE_KEYS})
    assert validate(valid) == []
    valid["PRINTHUB_IMAGE"] = "registry.example/printhub:latest"
    assert any("PRINTHUB_IMAGE" in error for error in validate(valid))


def test_release_environment_matches_narrow_printhub_fleet_credential(tmp_path) -> None:
    credentials = tmp_path / "fleet-credentials.json"
    token_file = tmp_path / "printhub-token"
    token = "a-production-fleet-token"
    credentials.write_text(
        json.dumps(
            {
                "credentials": [
                    {
                        "id": "printhub-berlin",
                        "token": token,
                        "roles": ["observer", "submitter"],
                        "sites": ["berlin"],
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    token_file.write_text(token + "\n", encoding="utf-8")
    values = {
        "PRINTER_FLEET_CREDENTIALS_SOURCE": credentials.name,
        "PRINTHUB_FLEET_TOKEN_SOURCE": token_file.name,
    }

    assert validate_fleet_credentials(values, base_directory=tmp_path) == []

    document = json.loads(credentials.read_text(encoding="utf-8"))
    document["credentials"][0]["roles"].append("admin")
    credentials.write_text(json.dumps(document), encoding="utf-8")
    assert validate_fleet_credentials(values, base_directory=tmp_path) == [
        "PrintHub Fleet credential must have observer and submitter but not admin"
    ]


def test_security_policy_blocks_fixable_high_findings() -> None:
    report = {
        "Results": [
            {
                "Vulnerabilities": [
                    {
                        "VulnerabilityID": "CVE-TEST",
                        "PkgName": "fixture",
                        "Severity": "HIGH",
                        "FixedVersion": "2",
                    }
                ]
            }
        ]
    }
    assert findings(report)[0] == [("CVE-TEST", "fixture")]


def compatibility_values() -> dict[str, str]:
    values = {
        key: f"ghcr.io/hartmannlight/{key.lower()}@sha256:{format(index, 'x') * 64}"
        for index, key in enumerate(IMAGE_KEYS, 1)
    }
    values.update(
        {
            "COMPATIBILITY_RELEASE": "v1.2.3",
            "PLATFORM_SOURCE_REVISION": "a" * 40,
            "PRINTHUB_SOURCE_REVISION": "b" * 40,
            "STUDIO_SOURCE_REVISION": "c" * 40,
            "THINGDEX_SOURCE_REVISION": "d" * 40,
        }
    )
    return values


def test_compatibility_manifest_binds_images_sources_and_environment(tmp_path) -> None:
    values = compatibility_values()
    manifest = build_manifest(values)
    output = tmp_path / "compatibility.json"
    write_manifest(manifest, output)

    assert manifest["schemaVersion"] == 1
    assert manifest["components"]["printerFleet"]["source"]["revision"] == "a" * 40
    assert validate_manifest(values, manifest) == []
    assert len(output.with_suffix(".json.sha256").read_text().split()[0]) == 64
    assert json.loads(output.read_text(encoding="utf-8")) == manifest

    changed = dict(values)
    changed["PRINTHUB_IMAGE"] = f"ghcr.io/example/other@sha256:{'f' * 64}"
    assert validate_manifest(changed, manifest) == [
        "PRINTHUB_IMAGE does not match compatibility manifest component printHub"
    ]


def test_manifest_rejects_mutable_images_and_inexact_source_revisions() -> None:
    values = compatibility_values()
    values["PRINTHUB_IMAGE"] = "ghcr.io/hartmannlight/printhub:latest"
    with pytest.raises(ValueError, match="PRINTHUB_IMAGE"):
        build_manifest(values)

    values = compatibility_values()
    values["THINGDEX_SOURCE_REVISION"] = "main"
    with pytest.raises(ValueError, match="THINGDEX_SOURCE_REVISION"):
        build_manifest(values)


def test_manifest_verifies_multiarch_digests(monkeypatch) -> None:
    manifest = build_manifest(compatibility_values())

    def inspect(command, text):
        reference = command[4]
        return json.dumps(
            {
                "digest": reference.rsplit("@", 1)[1],
                "manifests": [
                    {"platform": {"os": "linux", "architecture": "amd64"}},
                    {"platform": {"os": "linux", "architecture": "arm64"}},
                ],
            }
        )

    monkeypatch.setattr("scripts.build_compatibility_manifest.subprocess.check_output", inspect)
    verify_images(manifest)


def test_manifest_verifies_each_component_attestation(monkeypatch) -> None:
    calls = []
    monkeypatch.setattr(
        "scripts.build_compatibility_manifest.subprocess.run",
        lambda command, check: calls.append((command, check)),
    )

    verify_attestations(build_manifest(compatibility_values()))

    assert len(calls) == len(SIGNER_WORKFLOWS)
    assert all(call[0][:3] == ["gh", "attestation", "verify"] for call in calls)
    assert all("--source-digest" in call[0] and call[1] is True for call in calls)
