"""Tests for ``src/public_league/luck.py``.

Walks the fixture league end-to-end and pins the expected-wins /
actual-wins math.  The fixture has 4 owners, 2 seasons, and scored
regular-season weeks 1+2 (2025) and 1+2+3 (2024) — enough to catch
edge cases in the all-play computation and cross-season aggregation.
"""
from __future__ import annotations

import unittest

from src.public_league.luck import build_section, _all_play_week
from tests.public_league.fixtures import build_test_snapshot


class AllPlayPrimitiveTests(unittest.TestCase):
    """Unit-level: the single-week all-play math."""

    def test_strict_ordering(self) -> None:
        scores = [("A", 100.0), ("B", 90.0), ("C", 80.0), ("D", 70.0)]
        out = _all_play_week(scores)
        self.assertEqual(out["A"]["beats"], 3)
        self.assertEqual(out["A"]["ties"], 0)
        self.assertEqual(out["A"]["rivals"], 3)
        self.assertEqual(out["A"]["expectedShare"], 1.0)
        self.assertEqual(out["D"]["beats"], 0)
        self.assertEqual(out["D"]["expectedShare"], 0.0)

    def test_tie_splits_half(self) -> None:
        scores = [("A", 100.0), ("B", 100.0), ("C", 50.0)]
        out = _all_play_week(scores)
        # A and B tie, both beat C.
        self.assertEqual(out["A"]["beats"], 1)
        self.assertEqual(out["A"]["ties"], 1)
        self.assertAlmostEqual(out["A"]["expectedShare"], (1 + 0.5) / 2, places=6)
        self.assertEqual(out["C"]["beats"], 0)
        self.assertEqual(out["C"]["ties"], 0)

    def test_single_entry_returns_empty(self) -> None:
        self.assertEqual(_all_play_week([("A", 120.0)]), {})
        self.assertEqual(_all_play_week([]), {})


class LuckSectionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.snapshot = build_test_snapshot()
        cls.data = build_section(cls.snapshot)

    def test_top_level_shape(self) -> None:
        expected_keys = {
            "seasonsCovered",
            "currentSeason",
            "byOwnerCareer",
            "byOwnerSeason",
            "currentSeasonRanked",
            "weeklyTrail",
            "luckiestCareer",
            "unluckiestCareer",
            "luckiestCurrent",
            "unluckiestCurrent",
            "methodology",
        }
        self.assertTrue(expected_keys.issubset(set(self.data.keys())))

    def test_seasons_covered(self) -> None:
        # Fixture defines 2024 and 2025 (current).
        self.assertEqual(set(self.data["seasonsCovered"]), {"2024", "2025"})
        self.assertEqual(self.data["currentSeason"], "2025")

    def test_career_rows_sum_to_zero(self) -> None:
        # Expected wins and actual wins must sum to the same total across
        # all owners (pigeon-hole).
        total_actual = sum(r["actualWins"] for r in self.data["byOwnerCareer"])
        total_expected = sum(r["expectedWins"] for r in self.data["byOwnerCareer"])
        # 2025: 4 games, 2024: 6 games, total 10 games of W/L.
        self.assertAlmostEqual(total_actual, 10.0, places=1)
        self.assertAlmostEqual(total_expected, 10.0, places=1)

    def test_luckiest_and_unluckiest_career(self) -> None:
        career = self.data["byOwnerCareer"]
        self.assertEqual(career[0]["ownerId"], self.data["luckiestCareer"]["ownerId"])
        self.assertEqual(career[-1]["ownerId"], self.data["unluckiestCareer"]["ownerId"])
        # Luckiest delta must be >= unluckiest delta.
        self.assertGreaterEqual(career[0]["luckDelta"], career[-1]["luckDelta"])

    def test_owner_d_is_lucky_in_2025(self) -> None:
        """In the 2025 fixture, owner-D beats owner-C in wk1 despite D
        being the 3rd-best score → expected share 0.333 but actual 1.0.
        Net D 2025 luck should be around +0.67."""
        rows_2025 = self.data["currentSeasonRanked"]
        by_owner = {r["ownerId"]: r for r in rows_2025}
        self.assertIn("owner-D", by_owner)
        self.assertAlmostEqual(by_owner["owner-D"]["luckDelta"], 0.67, delta=0.05)

    def test_weekly_trail_is_chronological_and_cumulative(self) -> None:
        trail = self.data["weeklyTrail"]
        self.assertGreater(len(trail), 0)
        # Group by owner and check cumulative expected is monotonically
        # non-decreasing and cumGames increments by 1 each step.
        by_owner: dict[str, list] = {}
        for t in trail:
            by_owner.setdefault(t["ownerId"], []).append(t)
        for oid, rows in by_owner.items():
            last_cum_expected = -1.0
            last_games = 0
            for r in rows:
                self.assertGreaterEqual(
                    r["cumExpected"] + 1e-9,
                    last_cum_expected,
                    f"owner={oid} cumExpected regressed",
                )
                self.assertEqual(
                    r["cumGames"], last_games + 1, f"owner={oid} cumGames non-monotonic"
                )
                last_cum_expected = r["cumExpected"]
                last_games = r["cumGames"]

    def test_playoffs_excluded(self) -> None:
        """Playoff weeks must not appear in the luck trail or aggregates.
        Fixture has weeks 15 and 16 scored in 2025 playoffs; check neither
        bleeds into luck math."""
        trail_weeks = {(t["season"], t["week"]) for t in self.data["weeklyTrail"]}
        for season in ("2024", "2025"):
            self.assertNotIn((season, 15), trail_weeks)
            self.assertNotIn((season, 16), trail_weeks)

    def test_career_winpct_fields_populated(self) -> None:
        for row in self.data["byOwnerCareer"]:
            self.assertIn("actualWinPct", row)
            self.assertIn("expectedWinPct", row)
            self.assertIn("allPlayWinPct", row)
            self.assertGreaterEqual(row["actualWinPct"], 0.0)
            self.assertLessEqual(row["actualWinPct"], 1.0)
            self.assertGreaterEqual(row["expectedWinPct"], 0.0)
            self.assertLessEqual(row["expectedWinPct"], 1.0)


if __name__ == "__main__":
    unittest.main()
