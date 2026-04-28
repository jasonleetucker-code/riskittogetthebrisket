"""Tests for the ROS-driven power-rankings v2.

Verifies the formula composition + handling of missing inputs +
graceful degradation when ROS team-strength snapshot is absent.
"""
from __future__ import annotations

import json
import unittest
from pathlib import Path
from unittest.mock import patch

from src.ros import power_v2


class TestStreakScore(unittest.TestCase):
    def test_no_history_returns_neutral(self):
        self.assertEqual(power_v2._streak_score_from_outcomes([]), 0.5)

    def test_winning_streak_above_neutral(self):
        s = power_v2._streak_score_from_outcomes([1.0, 1.0, 1.0])
        self.assertGreater(s, 0.5)

    def test_losing_streak_below_neutral(self):
        s = power_v2._streak_score_from_outcomes([0.0, 0.0])
        self.assertLess(s, 0.5)

    def test_streak_caps_at_one(self):
        s = power_v2._streak_score_from_outcomes([1.0] * 20)
        self.assertLessEqual(s, 1.0)

    def test_streak_floors_at_zero(self):
        s = power_v2._streak_score_from_outcomes([0.0] * 20)
        self.assertGreaterEqual(s, 0.0)


class TestPercentile(unittest.TestCase):
    def test_top_value_yields_high_percentile(self):
        values = [10, 20, 30, 40, 50]
        self.assertGreater(power_v2._percentile(values, 50), 0.8)

    def test_bottom_value_low_percentile(self):
        values = [10, 20, 30, 40, 50]
        self.assertLess(power_v2._percentile(values, 10), 0.2)

    def test_empty_returns_zero(self):
        self.assertEqual(power_v2._percentile([], 5), 0.0)


class TestLoadTeamStrength(unittest.TestCase):
    def test_missing_file_returns_empty(self):
        with patch.object(power_v2, "ROS_DATA_DIR", Path("/nonexistent")):
            self.assertEqual(power_v2._load_team_strength_percentiles(), {})

    def test_loads_and_percentiles(self):
        # Create temp snapshot file under the real ROS_DATA_DIR.
        target = power_v2.ROS_DATA_DIR / "team_strength" / "latest.json"
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(
            json.dumps(
                [
                    {"ownerId": "alpha", "teamRosStrength": 90.0},
                    {"ownerId": "beta", "teamRosStrength": 60.0},
                    {"ownerId": "gamma", "teamRosStrength": 30.0},
                ]
            )
        )
        try:
            result = power_v2._load_team_strength_percentiles()
            self.assertEqual(set(result.keys()), {"alpha", "beta", "gamma"})
            self.assertGreater(result["alpha"], result["beta"])
            self.assertGreater(result["beta"], result["gamma"])
        finally:
            target.unlink()


class TestWeights(unittest.TestCase):
    def test_weights_sum_to_one(self):
        self.assertAlmostEqual(sum(power_v2.WEIGHTS.values()), 1.0, places=2)

    def test_team_ros_strength_dominates(self):
        # Per spec: 0.38 is the largest individual weight.
        self.assertEqual(
            max(power_v2.WEIGHTS.values()),
            power_v2.WEIGHTS["team_ros_strength"],
        )


if __name__ == "__main__":
    unittest.main()
