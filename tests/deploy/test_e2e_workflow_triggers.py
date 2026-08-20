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


# The exact title the alert step gives the tracker it creates.  Both
# tracker steps must select on it; see the test below for why.
_TRACKER_TITLE = "E2E safety net failing"


def test_tracker_steps_identify_their_own_issue_not_just_the_label() -> None:
    """``e2e-failures`` is a label, not an identity.

    Both steps used to find the tracker by label alone — the alert step
    took ``.[0].number``, the close step iterated ``.[].number``.  That
    silently assumes every issue wearing the label is this workflow's
    own run tracker, and nothing enforces it: the label is plain, and a
    human or another agent can apply it to a hand-written defect issue.

    #753 is exactly that — a real, open, reproducible defect carrying
    ``e2e-failures``.  Both halves misfired on it:

    * ``gh issue list`` sorts newest-first, so ``.[0]`` resolved to #753
      the moment it was filed, and run failures began commenting on
      somebody's bug report instead of the tracker (#732).
    * the close step's ``.[]`` drain would have CLOSED it, with a "green
      again" comment, on the first green ``main`` run — burying a live
      defect behind a true green.

    That second one is the close step's own stated fear ("a false
    all-clear CLOSES a real open failure") reached through a door its
    note did not anticipate: not a false green, but a true green closing
    an issue that was never a run tracker.

    The fix is to match what the alert step actually creates: author AND
    title.  Both clauses are load-bearing and this test requires both —
    author alone still matches a different bot-filed issue, and title
    alone still matches a human who reused the string.

    **AUDIT F-23 — what this test used to assert, and why that was worse
    than asserting nothing.**  It pinned the author clause as the literal
    string ``select(.author.login=="github-actions")``.  The login this
    bot actually files under is ``github-actions[bot]``, so the clause
    matched no issue in the repository: every failing run took the
    ``create`` branch and the close step could never drain the result.
    14 open trackers accumulated, all identically titled, 0 comments
    between them — while this assertion stayed green, because a literal
    string was present in a file.

    A guard may not pin a SPELLING it never verifies against reality.

    **ISSUE #958 — and the normalisation was the same mistake again.**  The
    paragraph above replaced a pinned spelling with a pinned TRANSFORMATION
    (``sub("\\[bot\\]$"; "")``) that was equally unverified.  It is wrong for
    the same reason: executing this shell against real ``jq`` shows that
    ``github-actions`` and ``github-actions[bot]`` BOTH pass that clause, and
    ``app/github-actions`` — the ``app/`` prefix ``gh`` puts on bot actors in
    ``--json author`` output — does not.  The duplicates therefore kept
    accumulating, and when ``verify-sharp-production.yml`` inherited this
    predicate verbatim it produced four fresh ones in 67 minutes (#951, #953,
    #955, #957).

    Three guesses is enough.  The author clause is REMOVED, and identity is the
    workflow-owned LABEL plus the exact TITLE.  That still protects #753 — a
    hand-filed defect carrying ``e2e-failures`` — because #753's title is not
    this workflow's title, which is the clause that was actually doing that
    work.  ``.[0]`` is likewise replaced by min-by-number: gh sorts
    newest-first, which is the mechanism by which #753 displaced #732 at all.

    This test now pins the STRUCTURE (title-keyed, no author dependence) while
    ``tests/deploy/test_sharp_tracker_dedup.py`` pins the BEHAVIOUR by running
    both workflows' real shell against a ``gh`` stub for all three spellings.
    A guard that asserts a string is present is what stayed green on top of a
    dead selector for two weeks; the behavioural test is the one that cannot.
    """
    wf = _workflow()
    for name in _ISSUE_STEP_NAMES:
        run = _step_named(wf, name)["run"]

        assert "select(.author" not in run and ".author.login ==" not in run, (
            f"{name!r} branches on the author login again. Three spellings have "
            "now been guessed wrong (F-23 twice, then issue #958); identity is "
            "LABEL + exact TITLE, which does not depend on a spelling."
        )
        assert ".[0].number" not in run, (
            f"{name!r} is back to `.[0]` off gh's newest-first sort — the "
            "mechanism that let #753 displace the real tracker #732."
        )
        # Not an f-string: ${TRACKER_TITLE} is the shell variable the
        # workflow expands, so the braces are literal text to match.
        assert 'select(.title==\\"${TRACKER_TITLE}\\")' in run, (
            f"{name!r} no longer filters the tracker lookup by title. "
            "Author alone still matches any other issue this bot opens."
        )
        assert f'TRACKER_TITLE="{_TRACKER_TITLE}"' in run, (
            f"{name!r} does not define TRACKER_TITLE as {_TRACKER_TITLE!r}. "
            "The two steps must agree on the title or the close step "
            "stops recognising what the alert step opened."
        )


def test_alert_step_creates_the_issue_it_looks_up() -> None:
    """The lookup title and the created title must be the same string.

    If the alert step ever creates a title its own lookup does not match,
    it opens a brand-new tracker on every failed run instead of reusing
    one — the "permanently red, accumulating duplicates" state the close
    step was added to end.
    """
    run = _step_named(_workflow(), "Alert on workflow failure")["run"]
    assert '--title "$TRACKER_TITLE"' in run, (
        "the alert step hardcodes a create-title instead of reusing "
        "TRACKER_TITLE, so its lookup and its create can drift apart"
    )
