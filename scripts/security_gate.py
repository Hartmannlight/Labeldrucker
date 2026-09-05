"""Fail closed on fixable High/Critical container findings."""

from __future__ import annotations

import json
from pathlib import Path
import sys


def findings(report: dict) -> tuple[list[tuple], list[tuple]]:
    if "Results" not in report:
        raise ValueError("Missing Trivy Results")
    blocked: list[tuple] = []
    unpatched: list[tuple] = []
    for result in report["Results"] or []:
        for finding in result.get("Vulnerabilities", []) or []:
            if finding.get("Severity") in {"HIGH", "CRITICAL"}:
                item = (finding.get("VulnerabilityID"), finding.get("PkgName"))
                (blocked if finding.get("FixedVersion") else unpatched).append(item)
        for kind in ("Secrets", "Misconfigurations"):
            for finding in result.get(kind, []) or []:
                if finding.get("Severity") in {"HIGH", "CRITICAL"} and finding.get("Status", "FAIL") != "PASS":
                    blocked.append((finding.get("ID", finding.get("RuleID", kind)), result.get("Target")))
    return blocked, unpatched


def self_test() -> None:
    report = {
        "Results": [
            {
                "Vulnerabilities": [
                    {"VulnerabilityID": "TEST", "PkgName": "fixture", "Severity": "HIGH", "FixedVersion": "2"}
                ]
            }
        ]
    }
    assert findings(report)[0]
    report["Results"][0]["Vulnerabilities"][0]["FixedVersion"] = ""
    assert findings(report)[1] and not findings(report)[0]


def main() -> int:
    if sys.argv[1:] == ["--self-test"]:
        self_test()
        return 0
    if not sys.argv[1:]:
        raise ValueError("At least one scan report is required")
    blocked: list[tuple] = []
    for name in sys.argv[1:]:
        report = json.loads(Path(name).read_text(encoding="utf-8"))
        failed, _unpatched = findings(report)
        for result in report["Results"] or []:
            for secret in result.get("Secrets", []) or []:
                secret.pop("Match", None)
                secret.pop("Code", None)
        Path("artifacts").mkdir(exist_ok=True)
        Path("artifacts", Path(name).name).write_text(json.dumps(report, indent=2), encoding="utf-8")
        blocked.extend(failed)
    return 1 if blocked else 0


if __name__ == "__main__":
    raise SystemExit(main())
