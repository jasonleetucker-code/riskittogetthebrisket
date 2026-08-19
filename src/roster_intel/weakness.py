"""THE canonical Team Weakness / Need Priority owner (row 1.2).

Answers *"which starting slots is this roster not good enough at"* from
the same canonical assignment the rest of the lane uses.

The governing constraint is ``MASTER_PRODUCT_PLAN.md`` §4.1:

    Need Priority must agree with the canonical lineup/assignment solve.
    An ``urgentNeed`` flag that contradicts the actual roster solve is a
    defect, not an alternate opinion.

So weakness is **derived from** :class:`~src.roster_intel.core.MeaningfulCore`
rather than computed beside it.  There is no second roster walk, no
second starter definition, and no per-position count that could disagree
with who the solver actually seated.

The thresholds are ONE RULE, not a table
========================================

The owner's listed thresholds are QB1 top 12 / QB2 top 24, RB1 top 12 /
RB2 top 24, WR1 top 12 / WR2 top 24 / WR3 top 36, TE1 top 12 / TE2 top
24 — and, for IDP, *"derive from required slots × league size"*.

Those are not two rules.  Measured against ``dynasty_main``'s real
lineup (QB 1 + SFLEX 1 → QB demand 2 after the #839 fold, RB 2, WR 3,
TE 2) in a 12-team league, **every listed number is exactly
`k × teamCount` for the k-th starter rung**:

    QB → [12, 24]      RB → [12, 24]
    WR → [12, 24, 36]  TE → [12, 24]

So this module implements the IDP rule for every position and the
offensive table falls out of it.  That matters beyond tidiness: a
hard-coded table is silently wrong in the 10-team league
(``dynasty_new``), where a "top 12 RB1" is not the last startable RB1 —
``k × teamCount`` gives 10 there, which is what the rule always meant.

Why FLEX gets no rung ladder
============================

Because #899 says so, and because it would double-count.  A FLEX-seated
RB3 is still a running back; he is evaluated on the RB ladder like any
other RB, exactly once.  Giving FLEX its own rungs would require a
cross-position rank (is RB3 a better "flex" than WR4?), and #899's
answer to that question is the *assignment solve*, which has already
run.  Sortable groups stay QB/RB/WR/TE/DL/LB/DB.

Superflex is folded into QB demand, not added as a second QB need — the
same single fold ``core.reserve_demand`` applies, read straight off
``ReserveDemand.starter_basis`` so the two cannot drift.  That is what
"treat SF as a QB-eligible starter assignment rather than creating
misleading duplicate QB counts" means in code.

Missing is never weak
=====================

A rung whose player carries no positional rank is ``UNKNOWN``, not
failed.  A player we cannot rank is not a player who ranks badly, and
scoring him as a need would manufacture trade targets out of a join
miss.  ``UNKNOWN`` rungs are counted and reported separately from unmet
ones and never contribute to ``priority``.

Pure computation.  No I/O, no network, no clock.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Iterable, Mapping, Sequence

from src.league_intel.replacement import normalize_base_position
from src.roster_intel.core import CoreMember, MeaningfulCore

__all__ = [
    "NEED_LEVELS",
    "PositionNeed",
    "PositionRanks",
    "SlotRung",
    "TeamWeakness",
    "build_position_ranks",
    "build_team_weakness",
]

#: Worst → best.  A position takes the level of its worst rung.
NEED_LEVELS: tuple[str, ...] = ("critical", "high", "moderate", "none")

#: Escalation bands, measured as SHORTFALL ÷ THRESHOLD — how far past
#: its bar a rung's holder sits, relative to the size of that bar.
#:
#: On a top-24 QB2 rung: QB30 is a shortfall of 6, i.e. 0.25 → moderate;
#: QB50 is 26, i.e. 1.08 → high; QB80 is 56, i.e. 2.33 → high, and
#: contributes more priority.
#:
#: Relative rather than an absolute rank gap because the rungs are
#: themselves proportional to league size and rung index: missing a
#: top-12 bar by 12 ranks is being replacement-level, while missing a
#: top-36 bar by 12 is being slightly short.  A fixed gap would call
#: those the same thing.
#:
#: PRIOR — a labelled starting point, not calibrated methodology.
_SEVERE_SHORTFALL_RATIO = 2.0
_MAJOR_SHORTFALL_RATIO = 1.0

NEED_THRESHOLD_STATUS = "PRIOR"


@dataclass(frozen=True)
class PositionRanks:
    """Positional rank of every player, plus WHICH population produced it.

    The population is carried because "top 12 QB" is only meaningful
    once you say top 12 of what.  Ranking against rostered players and
    ranking against the whole board are different statements, and a
    consumer comparing two teams must know they were measured the same
    way.  Nothing here picks a population — the caller supplies one and
    it is stamped.
    """

    ranks: Mapping[str, int] = field(default_factory=dict)
    population: str = "unspecified"
    population_size: int = 0

    def rank_of(self, player_id: str) -> int | None:
        return self.ranks.get(player_id)


def build_position_ranks(
    players: Iterable[tuple[str, str, float | None]],
    *,
    population: str,
) -> PositionRanks:
    """Rank players within their position by canonical value, descending.

    ``players`` is ``(player_id, position, value)``.  This ORDERS values
    it was handed; it computes none — the same posture
    ``strength.rank_team_strengths`` takes.  Positions are folded onto
    their slot family (DE/DT/EDGE → DL) so a rank and a rung are always
    in the same vocabulary.

    Unpriced players are **excluded**, not ranked last: an unknown value
    is not a low one, and seating it at the bottom of the ladder would
    let a join miss create a need.  They simply have no rank, which
    :func:`build_team_weakness` reports as ``UNKNOWN``.

    Deterministic: ties break on ``player_id``.
    """
    by_pos: dict[str, list[tuple[str, float]]] = {}
    for pid, pos, value in players:
        if value is None:
            continue
        by_pos.setdefault(normalize_base_position(pos), []).append((str(pid), float(value)))
    ranks: dict[str, int] = {}
    total = 0
    for entries in by_pos.values():
        entries.sort(key=lambda e: (-e[1], e[0]))
        total += len(entries)
        for i, (pid, _) in enumerate(entries, start=1):
            ranks[pid] = i
    return PositionRanks(ranks=ranks, population=population, population_size=total)


@dataclass(frozen=True)
class SlotRung:
    """One starter rung at one position: what it demands and who holds it.

    ``status`` is one of ``met`` / ``unmet`` / ``unfilled`` / ``unknown``.
    ``unfilled`` and ``unknown`` are deliberately distinct: nobody is
    there vs. somebody is there and we cannot rank them.
    """

    position: str
    rung: int
    threshold_rank: int
    status: str
    player_id: str | None = None
    player_rank: int | None = None

    @property
    def shortfall(self) -> int | None:
        """How many ranks past the threshold the holder sits.

        ``None`` unless the rung is genuinely unmet — an unfilled or
        unrankable rung has no measurable shortfall, and reporting 0
        would read as "just missed".
        """
        if self.status != "unmet" or self.player_rank is None:
            return None
        return self.player_rank - self.threshold_rank

    def to_dict(self) -> dict[str, Any]:
        return {
            "position": self.position,
            "rung": self.rung,
            "label": f"{self.position}{self.rung}",
            "thresholdRank": self.threshold_rank,
            "status": self.status,
            "playerId": self.player_id,
            "playerRank": self.player_rank,
            "shortfall": self.shortfall,
        }


@dataclass(frozen=True)
class PositionNeed:
    """Every rung at one position, reduced to one need statement."""

    position: str
    level: str
    priority: float
    rungs: tuple[SlotRung, ...] = ()
    reasons: tuple[str, ...] = ()

    @property
    def unfilled_rungs(self) -> int:
        return sum(1 for r in self.rungs if r.status == "unfilled")

    @property
    def unmet_rungs(self) -> int:
        return sum(1 for r in self.rungs if r.status == "unmet")

    @property
    def unknown_rungs(self) -> int:
        return sum(1 for r in self.rungs if r.status == "unknown")

    def to_dict(self) -> dict[str, Any]:
        return {
            "position": self.position,
            "level": self.level,
            "priority": round(self.priority, 4),
            "unfilledRungs": self.unfilled_rungs,
            "unmetRungs": self.unmet_rungs,
            "unknownRungs": self.unknown_rungs,
            "rungs": [r.to_dict() for r in self.rungs],
            "reasons": list(self.reasons),
        }


@dataclass(frozen=True)
class TeamWeakness:
    """Canonical need priority for ONE team."""

    by_position: dict[str, PositionNeed] = field(default_factory=dict)
    team_count: int = 0
    rank_population: str = "unspecified"
    available: bool = True
    unavailable_reason: str | None = None

    @property
    def ordered_needs(self) -> tuple[PositionNeed, ...]:
        """Needs worst-first — the order a trade-targeting consumer wants.

        Deterministic: position name breaks ties so two equally urgent
        rooms do not swap places between calls.
        """
        return tuple(
            sorted(
                self.by_position.values(),
                key=lambda n: (-n.priority, NEED_LEVELS.index(n.level), n.position),
            )
        )

    @property
    def urgent_positions(self) -> tuple[str, ...]:
        return tuple(n.position for n in self.ordered_needs if n.level in ("critical", "high"))

    def to_dict(self) -> dict[str, Any]:
        return {
            "available": self.available,
            "unavailableReason": self.unavailable_reason,
            "teamCount": self.team_count,
            "rankPopulation": self.rank_population,
            "thresholdRule": "rung_index_times_team_count",
            "thresholdStatus": NEED_THRESHOLD_STATUS,
            "needs": [n.to_dict() for n in self.ordered_needs],
            "urgentPositions": list(self.urgent_positions),
        }


def build_team_weakness(
    core: MeaningfulCore,
    ranks: PositionRanks,
    *,
    team_count: int,
) -> TeamWeakness:
    """Assess one team's starting-slot weakness against its own lineup.

    Args:
        core: the canonical population.  Its ``demand.starter_basis``
            supplies the rung counts, so Superflex is folded into QB
            exactly once and this module cannot disagree with the core
            about how many starters a position demands.
        ranks: league-wide positional ranks, with their population
            named.
        team_count: the league's team count — the rung multiplier.
            ``≤ 0`` is a refusal, not a league of nobody: every
            threshold would collapse to rank 0 and the whole roster
            would read as critically weak.
    """
    if not core.available:
        return TeamWeakness(
            available=False,
            unavailable_reason=core.unavailable_reason,
            rank_population=ranks.population,
        )
    if team_count <= 0:
        return TeamWeakness(
            available=False,
            unavailable_reason="unknown_team_count",
            rank_population=ranks.population,
        )

    members_by_pos = core.by_position()
    needs: dict[str, PositionNeed] = {}

    for position, demand in _dedicated_demand(core).items():
        candidates = _ordered_candidates(members_by_pos.get(position, ()))
        rungs: list[SlotRung] = []
        for k in range(1, demand + 1):
            threshold = k * team_count
            if k > len(candidates):
                rungs.append(
                    SlotRung(position=position, rung=k, threshold_rank=threshold, status="unfilled")
                )
                continue
            holder = candidates[k - 1]
            player_rank = ranks.rank_of(holder.player_id)
            if player_rank is None:
                status = "unknown"
            elif player_rank <= threshold:
                status = "met"
            else:
                status = "unmet"
            rungs.append(
                SlotRung(
                    position=position,
                    rung=k,
                    threshold_rank=threshold,
                    status=status,
                    player_id=holder.player_id,
                    player_rank=player_rank,
                )
            )
        needs[position] = _reduce(position, tuple(rungs))

    return TeamWeakness(
        by_position=needs,
        team_count=team_count,
        rank_population=ranks.population,
    )


def _dedicated_demand(core: MeaningfulCore) -> dict[str, int]:
    """Rung counts per position, straight off the core's own basis.

    Read from ``ReserveDemand.starter_basis`` rather than re-derived, so
    the #839 Superflex fold happens in exactly one place in the lane.
    Flex families are dropped here — see the module docstring for why
    FLEX gets no rung ladder.
    """
    return {pos: int(n) for pos, n in core.demand.dedicated_basis.items() if n > 0}


def _ordered_candidates(members: Sequence[CoreMember]) -> list[CoreMember]:
    """A position's core members, best first.

    Starters and reserves both qualify: the rung asks "is your k-th best
    player at this position good enough", and on a roster whose k-th
    best was seated as a reserve rather than a starter, that player is
    still the answer.  Deterministic on ties via ``player_id``.
    """
    return sorted(members, key=lambda m: (-m.value, m.player_id))


def _reduce(position: str, rungs: tuple[SlotRung, ...]) -> PositionNeed:
    """Collapse a position's rungs into one level + priority.

    A position takes the level of its **worst** rung, never an average.
    Averaging is what lets an elite QB1 hide a missing QB2 — and the
    missing QB2 is the whole reason to look.

    ``priority`` accumulates so that a room failing two rungs outranks
    one failing a single rung at the same severity; ``UNKNOWN`` rungs
    contribute nothing, because a rung we could not measure is not
    evidence of need.
    """
    priority = 0.0
    level = "none"
    reasons: list[str] = []

    for rung in rungs:
        if rung.status == "unfilled":
            priority += 3.0
            level = _worst(level, "critical")
            reasons.append(f"no {rung.position}{rung.rung} on the roster")
        elif rung.status == "unmet":
            # `shortfall` is not None here by construction: status is
            # "unmet" only when a real rank exceeded a real threshold.
            ratio = rung.shortfall / rung.threshold_rank
            if ratio >= _SEVERE_SHORTFALL_RATIO:
                priority += 2.0
                level = _worst(level, "high")
            elif ratio >= _MAJOR_SHORTFALL_RATIO:
                priority += 1.0
                level = _worst(level, "high")
            else:
                priority += 0.5
                level = _worst(level, "moderate")
            reasons.append(
                f"{rung.position}{rung.rung} is {rung.player_rank} "
                f"against a top-{rung.threshold_rank} bar"
            )
        elif rung.status == "unknown":
            reasons.append(
                f"{rung.position}{rung.rung} holder is unranked — need NOT measured here"
            )

    return PositionNeed(
        position=position,
        level=level,
        priority=priority,
        rungs=rungs,
        reasons=tuple(reasons),
    )


def _worst(a: str, b: str) -> str:
    return a if NEED_LEVELS.index(a) < NEED_LEVELS.index(b) else b
