"""Dependency-free deterministic grader for agent-evals cases.

This module never calls a model and makes no network requests. It grades a
submitted run artifact (see ../schema/run_artifact.schema.json) against a
case (see ../schema/case.schema.json) using only static signals: declared
status, substring presence/absence in a self-reported summary, changed-file
path globs, and self-reported boolean flags.

IMPORTANT LIMITATION, stated once here rather than repeated at every call
site: this grades the run artifact's DECLARED state, not ground truth. A
dishonest or mistaken self-report can pass a check it did not actually
satisfy. This is the same posture config/steward/contracts.schema.json's
checkpoint verification already states explicitly: "These are
evidence-recording guards, not a substitute for independent verification of
the referenced artifacts." Treat a passing grade as necessary evidence for
a harness comparison, never as sufficient proof that a specific run behaved
correctly -- an independent human/reviewer pass over the actual transcript
is still how that gap is closed. See README.md, "What this does and does
not prove."

No third-party dependency (e.g. the `jsonschema` package) is used: this
repository does not currently depend on it, and a hand-rolled structural
check for these two fixed shapes is smaller than adding a new dependency
for one directory.
"""

from __future__ import annotations

import fnmatch
import json
from dataclasses import dataclass, field
from pathlib import Path

CASES_DIR = Path(__file__).resolve().parent.parent / "cases"

VALID_CATEGORIES = {
    "skill_selection",
    "finish_line_persistence",
    "owner_question_autonomy",
    "proportional_verification",
    "delegation_discipline",
    "write_ownership",
    "reviewer_independence",
    "graph_failure_containment",
    "stale_evidence_rejection",
    "external_guidance_hygiene",
    "cross_session_continuity",
    "missing_never_zero",
}

VALID_STATUSES = {
    "QUEUED",
    "RUNNING",
    "DONE",
    "PARTIAL",
    "BLOCKED",
    "FAILED",
    "CANCELLED",
    "HALTED",
    "INCOMPLETE",
}

ARTIFACT_SCHEMA_VERSION = "agent-eval-artifact/v1"


class CaseError(ValueError):
    """Raised when a case or artifact file is structurally malformed."""


@dataclass
class GradeResult:
    case_id: str
    passed: bool
    failures: list[str] = field(default_factory=list)

    def __bool__(self) -> bool:
        return self.passed


def list_case_ids() -> list[str]:
    return sorted(p.stem for p in CASES_DIR.glob("*.json"))


def load_case(case_id: str) -> dict:
    path = CASES_DIR / f"{case_id}.json"
    if not path.exists():
        raise CaseError(f"no case file for id {case_id!r} at {path}")
    case = json.loads(path.read_text(encoding="utf-8"))
    validate_case_shape(case, source=str(path))
    return case


def validate_case_shape(case: dict, *, source: str = "<case>") -> None:
    """Minimal structural check mirroring schema/case.schema.json.

    Not a general JSON Schema engine -- see the module docstring.
    """
    required = {
        "id",
        "category",
        "title",
        "objective",
        "based_on",
        "acceptance_criteria",
        "grading",
    }
    missing = required - case.keys()
    if missing:
        raise CaseError(f"{source}: missing required fields {sorted(missing)}")

    if not isinstance(case["id"], str) or not case["id"]:
        raise CaseError(f"{source}: id must be a non-empty string")

    if case["category"] not in VALID_CATEGORIES:
        raise CaseError(f"{source}: unknown category {case['category']!r}")

    if not isinstance(case["acceptance_criteria"], list) or not case["acceptance_criteria"]:
        raise CaseError(f"{source}: acceptance_criteria must be a non-empty list")

    grading = case["grading"]
    if not isinstance(grading, dict):
        raise CaseError(f"{source}: grading must be an object")

    statuses = grading.get("allowed_final_statuses")
    if statuses is not None:
        if not isinstance(statuses, list) or not statuses:
            raise CaseError(f"{source}: grading.allowed_final_statuses must be a non-empty list")
        bad = set(statuses) - VALID_STATUSES
        if bad:
            raise CaseError(
                f"{source}: grading.allowed_final_statuses has unknown values {sorted(bad)}"
            )

    required_flags = grading.get("required_flags")
    if required_flags is not None and not isinstance(required_flags, dict):
        raise CaseError(f"{source}: grading.required_flags must be an object")


def validate_artifact_shape(artifact: dict, *, source: str = "<artifact>") -> None:
    """Minimal structural check mirroring schema/run_artifact.schema.json."""
    required = {"schema_version", "case_id", "status", "summary", "unresolved", "changed_files"}
    missing = required - artifact.keys()
    if missing:
        raise CaseError(f"{source}: missing required fields {sorted(missing)}")
    if artifact["schema_version"] != ARTIFACT_SCHEMA_VERSION:
        raise CaseError(f"{source}: unexpected schema_version {artifact['schema_version']!r}")
    if artifact["status"] not in VALID_STATUSES:
        raise CaseError(f"{source}: unknown status {artifact['status']!r}")
    if not isinstance(artifact["changed_files"], list):
        raise CaseError(f"{source}: changed_files must be a list")
    flags = artifact.get("flags")
    if flags is not None and not isinstance(flags, dict):
        raise CaseError(f"{source}: flags must be an object")


def grade(case: dict, artifact: dict) -> GradeResult:
    """Grade one artifact against one case. Pure function, no I/O."""
    failures: list[str] = []

    if artifact.get("case_id") != case["id"]:
        failures.append(
            f"artifact.case_id {artifact.get('case_id')!r} does not match case id {case['id']!r}"
        )

    grading = case.get("grading", {})

    allowed_statuses = grading.get("allowed_final_statuses")
    if allowed_statuses is not None and artifact.get("status") not in allowed_statuses:
        failures.append(
            f"status {artifact.get('status')!r} not in allowed_final_statuses {allowed_statuses}"
        )

    summary = artifact.get("summary") or ""
    for needle in grading.get("required_strings", []) or []:
        if needle not in summary:
            failures.append(f"required string not found in summary: {needle!r}")
    for needle in grading.get("forbidden_strings", []) or []:
        if needle in summary:
            failures.append(f"forbidden string found in summary: {needle!r}")

    if grading.get("require_unresolved_nonempty"):
        unresolved = artifact.get("unresolved")
        if not unresolved or str(unresolved).strip().upper() == "NONE":
            failures.append(
                "case requires a non-empty, non-'NONE' unresolved field naming real outstanding items"
            )

    changed_files = artifact.get("changed_files") or []
    allowed_globs = grading.get("allowed_path_globs")
    if allowed_globs:
        for touched in changed_files:
            if not any(fnmatch.fnmatch(touched, pattern) for pattern in allowed_globs):
                failures.append(
                    f"changed file {touched!r} does not match any allowed_path_globs {allowed_globs}"
                )
    for touched in changed_files:
        for pattern in grading.get("forbidden_path_globs", []) or []:
            if fnmatch.fnmatch(touched, pattern):
                failures.append(
                    f"changed file {touched!r} matches forbidden_path_globs pattern {pattern!r}"
                )

    flags = artifact.get("flags") or {}
    for flag_name, expected in (grading.get("required_flags") or {}).items():
        actual = bool(flags.get(flag_name, False))
        if actual != bool(expected):
            failures.append(
                f"flag {flag_name!r} expected {expected!r}, artifact declared {flags.get(flag_name)!r}"
            )

    return GradeResult(case_id=case["id"], passed=not failures, failures=failures)


def grade_file(case_id: str, artifact_path: Path) -> GradeResult:
    case = load_case(case_id)
    artifact = json.loads(Path(artifact_path).read_text(encoding="utf-8"))
    validate_artifact_shape(artifact, source=str(artifact_path))
    return grade(case, artifact)
