"""Preserve a verified rollback archive for the revision being deployed.

One complete triplet (``<sha>.tar``, ``.sha256``, ``.json``) is kept per
revision. An identical artifact is never rewritten. A *different* artifact for
the same revision is expected rather than suspicious: Next stamps a random
``BUILD_ID`` on every build, so re-running the deploy workflow for a revision
(same-commit redeploy, or a dispatched rollback to a recent commit) always
produces a new artifact ID from the same tested source. That archive is the one
the deploy validated and actually serves, so it replaces the saved one once the
deploy succeeds. Refusing it made every workflow rollback to a saved revision
fail closed and auto-roll back onto the release being rolled away from.

Incomplete, corrupt or non-regular saved files are still refused: they need an
operator, not a silent overwrite.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import sys
import tempfile
from pathlib import Path

_SHA = re.compile(r"[0-9a-f]{40}")
_DIGEST = re.compile(r"[0-9a-f]{64}")


def _artifact_id(path: Path, commit: str) -> str:
    manifest = json.loads(path.read_text(encoding="utf-8"))
    identity = manifest.get("identity")
    artifact_id = manifest.get("artifact_id")
    if (
        not isinstance(identity, dict)
        or identity.get("commit") != commit
        or not isinstance(artifact_id, str)
        or not _DIGEST.fullmatch(artifact_id)
    ):
        raise ValueError("release manifest identity is invalid")
    return artifact_id


def _file_digest(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _paths(release_dir: Path, commit: str) -> tuple[Path, Path, Path]:
    return tuple(release_dir / f"{commit}.{suffix}" for suffix in ("tar", "sha256", "json"))


def _existing_artifact_id(release_dir: Path, commit: str) -> str | None:
    """Return the saved artifact ID for ``commit``, or None when nothing is saved."""
    archive, sidecar, manifest = _paths(release_dir, commit)
    present = [path.exists() or path.is_symlink() for path in (archive, sidecar, manifest)]
    if not any(present):
        return None
    if not all(present) or any(
        path.is_symlink() or not path.is_file() for path in (archive, sidecar, manifest)
    ):
        raise ValueError("saved release is incomplete or unsafe; refusing overwrite")
    expected = sidecar.read_text(encoding="utf-8").strip()
    if not _DIGEST.fullmatch(expected) or _file_digest(archive) != expected:
        raise ValueError("saved release archive checksum mismatch; refusing overwrite")
    return _artifact_id(manifest, commit)


def save_release_archive(
    *,
    archive: Path,
    expected_sha256: str,
    manifest: Path,
    release_dir: Path,
    commit: str,
    check_only: bool = False,
) -> Path | None:
    """Check or save one revision.

    Returns the saved manifest path, or None for a ``check_only`` call that
    would publish (no saved triplet yet, or a different artifact ID that the
    successful deploy will replace).
    """
    if not _SHA.fullmatch(commit) or not _DIGEST.fullmatch(expected_sha256):
        raise ValueError("release revision or archive digest is invalid")
    if release_dir.is_symlink() or not release_dir.is_dir():
        raise ValueError("release directory must be a real directory")
    if archive.is_symlink() or not archive.is_file() or _file_digest(archive) != expected_sha256:
        raise ValueError("incoming release archive checksum mismatch")
    if manifest.is_symlink() or not manifest.is_file():
        raise ValueError("incoming release manifest is missing or unsafe")
    artifact_id = _artifact_id(manifest, commit)
    existing_id = _existing_artifact_id(release_dir, commit)
    if existing_id == artifact_id:
        return _paths(release_dir, commit)[2]
    if check_only:
        return None
    if existing_id is not None:
        print(
            f"replacing saved release {commit}: artifact {existing_id} -> {artifact_id}",
            file=sys.stderr,
        )

    target_archive, target_sidecar, target_manifest = _paths(release_dir, commit)
    with tempfile.TemporaryDirectory(prefix=f".{commit}.", dir=release_dir) as staging:
        stage = Path(staging)
        staged_archive = stage / "release.tar"
        shutil.copyfile(archive, staged_archive)
        if _file_digest(staged_archive) != expected_sha256:
            raise ValueError("staged release archive checksum mismatch")
        staged_sidecar = stage / "release.sha256"
        staged_sidecar.write_text(expected_sha256 + "\n", encoding="utf-8")
        staged_manifest = stage / "release.json"
        shutil.copyfile(manifest, staged_manifest)
        if _artifact_id(staged_manifest, commit) != artifact_id:
            raise ValueError("staged release manifest changed")
        # All three files are staged and checked before any final path is
        # published. When an older artifact of this revision is replaced, an
        # interruption between renames leaves either a tar/checksum mismatch
        # (refused for operator inspection) or a self-consistent new tar beside
        # a stale .json, which the next save of this revision replaces.
        # Rollback reads only the tar and its checksum.
        os.replace(staged_archive, target_archive)
        os.replace(staged_sidecar, target_sidecar)
        os.replace(staged_manifest, target_manifest)
    return target_manifest


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--archive", type=Path, required=True)
    parser.add_argument("--archive-sha256", required=True)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--release-dir", type=Path, required=True)
    parser.add_argument("--commit", required=True)
    parser.add_argument("--check-only", action="store_true")
    args = parser.parse_args()
    result = save_release_archive(
        archive=args.archive,
        expected_sha256=args.archive_sha256,
        manifest=args.manifest,
        release_dir=args.release_dir,
        commit=args.commit,
        check_only=args.check_only,
    )
    if result is not None:
        print(result)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
