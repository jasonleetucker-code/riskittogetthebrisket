"""No job may run the full unit suite under a budget it cannot finish in.

CLEANUP-3, 2026-10-07.  ``smoke-test.yml``'s "Validate Code Quality" job ran
``python -m pytest tests/ -x -q --tb=short -m "not livedata"`` inside
``timeout-minutes: 10``.  The suite outgrew that in mid-August: the job's last
green run was 2026-08-13, and every scheduled run since was CANCELLED at the
wall (48 of the last 60) — a grey "cancelled" rather than a red "failure", so
for ~50 days the step measured nothing and looked like nothing was wrong.  The
identical command took 3,353 s (56 min) in deploy.yml on 2026-10-07.

The repair removed the step from the smoke job instead of raising its budget,
because ``deploy.yml``'s validate job already runs the byte-identical command
against every SHA deployed from ``main`` (several times a day).  That decision
is only sound while the deploy gate keeps running it, so this module pins:

1. the deploy gate still runs the full hard-gate suite with a budget that fits;
2. no workflow job runs the full suite under a budget below the measured
   runtime (the root cause, wherever it reappears);
3. the smoke job keeps the scheduled, cheap checks it still uniquely owns.
"""

from __future__ import annotations

import re
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]
WORKFLOWS = ROOT / ".github" / "workflows"

# Measured: deploy.yml "Run unit tests (hard gate — pure logic)", run
# 37621154868 (2026-10-07) = 3,353 s, and the job around it 41-67 min over the
# eleven most recent successful deploys.  pr-validation.yml, release-candidate
# and deploy.yml all budget 80.  60 is the floor below which the full suite is
# known not to fit; it is not a target.
FULL_SUITE_MIN_BUDGET_MINUTES = 60

HARD_GATE_COMMAND = 'python -m pytest tests/ -x -q --tb=short -m "not livedata"'

# `pytest tests/` followed by whitespace or end of line: the WHOLE tree, not a
# subdirectory such as `tests/model_registry/`.
_FULL_SUITE = re.compile(r"pytest\s+tests/(?=\s|$)", re.MULTILINE)


def _load(name: str) -> dict:
    return yaml.safe_load((WORKFLOWS / name).read_text(encoding="utf-8")) or {}


def _job_running(document: dict, needle: str) -> tuple[str, dict] | None:
    for job_name, job in (document.get("jobs") or {}).items():
        if not isinstance(job, dict):
            continue
        for step in job.get("steps") or []:
            if isinstance(step, dict) and needle in (step.get("run") or ""):
                return job_name, job
    return None


def test_the_deploy_gate_still_runs_the_full_hard_gate_suite():
    found = _job_running(_load("deploy.yml"), HARD_GATE_COMMAND)
    assert found is not None, (
        "deploy.yml no longer runs the full hard-gate unit suite.  smoke-test.yml "
        "dropped its own copy BECAUSE this one exists; removing it leaves main with "
        "no scheduled full-suite run at all.  Restore it, or restore the smoke "
        "job's copy with a budget it fits in."
    )
    _, job = found
    assert int(job.get("timeout-minutes", 360)) >= FULL_SUITE_MIN_BUDGET_MINUTES


def test_no_job_runs_the_full_suite_under_a_budget_it_cannot_finish_in():
    offenders: list[str] = []
    for path in sorted(WORKFLOWS.glob("*.y*ml")):
        document = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        for job_name, job in (document.get("jobs") or {}).items():
            if not isinstance(job, dict):
                continue
            runs_full_suite = any(
                isinstance(step, dict) and _FULL_SUITE.search(step.get("run") or "")
                for step in job.get("steps") or []
            )
            if not runs_full_suite:
                continue
            budget = int(job.get("timeout-minutes", 360))
            if budget < FULL_SUITE_MIN_BUDGET_MINUTES:
                offenders.append(f"{path.name} :: {job_name} (timeout-minutes: {budget})")
    assert not offenders, (
        "these jobs run the full unit suite (measured ~56 min) under a budget it "
        "cannot finish in, so every run is CANCELLED rather than failed and the "
        "check silently measures nothing:\n  " + "\n  ".join(offenders)
    )


def test_the_smoke_job_keeps_its_scheduled_dependency_and_import_gates():
    """What the daily smoke uniquely adds over the push-triggered gates is a
    fresh install on days nothing was pushed.  Those cheap gates must stay."""
    jobs = _load("smoke-test.yml").get("jobs") or {}
    validate = jobs.get("validate") or {}
    step_names = {
        step.get("name") for step in validate.get("steps") or [] if isinstance(step, dict)
    }
    for required in (
        "Install dependencies",
        "Validate dependency graph (pip check)",
        "Python import gate",
    ):
        assert required in step_names, f"smoke-test.yml validate job lost {required!r}"
    assert "production-smoke" in jobs, "the production endpoint smoke job must stay"
