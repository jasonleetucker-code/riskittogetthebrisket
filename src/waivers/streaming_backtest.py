"""IDP weekly-streaming backtest — research / shadow harness (W3).

Answers one measured question: *does churning individual defenders week to
week gain realized best-ball lineup points over holding, and how does that
compare with simple, explicit streaming rules?*  The preregistration is
``docs/waivers/IDP_STREAMING_BACKTEST_PREREGISTRATION_2026-10-29.md``; the
results are ``docs/waivers/IDP_STREAMING_BACKTEST_RESULTS_2026-10-29.md``.

ISOLATED.  Nothing live may import this module (pinned by
``tests/waivers/test_streaming_backtest.py``).  It changes no value, rank,
bid or route; it reads public Sleeper data and the local temporal ledger and
writes research artifacts.

Nothing here is a second owner
==============================
================================  ============================================
question                          owner consumed
================================  ============================================
league chain / users / rosters    ``src.public_league.sleeper_client``
/ matchups / transactions
weekly stat lines                 ``src.league_comparison.sleeper_stats.fetch_week_stats_response``
league-card scoring               ``src.league_intel.scorer.score_stat_line``
weekly projections + rescoring    ``src.ros.sleeper_weekly_projections``
optimal best-ball lineup          ``src.ros.lineup.solve_optimal_assignment``
                                  (``objective="realized_points"``)
slot vocabulary / eligibility     ``src.ros.lineup`` (``starter_slots_from_roster_positions``,
                                  ``slot_eligible_positions``)
host player vs team entry         ``src.nfl_data.realized_points.is_host_player_entry``
kickoff times                     ``src.nfl_data.ingest.fetch_schedules``
point-in-time dynasty value       ``src.history.asof.value_known_before``
================================  ============================================

Invariants
==========
* **No hindsight.**  A week-``w`` decision is made from a
  :class:`DecisionContext` built by :func:`build_decision_context`, the ONE
  place timed inputs are filtered: realized points of weeks ``< w`` only,
  projections for week ``w`` (labelled not point-in-time verified), dynasty
  values known before the week-``w`` cutoff.  Week-``w`` realized points are
  read only by the scorer of a decision.
* **Missing is never zero.**  An unknown metric is neither added nor dropped.
  A missing weekly stat payload is an error, never a week of zeros.  A player
  absent from a COMPLETE payload scored 0.0 — the host's own award, verified
  against ``players_points`` by :func:`rescoring_agreement`.
* **Each season is scored with its own card and slots.**
"""

from __future__ import annotations

import gzip
import json
import math
import random
import statistics
import urllib.request
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Protocol

from src.league_intel.scorer import score_stat_line
from src.ros.lineup import (
    OBJECTIVE_REALIZED_POINTS,
    RosterPlayer,
    slot_eligible_positions,
    solve_optimal_assignment,
    starter_slots_from_roster_positions,
)

__all__ = [
    "DecisionContext",
    "Swap",
    "StreamingPolicy",
    "SeasonData",
    "Transaction",
    "MetricSwapPolicy",
    "DynastyReleasePolicy",
    "build_decision_context",
    "classify_roster_changes",
    "reconstruct_rosters",
    "optimal_lineup",
    "scenario_lineup",
    "simulate_policy",
    "simulate_hold",
    "simulate_actual",
    "bootstrap_ci",
    "verdict",
]

IDP_GROUPS: tuple[str, ...] = ("DL", "LB", "DB")
STREAMING_TX_TYPES = frozenset({"waiver", "free_agent"})
NON_STREAMING_TX_TYPES = frozenset({"trade", "commissioner"})
BOOTSTRAP_SEED = 20261029
BOOTSTRAP_RESAMPLES = 10_000
MIN_WEEKS_MANAGER = 6
MIN_TEAM_SEASONS = 6
MIN_PLAYER_WEEKS_ACCURACY = 100
ROLLING_WINDOW = 3
ROLLING_MIN_GAMES = 2

REPO = Path(__file__).resolve().parents[2]
RESEARCH_DIR = REPO / "data" / "research" / "idp_streaming"
EVIDENCE_DIR = REPO / "docs" / "waivers" / "evidence" / "idp_streaming"


# ── Data model ────────────────────────────────────────────────────────


@dataclass(frozen=True)
class Transaction:
    tx_id: str
    tx_type: str
    status: str
    leg: int
    created_ms: int
    status_updated_ms: int
    roster_ids: tuple[int, ...]
    adds: Mapping[str, int]
    drops: Mapping[str, int]
    waiver_bid: float | None

    @property
    def at(self) -> datetime:
        ms = self.status_updated_ms or self.created_ms
        return datetime.fromtimestamp(ms / 1000.0, tz=timezone.utc)


def transaction_from_sleeper(raw: Mapping[str, Any]) -> Transaction:
    settings = raw.get("settings") or {}
    bid = settings.get("waiver_bid") if isinstance(settings, Mapping) else None
    return Transaction(
        tx_id=str(raw.get("transaction_id") or ""),
        tx_type=str(raw.get("type") or ""),
        status=str(raw.get("status") or ""),
        leg=int(raw.get("leg") or 0),
        created_ms=int(raw.get("created") or 0),
        status_updated_ms=int(raw.get("status_updated") or raw.get("created") or 0),
        roster_ids=tuple(int(r) for r in (raw.get("roster_ids") or ())),
        adds={str(k): int(v) for k, v in (raw.get("adds") or {}).items()},
        drops={str(k): int(v) for k, v in (raw.get("drops") or {}).items()},
        waiver_bid=None if bid is None else float(bid),
    )


@dataclass(frozen=True)
class PlayerInfo:
    position: str
    fantasy_positions: tuple[str, ...]

    @property
    def group(self) -> str | None:
        """Swap group DL / LB / DB.  The dump's ``position`` can be a
        sub-position (DE, DT, CB, S); Sleeper's own ``fantasy_positions``
        then names the IDP family."""
        if self.position in IDP_GROUPS:
            return self.position
        for fp in self.fantasy_positions:
            if fp in IDP_GROUPS:
                return fp
        return None


@dataclass(frozen=True)
class Projection:
    points: float
    provider_updated_at: str | None


@dataclass
class SeasonData:
    """Everything one season's backtest reads.  ``rosters[w][rid]`` is the
    host's matchup roster (ground truth); ``points[w][pid]`` is the
    league-card rescoring of week ``w``'s COMPLETE stat payload.

    ``cutoffs[w]`` is week ``w``'s FIRST kickoff (the decision cutoff);
    ``week_ends[w]`` its LAST kickoff (a move processed before it still lands
    on week ``w``'s matchup roster — measured, see :func:`effective_week`).
    ``slots`` is the starter-slot list proven to reproduce the host's awarded
    team totals (``slot_source`` says how it was obtained)."""

    season: int
    scoring: Mapping[str, Any]
    roster_positions: Sequence[str]
    weeks: tuple[int, ...]
    rosters: dict[int, dict[int, frozenset[str]]]
    host_team_points: dict[int, dict[int, float]]
    host_player_points: dict[int, dict[str, float]]
    transactions: list[Transaction]
    points: dict[int, dict[str, float]]
    played: dict[int, frozenset[str]]
    projections: dict[int, dict[str, Projection]]
    players: dict[str, PlayerInfo]
    cutoffs: dict[int, datetime]
    week_ends: dict[int, datetime] = field(default_factory=dict)
    host_starters: dict[int, dict[int, list[str]]] = field(default_factory=dict)
    slots: list[str] = field(default_factory=list)
    slot_source: str = "published_roster_positions"
    best_ball_verified: bool = True
    cutoff_source: str = "unknown"
    projection_source: str = "sleeper_weekly_projections(rotowire)"

    def __post_init__(self) -> None:
        if not self.slots:
            self.slots = starter_slots_from_roster_positions(list(self.roster_positions))

    def idp_ids(self) -> frozenset[str]:
        return frozenset(pid for pid, info in self.players.items() if info.group)

    def realized(self, week: int, pid: str) -> float:
        """Host rule: absent from a complete payload = 0.0 scored."""
        return float(self.points[week].get(pid, 0.0))


# ── Lineup ────────────────────────────────────────────────────────────


def idp_slots(slots: Sequence[str]) -> list[str]:
    """The starter slots that accept a defender (for reporting)."""
    idp_family = {"DL", "LB", "DB", "DE", "DT", "EDGE", "CB", "S", "ILB", "OLB"}
    return [s for s in slots if {p.upper() for p in slot_eligible_positions(s)} & idp_family]


def _roster_player(pid: str, info: PlayerInfo | None, points: float) -> RosterPlayer:
    return RosterPlayer(
        player_id=pid,
        canonical_name=pid,
        position=(info.position if info else ""),
        ros_value=float(points),
        fantasy_positions=(info.fantasy_positions if info else ()),
    )


def optimal_lineup(
    pids: Iterable[str],
    points: Mapping[str, float],
    players: Mapping[str, PlayerInfo],
    slots: Sequence[str],
) -> tuple[float, frozenset[str]]:
    """Best-ball lineup: ``(total, starter ids)`` maximising realized points
    via the canonical exact solver.  A player absent from ``points`` scored
    0.0 (the caller passes a COMPLETE week)."""
    pool = [_roster_player(p, players.get(p), points.get(p, 0.0)) for p in sorted(set(pids))]
    assignment = solve_optimal_assignment(pool, list(slots), objective=OBJECTIVE_REALIZED_POINTS)
    total = sum(float(p.ros_value or 0.0) for p in assignment.values())
    return total, frozenset(p.player_id for p in assignment.values())


def scenario_lineup(
    data: SeasonData,
    rid: int,
    week: int,
    idp_set: Iterable[str],
    offense: Iterable[str] | None = None,
) -> tuple[float, frozenset[str]]:
    """Whole-lineup realized points for a scenario: the team's ACTUAL
    non-defender roster that week plus the scenario's defenders.  Offense is
    identical across scenarios, so a difference between two scenarios is
    the defenders' effect only (a two-way player stays wherever the exact
    solver puts him)."""
    idp = data.idp_ids()
    if offense is None:
        offense = {p for p in data.rosters[week].get(rid, frozenset()) if p not in idp}
    return optimal_lineup(set(offense) | set(idp_set), data.points[week], data.players, data.slots)


def infer_slots_from_starters(
    starters_by_week: Mapping[int, Mapping[int, Sequence[str]]],
    players: Mapping[str, PlayerInfo],
) -> list[str] | None:
    """Recover the starter-slot list from the host's slot-ordered
    ``starters`` arrays: slot ``i`` is the MOST restrictive slot type whose
    eligibility admits every player the host ever seated there.  Used only
    when the published ``roster_positions`` fails to reproduce the host's
    totals, and itself verified by :func:`lineup_reproduction`."""
    lengths = {len(s) for teams in starters_by_week.values() for s in teams.values()}
    if len(lengths) != 1:
        return None
    n = lengths.pop()
    candidates = ["QB", "RB", "WR", "TE", "K", "DL", "LB", "DB", "FLEX", "SUPER_FLEX", "IDP_FLEX"]
    out: list[str] = []
    for i in range(n):
        seated = [
            players[s[i]]
            for teams in starters_by_week.values()
            for s in teams.values()
            if s[i] and s[i] != "0" and s[i] in players
        ]
        chosen = None
        for slot in candidates:
            elig = {p.upper() for p in slot_eligible_positions(slot)}
            if seated and all(
                {fp.upper() for fp in (info.fantasy_positions or (info.position,))} & elig
                for info in seated
            ):
                chosen = slot
                break
        if chosen is None:
            return None
        out.append(chosen)
    return out


# ── Roster reconstruction + change attribution ────────────────────────


def effective_week(at: datetime, week_ends: Mapping[int, datetime]) -> int | None:
    """The week whose matchup roster first carries a move processed at
    ``at``: the first week whose LAST kickoff is after it.  Measured on
    2026: a free-agent add on a Sunday of week ``w`` is on week ``w``'s
    roster, so the first-kickoff rule would be a week late."""
    for week in sorted(week_ends):
        if week_ends[week] > at:
            return week
    return None


def reconstruct_rosters(
    start: Mapping[int, frozenset[str]],
    start_week: int,
    weeks: Sequence[int],
    transactions: Iterable[Transaction],
    week_ends: Mapping[int, datetime],
) -> dict[int, dict[int, frozenset[str]]]:
    """Walk complete transactions FORWARD from a known roster snapshot.

    A transaction applies from :func:`effective_week` of its processing
    instant.  Verified against the host's matchup rosters by
    :func:`reconstruction_agreement`; the matchup rosters stay the ground
    truth for every scenario.
    """
    by_week: dict[int, list[Transaction]] = {}
    for tx in transactions:
        if tx.status != "complete":
            continue
        ew = effective_week(tx.at, week_ends)
        if ew is not None:
            by_week.setdefault(ew, []).append(tx)
    state = {rid: set(players) for rid, players in start.items()}
    out: dict[int, dict[int, frozenset[str]]] = {start_week: dict(start)}
    for week in weeks:
        if week <= start_week:
            continue
        for tx in sorted(by_week.get(week, []), key=lambda t: (t.status_updated_ms, t.tx_id)):
            for pid, rid in tx.drops.items():
                state.setdefault(rid, set()).discard(pid)
            for pid, rid in tx.adds.items():
                state.setdefault(rid, set()).add(pid)
        out[week] = {rid: frozenset(players) for rid, players in state.items()}
    return out


def reconstruction_agreement(
    recon: Mapping[int, Mapping[int, frozenset[str]]],
    truth: Mapping[int, Mapping[int, frozenset[str]]],
    *,
    only: frozenset[str] | None = None,
) -> dict[str, Any]:
    """Exact roster-week matches; ``only`` restricts the comparison to a
    player subset (e.g. defenders)."""
    exact = total = 0
    sym_diff = 0
    for week, teams in truth.items():
        if week not in recon:
            continue
        for rid, players in teams.items():
            got = recon[week].get(rid, frozenset())
            if only is not None:
                got, players = got & only, players & only
            total += 1
            if got == players:
                exact += 1
            sym_diff += len(got ^ players)
    return {
        "rosterWeeks": total,
        "exactMatches": exact,
        "exactShare": (exact / total) if total else None,
        "totalPlayerMismatches": sym_diff,
    }


@dataclass(frozen=True)
class RosterChange:
    week: int
    roster_id: int
    player_id: str
    direction: str  # "add" | "drop"
    kind: str  # waiver | free_agent | trade | commissioner | unattributed
    tx_id: str | None
    waiver_bid: float | None


def classify_roster_changes(data: SeasonData) -> list[RosterChange]:
    """Attribute every week-over-week matchup-roster difference to the
    transaction that caused it: the latest complete transaction for that
    team + player + direction processed in ``[week_end(w-1), week_end(w))``.
    An unmatched difference is ``unattributed`` — reported, never guessed."""
    weeks = sorted(data.rosters)
    index: dict[tuple[int, str, str], list[Transaction]] = {}
    for tx in data.transactions:
        if tx.status != "complete":
            continue
        for pid, rid in tx.adds.items():
            index.setdefault((rid, pid, "add"), []).append(tx)
        for pid, rid in tx.drops.items():
            index.setdefault((rid, pid, "drop"), []).append(tx)
    out: list[RosterChange] = []
    for prev, week in zip(weeks, weeks[1:]):
        lo = data.week_ends.get(prev)
        hi = data.week_ends.get(week)
        for rid, players in data.rosters[week].items():
            before = data.rosters[prev].get(rid, frozenset())
            for direction, pids in (("add", players - before), ("drop", before - players)):
                for pid in sorted(pids):
                    cands = [
                        t
                        for t in index.get((rid, pid, direction), [])
                        if (lo is None or t.at >= lo) and (hi is None or t.at < hi)
                    ]
                    tx = max(cands, key=lambda t: t.status_updated_ms) if cands else None
                    out.append(
                        RosterChange(
                            week=week,
                            roster_id=rid,
                            player_id=pid,
                            direction=direction,
                            kind=tx.tx_type if tx else "unattributed",
                            tx_id=tx.tx_id if tx else None,
                            waiver_bid=(tx.waiver_bid if tx and direction == "add" else None),
                        )
                    )
    return out


# ── Decision context (THE leakage boundary) ───────────────────────────


@dataclass(frozen=True)
class Swap:
    drop_id: str
    add_id: str
    faab_bid: float | None = None


@dataclass(frozen=True)
class DecisionContext:
    season: int
    week: int
    cutoff_utc: datetime
    team_index: int
    idp_roster: frozenset[str]
    pool: frozenset[str]
    positions: Mapping[str, str]  # player id -> swap group DL / LB / DB
    eligibility: Mapping[str, tuple[str, ...]]
    idp_slots: tuple[str, ...]
    realized_before: Mapping[str, Mapping[int, float]]
    projection: Mapping[str, float]
    dynasty_value: Mapping[str, float]
    max_swaps: int
    projection_point_in_time_verified: bool = False
    dynasty_value_source: str | None = None


class StreamingPolicy(Protocol):
    """Baseline 7 (W4's dynasty-safe solver) must satisfy this; so do the
    simple rules.  The harness — not the policy — enforces legality."""

    name: str

    def decide(self, ctx: DecisionContext) -> Sequence[Swap]: ...


DynastyLookup = Callable[[str, datetime], "float | None"]


def build_decision_context(
    data: SeasonData,
    *,
    week: int,
    team_index: int,
    idp_roster: Iterable[str],
    pool: Iterable[str],
    max_swaps: int,
    dynasty_lookup: DynastyLookup | None = None,
    dynasty_value_source: str | None = None,
) -> DecisionContext:
    """The ONE place a decision's timed inputs are assembled and filtered.

    * realized points: weeks strictly before ``week`` in which the player
      recorded a stat line (a week he did not play is unknown, not 0);
    * projection: week ``week`` only;
    * dynasty value: whatever ``dynasty_lookup`` returns for the cutoff
      instant — the lookup itself must be instant-strict
      (:func:`ledger_dynasty_lookup` is).
    """
    cutoff = data.cutoffs[week]
    roster = frozenset(idp_roster)
    pool_set = frozenset(pool) - roster
    relevant = roster | pool_set
    realized: dict[str, dict[int, float]] = {}
    for w in data.weeks:
        if w >= week:
            continue
        pts = data.points.get(w, {})
        for pid in data.played.get(w, frozenset()) & relevant:
            realized.setdefault(pid, {})[w] = float(pts.get(pid, 0.0))
    proj_week = data.projections.get(week, {})
    projection = {pid: p.points for pid, p in proj_week.items() if pid in relevant}
    dyn: dict[str, float] = {}
    if dynasty_lookup is not None:
        for pid in sorted(roster):
            val = dynasty_lookup(pid, cutoff)
            if val is not None:
                dyn[pid] = val
    # The SWAP GROUP (DL / LB / DB), never the dump's raw sub-position: a
    # DE / DT / CB / S would otherwise match no group and silently never move.
    positions = {pid: data.players[pid].group or "" for pid in relevant if pid in data.players}
    eligibility = {
        pid: data.players[pid].fantasy_positions for pid in relevant if pid in data.players
    }
    return DecisionContext(
        season=data.season,
        week=week,
        cutoff_utc=cutoff,
        team_index=team_index,
        idp_roster=roster,
        pool=pool_set,
        positions=positions,
        eligibility=eligibility,
        idp_slots=tuple(idp_slots(data.slots)),
        realized_before=realized,
        projection=projection,
        dynasty_value=dyn,
        max_swaps=max_swaps,
        dynasty_value_source=dynasty_value_source,
    )


# ── Rule policies (baselines 2, 3, 4, 6) ──────────────────────────────

Metric = Callable[[str, DecisionContext], "float | None"]


def metric_previous_week(pid: str, ctx: DecisionContext) -> float | None:
    return ctx.realized_before.get(pid, {}).get(ctx.week - 1)


def metric_rolling(pid: str, ctx: DecisionContext) -> float | None:
    hist = ctx.realized_before.get(pid, {})
    recent = [hist[w] for w in sorted(hist)[-ROLLING_WINDOW:]]
    if len(recent) < ROLLING_MIN_GAMES:
        return None
    return statistics.fmean(recent)


def metric_projection(pid: str, ctx: DecisionContext) -> float | None:
    return ctx.projection.get(pid)


@dataclass
class MetricSwapPolicy:
    """Greedy 1-for-1 within-group swaps on one metric; strict improvement.

    Ties break deterministically: lower drop metric then lower id; higher add
    metric then lower id.
    """

    name: str
    metric: Metric

    def decide(self, ctx: DecisionContext) -> list[Swap]:
        known: dict[str, float] = {}
        for pid in ctx.idp_roster | ctx.pool:
            m = self.metric(pid, ctx)
            if m is not None:
                known[pid] = m
        roster = {p for p in ctx.idp_roster if p in known}
        pool = {p for p in ctx.pool if p in known}
        return _greedy_swaps(
            ctx,
            roster,
            pool,
            add_score=lambda p: known[p],
            pick_drop=lambda group_roster, _add: min(group_roster, key=lambda p: (known[p], p)),
            drop_score=lambda p: known[p],
        )


def _greedy_swaps(
    ctx: DecisionContext,
    roster: set[str],
    pool: set[str],
    *,
    add_score: Callable[[str], float],
    pick_drop: Callable[[list[str], str], "str | None"],
    drop_score: Callable[[str], float],
) -> list[Swap]:
    """Shared greedy: per group, the best add and its chosen drop; take the
    largest strictly positive improvement; repeat up to ``max_swaps``.  A
    defender released this week is not re-added the same week, and one added
    this week is not released the same week (that pair would net to a
    different, single swap and inflate the transaction count)."""
    swaps: list[Swap] = []
    released: set[str] = set()
    added: set[str] = set()
    for _ in range(ctx.max_swaps):
        best: tuple[float, str, str] | None = None
        for group in IDP_GROUPS:
            adds = [p for p in pool if ctx.positions.get(p) == group and p not in released]
            if not adds:
                continue
            a_id = min(adds, key=lambda p: (-add_score(p), p))
            group_roster = [
                p
                for p in roster
                if ctx.positions.get(p) == group
                and p not in added
                and drop_score(p) < add_score(a_id)
            ]
            if not group_roster:
                continue
            d_id = pick_drop(group_roster, a_id)
            if d_id is None:
                continue
            gain = add_score(a_id) - drop_score(d_id)
            if gain > 0 and (best is None or gain > best[0]):
                best = (gain, d_id, a_id)
        if best is None:
            break
        _, d_id, a_id = best
        swaps.append(Swap(d_id, a_id, 0.0))
        roster.discard(d_id)
        roster.add(a_id)
        pool.discard(a_id)
        released.add(d_id)
        added.add(a_id)
    return swaps


@dataclass
class DynastyReleasePolicy:
    """Baseline 6: add by projection; release the lowest point-in-time
    dynasty value among same-group rostered defenders projected below the
    add.  Unpriced (no observed value) are released first — a declared tier,
    never 'value 0'."""

    name: str = "6_release_lowest_dynasty_value"

    def decide(self, ctx: DecisionContext) -> list[Swap]:
        proj = ctx.projection
        roster = {p for p in ctx.idp_roster if p in proj}
        pool = {p for p in ctx.pool if p in proj}
        return _greedy_swaps(
            ctx,
            roster,
            pool,
            add_score=lambda p: proj[p],
            pick_drop=lambda group_roster, _add: min(
                group_roster,
                key=lambda p: (
                    p in ctx.dynasty_value,
                    ctx.dynasty_value.get(p, 0.0),
                    proj[p],
                    p,
                ),
            ),
            drop_score=lambda p: proj[p],
        )


# ── Scenarios ─────────────────────────────────────────────────────────


@dataclass
class WeekResult:
    week: int
    idp_set: frozenset[str]
    lineup_points: float
    starters: frozenset[str]
    adds: tuple[str, ...] = ()
    drops: tuple[str, ...] = ()
    faab: float | None = 0.0
    rejected_swaps: int = 0


def _idp_set(data: SeasonData, players: Iterable[str]) -> frozenset[str]:
    idp = data.idp_ids()
    return frozenset(p for p in players if p in idp)


def _non_streaming_deltas(
    changes: Sequence[RosterChange], data: SeasonData, rid: int
) -> dict[int, tuple[set[str], set[str]]]:
    """Per week: (defenders in, defenders out) by trades / commissioner /
    unattributed moves — applied in EVERY scenario."""
    idp = data.idp_ids()
    out: dict[int, tuple[set[str], set[str]]] = {}
    for ch in changes:
        if ch.roster_id != rid or ch.player_id not in idp or ch.kind in STREAMING_TX_TYPES:
            continue
        ins, outs = out.setdefault(ch.week, (set(), set()))
        (ins if ch.direction == "add" else outs).add(ch.player_id)
    return out


def decision_weeks(data: SeasonData) -> list[int]:
    return [w for w in data.weeks if w > min(data.weeks)]


def simulate_actual(data: SeasonData, rid: int) -> list[WeekResult]:
    out = []
    for w in decision_weeks(data):
        s = _idp_set(data, data.rosters[w].get(rid, frozenset()))
        pts, starters = scenario_lineup(data, rid, w, s)
        out.append(WeekResult(w, s, pts, starters))
    return out


def simulate_hold(data: SeasonData, rid: int, changes: Sequence[RosterChange]) -> list[WeekResult]:
    deltas = _non_streaming_deltas(changes, data, rid)
    state = set(_idp_set(data, data.rosters[min(data.weeks)].get(rid, frozenset())))
    out = []
    for w in decision_weeks(data):
        ins, outs = deltas.get(w, (set(), set()))
        state -= outs
        state |= ins
        s = frozenset(state)
        pts, starters = scenario_lineup(data, rid, w, s)
        out.append(WeekResult(w, s, pts, starters))
    return out


def simulate_hold_full(
    data: SeasonData, rid: int, changes: Sequence[RosterChange]
) -> list[WeekResult]:
    """Baseline 1b: undo EVERY streaming transaction that touches a defender,
    including its non-defender legs.  When a manager releases an offensive
    player to add a defender, baseline 1 keeps the release (offense is the
    actual offense in every scenario) and so never charges the offense that
    funded the extra defender; this variant restores it.  ``actual − 1b`` is
    the net effect of the defender-involving streaming moves."""
    idp = data.idp_ids()
    tx_by_id = {t.tx_id: t for t in data.transactions}
    defender_tx = {
        t.tx_id
        for t in data.transactions
        if t.tx_type in STREAMING_TX_TYPES
        and any(r == rid and p in idp for p, r in (*t.adds.items(), *t.drops.items()))
    }
    off_added: set[str] = set()
    off_dropped: set[str] = set()
    by_week: dict[int, list[RosterChange]] = {}
    for ch in changes:
        if ch.roster_id == rid and ch.player_id not in idp and ch.tx_id in defender_tx:
            by_week.setdefault(ch.week, []).append(ch)
    hold = simulate_hold(data, rid, changes)
    out = []
    for r in hold:
        for ch in by_week.get(r.week, []):
            if tx_by_id.get(ch.tx_id or "") is None:
                continue
            if ch.direction == "add":
                off_added.add(ch.player_id)
                off_dropped.discard(ch.player_id)
            else:
                off_dropped.add(ch.player_id)
                off_added.discard(ch.player_id)
        actual_off = {p for p in data.rosters[r.week].get(rid, frozenset()) if p not in idp}
        offense = (actual_off - off_added) | off_dropped
        pts, starters = scenario_lineup(data, rid, r.week, r.idp_set, offense=offense)
        out.append(WeekResult(r.week, r.idp_set, pts, starters))
    return out


def available_pool(
    data: SeasonData, rid: int, week: int, own: Iterable[str], *, masked: bool
) -> frozenset[str]:
    """Defenders not on ANOTHER team at the end of week-1; ``masked`` also
    drops anyone another team rostered in ``week`` (cleared waivers
    unclaimed → a $0 free-agent add).  A restriction only; see prereg §2."""
    taken: set[str] = set()
    for other, players in data.rosters[week - 1].items():
        if other != rid:
            taken |= players
    if masked:
        for other, players in data.rosters[week].items():
            if other != rid:
                taken |= players
    return frozenset(data.idp_ids() - taken - set(own))


def simulate_policy(
    data: SeasonData,
    rid: int,
    team_index: int,
    policy: StreamingPolicy,
    changes: Sequence[RosterChange],
    *,
    max_swaps: int,
    masked: bool,
    dynasty_lookup: DynastyLookup | None = None,
    dynasty_value_source: str | None = None,
) -> list[WeekResult]:
    deltas = _non_streaming_deltas(changes, data, rid)
    state = set(_idp_set(data, data.rosters[min(data.weeks)].get(rid, frozenset())))
    out = []
    for w in decision_weeks(data):
        ins, outs = deltas.get(w, (set(), set()))
        state -= outs
        state |= ins
        others_now = {
            p for other, players in data.rosters[w].items() if other != rid for p in players
        }
        pool = available_pool(data, rid, w, state, masked=masked)
        ctx = build_decision_context(
            data,
            week=w,
            team_index=team_index,
            idp_roster=state,
            pool=pool,
            max_swaps=max_swaps,
            dynasty_lookup=dynasty_lookup,
            dynasty_value_source=dynasty_value_source,
        )
        adds: list[str] = []
        drops: list[str] = []
        rejected = 0
        faab: float | None = 0.0
        avail = set(pool)
        for sw in list(policy.decide(ctx))[:max_swaps]:
            if sw.drop_id not in state or sw.add_id not in avail or sw.add_id in state:
                rejected += 1
                continue
            state.discard(sw.drop_id)
            state.add(sw.add_id)
            avail.discard(sw.add_id)
            avail.add(sw.drop_id)
            adds.append(sw.add_id)
            drops.append(sw.drop_id)
            if sw.add_id in others_now:
                faab = None  # contested: another team took him; cost unknown, never $0
            elif sw.faab_bid not in (None, 0.0) and faab is not None:
                faab += float(sw.faab_bid)
        s = frozenset(state)
        pts, starters = scenario_lineup(data, rid, w, s)
        out.append(WeekResult(w, s, pts, starters, tuple(adds), tuple(drops), faab, rejected))
    return out


# ── Statistics ────────────────────────────────────────────────────────


def bootstrap_ci(
    values: Sequence[float],
    *,
    clusters: Sequence[Sequence[float]] | None = None,
    resamples: int = BOOTSTRAP_RESAMPLES,
    seed: int = BOOTSTRAP_SEED,
) -> tuple[float, float] | None:
    """95% percentile CI of the mean.  With ``clusters``, resamples whole
    clusters and takes the pooled mean (cluster bootstrap)."""
    rng = random.Random(seed)
    stats: list[float] = []
    if clusters is not None:
        cl = [list(c) for c in clusters if c]
        if not cl:
            return None
        for _ in range(resamples):
            pick = [cl[rng.randrange(len(cl))] for _ in cl]
            flat = [v for c in pick for v in c]
            stats.append(sum(flat) / len(flat))
    else:
        vals = list(values)
        if not vals:
            return None
        n = len(vals)
        for _ in range(resamples):
            stats.append(sum(vals[rng.randrange(n)] for _ in range(n)) / n)
    stats.sort()
    lo = stats[int(math.floor(0.025 * (len(stats) - 1)))]
    hi = stats[int(math.ceil(0.975 * (len(stats) - 1)))]
    return lo, hi


def verdict(ci: tuple[float, float] | None) -> str:
    if ci is None:
        return "INSUFFICIENT"
    if ci[0] > 0:
        return "gains"
    if ci[1] < 0:
        return "loses"
    return "no_detectable_effect"


def summarize_deltas(
    per_week: Sequence[float], *, minimum: int, clusters: Sequence[Sequence[float]] | None = None
) -> dict[str, Any]:
    n = len(per_week)
    unit_n = len([c for c in clusters if c]) if clusters is not None else n
    out: dict[str, Any] = {
        "n": n,
        "nClusters": unit_n if clusters is not None else None,
        "mean": (sum(per_week) / n) if n else None,
        "total": sum(per_week) if n else None,
    }
    if unit_n < minimum:
        out.update(ci95=None, verdict="INSUFFICIENT", minimum=minimum)
        return out
    ci = bootstrap_ci(per_week, clusters=clusters)
    out.update(ci95=list(ci) if ci else None, verdict=verdict(ci), minimum=minimum)
    return out


# ── Point-in-time dynasty value ───────────────────────────────────────


def ledger_dynasty_lookup(
    ledger_path: Path | None, *, lane: str, source_key: str = ""
) -> DynastyLookup:
    """Instant-strict value lookup through ``src.history`` (never today's
    value; before the history floor → None)."""
    from src.history.asof import value_known_before
    from src.history.keys import player_asset_key

    memo: dict[tuple[str, str], float | None] = {}

    def lookup(pid: str, instant: datetime) -> float | None:
        key = (pid, instant.isoformat())
        if key not in memo:
            asset = player_asset_key(pid, None, None)
            res = value_known_before(
                asset,
                instant,
                lane=lane,
                source_key=source_key,
                path=ledger_path,
                # No knowledge_cutoff: a locally rebuilt ledger RECORDS every
                # archive row at rebuild time (today), which would hide all
                # of them.  The observation instant (the archive's own
                # timestamp) is what proves the value existed before the
                # decision, and it is enforced instant-strictly above.
            )
            val = res.get("value")
            memo[key] = (
                float(val)
                if val is not None
                and res.get("fidelity")
                in (
                    "exact",
                    "nearest-prior",
                )
                else None
            )
        return memo[key]

    return lookup


# ── Projection accuracy ───────────────────────────────────────────────


def projection_accuracy(data: SeasonData) -> dict[str, Any]:
    by_group: dict[str, list[float]] = {g: [] for g in IDP_GROUPS}
    after_kickoff = total_rows = 0
    for w in data.weeks:
        cutoff = data.cutoffs.get(w)
        for pid, proj in data.projections.get(w, {}).items():
            info = data.players.get(pid)
            if not info or not info.group:
                continue
            total_rows += 1
            if proj.provider_updated_at and cutoff:
                if datetime.fromisoformat(proj.provider_updated_at) > cutoff:
                    after_kickoff += 1
            if pid not in data.played.get(w, frozenset()):
                continue
            by_group[info.group].append(proj.points - data.realized(w, pid))
    out: dict[str, Any] = {
        "projectionRows": total_rows,
        "rowsUpdatedAfterCutoff": after_kickoff,
        "shareUpdatedAfterCutoff": (after_kickoff / total_rows) if total_rows else None,
        "byPosition": {},
    }
    for g, errs in by_group.items():
        n = len(errs)
        if n < MIN_PLAYER_WEEKS_ACCURACY:
            out["byPosition"][g] = {"n": n, "verdict": "INSUFFICIENT"}
            continue
        out["byPosition"][g] = {
            "n": n,
            "mae": statistics.fmean(abs(e) for e in errs),
            "rmse": math.sqrt(statistics.fmean(e * e for e in errs)),
            "bias": statistics.fmean(errs),
        }
    return out


# ── Fetch layer (cached, read-only public API) ────────────────────────


class DiskCache:
    """Raw Sleeper responses cached under the gitignored research dir.

    A cached payload is reused verbatim; a failed fetch is never cached.
    """

    def __init__(self, root: Path) -> None:
        self.root = root
        self.root.mkdir(parents=True, exist_ok=True)

    def _path(self, name: str) -> Path:
        return self.root / f"{name}.json.gz"

    def get(self, name: str, fetch: Callable[[], Any]) -> Any:
        path = self._path(name)
        if path.exists():
            with gzip.open(path, "rt", encoding="utf-8") as fh:
                return json.load(fh)
        payload = fetch()
        if payload is None:
            return None
        with gzip.open(path, "wt", encoding="utf-8") as fh:
            json.dump(payload, fh)
        return payload


def _sleeper_json(path: str) -> Any:
    from src.public_league import sleeper_client

    kind, payload = sleeper_client.request_json_classified(f"{sleeper_client.SLEEPER_BASE}{path}")
    if kind != sleeper_client.FETCH_OK:
        raise RuntimeError(f"sleeper fetch {path} -> {kind}")
    return payload


def _kickoffs_utc(
    season: int, sleeper_schedule: Any
) -> tuple[dict[int, datetime], dict[int, datetime], str]:
    """``(first kickoff, last kickoff, source)`` per regular-season week.
    nflverse (the canonical schedule owner) first; else Sleeper's schedule
    DATE: first = that date at 00:00 UTC (earlier than any kickoff, so a
    conservative decision cutoff), last = the last date + 1 day."""
    from zoneinfo import ZoneInfo

    first: dict[int, datetime] = {}
    last: dict[int, datetime] = {}

    def _put(week: int, utc: datetime, end: datetime) -> None:
        if week not in first or utc < first[week]:
            first[week] = utc
        if week not in last or end > last[week]:
            last[week] = end

    try:
        from src.nfl_data import ingest

        rows = ingest.fetch_schedules([season]) or []
    except Exception:  # noqa: BLE001
        rows = []
    et = ZoneInfo("America/New_York")
    for row in rows:
        if int(row.get("season") or 0) != season or row.get("game_type") != "REG":
            continue
        try:
            day = str(row["gameday"])
            hhmm = str(row.get("gametime") or "00:00")
            local = datetime.fromisoformat(f"{day}T{hhmm}:00").replace(tzinfo=et)
        except (KeyError, ValueError):
            continue
        utc = local.astimezone(timezone.utc)
        _put(int(row["week"]), utc, utc)
    if first:
        return first, last, "nflverse_schedule"
    for game in sleeper_schedule or []:
        try:
            utc = datetime.fromisoformat(str(game["date"])).replace(tzinfo=timezone.utc)
        except (KeyError, ValueError):
            continue
        _put(int(game["week"]), utc, utc + timedelta(days=1))
    return first, last, "sleeper_schedule_date_utc"


def _http_bytes(url: str, timeout: float) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": "riskit-research-idp-streaming/1.0"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:  # noqa: S310
        return resp.read()


def load_season(
    league: Mapping[str, Any],
    weeks: Sequence[int],
    *,
    cache: DiskCache,
    players_dump: Mapping[str, Any],
) -> tuple[SeasonData, dict[str, Any]]:
    """Fetch (or replay from cache) everything one season needs.

    Returns ``(data, private)`` where ``private`` carries names and ids that
    must stay in the gitignored research dir.
    """
    from src.league_comparison.sleeper_stats import fetch_week_stats_response
    from src.nfl_data.realized_points import is_host_player_entry
    from src.ros.sleeper_weekly_projections import (
        build_weekly_observations,
        fetch_weekly_projection_rows,
    )

    lid = str(league["league_id"])
    season = int(league["season"])
    tag = f"{season}"
    users = cache.get(f"{tag}_users", lambda: _sleeper_json(f"/league/{lid}/users"))
    rosters_now = cache.get(f"{tag}_rosters", lambda: _sleeper_json(f"/league/{lid}/rosters"))
    rosters: dict[int, dict[int, frozenset[str]]] = {}
    host_team: dict[int, dict[int, float]] = {}
    host_player: dict[int, dict[str, float]] = {}
    host_starters: dict[int, dict[int, list[str]]] = {}
    for w in weeks:
        mus = cache.get(
            f"{tag}_matchups_{w}", lambda w=w: _sleeper_json(f"/league/{lid}/matchups/{w}")
        )
        rosters[w] = {int(m["roster_id"]): frozenset(map(str, m.get("players") or [])) for m in mus}
        host_team[w] = {int(m["roster_id"]): float(m.get("points") or 0.0) for m in mus}
        host_player[w] = {
            str(pid): float(v) for m in mus for pid, v in (m.get("players_points") or {}).items()
        }
        host_starters[w] = {
            int(m["roster_id"]): [str(p) for p in m.get("starters") or []] for m in mus
        }
    transactions: list[Transaction] = []
    for leg in range(1, 19):
        txs = cache.get(
            f"{tag}_transactions_{leg}",
            lambda leg=leg: _sleeper_json(f"/league/{lid}/transactions/{leg}"),
        )
        transactions.extend(transaction_from_sleeper(t) for t in txs or [])
    scoring = dict(league.get("scoring_settings") or {})
    points: dict[int, dict[str, float]] = {}
    played: dict[int, frozenset[str]] = {}
    for w in weeks:

        def _stats(w: int = w) -> Any:
            resp = fetch_week_stats_response(season, w)
            if resp.error is not None or not isinstance(resp.payload, Mapping):
                raise RuntimeError(f"stats {season} w{w}: {resp.error}")
            return resp.payload

        payload = cache.get(f"{tag}_stats_{w}", _stats)
        if not payload:
            raise RuntimeError(f"stats {season} w{w}: empty payload (missing is not zero)")
        pts: dict[str, float] = {}
        pl: set[str] = set()
        for pid, line in payload.items():
            if not is_host_player_entry(pid) or not isinstance(line, Mapping):
                continue
            stats = {k: v for k, v in line.items() if isinstance(v, (int, float))}
            pts[str(pid)] = score_stat_line(stats, scoring).total_points
            if float(stats.get("gp", 1.0) or 0.0) >= 1.0:
                pl.add(str(pid))
        points[w] = pts
        played[w] = frozenset(pl)
    projections: dict[int, dict[str, Projection]] = {}
    for w in weeks:

        def _getter(url: str, timeout: float, w: int = w) -> bytes:
            raw = cache.get(
                f"{tag}_projections_{w}",
                lambda: json.loads(_http_bytes(url, timeout).decode("utf-8")),
            )
            return json.dumps(raw).encode("utf-8")

        res = fetch_weekly_projection_rows(season, w, http_get=_getter)
        if res.status != "ok":
            projections[w] = {}
            continue
        batch = build_weekly_observations(
            res.rows, season=season, week=w, observed_at=res.observed_at, scoring_settings=scoring
        )
        projections[w] = {
            o.sleeper_player_id: Projection(o.league_scored_points, o.provider_updated_at)
            for o in batch.observations
        }
    sched = cache.get(
        f"{tag}_schedule",
        lambda: json.loads(
            _http_bytes(f"https://api.sleeper.app/schedule/nfl/regular/{season}", 20.0)
        ),
    )
    cutoffs, week_ends, cutoff_source = _kickoffs_utc(season, sched)
    players: dict[str, PlayerInfo] = {}
    for pid, row in players_dump.items():
        pos = str(row.get("position") or "").upper()
        fps = tuple(str(p).upper() for p in (row.get("fantasy_positions") or ()) if p)
        if pos in IDP_GROUPS or any(p in IDP_GROUPS for p in fps):
            players[str(pid)] = PlayerInfo(pos, fps or (pos,))
        else:
            players[str(pid)] = PlayerInfo(pos, fps or ((pos,) if pos else ()))
    data = SeasonData(
        season=season,
        scoring=scoring,
        roster_positions=list(league.get("roster_positions") or []),
        weeks=tuple(weeks),
        rosters=rosters,
        host_team_points=host_team,
        host_player_points=host_player,
        transactions=transactions,
        points=points,
        played=played,
        projections=projections,
        players=players,
        cutoffs=cutoffs,
        week_ends=week_ends,
        host_starters=host_starters,
        cutoff_source=cutoff_source,
    )
    _resolve_slots(data)
    owner_by_user = {str(u.get("user_id")): u.get("display_name") for u in users or []}
    private = {
        "season": season,
        "rosterOwners": {
            int(r["roster_id"]): owner_by_user.get(str(r.get("owner_id"))) for r in rosters_now
        },
    }
    return data, private


# ── Verification ──────────────────────────────────────────────────────


def rescoring_agreement(data: SeasonData, tol: float = 0.011) -> dict[str, Any]:
    """Our league-card rescoring vs the host's ``players_points`` on every
    rostered player-week, IDP and all."""
    n = agree = 0
    idp_n = idp_agree = 0
    worst = 0.0
    idp = data.idp_ids()
    for w in data.weeks:
        for pid, host in data.host_player_points.get(w, {}).items():
            ours = data.realized(w, pid)
            ok = abs(ours - host) <= tol
            n += 1
            agree += ok
            if pid in idp:
                idp_n += 1
                idp_agree += ok
            worst = max(worst, abs(ours - host))
    return {
        "playerWeeks": n,
        "agree": agree,
        "idpPlayerWeeks": idp_n,
        "idpAgree": idp_agree,
        "maxAbsDiff": round(worst, 3),
        "tolerance": tol,
    }


def lineup_reproduction(
    data: SeasonData, slots: Sequence[str] | None = None, tol: float = 0.02
) -> dict[str, Any]:
    """Solver + slots on HOST player points vs the host's awarded totals."""
    use = list(slots if slots is not None else data.slots)
    n = agree = 0
    worst = 0.0
    for w in data.weeks:
        for rid, players in data.rosters[w].items():
            ours, _ = optimal_lineup(players, data.host_player_points[w], data.players, use)
            host = data.host_team_points[w].get(rid, 0.0)
            n += 1
            agree += abs(ours - host) <= tol
            worst = max(worst, abs(ours - host))
    return {"teamWeeks": n, "agree": agree, "maxAbsDiff": round(worst, 3), "tolerance": tol}


def _resolve_slots(data: SeasonData) -> None:
    """Keep the published slot list if it reproduces every host team total;
    otherwise try the list recovered from the host's ``starters`` arrays.
    Measured: the 2025 league object's published ``roster_positions`` (17
    starters) does NOT match the 22-starter lineups the host awarded that
    season, so a published list is evidence to verify, not truth."""
    published = starter_slots_from_roster_positions(list(data.roster_positions))
    rep = lineup_reproduction(data, published)
    if rep["teamWeeks"] and rep["agree"] == rep["teamWeeks"]:
        data.slots, data.slot_source = published, "published_roster_positions(verified)"
        return
    inferred = infer_slots_from_starters(data.host_starters, data.players)
    if inferred is not None:
        rep2 = lineup_reproduction(data, inferred)
        if rep2["teamWeeks"] and rep2["agree"] == rep2["teamWeeks"]:
            data.slots, data.slot_source = inferred, "inferred_from_host_starters(verified)"
            return
        if host_lineups_legal(data, inferred):
            # Every host lineup is a legal fill of these slots, yet the host
            # total is not the optimum: lineups were MANAGER-SET that season,
            # whatever the league object says today.  Optimal-lineup points
            # are then a POTENTIAL, not the awarded score — labelled.
            data.slots, data.slot_source = inferred, "inferred_from_host_starters(manager_set)"
            data.best_ball_verified = False
            return
    data.slots, data.slot_source = published, "published_roster_positions(UNVERIFIED)"
    data.best_ball_verified = False


def host_lineups_legal(data: SeasonData, slots: Sequence[str]) -> bool:
    """Is every host ``starters`` array a legal slot-by-slot fill?"""
    elig = [{p.upper() for p in slot_eligible_positions(s)} for s in slots]
    for teams in data.host_starters.values():
        for starters in teams.values():
            if len(starters) != len(slots):
                return False
            for i, pid in enumerate(starters):
                if not pid or pid == "0":
                    continue
                info = data.players.get(pid)
                if info is None:
                    continue
                if not (
                    {fp.upper() for fp in (info.fantasy_positions or (info.position,))} & elig[i]
                ):
                    return False
    return True


# ── Manager-level streaming detail ────────────────────────────────────


def streaming_activity(data: SeasonData, rid: int) -> dict[str, Any]:
    """Transaction-level defender churn for one team: every complete waiver /
    free-agent defender add or drop processed before the last scored week
    ended (including an add-and-drop inside one week that a matchup diff
    cannot see).  FAAB = winning bids on waiver claims that added a defender."""
    idp = data.idp_ids()
    end = data.week_ends.get(max(data.weeks)) if data.weeks else None
    txs = [
        t
        for t in data.transactions
        if t.status == "complete"
        and t.tx_type in STREAMING_TX_TYPES
        and (end is None or t.at < end)
    ]
    adds = [(t, p) for t in txs for p, r in t.adds.items() if r == rid and p in idp]
    drops = [(t, p) for t in txs for p, r in t.drops.items() if r == rid and p in idp]
    add_txs = {t.tx_id: t for t, _ in adds}
    by_group: dict[str, int] = {g: 0 for g in IDP_GROUPS}
    per_week: dict[int, int] = {}
    for t, p in adds:
        by_group[data.players[p].group or "?"] = by_group.get(data.players[p].group or "?", 0) + 1
        wk = effective_week(t.at, data.week_ends)
        if wk is not None:
            per_week[wk] = per_week.get(wk, 0) + 1
    bids = [t.waiver_bid for t in add_txs.values() if t.tx_type == "waiver"]
    return {
        "idpAdds": len(adds),
        "idpDrops": len(drops),
        "idpAddsBeforeWeek1Kickoff": sum(
            1
            for t, _ in adds
            if min(data.weeks) in data.cutoffs and t.at < data.cutoffs[min(data.weeks)]
        ),
        "faabOnIdpWaiverWins": sum(b for b in bids if b is not None),
        "idpWaiverWins": len(bids),
        "idpWaiverWinsAtZero": sum(1 for b in bids if b == 0.0),
        "addsByGroup": by_group,
        "addsByEffectiveWeek": dict(sorted(per_week.items())),
    }


def move_outcomes(
    data: SeasonData,
    rid: int,
    changes: Sequence[RosterChange],
    *,
    horizon: int = 3,
    dynasty_lookup: DynastyLookup | None = None,
) -> list[dict[str, Any]]:
    """For each matchup-visible streaming defender add, pair it with the
    defender released in the same transaction (if any) and compare their
    realized points over the following weeks.  Week ``w`` = the week the
    add first appears on the roster."""
    idp = data.idp_ids()
    tx_by_id = {t.tx_id: t for t in data.transactions}
    out = []
    weeks = list(data.weeks)
    for ch in changes:
        if (
            ch.roster_id != rid
            or ch.direction != "add"
            or ch.player_id not in idp
            or ch.kind not in STREAMING_TX_TYPES
        ):
            continue
        tx = tx_by_id.get(ch.tx_id or "")
        released = [p for p, r in (tx.drops.items() if tx else ()) if r == rid and p in idp]
        span = [w for w in weeks if ch.week <= w < ch.week + horizon]
        add_pts = sum(data.realized(w, ch.player_id) for w in span)
        rel_pts = sum(data.realized(w, p) for w in span for p in released) if released else None
        roster = data.rosters[ch.week].get(rid, frozenset())
        _, starters = optimal_lineup(roster, data.points[ch.week], data.players, data.slots)
        made_lineup = ch.player_id in starters
        dyn_released = None
        if dynasty_lookup is not None and released and ch.week in data.cutoffs:
            vals = [dynasty_lookup(p, data.cutoffs[ch.week]) for p in released]
            acq = dynasty_lookup(ch.player_id, data.cutoffs[ch.week])
            dyn_released = {
                "valued": sum(1 for v in vals if v is not None),
                "unvalued": sum(1 for v in vals if v is None),
                "sum": sum(v for v in vals if v is not None),
                "acquiredValued": int(acq is not None),
                "acquiredSum": acq or 0.0,
            }
        out.append(
            {
                "week": ch.week,
                "group": data.players[ch.player_id].group,
                "faab": ch.waiver_bid,
                "kind": ch.kind,
                "weeksObserved": len(span),
                "addPoints": add_pts,
                "addPointsNext1": _window_points(data, ch.player_id, ch.week, 1),
                "releasedPointsNext1": (
                    sum(_window_points(data, p, ch.week, 1) for p in released) if released else None
                ),
                "releasedCount": len(released),
                "releasedPoints": rel_pts,
                "madeLineupFirstWeek": made_lineup,
                "falsePositive": (rel_pts is not None and add_pts < rel_pts),
                "releasedDynastyValue": dyn_released,
                "_addId": ch.player_id,
                "_releasedIds": released,
            }
        )
    return out


# ── Runner ────────────────────────────────────────────────────────────

RULE_POLICIES: tuple[tuple[str, Callable[[], StreamingPolicy]], ...] = (
    (
        "2_previous_week_points",
        lambda: MetricSwapPolicy("2_previous_week_points", metric_previous_week),
    ),
    (
        "3_rolling_recent_production",
        lambda: MetricSwapPolicy("3_rolling_recent_production", metric_rolling),
    ),
    (
        "4_single_projection_provider",
        lambda: MetricSwapPolicy("4_single_projection_provider", metric_projection),
    ),
    ("6_release_lowest_dynasty_value", DynastyReleasePolicy),
)
SWAP_CAPS: tuple[int, ...] = (1, 3, 5)
PRIMARY_SWAP_CAP = 3


def _season_weeks(league: Mapping[str, Any]) -> list[int]:
    settings = league.get("settings") or {}
    if str(league.get("status")) == "complete":
        last = int(settings.get("playoff_week_start") or 15) - 1
    else:
        last = min(
            int(settings.get("last_scored_leg") or 0),
            int(settings.get("playoff_week_start") or 15) - 1,
        )
    return list(range(1, last + 1))


def _deltas(scen: Sequence[WeekResult], base: Sequence[WeekResult]) -> list[float]:
    by_week = {r.week: r.lineup_points for r in base}
    return [r.lineup_points - by_week[r.week] for r in scen]


def run_backtest(
    *,
    registry_league_key: str = "dynasty_main",
    seasons: Sequence[int] = (2025, 2026),
    manager_display_name: str,
    cache_dir: Path | None = None,
    ledger_path: Path | None = None,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Run every preregistered baseline.  Returns ``(evidence, private)``;
    only ``evidence`` (anonymous) may be committed."""
    from src.public_league import sleeper_client

    registry = json.loads(
        (REPO / "config" / "leagues" / "registry.json").read_text(encoding="utf-8")
    )
    start_id = next(
        str(lg["sleeperLeagueId"])
        for lg in registry["leagues"]
        if lg.get("key") == registry_league_key
    )
    cache = DiskCache(cache_dir or (RESEARCH_DIR / "raw"))
    chain = cache.get("chain", lambda: sleeper_client.walk_league_chain(start_id))
    dump = cache.get("players_nfl", sleeper_client.fetch_nfl_players)
    if not dump:
        raise RuntimeError("players dump unavailable (an empty dump is a failure)")

    canonical_lookup = ledger_dynasty_lookup(ledger_path, lane="canonical_board")
    idptc_lookup = ledger_dynasty_lookup(
        ledger_path, lane="source_value", source_key="idpTradeCalc"
    )

    evidence: dict[str, Any] = {
        "schema": "idp_streaming_backtest_v1",
        "preregistration": "docs/waivers/IDP_STREAMING_BACKTEST_PREREGISTRATION_2026-10-29.md",
        "generatedAt": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "seasons": {},
        "baselines": {},
        "managerB": {},
        "perTeam": [],
    }
    private: dict[str, Any] = {"seasons": {}}
    # per baseline/variant: lists of (season, rid, deltas)
    collected: dict[str, dict[str, list[tuple[int, int, list[float], int, float | None]]]] = {}
    mgr_rows: list[tuple[int, int]] = []
    team_rows: list[dict[str, Any]] = []

    for league in chain:
        season = int(league["season"])
        if season not in seasons:
            continue
        weeks = _season_weeks(league)
        data, priv = load_season(league, weeks, cache=cache, players_dump=dump)
        owners = priv["rosterOwners"]
        mgr_rid = next((rid for rid, name in owners.items() if name == manager_display_name), None)
        changes = classify_roster_changes(data)
        recon = reconstruct_rosters(
            data.rosters[weeks[0]], weeks[0], weeks, data.transactions, data.week_ends
        )
        idp = data.idp_ids()
        unattributed_idp = [c for c in changes if c.kind == "unattributed" and c.player_id in idp]
        from src.history.store import HISTORY_FLOOR

        floor = datetime.fromisoformat(HISTORY_FLOOR).replace(tzinfo=timezone.utc)
        dweeks = decision_weeks(data)
        dyn_available = bool(dweeks) and all(data.cutoffs[w] >= floor for w in dweeks)
        canon_probe = None
        if dyn_available:
            w0 = dweeks[0]
            probe_ids = sorted(
                p for players in data.rosters[w0].values() for p in _idp_set(data, players)
            )[:25]
            canon_probe = sum(
                1 for p in probe_ids if canonical_lookup(p, data.cutoffs[w0]) is not None
            )
        if canon_probe:
            dyn_lookup, dyn_source = canonical_lookup, "canonical_board"
        elif dyn_available:
            dyn_lookup, dyn_source = (
                idptc_lookup,
                "source_value:idpTradeCalc (vendor value, NOT canonical)",
            )
        else:
            dyn_lookup, dyn_source = None, None
        evidence["seasons"][str(season)] = {
            "scoredWeeks": weeks,
            "decisionWeeks": decision_weeks(data),
            "teams": len(data.rosters[weeks[0]]),
            "idpSlots": idp_slots(data.slots),
            "starterSlots": list(data.slots),
            "slotSource": data.slot_source,
            "bestBallVerified": data.best_ball_verified,
            "lineupQuantity": (
                "host_awarded_best_ball_points"
                if data.best_ball_verified
                else "optimal_lineup_POTENTIAL_points (host lineups were manager-set)"
            ),
            "idpScoringKeys": {
                k: v for k, v in sorted(data.scoring.items()) if k.startswith("idp_")
            },
            "cutoffSource": data.cutoff_source,
            "verification": {
                "rescoringVsHostPlayerPoints": rescoring_agreement(data),
                "lineupReproductionVsHostTeamPoints": lineup_reproduction(data),
                "forwardTransactionReconstructionVsMatchupRosters": reconstruction_agreement(
                    recon, data.rosters
                ),
                "forwardReconstructionDefendersOnly": reconstruction_agreement(
                    recon, data.rosters, only=idp
                ),
                "idpRosterChanges": sum(1 for c in changes if c.player_id in idp),
                "idpRosterChangesUnattributed": len(unattributed_idp),
                "idpRosterChangesByKind": _count(c.kind for c in changes if c.player_id in idp),
            },
            "projectionAccuracy": projection_accuracy(data),
            "projectionWeeksAvailable": sorted(w for w, p in data.projections.items() if p),
            "dynastyValueSource": dyn_source or "unavailable: before_history_boundary (2026-07-14)",
            "managerBPresent": mgr_rid is not None,
        }
        private["seasons"][str(season)] = {
            "managerRosterId": mgr_rid,
            "owners": owners,
        }
        if mgr_rid is not None:
            mgr_rows.append((season, mgr_rid))

        rids = sorted(data.rosters[weeks[0]])
        holds = {rid: simulate_hold(data, rid, changes) for rid in rids}
        actuals = {rid: simulate_actual(data, rid) for rid in rids}
        holds_full = {rid: simulate_hold_full(data, rid, changes) for rid in rids}
        for rid in rids:
            collected.setdefault("8_manager_actual", {}).setdefault("actual", []).append(
                {"season": season, "rid": rid, "deltas": _deltas(actuals[rid], holds[rid])}
            )
            collected["8_manager_actual"].setdefault("actual_vs_1b_hold_incl_offense", []).append(
                {"season": season, "rid": rid, "deltas": _deltas(actuals[rid], holds_full[rid])}
            )
            activity = streaming_activity(data, rid)
            team_rows.append(
                {
                    "season": season,
                    "_rid": rid,
                    "isManagerB": rid == mgr_rid,
                    "decisionWeeks": len(holds[rid]),
                    "holdMeanLineupPoints": statistics.fmean(r.lineup_points for r in holds[rid])
                    if holds[rid]
                    else None,
                    "actualMinusHoldMean": statistics.fmean(_deltas(actuals[rid], holds[rid]))
                    if holds[rid]
                    else None,
                    "holdMeanDefenders": _mean_size(holds[rid]),
                    "actualMeanDefenders": _mean_size(actuals[rid]),
                    "holdMeanDefendersNotPlaying": _mean_not_playing(holds[rid], data),
                    "actualMeanDefendersNotPlaying": _mean_not_playing(actuals[rid], data),
                    "idpStreamingAdds": activity["idpAdds"],
                    "idpStreamingAddsPerScoredWeek": activity["idpAdds"] / len(weeks),
                    "faabOnIdpWaiverWins": activity["faabOnIdpWaiverWins"],
                }
            )
            for name, factory in RULE_POLICIES:
                if name.startswith("6_") and dyn_lookup is None:
                    continue
                for masked in (True, False):
                    for cap in SWAP_CAPS:
                        res = simulate_policy(
                            data,
                            rid,
                            rids.index(rid),
                            factory(),
                            changes,
                            max_swaps=cap,
                            masked=masked,
                            dynasty_lookup=dyn_lookup if name.startswith("6_") else None,
                            dynasty_value_source=dyn_source,
                        )
                        variant = f"{'masked' if masked else 'unmasked'}_S{cap}"
                        collected.setdefault(name, {}).setdefault(variant, []).append(
                            {
                                "season": season,
                                "rid": rid,
                                "deltas": _deltas(res, holds[rid]),
                                "adds": sum(len(r.adds) for r in res),
                                "faab": None if any(r.faab is None for r in res) else 0.0,
                                "swaps": _swap_outcomes(res, data),
                                "dyn": _dyn_flow(res, data, dyn_lookup),
                            }
                        )
        if mgr_rid is not None:
            outcomes = move_outcomes(data, mgr_rid, changes, dynasty_lookup=dyn_lookup)
            league_outcomes = [o for rid in rids for o in move_outcomes(data, rid, changes)]
            evidence["managerB"][str(season)] = {
                "activity": {k: v for k, v in streaming_activity(data, mgr_rid).items()},
                "leagueMeanIdpStreamingAdds": statistics.fmean(
                    streaming_activity(data, rid)["idpAdds"] for rid in rids
                ),
                "moveOutcomes": _outcome_summary(outcomes),
                "leagueMoveOutcomes": _outcome_summary(league_outcomes),
                "streamedInLineupShare": _streamed_in_share(actuals[mgr_rid], holds[mgr_rid]),
            }
            private["seasons"][str(season)]["managerMoves"] = outcomes

    # ── aggregate baselines ──
    mgr_keys = set(mgr_rows)
    for name, variants in collected.items():
        evidence["baselines"][name] = {}
        for variant, rows in variants.items():
            block: dict[str, Any] = {}
            for scope in ("pooled", *[str(s) for s in seasons]):
                sel = [r for r in rows if scope == "pooled" or str(r["season"]) == scope]
                if not sel:
                    continue
                is_mgr = [(r["season"], r["rid"]) in mgr_keys for r in sel]
                clusters = [r["deltas"] for r in sel]
                flat = [v for c in clusters for v in c]
                mgr = [v for r, m in zip(sel, is_mgr) if m for v in r["deltas"]]
                cell: dict[str, Any] = {
                    "league": summarize_deltas(flat, minimum=MIN_TEAM_SEASONS, clusters=clusters),
                    "managerB": summarize_deltas(mgr, minimum=MIN_WEEKS_MANAGER),
                }
                if name != "8_manager_actual":
                    cell.update(
                        addsPerTeamWeek=(sum(r["adds"] for r in sel) / len(flat)) if flat else None,
                        managerBAdds=sum(r["adds"] for r, m in zip(sel, is_mgr) if m),
                        faabCost=(
                            0.0 if all(r["faab"] == 0.0 for r in sel) else "unknown_contested_adds"
                        ),
                        swapOutcomes=_outcome_summary([o for r in sel for o in r["swaps"]]),
                        managerBSwapOutcomes=_outcome_summary(
                            [o for r, m in zip(sel, is_mgr) if m for o in r["swaps"]]
                        ),
                        dynastyValueFlow=_merge_dyn([r["dyn"] for r in sel]),
                        managerBDynastyValueFlow=_merge_dyn(
                            [r["dyn"] for r, m in zip(sel, is_mgr) if m]
                        ),
                    )
                block[scope] = cell
            evidence["baselines"][name][variant] = block
    # manager B: actual behaviour vs each rule, paired by week (same weeks,
    # same hold reference, so the hold cancels): actual − rule per week.
    paired: dict[str, Any] = {}
    actual_rows = {
        (r["season"], r["rid"]): r["deltas"] for r in collected["8_manager_actual"]["actual"]
    }
    for name, variants in collected.items():
        if name == "8_manager_actual":
            continue
        for variant, rows in variants.items():
            for scope in ("pooled", *[str(s) for s in seasons]):
                diffs = [
                    a - b
                    for r in rows
                    if (r["season"], r["rid"]) in mgr_keys
                    and (scope == "pooled" or str(r["season"]) == scope)
                    for a, b in zip(actual_rows[(r["season"], r["rid"])], r["deltas"])
                ]
                if diffs:
                    paired.setdefault(name, {}).setdefault(variant, {})[scope] = summarize_deltas(
                        diffs, minimum=MIN_WEEKS_MANAGER
                    )
    evidence["managerBActualMinusRule"] = paired
    evidence["baselines"]["1_no_streaming_hold"] = "reference: every delta is scenario minus this"
    evidence["baselines"]["5_independent_source_consensus"] = (
        "N/A: one weekly IDP projection family available historically (Sleeper/RotoWire)"
    )
    evidence["baselines"]["7_full_dynasty_safe_optimizer"] = (
        "NOT RUN: awaiting W4 solver (src/waivers/streaming.py) via StreamingPolicy"
    )
    team_rows.sort(key=lambda r: (r["season"], r["holdMeanLineupPoints"] or 0.0))
    counters: dict[int, int] = {}
    for row in team_rows:
        counters[row["season"]] = counters.get(row["season"], 0) + 1
        row["label"] = "manager B" if row["isManagerB"] else f"T{counters[row['season']]:02d}"
        private.setdefault("teamLabels", {})[f"{row['season']}:{row['label']}"] = row.pop("_rid")
    evidence["perTeam"] = team_rows
    return evidence, private


def _mean_size(results: Sequence[WeekResult]) -> float | None:
    return statistics.fmean(len(r.idp_set) for r in results) if results else None


def _mean_not_playing(results: Sequence[WeekResult], data: SeasonData) -> float | None:
    """Defenders on the set who recorded no stat line that week (injured,
    inactive, bye) — the part of streaming that is injury replacement."""
    if not results:
        return None
    return statistics.fmean(len(r.idp_set - data.played.get(r.week, frozenset())) for r in results)


def _window_points(data: SeasonData, pid: str, week: int, horizon: int) -> float:
    return sum(data.realized(w, pid) for w in data.weeks if week <= w < week + horizon)


def _swap_outcomes(results: Sequence[WeekResult], data: SeasonData) -> list[dict[str, Any]]:
    """Each rule swap: the added vs released defender's realized points over
    the following 1 and 3 weeks (scoring only — never a decision input)."""
    out = []
    starters_by_week = {r.week: r.starters for r in results}
    for r in results:
        for add, drop in zip(r.adds, r.drops):
            out.append(
                {
                    "week": r.week,
                    "faab": 0.0,
                    "addPointsNext1": _window_points(data, add, r.week, 1),
                    "releasedPointsNext1": _window_points(data, drop, r.week, 1),
                    "addPoints": _window_points(data, add, r.week, 3),
                    "releasedPoints": _window_points(data, drop, r.week, 3),
                    "releasedCount": 1,
                    "madeLineupFirstWeek": add in starters_by_week.get(r.week, frozenset()),
                    "falsePositive": _window_points(data, add, r.week, 3)
                    < _window_points(data, drop, r.week, 3),
                    "releasedDynastyValue": None,
                }
            )
    return out


def _dyn_flow(
    results: Sequence[WeekResult], data: SeasonData, lookup: DynastyLookup | None
) -> dict[str, Any] | None:
    """Point-in-time value released vs acquired by a scenario's swaps."""
    if lookup is None:
        return None
    flow = {"releasedValued": 0, "releasedUnvalued": 0, "releasedSum": 0.0}
    flow.update(acquiredValued=0, acquiredUnvalued=0, acquiredSum=0.0)
    for r in results:
        cutoff = data.cutoffs[r.week]
        for side, ids in (("released", r.drops), ("acquired", r.adds)):
            for pid in ids:
                v = lookup(pid, cutoff)
                if v is None:
                    flow[f"{side}Unvalued"] += 1
                else:
                    flow[f"{side}Valued"] += 1
                    flow[f"{side}Sum"] += v
    return flow


def _merge_dyn(flows: Sequence[dict[str, Any] | None]) -> dict[str, Any] | None:
    present = [f for f in flows if f is not None]
    if not present:
        return None
    out = {k: sum(f[k] for f in present) for k in present[0]}
    out["netValuedSum"] = out["acquiredSum"] - out["releasedSum"]
    out["note"] = "valued players only; unvalued counts are reported, never priced at 0"
    return out


def _count(items: Iterable[str]) -> dict[str, int]:
    out: dict[str, int] = {}
    for it in items:
        out[it] = out.get(it, 0) + 1
    return dict(sorted(out.items()))


def _outcome_summary(outcomes: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    n = len(outcomes)
    paired = [o for o in outcomes if o["releasedPoints"] is not None]
    return {
        "streamingAdds": n,
        "madeLineupFirstWeekShare": (
            sum(1 for o in outcomes if o["madeLineupFirstWeek"]) / n if n else None
        ),
        "pairedWithRelease": len(paired),
        "falsePositiveShare": (
            sum(1 for o in paired if o["falsePositive"]) / len(paired) if paired else None
        ),
        "meanAddPointsNext3": statistics.fmean(o["addPoints"] for o in outcomes) if n else None,
        "meanReleasedPointsNext3": (
            statistics.fmean(o["releasedPoints"] for o in paired) if paired else None
        ),
        "pairedMeanAddPointsNext3": (
            statistics.fmean(o["addPoints"] for o in paired) if paired else None
        ),
        "pairedMeanAddMinusReleasedNext1": (
            statistics.fmean(o["addPointsNext1"] - o["releasedPointsNext1"] for o in paired)
            if paired
            else None
        ),
        "faabSpent": sum(o["faab"] or 0.0 for o in outcomes),
        "releasedDynastyValue": _sum_dyn(outcomes),
    }


def _sum_dyn(outcomes: Sequence[Mapping[str, Any]]) -> dict[str, Any] | None:
    blocks = [o["releasedDynastyValue"] for o in outcomes if o.get("releasedDynastyValue")]
    if not blocks:
        return None
    return {
        "releasedValued": sum(b["valued"] for b in blocks),
        "releasedUnvalued": sum(b["unvalued"] for b in blocks),
        "releasedSum": sum(b["sum"] for b in blocks),
        "acquiredValued": sum(b["acquiredValued"] for b in blocks),
        "acquiredSum": sum(b["acquiredSum"] for b in blocks),
    }


def _streamed_in_share(actual: Sequence[WeekResult], hold: Sequence[WeekResult]) -> dict[str, Any]:
    """Of the actual DEFENDER starters, how many were not in the hold set
    (i.e. arrived by waiver / free-agent streaming)."""
    hold_by = {r.week: r.idp_set for r in hold}
    starters = streamed = 0
    for r in actual:
        idp_starters = r.starters & r.idp_set
        starters += len(idp_starters)
        streamed += len(idp_starters - hold_by.get(r.week, frozenset()))
    return {
        "starterSlotsFilled": starters,
        "filledByStreamedPlayers": streamed,
        "share": (streamed / starters) if starters else None,
    }


def _rounded(obj: Any, nd: int = 3) -> Any:
    if isinstance(obj, float):
        return round(obj, nd)
    if isinstance(obj, dict):
        return {k: _rounded(v, nd) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_rounded(v, nd) for v in obj]
    return obj


def main(argv: Sequence[str] | None = None) -> int:
    import argparse

    parser = argparse.ArgumentParser(description="IDP streaming backtest (research only)")
    parser.add_argument("--manager", required=True, help="display name of the studied manager")
    parser.add_argument("--seasons", default="2025,2026")
    parser.add_argument("--ledger", type=Path, default=RESEARCH_DIR / "temporal_ledger.sqlite")
    parser.add_argument(
        "--evidence-out", type=Path, default=EVIDENCE_DIR / "results_2026-10-29.json"
    )
    args = parser.parse_args(argv)
    evidence, private = run_backtest(
        manager_display_name=args.manager,
        seasons=tuple(int(s) for s in args.seasons.split(",")),
        ledger_path=args.ledger if args.ledger and args.ledger.exists() else None,
    )
    blob = json.dumps(_rounded(evidence), indent=1, sort_keys=True, default=str)
    if args.manager in blob:
        raise RuntimeError("privacy guard: manager name leaked into evidence")
    args.evidence_out.parent.mkdir(parents=True, exist_ok=True)
    args.evidence_out.write_text(blob + "\n", encoding="utf-8")
    RESEARCH_DIR.mkdir(parents=True, exist_ok=True)
    (RESEARCH_DIR / "private_detail.json").write_text(
        json.dumps(private, indent=1, sort_keys=True, default=str), encoding="utf-8"
    )
    print(f"evidence -> {args.evidence_out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
