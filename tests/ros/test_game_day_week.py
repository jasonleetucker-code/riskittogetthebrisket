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
        # Sleeper's official host documentation verifies the canonical
        # median semantics for this even-sized league.
        self.assertTrue(sim.threshold_semantics_verified)


def test_live_resolution_preserves_banked_and_degrades_without_kickoff_evidence():
    from src.ros.game_day_week import GameEvidence, resolve_scoring_week

    players = {k: dict(v) for k, v in META.items()}
    players["p1"] = dict(players["p1"], team="SEA")
    players["p2"] = dict(players["p2"], team="MIN")
    matchups = [
        {
            "roster_id": 1,
            "matchup_id": 1,
            "points": 11.5,
            "players_points": {"p1": 11.5, "p2": 0.0},
        },
        {"roster_id": 8, "matchup_id": 1, "points": 0.0, "players_points": {}},
    ]
    result = resolve_scoring_week(
        league_key="fixture",
        league_payload={"settings": {"best_ball": 1, "league_average_match": 1, "num_teams": 2}},
        rosters=[_rosters()[0], {"roster_id": 8, "players": []}],
        matchups=matchups,
        players_meta=players,
        starter_slots=SLOTS,
        estimates={"ann alpha": 20.0, "bob bravo": 12.0},
        estimate_source="fixture",
        game_evidence={
            "SEA": GameEvidence("in_progress", "fixture-live", 100.0),
            "MIN": GameEvidence("not_started", "fixture-live", 100.0),
        },
        now=101.0,
    )
    assert result.mode == "live"
    assert result.host_scores["1"] == 11.5
    # No kickoff_at on the SEA evidence: real evidence exists that the game
    # is in progress, but nothing to time-prorate against, so remaining
    # stays None and this is a missing-evidence report, not a
    # methodology-undecided one (that seam closed 2026-09-09).
    assert result.progress_unavailable_player_ids == ("p1",)
    by_id = {p.player_id: p for p in result.week.teams[0].players}
    assert by_id["p1"].points_scored == 11.5
    assert by_id["p1"].projected_remaining is None
    assert by_id["p2"].projected_remaining == 12.0


def test_in_progress_remaining_is_time_prorated_with_kickoff_evidence():
    """Owner decision 2026-09-09: real kickoff evidence prorates, not blocks."""
    from src.ros.game_day_week import (
        GameEvidence,
        _ASSUMED_GAME_DURATION_SECONDS,
        resolve_scoring_week,
    )

    players = {k: dict(v) for k, v in META.items()}
    players["p1"] = dict(players["p1"], team="SEA")
    players["p2"] = dict(players["p2"], team="MIN")
    kickoff = 1_000.0
    elapsed = _ASSUMED_GAME_DURATION_SECONDS / 4.0  # a quarter of the assumed duration
    matchups = [
        {"roster_id": 1, "matchup_id": 1, "points": 6.0, "players_points": {"p1": 6.0}},
        {"roster_id": 2, "matchup_id": 1, "points": 0.0, "players_points": {"p2": 0.0}},
    ]
    result = resolve_scoring_week(
        league_key="fixture",
        league_payload=LEAGUE,
        rosters=_rosters(),
        matchups=matchups,
        players_meta=players,
        starter_slots=SLOTS,
        estimates={"ann alpha": 20.0, "bob bravo": 12.0},
        estimate_source="fixture",
        game_evidence={
            "SEA": GameEvidence("in_progress", "fixture-live", kickoff, kickoff),
            "MIN": GameEvidence("not_started", "fixture-live", kickoff, kickoff + 1000.0),
        },
        now=kickoff + elapsed,
    )
    assert result.mode == "live"
    assert result.progress_unavailable_player_ids == ()
    p1 = next(p for p in result.week.teams[0].players if p.player_id == "p1")
    # A quarter of the assumed game elapsed -> ~75% of the pregame estimate
    # should remain. Exact, not approximate: the model is a plain linear
    # scale-down, so this is checkable to the cent.
    assert p1.projected_remaining == 20.0 * 0.75
    assert p1.points_scored == 6.0


def test_ruled_out_player_remaining_is_zero_not_unknown():
    """A host-declared Out is definitive evidence, not a missing observation."""
    from src.ros.game_day_week import GameEvidence, resolve_scoring_week

    players = {k: dict(v) for k, v in META.items()}
    players["p1"] = dict(players["p1"], team="SEA", injury_status="Out")
    players["p2"] = dict(players["p2"], team="MIN")
    matchups = [
        {"roster_id": 1, "matchup_id": 1, "points": 0.0, "players_points": {"p1": 0.0}},
        {"roster_id": 2, "matchup_id": 1, "points": 3.0, "players_points": {"p2": 3.0}},
    ]
    result = resolve_scoring_week(
        league_key="fixture",
        league_payload=LEAGUE,
        rosters=_rosters(),
        matchups=matchups,
        players_meta=players,
        starter_slots=SLOTS,
        estimates={"ann alpha": 20.0, "bob bravo": 12.0},
        estimate_source="fixture",
        game_evidence={
            "SEA": GameEvidence("in_progress", "fixture-live", 100.0, 50.0),
            "MIN": GameEvidence("in_progress", "fixture-live", 100.0, 50.0),
        },
        now=100.0,
    )
    p1 = next(p for p in result.week.teams[0].players if p.player_id == "p1")
    assert p1.state == "inactive"
    assert p1.projected_remaining == 0.0
    assert "p1" not in result.progress_unavailable_player_ids


def test_now_before_kickoff_degrades_rather_than_negative_prorates():
    """Defensive: stale/inconsistent evidence must never overshoot to > full value."""
    from src.ros.game_day_week import GameEvidence, resolve_scoring_week

    players = {k: dict(v) for k, v in META.items()}
    players["p1"] = dict(players["p1"], team="SEA")
    players["p2"] = dict(players["p2"], team="MIN")
    matchups = [
        {"roster_id": 1, "matchup_id": 1, "points": 0.0, "players_points": {"p1": 0.0}},
        {"roster_id": 2, "matchup_id": 1, "points": 0.0, "players_points": {"p2": 0.0}},
    ]
    result = resolve_scoring_week(
        league_key="fixture",
        league_payload=LEAGUE,
        rosters=_rosters(),
        matchups=matchups,
        players_meta=players,
        starter_slots=SLOTS,
        estimates={"ann alpha": 20.0, "bob bravo": 12.0},
        estimate_source="fixture",
        game_evidence={
            # kickoff_at is AFTER now: inconsistent/stale evidence.
            "SEA": GameEvidence("in_progress", "fixture-live", 100.0, 500.0),
            "MIN": GameEvidence("not_started", "fixture-live", 100.0, 600.0),
        },
        now=100.0,
    )
    p1 = next(p for p in result.week.teams[0].players if p.player_id == "p1")
    assert p1.projected_remaining is None
    assert "p1" in result.progress_unavailable_player_ids


def test_final_resolution_and_lineup_use_only_observed_points():
    from src.ros.game_day_week import GameEvidence, actual_lineup, resolve_scoring_week

    players = {k: dict(v) for k, v in META.items()}
    players["p1"] = dict(players["p1"], team="SEA")
    players["p2"] = dict(players["p2"], team="MIN")
    roster = dict(_rosters()[0], players=["p1", "p2"], reserve=[], taxi=[])
    matchups = [
        {"roster_id": 1, "matchup_id": 1, "points": 28.0, "players_points": {"p1": 20.0, "p2": 8.0}}
    ]
    result = resolve_scoring_week(
        league_key="fixture",
        league_payload={"settings": {"best_ball": 1, "league_average_match": 1, "num_teams": 1}},
        rosters=[roster],
        matchups=matchups,
        players_meta=players,
        starter_slots=("QB", "RB"),
        estimates={},
        estimate_source=None,
        game_evidence={
            "SEA": GameEvidence("completed", "fixture-final", 200.0),
            "MIN": GameEvidence("completed", "fixture-final", 200.0),
        },
        now=201.0,
    )
    assert result.mode == "final"
    lineup = actual_lineup(result.week.teams[0], result.week.rules, players)
    assert lineup["complete"] is True
    assert lineup["total"] == 28.0
    assert {s["playerId"] for s in lineup["slots"]} == {"p1", "p2"}
    # Completed is definitive evidence nothing further is coming this week
    # (owner decision 2026-09-09) — 0.0, not an unknown None.
    assert all(p.projected_remaining == 0.0 for p in result.week.teams[0].players)


def test_schedule_past_kickoff_without_result_is_unknown_not_live():
    from src.ros.game_day_week import schedule_game_evidence

    rows = [
        {
            "season": 2026,
            "week": 1,
            "game_type": "REG",
            "gameday": "2026-09-09",
            "gametime": "20:20",
            "home_team": "SEA",
            "away_team": "NE",
            "home_score": None,
            "away_score": None,
            "result": None,
        }
    ]
    states = schedule_game_evidence(
        rows, season=2026, week=1, observed_at=100.0, now=2_000_000_000.0
    )
    assert states["SEA"].state == "unknown"
    assert states["NE"].state == "unknown"


def test_the_same_week_transitions_pregame_to_live_to_final_without_double_projection():
    from src.ros.game_day_week import GameEvidence, resolve_scoring_week

    players = {
        "p1": dict(META["p1"], team="SEA"),
        "p2": dict(META["p2"], team="MIN"),
    }
    rosters = [
        {"roster_id": 1, "players": ["p1"]},
        {"roster_id": 2, "players": ["p2"]},
    ]
    league = {"settings": {"best_ball": 1, "league_average_match": 0, "num_teams": 2}}
    estimates = {"ann alpha": 20.0, "bob bravo": 12.0}

    def resolve(matchups, evidence, now):
        return resolve_scoring_week(
            league_key="transition",
            league_payload=league,
            rosters=rosters,
            matchups=matchups,
            players_meta=players,
            starter_slots=("QB", "RB"),
            estimates=estimates,
            estimate_source="fixture",
            game_evidence=evidence,
            now=now,
        )

    pregame = resolve(
        [
            {"roster_id": 1, "matchup_id": 1, "points": 0.0},
            {"roster_id": 2, "matchup_id": 1, "points": 0.0},
        ],
        {
            "SEA": GameEvidence("not_started", "fixture", 50.0, 100.0),
            "MIN": GameEvidence("not_started", "fixture", 50.0, 100.0),
        },
        50.0,
    )
    live = resolve(
        [
            {
                "roster_id": 1,
                "matchup_id": 1,
                "points": 5.0,
                "players_points": {"p1": 5.0},
            },
            {
                "roster_id": 2,
                "matchup_id": 1,
                "points": 0.0,
                "players_points": {"p2": 0.0},
            },
        ],
        {
            "SEA": GameEvidence("in_progress", "fixture", 110.0, 100.0),
            "MIN": GameEvidence("not_started", "fixture", 110.0, 120.0),
        },
        110.0,
    )
    final = resolve(
        [
            {
                "roster_id": 1,
                "matchup_id": 1,
                "points": 20.0,
                "players_points": {"p1": 20.0},
            },
            {
                "roster_id": 2,
                "matchup_id": 1,
                "points": 12.0,
                "players_points": {"p2": 12.0},
            },
        ],
        {
            "SEA": GameEvidence("completed", "fixture", 200.0, 100.0),
            "MIN": GameEvidence("completed", "fixture", 200.0, 120.0),
        },
        200.0,
    )

    assert [pregame.mode, live.mode, final.mode] == ["pregame", "live", "final"]
    assert pregame.week.teams[0].players[0].projected_remaining == 20.0
    assert live.week.teams[0].players[0].points_scored == 5.0
    # kickoff_at=100.0, now=110.0: real, usable game-progress evidence, so
    # p1's remaining is time-prorated (not None, not the full 20.0) and he
    # is not reported as progress-unavailable.
    live_remaining = live.week.teams[0].players[0].projected_remaining
    assert live_remaining is not None
    assert 0.0 < live_remaining < 20.0
    assert live.progress_unavailable_player_ids == ()
    assert final.host_scores == {"1": 20.0, "2": 12.0}
    # Completed is definitive evidence nothing further is coming this week
    # (owner decision 2026-09-09) — 0.0, not an unknown None.
    assert all(
        player.projected_remaining == 0.0 for team in final.week.teams for player in team.players
    )
