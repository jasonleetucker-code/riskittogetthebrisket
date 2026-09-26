"""A position too thin to set a replacement level is EXCLUDED from VORP awards.

THE DEFECT, measured on real data (dynasty_new 2025, a league with no IDP
slots): Travis Hunter is a two-way player whose Sleeper eligibility
resolves to DB, and he was the league's ONLY rostered DB.  A position with
no dedicated slot gets a substitute cutoff of ``max(1, pool // 2)`` = 1, so
the replacement band below it was empty and ``replacement_per_game`` fell
back to the worst player's per-game rate: his own.  Because his rostered
games (bench weeks included) outnumber his starts, "replacement" came out
at 4.56/g and his VORP at 29.26, and he won Defensive Player of the Year
and Defensive Rookie of the Year against himself.

The repair (``awards._vorp_board``): the replacement band must be FULL
(``starter slots + 5`` rostered players) or the position is excluded
outright and published in ``vorpExclusions`` with its reason.  MISSING IS
NEVER ZERO: an unmeasurable baseline is never published as a 0 or as a
self-referential number.
"""

from __future__ import annotations

import unittest

from src.public_league import awards
from src.public_league.awards import VORP_EXCLUSION_THIN_BAND
from src.public_league.identity import build_manager_registry
from src.public_league.snapshot import PublicLeagueSnapshot, SeasonSnapshot
from tests.public_league.fixtures import REAL_LEAGUE_BENCH_DEPTH, add_rostered_bench

_OWNERS = ["owner-A", "owner-B", "owner-C", "owner-D"]
_USERS = [{"user_id": o, "display_name": o[-1], "metadata": {}} for o in _OWNERS]
_ROSTERS = [
    {"roster_id": i, "owner_id": o, "players": [], "settings": {"wins": 1, "losses": 1}}
    for i, o in enumerate(_OWNERS, start=1)
]
# Offense-only league: no DL/LB/DB slot anywhere.
_ROSTER_POSITIONS = ["QB", "RB", "WR", "TE", "FLEX", "SUPER_FLEX", "BN", "BN", "BN"]

_NFL_PLAYERS = {
    # The two-way player: WR/CB eligibility resolves to the DB family.
    "hunter": {
        "full_name": "Two Way",
        "position": "WR",
        "fantasy_positions": ["WR", "CB"],
        "team": "JAX",
        "years_exp": 0,
    },
    **{
        f"q{i}": {"full_name": f"QB {i}", "position": "QB", "team": "BUF", "years_exp": 4}
        for i in range(1, 5)
    },
}


def _entry(rid: int, starters: dict[str, float], bench: dict[str, float] | None = None) -> dict:
    pp = {**starters, **(bench or {})}
    return {
        "matchup_id": 1 if rid <= 2 else 2,
        "roster_id": rid,
        "points": round(sum(starters.values()), 2),
        "starters": list(starters),
        "players_points": pp,
    }


def _week(week: int) -> list[dict]:
    # Roster 1 starts the two-way player in weeks 1-2 and benches him in
    # week 3 (a rostered 0.0) -- so his rostered games (3) outnumber his
    # starts (2), exactly the shape that made his self-baseline positive.
    if week == 3:
        r1 = _entry(1, {"q1": 20.0}, bench={"hunter": 0.0})
    else:
        r1 = _entry(1, {"q1": 20.0, "hunter": 20.0})
    return [
        r1,
        _entry(2, {"q2": 22.0}),
        _entry(3, {"q3": 18.0}),
        _entry(4, {"q4": 16.0}),
    ]


def _snapshot() -> PublicLeagueSnapshot:
    league = {
        "league_id": "NOIDP",
        "season": "2025",
        "season_type": "regular",
        "status": "in_season",
        "total_rosters": 4,
        "roster_positions": _ROSTER_POSITIONS,
        "settings": {"playoff_week_start": 15, "last_scored_leg": 3},
    }
    season = SeasonSnapshot(
        season="2025",
        league_id="NOIDP",
        league=league,
        users=_USERS,
        rosters=_ROSTERS,
        matchups_by_week={w: _week(w) for w in (1, 2, 3)},
        transactions_by_week={},
        drafts=[],
        draft_picks_by_draft={},
        traded_picks=[],
        winners_bracket=[],
        losers_bracket=[],
    )
    snap = PublicLeagueSnapshot(
        root_league_id="NOIDP",
        generated_at="2025-10-01T00:00:00Z",
        seasons=[season],
        managers=build_manager_registry([{"league": league, "users": _USERS, "rosters": _ROSTERS}]),
        nfl_players=dict(_NFL_PLAYERS),
    )
    # A real offense-only league's bench: no defenders rostered at all.
    add_rostered_bench(
        snap,
        season,
        depth={p: n for p, n in REAL_LEAGUE_BENCH_DEPTH.items() if p not in ("DL", "LB", "DB")},
    )
    return snap


class TwoWayPlayerIsNotMeasuredAgainstHimselfTests(unittest.TestCase):
    def setUp(self) -> None:
        self.snap = _snapshot()
        self.season = self.snap.seasons[0]
        self.section = awards.build_section(self.snap)
        self.season_row = self.section["bySeason"][0]

    def test_the_fixture_reproduces_the_self_baseline(self) -> None:
        """Guard on the fixture itself: the lenient (retired) gate really
        does return the player's OWN rostered per-game rate as the DB
        replacement level, so the tests below exercise the real defect."""
        self.assertEqual(self.snap.player_position("hunter"), "DB")
        pool = [
            r
            for r in awards._player_all_rostered_totals(
                self.snap, self.season, regular_season_only=True
            ).values()
            if r["position"] == "DB"
        ]
        self.assertEqual([r["playerId"] for r in pool], ["hunter"])
        lenient = awards._replacement_per_game_for_position(pool, 1)
        self.assertAlmostEqual(lenient, 40.0 / 3, places=6)
        # 40 starter points - (40/3 x 2 starts) = 13.33 VORP against himself.
        self.assertGreater(40.0 - lenient * 2, 0.0)
        self.assertIsNone(
            awards._replacement_per_game_for_position(pool, 1, require_full_band=True)
        )

    def test_no_dpoy_or_def_roy_winner(self) -> None:
        keys = {a["key"] for a in self.season_row["awards"]}
        self.assertNotIn("def_mvp", keys)
        self.assertNotIn("def_roy", keys)
        race_keys = {r["key"] for r in self.section["awardRaces"]}
        self.assertNotIn("def_mvp", race_keys)
        self.assertNotIn("def_roy", race_keys)

    def test_the_player_is_absent_from_every_vorp_board(self) -> None:
        mvp = next(a for a in self.season_row["awards"] if a["key"] == "league_mvp")
        self.assertNotEqual(mvp["value"]["playerId"], "hunter")
        race = next(r for r in self.section["awardRaces"] if r["key"] == "league_mvp")
        self.assertNotIn("hunter", {s["value"]["playerId"] for s in race["standings"]})
        self.assertNotIn("hunter", {x["value"]["playerId"] for x in race["leaders"]})

    def test_the_exclusion_is_published(self) -> None:
        self.assertEqual(
            self.season_row["vorpExclusions"],
            [
                {
                    "position": "DB",
                    "reason": VORP_EXCLUSION_THIN_BAND,
                    "poolSize": 1,
                    "required": 6,
                    "starterSlots": 1,
                    "candidates": 1,
                }
            ],
        )
        race = next(r for r in self.section["awardRaces"] if r["key"] == "league_mvp")
        self.assertEqual([e["position"] for e in race["vorpExclusions"]], ["DB"])

    def test_offense_races_carry_no_defensive_exclusion(self) -> None:
        for race in self.section["awardRaces"]:
            if race["key"] in ("off_mvp", "off_roy"):
                self.assertNotIn("vorpExclusions", race)

    def test_measurable_positions_are_still_measured(self) -> None:
        rows, exclusions = awards._vorp_board(self.snap, self.season, regular_season_only=True)
        self.assertEqual({r["position"] for r in rows}, {"QB"})
        self.assertEqual([e["position"] for e in exclusions], ["DB"])
        for r in rows:
            self.assertIsNotNone(r["replacementPerGame"])


if __name__ == "__main__":
    unittest.main()
