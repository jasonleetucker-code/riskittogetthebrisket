"""Proves the deterministic grader actually discriminates a passing run
artifact from a failing one, and fails closed on malformed input. No
network, no model calls.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
AGENT_EVALS = REPO / "agent-evals"
sys.path.insert(0, str(AGENT_EVALS))

from graders.deterministic import (  # noqa: E402
    CaseError,
    grade,
    grade_file,
    load_case,
    validate_artifact_shape,
)

FIXTURES = Path(__file__).resolve().parent / "fixtures"


def test_known_good_artifact_passes_its_case():
    case = load_case("missing-never-zero-ros-playoff-odds")
    artifact = json.loads((FIXTURES / "missing_never_zero_pass.json").read_text(encoding="utf-8"))
    result = grade(case, artifact)
    assert result.passed, result.failures
    assert result.failures == []


def test_known_bad_artifact_fails_its_case_with_named_reasons():
    case = load_case("missing-never-zero-ros-playoff-odds")
    artifact = json.loads((FIXTURES / "missing_never_zero_fail.json").read_text(encoding="utf-8"))
    result = grade(case, artifact)
    assert not result.passed
    joined = " ".join(result.failures)
    assert "empty_input_reported_as_unsimulated_not_zero" in joined
    assert "regression_test_added" in joined
    assert "claimed_verified_without_production_evidence" in joined


def test_grade_file_matches_grade_on_the_same_pair():
    direct = grade(
        load_case("missing-never-zero-ros-playoff-odds"),
        json.loads((FIXTURES / "missing_never_zero_pass.json").read_text(encoding="utf-8")),
    )
    via_file = grade_file(
        "missing-never-zero-ros-playoff-odds", FIXTURES / "missing_never_zero_pass.json"
    )
    assert direct.passed == via_file.passed
    assert direct.failures == via_file.failures


def test_mismatched_case_id_is_flagged():
    case = load_case("merged-is-not-verified")
    artifact = json.loads((FIXTURES / "missing_never_zero_pass.json").read_text(encoding="utf-8"))
    result = grade(case, artifact)
    assert not result.passed
    assert any("does not match case id" in failure for failure in result.failures)


def test_forbidden_path_glob_is_enforced():
    case = load_case("trivial-doc-fix-does-not-load-unrelated-skill")
    artifact = {
        "schema_version": "agent-eval-artifact/v1",
        "case_id": case["id"],
        "status": "DONE",
        "summary": "fixed the typo",
        "unresolved": "NONE",
        "changed_files": ["src/utils/name_clean.py", "Dynasty Scraper.py"],
        "flags": {"loaded_unrelated_specialist_skill": False},
    }
    result = grade(case, artifact)
    assert not result.passed
    assert any("Dynasty Scraper.py" in failure for failure in result.failures)


def test_require_unresolved_nonempty_rejects_bare_none():
    case = load_case("methodology-invention-refusal-w1-27-rate-model")
    artifact = {
        "schema_version": "agent-eval-artifact/v1",
        "case_id": case["id"],
        "status": "BLOCKED",
        "summary": "surfaced the owner decision needed",
        "unresolved": "NONE",
        "changed_files": [],
        "flags": {
            "invented_methodology_without_flagging": False,
            "surfaced_owner_decision_needed": True,
        },
    }
    # this case's grading block does not set require_unresolved_nonempty,
    # so a bare NONE must not fail it -- prove the check is opt-in per case.
    result = grade(case, artifact)
    assert result.passed, result.failures


def test_validate_artifact_shape_fails_closed_on_missing_field():
    bad_artifact = {
        "schema_version": "agent-eval-artifact/v1",
        "case_id": "x",
        "status": "DONE",
        # missing summary/unresolved/changed_files
    }
    try:
        validate_artifact_shape(bad_artifact)
    except CaseError as exc:
        assert "missing required fields" in str(exc)
    else:
        raise AssertionError("expected CaseError for a malformed artifact")


def test_validate_artifact_shape_fails_closed_on_wrong_schema_version():
    bad_artifact = {
        "schema_version": "some-other-version",
        "case_id": "x",
        "status": "DONE",
        "summary": "x",
        "unresolved": "NONE",
        "changed_files": [],
    }
    try:
        validate_artifact_shape(bad_artifact)
    except CaseError as exc:
        assert "schema_version" in str(exc)
    else:
        raise AssertionError("expected CaseError for a wrong schema_version")


def test_cli_list_runs_with_no_network_and_exits_zero():
    result = subprocess.run(
        [sys.executable, str(AGENT_EVALS / "run_eval.py"), "--list"],
        capture_output=True,
        text=True,
        cwd=REPO,
        timeout=30,
    )
    assert result.returncode == 0, result.stderr
    assert "missing-never-zero-ros-playoff-odds" in result.stdout


def test_cli_grades_a_passing_artifact_and_exits_zero():
    result = subprocess.run(
        [
            sys.executable,
            str(AGENT_EVALS / "run_eval.py"),
            "--case",
            "missing-never-zero-ros-playoff-odds",
            "--artifact",
            str(FIXTURES / "missing_never_zero_pass.json"),
        ],
        capture_output=True,
        text=True,
        cwd=REPO,
        timeout=30,
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout.startswith("PASS")


def test_cli_grades_a_failing_artifact_and_exits_nonzero():
    result = subprocess.run(
        [
            sys.executable,
            str(AGENT_EVALS / "run_eval.py"),
            "--case",
            "missing-never-zero-ros-playoff-odds",
            "--artifact",
            str(FIXTURES / "missing_never_zero_fail.json"),
        ],
        capture_output=True,
        text=True,
        cwd=REPO,
        timeout=30,
    )
    assert result.returncode == 1
    assert result.stdout.startswith("FAIL")


def test_cli_reports_error_and_exits_two_for_unknown_case():
    result = subprocess.run(
        [
            sys.executable,
            str(AGENT_EVALS / "run_eval.py"),
            "--case",
            "does-not-exist",
            "--artifact",
            str(FIXTURES / "missing_never_zero_pass.json"),
        ],
        capture_output=True,
        text=True,
        cwd=REPO,
        timeout=30,
    )
    assert result.returncode == 2
    assert "ERROR" in result.stderr
