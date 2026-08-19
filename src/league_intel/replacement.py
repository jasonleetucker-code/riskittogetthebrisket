"""Replacement levels + separated scarcity components (LI-5, spec §19).

What "replacement level" means here
───────────────────────────────────
Four thresholds per position, each answering a different question:

    starter           the typical last starter — what the median team's
                      weakest starter at this position is worth
    bestBallStarter   the deepest anyone dips — the weakest player who
                      still cracks SOME team's optimal lineup.  In a
                      best-ball league there is no set lineup, so this
                      is the honest floor for "startable"
    roster            the last player worth rostering at all
    waiver            the best player nobody has rostered

**Endogenous flex allocation.**  The starter thresholds are NOT derived
by preassigning FLEX/SUPER_FLEX to positions.  They are measured from
what the exact optimizer (``src.ros.lineup``) actually starts across
every real roster in the league.

**KNOWN LIMITATION — this path optimizes on point estimates.**
``measure_endogenous_starters`` runs the optimizer over ``rosValue``,
a season-long MEAN.  Best ball pays for weekly SPIKES, and a mean
erases them: a TE averaging 8 PPG who hits 22 twice wins a FLEX slot
in those weeks and never wins one on a mean.  So this path
systematically understates flex demand for high-variance positions.

Measured against actual 2025 weekly scoring, re-solved under the
current 21-slot vector (158 team-weeks; see
``scripts/measure_te_demand_actuals.py``):

===================  ======================  ==============
quantity             projection (rosValue)   weekly actuals
===================  ======================  ==============
FLEX TE share        0.0%                    10.4%
TE started / team    2.00                    2.215
===================  ======================  ==============

An earlier version of this docstring reported "FLEX never takes a TE
at all" as a finding and built a mispricing argument on it.  That was
an artifact of the point estimates, not a property of the league —
corrected here so it is not propagated further.

For structural constants (e.g. the TE premium), calibrate from actual
weekly outcomes rather than from this path — see ADR-009 in
``docs/league-intelligence/DECISIONS.md``.  A preassigned even split is
still wrong in the same direction (it overstates TE flex demand); the
projection path is wrong in the opposite direction.  Both endpoints of
any before/after comparison must be measured the same way, or the
asymmetry dominates the result.

**Smoothed bands, not single ranks.**  A replacement level read off one
rank is hostage to one player's projection.  Rank-indexed levels
average a window around the threshold; the starter levels are
naturally smoothed by averaging across the league's teams.

Pure computation over a supplied pool — no I/O, no network.
"""

from __future__ import annotations

import statistics
from dataclasses import dataclass, field
from typing import Any, Iterable, Mapping, Sequence

from src.ros.lineup import RosterPlayer, optimize_lineup, roster_players_from_rows

__all__ = [
    "REPLACEMENT_SCHEMA_VERSION",
    "DEFAULT_BAND",
    "RevealedDemand",
    "measure_revealed_demand",
    "ReplacementLevel",
    "PositionReplacement",
    "ScarcityComponents",
    "normalize_base_position",
    "measure_endogenous_starters",
    "compute_replacement_levels",
    "compute_scarcity",
]

REPLACEMENT_SCHEMA_VERSION = 1

DEFAULT_BAND = 2
"""Half-width of the smoothing window for rank-indexed levels: the
level is the mean of ranks [r-BAND, r+BAND]."""

# Sleeper position → the base position a roster slot is named for.
# Mirrors the family map in src/ros/lineup.py; kept here so scarcity
# can bucket a pool without importing the optimizer's private maps.
_BASE_POSITION_ALIASES: dict[str, str] = {
    "DE": "DL",
    "DT": "DL",
    "EDGE": "DL",
    "NT": "DL",
    "OLB": "LB",
    "ILB": "LB",
    "MLB": "LB",
    "CB": "DB",
    "S": "DB",
    "SS": "DB",
    "FS": "DB",
}


def normalize_base_position(position: str) -> str:
    """Collapse a Sleeper position onto its roster-slot family."""
    pos = (position or "").strip().upper()
    return _BASE_POSITION_ALIASES.get(pos, pos)


@dataclass(frozen=True)
class ReplacementLevel:
    """One threshold for one position."""

    position: str
    tier: str
    value: float | None
    threshold_rank: int | None
    band_low: float | None
    band_high: float | None
    sample_size: int

    def to_dict(self) -> dict[str, Any]:
        return {
            "position": self.position,
            "tier": self.tier,
            "value": self.value,
            "thresholdRank": self.threshold_rank,
            "bandLow": self.band_low,
            "bandHigh": self.band_high,
            "sampleSize": self.sample_size,
        }


@dataclass(frozen=True)
class PositionReplacement:
    """All four thresholds for one position, plus what produced them."""

    position: str
    starters_per_team: float
    rostered_count: int
    priced_count: int = 0
    levels: dict[str, ReplacementLevel] = field(default_factory=dict)

    def value(self, tier: str) -> float | None:
        lvl = self.levels.get(tier)
        return lvl.value if lvl else None

    def to_dict(self) -> dict[str, Any]:
        return {
            "position": self.position,
            "startersPerTeam": self.starters_per_team,
            "rosteredCount": self.rostered_count,
            "pricedCount": self.priced_count,
            "levels": {k: v.to_dict() for k, v in self.levels.items()},
        }


@dataclass(frozen=True)
class ScarcityComponents:
    """The spec's scarcity signals, kept SEPARATE on purpose.

    Collapsing these to one number destroys the distinction between
    "this position is top-heavy" (eliteSeparation) and "there is
    nothing on waivers" (waiverScarcity) — they call for opposite
    roster moves.  Consumers combine them explicitly or not at all.

    The three ``*Scarcity`` fields are 0-1 normalized drops; the three
    separation/gap fields are in raw value units so they stay additive
    with player values.

    ``waiver_scarcity`` is measured against the best-ball starter floor
    rather than the last rostered player.  The literal roster tail is
    the noisiest number in the league (deep dart throws, and any
    identity-join miss lands there), and the decision it informs —
    "if I lose a starter, how far do I fall?" — is about the startable
    floor, not the worst body on a bench.
    """

    position: str
    lineup_scarcity: float | None
    roster_scarcity: float | None
    waiver_scarcity: float | None
    elite_separation: float | None
    starter_separation: float | None
    replacement_gap: float | None

    def to_dict(self) -> dict[str, Any]:
        return {
            "position": self.position,
            "lineupScarcity": self.lineup_scarcity,
            "rosterScarcity": self.roster_scarcity,
            "waiverScarcity": self.waiver_scarcity,
            "eliteSeparation": self.elite_separation,
            "starterSeparation": self.starter_separation,
            "replacementGap": self.replacement_gap,
        }


# ── Endogenous starter measurement ────────────────────────────────────


def _to_roster_players(players: Iterable[Mapping[str, Any]]) -> list[RosterPlayer]:
    """Delegates to the canonical adapter — see
    ``ros.lineup.roster_player_from_row`` for why this is no longer
    written out here."""
    return roster_players_from_rows(players)


@dataclass(frozen=True)
class EndogenousStarters:
    """What the optimizer actually started, league-wide."""

    team_count: int
    starters_per_team: dict[str, float]
    marginal_starter_values: dict[str, list[float]]
    slot_fill: dict[str, dict[str, int]]

    def to_dict(self) -> dict[str, Any]:
        return {
            "teamCount": self.team_count,
            "startersPerTeam": dict(self.starters_per_team),
            "slotFill": {k: dict(v) for k, v in self.slot_fill.items()},
        }


def measure_endogenous_starters(
    teams: Sequence[Mapping[str, Any]],
    starter_slots: Sequence[str],
) -> EndogenousStarters:
    """Run the exact optimizer on every roster and record what started.

    Returns per-position starters-per-team (the endogenous flex
    allocation), each team's *marginal* (lowest-valued) starter at each
    position, and the raw slot→position fill counts for diagnostics.

    **The values passed in decide what this measures.**  Given
    season-long means (``rosValue``), it reports the flex allocation of
    an *average* week, which understates high-variance positions —
    measured TE flex share is 0.0% on means against 10.4% on actual
    weekly scores.  Given per-week actuals it reports the real
    allocation.  Do not read the mean-based output as "what this league
    starts"; see the module docstring.
    """
    counts: dict[str, int] = {}
    marginal: dict[str, list[float]] = {}
    slot_fill: dict[str, dict[str, int]] = {}
    n_teams = 0

    for team in teams:
        players = team.get("players") or []
        if not players:
            continue
        n_teams += 1
        solution = optimize_lineup(_to_roster_players(players), starter_slots=starter_slots)
        per_pos: dict[str, list[float]] = {}
        for row in solution.starting_lineup:
            # BY THE PLAYER'S NOMINAL POSITION, NOT BY THE SLOT — and that
            # is deliberate, so read this before "fixing" it.
            #
            # It looks wrong on a hybrid: a DL/LB whom the optimizer slots
            # at LB still counts as DL here, so on the live 12 rosters
            # ``starters_per_team`` reads DL 2.667 / LB 3.250 / DB 3.083
            # while the league plainly starts 3 at each.  The slot truth
            # is real and is recorded — ``slot_fill`` below shows exactly
            # 36 DL / 36 LB / 36 DB, 3 per team.
            #
            # But these numbers exist to describe A POOL, and the pool is
            # keyed by nominal position: ``compute_scarcity`` builds
            # ``by_pos`` from ``normalize_base_position(player["position"])``.
            # Two separate consumers depend on that correspondence, and it
            # is worth naming them precisely rather than hand-waving at
            # "scarcity" — a vague justification is what invites the next
            # reader to re-open this:
            #
            #   * ``starters_per_team`` → ``starters_n`` → ``pool[:n]`` →
            #     ``median_starter``, which feeds ``eliteSeparation`` and
            #     ``starterSeparation``.  Slicing a pool of nominal-DLs
            #     with a count derived from DL *slots* mismatches
            #     numerator and denominator.
            #   * ``marginal_starter_values`` → the ``starter``
            #     replacement tier → ``lineupScarcity``, which IS the live
            #     axis of the league-adjusted overlay.  Note it reaches
            #     that axis through the MARGINALS, not through
            #     ``starters_n`` — an earlier version of this comment said
            #     otherwise and was wrong.
            #
            # Both are keyed nominally, so switching attribution to the
            # slot breaks both.
            #
            # The question this answers is "how many DL-pool bodies do
            # lineups consume", which is what a replacement level needs.
            # "How many DL slots does the league start" is a different
            # question with a different answer, and ``slot_fill`` is where
            # it lives.
            base = normalize_base_position(str(row.get("position") or ""))
            counts[base] = counts.get(base, 0) + 1
            per_pos.setdefault(base, []).append(float(row.get("rosValue") or 0.0))
            slot = str(row.get("slot") or "")
            slot_fill.setdefault(slot, {})
            slot_fill[slot][base] = slot_fill[slot].get(base, 0) + 1
        for base, values in per_pos.items():
            marginal.setdefault(base, []).append(min(values))

    per_team = {pos: n / n_teams for pos, n in counts.items()} if n_teams else {}
    return EndogenousStarters(
        team_count=n_teams,
        starters_per_team=per_team,
        marginal_starter_values=marginal,
        slot_fill=slot_fill,
    )


# ── Replacement levels ────────────────────────────────────────────────


def _banded_value(
    sorted_values: Sequence[float],
    rank: int,
    band: int,
) -> tuple[float | None, int | None, float | None, float | None]:
    """Mean of the values within ``band`` ranks of ``rank`` (1-indexed).

    Returns ``(value, clamped_rank, band_low, band_high)``.  A rank past
    the end of the pool clamps to the tail — the honest reading of
    "there is nobody left at this position".
    """
    if not sorted_values:
        return None, None, None, None
    n = len(sorted_values)
    r = max(1, min(rank, n))
    lo = max(1, r - band)
    hi = min(n, r + band)
    window = sorted_values[lo - 1 : hi]
    if not window:
        return None, None, None, None
    return statistics.fmean(window), r, min(window), max(window)


def compute_replacement_levels(
    teams: Sequence[Mapping[str, Any]],
    starter_slots: Sequence[str],
    *,
    free_agents: Sequence[Mapping[str, Any]] = (),
    band: int = DEFAULT_BAND,
    endogenous: EndogenousStarters | None = None,
) -> dict[str, PositionReplacement]:
    """Compute the four replacement tiers per position.

    Args:
        teams: every roster in the league, each ``{"players": [...]}``
            with ``position`` / ``rosValue`` / ``fantasyPositions``.
        starter_slots: the league's flattened starter slots.
        free_agents: unrostered players, for the ``waiver`` tier.
        band: smoothing half-width for rank-indexed tiers.
        endogenous: reuse a prior measurement instead of re-running the
            optimizer (the measurement is the expensive part).
    """
    measured = endogenous or measure_endogenous_starters(teams, starter_slots)

    # Unpriced players (no ROS read — deep dart throws, or an identity
    # miss) carry no information about where a threshold sits.  A
    # roster tier read off them would always be 0.0 and collapse every
    # downstream ratio, so they are excluded from the level pools.
    # They still count in ``rostered_count`` for transparency.
    rostered: dict[str, list[float]] = {}
    rostered_all: dict[str, int] = {}
    for team in teams:
        for p in team.get("players") or []:
            base = normalize_base_position(str(p.get("position") or ""))
            if not base:
                continue
            rostered_all[base] = rostered_all.get(base, 0) + 1
            value = float(p.get("rosValue") or 0.0)
            if value > 0:
                rostered.setdefault(base, []).append(value)
    for values in rostered.values():
        values.sort(reverse=True)

    fa: dict[str, list[float]] = {}
    for p in free_agents:
        base = normalize_base_position(str(p.get("position") or ""))
        if not base:
            continue
        value = float(p.get("rosValue") or 0.0)
        if value > 0:
            fa.setdefault(base, []).append(value)
    for values in fa.values():
        values.sort(reverse=True)

    out: dict[str, PositionReplacement] = {}
    for pos, pool in rostered.items():
        levels: dict[str, ReplacementLevel] = {}
        # Same unpriced-player exclusion as the pools above: a started
        # player with no ROS read means "we can't price this slot", not
        # "the floor is zero".  Left in, one such starter would drag
        # bestBallStarter (which reads the LOWEST marginals) to 0.0.
        marginals = sorted(v for v in measured.marginal_starter_values.get(pos, []) if v > 0)

        # starter — the TYPICAL last starter: median of every team's
        # marginal starter.  Averaging across teams is itself the
        # smoothing here, so no rank band is needed.
        if marginals:
            levels["starter"] = ReplacementLevel(
                position=pos,
                tier="starter",
                value=statistics.median(marginals),
                threshold_rank=None,
                band_low=marginals[0],
                band_high=marginals[-1],
                sample_size=len(marginals),
            )
            # bestBallStarter — the deepest ANY team dips.  Smoothed by
            # averaging the lowest few marginals rather than taking a
            # single team's outlier.
            k = min(len(marginals), max(1, band))
            levels["bestBallStarter"] = ReplacementLevel(
                position=pos,
                tier="bestBallStarter",
                value=statistics.fmean(marginals[:k]),
                threshold_rank=None,
                band_low=marginals[0],
                band_high=marginals[k - 1],
                sample_size=k,
            )

        # roster — the last player rostered at this position.
        value, rank, lo, hi = _banded_value(pool, len(pool), band)
        levels["roster"] = ReplacementLevel(
            position=pos,
            tier="roster",
            value=value,
            threshold_rank=rank,
            band_low=lo,
            band_high=hi,
            sample_size=len(pool),
        )

        # waiver — the best unrostered player at this position.
        fa_pool = fa.get(pos, [])
        if fa_pool:
            value, rank, lo, hi = _banded_value(fa_pool, 1, band)
            levels["waiver"] = ReplacementLevel(
                position=pos,
                tier="waiver",
                value=value,
                threshold_rank=rank,
                band_low=lo,
                band_high=hi,
                sample_size=len(fa_pool),
            )

        out[pos] = PositionReplacement(
            position=pos,
            starters_per_team=measured.starters_per_team.get(pos, 0.0),
            rostered_count=rostered_all.get(pos, len(pool)),
            priced_count=len(pool),
            levels=levels,
        )
    return out


# ── Scarcity components ───────────────────────────────────────────────


@dataclass(frozen=True)
class RevealedDemand:
    """What the league's managers ACTUALLY roster at a position.

    Evidence about **demand**, not about value.  Managers are not
    optimal; counts encode habit and inattention alongside genuine
    valuation.  And rostership is **jointly determined with supply** —
    you cannot roster six startable TEs if only thirty exist — so
    ``priced_supply`` and ``share_of_supply`` are reported beside the
    counts rather than the two being silently conflated.

    ``startable_per_team`` applies a value floor to separate a real
    depth piece from a speculative stash on a 58-man roster.  **The
    floor is scale-dependent** — pass ``value_by_key`` on the consensus
    0-9999 scale with a matching ``startable_floor``, or pass rosValue
    (0-100) with a floor on that scale.  Mixing them silently returns
    zero startable players, which is why
    :attr:`startable_per_team` should always be sanity-checked against
    :attr:`per_team`.
    """

    position: str
    required_starters: float
    team_count: int
    total_rostered: int
    per_team: float
    per_team_sd: float
    per_team_min: int
    per_team_max: int
    startable_per_team: float
    priced_supply: int
    share_of_supply: float | None

    @property
    def demand_ratio(self) -> float:
        """Rostered per team divided by required starters."""
        return self.per_team / self.required_starters if self.required_starters else 0.0

    @property
    def supply_constrained(self) -> bool:
        """True when the league has taken nearly the whole priced pool,
        so the count reflects scarcity of bodies rather than choice."""
        return self.share_of_supply is not None and self.share_of_supply >= 0.95

    def to_dict(self) -> dict[str, Any]:
        return {
            "position": self.position,
            "requiredStarters": self.required_starters,
            "teamCount": self.team_count,
            "totalRostered": self.total_rostered,
            "perTeam": self.per_team,
            "perTeamSd": self.per_team_sd,
            "perTeamMin": self.per_team_min,
            "perTeamMax": self.per_team_max,
            "startablePerTeam": self.startable_per_team,
            "pricedSupply": self.priced_supply,
            "shareOfSupply": self.share_of_supply,
            "demandRatio": self.demand_ratio,
            "supplyConstrained": self.supply_constrained,
        }


def measure_revealed_demand(
    teams: Sequence[Mapping[str, Any]],
    required_starters: Mapping[str, float],
    *,
    priced_supply: Mapping[str, int] | None = None,
    value_by_key: Mapping[str, float] | None = None,
    startable_floor: float = 1000.0,
) -> dict[str, RevealedDemand]:
    """Per-position rostership across the league's real rosters.

    This is the measurement the ``rosterScarcity`` concept was waiting
    for: how deep managers *actually* go, in this format, right now —
    as opposed to how deep a lineup requirement says they must.

    Caveats are structural, not bolted on: see :class:`RevealedDemand`.
    With a 12-team league, report and read the spread, not just the
    mean.
    """
    counts: dict[str, list[int]] = {pos: [] for pos in required_starters}
    startable: dict[str, list[int]] = {pos: [] for pos in required_starters}
    n_teams = 0
    for team in teams:
        players = team.get("players") or []
        if not players:
            continue
        n_teams += 1
        seen: dict[str, int] = {}
        seen_startable: dict[str, int] = {}
        for p in players:
            base = normalize_base_position(str(p.get("position") or ""))
            if base not in counts:
                continue
            seen[base] = seen.get(base, 0) + 1
            value = 0.0
            if value_by_key is not None:
                key = str(p.get("canonicalName") or p.get("name") or "").strip().lower()
                value = float(value_by_key.get(key) or 0.0)
            else:
                value = float(p.get("rosValue") or 0.0)
            if value >= startable_floor:
                seen_startable[base] = seen_startable.get(base, 0) + 1
        for pos in counts:
            counts[pos].append(seen.get(pos, 0))
            startable[pos].append(seen_startable.get(pos, 0))

    out: dict[str, RevealedDemand] = {}
    for pos, series in counts.items():
        if not series or not n_teams:
            continue
        total = sum(series)
        supply = int((priced_supply or {}).get(pos, 0))
        out[pos] = RevealedDemand(
            position=pos,
            required_starters=float(required_starters[pos]),
            team_count=n_teams,
            total_rostered=total,
            per_team=total / n_teams,
            per_team_sd=statistics.pstdev(series) if len(series) > 1 else 0.0,
            per_team_min=min(series),
            per_team_max=max(series),
            startable_per_team=sum(startable[pos]) / n_teams,
            priced_supply=supply,
            share_of_supply=(total / supply) if supply > 0 else None,
        )
    return out


def _safe_drop(top: float | None, bottom: float | None) -> float | None:
    """``1 - bottom/top`` — the normalized drop from top to bottom."""
    if top is None or bottom is None or top <= 0:
        return None
    return max(0.0, min(1.0, 1.0 - (bottom / top)))


def compute_scarcity(
    replacement: Mapping[str, PositionReplacement],
    teams: Sequence[Mapping[str, Any]],
) -> dict[str, ScarcityComponents]:
    """Derive the six separated scarcity signals per position.

    Deliberately six numbers, not one.  ``eliteSeparation`` high with
    ``waiverScarcity`` low means "pay up for the top guy, stream the
    rest"; the reverse means "any starter is precious".  A single
    blended score cannot express that difference.
    """
    by_pos: dict[str, list[float]] = {}
    for team in teams:
        for p in team.get("players") or []:
            base = normalize_base_position(str(p.get("position") or ""))
            value = float(p.get("rosValue") or 0.0)
            if base and value > 0:  # unpriced players carry no signal
                by_pos.setdefault(base, []).append(value)
    for values in by_pos.values():
        values.sort(reverse=True)

    out: dict[str, ScarcityComponents] = {}
    for pos, rep in replacement.items():
        pool = by_pos.get(pos, [])
        top = pool[0] if pool else None
        starter = rep.value("starter")
        best_ball = rep.value("bestBallStarter")
        roster_lvl = rep.value("roster")
        waiver = rep.value("waiver")

        # Typical starter = median of the players above the starter
        # threshold; falls back to the pool median when unmeasurable.
        starters_n = max(1, round(rep.starters_per_team * max(1, len(teams))))
        starter_pool = pool[:starters_n] if pool else []
        median_starter = statistics.median(starter_pool) if starter_pool else None
        elite = pool[max(0, round(len(pool) * 0.05) - 1)] if pool else None

        out[pos] = ScarcityComponents(
            position=pos,
            lineup_scarcity=_safe_drop(top, starter),
            roster_scarcity=_safe_drop(starter, roster_lvl),
            waiver_scarcity=_safe_drop(best_ball, waiver),
            elite_separation=(
                (elite - median_starter)
                if elite is not None and median_starter is not None
                else None
            ),
            starter_separation=(
                (median_starter - starter)
                if median_starter is not None and starter is not None
                else None
            ),
            replacement_gap=(
                (best_ball - waiver) if best_ball is not None and waiver is not None else None
            ),
        )
    return out
