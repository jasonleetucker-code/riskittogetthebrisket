"""Recaps and weekly results narrate FINISHED weeks only.

Measured on production 2026-09-24 (Thursday of week 3): the Home tab's Week in
Review read "The week 3 books shut at 24.2 total points across 4 matchups ...
3 of 8 teams finished under 100", a Thursday-night sliver published as a
closed week, with winners declared. ``weekly_recap`` promised "every completed
week" and ``weekly`` declares winners, but both walked every week with a
scored pair. Both now read ``metrics.final_weeks``, which extends the existing
``final_regular_season_weeks`` owner to playoff weeks.
"""

from __future__ import annotations

import unittest

from src.public_league import metrics, weekly, weekly_recap
from src.public_league.identity import build_manager_registry
from src.public_league.snapshot import PublicLeagueSnapshot, SeasonSnapshot

_OWNERS = ["owner-A", "owner-B", "owner-C", "owner-D"]
_USERS = [{"user_id": o, "display_name": o[-1], "metadata": {}} for o in _OWNERS]
_ROSTERS = [
    {"roster_id": i, "owner_id": o, "players": [], "settings": {}}
    for i, o in enumerate(_OWNERS, start=1)
]


def _week(a, b, c, d) -> list[dict]:
    return [
        {"matchup_id": 1, "roster_id": 1, "points": a},
        {"matchup_id": 1, "roster_id": 2, "points": b},
        {"matchup_id": 2, "roster_id": 3, "points": c},
        {"matchup_id": 2, "roster_id": 4, "points": d},
    ]


def _season(matchups_by_week, *, status="in_season", last_scored_leg=None, playoff_week_start=15):
    settings: dict = {"playoff_week_start": playoff_week_start, "playoff_teams": 2}
    if last_scored_leg is not None:
        settings["last_scored_leg"] = last_scored_leg
    league = {
        "league_id": "L1",
        "season": "2026",
        "season_type": "regular",
        "status": status,
        "total_rosters": 4,
        "settings": settings,
    }
    return SeasonSnapshot(
        season="2026",
        league_id="L1",
        league=league,
        users=_USERS,
        rosters=_ROSTERS,
        matchups_by_week=matchups_by_week,
        transactions_by_week={},
        drafts=[],
        draft_picks_by_draft={},
        traded_picks=[],
        winners_bracket=[],
        losers_bracket=[],
    )


def _snapshot(season: SeasonSnapshot) -> PublicLeagueSnapshot:
    return PublicLeagueSnapshot(
        root_league_id="L1",
        generated_at="2026-09-25T00:00:00Z",
        seasons=[season],
        managers=build_manager_registry(
            [{"league": season.league, "users": _USERS, "rosters": _ROSTERS}]
        ),
    )


_FINAL = _week(110.0, 100.0, 120.0, 90.0)
_THURSDAY = _week(18.0, 0.0, 6.2, 0.0)  # live: two partials, two untouched


class FinalWeeksTests(unittest.TestCase):
    def test_a_live_regular_week_is_withheld(self):
        season = _season({1: _FINAL, 2: _FINAL, 3: _THURSDAY}, last_scored_leg=2)
        self.assertEqual(metrics.final_weeks(season), [1, 2])

    def test_regular_weeks_agree_with_the_existing_owner(self):
        season = _season({1: _FINAL, 2: _FINAL, 3: _THURSDAY}, last_scored_leg=2)
        regular = [w for w in metrics.final_weeks(season) if w < season.playoff_week_start]
        self.assertEqual(regular, metrics.final_regular_season_weeks(season))

    def test_a_playoff_week_needs_the_host_clock(self):
        weeks = {1: _FINAL, 15: _week(130.0, 120.0, 111.0, 99.0)}
        self.assertEqual(metrics.final_weeks(_season(weeks, playoff_week_start=15)), [1])
        self.assertEqual(
            metrics.final_weeks(_season(weeks, playoff_week_start=15, last_scored_leg=15)), [1, 15]
        )

    def test_a_complete_season_has_no_live_week(self):
        season = _season({1: _FINAL, 15: _week(130.0, 0.0, 111.0, 99.0)}, status="complete")
        self.assertEqual(metrics.final_weeks(season), [1, 15])

    def test_post_season_status_does_not_finalize_a_live_playoff_week(self):
        # Sleeper reports ``post_season`` while the playoffs are being played.
        season = _season({1: _FINAL, 15: _THURSDAY}, status="post_season", last_scored_leg=14)
        self.assertEqual(metrics.final_weeks(season), [1])


class NarrationTests(unittest.TestCase):
    def setUp(self):
        self.snapshot = _snapshot(_season({1: _FINAL, 2: _FINAL, 3: _THURSDAY}, last_scored_leg=2))

    def test_the_recap_never_closes_the_books_on_a_live_week(self):
        section = weekly_recap.build_section(self.snapshot)
        self.assertEqual(sorted(r["week"] for r in section["weeks"]), [1, 2])
        self.assertEqual(section["latest"]["week"], 2)
        self.assertNotIn("2026:3", section["byKey"])

    def test_weekly_results_declare_no_winner_for_a_live_week(self):
        section = weekly.build_section(self.snapshot)
        self.assertEqual(sorted(w["week"] for w in section["weeks"]), [1, 2])


if __name__ == "__main__":
    unittest.main()
