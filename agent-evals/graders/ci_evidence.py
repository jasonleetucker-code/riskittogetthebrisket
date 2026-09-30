"""Independently retrieved CI records for the exact revision a run pinned.

A run's report that "tests passed" is DECLARED. This module answers the same
question from GitHub Actions' own workflow-run records for the artifact's
pinned ``repo_head_end``, read with ``gh api`` against a repository slug the
operator supplies. Nothing from the artifact chooses the endpoint: the only
artifact value used is the revision, which must be a full 40-character
lowercase SHA. There is no arbitrary URL fetch and no command from a
transcript is executed.

What a success proves, and what it does not. It proves the named workflow file
concluded ``success`` on a run whose ``head_sha`` is that revision. It does not
prove the tests are adequate: tests the run itself edited are part of what was
tested. And if the run edited the workflow file itself, the judge was changed by
the party being judged -- that evidence is refused (``workflow_changed_in_run``),
which requires the pinned diff (graders/diff_evidence.py) to be established.
Without that diff the workflow's identity is unverified and so is the result.
"""

from __future__ import annotations

import json
import re
import subprocess
from dataclasses import dataclass

from .diff_evidence import is_full_sha

REPO_SLUG = re.compile(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+")
GH_TIMEOUT_SECONDS = 30
MAX_RESPONSE_BYTES = 2 * 1024 * 1024
PER_PAGE = 100
# Retrieval failures the operator can fix (no gh, no auth, bad slug): a grading error.
OPERATOR_FAULTS = frozenset({"ci_repository_invalid", "ci_unavailable"})


@dataclass(frozen=True)
class CiRuns:
    """``runs`` is set only when the listing was retrieved completely."""

    runs: tuple[dict, ...] | None
    head: str | None
    reason: str | None = None


def fetch_workflow_runs(repo_slug: str, head, *, run=subprocess.run) -> CiRuns:
    """Every workflow run GitHub records for ``head`` in ``repo_slug``."""
    if (
        not isinstance(repo_slug, str)
        or not REPO_SLUG.fullmatch(repo_slug)
        or {".", ".."} & set(repo_slug.split("/"))
    ):
        return CiRuns(None, head, "ci_repository_invalid")
    if head is None:
        return CiRuns(None, head, "no_pinned_revisions")
    if not is_full_sha(head):
        return CiRuns(None, head, "revision_not_full_sha")
    endpoint = f"repos/{repo_slug}/actions/runs?head_sha={head}&per_page={PER_PAGE}"
    try:
        result = run(
            ["gh", "api", endpoint],
            capture_output=True,
            timeout=GH_TIMEOUT_SECONDS,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return CiRuns(None, head, "ci_unavailable")
    if result.returncode != 0 or len(result.stdout) > MAX_RESPONSE_BYTES:
        return CiRuns(None, head, "ci_unavailable")
    try:
        body = json.loads(result.stdout)
        runs = body["workflow_runs"]
        total = body["total_count"]
    except (ValueError, KeyError, TypeError):
        return CiRuns(None, head, "ci_response_malformed")
    if not isinstance(runs, list) or not all(isinstance(r, dict) for r in runs):
        return CiRuns(None, head, "ci_response_malformed")
    if total != len(runs):
        # A partial listing could omit the newest run for a workflow.
        return CiRuns(None, head, "ci_listing_truncated")
    return CiRuns(tuple(runs), head)


def workflow_verdict(runs: CiRuns, workflow_path: str) -> tuple[str, str]:
    """``("success" | "failure" | "not_checked", detail)`` for one workflow file.

    Only runs whose own ``head_sha`` is the pinned revision count; the newest
    such run decides, so a later re-run supersedes an earlier attempt.
    """
    if runs.runs is None:
        return "not_checked", runs.reason or "ci_unavailable"
    matching = [
        r for r in runs.runs if r.get("path") == workflow_path and r.get("head_sha") == runs.head
    ]
    if not matching:
        return "not_checked", "no_ci_run_for_revision"
    latest = max(matching, key=lambda r: (str(r.get("created_at", "")), r.get("run_attempt", 0)))
    detail = f"run {latest.get('id')} ({latest.get('event')})"
    if latest.get("status") != "completed":
        return "not_checked", f"ci_run_incomplete: {detail}"
    if latest.get("conclusion") == "success":
        return "success", detail
    return "failure", f"{detail} concluded {latest.get('conclusion')!r}"
