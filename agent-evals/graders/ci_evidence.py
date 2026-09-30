"""Independently retrieved CI records for the exact revision a run pinned.

A run's report that "tests passed" is DECLARED. This module answers the same
question from GitHub Actions' own records for the artifact's pinned
``repo_head_end``, read with ``gh api`` against a repository slug the operator
supplies. Nothing from the artifact chooses an endpoint: the only artifact value
used is the revision, which must be a full 40-character lowercase SHA. There is
no arbitrary URL fetch and no command from a transcript is executed.

A green run is only as good as the workflow bytes that ran, so three things are
proven before a success counts (the rest of the proof -- that the gate machinery
at the revision matches trusted history -- is graders/diff_evidence.py's
``gate_changes``, anchored on an operator-supplied trusted ref, never on the
artifact's own ``repo_head_start``):

* the run belongs to the operator's repository (``repository`` and
  ``head_repository``), for that exact ``head_sha``;
* a ``push`` run executes the workflow file at ``head_sha`` itself;
* a ``pull_request`` run executes the workflow from the merge of ``head_sha``
  with the PR's base, so the deciding run's OWN ``pull_requests`` record must
  name only the trusted base branch -- a PR aimed at a branch carrying a weakened
  workflow would otherwise run that copy under the same ``head_sha``. The base
  is never taken from a commit-level PR listing: GitHub omits closed-unmerged PRs
  there, so closing the weakened PR would hide it. GitHub empties a run's
  ``pull_requests`` once its PR is merged or closed, so a pull_request run can
  be verified only while its PR is open; afterwards it is ``ci_base_unproven``.

Residual limit: a pull_request run tested the merge with the base as it stood
when the run started, not the commit alone.
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
TRUSTED_EVENTS = frozenset({"push", "pull_request"})


@dataclass(frozen=True)
class CiRuns:
    """``runs`` is set only when the listing was retrieved completely."""

    runs: tuple[dict, ...] | None
    head: str | None
    reason: str | None = None
    slug: str | None = None


def valid_slug(repo_slug) -> bool:
    return (
        isinstance(repo_slug, str)
        and REPO_SLUG.fullmatch(repo_slug) is not None
        and not {".", ".."} & set(repo_slug.split("/"))
    )


def _gh_json(endpoint: str, run):
    try:
        result = run(
            ["gh", "api", endpoint], capture_output=True, timeout=GH_TIMEOUT_SECONDS, check=False
        )
    except (OSError, subprocess.TimeoutExpired):
        return None, "ci_unavailable"
    if result.returncode != 0 or len(result.stdout) > MAX_RESPONSE_BYTES:
        return None, "ci_unavailable"
    try:
        return json.loads(result.stdout), None
    except ValueError:
        return None, "ci_response_malformed"


def fetch_workflow_runs(repo_slug: str, head, *, run=subprocess.run) -> CiRuns:
    """Every workflow run GitHub records for ``head`` in ``repo_slug``."""
    if not valid_slug(repo_slug):
        return CiRuns(None, head, "ci_repository_invalid")
    if head is None:
        return CiRuns(None, head, "no_pinned_revisions", repo_slug)
    if not is_full_sha(head):
        return CiRuns(None, head, "revision_not_full_sha", repo_slug)
    body, reason = _gh_json(
        f"repos/{repo_slug}/actions/runs?head_sha={head}&per_page={PER_PAGE}", run
    )
    if reason:
        return CiRuns(None, head, reason, repo_slug)
    try:
        runs, total = body["workflow_runs"], body["total_count"]
    except (KeyError, TypeError):
        return CiRuns(None, head, "ci_response_malformed", repo_slug)
    if not isinstance(runs, list) or not all(isinstance(r, dict) for r in runs):
        return CiRuns(None, head, "ci_response_malformed", repo_slug)
    if total != len(runs):
        # A partial listing could omit the newest run for a workflow.
        return CiRuns(None, head, "ci_listing_truncated", repo_slug)
    return CiRuns(tuple(runs), head, None, repo_slug)


def _full_name(record, key):
    value = record.get(key)
    return value.get("full_name") if isinstance(value, dict) else None


def _run_pull_bases(record) -> list[str] | None:
    pulls = record.get("pull_requests", [])
    if not isinstance(pulls, list):
        return None
    bases = []
    for pull in pulls:
        base = pull.get("base") if isinstance(pull, dict) else None
        ref = base.get("ref") if isinstance(base, dict) else None
        if not isinstance(ref, str):
            return None
        bases.append(ref)
    return bases


def workflow_verdict(runs: CiRuns, workflow_path: str, *, trusted_base: str) -> tuple[str, str]:
    """``("success" | "failure" | "not_checked", detail)`` for one workflow file.

    Only the operator repository's own push / pull_request runs whose
    ``head_sha`` is the pinned revision count. The run that started last decides.
    """
    if runs.runs is None:
        return "not_checked", runs.reason or "ci_unavailable"
    matching = [
        r
        for r in runs.runs
        if r.get("path") == workflow_path
        and r.get("head_sha") == runs.head
        and r.get("event") in TRUSTED_EVENTS
        and _full_name(r, "repository") == runs.slug
        and _full_name(r, "head_repository") == runs.slug
    ]
    if not matching:
        return "not_checked", "no_ci_run_for_revision"
    for r in matching:
        started = r.get("run_started_at") or r.get("created_at")
        if not isinstance(started, str) or not isinstance(r.get("run_attempt", 1), int):
            return "not_checked", "ci_response_malformed"
    latest = max(
        matching,
        key=lambda r: (r.get("run_started_at") or r["created_at"], r.get("run_attempt", 1)),
    )
    detail = f"run {latest.get('id')} ({latest['event']})"
    if latest.get("status") != "completed":
        return "not_checked", f"ci_run_incomplete: {detail}"
    if latest["event"] == "pull_request":
        bases = _run_pull_bases(latest)
        if bases is None:
            return "not_checked", "ci_response_malformed"
        if not bases:
            return "not_checked", f"ci_base_unproven: {detail}"
        untrusted = sorted(set(bases) - {trusted_base})
        if untrusted:
            return "not_checked", f"ci_base_not_trusted: {detail} has PR base(s) {untrusted}"
    if latest.get("conclusion") == "success":
        return "success", detail
    return "failure", f"{detail} concluded {latest.get('conclusion')!r}"
