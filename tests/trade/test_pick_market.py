"""C7-PICKGEN-01 — market side of an unknown-slot owned pick (owner decision
2026-10-03).  For generated-trade comparability only; never canonical value."""

from __future__ import annotations

import pytest

from src.trade.pick_market import TierForecast, unknown_slot_market_value

KTC = {"early": 7000.0, "mid": 5900.0, "late": 5000.0}


def test_no_forecast_is_exactly_the_plain_tier_average():
    est = unknown_slot_market_value(2027, 1, KTC)
    assert est.value == round((7000 + 5900 + 5000) / 3)
    d = est.to_dict()
    assert d["basis"] == "plain_ktc_tier_average"
    assert d["isNativeMarketPrice"] is False and d["classification"] == "PRIOR"
    assert d["scope"] == "generated_trade_comparability_only"
    assert d["ktcTierValues"] == KTC and d["forecastConfidence"] is None


@pytest.mark.parametrize("missing", ["early", "mid", "late"])
def test_a_missing_tier_leaves_the_pick_unpriced_never_a_partial_average(missing):
    est = unknown_slot_market_value(2027, 2, {**KTC, missing: None})
    assert est.value is None and missing in est.reason


def test_zero_confidence_forecast_equals_the_plain_average():
    f = TierForecast({"early": 0.9, "mid": 0.1, "late": 0.0}, confidence=0.0, source="t")
    assert unknown_slot_market_value(2027, 1, KTC, forecast=f).value == (
        unknown_slot_market_value(2027, 1, KTC).value
    )


def test_full_confidence_forecast_is_the_expected_tier_value():
    f = TierForecast({"early": 0.5, "mid": 0.5, "late": 0.0}, confidence=1.0, source="t")
    assert unknown_slot_market_value(2027, 1, KTC, forecast=f).value == round(
        0.5 * 7000 + 0.5 * 5900
    )


def test_partial_confidence_shrinks_toward_thirds_and_never_hard_switches():
    f = TierForecast({"early": 1.0, "mid": 0.0, "late": 0.0}, confidence=0.4, source="t")
    est = unknown_slot_market_value(2027, 1, KTC, forecast=f)
    w = est.to_dict()["tierWeightsUsed"]
    assert w["early"] == pytest.approx(0.4 + 0.6 / 3)
    assert w["late"] == pytest.approx(0.6 / 3) and w["late"] > 0  # never collapses to one tier
    avg = unknown_slot_market_value(2027, 1, KTC).value
    assert avg < est.value < 7000
    assert est.to_dict()["forecastWeightedValue"] == 7000.0


def test_an_invalid_forecast_is_refused():
    with pytest.raises(ValueError):
        unknown_slot_market_value(
            2027,
            1,
            KTC,
            forecast=TierForecast({"early": 0.7, "mid": 0.7}, confidence=0.5, source="t"),
        )
