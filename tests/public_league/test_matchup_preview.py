"""Tests for ``src/public_league/matchup_preview.py``.

The fixture's 2025 season is fully scored through week 16, so
``matchup_preview`` should fall back to "recap" mode on the most
recently scored week.  We also test the preview path by manually
unscoring a matchup row.
"""
from __future__ import annotations

import copy
import unittest

from src.public_league.matchup_preview import build_section, _detect_current_week, _pair_key
from tests.public_league.fixtures import build_test_snapshot


class PairKeyTests(unittest.TestCase):
    def test_canonical_ordering(self) -> None:
        self.assertEqual(_pair_key("owner-B", "owner-A"), ("owner-A", "owner-B"))
        self.assertEqual(_pair_key("owner-A", "owner-B"), ("owner-A", "owner-B"))


class MatchupPreviewSectionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.snapshot = build_test_snapshot()
        cls.data = build_section(cls.snapshot)

    def test_top_level_shape(self) -> None:
        for key in ("currentSeason", "currentWeek", "mode", "matchups", "generatedAt"):
            self.assertIn(key, self.data)

    def test_fully_complete_season_falls_back_to_recap(self) -> None:
        # Fixture's 2025 is complete → mode should be "recap" and the
        # current week should be the most recent scored one (16).
        self.assertEqual(self.data["mode"], "recap")
        self.assertEqual(self.data["currentWeek"], 16)
        self.assertEqual(self.data["currentSeason"], "2025")

    def test_matchups_have_h2h_and_form(self) -> None:
        self.assertGreater(len(self.data["matchups"]), 0)
        for m in self.data["matchups"]:
            self.assertIn("home", m)
            self.assertIn("away", m)
            self.assertIn("h2h", m)
            self.assertIn("form", m)
            h2h = m["h2h"]
            self.assertIn("totalMeetings", h2h)
            self.assertIn("last5", h2h)
            self.assertIn("narrative", h2h)
            self.assertGreaterEqual(h2h["totalMeetings"], 0)
            self.assertLessEqual(len(h2h["last5"]), 5)
            self.assertIn("home", m["form"])
            self.assertIn("away", m["form"])
            self.assertIn("avgPoints", m["form"]["home"])
            self.assertIn("record", m["form"]["home"])

    def test_recap_points_populated(self) -> None:
        # In recap mode, both sides must have a numeric points field.
        for m in self.data["matchups"]:
            self.assertIsNotNone(m["home"]["points"])
            self.assertIsNotNone(m["away"]["points"])


class PreviewModeTests(unittest.TestCase):
    """Force a preview path by unscoring an existing matchup row."""

    def test_unscored_week_triggers_preview(self) -> None:
        snap = build_test_snapshot()
        # Clone and zero-out week 16 scores in the current season.
        current = snap.seasons[0]
        current.matchups_by_week[16] = [
            {**row, "points": 0} for row in current.matchups_by_week[16]
        ]
        # And add a brand-new unplayed week 17.
        current.matchups_by_week[17] = [
            {"matchup_id": 1, "roster_id": 1, "points": 0},
            {"matchup_id": 1, "roster_id": 2, "points": 0},
            {"matchup_id": 2, "roster_id": 3, "points": 0},
            {"matchup_id": 2, "roster_id": 4, "points": 0},
        ]
        data = build_section(snap)
        self.assertEqual(data["mode"], "preview")
        # Preview mode should target the earliest unscored week in the
        # season's walk; with week 16 now unscored, that's week 16.
        self.assertIn(data["currentWeek"], (16, 17))
        # Preview mode exposes null points, not zero.
        for m in data["matchups"]:
            self.assertIsNone(m["home"]["points"])
            self.assertIsNone(m["away"]["points"])


if __name__ == "__main__":
    unittest.main()
