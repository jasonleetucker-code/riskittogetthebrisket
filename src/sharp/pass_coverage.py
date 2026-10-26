"""Honest per-run coverage for the Sharp crawl passes (reporting only).

Four recurring passes feed the sharp cohort -- discovery, season records,
current rosters and trade activity.  Each one runs under a hard per-run
Sleeper call budget against a population far larger than that budget, and
until this module each one reported the same two facts about itself:
``budgetExhausted`` and, through the script, an exit code of ``2`` that the
systemd units map to success.  Neither says HOW MUCH of the eligible
population the run reached, how stale the part it did not reach has become,
or WHY it stopped.  A box audit (RPA-COL-016) found the rosters pass
examining about 1,400 of roughly 7,600 leagues per run and the oldest
records crawl 82 days old, with nothing an operator would notice.

This module only DESCRIBES a run.  It selects nothing, orders nothing and
scores nothing; the queue each pass walks is untouched.

Field vocabulary (shared by all four passes, additive under ``passCoverage``)
-----------------------------------------------------------------------------
``pass``                  discovery | records | rosters | activity (| ffpc lane)
``unit``                  what the counts below count (``leagues``,
                          ``managers``, ``graph_nodes`` ...) -- the passes do
                          not walk the same kind of thing
``attempted``             work-list entries this run actually reached
``succeeded`` / ``failed`` attempted entries that did / did not produce a result
``eligibleTotal``         size of the work list the run was given or derived
``remainingUnvisited``    eligible entries this run did not reach
``oldestCrawlMs``         timestamp of the OLDEST visit among entries that have
                          ever been visited (name mirrors
                          ``transactions.crawl_coverage`` in
                          ``src/sharp/transactions.py``), ``oldestCrawlAgeDays``
                          is that as an age at ``asOfMs``
``neverVisited``          entries with no visit on record at all -- OLDER than
                          any ``oldestCrawlMs``, so the two are read together
``callsUsed`` / ``callBudget``  Sleeper calls spent against the run's budget
``stoppedReason``         why the pass ended (vocabulary below)

Missing is never zero
---------------------
A quantity that could not be measured is ``None`` (JSON ``null``), never
``0``.  ``remainingUnvisited: 0`` means "measured, nothing left";
``remainingUnvisited: null`` means "not measured".  ``oldestCrawlMs`` is
``None`` when nothing has ever been visited -- an age of 0 days would say
the opposite.

``stoppedReason`` vocabulary
----------------------------
``completed``         the pass walked its whole work list.  Decided from the
                      work actually done, NOT from the budget flag: a run that
                      finishes its queue with the budget spent is ``completed``.
``budget_exhausted``  the call budget ended the run while work remained.
``sleeper_breaker_open``  the shared ``sleeper_api`` circuit breaker refused
                      calls (they were never sent to Sleeper).  Discovery and
                      activity ride that breaker (``sleeper_overlay._http_get_json``);
                      records and rosters use the pooled public client, which
                      has none.  The value is the one the transactions pass
                      already publishes (``transactions.STOPPED_BREAKER_OPEN``),
                      so a consumer reading ``stoppedReason`` across these four
                      passes and the transactions pass sees one vocabulary.
``cap_reached``       a configured selection or size cap left part of the
                      eligible population out of the work list.
``work_pending``      entries were still queued for a later run and the budget
                      was not what stopped this one (activity pass: leagues whose
                      fetch failed and are carried in the retry cursor).  A run
                      with pending work is never ``completed``.
``no_work``           the pass had nothing to do (empty cohort / empty queue).
``upstream_data_missing``  the pass's input was absent upstream, so part of the
                      population could not be visited at all (FFPC memberships
                      whose page carried no roster table).

A run where work was attempted and EVERY attempt failed is logged at WARNING
whatever its ``stoppedReason`` is -- a queue that drained because each fetch
failed is ``completed`` (the queue really did drain) but is not a healthy run.
Only the log level changes; ``stoppedReason`` and the exit code do not.

Exit codes are deliberately NOT part of this change: ``2`` still means
"budget exhausted" to the scripts, and the units still map it to success.
"""

from __future__ import annotations

import logging
import time
from datetime import datetime
from typing import Any

PASS_DISCOVERY = "discovery"
PASS_RECORDS = "records"
PASS_ROSTERS = "rosters"
PASS_ACTIVITY = "activity"

STOPPED_COMPLETED = "completed"
STOPPED_BUDGET_EXHAUSTED = "budget_exhausted"
STOPPED_BREAKER_OPEN = "sleeper_breaker_open"
STOPPED_CAP_REACHED = "cap_reached"
STOPPED_WORK_PENDING = "work_pending"
STOPPED_NO_WORK = "no_work"
STOPPED_UPSTREAM_MISSING = "upstream_data_missing"

#: Reasons that mean the run ended SHORT of the population it was meant to
#: cover.  These (and only these) are logged at WARNING.
STOPPED_SHORT = frozenset(
    {
        STOPPED_BUDGET_EXHAUSTED,
        STOPPED_BREAKER_OPEN,
        STOPPED_CAP_REACHED,
        STOPPED_WORK_PENDING,
        STOPPED_UPSTREAM_MISSING,
    }
)

_DAY_MS = 86_400_000

#: Name of the shared Sleeper circuit breaker (``sleeper_overlay._http_get_json``).
SLEEPER_BREAKER_NAME = "sleeper_api"


def now_ms() -> int:
    return int(time.time() * 1000)


def age_days(then_ms: int | None, *, as_of_ms: int) -> float | None:
    """Age in days of ``then_ms`` at ``as_of_ms``; ``None`` when never observed.

    A timestamp in the future (clock skew) reads as an age of zero rather than
    a negative age; ``None`` stays ``None`` -- it is not "just now".
    """
    if then_ms is None:
        return None
    return round(max(0, as_of_ms - int(then_ms)) / _DAY_MS, 2)


def classify_stop(
    *,
    budget_stopped: bool,
    work_remains: bool,
    breaker_blocked: bool = False,
    capped: bool = False,
) -> str:
    """The reason a pass ended, from what its own loop observed.

    ``budget_stopped`` is "the loop left because the budget check failed", not
    "the budget happens to be spent now".  ``work_remains`` must be true for a
    budget stop to be reported: a pass that drained its queue on its last
    call is ``completed``.
    """
    if breaker_blocked:
        return STOPPED_BREAKER_OPEN
    if budget_stopped and work_remains:
        return STOPPED_BUDGET_EXHAUSTED
    if capped:
        return STOPPED_CAP_REACHED
    return STOPPED_COMPLETED


def build_pass_coverage(
    *,
    pass_name: str,
    unit: str,
    attempted: int | None,
    succeeded: int | None,
    failed: int | None,
    eligible_total: int | None,
    remaining_unvisited: int | None,
    stopped_reason: str,
    calls_used: int | None,
    call_budget: int | None = None,
    oldest_crawl_ms: int | None = None,
    never_visited: int | None = None,
    oldest_basis: str | None = None,
    as_of_ms: int | None = None,
    extra: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Assemble the shared ``passCoverage`` block.

    Pure: every number is passed in by the caller that measured it.
    """
    as_of = now_ms() if as_of_ms is None else int(as_of_ms)
    block: dict[str, Any] = {
        "pass": pass_name,
        "unit": unit,
        "attempted": attempted,
        "succeeded": succeeded,
        "failed": failed,
        "eligibleTotal": eligible_total,
        "remainingUnvisited": remaining_unvisited,
        "neverVisited": never_visited,
        "oldestCrawlMs": oldest_crawl_ms,
        "oldestCrawlAgeDays": age_days(oldest_crawl_ms, as_of_ms=as_of),
        "oldestCrawlBasis": oldest_basis,
        "callsUsed": calls_used,
        "callBudget": call_budget,
        "stoppedReason": stopped_reason,
        "asOfMs": as_of,
    }
    if extra:
        block.update(extra)
    return block


def _fmt(value: Any) -> str:
    return "n/a" if value is None else str(value)


def format_summary(coverage: dict[str, Any]) -> str:
    """The one-line run summary, stable key=value so it greps and parses."""
    return (
        "sharp.coverage pass=%s unit=%s stoppedReason=%s attempted=%s succeeded=%s failed=%s "
        "eligibleTotal=%s remainingUnvisited=%s neverVisited=%s oldestCrawlAgeDays=%s "
        "callsUsed=%s callBudget=%s"
    ) % (
        _fmt(coverage.get("pass")),
        _fmt(coverage.get("unit")),
        _fmt(coverage.get("stoppedReason")),
        _fmt(coverage.get("attempted")),
        _fmt(coverage.get("succeeded")),
        _fmt(coverage.get("failed")),
        _fmt(coverage.get("eligibleTotal")),
        _fmt(coverage.get("remainingUnvisited")),
        _fmt(coverage.get("neverVisited")),
        _fmt(coverage.get("oldestCrawlAgeDays")),
        _fmt(coverage.get("callsUsed")),
        _fmt(coverage.get("callBudget")),
    )


def every_attempt_failed(coverage: dict[str, Any]) -> bool:
    """True when the run attempted work and not one attempt succeeded.

    Both figures must be measured: ``None`` is "not measured", so it can never
    read as "everything failed".
    """
    attempted = coverage.get("attempted")
    succeeded = coverage.get("succeeded")
    return (
        isinstance(attempted, int)
        and isinstance(succeeded, int)
        and attempted > 0
        and succeeded == 0
    )


def log_pass_summary(logger: logging.Logger, coverage: dict[str, Any]) -> int:
    """Log ONE summary line for the run; return the level used.

    ``WARNING`` when the run ended short of its population (budget exhausted
    with work left, breaker open, a selection cap, pending work) or when every
    attempt it made failed (a queue can drain, and read ``completed``, because
    each fetch failed); ``INFO`` otherwise.  Logging only: ``stoppedReason`` is
    not altered.
    """
    try:
        short = coverage.get("stoppedReason") in STOPPED_SHORT or every_attempt_failed(coverage)
        level = logging.WARNING if short else logging.INFO
        logger.log(level, "%s", format_summary(coverage))
        return level
    except Exception:  # noqa: BLE001 -- observability must never fail a crawl
        logger.warning("sharp.coverage: could not log the pass summary", exc_info=True)
        return logging.WARNING


def sleeper_breaker_fast_fails() -> int | None:
    """How many calls the shared Sleeper breaker has refused so far (read-only).

    An unregistered breaker has, by construction, refused nothing, so that is
    ``0``.  ``None`` only when the breaker registry could not be read.  The
    difference between two readings is the number of calls a run never sent.
    """
    try:
        from src.utils import circuit_breaker

        for snap in circuit_breaker.snapshot_all():
            if snap.get("name") == SLEEPER_BREAKER_NAME:
                return int(snap["counters"]["fastFail"])
        return 0
    except Exception:  # noqa: BLE001 -- observability must never fail a crawl
        return None


def breaker_refusals(before: int | None, after: int | None) -> int | None:
    """Calls the shared breaker refused between two readings (``None`` if either
    reading was unavailable -- an unknown is not "none refused")."""
    if before is None or after is None:
        return None
    return after - before


# ── activity pass ────────────────────────────────────────────────────
#
# The activity pass hands a bounded manager list to the Insider-Trading
# crawler (``src/intel/crawler.py``) and gets back a summary that says
# ``budgetExhausted`` and little else.  Everything else about where the crawl
# stands lives in the snapshot the crawler persists (``members``, ``leagues``,
# ``cursor``, ``lastRun``), which is what is read here -- read-only.

STOPPED_UNKNOWN = "unknown"


def _iso_to_ms(value: Any) -> int | None:
    """Epoch ms of an ISO-8601 string; ``None`` for absent or unparseable."""
    if not value:
        return None
    try:
        return int(datetime.fromisoformat(str(value)).timestamp() * 1000)
    except (ValueError, TypeError):
        return None


def _count(value: Any) -> int | None:
    """``len`` of a list, ``None`` for anything else (absent is not empty)."""
    return len(value) if isinstance(value, list) else None


def _activity_stopped_reason(
    *,
    summary: dict[str, Any],
    pending_members: int | None,
    pending_leagues: int | None,
    breaker_refused_calls: int | None,
    capped: bool,
) -> str:
    """Why an activity run ended, from the crawler's summary and its cursor.

    ``budgetExhausted`` alone cannot decide this: the crawler sets it from the
    pending MANAGERS and the pending leagues it did not reach, while
    ``completed`` is also false when only RETRY leagues (fetches that failed
    this run) are queued.  A run with any pending work therefore never reads
    ``completed``: when the budget is not what stopped it, it reads
    ``work_pending``.  ``pending_leagues`` is the cursor's league list, which
    already includes the retry leagues.

    ``completed`` is claimed only on positive evidence that nothing is pending
    (the crawler said so, or the saved cursor is empty); a summary and snapshot
    that say nothing about it leave the reason ``unknown``.
    """
    if breaker_refused_calls is not None and breaker_refused_calls > 0:
        return STOPPED_BREAKER_OPEN
    budget_flag = summary.get("budgetExhausted")
    completed_flag = summary.get("completed")
    if not isinstance(budget_flag, bool) and not isinstance(completed_flag, bool):
        # The summary did not say whether the budget ended the run, nor whether
        # it finished.
        return STOPPED_UNKNOWN
    cursor_pending = None if pending_members is None else bool(pending_members or pending_leagues)
    pending_evidence = completed_flag is False or budget_flag is True or bool(cursor_pending)
    no_pending_evidence = completed_flag is True or cursor_pending is False
    if pending_evidence:
        reason = classify_stop(budget_stopped=budget_flag is True, work_remains=True, capped=capped)
        return STOPPED_WORK_PENDING if reason == STOPPED_COMPLETED else reason
    if no_pending_evidence:
        return classify_stop(budget_stopped=False, work_remains=False, capped=capped)
    return STOPPED_UNKNOWN


def build_activity_coverage(
    *,
    eligible_managers: int,
    selected_managers: int,
    call_budget: int,
    refresh: dict[str, Any] | None,
    state: dict[str, Any] | None,
    breaker_refused_calls: int | None,
    as_of_ms: int | None = None,
) -> dict[str, Any]:
    """Coverage of one activity-pass run, in MANAGERS.

    Managers are the unit because both phases of the crawl start from them, and
    because the pass's own cap (``--max-managers``) acts on them: managers past
    the cap are not in the work list at all, so they are counted in
    ``remainingUnvisited`` and ``neverVisited`` rather than silently outside the
    denominator.

    ``refresh`` is ``intel_service.refresh_intel``'s summary; ``state`` is the
    snapshot it persisted.  Either may be unusable, and every figure that needed
    it is then ``None`` -- a snapshot that was never saved says nothing about the
    cursor, so it cannot be read as "no pending work".
    """
    as_of = now_ms() if as_of_ms is None else int(as_of_ms)
    if eligible_managers == 0:
        # Nothing was eligible, so nothing was attempted: a measured zero, not a
        # missing one.  (The crawl never ran, so there is no summary or snapshot.)
        return build_pass_coverage(
            pass_name=PASS_ACTIVITY,
            unit="managers",
            attempted=0,
            succeeded=0,
            failed=0,
            eligible_total=0,
            remaining_unvisited=0,
            stopped_reason=STOPPED_NO_WORK,
            calls_used=0,
            call_budget=call_budget,
            never_visited=0,
            as_of_ms=as_of,
        )
    summary = refresh if isinstance(refresh, dict) else {}
    snapshot = state if isinstance(state, dict) and state.get("generatedAt") else None

    pending_members: int | None = None
    pending_leagues: int | None = None
    if snapshot is not None:
        # ``cursor`` is ``None`` when nothing is pending: a measured zero.
        cursor = snapshot.get("cursor") if isinstance(snapshot.get("cursor"), dict) else {}
        pending_members = len(cursor.get("pendingMembers") or [])
        pending_leagues = len(cursor.get("pendingLeagues") or [])

    failed = _count(summary.get("failedMemberIds"))
    attempted = None if pending_members is None else selected_managers - pending_members
    succeeded = attempted - failed if attempted is not None and failed is not None else None
    remaining = None if attempted is None else eligible_managers - attempted
    not_selected = eligible_managers - selected_managers

    # Oldest visit among managers that have ever been visited, from the saved
    # snapshot.  The snapshot only keeps the CURRENT pool, so managers outside
    # it (past the cap) are by construction never-visited here.
    visited_ms: list[int] = []
    if snapshot is not None:
        members = snapshot.get("members") if isinstance(snapshot.get("members"), dict) else {}
        for entry in members.values():
            crawled = _iso_to_ms(entry.get("lastCrawledAt")) if isinstance(entry, dict) else None
            if crawled is not None:
                visited_ms.append(crawled)
    oldest_ms = min(visited_ms) if visited_ms else None
    never_visited = None if snapshot is None else eligible_managers - len(visited_ms)

    reason = _activity_stopped_reason(
        summary=summary,
        pending_members=pending_members,
        pending_leagues=pending_leagues,
        breaker_refused_calls=breaker_refused_calls,
        capped=not_selected > 0,
    )

    league_phase: dict[str, Any] = {"trackedLeagues": None}
    if snapshot is not None:
        leagues = snapshot.get("leagues") if isinstance(snapshot.get("leagues"), dict) else {}
        tracked = [e for e in leagues.values() if isinstance(e, dict) and not e.get("inactive")]
        fetched_ms: list[int] = []
        for entry in tracked:
            fetch_state = entry.get("fetchState")
            fetched = (
                _iso_to_ms(fetch_state.get("lastFetchedAt"))
                if isinstance(fetch_state, dict)
                else None
            )
            if fetched is not None:
                fetched_ms.append(fetched)
        last_run = snapshot.get("lastRun") if isinstance(snapshot.get("lastRun"), dict) else {}
        oldest_fetch_ms = min(fetched_ms) if fetched_ms else None
        league_phase = {
            "trackedLeagues": len(tracked),
            "pendingLeagues": pending_leagues,
            "retryLeagues": _count(last_run.get("retryLeagueIds")),
            "neverFetchedLeagues": len(tracked) - len(fetched_ms),
            "oldestFetchMs": oldest_fetch_ms,
            "oldestFetchAgeDays": age_days(oldest_fetch_ms, as_of_ms=as_of),
        }

    calls = summary.get("callsUsed")
    return build_pass_coverage(
        pass_name=PASS_ACTIVITY,
        unit="managers",
        attempted=attempted,
        succeeded=succeeded,
        failed=failed,
        eligible_total=eligible_managers,
        remaining_unvisited=remaining,
        stopped_reason=reason,
        calls_used=calls if isinstance(calls, int) else None,
        call_budget=call_budget,
        oldest_crawl_ms=oldest_ms,
        never_visited=never_visited,
        oldest_basis="intel snapshot members[].lastCrawledAt for the current manager pool",
        as_of_ms=as_of,
        extra={
            "managers": {
                "qualified": eligible_managers,
                "selected": selected_managers,
                "notSelectedByCap": not_selected,
                "pendingMembers": pending_members,
            },
            "leaguePhase": league_phase,
            "breakerRefusedCalls": breaker_refused_calls,
        },
    )
