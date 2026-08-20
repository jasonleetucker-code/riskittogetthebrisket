"""The bridge layer's ladder must be the SAME ladder the pipeline builds.

``src.bridges.measure_capability`` forms a combined offense+IDP pool to decide
whether a bridge can translate.  ``src.canonical.idp_backbone.
build_backbone_from_rows`` forms one to actually translate.  If those two
disagree about where a bridge's IDP entries sit, the layer would qualify a
bridge on one ladder and the board would translate on another — a second
owner of the same concept, arrived at by accident.

So this asserts the INVARIANT (the two agree), never a particular depth or
starting rank, which are properties of whichever board the test happens to
run against.
"""

from __future__ import annotations

import pytest

from src.bridges import CARDINAL, QUALIFIED, BridgeDescriptor, measure_capability
from src.canonical.idp_backbone import build_backbone_from_rows
from tests.archive_fixtures import newest_complete_raw_payload


@pytest.fixture(scope="module")
def board_rows() -> list[dict]:
    payload, _label = newest_complete_raw_payload()
    if payload is None:
        pytest.skip("no complete raw payload available")
    from src.api.data_contract import build_api_data_contract

    contract = build_api_data_contract(payload)
    rows = contract.get("playersArray") or []
    if not rows:
        pytest.skip("contract produced no rows")
    return rows


def _positions() -> tuple[frozenset[str], frozenset[str]]:
    from src.api.data_contract import _IDP_POSITIONS, _OFFENSE_POSITIONS

    # Picks occupy combined-pool ranks, so the pipeline unions them into the
    # offense side; the bridge layer must be handed the same universe.
    return frozenset(set(_OFFENSE_POSITIONS) | {"PICK"}), frozenset(_IDP_POSITIONS)


class TestTheTwoOwnersAgree:
    def test_the_bridge_ladder_matches_the_backbone_ladder(self, board_rows) -> None:
        offense, idp = _positions()
        backbone = build_backbone_from_rows(
            board_rows,
            source_key="idpTradeCalc",
            idp_positions=idp,
            offense_positions=offense,
        )
        ladder = backbone.shared_idp_ladder()
        if not ladder:
            pytest.skip("backbone produced no shared-market ladder on this board")

        descriptor = BridgeDescriptor(
            bridge_key="idpTradeCalc",
            display_name="IDP Trade Calculator",
            family="idpTradeCalc",
            kind=CARDINAL,
            offense_keys=("idpTradeCalc",),
            idp_keys=("idpTradeCalc",),
            comparability=QUALIFIED,
            comparability_evidence="one native board spanning offense, IDP and picks",
        )
        capability = measure_capability(
            descriptor, board_rows, offense_positions=offense, idp_positions=idp
        )

        assert capability.ladder_start == ladder[0]
        assert capability.ladder_depth == len(ladder)

    def test_the_incumbent_backbone_is_capable_on_a_real_board(self, board_rows) -> None:
        """Not a count — the property that it is not the identity ladder."""
        offense, idp = _positions()
        descriptor = BridgeDescriptor(
            bridge_key="idpTradeCalc",
            display_name="IDP Trade Calculator",
            family="idpTradeCalc",
            kind=CARDINAL,
            offense_keys=("idpTradeCalc",),
            idp_keys=("idpTradeCalc",),
            comparability=QUALIFIED,
            comparability_evidence="one native board spanning both pools",
        )
        capability = measure_capability(
            descriptor, board_rows, offense_positions=offense, idp_positions=idp
        )
        assert capability.spans_both_pools is True
        assert capability.is_identity_ladder is False
        assert capability.capable is True


class TestTheFamilyRuleUnlocksASecondBridge:
    """The measured reason this program's architecture is a family, not a key."""

    def _descriptor(self, offense_keys, idp_keys) -> BridgeDescriptor:
        return BridgeDescriptor(
            bridge_key="draftSharks",
            display_name="Draft Sharks 3D+",
            family="draftSharks",
            kind=CARDINAL,
            offense_keys=offense_keys,
            idp_keys=idp_keys,
            comparability=QUALIFIED,
            comparability_evidence=(
                "one league-scored pass; projection surplus converts to 3D Value + at "
                "0.09610 on offense and 0.09586 on IDP (ratio 0.998), with the spread "
                "within each pool larger than the difference between them"
            ),
        )

    def test_the_idp_key_alone_cannot_bridge(self, board_rows) -> None:
        offense, idp = _positions()
        capability = measure_capability(
            self._descriptor(("draftSharksIdp",), ("draftSharksIdp",)),
            board_rows,
            offense_positions=offense,
            idp_positions=idp,
        )
        if capability.idp_values == 0:
            pytest.skip("draftSharksIdp did not vote on this board")
        assert capability.offense_values == 0
        assert capability.capable is False

    def test_the_family_can(self, board_rows) -> None:
        offense, idp = _positions()
        capability = measure_capability(
            self._descriptor(("draftSharks",), ("draftSharksIdp",)),
            board_rows,
            offense_positions=offense,
            idp_positions=idp,
        )
        if capability.idp_values == 0 or capability.offense_values == 0:
            pytest.skip("a Draft Sharks half did not vote on this board")
        assert capability.spans_both_pools is True
        assert capability.is_identity_ladder is False
        assert capability.capable is True
