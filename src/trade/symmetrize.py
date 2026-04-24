"""Trade-direction symmetrization wrapper for the Monte Carlo
simulator.

Critical invariant: a trade result for ``(sideA, sideB)`` must be
the negation of the result for ``(sideB, sideA)``.  In practice:

    sim(A, B).winProbA  ==  1 - sim(B, A).winProbA
    sim(A, B).meanDelta == -sim(B, A).meanDelta

The v1 sim in ``src.trade.monte_carlo`` uses an RNG seeded per-call;
two directions produce independent samples and their deltas drift
slightly from perfect symmetry.  This module enforces symmetry by
running the sim in BOTH directions and averaging, eliminating
directional bias at the cost of a second pass.

Cost: 2× the samples — which is fine because MC is the bottleneck
only at n_sims > 100k, and we clamp at 200k anyway.

Output shape
------------
Same keys as the underlying ``SimResult.to_dict()`` plus:

    ``symmetryCheck``: {
        "winProbA_AB": float,
        "winProbA_BA": float,
        "drift": float,  # |winProbA_AB - (1-winProbA_BA)|
        "enforced": True,
    }

Consumers (trade calc UI) should render the AVERAGED values and
can optionally surface ``drift`` as a diagnostic.
"""
from __future__ import annotations

from typing import Any

from src.trade import monte_carlo as _mc


def _average_results(ab: _mc.SimResult, ba: _mc.SimResult) -> dict[str, Any]:
    """Average two directionally-opposite runs.  ``ba`` is negated
    where needed so the fields read as "side A's perspective"."""
    # winProbA in BA-direction = 1 - winProbB_in_BA = winProbA_flipped.
    winA_ab = ab.win_prob_a
    winA_ba_flipped = 1.0 - ba.win_prob_a
    avg_win_a = (winA_ab + winA_ba_flipped) / 2.0

    # meanDelta: BA-perspective delta is negated to realign with
    # side-A's perspective.
    avg_mean = (ab.mean_delta + (-ba.mean_delta)) / 2.0
    avg_std = (ab.std_delta + ba.std_delta) / 2.0
    # Percentile bands: negate BA's percentiles and re-sort.
    neg_ba_p10 = -ba.delta_p90  # mirror
    neg_ba_p50 = -ba.delta_p50
    neg_ba_p90 = -ba.delta_p10
    avg_p10 = (ab.delta_p10 + neg_ba_p10) / 2.0
    avg_p50 = (ab.delta_p50 + neg_ba_p50) / 2.0
    avg_p90 = (ab.delta_p90 + neg_ba_p90) / 2.0

    drift = abs(winA_ab - winA_ba_flipped)
    return {
        "winProbA": round(avg_win_a, 4),
        "winProbB": round(1.0 - avg_win_a, 4),
        "meanDelta": round(avg_mean, 1),
        "stdDelta": round(avg_std, 1),
        "deltaRange": {
            "p10": round(avg_p10, 1),
            "p50": round(avg_p50, 1),
            "p90": round(avg_p90, 1),
        },
        "sideAMean": round((ab.side_a_mean + ba.side_b_mean) / 2.0, 1),
        "sideBMean": round((ab.side_b_mean + ba.side_a_mean) / 2.0, 1),
        "nSims": ab.n_sims + ba.n_sims,
        "method": "consensus_based_win_rate_symmetrized",
        "labelHint": "consensus_based_win_rate",
        "disclaimer": (
            "This is the fraction of consensus-band samples where "
            "side A's total exceeds side B's — NOT a real-world "
            "win probability.  Direction-symmetrized to eliminate "
            "ordering bias."
        ),
        "symmetryCheck": {
            "winProbA_AB": round(winA_ab, 4),
            "winProbA_BA_flipped": round(winA_ba_flipped, 4),
            "drift": round(drift, 4),
            "enforced": True,
        },
    }


def simulate_symmetric(
    side_a: list[_mc.TradePlayer],
    side_b: list[_mc.TradePlayer],
    *,
    n_sims: int = 50_000,
    same_team_rho: float = 0.25,
    same_pos_group_rho: float = 0.10,
    seed: int | None = None,
) -> dict[str, Any]:
    """Run the sim in both directions and return the symmetrized
    result dict.  Uses different seeds (seed, seed+1) for the two
    passes so samples aren't correlated across directions."""
    ab = _mc.simulate_trade(
        side_a, side_b,
        n_sims=n_sims, same_team_rho=same_team_rho,
        same_pos_group_rho=same_pos_group_rho, seed=seed,
    )
    ba = _mc.simulate_trade(
        side_b, side_a,
        n_sims=n_sims, same_team_rho=same_team_rho,
        same_pos_group_rho=same_pos_group_rho,
        seed=(seed + 1) if seed is not None else None,
    )
    return _average_results(ab, ba)


def enrich_with_decision_shape(
    symmetric_result: dict[str, Any],
    side_a: list[_mc.TradePlayer],
    side_b: list[_mc.TradePlayer],
) -> dict[str, Any]:
    """Augment the symmetrized sim output with the decision-layer
    fields the user's prompt requires the trade calculator to show:

        * valueDelta           — raw p50 sum of A − sum of B
        * adjustedDelta        — same but weighted by confidence
        * winPct               — alias of winProbA, expressed 0–100
        * riskLevel            — low / medium / high bucket
        * tierImpact           — high-level "big" / "lateral" / "overpay"

    Preserves all existing fields.  Non-destructive.
    """
    a_p50 = sum(p.p50 for p in side_a)
    b_p50 = sum(p.p50 for p in side_b)
    raw_delta = a_p50 - b_p50

    # Adjusted delta: shrink by the spread-to-value ratio on each
    # side.  If side A is 20k with 30% internal spread but side B
    # is 20k with 5% spread, A is effectively worth less — adjust
    # down.  Heuristic, not a formal adjustment.
    def _spread_ratio(side):
        total = sum(p.p50 for p in side) or 1.0
        spread = sum((p.p90 - p.p10) for p in side)
        return spread / total if total > 0 else 0.0
    a_spread = _spread_ratio(side_a)
    b_spread = _spread_ratio(side_b)
    # Shrink the less-confident side's valuation proportionally.
    a_adjusted = a_p50 * (1.0 - 0.3 * a_spread)
    b_adjusted = b_p50 * (1.0 - 0.3 * b_spread)
    adjusted_delta = a_adjusted - b_adjusted

    win_pct = symmetric_result.get("winProbA", 0.5) * 100.0

    # Risk level from win-prob confidence + delta range width.
    p10 = (symmetric_result.get("deltaRange") or {}).get("p10", 0)
    p90 = (symmetric_result.get("deltaRange") or {}).get("p90", 0)
    range_width = abs(p90 - p10)
    # Wide range + close win prob = high risk.
    prob_confidence = abs(win_pct - 50.0)  # 0 = coin flip, 50 = locked
    if range_width > 3000 or prob_confidence < 10:
        risk_level = "high"
    elif range_width > 1500 or prob_confidence < 20:
        risk_level = "medium"
    else:
        risk_level = "low"

    # Tier impact — compare sum magnitudes.
    total_value = max(a_p50, b_p50, 1.0)
    ratio = abs(raw_delta) / total_value
    if ratio > 0.25:
        tier_impact = "significant"
    elif ratio > 0.10:
        tier_impact = "moderate"
    elif ratio > 0.03:
        tier_impact = "minor"
    else:
        tier_impact = "even"

    return {
        **symmetric_result,
        "valueDelta": round(raw_delta, 1),
        "adjustedDelta": round(adjusted_delta, 1),
        "winPct": round(win_pct, 1),
        "riskLevel": risk_level,
        "tierImpact": tier_impact,
        "decisionSummary": _summary(win_pct, raw_delta, risk_level, tier_impact),
    }


def _summary(win_pct: float, raw_delta: float, risk: str, impact: str) -> str:
    side = "Side A" if win_pct >= 50 else "Side B"
    return (
        f"{side} favored at {win_pct:.0f}% "
        f"(Δ={raw_delta:+.0f} {impact}, risk {risk})"
    )
