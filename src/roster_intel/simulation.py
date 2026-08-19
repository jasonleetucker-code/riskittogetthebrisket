"""Exact before → apply → re-solve → after roster simulation (C2-SIM-01).

Answers *"what does this transaction do to this roster"* as **roster
information** — who starts now who did not, who fell out of the
meaningful core, which needs closed and which opened — rather than as a
value subtraction.

Manifest `C2-SIM-01`, owner decision 26, inventory row 1.3. The
requirement is explicit: *"Promotions/displacements and need changes as
separate roster information, never a value subtraction."*

Why a value delta is not this
=============================

``/api/trade/simulate`` already computes ``Σ incoming − Σ outgoing``.
That number is real and this module does not replace it — but it cannot
answer the question row 1.3 asks, because roster effects are
**set-dependent**:

* acquiring a WR when you already start three can move a *different*
  WR out of FLEX and a RB in, so the displaced player is not the one
  traded;
* a player worth less than the one he replaces can still close a need,
  if the need was an unfilled slot rather than a quality gap;
* two additions of equal value have different effects depending on
  which rooms they land in.

FLEX and Superflex are what make this true. That is the same reason
droppability is a matching problem rather than a per-position count
(inventory 1.4), and it is why this re-solves rather than arithmetics:
:func:`~src.roster_intel.core.build_meaningful_core` runs again on the
post-transaction roster, using the same exact assignment owner, and the
two solves are compared.

What it does NOT do
===================

* **No grade, no verdict, no recommendation.** It reports movement.
  Whether the movement is good is a trade-lane judgement built on top,
  and folding one into the other is how a roster fact becomes an
  opinion nobody can audit.
* **No value arithmetic across the two sides.** ``strength_delta`` is
  the difference between two independently computed Team Strength
  aggregates, which is a *measurement of the two rosters*, not a
  scoring of the package.
* **No player valuation.** Same rule as everywhere in this lane.

Missing is never zero
=====================

An incoming player the board cannot price arrives ``ros_value=None``,
is excluded from the solve by the canonical owner, and is reported in
``unpriced_incoming`` — never seated, never counted as worthless. An
outgoing id that is not on the roster is reported in
``outgoing_not_found`` rather than silently ignored, because "I removed
a player you do not have" is a caller bug worth surfacing.

Pure computation. No I/O, no network, no clock.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Collection, Iterable, Mapping, Sequence

from src.roster_intel.core import CoreMember, MeaningfulCore, build_meaningful_core
from src.roster_intel.strength import TeamStrength, build_team_strength
from src.roster_intel.weakness import PositionRanks, TeamWeakness, build_team_weakness
from src.ros.lineup import RosterPlayer

__all__ = [
    "RosterSimulation",
    "SlotMovement",
    "simulate_roster_change",
]


@dataclass(frozen=True)
class SlotMovement:
    """One player's change of standing across the transaction.

    ``slot`` is the lineup slot the exact solve seated them in, or
    ``None`` when they were not in the meaningful core at all. ``role``
    is ``"starter"`` / ``"reserve"`` / ``None``.

    Both are carried before AND after because the interesting cases are
    not entries and exits — they are the quiet ones. A player who moves
    ``RB → FLEX`` is still a starter and still in the core, but the
    roster around him changed shape, and that is exactly the cascade a
    value delta cannot see.
    """

    player_id: str
    canonical_name: str
    position: str
    slot_before: str | None
    slot_after: str | None
    role_before: str | None
    role_after: str | None

    @property
    def kind(self) -> str:
        """``promoted`` / ``displaced`` / ``moved`` / ``unchanged``.

        Promotion and displacement are about the CORE, not the starting
        lineup alone: falling from starter to reserve is a demotion
        within the core, while falling out of the core entirely is a
        displacement. Collapsing the two would hide the difference
        between "he lost his slot" and "he stopped mattering".
        """
        if self.role_before is None and self.role_after is not None:
            return "promoted"
        if self.role_before is not None and self.role_after is None:
            return "displaced"
        if (self.role_before, self.slot_before) != (self.role_after, self.slot_after):
            return "moved"
        return "unchanged"

    def to_dict(self) -> dict[str, Any]:
        return {
            "playerId": self.player_id,
            "name": self.canonical_name,
            "position": self.position,
            "slotBefore": self.slot_before,
            "slotAfter": self.slot_after,
            "roleBefore": self.role_before,
            "roleAfter": self.role_after,
            "kind": self.kind,
        }


@dataclass(frozen=True)
class RosterSimulation:
    """One transaction's effect on one roster."""

    core_before: MeaningfulCore
    core_after: MeaningfulCore
    strength_before: TeamStrength
    strength_after: TeamStrength
    weakness_before: TeamWeakness | None = None
    weakness_after: TeamWeakness | None = None
    movements: tuple[SlotMovement, ...] = ()
    unpriced_incoming: frozenset[str] = frozenset()
    outgoing_not_found: frozenset[str] = frozenset()
    available: bool = True
    unavailable_reason: str | None = None

    @property
    def promotions(self) -> tuple[SlotMovement, ...]:
        return tuple(m for m in self.movements if m.kind == "promoted")

    @property
    def displacements(self) -> tuple[SlotMovement, ...]:
        return tuple(m for m in self.movements if m.kind == "displaced")

    @property
    def moves(self) -> tuple[SlotMovement, ...]:
        return tuple(m for m in self.movements if m.kind == "moved")

    @property
    def strength_delta(self) -> float:
        """After minus before, over the meaningful core.

        A difference between two independently measured rosters — NOT a
        scoring of the package. It can be negative while needs close, or
        positive while a need opens, and both are real.
        """
        return self.strength_after.total - self.strength_before.total

    @property
    def needs_fixed(self) -> tuple[str, ...]:
        """Positions that were urgent before and are not after."""
        if self.weakness_before is None or self.weakness_after is None:
            return ()
        return tuple(
            sorted(
                set(self.weakness_before.urgent_positions)
                - set(self.weakness_after.urgent_positions)
            )
        )

    @property
    def needs_created(self) -> tuple[str, ...]:
        """Positions that are urgent after and were not before.

        Reported with equal weight to ``needs_fixed``. A simulation that
        only showed what improved would be an advocacy tool.
        """
        if self.weakness_before is None or self.weakness_after is None:
            return ()
        return tuple(
            sorted(
                set(self.weakness_after.urgent_positions)
                - set(self.weakness_before.urgent_positions)
            )
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "available": self.available,
            "unavailableReason": self.unavailable_reason,
            "strengthBefore": self.strength_before.to_dict(),
            "strengthAfter": self.strength_after.to_dict(),
            "strengthDelta": round(self.strength_delta, 3),
            "coreBefore": self.core_before.to_dict(),
            "coreAfter": self.core_after.to_dict(),
            "weaknessBefore": (self.weakness_before.to_dict() if self.weakness_before else None),
            "weaknessAfter": self.weakness_after.to_dict() if self.weakness_after else None,
            "needsFixed": list(self.needs_fixed),
            "needsCreated": list(self.needs_created),
            "movements": [m.to_dict() for m in self.movements],
            "promotions": [m.to_dict() for m in self.promotions],
            "displacements": [m.to_dict() for m in self.displacements],
            "unpricedIncoming": sorted(self.unpriced_incoming),
            "outgoingNotFound": sorted(self.outgoing_not_found),
        }


def _index(core: MeaningfulCore) -> dict[str, CoreMember]:
    return {m.player_id: m for m in core.members}


def simulate_roster_change(
    pool: Iterable[RosterPlayer],
    starter_slots: Sequence[str],
    *,
    incoming: Iterable[RosterPlayer] = (),
    outgoing_ids: Collection[str] = (),
    ranks: PositionRanks | None = None,
    team_count: int | None = None,
    slot_eligibility: Mapping[str, Collection[str]] | None = None,
    config: Mapping[str, Any] | None = None,
) -> RosterSimulation:
    """Apply a transaction, re-solve, and report what moved.

    Args:
        pool: the roster BEFORE the transaction.
        starter_slots: the league's real flattened slots. Empty is a
            REFUSAL propagated from the core owner, not an empty lineup.
        incoming: players joining. Unpriced ones are reported, never
            seated.
        outgoing_ids: player ids leaving. Ids not on the roster are
            reported rather than ignored.
        ranks / team_count: supply BOTH to get the weakness half. Either
            alone leaves ``weakness_before``/``after`` ``None`` and the
            need deltas empty — an unmeasured need is not "no need".
    """
    before_pool = list(pool)
    leaving = {str(x) for x in outgoing_ids}
    on_roster = {p.player_id for p in before_pool}

    incoming_list = list(incoming)
    after_pool = [p for p in before_pool if p.player_id not in leaving] + incoming_list

    core_before = build_meaningful_core(
        before_pool, starter_slots, slot_eligibility=slot_eligibility, config=config
    )
    core_after = build_meaningful_core(
        after_pool, starter_slots, slot_eligibility=slot_eligibility, config=config
    )

    strength_before = build_team_strength(core_before)
    strength_after = build_team_strength(core_after)

    weakness_before = weakness_after = None
    if ranks is not None and team_count:
        weakness_before = build_team_weakness(core_before, ranks, team_count=team_count)
        weakness_after = build_team_weakness(core_after, ranks, team_count=team_count)

    # Movement is measured over the union of both cores plus everyone
    # who left, so a departing starter shows as displaced rather than
    # merely absent.
    idx_before, idx_after = _index(core_before), _index(core_after)
    movements: list[SlotMovement] = []
    for pid in sorted(set(idx_before) | set(idx_after)):
        b, a = idx_before.get(pid), idx_after.get(pid)
        src = b or a
        movements.append(
            SlotMovement(
                player_id=pid,
                canonical_name=(src.canonical_name if src else pid),
                position=(src.position if src else ""),
                slot_before=b.slot if b else None,
                slot_after=a.slot if a else None,
                role_before=b.role if b else None,
                role_after=a.role if a else None,
            )
        )

    return RosterSimulation(
        core_before=core_before,
        core_after=core_after,
        strength_before=strength_before,
        strength_after=strength_after,
        weakness_before=weakness_before,
        weakness_after=weakness_after,
        movements=tuple(m for m in movements if m.kind != "unchanged"),
        unpriced_incoming=frozenset(p.player_id for p in incoming_list if p.ros_value is None),
        outgoing_not_found=frozenset(leaving - on_roster),
        available=core_before.available and core_after.available,
        unavailable_reason=core_before.unavailable_reason or core_after.unavailable_reason,
    )
