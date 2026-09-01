#!/usr/bin/env python3
"""Backtest the FAAB recommender: OLD formula vs NEW engine.

Replays this league's REAL historical waiver claims (Sleeper's
completed ``waiver`` / ``free_agent`` transactions, persisted by
``scripts/fetch_faab_history.py`` under ``data/faab/``) through both
recommenders and reports, per claim and in aggregate, what each model
would have bid against what the claim actually cleared for.

    python scripts/faab_backtest.py
    python scripts/faab_backtest.py --league dynasty_new --limit 40
    python scripts/faab_backtest.py --json > /tmp/faab_backtest.json

Exit codes: 0 ok · 1 error · 2 no data.

READ THIS BEFORE QUOTING ANY NUMBER THIS SCRIPT PRINTS
──────────────────────────────────────────────────────
This is a *biased* backtest, and the bias is structural rather than
incidental.  It is stated at the top of every run (``--json`` carries
the same list under ``caveats``) and the per-band sample sizes are
printed so a reader can see which rows are worth anything.

1.  LOOK-AHEAD VALUE.  Every claim is joined to **today's** canonical
    value.  A player added for $0 in week 9 of 2024 who has since
    broken out now grades 3900, so the high-value bands are stuffed
    with players who were cheap precisely BECAUSE nobody knew yet.
    That makes both models look like they are "overbidding" the top
    bands and makes the top bands look artificially cheap.  There is
    no fix available offline — the platform keeps no historical board
    snapshot reaching back to 2024.
2.  WINNING BIDS ONLY.  Sleeper never exposes losing bids.  "Would
    have won" is therefore measured against the WINNING bid alone, and
    is an optimistic upper bound: a recommendation that ties or beats
    the winner is scored a win even though the real auction might have
    drawn a higher losing bid from someone else once our bid existed.
3.  NO HISTORICAL TEAM STATE.  Balances, rosters, drop sides and
    positional need at the time of each claim are not recoverable, so
    the NEW engine is run with a neutral team (full budget, no drop,
    neutral need, bubble status, balanced posture) against a full
    field of rivals each holding their full budget — i.e. against the
    most competitive field the league could have fielded.  That biases
    NEW's recommendation UP relative to what it would say in a real
    week-12 spot where half the league is broke.
4.  NO HISTORICAL WIRE.  The OLD formula is pool-relative — its only
    scale is ``candidate / best value on the wire`` — and no snapshot
    of the free-agent pool at claim time exists.  The best available
    proxy is the top canonical value among players actually claimed in
    the same scope (``--old-pool``, default ``season``).  OLD's numbers
    move materially with that choice, which is itself the finding: a
    formula with no absolute value scale cannot be backtested cleanly.
    The NEW engine's anchors are also computed off today's board.
5.  CHALLENGER (the Live Waiver Opportunity layer,
    docs/faab-live-opportunity-model.md) IS NOT VALIDATED BY THIS
    BACKTEST, and the CHALLENGER column exists to make that visible
    rather than to hide it.  ``src.trade.faab_opportunity`` reads
    TODAY's playerctx snapshot and TODAY's BDVM event ledger — neither
    has any historical retention, so calling it for a 2024 claim looks
    up 2026 role/event data, which is a FAR worse look-ahead violation
    than caveat 1's value join.  The report therefore stamps
    ``challengerRowsWithEvidence`` (almost always 0, and MUST be read
    before trusting any CHALLENGER number) rather than silently
    running the same look-ahead-biased comparison a second time.  The
    real validation path for this specific signal is the forward
    shadow-comparison log (``data/faab/shadow_comparisons_*.json``),
    not a retroactive replay.
"""

from __future__ import annotations

import argparse
import json
import statistics
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Sequence

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.trade import faab_engine as engine  # noqa: E402
from src.trade import faab_opportunity as opportunity  # noqa: E402
from src.trade.faab_history import history_path, load_bid_history  # noqa: E402

EXIT_OK = 0
EXIT_ERROR = 1
EXIT_NO_DATA = 2

# Value bands in canonical 0-9999 units.  Deliberately the same
# breakpoints the market calibration in ``config/trade/faab.json``
# quotes, so the two documents can be read against each other.
VALUE_BANDS: tuple[tuple[str, float, float], ...] = (
    ("<1200", 0.0, 1200.0),
    ("1200-1700", 1200.0, 1700.0),
    ("1700-2100", 1700.0, 2100.0),
    ("2100-2600", 2100.0, 2600.0),
    ("2600+", 2600.0, float("inf")),
)

LOW_VALUE_OVERBID_PCT = 0.05  # "> 5% of budget" per the brief


# ── The OLD formula ────────────────────────────────────────────────


def _old_formula(
    candidate_value: float,
    *,
    league_budget: int,
    top_value_in_pool: float | None,
) -> tuple[int, int]:
    """The PRE-ENGINE FAAB formula, reproduced verbatim.

    Returns ``(aggressive, reasonable)``.

    DUPLICATED ON PURPOSE.  This is the formula that used to live in
    ``src/trade/waiver.py::_compute_faab_bid``; that function is now a
    thin shim over ``src.trade.faab_engine`` and no longer computes
    this at all.  Importing the shim would backtest the NEW engine
    against ITSELF and silently report a perfect match.  Copying the
    arithmetic here freezes the baseline so this comparison stays
    valid however the shim evolves — and so it keeps working after the
    shim is eventually deleted.  Do not "de-duplicate" it.

    Note the defect the copy preserves: there is no absolute value
    scale anywhere in it.  ``share`` is relative to the best player on
    the wire, so the top available player always prices at 30% / 21%
    of the budget whether he grades 9999 or 900, and a BARREN wire
    makes every claim more expensive by lowering the denominator.
    """
    top_v = max(candidate_value, top_value_in_pool or 0)
    if top_v <= 0 or league_budget <= 0 or candidate_value <= 0:
        return (0, 0)
    share = candidate_value / top_v
    aggressive = max(1, round(league_budget * (0.05 + 0.25 * share)))
    reasonable = max(1, round(aggressive * 0.70))
    return (int(aggressive), int(reasonable))


# ── Inputs ─────────────────────────────────────────────────────────


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[1]


def _newest_export(explicit: str | None) -> Path | None:
    """Newest ``exports/latest/dynasty_data_*.json``.

    Filenames carry an ISO date, so a lexicographic max is the newest
    export; mtime is used only to break ties.
    """
    if explicit:
        p = Path(explicit)
        return p if p.exists() else None
    matches = sorted(
        (_repo_root() / "exports" / "latest").glob("dynasty_data_*.json"),
        key=lambda p: (p.name, p.stat().st_mtime),
    )
    return matches[-1] if matches else None


def _league_format(league_key: str) -> tuple[int, int, str]:
    """``(team_count, starters_per_team, display_name)`` from the registry.

    Falls back to the engine defaults when the registry cannot answer,
    because a backtest must still run on a league the registry has not
    been taught about yet.
    """
    try:
        from src.api import league_registry  # noqa: PLC0415

        cfg = league_registry.get_league_by_key(league_key)
    except Exception:  # noqa: BLE001 — registry is optional here
        cfg = None
    if cfg is None:
        return (12, 20, league_key)

    settings = getattr(cfg, "roster_settings", None) or {}
    team_count = int(settings.get("teamCount") or 12)
    starters = settings.get("starters") or {}
    total_starters = 0
    for slot_name, slots in starters.items():
        # K is excluded, matching the endpoint: kickers carry no
        # canonical value, so counting their slots would walk the
        # all-in anchor one rank further down the board per team
        # against no corresponding player supply.
        if str(slot_name).upper() == "K":
            continue
        try:
            total_starters += int(slots or 0)
        except (TypeError, ValueError):
            continue
    return (
        team_count,
        total_starters or 20,
        str(getattr(cfg, "display_name", "") or league_key),
    )


def _build_board(export_path: Path) -> list[dict[str, Any]]:
    from src.api.data_contract import build_api_data_contract  # noqa: PLC0415

    raw = json.loads(export_path.read_text(encoding="utf-8"))
    contract = build_api_data_contract(raw)
    arr = contract.get("playersArray")
    return [r for r in arr if isinstance(r, dict)] if isinstance(arr, list) else []


def _board_index(rows: Sequence[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    """Sleeper ``playerId`` → contract row, priced rows only."""
    out: dict[str, dict[str, Any]] = {}
    for row in rows:
        pid = row.get("playerId")
        value = row.get("rankDerivedValue")
        if not pid or not isinstance(value, (int, float)) or value <= 0:
            continue
        out[str(pid)] = row
    return out


def _anchor_board_values(rows: Sequence[dict[str, Any]]) -> list[float]:
    excluded = set(engine.FaabConfig().get("anchors", "excludedPositions", []) or [])
    return [
        float(r["rankDerivedValue"])
        for r in rows
        if isinstance(r.get("rankDerivedValue"), (int, float))
        and str(r.get("position") or "").upper() not in excluded
    ]


# ── One replayed claim ─────────────────────────────────────────────


@dataclass
class ClaimRow:
    player: str
    position: str
    value: float
    season: str
    week: int
    budget: int
    actual: int
    old_reasonable: int
    old_aggressive: int
    new_recommended: int
    new_objective: int
    challenger_recommended: int = 0
    challenger_had_evidence: bool = False

    @property
    def old_delta(self) -> int:
        return self.old_reasonable - self.actual

    @property
    def new_delta(self) -> int:
        return self.new_recommended - self.actual

    @property
    def challenger_delta(self) -> int:
        return self.challenger_recommended - self.actual

    @property
    def old_won(self) -> bool:
        return self.old_reasonable >= self.actual

    @property
    def new_won(self) -> bool:
        return self.new_recommended >= self.actual

    @property
    def challenger_won(self) -> bool:
        return self.challenger_recommended >= self.actual

    def to_dict(self) -> dict[str, Any]:
        return {
            "player": self.player,
            "position": self.position,
            "canonicalValue": round(self.value, 1),
            "season": self.season,
            "week": self.week,
            "seasonBudget": self.budget,
            "actualWinningBid": self.actual,
            "old": {
                "recommended": self.old_reasonable,
                "aggressive": self.old_aggressive,
                "deltaVsActual": self.old_delta,
                "wouldHaveWon": self.old_won,
            },
            "new": {
                "recommended": self.new_recommended,
                "objectiveCeiling": self.new_objective,
                "deltaVsActual": self.new_delta,
                "wouldHaveWon": self.new_won,
            },
            "challenger": {
                "recommended": self.challenger_recommended,
                "deltaVsActual": self.challenger_delta,
                "wouldHaveWon": self.challenger_won,
                # Almost always False on a historical claim — see caveat 5.
                # A True here means the opportunity layer found role/event
                # evidence keyed to THIS player TODAY, which for an old
                # claim is itself a look-ahead artifact, not a real signal.
                "hadEvidence": self.challenger_had_evidence,
            },
            "valueBand": _band_label(self.value),
        }


def _band_label(value: float) -> str:
    for label, lo, hi in VALUE_BANDS:
        if lo <= value < hi:
            return label
    return VALUE_BANDS[-1][0]


def _recommend_new(
    *,
    value: float,
    week: int,
    budget: int,
    team_count: int,
    starters_per_team: int,
    anchors: engine.Anchors,
    cfg: engine.FaabConfig,
    cache: dict[tuple[int, int, int, int], tuple[int, int]],
) -> tuple[int, int]:
    """``(recommendedBid, objectiveCeilingDollars)`` from the NEW engine.

    Team state at claim time is unrecoverable, so the team is neutral
    and every rival holds a full budget — see caveat 3 in the module
    docstring.
    """
    key = (int(round(value)), int(week), int(budget), int(team_count))
    hit = cache.get(key)
    if hit is not None:
        return hit

    league = engine.LeagueContext(
        original_budget=budget,
        team_count=team_count,
        starters_per_team=starters_per_team,
        current_week=week,
        in_season=True,
    )
    team = engine.TeamContext(
        faab_remaining=budget,
        open_roster_spots=1,  # no drop side is recoverable from history
        need_level="neutral",
        competitive_status="bubble",
        risk_posture="balanced",
    )
    rivals = [
        engine.RivalTeam(
            owner_id=f"rival-{i}",
            faab_remaining=budget,
            need_level="neutral",
            aggression=1.0,
            low_sample=True,
        )
        for i in range(max(0, team_count - 1))
    ]

    result = engine.recommend(
        engine.PlayerInput(value=float(value)),
        league,
        team,
        anchors=anchors,
        rivals=rivals,
        config=cfg,
    )
    out = (
        int(result["bids"]["recommended"]),
        int(result["objective"]["dollars"]),
    )
    cache[key] = out
    return out


def _recommend_challenger(
    *,
    value: float,
    player_id: str,
    player_name: str,
    week: int,
    budget: int,
    team_count: int,
    starters_per_team: int,
    anchors: engine.Anchors,
    cfg: engine.FaabConfig,
    cache: dict[tuple[str, int, int, int, int], tuple[int, bool]],
) -> tuple[int, bool]:
    """``(recommendedBid, hadEvidence)`` running TODAY's opportunity
    layer against a HISTORICAL claim.

    Read caveat 5 before trusting this number for anything but "is the
    plumbing correct" — ``player_id``/``player_name`` are looked up
    against TODAY's playerctx/event evidence, not evidence from the
    claim's actual date, because no historical snapshot of either
    exists.  ``hadEvidence`` is what lets the report show that
    honestly rather than asserting it in prose alone.
    """
    key = (player_id, int(round(value)), int(week), int(budget), int(team_count))
    hit = cache.get(key)
    if hit is not None:
        return hit

    opp = opportunity.opportunity_value(
        value,
        sleeper_id=player_id or None,
        player_name=player_name,
        config=cfg,
    )

    league = engine.LeagueContext(
        original_budget=budget,
        team_count=team_count,
        starters_per_team=starters_per_team,
        current_week=week,
        in_season=True,
    )
    team = engine.TeamContext(
        faab_remaining=budget,
        open_roster_spots=1,
        need_level="neutral",
        competitive_status="bubble",
        risk_posture="balanced",
    )
    rivals = [
        engine.RivalTeam(
            owner_id=f"rival-{i}",
            faab_remaining=budget,
            need_level="neutral",
            aggression=1.0,
            low_sample=True,
        )
        for i in range(max(0, team_count - 1))
    ]
    result = engine.recommend(
        engine.PlayerInput(value=float(opp["value"])),
        league,
        team,
        anchors=anchors,
        rivals=rivals,
        config=cfg,
    )
    out = (int(result["bids"]["recommended"]), bool(opp["hasEvidence"]))
    cache[key] = out
    return out


def _replay(
    payload: dict[str, Any],
    board: dict[str, dict[str, Any]],
    *,
    anchors: engine.Anchors,
    cfg: engine.FaabConfig,
    team_count: int,
    starters_per_team: int,
    old_pool: str,
) -> tuple[list[ClaimRow], dict[str, Any]]:
    """Join every persisted claim to a canonical value and price it."""
    seasons = [s for s in (payload.get("seasons") or []) if isinstance(s, dict)]

    # Pass 1: resolve values so the OLD formula's pool denominator can
    # be built before any bid is computed.
    resolved: list[dict[str, Any]] = []
    total = 0
    unmatched = 0
    for season in seasons:
        season_label = str(season.get("season") or "?")
        budget = int(season.get("budget") or 0) or 100
        season_teams = int(season.get("teamCount") or 0) or team_count
        for add in season.get("adds") or []:
            if not isinstance(add, dict):
                continue
            total += 1
            row = board.get(str(add.get("playerId")))
            if row is None:
                unmatched += 1
                continue
            try:
                bid = int(add.get("bid"))
                week = int(add.get("week") or 0)
            except (TypeError, ValueError):
                unmatched += 1
                continue
            resolved.append(
                {
                    "season": season_label,
                    "budget": budget,
                    "teamCount": season_teams,
                    "week": max(1, week),
                    "bid": bid,
                    "value": float(row["rankDerivedValue"]),
                    "name": str(row.get("displayName") or row.get("canonicalName") or "?"),
                    "position": str(row.get("position") or "").upper(),
                    "playerId": str(add.get("playerId") or ""),
                }
            )

    # OLD's pool denominator.  No historical wire snapshot exists, so
    # the proxy is the best player demonstrably available in the scope.
    pool_top: dict[Any, float] = {}
    if old_pool == "all":
        top = max((r["value"] for r in resolved), default=0.0)
        pool_top = {None: top}
    else:
        for r in resolved:
            key = r["season"] if old_pool == "season" else (r["season"], r["week"])
            pool_top[key] = max(pool_top.get(key, 0.0), r["value"])

    cache: dict[tuple[int, int, int, int], tuple[int, int]] = {}
    challenger_cache: dict[tuple[str, int, int, int, int], tuple[int, bool]] = {}
    rows: list[ClaimRow] = []
    for r in resolved:
        if old_pool == "all":
            key: Any = None
        elif old_pool == "season":
            key = r["season"]
        else:
            key = (r["season"], r["week"])
        old_agg, old_reas = _old_formula(
            r["value"],
            league_budget=r["budget"],
            top_value_in_pool=pool_top.get(key),
        )
        new_bid, new_obj = _recommend_new(
            value=r["value"],
            week=r["week"],
            budget=r["budget"],
            team_count=r["teamCount"],
            starters_per_team=starters_per_team,
            anchors=anchors,
            cfg=cfg,
            cache=cache,
        )
        challenger_bid, challenger_evidence = _recommend_challenger(
            value=r["value"],
            player_id=r["playerId"],
            player_name=r["name"],
            week=r["week"],
            budget=r["budget"],
            team_count=r["teamCount"],
            starters_per_team=starters_per_team,
            anchors=anchors,
            cfg=cfg,
            cache=challenger_cache,
        )
        rows.append(
            ClaimRow(
                player=r["name"],
                position=r["position"],
                value=r["value"],
                season=r["season"],
                week=r["week"],
                budget=r["budget"],
                actual=r["bid"],
                old_reasonable=old_reas,
                old_aggressive=old_agg,
                new_recommended=new_bid,
                new_objective=new_obj,
                challenger_recommended=challenger_bid,
                challenger_had_evidence=challenger_evidence,
            )
        )

    rows.sort(key=lambda c: (-c.value, c.season, c.week))
    join = {
        "claimsInHistory": total,
        "claimsPriced": len(rows),
        "claimsUnmatched": unmatched,
        "coveragePct": round(100.0 * len(rows) / total, 1) if total else 0.0,
    }
    return rows, join


# ── Aggregation ────────────────────────────────────────────────────


def _mean(values: Iterable[float]) -> float:
    vals = list(values)
    return statistics.fmean(vals) if vals else 0.0


def _model_recommendation(c: ClaimRow, model: str) -> int:
    if model == "old":
        return c.old_reasonable
    if model == "challenger":
        return c.challenger_recommended
    return c.new_recommended


def _model_won(c: ClaimRow, model: str) -> bool:
    if model == "old":
        return c.old_won
    if model == "challenger":
        return c.challenger_won
    return c.new_won


def _model_delta(c: ClaimRow, model: str) -> int:
    if model == "old":
        return c.old_delta
    if model == "challenger":
        return c.challenger_delta
    return c.new_delta


def _model_stats(rows: Sequence[ClaimRow], *, model: str) -> dict[str, Any]:
    recs = [_model_recommendation(c, model) for c in rows]
    wins = [c for c in rows if _model_won(c, model)]
    deltas = [_model_delta(c, model) for c in rows]

    overpay = [_model_delta(c, model) for c in wins]
    spend_on_wins = sum(_model_recommendation(c, model) for c in wins)
    budget_units = sum(_model_recommendation(c, model) / max(1, c.budget) for c in rows)
    win_budget_units = sum(_model_recommendation(c, model) / max(1, c.budget) for c in wins)
    return {
        "claims": len(rows),
        "wouldHaveWon": len(wins),
        "wouldHaveLost": len(rows) - len(wins),
        "winRatePct": round(100.0 * len(wins) / len(rows), 1) if rows else 0.0,
        "avgOverpaymentWhenWinning": round(_mean(overpay), 2),
        "medianOverpaymentWhenWinning": (round(statistics.median(overpay), 2) if overpay else 0.0),
        "avgRecommendation": round(_mean(recs), 2),
        "avgDeltaVsActual": round(_mean(deltas), 2),
        "totalRecommendedAllClaims": int(sum(recs)),
        "totalSpendOnWonClaims": int(spend_on_wins),
        "totalRecommendedBudgetUnits": round(budget_units, 2),
        "totalSpendOnWonBudgetUnits": round(win_budget_units, 2),
    }


def _actual_stats(rows: Sequence[ClaimRow]) -> dict[str, Any]:
    actuals = [c.actual for c in rows]
    zero = sum(1 for a in actuals if a == 0)
    return {
        "claims": len(rows),
        "totalActuallySpent": int(sum(actuals)),
        "totalActuallySpentBudgetUnits": round(sum(c.actual / max(1, c.budget) for c in rows), 2),
        "avgWinningBid": round(_mean(actuals), 2),
        "medianWinningBid": round(statistics.median(actuals), 2) if actuals else 0.0,
        "maxWinningBid": max(actuals) if actuals else 0,
        "zeroBidSharePct": round(100.0 * zero / len(rows), 1) if rows else 0.0,
    }


def _breakdown(
    rows: Sequence[ClaimRow],
    keyfn,
    order: Sequence[Any] | None = None,
) -> list[dict[str, Any]]:
    buckets: dict[Any, list[ClaimRow]] = {}
    for c in rows:
        buckets.setdefault(keyfn(c), []).append(c)
    keys = list(order) if order is not None else sorted(buckets)
    out: list[dict[str, Any]] = []
    for key in keys:
        group = buckets.get(key)
        if not group:
            continue
        out.append(
            {
                "key": str(key),
                "n": len(group),
                "oldWinRatePct": round(100.0 * sum(1 for c in group if c.old_won) / len(group), 1),
                "newWinRatePct": round(100.0 * sum(1 for c in group if c.new_won) / len(group), 1),
                "avgActualBidPctOfBudget": round(
                    _mean(100.0 * c.actual / max(1, c.budget) for c in group), 2
                ),
                "avgOldPctOfBudget": round(
                    _mean(100.0 * c.old_reasonable / max(1, c.budget) for c in group), 2
                ),
                "avgNewPctOfBudget": round(
                    _mean(100.0 * c.new_recommended / max(1, c.budget) for c in group), 2
                ),
                "avgCanonicalValue": round(_mean(c.value for c in group), 0),
            }
        )
    return out


def _edge_cases(rows: Sequence[ClaimRow], anchors: engine.Anchors) -> dict[str, Any]:
    """The two failure modes the brief names, for BOTH models.

    ``impactfulMissed``  a player above the all-in anchor whose claim
                         the model would have lost — the expensive
                         error, because these are the claims worth
                         winning.
    ``lowValueOverbid``  a player below the replacement anchor priced
                         above 5% of the budget — the wasteful error,
                         and precisely what the OLD formula's missing
                         value scale produced.
    """
    above = [c for c in rows if c.value > anchors.v_allin]
    below = [c for c in rows if c.value < anchors.v_repl]

    def overbid(model: str, group: Sequence[ClaimRow]) -> list[ClaimRow]:
        return [
            c
            for c in group
            if (c.old_reasonable if model == "old" else c.new_recommended)
            > LOW_VALUE_OVERBID_PCT * c.budget
        ]

    old_missed = [c for c in above if not c.old_won]
    new_missed = [c for c in above if not c.new_won]
    old_over = overbid("old", below)
    new_over = overbid("new", below)

    return {
        "allInAnchor": round(anchors.v_allin, 1),
        "replacementAnchor": round(anchors.v_repl, 1),
        "claimsAboveAllIn": len(above),
        "claimsBelowReplacement": len(below),
        "impactfulMissed": {"old": len(old_missed), "new": len(new_missed)},
        "lowValueOverbid": {"old": len(old_over), "new": len(new_over)},
        "impactfulMissedExamplesNew": [
            {
                "player": c.player,
                "value": round(c.value, 0),
                "season": c.season,
                "week": c.week,
                "actual": c.actual,
                "new": c.new_recommended,
            }
            for c in sorted(new_missed, key=lambda c: -(c.actual / max(1, c.budget)))[:8]
        ],
        "lowValueOverbidExamplesOld": [
            {
                "player": c.player,
                "value": round(c.value, 0),
                "season": c.season,
                "week": c.week,
                "actual": c.actual,
                "old": c.old_reasonable,
                "budget": c.budget,
            }
            for c in sorted(old_over, key=lambda c: -(c.old_reasonable / max(1, c.budget)))[:8]
        ],
    }


CAVEATS: tuple[str, ...] = (
    "LOOK-AHEAD BIAS: every claim is joined to TODAY's canonical value. A player "
    "added for $0 in 2024 who later broke out now grades high, so the high-value "
    "bands are systematically stuffed with players who were cheap BECAUSE nobody "
    "knew yet. Those bands read artificially cheap and both models read as "
    "'overbidding' there. Check the n column before trusting any band.",
    "WINNING BIDS ONLY: Sleeper never exposes losing bids. 'Would have won' is "
    "measured against the winning bid alone and is therefore an OPTIMISTIC upper "
    "bound for both models.",
    "NO HISTORICAL TEAM STATE: balances, rosters, drop sides and positional need "
    "at claim time are unrecoverable. The NEW engine runs neutral-team against a "
    "full field of rivals each holding a full budget, which biases it UP versus "
    "what it would say in a real late-season spot.",
    "NO HISTORICAL WIRE: the OLD formula is pool-relative and no free-agent-pool "
    "snapshot exists. Its denominator is proxied by the top canonical value among "
    "players actually claimed in the same scope (--old-pool). OLD's numbers move "
    "with that choice - which is itself the finding.",
    "OLD HEADLINE NUMBER: OLD is scored on its 'reasonable' bid (aggressive x 0.70), "
    "the figure the pre-engine UI presented as the recommendation. Its 'aggressive' "
    "figure is carried in the per-claim rows and in --json.",
    "CHALLENGER IS NOT VALIDATED BY THIS BACKTEST: the Live Waiver Opportunity layer "
    "reads TODAY's playerctx/event evidence for every historical claim, since neither "
    "has any retained history. Check 'challengerRowsWithEvidence' below before reading "
    "anything into a CHALLENGER number - a nonzero count on an old claim is itself a "
    "look-ahead artifact, not a real signal. This column exists to prove the mechanics "
    "are wired correctly, not to grade the opportunity layer's accuracy.",
)


# ── Rendering ──────────────────────────────────────────────────────


def _rule(char: str = "-", width: int = 96) -> str:
    return char * width


def _wrap(text: str, width: int, indent: str = "    ") -> list[str]:
    words = text.split()
    lines: list[str] = []
    current = ""
    for word in words:
        candidate = f"{current} {word}".strip()
        if len(candidate) > width and current:
            lines.append(indent + current)
            current = word
        else:
            current = candidate
    if current:
        lines.append(indent + current)
    return lines


def _render(report: dict[str, Any], *, limit: int) -> str:
    meta = report["meta"]
    out: list[str] = []
    add = out.append

    add(_rule("="))
    add(f"FAAB BACKTEST — OLD formula vs NEW engine — league {meta['leagueKey']}")
    add(_rule("="))
    add(
        f"  league          {meta['leagueDisplayName']} "
        f"({meta['teamCount']} teams x {meta['startersPerTeam']} starters)"
    )
    add(f"  board           {meta['exportPath']}")
    add(f"  history         {meta['historyPath']}")
    add(f"  seasons         {', '.join(meta['seasons'])}")
    add(
        f"  anchors         all-in {meta['anchors']['vAllIn']} | "
        f"replacement {meta['anchors']['vReplacement']} | source {meta['anchors']['source']}"
    )
    add(
        f"  join            {report['join']['claimsPriced']} of "
        f"{report['join']['claimsInHistory']} claims priced "
        f"({report['join']['coveragePct']}%) — "
        f"{report['join']['claimsUnmatched']} unmatched on the board"
    )
    add(f"  old-pool proxy  {meta['oldPool']}")
    add("")

    add(_rule("!"))
    add("!! READ THE CAVEATS — THESE RESULTS ARE BIASED BY CONSTRUCTION")
    add(_rule("!"))
    for i, caveat in enumerate(report["caveats"], 1):
        head, _, body = caveat.partition(":")
        # Only promote the prefix to a heading when it reads like one —
        # otherwise the whole sentence would be printed twice.
        if body and len(head) <= 40:
            add(f"  {i}. {head.strip()}:")
            out.extend(_wrap(body.strip(), 86, indent="     "))
        else:
            out.extend(_wrap(f"{i}. {caveat}", 86, indent="  "))
    add("")

    rows = report["claims"]
    shown = rows if limit <= 0 else rows[:limit]
    add(_rule("="))
    add(f"PER-CLAIM DETAIL ({len(shown)} of {len(rows)} claims, highest canonical value first)")
    add(_rule("="))
    header = (
        f"{'Player':<24}{'Pos':<5}{'Value':>7}{'Seas':>6}{'Wk':>4}"
        f"{'Bud':>6}{'Actual':>8}{'OLD':>7}{'dOLD':>7}{'NEW':>7}{'dNEW':>7}{'CHAL':>7}"
    )
    add(header)
    add(_rule("-", len(header)))
    for row in shown:
        chal_mark = "" if row["challenger"]["hadEvidence"] else "~"
        add(
            f"{row['player'][:23]:<24}{row['position'][:4]:<5}"
            f"{row['canonicalValue']:>7.0f}{row['season']:>6}{row['week']:>4}"
            f"{row['seasonBudget']:>6}{row['actualWinningBid']:>8}"
            f"{row['old']['recommended']:>7}{row['old']['deltaVsActual']:>+7}"
            f"{row['new']['recommended']:>7}{row['new']['deltaVsActual']:>+7}"
            f"{row['challenger']['recommended']:>6}{chal_mark}"
        )
    if limit > 0 and len(rows) > limit:
        add(f"... {len(rows) - limit} more (use --limit 0 for all)")
    add("  CHAL = challenger (Live Waiver Opportunity layer); '~' = no historical")
    add("         evidence found (expected for nearly every row — see caveat 5)")
    add("")

    actual = report["actual"]
    old = report["old"]
    new = report["new"]
    challenger = report["challenger"]
    add(_rule("="))
    add("AGGREGATE — WOULD-HAVE-WON (recommendation >= actual winning bid)")
    add(_rule("="))
    add(f"{'':<34}{'OLD':>14}{'NEW':>14}{'CHALLENGER':>14}")
    add(
        f"{'claims scored':<34}{old['claims']:>14}{new['claims']:>14}" f"{challenger['claims']:>14}"
    )
    add(
        f"{'would have WON':<34}{old['wouldHaveWon']:>14}{new['wouldHaveWon']:>14}"
        f"{challenger['wouldHaveWon']:>14}"
    )
    add(
        f"{'would have LOST':<34}{old['wouldHaveLost']:>14}{new['wouldHaveLost']:>14}"
        f"{challenger['wouldHaveLost']:>14}"
    )
    add(
        f"{'win rate':<34}{old['winRatePct']:>13.1f}%{new['winRatePct']:>13.1f}%"
        f"{challenger['winRatePct']:>13.1f}%"
    )
    add(
        f"{'avg overpayment when winning':<34}"
        f"{old['avgOverpaymentWhenWinning']:>14.2f}{new['avgOverpaymentWhenWinning']:>14.2f}"
        f"{challenger['avgOverpaymentWhenWinning']:>14.2f}"
    )
    add(
        f"{'median overpay when winning':<34}"
        f"{old['medianOverpaymentWhenWinning']:>14.2f}"
        f"{new['medianOverpaymentWhenWinning']:>14.2f}"
        f"{challenger['medianOverpaymentWhenWinning']:>14.2f}"
    )
    add(
        f"{'avg recommendation ($)':<34}"
        f"{old['avgRecommendation']:>14.2f}{new['avgRecommendation']:>14.2f}"
        f"{challenger['avgRecommendation']:>14.2f}"
    )
    add(
        f"{'avg delta vs actual ($)':<34}"
        f"{old['avgDeltaVsActual']:>+14.2f}{new['avgDeltaVsActual']:>+14.2f}"
        f"{challenger['avgDeltaVsActual']:>+14.2f}"
    )
    add("")
    add(
        f"  CHALLENGER rows with real historical evidence: "
        f"{report['challengerRowsWithEvidence']} of {len(rows)} — "
        "read caveat 5 before trusting anything above this line for CHALLENGER."
    )
    add("")

    add(_rule("="))
    add("AGGREGATE — TOTAL FAAB COMMITTED")
    add(_rule("="))
    add("  Raw dollars are NOT comparable across seasons (budget was $1,000 in 2024,")
    add("  $200 in 2025, $100 in 2026), so budget-units are the honest total: one unit")
    add("  = one full season budget.")
    add("")
    add(f"{'':<40}{'dollars':>14}{'budget-units':>16}")
    add(
        f"{'ACTUALLY spent (winning bids)':<40}"
        f"{actual['totalActuallySpent']:>14}{actual['totalActuallySpentBudgetUnits']:>16.2f}"
    )
    add(
        f"{'OLD — sum of recommendations':<40}"
        f"{old['totalRecommendedAllClaims']:>14}{old['totalRecommendedBudgetUnits']:>16.2f}"
    )
    add(
        f"{'OLD — spend on claims it would win':<40}"
        f"{old['totalSpendOnWonClaims']:>14}{old['totalSpendOnWonBudgetUnits']:>16.2f}"
    )
    add(
        f"{'NEW — sum of recommendations':<40}"
        f"{new['totalRecommendedAllClaims']:>14}{new['totalRecommendedBudgetUnits']:>16.2f}"
    )
    add(
        f"{'NEW — spend on claims it would win':<40}"
        f"{new['totalSpendOnWonClaims']:>14}{new['totalSpendOnWonBudgetUnits']:>16.2f}"
    )
    add("")
    add(
        f"  actual market: avg winning bid ${actual['avgWinningBid']:.2f}, "
        f"median ${actual['medianWinningBid']:.2f}, max ${actual['maxWinningBid']}, "
        f"{actual['zeroBidSharePct']}% of claims cost $0"
    )
    add("")

    for title, key, note in (
        (
            "BY VALUE BAND",
            "byValueBand",
            "n is the sample size — LOOK-AHEAD BIAS makes the high bands unreliable",
        ),
        ("BY WEEK", "byWeek", "week of the NFL season the claim was made"),
        ("BY SEASON", "bySeason", "each season ran a different budget"),
    ):
        add(_rule("="))
        add(f"ACCURACY {title}  ({note})")
        add(_rule("="))
        head = (
            f"{'bucket':<14}{'n':>6}{'OLD win%':>10}{'NEW win%':>10}"
            f"{'actual %bud':>13}{'OLD %bud':>11}{'NEW %bud':>11}{'avg value':>11}"
        )
        add(head)
        add(_rule("-", len(head)))
        for bucket in report[key]:
            add(
                f"{bucket['key']:<14}{bucket['n']:>6}"
                f"{bucket['oldWinRatePct']:>9.1f}%{bucket['newWinRatePct']:>9.1f}%"
                f"{bucket['avgActualBidPctOfBudget']:>13.2f}"
                f"{bucket['avgOldPctOfBudget']:>11.2f}{bucket['avgNewPctOfBudget']:>11.2f}"
                f"{bucket['avgCanonicalValue']:>11.0f}"
            )
        add("")

    edge = report["edgeCases"]
    add(_rule("="))
    add("EDGE CASES")
    add(_rule("="))
    add(f"  anchors: all-in {edge['allInAnchor']} · replacement {edge['replacementAnchor']}")
    add(f"  claims above the all-in anchor:      {edge['claimsAboveAllIn']}")
    add(f"  claims below the replacement anchor: {edge['claimsBelowReplacement']}")
    add("")
    add("  IMPACTFUL PLAYERS MISSED (value > all-in anchor, bid below the winning bid)")
    add(
        f"      OLD {edge['impactfulMissed']['old']:>4}   NEW {edge['impactfulMissed']['new']:>4}"
        f"   of {edge['claimsAboveAllIn']} such claims"
    )
    for ex in edge["impactfulMissedExamplesNew"]:
        add(
            f"      NEW missed: {ex['player'][:24]:<25} value {ex['value']:>5.0f}  "
            f"{ex['season']} wk{ex['week']:<3} actual ${ex['actual']:<5} vs NEW ${ex['new']}"
        )
    add("")
    add("  LOW-VALUE PLAYERS OVERBID (value < replacement anchor, bid > 5% of budget)")
    add(
        f"      OLD {edge['lowValueOverbid']['old']:>4}   NEW {edge['lowValueOverbid']['new']:>4}"
        f"   of {edge['claimsBelowReplacement']} such claims"
    )
    for ex in edge["lowValueOverbidExamplesOld"]:
        add(
            f"      OLD overbid: {ex['player'][:24]:<25} value {ex['value']:>5.0f}  "
            f"{ex['season']} wk{ex['week']:<3} actual ${ex['actual']:<5} vs OLD "
            f"${ex['old']} of ${ex['budget']}"
        )
    add("")
    add(_rule("="))
    add("Reminder: bands are look-ahead biased and 'would have won' is measured only")
    add("against WINNING bids (Sleeper publishes no losing bids), so every win rate")
    add("printed above is an optimistic upper bound. Read the n column.")
    add(_rule("="))
    return "\n".join(out)


# ── CLI ────────────────────────────────────────────────────────────


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Backtest the OLD FAAB formula against the NEW engine on real claims.",
    )
    parser.add_argument(
        "--league", default="dynasty_main", help="league key (default dynasty_main)"
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=25,
        help="rows in the per-claim table (0 = all; ignored for --json)",
    )
    parser.add_argument("--json", action="store_true", help="machine-readable output")
    parser.add_argument(
        "--export", help="explicit raw export path (default: newest in exports/latest)"
    )
    parser.add_argument(
        "--old-pool",
        choices=("season", "week", "all"),
        default="season",
        help="scope of the OLD formula's 'best on the wire' proxy (default season)",
    )
    args = parser.parse_args(argv)

    league_key = str(args.league)

    payload = load_bid_history(league_key)
    hist_path = history_path(league_key)
    if not payload:
        print(
            f"no bid history for league '{league_key}' at {hist_path}\n"
            f"  run: python scripts/fetch_faab_history.py --league {league_key}",
            file=sys.stderr,
        )
        return EXIT_NO_DATA

    export_path = _newest_export(args.export)
    if export_path is None:
        where = args.export or "exports/latest/dynasty_data_*.json"
        print(
            f"no raw export found (looked for {where})\n"
            "  a scrape export is required to price historical claims",
            file=sys.stderr,
        )
        return EXIT_NO_DATA

    try:
        board_rows = _build_board(export_path)
    except Exception as exc:  # noqa: BLE001 — report, don't traceback
        print(
            f"error: could not build the canonical contract from {export_path}: {exc}",
            file=sys.stderr,
        )
        return EXIT_ERROR

    if not board_rows:
        print(f"error: {export_path} produced an empty board", file=sys.stderr)
        return EXIT_NO_DATA

    try:
        cfg = engine.FaabConfig()
        team_count, starters_per_team, display_name = _league_format(league_key)
        anchors = engine.resolve_anchors(
            _anchor_board_values(board_rows),
            engine.LeagueContext(
                team_count=team_count,
                starters_per_team=starters_per_team,
            ),
            available_values=None,  # no historical wire snapshot exists
            config=cfg,
        )
        rows, join = _replay(
            payload,
            _board_index(board_rows),
            anchors=anchors,
            cfg=cfg,
            team_count=team_count,
            starters_per_team=starters_per_team,
            old_pool=str(args.old_pool),
        )
    except Exception as exc:  # noqa: BLE001
        print(f"error: backtest failed: {exc}", file=sys.stderr)
        return EXIT_ERROR

    if not rows:
        print(
            f"no historical claims could be joined to a canonical value "
            f"({join['claimsInHistory']} claims in history, none matched the board)",
            file=sys.stderr,
        )
        return EXIT_NO_DATA

    report: dict[str, Any] = {
        "meta": {
            "leagueKey": league_key,
            "leagueDisplayName": display_name,
            "teamCount": team_count,
            "startersPerTeam": starters_per_team,
            "exportPath": str(export_path),
            "historyPath": str(hist_path),
            "seasons": sorted({c.season for c in rows}, reverse=True),
            "anchors": anchors.to_dict(),
            "oldPool": str(args.old_pool),
            "oldModel": (
                "waiver._compute_faab_bid pre-engine formula "
                "(scored on reasonable = aggressive x 0.70)"
            ),
            "newModel": "src.trade.faab_engine.recommend -> bids.recommended",
            "challengerModel": (
                "src.trade.faab_opportunity.opportunity_value (TODAY's playerctx/event "
                "evidence) -> src.trade.faab_engine.recommend -> bids.recommended; "
                "NOT a validated backtest of the opportunity layer, see caveat 5"
            ),
        },
        "caveats": list(CAVEATS),
        "join": join,
        "actual": _actual_stats(rows),
        "old": _model_stats(rows, model="old"),
        "new": _model_stats(rows, model="new"),
        "challenger": _model_stats(rows, model="challenger"),
        "challengerRowsWithEvidence": sum(1 for c in rows if c.challenger_had_evidence),
        "byValueBand": _breakdown(
            rows, lambda c: _band_label(c.value), [b[0] for b in VALUE_BANDS]
        ),
        "byWeek": _breakdown(rows, lambda c: c.week, sorted({c.week for c in rows})),
        "bySeason": _breakdown(
            rows, lambda c: c.season, sorted({c.season for c in rows}, reverse=True)
        ),
        "edgeCases": _edge_cases(rows, anchors),
        "claims": [c.to_dict() for c in rows],
    }

    if args.json:
        print(json.dumps(report, indent=2))
    else:
        print(_render(report, limit=int(args.limit)))
    return EXIT_OK


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        sys.exit(EXIT_ERROR)
