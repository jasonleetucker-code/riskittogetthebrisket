"""Tests for ``src/public_league/weekly_recap.py``."""
from __future__ import annotations

import unittest

from src.public_league.weekly_recap import _weekly_trades_for, build_section
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

    def test_weekly_trades_counts_assets_when_leg_matches_week(self) -> None:
        # Regression: previously a `(adds or {}, {}).values()` typo raised
        # AttributeError whenever a completed trade's leg matched a scored
        # week.  The test fixture's trade legs don't overlap scored weeks,
        # so the bug never surfaced in unit tests — only in production.
        season = next(s for s in self.snapshot.seasons if s.season == "2025")
        fake_tx = {
            "transaction_id": "tx-regression",
            "type": "trade",
            "status": "complete",
            "leg": 2,
            "roster_ids": [1, 2],
            "adds": {"p-rb2": 1, "p-wr2": 2},
            "drops": {"p-rb2": 2, "p-wr2": 1},
        }
        original_trades = season.trades

        def patched_trades() -> list:
            return [*original_trades(), fake_tx]

        season.trades = patched_trades  # type: ignore[method-assign]
        try:
            out = _weekly_trades_for(season, self.snapshot, 2)
        finally:
            season.trades = original_trades  # type: ignore[method-assign]
        match = next((row for row in out if row["transactionId"] == "tx-regression"), None)
        self.assertIsNotNone(match)
        self.assertEqual(match["assetsMoved"], 2)


if __name__ == "__main__":
    unittest.main()
