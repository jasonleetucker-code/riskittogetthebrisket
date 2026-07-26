"""League Twin bridge: roster change → playoff/championship odds (LI-8).

What was missing
────────────────
``src/ros/playoff_sim.py::simulate_trade_impact`` is the League Twin's
trade path, and it takes ``strength_delta`` — ``ownerId → change in
that team's weekly scoring MEAN``.  Nothing produced that map.  A
caller had to invent the number, which is the part that actually
requires simulating a roster.

``src.league_intel.sim`` produces exactly that number from real
rosters.  This module is the join, and it is deliberately thin: no new
simulator, no second points model, no reimplementation of either side.

Two things it must get right, and both are easy to get silently wrong.

1. THE MULTIPLICATIVE BLEND — handled exactly, not approximated
──────────────────────────────────────────────────────────────
``_TeamDist.mean`` is not the presim mean.  It is::

    blended_mean = presim_mean * (1 + ROS_BLEND * ros_z)

with ``ROS_BLEND = 0.20`` and ``ros_z`` the team's ROS-strength
z-score.  So a delta measured in presim points is in the WRONG units
for a field that lives downstream of that multiplication.  Feeding a
raw presim delta understates (or overstates) the effect by the blend
factor — up to roughly ±40% at ``|ros_z| = 2``, which is not a rounding
error.

Because the blend is multiplicative it scales exactly::

    delta_on_TeamDist = (presim_after - presim_before) * (1 + ROS_BLEND * ros_z)

so this module applies the same factor rather than approximating it.

**ASSUMED, and stated because it is the one soft spot:** that ``ros_z``
itself is unchanged by the trade.  It is not — ``ros_z`` derives from
``teamRosStrength``, which a roster change moves.  Capturing that needs
a team-strength recompute per trade arm, which this module deliberately
does not do.  The residual is second-order (a change in the *blend* of
a change in the *mean*) and is stamped on every result rather than
buried.  ``blend_factor`` is returned so a caller can see exactly what
was applied.

2. THE VARIANCE THEIR DESIGN DISCARDS
─────────────────────────────────────
``simulate_trade_impact`` builds its "after" distributions with
``sd=d.sd`` — copied unchanged.  So a trade's effect on *variance* is
dropped entirely, and in best ball variance is precisely what roster
depth changes: consolidating four flex bodies into one stud raises the
mean and lowers the floor, and those are different trades to a team
that needs a ceiling versus one protecting a lead.

That is not a defect in their code — a scalar mean shift is a coherent
model and their paired-seed design depends on the draw count being
identical across arms.  But the information exists and should not
vanish silently, so ``sd_delta`` is computed and reported alongside.
It is **not** fed into ``simulate_trade_impact``; feeding it would
require re-deriving the distributions, which is a different design.
Callers that care about ceiling-vs-floor read it directly.

Unavailable is not zero
───────────────────────
An owner whose roster cannot be simulated gets **no entry** in the
delta map and an explicit ``unavailable`` record.  Returning 0.0 would
tell ``simulate_trade_impact`` "this trade does not move this team",
which is a claim, not an absence of one.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Iterable, Mapping, Sequence

from src.league_intel.sim import DEFAULT_SIM_WEEKS, simulate_trade_delta

__all__ = [
    "TWIN_BRIDGE_VERSION",
    "OwnerStrengthDelta",
    "TradeStrengthDeltas",
    "strength_deltas_from_rosters",
]

TWIN_BRIDGE_VERSION = "li.twin.2026-07-26.v1"

ROS_Z_ASSUMPTION = (
    "ros_z is assumed UNCHANGED by the trade. It derives from teamRosStrength, "
    "which a roster change moves, so the blend factor applied here is the "
    "pre-trade one. The residual is second-order (a change in the blend of a "
    "change in the mean) and is not captured; capturing it needs a "
    "team-strength recompute per arm."
)

SD_NOT_PROPAGATED = (
    "sd_delta is REPORTED but NOT fed into simulate_trade_impact, which copies "
    "sd unchanged by design. A trade that raises the ceiling while lowering the "
    "floor will show a mean delta only."
)


@dataclass(frozen=True)
class OwnerStrengthDelta:
    """One owner's simulated change, in ``_TeamDist.mean`` units."""

    owner_id: str
    mean_delta: float | None
    sd_delta: float | None
    blend_factor: float
    raw_mean_delta: float | None
    confidence: float = 0.0
    unavailable_reason: str | None = None

    @property
    def is_available(self) -> bool:
        return self.mean_delta is not None

    def to_dict(self) -> dict[str, Any]:
        return {
            "ownerId": self.owner_id,
            "meanDelta": self.mean_delta,
            "sdDelta": self.sd_delta,
            "blendFactor": self.blend_factor,
            "rawMeanDelta": self.raw_mean_delta,
            "confidence": self.confidence,
            "isAvailable": self.is_available,
            "unavailableReason": self.unavailable_reason,
        }


@dataclass
class TradeStrengthDeltas:
    """Everything ``simulate_trade_impact`` needs, plus what it drops."""

    per_owner: list[OwnerStrengthDelta] = field(default_factory=list)
    bridge_version: str = TWIN_BRIDGE_VERSION
    assumptions: list[str] = field(default_factory=list)

    @property
    def strength_delta(self) -> dict[str, float]:
        """The map to hand to ``simulate_trade_impact``.

        Owners whose rosters could not be simulated are ABSENT, not
        zero — ``simulate_trade_impact`` treats a missing owner as
        unmoved, which is the correct reading of "no information",
        whereas an explicit 0.0 would assert the trade is neutral for
        them.
        """
        return {d.owner_id: d.mean_delta for d in self.per_owner if d.mean_delta is not None}

    @property
    def unavailable(self) -> list[OwnerStrengthDelta]:
        return [d for d in self.per_owner if not d.is_available]

    def to_dict(self) -> dict[str, Any]:
        return {
            "bridgeVersion": self.bridge_version,
            "strengthDelta": self.strength_delta,
            "perOwner": [d.to_dict() for d in self.per_owner],
            "unavailableCount": len(self.unavailable),
            "assumptions": list(self.assumptions),
        }


def _blend_factor(ros_z: float | None, ros_blend: float) -> float:
    """The multiplier ``_TeamDist.mean`` already had applied.

    Mirrors ``playoff_sim``'s ``blended_mean = emp_mean * (1 + ROS_BLEND
    * ros_z)``.  When the owner had no ROS strength score the simulator
    skips the blend entirely, so the factor is exactly 1.0.
    """
    if ros_z is None:
        return 1.0
    return 1.0 + ros_blend * float(ros_z)


def strength_deltas_from_rosters(
    rosters_before: Mapping[str, Iterable[Mapping[str, Any]]],
    rosters_after: Mapping[str, Iterable[Mapping[str, Any]]],
    starter_slots: Sequence[str],
    *,
    ros_z_by_owner: Mapping[str, float] | None = None,
    ros_blend: float | None = None,
    weeks: int = DEFAULT_SIM_WEEKS,
    seed: int = 0,
    points_model: Any = None,
) -> TradeStrengthDeltas:
    """Simulate each changed roster and emit ``simulate_trade_impact`` input.

    ``rosters_before`` / ``rosters_after`` map ownerId → full roster
    rows (the ``fullRoster`` shape from the team-strength snapshot).
    Pass FULL rosters: best ball pays for the tail, and a truncated
    roster is the wrong input (ADR-011).

    Only owners present in BOTH maps are simulated — a trade cannot
    move a team that isn't in the league snapshot.

    ``ros_z_by_owner`` supplies each owner's ROS-strength z-score so the
    presim-units delta can be scaled into ``_TeamDist.mean`` units.
    Omitting it applies a factor of 1.0, which is correct only when the
    simulator ran without a ROS-strength map — so it is a defensible
    default, not a silent one, and ``blend_factor`` is reported per
    owner either way.
    """
    if ros_blend is None:
        from src.ros.playoff_sim import ROS_BLEND  # noqa: PLC0415

        ros_blend = ROS_BLEND
    z_map = ros_z_by_owner or {}

    out = TradeStrengthDeltas(
        assumptions=[
            ROS_Z_ASSUMPTION,
            SD_NOT_PROPAGATED,
            "deltas are in _TeamDist.mean units: presim points scaled by the "
            "same multiplicative ROS blend the simulator applied",
        ]
    )

    for owner in rosters_before:
        if owner not in rosters_after:
            continue
        factor = _blend_factor(z_map.get(owner), ros_blend)
        delta = simulate_trade_delta(
            rosters_before[owner],
            rosters_after[owner],
            starter_slots,
            weeks=weeks,
            seed=seed,
            points_model=points_model,
        )
        if not delta.is_available:
            out.per_owner.append(
                OwnerStrengthDelta(
                    owner_id=owner,
                    mean_delta=None,
                    sd_delta=None,
                    blend_factor=factor,
                    raw_mean_delta=None,
                    confidence=0.0,
                    unavailable_reason=delta.unavailable_reason,
                )
            )
            continue
        out.per_owner.append(
            OwnerStrengthDelta(
                owner_id=owner,
                mean_delta=delta.mean_delta * factor,
                sd_delta=delta.sd_delta,
                blend_factor=factor,
                raw_mean_delta=delta.mean_delta,
                confidence=delta.confidence,
            )
        )
    return out
