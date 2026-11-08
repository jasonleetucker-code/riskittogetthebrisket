"""The sharded hard gate is only as safe as its wiring.

``scripts/ci_test_shards.py`` proves a sharded run executed every test, but
that proof protects nothing unless the workflows (1) run the identical hard-gate
command on every shard, (2) make the merge/deploy decision depend on a job that
fails whenever any shard failed, was cancelled or was skipped, and (3) never let
an old target tree — one without the shard owner — be "sharded" into eight full
runs with no manifest.  These tests pin that wiring structurally.
"""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

import pytest
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


# ── Release Candidate ───────────────────────────────────────────────────
#
# release-candidate.yml validates a merge candidate it BUILDS, so the shards
# are only one gate if they provably test one tree.  The plan records head SHA,
# base SHA and the candidate tree hash; every job that reads the candidate
# rebuilds it from those pinned SHAs and fails unless the tree matches; the
# aggregator also requires the other gates' tree to be the planned one.

RC = "release-candidate.yml"
REBUILD_STEP = "Rebuild the candidate and assert it is the planned tree"
VERDICT_STEP = "Every required job succeeded"
EM = "—"

# Every gate the release candidate ran before the hard gate was sharded, minus
# the unit-test step (which moved to the `hard-gate` matrix), in order, with a
# command each must still run.  The candidate BUILD is now the pinned rebuild
# the shards use (review of #2146), so the gates and the shards share one tree.
_CANDIDATE_GATES = [
    (f"Checkout (full history {EM} the check diffs base against head)", None),
    ("Set up Python", None),
    ("Install dependencies", "pip install --require-hashes -r requirements-dev.lock.txt"),
    ("Release-candidate freshness (STRICT)", "--strict"),
    (
        "Rebuild the candidate and assert it is the planned tree",
        'git merge --no-edit "${BASE_SHA}"',
    ),
    ("Python format + lint gates", "python -m ruff format --check ."),
    ("Governance + planning gates", "python scripts/check_planning_integrity.py"),
    ("API data contract check (structural lane)", "--lane structural"),
    (
        f"Source health (advisory {EM} the deploy gate is the blocking one)",
        "scripts/check_source_health.py",
    ),
    ("Validate dependency graph (pip check)", "python -m pip check"),
    ("Preflight environment check", "python scripts/check_env.py"),
    ("Python syntax gate", "py_compile"),
    ("Python runtime import gate", "import server"),
    ("Deploy script syntax gate (existing scripts only)", "bash -n"),
    ("Set up Node.js", None),
    ("Install frontend dependencies", "npm ci"),
    ("Frontend unit tests (vitest)", "npm test"),
    ("Frontend build + bundle-size budget", "npm run check:bundles"),
]


def _step(job: dict, name: str) -> dict:
    matches = [s for s in _steps(job) if s.get("name") == name]
    assert len(matches) == 1, f"expected exactly one step named {name!r}"
    return matches[0]


def test_release_candidate_runs_the_hard_gate_only_in_the_sharded_matrix():
    doc = _load(RC)
    assert list(_hard_gate_jobs(doc)) == ["hard-gate"]
    gate = doc["jobs"]["hard-gate"]
    assert gate["needs"] == "plan"
    assert gate["strategy"]["fail-fast"] is False
    assert "fromJSON(needs.plan.outputs.shards)" in str(gate["strategy"]["matrix"]["shard"])
    assert gate["timeout-minutes"] == "${{ matrix.shard == 'serial' && 180 || 45 }}"
    step = next(s for s in _steps(gate) if HARD_GATE_COMMAND in (s.get("run") or ""))
    shard_env = step["env"]["RISKIT_TEST_SHARD"]
    # Empty on the serial fallback, so the plugin never registers there.
    assert "matrix.shard != 'serial'" in shard_env and "|| ''" in shard_env
    assert "needs.plan.outputs.shard_count" in shard_env
    assert "RISKIT_TEST_SHARD_MANIFEST" in step["env"]
    upload = next(s for s in _steps(gate) if "upload-artifact" in str(s.get("uses")))
    assert upload.get("if") == "${{ always() && needs.plan.outputs.mode == 'sharded' }}"
    # Real-OCR tests run instead of skipping, as in PR Validation and Deploy:
    # all three gates share one skip budget.
    assert any(
        "install -y" in (s.get("run") or "") and "tesseract-ocr" in s["run"] for s in _steps(gate)
    )


def test_release_candidate_runs_the_byte_identical_pr_gate_command():
    def gate_line(doc: dict, job: str) -> str:
        step = next(
            s for s in _steps(doc["jobs"][job]) if HARD_GATE_COMMAND in (s.get("run") or "")
        )
        return next(line for line in step["run"].splitlines() if HARD_GATE_COMMAND in line)

    assert gate_line(_load(RC), "hard-gate") == gate_line(_load("pr-validation.yml"), "backend")


def test_every_rc_job_that_reads_the_candidate_asserts_the_planned_tree():
    jobs = _load(RC)["jobs"]
    planned = {
        "HEAD_SHA": "${{ needs.plan.outputs.head_sha }}",
        "BASE_SHA": "${{ needs.plan.outputs.base_sha }}",
        "CANDIDATE_TREE": "${{ needs.plan.outputs.candidate_tree }}",
    }
    for job_id, consumer in (
        # The candidate gates too (review of #2146): pinned to the plan, so an
        # inert base commit landing mid-run cannot hand them another tree.
        ("candidate", "python -m ruff format --check ."),
        ("hard-gate", HARD_GATE_COMMAND),
        ("validate", "scripts/ci_test_shards.py verify"),
    ):
        steps = _steps(jobs[job_id])
        needs = jobs[job_id]["needs"]
        assert "plan" in ([needs] if isinstance(needs, str) else needs)
        checkout = steps[0]
        assert "actions/checkout" in checkout["uses"]
        assert checkout["with"]["ref"] == "${{ needs.plan.outputs.head_sha }}"
        assert checkout["with"]["fetch-depth"] == 0
        rebuild = _step(jobs[job_id], REBUILD_STEP)
        assert rebuild["env"] == planned
        assert rebuild.get("id") == "rebuild"
        assert "continue-on-error" not in rebuild
        consumer_at = next(i for i, s in enumerate(steps) if consumer in (s.get("run") or ""))
        assert steps.index(rebuild) < consumer_at, f"{job_id} reads the tree before asserting it"
    shard_run = _step(jobs["hard-gate"], REBUILD_STEP)["run"]
    assert shard_run == _step(jobs["validate"], REBUILD_STEP)["run"]
    assert shard_run == _step(jobs["candidate"], REBUILD_STEP)["run"]
    # Merged by the PINNED base SHA, never the moving branch.
    assert 'git merge --no-edit "${BASE_SHA}"' in shard_run
    assert "inputs.base_ref" not in shard_run and "origin/" not in shard_run
    assert "HEAD^{tree}" in shard_run
    check = '[[ "${tree}" == "${CANDIDATE_TREE}" ]] ||'
    publish = 'echo "candidate_tree=${tree}" >> "$GITHUB_OUTPUT"'
    # Published only once asserted.
    assert check in shard_run and shard_run.index(check) < shard_run.index(publish)
    # Nothing builds the candidate from the moving branch any more.
    assert 'git merge --no-edit "origin/' not in _runs(jobs["candidate"])


def test_no_workflow_input_is_interpolated_into_shell():
    """``${{ inputs.* }}`` inside ``run:`` is spliced into the script text
    before bash parses it; inputs reach shell only through ``env:``."""
    doc = _load(RC)
    for job_id, job in doc["jobs"].items():
        for step in _steps(job):
            assert "${{ inputs." not in (step.get("run") or ""), (job_id, step.get("name"))
    for job_id in ("plan", "candidate"):
        strict = _step(doc["jobs"][job_id], "Release-candidate freshness (STRICT)")
        assert strict["env"] == {"BASE_REF": "${{ inputs.base_ref }}"}
        assert '--base "origin/${BASE_REF}"' in strict["run"]


def test_a_partial_rerun_cannot_reuse_an_earlier_attempts_plan():
    """ "Re-run failed jobs" keeps ``plan``'s outputs from the earlier attempt,
    so the STRICT freshness check would not run again.  The plan publishes its
    attempt and the verdict refuses a plan from any other attempt."""
    doc = _load(RC)
    assert doc["jobs"]["plan"]["outputs"]["attempt"] == "${{ github.run_attempt }}"
    verdict = _step(doc["jobs"]["validate"], VERDICT_STEP)
    assert verdict["env"]["PLAN_ATTEMPT"] == "${{ needs.plan.outputs.attempt }}"
    assert verdict["env"]["RUN_ATTEMPT"] == "${{ github.run_attempt }}"
    assert '[[ "${PLAN_ATTEMPT}" != "${RUN_ATTEMPT}" ]]' in verdict["run"]


def test_shard_manifests_are_named_for_the_plans_attempt_and_tree():
    jobs = _load(RC)["jobs"]
    upload = next(s for s in _steps(jobs["hard-gate"]) if "upload-artifact" in str(s.get("uses")))
    download = _step(jobs["validate"], "Download shard manifests")
    name = upload["with"]["name"]
    assert name.endswith("-shard-${{ matrix.shard }}")
    prefix = name[: -len("${{ matrix.shard }}")]
    assert "${{ needs.plan.outputs.candidate_tree }}" in prefix
    assert "${{ needs.plan.outputs.attempt }}" in prefix
    # The verdict downloads exactly this plan's shards, never another attempt's
    # or another candidate's.
    assert download["with"]["pattern"] == prefix + "*"


def test_the_plan_records_the_candidate_identity_after_the_strict_check():
    jobs = _load(RC)["jobs"]
    plan = jobs["plan"]
    assert set(plan["outputs"]) == {
        "head_sha",
        "base_sha",
        "candidate_tree",
        "shards",
        "shard_count",
        "mode",
        "attempt",
    }
    steps = _steps(plan)
    strict = _step(plan, "Release-candidate freshness (STRICT)")
    # The same strict gate the candidate job runs, before anything is built.
    assert strict["run"] == _step(jobs["candidate"], "Release-candidate freshness (STRICT)")["run"]
    build = next(s for s in steps if s.get("id") == "build")
    assert steps.index(strict) < steps.index(build)
    assert 'git merge --no-edit "${base_sha}"' in build["run"]
    assert "HEAD^{tree}" in build["run"] and "candidate_tree=${tree}" in build["run"]
    # The head SHA is read before the merge moves HEAD.
    assert build["run"].index("head_sha=") < build["run"].index("git merge")


def test_the_plan_falls_back_to_serial_when_the_candidate_tree_lacks_the_shard_owner():
    plan = _load(RC)["jobs"]["plan"]
    steps = _steps(plan)
    build = next(s for s in steps if s.get("id") == "build")
    choose = next(s for s in steps if s.get("id") == "plan")
    # Decided on the merged CANDIDATE tree, not the head alone.
    assert steps.index(build) < steps.index(choose)
    run = choose["run"]
    assert "-f scripts/ci_test_shards.py" in run and "-f config/ci/test_shards.json" in run
    assert "python scripts/ci_test_shards.py matrix --github-output" in run
    assert 'shards=["serial"]' in run and "mode=serial" in run and "mode=sharded" in run


def test_validate_release_candidate_fails_closed():
    doc = _load(RC)
    named = [k for k, j in doc["jobs"].items() if j.get("name") == "Validate Release Candidate"]
    assert named == ["validate"], "the check name operators read must stay on the verdict job"
    validate = doc["jobs"]["validate"]
    assert set(validate["needs"]) == {"plan", "candidate", "hard-gate"}
    # always(), never !cancelled() or no `if`: a cancelled or failed upstream
    # must end RED here, not as a skipped job that reads as passed.
    assert validate["if"] == "${{ always() }}"
    assert "scripts/ci_test_shards.py verify" in _runs(validate)
    verdict = _step(validate, VERDICT_STEP)
    assert verdict["if"] == "${{ always() }}"
    assert verdict["env"]["GATES_TREE"] == "${{ needs.candidate.outputs.candidate_tree }}"
    assert verdict["env"]["PLANNED_TREE"] == "${{ needs.plan.outputs.candidate_tree }}"
    for var in ("PLAN_RESULT", "CANDIDATE_RESULT", "GATE_RESULT"):
        assert '"${' + var + '}" != "success"' in verdict["run"]


def test_no_other_release_candidate_gate_was_removed():
    candidate = _load(RC)["jobs"]["candidate"]
    steps = _steps(candidate)
    assert [s.get("name") for s in steps] == [name for name, _ in _CANDIDATE_GATES]
    for step, (name, command) in zip(steps, _CANDIDATE_GATES):
        if command is not None:
            assert command in (step.get("run") or ""), f"{name!r} no longer runs {command!r}"
        if name.startswith("Source health"):
            assert step.get("continue-on-error") is True and step.get("if") == "${{ always() }}"
        else:
            # Unconditional and blocking, as before.
            assert "if" not in step and "continue-on-error" not in step, name
    assert candidate["needs"] == "plan" and "if" not in candidate
    assert HARD_GATE_COMMAND not in _runs(candidate)
    # It publishes the tree it asserted, for the aggregator's identity check.
    assert candidate["outputs"]["candidate_tree"] == "${{ steps.rebuild.outputs.candidate_tree }}"


def test_one_release_candidate_at_a_time_on_manual_dispatch_only():
    doc = _load(RC)
    assert doc["concurrency"] == {"group": "release-candidate", "cancel-in-progress": False}
    assert set(doc[True]) == {"workflow_dispatch"}


# ── Release Candidate: the shell that enforces it, executed ─────────────


def _bash() -> str:
    bash = shutil.which("bash")
    if bash is None or shutil.which("git") is None:
        pytest.skip("needs bash and git")
    return bash


def _clean_env(home: Path) -> dict[str, str]:
    env = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}
    env.update(HOME=str(home), XDG_CONFIG_HOME=str(home), GIT_CONFIG_NOSYSTEM="1")
    return env


def _run_step(script: str, cwd: Path, env: dict[str, str]) -> subprocess.CompletedProcess:
    return subprocess.run(
        [_bash(), "-c", script], cwd=cwd, env=env, capture_output=True, text=True, check=False
    )


_TREE = "a" * 40
_ALL_GREEN = {
    "PLAN_RESULT": "success",
    "CANDIDATE_RESULT": "success",
    "GATE_RESULT": "success",
    "MODE": "sharded",
    "PLANNED_TREE": _TREE,
    "GATES_TREE": _TREE,
    "PLAN_ATTEMPT": "1",
    "RUN_ATTEMPT": "1",
}


@pytest.mark.parametrize(
    "override, passes",
    [
        ({}, True),
        ({"MODE": "serial"}, True),
        # "Re-run all jobs": the plan ran again in this attempt.
        ({"PLAN_ATTEMPT": "3", "RUN_ATTEMPT": "3"}, True),
        # "Re-run failed jobs": the plan (and its STRICT check) is attempt 1's.
        ({"PLAN_ATTEMPT": "1", "RUN_ATTEMPT": "2"}, False),
        ({"PLAN_ATTEMPT": ""}, False),
        ({"PLAN_RESULT": "failure"}, False),
        ({"CANDIDATE_RESULT": "cancelled"}, False),
        ({"GATE_RESULT": "failure"}, False),
        ({"GATE_RESULT": "skipped"}, False),
        ({"GATE_RESULT": "cancelled"}, False),
        ({"MODE": ""}, False),
        ({"GATES_TREE": "b" * 40}, False),
        ({"GATES_TREE": ""}, False),
        ({"PLANNED_TREE": "", "GATES_TREE": ""}, False),
    ],
)
def test_the_verdict_passes_only_when_everything_succeeded_on_one_tree(tmp_path, override, passes):
    script = _step(_load(RC)["jobs"]["validate"], VERDICT_STEP)["run"]
    env = {**_clean_env(tmp_path), **_ALL_GREEN, **override}
    result = _run_step(script, tmp_path, env)
    assert (result.returncode == 0) is passes, result.stdout + result.stderr


def test_a_partial_rerun_fails_with_the_instruction_to_rerun_everything(tmp_path):
    script = _step(_load(RC)["jobs"]["validate"], VERDICT_STEP)["run"]
    env = {**_clean_env(tmp_path), **_ALL_GREEN, "PLAN_ATTEMPT": "1", "RUN_ATTEMPT": "2"}
    result = _run_step(script, tmp_path, env)
    assert result.returncode != 0
    assert (
        "partial re-run detected: re-run ALL jobs so the strict freshness check and "
        "candidate build run again"
    ) in result.stdout


def _git(cwd: Path, env: dict[str, str], *args: str) -> str:
    identity = ("-c", "user.name=t", "-c", "user.email=t@example.com", "-c", "commit.gpgsign=false")
    return subprocess.run(
        ["git", *identity, *args], cwd=cwd, env=env, capture_output=True, text=True, check=True
    ).stdout.strip()


@pytest.fixture
def candidate_repo(tmp_path):
    """An origin whose head branch and base branch diverged, and the tree of
    their merge (the release candidate) computed independently."""
    _bash()
    env = _clean_env(tmp_path)
    origin = tmp_path / "origin"
    origin.mkdir()
    _git(origin, env, "init", "-q", "-b", "main")
    _git(origin, env, "config", "uploadpack.allowAnySHA1InWant", "true")
    (origin / "shared.txt").write_text("root\n", encoding="utf-8")
    _git(origin, env, "add", "-A")
    _git(origin, env, "commit", "-q", "-m", "root")
    _git(origin, env, "checkout", "-q", "-b", "frozen-head")
    (origin / "head.txt").write_text("head\n", encoding="utf-8")
    _git(origin, env, "add", "-A")
    _git(origin, env, "commit", "-q", "-m", "head")
    _git(origin, env, "checkout", "-q", "main")
    (origin / "base.txt").write_text("base\n", encoding="utf-8")
    _git(origin, env, "add", "-A")
    _git(origin, env, "commit", "-q", "-m", "base moved")
    head = _git(origin, env, "rev-parse", "frozen-head")
    base = _git(origin, env, "rev-parse", "main")
    oracle = tmp_path / "oracle"
    _git(tmp_path, env, "clone", "-q", str(origin), str(oracle))
    _git(oracle, env, "checkout", "-q", "--detach", head)
    _git(oracle, env, "merge", "--no-edit", "-q", base)
    tree = _git(oracle, env, "rev-parse", "HEAD^{tree}")
    assert tree != _git(origin, env, "rev-parse", f"{head}^{{tree}}")

    def checkout(name: str, *clone_args: str) -> Path:
        work = tmp_path / name
        _git(tmp_path, env, "clone", "-q", *clone_args, str(origin), str(work))
        _git(work, env, "checkout", "-q", "--detach", head)
        return work

    def land_inert_commit_on_base() -> str:
        """An automated commit lands on the base AFTER the plan ran."""
        (origin / "NOTES.md").write_text("inert prose\n", encoding="utf-8")
        _git(origin, env, "add", "-A")
        _git(origin, env, "commit", "-q", "-m", "inert docs commit")
        return _git(origin, env, "rev-parse", "main")

    return {
        "env": env,
        "head": head,
        "base": base,
        "tree": tree,
        "checkout": checkout,
        "land_inert_commit_on_base": land_inert_commit_on_base,
        "tmp": tmp_path,
    }


def _rebuild(
    repo: dict, work: Path, job: str = "hard-gate", **identity: str
) -> subprocess.CompletedProcess:
    script = _step(_load(RC)["jobs"][job], REBUILD_STEP)["run"]
    env = {
        **repo["env"],
        "HEAD_SHA": repo["head"],
        "BASE_SHA": repo["base"],
        "CANDIDATE_TREE": repo["tree"],
        "GITHUB_OUTPUT": str(work.parent / f"{work.name}.github_output"),
        **identity,
    }
    return _run_step(script, work, env)


def test_the_rebuild_reproduces_the_planned_tree(candidate_repo):
    work = candidate_repo["checkout"]("shard")
    result = _rebuild(candidate_repo, work)
    assert result.returncode == 0, result.stdout + result.stderr
    assert _git(work, candidate_repo["env"], "rev-parse", "HEAD^{tree}") == candidate_repo["tree"]


def test_the_rebuild_publishes_the_tree_it_asserted(candidate_repo):
    work = candidate_repo["checkout"]("gates")
    result = _rebuild(candidate_repo, work, job="candidate")
    assert result.returncode == 0, result.stdout + result.stderr
    published = (work.parent / "gates.github_output").read_text(encoding="utf-8")
    assert published.splitlines() == [f"candidate_tree={candidate_repo['tree']}"]


def test_an_inert_base_commit_after_the_plan_cannot_fail_the_candidate_gates(candidate_repo):
    """The candidate job used to merge the MOVING ``origin/<base_ref>`` on its
    own schedule, so a docs commit landing between plan and candidate gave it a
    different tree: a false red.  It now merges the plan's pinned base."""
    moved = candidate_repo["land_inert_commit_on_base"]()
    work = candidate_repo["checkout"]("gates")
    assert (
        _git(work, candidate_repo["env"], "rev-parse", "origin/main")
        == moved
        != (candidate_repo["base"])
    )
    # What the old step did: merge the moving branch.  A different tree.
    moving = candidate_repo["checkout"]("moving")
    _git(moving, candidate_repo["env"], "merge", "--no-edit", "-q", "origin/main")
    assert _git(moving, candidate_repo["env"], "rev-parse", "HEAD^{tree}") != candidate_repo["tree"]
    # What the candidate job does now: the planned tree, and it passes.
    result = _rebuild(candidate_repo, work, job="candidate")
    assert result.returncode == 0, result.stdout + result.stderr
    assert _git(work, candidate_repo["env"], "rev-parse", "HEAD^{tree}") == candidate_repo["tree"]


def test_the_rebuild_fetches_a_base_the_checkout_lacks(candidate_repo):
    work = candidate_repo["checkout"]("narrow", "--single-branch", "--branch", "frozen-head")
    result = _rebuild(candidate_repo, work)
    assert result.returncode == 0, result.stdout + result.stderr


def test_the_rebuild_fails_closed_on_a_different_tree(candidate_repo):
    work = candidate_repo["checkout"]("shard")
    head_tree = _git(work, candidate_repo["env"], "rev-parse", "HEAD^{tree}")
    result = _rebuild(candidate_repo, work, CANDIDATE_TREE=head_tree)
    assert result.returncode != 0
    assert "tree mismatch" in result.stdout + result.stderr


def test_the_rebuild_refuses_a_head_other_than_the_planned_one(candidate_repo):
    work = candidate_repo["checkout"]("shard")
    result = _rebuild(candidate_repo, work, HEAD_SHA=candidate_repo["base"])
    assert result.returncode != 0
    assert "head mismatch" in result.stdout + result.stderr


@pytest.mark.parametrize("missing", ["HEAD_SHA", "BASE_SHA", "CANDIDATE_TREE"])
def test_the_rebuild_refuses_a_missing_plan_identity(candidate_repo, missing):
    work = candidate_repo["checkout"]("shard")
    result = _rebuild(candidate_repo, work, **{missing: ""})
    assert result.returncode != 0
    assert "not a full SHA" in result.stdout + result.stderr
