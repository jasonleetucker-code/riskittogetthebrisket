"""Test evidence from independently retrieved CI records for the pinned revision.

No network: ``gh`` is replaced by a recording fake, and the pinned diff comes
from a throwaway git repository. Covers a run that declares its regression test
and success while CI failed at that revision, records for a different revision,
superseded attempts, a run that edited its own workflow, and malformed or
truncated responses.
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

CASE_ID = "missing-never-zero-ros-playoff-odds"
WORKFLOW = ".github/workflows/pr-validation.yml"
CHECK = f"ci_workflow:{WORKFLOW}"
FIXTURE = Path(__file__).resolve().parent / "fixtures" / "missing_never_zero_pass.json"


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
    base = _commit(
        root,
        {
            "src/ros/playoff_sim.py": "a\n",
            "tests/ros/test_playoff_sim.py": "a\n",
            WORKFLOW: "on: pull_request\n",
        },
        "base",
    )
    fixed = _commit(
        root,
        {"src/ros/playoff_sim.py": "b\n", "tests/ros/test_playoff_sim.py": "b\n"},
        "fix",
    )
    judge_edited = _commit(
        root,
        {"src/ros/playoff_sim.py": "c\n", "tests/ros/test_playoff_sim.py": "c\n", WORKFLOW: "x\n"},
        "fix and weaken the gate",
    )
    return {"root": root, "base": base, "fixed": fixed, "judge_edited": judge_edited}


def _artifact(tmp_path, start, end, changed=None) -> Path:
    artifact = json.loads(FIXTURE.read_text(encoding="utf-8"))
    artifact.update(repo_head_start=start, repo_head_end=end)
    if changed is not None:
        artifact["changed_files"] = changed
    path = tmp_path / "artifact.json"
    path.write_text(json.dumps(artifact), encoding="utf-8")
    return path


def _run(head, conclusion="success", *, status="completed", created="2026-09-30T12:00:00Z", **k):
    return {
        "id": k.get("id", 1),
        "path": k.get("path", WORKFLOW),
        "head_sha": head,
        "event": "pull_request",
        "status": status,
        "conclusion": conclusion,
        "created_at": created,
        "run_attempt": k.get("attempt", 1),
    }


def _fetcher(*runs):
    calls = []

    def fetch(slug, head):
        calls.append((slug, head))
        return CiRuns(tuple(runs), head)

    fetch.calls = calls
    return fetch


def _level(result):
    return {e["check"]: e for e in result.evidence}[CHECK]


# --- retrieval --------------------------------------------------------------------


class FakeGh:
    def __init__(self, stdout=b"", returncode=0, raises=None):
        self.stdout, self.returncode, self.raises, self.argv = stdout, returncode, raises, []

    def __call__(self, argv, **kwargs):
        self.argv.append((argv, kwargs))
        if self.raises:
            raise self.raises
        return subprocess.CompletedProcess(argv, self.returncode, self.stdout, b"")


def _body(runs, total=None):
    return json.dumps(
        {"total_count": len(runs) if total is None else total, "workflow_runs": runs}
    ).encode()


def test_fetch_reads_one_fixed_endpoint_for_the_pinned_revision():
    sha = "a" * 40
    gh = FakeGh(_body([_run(sha)]))
    result = fetch_workflow_runs("owner/repo", sha, run=gh)
    assert result.runs is not None and len(result.runs) == 1
    ((argv, kwargs),) = gh.argv
    assert argv == ["gh", "api", f"repos/owner/repo/actions/runs?head_sha={sha}&per_page=100"]
    assert "shell" not in kwargs and kwargs["timeout"] > 0


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
    assert fetch_workflow_runs("o/r", head, run=gh).reason == "revision_not_full_sha"
    assert gh.argv == []
    assert fetch_workflow_runs("o/r", None, run=gh).reason == "no_pinned_revisions"


@pytest.mark.parametrize(
    ("gh", "reason"),
    [
        (FakeGh(returncode=1), "ci_unavailable"),
        (FakeGh(raises=OSError("no gh")), "ci_unavailable"),
        (FakeGh(raises=subprocess.TimeoutExpired("gh", 30)), "ci_unavailable"),
        (FakeGh(b"{not json"), "ci_response_malformed"),
        (FakeGh(b'{"workflow_runs": 5, "total_count": 5}'), "ci_response_malformed"),
        (FakeGh(_body([_run("a" * 40)], total=250)), "ci_listing_truncated"),
        (FakeGh(b" " * (2 * 1024 * 1024 + 1)), "ci_unavailable"),
    ],
)
def test_unusable_responses_are_never_partial_evidence(gh, reason):
    result = fetch_workflow_runs("o/r", "a" * 40, run=gh)
    assert result.runs is None and result.reason == reason


# --- verdicts ---------------------------------------------------------------------


def test_verdict_counts_only_runs_for_the_pinned_revision_and_the_newest_attempt():
    head = "a" * 40
    other = _run("b" * 40, "success", id=9)  # a green run for a different commit
    assert workflow_verdict(CiRuns((other,), head), WORKFLOW)[0] == "not_checked"
    rerun = CiRuns(
        (
            _run(head, "failure", created="2026-09-30T10:00:00Z", id=1),
            _run(head, "success", created="2026-09-30T11:00:00Z", id=2, attempt=2),
        ),
        head,
    )
    assert workflow_verdict(rerun, WORKFLOW) == ("success", "run 2 (pull_request)")
    pending = CiRuns((_run(head, None, status="in_progress"),), head)
    assert workflow_verdict(pending, WORKFLOW)[1].startswith("ci_run_incomplete")
    assert workflow_verdict(CiRuns((_run(head, "failure"),), head), WORKFLOW)[0] == "failure"
    other_workflow = CiRuns((_run(head, path=".github/workflows/fast-gate.yml"),), head)
    assert workflow_verdict(other_workflow, WORKFLOW)[1] == "no_ci_run_for_revision"


# --- grading ----------------------------------------------------------------------


def test_ci_success_with_an_untouched_workflow_is_verified(repo, tmp_path):
    fetch = _fetcher(_run(repo["fixed"]))
    path = _artifact(tmp_path, repo["base"], repo["fixed"])
    result = grade_file(CASE_ID, path, repo=repo["root"], ci_repo="o/r", fetch_runs=fetch)
    assert result.passed, result.failures
    assert _level(result)["level"] == VERIFIED_AGAINST_ARTIFACT
    assert fetch.calls == [("o/r", repo["fixed"])]


def test_self_reported_success_fails_when_ci_failed_at_that_revision(repo, tmp_path):
    # The artifact declares DONE and regression_test_added; the CI record disagrees.
    fetch = _fetcher(_run(repo["fixed"], "failure", id=77))
    path = _artifact(tmp_path, repo["base"], repo["fixed"])
    result = grade_file(CASE_ID, path, repo=repo["root"], ci_repo="o/r", fetch_runs=fetch)
    assert not result.passed
    assert any("run 77" in f and "'failure'" in f for f in result.failures)


def test_a_run_that_edited_its_own_workflow_cannot_be_verified_by_it(repo, tmp_path):
    fetch = _fetcher(_run(repo["judge_edited"]))
    path = _artifact(
        tmp_path,
        repo["base"],
        repo["judge_edited"],
        changed=["src/ros/playoff_sim.py", "tests/ros/test_playoff_sim.py", WORKFLOW],
    )
    result = grade_file(CASE_ID, path, repo=repo["root"], ci_repo="o/r", fetch_runs=fetch)
    assert _level(result) == {
        "check": CHECK,
        "level": NOT_CHECKED,
        "reason": "workflow_changed_in_run",
    }
    strict = grade_file(
        CASE_ID,
        path,
        repo=repo["root"],
        ci_repo="o/r",
        fetch_runs=fetch,
        require_verified_ci=True,
    )
    assert not strict.passed


def test_ci_success_without_the_pinned_diff_leaves_the_judge_unverified(repo, tmp_path):
    fetch = _fetcher(_run(repo["fixed"]))
    path = _artifact(tmp_path, repo["base"], repo["fixed"])
    result = grade_file(CASE_ID, path, ci_repo="o/r", fetch_runs=fetch)
    assert _level(result)["reason"] == "workflow_identity_unverified"


def test_missing_ci_evidence_stays_unverified_and_can_be_required(repo, tmp_path):
    path = _artifact(tmp_path, repo["base"], repo["fixed"])
    lenient = grade_file(CASE_ID, path, repo=repo["root"], ci_repo="o/r", fetch_runs=_fetcher())
    assert lenient.passed and _level(lenient)["reason"] == "no_ci_run_for_revision"
    strict = grade_file(
        CASE_ID,
        path,
        repo=repo["root"],
        ci_repo="o/r",
        fetch_runs=_fetcher(),
        require_verified_ci=True,
    )
    assert not strict.passed
    # Without --ci-repo nothing is fetched and the check says so.
    offline = grade_file(CASE_ID, path, repo=repo["root"])
    assert _level(offline)["reason"] == "no_ci_repository"


def test_ci_operator_faults_are_grading_errors(repo, tmp_path):
    path = _artifact(tmp_path, repo["base"], repo["fixed"])

    def broken(slug, head):
        return CiRuns(None, head, "ci_unavailable")

    with pytest.raises(CaseError, match="ci_unavailable"):
        grade_file(CASE_ID, path, repo=repo["root"], ci_repo="o/r", fetch_runs=broken)


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


def test_cli_requires_ci_repo_for_strict_ci(tmp_path):
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
