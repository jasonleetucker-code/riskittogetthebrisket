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
    progress_bucket,
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
    # Unknown progress is NOT "early": it carries no weight and says so.
    assert provisional_confidence(None, None) == (0.0, "season_progress_unknown")
    assert provisional_confidence(0, 0) == (0.0, "season_progress_unknown")
    assert provisional_confidence(0, 14)[0] == 0.0
    mid, basis = provisional_confidence(7, 14)
    assert (
        mid == pytest.approx(PROVISIONAL_CONFIDENCE_CAP / 2)
        and basis == "provisional_season_progress"
    )
    assert provisional_confidence(13, 14)[0] < PROVISIONAL_CONFIDENCE_CAP
    # Every regular-season week final: the standings are observed, not forecast.
    assert provisional_confidence(14, 14) == (1.0, "final_standings_observed")


def test_provisional_confidence_accepts_floats_from_a_json_round_trip():
    # The defect this pins: the producer once wrote ``8.0`` and the consumer
    # required ``int``, so the forecast silently carried no weight.
    assert provisional_confidence(7.0, 14.0) == provisional_confidence(7, 14)
    assert provisional_confidence(True, 14)[1] == "season_progress_unknown"


def test_progress_buckets_are_quarters_plus_complete():
    assert progress_bucket(None, 14) is None
    assert [progress_bucket(w, 16) for w in (0, 3, 4, 8, 12, 15, 16)] == [0, 0, 1, 2, 3, 3, 4]


def _history(p, actual, bucket, n=CALIBRATION_MIN_OUTCOMES):
    return [(p, actual, bucket)] * n


def test_calibration_fits_the_shrinkage_weight_per_season_progress_bucket():
    perfect = _history({"early": 1.0, "mid": 0.0, "late": 0.0}, "early", 2)
    assert calibrated_confidence(perfect[:-1], 2) is None  # not enough outcomes
    assert calibrated_confidence(perfect, 2) == pytest.approx(1.0)
    # Another bucket's evidence never calibrates this one.
    assert calibrated_confidence(perfect, 0) is None
    assert calibrated_confidence(perfect, None) is None
    thirds = _history({"early": 1 / 3, "mid": 1 / 3, "late": 1 / 3}, "mid", 1)
    assert calibrated_confidence(thirds, 1) == 0.0  # no skill buys no trust
    wrong = _history({"early": 1.0, "mid": 0.0, "late": 0.0}, "late", 1)
    assert calibrated_confidence(wrong, 1) == 0.0
    # Half right, half wrong: the fit lands strictly between the extremes.
    mixed = _history({"early": 0.8, "mid": 0.2, "late": 0.0}, "early", 3, 18) + _history(
        {"early": 0.8, "mid": 0.2, "late": 0.0}, "mid", 3, 12
    )
    c = calibrated_confidence(mixed, 3)
    assert 0.0 < c < 1.0


def _sim(final, total, rule="reverse_record_lower_pf"):
    return {
        "draftOrderRule": rule,
        "season": 2026,
        "n_simulations": 6000,
        "regularSeasonProgress": {
            "weeksFinal": final,
            "weeksTotal": total,
            "complete": None if final is None or total is None else final >= total,
        },
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
    out = owned_pick_forecasts(_sim(7, 14), _CONTRACT)
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
    assert ev["seasonProgress"] == {"weeksFinal": 7, "weeksTotal": 14, "bucket": 2}


def test_no_recorded_rule_means_no_forecast():
    assert owned_pick_forecasts(_sim(7, 14, rule=None), _CONTRACT) == {}
    assert owned_pick_forecasts(None, _CONTRACT) == {}


def test_forecast_value_moves_from_the_average_toward_the_tiers_with_evidence():
    avg = unknown_slot_market_value(2027, 1, KTC).value
    early_season = owned_pick_forecasts(_sim(2, 14), _CONTRACT)[1][1]
    late_season = owned_pick_forecasts(_sim(12, 14), _CONTRACT)[1][1]
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


def test_calibration_replaces_the_provisional_confidence_only_in_its_bucket():
    hist = _history({"early": 1.0, "mid": 0.0, "late": 0.0}, "early", 0)
    early = owned_pick_forecasts(_sim(2, 14), _CONTRACT, calibration_history=hist)[1][1]
    assert early.calibrated is True and early.confidence == pytest.approx(1.0)
    assert early.provenance["confidenceBasis"] == "calibrated_shrinkage_fit"
    # Week 12 is a different instrument: bucket-0 outcomes do not calibrate it.
    late = owned_pick_forecasts(_sim(12, 14), _CONTRACT, calibration_history=hist)[1][1]
    assert late.calibrated is False
    assert late.provenance["confidenceBasis"] == "provisional_season_progress"


def test_unknown_progress_gives_the_forecast_no_weight():
    f = owned_pick_forecasts(_sim(None, None), _CONTRACT)[1][1]
    assert f.confidence == 0.0
    assert f.provenance["confidenceBasis"] == "season_progress_unknown"
    assert unknown_slot_market_value(2027, 1, KTC, forecast=f).value == (
        unknown_slot_market_value(2027, 1, KTC).value
    )


def test_no_forecast_names_its_reason_and_tier_sources_travel():
    d = unknown_slot_market_value(
        2028,
        1,
        KTC,
        forecast_unavailable_reason="class_beyond_forecast_horizon",
        ktc_tier_sources={"early": "ktcCrowdTradesSfTep", "mid": "ktcSfTep", "late": "ktcSfTep"},
    ).to_dict()
    assert d["forecastUnavailableReason"] == "class_beyond_forecast_horizon"
    assert d["ktcTierSources"]["early"] == "ktcCrowdTradesSfTep"
    assert unknown_slot_market_value(2028, 1, KTC).to_dict()["forecastUnavailableReason"] == (
        "no_forecast_supplied"
    )
