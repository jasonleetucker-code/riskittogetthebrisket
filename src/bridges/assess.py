"""Decide, per bridge, whether it may translate — and say why when it may not.

This is the policy layer.  ``descriptor.measure_capability`` reports what the
board can do; this module combines that with the declared comparability, the
acquisition outcome and the family census to produce one
:class:`~src.bridges.descriptor.BridgeAssessment` per bridge.

The order of the checks IS the policy, and it is ordered by how fundamental
the objection is, so the reported reason is the most useful one rather than
merely the first one a loop happened to hit:

1. **comparability** — if the two halves are not the same quantity, nothing
   else matters.  ``PENDING`` fails closed here: an unproven bridge does not
   vote.  This is what keeps "the vendor says it is one engine" from
   substituting for evidence.
2. **acquisition** — a bridge whose halves did not arrive cannot translate.
   ``AUTH_REQUIRED`` is preserved distinctly through to the reason string so
   an operator sees an owner action rather than an outage.
3. **freshness** — stale rows are real, but a stale bridge asserting a
   CURRENT cross-position relationship is a false claim, so ``STALE`` is not
   usable.
4. **capability** — measured, never declared.  A family that does not span
   both pools, or whose ladder is the identity, is
   ``INSUFFICIENT_COVERAGE`` however it is flagged in the registry.
5. **family independence** — two bridges from one provider are one opinion.
   The second is ``DEPENDENT_SOURCE_FAMILY``: retained, reported, and not
   counted again.

Nothing here weights bridges against each other.  Combining several bridges'
opinions is a separate decision with an existing canonical owner (the
count-aware mean-median that already blends the cross-market anchor), and
inventing a weighting rule here would be a second one.
"""

from __future__ import annotations

from typing import Any, Iterable, Mapping, Sequence

from src.bridges import states as bridge_states
from src.bridges.descriptor import (
    BridgeAssessment,
    BridgeCapability,
    BridgeDescriptor,
    measure_capability,
)
from src.sources import acquisition_state as acq

__all__ = ["assess_bridge", "assess_bridges", "usable_bridges"]


def _acquisition_verdict(
    descriptor: BridgeDescriptor,
    acquisition: Mapping[str, acq.AcquisitionOutcome] | None,
) -> tuple[str, str] | None:
    """``(state, reason)`` when acquisition alone decides, else ``None``."""
    if not acquisition:
        return None

    seen = [acquisition[k] for k in descriptor.keys if k in acquisition]
    if not seen:
        return None

    # A half that never arrived is fatal: a bridge needs both.
    failed = [o for o in seen if not o.acquired]
    if failed:
        worst = failed[0]
        for outcome in failed:
            if outcome.state == acq.AUTH_REQUIRED:
                worst = outcome
                break
        return (
            bridge_states.UNAVAILABLE,
            f"{worst.source_key}: {worst.state}" + (f" — {worst.reason}" if worst.reason else ""),
        )

    stale = [o for o in seen if o.state == acq.STALE]
    if stale:
        return (
            bridge_states.STALE,
            "stale halves: " + ", ".join(sorted(o.source_key for o in stale)),
        )

    no_cross = [o for o in seen if o.state == acq.NO_CROSS_POSITION_COVERAGE]
    if no_cross:
        return (
            bridge_states.INSUFFICIENT_COVERAGE,
            "acquired without cross-position coverage: "
            + ", ".join(sorted(o.source_key for o in no_cross)),
        )
    return None


def assess_bridge(
    descriptor: BridgeDescriptor,
    rows: Iterable[Mapping[str, Any]],
    *,
    offense_positions: Sequence[str] | frozenset[str],
    idp_positions: Sequence[str] | frozenset[str],
    acquisition: Mapping[str, acq.AcquisitionOutcome] | None = None,
    claimed_families: Iterable[str] = (),
    capability: BridgeCapability | None = None,
) -> BridgeAssessment:
    """Assess ONE bridge.  ``claimed_families`` are families already counted."""
    rows = list(rows or [])
    if capability is None:
        capability = measure_capability(
            descriptor,
            rows,
            offense_positions=offense_positions,
            idp_positions=idp_positions,
        )

    if descriptor.comparability == bridge_states.DISPROVEN:
        return BridgeAssessment(
            descriptor,
            capability,
            bridge_states.NOT_COMPARABLE,
            descriptor.comparability_evidence
            or "offense and IDP halves are proven not to share a basis",
        )
    if descriptor.comparability == bridge_states.PENDING:
        return BridgeAssessment(
            descriptor,
            capability,
            bridge_states.NOT_COMPARABLE,
            "comparability PENDING — an unproven bridge does not vote"
            + (
                f": {descriptor.comparability_evidence}"
                if descriptor.comparability_evidence
                else ""
            ),
        )

    verdict = _acquisition_verdict(descriptor, acquisition)
    if verdict is not None:
        return BridgeAssessment(descriptor, capability, verdict[0], verdict[1])

    if not capability.spans_both_pools:
        return BridgeAssessment(
            descriptor,
            capability,
            bridge_states.INSUFFICIENT_COVERAGE,
            f"does not span both pools (offense={capability.offense_values}, "
            f"idp={capability.idp_values})",
        )
    if capability.ladder_depth == 0:
        return BridgeAssessment(
            descriptor,
            capability,
            bridge_states.INSUFFICIENT_COVERAGE,
            "no IDP entries in the combined pool",
        )
    if capability.is_identity_ladder:
        return BridgeAssessment(
            descriptor,
            capability,
            bridge_states.INSUFFICIENT_COVERAGE,
            f"ladder starts at {capability.ladder_start} — that is the identity, "
            "i.e. the best defender priced as the best asset",
        )

    if descriptor.family in set(claimed_families):
        return BridgeAssessment(
            descriptor,
            capability,
            bridge_states.DEPENDENT_SOURCE_FAMILY,
            f"family {descriptor.family!r} is already represented by another bridge",
        )

    return BridgeAssessment(descriptor, capability, bridge_states.VALID)


def assess_bridges(
    descriptors: Sequence[BridgeDescriptor],
    rows: Iterable[Mapping[str, Any]],
    *,
    offense_positions: Sequence[str] | frozenset[str],
    idp_positions: Sequence[str] | frozenset[str],
    acquisition: Mapping[str, acq.AcquisitionOutcome] | None = None,
) -> list[BridgeAssessment]:
    """Assess every bridge, deduplicating provider families in declared order.

    Declared order decides which member of a family is counted, so the result
    is deterministic and the registry — not the board's row order — is what
    a reader consults to know which one won.
    """
    rows = list(rows or [])
    claimed: set[str] = set()
    out: list[BridgeAssessment] = []
    for descriptor in descriptors:
        assessment = assess_bridge(
            descriptor,
            rows,
            offense_positions=offense_positions,
            idp_positions=idp_positions,
            acquisition=acquisition,
            claimed_families=claimed,
        )
        if assessment.usable:
            claimed.add(descriptor.family)
        out.append(assessment)
    return out


def usable_bridges(assessments: Iterable[BridgeAssessment]) -> list[BridgeAssessment]:
    return [a for a in assessments if a.usable]
