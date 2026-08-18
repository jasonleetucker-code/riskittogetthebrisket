"""Roster capacity and the legal post-trade roster (the ROSTER half of C3-CAP-01).

Binding spec: ``docs/trade/ROSTER_CAPACITY_FORCED_DROP_TRADE_ANALYSIS_ADDENDUM_2026-08-14.md``
(#843, owner decision 2026-08-14, inventory row 2.14).  Its canonical flow is::

    before roster → apply trade → capacity / overage → required legal cleanup
                  → apply optimal cleanup → rerun roster intelligence → EVALUATE

**This module runs that flow up to the arrow before EVALUATE, and stops.**
Everything to its left is roster mechanics and belongs to this lane; the
evaluation — MAKE / LEAN MAKE / TOO CLOSE / LEAN PASS / PASS, package
ranking, mutual defensibility, the Use Team Context toggle — is the trade
lane's (`C3-CAP-01` is filed under `trade`, and depends on `C3-CTX-01`
which does not exist yet).

So this emits no verdict, no grade and no score, asserted structurally the
same way ``simulation.py`` is.  What it emits is the state the spec says an
evaluator must have and today has to invent.

Why it exists rather than living in the trade lane
==================================================

The spec forbids one specific shortcut by name:

    Do not model it solely as ``package delta - lowest raw player value``.
    Use canonical dropability / roster utility to determine the lowest-cost
    legal cleanup path, then recompute the final roster.

That shortcut is what gets written when the cleanup step has no owner.  The
pieces to do it properly all exist in this chain now — the exact assignment
solver, the meaningful core, the cut ladder — so the honest fix is to publish
the composed flow rather than to describe it.

Three rules the spec states and this module enforces
====================================================

* **Picks do not consume an active roster spot**, and must not be counted as
  players merely because they are in the package.  They are counted and
  reported (``picksExcluded``) so the omission is visible.
* **Do not invent a value for an open roster spot.**  Capacity is a
  feasibility dimension here; an open spot absorbs a player and costs nothing.
  A team with room enough for the incoming side ``fitsCleanly`` and carries no
  forced-drop cost at all.
* **Do not manufacture a bonus for becoming legal.**  Resolving an overage is
  reported as a state transition (``resolved`` / ``improved`` / ``unchanged``
  / ``worsened``), never as value.  The benefit shows up where the spec says
  it should: in avoided cuts and in the final roster.

Missing is never zero, and here that is the load-bearing rule
=============================================================

    Missing capacity data must remain degraded/unknown; do not silently
    assume zero open spots, zero overage, no forced drop, or auto-switch to
    Asset-Only.  — #843

So ``active_limit`` is ``int | None`` and ``None`` propagates: with no limit
known, ``open_spots``, ``over_limit_before``, ``cleanup_moves_required`` and
``final_count`` are all ``None`` and ``available`` is ``False`` with a reason.
A roster whose capacity is unknown is NOT a roster with infinite room.

**Taxi and IR relief is UNAVAILABLE, not zero.**  The registry knows a league's
``taxiSize``, but Sleeper's per-player taxi assignment is ingested nowhere in
this codebase, and IR eligibility is a per-player medical status nothing here
carries.  The spec allows those moves "only where actual league rules and
player eligibility permit" — we cannot establish either, so the count is
reported alongside an explicit ``taxiReliefModelled: false`` and its reason.
Assuming relief would understate required cuts; assuming none would overstate
them for a league that has it.  Saying so is the only honest option.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Collection, Iterable, Mapping, Sequence

from src.roster_intel.droppability import pool_cut_ladder
from src.roster_intel.simulation import RosterSimulation, simulate_roster_change
from src.ros.lineup import RosterPlayer

__all__ = [
    "CLEANUP_AMBIGUITY_TOLERANCE",
    "TAXI_RELIEF_UNAVAILABLE_REASON",
    "CapacityState",
    "CleanupPlan",
    "RosterCapacityOutcome",
    "plan_roster_capacity",
]

#: Two cleanup options are "close" when the cheaper one is within this
#: fraction of the dearer.  A labelled **PRIOR** — the spec says *"if multiple
#: cleanup options are close, preserve uncertainty rather than pretending one
#: drop is certain"* and does not say how close is close.  Nothing here is
#: calibrated against outcomes, and the tolerance decides only whether
#: alternatives are REPORTED; it never changes which cut is selected.
CLEANUP_AMBIGUITY_TOLERANCE = 0.10

TAXI_RELIEF_UNAVAILABLE_REASON = (
    "taxi/IR relief is not modelled: Sleeper's per-player taxi assignment is "
    "ingested nowhere in this codebase and IR eligibility is a per-player status "
    "no canonical source carries, so neither the league rule nor the player "
    "eligibility the spec requires can be established"
)


@dataclass(frozen=True)
class CapacityState:
    """Every capacity quantity #843 requires, each honestly nullable.

    ``None`` means UNMEASURED and propagates: with no ``active_limit`` there
    is no open-spot count, no overage and no cleanup requirement — because a
    roster whose limit is unknown is not a roster with infinite room.
    """

    active_limit: int | None
    active_count_before: int
    open_spots_before: int | None
    over_limit_before: int | None
    incoming_players: int
    outgoing_players: int
    picks_excluded: int
    net_player_change: int
    post_package_count: int
    over_limit_after_package: int | None
    cleanup_moves_required: int | None
    final_count: int | None
    #: ``resolved`` / ``improved`` / ``unchanged`` / ``worsened`` / ``none`` /
    #: ``unknown`` — measured on the POST-PACKAGE state, which is what the
    #: spec's worked examples describe ("team is 1 over; 2-for-1 returns it to
    #: legal size").
    overage_transition: str
    #: True when the incoming side fits in existing room and no cut is needed.
    #: ``None`` when the limit is unknown — not ``False``, which would assert
    #: a cut is required.
    fits_cleanly: bool | None
    taxi_size: int
    taxi_relief_modelled: bool
    taxi_relief_reason: str
    available: bool
    unavailable_reason: str | None

    def to_dict(self) -> dict[str, Any]:
        return {
            "activeLimit": self.active_limit,
            "activeCountBefore": self.active_count_before,
            "openSpotsBefore": self.open_spots_before,
            "overLimitBefore": self.over_limit_before,
            "incomingPlayers": self.incoming_players,
            "outgoingPlayers": self.outgoing_players,
            "picksExcluded": self.picks_excluded,
            "netPlayerChange": self.net_player_change,
            "postPackageCount": self.post_package_count,
            "overLimitAfterPackage": self.over_limit_after_package,
            "cleanupMovesRequired": self.cleanup_moves_required,
            "finalCount": self.final_count,
            "overageTransition": self.overage_transition,
            "fitsCleanly": self.fits_cleanly,
            "taxiSize": self.taxi_size,
            "taxiReliefModelled": self.taxi_relief_modelled,
            "taxiReliefReason": self.taxi_relief_reason,
            "available": self.available,
            "unavailableReason": self.unavailable_reason,
        }


@dataclass(frozen=True)
class CleanupPlan:
    """The cheapest LEGAL way back under the limit, and how sure it is.

    ``releases`` come off the canonical cut ladder, which is cheapest-first
    and whose prefixes are the optimal cut-set at every size (the matroid
    argument in ``src/draft/displacement.py``).  So taking the first *k* rungs
    IS the optimal legal cleanup of size *k* — no search, and no
    ``lowest raw player value``, which the spec forbids by name.
    """

    releases: tuple[dict[str, Any], ...] = ()
    total_effective_cut_cost: float | None = None
    #: False when the ladder cannot supply enough legal releases — every
    #: remaining player is required to fill the starting lineup.  Reported
    #: rather than resolved by cutting a starter anyway.
    feasible: bool = True
    shortfall: int = 0
    #: True when a rung just outside the plan costs about the same as the last
    #: one inside it.  Reporting only, per the spec's "preserve uncertainty
    #: rather than pretending one drop is certain".
    ambiguous: bool = False
    close_alternatives: tuple[dict[str, Any], ...] = ()
    tolerance: float = CLEANUP_AMBIGUITY_TOLERANCE

    def to_dict(self) -> dict[str, Any]:
        return {
            "releases": list(self.releases),
            "totalEffectiveCutCost": (
                None
                if self.total_effective_cut_cost is None
                else round(self.total_effective_cut_cost, 1)
            ),
            "feasible": self.feasible,
            "shortfall": self.shortfall,
            "ambiguous": self.ambiguous,
            "closeAlternatives": list(self.close_alternatives),
            "tolerance": self.tolerance,
            "toleranceStatus": "PRIOR",
            "valueScale": "rankDerivedValue",
        }


@dataclass(frozen=True)
class RosterCapacityOutcome:
    """Capacity, the cleanup, and the roster intelligence of the FINAL legal roster."""

    capacity: CapacityState
    cleanup: CleanupPlan
    #: before → final LEGAL roster.  Deliberately not before → post-package:
    #: *"the analyzer must not run season odds on an impossible over-limit
    #: roster when a required cleanup move materially changes the roster"*.
    simulation: RosterSimulation

    def to_dict(self) -> dict[str, Any]:
        return {
            "capacity": self.capacity.to_dict(),
            "cleanup": self.cleanup.to_dict(),
            "finalRoster": self.simulation.to_dict(),
        }


def _overage_transition(before: int | None, after: int | None) -> str:
    if before is None or after is None:
        return "unknown"
    if before == 0 and after == 0:
        return "none"
    if before > 0 and after == 0:
        return "resolved"
    if after < before:
        return "improved"
    if after > before:
        return "worsened"
    return "unchanged"


def plan_roster_capacity(
    pool: Iterable[RosterPlayer],
    starter_slots: Sequence[str],
    *,
    incoming: Iterable[RosterPlayer] = (),
    outgoing_ids: Collection[str] = (),
    incoming_picks: int = 0,
    outgoing_picks: int = 0,
    active_limit: int | None = None,
    waiver_values: Mapping[str, float] | None = None,
    scarcity: Mapping[str, Any] | None = None,
    taxi_size: int = 0,
    ranks: Any = None,
    team_count: int | None = None,
    slot_eligibility: Mapping[str, Collection[str]] | None = None,
    config: Mapping[str, Any] | None = None,
) -> RosterCapacityOutcome:
    """Run #843's flow up to — and not past — the evaluation step.

    Args:
        pool: the roster BEFORE the trade.
        incoming / outgoing_ids: the PLAYER sides of the package.
        incoming_picks / outgoing_picks: pick counts, reported and never
            counted as roster occupants — *"draft picks normally do not
            consume an immediate active roster spot and must not be counted
            as current players merely because they are included in the
            trade"*.
        active_limit: the league's active-roster limit.  ``None`` is UNKNOWN
            and degrades the whole capacity block rather than being read as
            "no limit".
        waiver_values: per-position waiver level for the cut ladder.  Absent
            means cut costs fall back to raw board value, exactly as the
            canonical owner already handles it.
        ranks / team_count: passed through to the simulation's weakness half.

    Returns the capacity state, the cleanup plan, and the before → FINAL
    LEGAL roster simulation.  No verdict: whether the result is worth doing
    is the trade lane's judgement.
    """
    before_pool = list(pool)
    incoming_list = list(incoming)
    leaving = {str(x) for x in outgoing_ids}

    post_package = [p for p in before_pool if p.player_id not in leaving] + incoming_list

    count_before = len(before_pool)
    post_count = len(post_package)

    limit = int(active_limit) if isinstance(active_limit, int) and active_limit > 0 else None
    open_before = max(0, limit - count_before) if limit is not None else None
    over_before = max(0, count_before - limit) if limit is not None else None
    over_after = max(0, post_count - limit) if limit is not None else None

    cleanup = CleanupPlan(tolerance=CLEANUP_AMBIGUITY_TOLERANCE)
    release_ids: list[str] = []
    if over_after:
        cleanup = _plan_cleanup(
            post_package,
            starter_slots,
            waiver_values or {},
            scarcity=scarcity,
            needed=over_after,
            slot_eligibility=slot_eligibility,
        )
        release_ids = [str(r["playerId"]) for r in cleanup.releases]

    final_pool_ids = leaving | set(release_ids)
    simulation = simulate_roster_change(
        before_pool,
        starter_slots,
        incoming=incoming_list,
        outgoing_ids=sorted(final_pool_ids),
        ranks=ranks,
        team_count=team_count,
        slot_eligibility=slot_eligibility,
        config=config,
    )

    capacity = CapacityState(
        active_limit=limit,
        active_count_before=count_before,
        open_spots_before=open_before,
        over_limit_before=over_before,
        incoming_players=len(incoming_list),
        outgoing_players=len(leaving & {p.player_id for p in before_pool}),
        picks_excluded=int(incoming_picks) + int(outgoing_picks),
        net_player_change=post_count - count_before,
        post_package_count=post_count,
        over_limit_after_package=over_after,
        cleanup_moves_required=over_after,
        final_count=(post_count - len(release_ids)) if limit is not None else None,
        overage_transition=_overage_transition(over_before, over_after),
        fits_cleanly=(None if limit is None else not over_after),
        taxi_size=int(taxi_size or 0),
        taxi_relief_modelled=False,
        taxi_relief_reason=TAXI_RELIEF_UNAVAILABLE_REASON,
        available=limit is not None,
        unavailable_reason=(None if limit is not None else "active_roster_limit_unknown"),
    )
    return RosterCapacityOutcome(capacity=capacity, cleanup=cleanup, simulation=simulation)


def _plan_cleanup(
    post_package: Sequence[RosterPlayer],
    starter_slots: Sequence[str],
    waiver_values: Mapping[str, float],
    *,
    scarcity: Mapping[str, Any] | None,
    needed: int,
    slot_eligibility: Mapping[str, Collection[str]] | None,
) -> CleanupPlan:
    """The first ``needed`` rungs of the canonical cut ladder.

    Optimal by construction: the ladder is cheapest-first and its prefixes
    nest, so the size-*k* prefix is the optimal legal cut-set of size *k*.
    """
    ladder = pool_cut_ladder(
        post_package,
        starter_slots,
        waiver_values,
        scarcity=scarcity,
        slot_eligibility=slot_eligibility,
    )
    rungs = [r.to_dict() for r in ladder.rungs]
    chosen = rungs[:needed]
    shortfall = max(0, needed - len(chosen))

    ambiguous = False
    close: list[dict[str, Any]] = []
    if chosen and len(rungs) > len(chosen):
        boundary = float(chosen[-1]["effectiveCutCost"])
        band = boundary + CLEANUP_AMBIGUITY_TOLERANCE * max(boundary, 1.0)
        close = [r for r in rungs[len(chosen) :] if float(r["effectiveCutCost"]) <= band]
        ambiguous = bool(close)

    return CleanupPlan(
        releases=tuple(chosen),
        total_effective_cut_cost=(
            sum(float(r["effectiveCutCost"]) for r in chosen) if chosen else None
        ),
        feasible=shortfall == 0,
        shortfall=shortfall,
        ambiguous=ambiguous,
        close_alternatives=tuple(close),
        tolerance=CLEANUP_AMBIGUITY_TOLERANCE,
    )
