"""CES package math + both-sides trade evaluation."""

from __future__ import annotations

import unittest

from src.bdvm.params import load_param_set
from src.bdvm.trade_math import evaluate_both_sides, package_value, trade_verdict

PARAMS = load_param_set("params_v1")


class TestPackageValue(unittest.TestCase):
    def test_reference_consolidation_premium(self):
        """Appendix C: veteran WR 2485 + young TE 6367 packages to 8041
        (naive sum 8852) against a 9800 single asset — consolidation
        premium ~1759 (~9.9% of the trade)."""
        verdict = trade_verdict(
            [9800.0], [2485.0, 6367.0], PARAMS, spots_available_a=2, spots_available_b=2
        )
        self.assertLessEqual(abs(verdict["side_a"] - 9800.0), 1.0)
        self.assertLessEqual(abs(verdict["side_b"] - 8041.0), 1.0)
        self.assertLessEqual(abs(verdict["edge"] - 1759.0), 2.0)
        self.assertAlmostEqual(verdict["edge_pct"], 9.9, delta=0.1)

    def test_roster_spot_charge(self):
        """Same package into a team with 1 open spot loses 120."""
        b_free = package_value([2485.0, 6367.0], PARAMS, spots_available=2)
        b_tight = package_value([2485.0, 6367.0], PARAMS, spots_available=1)
        self.assertAlmostEqual(b_free - b_tight, 120.0)
        self.assertLessEqual(abs(b_tight - 7921.0), 1.0)

    def test_ces_is_subadditive_but_single_asset_exact(self):
        self.assertAlmostEqual(package_value([5000.0], PARAMS), 5000.0)
        self.assertLess(package_value([2500.0, 2500.0], PARAMS), 5000.0)
        self.assertEqual(package_value([], PARAMS), 0.0)

    def test_shallow_league_raises_theta(self):
        deep = package_value([2500.0, 2500.0], PARAMS, roster_size=35)
        shallow = package_value([2500.0, 2500.0], PARAMS, roster_size=22)
        # higher θ → stronger stud premium → package worth less
        self.assertLess(shallow, deep)


class TestBothSides(unittest.TestCase):
    def test_double_positive_detection(self):
        """A contender sends a young TE for a veteran WR: positive for
        the contender in contender currency AND for the rebuilder in
        rebuilder currency (the reference §10.6 story)."""
        # values per strategy for [young TE] and [veteran WR]
        result = evaluate_both_sides(
            gives_by_strategy_a={"contender": [5875.0], "rebuilder": [6782.0]},
            gets_by_strategy_a={"contender": [4368.0], "rebuilder": [1144.0]},
            strategy_a="rebuilder",  # A is rebuilding: sends TE? no —
            strategy_b="contender",
            params=PARAMS,
        )
        # A (rebuilder) gives the TE (6782 in their currency) and gets the
        # vet WR (1144) — terrible for them; NOT double positive.
        self.assertLess(result["a_gain"], 0)
        self.assertFalse(result["double_positive"])

        result2 = evaluate_both_sides(
            gives_by_strategy_a={"contender": [4368.0], "rebuilder": [1144.0]},
            gets_by_strategy_a={"contender": [5875.0], "rebuilder": [6782.0]},
            strategy_a="contender",  # A contends: sends vet WR, gets TE
            strategy_b="rebuilder",  # B rebuilds: sends TE, gets vet WR? no
            params=PARAMS,
        )
        # A in contender currency: +5875 − 4368 > 0.
        self.assertGreater(result2["a_gain"], 0)
        # B in rebuilder currency: gets 1144, gives 6782 → negative.
        self.assertLess(result2["b_gain"], 0)
        self.assertFalse(result2["double_positive"])

    def test_true_double_positive(self):
        """Contender acquires the win-now vet; rebuilder acquires the
        young TE.  Each side wins in its own currency."""
        result = evaluate_both_sides(
            # A sends the young TE, valued per strategy:
            gives_by_strategy_a={"contender": [5875.0], "rebuilder": [6782.0]},
            # A receives the veteran WR:
            gets_by_strategy_a={"contender": [6875.0], "rebuilder": [1144.0]},
            strategy_a="contender",
            strategy_b="rebuilder",
            params=PARAMS,
        )
        # A (contender): +6875 − 5875 = +1000 in contender currency.
        self.assertGreater(result["a_gain"], 0)
        # B (rebuilder): receives TE (6782), sends WR (1144) → +5638.
        self.assertGreater(result["b_gain"], 0)
        self.assertTrue(result["double_positive"])


if __name__ == "__main__":
    unittest.main()
