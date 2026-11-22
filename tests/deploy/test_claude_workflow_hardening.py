"""``claude.yml`` runs least-privilege by default and pins its third-party action.

T13 (security hardening batch).  The workflow had no top-level ``permissions``
block, so any job added without its own block would inherit the repository's
default token scopes; and it ran ``anthropics/claude-code-action`` by a TAG,
which the action's publisher can move to different code at any time -- code
that then runs with this job's write token.

The job-level grants are deliberately unchanged: the action needs them, and
narrowing them is a behaviour change outside this unit.  ``deploy.yml`` is a
separate, production-critical unit and is not touched here.
"""

from __future__ import annotations

import re
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]
WORKFLOW = ROOT / ".github" / "workflows" / "claude.yml"

#: GitHub's own first-party actions are trusted by tag in this repository.
FIRST_PARTY = ("actions/",)


def _doc() -> dict:
    return yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))


def test_top_level_permissions_are_read_only():
    assert _doc()["permissions"] == {"contents": "read"}


def test_the_job_keeps_exactly_its_own_grants():
    assert _doc()["jobs"]["claude"]["permissions"] == {
        "contents": "write",
        "pull-requests": "write",
        "issues": "write",
        "id-token": "write",
        "actions": "read",
    }


def test_third_party_actions_are_pinned_to_a_commit_with_the_version_noted():
    lines = WORKFLOW.read_text(encoding="utf-8").splitlines()
    third_party = [ln for ln in lines if re.match(r"\s*(-\s+)?uses:\s", ln)]
    third_party = [
        ln for ln in third_party if not ln.split("uses:", 1)[1].strip().startswith(FIRST_PARTY)
    ]
    assert third_party, "no third-party action found -- this guard would pass vacuously"
    for line in third_party:
        ref = line.split("uses:", 1)[1].strip()
        assert re.fullmatch(
            r"[\w.-]+/[\w.-]+@[0-9a-f]{40} # v\d+(\.\d+)*", ref
        ), f"not pinned to a full commit SHA with its version in a comment: {line.strip()}"
