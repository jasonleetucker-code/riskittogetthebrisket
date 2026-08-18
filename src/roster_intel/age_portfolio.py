"""Roster Age-Value Portfolio / Young Core Index (row 1.6, #838).

League-relative age/value intelligence over the canonical meaningful
core: how a roster's dynasty value is distributed across ages, which
rooms are old relative to the league, and who owns the strongest
concentration of meaningful young talent.

Binding requirement:
``docs/OWNER_FEATURE_ADDENDUM_2026-08-14_AGE_VALUE_PORTFOLIO.md``.

THE guardrail
=============

    Do **not** create a second age-adjusted player valuation. Canonical
    dynasty value already embeds age and market expectations. This
    feature describes roster construction; it does not alter player
    value.

Nothing in this module returns a player value.  Age is only ever a
*weight's subject* — every statistic here is an aggregate **of** values
it was handed, and the one composite (:attr:`TeamAgePortfolio.young_core_index`)
is a percentile of a value-weighted youth score, not a currency.
:func:`build_age_portfolio` never sees a mutable value and never emits
one.

Three ways this metric goes wrong, and what stops each
======================================================

**Low-value youth dominating.**  A roster full of 21-year-old bench
darts is not young; it is bad.  Two guards, both structural rather than
tuned: the population is the **meaningful core** (which already excluded
those players), and within it every youth score is weighted by canonical
value, so a 21-year-old worth 300 moves the number ~1/30th as far as a
26-year-old worth 9000.

**Position-blind youth.**  A 27-year-old QB is young; a 27-year-old
running back is not.  Youth is therefore scored as a **position-relative
percentile** — the share of that position's league population who are
older — so QB and RB ages are never compared on one axis.

**Missing age read as young.**  A player with no DOB is excluded from
both the numerator and the denominator, and the coverage is reported
(:attr:`AgeCoverage`).  Treating unknown as 0, or as the mean, would let
an identity-join miss manufacture a young roster.  A team with no aged
players at all gets ``None``, never 0.0 — and 0.0 would read as "very
old" on the age axis and "no youth" on the index axis, i.e. wrong in
opposite directions depending on the field.

**Draft picks are not age-zero.**  Picks carry no age and are excluded
from age math by the addendum.  They are excluded here structurally,
because they are not eligible players and therefore never enter the
meaningful core in the first place — see
``core.build_meaningful_core``'s ``pool`` contract.

Status
======
The index is a **PRIOR**.  The addendum requires it be *"validated
against intuitive league examples before treating it as canonical"*;
that validation has not been run, so ``YOUNG_CORE_INDEX_STATUS`` says
``PRIOR`` and every payload carries it.

Pure computation.  No I/O, no network, no clock — ``as_of_season`` is
supplied by the caller so age maths stay deterministic and testable.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from typing import Any, Iterable, Mapping

from src.league_intel.replacement import normalize_base_position
from src.roster_intel.core import CoreMember, MeaningfulCore
from src.roster_intel.strength import POSITION_GROUPS

__all__ = [
    "AGE_BANDS",
    "AgeCoverage",
    "PositionAgeProfile",
    "TeamAgePortfolio",
    "YOUNG_CORE_INDEX_STATUS",
    "YouthCurve",
    "build_age_portfolio",
    "build_youth_curve",
    "rank_age_portfolios",
]

#: Reported alongside the per-age detail, never instead of it.  Bands
#: are for reading; the per-age series is the data.
AGE_BANDS: tuple[tuple[str, float, float], ...] = (
    ("21_and_under", 0.0, 21.999),
    ("22_24", 22.0, 24.999),
    ("25_27", 25.0, 27.999),
    ("28_30", 28.0, 30.999),
    ("31_plus", 31.0, 200.0),
)

YOUNG_CORE_INDEX_STATUS = "PRIOR"


@dataclass(frozen=True)
class AgeCoverage:
    """How much of a population we could actually age.

    Published on every age statistic because a value-weighted age over
    40% of a roster is a different claim from one over all of it, and
    the two must not render identically.
    """

    aged_players: int = 0
    total_players: int = 0
    aged_value: float = 0.0
    total_value: float = 0.0

    @property
    def value_share(self) -> float | None:
        """Share of the population's VALUE we could age.

        Value-weighted rather than headcount-weighted because that is
        what the statistic it qualifies is weighted by.  ``None`` when
        there is no value at all — a share of nothing is not 0%.
        """
        if self.total_value <= 0:
            return None
        return self.aged_value / self.total_value

    def to_dict(self) -> dict[str, Any]:
        return {
            "agedPlayers": self.aged_players,
            "totalPlayers": self.total_players,
            "agedValue": round(self.aged_value, 3),
            "totalValue": round(self.total_value, 3),
            "valueShare": (round(self.value_share, 4) if self.value_share is not None else None),
        }


@dataclass(frozen=True)
class YouthCurve:
    """Position-relative youth, measured from a real league population.

    ``by_position`` maps a position to its ascending list of observed
    ages.  :meth:`youth_score` reads a player's share of that
    population who are OLDER — 1.0 is the youngest observed, 0.0 the
    oldest — so QB and RB are never compared on one axis.

    Measured, not assumed.  There is no positional age table here and
    no curve constant to tune: the league's own ages define what young
    means at each position.
    """

    by_position: Mapping[str, tuple[float, ...]] = field(default_factory=dict)

    def youth_score(self, position: str, age: float | None) -> float | None:
        """``None`` when unmeasurable — no age, or no population to
        compare against.  Never 0.0, which would mean "oldest in the
        league"."""
        if age is None:
            return None
        pool = self.by_position.get(normalize_base_position(position))
        if not pool:
            return None
        if len(pool) == 1:
            # A population of one cannot express relative youth. 0.5 is
            # the honest centre, not a measurement — and it is recorded
            # as such by the coverage this feeds.
            return 0.5
        older = sum(1 for a in pool if a > age)
        return older / (len(pool) - 1) if older <= len(pool) - 1 else 1.0


def build_youth_curve(
    players: Iterable[tuple[str, float | None]],
) -> YouthCurve:
    """Build the league's positional age population.

    ``players`` is ``(position, age)`` over the league's whole
    comparison population.  Ageless players are excluded — an unknown
    age must not shift the curve it is measured against.
    """
    buckets: dict[str, list[float]] = {}
    for position, age in players:
        if age is None:
            continue
        buckets.setdefault(normalize_base_position(position), []).append(float(age))
    return YouthCurve(by_position={k: tuple(sorted(v)) for k, v in buckets.items()})


@dataclass(frozen=True)
class PositionAgeProfile:
    """One position group's age/value profile on one roster."""

    position: str
    value: float
    value_share: float | None
    value_weighted_age: float | None
    youth_score: float | None
    coverage: AgeCoverage = field(default_factory=AgeCoverage)
    league_rank: int | None = None
    league_percentile: float | None = None
    league_median_age: float | None = None

    @property
    def age_vs_league_median(self) -> float | None:
        """Years older than the league median for this room.  Positive
        is older.  ``None`` when either side is unmeasured."""
        if self.value_weighted_age is None or self.league_median_age is None:
            return None
        return self.value_weighted_age - self.league_median_age

    @property
    def is_old_for_league(self) -> bool:
        """The addendum's *"clear indication when the group is
        meaningfully older than league peers"*.

        A full year above the league median, which is a real gap at
        every position rather than measurement noise.  PRIOR, like the
        index.
        """
        delta = self.age_vs_league_median
        return delta is not None and delta >= 1.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "position": self.position,
            "value": round(self.value, 3),
            "valueShare": round(self.value_share, 4) if self.value_share is not None else None,
            "valueWeightedAge": (
                round(self.value_weighted_age, 2) if self.value_weighted_age is not None else None
            ),
            "youthScore": round(self.youth_score, 4) if self.youth_score is not None else None,
            "coverage": self.coverage.to_dict(),
            "leagueRank": self.league_rank,
            "leaguePercentile": (
                round(self.league_percentile, 4) if self.league_percentile is not None else None
            ),
            "leagueMedianAge": (
                round(self.league_median_age, 2) if self.league_median_age is not None else None
            ),
            "ageVsLeagueMedian": (
                round(self.age_vs_league_median, 2)
                if self.age_vs_league_median is not None
                else None
            ),
            "isOldForLeague": self.is_old_for_league,
        }


@dataclass(frozen=True)
class TeamAgePortfolio:
    """One team's age-value portfolio over its meaningful core."""

    value_weighted_core_age: float | None = None
    #: Secondary context per the addendum — the same statistic over the
    #: WHOLE roster.  ``None`` when the caller supplied no full roster.
    value_weighted_roster_age: float | None = None
    #: Value-weighted position-relative youth, 0-1.  The index's input.
    core_youth_score: float | None = None
    #: 0-100 league percentile of ``core_youth_score``.  ``None`` until
    #: ranked against a league — a team alone has no league-relative
    #: index, and 50.0 would be an invented middle.
    young_core_index: float | None = None
    by_position: dict[str, PositionAgeProfile] = field(default_factory=dict)
    #: Value at each observed age, and at each band.  The per-age series
    #: is the data; bands are for reading.
    value_by_age: dict[float, float] = field(default_factory=dict)
    value_by_band: dict[str, float] = field(default_factory=dict)
    coverage: AgeCoverage = field(default_factory=AgeCoverage)
    league_rank: int | None = None
    league_percentile: float | None = None
    available: bool = True
    unavailable_reason: str | None = None

    def to_dict(self) -> dict[str, Any]:
        ordered = [p for p in POSITION_GROUPS if p in self.by_position]
        ordered += sorted(p for p in self.by_position if p not in POSITION_GROUPS)
        return {
            "available": self.available,
            "unavailableReason": self.unavailable_reason,
            "valueWeightedCoreAge": (
                round(self.value_weighted_core_age, 2)
                if self.value_weighted_core_age is not None
                else None
            ),
            "valueWeightedRosterAge": (
                round(self.value_weighted_roster_age, 2)
                if self.value_weighted_roster_age is not None
                else None
            ),
            "coreYouthScore": (
                round(self.core_youth_score, 4) if self.core_youth_score is not None else None
            ),
            "youngCoreIndex": (
                round(self.young_core_index, 1) if self.young_core_index is not None else None
            ),
            "youngCoreIndexStatus": YOUNG_CORE_INDEX_STATUS,
            "byPosition": [self.by_position[p].to_dict() for p in ordered],
            "valueByAge": [
                {"age": age, "value": round(v, 3)} for age, v in sorted(self.value_by_age.items())
            ],
            "valueByBand": [
                {"band": name, "value": round(self.value_by_band.get(name, 0.0), 3)}
                for name, _, _ in AGE_BANDS
            ],
            "coverage": self.coverage.to_dict(),
            "leagueRank": self.league_rank,
            "leaguePercentile": (
                round(self.league_percentile, 4) if self.league_percentile is not None else None
            ),
        }


def build_age_portfolio(
    core: MeaningfulCore,
    ages: Mapping[str, float | None],
    *,
    youth: YouthCurve | None = None,
    full_roster: Iterable[tuple[str, float]] | None = None,
) -> TeamAgePortfolio:
    """Build one team's age-value portfolio over its meaningful core.

    Args:
        core: the canonical meaningful population.  Its refusal
            propagates — an unreadable roster has no age, and reporting
            one would invent it.
        ages: ``{player_id: age}``.  A missing key and an explicit
            ``None`` mean the same thing and are both excluded from the
            maths, never defaulted.
        youth: the league's positional age population, from
            :func:`build_youth_curve`.  Omitted ⇒ youth scores are
            ``None`` and no index is produced, which is the honest
            degradation: position-relative youth is undefined without a
            population to be relative to.
        full_roster: ``(player_id, value)`` over the WHOLE roster, for
            the addendum's secondary full-roster age.  Omitted ⇒
            ``None``, never a number.
    """
    if not core.available:
        return TeamAgePortfolio(available=False, unavailable_reason=core.unavailable_reason)

    members = core.members
    coverage = _coverage(members, ages)

    by_position: dict[str, PositionAgeProfile] = {}
    total_value = float(sum(m.value for m in members))
    # Already family-keyed — see the note in ``strength.build_team_strength``.
    for position, group in core.by_position().items():
        merged = list(group)
        group_value = float(sum(m.value for m in merged))
        by_position[position] = PositionAgeProfile(
            position=position,
            value=group_value,
            value_share=(group_value / total_value) if total_value > 0 else None,
            value_weighted_age=_value_weighted_age(merged, ages),
            youth_score=_value_weighted_youth(merged, ages, youth),
            coverage=_coverage(merged, ages),
        )

    value_by_age: dict[float, float] = {}
    for member in members:
        age = _age_of(member, ages)
        if age is None:
            continue
        value_by_age[age] = value_by_age.get(age, 0.0) + member.value

    return TeamAgePortfolio(
        value_weighted_core_age=_value_weighted_age(members, ages),
        value_weighted_roster_age=(
            _value_weighted_pairs(full_roster, ages) if full_roster is not None else None
        ),
        core_youth_score=_value_weighted_youth(members, ages, youth),
        by_position=by_position,
        value_by_age=value_by_age,
        value_by_band=_bands(value_by_age),
        coverage=coverage,
    )


def _age_of(member: CoreMember, ages: Mapping[str, float | None]) -> float | None:
    raw = ages.get(member.player_id)
    if raw is None:
        return None
    try:
        age = float(raw)
    except (TypeError, ValueError):
        return None
    # A non-positive age is not an age.  Sleeper occasionally carries 0
    # for an unresolved record, and 0 is exactly the value that would
    # make a roster look historically young.
    return age if age > 0 else None


def _coverage(members: Iterable[CoreMember], ages: Mapping[str, float | None]) -> AgeCoverage:
    members = list(members)
    aged = [m for m in members if _age_of(m, ages) is not None]
    return AgeCoverage(
        aged_players=len(aged),
        total_players=len(members),
        aged_value=float(sum(m.value for m in aged)),
        total_value=float(sum(m.value for m in members)),
    )


def _value_weighted_age(
    members: Iterable[CoreMember], ages: Mapping[str, float | None]
) -> float | None:
    """``Σ(age × value) / Σ(value)`` over members we could age.

    Ageless members leave BOTH sums, so they neither pull the average
    nor dilute it.  ``None`` when nothing could be aged or the aged
    value is zero — a weighted mean with no weight is undefined, and
    returning 0.0 would read as an impossibly young roster.
    """
    numerator = 0.0
    denominator = 0.0
    for member in members:
        age = _age_of(member, ages)
        if age is None:
            continue
        numerator += age * member.value
        denominator += member.value
    return numerator / denominator if denominator > 0 else None


def _value_weighted_pairs(
    pairs: Iterable[tuple[str, float]], ages: Mapping[str, float | None]
) -> float | None:
    """The same statistic over raw ``(player_id, value)`` rows."""
    numerator = 0.0
    denominator = 0.0
    for player_id, value in pairs:
        raw = ages.get(player_id)
        if raw is None:
            continue
        try:
            age = float(raw)
        except (TypeError, ValueError):
            continue
        if age <= 0:
            continue
        numerator += age * float(value)
        denominator += float(value)
    return numerator / denominator if denominator > 0 else None


def _value_weighted_youth(
    members: Iterable[CoreMember],
    ages: Mapping[str, float | None],
    youth: YouthCurve | None,
) -> float | None:
    """Value-weighted position-relative youth, 0-1.

    This is the line that stops low-value youth dominating: a player's
    youth counts in proportion to what he is worth, so a 21-year-old
    worth 300 moves the number a thirtieth as far as a 26-year-old worth
    9000.
    """
    if youth is None:
        return None
    numerator = 0.0
    denominator = 0.0
    for member in members:
        score = youth.youth_score(member.position, _age_of(member, ages))
        if score is None:
            continue
        numerator += score * member.value
        denominator += member.value
    return numerator / denominator if denominator > 0 else None


def _bands(value_by_age: Mapping[float, float]) -> dict[str, float]:
    out = {name: 0.0 for name, _, _ in AGE_BANDS}
    for age, value in value_by_age.items():
        for name, low, high in AGE_BANDS:
            if low <= age <= high:
                out[name] += value
                break
    return out


def rank_age_portfolios(
    by_team: Mapping[str, TeamAgePortfolio],
) -> dict[str, TeamAgePortfolio]:
    """Stamp league rank, percentile, the 0-100 Young Core Index and each
    room's league median age.

    The index is the league percentile of ``core_youth_score`` scaled to
    0-100 — the addendum's *"aggregate the meaningful core, then
    league-percentile the result"*.  Percentiling last is what makes it
    league-RELATIVE: an absolute youth score would drift with the NFL's
    age distribution rather than with roster construction.

    Teams with no measurable youth score are excluded from the ranking
    population and keep ``None``.  Ranking them would place a roster we
    could not age among rosters we could, and the position would be an
    artifact of the join, not of the roster.
    """
    ranked: dict[str, TeamAgePortfolio] = {}
    measurable = {
        k: v for k, v in by_team.items() if v.available and v.core_youth_score is not None
    }
    n = len(measurable)
    order = _rank_map({k: v.core_youth_score or 0.0 for k, v in measurable.items()})

    # League median age per position, over teams that could measure it.
    medians: dict[str, float] = {}
    positions = {p for v in by_team.values() for p in v.by_position}
    for position in positions:
        observed = sorted(
            v.by_position[position].value_weighted_age
            for v in by_team.values()
            if position in v.by_position and v.by_position[position].value_weighted_age is not None
        )
        if observed:
            medians[position] = _median(observed)

    for key, portfolio in by_team.items():
        positions_out = {
            position: replace(
                profile,
                league_median_age=medians.get(position),
                league_rank=_position_rank(by_team, position, key),
                league_percentile=_percentile(
                    _position_rank(by_team, position, key),
                    _position_population(by_team, position),
                ),
            )
            for position, profile in portfolio.by_position.items()
        }
        if key not in measurable:
            ranked[key] = replace(portfolio, by_position=positions_out)
            continue
        rank = order[key]
        percentile = _percentile(rank, n)
        ranked[key] = replace(
            portfolio,
            by_position=positions_out,
            league_rank=rank,
            league_percentile=percentile,
            # A one-team league has no percentile, so it has no index.
            young_core_index=(percentile * 100.0) if percentile is not None else None,
        )
    return ranked


def _position_population(by_team: Mapping[str, TeamAgePortfolio], position: str) -> int:
    return sum(
        1
        for v in by_team.values()
        if position in v.by_position and v.by_position[position].youth_score is not None
    )


def _position_rank(by_team: Mapping[str, TeamAgePortfolio], position: str, key: str) -> int | None:
    """Rank of one team's room by value-weighted youth — the addendum's
    per-position "youngest valuable room" leaderboards."""
    scores = {
        k: v.by_position[position].youth_score
        for k, v in by_team.items()
        if position in v.by_position and v.by_position[position].youth_score is not None
    }
    if key not in scores:
        return None
    return _rank_map(scores)[key]


def _rank_map(values: Mapping[str, float]) -> dict[str, int]:
    """Competition ranking, 1 = highest (youngest-and-most-valuable)."""
    ordered = sorted(values.items(), key=lambda kv: (-kv[1], kv[0]))
    out: dict[str, int] = {}
    last_value: float | None = None
    last_rank = 0
    for i, (key, value) in enumerate(ordered, start=1):
        if last_value is not None and value == last_value:
            out[key] = last_rank
        else:
            out[key] = i
            last_rank = i
            last_value = value
    return out


def _percentile(rank: int | None, n: int) -> float | None:
    if rank is None or n <= 1:
        return None
    return (n - rank) / (n - 1)


def _median(values: list[float]) -> float:
    mid = len(values) // 2
    if len(values) % 2:
        return values[mid]
    return (values[mid - 1] + values[mid]) / 2
