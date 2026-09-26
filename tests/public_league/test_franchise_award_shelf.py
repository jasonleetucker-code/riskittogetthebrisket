"""A franchise's award shelf lists awards WON, i.e. finalized seasons only.

Measured 2026-09-26: two weeks into 2026, franchise pages listed current race
LEADERS as awards won ("Top DB 2026"), and -- via the stale champion fallback
-- "Champion x2".
"""

from __future__ import annotations

import unittest

from src.public_league import franchise
from tests.public_league.test_in_progress_week_excluded import mid_week_snapshot


def _row(season: str, status: str, owner: str) -> dict:
    return {
        "season": season,
        "seasonStatus": status,
        "isComplete": status in ("complete", "post_season"),
        "awards": [
            {"key": "top_db", "label": "Top DB", "ownerId": owner},
            {"key": "champion", "label": "Champion", "ownerId": owner},
        ],
    }


class AwardShelfTests(unittest.TestCase):
    def test_only_complete_seasons_reach_the_shelf(self):
        section = {
            "bySeason": [
                _row("2026", "in_season", "owner-A"),
                _row("2025", "post_season", "owner-A"),  # playoffs still running
                _row("2024", "complete", "owner-A"),
            ]
        }
        shelf = franchise._awards_won_by_owner(section)["owner-A"]
        self.assertEqual(
            {r["key"]: r["seasons"] for r in shelf}, {"top_db": ["2024"], "champion": ["2024"]}
        )
        self.assertTrue(all(r["count"] == 1 for r in shelf))

    def test_an_in_progress_season_leaves_every_shelf_empty(self):
        section = franchise.build_section(mid_week_snapshot())
        for owner_id, detail in section["detail"].items():
            self.assertEqual(detail["awardsWon"], [], owner_id)


if __name__ == "__main__":
    unittest.main()
