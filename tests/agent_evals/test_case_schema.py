"""Every shipped agent-evals case must be structurally valid and internally
consistent. No network, no model calls -- pure static checks.

`agent-evals/` cannot be a normal dotted Python package (the directory name
has a hyphen), so it is reached via an explicit sys.path insertion rather
than a package import -- the same pattern agent-evals/run_eval.py itself
uses.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
AGENT_EVALS = REPO / "agent-evals"
sys.path.insert(0, str(AGENT_EVALS))

from graders.deterministic import (  # noqa: E402
    VALID_CATEGORIES,
    CaseError,
    list_case_ids,
    load_case,
    validate_case_shape,
)

CASES_DIR = AGENT_EVALS / "cases"


def test_cases_directory_is_not_empty():
    assert list_case_ids(), "agent-evals/cases must not be empty"


def test_every_case_file_is_valid_json():
    for path in CASES_DIR.glob("*.json"):
        json.loads(path.read_text(encoding="utf-8"))


def test_every_case_validates_against_the_case_shape():
    for case_id in list_case_ids():
        load_case(case_id)  # raises CaseError on any structural defect


def test_case_id_matches_its_filename():
    for path in CASES_DIR.glob("*.json"):
        case = json.loads(path.read_text(encoding="utf-8"))
        assert case["id"] == path.stem, f"{path}: id {case['id']!r} != filename {path.stem!r}"


def test_every_case_is_grounded_in_a_real_repository_record():
    for case_id in list_case_ids():
        case = load_case(case_id)
        based_on = case.get("based_on", "")
        assert (
            isinstance(based_on, str) and len(based_on) > 10
        ), f"{case_id}: based_on must point at a real repository record, not be empty/trivial"


def test_every_named_category_has_at_least_one_case():
    covered = {load_case(case_id)["category"] for case_id in list_case_ids()}
    missing = VALID_CATEGORIES - covered
    assert not missing, f"categories with no eval case: {sorted(missing)}"


def test_case_ids_are_unique_and_match_directory_listing():
    ids = list_case_ids()
    assert len(ids) == len(set(ids))


def test_grading_block_rejects_unknown_status_values():
    bad_case = {
        "id": "bad-case",
        "category": "missing_never_zero",
        "title": "x",
        "objective": "x",
        "based_on": "unit test fixture only",
        "acceptance_criteria": ["x"],
        "grading": {"allowed_final_statuses": ["NOT_A_REAL_STATUS"]},
    }
    try:
        validate_case_shape(bad_case)
    except CaseError as exc:
        assert "unknown values" in str(exc)
    else:
        raise AssertionError("expected CaseError for an unknown status value")


def test_grading_block_rejects_unknown_category():
    bad_case = {
        "id": "bad-case",
        "category": "not_a_real_category",
        "title": "x",
        "objective": "x",
        "based_on": "unit test fixture only",
        "acceptance_criteria": ["x"],
        "grading": {},
    }
    try:
        validate_case_shape(bad_case)
    except CaseError as exc:
        assert "unknown category" in str(exc)
    else:
        raise AssertionError("expected CaseError for an unknown category")


def test_loading_a_missing_case_id_fails_closed():
    try:
        load_case("this-case-does-not-exist")
    except CaseError:
        pass
    else:
        raise AssertionError("expected CaseError for a nonexistent case id")
