"""The wheelhouse proof must bind exact bytes to the lock and runtime."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from scripts import backend_wheelhouse as artifact


def _fixture(tmp_path: Path) -> tuple[Path, Path]:
    wheels = tmp_path / "wheels"
    wheels.mkdir()
    (wheels / "example-1.0-py3-none-any.whl").write_bytes(b"wheel bytes")
    lock = tmp_path / "requirements-dev.lock.txt"
    lock.write_text("example==1.0 --hash=sha256:abc\n", encoding="utf-8")
    return wheels, lock


def test_manifest_binds_wheel_bytes_lock_and_runtime(tmp_path):
    wheels, lock = _fixture(tmp_path)
    manifest = artifact.inspect(wheels, lock)
    assert manifest["schema"] == artifact.SCHEMA
    assert len(manifest["wheels"]) == 1
    assert artifact.verify(manifest, wheels, lock) == manifest["wheelhouse_sha256"]
    (wheels / "example-1.0-py3-none-any.whl").write_bytes(b"substituted")
    with pytest.raises(ValueError, match="differs"):
        artifact.verify(manifest, wheels, lock)


def test_manifest_rejects_lock_and_entry_drift(tmp_path):
    wheels, lock = _fixture(tmp_path)
    manifest = artifact.inspect(wheels, lock)
    lock.write_text("example==2.0 --hash=sha256:def\n", encoding="utf-8")
    with pytest.raises(ValueError, match="differs"):
        artifact.verify(manifest, wheels, lock)
    lock.write_text("example==1.0 --hash=sha256:abc\n", encoding="utf-8")
    (wheels / "unexpected.txt").write_text("x", encoding="utf-8")
    with pytest.raises(ValueError, match="unsafe"):
        artifact.inspect(wheels, lock)


def test_manifest_rejects_symlink_and_extra_claim(tmp_path):
    wheels, lock = _fixture(tmp_path)
    manifest = artifact.inspect(wheels, lock)
    manifest["extra"] = True
    with pytest.raises(ValueError, match="differs"):
        artifact.verify(manifest, wheels, lock)
    (wheels / "example-1.0-py3-none-any.whl").unlink()
    try:
        (wheels / "example-1.0-py3-none-any.whl").symlink_to(lock)
    except OSError:
        pytest.skip("symlink creation unavailable")
    with pytest.raises(ValueError, match="unsafe"):
        artifact.inspect(wheels, lock)


def test_manifest_json_roundtrip(tmp_path):
    wheels, lock = _fixture(tmp_path)
    manifest = artifact.inspect(wheels, lock)
    assert (
        artifact.verify(json.loads(json.dumps(manifest)), wheels, lock)
        == manifest["wheelhouse_sha256"]
    )
