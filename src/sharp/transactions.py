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


@dataclass
class SharpCrawlResult:
    leagues_considered: int = 0
    leagues_fetched: int = 0
    leagues_failed: int = 0
    leagues_pending: int = 0
    movements_ingested: int = 0
    transactions_seen: int = 0
    calls_used: int = 0
    week: int | None = None
    errors: dict[str, str] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "leaguesConsidered": self.leagues_considered,
            "leaguesFetched": self.leagues_fetched,
            "leaguesFailed": self.leagues_failed,
            "leaguesPending": self.leagues_pending,
            "movementsIngested": self.movements_ingested,
            "transactionsSeen": self.transactions_seen,
            "callsUsed": self.calls_used,
            "week": self.week,
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
) -> SharpCrawlResult:
    """One budgeted pass over the sharp-eligible leagues.

    Never raises on a fetch failure: a league that fails is recorded and
    skipped, its cursor left untouched so the next run retries it.  A
    failed roster fetch skips the league ENTIRELY rather than attributing
    movements with a stale owner map — same rule the intel crawler
    follows, and for the same reason.
    """
    now = now_ms if now_ms is not None else int(time.time() * 1000)
    fetch = http_get or crawler._default_http_get
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

        fetch_state = _load_fetch_state(conn)
        ordered = _league_order(targets, fetch_state)
        week = _current_week(b)
        result.week = week

        for idx, lid in enumerate(ordered):
            if not b.can_call(_MIN_CALLS_PER_LEAGUE):
                result.leagues_pending = len(ordered) - idx
                break

            rosters = b.get(f"{crawler.SLEEPER_BASE}/league/{lid}/rosters")
            if not isinstance(rosters, list):
                # No CURRENT owner map means no safe attribution.  Skip
                # the league whole and leave its cursor alone.
                result.leagues_failed += 1
                result.errors[lid] = "rosters_fetch_failed"
                continue

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
            for w in weeks:
                if not b.can_call():
                    weeks_clean = False
                    break
                txs = b.get(f"{crawler.SLEEPER_BASE}/league/{lid}/transactions/{w}")
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
                result.leagues_failed += 1
                result.errors[lid] = "transactions_fetch_failed"
                _save_fetch_state(conn, lid, state, error="transactions_fetch_failed")
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
            result.leagues_fetched += 1

        conn.commit()
    finally:
        conn.close()

    result.calls_used = b.used
    return result


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
    finally:
        conn.close()
    return {
        "sharpEligibleLeagues": len(eligible),
        "leaguesCrawled": crawled,
        "leaguesUncrawled": max(0, len(eligible) - crawled),
        "oldestCrawlMs": oldest,
    }
