"""A `gh` call that cannot reach GitHub must not read as "nothing found".

Two halves of one defect class, both measured on ``intel-refresh.yml``
(2026-10-07):

1. **No repository context.**  A job with no ``actions/checkout`` step has no
   ``.git`` directory, so ``gh issue`` / ``gh label`` cannot infer the repo and
   die with "not a git repository" unless ``GH_REPO`` is set.  The alert step
   had it; the close step did not.

2. **The error was swallowed.**  The close step read
   ``gh issue list ... 2>/dev/null || echo ""``, so the failure above became
   an empty list, the step logged "no open intel-stale issue; nothing to
   close", and the run was green — every day since 2026-09-21 — while the
   tracker #737 stayed open (run 37491346018).

``health-check.yml`` paid for half (1) once already (9 consecutive red runs,
2026-08-19..21), which is why its steps carry ``GH_REPO`` with a note.  These
guards make both halves structural instead of remembered.
"""

from __future__ import annotations

import re
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]
WORKFLOWS = ROOT / ".github" / "workflows"

# `gh` subcommands that infer the repository from the working directory.
_REPO_SCOPED_GH = re.compile(r"\bgh\s+(issue|label|pr|run|workflow|release)\b")

# A `gh issue list` command (with its `\`-continued lines) whose stderr is
# discarded.  That is the shape that turns "could not ask" into "found
# nothing".
_SWALLOWED_LOOKUP = re.compile(r"gh issue list(?:[^\n]*\\\n)*[^\n]*2>/dev/null")

# Workflows that still swallow a tracker lookup, recorded rather than fixed in
# the change that added this guard (the CLEANUP-3 stabilization PR scoped the
# repair to the trackers that were measurably broken).  Both check out the
# repository, so they are exposed only to a transient gh/API failure, not to
# the missing-context failure that kept #737 open.  This list may only
# SHRINK: the second test fails if an entry no longer offends.
_KNOWN_SWALLOWING_FOLLOWUPS = frozenset({"scheduled-refresh.yml", "audit-identity-matches.yml"})


def _workflows():
    for path in sorted(WORKFLOWS.glob("*.y*ml")):
        document = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        yield path, document


def _steps(job: dict):
    for step in job.get("steps") or []:
        if isinstance(step, dict):
            yield step


def _has_checkout(job: dict) -> bool:
    return any("actions/checkout" in str(step.get("uses") or "") for step in _steps(job))


def test_jobs_without_a_checkout_give_gh_its_repository():
    offenders: list[str] = []
    for path, document in _workflows():
        workflow_env = document.get("env") or {}
        for job_name, job in (document.get("jobs") or {}).items():
            if not isinstance(job, dict) or _has_checkout(job):
                continue
            job_env = job.get("env") or {}
            for step in _steps(job):
                script = step.get("run") or ""
                if not _REPO_SCOPED_GH.search(script):
                    continue
                step_env = step.get("env") or {}
                if "GH_REPO" in step_env or "GH_REPO" in job_env or "GH_REPO" in workflow_env:
                    continue
                if re.search(r"(--repo|-R)[ =]", script):
                    continue
                offenders.append(f"{path.name} :: {job_name} :: {step.get('name')}")
    assert not offenders, (
        "these steps run repo-scoped `gh` commands in a job with no checkout and no "
        "GH_REPO, so every call fails with 'not a git repository' (intel-refresh.yml's "
        "close step did exactly this and #737 never closed):\n  " + "\n  ".join(offenders)
    )


def _swallowing_workflows() -> set[str]:
    found: set[str] = set()
    for path, document in _workflows():
        for job in (document.get("jobs") or {}).values():
            if not isinstance(job, dict):
                continue
            for step in _steps(job):
                if _SWALLOWED_LOOKUP.search(step.get("run") or ""):
                    found.add(path.name)
    return found


def test_tracker_lookups_do_not_swallow_gh_errors():
    unexpected = _swallowing_workflows() - _KNOWN_SWALLOWING_FOLLOWUPS
    assert not unexpected, (
        "`gh issue list ... 2>/dev/null` makes a failed lookup indistinguishable from "
        "an empty one — a silent all-clear on the close side, a silent duplicate on the "
        "open side.  Use `if ! X=$(gh issue list ...); then echo ::error ...; fi` "
        "instead:\n  " + "\n  ".join(sorted(unexpected))
    )


def test_the_known_followup_list_only_shrinks():
    stale = _KNOWN_SWALLOWING_FOLLOWUPS - _swallowing_workflows()
    assert not stale, (
        "these workflows no longer swallow their tracker lookup — remove them from "
        f"_KNOWN_SWALLOWING_FOLLOWUPS so the guard covers them: {sorted(stale)}"
    )
