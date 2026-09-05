"""Tests for ``src/public_league/matchup_preview.py``.

The fixture's 2025 season is fully scored through week 16, so
``matchup_preview`` should fall back to "recap" mode on the most
recently scored week.  We also test the preview path by manually
unscoring a matchup row.
"""

from __future__ import annotations

import unittest

from src.public_league.matchup_preview import (
    build_section,
    _h2h_summary,
    _pair_key,
    _recent_form_for_owner,
)
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


class RecentFormSeasonLabellingTests(unittest.TestCase):
    """Week 1's recent-form window lies entirely in the PREVIOUS season.

    The per-game rows always carried their own ``season``; the
    aggregates did not, so ``record`` / ``avgPoints`` read as
    current-season form wherever they were shown or summarised. In Week
    1 that is guaranteed wrong — including the championship, which is
    the most quotable game in the window and the most misleading.
    """

    def setUp(self) -> None:
        self.snapshot = build_test_snapshot()
        # Any owner the fixture actually attributes matchups to.
        self.owner = sorted(self.snapshot.managers.by_owner_id)[0]

    def test_a_window_entirely_in_a_prior_season_is_flagged(self) -> None:
        # Week 1 of a season AFTER the fixture's data: every prior game
        # belongs to an earlier season.
        form = _recent_form_for_owner(self.snapshot, self.owner, "2026", 1, n=3)
        self.assertTrue(form["games"], "fixture should supply prior games")
        self.assertTrue(form["isPriorSeasonOnly"])
        self.assertNotIn("2026", form["seasons"])

    def test_a_mid_season_window_is_not_flagged_as_prior(self) -> None:
        form = _recent_form_for_owner(self.snapshot, self.owner, "2025", 16, n=3)
        self.assertTrue(form["games"])
        self.assertFalse(form["isPriorSeasonOnly"])
        self.assertIn("2025", form["seasons"])

    def test_seasons_are_reported_oldest_first(self) -> None:
        form = _recent_form_for_owner(self.snapshot, self.owner, "2026", 1, n=3)
        self.assertEqual(form["seasons"], sorted(form["seasons"]))

    def test_spans_seasons_matches_the_season_count(self) -> None:
        form = _recent_form_for_owner(self.snapshot, self.owner, "2026", 1, n=3)
        self.assertEqual(form["spansSeasons"], len(form["seasons"]) > 1)

    def test_no_prior_games_reports_none_not_zero(self) -> None:
        """MISSING IS NEVER ZERO. A manager with no scored history has
        no measurable form; 0.0 would read as 'averaged zero points'."""
        form = _recent_form_for_owner(self.snapshot, "owner-who-does-not-exist", "2026", 1)
        self.assertEqual(form["games"], [])
        self.assertIsNone(form["avgPoints"])
        self.assertEqual(form["seasons"], [])
        # An empty window is not "prior season only" — it is no evidence.
        self.assertFalse(form["isPriorSeasonOnly"])
        self.assertFalse(form["spansSeasons"])

    def test_a_real_window_still_reports_a_numeric_average(self) -> None:
        form = _recent_form_for_owner(self.snapshot, self.owner, "2025", 16, n=3)
        self.assertIsInstance(form["avgPoints"], float)


class EmptySeriesIsMissingNotZeroTests(unittest.TestCase):
    """A first-ever meeting has NO average margin — it does not have one of zero.

    Two of the six 2026 Week 1 matchups on production are first-ever meetings
    (new managers joined for 2026), and `_h2h_summary` returned
    ``avgMargin: 0.0`` / ``biggestMargin: 0.0`` for them.  That is a missing
    value rendered as a real one, and the reading it invites is the opposite
    of the truth: "average margin 0.0" says these two always play to a dead
    heat.  It is not cosmetic — the block is serialized straight into the
    narrative brief's prompt JSON (`matchup_narrative._build_brief`), so the
    article generator was being handed a fabricated dead-heat series.

    The sibling `_form_summary` already publishes ``avgPoints: None`` for a
    manager with no games, so this is the module's own existing convention
    applied consistently, not a new one.
    """

    def test_no_meetings_yields_none_for_undefined_aggregates(self) -> None:
        summary = _h2h_summary([], "owner-A", "owner-B")
        self.assertEqual(summary["totalMeetings"], 0)
        self.assertIsNone(summary["avgMargin"])
        self.assertIsNone(summary["biggestMargin"])
        self.assertIsNone(summary["biggestMarginWinner"])

    def test_counts_over_an_empty_series_stay_zero(self) -> None:
        # Deliberately NOT promoted to None: these are tallies of things that
        # happened zero times, and sums over an empty set.  They are facts.
        summary = _h2h_summary([], "owner-A", "owner-B")
        for key in (
            "sideAWins",
            "sideBWins",
            "ties",
            "playoffMeetings",
            "sideAPointsTotal",
            "sideBPointsTotal",
        ):
            self.assertEqual(summary[key], 0, key)

    def test_a_real_series_still_reports_numbers(self) -> None:
        meetings = [
            {
                "sideAOwnerId": "owner-A",
                "sideBOwnerId": "owner-B",
                "sideAPoints": 110.0,
                "sideBPoints": 100.0,
                "isPlayoff": False,
            },
            {
                "sideAOwnerId": "owner-A",
                "sideBOwnerId": "owner-B",
                "sideAPoints": 90.0,
                "sideBPoints": 120.0,
                "isPlayoff": True,
            },
        ]
        summary = _h2h_summary(meetings, "owner-A", "owner-B")
        self.assertEqual(summary["totalMeetings"], 2)
        self.assertEqual(summary["avgMargin"], 20.0)
        self.assertEqual(summary["biggestMargin"], 30.0)
        self.assertEqual(summary["biggestMarginWinner"], "owner-B")
        self.assertEqual(summary["playoffMeetings"], 1)

    def test_an_exactly_tied_meeting_has_no_margin_winner(self) -> None:
        # Distinct from the empty case and it must stay distinct: a tie HAS a
        # margin (zero) and no winner; an empty series has neither.
        meetings = [
            {
                "sideAOwnerId": "owner-A",
                "sideBOwnerId": "owner-B",
                "sideAPoints": 100.0,
                "sideBPoints": 100.0,
                "isPlayoff": False,
            }
        ]
        summary = _h2h_summary(meetings, "owner-A", "owner-B")
        self.assertEqual(summary["totalMeetings"], 1)
        self.assertEqual(summary["ties"], 1)
        self.assertEqual(summary["avgMargin"], 0.0)
        self.assertEqual(summary["biggestMargin"], 0.0)
        self.assertIsNone(summary["biggestMarginWinner"])
