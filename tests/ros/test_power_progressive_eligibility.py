"""Canonical Power early-season weighting and manager completeness.

The previous file pinned cliff-based Week-1/2/4 activation. The canonical
methodology intentionally replaces those cliffs with a smooth evidence curve:
results matter immediately, then earn more influence as scored games accumulate.
"""

from __future__ import annotations

import unittest
from unittest.mock import patch

from src.api import league_registry
from src.ros import power_v2, team_strength
from tests.ros.test_power_v2 import _make_snapshot


def _fake_league_env(owner_players, ros_values):
    fake_cfg = league_registry.LeagueConfig(
        key="test_league",
        display_name="Test League",
        sleeper_league_id="test-sleeper-id",
        scoring_profile="test",
        roster_settings={"starters": {"WR": 1}},
        idp_enabled=False,
    )
    aggregate_players = [
        {
            "canonicalName": f"player {pid.lower()}",
            "position": "WR",
            "rosValue": ros_values[oid],
            "confidence": 0.9,
        }
        for oid, pid in owner_players.items()
    ]
    import tempfile
    from pathlib import Path

    tmp = tempfile.TemporaryDirectory()
    return (
        tmp,
        patch.object(team_strength, "ROS_DATA_DIR", Path(tmp.name)),
        patch.object(league_registry, "get_default_league", return_value=fake_cfg),
        patch.object(league_registry, "get_league_by_key", return_value=fake_cfg),
        patch.object(team_strength, "load_ros_aggregate_players", return_value=aggregate_players),
    )


def _twelve_manager_rosters():
    return [{"owner_id": f"owner-{i:02d}", "roster_id": i} for i in range(1, 13)]


def _hydrate_with_players(snapshot, rosters):
    owner_players = {r["owner_id"]: f"p{r['roster_id']}" for r in rosters}
    for roster in snapshot.current_season.rosters:
        roster["players"] = [owner_players[roster["owner_id"]]]
    snapshot.nfl_players = {
        pid: {
            "full_name": f"Player {pid.upper()}",
            "position": "WR",
            "fantasy_positions": ["WR"],
        }
        for pid in owner_players.values()
    }
    return owner_players


def _section_with_n_scored_weeks(n: int):
    rosters = _twelve_manager_rosters()
    matchups = {
        wk: [
            {
                "roster_id": i,
                "matchup_id": (i + 1) // 2,
                "points": 100.0 + i + wk,
            }
            for i in range(1, 13)
        ]
        for wk in range(1, n + 1)
    }
    snapshot = _make_snapshot(rosters=rosters, matchups_by_week=matchups)
    owner_players = _hydrate_with_players(snapshot, rosters)
    ros_values = {oid: 100.0 - i for i, oid in enumerate(owner_players)}
    tmp, *patches = _fake_league_env(owner_players, ros_values)
    with tmp, patches[0], patches[1], patches[2], patches[3]:
        return power_v2.build_section(snapshot, lens=power_v2.LENS_CANONICAL)


class TestCanonicalSeasonAwareBlend(unittest.TestCase):
    def test_preseason_is_all_forward_and_ranks_all_twelve(self):
        section = _section_with_n_scored_weeks(0)
        self.assertTrue(section["preseason"])
        self.assertEqual(section["lens"], power_v2.LENS_CANONICAL)
        self.assertEqual(len(section["currentRanking"]), 12)
        self.assertEqual(section["blend"]["forwardWeight"], 1.0)
        self.assertEqual(section["blend"]["resultsWeight"], 0.0)
        self.assertEqual(set(section["effectiveWeights"]), {"team_ros_strength"})
        self.assertTrue(all(row["rank"] is not None for row in section["currentRanking"]))

    def test_week_one_gives_real_results_meaningful_but_minor_weight(self):
        section = _section_with_n_scored_weeks(1)
        blend = section["blend"]
        self.assertFalse(section["preseason"])
        self.assertGreater(blend["resultsWeight"], 0.20)
        self.assertLess(blend["resultsWeight"], 0.35)
        self.assertGreater(blend["forwardWeight"], blend["resultsWeight"])
        self.assertEqual(
            set(section["effectiveWeights"]),
            {"team_ros_strength", "all_play", "recent", "wl_record"},
        )
        self.assertIn("team_vorp", " ".join(section["missingInputs"]))
        for retired in ("ppg", "streak", "luck_regression", "schedule_adjusted"):
            self.assertNotIn(retired, section["effectiveWeights"])

    def test_results_influence_grows_smoothly_and_monotonically(self):
        results_shares = {
            n: _section_with_n_scored_weeks(n)["blend"]["resultsWeight"]
            for n in (0, 1, 2, 4, 8, 14)
        }
        self.assertEqual(results_shares[0], 0.0)
        self.assertLess(results_shares[1], results_shares[2])
        self.assertLess(results_shares[2], results_shares[4])
        self.assertLess(results_shares[4], results_shares[8])
        self.assertLess(results_shares[8], results_shares[14])
        # The late-season ceiling is the owner-approved 60% observed-results target.
        self.assertLess(results_shares[14], 0.60)
        self.assertGreater(results_shares[14], 0.55)

    def test_curve_is_not_a_week_number_switch(self):
        for n in (1, 2, 3, 4, 5):
            section = _section_with_n_scored_weeks(n)
            self.assertAlmostEqual(
                section["blend"]["resultsEvidence"],
                power_v2._results_evidence(n),
                places=6,
            )

    def test_missing_vorp_renormalises_inside_results_bucket(self):
        section = _section_with_n_scored_weeks(8)
        result_component_weight = sum(
            section["effectiveWeights"].get(k, 0.0)
            for k in ("all_play", "recent", "wl_record")
        )
        self.assertAlmostEqual(result_component_weight, section["blend"]["resultsWeight"], places=6)
        self.assertNotIn("team_vorp", section["effectiveWeights"])

    def test_repeated_calls_are_deterministic(self):
        first = _section_with_n_scored_weeks(4)
        second = _section_with_n_scored_weeks(4)
        self.assertEqual(
            [(r["ownerId"], r["rank"], r["powerScore"]) for r in first["currentRanking"]],
            [(r["ownerId"], r["rank"], r["powerScore"]) for r in second["currentRanking"]],
        )


if __name__ == "__main__":
    unittest.main()
