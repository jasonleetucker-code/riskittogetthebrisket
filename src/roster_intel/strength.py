"""THE canonical Team Strength owner (feature-inventory row 1.1).

One answer to *"how strong is this dynasty roster"*, computed over the
canonical :mod:`src.roster_intel.core` meaningful population rather than
over whatever set each consumer happened to select.

Row 1.1 records the state this replaces: Team Strength *"does not exist
as a single owner. Multiple partial notions exist and disagree"*.

What this is NOT, stated up front
==================================

Three neighbouring quantities exist and are **not** merged here, because
each answers a different question and collapsing them is what produced
the disagreement in the first place:

``/api/terminal``'s ``totalValue``
    A raw sum of ``rankDerivedValue`` over the WHOLE roster (W20-F003) —
    a **portfolio** total, not a strength.  It is a real quantity with
    real consumers, so it is not deleted; it is renamed in this module's
    vocabulary as ``full_roster_value`` and published **beside**
    ``total`` so the two can never be read as the same number.  On a
    deep best-ball roster they are far apart by construction: a 58-man
    roster books bench player #40 at full market value.

``src/ros/`` ROS 0-100 strength
    Rest-of-season PRODUCTION. ``MASTER_PRODUCT_PLAN.md`` §4.1 is
    explicit: *"Team Strength is dynasty roster strength; it is not
    Power Ranking, Playoff Odds, or ROS production."*  Different
    product, different lane, untouched.

``roster_intel.marginal``
    Lineup-derived MARGINAL contribution — what a position adds to the
    optimal lineup.  A diagnostic about lineup structure, not a value
    aggregate.  ``profiles.py`` already builds on it and keeps doing so.

It creates no value
===================

Team Strength **aggregates** canonical values; it never computes one.
That boundary is the same one #822 enforced when it rejected the
league-aware overlay for canonical promotion and ruled it *"may not own
a canonical field"*.  Every number here is a sum, a share or a rank of
values this module received.

Aggregates are deliberately **uncapped**.  ``OWNER_FEATURE_INVENTORY``
row 7.5: individual player and pick values are a 1–9999 product scale,
but *"Aggregates are NOT capped — Team Strength, package totals,
roster/portfolio totals and other multi-asset sums may exceed 9999 and
must not be clamped."*

FLEX is not a column
====================

§5 of the FLEX addendum: a FLEX-assigned player's value *"still belongs
to the team and must be included in the overall meaningful-roster Team
Strength calculation"*, but FLEX *"does not have to create a new
displayed/sortable Team Strength position."*  So a FLEX-seated RB is
summed under **RB** — :meth:`MeaningfulCore.by_position` groups on
native position — and the flex fact survives only as the diagnostic
``CoreMember.slot``.

Pure computation.  No I/O, no network, no clock.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from typing import Any, Iterable, Mapping, Sequence

from src.roster_intel.core import CoreMember, MeaningfulCore

__all__ = [
    "POSITION_GROUPS",
    "PositionStrength",
    "TeamStrength",
    "build_team_strength",
    "rank_team_strengths",
]

#: The owner-approved sortable position groups (MASTER_PRODUCT_PLAN
#: §4.1, as amended by #899 — *"Sortable position groups stay QB / RB /
#: WR / TE / DL / LB / DB"*).  DL absorbs DE/DT/EDGE through
#: ``normalize_base_position``; there is no separate EDGE group because
#: the lineup owner names no EDGE slot.
#:
#: This is a DISPLAY ORDER, not a filter.  A group outside it (K, or an
#: exotic slot a league configures) still contributes to ``total`` and
#: still appears in ``by_position`` — dropping it would make the parts
#: stop summing to the whole, which is a worse defect than an extra row.
POSITION_GROUPS: tuple[str, ...] = ("QB", "RB", "WR", "TE", "DL", "LB", "DB")


@dataclass(frozen=True)
class PositionStrength:
    """One position group on one roster."""

    position: str
    value: float
    count: int
    starter_value: float
    starter_count: int
    reserve_value: float
    reserve_count: int
    members: tuple[str, ...] = ()
    #: League rank (1 = strongest) and percentile, when a cohort was
    #: supplied.  ``None`` means NOT MEASURED — there was no league to
    #: rank against — never "last".
    league_rank: int | None = None
    league_percentile: float | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "position": self.position,
            "value": round(self.value, 3),
            "count": self.count,
            "starterValue": round(self.starter_value, 3),
            "starterCount": self.starter_count,
            "reserveValue": round(self.reserve_value, 3),
            "reserveCount": self.reserve_count,
            "members": list(self.members),
            "leagueRank": self.league_rank,
            "leaguePercentile": (
                round(self.league_percentile, 4) if self.league_percentile is not None else None
            ),
        }


@dataclass(frozen=True)
class TeamStrength:
    """Canonical Team Strength for ONE team.

    ``total`` is the meaningful-core figure — THE Team Strength number.
    ``full_roster_value`` is the whole-roster portfolio sum, published
    beside it as explicitly named context (see the module docstring).
    ``None`` when the caller supplied no full roster, because an absent
    portfolio must not read as a portfolio worth nothing.
    """

    total: float = 0.0
    starter_value: float = 0.0
    reserve_value: float = 0.0
    by_position: dict[str, PositionStrength] = field(default_factory=dict)
    full_roster_value: float | None = None
    unpriced_ids: frozenset[str] = frozenset()
    #: Slots the core could not fill.  A team missing two starters is
    #: not simply weaker — part of its strength is UNMEASURED, and a
    #: consumer comparing it to a full roster should say so.
    unfilled_starter_slots: tuple[str, ...] = ()
    unfilled_reserve_slots: tuple[str, ...] = ()
    league_rank: int | None = None
    league_percentile: float | None = None
    available: bool = True
    unavailable_reason: str | None = None

    @property
    def is_complete(self) -> bool:
        """True when every demanded slot was filled and nothing was
        unpriceable — i.e. the total is a statement about the whole
        roster rather than about the part we could read."""
        return not (self.unfilled_starter_slots or self.unfilled_reserve_slots or self.unpriced_ids)

    def to_dict(self) -> dict[str, Any]:
        ordered = _ordered_groups(self.by_position)
        return {
            "available": self.available,
            "unavailableReason": self.unavailable_reason,
            "total": round(self.total, 3),
            "starterValue": round(self.starter_value, 3),
            "reserveValue": round(self.reserve_value, 3),
            "byPosition": [self.by_position[p].to_dict() for p in ordered],
            "positionOrder": list(ordered),
            "fullRosterValue": (
                round(self.full_roster_value, 3) if self.full_roster_value is not None else None
            ),
            "unpricedIds": sorted(self.unpriced_ids),
            "unpricedCount": len(self.unpriced_ids),
            "unfilledStarterSlots": list(self.unfilled_starter_slots),
            "unfilledReserveSlots": list(self.unfilled_reserve_slots),
            "isComplete": self.is_complete,
            "leagueRank": self.league_rank,
            "leaguePercentile": (
                round(self.league_percentile, 4) if self.league_percentile is not None else None
            ),
        }


def _ordered_groups(groups: Mapping[str, PositionStrength]) -> tuple[str, ...]:
    """Owner-declared groups first, in their declared order, then any
    others alphabetically so nothing is silently dropped."""
    declared = [p for p in POSITION_GROUPS if p in groups]
    extra = sorted(p for p in groups if p not in POSITION_GROUPS)
    return tuple(declared + extra)


def build_team_strength(
    core: MeaningfulCore,
    *,
    full_roster_values: Iterable[float] | None = None,
) -> TeamStrength:
    """Aggregate one team's canonical values over its meaningful core.

    Args:
        core: the canonical population from
            :func:`src.roster_intel.core.build_meaningful_core`.  A core
            that refused (``available=False``) propagates its refusal
            rather than reporting a strength of 0 — "we could not read
            this league's lineup" and "this roster is worthless" must
            not be the same number.
        full_roster_values: canonical values for the WHOLE roster, if the
            caller has them.  Summed into ``full_roster_value`` as named
            portfolio context.  Omitted ⇒ ``None``, never 0.
    """
    if not core.available:
        return TeamStrength(
            available=False,
            unavailable_reason=core.unavailable_reason,
            unpriced_ids=core.unpriced_ids,
        )

    # ``core.by_position()`` is ALREADY keyed by slot family: every
    # ``CoreMember.position`` went through ``lineup_position``, which
    # folds DE/DT/EDGE → DL and CB/S/FS/SS → DB.  So DE and DT arrive in
    # one group rather than two, and there is no re-normalisation or
    # group merge to do here — a merge step would be unreachable code
    # defending against a state the core cannot produce.  Pinned by
    # ``test_core.py::test_core_member_position_is_always_a_family_token``.
    by_position: dict[str, PositionStrength] = {}
    for pos, members in core.by_position().items():
        starters = [m for m in members if m.role == "starter"]
        reserves = [m for m in members if m.role == "reserve"]
        by_position[pos] = PositionStrength(
            position=pos,
            value=_sum(members),
            count=len(members),
            starter_value=_sum(starters),
            starter_count=len(starters),
            reserve_value=_sum(reserves),
            reserve_count=len(reserves),
            members=tuple(m.player_id for m in members),
        )

    return TeamStrength(
        total=_sum(core.members),
        starter_value=_sum(core.starters),
        reserve_value=_sum(core.reserves),
        by_position=by_position,
        full_roster_value=(
            float(sum(full_roster_values)) if full_roster_values is not None else None
        ),
        unpriced_ids=core.unpriced_ids,
        unfilled_starter_slots=core.unfilled_starter_slots,
        unfilled_reserve_slots=core.unfilled_reserve_slots,
    )


def _sum(members: Sequence[CoreMember]) -> float:
    return float(sum(m.value for m in members))


def rank_team_strengths(
    by_team: Mapping[str, TeamStrength],
) -> dict[str, TeamStrength]:
    """Stamp league rank + percentile onto every team, overall and per
    position group.

    Comparability is what makes Team Strength useful, and it is sound
    here for a structural reason: every team in a league is measured
    against the SAME slot list, so the core sizes match and the totals
    are like-for-like.  (This is also why rank belongs at league level
    and not inside ``build_team_strength`` — one team alone has no rank,
    and inventing one from a constant is how "everyone is 100.00"
    metrics get born.)

    Teams whose core REFUSED are excluded from the ranking population
    entirely — not ranked last.  Ranking an unreadable roster against
    readable ones would state that it is the weakest, which is a claim
    about evidence we do not have.  They come back with ``league_rank``
    ``None``.

    ``percentile`` is the share of OTHER teams this team is at or above,
    so a 12-team league runs 1.0 (best) down to 0.0 (worst) rather than
    bottoming out at 1/12.  Ties share the better rank, standard
    competition style.
    """
    ranked: dict[str, TeamStrength] = {}
    measurable = {k: v for k, v in by_team.items() if v.available}

    overall = _rank_map({k: v.total for k, v in measurable.items()})
    n = len(measurable)

    # Per-position ranks are computed over teams that HAVE the group.
    # A team with no LB at all is genuinely last in LB, so it is
    # included at its real value once the group exists in the league.
    groups = {p for v in measurable.values() for p in v.by_position}
    per_group = {
        pos: _rank_map(
            {
                k: v.by_position[pos].value if pos in v.by_position else 0.0
                for k, v in measurable.items()
            }
        )
        for pos in groups
    }

    for key, strength in by_team.items():
        if key not in measurable:
            ranked[key] = strength
            continue
        rank = overall[key]
        positions = {
            pos: replace(
                ps,
                league_rank=per_group[pos][key],
                league_percentile=_percentile(per_group[pos][key], n),
            )
            for pos, ps in strength.by_position.items()
        }
        ranked[key] = replace(
            strength,
            by_position=positions,
            league_rank=rank,
            league_percentile=_percentile(rank, n),
        )
    return ranked


def _rank_map(values: Mapping[str, float]) -> dict[str, int]:
    """Standard competition ranking, 1 = highest value.

    Ties get the same rank and the next rank skips, so rank is always a
    truthful position in the ordering.  Deterministic under equal
    values: the secondary key is the team key.
    """
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
    """Share of the league this rank is at or above.

    ``None`` when there is nothing to compare to — a one-team league has
    no percentile, and returning 1.0 would dress a missing comparison up
    as dominance.
    """
    if rank is None or n <= 1:
        return None
    return (n - rank) / (n - 1)
