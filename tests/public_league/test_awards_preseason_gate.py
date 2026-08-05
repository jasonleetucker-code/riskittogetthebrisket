"""A season with no scored play must publish no awards (W19-F004).

Sleeper flips a dynasty league to ``in_season`` months before NFL week 1.
The live 2026 block published eight awards off that state — "Points King:
Jason, 0.0 PF", "Regular-Season Crown: Jason, 0-0", "League MVP: Justin
Jefferson, 0.0 VORP" — six of eight to one manager purely because an
all-zero sort has no tiebreak.
"""

from __future__ import annotations

import copy
import unittest

from src.public_league import awards
from tests.public_league.fixtures import build_test_snapshot


def _unplayed_copy(season):
    """Shape a season copy like Sleeper's preseason payload.

    Matchup rows exist with points 0.0 and a players_points map of zeros;
    every roster settings record is 0-0 with 0.0 points for.
    """
    unplayed = copy.deepcopy(season)
    unplayed.season = str(int(season.season) + 1)
    unplayed.league = dict(unplayed.league, status="in_season", season=unplayed.season)
    players_by_roster = {
        int(r["roster_id"]): list(r.get("players") or []) for r in unplayed.rosters
    }
    for entries in unplayed.matchups_by_week.values():
        for m in entries:
            m["points"] = 0.0
            m["custom_points"] = None
            roster_players = players_by_roster.get(int(m["roster_id"]), [])
            # Sleeper publishes the map for the upcoming season, all zeros.
            m["players"] = roster_players
            m["starters"] = roster_players[:4]
            m["players_points"] = {pid: 0.0 for pid in roster_players}
            m["starters_points"] = [0.0 for _ in roster_players[:4]]
    for roster in unplayed.rosters:
        settings = roster.setdefault("settings", {})
        settings.update(
            wins=0,
            losses=0,
            ties=0,
            fpts=0,
            fpts_decimal=0,
            fpts_against=0,
            fpts_against_decimal=0,
        )
    return unplayed


class PreseasonAwardGateTest(unittest.TestCase):
    """The gate is on scored play, never on league status or row presence."""

    @classmethod
    def setUpClass(cls):
        snapshot = build_test_snapshot()
        cls.newest = snapshot.seasons[0]
        cls.unplayed = _unplayed_copy(cls.newest)
        # bySeason is newest-first, so the unplayed season leads.
        snapshot.seasons = [cls.unplayed, *snapshot.seasons]
        cls.section = awards.build_section(snapshot)
        cls.blocks = {s["season"]: s for s in cls.section["bySeason"]}

    def test_unplayed_season_publishes_no_awards(self):
        block = self.blocks[self.unplayed.season]
        self.assertEqual(block["awards"], [])
        self.assertEqual(block["finalists"], {})

    def test_unplayed_season_states_why_rather_than_going_silent(self):
        block = self.blocks[self.unplayed.season]
        self.assertEqual(block["weeksScored"], 0)
        self.assertIs(block["hasScoredPlay"], False)
        self.assertEqual(block["awardsSuppressedReason"], "no_scored_games")

    def test_all_zero_player_points_is_not_player_scoring(self):
        # players_points exists for every roster-week and is entirely zeros.
        self.assertTrue(
            any(
                isinstance(m.get("players_points"), dict) and m["players_points"]
                for entries in self.unplayed.matchups_by_week.values()
                for m in entries
            )
        )
        self.assertIs(self.blocks[self.unplayed.season]["hasPlayerScoring"], False)

    def test_played_season_is_untouched(self):
        block = self.blocks[self.newest.season]
        self.assertGreater(len(block["awards"]), 0)
        self.assertGreater(block["weeksScored"], 0)
        self.assertIs(block["hasScoredPlay"], True)
        self.assertIsNone(block["awardsSuppressedReason"])

    def test_award_history_counts_only_seasons_with_play(self):
        # The rendered "N yrs" badge is len(historyByKey[key]); an unplayed
        # season must not inflate it.
        seasons_with_points_king = [
            s["season"]
            for s in self.section["bySeason"]
            if any(a["key"] == "points_king" for a in s["awards"])
        ]
        self.assertNotIn(self.unplayed.season, seasons_with_points_king)

    def test_unplayed_season_is_not_featured_and_runs_no_races(self):
        self.assertNotEqual(self.section["featuredSeason"], self.unplayed.season)
        self.assertEqual(self.section["upcomingSeason"], self.unplayed.season)

    def test_races_are_empty_when_the_featured_season_has_no_play(self):
        # Featured falls back to the newest season when NO season has begun.
        snapshot = build_test_snapshot()
        snapshot.seasons = [_unplayed_copy(snapshot.seasons[0])]
        section = awards.build_section(snapshot)
        self.assertEqual(section["awardRaces"], [])
        self.assertIsNone(section["hottestRace"])
        self.assertEqual(section["bySeason"][0]["awards"], [])


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
