"""Engine acceptance: the batch-1 behaviours the spec pins."""

from __future__ import annotations

import itertools

import pytest

from src.evidence_lineage.registry import LineageViolation
from src.trade.decision_engine import engine, policy, terms
from src.trade.decision_engine.contracts import TwoSidedDecision
from tests.trade.decision_engine.builders import asset_layer, layers, lineup_layer, unavailable
from tests.trade.decision_engine.scenarios import SCENARIOS

P = policy.load_params()


def _eval(**kw):
    return engine.evaluate_team(layers(**kw), params=P)


def test_all_stub_is_insufficient_with_named_missing_layers_and_no_numbers():
    a, b = SCENARIOS["all_stub"]()
    d = engine.evaluate_two_sided(a, b, params=P)
    assert d.shape == "insufficient"
    for team in d.teams:
        assert team.verdict == "INSUFFICIENT_EVIDENCE"
        codes = [m["code"] for m in team.missing_evidence]
        assert codes == [
            "strategy_unknown",
            "asset_term_unavailable",
            "roster_unknown",
            "roster_limit_unknown",
        ]
        assert all(t.value is None and not t.counted_as_vote for t in team.terms)
        assert team.reasons == () and team.confidence == "low"
        for v in team.key_numbers.values():
            assert set(v) == {"state", "reason"}


def test_both_gain_is_good_for_both_and_sides_are_independent():
    a, b = SCENARIOS["both_gain"]()
    d = engine.evaluate_two_sided(a, b, params=P)
    assert d.shape == "good_for_both"
    assert [t.verdict for t in d.teams] == ["YES", "YES"]
    # Independence: each side's decision is exactly its single-team decision.
    assert d.teams[0] == engine.evaluate_team(a, params=P)
    assert d.teams[1] == engine.evaluate_team(b, params=P)
    # Swapping the order swaps the teams and changes nothing else.
    swapped = engine.evaluate_two_sided(b, a, params=P)
    assert swapped.teams == (d.teams[1], d.teams[0])


@pytest.mark.parametrize("se", [0.45, 0.2, 0.05, 0.001, 1e-6])
def test_more_mc_draws_never_flip_a_below_band_delta_to_yes(se):
    d = _eval(
        strategy="WIN_NOW", asset=asset_layer([5000.0], [5000.0]), lineup=lineup_layer(0.9, se=se)
    )
    assert d.verdict == "NO" and d.neutral_tag is True


def test_indistinguishable_gives_no_low_confidence_and_the_tie_reason():
    d = _eval(
        strategy="BALANCED", asset=asset_layer([5000.0], [5000.0]), lineup=lineup_layer(0.3, se=0.1)
    )
    assert (d.verdict, d.neutral_tag, d.confidence) == ("NO", True, "low")
    assert d.reasons[0].code == "advantage_indistinguishable_from_current_roster"


def test_large_precise_c_under_win_now_gives_yes():
    d = _eval(
        strategy="WIN_NOW", asset=asset_layer([5000.0], [4400.0]), lineup=lineup_layer(3.5, se=0.2)
    )
    assert d.verdict == "YES" and d.neutral_tag is False
    c = next(t for t in d.terms if t.term == "C")
    assert c.precision_ok is True and c.magnitude_class == "large" and c.counted_as_vote


def test_imprecise_large_c_does_not_decide():
    d = _eval(
        strategy="WIN_NOW", asset=asset_layer([5000.0], [5000.0]), lineup=lineup_layer(3.5, se=0.9)
    )
    # An imprecise estimate is not a measured zero: it does not vote, so a
    # strategy that needs P is INSUFFICIENT_EVIDENCE, never a neutral tie.
    assert d.verdict == "INSUFFICIENT_EVIDENCE" and d.confidence == "low"
    assert d.missing_evidence == (
        {"code": "roster_term_partial", "layer": "C", "reason": "imprecise"},
    )


@pytest.mark.parametrize("se,why", [(None, "precision_unknown"), (5.0, "imprecise")])
@pytest.mark.parametrize("strategy", ["WIN_NOW", "BALANCED"])
def test_unknown_or_imprecise_large_loss_never_becomes_a_neutral_vote(strategy, se, why):
    # Review finding (PR #1862): A = F+ with an 8 ppg lineup loss.  Precise,
    # this is NO; with se=None / oversized se it used to read C as a neutral
    # vote and return YES via the "|0" column.  Unknown precision is missing
    # evidence, not a within-band roster change.
    precise = _eval(
        strategy=strategy, asset=asset_layer([5000.0], [5600.0]), lineup=lineup_layer(-8.0, se=0.1)
    )
    assert precise.verdict == "NO"
    d = _eval(
        strategy=strategy, asset=asset_layer([5000.0], [5600.0]), lineup=lineup_layer(-8.0, se=se)
    )
    assert d.verdict == "INSUFFICIENT_EVIDENCE"
    assert d.missing_evidence == ({"code": "roster_term_partial", "layer": "C", "reason": why},)
    c = next(t for t in d.terms if t.term == "C")
    assert not c.counted_as_vote and c.direction is None and c.magnitude_class is None
    assert c.state == "partial" and c.reason == why
    # The measured delta stays visible as a report-only number, never dropped.
    assert c.value == pytest.approx(-8.0) and c.precision_ok is (None if se is None else False)
    assert d.confidence == "low" and d.confidence_axes["coverage"] == "low"


@pytest.mark.parametrize("se", [None, 5.0])
def test_unknown_precision_c_under_long_term_falls_to_the_no_vote_column(se):
    d = _eval(
        strategy="LONG_TERM",
        asset=asset_layer([5000.0], [5600.0]),
        lineup=lineup_layer(-8.0, se=se),
    )
    assert d.policy_row.endswith("|-")
    assert not any(t.counted_as_vote for t in d.terms if t.term == "C")


@pytest.mark.parametrize("strategy", ["WIN_NOW", "BALANCED"])
def test_partial_c_never_votes_and_is_insufficient_where_essential(strategy):
    d = _eval(strategy=strategy, lineup=lineup_layer(5.0, coverage="partial"))
    assert d.verdict == "INSUFFICIENT_EVIDENCE"
    assert [m["code"] for m in d.missing_evidence] == ["roster_term_partial"]
    assert not any(t.counted_as_vote for t in d.terms if t.term == "C")


def test_partial_c_under_long_term_reports_only():
    d = _eval(
        strategy="LONG_TERM",
        asset=asset_layer([4700.0], [5000.0]),
        lineup=lineup_layer(-5.0, coverage="partial"),
    )
    assert d.verdict == "YES" and d.policy_row == "LONG_TERM|F|-"
    assert d.confidence_axes["coverage"] == "medium"


def test_offseason_c_is_not_applicable_rather_than_missing():
    d = _eval(
        strategy="WIN_NOW",
        asset=asset_layer([4700.0], [5000.0]),
        lineup=unavailable("no_remaining_fantasy_weeks"),
    )
    assert d.verdict == "YES" and d.missing_evidence == ()
    # Not applicable is not missing: coverage is not the "essential missing" LOW.
    assert d.confidence_axes["coverage"] == "medium"


@pytest.mark.parametrize("strategy", ["WIN_NOW", "BALANCED", "LONG_TERM"])
def test_agreement_of_a_and_c_never_yields_high(strategy):
    for send, recv, delta in itertools.product(
        ([5000.0], [3000.0, 2600.0]), ([4400.0], [5600.0], [5000.0]), (-4.0, -2.0, 0.2, 2.0, 4.0)
    ):
        d = _eval(
            strategy=strategy, asset=asset_layer(send, recv), lineup=lineup_layer(delta, se=0.05)
        )
        a = next(t for t in d.terms if t.term == "A")
        c = next(t for t in d.terms if t.term == "C")
        assert a.counted_as_vote and c.counted_as_vote
        assert d.confidence != "high"
        assert d.confidence_axes["agreement"] in ("medium", "low")


def test_a_alone_can_reach_high_confidence():
    d = _eval(
        strategy="LONG_TERM",
        asset=asset_layer([4000.0], [5000.0]),
        lineup=unavailable("no_remaining_fantasy_weeks"),
    )
    assert d.verdict == "YES"
    assert d.confidence_axes["agreement"] == "high"


def test_va_roster_overlap_caps_and_opposition_is_labelled():
    a, b = SCENARIOS["va_overlap"]()
    da = engine.evaluate_team(a, params=P)
    db = engine.evaluate_team(b, params=P)
    assert da.double_count_guard["vaRelation"] == "aligned"
    assert da.confidence_axes["overlap_guard"] == "medium"
    assert db.double_count_guard["vaRelation"] == "opposed"
    assert "va_structural_consolidation_premium" in [r.code for r in db.reasons]
    assert db.confidence_axes["overlap_guard"] == "high"


def test_reasons_are_at_most_three_one_per_family():
    for name in SCENARIOS:
        for team in engine.evaluate_two_sided(*SCENARIOS[name](), params=P).teams:
            fams = [r.family for r in team.reasons]
            assert len(fams) <= 3 and len(fams) == len(set(fams))


def test_unknown_roster_or_limit_is_insufficient():
    d = _eval(roster_known=None)
    assert "roster_unknown" in [m["code"] for m in d.missing_evidence]
    d = _eval(roster_limit_known=False)
    assert "roster_limit_unknown" in [m["code"] for m in d.missing_evidence]


def test_gate_codes_are_read_not_recomputed():
    d = _eval(
        asset=asset_layer([5000.0], [5000.0], gates=("unheld_assets", "pick_ownership_unknown"))
    )
    assert d.verdict == "INSUFFICIENT_EVIDENCE"
    assert [m["code"] for m in d.missing_evidence] == ["unheld_assets", "pick_ownership_unknown"]


def test_promoted_d2_replaces_c_and_d_is_never_counted_by_default():
    horizon = {"state": "available", "deltaPpg": 2.5}
    base = dict(
        strategy="WIN_NOW",
        asset=asset_layer([5000.0], [5000.0]),
        lineup=lineup_layer(-2.0, se=0.1),
        horizon=horizon,
    )
    d = _eval(**base)
    assert d.verdict == "NO"
    assert [t.term for t in d.terms if t.counted_as_vote] == ["A", "C"]
    promoted = engine.evaluate_team(
        layers(**base), params=P, promoted_families=frozenset({"bestball_horizon"})
    )
    assert [t.term for t in promoted.terms if t.counted_as_vote] == ["A", "D2"]
    assert promoted.verdict == "YES"
    assert promoted.receipt["promotedFamilies"] == ["bestball_horizon"]


def test_lineage_violation_raises_mechanically(monkeypatch):
    real = terms.select_p_term

    def double_vote(*args, **kwargs):
        c, d1, d2, chosen = real(*args, **kwargs)
        from dataclasses import replace

        return c, d1, replace(d2, state="available", counted_as_vote=True), chosen

    monkeypatch.setattr(engine, "select_p_term", double_vote)
    with pytest.raises(LineageViolation):
        _eval()


def test_what_would_change_price_grid_reruns_the_package_model():
    d = _eval(
        strategy="BALANCED",
        asset=asset_layer([5000.0], [4400.0]),
        lineup=lineup_layer(0.2, se=0.05),
    )
    assert d.verdict == "NO"
    price = next(w for w in d.what_would_change if w["kind"] == "price")
    assert price["side"] == "receive" and price["flipsTo"] in ("YES", "NO")
    # The flip value is the smallest on the grid: one step less does not flip.
    v = price["assetValue"]
    step = P["whatWouldChange"]["priceGridStep"]
    a_prev = terms.a_term_from_values([5000.0], [4400.0, float(v - step)], 0.0, P)
    o_prev = policy.decide_row(P, "BALANCED", policy.class_key(a_prev), "0")
    assert (o_prev.verdict, o_prev.neutral_tag) == ("NO", False)


def test_strategy_flip_is_reported():
    d = _eval(
        strategy="LONG_TERM",
        asset=asset_layer([4700.0], [5000.0]),
        lineup=lineup_layer(-2.0, se=0.1),
    )
    assert d.verdict == "YES"
    flips = {w["strategy"]: w["flipsTo"] for w in d.what_would_change if w["kind"] == "strategy"}
    assert flips == {"WIN_NOW": "NO", "BALANCED": "NO"}


def test_output_is_recommendation_only():
    d = engine.evaluate_two_sided(*SCENARIOS["both_gain"](), params=P)
    assert d.recommendation_only is True and d.executes is False
    with pytest.raises(ValueError):
        TwoSidedDecision(
            engine_version="x",
            param_set_id="y",
            teams=d.teams,
            shape="good_for_both",
            executes=True,
        )
    for team in d.teams:
        assert team.predictive_probability is None
        assert team.receipt["isProbability"] is False
        assert team.receipt["engineVersion"] == "decision_engine_v3_shadow"
        assert team.receipt["paramSetId"] == P["paramSetId"]
        assert team.receipt["packageModel"]["id"] == "geom_q078_v1"
        assert {b["code"] for b in team.receipt["knownChampionBiases"]} >= {
            "worsens_overage_no_release_charge"
        }


def test_deterministic():
    a, b = SCENARIOS["va_overlap"]()
    assert engine.evaluate_two_sided(a, b, params=P) == engine.evaluate_two_sided(a, b, params=P)
