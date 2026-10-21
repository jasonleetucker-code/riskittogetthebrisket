"""The V1 failure classifier is wired in as a REPORT, never as a gate.

``scripts/v1_failure_classifier.py`` explains a red run; it must not be able to
make one green, make one red, or be the reason a required check is skipped.
These tests pin that shape in ``v1-authenticated-verification.yml`` so a later
edit cannot quietly promote the classifier to a gate (a release-policy change
that needs the owner), and pin that nothing secret reaches it.
"""

from __future__ import annotations

import re
from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]
WORKFLOW = REPO_ROOT / ".github" / "workflows" / "v1-authenticated-verification.yml"
VERDICT_STEP = "Fail the job on API/lane4/browser verdicts"
CLASSIFY_STEP = "Classify failures (report-only, never a gate)"


def _doc() -> dict:
    return yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))


def _steps() -> list[dict]:
    return _doc()["jobs"]["v1-authenticated"]["steps"]


def _step(name: str) -> dict:
    matches = [s for s in _steps() if s.get("name") == name]
    assert len(matches) == 1, f"expected exactly one step named {name!r}"
    return matches[0]


def test_the_classifier_step_is_continue_on_error_and_always_runs():
    step = _step(CLASSIFY_STEP)
    assert step["continue-on-error"] is True
    assert "always()" in str(step["if"])
    assert step["id"] == "classify"


def test_the_classifier_runs_before_the_verdict_step_so_a_failed_run_still_gets_reported():
    names = [s.get("name") for s in _steps()]
    assert names.index(CLASSIFY_STEP) < names.index(VERDICT_STEP)


def test_no_step_reads_the_classifiers_output_so_it_cannot_gate_anything():
    for step in _steps():
        if step.get("id") == "classify":
            continue
        blob = yaml.safe_dump({k: v for k, v in step.items() if k != "name"})
        assert (
            "steps.classify" not in blob
        ), f"{step.get('name')!r} reads the classifier: that would make it a gate"
    job = _doc()["jobs"]["v1-authenticated"]
    assert "steps.classify" not in str(job.get("if", ""))
    assert "steps.classify" not in str(job.get("outputs", ""))


def test_the_classifier_receives_no_secret():
    step = _step(CLASSIFY_STEP)
    for key, value in (step.get("env") or {}).items():
        assert "secrets." not in str(value), key
        assert key.startswith("V1_"), key
    run = step["run"]
    assert "secrets." not in run
    assert "--probe-login" in run and "--probe-pre-revoke" in run


def test_the_classification_is_uploaded_with_the_other_sanitized_reports():
    upload = [s for s in _steps() if s.get("name") == "Upload the reports"][0]
    paths = upload["with"]["path"].split()
    assert "v1-failure-classification.json" in paths
    # The pre-existing S3 rule: nothing that can carry production data.
    assert not [
        p
        for p in paths
        if re.search(r"test-results|trace|\.zip|\.webm|\.png|video|screenshot", p, re.I)
    ]


def test_the_run_is_named_for_the_deploy_it_verifies():
    name = _doc()["run-name"]
    assert "workflow_run.head_sha" in name
    assert "workflow_run.id" in name


def test_a_revision_mismatch_is_reported_as_a_warning_and_does_not_fail_the_warm_step():
    warm = _step("Wait for a warm backend (bounded, public endpoints)")
    assert warm["continue-on-error"] is True
    script = warm["run"]
    assert "Production revision differs from the verified revision" in script
    start = script.index("Production revision differs")
    window = script[start - 400 : start + 400]
    assert "::warning" in window
    assert "sys.exit" not in script[script.index("commit and expected and commit != expected") :]


def test_the_restart_step_publishes_the_restart_instant_the_classifier_attributes_with():
    step = _step("Detect a backend restart during the run (public /api/status)")
    assert step["id"] == "restart"
    assert step["continue-on-error"] is True
    assert "backend_started_after" in step["run"] and "backend_commit_after" in step["run"]
    classify_env = _step(CLASSIFY_STEP)["env"]
    assert "steps.restart.outputs.backend_started_after" in classify_env["V1_STARTED_AFTER"]
    assert "steps.warm.outputs.backend_started_at" in classify_env["V1_STARTED_BEFORE"]


def test_the_required_gates_are_untouched():
    """The verdict and security steps keep exactly their pre-classifier contract."""
    verdict = _step(VERDICT_STEP)
    assert "if" not in verdict and "continue-on-error" not in verdict
    assert 'exit "$code"' in verdict["run"]
    assert "Security acceptance" in verdict["run"]
    security = _step("Security acceptance summary (incident 2026-10-08)")
    assert "continue-on-error" not in security
    doc = _doc()
    assert "concurrency" not in doc
    job = doc["jobs"]["v1-authenticated"]
    assert job["concurrency"] == {"group": "production-deploy", "cancel-in-progress": False}
    assert job["timeout-minutes"] == 50
