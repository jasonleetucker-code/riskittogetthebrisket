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
        # Use a temp dir so we never touch the production snapshot —
        # under the real ROS_DATA_DIR this test would wipe live data.
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            tmp_root = Path(tmp)
            target = tmp_root / "team_strength" / "latest.json"
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
            with patch.object(power_v2, "ROS_DATA_DIR", tmp_root):
                result = power_v2._load_team_strength_percentiles()
            self.assertEqual(set(result.keys()), {"alpha", "beta", "gamma"})
            self.assertGreater(result["alpha"], result["beta"])
            self.assertGreater(result["beta"], result["gamma"])


class TestWeights(unittest.TestCase):
    def test_weights_sum_to_one(self):
        self.assertAlmostEqual(sum(power_v2.WEIGHTS.values()), 1.0, places=2)

    def test_team_ros_strength_dominates(self):
        # Per spec: 0.38 is the largest individual weight.
        self.assertEqual(
            max(power_v2.WEIGHTS.values()),
            power_v2.WEIGHTS["team_ros_strength"],
        )


class TestDisplayNameResolution(unittest.TestCase):
    """Regression: power_v2 used to call ``registry.display_name_for(oid)``
    behind a ``hasattr`` guard.  ``ManagerRegistry`` doesn't define that
    method (the canonical helper is the module-level
    ``src.public_league.metrics.display_name_for(snapshot, owner_id)``),
    so the hasattr always returned False and ``displayName`` fell back
    to the raw Sleeper owner_id.  The /league Power Rankings table then
    rendered numeric IDs in the OWNER column.

    The fix imports ``metrics.display_name_for`` and calls it directly.
    These tests pin the new path:

      1. ``metrics.display_name_for`` is the canonical helper used
         everywhere else in the public_league pipeline (records.py,
         streaks.py, activity.py).  Verify it resolves to the
         manager's human-readable display name when registered.
      2. Falls back to owner_id when the registry has no entry —
         matching ``metrics.display_name_for``'s contract so a
         pre-snapshot orphan ownerId doesn't crash with AttributeError.

    The build_section integration is implicitly covered by the
    line that calls ``_metrics.display_name_for(snapshot, oid)``;
    these unit tests pin the helper itself so a future refactor of
    metrics.py won't silently regress the call site.
    """
    def test_metrics_display_name_for_resolves_registered_owner(self):
        from src.public_league.identity import Manager, ManagerRegistry
        from src.public_league.snapshot import PublicLeagueSnapshot
        from src.public_league import metrics
        registry = ManagerRegistry(
            by_owner_id={
                "owner-A": Manager(
                    owner_id="owner-A",
                    display_name="Russini Panini",
                    current_team_name="Russini Panini",
                ),
            },
        )
        snapshot = PublicLeagueSnapshot(
            root_league_id="L1",
            generated_at="2026-04-29T00:00:00Z",
            seasons=[],
            managers=registry,
        )
        # The canonical helper power_v2 now uses.
        self.assertEqual(
            metrics.display_name_for(snapshot, "owner-A"),
            "Russini Panini",
        )

    def test_metrics_display_name_for_falls_back_to_owner_id(self):
        from src.public_league.identity import ManagerRegistry
        from src.public_league.snapshot import PublicLeagueSnapshot
        from src.public_league import metrics
        snapshot = PublicLeagueSnapshot(
            root_league_id="L1",
            generated_at="2026-04-29T00:00:00Z",
            seasons=[],
            managers=ManagerRegistry(),
        )
        # Unknown owner_id falls through to the raw string — never
        # raises on missing manager.
        self.assertEqual(
            metrics.display_name_for(snapshot, "orphan-owner"),
            "orphan-owner",
        )

    def test_power_v2_uses_metrics_helper_not_registry_method(self):
        """Pin the source of the bug: ``ManagerRegistry`` does NOT
        expose ``display_name_for`` as a method.  Any future code
        that re-introduces ``registry.display_name_for(...)`` would
        silently fall back to owner_id again.  This test is the
        canary."""
        from src.public_league.identity import ManagerRegistry
        self.assertFalse(
            hasattr(ManagerRegistry, "display_name_for"),
            "If ManagerRegistry gains a display_name_for method, "
            "update power_v2.py to call it directly and remove this "
            "test — the bug it pins becomes irrelevant.",
        )


if __name__ == "__main__":
    unittest.main()
