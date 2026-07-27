"""Schedule → per-team ROS weeks: byes, playoff weeks, REG filtering."""

from __future__ import annotations

import unittest

from src.bdvm.ros import ros_value
from src.bdvm.schedule import team_weeks_from_schedule


def game(week, home, away, game_type="REG"):
    return {"week": week, "home_team": home, "away_team": away, "game_type": game_type}


class TestTeamWeeks(unittest.TestCase):
    def test_byes_and_playoffs_marked(self):
        rows = [game(w, "AAA", "BBB") for w in range(1, 19) if w not in (7, 12)]
        rows.append(game(7, "CCC", "DDD"))  # AAA/BBB on bye week 7 and 12
        weeks = team_weeks_from_schedule(rows, playoff_weeks=(15, 16, 17))
        aaa = weeks["AAA"]
        self.assertEqual(len(aaa), 18)
        byes = [w.week for w in aaa if w.is_bye]
        self.assertEqual(byes, [7, 12])
        playoffs = [w.week for w in aaa if w.is_league_playoff]
        self.assertEqual(playoffs, [15, 16, 17])

    def test_postseason_rows_ignored(self):
        rows = [game(1, "AAA", "BBB"), game(19, "AAA", "BBB", game_type="POST")]
        weeks = team_weeks_from_schedule(rows, max_week=18)
        self.assertEqual(len(weeks["AAA"]), 18)
        self.assertFalse(weeks["AAA"][0].is_bye)

    def test_ros_value_respects_byes_and_playoff_weight(self):
        rows = [game(w, "AAA", "BBB") for w in range(1, 19) if w != 9]
        weeks = team_weeks_from_schedule(rows, playoff_weeks=(15, 16, 17))["AAA"]
        base = ros_value(12.0, 4.0, 7.0, weeks, playoff_weight=0.0)
        weighted = ros_value(12.0, 4.0, 7.0, weeks, playoff_weight=0.35)
        # 17 playable weeks (18 minus one bye)
        per_game = base / 17.0
        self.assertAlmostEqual(weighted - base, 3 * 0.35 * per_game, places=6)


if __name__ == "__main__":
    unittest.main()
