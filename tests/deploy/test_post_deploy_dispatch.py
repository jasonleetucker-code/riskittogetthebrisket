"""Bot-started deploys dispatch their own post-deploy workflows (STAB-10).

GitHub creates no ``workflow_run`` run for a run started by GITHUB_TOKEN, so
scheduled-refresh's data deploys (triggering actor ``github-actions[bot]``;
measured runs 44315967974 / 44411720980 / 44455009771) got neither the data
delivery shadow nor V1 verification.  deploy.yml now dispatches both for such
runs only.  These tests pin the conditions (never for a human-started deploy,
which already gets ``workflow_run``), the minimal token, the inputs that tie the
dispatched runs to THIS deploy, and that a failed dispatch cannot turn a shipped
deploy red.
"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[2]
WORKFLOWS = ROOT / ".github" / "workflows"
BOT = "github.triggering_actor == 'github-actions[bot]'"


def _load(name: str) -> dict:
    return yaml.safe_load((WORKFLOWS / name).read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def deploy() -> dict:
    return _load("deploy.yml")


@pytest.fixture(scope="module")
def v1() -> dict:
    return _load("v1-authenticated-verification.yml")


@pytest.mark.parametrize("job", ["dispatch-data-delivery-shadow", "dispatch-v1-verification"])
def test_dispatch_jobs_are_bot_only_minimal_and_cannot_fail_the_deploy(deploy, job):
    spec = deploy["jobs"][job]
    assert BOT in spec["if"], "a human-started deploy already gets workflow_run: never twice"
    assert spec["permissions"] == {"actions": "write"}
    assert "environment" not in spec, "no production secrets in a dispatch job"
    (step,) = spec["steps"]
    assert step["continue-on-error"] is True
    assert "::error title=Post-deploy dispatch failed::" in step["run"]
    assert step["env"]["GH_TOKEN"] == "${{ github.token }}"
    assert step["env"]["DEPLOY_RUN_ID"] == "${{ github.run_id }}"
    assert "${{ inputs." not in step["run"] and "${{ needs." not in step["run"]


def test_shadow_is_dispatched_after_every_gate_and_beside_the_deploy(deploy):
    spec = deploy["jobs"]["dispatch-data-delivery-shadow"]
    assert set(spec["needs"]) == {
        "resolve",
        "validate",
        "test-plan",
        "hard-gate",
        "hard-gate-complete",
    }
    assert "deploy" not in spec["needs"], "the gate wall-clock must not absorb the box deploy"
    # It must also run when a gate FAILED (that is shadow evidence), never on cancel.
    assert spec["if"].startswith("${{ !cancelled() && ")
    run = spec["steps"][0]["run"]
    assert (
        'gh workflow run data-delivery-shadow.yml --ref main -f deploy_run_id="${DEPLOY_RUN_ID}"'
        in run
    )


def test_v1_is_dispatched_only_after_a_successful_main_deploy(deploy):
    spec = deploy["jobs"]["dispatch-v1-verification"]
    assert spec["needs"] == ["resolve", "deploy"]
    cond = spec["if"]
    # No status function: success() is implied, so a failed deploy dispatches nothing.
    for fn in ("always()", "cancelled()", "failure()"):
        assert fn not in cond
    assert "github.ref == 'refs/heads/main'" in cond
    step = spec["steps"][0]
    assert step["env"]["DEPLOY_SHA"] == "${{ needs.resolve.outputs.sha }}"
    run = step["run"]
    assert "gh workflow run v1-authenticated-verification.yml --ref main" in run
    for flag in (
        "-f suite=browser",
        '-f deploy_run_id="${DEPLOY_RUN_ID}"',
        '-f deploy_sha="${DEPLOY_SHA}"',
    ):
        assert flag in run


def test_the_dispatched_workflows_accept_what_deploy_sends(v1):
    shadow_inputs = _load("data-delivery-shadow.yml")[True]["workflow_dispatch"]["inputs"]
    assert "deploy_run_id" in shadow_inputs
    inputs = v1[True]["workflow_dispatch"]["inputs"]
    assert "browser" in inputs["suite"]["options"]
    for name in ("deploy_run_id", "deploy_sha"):
        assert inputs[name]["type"] == "string"
        assert inputs[name].get("required", False) is False
        assert inputs[name]["default"] == ""


def test_v1_dispatched_run_verifies_this_deploys_commit(v1):
    job = v1["jobs"]["v1-authenticated"]
    steps = {s["name"]: s for s in job["steps"]}
    ref = steps["Checkout"]["with"]["ref"]
    expected = steps["Resolve production origin"]["env"]["EXPECTED_SOURCE_SHA"]
    assert ref == expected
    assert "inputs.deploy_sha" in ref
    env = steps["Resolve production origin"]["env"]
    assert "inputs.deploy_run_id" in env["DEPLOY_RUN_ID"]
    assert "needs.wait-for-deploy.outputs.completed_at" in env["DEPLOY_COMPLETED_AT"]


def test_v1_waits_for_the_deploy_run_before_entering_the_deploy_group(v1):
    wait = v1["jobs"]["wait-for-deploy"]
    assert "concurrency" not in wait, "the wait must not queue in production-deploy"
    assert wait["permissions"] == {"actions": "read"}
    assert "inputs.deploy_run_id != ''" in wait["if"]
    run = wait["steps"][0]["run"]
    assert '"${status}" == "completed"' in run
    assert '".github/workflows/deploy.yml"' in run and '"main"' in run
    job = v1["jobs"]["v1-authenticated"]
    assert job["needs"] == "wait-for-deploy"
    assert job["concurrency"] == {"group": "production-deploy", "cancel-in-progress": False}
    cond = job["if"]
    assert cond.startswith("${{ !cancelled() && (")
    # A deploy-dispatched run proceeds only on that deploy's success; a plain
    # manual dispatch and the workflow_run path keep their old gates.
    assert "needs.wait-for-deploy.outputs.conclusion == 'success'" in cond
    assert "inputs.deploy_run_id == ''" in cond
    assert "github.event.workflow_run.conclusion == 'success'" in cond
    assert "github.event.workflow_run.head_branch == 'main'" in cond
