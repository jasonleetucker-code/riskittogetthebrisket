"""`src/ros/game_day_week.py` — resolving a live league-week for the simulator.

`game_day_sim` shipped with zero callers; this module is the resolver half.
The tests that matter are the ones about what is NOT there: a player nobody
priced, a player the roster benches to IR, a week that has already started.
Each of those has a wrong answer that looks like a right one — a zero — and
each is pinned here.
"""

from __future__ import annotations

import unittest

from src.ros.game_day_sim import simulate_league_week
from src.ros.game_day_week import (
    GameDayWeekRefusal,
    opponents_from_matchups,
    resolve_pregame_week,
)

SLOTS = ["QB", "RB", "RB", "WR", "WR", "FLEX"]

LEAGUE = {"settings": {"best_ball": 1, "league_average_match": 1, "num_teams": 2}}


def _meta(**names):
    out = {}
    for pid, (full, pos) in names.items():
        out[pid] = {"full_name": full, "position": pos, "fantasy_positions": [pos]}
    return out


META = _meta(
    p1=("Ann Alpha", "QB"),
    p2=("Bob Bravo", "RB"),
    p3=("Cy Charlie", "WR"),
    p4=("Dee Delta", "WR"),
    p5=("Eve Echo", "RB"),
    p6=("Fay Foxtrot", "TE"),
)

ESTIMATES = {
    "ann alpha": 20.0,
    "bob bravo": 12.0,
    "cy charlie": 11.0,
    "dee delta": 10.0,
    "eve echo": 9.0,
    # Fay Foxtrot deliberately absent — the unpriced case.
}


def _rosters(*, taxi=(), reserve=()):
    return [
        {
            "roster_id": 1,
            "players": ["p1", "p2", "p3"],
            "taxi": list(taxi),
            "reserve": list(reserve),
        },
        {"roster_id": 2, "players": ["p4", "p5", "p6"]},
    ]


def _matchups():
    return [
        {"roster_id": 1, "matchup_id": 1, "points": 0},
        {"roster_id": 2, "matchup_id": 1, "points": 0},
    ]


def _resolve(**over):
    kwargs = dict(
        league_key="test_league",
        league_payload=LEAGUE,
        rosters=_rosters(),
        matchups=_matchups(),
        players_meta=META,
        starter_slots=SLOTS,
        estimates=dict(ESTIMATES),
        estimate_source="test:estimates",
    )
    kwargs.update(over)
    return resolve_pregame_week(**kwargs)


class OpponentsTests(unittest.TestCase):
    def test_a_two_roster_matchup_pairs_both_ways(self) -> None:
        self.assertEqual(opponents_from_matchups(_matchups()), {"1": "2", "2": "1"})

    def test_a_bye_has_no_opponent_rather_than_an_arbitrary_one(self) -> None:
        rows = [{"roster_id": 3, "matchup_id": 9}]
        self.assertEqual(opponents_from_matchups(rows), {"3": None})

    def test_a_three_roster_group_names_no_opponent_for_any_member(self) -> None:
        rows = [{"roster_id": i, "matchup_id": 4} for i in (1, 2, 3)]
        self.assertEqual(opponents_from_matchups(rows), {"1": None, "2": None, "3": None})

    def test_a_row_with_no_matchup_id_is_unscheduled_not_dropped(self) -> None:
        # Dropping it would leave the team out of the opponents map entirely,
        # which reads as "not asked about" rather than "no game".
        self.assertEqual(opponents_from_matchups([{"roster_id": 7}]), {"7": None})

    def test_no_matchups_at_all_is_empty_not_an_error(self) -> None:
        self.assertEqual(opponents_from_matchups(None), {})


class PregameResolutionTests(unittest.TestCase):
    def test_priced_players_are_not_started_with_their_estimate(self) -> None:
        res = _resolve()
        team1 = next(t for t in res.teams if t.team_id == "1")
        ann = next(p for p in team1.players if p.player_id == "p1")
        self.assertEqual(ann.state, "not_started")
        self.assertEqual(ann.projected_remaining, 20.0)
        # Pregame: nothing banked, and that is an observation.
        self.assertEqual(ann.points_scored, 0.0)

    def test_an_unpriced_player_is_unknown_and_reported_never_zero(self) -> None:
        res = _resolve()
        team2 = next(t for t in res.teams if t.team_id == "2")
        fay = next(p for p in team2.players if p.player_id == "p6")
        self.assertEqual(fay.state, "unknown")
        self.assertIsNone(fay.projected_remaining)
        self.assertIn("p6", res.unpriced_player_ids["2"])
        self.assertEqual(res.estimate_coverage, (5, 6))

    def test_an_unpriced_player_is_excluded_from_every_draw(self) -> None:
        # The simulator's own contract, reached through this resolver.
        res = _resolve()
        sim = simulate_league_week(
            rules=res.rules,
            teams=res.teams,
            opponents=res.opponents,
            season=2026,
            week=1,
            draws=50,
            seed=3,
        )
        team2 = next(t for t in sim.teams if t.team_id == "2")
        self.assertIn("p6", team2.unsimulable_player_ids)

    def test_ir_and_taxi_players_leave_the_week_entirely(self) -> None:
        res = _resolve(rosters=_rosters(taxi=("p3",)))
        team1 = next(t for t in res.teams if t.team_id == "1")
        self.assertNotIn("p3", [p.player_id for p in team1.players])
        self.assertEqual(res.ineligible_player_ids["1"], ("p3",))
        # And he is NOT counted as merely unpriced — a different fact.
        self.assertNotIn("p3", res.unpriced_player_ids["1"])

    def test_a_duplicate_roster_entry_is_one_player(self) -> None:
        rosters = _rosters()
        rosters[0]["players"] = ["p1", "p1", "p2", "p3"]
        res = _resolve(rosters=rosters)
        team1 = next(t for t in res.teams if t.team_id == "1")
        self.assertEqual(len(team1.players), 3)

    def test_every_team_gets_an_opponents_entry(self) -> None:
        # An ABSENT key and a key holding None must not be left for the
        # simulator to tell apart.
        res = _resolve(matchups=[])
        for team in res.teams:
            self.assertIn(team.team_id, res.opponents)
            self.assertIsNone(res.opponents[team.team_id])

    def test_no_projection_snapshot_resolves_and_says_so(self) -> None:
        res = _resolve(estimates=None, estimate_source=None)
        self.assertIsNone(res.estimate_source)
        self.assertEqual(res.estimate_coverage, (0, 6))
        self.assertTrue(any("no projection snapshot" in n for n in res.notes))
        self.assertTrue(all(p.state == "unknown" for t in res.teams for p in t.players))

    def test_partial_coverage_is_reported_rather_than_smoothed_over(self) -> None:
        res = _resolve()
        self.assertTrue(any("unpriced" in n for n in res.notes))

    def test_league_rules_come_from_the_league_payload(self) -> None:
        res = _resolve()
        self.assertTrue(res.rules.best_ball)
        self.assertIs(res.rules.median_enabled, True)
        self.assertEqual(res.rules.team_count, 2)
        self.assertEqual(res.rules.starter_slots, tuple(SLOTS))


class RefusalTests(unittest.TestCase):
    def test_a_week_that_has_begun_is_refused_not_degraded(self) -> None:
        started = _matchups()
        started[0]["points"] = 12.5
        with self.assertRaises(GameDayWeekRefusal) as ctx:
            _resolve(matchups=started)
        self.assertIn("already begun", str(ctx.exception))

    def test_a_player_level_score_also_counts_as_begun(self) -> None:
        started = _matchups()
        started[1]["players_points"] = {"p4": 3.2}
        with self.assertRaises(GameDayWeekRefusal):
            _resolve(matchups=started)

    def test_no_rosters_is_refused(self) -> None:
        with self.assertRaises(GameDayWeekRefusal):
            _resolve(rosters=[])

    def test_no_starter_slots_is_refused(self) -> None:
        # Defaulting a slot list would simulate a different league.
        with self.assertRaises(GameDayWeekRefusal):
            _resolve(starter_slots=[])


class EndToEndTests(unittest.TestCase):
    def test_the_resolver_feeds_the_simulator_coherently(self) -> None:
        res = _resolve()
        sim = simulate_league_week(
            rules=res.rules,
            teams=res.teams,
            opponents=res.opponents,
            season=2026,
            week=1,
            draws=200,
            seed=5,
        )
        self.assertEqual(len(sim.teams), 2)
        a, b = sorted(sim.teams, key=lambda t: t.team_id)
        # One head-to-head: the two win percentages plus a tie account for
        # the whole probability mass.
        total = (a.win_matchup_pct or 0) + (b.win_matchup_pct or 0) + (a.tie_matchup_pct or 0)
        self.assertAlmostEqual(total, 100.0, delta=0.05)
        # The unverified threshold semantics travel with the result.
        self.assertFalse(sim.threshold_semantics_verified)
