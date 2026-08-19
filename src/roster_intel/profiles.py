"""Per-position roster profiles, built ON the marginal engine.

Every strength-flavoured field here derives from
``marginal.position_marginals`` / ``absence_impacts`` — i.e. from
re-solving the exact lineup — never from summed value or headcount.
The descriptive fields (age, injury, bye, tier counts) are exactly
that: descriptive.  They are reported beside strength, not blended
into it, because a blend would let a young thin room and an old deep
room land on the same number.

Two judgements that need naming rather than burying:

* **Tiers are defined against league replacement levels**, not against
  a roster's own best player.  A roster-relative tier makes every team
  look like it has an elite player, which is how "everyone is 100.00"
  metrics get born.  Tiering against ``replacement.PositionReplacement``
  means a weak room reports zero elites and says so.

* **Surplus and need are lineup-derived, not count-derived.**  Surplus
  is priced value that does not enter the optimal lineup and is not
  needed as absence insurance.  Need is unfilled slots plus positions
  where a single absence collapses the group.  Counting bodies against
  a required-slot table would call five QBs "surplus 3" in a superflex
  league whether or not those QBs actually play.

Pure computation.  No I/O, no network, no clock: ``as_of_season`` is
supplied by the caller so age maths stay deterministic and testable.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping, Sequence

from src.league_intel.replacement import PositionReplacement, normalize_base_position
from src.roster_intel.marginal import (
    AbsenceImpact,
    PositionMarginal,
    RosterMarginals,
    absence_impacts,
    position_marginals,
)
from src.ros.lineup import RosterPlayer, is_priced, priced_players

__all__ = [
    "ELITE_PERCENTILE",
    "PositionProfile",
    "RosterProfile",
    "TIER_ORDER",
    "build_position_profiles",
    "classify_tier",
    "elite_threshold",
]

# Ordered best → worst.  A player sits in the highest tier whose
# threshold they clear.
TIER_ORDER = ("elite", "starter", "depth", "developmental")

# A position is "urgent" when the optimizer cannot fill its slots, or
# when losing one starter erases this share of the group's contribution.
_URGENT_FRAGILITY = 0.75
# Surplus must be worth at least this share of the position's starter
# replacement level before it is called tradeable — otherwise every
# bench dart throw reads as an asset.
_SURPLUS_FLOOR_RATIO = 0.60
# "elite" = top this share of a position's rostered priced pool. Matches
# the elite definition already in src/league_intel/replacement.py
# (compute_scarcity_components) so the word means one thing repo-wide.
ELITE_PERCENTILE = 0.05


def elite_threshold(position_values: Sequence[float]) -> float | None:
    """The top-``ELITE_PERCENTILE`` value at one position.

    Deliberately the SAME definition ``src/league_intel/replacement.py``
    already uses for ``eliteSeparation`` (``pool[round(n * 0.05) - 1]``
    over the descending position pool), so the two do not drift into
    two different meanings of the word "elite".

    Reachable by construction: the result is an actual member of the
    pool, so at least one player always clears it. That property is the
    whole point — see :func:`classify_tier`.

    ``None`` when nothing at the position is priced.
    """
    vals = sorted((float(v) for v in position_values if v and v > 0), reverse=True)
    if not vals:
        return None
    return vals[max(0, round(len(vals) * ELITE_PERCENTILE) - 1)]


def classify_tier(
    value: float,
    replacement: PositionReplacement | None,
    *,
    elite: float | None = None,
) -> str:
    """Bucket one player against the league's replacement levels.

    Tiers, best → worst:

    ``elite``          top-5% of the position's rostered priced pool
    ``starter``        at or above the typical last starter
    ``depth``          at or above the last player worth rostering
    ``developmental``  everything else, and everything unmeasurable

    **``elite`` is a distribution percentile, not a replacement level,
    because no replacement level can express it.** The four levels in
    ``replacement.py`` are all *floors* — ``starter`` is the median
    team's weakest starter and ``bestBallStarter`` is the deepest
    anyone dips, which is BELOW it by construction (mean of the lowest
    marginals vs. their median). An earlier version of this function
    read ``bestBallStarter`` as the elite bar. That is inverted: it set
    the top tier at the startable floor, so anything reaching
    ``starter`` had already returned ``elite``, the ``starter`` tier was
    unreachable, and ~65-78% of every rostered player classified elite.

    ``elite`` is therefore only honoured when it is strictly above
    ``starter``. If a caller supplies nothing, or supplies a threshold
    that does not separate, no player is promoted — an unmeasurable
    boundary must not promote, which is the same rule that sends a
    position with no levels at all to ``developmental``.

    Args:
        value: the player's ROS value.
        replacement: the position's measured levels.
        elite: the position's elite threshold, from
            :func:`elite_threshold`. Omitted ⇒ the ``elite`` tier is
            not assigned.
    """
    if replacement is None or value <= 0:
        return "developmental"
    starter = replacement.value("starter")
    roster = replacement.value("roster")
    # Strict ladder. `elite` is ignored unless it genuinely separates
    # from `starter`, otherwise the top tier swallows the one below it.
    if elite is not None and starter is not None and elite > starter and value >= elite:
        return "elite"
    if starter is not None and value >= starter:
        return "starter"
    if roster is not None and value >= roster:
        return "depth"
    return "developmental"


@dataclass(frozen=True)
class PositionProfile:
    """One position on one roster."""

    position: str

    # ── strength (all lineup-derived) ──
    marginal_points: float
    marginal_share: float
    entry_rate: float
    entered_lineup: int
    fragility: float
    worst_absence_drop: float

    # ── structure ──
    rostered: int
    required_slots: int
    tier_counts: dict[str, int] = field(default_factory=dict)

    # ── exposure (descriptive, never blended into strength) ──
    mean_age: float | None = None
    age_over_28: int = 0
    injured_count: int = 0
    injured_starters: int = 0
    bye_concentration: float | None = None

    # ── market position ──
    # The position's starter REPLACEMENT LEVEL, not a gap. Consumers
    # multiply it by unfilled slots (see partner.py::_need_alignment), so
    # the value has always been a level; only the name was wrong.
    replacement_level: float | None = None
    tradeable_surplus: float = 0.0
    surplus_players: tuple[str, ...] = ()
    urgent_need: bool = False
    need_reasons: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {
            "position": self.position,
            # NOT points — see ``marginal.py::PositionMarginal.to_dict``.
            # ``marginalPoints`` is a deprecated alias kept for one release.
            "marginalStrengthIndex": round(self.marginal_points, 3),
            "marginalPoints": round(self.marginal_points, 3),  # deprecated alias
            "marginalShare": round(self.marginal_share, 4),
            "entryRate": round(self.entry_rate, 4),
            "enteredLineup": self.entered_lineup,
            "fragility": round(self.fragility, 4),
            "worstAbsenceDrop": round(self.worst_absence_drop, 3),
            "rostered": self.rostered,
            "requiredSlots": self.required_slots,
            "tierCounts": dict(self.tier_counts),
            "meanAge": round(self.mean_age, 2) if self.mean_age is not None else None,
            "ageOver28": self.age_over_28,
            "injuredCount": self.injured_count,
            "injuredStarters": self.injured_starters,
            "byeConcentration": (
                round(self.bye_concentration, 4) if self.bye_concentration is not None else None
            ),
            # ``replacementGap`` is a deprecated alias: the value is and
            # always was the starter replacement LEVEL, not a gap.
            "replacementLevel": (
                round(self.replacement_level, 3) if self.replacement_level is not None else None
            ),
            "replacementGap": (
                round(self.replacement_level, 3) if self.replacement_level is not None else None
            ),
            "tradeableSurplus": round(self.tradeable_surplus, 3),
            "surplusPlayers": list(self.surplus_players),
            "urgentNeed": self.urgent_need,
            "needReasons": list(self.need_reasons),
        }


@dataclass(frozen=True)
class RosterProfile:
    """Every position on one roster, plus the solve it derives from."""

    lineup_score: float
    filled_slots: int
    total_slots: int
    positions: dict[str, PositionProfile] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "lineupScore": round(self.lineup_score, 3),
            "filledSlots": self.filled_slots,
            "totalSlots": self.total_slots,
            "positions": {k: v.to_dict() for k, v in sorted(self.positions.items())},
        }


def _required_slots(slots: Sequence[str]) -> dict[str, int]:
    """Dedicated slot count per position.

    FLEX / SUPER_FLEX / IDP_FLEX are deliberately NOT attributed to any
    position: who fills them is endogenous (LI-5 measured QB taking
    SUPER_FLEX 9 times in 12, TE taking FLEX zero times).  Splitting
    them by assumption is the error that made the old even-split
    demand numbers wrong by 40% at QB.
    """
    out: dict[str, int] = {}
    for slot in slots:
        s = normalize_base_position(str(slot).upper())
        if s in {"FLEX", "SUPER_FLEX", "IDP_FLEX", "BN"}:
            continue
        out[s] = out.get(s, 0) + 1
    return out


def _bye_concentration(byes: Sequence[int]) -> float | None:
    """Share of the position's players sharing its most common bye week.

    1.0 means the whole room is off the same week — the case that
    silently zeroes a position.  ``None`` when no bye data is supplied.
    """
    known = [b for b in byes if b]
    if not known:
        return None
    counts: dict[int, int] = {}
    for b in known:
        counts[b] = counts.get(b, 0) + 1
    return max(counts.values()) / len(known)


def build_position_profiles(
    pool: Sequence[RosterPlayer],
    slots: Sequence[str],
    *,
    replacement: Mapping[str, PositionReplacement] | None = None,
    player_meta: Mapping[str, Mapping[str, Any]] | None = None,
    as_of_season: int | None = None,
    marginals: RosterMarginals | None = None,
    league_position_values: Mapping[str, Sequence[float]] | None = None,
) -> RosterProfile:
    """Profile every position on one roster.

    Args:
        pool: the roster, already eligibility-enriched (see
            ``roster_source.build_roster_pool`` — position-only rows
            silently understate IDP).
        slots: the league's flattened starter slots.
        replacement: league replacement levels for tiering. Omitted ⇒
            every player tiers as ``developmental`` and tier counts
            carry no signal, which is the honest degradation.
        player_meta: ``{player_id: {"age": int, "byeWeek": int}}``.
        as_of_season: reserved for age-at-season maths; ages are taken
            from ``player_meta`` as supplied so this stays clock-free.
        marginals: reuse a prior solve (the expensive part).
        league_position_values: ``{base_position: [ros_value, ...]}``
            across every rostered priced player in the LEAGUE, used for
            the top-5% ``elite`` cut. This roster alone is far too small
            a sample — 2-5 players at a position — so omitting it means
            no player tiers ``elite`` rather than tiering against noise.
    """
    pool_list = list(pool)
    slots_list = list(slots)
    marg = marginals or position_marginals(pool_list, slots_list)
    absence = absence_impacts(pool_list, slots_list)
    required = _required_slots(slots_list)
    meta = player_meta or {}

    # Which players actually entered the optimal lineup.
    from src.roster_intel.marginal import solve_summary  # local: avoids cycle at import

    entered_ids = solve_summary(pool_list, slots_list).assigned_ids

    by_pos: dict[str, list[RosterPlayer]] = {}
    for p in pool_list:
        base = normalize_base_position(p.position)
        if base:
            by_pos.setdefault(base, []).append(p)

    profiles: dict[str, PositionProfile] = {}
    for pos, players in by_pos.items():
        pm: PositionMarginal | None = marg.by_position.get(pos)
        ai: AbsenceImpact | None = absence.get(pos)
        rep = (replacement or {}).get(pos)

        elite_cut = elite_threshold((league_position_values or {}).get(pos, ()))

        tier_counts = {t: 0 for t in TIER_ORDER}
        for p in players:
            # A tier is a claim about value; UNKNOWN makes none.
            if not is_priced(p):
                continue
            tier_counts[classify_tier(p.ros_value, rep, elite=elite_cut)] += 1

        ages = [
            float(meta.get(p.player_id, {}).get("age"))
            for p in players
            if meta.get(p.player_id, {}).get("age") is not None
        ]
        byes = [int(meta.get(p.player_id, {}).get("byeWeek") or 0) for p in players]

        injured = [p for p in players if p.injured]
        injured_starters = [p for p in injured if p.player_id in entered_ids]

        # Surplus: priced, does NOT enter the lineup, and clears a
        # meaningful share of the starter replacement level. The floor
        # stops every bench dart throw reading as a tradeable asset.
        starter_level = rep.value("starter") if rep else None
        floor = (starter_level or 0.0) * _SURPLUS_FLOOR_RATIO
        surplus = [
            p
            for p in players
            if is_priced(p)
            and p.ros_value > 0
            and p.player_id not in entered_ids
            and p.ros_value >= floor
        ]

        # Need: the optimizer could not fill this position's dedicated
        # slots, or one absence collapses the group.
        need_reasons: list[str] = []
        req = required.get(pos, 0)
        entered = pm.entered_lineup if pm else 0
        if req and entered < req:
            need_reasons.append(f"only {entered} of {req} dedicated {pos} slots filled")
        if ai and ai.fragility >= _URGENT_FRAGILITY:
            need_reasons.append(
                f"one absence costs {ai.fragility:.0%} of an average starter's value"
            )
        if req and not players:
            need_reasons.append(f"no {pos} rostered")

        profiles[pos] = PositionProfile(
            position=pos,
            marginal_points=pm.marginal_points if pm else 0.0,
            marginal_share=pm.marginal_share if pm else 0.0,
            entry_rate=pm.entry_rate if pm else 0.0,
            entered_lineup=entered,
            fragility=ai.fragility if ai else 0.0,
            worst_absence_drop=ai.worst_drop if ai else 0.0,
            rostered=len(players),
            required_slots=req,
            tier_counts=tier_counts,
            mean_age=(sum(ages) / len(ages)) if ages else None,
            age_over_28=sum(1 for a in ages if a > 28),
            injured_count=len(injured),
            injured_starters=len(injured_starters),
            bye_concentration=_bye_concentration(byes),
            replacement_level=(rep.value("starter") if rep else None),
            tradeable_surplus=float(sum(p.ros_value for p in priced_players(surplus))),
            surplus_players=tuple(sorted(p.canonical_name or p.player_id for p in surplus)),
            urgent_need=bool(need_reasons),
            need_reasons=tuple(need_reasons),
        )

    # Positions the league requires that the roster carries NONE of.
    for pos, req in required.items():
        if pos in profiles:
            continue
        profiles[pos] = PositionProfile(
            position=pos,
            marginal_points=0.0,
            marginal_share=0.0,
            entry_rate=0.0,
            entered_lineup=0,
            fragility=0.0,
            worst_absence_drop=0.0,
            rostered=0,
            required_slots=req,
            tier_counts={t: 0 for t in TIER_ORDER},
            urgent_need=True,
            need_reasons=(f"no {pos} rostered",),
        )

    return RosterProfile(
        lineup_score=marg.lineup_score,
        filled_slots=marg.filled_slots,
        total_slots=marg.total_slots,
        positions=profiles,
    )
