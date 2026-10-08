"""The production backend installer rejects changed bytes before running pip."""

from __future__ import annotations

import hashlib
import io
import json
import sys
import tarfile
from pathlib import Path
from types import SimpleNamespace

import pytest

from scripts import backend_wheelhouse, stage_backend_artifact
from src.api.build_identity import create_release_manifest

SHA = "a" * 40


def _release(tmp_path: Path) -> tuple[Path, Path, str]:
    root = tmp_path / "checkout"
    (root / ".git").mkdir(parents=True)
    (root / ".git/HEAD").write_text(SHA + "\n", encoding="utf-8")
    (root / "frontend/.next").mkdir(parents=True)
    (root / "frontend/.next/BUILD_ID").write_text("backend-test", encoding="utf-8")
    (root / "frontend/.next/server").mkdir()
    (root / "frontend/.next/server/app-paths-manifest.json").write_text("{}", encoding="utf-8")
    (root / "frontend/.next/server/pages-manifest.json").write_text("{}", encoding="utf-8")
    (root / "frontend/package-lock.json").write_text("{}\n", encoding="utf-8")
    (root / "requirements.lock.txt").write_text("example==1.0\n", encoding="utf-8")
    (root / "requirements-build.lock.txt").write_text("setuptools==84.0.0\n", encoding="utf-8")
    wheelhouse = tmp_path / "wheelhouse"
    (wheelhouse / "backend-wheels").mkdir(parents=True)
    (wheelhouse / "backend-sources").mkdir()
    (wheelhouse / "backend-wheels/example-1.0-py3-none-any.whl").write_bytes(b"wheel")
    for name in ("requirements.lock.txt", "requirements-build.lock.txt"):
        (wheelhouse / name).write_bytes((root / name).read_bytes())
    wheel_manifest = backend_wheelhouse.inspect(
        wheelhouse / "backend-wheels",
        wheelhouse / "requirements.lock.txt",
        wheelhouse / "requirements-build.lock.txt",
        wheelhouse / "backend-sources",
    )
    (wheelhouse / "backend-wheelhouse-manifest.json").write_text(
        json.dumps(wheel_manifest), encoding="utf-8"
    )
    backend_tar = root / "backend-wheelhouse.tar"
    with tarfile.open(backend_tar, "w") as bundle:
        for name in (
            "backend-wheelhouse-manifest.json",
            "requirements.lock.txt",
            "requirements-build.lock.txt",
            "backend-wheels",
            "backend-sources",
        ):
            bundle.add(wheelhouse / name, arcname=name)
    manifest = create_release_manifest(
        root,
        root / "frontend/.next",
        commit=SHA,
        node_version="v20.19.0",
        backend_archive=backend_tar,
    )
    (root / "release-manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    release = tmp_path / "release.tar"
    with tarfile.open(release, "w") as bundle:
        bundle.add(root / "release-manifest.json", arcname="release-manifest.json")
        bundle.add(backend_tar, arcname="backend-wheelhouse.tar")
    return root, release, hashlib.sha256(release.read_bytes()).hexdigest()


def test_installer_checks_layers_and_records_only_successful_offline_install(tmp_path, monkeypatch):
    root, release, digest = _release(tmp_path)
    calls = []
    monkeypatch.setenv("PIP_TARGET", str(tmp_path / "redirected"))
    monkeypatch.setenv("PYTHONPATH", str(tmp_path / "injected"))

    def fake_run(args, **kwargs):
        calls.append((args, kwargs))
        return SimpleNamespace(returncode=0)

    def fake_output(args, **_kwargs):
        if "-I" in args:
            return json.dumps({"example": {"version": "1.0", "in_venv": True}})
        return f"{sys.implementation.name}-{sys.version_info.major}.{sys.version_info.minor}\n"

    monkeypatch.setattr(stage_backend_artifact.subprocess, "run", fake_run)
    monkeypatch.setattr(
        stage_backend_artifact.subprocess,
        "check_output",
        fake_output,
    )
    monkeypatch.setattr(
        stage_backend_artifact.shutil,
        "disk_usage",
        lambda _path: SimpleNamespace(free=10 * 1024**3),
    )
    receipt = root / ".backend-artifact-receipt.json"
    observed = stage_backend_artifact.install(
        release_archive=release,
        archive_sha256=digest,
        checkout=root,
        commit=SHA,
        venv_python=Path(sys.executable),
        receipt=receipt,
    )
    assert (
        observed
        == json.loads((root / "release-manifest.json").read_text())["identity"][
            "backend_artifact_sha256"
        ]
    )
    assert len(calls) == 2
    assert "--no-index" in calls[0][0] and "--require-hashes" in calls[0][0]
    assert "--isolated" in calls[0][0] and calls[1][0][-1] == "check"
    assert "PIP_TARGET" not in calls[0][1]["env"]
    assert "PYTHONPATH" not in calls[0][1]["env"]
    assert json.loads(receipt.read_text())["pip_check"] == "passed"
    assert json.loads(receipt.read_text())["installed_wheels_verified"] == 1

    receipt.unlink()
    with pytest.raises(ValueError, match="release archive SHA-256 mismatch"):
        stage_backend_artifact.install(
            release_archive=release,
            archive_sha256="0" * 64,
            checkout=root,
            commit=SHA,
            venv_python=Path(sys.executable),
            receipt=receipt,
        )
    assert not receipt.exists()
    assert len(calls) == 2


def test_installer_refuses_receipt_for_wrong_serving_venv_distribution(tmp_path, monkeypatch):
    root, release, digest = _release(tmp_path)
    monkeypatch.setattr(stage_backend_artifact.subprocess, "run", lambda *_args, **_kwargs: None)

    def fake_output(args, **_kwargs):
        if "-I" in args:
            return json.dumps({"example": {"version": "1.0", "in_venv": False}})
        return f"{sys.implementation.name}-{sys.version_info.major}.{sys.version_info.minor}\n"

    monkeypatch.setattr(stage_backend_artifact.subprocess, "check_output", fake_output)
    monkeypatch.setattr(
        stage_backend_artifact.shutil,
        "disk_usage",
        lambda _path: SimpleNamespace(free=10 * 1024**3),
    )
    receipt = root / ".backend-artifact-receipt.json"
    with pytest.raises(ValueError, match="not installed in serving venv"):
        stage_backend_artifact.install(
            release_archive=release,
            archive_sha256=digest,
            checkout=root,
            commit=SHA,
            venv_python=Path(sys.executable),
            receipt=receipt,
        )
    assert not receipt.exists()


def test_nested_wheelhouse_rejects_path_escape(tmp_path):
    archive = tmp_path / "unsafe.tar"
    with tarfile.open(archive, "w") as bundle:
        member = tarfile.TarInfo("../outside")
        member.size = 4
        bundle.addfile(member, io.BytesIO(b"evil"))
    with pytest.raises(ValueError, match="unsafe path"):
        stage_backend_artifact._extract_wheelhouse(archive, tmp_path / "stage")
    assert not (tmp_path / "outside").exists()
