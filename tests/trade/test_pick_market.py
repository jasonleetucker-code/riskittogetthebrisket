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


# ── Forecast half (owner decision 2026-10-04) ────────────────────────

from src.trade.pick_market import (  # noqa: E402
    CALIBRATION_MIN_OUTCOMES,
    PROVISIONAL_CONFIDENCE_CAP,
    calibrated_confidence,
    owned_pick_forecasts,
    provisional_confidence,
    tier_probabilities_from_slots,
)


def test_slot_distribution_maps_onto_canonical_tiers():
    dist = [0.5, 0.5] + [0.0] * 10  # slots 1-2 of 12 → Early
    assert tier_probabilities_from_slots(dist, league_size=12) == {
        "early": 1.0,
        "mid": 0.0,
        "late": 0.0,
    }
    spread = [1 / 12] * 12
    probs = tier_probabilities_from_slots(spread, league_size=12)
    assert probs == pytest.approx({"early": 1 / 3, "mid": 1 / 3, "late": 1 / 3})


def test_provisional_confidence_grows_with_the_season_and_is_capped():
    assert provisional_confidence(0, 0) == (0.0, "no_regular_season_evidence")
    assert provisional_confidence(0, 84)[0] == 0.0
    mid, basis = provisional_confidence(42, 42)
    assert (
        mid == pytest.approx(PROVISIONAL_CONFIDENCE_CAP / 2)
        and basis == "provisional_season_progress"
    )
    assert provisional_confidence(83, 1)[0] < PROVISIONAL_CONFIDENCE_CAP
    # Regular season over: the final standings are observed, not forecast.
    assert provisional_confidence(84, 0) == (1.0, "final_standings_observed")


def test_calibration_needs_enough_realized_drafts_and_rewards_only_skill():
    perfect = [({"early": 1.0, "mid": 0.0, "late": 0.0}, "early")] * CALIBRATION_MIN_OUTCOMES
    assert calibrated_confidence(perfect[:-1]) is None
    assert calibrated_confidence(perfect) == pytest.approx(1.0)
    thirds = [({"early": 1 / 3, "mid": 1 / 3, "late": 1 / 3}, "mid")] * CALIBRATION_MIN_OUTCOMES
    assert calibrated_confidence(thirds) == pytest.approx(0.0)
    wrong = [({"early": 1.0, "mid": 0.0, "late": 0.0}, "late")] * CALIBRATION_MIN_OUTCOMES
    assert calibrated_confidence(wrong) == 0.0  # worse than thirds earns nothing


def _sim(played, remaining, rule="reverse_record_lower_pf"):
    return {
        "draftOrderRule": rule,
        "season": 2026,
        "n_simulations": 6000,
        "regularSeasonGamesPlayed": played,
        "regularSeasonGamesRemaining": remaining,
        "playoffOdds": [
            {
                "ownerId": "o1",
                "draftSlotDistribution": [0.6, 0.3, 0.1],
                "finalWins": {"mean": 3.1, "p10": 2, "p50": 3, "p90": 4},
                "finalPointsFor": {"mean": 1400.0, "p10": 1300, "p50": 1400, "p90": 1500},
            },
            {"ownerId": "o2", "draftSlotDistribution": [0.2, 0.4, 0.4]},
            {"ownerId": "o3", "draftSlotDistribution": [0.2, 0.3, 0.5]},
        ],
    }


_CONTRACT = {
    "sleeper": {
        "teams": [
            {"ownerId": "o1", "roster_id": 1},
            {"ownerId": "o2", "roster_id": 2},
            {"ownerId": "o3", "roster_id": 3},
        ]
    }
}


def test_owned_pick_forecasts_cover_only_the_class_after_the_simulated_season():
    out = owned_pick_forecasts(_sim(10, 10), _CONTRACT)
    year, f = out[1]
    assert year == 2027
    assert f.probabilities == pytest.approx({"early": 0.6, "mid": 0.3, "late": 0.1})
    assert f.calibrated is False
    ev = f.provenance
    assert ev["draftOrderRule"] == "reverse_record_lower_pf"
    assert ev["finalRecordDistribution"]["p50"] == 3
    assert ev["finalPointsForDistribution"]["mean"] == 1400.0
    assert ev["slotDistribution"] == [0.6, 0.3, 0.1]
    assert ev["confidenceBasis"] == "provisional_season_progress"


def test_no_recorded_rule_means_no_forecast():
    assert owned_pick_forecasts(_sim(10, 10, rule=None), _CONTRACT) == {}
    assert owned_pick_forecasts(None, _CONTRACT) == {}


def test_forecast_value_moves_from_the_average_toward_the_tiers_with_evidence():
    avg = unknown_slot_market_value(2027, 1, KTC).value
    early_season = owned_pick_forecasts(_sim(2, 82), _CONTRACT)[1][1]
    late_season = owned_pick_forecasts(_sim(70, 14), _CONTRACT)[1][1]
    v_early = unknown_slot_market_value(2027, 1, KTC, forecast=early_season).value
    v_late = unknown_slot_market_value(2027, 1, KTC, forecast=late_season).value
    assert avg < v_early < v_late < 7000  # leans Early; never hard-switches
    d = unknown_slot_market_value(2027, 1, KTC, forecast=late_season).to_dict()
    for key in (
        "ktcTierValues",
        "genericAverage",
        "forecastProbabilities",
        "forecastConfidence",
        "forecastWeightedValue",
        "tierWeightsUsed",
        "forecastEvidence",
    ):
        assert d[key] is not None, key
    assert d["methodVersion"] and d["value"] == v_late


def test_calibration_replaces_the_provisional_confidence():
    f = owned_pick_forecasts(_sim(2, 82), _CONTRACT, calibration=0.8)[1][1]
    assert f.confidence == 0.8 and f.calibrated is True
    assert f.provenance["confidenceBasis"] == "calibrated_brier_skill"
