"""Publish only tested component archives and never overwrite immutable tags."""

from __future__ import annotations

import json
import os
from pathlib import Path
import re
import subprocess
import sys


def run(*args: str) -> str:
    return subprocess.check_output(args, text=True).strip()


def output(key: str, value: str) -> None:
    with Path(os.environ["GITHUB_OUTPUT"]).open("a", encoding="utf-8") as stream:
        stream.write(f"{key}={value}\n")


def assert_absent(reference: str) -> None:
    result = subprocess.run(
        ["docker", "buildx", "imagetools", "inspect", reference],
        capture_output=True,
        text=True,
    )
    if result.returncode == 0:
        raise RuntimeError(f"Refusing to overwrite immutable reference {reference}")
    message = (result.stderr + result.stdout).lower()
    if not any(term in message for term in ("not found", "manifest unknown", "no such manifest")):
        raise RuntimeError(f"Cannot establish whether {reference} exists: {result.stderr}")


def release_context() -> tuple[str, str, str, str | None]:
    image = os.environ["IMAGE"]
    component = os.environ["COMPONENT"]
    sha = os.environ["GITHUB_SHA"]
    ref = os.environ["GITHUB_REF"]
    if component not in {"printer-fleet", "printhub-ipp", "printer-fleet-console"}:
        raise RuntimeError("Unexpected component")
    if not re.fullmatch(r"[a-f0-9]{40}", sha):
        raise RuntimeError("Unexpected source SHA")
    version = ref.removeprefix("refs/tags/") if ref.startswith("refs/tags/") else None
    if ref != "refs/heads/main" and not (version and re.fullmatch(r"v\d+\.\d+\.\d+", version)):
        raise RuntimeError("Publication is restricted to main and exact vMAJOR.MINOR.PATCH tags")
    return image, component, sha, version


def main() -> None:
    image, component, sha, version = release_context()
    build = f"sha-{sha}-r{os.environ['GITHUB_RUN_ID']}-{os.environ['GITHUB_RUN_ATTEMPT']}"
    mode = sys.argv[1]
    if mode == "platform":
        arch = os.environ["ARCH"]
        if arch not in {"amd64", "arm64"}:
            raise RuntimeError("Unexpected platform")
        tag = f"{image}:{build}-{arch}"
        assert_absent(tag)
        run("docker", "load", "-i", "candidate/image.tar")
        run("docker", "tag", f"candidate:{component}", tag)
        run("docker", "push", tag)
        manifest = json.loads(
            run("docker", "buildx", "imagetools", "inspect", tag, "--format", "{{json .Manifest}}")
        )
        Path("metadata").mkdir(exist_ok=True)
        Path(f"metadata/{arch}.json").write_text(
            json.dumps({"arch": arch, "reference": f"{image}@{manifest['digest']}"}),
            encoding="utf-8",
        )
        output("digest", manifest["digest"])
        output("image", image)
        return
    if mode == "merge":
        entries = [json.loads(path.read_text(encoding="utf-8")) for path in Path("metadata").glob("*.json")]
        if len(entries) != 2 or {entry["arch"] for entry in entries} != {"amd64", "arm64"}:
            raise RuntimeError("Both platform images are required")
        immutable = f"{image}:{build}"
        assert_absent(immutable)
        references = [entry["reference"] for entry in entries]
        if any(
            not re.fullmatch(re.escape(image) + r"@sha256:[a-f0-9]{64}", reference)
            for reference in references
        ):
            raise RuntimeError("Invalid platform image reference")
        run("docker", "buildx", "imagetools", "create", "-t", immutable, *references)
        manifest = json.loads(
            run("docker", "buildx", "imagetools", "inspect", immutable, "--format", "{{json .Manifest}}")
        )
        platforms = {
            (item.get("platform", {}).get("os"), item.get("platform", {}).get("architecture"))
            for item in manifest["manifests"]
        }
        if not {("linux", "amd64"), ("linux", "arm64")} <= platforms:
            raise RuntimeError("Published index is missing a supported platform")
        if version:
            run("git", "fetch", "origin", "main")
            subprocess.run(["git", "merge-base", "--is-ancestor", sha, "FETCH_HEAD"], check=True)
            assert_absent(f"{image}:{version}")
        output("digest", manifest["digest"])
        output("image", image)
        Path("release-digest.txt").write_text(f"{component}={image}@{manifest['digest']}\n", encoding="utf-8")
        return
    if mode == "promote":
        digest = os.environ["DIGEST"]
        if not re.fullmatch(r"sha256:[a-f0-9]{64}", digest):
            raise RuntimeError("Invalid image digest")
        target = f"{image}@{digest}"
        if version:
            assert_absent(f"{image}:{version}")
            run("docker", "buildx", "imagetools", "create", "-t", f"{image}:{version}", target)
        elif run("git", "ls-remote", "origin", "refs/heads/main").split()[0] == sha:
            run("docker", "buildx", "imagetools", "create", "-t", f"{image}:latest", target)
        return
    raise RuntimeError("Unknown release operation")


if __name__ == "__main__":
    main()
