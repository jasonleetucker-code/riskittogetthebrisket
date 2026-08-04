"""Rookie-pick distribution tests, pinned to the reference numbers."""

from __future__ import annotations

import unittest

from src.bdvm.params import load_param_set
from src.bdvm.picks import PickConfigError, pick_value, pick_values_all_strategies

PARAMS = load_param_set("params_v1")


class TestPickValues(unittest.TestCase):
    def test_reference_pick_table(self):
        """Appendix C rookie-pick table reproduces exactly (±1)."""
        golden = {
            1: (4585, 4984, 5383, 0.62, 7200),
            3: (3201, 3479, 3757, 0.50, 5900),
            6: (2226, 2420, 2614, 0.38, 5000),
            12: (1455, 1582, 1709, 0.27, 4200),
            16: (997, 1084, 1171, 0.20, 3600),
            24: (598, 650, 702, 0.13, 3000),
            36: (283, 308, 333, 0.07, 2400),
        }
        for slot, (cont, bal, reb, p_hit, ceiling) in golden.items():
            c = pick_value(slot, PARAMS, strategy="contender")
            b = pick_value(slot, PARAMS, strategy="balanced")
            r = pick_value(slot, PARAMS, strategy="rebuilder")
            self.assertLessEqual(abs(c["ev"] - cont), 1.0, msg=f"slot {slot} contender")
            self.assertLessEqual(abs(b["ev"] - bal), 1.0, msg=f"slot {slot} balanced")
            self.assertLessEqual(abs(r["ev"] - reb), 1.0, msg=f"slot {slot} rebuilder")
            self.assertAlmostEqual(b["p_hit"], p_hit)
            self.assertAlmostEqual(b["ceiling"], ceiling)

    def test_next_year_weak_class_rebuilder(self):
        """Reference: next-year ~1.06, weak class (0.9×), rebuilder = 2188."""
        pv = pick_value(6, PARAMS, class_strength=0.9, years_out=1, strategy="rebuilder")
        self.assertLessEqual(abs(pv["ev"] - 2188.0), 1.0)

    def test_slot_monotonicity(self):
        values = [pick_value(s, PARAMS)["ev"] for s in (1, 3, 6, 12, 16, 24, 36)]
        self.assertEqual(values, sorted(values, reverse=True))

    def test_deep_picks_are_not_all_the_same_pick(self):
        """Past the last tabulated slot the table is EXTRAPOLATED.

        Nearest-neighbour snapping made every slot from 36 on return the
        3.12 pick's EV of 308 — in a 12-team league that is every pick in
        rounds 4+, all priced identically (audit M7).  The tail now
        continues the last measured segment's per-slot geometric decay.
        """
        deep = [pick_value(s, PARAMS)["ev"] for s in (36, 40, 48, 60, 72, 120)]
        self.assertEqual(deep, sorted(deep, reverse=True))
        self.assertEqual(len(set(round(v, 3) for v in deep)), len(deep))
        # Hand-derived at slot 48 = 36 + one full 24→36 span, so every
        # component decays by exactly its 24→36 ratio:
        #   p_hit 0.07·(0.07/0.13)      = 0.0376923…
        #   v_hit 2400·(2400/3000)      = 1920
        #   p_mid 0.20·(0.20/0.26)      = 0.1538461…
        #   v_mid  700·(700/1000)       = 490
        #   EV = 0.0376923·1920 + 0.1538461·490 = 147.7538…  (balanced
        #   carries pick_premium 1.0, class strength 1.0, no discount)
        p48 = pick_value(48, PARAMS)
        self.assertAlmostEqual(p48["p_hit"], 0.07 * (0.07 / 0.13), places=9)
        self.assertAlmostEqual(p48["ceiling"], 1920.0, places=6)
        self.assertAlmostEqual(p48["median"], 490.0, places=6)
        self.assertAlmostEqual(p48["ev"], 147.7538461538, places=6)
        # A pick 50 rounds deep is worth ~nothing, not 308.
        self.assertLess(pick_value(600, PARAMS)["ev"], 1.0)
        self.assertGreaterEqual(pick_value(600, PARAMS)["ev"], 0.0)

    def test_rebuilder_premium_ordering(self):
        for slot in (1, 12, 36):
            c = pick_value(slot, PARAMS, strategy="contender")["ev"]
            b = pick_value(slot, PARAMS, strategy="balanced")["ev"]
            r = pick_value(slot, PARAMS, strategy="rebuilder")["ev"]
            self.assertLess(c, b)
            self.assertLess(b, r)

    def test_class_strength_clamped(self):
        hi = pick_value(1, PARAMS, class_strength=5.0)
        self.assertAlmostEqual(hi["class_strength"], 1.15)
        lo = pick_value(1, PARAMS, class_strength=0.1)
        self.assertAlmostEqual(lo["class_strength"], 0.85)

    def test_probabilities_are_a_distribution(self):
        pv = pick_value(8, PARAMS)
        self.assertAlmostEqual(pv["p_hit"] + pv["p_mid"] + pv["p_miss"], 1.0)
        for k in ("p_hit", "p_mid", "p_miss"):
            self.assertGreaterEqual(pv[k], 0.0)

    def test_bad_slot_raises(self):
        with self.assertRaises(PickConfigError):
            pick_value(0, PARAMS)

    def test_all_strategies_helper(self):
        allv = pick_values_all_strategies(6, PARAMS)
        self.assertIn("risk_neutral", allv)
        self.assertEqual(set(allv), set(PARAMS.strategy_names()))


if __name__ == "__main__":
    unittest.main()
