"""Verify a CI archive against the checked-out commit and stage its Next build."""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import tarfile
import tempfile
from pathlib import Path, PurePosixPath

from src.api.build_identity import (
    NEXT_ROUTE_CACHE_DIRECTORY,
    resolve_build_identity,
    verify_release_manifest,
)


def _digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _text_digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes().replace(b"\r\n", b"\n")).hexdigest()


def _extract_checked(archive: Path, destination: Path) -> None:
    """Extract only the four expected trees; never follow archive links."""
    allowed_files = {
        "release-manifest.json",
        "requirements.lock.txt",
        "frontend/package-lock.json",
        "backend-wheelhouse.tar",
    }
    with tarfile.open(archive, "r:") as bundle:
        members = bundle.getmembers()
        if len(members) > 50000:
            raise ValueError("release archive contains too many entries")
        for member in members:
            name = PurePosixPath(member.name)
            if (
                name.is_absolute()
                or ".." in name.parts
                or not name.parts
                or (
                    member.name not in allowed_files
                    and name.parts[:2] != ("frontend", ".next")
                    and member.name != "frontend"
                )
            ):
                raise ValueError(f"unexpected release archive path: {member.name}")
            if not (member.isdir() or member.isfile()):
                raise ValueError(f"release archive link or special file: {member.name}")
            target = destination.joinpath(*name.parts)
            if member.isdir():
                target.mkdir(parents=True, exist_ok=True)
            else:
                target.parent.mkdir(parents=True, exist_ok=True)
                source = bundle.extractfile(member)
                if source is None:
                    raise ValueError(f"release archive file unreadable: {member.name}")
                with source, target.open("wb") as output:
                    shutil.copyfileobj(source, output)


def stage(
    *,
    archive: Path,
    archive_sha256: str,
    checkout: Path,
    commit: str,
    staging: Path,
    node_version: str,
    receipt: Path | None = None,
) -> str:
    """Fail closed before replacing the staging directory."""
    if len(archive_sha256) != 64 or _digest(archive) != archive_sha256.lower():
        raise ValueError("release archive SHA-256 mismatch")
    if resolve_build_identity(checkout)["commit"] != commit:
        raise ValueError("release checkout Git SHA mismatch")
    with tempfile.TemporaryDirectory(prefix=".release-", dir=staging.parent) as tmp:
        root = Path(tmp)
        _extract_checked(archive, root)
        manifest = json.loads((root / "release-manifest.json").read_text(encoding="utf-8"))
        verify_release_manifest(manifest, root, root / "frontend/.next", expected_commit=commit)
        if (root / "frontend/.next/server" / NEXT_ROUTE_CACHE_DIRECTORY).exists():
            # The digest ignores Next's runtime response cache because the LIVE
            # tree grows one; a tested archive never carries it.
            raise ValueError("release archive carries a runtime route cache")
        identity = manifest["identity"]
        for relative, key in (
            ("requirements.lock.txt", "python_lock_sha256"),
            ("frontend/package-lock.json", "frontend_lock_sha256"),
        ):
            if _text_digest(checkout / relative) != identity[key]:
                raise ValueError(f"release archive differs from checked-out {relative}")
        built_node = identity["node_version"].lstrip("v").split(".", 1)[0]
        runtime_node = node_version.lstrip("v").split(".", 1)[0]
        if built_node != runtime_node:
            raise ValueError("release Node major version differs from production")
        if staging.exists():
            shutil.rmtree(staging)
        shutil.move(str(root / "frontend/.next"), str(staging))
        if receipt is not None:
            receipt.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(root / "release-manifest.json", receipt)
        return manifest["artifact_id"]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--archive", type=Path, required=True)
    parser.add_argument("--archive-sha256", required=True)
    parser.add_argument("--checkout", type=Path, required=True)
    parser.add_argument("--commit", required=True)
    parser.add_argument("--staging", type=Path, required=True)
    parser.add_argument("--node-version", required=True)
    parser.add_argument("--receipt", type=Path)
    args = parser.parse_args()
    print(
        stage(
            archive=args.archive,
            archive_sha256=args.archive_sha256,
            checkout=args.checkout,
            commit=args.commit,
            staging=args.staging,
            node_version=args.node_version,
            receipt=args.receipt,
        )
    )


if __name__ == "__main__":
    main()
