"""TC-A / UX audit P0-1: Monte Carlo and the /trade meter must agree.

The meter publishes ``adjusted = raw + VA`` per side, VA from the ACTIVE
package model (``packageAdjustPair`` in JS, ``package_model.adjust_pair`` here).
``/api/trade/simulate-mc`` simulates around the same centres and reports
``vaAdjustment`` / ``adjustedDelta``.  Measured on /trade before this fix
(Bowers + McConkey vs K. Williams + B. Hall + D. Smith + M. Golden): the
meter applied a 5,806 adjustment and read "Gap 11, FAIR"; Monte Carlo
applied 1,879 (``effectiveValue``) and said "Side B clearly worth more
(98%)".  The cause was a per-asset 9999 clamp on the shifted p50: a premium
landing on a side holding an elite asset was mostly absorbed.

These tests pin the parity: same values + same model -> same adjusted gap.
"""

from __future__ import annotations

import unittest

from src.trade import monte_carlo as mc
from src.trade import symmetrize
from src.valuation_math import package_model


def _p(name: str, v: float) -> mc.TradePlayer:
    return mc.TradePlayer(
        name=name,
        team=name[:3].upper(),
        position_group="offense",
        p10=v * 0.85,
        p50=v,
        p90=v * 1.15,
        band_source=mc.BAND_SOURCE_SYNTHETIC,
    )


# The audit's state, at the board values captured on 2026-10-17.
ELITE_SIDE = [_p("Bowers", 9961.0), _p("McConkey", 4730.0)]
DEPTH_SIDE = [
    _p("KWilliams", 5814.0),
    _p("BHall", 4912.0),
    _p("DSmith", 3410.0),
    _p("MGolden", 3209.0),
]


def _meter_adjusted_gap(a: list[mc.TradePlayer], b: list[mc.TradePlayer]) -> float:
    """What the meter publishes: adjusted A - adjusted B (raw + VA each)."""
    a_adj, b_adj, _, _ = package_model.adjusted_pair_totals([p.p50 for p in a], [p.p50 for p in b])
    return a_adj - b_adj


class MonteCarloAppliesTheMetersAdjustment(unittest.TestCase):
    def test_full_adjustment_lands_on_a_side_holding_an_elite_asset(self) -> None:
        value, side, displayed = package_model.adjust_pair(
            [p.p50 for p in ELITE_SIDE], [p.p50 for p in DEPTH_SIDE]
        )
        self.assertTrue(displayed and value > 0, "fixture must earn an adjustment")
        _a, _b, info = mc._apply_consolidation_adjustment(ELITE_SIDE, DEPTH_SIDE)
        self.assertEqual(info["value"], value)
        self.assertEqual(info["side"], side)
        self.assertEqual(
            info["effectiveValue"],
            value,
            "Monte Carlo absorbed part of the package adjustment the meter applies "
            "in full (the per-asset 9999 clamp, UX audit P0-1).",
        )
        shifted = _a if side == 1 else _b
        original = ELITE_SIDE if side == 1 else DEPTH_SIDE
        self.assertAlmostEqual(
            sum(p.p50 for p in shifted) - sum(p.p50 for p in original), value, delta=0.5
        )

    def test_adjusted_delta_is_the_meters_adjusted_gap(self) -> None:
        base = symmetrize.simulate_symmetric(
            ELITE_SIDE, DEPTH_SIDE, n_sims=4000, seed=7, apply_consolidation_adjustment=True
        )
        enriched = symmetrize.enrich_with_decision_shape(base, ELITE_SIDE, DEPTH_SIDE)
        self.assertAlmostEqual(
            enriched["adjustedDelta"], _meter_adjusted_gap(ELITE_SIDE, DEPTH_SIDE), delta=0.6
        )
        # The simulated mean sits on the same centre (symmetric synthetic
        # bands: the triangular draw is unbiased), so the headline cannot
        # contradict the meter by thousands of points any more.
        self.assertAlmostEqual(
            base["meanDelta"], _meter_adjusted_gap(ELITE_SIDE, DEPTH_SIDE), delta=300.0
        )

    def test_no_adjustment_means_adjusted_equals_raw(self) -> None:
        """A 1-for-1 earns no adjustment under either model, so the meter's
        adjusted gap is the raw gap.  ``adjustedDelta`` used to shrink both
        sides by a spread heuristic here -- an unnamed third quantity."""
        a, b = [_p("Star", 6052.0)], [_p("Good", 5699.0)]
        base = symmetrize.simulate_symmetric(
            a, b, n_sims=2000, seed=3, apply_consolidation_adjustment=True
        )
        enriched = symmetrize.enrich_with_decision_shape(base, a, b)
        self.assertFalse(enriched["vaAdjustment"]["applied"])
        self.assertAlmostEqual(enriched["adjustedDelta"], 6052.0 - 5699.0, delta=0.6)
        self.assertAlmostEqual(enriched["adjustedDelta"], _meter_adjusted_gap(a, b), delta=0.6)


if __name__ == "__main__":
    unittest.main()
