"""An in-progress week contributes NOTHING to finished-week surfaces.

Measured on the live snapshot 2026-09-26 (Friday of week 3; 7 of 12 teams had
scored, 240 of 252 starter slots were 0.0 stubs): the awards page named Bijan
Robinson League MVP on a Thursday-night game, posted Roy's 16.7-point sliver as
the season's "Lowest single week", and the record book ranked that sliver the
1st-lowest single-week score all-time.

The contract pinned here: every surface that claims a FINISHED result reads
``metrics.final_weeks`` (the one canonical definition), so a snapshot taken
mid-week produces exactly what the same league produced once the previous week
closed -- the live week is absent, never partially counted.
"""

from __future__ import annotations

import copy
import unittest

from src.public_league import awards, matchup_preview, metrics, records, rivalries, streaks
from src.public_league.identity import build_manager_registry
from src.public_league.snapshot import PublicLeagueSnapshot, SeasonSnapshot

_OWNERS = ["owner-A", "owner-B", "owner-C", "owner-D"]
_USERS = [{"user_id": o, "display_name": o[-1], "metadata": {}} for o in _OWNERS]
# Roster i holds QB "q{i}", RB "r{i}", DL "d{i}".
_ROSTERS = [
    {
        "roster_id": i,
        "owner_id": o,
        "players": [f"q{i}", f"r{i}", f"d{i}"],
        "settings": {"wins": 1, "losses": 1, "fpts": 200},
    }
    for i, o in enumerate(_OWNERS, start=1)
]
NFL_PLAYERS = {
    f"{p}{i}": {
        "full_name": f"{p.upper()} Player {i}",
        "position": pos,
        "fantasy_positions": [pos],
        "team": "BUF",
        "years_exp": 3,
    }
    for i in range(1, 5)
    for p, pos in (("q", "QB"), ("r", "RB"), ("d", "DL"))
}


def _entry(mid: int, rid: int, q: float, r: float, d: float) -> dict:
    return {
        "matchup_id": mid,
        "roster_id": rid,
        "points": round(q + r + d, 2),
        "starters": [f"q{rid}", f"r{rid}", f"d{rid}"],
        "players_points": {f"q{rid}": q, f"r{rid}": r, f"d{rid}": d},
    }


# Two FINISHED weeks.  1 v 2 and 3 v 4 both weeks.
WEEK_1 = [
    _entry(1, 1, 25.0, 18.0, 9.0),  # 52
    _entry(1, 2, 20.0, 15.0, 8.0),  # 43
    _entry(2, 3, 30.0, 12.0, 11.0),  # 53
    _entry(2, 4, 22.0, 20.0, 7.0),  # 49
]
WEEK_2 = [
    _entry(1, 1, 21.0, 16.0, 6.0),  # 43
    _entry(1, 2, 24.0, 19.0, 10.0),  # 53
    _entry(2, 3, 28.0, 14.0, 12.0),  # 54
    _entry(2, 4, 19.0, 17.0, 8.0),  # 44
]
# The live week: roster 1's RB had a monster Thursday, roster 2 has not
# kicked off (literal 0.0 stubs), roster 3 posted a sliver, roster 4 nothing.
WEEK_3_LIVE = [
    _entry(1, 1, 0.0, 44.79, 0.0),
    _entry(1, 2, 0.0, 0.0, 0.0),
    _entry(2, 3, 0.0, 0.0, 6.2),
    _entry(2, 4, 0.0, 0.0, 0.0),
]


def season_with(weeks: dict[int, list[dict]], *, last_scored_leg: int = 2) -> SeasonSnapshot:
    league = {
        "league_id": "L1",
        "season": "2026",
        "season_type": "regular",
        "status": "in_season",
        "total_rosters": 4,
        "roster_positions": ["QB", "RB", "DL", "BN"],
        "settings": {
            "playoff_week_start": 15,
            "playoff_teams": 2,
            "last_scored_leg": last_scored_leg,
        },
        # Sleeper carries LAST season's champion forward -- must stay unused.
        "metadata": {"latest_league_winner_roster_id": "2"},
    }
    return SeasonSnapshot(
        season="2026",
        league_id="L1",
        league=league,
        users=_USERS,
        rosters=_ROSTERS,
        matchups_by_week=copy.deepcopy(weeks),
        transactions_by_week={},
        drafts=[],
        draft_picks_by_draft={},
        traded_picks=[],
        winners_bracket=[],
        losers_bracket=[],
    )


def snapshot_of(season: SeasonSnapshot) -> PublicLeagueSnapshot:
    return PublicLeagueSnapshot(
        root_league_id="L1",
        generated_at="2026-09-26T00:00:00Z",
        seasons=[season],
        managers=build_manager_registry(
            [{"league": season.league, "users": _USERS, "rosters": _ROSTERS}]
        ),
        nfl_players=copy.deepcopy(NFL_PLAYERS),
    )


def post_week_snapshot() -> PublicLeagueSnapshot:
    """The league as it stood when week 2 closed (week 3 not yet started)."""
    return snapshot_of(season_with({1: WEEK_1, 2: WEEK_2}))


def mid_week_snapshot() -> PublicLeagueSnapshot:
    """The same league on Friday of week 3."""
    return snapshot_of(season_with({1: WEEK_1, 2: WEEK_2, 3: WEEK_3_LIVE}))


class AwardsIgnoreTheLiveWeekTests(unittest.TestCase):
    def setUp(self):
        self.mid = awards.build_section(mid_week_snapshot())
        self.post = awards.build_section(post_week_snapshot())

    def test_mid_week_awards_equal_the_post_week_board(self):
        self.assertEqual(self.mid, self.post)

    def _award(self, key):
        row = self.mid["bySeason"][0]
        return next((a for a in row["awards"] if a["key"] == key), None)

    def test_a_thursday_sliver_is_not_the_lowest_single_week(self):
        low = self._award("lowest_single_week")
        self.assertEqual(low["value"]["week"], 1)
        self.assertEqual(low["value"]["points"], 43.0)

    def test_a_thursday_explosion_does_not_crown_the_mvp(self):
        # r1's 44.79 live points would otherwise lead every RB/VORP board.
        mvp = self._award("league_mvp")
        self.assertNotEqual(mvp["value"]["playerId"], "r1")
        self.assertEqual(mvp["value"]["gamesStarted"], 2)
        self.assertEqual(mvp["value"]["asOfWeek"], 2)
        top_rb = self._award("top_rb")
        self.assertEqual(top_rb["value"]["playerId"], "r4")
        self.assertEqual(top_rb["value"]["starterPoints"], 37.0)

    def test_weekly_hammer_counts_only_finished_weeks(self):
        hammer = self.mid["bySeason"][0]["finalists"]["weekly_hammer"]
        finishes = {r["ownerId"]: r["value"]["highScoreFinishes"] for r in hammer}
        # Week 1 top: C (53); week 2 top: C (54).  A's live 44.79 earns nothing.
        self.assertEqual(finishes.get("owner-C"), 2)
        self.assertNotIn("owner-A", {k for k, v in finishes.items() if v})

    def test_no_champion_from_last_seasons_metadata(self):
        self.assertIsNone(self._award("champion"))


class RecordBookIgnoresTheLiveWeekTests(unittest.TestCase):
    def test_records_equal_the_post_week_book(self):
        mid = records.build_section(mid_week_snapshot())
        self.assertEqual(mid, records.build_section(post_week_snapshot()))
        # The 6.2-point sliver is not the lowest single week ever.
        self.assertEqual(mid["singleWeekLowest"][0]["points"], 43.0)
        self.assertTrue(all(r["week"] != 3 for r in mid["singleWeekLowest"]))

    def test_streaks_equal_the_post_week_streaks(self):
        mid = streaks.build_section(mid_week_snapshot())
        self.assertEqual(mid, streaks.build_section(post_week_snapshot()))
        self.assertEqual(mid["latestWeek"], {"season": "2026", "week": 2})
        # Nothing from the live week can be "notable this week".
        self.assertTrue(all(n["week"] != 3 for n in mid["notableThisWeek"]))

    def test_rivalries_equal_the_post_week_rivalries(self):
        mid = rivalries.build_section(mid_week_snapshot())
        self.assertEqual(mid, rivalries.build_section(post_week_snapshot()))
        for rec in mid["rivalries"]:
            self.assertEqual(rec["totalMeetings"], 2)


class PreviewHistoryIgnoresTheLiveWeekTests(unittest.TestCase):
    def test_h2h_history_equals_the_post_week_history(self):
        self.assertEqual(
            matchup_preview._build_h2h_index(mid_week_snapshot()),
            matchup_preview._build_h2h_index(post_week_snapshot()),
        )

    def test_live_week_is_previewed_and_never_the_most_recent_meeting(self):
        section = matchup_preview.build_section(mid_week_snapshot())
        self.assertEqual((section["mode"], section["currentWeek"]), ("preview", 3))
        for m in section["matchups"]:
            self.assertEqual(m["h2h"]["totalMeetings"], 2)
            self.assertEqual(m["h2h"]["lastMeeting"]["week"], 2)
            self.assertNotIn("wk 3", m["h2h"]["narrative"])
            self.assertIsNone(m["home"]["points"])


class CombinedFinalTests(unittest.TestCase):
    """A two-week final is undecided until its SECOND leg is final."""

    def _snap(self, last_scored_leg):
        weeks = {
            1: WEEK_1,
            15: [_entry(1, 1, 30.0, 20.0, 10.0), _entry(1, 2, 25.0, 20.0, 10.0)],
            16: [_entry(1, 1, 5.0, 0.0, 0.0), _entry(1, 2, 0.0, 0.0, 0.0)],
        }
        season = season_with(weeks, last_scored_leg=last_scored_leg)
        season.league["settings"]["playoff_week_start"] = 15
        return snapshot_of(season)

    def test_first_leg_alone_emits_no_pair(self):
        pairs = list(metrics.walk_matchup_pairs(self._snap(15)))
        self.assertEqual([wk for _s, wk, *_rest in pairs if wk >= 15], [])

    def test_both_legs_final_emit_one_combined_pair(self):
        pairs = [p for p in metrics.walk_matchup_pairs(self._snap(16)) if p[1] >= 15]
        self.assertEqual(len(pairs), 1)
        self.assertEqual(pairs[0][2]["_combinedWeeks"], [15, 16])


if __name__ == "__main__":
    unittest.main()
