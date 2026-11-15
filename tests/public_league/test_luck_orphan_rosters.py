"""#1530 finding A -- Luck's expected and actual wins over ONE game set.

``luck.py`` used to drop an ownerless (orphan) roster from every all-play
rival set while still crediting the owner who played it with the actual
result, so expected and actual wins were summed over different games.
Measured on ``dynasty_new`` 2024, where rosters 3 and 5 had no owner all
season.  The fixture is that season's real regular-season matchup rows
(``tests/fixtures/public_league/dynasty_new_2024_matchups.json``; owner ids
anonymised).

The canonical rule is ``schedule_impact``'s: an orphan roster is a real
participant.  Luck now consumes that owner, so the two must agree exactly.
"""

from __future__ import annotations

import json
import unittest
from pathlib import Path

from src.public_league import luck
from src.public_league import schedule_impact as si
from src.public_league.identity import build_manager_registry
from src.public_league.snapshot import PublicLeagueSnapshot, SeasonSnapshot

FIXTURE = (
    Path(__file__).resolve().parents[1]
    / "fixtures"
    / "public_league"
    / "dynasty_new_2024_matchups.json"
)


def _dynasty_new_2024() -> PublicLeagueSnapshot:
    fx = json.loads(FIXTURE.read_text(encoding="utf-8"))
    league = {
        "league_id": fx["league_id"],
        "name": "dynasty_new 2024 fixture",
        "season": fx["season"],
        "season_type": "regular",
        "status": fx["status"],
        "total_rosters": fx["total_rosters"],
        "settings": fx["settings"],
    }
    rosters = [{**r, "players": []} for r in fx["rosters"]]
    users = [
        {"user_id": r["owner_id"], "display_name": r["owner_id"], "metadata": {}}
        for r in rosters
        if r["owner_id"]
    ]
    season = SeasonSnapshot(
        season=fx["season"],
        league_id=fx["league_id"],
        league=league,
        users=users,
        rosters=rosters,
        matchups_by_week={int(w): rows for w, rows in fx["weeks"].items()},
        transactions_by_week={},
        drafts=[],
        draft_picks_by_draft={},
        traded_picks=[],
        winners_bracket=[],
        losers_bracket=[],
    )
    return PublicLeagueSnapshot(
        root_league_id=fx["league_id"],
        generated_at="2026-10-07T00:00:00+00:00",
        seasons=[season],
        managers=build_manager_registry([{"league": league, "users": users, "rosters": rosters}]),
    )


class LuckOrphanRosterTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.snap = _dynasty_new_2024()
        cls.section = luck.build_section(cls.snap)
        cls.contract = si.season_contract(cls.snap, cls.snap.seasons[0])

    def test_fixture_really_has_the_two_orphan_rosters(self) -> None:
        orphans = sorted(r["roster_id"] for r in self.snap.seasons[0].rosters if not r["owner_id"])
        self.assertEqual(orphans, [3, 5])
        orphan_teams = sorted(t["teamKey"] for t in self.contract["teams"] if t["orphanRoster"])
        self.assertEqual(orphan_teams, ["roster:3", "roster:5"])

    def test_expected_and_actual_are_measured_over_the_same_games(self) -> None:
        # The defect: an owner's game against an orphan counted in ACTUAL wins
        # while the orphan was missing from that week's all-play rivals.  Every
        # owner row must now equal the canonical contract on both halves.
        canon = {t["ownerId"]: t for t in self.contract["teams"] if t["ownerId"]}
        rows = self.section["byOwnerSeason"]
        self.assertEqual(len(rows), 8)
        for row in rows:
            c = canon[row["ownerId"]]
            self.assertEqual(row["gamesPlayed"], c["games"], row["ownerId"])
            self.assertAlmostEqual(row["actualWins"], round(c["actualH2HCredits"], 2), places=9)
            self.assertAlmostEqual(
                row["expectedWins"], round(c["equalOpponentExpectedH2HCredits"], 2), places=9
            )
            self.assertAlmostEqual(row["luckDelta"], round(c["scheduleImpact"], 2), delta=0.011)

    def test_orphans_are_rivals_in_every_week(self) -> None:
        # 10 teams play every regular-season week: 9 rivals each, orphans included.
        career = {r["ownerId"]: r for r in self.section["byOwnerCareer"]}
        for oid, row in career.items():
            losses = row["allPlayLosses"]
            rivals = row["allPlayBeats"] + row["allPlayTies"] + losses
            self.assertEqual(rivals, 9 * row["gamesPlayed"], oid)

    def test_an_orphan_roster_is_never_published_as_a_luck_row(self) -> None:
        owners = {r["ownerId"] for r in self.section["byOwnerSeason"]}
        owners |= {r["ownerId"] for r in self.section["byOwnerCareer"]}
        owners |= {t["ownerId"] for t in self.section["weeklyTrail"]}
        self.assertFalse(any(o is None or str(o).startswith("roster:") for o in owners))


class LuckSeasonStateTests(unittest.TestCase):
    """A season Luck cannot evaluate is NAMED with its reason, never silently
    absent from the tables."""

    def test_a_fully_evaluated_season_reports_complete(self) -> None:
        section = luck.build_section(_dynasty_new_2024())
        self.assertEqual(
            section["seasonStates"],
            [
                {
                    "season": "2024",
                    "state": "complete",
                    "reason": None,
                    "issueCount": 0,
                    "teamWeeks": 8 * 14,
                }
            ],
        )

    def test_an_unsupported_season_is_named_not_dropped(self) -> None:
        snap = _dynasty_new_2024()
        # A team in two games in one week: a format the canonical owner
        # refuses to evaluate rather than simplify.
        week1 = snap.seasons[0].matchups_by_week[1]
        week1.append({"roster_id": week1[0]["roster_id"], "matchup_id": 99, "points": 1.0})
        week1.append({"roster_id": week1[1]["roster_id"], "matchup_id": 99, "points": 2.0})
        section = luck.build_section(snap)

        self.assertEqual(section["byOwnerSeason"], [])
        (state,) = section["seasonStates"]
        self.assertEqual(state["state"], "unsupported")
        self.assertEqual(state["reason"], "format_not_one_game_per_team_week")
        self.assertEqual(state["teamWeeks"], 0)
        self.assertGreater(state["issueCount"], 0)


if __name__ == "__main__":
    unittest.main()
