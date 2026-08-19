"""Marginal best-ball contribution — the measurement everything else rests on.

Positional strength is NOT summed value and NOT player count.  Both are
easy to compute and both are wrong in a best-ball superflex league, for
the same reason: they credit players who never play.

A concrete failure the count/sum proxies produce, and this module does
not.  Take a roster with five high-value QBs in a league with one QB slot
and one SUPER_FLEX.  Summed value calls that the strongest QB room in the
league.  Counting calls it five-deep.  In reality at most two QBs ever
score, the third through fifth contribute only insurance, and the roster
is starving other positions to hold them.  ``lineup.py``'s exact
optimizer already knows this — it simply was never asked.

So every strength number here is defined by re-solving the optimal
lineup with something removed and measuring what the score loses:

    marginal(position) = S(full roster) − S(roster without that position)
    marginal(player)   = S(full roster) − S(roster without that player)

That is the player's or group's actual contribution to the optimized
lineup, which is exactly the quantity the brief demands and exactly what
a name-value proxy cannot see.

The second half of the brief — "or preserve output during absences" — is
the ``absence`` family.  A position can contribute little marginal value
because it is thin (bad) or because its backups are nearly as good as its
starters (good).  Marginal contribution alone cannot tell those apart;
leave-one-out absence drops can, so both are reported.

Pure computation.  No I/O, no network, no clock — mirrors
``src/league_intel/replacement.py``'s shape and consumes
``src/ros/lineup.py`` as-is.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Iterable, Mapping, Sequence

from src.league_intel.replacement import normalize_base_position
from src.ros.lineup import (
    RosterPlayer,
    priced_players,
    roster_players_from_rows,
    solve_optimal_assignment,
)

__all__ = [
    "AbsenceImpact",
    "LineupSolutionSummary",
    "PositionMarginal",
    "RosterMarginals",
    "absence_impacts",
    "optimal_score",
    "position_marginals",
    "solve_summary",
    "to_roster_players",
]


def to_roster_players(players: Iterable[Mapping[str, Any]]) -> list[RosterPlayer]:
    """Map roster rows onto the optimizer's frozen dataclass.

    Delegates to ``ros.lineup.roster_player_from_row``.  This used to be
    a hand-maintained copy of ``replacement._to_roster_players``, whose
    own docstring said the two "must agree ... or their numbers stop
    being comparable".  They now agree structurally rather than by
    vigilance.  Kept as a name because callers import it.
    """
    return roster_players_from_rows(players)


@dataclass(frozen=True)
class LineupSolutionSummary:
    """One optimal-lineup solve, reduced to what the callers need."""

    score: float
    assigned_ids: frozenset[str]
    # slot label -> player_id, so callers can see WHERE a player entered
    # (a QB filling SUPER_FLEX is a different fact from a QB filling QB).
    slot_assignment: dict[str, str] = field(default_factory=dict)
    filled_slots: int = 0
    total_slots: int = 0

    @property
    def unfilled_slots(self) -> int:
        return max(0, self.total_slots - self.filled_slots)


def solve_summary(
    pool: Sequence[RosterPlayer],
    slots: Sequence[str],
) -> LineupSolutionSummary:
    """Solve the exact assignment and summarize it.

    Thin wrapper over ``solve_optimal_assignment`` so this module never
    reimplements lineup logic — the optimizer is consumed, not rebuilt.
    """
    slots_list = list(slots)
    if not pool or not slots_list:
        return LineupSolutionSummary(
            score=0.0,
            assigned_ids=frozenset(),
            slot_assignment={},
            filled_slots=0,
            total_slots=len(slots_list),
        )
    assignment = solve_optimal_assignment(list(pool), slots_list)
    # The solver already refuses to seat an unpriced player; filtering
    # here states that rather than relying on it.
    score = float(sum(p.ros_value for p in priced_players(assignment.values())))
    slot_map: dict[str, str] = {}
    for slot_idx, player in assignment.items():
        # Key by index-qualified slot so duplicate slot labels (RB, RB)
        # do not collide.
        slot_map[f"{slots_list[slot_idx]}#{slot_idx}"] = player.player_id
    return LineupSolutionSummary(
        score=score,
        assigned_ids=frozenset(p.player_id for p in assignment.values()),
        slot_assignment=slot_map,
        filled_slots=len(assignment),
        total_slots=len(slots_list),
    )


def optimal_score(pool: Sequence[RosterPlayer], slots: Sequence[str]) -> float:
    """Optimal lineup score for a pool.  Convenience for delta math."""
    return solve_summary(pool, slots).score


@dataclass(frozen=True)
class PositionMarginal:
    """What one position actually contributes to the optimized lineup."""

    position: str
    rostered: int
    priced: int
    # S(full) − S(full minus every player at this position).
    marginal_points: float
    # Share of the full lineup score this position is responsible for.
    marginal_share: float
    # How many of this position's players entered the optimal lineup,
    # and where.
    entered_lineup: int
    entry_rate: float
    slots_filled: tuple[str, ...]
    # Players with real value that never enter, even though they are
    # rostered — the clog signal.
    non_entering_priced: int
    clogger_value: float

    def to_dict(self) -> dict[str, Any]:
        return {
            "position": self.position,
            "rostered": self.rostered,
            "priced": self.priced,
            # NOT points.  The underlying quantity is a difference of two
            # lineup solves whose weights are ``rosValue`` — a 0-100
            # normalized log-rank index (``src/ros/parse.py``).
            # ``marginalPoints`` is retained as a deprecated alias for one
            # release; new consumers read ``marginalStrengthIndex``.
            "marginalStrengthIndex": round(self.marginal_points, 3),
            "marginalPoints": round(self.marginal_points, 3),  # deprecated alias
            "marginalShare": round(self.marginal_share, 4),
            "enteredLineup": self.entered_lineup,
            "entryRate": round(self.entry_rate, 4),
            "slotsFilled": list(self.slots_filled),
            "nonEnteringPriced": self.non_entering_priced,
            "cloggerValue": round(self.clogger_value, 3),
        }


@dataclass(frozen=True)
class RosterMarginals:
    """Full-roster marginal picture."""

    lineup_score: float
    filled_slots: int
    total_slots: int
    by_position: dict[str, PositionMarginal] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "lineupScore": round(self.lineup_score, 3),
            "filledSlots": self.filled_slots,
            "totalSlots": self.total_slots,
            "byPosition": {k: v.to_dict() for k, v in sorted(self.by_position.items())},
        }


def _base_of(player: RosterPlayer) -> str:
    return normalize_base_position(player.position)


def position_marginals(
    pool: Sequence[RosterPlayer],
    slots: Sequence[str],
) -> RosterMarginals:
    """Marginal contribution of every position on one roster.

    For each position P present on the roster we re-solve the lineup
    with all of P removed.  The score difference is P's contribution.
    This is deliberately a GROUP leave-out rather than a sum of
    individual leave-outs: individual marginals do not add up, because
    removing a team's QB1 promotes QB2 into the same slot.  Summing
    them would double-count the slot and inflate every deep position.
    """
    pool_list = list(pool)
    slots_list = list(slots)
    full = solve_summary(pool_list, slots_list)

    by_pos: dict[str, list[RosterPlayer]] = {}
    for p in pool_list:
        base = _base_of(p)
        if base:
            by_pos.setdefault(base, []).append(p)

    out: dict[str, PositionMarginal] = {}
    for pos, players in by_pos.items():
        remaining = [p for p in pool_list if _base_of(p) != pos]
        without = solve_summary(remaining, slots_list)
        marginal = full.score - without.score

        entered = [p for p in players if p.player_id in full.assigned_ids]
        slots_filled = tuple(
            sorted(
                slot.split("#")[0]
                for slot, pid in full.slot_assignment.items()
                if pid in {p.player_id for p in entered}
            )
        )
        priced = [p for p in priced_players(players) if p.ros_value > 0]
        non_entering = [p for p in priced if p.player_id not in full.assigned_ids]

        out[pos] = PositionMarginal(
            position=pos,
            rostered=len(players),
            priced=len(priced),
            marginal_points=marginal,
            marginal_share=(marginal / full.score) if full.score > 0 else 0.0,
            entered_lineup=len(entered),
            entry_rate=(len(entered) / len(players)) if players else 0.0,
            slots_filled=slots_filled,
            non_entering_priced=len(non_entering),
            clogger_value=float(sum(p.ros_value for p in priced_players(non_entering))),
        )

    return RosterMarginals(
        lineup_score=full.score,
        filled_slots=full.filled_slots,
        total_slots=full.total_slots,
        by_position=out,
    )


@dataclass(frozen=True)
class AbsenceImpact:
    """How well a position preserves output when one starter is gone.

    ``mean_drop`` is the average points lost across leave-one-out solves
    for each of this position's lineup entrants.  ``worst_drop`` is the
    single most damaging absence — the one that actually keeps a manager
    up at night, and the number a mean hides.
    """

    position: str
    starters_tested: int
    mean_drop: float
    worst_drop: float
    # Share of an absent starter's OWN value that the roster fails to
    # replace: 0 means the next player up is just as good (deep), 1
    # means the starter is irreplaceable on this roster (fragile).
    #
    # Deliberately normalized by mean entrant value, NOT by the
    # position's marginal contribution.  The marginal denominator is
    # degenerate: for n entrants with no bench behind them the
    # individual drops sum to the group marginal, so mean_drop/marginal
    # collapses to ~1/n and reports the SAME number for a deep room and
    # a thin one.  That is the `_positional_coverage` failure mode (a
    # constant wearing a score's clothes) and it is guarded by
    # test_fragility_separates_deep_from_thin.
    fragility: float

    def to_dict(self) -> dict[str, Any]:
        return {
            "position": self.position,
            "startersTested": self.starters_tested,
            "meanDrop": round(self.mean_drop, 3),
            "worstDrop": round(self.worst_drop, 3),
            "fragility": round(self.fragility, 4),
        }


def absence_impacts(
    pool: Sequence[RosterPlayer],
    slots: Sequence[str],
) -> dict[str, AbsenceImpact]:
    """Leave-one-out absence cost per position.

    This is the "preserve output during absences" half of strength.  A
    position whose marginal contribution is large but whose worst-case
    absence drop is small is genuinely strong; one where a single
    absence erases most of the contribution is a starter plus wishes.

    Cost is O(entrants × solve), which at roster scale (≤60 players,
    ≤25 slots) is trivial — the optimizer is O(P·S·E).
    """
    pool_list = list(pool)
    slots_list = list(slots)
    full = solve_summary(pool_list, slots_list)

    by_pos: dict[str, list[RosterPlayer]] = {}
    for p in pool_list:
        if p.player_id in full.assigned_ids:
            base = _base_of(p)
            if base:
                by_pos.setdefault(base, []).append(p)

    out: dict[str, AbsenceImpact] = {}
    for pos, entrants in by_pos.items():
        drops: list[float] = []
        for target in entrants:
            remaining = [p for p in pool_list if p.player_id != target.player_id]
            drops.append(max(0.0, full.score - solve_summary(remaining, slots_list).score))
        if not drops:
            continue
        mean_drop = sum(drops) / len(drops)
        worst = max(drops)
        valued_entrants = priced_players(entrants)
        # An UNKNOWN carries no value into the mean.  With nobody priced
        # the mean is genuinely unmeasured; 0.0 is the pre-existing
        # convention of this (different-owner) module and is left alone
        # rather than changed on a hardening unit's authority.
        mean_entrant_value = (
            sum(p.ros_value for p in valued_entrants) / len(valued_entrants)
            if valued_entrants
            else 0.0
        )
        out[pos] = AbsenceImpact(
            position=pos,
            starters_tested=len(drops),
            mean_drop=mean_drop,
            worst_drop=worst,
            fragility=(min(1.0, mean_drop / mean_entrant_value) if mean_entrant_value > 0 else 0.0),
        )
    return out
