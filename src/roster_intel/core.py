"""THE canonical Meaningful Roster Core (C2-CORE-01).

One site-wide answer to *"which players on this roster materially
contribute to its competitive/value portfolio"*, so that Team Strength,
Team Weakness, the age/value portfolio and roster-aware trade simulation
all select the same population instead of each inventing a top-N rule.

Binding requirement:
``docs/OWNER_FEATURE_ADDENDUM_2026-08-18_FLEX_STARTER_ASSIGNMENT.md``
(#899), amending #839, mirrored into ``docs/MASTER_PRODUCT_PLAN.md``
§4.1 and ``docs/OWNER_FEATURE_INVENTORY.md`` row 1.7.

The whole design is one idea
=============================

**Reserve demand is just more slots.**  So the reserve pass is the
*same exact solver*, run a second time over the players the starting
lineup did not take::

    starters  = assign_lineup(pool, league_slots)      # exact
    remaining = pool − starters − unpriced
    reserves  = assign_lineup(remaining, reserve_slots)  # exact, same owner
    core      = starters ∪ reserves

That is what §3's *"must use global legality-aware selection rather
than independent greedy lists that can assign the same player twice"*
asks for, and it makes every-player-at-most-once **structural** rather
than asserted: the solver already enforces one slot per player, and the
second pass cannot see a player the first one took.

It also gets the acceptance criteria right for free.  If the two best
remaining FLEX-eligible players are RB3 and WR4, the exact solve seats
them as FLEX **starters**; they leave the pool; so the first RB reserve
is RB4 and the WR reserves start at WR5.  No per-position list is
consulted at any point, which is precisely why RB3 cannot also be
counted as RB depth.

Why not a greedy
----------------
Because the repo already measured what a greedy costs here.  C2-U1
scored two production greedy lineup fills against Sleeper's own awarded
best-ball lineups over 10 real team-weeks: **0/10** and **5/10**, versus
**10/10** for ``solve_optimal_assignment``.  Reserve selection has the
same set-dependence FLEX creates, so it gets the same solver.

Superflex
---------
``d(QB) = qb_dedicated + sf_slots`` **before** the multiplier — the
literal #839 rule, recorded in ``config/roster_intel/meaningful_core.json``
as ``superflexFoldsIntoQb`` and reproducing the owner's own worked
example (1 QB + 1 SF ⇒ base 2 ⇒ ``ceil(1.5 × 2)`` = 3 meaningful QBs).

**The assumption this carries is named rather than buried:** the
*assignment* step makes no such claim.  If the exact solve seats a WR in
SUPER_FLEX — legal, and LI-5 measured SF going to a QB in 9 of 12 live
rosters, so 3 of 12 went elsewhere — that WR is a starter and leaves the
pool, while QB reserve demand still counts the SF slot as QB demand.
The two are consistent (nobody is double-counted) but the demand side is
an owner prior, not a measurement.  ``docs/roster-intelligence/``
carries the full note.

Missing is never zero
---------------------
``solve_optimal_assignment`` already refuses to seat a player whose
``ros_value is None`` — an unpriceable player must not win a slot a
priced one could fill — and reports them in
``LineupAssignment.unpriced_ids``.  This module carries that set onto
the core and **never** substitutes 0.  A core that is smaller than its
demand says so through ``unfilled_starter_slots`` /
``unfilled_reserve_slots``; it does not pad itself.

Pure computation.  No I/O beyond reading the config prior, no network,
no clock.
"""

from __future__ import annotations

import json
import math
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import Any, Collection, Iterable, Mapping, Sequence

from src.ros.lineup import (
    RosterPlayer,
    assign_lineup,
    lineup_position,
    normalize_slot,
    slot_demand,
)

__all__ = [
    "CoreMember",
    "MeaningfulCore",
    "ReserveDemand",
    "SUPERFLEX_SLOT",
    "build_meaningful_core",
    "load_core_config",
    "reserve_demand",
    "reserve_slot_list",
]

_CONFIG_PATH = (
    Path(__file__).resolve().parents[2] / "config" / "roster_intel" / "meaningful_core.json"
)

#: Defaults if the config file is missing/unreadable.  Identical to the
#: shipped file — a config read must not be able to change the number
#: silently by failing.
_DEFAULT_CONFIG: dict[str, Any] = {
    "reserveMultiplier": 1.5,
    "reserveMultiplierStatus": "PRIOR",
    "reserveMultiplierProvenance": "owner_addendum_839_amended_899",
    "superflexFoldsIntoQb": True,
}

SUPERFLEX_SLOT = "SUPER_FLEX"

#: Slots that exist in a lineup but generate no RESERVE demand.
#:
#: A reserve POLICY, not a slot classification — which is why it is the
#: only slot-shaped constant left here.  A kicker is a real starter and
#: is assigned as one; nobody carries a backup kicker as portfolio
#: value, and counting one would put a K in the population Team
#: Strength sums.  Whether ``K`` is a lineup slot at all is the lineup
#: owner's question and it answers yes; whether it earns a backup is
#: this module's, and it answers no.
_NO_RESERVE_SLOTS: frozenset[str] = frozenset({"K", "DEF"})


@lru_cache(maxsize=4)
def load_core_config(path: str | None = None) -> dict[str, Any]:
    """Read the core config, falling back to the shipped defaults.

    Cached because the reserve multiplier is read once per team per
    build and the file never changes within a process.
    """
    target = Path(path) if path else _CONFIG_PATH
    try:
        raw = json.loads(target.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return dict(_DEFAULT_CONFIG)
    if not isinstance(raw, dict):
        return dict(_DEFAULT_CONFIG)
    merged = dict(_DEFAULT_CONFIG)
    for key in _DEFAULT_CONFIG:
        if key in raw:
            merged[key] = raw[key]
    return merged


@dataclass(frozen=True)
class ReserveDemand:
    """How many reserve bodies each slot family demands, and why.

    ``by_slot`` is keyed by SLOT name, not by position, because that is
    what the second solve consumes: an extra ``FLEX`` slot carries the
    league's own flex eligibility, so no private position table is
    needed anywhere in this module.

    ``starter_basis`` records the slot count the multiplier was applied
    to — including the Superflex fold into QB — so a consumer can audit
    the arithmetic without re-deriving it.

    ``flex_slots`` names which of those basis keys are FLEX SLOTS rather
    than positions, read from the canonical owner's own
    ``slot_demand().flex_capacity``.  It is published because consumers
    genuinely need the split — Team Weakness ranks players within a
    POSITION and a flex slot is not one — and publishing it is what let
    ``weakness.py`` stop importing ``core._is_dedicated``.
    """

    by_slot: dict[str, int] = field(default_factory=dict)
    starter_basis: dict[str, int] = field(default_factory=dict)
    flex_slots: frozenset[str] = frozenset()
    multiplier: float = 1.5
    multiplier_status: str = "PRIOR"
    multiplier_provenance: str = "owner_addendum_839_amended_899"
    superflex_folded_into_qb: bool = True

    def total(self) -> int:
        return sum(self.by_slot.values())

    @property
    def dedicated_basis(self) -> dict[str, int]:
        """The basis entries that name a POSITION, not a flex slot.

        The question Team Weakness asks — "how many real QBs does this
        league start" — and the reason it no longer reaches into this
        module's privates to answer it.
        """
        return {k: v for k, v in self.starter_basis.items() if k not in self.flex_slots}

    def to_dict(self) -> dict[str, Any]:
        return {
            "bySlot": dict(sorted(self.by_slot.items())),
            "starterBasis": dict(sorted(self.starter_basis.items())),
            "dedicatedBasis": dict(sorted(self.dedicated_basis.items())),
            "flexSlots": sorted(self.flex_slots),
            "total": self.total(),
            "multiplier": self.multiplier,
            "multiplierStatus": self.multiplier_status,
            "multiplierProvenance": self.multiplier_provenance,
            "superflexFoldedIntoQb": self.superflex_folded_into_qb,
        }


@dataclass(frozen=True)
class CoreMember:
    """One player in the meaningful core, and the slot that admitted them.

    ``role`` is ``"starter"`` or ``"reserve"``.  ``slot`` is the slot the
    exact solve seated them in — a FLEX starter carries ``"FLEX"``, which
    is the *internal assignment fact* §5 says may be exposed
    diagnostically while never becoming a sortable Team Strength
    position.  ``position`` stays the player's NATIVE position, which is
    the one Team Strength groups on.
    """

    player_id: str
    canonical_name: str
    position: str
    slot: str
    role: str
    value: float

    def to_dict(self) -> dict[str, Any]:
        return {
            "playerId": self.player_id,
            "name": self.canonical_name,
            "position": self.position,
            "slot": self.slot,
            "role": self.role,
            "value": round(self.value, 3),
        }


@dataclass(frozen=True)
class MeaningfulCore:
    """The canonical meaningful-roster population for ONE team.

    Consumers read ``members`` (or ``starters`` / ``reserves``) and must
    not re-select.  ``unpriced_ids`` is the third state — neither in the
    core nor excluded on merit — and is reported so a consumer can say
    "we could not price 4 of this roster" instead of implying it scored
    them at zero.
    """

    members: tuple[CoreMember, ...] = ()
    unpriced_ids: frozenset[str] = frozenset()
    duplicate_ids: frozenset[str] = frozenset()
    unfilled_starter_slots: tuple[str, ...] = ()
    unfilled_reserve_slots: tuple[str, ...] = ()
    starter_slots: tuple[str, ...] = ()
    demand: ReserveDemand = field(default_factory=ReserveDemand)
    slot_source: str | None = None
    available: bool = True
    unavailable_reason: str | None = None

    @property
    def starters(self) -> tuple[CoreMember, ...]:
        return tuple(m for m in self.members if m.role == "starter")

    @property
    def reserves(self) -> tuple[CoreMember, ...]:
        return tuple(m for m in self.members if m.role == "reserve")

    @property
    def core_ids(self) -> frozenset[str]:
        return frozenset(m.player_id for m in self.members)

    def by_position(self) -> dict[str, tuple[CoreMember, ...]]:
        """Core members grouped on their NATIVE position.

        A FLEX-assigned RB groups under RB.  That is what §5's "FLEX is
        not a separate sortable Team Strength position" means in
        practice: the value belongs to the team and to the player's own
        room, and the flex fact lives on ``CoreMember.slot``.
        """
        out: dict[str, list[CoreMember]] = {}
        for m in self.members:
            out.setdefault(m.position, []).append(m)
        return {k: tuple(v) for k, v in sorted(out.items())}

    def to_dict(self) -> dict[str, Any]:
        return {
            "available": self.available,
            "unavailableReason": self.unavailable_reason,
            "members": [m.to_dict() for m in self.members],
            "starterCount": len(self.starters),
            "reserveCount": len(self.reserves),
            "unpricedIds": sorted(self.unpriced_ids),
            "duplicateIds": sorted(self.duplicate_ids),
            "unfilledStarterSlots": list(self.unfilled_starter_slots),
            "unfilledReserveSlots": list(self.unfilled_reserve_slots),
            "starterSlots": list(self.starter_slots),
            "slotSource": self.slot_source,
            "demand": self.demand.to_dict(),
        }


def reserve_demand(
    starter_slots: Sequence[str],
    *,
    config: Mapping[str, Any] | None = None,
    slot_eligibility: Mapping[str, Collection[str]] | None = None,
) -> ReserveDemand:
    """Reserve demand per slot family, from the league's REAL slot list.

    ``reserve_demand(p) = ceil(M × starters(p)) − starters(p)``, applied
    per dedicated position and per ordinary/IDP flex slot name
    (addendum §3).  Superflex is folded into QB first when the config
    says so, which is the one place the #839 rule is applied.

    ``ceil`` is the addendum's own operator, not a rounding choice:
    ``M = 1.5`` on a single dedicated slot yields ``ceil(1.5) − 1 = 1``,
    so every real starting position gets at least one backup, and a
    2-slot position gets one rather than two.

    **The basis IS the canonical owner's answer.**  ``lineup.slot_demand``
    already publishes ``dedicated`` (per position) and ``flex_capacity``
    (per flex slot name) as separate named quantities, and this consumes
    both rather than counting the slot list again.  The re-derivation it
    replaces was wrong in a way nothing caught: it never consulted
    ``lineup.NON_LINEUP_SLOTS``, so fed a league's raw ``rosterPositions``
    it reported ``BN: 37, IR: 1, TAXI: 1`` as positions with reserve
    demand, and ``weakness`` carried that through into rungs.  Not
    reachable from production — every traced caller passed
    already-filtered slots — which is exactly how it survived.

    It also needed a private list of flex slot names to decide which
    slots got per-slot demand.  That list is gone: a flex slot is one
    the owner reports in ``flex_capacity``, so a slot added there can no
    longer be silently zeroed here by omission.

    ``slot_eligibility`` is the league's CONFIGURED flex eligibility
    (``flexEligible`` / ``sflexEligible`` / ``idpFlexEligible``).  It is
    threaded through for the same reason :func:`build_meaningful_core`
    threads it into the solve: a core that seats starters under the
    league's own rules and computes reserves under the defaults is
    internally inconsistent.
    """
    cfg = dict(_DEFAULT_CONFIG)
    cfg.update(config or load_core_config())
    multiplier = float(cfg["reserveMultiplier"])
    fold_sf = bool(cfg["superflexFoldsIntoQb"])

    canonical = slot_demand(starter_slots, eligibility_overrides=slot_eligibility)

    # Dedicated positions, minus the ones that earn no backup.
    basis: dict[str, int] = {
        pos: int(n) for pos, n in canonical.dedicated.items() if pos not in _NO_RESERVE_SLOTS
    }
    # Flex slots carry demand on the SLOT, not split across the positions
    # it accepts — a FLEX reserve is "one more flex body", and splitting
    # it would put fractional demand on positions the league may not even
    # be short of.  SUPER_FLEX is excluded here and folded below.
    for slot, n in canonical.flex_capacity.items():
        if slot in _NO_RESERVE_SLOTS or slot == SUPERFLEX_SLOT:
            continue
        basis[slot] = basis.get(slot, 0) + int(n)

    sf_slots = int(canonical.flex_capacity.get(SUPERFLEX_SLOT, 0))
    if fold_sf and sf_slots:
        # #839: a Superflex slot IS real QB demand.  Added before the
        # multiplier, which is what makes 1 QB + 1 SF produce three
        # meaningful QBs rather than two.  With the fold off, SF
        # generates no reserve demand of its own — the alternative the
        # owner did not pick.
        basis["QB"] = basis.get("QB", 0) + sf_slots

    basis = {k: v for k, v in basis.items() if v > 0}
    by_slot = {slot: math.ceil(multiplier * n) - n for slot, n in basis.items()}
    return ReserveDemand(
        by_slot={k: v for k, v in by_slot.items() if v > 0},
        starter_basis=basis,
        flex_slots=frozenset(canonical.flex_capacity) - {SUPERFLEX_SLOT},
        multiplier=multiplier,
        multiplier_status=str(cfg["reserveMultiplierStatus"]),
        multiplier_provenance=str(cfg["reserveMultiplierProvenance"]),
        superflex_folded_into_qb=fold_sf,
    )


def reserve_slot_list(demand: ReserveDemand) -> list[str]:
    """Flatten reserve demand into a slot list the solver can consume.

    Sorted for determinism.  These are ordinary slot names, so the
    second solve applies exactly the same eligibility rules as the
    first — which is the reason this module needs no eligibility table
    of its own.
    """
    out: list[str] = []
    for slot in sorted(demand.by_slot):
        out.extend([slot] * demand.by_slot[slot])
    return out


def build_meaningful_core(
    pool: Iterable[RosterPlayer],
    starter_slots: Sequence[str],
    *,
    slot_eligibility: Mapping[str, Collection[str]] | None = None,
    config: Mapping[str, Any] | None = None,
    slot_source: str | None = None,
) -> MeaningfulCore:
    """THE meaningful-core entry point.  Two exact solves, in order.

    Args:
        pool: the roster, as canonical ``RosterPlayer`` rows.  Draft
            picks are not eligible players and must not be in here —
            they are portfolio value, not roster construction.
        starter_slots: the league's REAL flattened starter slots, from
            ``lineup.resolve_starter_slots``.  An empty list is a
            REFUSAL, not an empty lineup: the core comes back
            ``available=False`` with ``no_starter_slots``, because
            "this league starts nobody" and "we do not know this
            league's lineup" must not read the same.
        slot_eligibility: the league's CONFIGURED flex eligibility
            (``flexEligible`` / ``sflexEligible`` / ``idpFlexEligible``),
            passed through to both solves unchanged.
    """
    pool_list = list(pool)
    slots = [normalize_slot(str(s)) for s in starter_slots if str(s).strip()]
    demand = reserve_demand(slots, config=config, slot_eligibility=slot_eligibility)

    if not slots:
        return MeaningfulCore(
            available=False,
            unavailable_reason="no_starter_slots",
            demand=demand,
        )

    # ── Pass 1: the ACTUAL starting lineup, dedicated + FLEX + SF + IDP
    # FLEX together.  One solve, so a FLEX seat is decided against the
    # same objective as a dedicated one.
    starters = assign_lineup(pool_list, slots, slot_eligibility=slot_eligibility)
    starter_ids = starters.starter_ids

    members: list[CoreMember] = [
        _member(p, starters.slots[i], "starter") for i, p in sorted(starters.assignments.items())
    ]

    # ── Pass 2: reserves, from what is LEFT.  Removing the starters
    # here is the entire acceptance-criteria story: RB3 seated at FLEX
    # is not in `remaining`, so the RB reserve slot must reach RB4.
    remaining = [p for p in pool_list if p.player_id not in starter_ids]
    reserve_slots = reserve_slot_list(demand)
    reserve_unfilled: tuple[str, ...] = ()
    if reserve_slots:
        reserves = assign_lineup(remaining, reserve_slots, slot_eligibility=slot_eligibility)
        members.extend(
            _member(p, reserves.slots[i], "reserve")
            for i, p in sorted(reserves.assignments.items())
        )
        reserve_unfilled = tuple(reserves.unfilled_slots)

    return MeaningfulCore(
        members=tuple(members),
        # Unpriced is measured over the WHOLE roster, not the leftovers:
        # a player we cannot price is unpriced whether or not a slot
        # would have wanted them.
        unpriced_ids=starters.unpriced_ids,
        duplicate_ids=starters.duplicate_ids,
        unfilled_starter_slots=tuple(starters.unfilled_slots),
        unfilled_reserve_slots=reserve_unfilled,
        starter_slots=tuple(slots),
        demand=demand,
        slot_source=slot_source,
    )


def _member(player: RosterPlayer, slot: str, role: str) -> CoreMember:
    """Build one core member.

    ``value`` is the player's own ``ros_value``, NOT the solver's
    health-adjusted objective.  The objective exists to decide *who
    starts*; the portfolio value of an injured player is his value, and
    discounting it here would quietly apply the injury penalty a second
    time in every downstream sum.

    ``ros_value`` is asserted rather than coerced.  Only assigned
    players reach here, and ``solve_optimal_assignment`` already proved
    their objective is not ``None`` — so a ``None`` at this point is a
    broken invariant upstream, and ``or 0.0`` would turn it into a real
    player worth nothing.
    """
    if player.ros_value is None:  # pragma: no cover — invariant guard
        raise ValueError(
            f"assigned player {player.player_id!r} has no value; "
            "solve_optimal_assignment must not seat an unpriced player"
        )
    return CoreMember(
        player_id=player.player_id,
        canonical_name=player.canonical_name or player.player_id,
        position=lineup_position(player.position),
        slot=slot,
        role=role,
        value=float(player.ros_value),
    )
