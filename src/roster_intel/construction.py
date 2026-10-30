"""Roster Construction V1: where a roster's lineup points and dynasty value sit.

Owner directive 2026-10-30 (PHASE 3). Spec:
``docs/OWNER_FEATURE_ADDENDUM_2026-08-29_BEST_BALL_ROSTER_UTILITY.md`` §§9-20 and
``docs/OWNER_PRODUCT_BACKLOG_SPEC.md`` FC-01 / FC-02 / FC-06.

The question this module answers, for every team in one league-season:

* how many fantasy points each POSITION GROUP contributed to the team's legal
  optimal weekly lineup, and how that ranks in the league;
* how much canonical dynasty value the team holds at each position (read only);
* per player: weeks owned, optimal starts while owned, starts on a stated
  counterfactual roster, and weeks above the league's empirical starter standard;
* depth and coverage facts, and evidence-backed diagnoses that may say NO ACTION.

Nothing here is a second owner
==============================

===================================  ==============================================
question                             owner consumed
===================================  ==============================================
legal optimal lineup                 ``src.ros.lineup.solve_optimal_assignment``
                                     (``OBJECTIVE_REALIZED_POINTS``; one solver)
slot eligibility / position family   ``src.ros.lineup`` (``precompute_slot_eligibility``,
                                     ``slot_eligible_positions``, ``lineup_position``)
weekly rosters as owned + points     ``src.public_league.player_impact.season_team_weeks``
                                     (Sleeper matchups: the host's own record)
conditional marginal contribution    ``player_impact`` ``gameChangerPoints``
                                     (L(R) - L(R without p)); consumed, not recomputed
canonical dynasty value              ``rankDerivedValue`` from the live contract,
                                     read only; this module never writes it
competitive posture                  ``src.roster_intel.window`` via the caller
===================================  ==============================================

Invariants
==========
* **Missing is never zero.**  A player with no recorded points in a week is
  ``unobserved``: the solver cannot seat him, he is out of every denominator for
  that week, and a team-week whose optimum cannot be proven is excluded with a
  named reason.  The host's own recorded ``0.0`` is a real value (and is
  labelled as indistinguishable from a bye or inactive week).
* **One lineup solver.**  Every number that depends on a lineup comes from
  ``solve_optimal_assignment``.  There is no per-position count or greedy.
* **No future leakage.**  A week's lineup, starter standard and startability read
  only that week's data.  The counterfactual is labelled ex post.
* **No value write-back.**  ``rankDerivedValue`` is summed for display and never
  returned under a canonical field name or fed back into anything.
* **Diagnoses carry evidence and may be NO_ACTION.**  No diagnosis names an add,
  a drop or a trade.

Pure: no I/O, no clock, no network.  Deterministic for identical inputs.
"""

from __future__ import annotations

import math
from collections import defaultdict
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any

from src.ros.lineup import (
    OBJECTIVE_REALIZED_POINTS,
    RosterPlayer,
    lineup_position,
    ordered_positions,
    precompute_slot_eligibility,
    slot_eligible_positions,
    solve_optimal_assignment,
)

SCHEMA_VERSION = "roster_construction.v1"
METHOD_VERSION = "rc_v1"
FLAG = "roster_construction"

LINEUP_BEST_BALL = "best_ball"
LINEUP_MANAGED = "managed"
LINEUP_UNVERIFIED = "unverified"

#: What the production numbers measure, per lineup mode.
BASIS_HOST_BEST_BALL = "host_best_ball_optimal"
BASIS_HYPOTHETICAL = "hypothetical_optimal"

# Team-week exclusion reasons.
X_CONTRADICTED = "contradicted_settings"
X_HOST_MISMATCH = "host_score_mismatch"
X_POINTS_INCOMPLETE = "roster_points_incomplete"
X_SLOTS_UNKNOWN = "starter_slots_unknown"

PARITY_REPRODUCED = "host_score_reproduced"
PARITY_UNVERIFIED = "no_host_score_complete_pool"
PARITY_NOT_APPLICABLE = "not_best_ball"

SCENARIO_END_ROSTER = "end_roster_plus_player"

STATUS_FIRED = "fired"
STATUS_NOT_FIRED = "not_fired"
STATUS_NOT_EVALUATED = "not_evaluated"
VERDICT_REVIEW = "REVIEW"
VERDICT_NO_ACTION = "NO_ACTION"

_ROUND = 2


def _r(x: float) -> float:
    return round(float(x), _ROUND)


# ── inputs ───────────────────────────────────────────────────────────────
@dataclass(frozen=True)
class PlayerMeta:
    """Slot eligibility and grouping for one player (host directory)."""

    position: str
    fantasy_positions: tuple[str, ...] = ()
    name: str = ""


@dataclass(frozen=True)
class TeamWeekIn:
    """One team's finished week as the host recorded it."""

    roster_id: int
    roster: tuple[str, ...]
    points: Mapping[str, float]
    counted: tuple[str, ...] = ()
    score: float | None = None
    owner_id: str = ""


@dataclass(frozen=True)
class SeasonInput:
    season: str
    slots: tuple[str, ...]
    slot_source: str | None
    lineup_mode: str
    weeks: Mapping[int, Sequence[TeamWeekIn]]
    players: Mapping[str, PlayerMeta]
    excluded_weeks: Sequence[Mapping[str, Any]] = ()
    contradicted: Mapping[int, Sequence[str]] = field(default_factory=dict)
    regular_weeks: frozenset[int] = frozenset()
    include_playoffs: bool = False
    roster_limit: int | None = None
    team_labels: Mapping[int, str] = field(default_factory=dict)
    #: ``(playerId, rosterId, week) -> {"value": float|None, "reason": str|None}``
    marginal: Mapping[tuple[str, int, int], Mapping[str, Any]] = field(default_factory=dict)
    #: Why marginal contribution is unavailable league-wide (None = consult per record).
    marginal_unavailable_reason: str | None = None


@dataclass(frozen=True)
class ValuePlayer:
    player_id: str
    name: str
    position: str
    value: float | None
    age: float | None = None
    injury: str | None = None


@dataclass(frozen=True)
class ValueInput:
    available: bool
    reason: str | None = None
    as_of: str | None = None
    teams: Mapping[int, Sequence[ValuePlayer]] = field(default_factory=dict)


# ── helpers ──────────────────────────────────────────────────────────────
def group_of(meta: PlayerMeta | None) -> str:
    """Base position family a player's points are attributed to."""
    if meta is None or not meta.position:
        return ""
    return lineup_position(meta.position)


def position_groups(slots: Sequence[str]) -> tuple[str, ...]:
    """Every base family some configured slot can seat, in lineup-card order.

    FLEX is never a group: a FLEX slot contributes its eligible families.
    """
    fams = {lineup_position(p) for s in slots for p in slot_eligible_positions(s)}
    return ordered_positions(f for f in fams if f)


def _roster_player(pid: str, meta: PlayerMeta | None, pts: float | None) -> RosterPlayer:
    meta = meta or PlayerMeta(position="")
    return RosterPlayer(
        player_id=pid,
        canonical_name=meta.name or pid,
        position=meta.position,
        ros_value=None if pts is None else float(pts),
        fantasy_positions=tuple(meta.fantasy_positions),
    )


def _solve(pool: list[RosterPlayer], slots: list[str], elig) -> dict[int, RosterPlayer]:
    return solve_optimal_assignment(
        pool, slots, precomputed_eligibility=elig, objective=OBJECTIVE_REALIZED_POINTS
    )


def _score(assignment: Mapping[int, RosterPlayer]) -> float:
    return sum(float(p.ros_value) for p in assignment.values())


def rank_table(values: Mapping[int, float | None], *, higher_is_better: bool = True) -> dict:
    """Competition ranks (ties share a rank) over the KNOWN values only."""
    known = {k: float(v) for k, v in values.items() if v is not None}
    n = len(known)
    vals = sorted(known.values())
    out: dict[int, dict[str, Any]] = {}
    for k in values:
        v = known.get(k)
        if v is None:
            out[k] = {"rank": None, "of": n, "percentile": None, "tiedWith": 0}
            continue
        better = sum(1 for o in known.values() if (o > v if higher_is_better else o < v))
        rank = 1 + better
        out[k] = {
            "rank": rank,
            "of": n,
            "percentile": round((n - rank) / (n - 1), 4) if n > 1 else None,
            "tiedWith": sum(1 for o in known.values() if o == v) - 1,
        }
    summary = {
        "teamsCompared": n,
        "leagueMean": _r(sum(vals) / n) if n else None,
        "leagueMedian": _r(_median(vals)) if n else None,
    }
    return {"byTeam": out, "summary": summary}


def _median(vals: Sequence[float]) -> float:
    s = sorted(vals)
    m = len(s) // 2
    return s[m] if len(s) % 2 else (s[m - 1] + s[m]) / 2


def _quantile(vals: Sequence[float], q: float) -> float | None:
    s = sorted(vals)
    if not s:
        return None
    pos = (len(s) - 1) * q
    lo, hi = math.floor(pos), math.ceil(pos)
    return s[lo] + (s[hi] - s[lo]) * (pos - lo)


def _spells(weeks: Sequence[int], included: Sequence[int]) -> list[dict[str, int]]:
    """Contiguous ownership spells over the INCLUDED week sequence."""
    order = {w: i for i, w in enumerate(included)}
    out: list[dict[str, int]] = []
    for w in sorted(weeks):
        if out and order.get(w, -2) == order.get(out[-1]["toWeek"], -9) + 1:
            out[-1]["toWeek"] = w
        else:
            out.append({"fromWeek": w, "toWeek": w})
    return out


# ── one team-week ────────────────────────────────────────────────────────
@dataclass
class TeamWeekSolution:
    roster_id: int
    week: int
    valid: bool
    reason: str | None
    parity: str | None
    score: float | None
    host_score: float | None
    roster: tuple[str, ...]
    points: Mapping[str, float]
    #: [(slotIndex, slotLabel, playerId, points)]
    assigned: list[tuple[int, str, str, float]]
    unfilled_slots: list[str]
    unobserved: tuple[str, ...]
    counted: tuple[str, ...]
    pool: list[RosterPlayer] = field(default_factory=list, repr=False)
    elig: Any = field(default=None, repr=False)

    @property
    def assigned_ids(self) -> frozenset[str]:
        return frozenset(pid for _i, _s, pid, _p in self.assigned)


def solve_team_week(
    team: TeamWeekIn,
    week: int,
    si: SeasonInput,
    *,
    tolerance: float,
) -> TeamWeekSolution:
    slots = list(si.slots)
    pids = sorted(set(team.roster) | set(team.counted))
    unobserved = tuple(p for p in pids if team.points.get(p) is None)
    base = dict(
        roster_id=team.roster_id,
        week=week,
        host_score=None if team.score is None else float(team.score),
        roster=tuple(sorted(set(team.roster))),
        points=team.points,
        unobserved=unobserved,
        counted=tuple(team.counted),
    )
    if week in si.contradicted:
        return TeamWeekSolution(
            valid=False,
            reason=X_CONTRADICTED,
            parity=None,
            score=None,
            assigned=[],
            unfilled_slots=[],
            **base,
        )
    if not slots:
        return TeamWeekSolution(
            valid=False,
            reason=X_SLOTS_UNKNOWN,
            parity=None,
            score=None,
            assigned=[],
            unfilled_slots=[],
            **base,
        )
    pool = [_roster_player(p, si.players.get(p), team.points.get(p)) for p in pids]
    elig = precompute_slot_eligibility(pool, slots)
    assignment = _solve(pool, slots, elig)
    score = _score(assignment)
    assigned = sorted((i, slots[i], p.player_id, float(p.ros_value)) for i, p in assignment.items())
    unfilled = [slots[i] for i in range(len(slots)) if i not in assignment]
    if si.lineup_mode == LINEUP_BEST_BALL and team.score is not None:
        ok = abs(score - float(team.score)) <= tolerance
        valid, reason = ok, (None if ok else X_HOST_MISMATCH)
        parity = PARITY_REPRODUCED if ok else X_HOST_MISMATCH
    elif not unobserved:
        valid, reason = True, None
        parity = PARITY_UNVERIFIED if si.lineup_mode == LINEUP_BEST_BALL else PARITY_NOT_APPLICABLE
    else:
        valid, reason, parity = False, X_POINTS_INCOMPLETE, None
    return TeamWeekSolution(
        valid=valid,
        reason=reason,
        parity=parity,
        score=_r(score),
        assigned=assigned,
        unfilled_slots=unfilled,
        pool=pool,
        elig=elig,
        **base,
    )


def _resolve_without(sol: TeamWeekSolution, drop: set[str], slots: list[str]) -> float:
    pool = [p for p in sol.pool if p.player_id not in drop]
    return _score(_solve(pool, slots, sol.elig))


# ── the league-season ────────────────────────────────────────────────────
@dataclass
class LeagueSeason:
    si: SeasonInput
    groups: tuple[str, ...]
    included_weeks: list[int]
    solutions: dict[int, dict[int, TeamWeekSolution]]  # week -> rosterId -> solution
    team_ids: list[int]
    thresholds: dict[int, dict[str, dict[str, Any]]]  # week -> group -> {starters, threshold}
    league_points: dict[str, dict[int, float]]  # pid -> week -> points (any roster)
    production: dict[int, dict[str, dict[str, Any]]]  # rid -> group -> aggregates
    depth: dict[int, dict[str, dict[str, Any]]]
    team_stats: dict[int, dict[str, Any]]
    priors: Mapping[str, Any]


def compute_league_season(si: SeasonInput, priors: Mapping[str, Any]) -> LeagueSeason:
    """Solve every team-week once and aggregate the league-wide quantities."""
    tol = float(priors.get("hostScoreTolerance", 0.011))
    slots = list(si.slots)
    groups = position_groups(slots)
    included = sorted(si.weeks)
    solutions: dict[int, dict[int, TeamWeekSolution]] = {}
    league_points: dict[str, dict[int, float]] = defaultdict(dict)
    team_ids: set[int] = set()
    for wk in included:
        solutions[wk] = {}
        for team in sorted(si.weeks[wk], key=lambda t: t.roster_id):
            team_ids.add(team.roster_id)
            solutions[wk][team.roster_id] = solve_team_week(team, wk, si, tolerance=tol)
            if wk not in si.contradicted:
                for pid, pts in team.points.items():
                    if pts is not None:
                        league_points[pid][wk] = float(pts)

    # Empirical league starter standard, per week and group (same-week data only).
    thresholds: dict[int, dict[str, dict[str, Any]]] = {}
    for wk in included:
        valid = [s for s in solutions[wk].values() if s.valid]
        per_group: dict[str, dict[str, Any]] = {}
        if not valid:
            thresholds[wk] = {g: {"starters": None, "threshold": None, "teams": 0} for g in groups}
            continue
        started = defaultdict(int)
        pool_pts: dict[str, list[float]] = defaultdict(list)
        for s in valid:
            for _i, _slot, pid, _p in s.assigned:
                started[group_of(si.players.get(pid))] += 1
            for pid in s.roster:
                pts = s.points.get(pid)
                if pts is not None:
                    pool_pts[group_of(si.players.get(pid))].append(float(pts))
        for g in groups:
            n = started.get(g, 0)
            ranked = sorted(pool_pts.get(g, []), reverse=True)
            thr = ranked[n - 1] if 0 < n <= len(ranked) else None
            per_group[g] = {"starters": n, "threshold": thr, "teams": len(valid)}
        thresholds[wk] = per_group

    production: dict[int, dict[str, dict[str, Any]]] = {}
    depth: dict[int, dict[str, dict[str, Any]]] = {}
    team_stats: dict[int, dict[str, Any]] = {}
    top_n = int(priors.get("topContributors", 3))
    for rid in sorted(team_ids):
        prod = {
            g: {
                "points": 0.0,
                "appearances": 0,
                "contributors": defaultdict(lambda: [0.0, 0]),
                "slotAllocation": defaultdict(lambda: [0, 0.0]),
                "weekly": [],
                "observed": 0.0,
            }
            for g in groups
        }
        dep = {
            g: {
                "holesDedicated": [],
                "zeroFlexStarts": 0,
                "insurance": [],
                "redundantPoints": 0.0,
                "redundantStartableWeeks": 0,
                "leaveOut": 0.0,
                "leaveOutWeeks": 0,
                "rostered": [],
            }
            for g in groups
        }
        valid_weeks: list[int] = []
        excluded: list[dict[str, Any]] = []
        observed_ok_weeks = 0
        flex_unfilled = 0
        over_limit: list[int] = []
        parity: dict[str, int] = defaultdict(int)
        for wk in included:
            sol = solutions[wk].get(rid)
            if sol is None:
                for g in groups:
                    prod[g]["weekly"].append({"week": wk, "points": None, "reason": "no_matchup"})
                continue
            if si.roster_limit is not None and len(sol.roster) > si.roster_limit:
                over_limit.append(wk)
            if not sol.valid:
                excluded.append({"week": wk, "reason": sol.reason})
                for g in groups:
                    prod[g]["weekly"].append({"week": wk, "points": None, "reason": sol.reason})
                continue
            valid_weeks.append(wk)
            parity[sol.parity or "unknown"] += 1
            week_pts = defaultdict(float)
            for _i, slot, pid, pts in sol.assigned:
                g = group_of(si.players.get(pid))
                if g not in prod:
                    continue
                prod[g]["points"] += pts
                prod[g]["appearances"] += 1
                c = prod[g]["contributors"][pid]
                c[0] += pts
                c[1] += 1
                sa = prod[g]["slotAllocation"][slot]
                sa[0] += 1
                sa[1] += pts
                week_pts[g] += pts
                if slot == g:
                    if pts == 0.0:
                        dep[g]["holesDedicated"].append(wk)
                elif pts == 0.0:
                    dep[g]["zeroFlexStarts"] += 1
            for slot in sol.unfilled_slots:
                if slot in dep:
                    dep[slot]["holesDedicated"].append(wk)
                else:
                    flex_unfilled += 1
            for g in groups:
                prod[g]["weekly"].append({"week": wk, "points": _r(week_pts.get(g, 0.0))})
            # Observed submitted lineup (managed leagues): the host's counted players.
            if si.lineup_mode != LINEUP_BEST_BALL and sol.counted:
                if all(sol.points.get(p) is not None for p in sol.counted):
                    observed_ok_weeks += 1
                    for pid in sol.counted:
                        g = group_of(si.players.get(pid))
                        if g in prod:
                            prod[g]["observed"] += float(sol.points[pid])
            # Depth: per group.
            assigned_ids = sol.assigned_ids
            thr = thresholds[wk]
            by_group_roster: dict[str, list[str]] = defaultdict(list)
            for pid in sol.roster:
                by_group_roster[group_of(si.players.get(pid))].append(pid)
            base_score = float(sol.score)  # valid => solved
            for g in groups:
                members = by_group_roster.get(g, [])
                dep[g]["rostered"].append(len(members))
                for pid in members:
                    pts = sol.points.get(pid)
                    if pts is None or pid in assigned_ids:
                        continue
                    dep[g]["redundantPoints"] += float(pts)
                    t = thr.get(g, {}).get("threshold")
                    if t is not None and float(pts) >= t:
                        dep[g]["redundantStartableWeeks"] += 1
                starters = [
                    (pts, pid)
                    for _i, _s, pid, pts in sol.assigned
                    if group_of(si.players.get(pid)) == g
                ]
                if starters:
                    without_all = _resolve_without(sol, set(members), list(si.slots))
                    dep[g]["leaveOut"] += base_score - without_all
                    dep[g]["leaveOutWeeks"] += 1
                    top_pts, top_pid = max(starters, key=lambda t: (t[0], t[1]))
                    if top_pts > 0:
                        loss = base_score - _resolve_without(sol, {top_pid}, list(si.slots))
                        dep[g]["insurance"].append(1.0 - loss / top_pts)
        prod_out: dict[str, dict[str, Any]] = {}
        for g in groups:
            p = prod[g]
            contribs = sorted(p["contributors"].items(), key=lambda kv: (-kv[1][0], kv[0]))
            prod_out[g] = {
                "points": _r(p["points"]),
                "ppg": _r(p["points"] / len(valid_weeks)) if valid_weeks else None,
                "appearances": p["appearances"],
                "distinctContributors": len(contribs),
                "topContributors": [
                    {"playerId": pid, "points": _r(v[0]), "starts": v[1]}
                    for pid, v in contribs[:top_n]
                ],
                "slotAllocation": {
                    slot: {"starts": v[0], "points": _r(v[1])}
                    for slot, v in sorted(p["slotAllocation"].items())
                },
                "weekly": p["weekly"],
                "observedSubmittedPoints": (
                    _r(p["observed"])
                    if si.lineup_mode != LINEUP_BEST_BALL and observed_ok_weeks
                    else None
                ),
            }
        dep_out: dict[str, dict[str, Any]] = {}
        dedicated = defaultdict(int)
        for s in si.slots:
            dedicated[s] += 1
        for g in groups:
            d = dep[g]
            ins = d["insurance"]
            dep_out[g] = {
                "holes": {
                    "dedicated": len(d["holesDedicated"]),
                    "weeks": sorted(set(d["holesDedicated"])),
                    "zeroPointFlexStarts": d["zeroFlexStarts"],
                },
                "depthInsurance": {
                    "meanRatio": round(sum(ins) / len(ins), 4) if ins else None,
                    "n": len(ins),
                },
                "redundantPoints": _r(d["redundantPoints"]),
                "redundantStartableWeeks": d["redundantStartableWeeks"],
                "positionLeaveOutPoints": _r(d["leaveOut"]) if d["leaveOutWeeks"] else None,
                "rosteredPerStartingSlot": (
                    round(sum(d["rostered"]) / len(d["rostered"]) / dedicated[g], 3)
                    if d["rostered"] and dedicated.get(g)
                    else None
                ),
            }
        production[rid] = prod_out
        depth[rid] = dep_out
        team_stats[rid] = {
            "validWeeks": valid_weeks,
            "excludedWeeks": excluded,
            "flexUnfilledSlotWeeks": flex_unfilled,
            "rosterOverLimitWeeks": over_limit,
            "observedSubmittedWeeks": observed_ok_weeks,
            "lineupParity": dict(sorted(parity.items())),
        }
    return LeagueSeason(
        si=si,
        groups=groups,
        included_weeks=included,
        solutions=solutions,
        team_ids=sorted(team_ids),
        thresholds=thresholds,
        league_points=dict(league_points),
        production=production,
        depth=depth,
        team_stats=team_stats,
        priors=priors,
    )


# ── player ledger ────────────────────────────────────────────────────────
def player_ledger(ls: LeagueSeason, rid: int, pid: str) -> dict[str, Any]:
    """Owned weeks, optimal starts while owned, league startability, marginal."""
    si = ls.si
    owned: list[int] = []
    eligible = 0
    starts = 0
    started_pts = 0.0
    zero_weeks = 0
    unobserved = 0
    invalid = 0
    marg_sum = 0.0
    marg_known = 0
    marg_reasons: dict[str, int] = defaultdict(int)
    for wk in ls.included_weeks:
        sol = ls.solutions[wk].get(rid)
        if sol is None or pid not in sol.roster:
            continue
        owned.append(wk)
        pts = sol.points.get(pid)
        if not sol.valid:
            invalid += 1
            continue
        if pts is None:
            unobserved += 1
            continue
        eligible += 1
        if float(pts) == 0.0:
            zero_weeks += 1
        if pid in sol.assigned_ids:
            starts += 1
            started_pts += float(pts)
        rec = si.marginal.get((pid, rid, wk))
        if si.marginal_unavailable_reason:
            marg_reasons[si.marginal_unavailable_reason] += 1
        elif rec is None:
            marg_reasons["no_marginal_record"] += 1
        elif rec.get("value") is None:
            marg_reasons[str(rec.get("reason") or "unknown")] += 1
        else:
            marg_sum += float(rec["value"])
            marg_known += 1
    # League-relative startability over every week the player had known points.
    stw = 0
    stw_of = 0
    for wk, pts in sorted(ls.league_points.get(pid, {}).items()):
        g = group_of(si.players.get(pid))
        t = ls.thresholds.get(wk, {}).get(g, {}).get("threshold")
        if t is None:
            continue
        stw_of += 1
        if pts >= t:
            stw += 1
    return {
        "ownedWeeks": len(owned),
        "ownershipSpells": _spells(owned, ls.included_weeks),
        "eligibleOwnedWeeks": eligible,
        "starts": {"value": starts, "of": eligible},
        "startRate": round(starts / eligible, 4) if eligible else None,
        "startedPoints": _r(started_pts),
        "zeroPointWeeks": zero_weeks,
        "unobservedWeeks": unobserved,
        "excludedTeamWeeks": invalid,
        "marginalPoints": {
            "value": _r(marg_sum) if marg_known else None,
            "knownWeeks": marg_known,
            "unavailableWeeks": dict(sorted(marg_reasons.items())),
            "source": "player_impact.gameChangerPoints",
        },
        "leagueStartable": {"value": stw, "of": stw_of, "poolScope": "rostered"},
    }


_UNKNOWN_HIGH = 1.0e6


def hypothetical_starts(
    ls: LeagueSeason, rid: int, candidates: Iterable[str]
) -> tuple[dict[str, dict[str, Any]], dict[str, Any]]:
    """Scenario ``end_roster_plus_player``: R* = the team's roster in its last
    included week; for each week, would the player enter the optimum of R* + {p}?

    A replayed teammate with no recorded points that week (on no league roster)
    is UNKNOWN, never zero.  The week is still decided when the answer does not
    depend on the unknowns: the optimum is monotone, so the player is
    DETERMINED to enter if he enters even with every unknown teammate at an
    unbeatable score, and DETERMINED not to if he misses even with every
    unknown teammate absent.  Otherwise the week is undetermined and excluded.
    """
    si = ls.si
    slots = list(si.slots)
    end_week = None
    for wk in reversed(ls.included_weeks):
        if rid in ls.solutions[wk]:
            end_week = wk
            break
    cands = sorted(set(candidates))
    meta = {
        "scenario": SCENARIO_END_ROSTER,
        "endRosterWeek": end_week,
        "expost": True,
        "assumptions": [
            "The team's roster in its last included week is replayed across every "
            "included week, plus the player being asked about.",
            "Uses realized points (ex post): this is not a decision evaluation.",
            "No roster cap, transaction cost or waiver competition is modelled.",
            "A replayed teammate with no recorded points that week is unknown, not zero; "
            "a week counts only when the answer is the same whatever he would have scored.",
        ],
        "weeksWithUnknownTeammates": [],
    }
    out = {
        pid: {"value": 0, "of": 0, "undeterminedWeeksExcluded": 0, "unobservedWeeksExcluded": 0}
        for pid in cands
    }
    if end_week is None or not slots:
        for pid in cands:
            out[pid] = {"value": None, "of": 0, "reason": "no_end_roster"}
        return out, meta
    r_star = sorted(ls.solutions[end_week][rid].roster)
    universe = sorted(set(r_star) | set(cands))
    proto = [_roster_player(p, si.players.get(p), 0.0) for p in universe]
    elig = precompute_slot_eligibility(proto, slots)
    lp = ls.league_points
    for wk in ls.included_weeks:
        if wk in si.contradicted:
            continue
        star_pts = {p: lp.get(p, {}).get(wk) for p in r_star}
        unknown = sorted(p for p, v in star_pts.items() if v is None)
        if unknown:
            meta["weeksWithUnknownTeammates"].append({"week": wk, "unknown": len(unknown)})
        known_pool = [
            _roster_player(p, si.players.get(p), v) for p, v in star_pts.items() if v is not None
        ]
        high_pool = known_pool + [
            _roster_player(p, si.players.get(p), _UNKNOWN_HIGH) for p in unknown
        ]
        cache: dict[str, frozenset[str]] = {}

        def _ids(pool: list[RosterPlayer], key: str) -> frozenset[str]:
            if key not in cache:
                cache[key] = frozenset(x.player_id for x in _solve(pool, slots, elig).values())
            return cache[key]

        for pid in cands:
            ppts = lp.get(pid, {}).get(wk)
            if ppts is None:
                out[pid]["unobservedWeeksExcluded"] += 1
                continue
            if pid in star_pts:
                lo = pid in _ids(high_pool, "high")
                hi = pid in _ids(known_pool, "known")
            else:
                me = _roster_player(pid, si.players.get(pid), ppts)
                lo = pid in frozenset(
                    x.player_id for x in _solve(high_pool + [me], slots, elig).values()
                )
                hi = (
                    lo
                    if not unknown
                    else pid
                    in frozenset(
                        x.player_id for x in _solve(known_pool + [me], slots, elig).values()
                    )
                )
            if lo == hi:
                out[pid]["of"] += 1
                out[pid]["value"] += int(lo)
            else:
                out[pid]["undeterminedWeeksExcluded"] += 1
    return out, meta


# ── value block ──────────────────────────────────────────────────────────
def positional_value(vi: ValueInput, groups: Sequence[str]) -> dict[str, Any]:
    """Σ rankDerivedValue by position per team (read only), with ranks."""
    if not vi.available:
        return {"available": False, "reason": vi.reason}
    per_team: dict[int, dict[str, dict[str, Any]]] = {}
    for rid, players in vi.teams.items():
        rows: dict[str, dict[str, Any]] = {}
        for g in groups:
            members = [p for p in players if p.position == g]
            priced = [p for p in members if p.value is not None]
            vals = sorted((float(p.value) for p in priced), reverse=True)
            total = sum(vals)
            rows[g] = {
                "total": _r(total) if priced else (0.0 if not members else None),
                "pricedCount": len(priced),
                "unpricedCount": len(members) - len(priced),
                "unpricedIds": sorted(p.player_id for p in members if p.value is None),
                "top1Share": round(vals[0] / total, 4) if total > 0 else None,
                "hhi": round(sum((v / total) ** 2 for v in vals), 4) if total > 0 else None,
            }
        per_team[rid] = rows
    ranks = {g: rank_table({rid: per_team[rid][g]["total"] for rid in per_team}) for g in groups}
    return {"available": True, "asOf": vi.as_of, "perTeam": per_team, "ranks": ranks}


# ── tags + diagnoses ─────────────────────────────────────────────────────
def player_tags(
    ledger: Mapping[str, Any], vp: ValuePlayer | None, group: str, priors: Mapping[str, Any]
) -> list[str]:
    tags: list[str] = []
    if vp is not None and vp.injury:
        tags.append("injured")
    rate = ledger.get("startRate")
    owned_ok = ledger.get("eligibleOwnedWeeks", 0) >= int(priors.get("minOwnedWeeks", 4))
    age = vp.age if vp is not None else None
    dev_age = (priors.get("developmentalMaxAge") or {}).get(group)
    vet_age = (priors.get("veteranMinAge") or {}).get(group)
    low = rate is not None and rate < float(priors.get("lowContributionStartRate", 0.25))
    if owned_ok and low:
        tags.append("low_contribution")
    if age is not None and dev_age is not None and age <= dev_age and (low or rate is None):
        tags.append("developmental")
    if (
        age is not None
        and vet_age is not None
        and age >= vet_age
        and rate is not None
        and rate >= float(priors.get("productiveStartRate", 0.5))
    ):
        tags.append("productive_veteran")
    return tags


def _q(n: int, priors: Mapping[str, Any]) -> int:
    return max(1, math.ceil(n * float(priors.get("quartileFraction", 0.25))))


def diagnose(
    ls: LeagueSeason,
    rid: int,
    value: Mapping[str, Any],
    players: Sequence[Mapping[str, Any]],
    posture: Mapping[str, Any] | None,
) -> dict[str, Any]:
    """Evidence-backed construction diagnoses.  Never a transaction."""
    priors = ls.priors
    prod_ranks = {
        g: rank_table(
            {
                t: ls.production[t][g]["points"]
                for t in ls.production
                if ls.team_stats[t]["validWeeks"]
            }
        )
        for g in ls.groups
    }
    out: list[dict[str, Any]] = []
    by_group_players: dict[str, list[Mapping[str, Any]]] = defaultdict(list)
    for p in players:
        by_group_players[p["position"]].append(p)

    def _d(rule, g, status, verdict=None, evidence=None, explanation="", reason=None):
        out.append(
            {
                "rule": rule,
                "position": g,
                "status": status,
                "verdict": verdict,
                "evidence": evidence or {},
                "explanation": explanation,
                "notEvaluatedReason": reason,
            }
        )

    team_valid = bool(ls.team_stats.get(rid, {}).get("validWeeks"))
    for g in ls.groups:
        pr = prod_ranks[g]["byTeam"].get(rid, {})
        if not value.get("available"):
            _d("RC-D1", g, STATUS_NOT_EVALUATED, reason=f"value_unavailable:{value.get('reason')}")
        elif not team_valid or pr.get("rank") is None or rid not in value["perTeam"]:
            _d("RC-D1", g, STATUS_NOT_EVALUATED, reason="insufficient_production_or_value")
        else:
            vr = value["ranks"][g]["byTeam"].get(rid, {})
            n_p, n_v = pr["of"], vr["of"]
            if vr.get("rank") is None:
                _d("RC-D1", g, STATUS_NOT_EVALUATED, reason="position_value_unknown")
            elif vr["rank"] <= _q(n_v, priors) and pr["rank"] >= n_p - _q(n_p, priors) + 1:
                holders = sorted(
                    (p for p in by_group_players[g] if p.get("dynastyValue") is not None),
                    key=lambda p: -float(p["dynastyValue"]),
                )[:3]
                explained: list[str] = []
                if holders:
                    top = holders[0]
                    tags = set(top.get("tags", []))
                    if "injured" in tags:
                        explained.append("injured")
                    if "developmental" in tags:
                        explained.append("developmental")
                    if top["eligibleOwnedWeeks"] < int(priors.get("minOwnedWeeks", 4)):
                        explained.append("owned_too_briefly_to_judge")
                ev = {
                    "valueRank": [vr["rank"], n_v],
                    "productionRank": [pr["rank"], n_p],
                    "explainedBy": explained,
                    "holders": [
                        {
                            "playerId": p["playerId"],
                            "dynastyValue": p["dynastyValue"],
                            "starts": p.get("starts"),
                            "tags": p.get("tags", []),
                        }
                        for p in holders
                    ],
                }
                if explained:
                    _d(
                        "RC-D1",
                        g,
                        STATUS_FIRED,
                        VERDICT_NO_ACTION,
                        ev,
                        f"{g} value rank {vr['rank']}/{n_v} but production rank "
                        f"{pr['rank']}/{n_p}: the top {g} value holder is "
                        f"{' and '.join(e.replace('_', ' ') for e in explained)}. "
                        "This gap is expected and needs no action.",
                    )
                else:
                    _d(
                        "RC-D1",
                        g,
                        STATUS_FIRED,
                        VERDICT_REVIEW,
                        ev,
                        f"{g} value rank {vr['rank']}/{n_v} but production rank "
                        f"{pr['rank']}/{n_p}: value held at {g} is not reaching the lineup.",
                    )
            else:
                _d(
                    "RC-D1",
                    g,
                    STATUS_NOT_FIRED,
                    evidence={"valueRank": [vr["rank"], n_v], "productionRank": [pr["rank"], n_p]},
                )

        # RC-D2 strong starters, thin coverage.
        if not team_valid or pr.get("rank") is None:
            _d("RC-D2", g, STATUS_NOT_EVALUATED, reason="insufficient_production")
        else:
            ratios = [
                ls.depth[t][g]["depthInsurance"]["meanRatio"]
                for t in ls.depth
                if ls.depth[t][g]["depthInsurance"]["meanRatio"] is not None
            ]
            p25 = _quantile(ratios, 0.25)
            mine = ls.depth[rid][g]
            ratio = mine["depthInsurance"]["meanRatio"]
            holes = mine["holes"]["dedicated"]
            ev = {
                "productionRank": [pr["rank"], pr["of"]],
                "depthInsuranceRatio": ratio,
                "leagueP25": None if p25 is None else round(p25, 4),
                "dedicatedHoles": holes,
                "holeWeeks": mine["holes"]["weeks"],
            }
            fires = (
                pr["rank"] <= _q(pr["of"], priors)
                and ratio is not None
                and p25 is not None
                and ratio <= p25
                and holes >= int(priors.get("thinCoverageMinHoles", 2))
            )
            if fires:
                _d(
                    "RC-D2",
                    g,
                    STATUS_FIRED,
                    VERDICT_REVIEW,
                    ev,
                    f"{g} starters rank {pr['rank']}/{pr['of']} but backups replace little "
                    f"of a lost starter (ratio {ratio} vs league P25 {round(p25, 4)}) and "
                    f"{holes} starter-slot weeks went empty or scoreless. Cheaper depth may "
                    "help; the Waiver Advisor decides whether any move is worth its "
                    "dynasty cost.",
                )
            else:
                _d("RC-D2", g, STATUS_NOT_FIRED, evidence=ev)

        # RC-D6 valuable but lineup-redundant.
        if not value.get("available"):
            _d("RC-D6", g, STATUS_NOT_EVALUATED, reason=f"value_unavailable:{value.get('reason')}")
        else:
            league_vals = sorted(
                (
                    float(v)
                    for team_players in value.get("_players", {}).values()
                    for (pg, v) in team_players
                    if pg == g and v is not None
                ),
                reverse=True,
            )
            cut = league_vals[_q(len(league_vals), priors) - 1] if league_vals else None
            flagged = []
            for p in by_group_players[g]:
                v = p.get("dynastyValue")
                m = p.get("marginalPoints", {}).get("value")
                kw = p["marginalPoints"]["knownWeeks"]
                if v is None or cut is None or float(v) < cut or m is None:
                    continue
                if kw < int(priors.get("minOwnedWeeks", 4)):
                    continue
                if "injured" in p.get("tags", []):
                    continue
                per_wk = m / kw
                if per_wk <= float(priors.get("redundantMarginalPerOwnedWeekMax", 1.0)) and (
                    p.get("redundantStartableWeeks", 0) > 0
                ):
                    flagged.append(
                        {
                            "playerId": p["playerId"],
                            "dynastyValue": v,
                            "marginalPerOwnedWeek": _r(per_wk),
                            "benchedStartableWeeks": p.get("redundantStartableWeeks", 0),
                        }
                    )
            if flagged:
                _d(
                    "RC-D6",
                    g,
                    STATUS_FIRED,
                    VERDICT_REVIEW,
                    {"players": flagged, "leagueTopQuartileValue": cut},
                    "Valuable in trade but adds little to THIS roster's optimal lineup: his "
                    "good weeks were usually covered by teammates. His dynasty value is "
                    "unchanged; any trade is a Trade Desk question.",
                )
            else:
                _d("RC-D6", g, STATUS_NOT_FIRED, evidence={"leagueTopQuartileValue": cut})

    # RC-D3 contender bench (team level).
    if posture is None or not posture.get("label"):
        _d(
            "RC-D3",
            None,
            STATUS_NOT_EVALUATED,
            reason=(posture or {}).get("reason") or "posture_unavailable",
        )
    else:
        idle = [
            p["playerId"]
            for p in players
            if p["eligibleOwnedWeeks"] >= int(priors.get("minOwnedWeeks", 4))
            and (p.get("starts") or {}).get("value") == 0
            and (p.get("leagueStartable") or {}).get("value") == 0
        ]
        ev = {"posture": posture.get("label"), "idleOwnedPlayers": idle}
        if posture["label"] == "PUSH" and len(idle) >= int(priors.get("contenderBenchMinCount", 5)):
            _d(
                "RC-D3",
                None,
                STATUS_FIRED,
                VERDICT_REVIEW,
                ev,
                f"A PUSH team holds {len(idle)} players who never entered the lineup and never "
                "cleared the league starter standard while owned.",
            )
        else:
            _d("RC-D3", None, STATUS_NOT_FIRED, evidence=ev)

    # RC-D4 aging reliance (team level).
    ages = value.get("_ages", {}) if value.get("available") else {}
    if not ages:
        _d("RC-D4", None, STATUS_NOT_EVALUATED, reason="ages_unavailable")
    else:
        wavg: dict[int, float | None] = {}
        for t in ls.team_ids:
            num = den = 0.0
            for wk in ls.team_stats[t]["validWeeks"]:
                for _i, _s, pid, pts in ls.solutions[wk][t].assigned:
                    a = ages.get(pid)
                    if a is not None and pts > 0:
                        num += a * pts
                        den += pts
            wavg[t] = round(num / den, 2) if den else None
        tbl = rank_table(wavg)
        mine = tbl["byTeam"].get(rid, {})
        ev = {
            "pointsWeightedStarterAge": wavg.get(rid),
            "oldestRank": [mine.get("rank"), mine.get("of")],
            "ageAsOf": value.get("asOf"),
        }
        if mine.get("rank") is not None and mine["rank"] <= _q(mine["of"], priors):
            _d(
                "RC-D4",
                None,
                STATUS_FIRED,
                VERDICT_REVIEW,
                ev,
                f"Lineup points came from one of the league's oldest starting groups "
                f"(points-weighted age {wavg.get(rid)}, rank {mine['rank']}/{mine['of']} oldest).",
            )
        else:
            _d("RC-D4", None, STATUS_NOT_FIRED, evidence=ev)

    _d("RC-D5", None, STATUS_NOT_EVALUATED, reason="requires_forward_projection")
    _d("RC-D7", None, STATUS_NOT_EVALUATED, reason="trade_desk_dependency")
    review = [d for d in out if d["verdict"] == VERDICT_REVIEW]
    return {
        "diagnoses": out,
        "overall": {
            "verdict": VERDICT_REVIEW if review else VERDICT_NO_ACTION,
            "reviewCount": len(review),
            "rulesNotEvaluated": sorted(
                {
                    f"{d['rule']}:{d['notEvaluatedReason']}"
                    for d in out
                    if d["status"] == STATUS_NOT_EVALUATED
                }
            ),
            "note": "Diagnoses are evidence for review. None of them is a transaction.",
        },
    }


# ── payload ──────────────────────────────────────────────────────────────
def build_team_view(
    ls: LeagueSeason,
    rid: int,
    vi: ValueInput,
    *,
    posture: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Selected-team view.  ``rid`` must be one of ``ls.team_ids``."""
    si = ls.si
    groups = ls.groups
    value = positional_value(vi, groups)
    value_players = {p.player_id: p for p in vi.teams.get(rid, ())} if vi.available else {}
    if vi.available:
        value["_players"] = {t: [(p.position, p.value) for p in ps] for t, ps in vi.teams.items()}
        value["_ages"] = {
            p.player_id: p.age for ps in vi.teams.values() for p in ps if p.age is not None
        }

    hist = {
        pid
        for wk in ls.included_weeks
        if rid in ls.solutions[wk]
        for pid in ls.solutions[wk][rid].roster
    }
    candidates = hist | set(value_players)
    hypo, hypo_meta = hypothetical_starts(ls, rid, candidates)

    redundant_sw: dict[str, int] = defaultdict(int)
    for wk in ls.team_stats[rid]["validWeeks"]:
        sol = ls.solutions[wk][rid]
        for pid in sol.roster:
            pts = sol.points.get(pid)
            if pts is None or pid in sol.assigned_ids:
                continue
            t = ls.thresholds[wk].get(group_of(si.players.get(pid)), {}).get("threshold")
            if t is not None and float(pts) >= t:
                redundant_sw[pid] += 1

    players: list[dict[str, Any]] = []
    for pid in sorted(candidates):
        meta = si.players.get(pid)
        vp = value_players.get(pid)
        g = group_of(meta) or (vp.position if vp else "")
        led = player_ledger(ls, rid, pid)
        row = {
            "playerId": pid,
            "name": (vp.name if vp and vp.name else (meta.name if meta else "")) or pid,
            "position": g,
            "onCurrentRoster": vp is not None,
            "onSeasonRoster": pid in hist,
            "dynastyValue": None if vp is None else vp.value,
            "age": None if vp is None else vp.age,
            "injuryStatus": None if vp is None else vp.injury,
            **led,
            "hypotheticalStarts": {"scenario": SCENARIO_END_ROSTER, **hypo.get(pid, {})},
            "redundantStartableWeeks": redundant_sw.get(pid, 0),
        }
        row["tags"] = player_tags(led, vp, g, ls.priors)
        players.append(row)

    prod_ranks = {
        g: rank_table(
            {
                t: ls.production[t][g]["points"]
                for t in ls.team_ids
                if ls.team_stats[t]["validWeeks"]
            }
        )
        for g in groups
    }
    ppg_ranks = {
        g: rank_table({t: ls.production[t][g]["ppg"] for t in ls.team_ids}) for g in groups
    }
    diag = diagnose(ls, rid, value, players, posture)
    positions = []
    for g in groups:
        pr = prod_ranks[g]
        prod = dict(ls.production[rid][g])
        prod.update(
            {
                "rank": pr["byTeam"].get(rid, {}).get("rank"),
                "of": pr["summary"]["teamsCompared"],
                "percentile": pr["byTeam"].get(rid, {}).get("percentile"),
                "tiedWith": pr["byTeam"].get(rid, {}).get("tiedWith"),
                "ppgRank": ppg_ranks[g]["byTeam"].get(rid, {}).get("rank"),
                "leagueMean": pr["summary"]["leagueMean"],
                "leagueMedian": pr["summary"]["leagueMedian"],
            }
        )
        if value["available"] and rid in value["perTeam"]:
            vr = value["ranks"][g]["byTeam"].get(rid, {})
            val = {
                **value["perTeam"][rid][g],
                "rank": vr.get("rank"),
                "of": vr.get("of"),
                "percentile": vr.get("percentile"),
                "leagueMean": value["ranks"][g]["summary"]["leagueMean"],
                "leagueMedian": value["ranks"][g]["summary"]["leagueMedian"],
                "asOf": value.get("asOf"),
            }
        else:
            val = {
                "available": False,
                "reason": value.get("reason") if not value["available"] else "team_not_in_contract",
            }
        ratios = [
            ls.depth[t][g]["depthInsurance"]["meanRatio"]
            for t in ls.team_ids
            if ls.depth[t][g]["depthInsurance"]["meanRatio"] is not None
        ]
        depth = dict(ls.depth[rid][g])
        depth["depthInsurance"] = {
            **depth["depthInsurance"],
            "leagueP25": None if not ratios else round(_quantile(ratios, 0.25), 4),
        }
        positions.append({"position": g, "production": prod, "value": val, "depth": depth})

    stats = ls.team_stats[rid]
    lineup_basis = (
        BASIS_HOST_BEST_BALL if si.lineup_mode == LINEUP_BEST_BALL else BASIS_HYPOTHETICAL
    )
    return {
        "team": {
            "rosterId": rid,
            "label": si.team_labels.get(rid, f"Team {rid}"),
            "validWeeks": stats["validWeeks"],
            "excludedWeeks": stats["excludedWeeks"],
            "rosterOverLimitWeeks": stats["rosterOverLimitWeeks"],
            "flexUnfilledSlotWeeks": stats["flexUnfilledSlotWeeks"],
            "lineupParity": stats["lineupParity"],
            "observedSubmittedWeeks": stats["observedSubmittedWeeks"],
            "posture": posture,
        },
        "lineupBasis": lineup_basis,
        "positions": positions,
        "players": players,
        "hypotheticalScenario": hypo_meta,
        **diag,
    }


def league_overview(ls: LeagueSeason) -> dict[str, Any]:
    """Every team's production per group with ranks (for the team picker / compare)."""
    teams = []
    for t in ls.team_ids:
        teams.append(
            {
                "rosterId": t,
                "label": ls.si.team_labels.get(t, f"Team {t}"),
                "validWeeks": len(ls.team_stats[t]["validWeeks"]),
                "points": {g: ls.production[t][g]["points"] for g in ls.groups},
            }
        )
    return {"teams": teams}


def assumptions(si: SeasonInput) -> list[str]:
    out = [
        "Production ranks cover the selected season's weekly rosters as the host recorded "
        "them; value ranks cover the CURRENT rosters on the live board. They are different "
        "rosters at different times and are ranked separately.",
        "Each starter's points count once, at his own position: a WR in FLEX is WR "
        "production. FLEX is an allocation, not a position.",
        "The league starter standard for a position-week is the score of the N-th best "
        "rostered player at that position, where N is how many players at that position "
        "the league's optimal lineups actually started that week. Free agents are not in "
        "the pool.",
        "The host records a bye, an inactive week and a scoreless game as the same 0.0.",
        "Positional dynasty value counts players only (no picks) and never includes an "
        "unpriced player as zero.",
    ]
    if si.lineup_mode != LINEUP_BEST_BALL:
        out.append(
            "This league sets lineups manually: production figures are the HYPOTHETICAL "
            "optimal lineup, and observedSubmittedPoints shows what the submitted lineups "
            "actually scored. The two are never mixed."
        )
    if si.include_playoffs:
        out.append(
            "Playoff weeks are included; teams without a playoff matchup have fewer weeks, "
            "so compare ppgRank as well as rank."
        )
    return out
