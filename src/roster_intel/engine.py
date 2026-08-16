"""Roster-level rollups — the single entry point for WS-J.

Composes the pieces into one per-roster payload: values, marginal
strength, per-position profiles, the competitive window, and (when the
caller supplies simulator output) playoff and championship probability.

``src/ros/playoff_sim.py`` is CONSUMED, not duplicated.  It already
models the remaining schedule, per-team variance and the bracket; a
second simulator here would be a parallel path and the two would drift.
This module takes its output as an input and reads the rows it needs.

Fragility semantics — read this before exporting it
───────────────────────────────────────────────────
A consuming agent derived "deficit" as ``fragility x marginal`` and got
QB reported as the biggest need on a QB-STRONG roster.  That inversion
is not a bug in fragility; it is fragility being read as the wrong
quantity.

    fragility  = CONCENTRATION. Share of an absent starter's value the
                 roster fails to replace. High fragility means the
                 position's output is concentrated in few players.
    marginal   = CONTRIBUTION. What the position adds to the optimal
                 lineup.

A great QB room in a superflex league is BOTH high-marginal and
high-fragility: the two starters are excellent and nobody behind them
is close.  Multiplying those reports the roster's greatest STRENGTH as
its greatest need.

Deficiency is a different measurement and is provided here as
``PositionNeed.deficit`` so consumers stop deriving it: it is the gap
between what the position contributes and what a replacement-level
occupant of the same slots would contribute.  Low contribution relative
to replacement is a deficit; high concentration is a RISK, and the two
are reported separately because they call for different moves — a
deficit says acquire a starter, concentration says acquire insurance.

Pure computation.  No I/O, no network, no clock.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping, Sequence

from src.league_intel.replacement import PositionReplacement
from src.roster_intel.marginal import position_marginals, solve_summary
from src.roster_intel.profiles import RosterProfile, build_position_profiles
from src.roster_intel.window import CompetitiveWindow, compute_window
from src.ros.lineup import RosterPlayer

__all__ = [
    "PositionNeed",
    "RosterIntel",
    "RosterValues",
    "analyze_roster",
    "position_needs",
]


@dataclass(frozen=True)
class RosterValues:
    """Value rollups across the parallel scales (LI-4 schema).

    Kept as separate fields rather than one blended number: the whole
    point of the LI-4 schema is that market, consensus and
    league-adjusted can disagree, and a blend hides the disagreement
    that makes a trade findable.
    """

    market: float = 0.0
    consensus: float = 0.0
    league_adjusted: float = 0.0
    ros: float = 0.0
    # Starting-lineup ROS value vs everything else.
    starters_ros: float = 0.0
    bench_ros: float = 0.0
    #: ``None`` means NOBODY SUPPLIED IT — not "this roster holds no picks".
    #:
    #: Every production caller (``src/api/gameplan.py``) omits the argument,
    #: so the previous ``0.0`` default was published on a live field as a
    #: real, measured $0 of draft capital for teams that in fact hold picks
    #: worth thousands.  That is the repo's MISSING-IS-NEVER-ZERO rule
    #: broken on an output surface (C1-U6 follow-up 6).  Repaired by making
    #: the missing state expressible rather than by inventing a number: no
    #: second pick pricer is introduced here, and a caller that DOES have
    #: the roster's pick total still passes it.
    pick_value: float | None = None
    priced_players: int = 0
    unpriced_players: int = 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "market": round(self.market, 3),
            "consensus": round(self.consensus, 3),
            "leagueAdjusted": round(self.league_adjusted, 3),
            "ros": round(self.ros, 3),
            "startersRos": round(self.starters_ros, 3),
            "benchRos": round(self.bench_ros, 3),
            "pickValue": (None if self.pick_value is None else round(self.pick_value, 3)),
            "pickValueState": ("unavailable" if self.pick_value is None else "supplied"),
            "pricedPlayers": self.priced_players,
            "unpricedPlayers": self.unpriced_players,
        }


@dataclass(frozen=True)
class PositionNeed:
    """Deficiency and risk, kept SEPARATE (see module docstring).

    ``deficit`` answers "am I below replacement here" — acquire a
    starter.  ``concentration_risk`` answers "would one absence hurt" —
    acquire insurance.  A consumer that multiplies them reproduces the
    QB inversion.
    """

    position: str
    deficit: float
    concentration_risk: float
    replacement_baseline: float | None
    actual_contribution: float
    urgent: bool
    reasons: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {
            "position": self.position,
            "deficit": round(self.deficit, 3),
            "concentrationRisk": round(self.concentration_risk, 4),
            "replacementBaseline": (
                round(self.replacement_baseline, 3)
                if self.replacement_baseline is not None
                else None
            ),
            "actualContribution": round(self.actual_contribution, 3),
            "urgent": self.urgent,
            "reasons": list(self.reasons),
            "_semantics": {
                "deficit": "contribution shortfall vs a replacement-level occupant; >0 means acquire a starter",
                "concentrationRisk": "share of an absent starter's value not replaced; high means acquire insurance",
                "warning": "do NOT multiply these; concentration is not deficiency (a strong room is high on both)",
            },
        }


def position_needs(
    profile: RosterProfile,
    replacement: Mapping[str, PositionReplacement] | None = None,
) -> dict[str, PositionNeed]:
    """Deficit and concentration risk per position.

    ``deficit`` = what a replacement-level occupant of this position's
    dedicated slots WOULD contribute, minus what the roster actually
    contributes.  Positive means the roster is below replacement there.

    Deliberately NOT derived from fragility: fragility measures
    concentration, and a strong concentrated room would invert into a
    phantom need (the exact defect a consumer hit).
    """
    out: dict[str, PositionNeed] = {}
    for pos, prof in profile.positions.items():
        rep = (replacement or {}).get(pos)
        baseline_per_slot = rep.value("starter") if rep else None
        req = prof.required_slots

        if baseline_per_slot is not None and req > 0:
            baseline = baseline_per_slot * req
            deficit = max(0.0, baseline - prof.marginal_points)
        else:
            baseline = None
            deficit = 0.0

        reasons = list(prof.need_reasons)
        if deficit > 0 and baseline:
            reasons.append(
                f"contributes {prof.marginal_points:.0f} vs a replacement-level "
                f"{baseline:.0f} across {req} dedicated slot(s)"
            )

        out[pos] = PositionNeed(
            position=pos,
            deficit=deficit,
            concentration_risk=prof.fragility,
            replacement_baseline=baseline,
            actual_contribution=prof.marginal_points,
            urgent=prof.urgent_need or deficit > 0,
            reasons=tuple(reasons),
        )
    return out


@dataclass(frozen=True)
class RosterIntel:
    """Everything WS-J knows about one roster."""

    owner_id: str
    values: RosterValues
    lineup_score: float
    filled_slots: int
    total_slots: int
    profile: RosterProfile
    needs: dict[str, PositionNeed]
    window: CompetitiveWindow
    playoff_odds: float | None = None
    championship_odds: float | None = None
    playoff_odds_ci: tuple[float, float] | None = None
    championship_odds_ci: tuple[float, float] | None = None
    odds_source: str = "unavailable"
    notes: tuple[str, ...] = field(default_factory=tuple)

    def to_dict(self) -> dict[str, Any]:
        return {
            "ownerId": self.owner_id,
            "values": self.values.to_dict(),
            "lineupScore": round(self.lineup_score, 3),
            "filledSlots": self.filled_slots,
            "totalSlots": self.total_slots,
            "positions": self.profile.to_dict()["positions"],
            "needs": {k: v.to_dict() for k, v in sorted(self.needs.items())},
            "competitiveWindow": self.window.to_dict(),
            "playoffOdds": self.playoff_odds,
            "playoffOddsCi": list(self.playoff_odds_ci) if self.playoff_odds_ci else None,
            "championshipOdds": self.championship_odds,
            "championshipOddsCi": (
                list(self.championship_odds_ci) if self.championship_odds_ci else None
            ),
            "oddsSource": self.odds_source,
            "notes": list(self.notes),
        }


def _rollup_values(
    pool: Sequence[RosterPlayer],
    entered_ids: frozenset[str],
    player_values: Mapping[str, Mapping[str, Any]] | None,
    pick_value: float | None,
) -> RosterValues:
    """Sum the parallel value scales over the roster.

    NOTE: these are portfolio totals, deliberately NOT a strength
    signal.  Strength is marginal (see ``marginal.py``); a summed
    portfolio is what you would trade, not what you would score.
    """
    pv = player_values or {}
    market = consensus = adjusted = ros = starters = bench = 0.0
    priced = unpriced = 0
    for p in pool:
        ros += max(0.0, p.ros_value)
        if p.ros_value > 0:
            priced += 1
        else:
            unpriced += 1
        if p.player_id in entered_ids:
            starters += max(0.0, p.ros_value)
        else:
            bench += max(0.0, p.ros_value)
        row = pv.get(p.player_id) or pv.get(p.canonical_name) or {}
        market += float(row.get("marketValue") or 0.0)
        consensus += float(row.get("consensusValue") or 0.0)
        adjusted += float(row.get("leagueAdjustedDynastyValue") or row.get("consensusValue") or 0.0)
    return RosterValues(
        market=market,
        consensus=consensus,
        league_adjusted=adjusted,
        ros=ros,
        starters_ros=starters,
        bench_ros=bench,
        pick_value=pick_value,
        priced_players=priced,
        unpriced_players=unpriced,
    )


def _unpriced_note(pool: Sequence[RosterPlayer]) -> str | None:
    """Warn that ``unpricedPlayers == 0`` is not proof of a clean join.

    ``roster_source.build_roster_pool`` DROPS names it cannot value, so
    on that path the count is structurally zero (measured: 0 for all 12
    real rosters while 32 of 665 rostered names were dropped).  Other
    builders — ``src/ros/team_strength.py`` — keep unvalued players at
    0.0 instead, and there the count is real.  A reader cannot tell
    which builder produced the pool from the number alone, so say so
    rather than let 0 be read as full coverage.
    """
    if any(p.ros_value <= 0 for p in pool):
        return None
    return (
        "unpricedPlayers is 0 because every player IN the pool carries a value; "
        "this is not a join-coverage claim — builders that drop unvalued names "
        "(roster_source.build_roster_pool) report their losses in JoinReport"
    )


@dataclass(frozen=True)
class _Odds:
    playoff: float | None = None
    championship: float | None = None
    playoff_ci: tuple[float, float] | None = None
    championship_ci: tuple[float, float] | None = None
    source: str = "unavailable"
    notes: tuple[str, ...] = ()


def _odds_for(
    owner_id: str,
    playoff_odds: Sequence[Mapping[str, Any]] | None,
) -> _Odds:
    """Pull this owner's row out of playoff_sim output.

    The simulator's row schema is NOT fixed.  ``simulate_playoff_odds``
    on main emits ``playoffOdds`` / ``byeOdds`` / ``topSeedOdds`` /
    ``seedDistribution`` and NOTHING else — no championship odds and no
    confidence intervals.  The bracket run and the Wilson intervals
    come from the LI-8 work, which is a separate unmerged branch.

    So the fields are read defensively AND their absence is reported.
    Missing intervals stay None rather than collapsing to zero width: a
    point estimate presented without an interval reads as a certainty,
    and 0.61 from 2,000 sims is +/- 2 points.
    """
    if not playoff_odds:
        return _Odds()
    row = next((r for r in playoff_odds if str(r.get("ownerId")) == str(owner_id)), None)
    if row is None:
        return _Odds(source="owner_not_in_simulation")

    def _ci(key: str) -> tuple[float, float] | None:
        raw = row.get(key)
        if isinstance(raw, (list, tuple)) and len(raw) == 2:
            return (float(raw[0]), float(raw[1]))
        return None

    po = row.get("playoffOdds")
    ch = row.get("championshipOdds")
    playoff_ci = _ci("playoffOddsCi")
    championship_ci = _ci("championshipOddsCi")

    notes: list[str] = []
    if ch is None:
        notes.append(
            "simulator supplied no championshipOdds; this build of "
            "src/ros/playoff_sim.py stops at playoff qualification and does "
            "not run the bracket"
        )
    if po is not None and playoff_ci is None:
        notes.append(
            "playoff odds carry no confidence interval; treat the point "
            "estimate as approximate and do not compare two teams on it alone"
        )

    return _Odds(
        playoff=float(po) if po is not None else None,
        championship=float(ch) if ch is not None else None,
        playoff_ci=playoff_ci,
        championship_ci=championship_ci,
        source="playoff_sim",
        notes=tuple(notes),
    )


def analyze_roster(
    owner_id: str,
    pool: Sequence[RosterPlayer],
    slots: Sequence[str],
    *,
    replacement: Mapping[str, PositionReplacement] | None = None,
    player_meta: Mapping[str, Mapping[str, Any]] | None = None,
    player_values: Mapping[str, Mapping[str, Any]] | None = None,
    # ``None`` = not supplied.  See ``RosterValues.pick_value``: an
    # unfed parameter must not publish as a measured $0.
    pick_value: float | None = None,
    playoff_odds: Sequence[Mapping[str, Any]] | None = None,
    lineup_scores: Mapping[str, float] | None = None,
    override_state: str | None = None,
    override_reason: str | None = None,
) -> RosterIntel:
    """Full WS-J analysis for one roster.

    ``playoff_odds`` is ``simulate_playoff_odds(...)["playoffOdds"]``
    from ``src/ros/playoff_sim.py``.  Supplying it upgrades the
    competitive window's competitiveness axis from a structural proxy
    to simulated odds AND attaches the probabilities directly.
    """
    pool_list = list(pool)
    slots_list = list(slots)

    marg = position_marginals(pool_list, slots_list)
    entered = solve_summary(pool_list, slots_list).assigned_ids

    profile = build_position_profiles(
        pool_list,
        slots_list,
        replacement=replacement,
        player_meta=player_meta,
        marginals=marg,
    )
    needs = position_needs(profile, replacement)
    window = compute_window(
        owner_id,
        pool_list,
        slots_list,
        playoff_odds=playoff_odds,
        lineup_scores=lineup_scores,
        player_meta=player_meta,
        override_state=override_state,
        override_reason=override_reason,
    )
    odds = _odds_for(owner_id, playoff_odds)

    notes: list[str] = []
    if odds.source == "unavailable":
        notes.append(
            "no playoff_sim output supplied; playoff/championship odds omitted "
            "and the competitive window fell back to a structural proxy"
        )
    elif odds.source == "owner_not_in_simulation":
        notes.append(f"owner {owner_id!r} absent from the supplied simulation rows")
    notes.extend(odds.notes)
    if replacement is None:
        notes.append(
            "no replacement levels supplied; tiers default to developmental "
            "and position deficits are not computed"
        )
    if window.inputs.trajectory_sample == 0 and not window.overridden:
        # Escalated to the roster level deliberately.  With no ages the
        # window keeps its second axis pinned at neutral and the whole
        # distribution reduces to a one-dimensional read of
        # competitiveness — which silently makes some states (a young
        # roster losing now) unreachable.  Measured on the real league:
        # ages absent, `productive_struggle` was the most-likely state
        # for zero of twelve teams; ages joined, for one.  That is a
        # wiring gap, not a property of the league, and it must not read
        # as a finding.  Ages are available offline in
        # data/public_league/nfl_players_full.json (10,954 of 12,201
        # entries) and on the live Sleeper overlay — there is no reason
        # for a caller to leave this empty.
        notes.append(
            "no ages reached the window for any lineup entrant; the trajectory "
            "axis is pinned neutral and the distribution is a competitiveness-only "
            "read (states that require a young or old roster are unreachable) — "
            "supply player_meta ages"
        )
    if unpriced_note := _unpriced_note(pool_list):
        notes.append(unpriced_note)

    return RosterIntel(
        owner_id=owner_id,
        values=_rollup_values(pool_list, entered, player_values, pick_value),
        lineup_score=marg.lineup_score,
        filled_slots=marg.filled_slots,
        total_slots=marg.total_slots,
        profile=profile,
        needs=needs,
        window=window,
        playoff_odds=odds.playoff,
        championship_odds=odds.championship,
        playoff_odds_ci=odds.playoff_ci,
        championship_odds_ci=odds.championship_ci,
        odds_source=odds.source,
        notes=tuple(notes),
    )
