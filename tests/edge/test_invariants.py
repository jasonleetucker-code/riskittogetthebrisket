"""Invariants Consensus Edge must never violate.

These are not coverage tests. Each one pins a rule that, if broken, produces a
confident-looking buy/sell recommendation that is wrong — which is worse than
no recommendation at all.
"""

from __future__ import annotations

from datetime import date

import pytest

from src.edge import components, history, panel, score


# ── look-ahead ─────────────────────────────────────────────────────────


def test_an_as_of_snapshot_never_reads_a_later_commit():
    """THE backtest invariant. Everything else is worthless without it."""
    for as_of in (date(2026, 5, 1), date(2026, 6, 15), date(2026, 7, 20)):
        snapshot = history.snapshot_at("ktcSfTep", as_of)
        assert snapshot is not None
        assert snapshot.committed_at.date() <= as_of, (
            f"as-of {as_of} resolved to a commit from {snapshot.committed_at.date()} — "
            "the future leaked into a feature"
        )


def test_a_source_that_did_not_exist_yet_returns_none_not_zero():
    """Absent must stay absent. A zero here becomes a fabricated price."""
    assert history.snapshot_at("ktcSfTep", date(2026, 1, 1)) is None


def test_staleness_is_reported_rather_than_hidden():
    """A source resolved from an old commit must say so."""
    snapshot = history.snapshot_at("idpTradeCalc", date(2026, 7, 20))
    if snapshot is not None:
        assert snapshot.age_days >= 0
        assert snapshot.is_stale == (snapshot.age_days > history.DEFAULT_STALE_AFTER_DAYS)


# ── independence ───────────────────────────────────────────────────────


def test_the_anchor_and_its_vendor_siblings_can_never_vote_on_fair_value():
    """Dropping ktcSfTep while keeping ktc removes the label and not the leak."""
    voters, excluded = panel._eligible_sources(
        date(2026, 6, 15),
        "ktcSfTep",
        all_sources=history.available_sources(),
        policy="strict",
    )
    voting = {snapshot.source for snapshot in voters}
    for sibling in ("ktcSfTep", "ktc", "fantasyNavigatorSf"):
        assert sibling not in voting
    assert any("anchor_family" in item or "market_derived" in item for item in excluded)


def test_no_market_derived_source_survives_the_strict_policy():
    voters, _excluded = panel._eligible_sources(
        date(2026, 6, 15),
        "ktcSfTep",
        all_sources=history.available_sources(),
        policy="strict",
    )
    for snapshot in voters:
        assert snapshot.source not in panel.MARKET_DERIVED_SOURCES


def test_an_idp_scoped_source_cannot_price_an_offense_player():
    """idpTradeCalc is a market anchor; letting it vote on offense reintroduces it."""
    assert panel._votes_in_scope("idpTradeCalc", "idp") is True
    assert panel._votes_in_scope("idpTradeCalc", "offense") is False


def test_the_registry_key_to_filename_indirection_is_resolved():
    """``draftSharks`` reads ``draftSharksSf.csv`` — keying on the stem drops it."""
    assert panel._registry_scopes().get("draftSharksSf") == "overall_offense"


# ── missing data never becomes neutral ─────────────────────────────────


def test_a_component_without_inputs_is_none_not_zero():
    result = components.mispricing_component(
        log_gap=None,
        cohort_gaps=[],
        fair_value_source_count=0,
        fair_value_dispersion=None,
        market_is_stale=False,
    )
    assert result.value is None
    assert result.confidence == 0.0


def test_missing_evidence_cannot_raise_confidence():
    complete = components.mispricing_component(
        log_gap=0.3,
        cohort_gaps=[0.0] * 40,
        fair_value_source_count=5,
        fair_value_dispersion=None,
        market_is_stale=False,
    )
    sparse = components.mispricing_component(
        log_gap=0.3,
        cohort_gaps=[0.0] * 40,
        fair_value_source_count=1,
        fair_value_dispersion=None,
        market_is_stale=False,
    )
    assert sparse.confidence < complete.confidence


def test_a_stale_market_price_lowers_confidence():
    fresh = components.mispricing_component(
        log_gap=0.3,
        cohort_gaps=[0.1] * 40,
        fair_value_source_count=4,
        fair_value_dispersion=None,
        market_is_stale=False,
    )
    stale = components.mispricing_component(
        log_gap=0.3,
        cohort_gaps=[0.1] * 40,
        fair_value_source_count=4,
        fair_value_dispersion=None,
        market_is_stale=True,
    )
    assert stale.confidence < fresh.confidence
    assert "market_price_is_stale" in stale.warnings


# ── momentum must never drive a recommendation ─────────────────────────


def test_momentum_is_non_directional_and_excluded_from_the_score():
    """The strongest market predictor in the panel, deliberately kept out.

    Momentum scores ~+0.38 out-of-sample against the 14-day market target while
    mispricing scores ~+0.10. Admitting it would improve every backtest number
    and turn the product into "buy whatever just went up".
    """
    momentum = components.momentum_component(
        trailing_log_change_30d=0.9, trailing_log_change_7d=0.5
    )
    assert momentum.directional is False
    assert momentum.value is not None and momentum.value > 0.5

    blended, _notes = score.combine({"momentum": momentum})
    assert blended == 0.0, "momentum leaked into the directional score"


def test_a_huge_momentum_cannot_create_a_buy():
    result = score.evaluate(
        player_key="test",
        components={
            "momentum": components.momentum_component(
                trailing_log_change_30d=2.0, trailing_log_change_7d=2.0
            ),
        },
    )
    assert result.score == 0.0
    assert result.classification in {"Neutral", "Insufficient Evidence"}


# ── conflict beats neutral ─────────────────────────────────────────────


def test_strong_opposing_evidence_is_conflicted_not_neutral():
    """A zero from cancellation and a zero from agreement are different facts."""
    up = components.ComponentScore(key="mispricing", value=0.8, confidence=0.9, directional=True)
    down = components.ComponentScore(key="sharp_flow", value=-0.8, confidence=0.9, directional=True)
    result = score.evaluate(player_key="test", components={"mispricing": up, "sharp_flow": down})
    assert result.conflict["conflicted"] is True
    assert result.classification == "Conflicted"
    assert result.classification != "Neutral"


def test_a_conflicted_result_cannot_enter_a_ranked_list():
    up = components.ComponentScore(key="mispricing", value=1.0, confidence=1.0, directional=True)
    down = components.ComponentScore(key="sharp_flow", value=-1.0, confidence=1.0, directional=True)
    result = score.evaluate(player_key="test", components={"mispricing": up, "sharp_flow": down})
    assert score.qualifies_for_ranked_list(result, direction="buy") is False


# ── refusals ───────────────────────────────────────────────────────────


def test_low_confidence_blocks_any_call_however_extreme_the_score():
    weak = components.ComponentScore(
        key="mispricing", value=1.0, confidence=0.001, directional=True
    )
    result = score.evaluate(player_key="test", components={"mispricing": weak})
    assert result.classification == "Insufficient Evidence"
    assert score.qualifies_for_ranked_list(result, direction="buy") is False


def test_a_strong_call_needs_more_confidence_than_an_ordinary_one():
    strong_signal = components.ComponentScore(
        key="mispricing", value=0.95, confidence=0.5, directional=True
    )
    result = score.evaluate(player_key="test", components={"mispricing": strong_signal})
    # High score, middling confidence -> downgraded, never Strong.
    assert result.classification in {"Buy", "Neutral"}
    assert result.classification != "Strong Buy"


# ── ranking policy ─────────────────────────────────────────────────────


def test_ranked_lists_have_no_positional_quota():
    """A player must never be promoted because his position needed filling."""
    results = []
    for index in range(5):
        component = components.ComponentScore(
            key="mispricing", value=0.9, confidence=0.95, directional=True
        )
        results.append(
            score.evaluate(player_key=f"wr{index}", components={"mispricing": component})
        )
    weak = components.ComponentScore(
        key="mispricing", value=0.01, confidence=0.95, directional=True
    )
    results.append(score.evaluate(player_key="lonely_qb", components={"mispricing": weak}))

    top = score.rank(results, direction="buy", limit=20)
    assert "lonely_qb" not in {item.player_key for item in top}

    leaders = score.position_leaders(
        results,
        {**{f"wr{i}": "WR" for i in range(5)}, "lonely_qb": "QB"},
        direction="buy",
    )
    assert leaders.get("QB") is None, "an unqualified player was promoted to represent QB"


# ── score bounds ───────────────────────────────────────────────────────


@pytest.mark.parametrize("value", [-1.0, -0.5, 0.0, 0.5, 1.0])
def test_the_score_stays_within_bounds(value):
    component = components.ComponentScore(
        key="mispricing", value=value, confidence=0.9, directional=True
    )
    result = score.evaluate(player_key="test", components={"mispricing": component})
    assert -100.0 <= result.score <= 100.0
    assert 0.0 <= result.confidence <= 100.0


def test_every_result_carries_a_model_version_and_shadow_status():
    component = components.ComponentScore(
        key="mispricing", value=0.5, confidence=0.9, directional=True
    )
    payload = score.evaluate(player_key="test", components={"mispricing": component}).to_dict()
    assert payload["modelVersion"] == score.MODEL_VERSION
    assert (
        payload["weightsValidated"] is False
    ), "weights are not fitted; a payload claiming otherwise would misrepresent the model"


# ── sharp flow posterior ───────────────────────────────────────────────


def test_one_buy_is_not_unanimous_conviction():
    """The ratio (buys-sells)/volume reports 1-0 as +1.0, same as 40-0."""
    thin = components.sharp_flow_component(buys=1, sells=0, unique_managers=1, unique_leagues=1)
    thick = components.sharp_flow_component(buys=40, sells=0, unique_managers=12, unique_leagues=9)
    assert thin.value is not None and thick.value is not None
    assert thin.value < thick.value
    assert thin.confidence < thick.confidence


def test_one_manager_cannot_produce_a_confident_signal():
    concentrated = components.sharp_flow_component(
        buys=20, sells=0, unique_managers=1, unique_leagues=1
    )
    broad = components.sharp_flow_component(buys=20, sells=0, unique_managers=10, unique_leagues=8)
    assert concentrated.confidence < broad.confidence
    assert "single_manager" in concentrated.warnings


def test_sharp_flow_never_claims_to_know_the_price_paid():
    result = components.sharp_flow_component(buys=5, sells=1, unique_managers=4, unique_leagues=3)
    assert result.evidence["priceAware"] is False
    assert "unvalidated_component" in result.warnings


def test_an_absent_data_quality_assessment_cannot_raise_confidence():
    """Folding in a default 1.0 and taking a geometric mean inflated the answer.

    One component at 0.50 came out at 0.71 overall — enough to clear the
    Strong-call floor on a single mediocre input. Missing evidence must leave
    confidence where it was, never improve it.
    """
    component = components.ComponentScore(
        key="mispricing", value=0.9, confidence=0.5, directional=True
    )
    without_quality = score.overall_confidence({"mispricing": component})
    assert without_quality == pytest.approx(50.0, abs=0.5)

    perfect_quality = components.ComponentScore(
        key="data_quality", value=None, confidence=1.0, directional=False
    )
    with_quality = score.overall_confidence(
        {"mispricing": component, "data_quality": perfect_quality}
    )
    assert with_quality >= without_quality


def test_a_degenerate_cohort_cannot_manufacture_a_huge_z():
    """Near-identical gaps are not a ranking, however tight their spread.

    Guarding only against MAD == 0 is not enough: a deep positional tier priced
    off one thin board produces MAD ~0.01, and a two-hundredths difference
    became z = 10 on the live board.
    """
    cohort = [0.20 + (index % 3) * 0.001 for index in range(40)]
    z = components.robust_z(0.24, cohort)
    assert z is not None
    assert abs(z) < 1.0, f"degenerate cohort produced z={z}"


def test_the_unnormalized_fallback_cannot_outrank_a_real_measurement():
    """A row we could not cohort-normalize must never top one we could."""
    normalized = components.mispricing_component(
        log_gap=0.5,
        cohort_gaps=[0.0 + i * 0.01 for i in range(40)],
        fair_value_source_count=6,
        fair_value_dispersion=None,
        market_is_stale=False,
    )
    fallback = components.mispricing_component(
        log_gap=5.0,  # absurdly large, but uncohorted
        cohort_gaps=[],
        fair_value_source_count=6,
        fair_value_dispersion=None,
        market_is_stale=False,
    )
    assert fallback.value is not None and normalized.value is not None
    assert abs(fallback.value) <= components.UNNORMALIZED_SHRINKAGE
    assert abs(fallback.value) < abs(normalized.value)
    assert fallback.confidence < normalized.confidence


def test_the_live_fair_value_uses_the_same_construction_as_the_panel():
    """The validated evidence only transfers if the quantities match.

    ``docs/edge/BACKTEST.md``'s +0.09 was earned by rank -> percentile -> Hill.
    An earlier live version averaged ``valueContribution`` instead, i.e. cited
    evidence for a quantity it did not compute.
    """
    from src.edge import service

    source = __import__("inspect").getsource(service._fair_value)
    assert "effectiveRank" in source
    assert "percentile_to_value" in source
    assert (
        "valueContribution" not in source.split('"""')[2]
    ), "live fair value must not average valueContribution — the panel does not"
