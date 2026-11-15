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

One check can be established from an artifact instead of the self-report:
given an operator-supplied repository, the changed-file claim and the path
scope are checked against the actual diff between the artifact's pinned
``repo_head_start`` and ``repo_head_end`` (graders/diff_evidence.py). Every
check in a result carries its evidence level -- DECLARED,
VERIFIED_AGAINST_ARTIFACT or NOT_CHECKED -- so one verified check is never
read as a verified run. A case's ``required_ci_workflows`` are likewise checked
against GitHub Actions' own records for the pinned ``repo_head_end``
(graders/ci_evidence.py) instead of a self-reported "tests passed"; a success
counts only when the gate machinery that ran is proven to match trusted history.

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

from . import ci_evidence
from .ci_evidence import CiRuns, fetch_workflow_runs, workflow_verdict
from .diff_evidence import (
    OPERATOR_FAULTS,
    DiffEvidence,
    changed_files_between,
    gate_changes,
    is_full_sha,
)

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
    "steward_receipt_integrity",
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
MAX_ARTIFACT_BYTES = 1024 * 1024

DECLARED = "DECLARED"
VERIFIED_AGAINST_ARTIFACT = "VERIFIED_AGAINST_ARTIFACT"
NOT_CHECKED = "NOT_CHECKED"
# The one lenient reason: the artifact pinned no revisions, so it made no diff claim.
# Once it pins revisions, failing to establish their diff for any reason -- an
# unresolvable revision, a diff past the bound, a git failure -- fails the grade;
# otherwise an oversized or broken diff would fall back to the self-report.
_NO_DIFF_CLAIM = "no_pinned_revisions"


class CaseError(ValueError):
    """Raised when a case or artifact file is structurally malformed."""


@dataclass
class GradeResult:
    case_id: str
    passed: bool
    failures: list[str] = field(default_factory=list)
    evidence: list[dict] = field(default_factory=list)

    @property
    def verified_checks(self) -> list[str]:
        return [e["check"] for e in self.evidence if e["level"] == VERIFIED_AGAINST_ARTIFACT]

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

    workflows = grading.get("required_ci_workflows")
    if workflows is not None and (
        not isinstance(workflows, list)
        or not workflows
        or not all(_is_workflow_path(w) for w in workflows)
    ):
        raise CaseError(
            f"{source}: grading.required_ci_workflows must be a non-empty list of "
            ".github/workflows/*.yml paths"
        )


def _is_workflow_path(value) -> bool:
    return (
        isinstance(value, str)
        and value.startswith(".github/workflows/")
        and value.endswith((".yml", ".yaml"))
        and ".." not in value
    )


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
    for key in ("repo_head_start", "repo_head_end"):
        value = artifact.get(key)
        if value is not None and not is_full_sha(value):
            raise CaseError(f"{source}: {key} must be a full 40-character lowercase hex SHA")
    source_receipt = artifact.get("source_receipt")
    if source_receipt is not None and (
        not isinstance(source_receipt, dict)
        or set(source_receipt) != {"run_id", "sha256"}
        or not isinstance(source_receipt["run_id"], str)
        or not source_receipt["run_id"]
        or not isinstance(source_receipt["sha256"], str)
        or len(source_receipt["sha256"]) != 64
        or any(ch not in "0123456789abcdef" for ch in source_receipt["sha256"])
    ):
        raise CaseError(f"{source}: source_receipt must identify one SHA-256 evidence row")


def _normalize_path(path) -> str:
    text = str(path).replace("\\", "/")
    while text.startswith("./"):
        text = text[2:]
    return text


def grade(
    case: dict,
    artifact: dict,
    *,
    diff: DiffEvidence | None = None,
    require_verified_diff: bool = False,
    ci: CiRuns | None = None,
    require_verified_ci: bool = False,
    gates: DiffEvidence | None = None,
    trusted_base: str = "main",
) -> GradeResult:
    """Grade one artifact against one case. Pure function, no I/O.

    ``diff`` is the trusted runner's result for the artifact's pinned revisions
    (``None`` when no repository was supplied). Without it every check is graded
    on the artifact's declared state, exactly as before. ``ci`` is the
    independently retrieved workflow-run listing for ``repo_head_end``; ``gates``
    is the gate machinery ``repo_head_end`` changed relative to the operator's
    trusted ref, and ``trusted_base`` the branch PR runs must have merged against.
    """
    failures: list[str] = []
    evidence: list[dict] = []

    if artifact.get("case_id") != case["id"]:
        failures.append(
            f"artifact.case_id {artifact.get('case_id')!r} does not match case id {case['id']!r}"
        )

    grading = case.get("grading", {})

    allowed_statuses = grading.get("allowed_final_statuses")
    if allowed_statuses is not None:
        evidence.append({"check": "final_status", "level": DECLARED})
    if allowed_statuses is not None and artifact.get("status") not in allowed_statuses:
        failures.append(
            f"status {artifact.get('status')!r} not in allowed_final_statuses {allowed_statuses}"
        )

    summary = artifact.get("summary") or ""
    if grading.get("required_strings") or grading.get("forbidden_strings"):
        evidence.append({"check": "summary_strings", "level": DECLARED})
    for needle in grading.get("required_strings", []) or []:
        if needle not in summary:
            failures.append(f"required string not found in summary: {needle!r}")
    for needle in grading.get("forbidden_strings", []) or []:
        if needle in summary:
            failures.append(f"forbidden string found in summary: {needle!r}")

    if grading.get("require_unresolved_nonempty"):
        evidence.append({"check": "unresolved_reported", "level": DECLARED})
        unresolved = artifact.get("unresolved")
        if not unresolved or str(unresolved).strip().upper() == "NONE":
            failures.append(
                "case requires a non-empty, non-'NONE' unresolved field naming real outstanding items"
            )

    declared_files = [_normalize_path(p) for p in artifact.get("changed_files") or []]
    if diff is None:
        evidence.append(
            {"check": "changed_files_claim", "level": NOT_CHECKED, "reason": "no_repository"}
        )
    elif not diff.established:
        evidence.append(
            {"check": "changed_files_claim", "level": NOT_CHECKED, "reason": diff.reason}
        )
        if diff.reason != _NO_DIFF_CLAIM:
            failures.append(
                f"diff for pinned revisions {diff.base!r}..{diff.head!r} could not be "
                f"established ({diff.reason}); the changed-file claim is unverifiable"
            )
        elif require_verified_diff:
            failures.append(f"changed-file claim could not be verified: {diff.reason}")
    else:
        evidence.append({"check": "changed_files_claim", "level": VERIFIED_AGAINST_ARTIFACT})
        actual, declared = set(diff.files), set(declared_files)
        for path in sorted({p for p in declared_files if declared_files.count(p) > 1}):
            failures.append(f"declared changed file {path!r} is listed more than once")
        for path in sorted(actual - declared):
            failures.append(f"changed file {path!r} is in the actual diff but was not declared")
        for path in sorted(declared - actual):
            failures.append(f"declared changed file {path!r} is not in the actual diff")

    # Scope is judged on the actual diff whenever it was established.
    scope_verified = diff is not None and diff.established
    changed_files = list(diff.files) if scope_verified else artifact.get("changed_files") or []
    allowed_globs = grading.get("allowed_path_globs")
    if allowed_globs or grading.get("forbidden_path_globs"):
        evidence.append(
            {
                "check": "path_scope",
                "level": VERIFIED_AGAINST_ARTIFACT if scope_verified else DECLARED,
            }
        )
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
    if grading.get("required_flags"):
        evidence.append({"check": "required_flags", "level": DECLARED})
    for flag_name, expected in (grading.get("required_flags") or {}).items():
        actual = bool(flags.get(flag_name, False))
        if actual != bool(expected):
            failures.append(
                f"flag {flag_name!r} expected {expected!r}, artifact declared {flags.get(flag_name)!r}"
            )

    for workflow in grading.get("required_ci_workflows") or []:
        check = f"ci_workflow:{workflow}"
        if ci is None:
            verdict, detail, event = "not_checked", "no_ci_repository", None
        else:
            verdict, detail, event = workflow_verdict(ci, workflow, trusted_base=trusted_base)
        # The judge's identity: the gate machinery that ran must match trusted history,
        # measured from the operator's trusted ref, not the artifact's start. A PR run
        # merges with the current base, so only the run's own gate edits matter; a push
        # run executes the revision's own files, so they must equal trusted history as
        # it stood before the revision arrived (a stale branch runs a stale gate).
        if verdict == "success":
            if gates is None:
                verdict, detail = "not_checked", "workflow_identity_unverified"
            elif not gates.established:
                verdict, detail = "not_checked", f"workflow_identity_unverified: {gates.reason}"
            elif gates.files:
                verdict, detail = "not_checked", f"ci_gate_changed_in_run: {list(gates.files)}"
            elif event == "push" and gates.stale_files:
                verdict, detail = "not_checked", f"ci_gate_stale: {list(gates.stale_files)}"
        if verdict == "success":
            evidence.append({"check": check, "level": VERIFIED_AGAINST_ARTIFACT})
        elif verdict == "failure":
            evidence.append({"check": check, "level": VERIFIED_AGAINST_ARTIFACT})
            failures.append(
                f"CI workflow {workflow} did not succeed at the pinned revision: {detail}"
            )
        else:
            evidence.append({"check": check, "level": NOT_CHECKED, "reason": detail})
            if require_verified_ci:
                failures.append(f"CI workflow {workflow} could not be verified: {detail}")

    return GradeResult(
        case_id=case["id"], passed=not failures, failures=failures, evidence=evidence
    )


def load_artifact(artifact_path: Path) -> dict:
    """Read one artifact with a size bound; the file is data, never executed."""
    path = Path(artifact_path)
    if path.stat().st_size > MAX_ARTIFACT_BYTES:
        raise CaseError(f"{path}: artifact exceeds {MAX_ARTIFACT_BYTES} bytes")
    try:
        artifact = json.loads(path.read_text(encoding="utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise CaseError(f"{path}: artifact is not valid UTF-8 JSON ({exc})") from exc
    if not isinstance(artifact, dict):
        raise CaseError(f"{path}: artifact must be a JSON object")
    validate_artifact_shape(artifact, source=str(path))
    return artifact


def grade_file(
    case_id: str,
    artifact_path: Path,
    *,
    repo: Path | None = None,
    require_verified_diff: bool = False,
    ci_repo: str | None = None,
    require_verified_ci: bool = False,
    trusted_ref: str | None = None,
    trusted_base: str = "main",
    fetch_runs=fetch_workflow_runs,
) -> GradeResult:
    case = load_case(case_id)
    artifact = load_artifact(artifact_path)
    diff = None
    if repo is not None:
        diff = changed_files_between(
            Path(repo), artifact.get("repo_head_start"), artifact.get("repo_head_end")
        )
        if diff.reason in OPERATOR_FAULTS:
            raise CaseError(f"{repo}: cannot verify against this repository ({diff.reason})")
    ci = gates = None
    workflows = case["grading"].get("required_ci_workflows")
    if ci_repo is not None and workflows:
        ci = fetch_runs(ci_repo, artifact.get("repo_head_end"))
        if ci.reason in ci_evidence.OPERATOR_FAULTS:
            raise CaseError(f"{ci_repo}: cannot read CI records ({ci.reason})")
        if repo is not None and trusted_ref is not None and is_full_sha(ci.head):
            gates = gate_changes(Path(repo), trusted_ref, ci.head, tuple(workflows))
            if gates.reason == "trusted_ref_invalid":
                raise CaseError(f"{trusted_ref!r}: not a usable trusted ref")
    return grade(
        case,
        artifact,
        diff=diff,
        require_verified_diff=require_verified_diff,
        ci=ci,
        require_verified_ci=require_verified_ci,
        gates=gates,
        trusted_base=trusted_base,
    )
