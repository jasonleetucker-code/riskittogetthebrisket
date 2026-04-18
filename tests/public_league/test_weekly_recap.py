"""Tests for ``src/public_league/weekly_recap.py``."""
from __future__ import annotations

import unittest

from src.public_league.weekly_recap import build_section
from tests.public_league.fixtures import build_test_snapshot


class WeeklyRecapSectionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.snapshot = build_test_snapshot()
        cls.data = build_section(cls.snapshot)

    def test_top_level_shape(self) -> None:
        for key in ("seasonsCovered", "weeks", "byKey", "latest"):
            self.assertIn(key, self.data)

    def test_every_recap_has_required_fields(self) -> None:
        for recap in self.data["weeks"]:
            for key in (
                "season",
                "week",
                "isPlayoff",
                "matchups",
                "mvp",
                "bust",
                "blowout",
                "nailBiter",
                "badBeat",
                "trades",
                "headline",
                "summary",
            ):
                self.assertIn(key, recap, f"missing {key} in recap {recap.get('season')}:{recap.get('week')}")
            self.assertIsInstance(recap["headline"], str)
            self.assertTrue(recap["headline"])
            self.assertIsInstance(recap["summary"], str)
            self.assertTrue(recap["summary"])

    def test_week_2_of_2025_has_expected_superlatives(self) -> None:
        # Fixture: 2025 wk2 → A 145.8 beats C 142.1 (close), B 165.0 beats D 95.6 (blowout).
        recap = self.data["byKey"]["2025:2"]
        self.assertIsNotNone(recap)
        # MVP: highest scorer is owner-B at 165.0.
        self.assertEqual(recap["mvp"]["ownerId"], "owner-B")
        self.assertEqual(recap["mvp"]["points"], 165.0)
        # Bust: lowest scorer is owner-D at 95.6.
        self.assertEqual(recap["bust"]["ownerId"], "owner-D")
        self.assertEqual(recap["bust"]["points"], 95.6)
        # Blowout: B beats D by 69.4.
        self.assertEqual(recap["blowout"]["margin"], 69.4)
        self.assertEqual(recap["blowout"]["winner"]["ownerId"], "owner-B")
        # Nailbiter: A beats C by 3.7.
        self.assertEqual(recap["nailBiter"]["margin"], 3.7)
        self.assertEqual(recap["nailBiter"]["winner"]["ownerId"], "owner-A")

    def test_bykey_maps_every_week(self) -> None:
        for recap in self.data["weeks"]:
            key = f"{recap['season']}:{recap['week']}"
            self.assertIn(key, self.data["byKey"])
            self.assertIs(self.data["byKey"][key], recap)

    def test_weeks_sorted_newest_first(self) -> None:
        weeks = self.data["weeks"]
        for i in range(1, len(weeks)):
            prev = weeks[i - 1]
            cur = weeks[i]
            self.assertTrue(
                (int(prev["season"]), prev["week"]) >= (int(cur["season"]), cur["week"]),
                f"weeks not newest-first: {prev['season']}:{prev['week']} vs {cur['season']}:{cur['week']}",
            )

    def test_latest_matches_first_weeks_entry(self) -> None:
        self.assertEqual(self.data["latest"], self.data["weeks"][0])

    def test_matchup_oneliners_populated(self) -> None:
        for recap in self.data["weeks"]:
            for m in recap["matchups"]:
                self.assertIsInstance(m["oneliner"], str)
                self.assertTrue(m["oneliner"])


if __name__ == "__main__":
    unittest.main()
