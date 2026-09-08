#!/usr/bin/env python3
"""Create or safely restore a portable backup of PrintHub product data."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path, PurePosixPath
import tarfile
import tempfile
from typing import Iterable


FORMAT = "printhub-backup-v1"


def digest(path: Path) -> str:
    value = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            value.update(chunk)
    return value.hexdigest()


def parse_source(value: str) -> tuple[str, Path]:
    if "=" not in value:
        raise argparse.ArgumentTypeError("sources use NAME=PATH")
    name, raw_path = value.split("=", 1)
    if not name or not name.replace("-", "").replace("_", "").isalnum():
        raise argparse.ArgumentTypeError("source NAME must be alphanumeric with - or _")
    path = Path(raw_path).resolve()
    if not path.is_dir():
        raise argparse.ArgumentTypeError(f"source is not a directory: {path}")
    return name, path


def iter_files(sources: Iterable[tuple[str, Path]]):
    for name, root in sources:
        for path in sorted(item for item in root.rglob("*") if item.is_file()):
            yield name, root, path


def create_backup(output: Path, sources: list[tuple[str, Path]]) -> None:
    output = output.resolve()
    if output.exists():
        raise ValueError(f"refusing to overwrite existing backup: {output}")
    names = [name for name, _ in sources]
    if len(names) != len(set(names)):
        raise ValueError("source names must be unique")
    output.parent.mkdir(parents=True, exist_ok=True)
    manifest = {"format": FORMAT, "files": []}
    with tempfile.NamedTemporaryFile(dir=output.parent, delete=False) as temporary:
        temporary_path = Path(temporary.name)
    try:
        with tarfile.open(temporary_path, "w:gz") as archive:
            for name, root, path in iter_files(sources):
                relative = path.relative_to(root).as_posix()
                stored = f"data/{name}/{relative}"
                archive.add(path, arcname=stored, recursive=False)
                manifest["files"].append(
                    {"path": stored, "bytes": path.stat().st_size, "sha256": digest(path)}
                )
            encoded = (json.dumps(manifest, indent=2, sort_keys=True) + "\n").encode()
            info = tarfile.TarInfo("manifest.json")
            info.size = len(encoded)
            info.mode = 0o600
            import io

            archive.addfile(info, io.BytesIO(encoded))
        temporary_path.replace(output)
    finally:
        temporary_path.unlink(missing_ok=True)


def _safe_members(archive: tarfile.TarFile):
    for member in archive.getmembers():
        path = PurePosixPath(member.name)
        if path.is_absolute() or ".." in path.parts or member.issym() or member.islnk():
            raise ValueError(f"unsafe archive member: {member.name}")
        yield member


def restore_backup(archive_path: Path, output: Path) -> None:
    output = output.resolve()
    if output.exists() and any(output.iterdir()):
        raise ValueError(f"refusing to restore into non-empty directory: {output}")
    output.mkdir(parents=True, exist_ok=True)
    with tarfile.open(archive_path.resolve(), "r:gz") as archive:
        members = list(_safe_members(archive))
        manifest_file = archive.extractfile("manifest.json")
        if manifest_file is None:
            raise ValueError("backup has no manifest")
        manifest = json.load(manifest_file)
        if manifest.get("format") != FORMAT:
            raise ValueError("unsupported backup format")
        archive.extractall(output, members=members, filter="data")
    for item in manifest.get("files", []):
        restored = output / PurePosixPath(item["path"])
        if not restored.is_file() or restored.stat().st_size != item["bytes"]:
            raise ValueError(f"restored file is missing or truncated: {item['path']}")
        if digest(restored) != item["sha256"]:
            raise ValueError(f"restored checksum mismatch: {item['path']}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    create = subparsers.add_parser("create")
    create.add_argument("output", type=Path)
    create.add_argument("--source", type=parse_source, action="append", required=True)
    restore = subparsers.add_parser("restore")
    restore.add_argument("archive", type=Path)
    restore.add_argument("output", type=Path)
    args = parser.parse_args()
    if args.command == "create":
        create_backup(args.output, args.source)
        print(f"Created {args.output}")
    else:
        restore_backup(args.archive, args.output)
        print(f"Restored into {args.output}")


if __name__ == "__main__":
    main()
