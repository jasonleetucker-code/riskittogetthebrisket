"""Release identity is bound to exact source, locks and built frontend bytes."""

import copy
import json
from pathlib import Path

import pytest

from src.api.build_identity import (
    create_release_manifest,
    resolve_runtime_release_identity,
    verify_release_manifest,
)

SHA = "a" * 40


@pytest.fixture
def release_tree(tmp_path: Path) -> tuple[Path, Path]:
    (tmp_path / ".git").mkdir()
    (tmp_path / ".git/HEAD").write_text(SHA + "\n", encoding="utf-8")
    (tmp_path / "frontend/.next/static").mkdir(parents=True)
    (tmp_path / "frontend/package-lock.json").write_text(
        '{"lockfileVersion":3}\n', encoding="utf-8"
    )
    (tmp_path / "requirements.lock.txt").write_text("fastapi==0.141.1\n", encoding="utf-8")
    build = tmp_path / "frontend/.next"
    (build / "BUILD_ID").write_text("build-123\n", encoding="utf-8")
    (build / "static/chunk.js").write_bytes(b"compiled javascript")
    (build / "cache").mkdir()
    (build / "cache/trace").write_bytes(b"ephemeral cache")
    return tmp_path, build


def manifest(root: Path, build: Path, commit: str = SHA) -> dict:
    return create_release_manifest(
        root,
        build,
        commit=commit,
        node_version="v20.19.0",
        run_id="123",
        built_at_utc="2026-10-03T00:00:00Z",
    )


def test_artifact_identity_is_content_addressed_and_verifiable(release_tree):
    root, build = release_tree
    first = manifest(root, build)
    second = create_release_manifest(
        root,
        build,
        commit=SHA,
        node_version="v20.19.0",
        run_id="456",
        built_at_utc="2026-10-04T00:00:00Z",
    )
    assert first["artifact_id"] == second["artifact_id"]
    assert first["identity"]["backend_artifact_sha256"] is None
    assert first["backend_artifact_unavailable_reason"]
    verify_release_manifest(first, root, build, expected_commit=SHA)
    (build / "cache/trace").write_bytes(b"different disposable cache")
    assert manifest(root, build)["artifact_id"] == first["artifact_id"]


def test_every_identity_input_changes_artifact_id(release_tree):
    root, build = release_tree
    baseline = manifest(root, build)["artifact_id"]
    (root / ".git/HEAD").write_text("b" * 40 + "\n", encoding="utf-8")
    assert manifest(root, build, "b" * 40)["artifact_id"] != baseline
    (root / ".git/HEAD").write_text(SHA + "\n", encoding="utf-8")

    lock = root / "requirements.lock.txt"
    lock.write_text("fastapi==0.141.2\n", encoding="utf-8")
    assert manifest(root, build)["artifact_id"] != baseline
    lock.write_text("fastapi==0.141.1\n", encoding="utf-8")

    frontend_lock = root / "frontend/package-lock.json"
    frontend_lock.write_text('{"lockfileVersion":4}\n', encoding="utf-8")
    assert manifest(root, build)["artifact_id"] != baseline
    frontend_lock.write_text('{"lockfileVersion":3}\n', encoding="utf-8")

    (build / "static/chunk.js").write_bytes(b"tampered javascript")
    assert manifest(root, build)["artifact_id"] != baseline


def test_mismatched_commit_or_corrupted_bytes_are_refused(release_tree):
    root, build = release_tree
    built = manifest(root, build)
    with pytest.raises(ValueError, match="Git SHA mismatch"):
        verify_release_manifest(built, root, build, expected_commit="b" * 40)

    with pytest.raises(ValueError, match="differs from the checkout"):
        manifest(root, build, "b" * 40)

    (build / "static/chunk.js").write_bytes(b"modified")
    with pytest.raises(ValueError, match="frontend bytes mismatch"):
        verify_release_manifest(built, root, build, expected_commit=SHA)


def test_manifest_identity_cannot_be_relabelled(release_tree):
    root, build = release_tree
    built = manifest(root, build)
    forged = copy.deepcopy(built)
    forged["artifact_id"] = "0" * 64
    with pytest.raises(ValueError, match="identity mismatch"):
        verify_release_manifest(forged, root, build, expected_commit=SHA)

    forged = copy.deepcopy(built)
    forged["identity"]["backend_artifact_sha256"] = "0" * 64
    with pytest.raises(ValueError, match="backend identity is unsupported"):
        verify_release_manifest(forged, root, build, expected_commit=SHA)


def test_running_identity_reports_verified_bytes_and_unknown_backend(release_tree):
    root, build = release_tree
    absent = resolve_runtime_release_identity(root, commit=SHA)
    assert absent["frontend_artifact_id"] is None
    assert absent["frontend_artifact_unavailable_reason"] == "manifest_missing"
    assert absent["dependency_lock_sha256"]

    built = manifest(root, build)
    (root / ".release-manifest.json").write_text(json.dumps(built), encoding="utf-8")
    running = resolve_runtime_release_identity(root, commit=SHA)
    assert running["frontend_artifact_id"] == built["artifact_id"]
    assert running["frontend_build_id"] == "build-123"
    assert running["frontend_artifact_unavailable_reason"] is None
    assert running["backend_artifact_sha256"] is None
    assert running["backend_artifact_unavailable_reason"]

    (build / "static/chunk.js").write_bytes(b"corrupted after deployment")
    corrupt = resolve_runtime_release_identity(root, commit=SHA)
    assert corrupt["frontend_artifact_id"] is None
    assert corrupt["frontend_artifact_unavailable_reason"] == "manifest_invalid_or_mismatch"


def test_v2_backend_identity_requires_exact_archive_or_install_receipt(release_tree):
    root, build = release_tree
    archive = root / "backend-wheelhouse.tar"
    archive.write_bytes(b"tested backend artifact")
    built = create_release_manifest(
        root,
        build,
        commit=SHA,
        node_version="v20.19.0",
        backend_archive=archive,
    )
    assert built["schema_version"] == "calculator-release/v2"
    verify_release_manifest(built, root, build, expected_commit=SHA)
    archive.write_bytes(b"substituted backend artifact")
    with pytest.raises(ValueError, match="backend bytes mismatch"):
        verify_release_manifest(built, root, build, expected_commit=SHA)
    archive.unlink()
    with pytest.raises(ValueError, match="install receipt missing"):
        verify_release_manifest(built, root, build, expected_commit=SHA)
    identity = built["identity"]
    receipt = {
        "commit": SHA,
        "backend_artifact_sha256": identity["backend_artifact_sha256"],
        "python_lock_sha256": identity["python_lock_sha256"],
        "python_abi": identity["python_abi"],
        "pip_check": "passed",
        "installed_wheels_verified": 1,
    }
    (root / ".backend-artifact-receipt.json").write_text(json.dumps(receipt), encoding="utf-8")
    verify_release_manifest(built, root, build, expected_commit=SHA)
    (root / ".release-manifest.json").write_text(json.dumps(built), encoding="utf-8")
    running = resolve_runtime_release_identity(root, commit=SHA)
    assert running["backend_artifact_sha256"] == identity["backend_artifact_sha256"]
    assert running["backend_artifact_unavailable_reason"] is None
    receipt["installed_wheels_verified"] = 0
    (root / ".backend-artifact-receipt.json").write_text(json.dumps(receipt), encoding="utf-8")
    with pytest.raises(ValueError, match="install receipt mismatch"):
        verify_release_manifest(built, root, build, expected_commit=SHA)
    receipt["installed_wheels_verified"] = 1
    receipt["pip_check"] = "failed"
    (root / ".backend-artifact-receipt.json").write_text(json.dumps(receipt), encoding="utf-8")
    with pytest.raises(ValueError, match="install receipt mismatch"):
        verify_release_manifest(built, root, build, expected_commit=SHA)


def test_workflow_packages_only_after_build_and_checks():
    workflow = (Path(__file__).resolve().parents[2] / ".github/workflows/deploy.yml").read_text(
        encoding="utf-8"
    )
    assert (
        workflow.index("- name: Frontend bundle-size gate")
        < workflow.index("- name: Package tested release artifact")
        < workflow.index("- name: Upload tested release artifact")
    )
    assert "--exclude='frontend/.next/cache'" in workflow
    assert "sha256sum -c calculator-release.tar.sha256" in workflow
