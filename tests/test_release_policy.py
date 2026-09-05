from __future__ import annotations

from pathlib import Path
import json

import pytest
import yaml

from scripts.release_component import release_context
from scripts.build_compatibility_manifest import (
    SIGNER_WORKFLOWS,
    build_manifest,
    main as build_manifest_main,
    verify_attestations,
    verify_images,
    write_manifest,
)
from scripts.validate_hardware_acceptance import (
    acceptance_reference,
    validation_errors as hardware_acceptance_errors,
)
from scripts.security_gate import findings, main as security_gate_main
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
        "platform-integration.yml",
    }
    candidates = workflows["container-gate.yml"]["jobs"]["candidate"]["strategy"]["matrix"]["include"]
    combinations = {(item["component"], item["arch"], item["runner"]) for item in candidates}
    assert combinations == {
        ("printer-fleet", "amd64", "ubuntu-24.04"),
        ("printer-fleet", "arm64", "ubuntu-24.04-arm"),
        ("printhub-ipp", "amd64", "ubuntu-24.04"),
        ("printhub-ipp", "arm64", "ubuntu-24.04-arm"),
        ("printer-fleet-console", "amd64", "ubuntu-24.04"),
        ("printer-fleet-console", "arm64", "ubuntu-24.04-arm"),
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


def test_security_gate_reports_blocked_identifier_without_secret_match(
    tmp_path, monkeypatch, capsys
) -> None:
    report = tmp_path / "scan.json"
    report.write_text(
        json.dumps(
            {
                "Results": [
                    {
                        "Target": "candidate",
                        "Secrets": [
                            {
                                "ID": "private-key",
                                "Severity": "CRITICAL",
                                "Match": "sensitive material",
                                "Code": {"Lines": []},
                            }
                        ],
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr("sys.argv", ["security_gate.py", str(report)])

    assert security_gate_main() == 1
    assert "private-key (candidate)" in capsys.readouterr().err
    sanitized = json.loads((tmp_path / "artifacts" / "scan.json").read_text())
    assert "Match" not in sanitized["Results"][0]["Secrets"][0]
    assert "Code" not in sanitized["Results"][0]["Secrets"][0]


def test_runtime_images_remove_python_build_tooling() -> None:
    for path in (ROOT / "printer-fleet" / "Dockerfile", ROOT / "ipp-gateway" / "Dockerfile"):
        document = path.read_text(encoding="utf-8")
        assert "python -m pip uninstall -y pip setuptools wheel jaraco.context" in document


def test_fleet_console_keeps_operator_credentials_out_of_images_and_storage() -> None:
    dockerfile = (ROOT / "fleet-console" / "Dockerfile").read_text(encoding="utf-8")
    client = (ROOT / "fleet-console" / "api.js").read_text(encoding="utf-8")
    smoke = (ROOT / "scripts" / "container_smoke.py").read_text(encoding="utf-8")
    production = yaml.safe_load(
        (ROOT / "deploy" / "compose.standalone.yaml").read_text(encoding="utf-8")
    )["services"]["fleet-console"]

    assert "USER nginx" in dockerfile
    assert "TOKEN" not in dockerfile.upper()
    assert "localStorage" not in client
    assert "sessionStorage" not in client
    assert '"--read-only"' in smoke
    assert production["read_only"] is True
    assert production["cap_drop"] == ["ALL"]
    assert "/etc/nginx/http.d" in production["tmpfs"]


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


def hardware_acceptance() -> dict[str, object]:
    return {
        "schemaVersion": 1,
        "release": "v1.2.3",
        "platformRevision": "a" * 40,
        "testedAt": "2026-09-05T10:00:00Z",
        "reviewedAt": "2026-09-05T11:00:00Z",
        "tester": {"name": "Test Operator", "site": "isolated-lab"},
        "reviewer": {"name": "Independent Reviewer"},
        "scenarios": {
            "public_catalog_boundary": "pass",
            "maintenance_serialization": "pass",
            "queue_isolation": "pass",
            "disconnect_ambiguity": "pass",
            "media_change": "pass",
            "cups_browser": "pass",
            "color_dither": "pass",
            "a4_hold_fit": "pass",
        },
        "transports": {
            "raw_tcp": {
                "advertised": True,
                "outcome": "pass",
                "printer": {
                    "manufacturer": "Zebra",
                    "model": "ZT411",
                    "firmware": "V1",
                    "serialSuffix": "1234",
                },
                "media": {
                    "widthMm": 50,
                    "heightMm": 50,
                    "tracking": "gap",
                    "color": "white",
                    "technology": "thermal-transfer",
                    "dpi": 203,
                },
                "connectionSummary": "isolated Ethernet port 9100",
                "reportedState": "transport_accepted",
                "auditCorrelationIds": ["correlation-1"],
                "printHubJobIds": ["job-1"],
                "fleetDeliveryIds": ["delivery-1"],
                "evidence": ["https://example.invalid/evidence/1"],
            },
            "serial_over_tcp": {
                "advertised": False,
                "outcome": "not_tested",
                "reason": "not part of this release",
            },
            "print_agent": {
                "advertised": False,
                "outcome": "not_tested",
                "reason": "not part of this release",
            },
        },
    }


def hardware_reference(document: dict[str, object] | None = None) -> dict[str, object]:
    value = document or hardware_acceptance()
    encoded = (json.dumps(value, sort_keys=True) + "\n").encode()
    return acceptance_reference(value, encoded)


def test_compatibility_manifest_binds_images_sources_and_environment(tmp_path) -> None:
    values = compatibility_values()
    manifest = build_manifest(values, hardware_reference())
    output = tmp_path / "compatibility.json"
    write_manifest(manifest, output)

    assert manifest["schemaVersion"] == 2
    assert manifest["components"]["printerFleet"]["source"]["revision"] == "a" * 40
    assert manifest["hardwareAcceptance"]["supportedTransports"] == ["raw_tcp"]
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
        build_manifest(values, hardware_reference())

    values = compatibility_values()
    values["THINGDEX_SOURCE_REVISION"] = "main"
    with pytest.raises(ValueError, match="THINGDEX_SOURCE_REVISION"):
        build_manifest(values, hardware_reference())


def test_manifest_verifies_multiarch_digests(monkeypatch) -> None:
    manifest = build_manifest(compatibility_values(), hardware_reference())

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

    verify_attestations(build_manifest(compatibility_values(), hardware_reference()))

    assert len(calls) == len(SIGNER_WORKFLOWS)
    assert all(call[0][:3] == ["gh", "attestation", "verify"] for call in calls)
    assert all("--source-digest" in call[0] and call[1] is True for call in calls)


def test_hardware_acceptance_requires_independent_complete_real_device_evidence() -> None:
    valid = hardware_acceptance()
    assert hardware_acceptance_errors(
        valid,
        expected_release="v1.2.3",
        expected_platform_revision="a" * 40,
    ) == []

    invalid = json.loads(json.dumps(valid))
    invalid["reviewer"]["name"] = invalid["tester"]["name"]
    invalid["scenarios"]["a4_hold_fit"] = "not_tested"
    invalid["transports"]["raw_tcp"]["outcome"] = "not_tested"
    invalid["transports"]["raw_tcp"]["api_token"] = "must-never-be-recorded"
    errors = hardware_acceptance_errors(
        invalid,
        expected_release="v1.2.3",
        expected_platform_revision="a" * 40,
    )

    assert any("different people" in error for error in errors)
    assert any("a4_hold_fit must pass" in error for error in errors)
    assert any("advertised transport raw_tcp must pass" in error for error in errors)
    assert any("not permitted in sanitized evidence" in error for error in errors)


def test_compatibility_manifest_cli_embeds_and_copies_validated_hardware_evidence(
    tmp_path, monkeypatch
) -> None:
    values = compatibility_values()
    for key, value in values.items():
        monkeypatch.setenv(key, value)
    acceptance_path = tmp_path / "acceptance.json"
    encoded = (json.dumps(hardware_acceptance(), indent=2) + "\n").encode()
    acceptance_path.write_bytes(encoded)
    output = tmp_path / "release" / "compatibility.json"
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(
        "sys.argv",
        [
            "build_compatibility_manifest.py",
            "--hardware-acceptance",
            acceptance_path.name,
            "--output",
            str(output),
        ],
    )

    assert build_manifest_main() == 0
    manifest = json.loads(output.read_text(encoding="utf-8"))
    copied = output.parent / "hardware-acceptance.json"
    assert copied.read_bytes() == encoded
    assert manifest["hardwareAcceptance"]["sha256"] == acceptance_reference(
        hardware_acceptance(), encoded
    )["sha256"]


def test_checked_in_hardware_acceptance_example_is_deliberately_not_releasable() -> None:
    example = json.loads(
        (ROOT / "docs" / "acceptance" / "hardware-acceptance.example.json").read_text(
            encoding="utf-8"
        )
    )

    errors = hardware_acceptance_errors(example)

    assert any("must pass before stable release" in error for error in errors)
    assert any("advertised transport raw_tcp must pass" in error for error in errors)
