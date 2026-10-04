"""The artifact deploy must only fall back for an explicit historical rollback."""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest
import yaml

from scripts.deploy_release_mode import release_mode


def _git(repo: Path, *args: str) -> str:
    return subprocess.check_output(["git", "-C", str(repo), *args], text=True).strip()


def test_release_mode_never_silently_downgrades(tmp_path: Path):
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-q")
    _git(repo, "config", "user.email", "test@example.com")
    _git(repo, "config", "user.name", "Test")
    (repo / "requirements.txt").write_text("legacy\n", encoding="utf-8")
    _git(repo, "add", ".")
    _git(repo, "commit", "-q", "-m", "legacy")
    legacy = _git(repo, "rev-parse", "HEAD")

    with pytest.raises(ValueError, match="explicit manual rollback override"):
        release_mode(repo, legacy, "push", False)
    with pytest.raises(ValueError, match="explicit manual rollback override"):
        release_mode(repo, legacy, "push", True)
    with pytest.raises(ValueError, match="explicit manual rollback override"):
        release_mode(repo, legacy, "workflow_dispatch", False)
    assert release_mode(repo, legacy, "workflow_dispatch", True) == "legacy"

    for path in (
        "requirements.lock.txt",
        "requirements-dev.lock.txt",
        "scripts/release_artifact.py",
        "scripts/stage_release_artifact.py",
    ):
        file = repo / path
        file.parent.mkdir(parents=True, exist_ok=True)
        file.write_text("artifact\n", encoding="utf-8")
    _git(repo, "add", ".")
    _git(repo, "commit", "-q", "-m", "artifact")
    artifact = _git(repo, "rev-parse", "HEAD")
    assert release_mode(repo, artifact, "push", False) == "artifact"
    assert release_mode(repo, artifact, "workflow_dispatch", True) == "artifact"

    with pytest.raises(ValueError, match="exact commit SHA"):
        release_mode(repo, "HEAD", "workflow_dispatch", True)


def test_workflow_only_skips_artifact_steps_for_explicit_legacy_mode():
    workflow = yaml.safe_load(
        (Path(__file__).resolve().parents[2] / ".github/workflows/deploy.yml").read_text(
            encoding="utf-8"
        )
    )
    jobs = workflow["jobs"]
    assert jobs["resolve"]["outputs"]["release_mode"] == "${{ steps.classify.outputs.mode }}"
    classify = next(step for step in jobs["resolve"]["steps"] if step.get("id") == "classify")
    assert "scripts/deploy_release_mode.py" in classify["run"]
    assert classify["env"]["EVENT_NAME"] == "${{ github.event_name }}"
    assert classify["env"]["ALLOW_LEGACY"] == "${{ inputs.allow_non_fast_forward || false }}"

    condition = "${{ needs.resolve.outputs.release_mode == 'artifact' }}"
    for job, names in (
        ("validate", ("Package tested release artifact", "Upload tested release artifact")),
        (
            "deploy",
            (
                "Download tested release artifact",
                "Verify downloaded archive is the validated archive",
                "Transfer tested release archive to production",
                "Verify live frontend matches the tested artifact",
            ),
        ),
    ):
        steps = {step["name"]: step for step in jobs[job]["steps"]}
        for name in names:
            assert steps[name]["if"] == condition
    smoke = next(
        step for step in jobs["deploy"]["steps"] if step["name"] == "Post-deploy smoke test"
    )
    assert smoke["env"]["RELEASE_MODE"] == "${{ needs.resolve.outputs.release_mode }}"
    assert 'if [[ "${RELEASE_MODE}" == "legacy" ]]' in smoke["run"]
