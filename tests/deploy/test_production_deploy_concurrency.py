"""No workflow may queue in ``production-deploy`` for a run that does nothing.

GitHub keeps ONE pending run per concurrency group: a new arrival cancels
whichever run was pending.  A workflow-level ``concurrency`` block is entered
before any job-level ``if`` is evaluated, so a workflow whose job is about to
be skipped still sits pending in the group, and it cancels the queued
production deploy.

Measured 2026-09-24: ``v1-authenticated-verification.yml`` (``workflow_run`` on
every Deploy Production completion; job gated on a successful main deploy)
displaced Deploy Production 36072042988 (the #1427 merge) and 36072618473
(the post-merge data refresh), both cancelled with zero jobs started.  Every
cancelled deploy spawned another such run.

Rule: a workflow that can SKIP its work serialises with deploys at JOB level,
where the group is acquired only when the job actually runs.
"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]
WORKFLOWS = sorted((REPO_ROOT / ".github" / "workflows").glob("*.yml"))
GROUP = "production-deploy"
# Triggers that fire for runs the workflow may not want (every conclusion of
# the upstream workflow / every tick), and so are the ones gated by a job ``if``.
_SKIP_PRONE_TRIGGERS = {"workflow_run", "schedule"}


def _load(path: Path) -> dict:
    return yaml.safe_load(path.read_text(encoding="utf-8")) or {}


def _triggers(doc: dict) -> set[str]:
    # PyYAML reads the bare key ``on`` as boolean True.
    on = doc.get(True, doc.get("on"))
    if isinstance(on, str):
        return {on}
    if isinstance(on, list):
        return set(on)
    return set(on or {})


def _group(concurrency: object) -> str | None:
    if isinstance(concurrency, str):
        return concurrency
    if isinstance(concurrency, dict):
        return str(concurrency.get("group"))
    return None


def _workflow_level_deploy_group(doc: dict) -> bool:
    return _group(doc.get("concurrency")) == GROUP


def test_the_deploy_group_is_found_where_expected():
    """Guard the guard: if nothing matches, the rule below is vacuous."""
    users = [p.name for p in WORKFLOWS if _workflow_level_deploy_group(_load(p))]
    assert "deploy.yml" in users


@pytest.mark.parametrize("path", WORKFLOWS, ids=lambda p: p.name)
def test_no_skippable_workflow_holds_the_deploy_group_at_workflow_level(path: Path):
    doc = _load(path)
    if not _workflow_level_deploy_group(doc):
        return
    skip_prone = sorted(_triggers(doc) & _SKIP_PRONE_TRIGGERS)
    gated_jobs = sorted(
        name for name, job in (doc.get("jobs") or {}).items() if "if" in (job or {})
    )
    assert not skip_prone and not gated_jobs, (
        f"{path.name} declares workflow-level `concurrency: {GROUP}` but can run "
        f"without doing work (triggers {skip_prone}, job-level `if` on {gated_jobs}). "
        "A skipped run still queues in the group and cancels the pending deploy; "
        "move `concurrency` onto the job."
    )


def test_v1_verification_serialises_at_job_level():
    doc = _load(REPO_ROOT / ".github" / "workflows" / "v1-authenticated-verification.yml")
    assert "concurrency" not in doc
    job = doc["jobs"]["v1-authenticated"]
    assert job["concurrency"] == {"group": GROUP, "cancel-in-progress": False}
    assert "workflow_run" in _triggers(doc)


def test_deploy_semantics_unchanged():
    doc = _load(REPO_ROOT / ".github" / "workflows" / "deploy.yml")
    assert doc["concurrency"] == {"group": GROUP, "cancel-in-progress": False}
