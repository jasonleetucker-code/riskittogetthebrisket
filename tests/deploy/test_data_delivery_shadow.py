"""The data-only delivery SHADOW: the gate set, the bookkeeping and the workflow.

Audit-remediation Task 3 (owner directive 2026-11-18).  Shadow mode only: the
workflow records what a data-only fast path would have done beside the full
Deploy Production verdict and decides nothing.  These tests pin that it CANNOT
decide anything (no secrets, no box, no deploy, no shared concurrency group, no
hook into deploy.yml), that its gate set mirrors steps the full pipeline really
runs, and that every comparison outcome is computed the way the design document
(docs/ops/DATA_ONLY_DELIVERY_DESIGN_2026-11-18.md) defines it.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys
from unittest import mock

import pytest
import yaml

from scripts import data_delivery_gate as gate
from scripts import data_delivery_shadow as shadow
from scripts import resolve_deploy_ref

ROOT = Path(__file__).resolve().parents[2]
WORKFLOW = ROOT / ".github" / "workflows" / "data-delivery-shadow.yml"
DEPLOY = ROOT / ".github" / "workflows" / "deploy.yml"
DESIGN = ROOT / "docs" / "ops" / "DATA_ONLY_DELIVERY_DESIGN_2026-11-18.md"
SHA_A, SHA_B, SHA_C = "a" * 40, "b" * 40, "c" * 40


def _load(path: Path) -> dict:
    return yaml.safe_load(path.read_text(encoding="utf-8")) or {}


def _on(doc: dict) -> dict:
    return doc.get(True, doc.get("on")) or {}


def _run_text(doc: dict) -> str:
    return "\n".join(
        str(step.get("run") or "")
        for job in (doc.get("jobs") or {}).values()
        for step in job.get("steps") or []
    )


# ── the workflow cannot decide anything ────────────────────────────────────


def test_the_shadow_observes_every_deploy_run_and_nothing_else():
    on = _on(_load(WORKFLOW))
    assert set(on) == {"workflow_run", "workflow_dispatch"}
    assert on["workflow_run"]["workflows"] == [_load(DEPLOY)["name"]] == ["Deploy Production"]
    assert on["workflow_run"]["types"] == ["completed"]


def test_the_shadow_holds_no_secret_and_writes_nothing():
    doc = _load(WORKFLOW)
    text = WORKFLOW.read_text(encoding="utf-8")
    assert "secrets." not in text
    assert doc["permissions"] == {"contents": "read", "actions": "read"}
    for job in doc["jobs"].values():
        assert "permissions" not in job, "a job may not widen the read-only token"
        assert "environment" not in job, "the production environment carries the box secrets"
    run = _run_text(doc)
    for forbidden in (
        "ssh ",
        "scp ",
        "deploy.sh",
        "gh workflow run",
        "gh api",
        "git push",
        "curl ",
        "PROD_PUBLIC_URL",
        "DEPLOY_HOST",
    ):
        assert forbidden not in run, f"the shadow must not run {forbidden!r}"


def test_the_shadow_never_queues_in_the_production_deploy_group():
    doc = _load(WORKFLOW)
    group = str(doc["concurrency"]["group"])
    assert group.startswith("data-delivery-shadow-")
    code_lines = [
        line
        for line in WORKFLOW.read_text(encoding="utf-8").splitlines()
        if not line.lstrip().startswith("#")
    ]
    assert not [line for line in code_lines if "production-deploy" in line]
    for job in doc["jobs"].values():
        assert "concurrency" not in job


def test_deploy_yml_has_no_hook_into_the_shadow():
    """The strict L3 file is untouched: nothing in it calls the shadow tooling."""
    text = DEPLOY.read_text(encoding="utf-8")
    for name in (
        "classify_deploy_delta",
        "data_delivery_gate",
        "data_delivery_shadow",
        "data-delivery",
    ):
        assert name not in text


def test_only_the_gate_step_may_fail_without_failing_the_shadow():
    doc = _load(WORKFLOW)
    (job,) = doc["jobs"].values()
    assert "continue-on-error" not in job, "a broken shadow must read red, not green"
    advisory = [s["name"] for s in job["steps"] if s.get("continue-on-error")]
    assert advisory == ["Run the data gate set (shadow, decides nothing)"]


def test_the_fast_path_only_runs_on_a_data_only_classification():
    (job,) = _load(WORKFLOW)["jobs"].values()
    by_name = {s["name"]: s for s in job["steps"]}
    for name in (
        "Check out the deploy target tree (DATA_ONLY only)",
        "Install the target's locked dependencies (DATA_ONLY only)",
        "Run the data gate set (shadow, decides nothing)",
    ):
        assert by_name[name]["if"] == "${{ steps.classify.outputs.classification == 'DATA_ONLY' }}"


def test_the_deploy_run_id_reaches_shell_only_as_validated_env():
    text = WORKFLOW.read_text(encoding="utf-8")
    run = _run_text(_load(WORKFLOW))
    assert "${{ inputs." not in run and "${{ github.event" not in run
    assert '[[ "${DEPLOY_RUN_ID}" =~ ^[0-9]+$ ]]' in text


def test_the_design_document_exists_and_keeps_activation_blocked():
    text = DESIGN.read_text(encoding="utf-8")
    assert "BLOCKED — OWNER DECISION" in text
    for name in ("classify_deploy_delta.py", "data_delivery_gate.py", "data-delivery-shadow.yml"):
        assert name in text


# ── the gate set mirrors the full pipeline ─────────────────────────────────


def test_the_gate_set_is_the_documented_one():
    gates = gate.default_gates("python")
    assert [(g.name, g.blocking) for g in gates] == [
        ("runtime_import", True),
        ("contract_full_lane", True),
        ("tracked_data_privacy", True),
        ("source_health", False),
        ("livedata_tests", False),
    ]


def test_every_mirrored_deploy_step_still_exists():
    deploy = DEPLOY.read_text(encoding="utf-8")
    for g in gate.default_gates("python"):
        if g.mirrors.startswith("deploy.yml::validate::"):
            step = g.mirrors.split("::", 2)[2]
            assert f"- name: {step}" in deploy, f"{g.name} mirrors a step deploy.yml no longer has"


def test_the_contract_gate_runs_the_full_lane_command_the_deploy_runs():
    deploy = DEPLOY.read_text(encoding="utf-8")
    assert "python scripts/validate_api_contract.py --repo . --lane full" in deploy
    contract = next(g for g in gate.default_gates("python") if g.name == "contract_full_lane")
    assert list(contract.argv[1:]) == [
        "scripts/validate_api_contract.py",
        "--repo",
        ".",
        "--lane",
        "full",
    ]


def test_every_gate_input_exists_in_this_tree():
    for g in gate.default_gates("python"):
        for arg in g.argv[1:]:
            if arg.startswith(("scripts/", "tests/")) and arg != "tests/":
                assert (ROOT / arg).exists(), f"{g.name} names a missing file {arg}"


def _py(code: str) -> tuple[str, ...]:
    return (sys.executable, "-c", code)


def test_a_failing_blocking_gate_refuses_and_an_advisory_one_does_not(tmp_path: Path):
    gates = (
        gate.Gate("ok", True, _py("print('fine')"), "m", 60),
        gate.Gate("bad_advisory", False, _py("import sys; sys.exit(3)"), "m", 60),
    )
    receipt = gate.run_gates(gates, tmp_path)
    assert receipt["wouldShip"] is True
    assert receipt["advisoryFailures"] == ["bad_advisory"]

    gates += (gate.Gate("bad_blocking", True, _py("import sys; sys.exit(1)"), "m", 60),)
    receipt = gate.run_gates(gates, tmp_path)
    assert receipt["wouldShip"] is False
    assert receipt["blockingFailures"] == ["bad_blocking"]
    assert [g["status"] for g in receipt["gates"]] == ["pass", "fail", "fail"]


def test_a_gate_that_times_out_or_cannot_start_refuses(tmp_path: Path):
    receipt = gate.run_gates(
        (gate.Gate("slow", True, _py("import time; time.sleep(30)"), "m", 1),), tmp_path
    )
    assert receipt["gates"][0]["status"] == "timeout"
    assert receipt["wouldShip"] is False
    receipt = gate.run_gates(
        (gate.Gate("missing", True, (str(tmp_path / "no-such-binary"),), "m", 5),), tmp_path
    )
    assert receipt["gates"][0]["status"] == "error"
    assert receipt["wouldShip"] is False


def test_no_blocking_gate_is_not_a_pass(tmp_path: Path):
    receipt = gate.run_gates((gate.Gate("adv", False, _py("pass"), "m", 60),), tmp_path)
    assert receipt["wouldShip"] is False


def test_gates_run_in_the_target_tree_with_the_pipeline_env(tmp_path: Path):
    probe = _py(
        "import os, pathlib; print(pathlib.Path.cwd().name, os.environ['UPTIME_CHECK_ENABLED'])"
    )
    receipt = gate.run_gates(
        (gate.Gate("probe", True, probe, "m", 60, {"UPTIME_CHECK_ENABLED": "0"}),), tmp_path
    )
    assert receipt["gates"][0]["outputTail"] == [f"{tmp_path.name} 0"]


# ── which commit a deploy run deployed ─────────────────────────────────────


def test_the_resolved_line_is_what_resolve_deploy_ref_prints(tmp_path: Path, capsys):
    env = {
        **os.environ,
        "GIT_AUTHOR_NAME": "t",
        "GIT_AUTHOR_EMAIL": "t@example.invalid",
        "GIT_COMMITTER_NAME": "t",
        "GIT_COMMITTER_EMAIL": "t@example.invalid",
        "GIT_CONFIG_GLOBAL": os.devnull,
        "GIT_CONFIG_NOSYSTEM": "1",
    }
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True, env=env)
    subprocess.run(
        ["git", "-C", str(tmp_path), "commit", "-q", "--allow-empty", "-m", "c"],
        check=True,
        env=env,
    )
    sha = subprocess.run(
        ["git", "-C", str(tmp_path), "rev-parse", "HEAD"],
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip()
    assert resolve_deploy_ref.main(["--default", sha, "--repo", str(tmp_path)]) == 0
    line = capsys.readouterr().out
    match = shadow.RESOLVED_LINE.search(f"2026-11-18T10:51:20.1Z {line}")
    assert match and match.groups() == (sha, "default")


def _job(name: str, conclusion: str | None, job_id: int = 1, **extra) -> dict:
    return {"id": job_id, "name": name, "conclusion": conclusion, **extra}


def test_a_dispatch_target_comes_from_the_resolve_log_not_head_sha():
    run = {"event": "workflow_dispatch", "head_sha": SHA_A}
    jobs = [_job(shadow.RESOLVE_JOB, "success", 7)]
    log = f"2026-11-18T10:51:20.1Z resolved deploy target: {SHA_B} (commit; requested '{SHA_B}')"
    assert shadow.deployed_target(run, jobs, lambda path: log) == (SHA_B, "resolve_job_log:commit")


def test_an_unreadable_dispatch_target_is_unknown_never_head_sha():
    run = {"event": "workflow_dispatch", "head_sha": SHA_A}
    jobs = [_job(shadow.RESOLVE_JOB, "success", 7)]

    def boom(path: str) -> str:
        raise RuntimeError("log expired")

    sha, source = shadow.deployed_target(run, jobs, boom)
    assert sha is None and source.startswith("dispatch_target_unreadable")
    assert shadow.deployed_target(run, [], boom) == (None, "resolve_job_did_not_succeed")


def test_a_push_target_is_its_head_sha_even_without_a_log():
    run = {"event": "push", "head_sha": SHA_A}
    assert (
        shadow.deployed_target(run, [_job(shadow.RESOLVE_JOB, "success")], lambda p: "")[0] == SHA_A
    )
    assert shadow.deployed_target(run, [], lambda p: "")[0] == SHA_A


def test_the_base_is_the_newest_success_created_before_the_observed_run():
    observed = {"id": 5, "created_at": "2026-11-18T10:00:00Z"}
    runs = [
        {"id": 5, "conclusion": "success", "created_at": "2026-11-18T10:00:00Z"},
        {"id": 6, "conclusion": "success", "created_at": "2026-11-18T11:00:00Z"},
        {"id": 3, "conclusion": "success", "created_at": "2026-11-18T08:00:00Z"},
        {"id": 4, "conclusion": "success", "created_at": "2026-11-18T09:00:00Z"},
        {"id": 2, "conclusion": "failure", "created_at": "2026-11-18T09:30:00Z"},
    ]
    found = shadow.find_base_run(lambda path: {"workflow_runs": runs}, observed)
    assert found["id"] == 4


def _fake_github(runs: dict, jobs: dict, logs: dict):
    def get_json(path: str):
        if path.startswith("actions/workflows/deploy.yml/runs"):
            return {"workflow_runs": list(runs.values())}
        if path.startswith("actions/runs/") and "/jobs" in path:
            return {"jobs": jobs[int(path.split("/")[2])]}
        return runs[int(path.split("/")[2])]

    return get_json, lambda path: logs[int(path.split("/")[2])]


def test_resolve_inputs_end_to_end_on_fakes():
    runs = {
        10: {
            "id": 10,
            "path": shadow.DEPLOY_WORKFLOW_PATH,
            "event": "workflow_dispatch",
            "head_sha": SHA_C,
            "conclusion": "failure",
            "created_at": "2026-11-18T10:00:00Z",
        },
        9: {
            "id": 9,
            "path": shadow.DEPLOY_WORKFLOW_PATH,
            "event": "push",
            "head_sha": SHA_A,
            "conclusion": "success",
            "created_at": "2026-11-18T08:00:00Z",
        },
    }
    jobs = {
        10: [
            _job(shadow.RESOLVE_JOB, "success", 100),
            _job(
                shadow.VALIDATE_JOB,
                "failure",
                101,
                steps=[
                    {
                        "name": "API data contract check (FULL lane — blocking)",
                        "conclusion": "failure",
                    }
                ],
            ),
        ],
        9: [_job(shadow.RESOLVE_JOB, "success", 90)],
    }
    logs = {
        100: f"2026-11-18T10:51:20.1Z resolved deploy target: {SHA_C} (default; requested '<default>')",
        90: "",
    }
    get_json, get_text = _fake_github(runs, jobs, logs)
    inputs = shadow.resolve_inputs(get_json, get_text, 10)
    assert inputs["errors"] == []
    assert inputs["target"] == {"sha": SHA_C, "source": "resolve_job_log:default"}
    assert inputs["base"]["sha"] == SHA_A and inputs["base"]["runId"] == 9
    assert inputs["observedJobs"][1]["failedSteps"] == [
        "API data contract check (FULL lane — blocking)"
    ]


def test_resolve_refuses_a_run_of_another_workflow():
    get_json = lambda path: {"id": 1, "path": ".github/workflows/e2e.yml"}  # noqa: E731
    inputs = shadow.resolve_inputs(get_json, lambda p: "", 1)
    assert inputs["errors"] == ["not_a_deploy_production_run"]


# ── the full verdict and the comparison ────────────────────────────────────


def _brief(name: str, conclusion: str | None, failed_steps=()) -> dict:
    return {
        "name": name,
        "conclusion": conclusion,
        "failedSteps": list(failed_steps),
        "startedAt": "2026-11-18T10:00:00Z",
        "completedAt": "2026-11-18T10:10:00Z",
    }


PASSING = [
    _brief(shadow.RESOLVE_JOB, "success"),
    _brief(shadow.VALIDATE_JOB, "success"),
    _brief(shadow.PLAN_JOB, "success"),
    _brief("Hard gate (1/2)", "success"),
    _brief("Hard gate (2/2)", "success"),
    _brief(shadow.COMPLETE_JOB, "success"),
    _brief(shadow.DEPLOY_JOB, "success"),
]


def test_full_verdict_pass_fail_unknown():
    assert shadow.full_verdict(PASSING)["preDeploy"] == "pass"
    shard_failed = [
        j
        if j["name"] != "Hard gate (2/2)"
        else _brief("Hard gate (2/2)", "failure", ["Run unit tests (hard gate — pure logic)"])
        for j in PASSING
    ]
    shard_failed = [
        j if j["name"] != shadow.COMPLETE_JOB else _brief(shadow.COMPLETE_JOB, "skipped")
        for j in shard_failed
    ]
    verdict = shadow.full_verdict(shard_failed)
    assert verdict["preDeploy"] == "fail"
    assert verdict["failedSteps"] == ["Hard gate (2/2)::Run unit tests (hard gate — pure logic)"]
    cancelled = [
        j if j["name"] != shadow.COMPLETE_JOB else _brief(shadow.COMPLETE_JOB, "cancelled")
        for j in PASSING
    ]
    assert shadow.full_verdict(cancelled)["preDeploy"] == "unknown"
    # A runner that could not be prepared judged neither the code nor the data.
    infra = [
        _brief(j["name"], "failure", ["Install tesseract-ocr (screenshot import OCR tests)"])
        if j["name"].startswith("Hard gate (")
        else j
        for j in PASSING
    ]
    verdict = shadow.full_verdict(infra)
    assert (verdict["preDeploy"], verdict["failureKind"]) == ("unknown", "infrastructure")
    # ...but a failed job with no failed step named (a timeout) is a gate failure.
    unnamed = [_brief(j["name"], "failure") if j["name"] == "Hard gate (1/2)" else j for j in infra]
    verdict = shadow.full_verdict(unnamed)
    assert (verdict["preDeploy"], verdict["failureKind"]) == ("fail", "gate")
    # A failed deploy JOB is box-side: it is reported, not a pre-deploy verdict.
    deploy_failed = [
        j if j["name"] != shadow.DEPLOY_JOB else _brief(shadow.DEPLOY_JOB, "failure")
        for j in PASSING
    ]
    verdict = shadow.full_verdict(deploy_failed)
    assert verdict["preDeploy"] == "pass" and verdict["deployJob"] == "failure"


def _inputs(jobs) -> dict:
    return {
        "deployRunId": 10,
        "observedRun": {
            "event": "push",
            "created_at": "2026-11-18T10:00:00Z",
            "run_started_at": "2026-11-18T10:00:00Z",
            "conclusion": "success",
        },
        "observedJobs": jobs,
        "errors": [],
    }


def _classification(cls: str) -> dict:
    return {
        "classification": cls,
        "reasons": [],
        "target": {"sha": SHA_B},
        "base": {"sha": SHA_A, "source": "t"},
        "codePathGroups": {},
        "rulesDigest": "r",
    }


FAILING = [
    j if j["name"] != shadow.VALIDATE_JOB else _brief(shadow.VALIDATE_JOB, "failure")
    for j in PASSING
]


@pytest.mark.parametrize(
    ("cls", "jobs", "would_ship", "outcome"),
    [
        ("DATA_ONLY", PASSING, True, shadow.AGREE_SHIP),
        ("DATA_ONLY", FAILING, False, shadow.AGREE_REFUSE),
        ("DATA_ONLY", FAILING, True, shadow.UNSAFE_DISAGREEMENT),
        ("DATA_ONLY", PASSING, False, shadow.CONSERVATIVE_DISAGREEMENT),
        ("DATA_ONLY", [], True, shadow.NO_FULL_VERDICT),
        ("DATA_ONLY", PASSING, None, shadow.FAST_PATH_NOT_RUN),
        ("CODE", PASSING, None, shadow.NOT_APPLICABLE),
    ],
)
def test_compare_outcomes(cls, jobs, would_ship, outcome):
    gates = None if would_ship is None else {"wouldShip": would_ship, "gates": [], "seconds": {}}
    verdict = shadow.compare(_inputs(jobs), _classification(cls), gates, None)
    assert verdict["outcome"] == outcome
    assert verdict["decidesNothing"] is True


def test_the_summary_says_it_decides_nothing():
    verdict = shadow.compare(
        _inputs(PASSING), _classification("DATA_ONLY"), {"wouldShip": True}, None
    )
    summary = shadow.render_summary(verdict)
    assert "decides nothing" in summary and "BLOCKED" in summary


def test_timing_counts_pre_deploy_runner_minutes_only():
    timing = shadow.full_timing(_inputs(PASSING)["observedRun"], PASSING)
    assert (
        timing["preDeployRunnerMinutes"] == 60.0
    )  # six 10-minute gate jobs; the deploy job excluded
    assert timing["preDeployWallMinutes"] == 10.0


def _verdict(outcome: str, created: str, runner: float = 120.0, shadow_min: float = 4.0) -> dict:
    return {
        "schema": shadow.SCHEMA,
        "classification": "DATA_ONLY",
        "outcome": outcome,
        "deployCreatedAt": created,
        "deployRunId": 1,
        "rulesDigest": "r",
        "fullVerdict": {"failedSteps": []},
        "fastPath": {},
        "timing": {"preDeployRunnerMinutes": runner, "shadowJobWallMinutes": shadow_min},
    }


def test_aggregate_meets_the_evidence_floor_only_without_unsafe_disagreements(tmp_path: Path):
    days = [f"2026-11-{d:02d}T10:00:00Z" for d in range(1, 31)]
    verdicts = [_verdict(shadow.AGREE_SHIP, day) for day in days] + [
        _verdict(shadow.AGREE_SHIP, day.replace("T10", "T12")) for day in days[:5]
    ]
    report = shadow.aggregate(verdicts)
    assert report["activationEvidenceMet"] is True
    assert report["runnerMinutesSavedOnAgreedShips"] == round(116.0 * len(verdicts), 1)
    assert report["activationDecision"].startswith("BLOCKED")

    report = shadow.aggregate(verdicts + [_verdict(shadow.UNSAFE_DISAGREEMENT, days[-1])])
    assert report["activationEvidenceMet"] is False
    assert report["activationEvidenceCriteria"]["zeroUnsafeDisagreements"] is False

    for i, v in enumerate(verdicts[:3]):
        (tmp_path / f"v{i}.json").write_text(json.dumps(v), encoding="utf-8")
    (tmp_path / "not-a-verdict.json").write_text("{}", encoding="utf-8")
    assert len(shadow._load_verdicts(tmp_path)) == 3


def test_github_reader_refuses_a_bad_slug_or_no_token():
    with pytest.raises(ValueError):
        shadow.GitHubReader("not a slug", "t")
    with pytest.raises(ValueError):
        shadow.GitHubReader("owner/name", "")


# ── review fixes: gate-set budget, incremental receipt, anchored log line ───
def test_gate_set_budget_fits_the_job_limit_with_margin():
    job = yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))["jobs"]["shadow"]
    assert job["timeout-minutes"] * 60 >= gate.GATE_SET_BUDGET_SECONDS + 15 * 60
    steps = {s.get("id"): s for s in job["steps"]}
    assert steps["gates"]["timeout-minutes"] * 60 > gate.GATE_SET_BUDGET_SECONDS
    # the per-gate timeouts alone would NOT fit, which is why the deadline exists
    assert sum(g.timeout_seconds for g in gate.default_gates()) > job["timeout-minutes"] * 60 - 900


def test_budget_exhaustion_skips_later_gates_and_refuses(tmp_path: Path):
    gates = (
        gate.Gate("first", True, _py("import time; time.sleep(60)"), "m", 600),
        gate.Gate("second", True, _py("print('never runs')"), "m", 600),
        gate.Gate("adv", False, _py("print('never runs')"), "m", 600),
    )
    receipt = gate.run_gates(gates, tmp_path, budget_seconds=31)
    statuses = {g["name"]: g["status"] for g in receipt["gates"]}
    assert statuses["first"] == "timeout"  # capped to the 31s budget, not 600s
    assert statuses["second"] == "skipped_budget"
    assert statuses["adv"] == "skipped_budget"
    assert receipt["wouldShip"] is False
    assert "second" in receipt["blockingFailures"]


def test_receipt_is_written_after_every_gate_and_partial_never_ships(tmp_path: Path):
    path = tmp_path / "out" / "gates.json"
    seen: list[dict] = []
    real = gate._write_receipt

    def spy(p, receipt):
        real(p, receipt)
        seen.append(json.loads(p.read_text(encoding="utf-8")))

    gates = (
        gate.Gate("a", True, _py("print('a')"), "m", 60),
        gate.Gate("b", True, _py("print('b')"), "m", 60),
    )
    with mock.patch.object(gate, "_write_receipt", spy):
        final = gate.run_gates(gates, tmp_path, receipt_path=path)
    assert [len(r["gates"]) for r in seen] == [1, 2]
    assert seen[0]["complete"] is False and seen[0]["wouldShip"] is False
    assert seen[1]["complete"] is True and seen[1]["wouldShip"] is True
    assert final["complete"] is True


def test_resolved_line_is_anchored_against_a_spoofing_branch_name():
    spoof = f"resolved deploy target: {SHA_A} (commit; requested 'x')"
    log = (
        f"2026-11-18T10:51:19.0Z REQUESTED: feature/{spoof}\n"
        f"2026-11-18T10:51:19.1Z echo requested feature/{spoof}\n"
    )
    assert shadow.RESOLVED_LINE.search(log) is None
    run = {"event": "workflow_dispatch", "head_sha": SHA_C}
    jobs = [_job(shadow.RESOLVE_JOB, "success", 7)]
    assert shadow.deployed_target(run, jobs, lambda path: log)[0] is None


def test_the_real_line_wins_over_an_earlier_full_line_spoof():
    real = f"resolved deploy target: {SHA_B} (branch; requested 'main')"
    fake = f"resolved deploy target: {SHA_A} (commit; requested 'x')"
    log = f"2026-11-18T10:51:19.0Z {fake}\n2026-11-18T10:51:20.1Z {real}\n"
    run = {"event": "workflow_dispatch", "head_sha": SHA_C}
    jobs = [_job(shadow.RESOLVE_JOB, "success", 7)]
    assert shadow.deployed_target(run, jobs, lambda path: log) == (SHA_B, "resolve_job_log:branch")
