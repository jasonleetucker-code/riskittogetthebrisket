"""Team-strength composite + lineup-optimizer tests.

Mocks a tiny roster + an aggregated player-values list and verifies:
  - The optimizer fills starter slots greedily by ROS value.
  - SUPER_FLEX slots fall to QBs even when WRs have higher values
    (because slot priority filled WRs first).
  - Bench depth contribution decays with position seen-count.
  - Composite weighting matches the documented weights.
"""
from __future__ import annotations

import unittest

from src.ros.lineup import RosterPlayer, optimize_lineup
from src.ros.team_strength import compute_team_strength


def _agg(name: str, pos: str, value: float) -> dict:
    return {
        "canonicalName": name,
        "position": pos,
        "rosValue": value,
        "confidence": 0.9,
    }


class TestOptimizeLineup(unittest.TestCase):
    def test_picks_highest_eligible(self):
        roster = [
            RosterPlayer("p1", "TopQB", "QB", 95.0),
            RosterPlayer("p2", "BackupQB", "QB", 70.0),
            RosterPlayer("p3", "TopWR", "WR", 90.0),
            RosterPlayer("p4", "MidWR", "WR", 75.0),
            RosterPlayer("p5", "TopRB", "RB", 85.0),
        ]
        sol = optimize_lineup(roster, starter_slots=["QB", "WR", "RB", "FLEX"])
        slot_picks = {row["slot"]: row["canonicalName"] for row in sol.starting_lineup}
        self.assertEqual(slot_picks["QB"], "TopQB")
        self.assertEqual(slot_picks["WR"], "TopWR")
        self.assertEqual(slot_picks["RB"], "TopRB")
        # FLEX should be the next best WR/RB/TE remaining after the
        # primary slots filled.
        self.assertEqual(slot_picks["FLEX"], "MidWR")

    def test_super_flex_takes_qb_when_better(self):
        roster = [
            RosterPlayer("p1", "QB1", "QB", 95.0),
            RosterPlayer("p2", "QB2", "QB", 88.0),
            RosterPlayer("p3", "WR1", "WR", 80.0),
            RosterPlayer("p4", "WR2", "WR", 70.0),
        ]
        sol = optimize_lineup(roster, starter_slots=["QB", "WR", "SUPER_FLEX"])
        slot_picks = {row["slot"]: row["canonicalName"] for row in sol.starting_lineup}
        # SF slot should pick QB2 (88) over the next-best WR (70).
        self.assertEqual(slot_picks["SUPER_FLEX"], "QB2")

    def test_unfilled_slot_when_no_eligible(self):
        roster = [
            RosterPlayer("p1", "OnlyQB", "QB", 90.0),
        ]
        sol = optimize_lineup(roster, starter_slots=["QB", "WR"])
        self.assertIn("WR", sol.unfilled_slots)
        self.assertEqual(len(sol.starting_lineup), 1)

    def test_bench_depth_decays(self):
        roster = [
            RosterPlayer("p1", "TopWR", "WR", 90.0),
            RosterPlayer("p2", "BenchWR1", "WR", 70.0),
            RosterPlayer("p3", "BenchWR2", "WR", 60.0),
            RosterPlayer("p4", "BenchWR3", "WR", 50.0),
        ]
        # One WR starter slot -> 3 WRs land in bench.
        sol = optimize_lineup(roster, starter_slots=["WR"])
        depth_factors = [row["depthFactor"] for row in sol.bench_depth]
        # 1.0, 0.65, 0.65^2 ≈ 0.4225
        self.assertEqual(depth_factors[0], 1.0)
        self.assertAlmostEqual(depth_factors[1], 0.65, places=2)
        self.assertAlmostEqual(depth_factors[2], 0.4225, places=2)


class TestTeamStrengthComposite(unittest.TestCase):
    def test_composite_uses_documented_weights(self):
        teams = [
            {
                "ownerId": "o1",
                "rosterId": 1,
                "teamName": "Team Alpha",
                "players": [
                    {"playerId": "1", "name": "TopQB", "position": "QB"},
                    {"playerId": "2", "name": "TopWR", "position": "WR"},
                    {"playerId": "3", "name": "TopRB", "position": "RB"},
                ],
            }
        ]
        agg = [
            _agg("TopQB", "QB", 90),
            _agg("TopWR", "WR", 85),
            _agg("TopRB", "RB", 80),
        ]
        out = compute_team_strength(
            teams,
            aggregated_players=agg,
            starter_slots=["QB", "WR", "RB"],
        )
        self.assertEqual(len(out), 1)
        team = out[0]
        # Sanity: composite should be a weighted blend, not raw sum.
        starting = team["startingLineupScore"]
        depth = team["benchDepthScore"]
        coverage = team["positionalCoverageScore"]
        health = team["healthAvailabilityScore"]
        expected = 0.72 * starting + 0.18 * depth + 0.05 * coverage + 0.05 * health
        self.assertAlmostEqual(team["teamRosStrength"], round(expected, 2))

    def test_unmapped_players_surface_in_payload(self):
        teams = [
            {
                "ownerId": "o1",
                "rosterId": 1,
                "teamName": "Team Beta",
                "players": [
                    {"playerId": "1", "name": "InAggregate", "position": "QB"},
                    {"playerId": "2", "name": "MissingFromROS", "position": "WR"},
                ],
            }
        ]
        agg = [_agg("InAggregate", "QB", 80)]
        out = compute_team_strength(
            teams,
            aggregated_players=agg,
            starter_slots=["QB", "WR"],
        )
        self.assertEqual(out[0]["unmappedPlayerCount"], 1)
        self.assertIn("MissingFromROS", out[0]["unmappedPlayers"])

    def test_teams_sort_by_strength_desc(self):
        teams = [
            {
                "ownerId": "weak",
                "rosterId": 2,
                "teamName": "Weak",
                "players": [{"playerId": "1", "name": "Low", "position": "QB"}],
            },
            {
                "ownerId": "strong",
                "rosterId": 1,
                "teamName": "Strong",
                "players": [{"playerId": "2", "name": "High", "position": "QB"}],
            },
        ]
        agg = [_agg("Low", "QB", 30), _agg("High", "QB", 90)]
        out = compute_team_strength(teams, aggregated_players=agg, starter_slots=["QB"])
        self.assertEqual(out[0]["teamName"], "Strong")
        self.assertEqual(out[0]["rank"], 1)
        self.assertEqual(out[1]["rank"], 2)


if __name__ == "__main__":
    unittest.main()
