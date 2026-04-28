"""Direction classifier + per-player tag tests.

Pure-function tests with synthetic inputs.  No I/O, no live snapshots.
"""
from __future__ import annotations

import unittest

from src.ros.direction import (
    _is_veteran,
    build_roster_age_profile,
    classify_team,
)
from src.ros.tags import tag_descriptions, tags_for_player


class TestIsVeteran(unittest.TestCase):
    def test_qb_threshold(self):
        self.assertTrue(_is_veteran("QB", 32))
        self.assertFalse(_is_veteran("QB", 31))

    def test_rb_threshold(self):
        self.assertTrue(_is_veteran("RB", 26))
        self.assertFalse(_is_veteran("RB", 25))

    def test_wr_threshold(self):
        self.assertTrue(_is_veteran("WR", 29))

    def test_split_position_uses_first(self):
        self.assertTrue(_is_veteran("EDGE/DL", 30))

    def test_unknown_position_safe(self):
        self.assertFalse(_is_veteran("XY", 35))

    def test_missing_age_returns_false(self):
        self.assertFalse(_is_veteran("QB", None))


class TestRosterAgeProfile(unittest.TestCase):
    def test_counts_buckets(self):
        roster = [
            {"position": "QB", "age": 33},
            {"position": "WR", "age": 22},
            {"position": "RB", "age": 28},
            {"position": "TE", "age": 25},
        ]
        profile = build_roster_age_profile(roster)
        self.assertEqual(profile["totalPlayers"], 4)
        self.assertEqual(profile["vetCount"], 2)  # QB 33, RB 28
        # youngCount counts age <= 24 → only WR 22.
        self.assertEqual(profile["youngCount"], 1)


class TestClassifyTeam(unittest.TestCase):
    def test_strong_buyer(self):
        out = classify_team(
            playoff_odds_pct=0.85,
            championship_odds_pct=0.20,
            team_ros_strength_percentile=0.95,
        )
        self.assertEqual(out["label"], "Strong Buyer")

    def test_buyer(self):
        out = classify_team(
            playoff_odds_pct=0.65,
            championship_odds_pct=0.06,
            team_ros_strength_percentile=0.7,
        )
        self.assertEqual(out["label"], "Buyer")

    def test_selective_buyer(self):
        out = classify_team(
            playoff_odds_pct=0.50,
            championship_odds_pct=0.03,
            team_ros_strength_percentile=0.5,
        )
        self.assertEqual(out["label"], "Selective Buyer")

    def test_strong_seller_with_age(self):
        out = classify_team(
            playoff_odds_pct=0.05,
            championship_odds_pct=0.005,
            team_ros_strength_percentile=0.1,
            roster_age_profile={"vetCount": 5, "totalPlayers": 12},
        )
        self.assertEqual(out["label"], "Strong Seller / Rebuilder")

    def test_seller_without_age_profile(self):
        out = classify_team(
            playoff_odds_pct=0.05,
            championship_odds_pct=0.005,
            team_ros_strength_percentile=0.1,
            roster_age_profile={"vetCount": 1},
        )
        # Without age-heavy profile, falls into Seller (not Strong).
        self.assertEqual(out["label"], "Seller")

    def test_hold_default_band(self):
        out = classify_team(
            playoff_odds_pct=0.42,
            championship_odds_pct=0.02,
            team_ros_strength_percentile=0.4,
        )
        # Falls into Hold / Evaluate (no other branch claims this).
        self.assertEqual(out["label"], "Hold / Evaluate")


class TestTagsForPlayer(unittest.TestCase):
    def test_no_ros_value_no_tags(self):
        tags = tags_for_player(
            canonical_name="X",
            position="QB",
            age=25,
            ros_value=None,
        )
        self.assertEqual(tags, [])

    def test_zero_ros_value_no_tags(self):
        tags = tags_for_player(
            canonical_name="X", position="QB", age=25, ros_value=0
        )
        self.assertEqual(tags, [])

    def test_win_now_target_for_strong_vet(self):
        tags = tags_for_player(
            canonical_name="Veteran QB",
            position="QB",
            age=33,
            ros_value=70,
        )
        self.assertIn("Win-now target", tags)

    def test_contender_upgrade_for_elite_offense(self):
        tags = tags_for_player(
            canonical_name="Elite WR",
            position="WR",
            age=27,
            ros_value=85,
            ros_rank_overall=10,
        )
        self.assertIn("Contender upgrade", tags)

    def test_seller_cash_out_dynasty_lag(self):
        tags = tags_for_player(
            canonical_name="Aging Stud",
            position="WR",
            age=30,
            ros_value=70,
            dynasty_value=40,  # 40 < 70 * 0.7
        )
        self.assertIn("Seller cash-out", tags)

    def test_rebuilder_hold_for_young_unproven(self):
        tags = tags_for_player(
            canonical_name="Young WR",
            position="WR",
            age=22,
            ros_value=40,
        )
        self.assertIn("Rebuilder hold", tags)

    def test_idp_contender_target(self):
        tags = tags_for_player(
            canonical_name="Elite LB",
            position="LB",
            age=27,
            ros_value=80,
            ros_rank_overall=20,
        )
        self.assertIn("IDP contender target", tags)

    def test_descriptions_cover_all_tags(self):
        # Every tag the classifier can emit should have a description.
        all_tags_emitted = set()
        for params in [
            {"position": "QB", "age": 33, "ros_value": 70},
            {"position": "WR", "age": 27, "ros_value": 85, "ros_rank_overall": 10},
            {"position": "WR", "age": 30, "ros_value": 70, "dynasty_value": 40},
            {"position": "WR", "age": 22, "ros_value": 40},
            {"position": "LB", "age": 27, "ros_value": 80, "ros_rank_overall": 20},
            {"position": "RB", "age": 30, "ros_value": 65, "volatility_flag": True, "ros_rank_overall": 50},
        ]:
            tags = tags_for_player(canonical_name="X", **params)
            all_tags_emitted.update(tags)
        descriptions = tag_descriptions()
        for tag in all_tags_emitted:
            self.assertIn(tag, descriptions, f"missing description for {tag}")


if __name__ == "__main__":
    unittest.main()
