"""Saved release retention preserves immediate rollback and unknown files."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from scripts.release_retention import prune_releases


def _release(directory: Path, number: int) -> str:
    sha = f"{number:040x}"
    for suffix in ("tar", "sha256", "json"):
        path = directory / f"{sha}.{suffix}"
        path.write_bytes(b"release")
        os.utime(path, ns=(number, number))
    return sha


def test_keeps_newest_and_both_rollback_boundaries(tmp_path: Path):
    shas = [_release(tmp_path, number) for number in range(1, 7)]
    unknown = tmp_path / "operator-notes.txt"
    unknown.write_text("leave alone", encoding="utf-8")
    removed = prune_releases(tmp_path, current=shas[2], previous=shas[0], keep=2)
    assert removed == [shas[3], shas[1]]
    for sha in (shas[5], shas[4], shas[2], shas[0]):
        assert (tmp_path / f"{sha}.tar").exists()
    assert unknown.read_text(encoding="utf-8") == "leave alone"


def test_incomplete_release_is_never_deleted(tmp_path: Path):
    root = tmp_path / "releases"
    root.mkdir()
    shas = [_release(root, number) for number in range(1, 4)]
    (root / f"{shas[0]}.json").unlink()
    removed = prune_releases(root, current=shas[2], previous=None, keep=2)
    assert removed == []
    assert (root / f"{shas[0]}.tar").exists()


def test_symlinked_release_is_never_deleted(tmp_path: Path):
    root = tmp_path / "releases"
    root.mkdir()
    sha = _release(root, 1)
    outside = tmp_path / "outside.tar"
    outside.write_bytes(b"outside")
    link = root / f"{0:040x}.tar"
    release_link = root.parent / "release-link"
    try:
        link.symlink_to(outside)
        release_link.symlink_to(root, target_is_directory=True)
    except OSError:
        pytest.skip("symlink creation unavailable")
    removed = prune_releases(root, current=sha, previous=None, keep=2)
    assert removed == []
    assert outside.read_bytes() == b"outside"
    with pytest.raises(ValueError, match="real directory"):
        prune_releases(release_link, current=sha, previous=None)


def test_successful_deploy_wires_bounded_retention():
    deploy = (Path(__file__).resolve().parents[2] / "deploy/deploy.sh").read_text(encoding="utf-8")
    record = deploy[
        deploy.index("record_success_state() {") : deploy.index("attempt_auto_rollback() {")
    ]
    assert "scripts/release_retention.py" in record
    assert '--current "${TARGET_REV}"' in record
    assert '--previous "${PRE_DEPLOY_REV}"' in record
    assert "--keep 8" in record
