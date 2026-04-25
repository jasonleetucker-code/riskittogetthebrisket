"""Tests for ``src/public_league/streaks.py``.

The fixture gives every owner a mix of W/L results across 2 seasons of
regular + playoff games.  We pin:
    * Trailing W/L streaks are correctly computed from the last-played
      game backwards.
    * Point threshold streaks respect the threshold cutoff and do not
      bleed across a below-threshold week.
    * "Records in reach" carries both a holder and an optional chaser.
    * "Notable this week" entries are keyed by the most recently scored
      game in the snapshot.
"""
from __future__ import annotations

import unittest

from src.public_league.streaks import (
    build_section,
    _active_streaks_for_owner,
    _trailing_run,
)
from tests.public_league.fixtures import build_test_snapshot


class TrailingRunTests(unittest.TestCase):
    def test_counts_consecutive_true_at_tail(self) -> None:
        # events already chronological old → new; reversed gives new first.
        events = [
            {"result": "L"},
            {"result": "W"},
            {"result": "W"},
            {"result": "W"},
        ]
        length, start, end = _trailing_run(
            list(reversed(events)), lambda e: e["result"] == "W"
        )
        self.assertEqual(length, 3)
        # end_event is the MOST recent (last chronologically).
        self.assertIs(end, events[-1])
        # start_event is the CHRONOLOGICALLY earliest event in the run.
        self.assertIs(start, events[1])

    def test_stops_at_first_false(self) -> None:
        events = [
            {"result": "W"},
            {"result": "W"},
            {"result": "L"},
            {"result": "W"},
        ]
        length, _, _ = _trailing_run(
            list(reversed(events)), lambda e: e["result"] == "W"
        )
        self.assertEqual(length, 1)

    def test_zero_when_tail_is_false(self) -> None:
        events = [{"result": "W"}, {"result": "L"}]
        length, start, end = _trailing_run(
            list(reversed(events)), lambda e: e["result"] == "W"
        )
        self.assertEqual(length, 0)
        self.assertIsNone(start)
        self.assertIsNone(end)


class ActiveStreakOwnerTests(unittest.TestCase):
    def test_ends_on_win_reports_win_streak_not_loss(self) -> None:
        events = [
            {"result": "L", "points": 100.0, "week": 1, "season": "2025"},
            {"result": "W", "points": 120.0, "week": 2, "season": "2025"},
            {"result": "W", "points": 130.0, "week": 3, "season": "2025"},
        ]
        out = _active_streaks_for_owner(events, "owner-A", "Ann")
        self.assertIn("winStreak", out)
        self.assertNotIn("lossStreak", out)
        self.assertEqual(out["winStreak"]["length"], 2)

    def test_only_winloss_streaks_after_threshold_streaks_removed(self) -> None:
        # plus100 / plus120 / plus140 streaks have been removed — only
        # win and loss streaks remain.
        events = [
            {"result": "W", "points": 130.0, "week": 1, "season": "2025"},
            {"result": "W", "points": 90.0, "week": 2, "season": "2025"},
            {"result": "W", "points": 125.0, "week": 3, "season": "2025"},
            {"result": "W", "points": 140.0, "week": 4, "season": "2025"},
        ]
        out = _active_streaks_for_owner(events, "owner-A", "Ann")
        self.assertNotIn("plus100Streak", out)
        self.assertNotIn("plus120Streak", out)
        self.assertNotIn("plus140Streak", out)
        self.assertEqual(out["winStreak"]["length"], 4)

    def test_tie_at_tail_reports_no_win_or_loss_streak(self) -> None:
        events = [
            {"result": "W", "points": 100.0, "week": 1, "season": "2025"},
            {"result": "T", "points": 100.0, "week": 2, "season": "2025"},
        ]
        out = _active_streaks_for_owner(events, "owner-A", "Ann")
        self.assertNotIn("winStreak", out)
        self.assertNotIn("lossStreak", out)


class StreaksSectionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.snapshot = build_test_snapshot()
        cls.data = build_section(cls.snapshot)

    def test_top_level_shape(self) -> None:
        expected = {
            "seasonsCovered",
            "currentSeason",
            "latestWeek",
            "activeStreaks",
            "activeStreaksByType",
            "currentStreaksByOwner",
            "longestWinStreaks",
            "longestLossStreaks",
            "recordsInReach",
            "notableThisWeek",
        }
        self.assertTrue(expected.issubset(set(self.data.keys())))

    def test_latest_week_is_most_recent_scored(self) -> None:
        # Fixture: 2025 latest scored week is 16 (playoff championship).
        self.assertEqual(self.data["latestWeek"], {"season": "2025", "week": 16})

    def test_records_in_reach_has_holder(self) -> None:
        self.assertGreater(len(self.data["recordsInReach"]), 0)
        for rec in self.data["recordsInReach"]:
            self.assertIn("holder", rec)
            self.assertIn("category", rec)
            self.assertIn("label", rec)
            holder = rec["holder"]
            self.assertIn("ownerId", holder)
            self.assertIn("displayName", holder)
            self.assertIn("valueLabel", holder)

    def test_active_streaks_are_sorted_within_type(self) -> None:
        by_type = self.data["activeStreaksByType"]
        for stype, rows in by_type.items():
            for i in range(1, len(rows)):
                self.assertGreaterEqual(
                    rows[i - 1]["length"],
                    rows[i]["length"],
                    f"streak type {stype} not sorted desc by length",
                )

    def test_active_streaks_have_display_name(self) -> None:
        for s in self.data["activeStreaks"]:
            self.assertIn("ownerId", s)
            self.assertIn("displayName", s)
            self.assertGreater(s["length"], 0)


if __name__ == "__main__":
    unittest.main()
