"""The deploy stages only the archive that CI identified and tested."""

import hashlib
import io
import json
import tarfile
from pathlib import Path

import pytest

from scripts.stage_release_artifact import stage
from src.api.build_identity import create_release_manifest

SHA = "a" * 40


@pytest.fixture
def release(tmp_path: Path):
    checkout = tmp_path / "checkout"
    (checkout / ".git").mkdir(parents=True)
    (checkout / ".git/HEAD").write_text(SHA + "\n", encoding="utf-8")
    (checkout / "frontend/.next/static").mkdir(parents=True)
    (checkout / "requirements.lock.txt").write_text("fastapi==1.0\n", encoding="utf-8")
    (checkout / "frontend/package-lock.json").write_text("{}\n", encoding="utf-8")
    (checkout / "frontend/.next/BUILD_ID").write_text("ci-build\n", encoding="utf-8")
    (checkout / "frontend/.next/static/app.js").write_bytes(b"tested frontend")
    (checkout / "frontend/.next/server").mkdir()
    (checkout / "frontend/.next/server/app-paths-manifest.json").write_text(
        '{"/page": "app/page.js"}', encoding="utf-8"
    )
    (checkout / "frontend/.next/server/pages-manifest.json").write_text("{}", encoding="utf-8")
    manifest = create_release_manifest(
        checkout, checkout / "frontend/.next", commit=SHA, node_version="v20.19.0"
    )
    (checkout / "release-manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    archive = tmp_path / "release.tar"
    with tarfile.open(archive, "w") as bundle:
        for name in (
            "release-manifest.json",
            "requirements.lock.txt",
            "frontend/package-lock.json",
            "frontend/.next/BUILD_ID",
            "frontend/.next/static/app.js",
            "frontend/.next/server/app-paths-manifest.json",
            "frontend/.next/server/pages-manifest.json",
        ):
            bundle.add(checkout / name, arcname=name)
    digest = hashlib.sha256(archive.read_bytes()).hexdigest()
    return checkout, archive, digest, manifest


def _stage(tmp_path: Path, release, **overrides):
    checkout, archive, digest, _ = release
    args = {
        "archive": archive,
        "archive_sha256": digest,
        "checkout": checkout,
        "commit": SHA,
        "staging": checkout / "frontend/.next.new",
        "node_version": "v20.20.0",
        "receipt": tmp_path / "receipt.json",
    }
    args.update(overrides)
    return stage(**args)


def test_verified_ci_bytes_are_staged(release, tmp_path):
    checkout, _, _, manifest = release
    assert _stage(tmp_path, release) == manifest["artifact_id"]
    assert (checkout / "frontend/.next.new/static/app.js").read_bytes() == b"tested frontend"
    assert json.loads((tmp_path / "receipt.json").read_text()) == manifest


def test_archive_checksum_and_checkout_lock_are_required(release, tmp_path):
    checkout, _, _, _ = release
    with pytest.raises(ValueError, match="archive SHA-256 mismatch"):
        _stage(tmp_path, release, archive_sha256="0" * 64)
    (checkout / "requirements.lock.txt").write_text("fastapi==2.0\n", encoding="utf-8")
    with pytest.raises(ValueError, match="checked-out requirements.lock.txt"):
        _stage(tmp_path, release)
    assert not (checkout / "frontend/.next.new").exists()


def test_wrong_node_major_refused(release, tmp_path):
    with pytest.raises(ValueError, match="Node major"):
        _stage(tmp_path, release, node_version="v24.0.0")


def test_rejected_archive_preserves_existing_staging(release, tmp_path):
    checkout, _, _, _ = release
    staging = checkout / "frontend/.next.new"
    staging.mkdir()
    (staging / "known-good").write_text("keep", encoding="utf-8")
    with pytest.raises(ValueError, match="Node major"):
        _stage(tmp_path, release, node_version="v24.0.0")
    assert (staging / "known-good").read_text(encoding="utf-8") == "keep"


def test_archive_path_escape_refused(release, tmp_path):
    checkout, _, _, _ = release
    archive = tmp_path / "malicious.tar"
    with tarfile.open(archive, "w") as bundle:
        entry = tarfile.TarInfo("../outside")
        entry.size = 4
        bundle.addfile(entry, io.BytesIO(b"evil"))
    digest = hashlib.sha256(archive.read_bytes()).hexdigest()
    with pytest.raises(ValueError, match="unexpected release archive path"):
        _stage(tmp_path, release, archive=archive, archive_sha256=digest)
    assert not (checkout / "frontend/.next.new").exists()


def test_v2_backend_archive_is_verified_before_frontend_staging(release, tmp_path):
    checkout, _, _, _ = release
    backend = checkout / "backend-wheelhouse.tar"
    backend.write_bytes(b"ci backend bytes")
    manifest = create_release_manifest(
        checkout,
        checkout / "frontend/.next",
        commit=SHA,
        node_version="v20.19.0",
        backend_archive=backend,
    )
    (checkout / "release-manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    archive = tmp_path / "v2-release.tar"
    with tarfile.open(archive, "w") as bundle:
        for name in (
            "release-manifest.json",
            "requirements.lock.txt",
            "frontend/package-lock.json",
            "frontend/.next/BUILD_ID",
            "frontend/.next/static/app.js",
            "frontend/.next/server/app-paths-manifest.json",
            "frontend/.next/server/pages-manifest.json",
            "backend-wheelhouse.tar",
        ):
            bundle.add(checkout / name, arcname=name)
    digest = hashlib.sha256(archive.read_bytes()).hexdigest()
    assert (
        _stage(tmp_path, release, archive=archive, archive_sha256=digest) == manifest["artifact_id"]
    )
    backend.write_bytes(b"changed")
    with tarfile.open(archive, "w") as bundle:
        for name in (
            "release-manifest.json",
            "requirements.lock.txt",
            "frontend/package-lock.json",
            "frontend/.next/BUILD_ID",
            "frontend/.next/static/app.js",
            "frontend/.next/server/app-paths-manifest.json",
            "frontend/.next/server/pages-manifest.json",
            "backend-wheelhouse.tar",
        ):
            bundle.add(checkout / name, arcname=name)
    with pytest.raises(ValueError, match="backend bytes mismatch"):
        _stage(
            tmp_path,
            release,
            archive=archive,
            archive_sha256=hashlib.sha256(archive.read_bytes()).hexdigest(),
        )


def test_deploy_consumes_validation_archive_and_rollback_keeps_it():
    root = Path(__file__).resolve().parents[2]
    workflow = (root / ".github/workflows/deploy.yml").read_text(encoding="utf-8")
    deploy = (root / "deploy/deploy.sh").read_text(encoding="utf-8")
    rollback = (root / "deploy/rollback.sh").read_text(encoding="utf-8")
    assert "archive_sha256: ${{ steps.package.outputs.archive_sha256 }}" in workflow
    assert "artifact_id: ${{ steps.package.outputs.artifact_id }}" in workflow
    assert "VALIDATED_SHA256: ${{ needs.validate.outputs.archive_sha256 }}" in workflow
    assert (
        workflow.index("Download tested release artifact")
        < workflow.index("Transfer tested release archive to production")
        < workflow.index("Run remote deploy script")
    )
    assert 'export RELEASE_ARCHIVE="${RELEASE_ARCHIVE_REMOTE:-}"' in workflow
    assert "if: ${{ needs.resolve.outputs.release_mode == 'artifact' }}" in workflow
    assert "Verify live frontend matches the tested artifact" in workflow
    assert "python3 -m scripts.stage_release_artifact" in deploy
    assert "python3 -m scripts.save_release_archive" in deploy
    assert "--check-only" in deploy
    assert "python3 -m scripts.stage_release_artifact" in rollback
    assert "refusing a rebuild that changes tested bytes" in rollback


def test_archive_carrying_a_runtime_route_cache_is_refused(release, tmp_path):
    """The digest tolerates Next's live response cache; a tested archive has none."""
    checkout, _, _, manifest = release
    owner = hashlib.sha256(b"/page").hexdigest()
    entry = f"frontend/.next/server/route-cache/APP_PAGE/{owner}/$/index.html"
    archive = tmp_path / "cached-release.tar"
    with tarfile.open(archive, "w") as bundle:
        for name in (
            "release-manifest.json",
            "requirements.lock.txt",
            "frontend/package-lock.json",
            "frontend/.next/BUILD_ID",
            "frontend/.next/static/app.js",
            "frontend/.next/server/app-paths-manifest.json",
            "frontend/.next/server/pages-manifest.json",
        ):
            bundle.add(checkout / name, arcname=name)
        info = tarfile.TarInfo(entry)
        info.size = 4
        bundle.addfile(info, io.BytesIO(b"page"))
    digest = hashlib.sha256(archive.read_bytes()).hexdigest()
    with pytest.raises(ValueError, match="carries a runtime route cache"):
        _stage(tmp_path, release, archive=archive, archive_sha256=digest)
    assert not (checkout / "frontend/.next.new").exists()
