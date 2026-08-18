"""The production health check must not exempt the degraded status.

AUDIT FINDING F-21 (2026-08-18)
───────────────────────────────
``.github/workflows/health-check.yml`` is the only always-on external check
of production.  It mapped ``503`` to a non-failing ``::warning``::

    elif [[ "${HTTP_CODE}" == "503" ]]; then
      echo "::warning title=Health Degraded::Service returned 503 (degraded)."
      # no exit 1
    else
      echo "::error title=Health Check Failed::..."
      exit 1

``503`` is precisely what ``server.py::get_health`` returns for stale data, a
failed or stalled scrape, or contract validation failure — so the one status
that means "something is wrong" was the ONE non-200 that could not fail the
run.  Every other unexpected code did.  Twenty consecutive runs were green,
and there was no ``if: failure()`` handler, so even a genuine failure
produced nothing but a red square.

Three further steps SKIPPED the coverage and backup assertions with a
warning whenever ``/api/status`` was unreachable, so "we could not check"
read identically to "we checked and it is fine" — exactly when it mattered.

WHY A THRESHOLD RATHER THAN AN EXEMPTION
────────────────────────────────────────
The concern behind the exemption was real: a momentary degrade should not
page anyone.  The answer to that is a CONSECUTIVE-failure threshold, which
``deploy/systemd/dynasty-healthcheck.sh`` already applies to liveness
(``HEALTH_FAIL_THRESHOLD``).  This workflow keeps no state between its
6-hourly runs, so "consecutive" is measured within the run.

This module is static — it reads the workflow, runs nothing, needs no
network.  It exists because a reviewer cannot catch a re-introduced
exemption by reading a diff: it looks like ordinary branch handling.
"""

from __future__ import annotations

import re
from pathlib import Path

import yaml

_WORKFLOW = Path(__file__).resolve().parents[2] / ".github/workflows/health-check.yml"


def _text() -> str:
    return _WORKFLOW.read_text()


def _code_only() -> str:
    """Workflow source with comment-only lines stripped.

    Load-bearing: this file's comments quote the defect verbatim, including
    the old ``::warning title=Health Degraded`` line.  A guard that matched
    the raw text would match the explanation as readily as a regression —
    the exact mistake that made two earlier guards in this session
    decorative.
    """
    return "\n".join(ln for ln in _text().splitlines() if not ln.strip().startswith("#"))


def test_the_workflow_is_still_where_this_test_thinks_it_is() -> None:
    """Guards against every assertion below passing vacuously."""
    assert _WORKFLOW.exists()
    doc = yaml.safe_load(_text())
    assert "health" in doc["jobs"]


def test_a_sustained_degrade_fails_the_run() -> None:
    """The 503 branch must exit non-zero."""
    code = _code_only()
    match = re.search(r'elif \[\[ "\$\{HTTP_CODE\}" == "503".*?(?=\n\s*else\b)', code, re.S)
    assert match, "the 503 branch is gone — has the check been restructured?"
    branch = match.group(0)
    assert "exit 1" in branch, f"503 does not fail the run:\n{branch}"


def test_degraded_is_reported_as_an_error_not_a_warning() -> None:
    code = _code_only()
    assert "::warning title=Health Degraded" not in code
    assert "::error title=Health Degraded" in code


def test_the_threshold_is_a_delay_not_an_exemption() -> None:
    """A degrade must be probed more than once before it fails — and the
    probe count must be finite, or 'consecutive' becomes 'never'."""
    code = _code_only()
    probes = re.search(r"HEALTH_PROBES=(\d+)", code)
    gap = re.search(r"HEALTH_PROBE_GAP_SEC=(\d+)", code)
    assert probes and gap, "no consecutive-probe threshold found"
    assert 2 <= int(probes.group(1)) <= 10, probes.group(1)
    assert 1 <= int(gap.group(1)) <= 300, gap.group(1)


def test_an_unreachable_status_endpoint_is_not_a_pass() -> None:
    """ "Skipped" must not be a silent success on any of the three steps."""
    code = _code_only()
    assert "::warning title=Status Unreachable" not in code
    # Match ANNOTATION emissions only.  The failure handler's issue body
    # explains what "Status Unreachable" means in prose, and counting that
    # line would make this assertion depend on the wording of a help text.
    unreachable = [ln for ln in code.splitlines() if "title=Status Unreachable" in ln]
    assert len(unreachable) == 3, unreachable
    for line in unreachable:
        assert "::error" in line, line


def test_no_step_is_silenced() -> None:
    """None of the repairs above mean anything if a step is allowed to fail
    quietly."""
    doc = yaml.safe_load(_text())
    for step in doc["jobs"]["health"]["steps"]:
        assert not step.get("continue-on-error"), step.get("name")


def test_a_failure_reaches_a_human() -> None:
    """A red square on a page nobody watches is not an alert."""
    doc = yaml.safe_load(_text())
    conditions = [str(s.get("if") or "") for s in doc["jobs"]["health"]["steps"]]
    assert any("failure()" in c for c in conditions), conditions


def test_the_alert_can_clear() -> None:
    """An alert that cannot clear stops being read.  The repo learned this
    on ``stale-sources``; the counterpart ships with the handler this time."""
    doc = yaml.safe_load(_text())
    conditions = [str(s.get("if") or "") for s in doc["jobs"]["health"]["steps"]]
    assert any("success()" in c for c in conditions), conditions


def test_no_unreachable_code_left_behind() -> None:
    """A stray ``exit 0`` after an ``exit 1`` would read as an exemption to
    the next person and does nothing for this one."""
    lines = [ln.strip() for ln in _code_only().splitlines()]
    for i, line in enumerate(lines[:-1]):
        if line == "exit 1":
            assert lines[i + 1] != "exit 0", f"dead exit 0 at line {i + 2}"
