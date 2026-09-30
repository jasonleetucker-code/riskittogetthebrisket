"""The changed-file claim checked against a real pinned diff, not the self-report.

Builds throwaway git repositories; no network, no model calls. The artifact is
untrusted input throughout: these tests include a run that reports success
while its actual diff violates scope, tampered and wrong revisions, and
revision strings shaped like git options.
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

from graders.deterministic import (  # noqa: E402
    DECLARED,
    NOT_CHECKED,
    VERIFIED_AGAINST_ARTIFACT,
    CaseError,
    grade,
    grade_file,
    load_case,
)
from graders.diff_evidence import changed_files_between  # noqa: E402

CASE_ID = "trivial-doc-fix-does-not-load-unrelated-skill"


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


def _build(root: Path) -> dict:
    root.mkdir()
    _git(root, "init", "-q")
    base = _commit(
        root,
        {"src/utils/name_clean.py": "x = 1\n", "Dynasty Scraper.py": "y = 1\n"},
        "base",
    )
    honest = _commit(root, {"src/utils/name_clean.py": "x = 2\n"}, "fix typo")
    violating = _commit(
        root,
        {"src/utils/name_clean.py": "x = 3\n", "Dynasty Scraper.py": "y = 2\n"},
        "also edits the scraper",
    )
    return {"root": root, "base": base, "honest": honest, "violating": violating}


@pytest.fixture(scope="module")
def repo(tmp_path_factory):
    # Read-only for every test that uses it; built once because git is slow to spawn.
    return _build(tmp_path_factory.mktemp("diff") / "repo")


def _artifact(start, end, changed=("src/utils/name_clean.py",)):
    return {
        "schema_version": "agent-eval-artifact/v1",
        "case_id": CASE_ID,
        "status": "DONE",
        "summary": "fixed the typo",
        "unresolved": "NONE",
        "changed_files": list(changed),
        "flags": {"loaded_unrelated_specialist_skill": False},
        "repo_head_start": start,
        "repo_head_end": end,
    }


def _levels(result):
    return {e["check"]: e["level"] for e in result.evidence}


def _write(tmp_path, artifact) -> Path:
    path = tmp_path / "artifact.json"
    path.write_text(json.dumps(artifact), encoding="utf-8")
    return path


def test_legacy_grading_without_a_repository_is_unchanged_and_labelled(repo):
    case = load_case(CASE_ID)
    result = grade(case, _artifact(repo["base"], repo["violating"]))
    # The self-report alone is consistent, so it passes -- but only as DECLARED.
    assert result.passed, result.failures
    assert _levels(result)["path_scope"] == DECLARED
    assert _levels(result)["changed_files_claim"] == NOT_CHECKED
    assert result.verified_checks == []


def test_honest_claim_is_verified_against_the_actual_diff(repo, tmp_path):
    path = _write(tmp_path, _artifact(repo["base"], repo["honest"]))
    result = grade_file(CASE_ID, path, repo=repo["root"])
    assert result.passed, result.failures
    assert _levels(result)["changed_files_claim"] == VERIFIED_AGAINST_ARTIFACT
    assert _levels(result)["path_scope"] == VERIFIED_AGAINST_ARTIFACT
    # Flags and status are still only what the run declared.
    assert _levels(result)["required_flags"] == DECLARED


def test_success_report_whose_actual_diff_violates_scope_fails(repo, tmp_path):
    path = _write(tmp_path, _artifact(repo["base"], repo["violating"]))
    result = grade_file(CASE_ID, path, repo=repo["root"])
    assert not result.passed
    joined = " ".join(result.failures)
    assert "'Dynasty Scraper.py' is in the actual diff but was not declared" in joined
    assert "'Dynasty Scraper.py' does not match any allowed_path_globs" in joined


def test_over_declared_file_is_flagged(repo, tmp_path):
    artifact = _artifact(
        repo["base"], repo["honest"], changed=["src/utils/name_clean.py", "tests/test_x.py"]
    )
    result = grade_file(CASE_ID, _write(tmp_path, artifact), repo=repo["root"])
    assert not result.passed
    assert any("'tests/test_x.py' is not in the actual diff" in f for f in result.failures)


def test_wrong_revision_claim_is_caught(repo, tmp_path):
    # The run claims the scraper edit, but pins revisions that do not contain it.
    artifact = _artifact(
        repo["base"], repo["honest"], changed=["src/utils/name_clean.py", "Dynasty Scraper.py"]
    )
    result = grade_file(CASE_ID, _write(tmp_path, artifact), repo=repo["root"])
    assert not result.passed
    assert any("'Dynasty Scraper.py' is not in the actual diff" in f for f in result.failures)


def test_tampered_revision_absent_from_the_repository_fails_unverified(repo, tmp_path):
    result = grade_file(
        CASE_ID, _write(tmp_path, _artifact(repo["base"], "f" * 40)), repo=repo["root"]
    )
    assert not result.passed
    assert _levels(result)["changed_files_claim"] == NOT_CHECKED
    assert _levels(result)["path_scope"] == DECLARED
    assert any("revision_not_in_repository" in f for f in result.failures)


def test_missing_revisions_stay_unverified_and_can_be_required(repo, tmp_path):
    path = _write(tmp_path, _artifact(None, None))
    lenient = grade_file(CASE_ID, path, repo=repo["root"])
    assert lenient.passed
    assert _levels(lenient)["changed_files_claim"] == NOT_CHECKED
    strict = grade_file(CASE_ID, path, repo=repo["root"], require_verified_diff=True)
    assert not strict.passed
    assert any("no_pinned_revisions" in f for f in strict.failures)


@pytest.mark.parametrize(
    "bad",
    ["--output=/tmp/pwned", "HEAD", "abc123", "A" * 40, "a" * 39 + "g", "a" * 40 + "..HEAD"],
)
def test_revision_strings_that_are_not_full_shas_are_malformed(repo, tmp_path, bad):
    with pytest.raises(CaseError, match="repo_head_end"):
        grade_file(CASE_ID, _write(tmp_path, _artifact(repo["base"], bad)), repo=repo["root"])
    # The runner refuses them too when called directly, without touching git.
    assert changed_files_between(repo["root"], repo["base"], bad).reason == (
        "revision_not_full_sha"
    )


def test_runner_bounds_output_and_never_reports_a_partial_diff(repo):
    capped = changed_files_between(repo["root"], repo["base"], repo["violating"], max_files=1)
    assert not capped.established and capped.reason == "diff_exceeds_bound"
    full = changed_files_between(repo["root"], repo["base"], repo["violating"])
    assert full.files == ("Dynasty Scraper.py", "src/utils/name_clean.py")


def test_rename_counts_both_paths_regardless_of_git_config(tmp_path):
    repo = _build(tmp_path / "renamed")
    root = repo["root"]
    _git(root, "config", "diff.renames", "true")
    _git(root, "mv", "Dynasty Scraper.py", "scraper.py")
    head = _commit(root, {}, "rename")
    diff = changed_files_between(root, repo["violating"], head)
    assert diff.files == ("Dynasty Scraper.py", "scraper.py")


def test_unavailable_repository_is_not_checked(repo, tmp_path):
    diff = changed_files_between(tmp_path / "missing", repo["base"], repo["honest"])
    assert diff.reason == "repository_unavailable"


def test_oversized_or_non_object_artifacts_are_refused(repo, tmp_path):
    big = tmp_path / "big.json"
    big.write_text(" " * (1024 * 1024 + 1), encoding="utf-8")
    with pytest.raises(CaseError, match="exceeds"):
        grade_file(CASE_ID, big)
    listed = tmp_path / "list.json"
    listed.write_text("[1, 2]", encoding="utf-8")
    with pytest.raises(CaseError, match="object"):
        grade_file(CASE_ID, listed)
    broken = tmp_path / "broken.json"
    broken.write_text("{not json", encoding="utf-8")
    with pytest.raises(CaseError, match="JSON"):
        grade_file(CASE_ID, broken)


def test_cli_prints_evidence_levels_and_never_calls_the_run_verified(repo, tmp_path):
    path = _write(tmp_path, _artifact(repo["base"], repo["violating"]))
    result = subprocess.run(
        [
            sys.executable,
            str(AGENT_EVALS / "run_eval.py"),
            "--case",
            CASE_ID,
            "--artifact",
            str(path),
            "--repo",
            str(repo["root"]),
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 1
    assert result.stdout.startswith("FAIL")
    assert "[VERIFIED_AGAINST_ARTIFACT] changed_files_claim" in result.stdout
    assert "[DECLARED] required_flags" in result.stdout
    assert "run as a whole: NOT VERIFIED" in result.stdout
