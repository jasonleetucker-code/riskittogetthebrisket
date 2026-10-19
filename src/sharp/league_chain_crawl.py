"""Budgeted ``previous_league_id`` chain pass for trade-bearing leagues (G6).

WHY THIS EXISTS
───────────────
League maturity (``league_filter.resolve_league_maturity``) is answered from
the persisted chain store (``ledger.league_season_chain``).  The records crawl
already records a hop for every season it walks -- but it walks only
SHARP-eligible leagues.  Trades also arrive from leagues the records crawl
never visits (Insider / activity lanes, KTC rows naming a Sleeper league), and
for those the store holds nothing, so their maturity is ``chain_not_walked``:
unknown, never "new".  This pass closes that gap with the same walker, the
same store and the same capture owner -- it adds no fourth chain walker:

    sleeper_client.iter_league_chain       the ONE walker
    ledger.record_league_chain_hop         the ONE chain schema
    league_format_capture.record_capture   each prior season's format (G4f)

FETCH POLICY
────────────
Targets are trade-bearing leagues in the intel ledger whose point-in-time
maturity is still a LOWER BOUND because a link was never walked (never-walked
starts first, then partially walked chains; ids in sorted order -- stable, so
a budget-capped run resumes where the last one stopped).  A hop the store
already holds as ``complete`` is followed from the store at ZERO calls --
Sleeper settings are frozen once a league completes.  Everything else costs
one public ``GET /v1/league/{id}``.  The pass stops at the first HTTP 429
(``rate_limited``) or after :data:`MAX_CONSECUTIVE_FAILURES` failed fetches,
and never spends past its budget.

It is OFF unless given a budget: :data:`DEFAULT_BUDGET` is ``0`` and the
transaction-crawl timer passes ``--chain-budget`` explicitly, so enabling it is
a reviewed unit change, never a default.  Every Sleeper crawl shares the box's
public IP; this one runs inside the transaction-crawl timer's slot (after its
format passes, skipped when they stopped on a 429).

WHAT THIS DOES NOT DO
─────────────────────
It touches no value, writes no ``leagues`` row (prior seasons are not the
discovery graph), and never runs inside a request.  Results are COUNTS; no
league id leaves this module except in the box-local store.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

from src.intel import ledger, league_filter

log = logging.getLogger(__name__)

#: OFF by default -- see the module note.
DEFAULT_BUDGET = 0
DEFAULT_SLEEP_S = 0.12
#: Same stop the format pass uses: a run of transport failures means the
#: shared IP or Sleeper is unwell; stop rather than spend the budget on it.
MAX_CONSECUTIVE_FAILURES = 10
#: ``league_season_chain.source`` for hops this pass records.
SOURCE_CHAIN_PASS = "chain_pass_league_endpoint"


@dataclass
class ChainCrawlResult:
    targets: int = 0
    chains_walked: int = 0
    hops_fetched: int = 0
    hops_from_store: int = 0
    hops_new: int = 0
    captures_new: int = 0
    calls_used: int = 0
    stopped_reason: str | None = None
    leagues_pending: int = 0
    #: ``{coverage state/reason: count}`` -- aggregate, never ids.
    walk_outcomes: dict[str, int] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "targets": self.targets,
            "chainsWalked": self.chains_walked,
            "hopsFetched": self.hops_fetched,
            "hopsFromStore": self.hops_from_store,
            "hopsNew": self.hops_new,
            "capturesNew": self.captures_new,
            "callsUsed": self.calls_used,
            "stoppedReason": self.stopped_reason,
            "leaguesPending": self.leagues_pending,
            "walkOutcomes": dict(sorted(self.walk_outcomes.items())),
        }


def _trade_bearing_league_ids(conn: Any) -> list[str]:
    try:
        rows = conn.execute(
            "SELECT DISTINCT league_id FROM asset_movements WHERE tx_type = 'trade'"
        ).fetchall()
    except Exception:  # noqa: BLE001 — an empty / foreign ledger has no targets
        return []
    return sorted({str(r[0]) for r in rows if r[0]})


def due_league_ids(
    candidates: list[str],
    chain: dict[str, league_filter.ChainHop],
) -> list[str]:
    """The candidates whose point-in-time maturity a walk could still improve:
    never walked first, then chains stopped at an unwalked link or crossing a
    predecessor last seen in progress (it may have completed since; the walk
    re-fetches every non-complete hop).  An EXACT answer, or one that already
    proves the primary bar, is not due."""
    never: list[str] = []
    partial: list[str] = []
    for lid in sorted(set(candidates)):
        m = league_filter.resolve_league_maturity(lid, chain)
        if m.stop_reason == league_filter.STOP_START_NOT_WALKED:
            never.append(lid)
        elif not m.meets(league_filter.MATURITY_PRIMARY_MIN_COMPLETED_SEASONS) and (
            m.stop_reason == league_filter.STOP_NOT_WALKED
            or league_filter.FLAG_STATUS_UNVERIFIED in m.flags
        ):
            partial.append(lid)
    return never + partial


def _stored_league(hop: league_filter.ChainHop) -> dict[str, Any]:
    """A completed hop rendered as the league fields the walker reads."""
    settings: dict[str, Any] = {}
    if hop.league_type is not None:
        settings["type"] = hop.league_type
    if hop.best_ball is not None:
        settings["best_ball"] = int(hop.best_ball)
    return {
        "league_id": hop.league_id,
        "season": hop.season,
        "status": hop.status,
        "previous_league_id": hop.previous_league_id or "0",
        "settings": settings,
    }


def crawl_league_chains(
    *,
    league_ids: list[str] | None = None,
    budget: int = DEFAULT_BUDGET,
    http_get: Callable[[str], Any] | None = None,
    ledger_path: Path | None = None,
    sleep_s: float = DEFAULT_SLEEP_S,
    sleep_fn: Callable[[float], None] = time.sleep,
    clock_ms: Callable[[], int] | None = None,
) -> ChainCrawlResult:
    """Walk the due chains within ``budget`` Sleeper calls, recording every
    fetched hop and its point-in-time format.  Commits per hop (the writer
    lock is never held across network I/O); never raises on a fetch failure.

    ``http_get`` is the format pass's classified fetcher contract: payload,
    ``None`` for a league that does not exist, ``lfc.FETCH_ERROR`` for a
    transport failure, ``lfc.RateLimited`` raised on a 429.
    """
    from src.public_league import sleeper_client  # noqa: PLC0415
    from src.sharp import league_format_capture as lfc  # noqa: PLC0415

    result = ChainCrawlResult()
    if budget <= 0:
        result.stopped_reason = "chain_budget_zero"
        return result
    fetch = http_get or lfc._default_http_get
    tick = clock_ms or (lambda: int(time.time() * 1000))
    conn = ledger.connect(ledger_path)
    try:
        ledger.ensure_league_chain_schema(conn)
        lfc.ensure_schema(conn)
        chain: dict[str, league_filter.ChainHop] = ledger.load_league_chain(conn)
        candidates = league_ids if league_ids is not None else _trade_bearing_league_ids(conn)
        due = due_league_ids(list(candidates), chain)
        result.targets = len(due)
        state: dict[str, Any] = {"calls": 0, "consecutive": 0, "stop": None, "live": set()}

        def fetch_league(lid: str) -> tuple[str, Any]:
            hop = chain.get(lid)
            if hop is not None and hop.is_complete:
                result.hops_from_store += 1
                return sleeper_client.FETCH_OK, _stored_league(hop)
            if state["calls"] >= budget:
                state["stop"] = "budget_exhausted"
                return "budget", None
            if state["calls"] and sleep_s:
                sleep_fn(sleep_s)
            state["calls"] += 1
            try:
                league = fetch(f"{lfc.SLEEPER_BASE}/league/{lid}")
            except lfc.RateLimited:
                state["stop"] = "rate_limited"
                return sleeper_client.FETCH_RATE_LIMITED, None
            if league is lfc.FETCH_ERROR or (league is not None and not isinstance(league, dict)):
                state["consecutive"] += 1
                if state["consecutive"] >= MAX_CONSECUTIVE_FAILURES:
                    state["stop"] = "consecutive_fetch_failures"
                return sleeper_client.FETCH_ERROR, None
            state["consecutive"] = 0
            if league is None:
                return sleeper_client.FETCH_NOT_FOUND, None
            if str(league.get("league_id") or "").strip() != lid:
                # A payload naming another league proves nothing about this one.
                return sleeper_client.FETCH_ERROR, None
            state["live"].add(lid)
            return sleeper_client.FETCH_OK, league

        def on_fetched(league: dict[str, Any]) -> None:
            lid = str(league.get("league_id") or "").strip()
            if lid not in state["live"]:
                return  # answered from the store: nothing new to record
            state["live"].discard(lid)
            now = tick()
            result.hops_fetched += 1
            if (
                ledger.record_league_chain_hop(
                    conn, league, observed_ms=now, source=SOURCE_CHAIN_PASS
                )
                == "new"
            ):
                result.hops_new += 1
            if (
                lfc.record_capture(
                    conn, league, captured_ms=now, source=lfc.SOURCE_CHAIN_WALK, league_id=lid
                )
                == "new"
            ):
                result.captures_new += 1
            hop = league_filter.ChainHop.from_league(league, observed_ms=now)
            if hop is not None:
                chain[lid] = hop
            conn.commit()

        for i, start in enumerate(due):
            if state["stop"] is not None:
                result.leagues_pending = len(due) - i
                break
            coverage: dict[str, Any] = {}
            for _league in sleeper_client.iter_league_chain(
                start,
                league_filter.MATURITY_MAX_HOPS,
                fetch_league_fn=fetch_league,
                coverage=coverage,
                on_league_fetched=on_fetched,
            ):
                pass
            result.chains_walked += 1
            key = str(coverage.get("reason") or coverage.get("state") or "unknown")
            result.walk_outcomes[key] = result.walk_outcomes.get(key, 0) + 1
        conn.commit()
        result.calls_used = int(state["calls"])
        result.stopped_reason = state["stop"]
    finally:
        conn.close()
    log.info("sharp.league_chain_crawl: %s", result.to_dict())
    return result
