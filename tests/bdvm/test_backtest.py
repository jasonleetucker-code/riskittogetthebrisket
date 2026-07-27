"""Backtest harness: metrics, folds, leakage guard, baselines."""

from __future__ import annotations

import unittest

from src.bdvm.backtest import (
    Fold,
    LeakageError,
    baseline_predictions,
    brier,
    calibration,
    compare_surplus_modes,
    evaluate_fold,
    mae,
    rmse,
    rolling_origin_folds,
    run_backtest,
    s3_calibration,
    spearman,
)


class TestMetrics(unittest.TestCase):
    def test_mae_rmse(self):
        self.assertAlmostEqual(mae([1, 2, 3], [2, 2, 5]), 1.0)
        self.assertAlmostEqual(rmse([1, 2, 3], [2, 2, 5]), (5 / 3) ** 0.5)

    def test_spearman_perfect_and_reversed(self):
        self.assertAlmostEqual(spearman([1, 2, 3, 4], [10, 20, 30, 40]), 1.0)
        self.assertAlmostEqual(spearman([1, 2, 3, 4], [40, 30, 20, 10]), -1.0)

    def test_spearman_handles_ties(self):
        r = spearman([1, 1, 2, 3], [1, 2, 3, 4])
        self.assertGreater(r, 0.7)
        self.assertLess(r, 1.0)

    def test_brier(self):
        self.assertAlmostEqual(brier([1.0, 0.0], [1, 0]), 0.0)
        self.assertAlmostEqual(brier([0.5, 0.5], [1, 0]), 0.25)

    def test_calibration_slope_of_perfect_forecaster(self):
        import random

        rng = random.Random(7)
        preds, outs = [], []
        for _ in range(4000):
            p = rng.random()
            preds.append(p)
            outs.append(1 if rng.random() < p else 0)
        cal = calibration(preds, outs)
        self.assertAlmostEqual(cal["slope"], 1.0, delta=0.15)
        self.assertAlmostEqual(cal["intercept"], 0.0, delta=0.08)

    def test_empty_inputs_raise(self):
        with self.assertRaises(ValueError):
            mae([], [])


class TestFoldsAndLeakage(unittest.TestCase):
    def test_rolling_origin_never_tests_first_season(self):
        folds = rolling_origin_folds([2022, 2023, 2024, 2025])
        self.assertEqual(
            [(f.train_through, f.test_season) for f in folds],
            [(2022, 2023), (2023, 2024), (2024, 2025)],
        )

    def test_leakage_raises(self):
        rows = [
            {
                "player_key": "a",
                "season": 2024,
                "position": "WR",
                "feature_as_of": "2024-09-15",  # after the prediction date!
                "predicted": 10.0,
                "actual": 12.0,
            }
        ]
        with self.assertRaises(LeakageError):
            evaluate_fold(rows, fold=Fold(2023, 2024), prediction_date="2024-08-15")

    def test_missing_feature_stamp_raises(self):
        rows = [
            {"player_key": "a", "season": 2024, "position": "WR", "predicted": 10.0, "actual": 12.0}
        ]
        with self.assertRaises(LeakageError):
            evaluate_fold(rows, fold=Fold(2023, 2024), prediction_date="2024-08-15")

    def test_run_backtest_requires_declared_prediction_dates(self):
        rows = [
            {
                "player_key": "a",
                "season": s,
                "position": "WR",
                "feature_as_of": f"{s}-08-01",
                "predicted": 1.0,
                "actual": 1.0,
            }
            for s in (2023, 2024)
        ]
        with self.assertRaises(LeakageError):
            run_backtest(rows, prediction_dates={2023: "2023-08-15"})


class TestBaselinesAndScoring(unittest.TestCase):
    def _rows(self):
        rows = []
        for i in range(12):
            actual = 5.0 + i
            rows.append(
                {
                    "player_key": f"p{i}",
                    "season": 2024,
                    "position": "WR",
                    "feature_as_of": "2024-08-01",
                    "predicted": actual + (0.5 if i % 2 else -0.5),  # good model
                    "prior_ppg": actual - 2.0,
                    "projection_fpg": actual - 1.0,
                    "age": 24 + (i % 6),
                    "market_value": 20.0 - i,  # anti-correlated
                    "actual": actual,
                }
            )
        return rows

    def test_baseline_predictions_shapes(self):
        b = baseline_predictions(self._rows()[0])
        self.assertEqual(
            set(b),
            {"B0_prior_ppg", "B1_projection", "B2_projection_age", "B3_market", "B4_proj_age_pos"},
        )
        # age 24 → no penalty; B2 == B1
        self.assertEqual(b["B2_projection_age"], b["B1_projection"])
        old = baseline_predictions({**self._rows()[0], "age": 30})
        self.assertLess(old["B2_projection_age"], old["B1_projection"])

    def test_evaluate_fold_scores_model_and_baselines(self):
        result = evaluate_fold(self._rows(), fold=Fold(2023, 2024), prediction_date="2024-08-15")
        res = result["results"]
        self.assertGreater(res["model"]["spearman"], 0.9)
        self.assertGreater(res["B0_prior_ppg"]["spearman"], 0.9)
        self.assertLess(res["B3_market"]["spearman"], -0.9)  # anti-correlated
        self.assertIn("byPosition", result)
        self.assertIn("WR", result["byPosition"])

    def test_run_backtest_end_to_end(self):
        rows = self._rows() + [
            {**r, "season": 2025, "feature_as_of": "2025-08-01"} for r in self._rows()
        ]
        out = run_backtest(
            rows, prediction_dates={2024: "2024-08-15", 2025: "2025-08-15"}, min_train=1
        )
        self.assertEqual(out["foldCount"], 1)  # 2024 is the min-train season
        self.assertEqual(out["folds"][0]["fold"]["testSeason"], 2025)


class TestS3AndAblation(unittest.TestCase):
    def test_s3_calibration_gap(self):
        rows = [{"position": "RB", "predicted_s3": 0.6, "still_startable": 1}] * 3 + [
            {"position": "RB", "predicted_s3": 0.6, "still_startable": 0}
        ] * 7
        out = s3_calibration(rows)
        self.assertAlmostEqual(out["RB"]["meanPredictedS3"], 0.6)
        self.assertAlmostEqual(out["RB"]["observedRetention"], 0.3)
        self.assertAlmostEqual(out["RB"]["gap"], 0.3)

    def test_compare_surplus_modes(self):
        out = compare_surplus_modes(
            {
                "option": {"a": 100, "b": 80, "c": 60},
                "plain": {"a": 100, "b": 60, "c": 80},
            }
        )
        pair = out["rankAgreement"][0]
        self.assertEqual(pair["n"], 3)
        self.assertLess(pair["spearman"], 1.0)


if __name__ == "__main__":
    unittest.main()
