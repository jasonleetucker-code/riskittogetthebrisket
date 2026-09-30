"""Independently retrieved CI records for the exact revision a run pinned.

A run's report that "tests passed" is DECLARED. This module answers the same
question from GitHub Actions' own records for the artifact's pinned
``repo_head_end``, read with ``gh api`` against a repository slug the operator
supplies. Nothing from the artifact chooses an endpoint: the only artifact value
used is the revision, which must be a full 40-character lowercase SHA, and PR
numbers come from GitHub's own run records. There is no arbitrary URL fetch and
no command from a transcript is executed.

A green run is only as good as the workflow bytes that ran. Before a success
counts, this module proves the run's provenance; graders/diff_evidence.py's
``gate_changes`` proves the gate machinery matches trusted history, anchored on
an operator-supplied trusted ref, never on the artifact's own ``repo_head_start``.

* The run belongs to the operator's repository (``repository`` and
  ``head_repository``), for that exact ``head_sha``, and is a ``push`` or
  ``pull_request`` run.
* A ``push`` run executes the workflow file at ``head_sha`` itself.
* A ``pull_request`` run executes the workflow from the merge of ``head_sha``
  with the PR's base. GitHub computes a run's ``pull_requests`` at query time from
  the currently open PRs -- it is not a record of the run -- so it is trusted only
  when (a) an entry's ``head.sha`` is the run's ``head_sha``, (b) every such entry
  targets the trusted base branch, and (c) that PR's timeline has no
  ``base_ref_changed`` event, so its base cannot have been something else when the
  run started. A merged or closed PR drops out of ``pull_requests`` entirely, so a
  pull_request run can be verified only while its PR is open. Commit-level PR
  listings are never used: they omit closed PRs.

Residual limit: a pull_request run tested the merge with the base as it stood
when the run started, not the commit alone.
"""

from __future__ import annotations

import json
import re
import subprocess
from dataclasses import dataclass, field

from .diff_evidence import is_full_sha

REPO_SLUG = re.compile(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+")
GH_TIMEOUT_SECONDS = 30
MAX_RESPONSE_BYTES = 2 * 1024 * 1024
PER_PAGE = 100
MAX_PULL_TIMELINES = 10
# Retrieval failures the operator can fix (no gh, no auth, bad slug): a grading error.
OPERATOR_FAULTS = frozenset({"ci_repository_invalid", "ci_unavailable"})
TRUSTED_EVENTS = frozenset({"push", "pull_request"})


@dataclass(frozen=True)
class CiRuns:
    """``runs`` is set only when the listing was retrieved completely.

    ``retargeted`` maps a PR number to whether its timeline shows a base change
    (``None``: the timeline could not be read completely, so it is unknown).
    """

    runs: tuple[dict, ...] | None
    head: str | None
    reason: str | None = None
    slug: str | None = None
    retargeted: dict = field(default_factory=dict)


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


def _pulls_for_head(record, head) -> list[dict] | None:
    """The run's PR entries whose own head is ``head``; ``None`` if malformed."""
    pulls = record.get("pull_requests", [])
    if not isinstance(pulls, list):
        return None
    matching = []
    for pull in pulls:
        if not isinstance(pull, dict):
            return None
        base, pull_head = pull.get("base"), pull.get("head")
        if not (
            isinstance(pull.get("number"), int)
            and isinstance(base, dict)
            and isinstance(base.get("ref"), str)
            and isinstance(pull_head, dict)
        ):
            return None
        if pull_head.get("sha") == head:
            matching.append(pull)
    return matching


def fetch_workflow_runs(repo_slug: str, head, *, run=subprocess.run) -> CiRuns:
    """Workflow runs for ``head`` in ``repo_slug``, plus base-change history of their PRs."""
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
    numbers = sorted({p["number"] for r in runs for p in (_pulls_for_head(r, head) or [])})
    retargeted = {}
    for number in numbers[:MAX_PULL_TIMELINES]:
        events, reason = _gh_json(
            f"repos/{repo_slug}/issues/{number}/timeline?per_page={PER_PAGE}", run
        )
        if reason or not isinstance(events, list) or len(events) >= PER_PAGE:
            retargeted[number] = None  # unreadable or possibly truncated: unknown
        else:
            retargeted[number] = any(
                isinstance(e, dict) and e.get("event") == "base_ref_changed" for e in events
            )
    return CiRuns(tuple(runs), head, None, repo_slug, retargeted)


def _full_name(record, key):
    value = record.get(key)
    return value.get("full_name") if isinstance(value, dict) else None


def workflow_verdict(
    runs: CiRuns, workflow_path: str, *, trusted_base: str
) -> tuple[str, str, str | None]:
    """``(verdict, detail, event)`` for one workflow file.

    ``verdict`` is ``success`` / ``failure`` / ``not_checked``; ``event`` is the
    deciding run's event, which decides how its gate identity must be proven.
    The run that started last decides.
    """
    if runs.runs is None:
        return "not_checked", runs.reason or "ci_unavailable", None
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
        return "not_checked", "no_ci_run_for_revision", None
    for r in matching:
        started = r.get("run_started_at") or r.get("created_at")
        if not isinstance(started, str) or not isinstance(r.get("run_attempt", 1), int):
            return "not_checked", "ci_response_malformed", None
    latest = max(
        matching,
        key=lambda r: (r.get("run_started_at") or r["created_at"], r.get("run_attempt", 1)),
    )
    event = latest["event"]
    detail = f"run {latest.get('id')} ({event})"
    if latest.get("status") != "completed":
        return "not_checked", f"ci_run_incomplete: {detail}", event
    if event == "pull_request":
        pulls = _pulls_for_head(latest, runs.head)
        if pulls is None:
            return "not_checked", "ci_response_malformed", event
        if not pulls:
            return "not_checked", f"ci_base_unproven: {detail}", event
        untrusted = sorted({p["base"]["ref"] for p in pulls} - {trusted_base})
        if untrusted:
            return (
                "not_checked",
                f"ci_base_not_trusted: {detail} has PR base(s) {untrusted}",
                event,
            )
        for pull in pulls:
            state = runs.retargeted.get(pull["number"])
            if state is None:
                return "not_checked", f"ci_base_unproven: {detail} PR history unread", event
            if state:
                return "not_checked", f"ci_base_retargeted: {detail} PR {pull['number']}", event
    if latest.get("conclusion") == "success":
        return "success", detail, event
    return "failure", f"{detail} concluded {latest.get('conclusion')!r}", event
