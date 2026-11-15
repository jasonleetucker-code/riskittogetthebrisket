"""Term classification and the declared policy table."""

from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path

import pytest

from src.trade.decision_engine import policy, terms
from src.trade.decision_engine.contracts import PROMOTED_LAYER_FAMILIES, STRATEGIES
from src.valuation_math import fairness_bands
from tests.trade.decision_engine.builders import asset_layer, lineup_layer

ROOT = Path(__file__).resolve().parents[3]
P = policy.load_params()


# ── A ──────────────────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "send,recv,direction,magnitude",
    [
        ([5000.0], [5000.0], "neutral", None),
        ([5000.0], [4700.0], "opposes", "modest"),  # 6% slight
        ([5000.0], [4400.0], "opposes", "large"),  # 12% unfair
        ([4400.0], [5000.0], "favours", "large"),
        ([1000.0], [900.0], "neutral", None),  # 10% but under the absolute minimum
    ],
)
def test_a_is_classified_by_the_fairness_band_owner(send, recv, direction, magnitude):
    a, detail = terms.classify_asset(asset_layer(send, recv), P)
    assert (a.direction, a.magnitude_class) == (direction, magnitude)
    assert a.counted_as_vote and a.state == "available"
    gap = sum(recv) - sum(send)
    assert detail["fairness"] == fairness_bands.classify(gap, max(sum(send), sum(recv)))


def test_a_nets_the_marginal_forced_release_charge():
    a, detail = terms.classify_asset(asset_layer([5000.0], [5300.0], forced=400.0), P)
    assert a.value == pytest.approx(-100.0)
    assert detail["forcedReleaseCharge"] == 400.0


@pytest.mark.parametrize("basis", ["unknown", None])
def test_unknown_forced_release_cost_keeps_a_from_voting(basis):
    asset = asset_layer([5000.0], [5300.0], forced=None, forced_state=basis or "missing")
    if basis is None:
        asset.pop("forcedDropCostBasis")
    a, _ = terms.classify_asset(asset, P)
    assert a.counted_as_vote is False and a.state == "partial"


def test_gated_a_does_not_vote_and_never_reads_zero():
    a, detail = terms.classify_asset(
        asset_layer([5000.0], [5000.0], gates=("off_board_assets",)), P
    )
    assert (a.state, a.counted_as_vote, a.value) == ("partial", False, None)
    assert detail["gateCodes"] == ["off_board_assets"]
    stale, _ = terms.classify_asset(asset_layer([5000.0], [5000.0], gates=("stale_values",)), P)
    assert stale.state == "stale" and not stale.counted_as_vote


# ── C ──────────────────────────────────────────────────────────────────────


def test_c_band_is_materiality_alone_without_a_predictive_basis():
    c = terms.classify_lineup(lineup_layer(0.9, se=0.05, psd=10.0, basis="unavailable"), P)
    assert c.band == pytest.approx(1.0) and c.direction == "neutral"
    c2 = terms.classify_lineup(lineup_layer(2.0, se=0.05, psd=6.0, basis="proxy_dispersion"), P)
    assert c2.band == pytest.approx(3.0)  # zPrior 0.5 x 6.0
    assert c2.direction == "neutral"


def test_c_materiality_is_read_from_the_analyze_trade_owner():
    cfg = json.loads((ROOT / "config/trade/analyze_trade.json").read_text(encoding="utf-8"))
    assert P["terms"]["C"]["materialityPpg"] == cfg["rosterUtility"]["materialityPpg"]
    assert P["terms"]["C"]["largeMultiple"] == cfg["rosterUtility"]["largeMultiple"]


@pytest.mark.parametrize("draws_se", [0.6, 0.3, 0.1, 0.01, 0.0001])
def test_more_draws_never_flip_a_below_band_delta(draws_se):
    c = terms.classify_lineup(lineup_layer(0.8, se=draws_se), P)
    assert c.band == pytest.approx(1.0)
    # Precise: a within-band neutral vote.  Imprecise (se above the gate):
    # no vote at all.  Neither can ever read as a distinguishable result.
    if c.precision_ok:
        assert c.direction == "neutral" and c.counted_as_vote
    else:
        assert c.direction is None and not c.counted_as_vote
    assert c.magnitude_class is None


def test_precision_gate_and_magnitudes():
    imprecise = terms.classify_lineup(lineup_layer(5.0, se=0.6), P)
    assert (imprecise.direction, imprecise.precision_ok, imprecise.reason) == (
        None,
        False,
        "imprecise",
    )
    assert imprecise.state == "partial" and not imprecise.counted_as_vote
    assert imprecise.value == pytest.approx(5.0) and imprecise.mc_standard_error == 0.6
    unknown = terms.classify_lineup(lineup_layer(5.0, se=None), P)
    assert unknown.direction is None and unknown.precision_ok is None
    assert (unknown.state, unknown.reason, unknown.counted_as_vote) == (
        "partial",
        "precision_unknown",
        False,
    )
    modest = terms.classify_lineup(lineup_layer(-2.0, se=0.2), P)
    assert (modest.direction, modest.magnitude_class) == ("opposes", "modest")
    large = terms.classify_lineup(lineup_layer(3.0, se=0.2), P)
    assert (large.direction, large.magnitude_class, large.precision_ok) == (
        "favours",
        "large",
        True,
    )


@pytest.mark.parametrize(
    "layer",
    [
        lineup_layer(4.0, coverage="partial"),
        lineup_layer(4.0, state="partial", reason="unprojected_traded_player"),
        lineup_layer(4.0, state="stale", reason="snapshot_stale"),
        lineup_layer(None, state="available"),
        {"deltaPpg": 4.0},
    ],
)
def test_partial_stale_or_malformed_c_never_votes(layer):
    c = terms.classify_lineup(layer, P)
    assert c.counted_as_vote is False and c.direction is None


# ── D1 / D2 ────────────────────────────────────────────────────────────────


def test_promoted_layer_families_are_empty_in_batch_1():
    assert PROMOTED_LAYER_FAMILIES == frozenset()


def _d(term: str, delta: float):
    layer = {"state": "available", "reason": None, ("delta" if term == "D1" else "deltaPpg"): delta}
    return terms.classify_title(layer, P) if term == "D1" else terms.classify_horizon(layer, P)


def test_d_terms_vote_only_when_promoted():
    c = terms.classify_lineup(lineup_layer(-2.0, se=0.1), P)
    d1, d2 = _d("D1", 0.05), _d("D2", 2.0)
    c2, d1b, d2b, chosen = terms.select_p_term(c, d1, d2, promoted_families=frozenset(), params=P)
    assert (
        chosen == "C" and c2.counted_as_vote and not d1b.counted_as_vote and not d2b.counted_as_vote
    )
    assert d1b.reason == d2b.reason == "not_promoted"
    c3, d1c, d2c, chosen = terms.select_p_term(
        c, d1, d2, promoted_families=frozenset({"bestball_horizon"}), params=P
    )
    assert chosen == "D2" and d2c.counted_as_vote and not c3.counted_as_vote
    assert c3.reason == "replaced_by_D2" and not d1c.counted_as_vote


def test_a_promoted_but_unavailable_d_does_not_replace_c():
    c = terms.classify_lineup(lineup_layer(2.0, se=0.1), P)
    d1 = terms.classify_title({"state": "unavailable", "reason": "basis_mismatch"}, P)
    d2 = terms.classify_horizon({"state": "unavailable", "reason": "not_built"}, P)
    _, _, _, chosen = terms.select_p_term(
        c, d1, d2, promoted_families=frozenset({"playoff_presim", "bestball_horizon"}), params=P
    )
    assert chosen == "C"


def test_horizon_by_season_needs_every_season():
    full = {
        "state": "available",
        "before": {"bySeason": [[2026, 120.0, None], [2027, 118.0, None]]},
        "after": {"bySeason": [[2026, 122.0, None], [2027, 121.0, None]]},
    }
    assert terms.classify_horizon(full, P).value == pytest.approx(2.5)
    holed = {**full, "after": {"bySeason": [[2026, 122.0, None], [2027, None, None]]}}
    assert terms.classify_horizon(holed, P).state == "partial"


# ── Policy table ───────────────────────────────────────────────────────────


def test_table_is_complete_and_param_set_id_is_content_hashed():
    policy.validate_params(P)
    assert P["paramSetId"].startswith("de1-")
    other = json.loads(json.dumps(P))
    other["terms"]["C"]["zPrior"] = 0.75
    assert policy.param_set_id(other) != P["paramSetId"]


def test_incomplete_table_is_refused():
    broken = json.loads(json.dumps(P))
    del broken["policy"]["WIN_NOW|F|-"]
    with pytest.raises(policy.PolicyConfigError):
        policy.validate_params(broken)


@pytest.mark.parametrize("strategy", STRATEGIES)
def test_table_is_monotone_in_both_terms(strategy):
    order = policy.VERDICT_ORDER
    for p_class in policy.P_CLASSES:
        seq = [order[P["policy"][f"{strategy}|{a}|{p_class}"]["verdict"]] for a in policy.A_CLASSES]
        assert seq == sorted(seq), (strategy, p_class)
    for a_class in policy.A_CLASSES:
        seq = [
            order[P["policy"][f"{strategy}|{a_class}|{p}"]["verdict"]]
            for p in policy.P_CLASSES[:-1]
        ]
        assert seq == sorted(seq), (strategy, a_class)


@pytest.mark.parametrize("strategy", STRATEGIES)
def test_a_single_clearing_term_is_never_vetoed_by_the_tie(strategy):
    for cls in ("F", "F+", "O", "O+"):
        want = "YES" if cls.startswith("F") else "NO"
        assert P["policy"][f"{strategy}|{cls}|0"]["verdict"] == want
        assert P["policy"][f"{strategy}|{cls}|-"]["verdict"] == want
        assert P["policy"][f"{strategy}|0|{cls}"]["verdict"] == want


def test_tie_rows_read_no_with_neutral_tag():
    o = policy.decide_row(P, "BALANCED", "0", "0")
    assert (o.verdict, o.neutral_tag, o.raw_verdict) == ("NO", True, "TIE")
    o = policy.decide_row(P, "LONG_TERM", "0", "-")
    assert (o.verdict, o.neutral_tag) == ("NO", True)


def test_class_key():
    a, _ = terms.classify_asset(asset_layer([5000.0], [4400.0]), P)
    assert policy.class_key(a) == "O+"
    assert policy.class_key(replace(a, counted_as_vote=False)) == "-"
    with pytest.raises(ValueError):
        policy.class_key(None, voting_required=True)
