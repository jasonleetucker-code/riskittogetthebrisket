"""The committed Python locks are the install authority for CI and deploy."""

import json

import pytest

from scripts import python_lock


def test_committed_lock_matches_manifests_and_runtime_dev_versions():
    python_lock.check()


def test_manifest_change_requires_lock_refresh(tmp_path, monkeypatch):
    metadata = json.loads(python_lock.METADATA.read_text(encoding="utf-8"))
    metadata["sha256"]["requirements.txt"] = "0" * 64
    path = tmp_path / "python-lock.json"
    path.write_text(json.dumps(metadata), encoding="utf-8")
    monkeypatch.setattr(python_lock, "METADATA", path)

    with pytest.raises(ValueError, match="requirements.txt"):
        python_lock.check()


def test_lock_entry_without_hash_is_refused(tmp_path):
    lock = tmp_path / "requirements.lock.txt"
    lock.write_text("example==1.2.3\n", encoding="utf-8")

    with pytest.raises(ValueError, match="missing SHA-256 hash"):
        python_lock.locked(lock)


def test_lock_digest_is_checkout_line_ending_independent(tmp_path):
    path = tmp_path / "requirements.txt"
    path.write_bytes(b"fastapi~=0.141.1\n")
    digest = python_lock.digest(path)
    path.write_bytes(b"fastapi~=0.141.1\r\n")
    assert python_lock.digest(path) == digest


def test_runtime_and_dev_cannot_resolve_different_versions(tmp_path, monkeypatch):
    original = python_lock.DEV.read_text(encoding="utf-8")
    path = tmp_path / "requirements-dev.lock.txt"
    path.write_text(
        original.replace("aiohappyeyeballs==2.7.1", "aiohappyeyeballs==2.7.0", 1), encoding="utf-8"
    )
    monkeypatch.setattr(python_lock, "DEV", path)
    metadata = json.loads(python_lock.METADATA.read_text(encoding="utf-8"))
    metadata["sha256"]["requirements-dev.lock.txt"] = python_lock.digest(path)
    meta_path = tmp_path / "python-lock.json"
    meta_path.write_text(json.dumps(metadata), encoding="utf-8")
    monkeypatch.setattr(python_lock, "METADATA", meta_path)

    with pytest.raises(ValueError, match="dev/runtime lock divergence"):
        python_lock.check()


@pytest.mark.parametrize(
    "path",
    ("deploy/deploy.sh", "deploy/bootstrap-production.sh", "deploy/rollback.sh"),
)
def test_production_install_cannot_resolve_floating_graph(path):
    script = (python_lock.ROOT / path).read_text(encoding="utf-8")
    assert "requirements.lock.txt" in script
    assert "python3 scripts/python_lock.py check" in script
    assert 'install --require-hashes -r "${req_file}"' in script


def test_rollback_legacy_target_remains_recoverable():
    script = (python_lock.ROOT / "deploy/rollback.sh").read_text(encoding="utf-8")
    assert 'if [[ -f "requirements.lock.txt" ]]; then' in script
    assert "Rollback target predates the Python lock" in script


@pytest.mark.parametrize(
    "path",
    (
        ".github/workflows/pr-validation.yml",
        ".github/workflows/release-candidate.yml",
        ".github/workflows/deploy.yml",
    ),
)
def test_required_validation_installs_exact_development_graph(path):
    workflow = (python_lock.ROOT / path).read_text(encoding="utf-8")
    assert "python scripts/python_lock.py check" in workflow
    assert "pip install --require-hashes -r requirements-dev.lock.txt" in workflow
    if path == ".github/workflows/deploy.yml":
        # An explicitly requested pre-artifact historical rollback cannot
        # carry a lock that did not exist at its target revision. The deploy
        # classifier admits that mode only for a manual pre-cutover ancestor;
        # keep the one floating install confined to that named exception.
        legacy_install = (
            'elif [[ "${RELEASE_MODE}" == "legacy" ]]; then\n'
            '            echo "::notice::Explicit historical rollback: installing the target\'s legacy requirements-dev.txt. Exact Python lock identity is unavailable."\n'
            "            pip install -r requirements-dev.txt"
        )
        assert legacy_install in workflow
        assert workflow.count("pip install -r requirements-dev.txt") == 1
        workflow = workflow.replace(legacy_install, "")
    assert "pip install -r requirements-dev.txt" not in workflow


def test_scheduled_refresh_installs_exact_runtime_graph():
    workflow = (python_lock.ROOT / ".github/workflows/scheduled-refresh.yml").read_text(
        encoding="utf-8"
    )
    assert "python scripts/python_lock.py check" in workflow
    assert "pip install --require-hashes -r requirements.lock.txt" in workflow
    assert "pip install -r requirements.txt" not in workflow
