"""The weekly calibration trackers must find the issue they filed.

CI reliability lane, 2026-08-20.

Two workflows open issues under the ``calibration`` label:
``audit-rank-form-drift.yml`` and ``refit-hill-curves.yml``.  **The label
did not exist.**  Run ``32114681240`` (2026-08-18) logged it verbatim::

    could not add label: 'calibration' not found

So ``gh issue create --label calibration`` failed, the ``|| gh issue
create`` fallback filed an UNLABELLED issue, and the drift audit's dedup
lookup — which filtered on that same label — could never find it again.
Every following weekly run would mint a fresh duplicate while the close
step, which matches on TITLE, could still close them.  The two halves of
one tracker were keyed differently, and the half that files used the key
that did not resolve.

**This is not hypothetical.**  ``refit-hill-curves.yml`` shares the label
and had no dedup at all; its promotion request is open twice, as #777
(2026-08-11) and #895 (2026-08-18), exactly one week apart, neither
labelled.  The mechanism is visible in the live issue list.

A tracker that cannot find its own issue is worse than no tracker: it
converts one open work item into a weekly stream of them, and a stream of
duplicates is how a real finding gets tuned out.

WHAT IS NOT CHANGED
===================
``refit-hill-curves.yml`` still has no auto-close, deliberately.  Its
issue means "a challenger cleared the held-out gate and is waiting for a
human to promote it" — a work item, not an alert — and silently closing
a promotion request is worse than leaving a stale one open (ADR-008).
Only the open side is deduped.
"""

from __future__ import annotations

import re
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]
WORKFLOWS = ROOT / ".github" / "workflows"

LABEL = "calibration"
CONSUMERS = ("audit-rank-form-drift.yml", "refit-hill-curves.yml")


def _issue_steps(path: Path) -> list[tuple[str, str]]:
    """(step name, runnable script) for steps that create or list issues."""
    document = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    steps: list[tuple[str, str]] = []
    for job in (document.get("jobs") or {}).values():
        if not isinstance(job, dict):
            continue
        for step in job.get("steps") or []:
            if not isinstance(step, dict) or not isinstance(step.get("run"), str):
                continue
            script = "\n".join(
                line for line in step["run"].splitlines() if not line.lstrip().startswith("#")
            )
            if "gh issue create" in script:
                steps.append((str(step.get("name", "<unnamed>")), script))
    return steps


def test_both_calibration_workflows_still_file_issues():
    """Non-vacuity: silent if these steps are renamed or removed."""
    for name in CONSUMERS:
        path = WORKFLOWS / name
        assert path.exists(), f"{name} is gone — re-point this guard"
        assert _issue_steps(
            path
        ), f"{name} no longer creates issues; this guard would pass vacuously"


def test_the_label_is_created_before_it_is_relied_on():
    """A label that does not exist cannot label, and cannot be a key."""
    missing: list[str] = []
    for name in CONSUMERS:
        for step_name, script in _issue_steps(WORKFLOWS / name):
            if f"gh label create {LABEL}" not in script:
                missing.append(f"{name} :: {step_name}")
    assert not missing, (
        f"these steps apply the {LABEL!r} label without ensuring it exists. It did "
        "not exist on 2026-08-18 and `gh issue create --label` failed, so the "
        "fallback filed unlabelled issues the dedup could never find again. Create "
        "it idempotently, the way scheduled-refresh.yml and e2e.yml already do:\n  "
        + "\n  ".join(missing)
    )


def test_the_open_side_dedups_and_does_not_depend_on_the_label_resolving():
    """One key for both halves, and it must be the one that always works.

    The close step matches on exact title precisely because the label is
    shared between these two workflows and a label-only close would reach
    over and close the other one's issues.  The open side must use that
    same key, or a fallback-created issue is closable but not findable.
    """
    broken: list[str] = []
    for name in CONSUMERS:
        for step_name, script in _issue_steps(WORKFLOWS / name):
            if "gh issue list" not in script:
                broken.append(f"{name} :: {step_name} — no dedup lookup at all")
                continue
            # The LOOKUP only, not the create below it.  Slicing to the
            # end of the step would drag in `gh issue create --label
            # calibration` -- which is correct there and forbidden here --
            # and the guard would fail on the fixed code.  It did, on the
            # first run.
            lookup = script[script.index("gh issue list") :]
            if "gh issue create" in lookup:
                lookup = lookup[: lookup.index("gh issue create")]
            if f"--label {LABEL}" in lookup:
                broken.append(f"{name} :: {step_name} — dedup filters on the {LABEL!r} label")
            if not re.search(r"select\(\.title == ", lookup):
                broken.append(f"{name} :: {step_name} — dedup does not match on the exact title")
    assert not broken, (
        "the open side of a calibration tracker cannot reliably find the issue it "
        "filed, so it will mint a duplicate every week (measured: #777 and #895 are "
        "the same request seven days apart). Key the lookup on the exact title, the "
        "same key the close step uses:\n  " + "\n  ".join(broken)
    )


def test_the_refit_tracker_still_has_no_auto_close():
    """ADR-008: a promotion request is a work item, not an alert.

    Pinned so that "make the trackers consistent" never turns into
    silently closing something a human was asked to decide.
    """
    text = (WORKFLOWS / "refit-hill-curves.yml").read_text(encoding="utf-8")
    runnable = "\n".join(line for line in text.splitlines() if not line.lstrip().startswith("#"))
    assert "gh issue close" not in runnable, (
        "refit-hill-curves.yml now auto-closes its issue. That issue means 'a "
        "challenger cleared the held-out gate and is waiting for a human to promote "
        "it'. Closing it silently discards a decision request — see ADR-008 and the "
        "note in audit-rank-form-drift.yml's close step"
    )
