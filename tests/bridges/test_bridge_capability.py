"""Bridge capability is MEASURED, and a family is the unit that can bridge.

Two properties are pinned here, and the second is the repair.

**Capability, not a label.**  ``tests/consensus_edge/test_fair_value.py::
TestTheGuardIsACapabilityNotAFlag`` demonstrated that the pipeline's
``is_backbone`` flag can be moved onto a source that cannot seed a ladder,
satisfying the guard while leaving the board exactly as broken.  Nothing in
this package consults a flag for that question.

**A bridge is a FAMILY, not a key.**  Draft Sharks publishes offense and IDP
on one native scale from one league-scored pass, but the halves are
registered under two keys.  Measured per key, its IDP half carries zero
offense values and produces the identity ladder ``[1, 2, 3, …]`` — which is
precisely the fallback the crosswalk exists to prevent.  Measured per family,
it is a real second bridge.  ``TestTheFamilyRuleIsWhatMakesThisWork`` asserts
both halves of that, so the suite cannot pass with or without the repair.
"""

from __future__ import annotations

import pytest

from src.bridges import (
    CARDINAL,
    DEPENDENT_SOURCE_FAMILY,
    DISPROVEN,
    INSUFFICIENT_COVERAGE,
    NOT_COMPARABLE,
    ORDINAL,
    PENDING,
    QUALIFIED,
    VALID,
    BridgeDescriptor,
    assess_bridge,
    assess_bridges,
    measure_capability,
)
from src.bridges.descriptor import BridgeDescriptorError
from src.bridges.states import STALE as BRIDGE_STALE
from src.bridges.states import UNAVAILABLE as BRIDGE_UNAVAILABLE
from src.sources import acquisition_state as acq

OFFENSE = frozenset({"QB", "RB", "WR", "TE"})
IDP = frozenset({"DL", "LB", "DB"})


def _row(name: str, position: str, **values: float) -> dict:
    return {"displayName": name, "position": position, "canonicalSiteValues": dict(values)}


def _two_key_board() -> list[dict]:
    """A vendor whose offense and IDP halves sit under different keys.

    Offense values dominate, so a family-wide pool puts the best defender
    behind several offensive assets — a real ladder.
    """
    return [
        _row("Off One", "QB", vendorOff=100.0),
        _row("Off Two", "RB", vendorOff=72.0),
        _row("Off Three", "WR", vendorOff=64.0),
        _row("Def One", "LB", vendorIdp=53.0),
        _row("Def Two", "DB", vendorIdp=36.0),
        _row("Def Three", "DL", vendorIdp=11.0),
    ]


def _descriptor(**over) -> BridgeDescriptor:
    base = dict(
        bridge_key="vendor",
        display_name="Vendor",
        family="vendor",
        kind=CARDINAL,
        offense_keys=("vendorOff",),
        idp_keys=("vendorIdp",),
        comparability=QUALIFIED,
        comparability_evidence="measured shared scale",
    )
    base.update(over)
    return BridgeDescriptor(**base)


class TestTheFamilyRuleIsWhatMakesThisWork:
    """RED -> GREEN, asserted in one place rather than assumed."""

    def test_measured_per_key_the_idp_half_cannot_bridge(self) -> None:
        """The pre-repair rule: one key, and it spans only one pool."""
        single_key = _descriptor(offense_keys=("vendorIdp",), idp_keys=("vendorIdp",))
        cap = measure_capability(
            single_key, _two_key_board(), offense_positions=OFFENSE, idp_positions=IDP
        )
        assert cap.offense_values == 0, "fixture does not reproduce the defect"
        assert cap.spans_both_pools is False
        assert cap.is_identity_ladder is True, (
            "the single-key rule must produce the identity ladder here, or this "
            "suite would pass with or without the family repair"
        )
        assert cap.capable is False

    def test_measured_per_family_the_same_vendor_bridges(self) -> None:
        cap = measure_capability(
            _descriptor(), _two_key_board(), offense_positions=OFFENSE, idp_positions=IDP
        )
        assert cap.offense_values == 3
        assert cap.idp_values == 3
        assert cap.spans_both_pools is True
        assert cap.ladder_start == 4, "the best defender sits behind three offensive assets"
        assert cap.is_identity_ladder is False
        assert cap.capable is True


class TestCapabilityIsMeasuredNotDeclared:
    def test_an_identity_ladder_is_refused_however_it_is_declared(self) -> None:
        """Both pools present, but a defender tops the combined pool.

        This is the shape that matters: the bridge genuinely spans offense and
        IDP, so it clears every coverage check, and its ladder still says the
        best defender is the best asset — which is the claim the crosswalk
        exists to prevent a source from making.
        """
        rows = [
            _row("Def One", "LB", vendorIdp=99.0),
            _row("Off One", "QB", vendorOff=53.0),
            _row("Def Two", "DB", vendorIdp=36.0),
        ]
        assessment = assess_bridge(
            _descriptor(), rows, offense_positions=OFFENSE, idp_positions=IDP
        )
        assert assessment.capability.ladder_start == 1
        assert assessment.state == INSUFFICIENT_COVERAGE
        assert "identity" in assessment.reason
        assert assessment.usable is False

    def test_depth_alone_does_not_confer_capability(self) -> None:
        """A deep IDP-only board still produces the identity ladder."""
        rows = [_row(f"Def {i}", "LB", vendorIdp=float(500 - i)) for i in range(200)]
        cap = measure_capability(_descriptor(), rows, offense_positions=OFFENSE, idp_positions=IDP)
        assert cap.ladder_depth == 200
        assert cap.capable is False


class TestComparabilityFailsClosed:
    def test_pending_does_not_vote(self) -> None:
        assessment = assess_bridge(
            _descriptor(comparability=PENDING, comparability_evidence="basis unproven"),
            _two_key_board(),
            offense_positions=OFFENSE,
            idp_positions=IDP,
        )
        assert assessment.state == NOT_COMPARABLE
        assert assessment.usable is False
        assert "PENDING" in assessment.reason

    def test_a_pending_bridge_is_still_capable_and_still_refused(self) -> None:
        """Capability and permission are different questions."""
        assessment = assess_bridge(
            _descriptor(comparability=PENDING),
            _two_key_board(),
            offense_positions=OFFENSE,
            idp_positions=IDP,
        )
        assert assessment.capability.capable is True
        assert assessment.usable is False

    def test_disproven_does_not_vote(self) -> None:
        assessment = assess_bridge(
            _descriptor(comparability=DISPROVEN, comparability_evidence="different bases"),
            _two_key_board(),
            offense_positions=OFFENSE,
            idp_positions=IDP,
        )
        assert assessment.state == NOT_COMPARABLE

    def test_qualified_without_evidence_is_refused_at_construction(self) -> None:
        with pytest.raises(BridgeDescriptorError) as exc:
            _descriptor(comparability=QUALIFIED, comparability_evidence="")
        assert "unevidenced qualification" in str(exc.value)

    def test_a_one_pool_bridge_is_refused_at_construction(self) -> None:
        with pytest.raises(BridgeDescriptorError) as exc:
            BridgeDescriptor(
                bridge_key="half",
                display_name="Half",
                family="half",
                kind=ORDINAL,
                offense_keys=(),
                idp_keys=("x",),
            )
        assert "BOTH an offense half and" in str(exc.value)


class TestAcquisitionGatesTheBridge:
    def test_a_failed_half_makes_the_bridge_unavailable(self) -> None:
        assessment = assess_bridge(
            _descriptor(),
            _two_key_board(),
            offense_positions=OFFENSE,
            idp_positions=IDP,
            acquisition={
                "vendorOff": acq.AcquisitionOutcome("vendorOff", acq.HEALTHY, row_count=3),
                "vendorIdp": acq.AcquisitionOutcome(
                    "vendorIdp", acq.PARSE_FAILED, reason="table shape changed"
                ),
            },
        )
        assert assessment.state == BRIDGE_UNAVAILABLE
        assert "PARSE_FAILED" in assessment.reason

    def test_auth_required_survives_into_the_reason(self) -> None:
        """An owner action must not read as an outage."""
        assessment = assess_bridge(
            _descriptor(),
            _two_key_board(),
            offense_positions=OFFENSE,
            idp_positions=IDP,
            acquisition={
                "vendorIdp": acq.AcquisitionOutcome(
                    "vendorIdp", acq.AUTH_REQUIRED, reason="owner session not available"
                )
            },
        )
        assert "AUTH_REQUIRED" in assessment.reason

    def test_a_stale_half_makes_the_bridge_stale_and_unusable(self) -> None:
        assessment = assess_bridge(
            _descriptor(),
            _two_key_board(),
            offense_positions=OFFENSE,
            idp_positions=IDP,
            acquisition={
                "vendorIdp": acq.AcquisitionOutcome(
                    "vendorIdp", acq.STALE, reason="36 days", row_count=3
                )
            },
        )
        assert assessment.state == BRIDGE_STALE
        assert assessment.usable is False


class TestOneFamilyIsOneOpinion:
    def test_a_second_bridge_from_one_family_does_not_count_twice(self) -> None:
        first = _descriptor(bridge_key="vendorA")
        second = _descriptor(bridge_key="vendorB")
        results = assess_bridges(
            [first, second], _two_key_board(), offense_positions=OFFENSE, idp_positions=IDP
        )
        assert results[0].state == VALID
        assert results[1].state == DEPENDENT_SOURCE_FAMILY
        assert (
            results[1].capability.capable is True
        ), "the duplicate is refused for independence, not for incapability"

    def test_independent_families_both_count(self) -> None:
        other = _descriptor(bridge_key="other", family="other")
        results = assess_bridges(
            [_descriptor(), other],
            _two_key_board(),
            offense_positions=OFFENSE,
            idp_positions=IDP,
        )
        assert [r.state for r in results] == [VALID, VALID]

    def test_an_unusable_bridge_does_not_claim_its_family(self) -> None:
        """A refused bridge must not block a usable sibling."""
        blocked = _descriptor(bridge_key="blocked", comparability=PENDING)
        usable = _descriptor(bridge_key="usable")
        results = assess_bridges(
            [blocked, usable], _two_key_board(), offense_positions=OFFENSE, idp_positions=IDP
        )
        assert results[0].state == NOT_COMPARABLE
        assert results[1].state == VALID
