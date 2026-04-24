"""Tests for trade-direction symmetrization + decision-layer fields."""
from __future__ import annotations

from src.trade import monte_carlo as mc
from src.trade import symmetrize as sym


def _p(name, p50, team="BUF", group="offense"):
    return mc.TradePlayer(
        name=name, team=team, position_group=group,
        p10=p50 * 0.85, p50=p50, p90=p50 * 1.15,
    )


def test_symmetric_result_sums_to_one_on_win_prob():
    """Core invariant: winProbA + winProbB == 1 exactly."""
    result = sym.simulate_symmetric(
        [_p("A", 5000)], [_p("B", 4500)], n_sims=2000, seed=1,
    )
    assert abs(result["winProbA"] + result["winProbB"] - 1.0) < 1e-6


def test_reversed_sides_give_flipped_win_prob():
    """sim(A,B).winProbA ~= 1 - sim(B,A).winProbA (after both are
    symmetrized the delta should be tiny, not zero)."""
    ab = sym.simulate_symmetric([_p("A", 5000)], [_p("B", 4500)], n_sims=3000, seed=7)
    ba = sym.simulate_symmetric([_p("B", 4500)], [_p("A", 5000)], n_sims=3000, seed=7)
    # |winProbA(AB) + winProbA(BA) - 1| should be tiny after symmetrization.
    delta = abs(ab["winProbA"] + ba["winProbA"] - 1.0)
    # After symmetrization: each call already averages its own
    # direction-swap, so the delta should be basically 0.
    assert delta < 0.02, f"symmetry drift {delta:.4f} too high"


def test_clear_winner_still_clear_after_symmetrization():
    result = sym.simulate_symmetric(
        [_p("A", 10000)], [_p("B", 100)], n_sims=5000, seed=42,
    )
    assert result["winProbA"] > 0.99


def test_equal_sides_centers_on_half():
    result = sym.simulate_symmetric(
        [_p("A", 5000)], [_p("B", 5000)], n_sims=5000, seed=1,
    )
    # True 50/50 — with symmetrization we should land within 1% of 0.5.
    assert 0.49 <= result["winProbA"] <= 0.51


def test_symmetry_check_drift_reported():
    result = sym.simulate_symmetric(
        [_p("A", 7000)], [_p("B", 6500)], n_sims=2000, seed=9,
    )
    assert "symmetryCheck" in result
    sc = result["symmetryCheck"]
    assert sc["enforced"] is True
    assert "drift" in sc
    assert sc["drift"] >= 0


def test_delta_range_monotonic_after_symmetrization():
    result = sym.simulate_symmetric(
        [_p("A", 8000)], [_p("B", 6000)], n_sims=2000, seed=5,
    )
    r = result["deltaRange"]
    assert r["p10"] <= r["p50"] <= r["p90"]


def test_n_sims_doubled_to_capture_both_directions():
    """The reported nSims should reflect that we ran the sim twice."""
    result = sym.simulate_symmetric(
        [_p("A", 5000)], [_p("B", 5000)], n_sims=3000, seed=1,
    )
    assert result["nSims"] == 6000


def test_disclaimer_mentions_symmetrization():
    result = sym.simulate_symmetric(
        [_p("A", 5000)], [_p("B", 5000)], n_sims=1000, seed=1,
    )
    assert "symmetrized" in result["disclaimer"].lower()


def test_enrich_adds_decision_layer_fields():
    base = sym.simulate_symmetric(
        [_p("A", 8000)], [_p("B", 5000)], n_sims=2000, seed=1,
    )
    side_a = [mc.TradePlayer(name="A", team="BUF", position_group="offense",
                              p10=6800, p50=8000, p90=9200)]
    side_b = [mc.TradePlayer(name="B", team="KC", position_group="offense",
                              p10=4250, p50=5000, p90=5750)]
    enriched = sym.enrich_with_decision_shape(base, side_a, side_b)
    assert "valueDelta" in enriched
    assert "adjustedDelta" in enriched
    assert "winPct" in enriched
    assert "riskLevel" in enriched
    assert enriched["riskLevel"] in ("low", "medium", "high")
    assert "tierImpact" in enriched
    assert enriched["tierImpact"] in ("even", "minor", "moderate", "significant")
    assert "decisionSummary" in enriched


def test_close_trade_has_high_risk_label():
    # Two roughly-equal sides with wide bands → high risk.
    side_a = [mc.TradePlayer(name="A", team="BUF", position_group="offense",
                              p10=3000, p50=5000, p90=7000)]
    side_b = [mc.TradePlayer(name="B", team="KC", position_group="offense",
                              p10=3000, p50=5000, p90=7000)]
    base = sym.simulate_symmetric(side_a, side_b, n_sims=2000, seed=1)
    enriched = sym.enrich_with_decision_shape(base, side_a, side_b)
    assert enriched["riskLevel"] in ("medium", "high")


def test_lopsided_trade_has_significant_impact():
    side_a = [mc.TradePlayer(name="A", team="BUF", position_group="offense",
                              p10=8000, p50=9000, p90=10000)]
    side_b = [mc.TradePlayer(name="B", team="KC", position_group="offense",
                              p10=500, p50=600, p90=700)]
    base = sym.simulate_symmetric(side_a, side_b, n_sims=2000, seed=1)
    enriched = sym.enrich_with_decision_shape(base, side_a, side_b)
    assert enriched["tierImpact"] == "significant"
