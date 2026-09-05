from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from scripts.release_component import release_context
from scripts.security_gate import findings
from scripts.validate_release_env import IMAGE_KEYS, SECRET_KEYS, validate


ROOT = Path(__file__).resolve().parents[1]


def test_workflows_parse_and_candidate_matrix_covers_native_platforms() -> None:
    workflows = {
        path.name: yaml.safe_load(path.read_text(encoding="utf-8"))
        for path in (ROOT / ".github" / "workflows").glob("*.yml")
    }
    assert set(workflows) == {"ci.yml", "container-gate.yml", "container-release.yml"}
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
    assert validate(valid) == []
    valid["PRINTHUB_IMAGE"] = "registry.example/printhub:latest"
    assert any("PRINTHUB_IMAGE" in error for error in validate(valid))


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
