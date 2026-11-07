"""The sharded hard gate is only as safe as its wiring.

``scripts/ci_test_shards.py`` proves a sharded run executed every test, but
that proof protects nothing unless the workflows (1) run the identical hard-gate
command on every shard, (2) make the merge/deploy decision depend on a job that
fails whenever any shard failed, was cancelled or was skipped, and (3) never let
an old target tree — one without the shard owner — be "sharded" into eight full
runs with no manifest.  These tests pin that wiring structurally.
"""

from __future__ import annotations

from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]
WORKFLOWS = ROOT / ".github" / "workflows"
HARD_GATE_COMMAND = 'python -m pytest tests/ -x -q --tb=short -m "not livedata"'


def _load(name: str) -> dict:
    return yaml.safe_load((WORKFLOWS / name).read_text(encoding="utf-8"))


def _steps(job: dict) -> list[dict]:
    return [s for s in job.get("steps") or [] if isinstance(s, dict)]


def _runs(job: dict) -> str:
    return "\n".join(s.get("run") or "" for s in _steps(job))


def _hard_gate_jobs(doc: dict) -> dict[str, dict]:
    return {k: j for k, j in doc["jobs"].items() if HARD_GATE_COMMAND in _runs(j)}


# ── PR Validation ───────────────────────────────────────────────────────


def test_pr_validation_runs_the_hard_gate_only_in_the_sharded_backend_matrix():
    doc = _load("pr-validation.yml")
    assert list(_hard_gate_jobs(doc)) == ["backend"]
    backend = doc["jobs"]["backend"]
    assert backend["strategy"]["fail-fast"] is False
    assert "fromJSON(needs.scope.outputs.shards)" in str(backend["strategy"]["matrix"]["shard"])
    step = next(s for s in _steps(backend) if HARD_GATE_COMMAND in (s.get("run") or ""))
    assert "RISKIT_TEST_SHARD" in step["env"] and "RISKIT_TEST_SHARD_MANIFEST" in step["env"]
    upload = next(s for s in _steps(backend) if "upload-artifact" in str(s.get("uses")))
    assert upload.get("if") == "${{ always() }}", "a failed shard's manifest must still upload"


def test_validate_pr_fails_closed_on_any_unsuccessful_dependency():
    doc = _load("pr-validation.yml")
    validate = next(j for j in doc["jobs"].values() if j.get("name") == "Validate PR")
    assert set(validate["needs"]) == {"scope", "checks", "backend"}
    # always(), never !cancelled(): a manually cancelled run must not leave the
    # required check SKIPPED, which GitHub counts as satisfied.
    assert validate["if"] == "${{ always() }}"
    runs = _runs(validate)
    assert "scripts/ci_test_shards.py verify" in runs
    assert 'BACKEND_RESULT}" != "success"' in runs and 'CHECKS_RESULT}" != "success"' in runs


# ── Deploy Production ───────────────────────────────────────────────────


def test_deploy_runs_the_hard_gate_in_one_matrix_job_with_a_serial_fallback():
    doc = _load("deploy.yml")
    assert list(_hard_gate_jobs(doc)) == ["hard-gate"]
    gate = doc["jobs"]["hard-gate"]
    assert gate["strategy"]["fail-fast"] is False
    step = next(s for s in _steps(gate) if HARD_GATE_COMMAND in (s.get("run") or ""))
    shard_env = step["env"]["RISKIT_TEST_SHARD"]
    # On the serial fallback the variable is EMPTY, so the plugin never
    # registers and the command runs exactly as the old serial gate did.
    assert "matrix.shard != 'serial'" in shard_env and "|| ''" in shard_env
    # The tested tree is the resolved target, as in validate.
    assert any(
        "Assert the tested tree is the resolved target" == s.get("name") for s in _steps(gate)
    )


def test_an_operator_can_force_the_serial_gate_on_dispatch():
    doc = _load("deploy.yml")
    flag = doc[True]["workflow_dispatch"]["inputs"]["serial_hard_gate"]
    assert flag["default"] is False and flag["type"] == "boolean"
    plan = doc["jobs"]["test-plan"]
    step = next(s for s in _steps(plan) if s.get("id") == "plan")
    assert step["env"]["FORCE_SERIAL"] == "${{ inputs.serial_hard_gate || false }}"
    assert '"${FORCE_SERIAL}" == "true"' in step["run"]


def test_a_hung_shard_cannot_hold_the_deploy_group_for_hours():
    gate = _load("deploy.yml")["jobs"]["hard-gate"]
    assert gate["timeout-minutes"] == "${{ matrix.shard == 'serial' && 180 || 45 }}"


def test_the_plan_only_shards_a_target_that_carries_the_shard_owner():
    plan_run = _runs(_load("deploy.yml")["jobs"]["test-plan"])
    assert '"${RELEASE_MODE}" == "artifact"' in plan_run
    assert (
        "-f scripts/ci_test_shards.py" in plan_run and "-f config/ci/test_shards.json" in plan_run
    )
    assert 'shards=["serial"]' in plan_run


def test_deploy_waits_on_a_completeness_job_that_fails_closed():
    doc = _load("deploy.yml")
    assert "hard-gate-complete" in doc["jobs"]["deploy"]["needs"]
    complete = doc["jobs"]["hard-gate-complete"]
    assert set(complete["needs"]) >= {"test-plan", "hard-gate"}
    # No job-level `if`: a failed or cancelled shard SKIPS this job, and a
    # skipped need skips `deploy` — fail-closed.  (An `if: always()` here would
    # be harmless for safety but breaks the production-deploy concurrency rule.)
    assert "if" not in complete
    runs = _runs(complete)
    assert "scripts/ci_test_shards.py verify" in runs
    assert 'GATE_RESULT}" != "success"' in runs and 'PLAN_RESULT}" != "success"' in runs
    # deploy has no if: of its own, so the implicit success() requires every
    # need — hard-gate-complete included — to have succeeded.
    assert "if" not in doc["jobs"]["deploy"]


def test_validate_no_longer_runs_the_hard_gate_but_keeps_the_advisory_live_tier():
    validate = _load("deploy.yml")["jobs"]["validate"]
    assert HARD_GATE_COMMAND not in _runs(validate)
    live = next(s for s in _steps(validate) if "-m livedata" in (s.get("run") or ""))
    assert live.get("continue-on-error") is True
