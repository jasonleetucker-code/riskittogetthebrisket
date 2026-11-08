"""Hand-checkable arithmetic for the offline signal diagnostics.

``src/bdvm/signal_diagnostics.py`` is evaluation-only; these tests pin the
arithmetic by hand and pin its incumbent-ladder copy against the SERVED
function so a threshold edit cannot silently desynchronise the diagnosis.
"""

from __future__ import annotations

import math
import unittest

from src.bdvm import signal_diagnostics as sd
from src.bdvm.market import buy_hold_sell
from src.bdvm.params import load_param_set

PARAMS = load_param_set()
TH = {k: float(v) for k, v in PARAMS["market"]["signal_thresholds"].items() if k.endswith("alpha")}


class TestRanks(unittest.TestCase):
    def test_average_ranks_ties(self):
        self.assertEqual(sd.average_ranks([10, 20, 20, 30]), [0.0, 1.5, 1.5, 3.0])

    def test_percentiles(self):
        self.assertEqual(sd.percentiles([5, 1, 3]), [1.0, 0.0, 0.5])
        self.assertEqual(sd.percentiles([7]), [0.5])
        self.assertEqual(sd.percentiles([]), [])

    def test_spearman(self):
        self.assertAlmostEqual(sd.spearman([1, 2, 3, 4], [10, 20, 30, 40]), 1.0)
        self.assertAlmostEqual(sd.spearman([1, 2, 3, 4], [4, 3, 2, 1]), -1.0)
        # constant input is undefined, never 0
        self.assertIsNone(sd.spearman([1, 1, 1, 1], [1, 2, 3, 4]))
        self.assertIsNone(sd.spearman([1, 2], [1, 2]))

    def test_quantile_linear(self):
        v = [0.0, 10.0, 20.0, 30.0]
        self.assertEqual(sd.quantile(v, 0.0), 0.0)
        self.assertEqual(sd.quantile(v, 1.0), 30.0)
        self.assertAlmostEqual(sd.quantile(v, 0.5), 15.0)
        self.assertAlmostEqual(sd.quantile(v, 1 / 3), 10.0)


class TestScaleAlignment(unittest.TestCase):
    def test_quantile_match_is_monotone_and_hits_target_distribution(self):
        fund = [1.0, 5.0, 2.0, 9.0]
        target = [100.0, 200.0, 300.0, 400.0]
        out = sd.quantile_match(fund, target)
        # ranks 0,2,1,3 of 4 -> percentiles 0, 2/3, 1/3, 1
        self.assertAlmostEqual(out[0], 100.0)
        self.assertAlmostEqual(out[2], 200.0)
        self.assertAlmostEqual(out[1], 300.0)
        self.assertAlmostEqual(out[3], 400.0)

    def test_pure_level_offset_vanishes_after_alignment(self):
        market = [1000.0, 2000.0, 3000.0, 4000.0, 5000.0]
        fund = [m * 0.25 for m in market]  # same order, 4x lower
        # incumbent: every player is a deep sell; aligned: all HOLD
        inc = [sd.incumbent_label((f - m) * 1.0, TH) for f, m in zip(fund, market)]
        self.assertEqual(set(inc[1:]), {"STRONG_SELL"})
        self.assertEqual(set(sd.scale_aligned_labels(fund, market, [1.0] * 5, TH)), {"HOLD"})


class TestIncumbentCopy(unittest.TestCase):
    def test_matches_served_ladder_when_gates_pass(self):
        for alpha in (-2000, -900.5, -900, -401, -400, 0, 400, 401, 900, 900.5, 3000):
            served = buy_hold_sell(
                {"alpha": alpha, "liquidity": 0.9, "liquidityMeasured": True}, PARAMS
            )
            self.assertEqual(sd.incumbent_label(float(alpha), TH), served["signal"], alpha)


class TestChallengerLabels(unittest.TestCase):
    def test_percentile_gap_labels(self):
        # fund order reversed vs market over 5 -> percentile gaps -1, -.5, 0, .5, 1
        fund = [5, 4, 3, 2, 1]
        market = [1, 2, 3, 4, 5]
        self.assertEqual(
            sd.percentile_gap_labels(fund, market, strong=0.75, weak=0.25),
            ["STRONG_BUY", "BUY", "HOLD", "SELL", "STRONG_SELL"],
        )

    def test_position_relative_is_independent_per_group(self):
        fund = [1, 2, 10, 20]
        market = [2, 1, 20, 10]
        groups = ["A", "A", "B", "B"]
        out = sd.position_percentile_gap_labels(fund, market, groups, strong=0.75, weak=0.25)
        self.assertEqual(out, ["STRONG_SELL", "STRONG_BUY", "STRONG_SELL", "STRONG_BUY"])


class TestEvaluation(unittest.TestCase):
    def test_excess_forward_change_removes_median_drift(self):
        m0 = [100.0, 100.0, 100.0]
        m1 = [110.0, 120.0, 90.0]  # rel .10 .20 -.10, median .10
        out = sd.excess_forward_change(m0, m1)
        for got, want in zip(out, [0.0, 0.10, -0.20]):
            self.assertAlmostEqual(got, want)

    def test_evaluate_origin_hit_rates(self):
        labels = ["STRONG_SELL", "SELL", "BUY", "HOLD"]
        fx = [-0.1, 0.2, 0.3, -0.3]
        score = [-3.0, -2.0, 2.0, 0.0]
        r = sd.evaluate_origin(labels, score, fx)
        self.assertEqual(r["n_sell"], 2)
        self.assertAlmostEqual(r["sell_hit"], 0.5)
        self.assertEqual(r["n_buy"], 1)
        self.assertAlmostEqual(r["buy_hit"], 1.0)
        self.assertAlmostEqual(r["base_down"], 0.5)
        self.assertAlmostEqual(r["base_up"], 0.5)
        self.assertFalse(math.isnan(r["ic"]))

    def test_no_support_is_none_not_zero(self):
        r = sd.evaluate_origin(["HOLD", "HOLD", "HOLD"], [1, 2, 3], [0.1, 0.2, 0.3])
        self.assertIsNone(r["sell_hit"])
        self.assertIsNone(r["buy_hit"])
        self.assertEqual(sd.label_census(["B", "A", "B"]), {"A": 1, "B": 2})


if __name__ == "__main__":
    unittest.main()


class TestUncertainty(unittest.TestCase):
    def test_sign_flip_exact(self):
        # values (+1,+1): patterns ++,+-,-+,-- -> |sum| >= 2 for 2 of 4 -> p = 0.5
        self.assertAlmostEqual(sd.sign_flip_p([1.0, 1.0]), 0.5)
        # (+1,-1): |sum| = 0, every pattern qualifies -> p = 1
        self.assertAlmostEqual(sd.sign_flip_p([1.0, -1.0]), 1.0)
        self.assertIsNone(sd.sign_flip_p([1.0]))

    def test_bootstrap_ci_constant_and_deterministic(self):
        self.assertEqual(sd.bootstrap_mean_ci([0.5, 0.5, 0.5]), (0.5, 0.5))
        a = sd.bootstrap_mean_ci([0.0, 1.0, 2.0, 3.0], n_boot=500, seed=3)
        self.assertEqual(a, sd.bootstrap_mean_ci([0.0, 1.0, 2.0, 3.0], n_boot=500, seed=3))
        self.assertLessEqual(a[0], 1.5)
        self.assertGreaterEqual(a[1], 1.5)
        self.assertIsNone(sd.bootstrap_mean_ci([1.0]))

    def test_cluster_rate_ci(self):
        self.assertEqual(sd.cluster_rate_ci([(5, 10), (5, 10), (5, 10)]), (0.5, 0.5))
        self.assertIsNone(sd.cluster_rate_ci([(0, 0), (0, 0)]))
