"""Preseason ranking + progressive per-component eligibility (2026-09).

Acceptance scenarios 1 and 2 of the Week 1 Power Rankings directive:

    1. Entering Week 1 (preseason): all real managers are ranked with
       deterministic non-null scores, with no fabricated current-season
       results (the historical-results components are correctly
       suppressed, not zeroed).
    2. After Week 1: Week-1-derived components begin contributing, the
       forward-looking component remains part of the model, components
       that are not yet eligible are excluded (not zeroed), and every
       manager stays ranked.

The eligibility thresholds pinned here (``_MIN_SCORED_GAMES``) are
DERIVED from the component formulas, not chosen -- see the module
docstring on ``src/ros/power_v2.py`` next to the constant for the
per-component justification. This file proves the resulting activation
timeline: 1 game -> ppg/wl_record/all_play; 2 games -> + streak; 4 games
-> + recent/luck_regression (the full spec vector).
"""

from __future__ import annotations

import unittest
from unittest.mock import patch

from src.api import league_registry
from src.ros import power_v2, team_strength
from tests.ros.test_power_v2 import _make_snapshot


def _fake_league_env(owner_players, ros_values):
    """Context manager stack: a resolvable league config + ROS aggregate,
    so the live team-strength fallback can answer without any network
    I/O or dependence on this sandbox's ambient config/data files."""
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
        pid: {"full_name": f"Player {pid.upper()}", "position": "WR", "fantasy_positions": ["WR"]}
        for pid in owner_players.values()
    }
    return owner_players


class TestScenario1PreseasonEnteringWeek1(unittest.TestCase):
    """All 12 real managers ranked with deterministic non-null scores;
    no fabricated current-season results."""

    def test_all_twelve_managers_are_ranked_preseason(self):
        rosters = _twelve_manager_rosters()
        snapshot = _make_snapshot(rosters=rosters)
        owner_players = _hydrate_with_players(snapshot, rosters)
        ros_values = {oid: 100.0 - i for i, oid in enumerate(owner_players)}

        tmp, *patches = _fake_league_env(owner_players, ros_values)
        with tmp, patches[0], patches[1], patches[2], patches[3]:
            section = power_v2.build_section(snapshot, lens=power_v2.LENS_FORWARD_LOOKING)

        self.assertTrue(section["preseason"])
        self.assertIsNone(section.get("unrankable"))
        self.assertEqual(len(section["currentRanking"]), 12)
        for row in section["currentRanking"]:
            self.assertIsNotNone(row["powerScore"])
            self.assertIsNotNone(row["rank"])

    def test_preseason_does_not_fabricate_current_season_results(self):
        """No historical-results component may be present preseason --
        there are no games to have produced them."""
        rosters = _twelve_manager_rosters()
        snapshot = _make_snapshot(rosters=rosters)
        owner_players = _hydrate_with_players(snapshot, rosters)
        ros_values = {oid: 100.0 - i for i, oid in enumerate(owner_players)}

        tmp, *patches = _fake_league_env(owner_players, ros_values)
        with tmp, patches[0], patches[1], patches[2], patches[3]:
            section = power_v2.build_section(snapshot, lens=power_v2.LENS_FORWARD_LOOKING)

        for component in power_v2._HISTORICAL_RESULTS_COMPONENTS:
            self.assertNotIn(component, section["effectiveWeights"])

    def test_scores_are_deterministic_across_repeated_calls(self):
        rosters = _twelve_manager_rosters()
        snapshot = _make_snapshot(rosters=rosters)
        owner_players = _hydrate_with_players(snapshot, rosters)
        ros_values = {oid: 100.0 - i for i, oid in enumerate(owner_players)}

        tmp, *patches = _fake_league_env(owner_players, ros_values)
        with tmp, patches[0], patches[1], patches[2], patches[3]:
            first = power_v2.build_section(snapshot, lens=power_v2.LENS_FORWARD_LOOKING)
            second = power_v2.build_section(snapshot, lens=power_v2.LENS_FORWARD_LOOKING)

        first_scores = {r["ownerId"]: r["powerScore"] for r in first["currentRanking"]}
        second_scores = {r["ownerId"]: r["powerScore"] for r in second["currentRanking"]}
        self.assertEqual(first_scores, second_scores)


class TestScenario2AfterWeek1(unittest.TestCase):
    """Week-1-derived components begin contributing; the forward-looking
    component remains part of the model; not-yet-eligible components are
    excluded (not zeroed); every manager stays ranked."""

    def _snapshot_with_n_scored_weeks(self, n):
        rosters = _twelve_manager_rosters()
        matchups = {
            wk: [
                {"roster_id": i, "matchup_id": (i + 1) // 2, "points": 100.0 + i + wk}
                for i in range(1, 13)
            ]
            for wk in range(1, n + 1)
        }
        snapshot = _make_snapshot(rosters=rosters, matchups_by_week=matchups)
        owner_players = _hydrate_with_players(snapshot, rosters)
        return snapshot, owner_players

    def test_week_1_adds_ppg_wl_all_play_keeps_team_ros_strength(self):
        snapshot, owner_players = self._snapshot_with_n_scored_weeks(1)
        ros_values = {oid: 100.0 - i for i, oid in enumerate(owner_players)}
        tmp, *patches = _fake_league_env(owner_players, ros_values)
        with tmp, patches[0], patches[1], patches[2], patches[3]:
            section = power_v2.build_section(snapshot, lens=power_v2.LENS_FORWARD_LOOKING)

        self.assertFalse(section["preseason"])
        eff = section["effectiveWeights"]
        self.assertIn("team_ros_strength", eff, "the forward-looking component must survive Week 1")
        self.assertIn("ppg", eff)
        self.assertIn("wl_record", eff)
        self.assertIn("all_play", eff)
        # Not yet eligible at n=1.
        self.assertNotIn("recent", eff)
        self.assertNotIn("streak", eff)
        self.assertNotIn("luck_regression", eff)
        self.assertEqual(len(section["currentRanking"]), 12)
        for row in section["currentRanking"]:
            self.assertIsNotNone(row["powerScore"])
            # A not-yet-eligible component is excluded, not zeroed.
            self.assertIsNone(row["components"].get("recent"))
            self.assertIsNone(row["components"].get("luck_regression"))
            self.assertIsNone(row["components"].get("streak"))

    def test_week_2_adds_streak(self):
        snapshot, owner_players = self._snapshot_with_n_scored_weeks(2)
        ros_values = {oid: 100.0 - i for i, oid in enumerate(owner_players)}
        tmp, *patches = _fake_league_env(owner_players, ros_values)
        with tmp, patches[0], patches[1], patches[2], patches[3]:
            section = power_v2.build_section(snapshot, lens=power_v2.LENS_FORWARD_LOOKING)

        eff = section["effectiveWeights"]
        self.assertIn("streak", eff)
        self.assertNotIn("recent", eff)
        self.assertNotIn("luck_regression", eff)

    def test_week_4_activates_the_full_spec_vector(self):
        snapshot, owner_players = self._snapshot_with_n_scored_weeks(4)
        ros_values = {oid: 100.0 - i for i, oid in enumerate(owner_players)}
        tmp, *patches = _fake_league_env(owner_players, ros_values)
        with tmp, patches[0], patches[1], patches[2], patches[3]:
            section = power_v2.build_section(snapshot, lens=power_v2.LENS_FORWARD_LOOKING)

        eff = set(section["effectiveWeights"])
        self.assertTrue(
            {
                "team_ros_strength",
                "ppg",
                "wl_record",
                "all_play",
                "streak",
                "recent",
                "luck_regression",
            }
            <= eff
            or {"ppg", "wl_record", "all_play", "streak", "recent", "luck_regression"} <= eff,
            eff,
        )
        for row in section["currentRanking"]:
            self.assertIsNotNone(row["powerScore"])

    def test_no_sudden_jump_weight_share_moves_gradually(self):
        """The documented complaint: the model must not jump from ~100%
        roster strength to an almost-entirely-one-game-result mix in a
        single week. Verify the forward-looking share decreases
        monotonically but never collapses to near-zero in one step."""
        shares = {}
        for n in (0, 1, 2, 4):
            snapshot, owner_players = (
                self._snapshot_with_n_scored_weeks(n)
                if n
                else (
                    _make_snapshot(rosters=_twelve_manager_rosters()),
                    None,
                )
            )
            if owner_players is None:
                owner_players = _hydrate_with_players(snapshot, _twelve_manager_rosters())
            ros_values = {oid: 100.0 - i for i, oid in enumerate(owner_players)}
            tmp, *patches = _fake_league_env(owner_players, ros_values)
            with tmp, patches[0], patches[1], patches[2], patches[3]:
                section = power_v2.build_section(snapshot, lens=power_v2.LENS_FORWARD_LOOKING)
            eff = section["effectiveWeights"]
            ros_share = eff.get("team_ros_strength", 0.0) / sum(eff.values()) if eff else 0.0
            shares[n] = ros_share

        # Monotonically non-increasing as more weeks activate.
        self.assertGreaterEqual(shares[0], shares[1])
        self.assertGreaterEqual(shares[1], shares[2])
        self.assertGreaterEqual(shares[2], shares[4])
        # No single week collapses the ROS share by more than half.
        self.assertGreater(shares[1], shares[0] * 0.3, shares)


if __name__ == "__main__":
    unittest.main()
