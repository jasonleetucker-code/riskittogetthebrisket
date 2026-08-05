"""The ROS direction section's documented inputs actually reach it.

Audit W17-F010 / W20-F016: ``build_section`` did ``_ = snapshot`` under
a comment claiming "roster ages come from team_strength snapshot
directly". They do not — ``fullRoster`` rows carry ``position`` and
``rosValue`` and no age — so ``build_roster_age_profile`` was never
called on any production path, all 12 live rows shipped
``ageProfile: {}``, and the "Strong Seller / Rebuilder" band gated on
``vetCount >= 4`` was structurally unreachable.

Also pinned here: the two surviving direction engines stamp which one
they are (W20-F006's acceptance criterion), and an unmeasurable ROS
strength percentile reports as unavailable rather than as 0%.
"""

from __future__ import annotations

import unittest
from types import SimpleNamespace
from unittest.mock import patch

from src.ros import trade_deadline
from src.ros.direction import build_roster_age_profile, classify_team
from src.roster_intel.window import DIRECTION_ENGINE as WINDOW_ENGINE

_SNAPSHOT_ROWS = [
    {
        "ownerId": "owner-a",
        "teamName": "Aging Anchors",
        "rank": 12,
        # Four veterans by the position-aware table (RB 26+, WR 29+,
        # QB 32+) plus one youngster.
        "fullRoster": [
            {"playerId": "p1", "position": "RB"},
            {"playerId": "p2", "position": "WR"},
            {"playerId": "p3", "position": "QB"},
            {"playerId": "p4", "position": "TE"},
            {"playerId": "p5", "position": "WR"},
        ],
    },
    {
        "ownerId": "owner-b",
        "teamName": "Kids",
        "rank": 1,
        "fullRoster": [{"playerId": "p5", "position": "WR"}],
    },
]

_NFL_PLAYERS = {
    "p1": {"age": 29},
    "p2": {"age": 31},
    "p3": {"age": 34},
    "p4": {"age": 32},
    "p5": {"age": 22},
}

_ODDS = {"owner-a": {"playoffOdds": 0.01}, "owner-b": {"playoffOdds": 0.99}}
_CHAMPS = {
    "owner-a": {"championshipOdds": 0.001},
    "owner-b": {"championshipOdds": 0.40},
}


def _snapshot(players=None):
    return SimpleNamespace(nfl_players=_NFL_PLAYERS if players is None else players)


class TeamsWithAgesTests(unittest.TestCase):
    def test_joins_ages_from_the_sleeper_dump(self) -> None:
        with patch.object(
            trade_deadline, "load_team_strength_snapshot", return_value=_SNAPSHOT_ROWS
        ):
            teams = trade_deadline.teams_with_ages(_snapshot())
        self.assertEqual([t["ownerId"] for t in teams], ["owner-a", "owner-b"])
        ages = [p["age"] for p in teams[0]["players"]]
        self.assertEqual(ages, [29, 31, 34, 32, 22])

    def test_missing_dump_yields_no_teams_rather_than_ageless_ones(self) -> None:
        with patch.object(
            trade_deadline, "load_team_strength_snapshot", return_value=_SNAPSHOT_ROWS
        ):
            self.assertEqual(trade_deadline.teams_with_ages(_snapshot({})), [])
            self.assertEqual(trade_deadline.teams_with_ages(SimpleNamespace()), [])

    def test_a_player_sleeper_cannot_age_stays_none(self) -> None:
        with patch.object(
            trade_deadline, "load_team_strength_snapshot", return_value=_SNAPSHOT_ROWS
        ):
            teams = trade_deadline.teams_with_ages(_snapshot({"p1": {}}))
        self.assertIsNone(teams[0]["players"][0]["age"])
        # And the profile skips it rather than counting it either way.
        profile = build_roster_age_profile(teams[0]["players"])
        self.assertEqual(profile["vetCount"], 0)
        self.assertEqual(profile["youngCount"], 0)


class BuildSectionTests(unittest.TestCase):
    def _section(self):
        with (
            patch.object(
                trade_deadline, "load_team_strength_snapshot", return_value=_SNAPSHOT_ROWS
            ),
            patch.object(trade_deadline, "_load_playoff_odds_map", return_value=_ODDS),
            patch.object(trade_deadline, "_load_championship_map", return_value=_CHAMPS),
        ):
            return trade_deadline.build_section(_snapshot())

    def test_every_row_carries_a_non_empty_age_profile(self) -> None:
        rows = self._section()["teams"]
        self.assertEqual(len(rows), 2)
        empty = [r["ownerId"] for r in rows if not r.get("ageProfile")]
        self.assertEqual(empty, [], "build_section discarded the snapshot again")
        by_owner = {r["ownerId"]: r for r in rows}
        self.assertEqual(by_owner["owner-a"]["ageProfile"]["vetCount"], 4)
        self.assertEqual(by_owner["owner-b"]["ageProfile"]["youngCount"], 1)

    def test_the_age_gated_band_is_reachable_in_production(self) -> None:
        by_owner = {r["ownerId"]: r for r in self._section()["teams"]}
        self.assertEqual(by_owner["owner-a"]["label"], "Strong Seller / Rebuilder")

    def test_both_direction_engines_stamp_which_one_they_are(self) -> None:
        section = self._section()
        self.assertEqual(section["directionEngine"], "ros.direction")
        for row in section["teams"]:
            self.assertEqual(row["directionEngine"], "ros.direction")
        # ...and they are different engines, deliberately.
        self.assertNotEqual(section["directionEngine"], WINDOW_ENGINE)


class StrengthIsReportedHonestlyTests(unittest.TestCase):
    def test_unmeasurable_strength_reads_unavailable_not_zero_percent(self) -> None:
        out = classify_team(
            playoff_odds_pct=0.5,
            championship_odds_pct=0.03,
            team_ros_strength_percentile=None,
        )
        self.assertIn("ROS strength percentile unavailable", out["summary"])
        self.assertNotIn("percentile 0%", out["summary"])

    def test_a_measured_zero_still_reads_as_zero(self) -> None:
        out = classify_team(
            playoff_odds_pct=0.5,
            championship_odds_pct=0.03,
            team_ros_strength_percentile=0.0,
        )
        self.assertIn("ROS strength percentile 0%", out["summary"])

    def test_an_unranked_owner_gets_none_not_a_last_place_percentile(self) -> None:
        rows = trade_deadline.build_team_directions(
            playoff_odds_map=_ODDS,
            championship_map=_CHAMPS,
            team_strength_map={"owner-a": {"teamName": "A"}},  # no rank
        )
        by_owner = {r["ownerId"]: r for r in rows}
        self.assertIsNone(by_owner["owner-a"]["rosStrengthPercentile"])


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
