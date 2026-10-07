"""Saved rollback archives: kept when identical, replaced by a newer tested build.

Next stamps a random BUILD_ID on every build, so re-running the deploy workflow
for an already-saved revision (a same-commit redeploy, or a dispatched rollback
to a recent commit) always produces a different artifact ID from the same
tested source. Refusing it made every such workflow rollback fail closed and
auto-roll back onto the release being rolled away from (#1667 review, B2).
Incomplete or corrupt saved triplets are still refused for an operator.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from scripts.save_release_archive import save_release_archive

COMMIT = "a" * 40


def _candidate(root: Path, *, content: bytes, artifact_id: str) -> tuple[Path, str, Path]:
    root.mkdir()
    archive = root / "release.tar"
    archive.write_bytes(content)
    digest = hashlib.sha256(content).hexdigest()
    manifest = root / "release.json"
    manifest.write_text(
        json.dumps({"identity": {"commit": COMMIT}, "artifact_id": artifact_id}),
        encoding="utf-8",
    )
    return archive, digest, manifest


def _save(candidate: tuple[Path, str, Path], release_dir: Path, *, check_only: bool = False):
    archive, digest, manifest = candidate
    return save_release_archive(
        archive=archive,
        expected_sha256=digest,
        manifest=manifest,
        release_dir=release_dir,
        commit=COMMIT,
        check_only=check_only,
    )


def test_stages_complete_triplet_then_preserves_it_on_same_artifact(tmp_path: Path):
    release_dir = tmp_path / "saved"
    release_dir.mkdir()
    first = _candidate(tmp_path / "first", content=b"tested build", artifact_id="b" * 64)
    manifest_path = _save(first, release_dir)
    assert manifest_path == release_dir / f"{COMMIT}.json"
    assert (release_dir / f"{COMMIT}.tar").read_bytes() == b"tested build"
    assert (release_dir / f"{COMMIT}.sha256").read_text(encoding="utf-8").strip() == first[1]

    # Another archive may have different tar metadata but the same tested
    # content identity. The prior rollback triplet is kept byte for byte.
    second = _candidate(tmp_path / "second", content=b"repacked build", artifact_id="b" * 64)
    assert _save(second, release_dir, check_only=True) == manifest_path
    assert _save(second, release_dir) == manifest_path
    assert (release_dir / f"{COMMIT}.tar").read_bytes() == b"tested build"


def test_rebuilt_same_revision_artifact_is_accepted_then_replaces_saved(tmp_path: Path):
    release_dir = tmp_path / "saved"
    release_dir.mkdir()
    first = _candidate(tmp_path / "first", content=b"first tested build", artifact_id="b" * 64)
    _save(first, release_dir)
    rebuilt = _candidate(tmp_path / "rebuilt", content=b"rebuilt same source", artifact_id="c" * 64)

    # Before the live frontend is touched: accepted, and nothing changes yet,
    # so a failure of this deploy still rolls back onto the saved bytes.
    assert _save(rebuilt, release_dir, check_only=True) is None
    assert (release_dir / f"{COMMIT}.tar").read_bytes() == b"first tested build"

    # After the deploy succeeds: the bytes actually serving replace the triplet.
    manifest_path = _save(rebuilt, release_dir)
    assert manifest_path == release_dir / f"{COMMIT}.json"
    assert (release_dir / f"{COMMIT}.tar").read_bytes() == b"rebuilt same source"
    assert (release_dir / f"{COMMIT}.sha256").read_text(encoding="utf-8").strip() == rebuilt[1]
    saved = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert saved["artifact_id"] == "c" * 64
    assert sorted(path.name for path in release_dir.iterdir()) == [
        f"{COMMIT}.json",
        f"{COMMIT}.sha256",
        f"{COMMIT}.tar",
    ]


def test_incomplete_or_corrupt_prior_archive_is_never_overwritten(tmp_path: Path):
    release_dir = tmp_path / "saved"
    release_dir.mkdir()
    candidate = _candidate(tmp_path / "new", content=b"known good", artifact_id="b" * 64)
    _save(candidate, release_dir)
    (release_dir / f"{COMMIT}.tar").write_bytes(b"corrupt")
    with pytest.raises(ValueError, match="checksum mismatch"):
        _save(candidate, release_dir)
    assert (release_dir / f"{COMMIT}.tar").read_bytes() == b"corrupt"
    (release_dir / f"{COMMIT}.sha256").unlink()
    with pytest.raises(ValueError, match="incomplete"):
        _save(candidate, release_dir)


def test_check_only_does_not_publish_a_new_archive(tmp_path: Path):
    release_dir = tmp_path / "saved"
    release_dir.mkdir()
    candidate = _candidate(tmp_path / "new", content=b"tested build", artifact_id="b" * 64)
    assert _save(candidate, release_dir, check_only=True) is None
    assert list(release_dir.iterdir()) == []
