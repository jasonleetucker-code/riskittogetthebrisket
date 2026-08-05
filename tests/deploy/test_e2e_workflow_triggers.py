"""The E2E safety net's triggering rules are load-bearing and unpinned.

Three separate decisions live in ``.github/workflows/e2e.yml`` that are
invisible from the job body, and every one of them has already been got
wrong once:

1. **Who may write to the ``e2e-failures`` tracker.**  That issue answers
   "is MAIN's safety net broken".  Both steps therefore require
   ``github.ref == 'refs/heads/main'`` *and* a non-``pull_request``
   event.  A green run that is not main's must not close it: #716 was a
   green DISPATCH on a branch issuing main's all-clear, and a green PR
   run is green for a merge commit of a branch that is not main.  The
   close direction is the dangerous one — a false all-clear closes a
   real open failure, while a false alarm merely files a wrong one.

   The two clauses are redundant today (a ``pull_request`` run's ref is
   ``refs/pull/<n>/merge``, never ``refs/heads/main``), which is exactly
   the trap: it makes replacing one with the other look like a no-op.
   It is not.  Dropping the ref clause re-opens #716 while every test
   and every PR check stays green.

2. **The PR path list.**  It is the SSR/module-graph surface, added
   after #709 put a ``dynamic()`` boundary around ``{children}`` and
   shipped a build that rendered every page twice.  Six rounds of
   performance instrumentation reported unchanged numbers for it; this
   suite's Playwright strict-mode locators were the sole detector.  The
   *exclusion* of ``frontend/components/ds/**`` is as deliberate as any
   inclusion — the design system is touched by a large share of frontend
   PRs, so listing it would quietly turn this into the every-PR gate the
   header rules out.

3. **Per-ref concurrency.**  With one global group and
   ``cancel-in-progress``, the first PR run cancels the nightly and every
   other PR's run — and a cancelled run reports the same "not green" as a
   failure while having tested nothing.
"""

from __future__ import annotations

from pathlib import Path

import yaml

_REPO = Path(__file__).resolve().parents[2]
_WORKFLOW = _REPO / ".github" / "workflows" / "e2e.yml"

# The steps that write to the shared ``e2e-failures`` tracking issue.
_ISSUE_STEP_NAMES = (
    "Alert on workflow failure",
    "Close the tracking issue when the suite is green",
)

_EXPECTED_PR_PATHS = [
    "frontend/app/layout.jsx",
    "frontend/app/AppShellWrapper.jsx",
    "frontend/components/AppShell.jsx",
    "frontend/components/shell/**",
    "frontend/middleware.js",
    "frontend/lib/public-routes.js",
    "frontend/package.json",
    "frontend/next.config.*",
    "tests/e2e/**",
    ".github/workflows/e2e.yml",
]


def _workflow() -> dict:
    return yaml.safe_load(_WORKFLOW.read_text(encoding="utf-8"))


def _triggers(wf: dict) -> dict:
    # ``on:`` is a YAML 1.1 boolean, so safe_load keys it as True.  Accept
    # either in case a future loader is configured differently.
    return wf.get("on", wf.get(True))


def _steps(wf: dict) -> list[dict]:
    return [step for job in wf["jobs"].values() for step in job.get("steps", [])]


def _step_named(wf: dict, name: str) -> dict:
    for step in _steps(wf):
        if step.get("name") == name:
            return step
    raise AssertionError(
        f"step {name!r} is gone from e2e.yml — if it was renamed, update "
        "_ISSUE_STEP_NAMES here rather than deleting the guard it carries"
    )


def test_workflow_parses() -> None:
    assert isinstance(_workflow(), dict)


def test_all_three_triggers_are_present() -> None:
    triggers = _triggers(_workflow())
    assert set(triggers) == {"schedule", "workflow_dispatch", "pull_request"}


def test_pr_trigger_is_path_filtered_to_the_shell_surface() -> None:
    pr = _triggers(_workflow())["pull_request"]
    assert pr["paths"] == _EXPECTED_PR_PATHS


def test_pr_trigger_still_exercises_itself() -> None:
    # The workflow is on its own path list, so a change to the triggering
    # rules proves them in the same PR that makes it.
    pr = _triggers(_workflow())["pull_request"]
    assert ".github/workflows/e2e.yml" in pr["paths"]


def test_design_system_is_deliberately_not_a_pr_trigger() -> None:
    pr = _triggers(_workflow())["pull_request"]
    assert not [p for p in pr["paths"] if p.startswith("frontend/components/ds")], (
        "adding components/ds/** turns this into the every-PR gate the "
        "workflow header rules out; dispatch by hand for a risky ds change"
    )


def test_concurrency_is_keyed_per_pr_or_ref() -> None:
    concurrency = _workflow()["concurrency"]
    assert concurrency["cancel-in-progress"] is True
    assert (
        concurrency["group"]
        == "e2e-safety-net-${{ github.event.pull_request.number || github.ref }}"
    )


def test_only_main_may_write_to_the_failures_tracker() -> None:
    wf = _workflow()
    for name in _ISSUE_STEP_NAMES:
        condition = _step_named(wf, name)["if"]
        assert "github.ref == 'refs/heads/main'" in condition, (
            f"{name!r} lost its ref guard.  A non-'pull_request' check is "
            "NOT a substitute: workflow_dispatch on a branch satisfies it, "
            "which is incident #716."
        )
        has_event_guard = "github.event_name != 'pull_request'" in condition
        assert has_event_guard, f"{name!r} lost its PR-run guard."


def test_the_two_tracker_steps_guard_opposite_outcomes() -> None:
    wf = _workflow()
    assert _step_named(wf, "Alert on workflow failure")["if"].startswith("failure()")
    assert _step_named(wf, "Close the tracking issue when the suite is green")["if"].startswith(
        "success()"
    )
