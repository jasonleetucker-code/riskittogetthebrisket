"""Test evidence from independently retrieved CI records for the pinned revision.

No network: ``gh`` is replaced by a recording fake, and history comes from a
throwaway git repository with a trusted ``main``. Covers a run that declares its
regression test and success while CI failed at that revision; records for another
revision or repository; a PR run whose base branch carries a weakened workflow; an
artifact whose chosen start hides an earlier gate edit; gate-script and conftest
edits; and malformed, truncated or unusable responses.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
AGENT_EVALS = REPO / "agent-evals"
sys.path.insert(0, str(AGENT_EVALS))

from graders.ci_evidence import CiRuns, fetch_workflow_runs, workflow_verdict  # noqa: E402
from graders.deterministic import (  # noqa: E402
    NOT_CHECKED,
    VERIFIED_AGAINST_ARTIFACT,
    CaseError,
    grade_file,
    validate_case_shape,
)
from graders.diff_evidence import gate_changes  # noqa: E402

CASE_ID = "missing-never-zero-ros-playoff-odds"
SLUG = "o/r"
WORKFLOW = ".github/workflows/pr-validation.yml"
CHECK = f"ci_workflow:{WORKFLOW}"
FIXTURE = Path(__file__).resolve().parent / "fixtures" / "missing_never_zero_pass.json"
CODE = {"src/ros/playoff_sim.py": "a\n", "tests/ros/test_playoff_sim.py": "a\n"}


def _git(repo: Path, *args: str) -> str:
    return subprocess.check_output(["git", "-C", str(repo), *args], text=True).strip()


def _commit(repo: Path, files: dict[str, str], message: str) -> str:
    for rel, text in files.items():
        path = repo / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
    _git(repo, "add", "-A")
    _git(repo, "-c", "user.name=t", "-c", "user.email=t@example.invalid", "commit", "-qm", message)
    return _git(repo, "rev-parse", "HEAD")


@pytest.fixture(scope="module")
def repo(tmp_path_factory):
    root = tmp_path_factory.mktemp("ci") / "repo"
    root.mkdir()
    _git(root, "init", "-q")
    _git(root, "checkout", "-q", "-b", "main")
    base = _commit(root, {**CODE, WORKFLOW: "on: pull_request\n"}, "base")
    _git(root, "checkout", "-q", "-b", "work")
    fixed = _commit(root, {"src/ros/playoff_sim.py": "b\n"}, "fix")
    # An earlier commit weakens the gate; the artifact then pins start *after* it.
    weakened = _commit(root, {WORKFLOW: "exit 0\n"}, "weaken the gate")
    hidden = _commit(root, {"src/ros/playoff_sim.py": "c\n"}, "fix on top")
    _git(root, "checkout", "-q", "-b", "conftest", fixed)
    skip_all = _commit(root, {"tests/conftest.py": "skip everything\n"}, "skip all tests")
    return {
        "root": root,
        "base": base,
        "fixed": fixed,
        "weakened": weakened,
        "hidden": hidden,
        "skip_all": skip_all,
    }


def _artifact(tmp_path, start, end, changed) -> Path:
    artifact = json.loads(FIXTURE.read_text(encoding="utf-8"))
    artifact.update(repo_head_start=start, repo_head_end=end, changed_files=changed)
    path = tmp_path / "artifact.json"
    path.write_text(json.dumps(artifact), encoding="utf-8")
    return path


def _run(head, conclusion="success", *, event="pull_request", **k):
    return {
        "id": k.get("id", 1),
        "path": k.get("path", WORKFLOW),
        "head_sha": head,
        "event": event,
        "status": k.get("status", "completed"),
        "conclusion": conclusion,
        "run_started_at": k.get("started", "2026-09-30T12:00:00Z"),
        "created_at": k.get("started", "2026-09-30T12:00:00Z"),
        "run_attempt": k.get("attempt", 1),
        "repository": {"full_name": SLUG},
        "head_repository": {"full_name": k.get("head_repo", SLUG)},
    }


def _fetcher(*runs, bases=("main",)):
    calls = []

    def fetch(slug, head):
        calls.append((slug, head))
        return CiRuns(tuple(runs), head, None, slug, tuple(bases))

    fetch.calls = calls
    return fetch


def _grade(repo, path, fetch, **extra):
    options = {"repo": repo["root"], "ci_repo": SLUG, "trusted_ref": "main", "fetch_runs": fetch}
    return grade_file(CASE_ID, path, **{**options, **extra})


def _entry(result):
    return {e["check"]: e for e in result.evidence}[CHECK]


# --- retrieval --------------------------------------------------------------------


class FakeGh:
    def __init__(self, *responses, raises=None):
        self.responses, self.raises, self.argv = list(responses), raises, []

    def __call__(self, argv, **kwargs):
        self.argv.append((argv, kwargs))
        if self.raises:
            raise self.raises
        stdout, code = self.responses.pop(0)
        return subprocess.CompletedProcess(argv, code, stdout, b"")


def _runs_body(runs, total=None):
    count = len(runs) if total is None else total
    return json.dumps({"total_count": count, "workflow_runs": runs}).encode(), 0


def _pulls_body(*bases):
    return json.dumps([{"base": {"ref": b}} for b in bases]).encode(), 0


def test_fetch_reads_two_fixed_endpoints_for_the_pinned_revision():
    sha = "a" * 40
    gh = FakeGh(_runs_body([_run(sha)]), _pulls_body("main"))
    result = fetch_workflow_runs(SLUG, sha, run=gh)
    assert len(result.runs) == 1 and result.pull_bases == ("main",) and result.slug == SLUG
    assert [argv for argv, _ in gh.argv] == [
        ["gh", "api", f"repos/o/r/actions/runs?head_sha={sha}&per_page=100"],
        ["gh", "api", f"repos/o/r/commits/{sha}/pulls?per_page=100"],
    ]
    assert all("shell" not in kwargs and kwargs["timeout"] > 0 for _, kwargs in gh.argv)


@pytest.mark.parametrize(
    "slug", ["owner", "a/b/c", "../x", "o/..", "a b/c", "o/r?x=1", "https://x/y"]
)
def test_invalid_repository_slug_never_reaches_gh(slug):
    gh = FakeGh()
    assert fetch_workflow_runs(slug, "a" * 40, run=gh).reason == "ci_repository_invalid"
    assert gh.argv == []


@pytest.mark.parametrize("head", ["HEAD", "a" * 39, "A" * 40, "a" * 40 + "&per_page=1"])
def test_revisions_that_are_not_full_shas_never_reach_gh(head):
    gh = FakeGh()
    assert fetch_workflow_runs(SLUG, head, run=gh).reason == "revision_not_full_sha"
    assert fetch_workflow_runs(SLUG, None, run=gh).reason == "no_pinned_revisions"
    assert gh.argv == []


@pytest.mark.parametrize(
    ("responses", "raises", "reason"),
    [
        ([(b"", 1)], None, "ci_unavailable"),
        ([], OSError("no gh"), "ci_unavailable"),
        ([], subprocess.TimeoutExpired("gh", 30), "ci_unavailable"),
        ([(b"{not json", 0)], None, "ci_response_malformed"),
        ([(b'{"workflow_runs": 5, "total_count": 5}', 0)], None, "ci_response_malformed"),
        ([_runs_body([_run("a" * 40)], total=250)], None, "ci_listing_truncated"),
        ([(b" " * (2 * 1024 * 1024 + 1), 0)], None, "ci_unavailable"),
        ([_runs_body([]), (b"", 1)], None, "ci_unavailable"),
        ([_runs_body([]), (b'[{"base": 3}]', 0)], None, "ci_response_malformed"),
    ],
)
def test_unusable_responses_are_never_partial_evidence(responses, raises, reason):
    result = fetch_workflow_runs(SLUG, "a" * 40, run=FakeGh(*responses, raises=raises))
    assert result.runs is None and result.reason == reason


# --- verdicts ---------------------------------------------------------------------


def _verdict(head, *runs, bases=("main",)):
    return workflow_verdict(CiRuns(runs, head, None, SLUG, bases), WORKFLOW, trusted_base="main")


def test_verdict_counts_only_this_repository_this_revision_and_trusted_events():
    head = "a" * 40
    assert _verdict(head, _run("b" * 40))[1] == "no_ci_run_for_revision"
    assert _verdict(head, _run(head, head_repo="fork/r"))[1] == "no_ci_run_for_revision"
    assert _verdict(head, _run(head, event="pull_request_target"))[1] == "no_ci_run_for_revision"
    other_file = _run(head, path=".github/workflows/fast-gate.yml")
    assert _verdict(head, other_file)[1] == "no_ci_run_for_revision"


def test_the_run_that_started_last_decides():
    head = "a" * 40
    older_fail = _run(head, "failure", id=1, started="2026-09-30T10:00:00Z")
    newer_pass = _run(head, "success", id=2, started="2026-09-30T11:00:00Z")
    assert _verdict(head, older_fail, newer_pass) == ("success", "run 2 (pull_request)")
    assert _verdict(head, _run(head, None, status="in_progress"))[1].startswith("ci_run_incomplete")
    assert _verdict(head, _run(head, "failure"))[0] == "failure"


def test_pr_runs_need_every_associated_pr_to_target_the_trusted_base():
    head = "a" * 40
    assert _verdict(head, _run(head), bases=("main", "claude/x"))[1].startswith(
        "ci_base_not_trusted"
    )
    assert _verdict(head, _run(head), bases=())[1].startswith("ci_base_unproven")
    # A push run executes the workflow at head_sha itself; no PR base is involved.
    assert _verdict(head, _run(head, event="push"), bases=())[0] == "success"


def test_malformed_run_fields_are_not_a_crash():
    head = "a" * 40
    tied = [_run(head, attempt="2"), _run(head, id=2)]
    assert _verdict(head, *tied) == ("not_checked", "ci_response_malformed")


# --- gate identity ----------------------------------------------------------------


def test_gate_changes_are_measured_from_the_trusted_ref_not_the_artifact_start(repo):
    hidden = gate_changes(repo["root"], "main", repo["hidden"])
    assert hidden.files == (WORKFLOW,)  # visible though the artifact would start after it
    assert gate_changes(repo["root"], "main", repo["fixed"]).files == ()
    assert gate_changes(repo["root"], "main", repo["skip_all"]).files == ("tests/conftest.py",)
    assert gate_changes(repo["root"], "--output=x", repo["fixed"]).reason == "trusted_ref_invalid"
    assert gate_changes(repo["root"], "nope", repo["fixed"]).reason == "trusted_ref_unresolvable"


# --- grading ----------------------------------------------------------------------


def test_green_ci_with_trusted_gates_is_verified(repo, tmp_path):
    fetch = _fetcher(_run(repo["fixed"]))
    path = _artifact(tmp_path, repo["base"], repo["fixed"], ["src/ros/playoff_sim.py"])
    result = _grade(repo, path, fetch)
    assert result.passed, result.failures
    assert _entry(result)["level"] == VERIFIED_AGAINST_ARTIFACT
    assert fetch.calls == [(SLUG, repo["fixed"])]


def test_self_reported_success_fails_when_ci_failed_at_that_revision(repo, tmp_path):
    fetch = _fetcher(_run(repo["fixed"], "failure", id=77))
    path = _artifact(tmp_path, repo["base"], repo["fixed"], ["src/ros/playoff_sim.py"])
    result = _grade(repo, path, fetch)
    assert not result.passed
    assert any("run 77" in f and "'failure'" in f for f in result.failures)


def test_start_chosen_to_hide_a_gate_edit_does_not_verify(repo, tmp_path):
    # The artifact's own diff (weakened..hidden) omits the workflow edit; the trusted
    # merge-base does not.
    fetch = _fetcher(_run(repo["hidden"]))
    path = _artifact(tmp_path, repo["weakened"], repo["hidden"], ["src/ros/playoff_sim.py"])
    entry = _entry(_grade(repo, path, fetch))
    assert entry["level"] == NOT_CHECKED
    assert entry["reason"].startswith("ci_gate_changed_in_run") and WORKFLOW in entry["reason"]
    assert not _grade(repo, path, fetch, require_verified_ci=True).passed


def test_conftest_edit_is_a_gate_change(repo, tmp_path):
    fetch = _fetcher(_run(repo["skip_all"]))
    path = _artifact(tmp_path, repo["fixed"], repo["skip_all"], ["tests/conftest.py"])
    assert "tests/conftest.py" in _entry(_grade(repo, path, fetch))["reason"]


def test_pr_run_against_an_untrusted_base_does_not_verify(repo, tmp_path):
    fetch = _fetcher(_run(repo["fixed"]), bases=("claude/weakened",))
    path = _artifact(tmp_path, repo["base"], repo["fixed"], ["src/ros/playoff_sim.py"])
    assert _entry(_grade(repo, path, fetch))["reason"].startswith("ci_base_not_trusted")


def test_without_trusted_history_a_green_run_stays_unverified(repo, tmp_path):
    fetch = _fetcher(_run(repo["fixed"]))
    path = _artifact(tmp_path, repo["base"], repo["fixed"], ["src/ros/playoff_sim.py"])
    no_ref = _grade(repo, path, fetch, trusted_ref=None)
    assert _entry(no_ref)["reason"] == "workflow_identity_unverified"
    no_repo = grade_file(CASE_ID, path, ci_repo=SLUG, trusted_ref="main", fetch_runs=fetch)
    assert _entry(no_repo)["reason"] == "workflow_identity_unverified"


def test_missing_ci_evidence_stays_unverified_and_can_be_required(repo, tmp_path):
    path = _artifact(tmp_path, repo["base"], repo["fixed"], ["src/ros/playoff_sim.py"])
    lenient = _grade(repo, path, _fetcher())
    assert lenient.passed and _entry(lenient)["reason"] == "no_ci_run_for_revision"
    assert not _grade(repo, path, _fetcher(), require_verified_ci=True).passed
    offline = grade_file(CASE_ID, path, repo=repo["root"])
    assert _entry(offline)["reason"] == "no_ci_repository"


def test_operator_faults_are_grading_errors(repo, tmp_path):
    path = _artifact(tmp_path, repo["base"], repo["fixed"], ["src/ros/playoff_sim.py"])

    def broken(slug, head):
        return CiRuns(None, head, "ci_unavailable")

    with pytest.raises(CaseError, match="ci_unavailable"):
        _grade(repo, path, broken)
    with pytest.raises(CaseError, match="trusted ref"):
        _grade(repo, path, _fetcher(_run(repo["fixed"])), trusted_ref="-x")


@pytest.mark.parametrize(
    "workflows",
    [[], "pr.yml", ["../evil.yml"], ["scripts/x.yml"], [".github/workflows/../x.yml"], [3]],
)
def test_required_ci_workflows_must_be_workflow_paths(workflows):
    case = {
        "id": "x",
        "category": "missing_never_zero",
        "title": "t",
        "objective": "o",
        "based_on": "b",
        "acceptance_criteria": ["a"],
        "grading": {"required_ci_workflows": workflows},
    }
    with pytest.raises(CaseError, match="required_ci_workflows"):
        validate_case_shape(case)


def test_cli_requires_ci_repo_for_strict_ci():
    result = subprocess.run(
        [
            sys.executable,
            str(AGENT_EVALS / "run_eval.py"),
            "--case",
            CASE_ID,
            "--artifact",
            str(FIXTURE),
            "--require-verified-ci",
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 2
    assert "--require-verified-ci needs --ci-repo" in result.stderr
