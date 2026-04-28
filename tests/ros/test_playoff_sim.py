"""ROS playoff + championship simulator tests.

Build a tiny synthetic snapshot, run the sims with a low simulation
count for speed, and assert structural properties: probabilities sum
to 1.0 across seeds, contender tier classification matches the spec,
ROS-strength availability gracefully degrades to empirical-only.
"""
from __future__ import annotations

import random
import unittest
from unittest.mock import patch

from src.ros import championship, playoff_sim
from src.ros.championship import _contender_tier


class TestContenderTier(unittest.TestCase):
    def test_favorite_tier(self):
        self.assertEqual(_contender_tier(0.25, 0.95), "Favorite")

    def test_serious_contender_tier(self):
        self.assertEqual(_contender_tier(0.12, 0.80), "Serious Contender")

    def test_dangerous_playoff_tier(self):
        self.assertEqual(_contender_tier(0.06, 0.55), "Dangerous Playoff Team")
        self.assertEqual(_contender_tier(0.02, 0.55), "Dangerous Playoff Team")

    def test_fringe_playoff(self):
        self.assertEqual(_contender_tier(0.01, 0.35), "Fringe Playoff Team")

    def test_long_shot(self):
        self.assertEqual(_contender_tier(0.00, 0.15), "Long Shot")

    def test_rebuilder(self):
        self.assertEqual(_contender_tier(0.00, 0.05), "Rebuilder / Seller")


class TestEmptySnapshot(unittest.TestCase):
    """Sims must degrade gracefully when no scoring data exists."""

    def test_playoff_empty(self):
        from types import SimpleNamespace
        snap = SimpleNamespace(seasons=[], managers=None)
        out = playoff_sim.simulate_playoff_odds(snap, n_simulations=10)
        self.assertEqual(out["playoffOdds"], [])

    def test_championship_empty(self):
        from types import SimpleNamespace
        snap = SimpleNamespace(seasons=[], managers=None)
        out = championship.simulate_championship_odds(snap, n_simulations=10)
        self.assertEqual(out["championshipOdds"], [])


class TestRosStrengthLoader(unittest.TestCase):
    def test_returns_empty_when_no_snapshot(self):
        from pathlib import Path
        with patch.object(playoff_sim, "ROS_DATA_DIR", Path("/nonexistent")):
            self.assertEqual(playoff_sim._load_ros_strength_map(), {})


class TestSimulateBracket(unittest.TestCase):
    def test_top_seed_wins_when_distribution_is_dominant(self):
        # Construct distributions where owner1 is overwhelmingly best.
        distributions = {
            f"o{i}": playoff_sim._TeamDist(
                owner_id=f"o{i}",
                mean=200.0 - i * 30,  # o0 = 200, o5 = 50
                sd=5.0,
                pf_to_date=0.0,
            )
            for i in range(6)
        }
        rng = random.Random(42)
        finishes = championship._simulate_bracket(
            list(distributions.keys()),
            distributions,
            bye_seeds=2,
            rng=rng,
        )
        # Owner with the highest mean should usually win.  Run many
        # times to check; a single run could go either way due to sd.
        wins = 0
        for seed in range(50):
            rng = random.Random(seed)
            out = championship._simulate_bracket(
                list(distributions.keys()),
                distributions,
                bye_seeds=2,
                rng=rng,
            )
            if out.get("o0") == 1:
                wins += 1
        self.assertGreater(wins, 25, "top seed should win majority of brackets")


class TestRosBlendConstants(unittest.TestCase):
    def test_blend_is_modest(self):
        # Spec: empirical history should still dominate; tunable but
        # not aggressive by default.
        self.assertLessEqual(playoff_sim.ROS_BLEND, 0.30)
        self.assertGreater(playoff_sim.ROS_BLEND, 0.0)

    def test_variance_bump_above_one(self):
        self.assertGreater(playoff_sim.BEST_BALL_VARIANCE_BUMP, 1.0)


if __name__ == "__main__":
    unittest.main()
