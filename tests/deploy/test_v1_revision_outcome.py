"""V1 verification states whether it verified the deploy that triggered it.

CI-5b.  When production's public ``/api/status`` ``build.commit`` differed from
the triggering deploy's SHA, the workflow emitted one ``::warning`` ("this
run's verdict is not a verdict on the triggering deploy") and the suites still
concluded green -- so a LATER deploy's green read as verification of this one.

Now the run waits (bounded) for production to run the expected SHA, then
publishes an explicit outcome -- ``verified_revision`` / ``unmeasured`` /
``not_a_deploy_verification`` -- as a step output, a job output and the job
summary.  The publish step's real shell is executed below.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[2]
WORKFLOW = ROOT / ".github" / "workflows" / "v1-authenticated-verification.yml"
WAIT = "Wait for production to run the verified revision (bounded, public /api/status)"
PUBLISH = "Publish whether this run verified the triggering deploy"
VERDICT = "Fail the job on API/lane4/browser verdicts"

A = "a" * 40
B = "b" * 40


def _job() -> dict:
    return yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))["jobs"]["v1-authenticated"]


def _names() -> list[str]:
    return [s.get("name") for s in _job()["steps"]]


def _step(name: str) -> dict:
    return next(s for s in _job()["steps"] if s.get("name") == name)


def _publish(tmp_path: Path, **env: str) -> tuple[int, dict[str, str], str, str]:
    outputs = tmp_path / "out"
    summary = tmp_path / "summary"
    base = {
        "PATH": "/usr/bin:/bin",
        "GITHUB_OUTPUT": str(outputs),
        "GITHUB_STEP_SUMMARY": str(summary),
        "BASELINE_REQUESTED": "false",
        "RUNNING_BEFORE": "",
        "RUNNING_AFTER": "",
    }
    base.update(env)
    proc = subprocess.run(
        ["bash", "-c", _step(PUBLISH)["run"]],
        env=base,
        capture_output=True,
        text=True,
        timeout=30,
    )
    parsed = {}
    if outputs.exists():
        for line in outputs.read_text(encoding="utf-8").splitlines():
            key, _, value = line.partition("=")
            parsed[key] = value
    text = summary.read_text(encoding="utf-8") if summary.exists() else ""
    return proc.returncode, parsed, text, proc.stdout


def test_a_matching_revision_is_verified(tmp_path):
    rc, out, summary, _ = _publish(tmp_path, V1_EXPECTED_SHA=A, RUNNING_BEFORE=A, RUNNING_AFTER=A)
    assert rc == 0
    assert out["outcome"] == "verified_revision"
    assert "verified_revision" in summary


def test_a_different_revision_is_unmeasured_and_says_so_everywhere(tmp_path):
    rc, out, summary, stdout = _publish(tmp_path, V1_EXPECTED_SHA=A, RUNNING_BEFORE=B)
    assert rc == 0, "the outcome is published, never a failure by itself"
    assert out["outcome"] == "unmeasured"
    assert out["reason"].startswith("revision_differs")
    assert "::warning title=V1 did NOT verify the triggering deploy::" in stdout
    assert "UNMEASURED" in summary and "**not** a verification" in summary
    assert B[:12] in out["reason"] and A[:12] in out["reason"]


@pytest.mark.parametrize(
    "env",
    [
        {"V1_EXPECTED_SHA": A, "RUNNING_BEFORE": ""},
        {"V1_EXPECTED_SHA": "", "RUNNING_BEFORE": A},
    ],
)
def test_an_unreadable_revision_is_unmeasured_not_verified(tmp_path, env):
    _rc, out, _summary, _ = _publish(tmp_path, **env)
    assert out["outcome"] == "unmeasured"
    assert out["reason"].startswith("revision_unknown")


def test_a_revision_change_during_the_run_is_unmeasured(tmp_path):
    _rc, out, _summary, _ = _publish(tmp_path, V1_EXPECTED_SHA=A, RUNNING_BEFORE=A, RUNNING_AFTER=B)
    assert out["outcome"] == "unmeasured"
    assert out["reason"].startswith("revision_changed_during_run")


def test_a_baseline_run_makes_no_deploy_claim(tmp_path):
    _rc, out, _summary, _ = _publish(tmp_path, BASELINE_REQUESTED="true")
    assert out["outcome"] == "not_a_deploy_verification"


def test_the_wait_is_bounded_advisory_and_runs_before_the_suites():
    step = _step(WAIT)
    assert step["id"] == "revision"
    assert step["continue-on-error"] is True, "an unconfirmed revision is unmeasured, never red"
    assert "deadline=$(( $(date +%s) + 180 ))" in step["run"]
    assert "--max-time 30" in step["run"]
    assert "running_commit=" in step["run"]
    names = _names()
    assert names.index("Wait for a warm backend (bounded, public endpoints)") < names.index(WAIT)
    for suite in (
        "API verification suite",
        "Browser verification suite (prod-auth Playwright specs)",
        "Trade analysis smoke (2-team analyze + 3-team analyze-multi)",
    ):
        assert names.index(WAIT) < names.index(suite)


def test_the_outcome_is_published_on_every_run_and_as_a_job_output():
    step = _step(PUBLISH)
    assert step["if"] == "${{ always() }}"
    assert "continue-on-error" not in step
    assert "steps.revision.outputs.running_commit" in step["env"]["RUNNING_BEFORE"]
    assert "steps.restart.outputs.backend_commit_after" in step["env"]["RUNNING_AFTER"]
    names = _names()
    assert names.index("Detect a backend restart during the run (public /api/status)") < (
        names.index(PUBLISH)
    )
    assert names.index(PUBLISH) < names.index(VERDICT)
    outputs = _job()["outputs"]
    assert outputs["revision_outcome"] == "${{ steps.verified_revision.outputs.outcome }}"
