"""Regression tests for the phantom future-week VORP defect.

Sleeper pre-generates ``matchup_id`` for the WHOLE season's schedule at
draft time, and stamps every future (not-yet-played) week's matchup
payload with a real-looking but fabricated shape: the roster's CURRENT
starting lineup echoed into ``starters``, and ``players_points`` stubbed
at ``0.0`` for every one of the roster's players (not just starters) —
confirmed live against production Sleeper league 1312006700437352448 on
2026-09-15 (see the investigation that produced this fix).  Neither
``matchup_id`` presence nor ``starters``/``players_points`` presence can
tell a played week from a merely scheduled one.

Before this fix, ``_starter_scoring_walk`` and
``_player_all_rostered_totals`` (``src/public_league/awards.py``) walked
every week present in ``matchups_by_week`` unconditionally, so a player
who happened to still be in their roster's frozen "current lineup" echo
picked up one phantom, zero-point "game" for every future week Sleeper
had already scheduled — while a player NOT in that echo did not.  Two
players at the same position with identical real production could end up
with wildly different ``gamesStarted`` (1 vs. many), which
``replacementPerGame * gamesStarted`` then charged unevenly, producing
internally inconsistent VORP.  This is exactly what happened live:
Greg Rousseau (DL) and Caleb Williams (QB) were still in their rosters'
frozen lineup echo and accumulated 18 counted "games" (1 real + 17
phantom) while T.J. Watt (DL), Josh Allen (QB) and others not in that
echo stayed at 1.

The fixture below reproduces that exact shape (one real week, three
phantom weeks with the same structure Sleeper actually returns) so this
bug class cannot silently regress.
"""

from __future__ import annotations

import unittest

from src.public_league import metrics
from src.public_league.awards import (
    _player_all_rostered_totals,
    _player_starter_totals,
    _starter_scoring_walk,
    _vorp_rows,
)
from src.public_league.identity import build_manager_registry
from src.public_league.snapshot import PublicLeagueSnapshot, SeasonSnapshot


_LEAGUE = {
    "league_id": "PHANTOM-L1",
    "name": "Phantom Week League",
    "season": "2026",
    "season_type": "regular",
    "status": "in_season",
    "total_rosters": 2,
    "settings": {"playoff_week_start": 15},
}
_USERS = [
    {"user_id": "owner-1", "display_name": "Owner One", "metadata": {"team_name": "Team One"}},
    {"user_id": "owner-2", "display_name": "Owner Two", "metadata": {"team_name": "Team Two"}},
]
_ROSTERS = [
    {"roster_id": 1, "owner_id": "owner-1", "players": [], "settings": {}},
    {"roster_id": 2, "owner_id": "owner-2", "players": [], "settings": {}},
]
_NFL_PLAYERS = {
    "allen": {"first_name": "Josh", "last_name": "Allen", "position": "QB"},
    "caleb": {"first_name": "Caleb", "last_name": "Williams", "position": "QB"},
    "watt": {"first_name": "T.J.", "last_name": "Watt", "position": "DL"},
    "rousseau": {"first_name": "Greg", "last_name": "Rousseau", "position": "DL"},
    "kicker_x": {"first_name": "Kick", "last_name": "Erman", "position": "K"},
}

# Real week 1: everyone plays and scores.  roster 1 (Allen/Watt/Kicker)
# is NOT echoed into any future week's starters; roster 2
# (Caleb/Rousseau) IS — reproducing the exact asymmetry observed live.
_WEEK_1_REAL = [
    {
        "matchup_id": 1,
        "roster_id": 1,
        "points": 93.47,
        "players_points": {"allen": 43.49, "watt": 49.97, "kicker_x": 0.0},
        "starters": ["allen", "watt", "kicker_x"],
    },
    {
        "matchup_id": 1,
        "roster_id": 2,
        "points": 91.88,
        "players_points": {"caleb": 46.97, "rousseau": 44.91},
        "starters": ["caleb", "rousseau"],
    },
]


def _phantom_week(week: int) -> list[dict]:
    """One Sleeper future-week placeholder, shaped exactly like the live
    payloads captured during the investigation: matchup_id populated,
    points 0.0, players_points stubbed at 0.0 for the WHOLE roster, and
    roster 2's starters frozen to its current (real) lineup while
    roster 1's is not."""
    return [
        {
            "matchup_id": 100 + week,
            "roster_id": 1,
            "points": 0.0,
            "players_points": {"allen": 0.0, "watt": 0.0, "kicker_x": 0.0},
            "starters": [],
        },
        {
            "matchup_id": 100 + week,
            "roster_id": 2,
            "points": 0.0,
            "players_points": {"caleb": 0.0, "rousseau": 0.0},
            "starters": ["caleb", "rousseau"],
        },
    ]


def _build_snapshot(matchups_by_week: dict[int, list[dict]]) -> PublicLeagueSnapshot:
    season = SeasonSnapshot(
        season="2026",
        league_id="PHANTOM-L1",
        league=_LEAGUE,
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
    return PublicLeagueSnapshot(
        root_league_id="PHANTOM-L1",
        generated_at="2026-09-15T00:00:00Z",
        seasons=[season],
        managers=build_manager_registry(
            [{"league": _LEAGUE, "users": _USERS, "rosters": _ROSTERS}]
        ),
        nfl_players=_NFL_PLAYERS,
    )


def _phantom_snapshot(phantom_weeks: tuple[int, ...] = (2, 3, 4)) -> PublicLeagueSnapshot:
    matchups = {1: _WEEK_1_REAL}
    for wk in phantom_weeks:
        matchups[wk] = _phantom_week(wk)
    return _build_snapshot(matchups)


class ScoredWeeksHelperTests(unittest.TestCase):
    """Direct coverage of the new canonical week-eligibility gate."""

    def test_phantom_weeks_excluded(self) -> None:
        snap = _phantom_snapshot()
        season = snap.seasons[0]
        self.assertEqual(metrics.scored_weeks(season.matchups_by_week), [1])

    def test_partially_scored_week_still_counts(self) -> None:
        """A week where at least one entry has real points (a currently
        in-progress week, or a bye-heavy roster) is not a phantom week —
        it is included whole."""
        matchups = {
            1: [
                {"matchup_id": 1, "roster_id": 1, "points": 45.0},
                {"matchup_id": 1, "roster_id": 2, "points": 0.0},  # MNF not played yet
            ]
        }
        self.assertEqual(metrics.scored_weeks(matchups), [1])

    def test_future_week_with_empty_players_points_is_still_excluded(self) -> None:
        """Gating happens at the week/points level, before players_points
        is ever inspected, so an empty ``{}`` future week is excluded
        exactly like a zero-stubbed one."""
        matchups = {
            1: _WEEK_1_REAL,
            2: [
                {"matchup_id": 2, "roster_id": 1, "points": 0.0, "players_points": {}},
                {"matchup_id": 2, "roster_id": 2, "points": 0.0, "players_points": {}},
            ],
        }
        self.assertEqual(metrics.scored_weeks(matchups), [1])

    def test_week_with_no_matchup_id_but_real_points_still_counts(self) -> None:
        """scored_weeks decides played-ness from points, not matchup_id —
        it must not accidentally reintroduce a matchup_id dependency."""
        matchups = {1: [{"matchup_id": None, "roster_id": 1, "points": 10.0}]}
        self.assertEqual(metrics.scored_weeks(matchups), [1])


class StarterScoringWalkGatingTests(unittest.TestCase):
    """``_starter_scoring_walk`` must never yield a phantom-week row."""

    def test_walk_yields_only_real_week(self) -> None:
        snap = _phantom_snapshot()
        season = snap.seasons[0]
        weeks_seen = {
            row[0] for row in _starter_scoring_walk(snap, season, regular_season_only=True)
        }
        self.assertEqual(weeks_seen, {1})

    def test_caleb_is_not_credited_with_phantom_starts(self) -> None:
        """Caleb Williams (echoed into every phantom week's frozen
        starters, exactly like the live production case) must NOT
        accumulate more than his one real game."""
        snap = _phantom_snapshot()
        season = snap.seasons[0]
        totals = _player_starter_totals(snap, season, regular_season_only=True)
        self.assertEqual(totals["caleb"]["gamesStarted"], 1)
        self.assertAlmostEqual(totals["caleb"]["starterPoints"], 46.97, places=2)


class PlayerStarterTotalsPhantomWeekTests(unittest.TestCase):
    """gamesStarted must equal real production, never inflated by echoed
    future-lineup placeholders."""

    def setUp(self) -> None:
        self.snap = _phantom_snapshot()
        self.season = self.snap.seasons[0]
        self.totals = _player_starter_totals(self.snap, self.season, regular_season_only=True)

    def test_watt_and_allen_stay_at_one_real_game(self) -> None:
        self.assertEqual(self.totals["watt"]["gamesStarted"], 1)
        self.assertEqual(self.totals["allen"]["gamesStarted"], 1)

    def test_rousseau_and_caleb_are_not_inflated_by_the_frozen_echo(self) -> None:
        """Before the fix these would have accumulated 4 (1 real + 3
        phantom) purely because their owners' current lineup happens to
        still include them — exactly the live Rousseau/Caleb pattern."""
        self.assertEqual(self.totals["rousseau"]["gamesStarted"], 1)
        self.assertEqual(self.totals["caleb"]["gamesStarted"], 1)

    def test_legitimate_zero_point_start_in_a_real_week_still_counts(self) -> None:
        """kicker_x genuinely started and scored 0 in the one REAL week —
        that is a legitimate zero, not a phantom one, and must still be
        counted as a game."""
        self.assertEqual(self.totals["kicker_x"]["gamesStarted"], 1)
        self.assertAlmostEqual(self.totals["kicker_x"]["starterPoints"], 0.0, places=2)

    def test_games_started_never_exceeds_scored_weeks(self) -> None:
        scored = len(metrics.scored_weeks(self.season.matchups_by_week))
        for rec in self.totals.values():
            self.assertLessEqual(rec["gamesStarted"], scored)

    def test_more_phantom_weeks_does_not_further_inflate_games(self) -> None:
        """Widening the phantom-week window (Sleeper over-fetches 18
        weeks in production) must not change the result — every one of
        them is excluded the same way."""
        wide = _phantom_snapshot(phantom_weeks=tuple(range(2, 19)))
        totals = _player_starter_totals(wide, wide.seasons[0], regular_season_only=True)
        self.assertEqual(totals["caleb"]["gamesStarted"], 1)
        self.assertEqual(totals["rousseau"]["gamesStarted"], 1)


class AllRosteredTotalsPhantomWeekTests(unittest.TestCase):
    """``_player_all_rostered_totals`` (PR #1364's replacement-pool
    population) must exclude phantom weeks too — it is the more
    dangerous half of this bug, since players_points stubs the WHOLE
    roster (not just echoed starters) for every future week, which
    would otherwise deflate replacementPerGame for nearly the entire
    league's player pool."""

    def setUp(self) -> None:
        self.snap = _phantom_snapshot()
        self.season = self.snap.seasons[0]
        self.totals = _player_all_rostered_totals(self.snap, self.season, regular_season_only=True)

    def test_every_rostered_player_games_capped_at_real_weeks(self) -> None:
        for pid, rec in self.totals.items():
            self.assertEqual(rec["games"], 1, f"{pid} should have exactly 1 real game")

    def test_points_reflect_only_the_real_week(self) -> None:
        self.assertAlmostEqual(self.totals["rousseau"]["points"], 44.91, places=2)
        self.assertAlmostEqual(self.totals["caleb"]["points"], 46.97, places=2)

    def test_midseason_add_drop_only_counts_rostered_weeks(self) -> None:
        """A player who only appears in players_points for SOME of the
        scored weeks (added/dropped mid-season) accumulates games only
        from the weeks they were actually rostered."""
        matchups = {
            1: [
                {
                    "matchup_id": 1,
                    "roster_id": 1,
                    "points": 40.0,
                    "players_points": {"allen": 40.0},
                    "starters": ["allen"],
                }
            ],
            2: [
                {
                    "matchup_id": 2,
                    "roster_id": 1,
                    "points": 30.0,
                    "players_points": {"caleb": 30.0},  # allen was dropped, caleb added
                    "starters": ["caleb"],
                }
            ],
        }
        snap = _build_snapshot(matchups)
        totals = _player_all_rostered_totals(snap, snap.seasons[0], regular_season_only=True)
        self.assertEqual(totals["allen"]["games"], 1)
        self.assertEqual(totals["caleb"]["games"], 1)


class VorpArithmeticInvariantTests(unittest.TestCase):
    """End-to-end VORP arithmetic proofs (acceptance criteria A-D)."""

    def setUp(self) -> None:
        self.snap = _phantom_snapshot()
        self.season = self.snap.seasons[0]
        self.rows = _vorp_rows(self.snap, self.season, regular_season_only=True)
        self.by_id = {r["playerId"]: r for r in self.rows}

    def test_same_position_shares_one_replacement_rate(self) -> None:
        """DL invariant (acceptance A/B): Watt and Rousseau must be
        charged the EXACT same replacementPerGame."""
        self.assertEqual(
            self.by_id["watt"]["replacementPerGame"],
            self.by_id["rousseau"]["replacementPerGame"],
        )

    def test_qb_shares_one_replacement_rate(self) -> None:
        """QB invariant (acceptance C): Allen and Caleb must be charged
        the exact same replacementPerGame."""
        self.assertEqual(
            self.by_id["allen"]["replacementPerGame"],
            self.by_id["caleb"]["replacementPerGame"],
        )

    def test_equal_games_started_monotonicity(self) -> None:
        """Watt and Rousseau both have gamesStarted == 1 after the fix,
        so ordering by starterPoints must equal ordering by vorp."""
        watt, rousseau = self.by_id["watt"], self.by_id["rousseau"]
        self.assertEqual(watt["gamesStarted"], rousseau["gamesStarted"])
        higher_points = max(watt, rousseau, key=lambda r: r["starterPoints"])
        higher_vorp = max(watt, rousseau, key=lambda r: r["vorp"])
        self.assertEqual(higher_points["playerId"], higher_vorp["playerId"])

    def test_watt_vorp_is_exactly_arithmetically_explained(self) -> None:
        """Acceptance A: Watt's VORP == starterPoints - replacementPerGame * gamesStarted,
        with no hidden term."""
        watt = self.by_id["watt"]
        expected = round(
            max(0.0, watt["starterPoints"] - watt["replacementPerGame"] * watt["gamesStarted"]), 2
        )
        self.assertEqual(watt["vorp"], expected)
        self.assertEqual(
            watt["replacementTotal"], round(watt["replacementPerGame"] * watt["gamesStarted"], 2)
        )

    def test_caleb_does_not_rank_below_allen_on_phantom_games_alone(self) -> None:
        """Acceptance D: Caleb Williams has MORE raw starter points than
        Josh Allen and, after the fix, the SAME gamesStarted (1) and the
        SAME QB replacementPerGame — so his VORP must be >= Allen's.  If
        this ever fails, the arithmetic must show a legitimate extra
        start for Allen, not a phantom-week artifact for Caleb."""
        allen, caleb = self.by_id["allen"], self.by_id["caleb"]
        self.assertGreater(caleb["starterPoints"], allen["starterPoints"])
        self.assertEqual(caleb["gamesStarted"], allen["gamesStarted"])
        self.assertGreaterEqual(caleb["vorp"], allen["vorp"])

    def test_all_rows_share_one_as_of_week(self) -> None:
        """Acceptance F: every VORP row from one calculation shares the
        same as-of boundary."""
        as_of_weeks = {r["asOfWeek"] for r in self.rows}
        self.assertEqual(as_of_weeks, {1})


class VorpCalcVersionStampTests(unittest.TestCase):
    def test_rows_carry_a_calc_version(self) -> None:
        snap = _phantom_snapshot()
        rows = _vorp_rows(snap, snap.seasons[0], regular_season_only=True)
        self.assertTrue(rows)
        from src.public_league.awards import _VORP_CALC_VERSION

        for r in rows:
            self.assertEqual(r["calcVersion"], _VORP_CALC_VERSION)


if __name__ == "__main__":
    unittest.main()
