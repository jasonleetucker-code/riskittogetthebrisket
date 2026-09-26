"""Only a DECIDED championship names a champion.

Measured 2026-09-26 on the live snapshot: the 2026 league (in season, week 3,
winners bracket unplayed) carried ``metadata.latest_league_winner_roster_id =
2`` -- Sleeper copies LAST season's champion onto the next season's league
object.  ``season_champion`` fell back to it, so the awards page published the
2025 champion as the 2026 Champion and his franchise shelf read "Champion x2".
"""

from __future__ import annotations

import unittest

from src.public_league import awards, metrics
from src.public_league.identity import build_manager_registry
from src.public_league.snapshot import PublicLeagueSnapshot, SeasonSnapshot

_OWNERS = ["owner-A", "owner-B", "owner-C", "owner-D"]
_USERS = [{"user_id": o, "display_name": o[-1], "metadata": {}} for o in _OWNERS]
_ROSTERS = [
    {"roster_id": i, "owner_id": o, "players": [], "settings": {"wins": 1}}
    for i, o in enumerate(_OWNERS, start=1)
]

# Semifinals decided, 3rd-place game decided, final NOT played yet.
_BRACKET_FINAL_UNPLAYED = [
    {"r": 1, "m": 1, "t1": 1, "t2": 4, "w": 1, "l": 4},
    {"r": 1, "m": 2, "t1": 2, "t2": 3, "w": 2, "l": 3},
    {"r": 2, "m": 3, "t1": 1, "t2": 2, "w": None, "l": None, "p": 1},
    {"r": 2, "m": 4, "t1": 4, "t2": 3, "w": 3, "l": 4, "p": 3},
]
_BRACKET_DECIDED = [
    {"r": 1, "m": 1, "t1": 1, "t2": 4, "w": 1, "l": 4},
    {"r": 1, "m": 2, "t1": 2, "t2": 3, "w": 2, "l": 3},
    {"r": 2, "m": 3, "t1": 1, "t2": 2, "w": 1, "l": 2, "p": 1},
    {"r": 2, "m": 4, "t1": 4, "t2": 3, "w": 3, "l": 4, "p": 3},
]


def _season(status: str, bracket: list[dict], metadata_winner: int | None = 2) -> SeasonSnapshot:
    league = {
        "league_id": "L1",
        "season": "2026",
        "status": status,
        "total_rosters": 4,
        "settings": {"playoff_week_start": 15, "last_scored_leg": 3},
        "metadata": (
            {"latest_league_winner_roster_id": str(metadata_winner)}
            if metadata_winner is not None
            else {}
        ),
    }
    week = [
        {"matchup_id": 1, "roster_id": 1, "points": 110.0},
        {"matchup_id": 1, "roster_id": 2, "points": 100.0},
        {"matchup_id": 2, "roster_id": 3, "points": 120.0},
        {"matchup_id": 2, "roster_id": 4, "points": 90.0},
    ]
    return SeasonSnapshot(
        season="2026",
        league_id="L1",
        league=league,
        users=_USERS,
        rosters=_ROSTERS,
        matchups_by_week={1: week},
        transactions_by_week={},
        drafts=[],
        draft_picks_by_draft={},
        traded_picks=[],
        winners_bracket=bracket,
        losers_bracket=[],
    )


def _snapshot(season: SeasonSnapshot) -> PublicLeagueSnapshot:
    return PublicLeagueSnapshot(
        root_league_id="L1",
        generated_at="2026-09-26T00:00:00Z",
        seasons=[season],
        managers=build_manager_registry(
            [{"league": season.league, "users": _USERS, "rosters": _ROSTERS}]
        ),
    )


class SeasonChampionTests(unittest.TestCase):
    def test_in_progress_season_carrying_last_years_winner_has_no_champion(self):
        # The live 2026 shape: bracket seeded but unplayed, stale metadata.
        season = _season("in_season", [dict(m, w=None, l=None) for m in _BRACKET_DECIDED])
        self.assertIsNone(metrics.season_champion(season))

    def test_post_season_with_unplayed_final_has_no_champion(self):
        # ``post_season`` = playoffs being played; the metadata is last year's.
        self.assertIsNone(metrics.season_champion(_season("post_season", _BRACKET_FINAL_UNPLAYED)))

    def test_a_decided_third_place_game_never_crowns_a_champion(self):
        # The old "minimum placement" fallback returned roster 3 (place 3).
        season = _season("post_season", _BRACKET_FINAL_UNPLAYED, metadata_winner=None)
        self.assertIsNone(metrics.season_champion(season))

    def test_decided_final_names_its_winner(self):
        self.assertEqual(metrics.season_champion(_season("post_season", _BRACKET_DECIDED)), 1)

    def test_complete_season_without_a_bracket_keeps_the_metadata_answer(self):
        self.assertEqual(metrics.season_champion(_season("complete", [])), 2)

    def test_in_progress_awards_publish_no_champion(self):
        section = awards.build_section(
            _snapshot(_season("in_season", [dict(m, w=None, l=None) for m in _BRACKET_DECIDED]))
        )
        keys = [a["key"] for a in section["bySeason"][0]["awards"]]
        self.assertNotIn("champion", keys)
        self.assertNotIn("playoff_mvp", keys)


if __name__ == "__main__":
    unittest.main()
