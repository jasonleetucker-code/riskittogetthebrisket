"""Tests for ``src/public_league/power.py``."""
from __future__ import annotations

import unittest

from src.public_league.power import build_section, _percentile_rank
from tests.public_league.fixtures import build_test_snapshot


class PercentileTests(unittest.TestCase):
    def test_top_scores_one(self) -> None:
        self.assertEqual(_percentile_rank([10.0, 20.0, 30.0], 30.0), 1.0)

    def test_bottom_scores_zero(self) -> None:
        self.assertEqual(_percentile_rank([10.0, 20.0, 30.0], 10.0), 0.0)

    def test_tied_gets_midrank(self) -> None:
        # Value 20 in [10, 20, 20]: 1 below, 1 other tied → (1 + 0.5) / 2 = 0.75
        self.assertAlmostEqual(_percentile_rank([10.0, 20.0, 20.0], 20.0), 0.75, places=3)

    def test_singleton_is_midpoint(self) -> None:
        self.assertEqual(_percentile_rank([50.0], 50.0), 0.5)


class PowerSectionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.snapshot = build_test_snapshot()
        cls.data = build_section(cls.snapshot)

    def test_top_level_shape(self) -> None:
        expected = {
            "seasonsCovered",
            "weeks",
            "seriesByOwner",
            "currentRanking",
            "methodology",
            "weights",
        }
        self.assertTrue(expected.issubset(set(self.data.keys())))

    def test_weeks_are_chronological(self) -> None:
        last_year = 0
        last_week = 0
        for w in self.data["weeks"]:
            try:
                year = int(w["season"])
            except (TypeError, ValueError):
                year = 0
            if year > last_year:
                last_week = 0
            self.assertTrue(
                (year, w["week"]) >= (last_year, last_week),
                f"weeks regress: {w['season']} wk {w['week']} before {last_year} wk {last_week}",
            )
            last_year = year
            last_week = w["week"]

    def test_every_week_ranks_every_owner_exactly_once(self) -> None:
        for w in self.data["weeks"]:
            rankings = w["rankings"]
            owners = [r["ownerId"] for r in rankings]
            self.assertEqual(len(owners), len(set(owners)))
            ranks = sorted(r["rank"] for r in rankings)
            self.assertEqual(ranks, list(range(1, len(owners) + 1)))

    def test_power_is_zero_to_hundred(self) -> None:
        for w in self.data["weeks"]:
            for r in w["rankings"]:
                self.assertGreaterEqual(r["power"], 0.0)
                self.assertLessEqual(r["power"], 100.0)

    def test_current_ranking_matches_last_week(self) -> None:
        if not self.data["weeks"]:
            return
        last = self.data["weeks"][-1]["rankings"]
        self.assertEqual(self.data["currentRanking"], last)

    def test_series_ownerids_match_rankings(self) -> None:
        ranked_owners = {r["ownerId"] for w in self.data["weeks"] for r in w["rankings"]}
        series_owners = {s["ownerId"] for s in self.data["seriesByOwner"]}
        self.assertEqual(ranked_owners, series_owners)

    def test_components_and_record_fields(self) -> None:
        for w in self.data["weeks"]:
            for r in w["rankings"]:
                self.assertIn("components", r)
                c = r["components"]
                for key in (
                    "pointsPerGame",
                    "pointsPerGamePct",
                    "recentAvg",
                    "recentAvgPct",
                    "allPlayWinPctThisWeek",
                ):
                    self.assertIn(key, c)
                self.assertIn("record", r)
                self.assertRegex(r["record"], r"^\d+-\d+$")


if __name__ == "__main__":
    unittest.main()
