"""A production check that did not run must not report success.

CI reliability lane, 2026-08-20.

``health-check.yml`` and ``smoke-test.yml`` gated on::

    jobs:
      health:
        if: ${{ vars.PROD_PUBLIC_URL != '' }}

A job skipped by a job-level ``if`` reports **neutral**, and the checks
UI, the merge page and the run's own conclusion all render neutral as
SUCCESS.  ``health-check.yml``'s ``health`` job is the workflow's ONLY
job, so an unset or renamed ``PROD_PUBLIC_URL`` would have retired the
always-on external check of production without a single red tick: every
six hours the repository would be told production was fine by a run that
never looked.

This is the same defect class as AUDIT F-21, which ``health-check.yml``
already documents in the step below — a check that cannot report the
condition it exists for.  F-21 was an exemption *inside* the assertion;
this removed the assertion entirely.

NOT A LIVE FAILURE, and the distinction is worth keeping straight: the
variable is set today (``prod-e2e-smoke.yml`` refuses when it is empty
and ran green at 2026-08-20T04:53Z), so this guards against a
configuration regression rather than repairing something currently
broken.

THE FIX IS THE REPOSITORY'S OWN CONVENTION, not a new invention.  Four
workflows already refuse loudly on the identical condition —
``prod-e2e-smoke.yml``, ``intel-refresh.yml``, ``public-league-warmup.yml``
and ``deploy.yml``, the last with a step named "Assert post-deploy
verification will actually run" whose entire purpose is this defect
class.  Two workflows were the stragglers.
"""

from __future__ import annotations

import re
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]
WORKFLOWS = ROOT / ".github" / "workflows"

VARIABLE = "PROD_PUBLIC_URL"


def _consumers() -> list[Path]:
    """Workflows that read ``vars.PROD_PUBLIC_URL``."""
    found = [
        path
        for path in sorted(WORKFLOWS.glob("*.yml"))
        if f"vars.{VARIABLE}" in path.read_text(encoding="utf-8")
    ]
    assert found, (
        f"no workflow references vars.{VARIABLE} — either the variable was renamed "
        "(in which case this guard needs rewriting) or it would now pass vacuously"
    )
    return found


def _runnable(script: str) -> str:
    return "\n".join(line for line in script.splitlines() if not line.lstrip().startswith("#"))


def test_no_job_is_gated_on_the_production_url_being_set():
    """A skipped job is not a passed job, but it renders as one."""
    offenders: list[str] = []
    for path in _consumers():
        document = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        for job_name, job in (document.get("jobs") or {}).items():
            if not isinstance(job, dict):
                continue
            condition = job.get("if")
            if isinstance(condition, str) and VARIABLE in condition:
                offenders.append(f"{path.name} :: job {job_name} :: if: {condition}")
    assert not offenders, (
        f"a job is gated on vars.{VARIABLE} at JOB level. A skipped job reports "
        "neutral, which renders as success — so an unset variable would retire the "
        "check silently. Move the condition into a step that can `exit 1`, the shape "
        "prod-e2e-smoke.yml already uses:\n  " + "\n  ".join(offenders)
    )


def test_every_consumer_refuses_loudly_when_the_production_url_is_empty():
    """Removing the job gate is only half of it.

    Dropping the ``if`` without adding a refusal would leave the job
    running against an empty origin, which is a different way to assert
    nothing.  Each consumer must contain a step that detects the empty
    case, annotates it, and exits non-zero.
    """
    missing: list[str] = []
    for path in _consumers():
        document = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        refuses = False
        for job in (document.get("jobs") or {}).values():
            if not isinstance(job, dict):
                continue
            for step in job.get("steps") or []:
                if not isinstance(step, dict) or not isinstance(step.get("run"), str):
                    continue
                script = _runnable(step["run"])
                if VARIABLE not in script:
                    continue
                emptiness = re.search(r'-z\s+"\$\{?\{?[^"]*\}?\}?"', script)
                annotates = "::error" in script and VARIABLE in script
                refuses_here = re.search(r"(^|\s|;)exit\s+[1-9]", script, re.MULTILINE)
                if emptiness and annotates and refuses_here:
                    refuses = True
                    break
            if refuses:
                break
        if not refuses:
            missing.append(path.name)
    assert not missing, (
        f"these workflows read vars.{VARIABLE} but never refuse when it is empty. "
        "Running against an empty origin asserts nothing just as surely as skipping "
        "does; annotate with `::error` and `exit 1`:\n  " + "\n  ".join(missing)
    )
