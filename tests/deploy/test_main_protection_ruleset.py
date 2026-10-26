"""The ``main`` ruleset payload must not lock out the automation that feeds prod.

``deploy/github/main-protection-ruleset.json`` is inert until an admin runs
``deploy/github/apply-branch-protection.sh``.  As first written it carried a
single bypass actor (the admin role), so applying it would have rejected every
legitimate automated push to ``main``: the box timers push with the write
deploy key and four workflows push with ``GITHUB_TOKEN`` (the GitHub Actions
app).  Deploy dispatch and production ``source_health`` key on those commits
(CLAUDE.md, W31-F001), so the "protection" would have frozen production.

These tests derive the pusher population from the repository itself, so a new
direct-to-``main`` pusher without a matching bypass actor fails here before the
payload can be applied (stabilization audit 2026-10-07).
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import yaml

REPO = Path(__file__).resolve().parents[2]
PAYLOAD = REPO / "deploy" / "github" / "main-protection-ruleset.json"
GITHUB_ACTIONS_APP_ID = 15368
ADMIN_ROLE_ID = 5
WRITE_ROLE_ID = 4

_PUSH_RE = re.compile(r"^\s*(?:if\s+)?git push\b", re.MULTILINE)


def _payload() -> dict:
    return json.loads(PAYLOAD.read_text(encoding="utf-8"))


def _bypass(actor_type: str, actor_id) -> dict | None:
    for actor in _payload()["bypass_actors"]:
        if actor["actor_type"] == actor_type and actor.get("actor_id") == actor_id:
            return actor
    return None


def _workflow_pushers() -> list[str]:
    return sorted(
        p.name
        for p in (REPO / ".github" / "workflows").glob("*.yml")
        if _PUSH_RE.search(p.read_text(encoding="utf-8"))
    )


def _box_pushers() -> list[str]:
    return sorted(
        p.name
        for p in (REPO / "deploy").glob("*.sh")
        if re.search(r"^\s*(?:if\s+)?git push origin main\b", p.read_text(encoding="utf-8"), re.M)
    )


def test_the_pusher_population_is_what_the_audit_found():
    """Guards the guard: if discovery silently finds nothing, the bypass
    assertions below would pass vacuously."""
    assert {
        "refit-hill-curves.yml",
        "scheduled-refresh.yml",
        "verify-sharp-production.yml",
    } <= set(_workflow_pushers())
    assert {"dlf_fetch_and_push.sh", "idpshow_fetch_and_push.sh"} <= set(_box_pushers())


def test_workflow_pushers_are_covered_by_the_github_actions_bypass():
    pushers = _workflow_pushers()
    assert pushers, "precondition"
    actor = _bypass("Integration", GITHUB_ACTIONS_APP_ID)
    assert actor is not None and actor["bypass_mode"] == "always", (
        f"{pushers} push to main with GITHUB_TOKEN; without an Integration "
        f"{GITHUB_ACTIONS_APP_ID} bypass the ruleset rejects them and the data "
        "refresh / Hill evidence / Sharp smoke commits stop."
    )


def test_box_timer_pushers_are_covered_by_the_deploy_key_bypass():
    pushers = _box_pushers()
    assert pushers, "precondition"
    actor = _bypass("DeployKey", None)
    assert actor is not None and actor["bypass_mode"] == "always", (
        f"{pushers} push to main from the production box with the write deploy "
        "key; without a DeployKey bypass the DLF / IDP Show freshness pushes stop."
    )


def test_no_agent_gets_direct_main_authority_by_default():
    """The owner and AI agent sessions push as the same admin account, so an
    ``always`` admin bypass is direct-main authority for every agent.  The
    payload's default is ``pull_request`` (direct pushes blocked; a red PR can
    still be merged by the admin in an emergency).  Changing this is an owner
    decision, not an edit."""
    admin = _bypass("RepositoryRole", ADMIN_ROLE_ID)
    assert admin is not None, "the admin must keep an emergency path"
    assert admin["bypass_mode"] == "pull_request"
    assert _bypass("RepositoryRole", WRITE_ROLE_ID) is None


def test_required_check_is_a_job_name_that_exists_on_every_pr():
    rules = {r["type"]: r for r in _payload()["rules"]}
    assert {"deletion", "non_fast_forward", "pull_request", "required_status_checks"} <= set(rules)
    params = rules["required_status_checks"]["parameters"]
    # Requiring up-to-date branches would chase the 2-hourly data refresh
    # forever (CLAUDE.md "Release discipline — HEAD FREEZE").
    assert params["strict_required_status_checks_policy"] is False
    contexts = [c["context"] for c in params["required_status_checks"]]
    assert contexts == ["Validate PR"]

    wf = yaml.safe_load((REPO / ".github" / "workflows" / "pr-validation.yml").read_text("utf-8"))
    job_names = {job.get("name") for job in wf["jobs"].values()}
    assert "Validate PR" in job_names, "GitHub matches required checks by JOB name"
    on = wf.get(True) or wf.get("on")  # PyYAML parses the `on:` key as True
    pr_trigger = on.get("pull_request") or {}
    assert not (
        pr_trigger.get("paths") or pr_trigger.get("paths-ignore")
    ), "a required check that does not run on every PR blocks the PRs it skips"


def test_payload_review_count_allows_a_solo_maintainer_to_merge():
    rules = {r["type"]: r for r in _payload()["rules"]}
    assert rules["pull_request"]["parameters"]["required_approving_review_count"] == 0
