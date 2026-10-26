"""Sharp Tracker's transaction crawl — the movements the board reads.

WHY THIS EXISTS
---------------
Until this module, ``ledger.ingest_events`` had exactly ONE caller:
``src/intel/ingest.py``, migrating Insider Trading's league-mate
snapshot.  So the ledger held only the user's own league-mates'
movements.  Discovery mapped ~356 managers across ~836 leagues and the
records crawl scored them, but **nobody ever fetched their trades** — a
Sharp Tracker board wired to that ledger would have rendered empty, and
correctly so.

This is the crawl that fills the gap.

HOW IT DIFFERS FROM ``intel.crawler.crawl``
-------------------------------------------
That one is MEMBER-driven: it starts from the pool, discovers each
member's leagues, and writes a per-league JSON snapshot.  This one is
LEAGUE-driven: the discovery graph already knows which leagues qualify,
so it walks those directly and writes straight into the ledger.

What it deliberately does NOT do is re-implement transaction parsing.
``crawler._events_from_tx`` already handles paired add/drop semantics,
pick discriminators, ``status == "complete"`` filtering and the
roster-slot movement key (D10); the audit found four independent
Sleeper transaction fetchers in this repo and a fifth would be the
problem, not the feature.  So extraction, the roster-owner map, the
week selection and the call budget are all reused as-is.

POOL = EVERY ROSTER OWNER IN THE LEAGUE, NOT JUST THE SHARPS
------------------------------------------------------------
Both sides of a trade are recorded, then the board filters to the
qualified cohort at READ time (``asset_signals(user_ids=...)``).  Three
reasons that ordering is right:

1. Qualification MOVES.  Records accumulate every week, so a manager
   who qualifies next month should arrive with history rather than
   starting blank.
2. Sharp-vs-sharp disagreement needs both sides present to be visible
   at all.
3. Filtering at read time is a WHERE clause; filtering at crawl time is
   a re-crawl.
"""

from __future__ import annotations

import json
import logging
import sqlite3
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Sequence

from src.intel import crawler, ledger
from src.sharp import discovery

log = logging.getLogger(__name__)

# Lower than the intel crawler's 900: this runs against hundreds of
# leagues on a timer, and Sleeper's published guidance is to stay under
# 1000 calls/minute.  A capped run that resumes beats a greedy one that
# trips a limiter.
DEFAULT_BUDGET = 600

# A league costs at least 2 calls (rosters + one transactions week), so
# stopping below this leaves a league half-fetched.
_MIN_CALLS_PER_LEAGUE = 2

# A league whose ``/rosters`` answered 404 is GONE (deleted, or an id that never
# existed) -- not "failed" and not "no trades".  It is recorded with a timestamp
# in ``sharp_league_gone`` and left out of the queue for this long.  Weekly: the
# same re-check rule the format-capture pass uses
# (``league_format_capture.DEFAULT_REFRESH_AFTER_HOURS``).
GONE_RECHECK_AFTER_HOURS = 168.0
# Once past that window, at most this many gone leagues (stalest check first) are
# re-checked per run -- a trickle, not a wall.  A gone league is never skipped
# forever (a transient or mistaken 404 heals), and the re-check can never again
# become the 598-league head of the queue: it costs at most this many calls of a
# run's budget.  PRIOR, not fitted: ~3% of the default 600-call budget, which at
# four runs a day cycles a few hundred gone leagues in about the weekly window.
GONE_RECHECK_MAX_PER_RUN = 20

STOPPED_BUDGET_EXHAUSTED = "budget_exhausted"
STOPPED_BREAKER_OPEN = "sleeper_breaker_open"


class _Outcome:
    """A named, non-payload answer from the fetcher (compared by identity)."""

    def __init__(self, name: str) -> None:
        self._name = name

    def __repr__(self) -> str:
        return self._name


#: The fetcher's answer for a resource Sleeper says does not exist (HTTP 404, or
#: a 200 with a JSON ``null`` body).  ``None`` stays "the fetch failed" -- the two
#: used to be indistinguishable, which is how deleted leagues read as an outage.
NOT_FOUND = _Outcome("NOT_FOUND")
#: The fetcher's answer when the shared ``sleeper_api`` circuit breaker refused
#: the call: Sleeper was not contacted at all.
BREAKER_OPEN = _Outcome("BREAKER_OPEN")

_GONE_SCHEMA = """
CREATE TABLE IF NOT EXISTS sharp_league_gone (
  league_id       TEXT PRIMARY KEY,
  first_gone_ms   INTEGER NOT NULL,
  last_checked_ms INTEGER NOT NULL,
  not_found_count INTEGER NOT NULL,
  endpoint        TEXT NOT NULL
);
"""


def ensure_gone_schema(conn: sqlite3.Connection) -> None:
    """Additive ``CREATE TABLE IF NOT EXISTS`` -- deliberately NOT wired to
    ``ledger.SCHEMA_VERSION``: a version bump runs ``_migrate`` and clears the
    movement tables and this crawl's fetch cursor on every deployed ledger.
    (Same posture as ``league_format_capture.ensure_schema`` and
    ``roster_store.ensure_roster_schema``.)  ``executescript`` commits, so call
    it ONCE per run, before any transaction that must stay open."""
    conn.executescript(_GONE_SCHEMA)


def _default_http_get(url: str) -> Any:
    """The crawl's fetcher: the payload on success, ``None`` on a failure,
    :data:`NOT_FOUND` for a 404 / null body, :data:`BREAKER_OPEN` when the shared
    ``sleeper_api`` breaker refused the call.

    It still rides the breaker (a real Sleeper outage must still fast-fail), but
    through the classifying variant, so the crawl can tell "this league is gone"
    and "the breaker is open" apart from an ordinary failure.
    """
    from src.api import sleeper_overlay  # noqa: PLC0415

    kind, payload = sleeper_overlay._http_get_json_classified(url)
    if kind == sleeper_overlay.FETCH_NOT_FOUND:
        return NOT_FOUND
    if kind == sleeper_overlay.FETCH_BREAKER_OPEN:
        return BREAKER_OPEN
    return payload


@dataclass
class SharpCrawlResult:
    leagues_considered: int = 0
    leagues_fetched: int = 0
    leagues_failed: int = 0
    leagues_pending: int = 0
    # Leagues whose rosters answered 404 / null THIS run (newly marked gone, or
    # re-confirmed after the re-check window).  Not failures; not "no trades".
    leagues_gone: int = 0
    # Leagues already known gone and still inside the re-check window: left out of
    # the queue, so they cost no budget and are not "pending".
    leagues_gone_skipped: int = 0
    # Previously-gone leagues that answered with rosters again (mark cleared).
    leagues_recovered: int = 0
    movements_ingested: int = 0
    transactions_seen: int = 0
    calls_used: int = 0
    week: int | None = None
    # Why the pass ended before its queue did: ``budget_exhausted`` or
    # ``sleeper_breaker_open`` (the shared breaker refused a call, so the rest of
    # the queue was NOT attempted).  ``None`` = the queue was walked to the end.
    stopped_reason: str | None = None
    errors: dict[str, str] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "leaguesConsidered": self.leagues_considered,
            "leaguesFetched": self.leagues_fetched,
            "leaguesFailed": self.leagues_failed,
            "leaguesPending": self.leagues_pending,
            "leaguesGone": self.leagues_gone,
            "leaguesGoneSkipped": self.leagues_gone_skipped,
            "leaguesRecovered": self.leagues_recovered,
            "movementsIngested": self.movements_ingested,
            "transactionsSeen": self.transactions_seen,
            "callsUsed": self.calls_used,
            "week": self.week,
            "stoppedReason": self.stopped_reason,
            "errors": dict(self.errors),
        }


def _load_fetch_state(conn) -> dict[str, dict[str, Any]]:
    rows = conn.execute(
        """
        SELECT league_id, max_created_ms, boundary_tx_ids, backfilled, last_fetched_ms
        FROM sharp_league_fetch
        """
    ).fetchall()
    out: dict[str, dict[str, Any]] = {}
    for row in rows:
        try:
            boundary = json.loads(row["boundary_tx_ids"] or "[]")
        except (ValueError, TypeError):
            boundary = []
        out[str(row["league_id"])] = {
            "maxCreatedSeen": int(row["max_created_ms"] or 0),
            "boundaryTxIds": [str(t) for t in boundary if t],
            "backfilled": bool(row["backfilled"]),
            "lastFetchedMs": int(row["last_fetched_ms"] or 0),
        }
    return out


def _save_fetch_state(conn, league_id: str, state: dict[str, Any], *, error: str | None) -> None:
    conn.execute(
        """
        INSERT INTO sharp_league_fetch
          (league_id, max_created_ms, boundary_tx_ids, backfilled, last_fetched_ms, last_error)
        VALUES (?, ?, ?, ?, ?, ?)
        ON CONFLICT(league_id) DO UPDATE SET
          max_created_ms  = excluded.max_created_ms,
          boundary_tx_ids = excluded.boundary_tx_ids,
          backfilled      = excluded.backfilled,
          last_fetched_ms = excluded.last_fetched_ms,
          last_error      = excluded.last_error
        """,
        (
            str(league_id),
            int(state.get("maxCreatedSeen") or 0),
            json.dumps(sorted(state.get("boundaryTxIds") or [])),
            1 if state.get("backfilled") else 0,
            int(state.get("lastFetchedMs") or 0),
            error,
        ),
    )


def _load_gone_state(conn) -> dict[str, dict[str, Any]]:
    """``{league_id: {...}}`` for every league last observed gone.  A ledger
    without the table reads as "none observed", never as an error."""
    try:
        rows = conn.execute(
            """
            SELECT league_id, first_gone_ms, last_checked_ms, not_found_count, endpoint
            FROM sharp_league_gone
            """
        ).fetchall()
    except sqlite3.OperationalError:
        return {}
    return {
        str(r["league_id"]): {
            "firstGoneMs": int(r["first_gone_ms"]),
            "lastCheckedMs": int(r["last_checked_ms"]),
            "notFoundCount": int(r["not_found_count"]),
            "endpoint": str(r["endpoint"] or ""),
        }
        for r in rows
    }


def _record_gone(conn, league_id: str, *, now_ms: int, endpoint: str) -> None:
    """Mark a league gone, or re-confirm it.  ``first_gone_ms`` survives a
    re-confirmation, so the row says how long Sleeper has been refusing it."""
    conn.execute(
        """
        INSERT INTO sharp_league_gone
          (league_id, first_gone_ms, last_checked_ms, not_found_count, endpoint)
        VALUES (?, ?, ?, 1, ?)
        ON CONFLICT(league_id) DO UPDATE SET
          last_checked_ms = excluded.last_checked_ms,
          not_found_count = sharp_league_gone.not_found_count + 1,
          endpoint        = excluded.endpoint
        """,
        (str(league_id), int(now_ms), int(now_ms), endpoint),
    )


def _clear_gone(conn, league_id: str) -> None:
    conn.execute("DELETE FROM sharp_league_gone WHERE league_id = ?", (str(league_id),))


def _split_gone(
    league_ids: Sequence[str],
    gone_state: dict[str, dict[str, Any]],
    *,
    now_ms: int,
    recheck_after_hours: float = GONE_RECHECK_AFTER_HOURS,
    max_recheck: int | None = None,
) -> tuple[list[str], list[str], list[str]]:
    """``(healthy, recheck, skipped)``.

    * a league with no gone mark is ``healthy`` -- the normal queue;
    * a gone league INSIDE the re-check window is ``skipped`` (it would only 404
      again and burn a budget slot);
    * a gone league PAST the window is due: the ``max_recheck`` stalest-checked
      go to ``recheck`` (a bounded trickle, see :data:`GONE_RECHECK_MAX_PER_RUN`),
      the rest are ``skipped`` until a later run.
    """
    window_ms = int(recheck_after_hours * 3600 * 1000)
    limit = GONE_RECHECK_MAX_PER_RUN if max_recheck is None else max(0, int(max_recheck))
    healthy: list[str] = []
    due: list[str] = []
    skipped: list[str] = []
    for lid in league_ids:
        gone = gone_state.get(str(lid))
        if gone is None:
            healthy.append(lid)
        elif (now_ms - int(gone["lastCheckedMs"])) < window_ms:
            skipped.append(lid)
        else:
            due.append(lid)
    due.sort(key=lambda lid: (int(gone_state[str(lid)]["lastCheckedMs"]), str(lid)))
    return healthy, due[:limit], skipped + due[limit:]


def _league_order(league_ids: Sequence[str], fetch_state: dict[str, dict[str, Any]]) -> list[str]:
    """Never-fetched leagues first, then the stalest.

    A budget-capped run must make progress ACROSS the graph rather than
    re-walking whichever leagues happen to sort first — otherwise the
    tail of the discovery graph never gets crawled at all.
    """
    return sorted(
        league_ids,
        key=lambda lid: (
            1 if fetch_state.get(str(lid), {}).get("backfilled") else 0,
            fetch_state.get(str(lid), {}).get("lastFetchedMs", 0),
            str(lid),
        ),
    )


def _current_week(budget: crawler._CallBudget) -> int:
    """Sleeper's current NFL week, defaulting conservatively.

    Week 0 is REAL — Sleeper files preseason trades there — so it is
    never coerced up to 1 (same rule as the intel crawler).
    """
    if not budget.can_call():
        return 1
    state = budget.get(f"{crawler.SLEEPER_BASE}/state/nfl")
    if isinstance(state, dict):
        try:
            return max(0, min(18, int(state.get("week"))))
        except (TypeError, ValueError):
            pass
    return 1


def crawl_transactions(
    league_ids: Sequence[str] | None = None,
    *,
    budget: int = DEFAULT_BUDGET,
    sleep_s: float = crawler.DEFAULT_SLEEP_S,
    http_get: Callable[[str], Any] | None = None,
    now_ms: int | None = None,
    sleep_fn: Callable[[float], None] = time.sleep,
    ledger_path: Path | None = None,
    skip_gone: bool = True,
) -> SharpCrawlResult:
    """One budgeted pass over the sharp-eligible leagues.

    Never raises on a fetch failure: a league that fails is recorded and
    skipped, its cursor left untouched so the next run retries it.  A
    failed roster fetch skips the league ENTIRELY rather than attributing
    movements with a stale owner map — same rule the intel crawler
    follows, and for the same reason.

    ``http_get`` returns the payload, ``None`` for a failure, and may return
    :data:`NOT_FOUND` / :data:`BREAKER_OPEN` (see :func:`_default_http_get`).

    **A league whose rosters answer 404 is GONE, not failed.**  It is recorded
    (``sharp_league_gone``, timestamped) and skipped for
    :data:`GONE_RECHECK_AFTER_HOURS`; after that at most
    :data:`GONE_RECHECK_MAX_PER_RUN` of them are re-checked per run, so it
    neither heads the queue nor is forgotten.  It is not deleted, and it is not
    "no trades".  ``skip_gone=False`` (an operator naming leagues explicitly)
    fetches a known-gone league like any other.

    **A refused call stops the pass.**  When the shared ``sleeper_api`` breaker
    refuses a call, Sleeper was not contacted; every remaining league would
    fast-fail and burn a paced budget slot (and its sleep) on an instant
    ``None``.  The pass stops, the cursor of the league in hand is left alone,
    and ``stopped_reason`` says ``sleeper_breaker_open``.
    """
    now = now_ms if now_ms is not None else int(time.time() * 1000)
    fetch = http_get or _default_http_get
    b = crawler._CallBudget(budget, sleep_s, fetch, sleep_fn)
    result = SharpCrawlResult()

    conn = ledger.connect(ledger_path)
    try:
        targets = [
            str(lid)
            for lid in (
                league_ids
                if league_ids is not None
                else discovery.sharp_eligible_league_ids(ledger_path=ledger_path)
            )
            if str(lid or "").strip()
        ]
        result.leagues_considered = len(targets)
        if not targets:
            return result

        ensure_gone_schema(conn)
        fetch_state = _load_fetch_state(conn)
        gone_state = _load_gone_state(conn)
        if skip_gone:
            healthy, recheck, skipped = _split_gone(targets, gone_state, now_ms=now)
            # The re-check trickle goes first: it is capped, so it costs at most
            # GONE_RECHECK_MAX_PER_RUN calls; last, it would starve for as long
            # as healthy leagues use the whole budget (always, at this size).
            ordered = recheck + _league_order(healthy, fetch_state)
        else:
            skipped = []
            ordered = _league_order(targets, fetch_state)
        result.leagues_gone_skipped = len(skipped)
        week = _current_week(b)
        result.week = week

        for idx, lid in enumerate(ordered):
            if not b.can_call(_MIN_CALLS_PER_LEAGUE):
                result.leagues_pending = len(ordered) - idx
                result.stopped_reason = STOPPED_BUDGET_EXHAUSTED
                break

            rosters = b.get(f"{crawler.SLEEPER_BASE}/league/{lid}/rosters")
            if rosters is BREAKER_OPEN:
                # Sleeper was not contacted.  This league was not attempted,
                # so it (and everything after it) is still pending.
                result.leagues_pending = len(ordered) - idx
                result.stopped_reason = STOPPED_BREAKER_OPEN
                break
            if rosters is NOT_FOUND:
                # An answer, not an outage: Sleeper says this league does not
                # exist.  Record it (timestamped, not deleted) so it stops
                # heading the queue; it is neither a failure nor "no trades".
                _record_gone(conn, lid, now_ms=now, endpoint="rosters")
                conn.commit()
                result.leagues_gone += 1
                continue
            if not isinstance(rosters, list):
                # No CURRENT owner map means no safe attribution.  Skip
                # the league whole and leave its cursor alone.
                result.leagues_failed += 1
                result.errors[lid] = "rosters_fetch_failed"
                continue
            if lid in gone_state:
                # It answered with rosters again: the gone mark no longer holds.
                _clear_gone(conn, lid)
                conn.commit()  # never hold the writer lock across the next network call
                result.leagues_recovered += 1

            # Pool = everyone on this league's rosters.  See the module
            # docstring: both sides are recorded, the cohort filter is
            # applied at read time.
            all_owners = {
                str(r.get("owner_id") or "").strip()
                for r in rosters
                if isinstance(r, dict) and str(r.get("owner_id") or "").strip()
            }
            for roster in rosters:
                if isinstance(roster, dict):
                    all_owners.update(
                        str(c).strip()
                        for c in (roster.get("co_owners") or [])
                        if str(c or "").strip()
                    )
            rid_to_owner, _ = crawler._roster_owner_map(rosters, all_owners)
            if not rid_to_owner:
                result.leagues_failed += 1
                result.errors[lid] = "no_rosters_with_owners"
                continue

            state = fetch_state.get(lid) or {
                "maxCreatedSeen": 0,
                "boundaryTxIds": [],
                "backfilled": False,
            }
            max_seen = int(state.get("maxCreatedSeen") or 0)
            boundary_ids = {str(t) for t in state.get("boundaryTxIds") or []}
            is_backfill = not state.get("backfilled")

            weeks = crawler._weeks_to_fetch(
                {"fetchState": {"backfilled": state.get("backfilled")}}, week, None, now
            )
            backfill_cutoff = now - crawler.BACKFILL_MAX_DAYS * 24 * 3600 * 1000

            fetched: list[tuple[int, dict[str, Any]]] = []
            weeks_clean = True
            breaker_open = False
            for w in weeks:
                if not b.can_call():
                    weeks_clean = False
                    break
                txs = b.get(f"{crawler.SLEEPER_BASE}/league/{lid}/transactions/{w}")
                if txs is BREAKER_OPEN:
                    weeks_clean = False
                    breaker_open = True
                    break
                if not isinstance(txs, list):
                    weeks_clean = False
                    continue
                created = [
                    crawler._tx_created_ms(t)
                    for t in txs
                    if isinstance(t, dict) and crawler._tx_created_ms(t) > 0
                ]
                fetched.extend((w, t) for t in txs if isinstance(t, dict))
                # Backfill age stop.  Weeks 0-1 are exempt: they are the
                # degenerate offseason buckets and a stale week 0 must
                # not halt the walk.
                if is_backfill and w > 1 and created and max(created) < backfill_cutoff:
                    break

            known: set[str] = set()
            events: list[dict[str, Any]] = []
            new_max = max_seen
            for w, tx in fetched:
                created_ms = crawler._tx_created_ms(tx)
                tx_id = str(tx.get("transaction_id") or "")
                if created_ms < max_seen:
                    continue
                if created_ms == max_seen and tx_id in boundary_ids:
                    continue
                if created_ms > new_max:
                    new_max = created_ms
                if is_backfill and created_ms < backfill_cutoff:
                    continue
                events.extend(crawler._events_from_tx(tx, lid, w, rid_to_owner, all_owners, known))

            result.transactions_seen += len(fetched)
            if events:
                ingest = ledger.ingest_events(events, conn=conn)
                result.movements_ingested += ingest.movements_inserted

            if not weeks_clean:
                # Do NOT advance the cursor past a week we failed to
                # fetch — that would filter its transactions out
                # permanently.  Retry next run.
                reason = STOPPED_BREAKER_OPEN if breaker_open else "transactions_fetch_failed"
                result.leagues_failed += 1
                result.errors[lid] = reason
                _save_fetch_state(conn, lid, state, error=reason)
                conn.commit()
                if breaker_open:
                    result.leagues_pending = len(ordered) - idx - 1
                    result.stopped_reason = STOPPED_BREAKER_OPEN
                    break
                continue

            new_boundary = {
                str(tx.get("transaction_id") or "")
                for _w, tx in fetched
                if crawler._tx_created_ms(tx) == new_max and tx.get("transaction_id")
            }
            if new_max == max_seen:
                new_boundary |= boundary_ids
            _save_fetch_state(
                conn,
                lid,
                {
                    "maxCreatedSeen": new_max,
                    "boundaryTxIds": sorted(new_boundary),
                    "backfilled": True,
                    "lastFetchedMs": now,
                },
                error=None,
            )
            # Commit PER LEAGUE, not once for the whole crawl.  Every
            # iteration does network I/O, so a single end-of-crawl commit
            # held the SQLite writer lock across the entire budget — the
            # same contention records.py repaired per season (V1-59): in a
            # quiet period most leagues yield zero new events, nothing
            # else commits, and the implicit transaction opened by the
            # first _save_fetch_state upsert starves every concurrent
            # sharp unit past its 30 s busy_timeout.  Movements dedupe on
            # movement_id and fetch state upserts on league_id, so
            # per-league durability changes no outcome — only the lock
            # window.
            conn.commit()
            result.leagues_fetched += 1

        conn.commit()
    finally:
        conn.close()

    result.calls_used = b.used
    _log_summary(result)
    return result


def _log_summary(result: SharpCrawlResult) -> None:
    """One line saying what the pass did and why it ended, so a run that
    fetched nothing explains itself in the journal (the exit code cannot:
    2 means "leagues remain" however the pass ended)."""
    line = (
        "sharp transaction crawl: considered=%d fetched=%d failed=%d gone=%d "
        "gone_skipped=%d recovered=%d pending=%d calls=%d stopped=%s"
    )
    args = (
        result.leagues_considered,
        result.leagues_fetched,
        result.leagues_failed,
        result.leagues_gone,
        result.leagues_gone_skipped,
        result.leagues_recovered,
        result.leagues_pending,
        result.calls_used,
        result.stopped_reason or "none",
    )
    if result.stopped_reason == STOPPED_BREAKER_OPEN:
        log.error(
            line + " -- the shared sleeper_api circuit breaker REFUSED a call, so "
            "%d league(s) were NOT attempted (Sleeper was not contacted for them)",
            *args,
            result.leagues_pending,
        )
    else:
        log.info(line, *args)


def crawl_coverage(*, ledger_path: Path | None = None) -> dict[str, Any]:
    """How much of the sharp-eligible graph has actually been crawled.

    Reported so "no signal" and "not crawled yet" can never read the
    same on the board.
    """
    eligible = discovery.sharp_eligible_league_ids(ledger_path=ledger_path)
    conn = ledger.connect(ledger_path)
    try:
        row = conn.execute(
            "SELECT COUNT(*) AS n FROM sharp_league_fetch WHERE backfilled = 1"
        ).fetchone()
        crawled = int(row["n"] or 0) if row else 0
        stale = conn.execute(
            "SELECT MIN(last_fetched_ms) AS oldest FROM sharp_league_fetch WHERE backfilled = 1"
        ).fetchone()
        oldest = int(stale["oldest"] or 0) if stale and stale["oldest"] else None
        crawled_ids = {
            str(r["league_id"])
            for r in conn.execute(
                "SELECT league_id FROM sharp_league_fetch WHERE backfilled = 1"
            ).fetchall()
        }
        gone_ids = set(_load_gone_state(conn))
    finally:
        conn.close()
    eligible_ids = {str(lid) for lid in eligible}
    gone_eligible = eligible_ids & gone_ids
    return {
        "sharpEligibleLeagues": len(eligible),
        "leaguesCrawled": crawled,
        "leaguesUncrawled": max(0, len(eligible) - crawled),
        # Sleeper says these do not exist: they are in "uncrawled" for good, so
        # without this the uncrawled number reads as work still to do.
        "leaguesGone": len(gone_eligible),
        "leaguesUncrawledReachable": len(eligible_ids - crawled_ids - gone_ids),
        "oldestCrawlMs": oldest,
    }
