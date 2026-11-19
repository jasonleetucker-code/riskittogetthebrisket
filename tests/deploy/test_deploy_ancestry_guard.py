"""The deploy guard refuses stale runs, unverified rollbacks and backwards deploys (STAB-1).

``scripts/deploy_ancestry_guard.py`` is the one decision the Deploy Production
job makes before it touches the box.  These tests drive it against a real
temporary git history:

    A --- B --- C          (main line: production at B unless stated)
     \\
      D                    (a diverged side branch)

and pin the workflow wiring that feeds it, so a future edit cannot quietly
disconnect an input (an empty ``expected_live_sha`` or ``run_attempt`` must
refuse, never read as "no rollback" / "fresh").
"""

from __future__ import annotations

import os
import shutil
import subprocess
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
import yaml

from scripts.deploy_ancestry_guard import (
    MAX_QUEUE_AGE,
    GuardInputs,
    baseline_state,
    decide,
    main,
)

ROOT = Path(__file__).resolve().parents[2]
WORKFLOW = ROOT / ".github" / "workflows" / "deploy.yml"
NOW = datetime(2026, 11, 19, 12, 0, tzinfo=timezone.utc)
FRESH = (NOW - timedelta(minutes=25)).isoformat().replace("+00:00", "Z")


def _git(repo: Path, *args: str) -> str:
    return subprocess.check_output(["git", "-C", str(repo), *args], text=True).strip()


def _commit(repo: Path, name: str) -> str:
    (repo / f"{name}.txt").write_text(name, encoding="utf-8")
    _git(repo, "add", ".")
    _git(repo, "commit", "-q", "-m", name)
    return _git(repo, "rev-parse", "HEAD")


@pytest.fixture(scope="module")
def history(tmp_path_factory) -> dict[str, object]:
    repo = tmp_path_factory.mktemp("guard") / "repo"
    repo.mkdir()
    _git(repo, "init", "-q", "-b", "main")
    _git(repo, "config", "user.email", "test@example.com")
    _git(repo, "config", "user.name", "Test")
    a = _commit(repo, "A")
    b = _commit(repo, "B")
    c = _commit(repo, "C")
    _git(repo, "checkout", "-q", "-b", "side", a)
    d = _commit(repo, "D")
    _git(repo, "checkout", "-q", "main")
    return {"repo": repo, "A": a, "B": b, "C": c, "D": d}


def _inputs(**overrides) -> GuardInputs:
    base = {
        "target": "",
        "live": "",
        "event": "push",
        "run_attempt": "1",
        "run_created_at": FRESH,
        "allow_non_fast_forward": "false",
        "expected_live_sha": "",
        "now": NOW,
    }
    base.update(overrides)
    # What the workflow's remote read reports for these contents: no contents
    # = an ABSENT state file unless a test says otherwise.  An EMPTY file is
    # live_read="present" with live="", and is spelled out where it is tested.
    base.setdefault("live_read", "present" if base["live"] else "absent")
    return GuardInputs(**base)


def _decide(history, **overrides):
    return decide(_inputs(**overrides), history["repo"])


def _errors(verdict) -> str:
    return "\n".join(line for line in verdict.lines if line.startswith("::error"))


# ── direction ────────────────────────────────────────────────────────


def test_forward_deploy_passes_and_names_what_ships(history):
    verdict = _decide(history, target=history["C"], live=history["B"])
    assert verdict.allowed, verdict.lines
    assert any("Fast-forward deploy" in line for line in verdict.lines)
    assert any(
        line.strip().startswith("shipping:") and line.endswith(" C") for line in verdict.lines
    )


def test_same_commit_redeploy_passes(history):
    verdict = _decide(history, target=history["B"], live=history["B"])
    assert verdict.allowed, verdict.lines
    assert any("Redeploy" in line for line in verdict.lines)


def test_backwards_deploy_is_refused_and_names_the_dropped_commits(history):
    verdict = _decide(history, target=history["A"], live=history["B"])
    assert not verdict.allowed
    errors = _errors(verdict)
    assert "would move production BACKWARDS by 1 commit(s)" in errors
    assert f"expected_live_sha={history['B']}" in errors, "the refusal must say how to retry"
    assert any(line.strip().startswith("dropping:") for line in verdict.lines)


def test_diverged_deploy_is_refused(history):
    verdict = _decide(history, target=history["D"], live=history["B"])
    assert not verdict.allowed
    assert "DIVERGED" in _errors(verdict)


def test_no_baseline_first_deploy_behaves_as_before(history):
    verdict = _decide(history, target=history["A"], live="")
    assert verdict.allowed, verdict.lines
    assert any("No deploy baseline" in line for line in verdict.lines)


def test_failed_baseline_read_is_not_no_baseline(history):
    verdict = _decide(history, target=history["A"], live="", live_read="failed")
    assert not verdict.allowed
    assert "Cannot read the production baseline" in _errors(verdict)


@pytest.mark.parametrize("contents", ["", "   ", "\n\t \n"])
def test_an_empty_state_file_is_refused_not_read_as_a_first_deploy(history, contents):
    # A file that EXISTS but holds no commit is what an interrupted
    # ``printf > file`` leaves behind.  It is not "no baseline": passing it as
    # one would let any target -- backwards included -- ship.
    verdict = _decide(
        history, target=history["A"], live=contents, live_read="present", live_file="/state/last"
    )
    assert not verdict.allowed
    errors = _errors(verdict)
    assert "Empty deploy baseline" in errors
    assert "/state/last exists on the box but is empty" in errors
    assert "No deploy baseline" not in "\n".join(verdict.lines)


def test_an_empty_state_file_is_refused_even_with_rollback_intent(history):
    verdict = _decide(
        history,
        target=history["A"],
        live="",
        live_read="present",
        event="workflow_dispatch",
        allow_non_fast_forward="true",
        expected_live_sha=history["B"],
    )
    assert not verdict.allowed
    assert "Empty deploy baseline" in _errors(verdict)


@pytest.mark.parametrize(
    ("live_read", "live", "state"),
    [
        ("absent", "", "absent"),
        ("present", "", "empty"),
        ("present", " \n", "empty"),
        ("present", "not-a-sha", "malformed"),
        ("present", "abc1234", "malformed"),
        ("present", "a" * 40, "ok"),
        ("present", " " + "A" * 40 + "\n", "ok"),
        ("failed", "", "failed"),
        ("failed", "a" * 40, "failed"),
        # An "absent" read that nonetheless carried contents is contradictory:
        # fail closed rather than pick one reading.
        ("absent", "a" * 40, "failed"),
        ("ok", "", "failed"),
    ],
)
def test_baseline_state_names_every_file_state(live_read, live, state):
    assert baseline_state(live_read, live) == state


def test_baseline_that_is_not_a_sha_is_refused_even_with_rollback_intent(history):
    for flag, expected in (("false", ""), ("true", history["B"])):
        verdict = _decide(
            history,
            target=history["A"],
            live="not-a-sha",
            event="workflow_dispatch",
            allow_non_fast_forward=flag,
            expected_live_sha=expected,
        )
        assert not verdict.allowed
        assert "Unreadable deploy baseline" in _errors(verdict)


def test_baseline_missing_from_history_needs_an_authorised_rollback(history):
    ghost = "f" * 40
    refused = _decide(history, target=history["C"], live=ghost)
    assert not refused.allowed
    assert "Cannot verify deploy safety" in _errors(refused)
    allowed = _decide(
        history,
        target=history["C"],
        live=ghost,
        event="workflow_dispatch",
        allow_non_fast_forward="true",
        expected_live_sha=ghost,
    )
    assert allowed.allowed, allowed.lines


def test_target_that_is_not_a_full_sha_is_refused(history):
    verdict = _decide(history, target=history["C"][:12], live=history["B"])
    assert not verdict.allowed
    assert "No resolved deploy target" in _errors(verdict)


# ── rollback compare-and-swap ────────────────────────────────────────


def test_rollback_with_matching_expected_live_sha_passes(history):
    for target in (history["A"], history["D"]):
        verdict = _decide(
            history,
            target=target,
            live=history["B"],
            event="workflow_dispatch",
            allow_non_fast_forward="true",
            expected_live_sha=history["B"].upper(),
        )
        assert verdict.allowed, verdict.lines
        assert any("Rollback authorised" in line for line in verdict.lines)
        assert any("Non-fast-forward deploy" in line for line in verdict.lines)


@pytest.mark.parametrize(
    ("expected", "title"),
    [
        ("", "Rollback needs expected_live_sha"),
        ("   ", "Rollback needs expected_live_sha"),
        ("abc1234", "Malformed expected_live_sha"),
        ("g" * 40, "Malformed expected_live_sha"),
        ("STALE", "Production moved since this rollback was requested"),
    ],
)
def test_rollback_with_missing_malformed_or_stale_expected_sha_is_refused(history, expected, title):
    if expected == "STALE":
        # Requested while production was at A; production has since moved to B.
        expected = history["A"]
    verdict = _decide(
        history,
        target=history["A"],
        live=history["B"],
        event="workflow_dispatch",
        allow_non_fast_forward="true",
        expected_live_sha=expected,
    )
    assert not verdict.allowed
    errors = _errors(verdict)
    assert f"title={title}" in errors
    assert history["B"] in errors, "the refusal must print the live value to retry with"
    assert "/api/status" in errors or title == "Malformed expected_live_sha"


def test_stale_rollback_is_refused_even_when_it_would_be_a_forward_move(history):
    # A long-ago rollback request whose target happens to be ahead of today's
    # production is still a request against a state that no longer exists.
    verdict = _decide(
        history,
        target=history["C"],
        live=history["B"],
        event="workflow_dispatch",
        allow_non_fast_forward="true",
        expected_live_sha=history["A"],
    )
    assert not verdict.allowed
    assert "Production moved since this rollback was requested" in _errors(verdict)


def test_rollback_with_no_recorded_baseline_is_refused(history):
    verdict = _decide(
        history,
        target=history["A"],
        live="",
        event="workflow_dispatch",
        allow_non_fast_forward="true",
        expected_live_sha=history["B"],
    )
    assert not verdict.allowed
    assert "Rollback has no live commit to compare" in _errors(verdict)


@pytest.mark.parametrize("event", ["push", "schedule", "workflow_run"])
def test_rollback_intent_on_a_non_dispatch_event_is_refused(history, event):
    verdict = _decide(
        history,
        target=history["A"],
        live=history["B"],
        event=event,
        allow_non_fast_forward="true",
        expected_live_sha=history["B"],
    )
    assert not verdict.allowed
    assert "Rollback intent on a non-dispatch run" in _errors(verdict)


def test_an_unparseable_rollback_flag_is_refused(history):
    verdict = _decide(history, target=history["C"], live=history["B"], allow_non_fast_forward="yes")
    assert not verdict.allowed
    assert "Invalid rollback flag" in _errors(verdict)


def test_a_push_renders_the_flag_empty_and_deploys_forward(history):
    # inputs.* are empty strings on a push; empty must read as "no rollback".
    verdict = _decide(history, target=history["C"], live=history["B"], allow_non_fast_forward="")
    assert verdict.allowed, verdict.lines


# ── stale queue ──────────────────────────────────────────────────────


def test_zombie_first_attempt_is_refused(history):
    created = "2026-08-19T03:12:00Z"  # queued for three months
    verdict = _decide(
        history,
        target=history["C"],
        live=history["B"],
        event="workflow_dispatch",
        run_created_at=created,
    )
    assert not verdict.allowed
    errors = _errors(verdict)
    assert "Stale queued deploy refused" in errors
    assert "2026-08-19T03:12:00+00:00" in errors


def test_queue_bound_edges(history):
    inside = (NOW - MAX_QUEUE_AGE + timedelta(minutes=1)).isoformat()
    outside = (NOW - MAX_QUEUE_AGE - timedelta(minutes=1)).isoformat()
    assert _decide(history, target=history["C"], live=history["B"], run_created_at=inside).allowed
    assert not _decide(
        history, target=history["C"], live=history["B"], run_created_at=outside
    ).allowed


def test_the_bound_covers_every_observed_deploy():
    # Longest creation -> guard time over 85 sampled Deploy Production runs
    # (2026-11-06..19) was 136 minutes.  The bound must leave real headroom.
    assert MAX_QUEUE_AGE >= timedelta(minutes=136) * 2
    assert MAX_QUEUE_AGE <= timedelta(hours=24)


def test_a_zombie_stale_queue_check_runs_before_the_rollback_check(history):
    # A months-old rollback dispatch is refused for staleness even if its
    # expected_live_sha happens to still match.
    verdict = _decide(
        history,
        target=history["A"],
        live=history["B"],
        event="workflow_dispatch",
        run_created_at="2026-08-19T03:12:00Z",
        allow_non_fast_forward="true",
        expected_live_sha=history["B"],
    )
    assert not verdict.allowed
    assert "Stale queued deploy refused" in _errors(verdict)


def test_rerun_attempt_is_exempt_from_the_queue_bound(history):
    verdict = _decide(
        history,
        target=history["C"],
        live=history["B"],
        run_attempt="2",
        run_created_at="2026-08-19T03:12:00Z",
    )
    assert verdict.allowed, verdict.lines
    assert any("Re-run attempt" in line for line in verdict.lines)


def test_rerun_does_not_exempt_direction(history):
    verdict = _decide(
        history, target=history["A"], live=history["B"], run_attempt="3", run_created_at=""
    )
    assert not verdict.allowed
    assert "BACKWARDS" in _errors(verdict)


@pytest.mark.parametrize("created", ["", "not-a-time", "2026-11-19T11:30:00"])
def test_unreadable_created_at_fails_closed(history, created):
    verdict = _decide(history, target=history["C"], live=history["B"], run_created_at=created)
    assert not verdict.allowed
    assert "Cannot verify run freshness" in _errors(verdict)


def test_created_at_far_in_the_future_fails_closed(history):
    future = (NOW + timedelta(hours=2)).isoformat()
    verdict = _decide(history, target=history["C"], live=history["B"], run_created_at=future)
    assert not verdict.allowed
    assert "Cannot verify run freshness" in _errors(verdict)


@pytest.mark.parametrize("attempt", ["", "0", "x", "-1"])
def test_unreadable_run_attempt_fails_closed(history, attempt):
    verdict = _decide(history, target=history["C"], live=history["B"], run_attempt=attempt)
    assert not verdict.allowed
    assert "Cannot verify run freshness" in _errors(verdict)


# ── CLI ──────────────────────────────────────────────────────────────


def test_cli_exit_codes_and_annotations(history, capsys):
    common = [
        "--repo",
        str(history["repo"]),
        "--live",
        history["B"],
        "--run-attempt",
        "1",
        "--run-created-at",
        FRESH,
        "--now",
        NOW.isoformat(),
    ]
    assert main(["--target", history["C"], "--event", "push", *common]) == 0
    assert main(["--target", history["A"], "--event", "push", *common]) == 1
    out = capsys.readouterr().out
    assert "::error title=Deploy would skip or reverse shipped code::" in out
    assert (
        main(["--target", history["C"], "--event", "push", "--live-read", "failed", *common]) == 1
    )
    no_live = [arg for arg in common if arg != history["B"] and arg != "--live"]
    # An absent file is a first deploy; an empty one is refused.
    first = ["--target", history["C"], "--event", "push", "--live", "", *no_live]
    assert main([*first, "--live-read", "absent"]) == 0
    assert main([*first, "--live-read", "present"]) == 1
    assert "::error title=Empty deploy baseline::" in capsys.readouterr().out


# ── workflow wiring ──────────────────────────────────────────────────


@pytest.fixture(scope="module")
def workflow():
    return yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))


def _step(job: dict, prefix: str) -> tuple[int, dict]:
    for index, step in enumerate(job["steps"]):
        if step.get("name", "").startswith(prefix):
            return index, step
    raise AssertionError(f"no step starting with {prefix!r}")


def test_dispatch_declares_expected_live_sha(workflow):
    inputs = workflow[True]["workflow_dispatch"]["inputs"]
    sha = inputs["expected_live_sha"]
    assert sha["type"] == "string"
    assert sha.get("required", False) is False
    assert inputs["allow_non_fast_forward"]["default"] is False


def test_guard_step_feeds_every_input_to_the_helper(workflow):
    deploy = workflow["jobs"]["deploy"]
    _, guard = _step(deploy, "Guard against skipping")
    env = guard["env"]
    assert env["ALLOW_NON_FF"] == "${{ inputs.allow_non_fast_forward }}"
    assert env["EXPECTED_LIVE_SHA"] == "${{ inputs.expected_live_sha }}"
    assert env["EVENT_NAME"] == "${{ github.event_name }}"
    assert env["RUN_ATTEMPT"] == "${{ github.run_attempt }}"
    assert env["GH_TOKEN"] == "${{ github.token }}"
    run = guard["run"]
    assert "python3 scripts/deploy_ancestry_guard.py" in run
    for flag in (
        '--target "${TARGET_SHA}"',
        '--live "${LAST_DEPLOYED}"',
        '--live-read "${LIVE_READ}"',
        '--live-file "${LAST_SUCCESSFUL_DEPLOY_COMMIT_FILE}"',
        '--event "${EVENT_NAME}"',
        '--run-attempt "${RUN_ATTEMPT}"',
        '--run-created-at "${RUN_CREATED_AT}"',
        '--allow-non-fast-forward "${ALLOW_NON_FF:-false}"',
        '--expected-live-sha "${EXPECTED_LIVE_SHA:-}"',
    ):
        assert flag in run, flag
    assert "actions/runs/${GITHUB_RUN_ID}" in run
    # A failed SSH read must reach the helper as a failure, not as "no baseline".
    assert "LIVE_READ=failed" in run


def test_deploy_job_token_can_read_its_own_run(workflow):
    deploy = workflow["jobs"]["deploy"]
    assert deploy["permissions"] == {"contents": "read", "actions": "read"}


def test_guard_runs_before_any_production_mutation(workflow):
    deploy = workflow["jobs"]["deploy"]
    guard, _ = _step(deploy, "Guard against skipping")
    for mutation in ("Transfer tested release archive", "Run remote deploy script"):
        index, _ = _step(deploy, mutation)
        assert guard < index, mutation
    # The helper is the WORKFLOW commit's own (the job checks out no ref), so a
    # rollback to an older target cannot remove the guard it is judged by.
    _, checkout = _step(deploy, "Checkout")
    assert "ref" not in (checkout.get("with") or {})


# ── the step's shell glue, run for real with fake ssh / gh ───────────


#: The fake ``ssh`` runs the step's REAL remote command locally, against a
#: temporary state file, so the absent / empty / malformed / ok distinction is
#: tested where it is made rather than assumed.
_REMOTE_SSH = 'exec bash -c "${@: -1}"'


def _run_guard_step(
    history,
    workflow,
    tmp_path,
    *,
    state: str | None,
    ssh: str = _REMOTE_SSH,
    gh: str | None = None,
    attempt: str = "1",
):
    """Run the guard step's shell for real.

    ``state`` is the box's state-file contents; ``None`` means the file does
    not exist.  ``sleep`` is faked (and logged) so retries cost no time.
    """
    bash = shutil.which("bash")
    if bash is None:
        pytest.skip("bash is required to run the workflow step")
    _, guard = _step(workflow["jobs"]["deploy"], "Guard against skipping")
    repo = history["repo"]
    (repo / "scripts").mkdir(exist_ok=True)
    shutil.copy(ROOT / "scripts" / "deploy_ancestry_guard.py", repo / "scripts")
    tmp_path.mkdir(parents=True, exist_ok=True)
    state_file = tmp_path / "box" / "last_successful_deploy_commit"
    state_file.parent.mkdir(parents=True)
    if state is not None:
        state_file.write_text(state, encoding="utf-8")
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir(parents=True)
    sleep_log = tmp_path / "sleep.log"
    if gh is None:
        gh = f"echo {_now_iso()}"
    for name, body in (("ssh", ssh), ("gh", gh), ("sleep", f'echo "$1" >> "{sleep_log}"')):
        fake = bin_dir / name
        fake.write_text(f"#!/usr/bin/env bash\n{body}\n", encoding="utf-8")
        fake.chmod(0o755)
    github_env = tmp_path / "github_env"
    github_env.write_text("", encoding="utf-8")
    env = {
        "PATH": f"{bin_dir}{os.pathsep}{os.environ['PATH']}",
        "HOME": str(tmp_path),
        "GITHUB_ENV": str(github_env),
        "GITHUB_REPOSITORY": "owner/repo",
        "GITHUB_RUN_ID": "1",
        "DEPLOY_PORT_RESOLVED": "22",
        "DEPLOY_USER_RESOLVED": "deploy",
        "DEPLOY_HOST_RESOLVED": "box.invalid",
        "DEPLOY_KEY_FILE": "/dev/null",
        "DEPLOY_KNOWN_HOSTS_FILE": "/dev/null",
        "DEPLOY_TARGET_SHA": history["C"],
        "LAST_SUCCESSFUL_DEPLOY_COMMIT_FILE": str(state_file),
        "ALLOW_NON_FF": "",
        "EXPECTED_LIVE_SHA": "",
        "EVENT_NAME": "push",
        "RUN_ATTEMPT": attempt,
    }
    result = subprocess.run(
        [bash, "-c", guard["run"]],
        cwd=repo,
        env=env,
        capture_output=True,
        text=True,
        timeout=60,
    )
    sleeps = sleep_log.read_text(encoding="utf-8").split() if sleep_log.exists() else []
    return result, github_env.read_text(encoding="utf-8"), state_file, sleeps


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _counting_gh(tmp_path: Path, fails: int) -> str:
    """A fake ``gh`` that fails its first ``fails`` calls, then answers."""
    counter = tmp_path / "gh.calls"
    return (
        f'n=$(( $(cat "{counter}" 2>/dev/null || echo 0) + 1 )); echo "$n" > "{counter}"\n'
        f'if [ "$n" -le {fails} ]; then exit 1; fi\n'
        f"echo {_now_iso()}"
    )


def _gh_calls(tmp_path: Path) -> int:
    return int((tmp_path / "gh.calls").read_text(encoding="utf-8"))


def test_step_deploys_forward_and_exports_the_target(history, workflow, tmp_path):
    result, github_env, _, _ = _run_guard_step(
        history, workflow, tmp_path, state=f"{history['B']}\n"
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert "Fast-forward deploy" in result.stdout
    assert f"DEPLOY_TARGET_SHA={history['C']}" in github_env


def test_step_treats_an_absent_state_file_as_no_baseline(history, workflow, tmp_path):
    result, _, _, _ = _run_guard_step(history, workflow, tmp_path, state=None)
    assert result.returncode == 0, result.stdout + result.stderr
    assert "No deploy baseline" in result.stdout


@pytest.mark.parametrize("contents", ["", "\n", "  \t\n  \n"], ids=["empty", "newline", "blank"])
def test_step_refuses_an_empty_state_file(history, workflow, tmp_path, contents):
    result, github_env, state_file, _ = _run_guard_step(history, workflow, tmp_path, state=contents)
    assert result.returncode == 1, result.stdout + result.stderr
    assert "::error title=Empty deploy baseline::" in result.stdout
    assert f"{state_file} exists on the box but is empty" in result.stdout
    assert "No deploy baseline" not in result.stdout
    assert f"DEPLOY_TARGET_SHA={history['C']}" in github_env


def test_step_refuses_a_malformed_state_file(history, workflow, tmp_path):
    result, _, _, _ = _run_guard_step(history, workflow, tmp_path, state="deploy-in-progress\n")
    assert result.returncode == 1, result.stdout + result.stderr
    assert "::error title=Unreadable deploy baseline::" in result.stdout


def test_step_fails_closed_when_the_state_file_cannot_be_read(history, workflow, tmp_path):
    # A directory where the file should be: it exists, but reading it fails.
    result, _, _, _ = _run_guard_step(
        history,
        workflow,
        tmp_path,
        state=None,
        ssh=f'mkdir -p "$LAST_SUCCESSFUL_DEPLOY_COMMIT_FILE"\n{_REMOTE_SSH}',
    )
    assert result.returncode == 1, result.stdout + result.stderr
    assert "Cannot read the production baseline" in result.stdout


def test_step_fails_closed_when_the_baseline_read_fails(history, workflow, tmp_path):
    result, github_env, _, _ = _run_guard_step(
        history, workflow, tmp_path, state=f"{history['B']}\n", ssh="exit 255"
    )
    assert result.returncode == 1
    assert "Cannot read the production baseline" in result.stdout
    assert f"DEPLOY_TARGET_SHA={history['C']}" in github_env


def test_step_fails_closed_when_the_ssh_output_is_unrecognised(history, workflow, tmp_path):
    # e.g. a login banner on stdout: never guess which part is the commit.
    result, _, _, _ = _run_guard_step(
        history, workflow, tmp_path, state=None, ssh=f"echo {history['B']}"
    )
    assert result.returncode == 1, result.stdout + result.stderr
    assert "Cannot read the production baseline" in result.stdout


def test_step_retries_the_run_api_before_failing_closed(history, workflow, tmp_path):
    result, _, _, sleeps = _run_guard_step(
        history, workflow, tmp_path, state=f"{history['B']}\n", gh=_counting_gh(tmp_path, 2)
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert "Fast-forward deploy" in result.stdout
    assert _gh_calls(tmp_path) == 3
    assert len(sleeps) == 2, sleeps


def test_step_fails_closed_when_the_run_api_is_unreadable(history, workflow, tmp_path):
    result, _, _, sleeps = _run_guard_step(
        history, workflow, tmp_path, state=f"{history['B']}\n", gh=_counting_gh(tmp_path, 99)
    )
    assert result.returncode == 1
    assert "Cannot verify run freshness" in result.stdout
    # Bounded: three attempts, two short waits, then the helper fails closed.
    assert _gh_calls(tmp_path) == 3
    assert len(sleeps) == 2 and all(0 < float(s) <= 10 for s in sleeps), sleeps
    rerun, _, _, _ = _run_guard_step(
        history,
        workflow,
        tmp_path / "rerun",
        state=f"{history['B']}\n",
        gh="exit 1",
        attempt="2",
    )
    assert rerun.returncode == 0, rerun.stdout + rerun.stderr
