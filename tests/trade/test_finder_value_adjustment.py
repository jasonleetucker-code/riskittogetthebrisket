"""Regression and parity tests for arbitrage-finder package adjustment."""

from __future__ import annotations

import pytest

from src.trade.finder import Asset, _score_trade
from src.trade.market_value_adjustment import PackageAdjustment, ktc_adjust_package


def _asset(name: str, model: int, market: int) -> Asset:
    return Asset(
        name=name,
        position="WR",
        team="TST",
        model_value=model,
        market_value=market,
        source_count=5,
        market_source="ktcSfTep",
    )


@pytest.mark.parametrize(
    ("first", "second", "expected"),
    [
        ([5000], [4500], PackageAdjustment()),
        ([5000], [3000, 2500], PackageAdjustment(2192, 1, True)),
        ([3000, 2500], [5000], PackageAdjustment(2192, 2, True)),
        ([6000, 1200], [4000, 3000], PackageAdjustment(2502, 1, True)),
        ([6000], [2500, 2000, 1500], PackageAdjustment(3595, 1, True)),
    ],
)
def test_python_port_matches_frontend_ktc_adjust_package_fixtures(
    first: list[int],
    second: list[int],
    expected: PackageAdjustment,
) -> None:
    assert ktc_adjust_package(first, second) == expected


def test_one_for_one_remains_unadjusted() -> None:
    candidate = _score_trade(
        [_asset("Give", 4000, 5000)],
        [_asset("Receive", 4500, 4500)],
    )

    assert candidate is not None
    payload = candidate.to_dict()
    assert payload["marketValueAdjustment"] == 0
    assert payload["marketValueAdjustmentSide"] is None
    assert payload["giveKtcTotal"] == 5000
    assert payload["receiveKtcTotal"] == 4500


def test_adjustment_can_turn_raw_opponent_loss_into_adjusted_win() -> None:
    # Raw market sums say the opponent gives 5,500 to receive 5,000.
    # The canonical package formula adds 2,192 to the single stud on the
    # give side, so the opponent actually receives an adjusted 7,192.
    candidate = _score_trade(
        [_asset("Stud", 4000, 5000)],
        [
            _asset("Piece A", 2300, 3000),
            _asset("Piece B", 2200, 2500),
        ],
    )

    assert candidate is not None
    payload = candidate.to_dict()
    assert payload["rawGiveKtcTotal"] == 5000
    assert payload["rawReceiveKtcTotal"] == 5500
    assert payload["marketValueAdjustment"] == 2192
    assert payload["marketValueAdjustmentSide"] == "give"
    assert payload["adjustedGiveKtcTotal"] == 7192
    assert payload["adjustedReceiveKtcTotal"] == 5500
    assert payload["ktcDelta"] == 1692
    assert payload["opponentKtcAppeal"] > 0


def test_raw_false_positive_is_rejected_after_package_adjustment() -> None:
    # Raw sums make this look favorable to the opponent: they give 5,000
    # and receive 5,500. The single 5,000 asset receives a 2,192 package
    # premium, making the adjusted cost 7,192; the finder must reject it.
    candidate = _score_trade(
        [
            _asset("Piece A", 2000, 3000),
            _asset("Piece B", 1800, 2500),
        ],
        [_asset("Stud", 5000, 5000)],
    )

    assert candidate is None
