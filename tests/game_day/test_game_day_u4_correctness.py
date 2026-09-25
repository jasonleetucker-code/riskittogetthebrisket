"""Game Day U4 — resolver + simulation correctness on SYNTHETIC inputs.

Every case here is hand-built and says so.  They pin the mechanics the
replay (``test_game_day_replay.py``) cannot isolate: lineup choice vs sum on
negative / zero points, completed players displaced through FLEX and
SUPER_FLEX, observed-clock mapping for every status, the labelled wall-time
fallback, the kickoff-locked weekly baseline, and the first-down imputation.
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from src.nfl_data import live_game_state as lgs
from src.nfl_data.first_down_rate import (
    FIRST_DOWNS_PER_YARD,
    imputed_sleeper_first_down_bonus,
)
from src.ros.game_day_estimates import (
    BASIS_PRESEASON,
    BASIS_WEEKLY,
    resolve_game_day_estimates,
)
from src.ros.game_day_sim import (
    LeagueWeekRules,
    PlayerWeek,
    TeamWeek,
    simulate_league_week,
)
from src.ros.game_day_week import (
    GameEvidence,
    ObservedSlate,
    _ASSUMED_GAME_DURATION_SECONDS,
    actual_lineup,
    observed_game_evidence,
    resolve_scoring_week,
)
from src.ros.lineup import OBJECTIVE_REALIZED_POINTS, RosterPlayer, solve_optimal_assignment
from src.ros.sleeper_weekly_projections import FetchResult

GOLDEN = Path(__file__).resolve().parents[1] / "league_intel" / "fixtures"


def _rules(slots, *, best_ball=True, median=False, teams=2):
    return LeagueWeekRules(
        league_key="synthetic",
        starter_slots=tuple(slots),
        best_ball=best_ball,
        median_enabled=median,
        team_count=teams,
    )


# ── Lineup: choice and sum use the same number ──────────────────────────────


def test_negative_bench_player_never_displaces_a_zero_starter():
    """SYNTHETIC: two kickers, one -1.5 (missed FGs), one 0.0 (no attempts)."""
    pool = [
        RosterPlayer("k_neg", "neg", "K", -1.5),
        RosterPlayer("k_zero", "zero", "K", 0.0),
    ]
    # `k_neg` sorts first by id: under the clamped objective both read 0.0
    # and the tie-break seats the -1.5.  That is the defect.
    clamped = solve_optimal_assignment(pool, ["K"])
    assert clamped[0].player_id == "k_neg"
    raw = solve_optimal_assignment(pool, ["K"], objective=OBJECTIVE_REALIZED_POINTS)
    assert raw[0].player_id == "k_zero"


def test_a_negative_player_still_fills_a_slot_nobody_else_can():
    """Best ball fills every fillable slot, even at a negative score."""
    pool = [RosterPlayer("k_neg", "neg", "K", -1.5), RosterPlayer("qb", "qb", "QB", 20.0)]
    raw = solve_optimal_assignment(pool, ["QB", "K"], objective=OBJECTIVE_REALIZED_POINTS)
    assert {p.player_id for p in raw.values()} == {"qb", "k_neg"}


def test_realized_objective_reproduces_host_awarded_best_ball_totals():
    """The 10 real 2025 Sleeper best-ball team-weeks still match 10/10."""
    cases = json.loads((GOLDEN / "golden_bestball_lineups.json").read_text())
    assert len(cases) == 10
    for case in cases:
        roster = [
            RosterPlayer(
                pid,
                pid,
                info["position"],
                info["points"],
                fantasy_positions=tuple(info["fantasyPositions"]),
            )
            for pid, info in case["players"].items()
        ]
        chosen = solve_optimal_assignment(
            roster, list(case["starterSlots"]), objective=OBJECTIVE_REALIZED_POINTS
        )
        total = sum(case["players"][p.player_id]["points"] for p in chosen.values())
        assert total == pytest.approx(case["hostPoints"], abs=0.02)
        filled = [s for s in case["hostStarters"] if s != "0"]
        assert len(chosen) == len(filled)


def test_game_day_sim_scores_with_raw_points():
    """A completed -1.5 bench K must not be summed over a completed 0.0 K."""
    team = TeamWeek(
        "a",
        (
            PlayerWeek("k_neg", "K", "completed", points_scored=-1.5),
            PlayerWeek("k_zero", "K", "completed", points_scored=0.0),
        ),
    )
    other = TeamWeek("b", (PlayerWeek("k2", "K", "completed", points_scored=1.0),))
    sim = simulate_league_week(
        rules=_rules(["K"]),
        teams=[team, other],
        opponents={"a": "b", "b": "a"},
        season=2026,
        week=3,
        draws=20,
    )
    a = next(t for t in sim.teams if t.team_id == "a")
    assert a.points_banked == 0.0
    assert a.projected_mean == 0.0
    assert a.player_lineup_pct == {"k_neg": 0.0, "k_zero": 100.0}


# ── Completed players can still be displaced (FLEX / SUPER_FLEX cascade) ──


def test_completed_player_is_displaced_through_flex_by_a_later_player():
    """SYNTHETIC: RB_A 8 (done), RB_B 5 (done), WR_C to play, mean 30."""
    team = TeamWeek(
        "a",
        (
            PlayerWeek("rb_a", "RB", "completed", points_scored=8.0),
            PlayerWeek("rb_b", "RB", "completed", points_scored=5.0),
            PlayerWeek("wr_c", "WR", "not_started", points_scored=0.0, projected_remaining=30.0),
        ),
    )
    opp = TeamWeek("b", (PlayerWeek("rb_x", "RB", "completed", points_scored=1.0),))
    sim = simulate_league_week(
        rules=_rules(["RB", "FLEX"]),
        teams=[team, opp],
        opponents={"a": "b", "b": "a"},
        season=2026,
        week=3,
        draws=400,
    )
    a = next(t for t in sim.teams if t.team_id == "a")
    pct = a.player_lineup_pct
    assert pct["rb_a"] == 100.0  # 8 always beats 5 for the RB slot
    assert pct["wr_c"] > 90.0  # usually outscores 5 -> takes FLEX
    assert pct["rb_b"] < 10.0  # the completed 5.0 is displaced
    assert pct["wr_c"] + pct["rb_b"] == pytest.approx(100.0)
    # Banked points are never lost: every draw's total is >= today's lineup.
    assert a.projected_p10 >= a.points_banked == 13.0


def test_super_flex_cascade_moves_a_completed_qb_and_benches_a_completed_wr():
    """SYNTHETIC: QB1 12 (done), WR 6 (done), QB2 to play (mean 25)."""
    team = TeamWeek(
        "a",
        (
            PlayerWeek("qb1", "QB", "completed", points_scored=12.0),
            PlayerWeek("wr", "WR", "completed", points_scored=6.0),
            PlayerWeek("qb2", "QB", "in_progress", points_scored=4.0, projected_remaining=21.0),
        ),
    )
    opp = TeamWeek("b", (PlayerWeek("qbx", "QB", "completed", points_scored=10.0),))
    sim = simulate_league_week(
        rules=_rules(["QB", "SUPER_FLEX"]),
        teams=[team, opp],
        opponents={"a": "b", "b": "a"},
        season=2026,
        week=3,
        draws=400,
    )
    a = next(t for t in sim.teams if t.team_id == "a")
    assert a.player_lineup_pct["qb1"] == 100.0
    assert a.player_lineup_pct["wr"] < 5.0
    assert a.player_lineup_pct["qb2"] > 95.0
    # The in-progress QB's banked 4.0 is kept and only 21.0 is drawn.
    assert a.projected_mean == pytest.approx(12.0 + 4.0 + 21.0, rel=0.08)


def test_all_completed_week_has_no_variance_and_no_leverage():
    team = TeamWeek(
        "a", (PlayerWeek("q", "QB", "completed", points_scored=20.0, nfl_game_id="g1"),)
    )
    opp = TeamWeek("b", (PlayerWeek("r", "QB", "completed", points_scored=10.0, nfl_game_id="g1"),))
    sim = simulate_league_week(
        rules=_rules(["QB"]),
        teams=[team, opp],
        opponents={"a": "b", "b": "a"},
        season=2026,
        week=3,
        draws=50,
    )
    a = next(t for t in sim.teams if t.team_id == "a")
    assert a.projected_p10 == a.projected_p90 == a.projected_mean == 20.0
    assert a.win_matchup_pct == 100.0
    assert a.game_leverage == []  # nothing left to play anywhere


def test_leverage_names_the_game_that_decides_the_matchup():
    """SYNTHETIC: a 10-point lead with one live game each side; g_live matters."""
    team = TeamWeek(
        "a",
        (
            PlayerWeek("a1", "QB", "completed", points_scored=10.0, nfl_game_id="g_done"),
            PlayerWeek(
                "a2", "RB", "not_started", 0.0, projected_remaining=10.0, nfl_game_id="g_live"
            ),
        ),
    )
    opp = TeamWeek(
        "b",
        (
            PlayerWeek("b1", "QB", "completed", points_scored=10.0, nfl_game_id="g_done"),
            PlayerWeek(
                "b2", "RB", "not_started", 0.0, projected_remaining=10.0, nfl_game_id="g_live"
            ),
        ),
    )
    sim = simulate_league_week(
        rules=_rules(["QB", "RB"]),
        teams=[team, opp],
        opponents={"a": "b", "b": "a"},
        season=2026,
        week=3,
        draws=400,
    )
    a = next(t for t in sim.teams if t.team_id == "a")
    games = {g["gameId"]: g for g in a.game_leverage}
    assert set(games) == {"g_live"}  # g_done has nothing left to play
    # Up to sampling noise at the median: a2 beating b2 IS the matchup.
    assert games["g_live"]["leverage"] == pytest.approx(100.0, abs=3.0)
    assert games["g_live"]["teamPlayerIds"] == ["a2"]


# ── Observed game state -> evidence ────────────────────────────────────────

NOW = datetime(2026, 9, 25, 1, 50, tzinfo=timezone.utc)


def _obs(name, state, period=None, clock=None, home=7, away=17, kickoff=None, age_s=30.0):
    return lgs.ObservedGameState(
        espn_event_id="1",
        home_team="ATL",
        away_team="GB",
        home_team_raw="ATL",
        away_team_raw="GB",
        kickoff=kickoff or datetime(2026, 9, 25, 0, 15, tzinfo=timezone.utc),
        espn_state=state,
        status_name=name,
        phase=lgs.STATUS_NAME_TO_PHASE.get(name, lgs.PHASE_UNKNOWN),
        phase_reason=None if name in lgs.STATUS_NAME_TO_PHASE else f"unmapped_status_name:{name}",
        period=period,
        clock_seconds=clock,
        display_clock=None,
        status_detail=None,
        completed=None,
        home_score=home,
        away_score=away,
        observed_at=NOW - timedelta(seconds=age_s),
    )


def _slate(*games, season=2026, week=3, ok=True):
    return lgs.ScoreboardSnapshot(
        observed_at=NOW,
        enabled=True,
        source_url="fixture",
        http_status=200,
        error=None if ok else "fetch_failed:Timeout",
        season=season,
        season_type=2,
        week=week,
        games=tuple(games),
    )


def _evidence(obs, **kw):
    slate = observed_game_evidence(
        _slate(obs), schedule_rows=[], season=2026, week=3, now=NOW.timestamp(), **kw
    )
    return slate, slate.evidence.get("GB")


@pytest.mark.parametrize(
    ("obs", "state", "fraction", "reason"),
    [
        (
            _obs("STATUS_SCHEDULED", "pre", kickoff=NOW + timedelta(hours=1)),
            "not_started",
            1.0,
            None,
        ),
        (_obs("STATUS_END_PERIOD", "in", 1, 0.0), "in_progress", 0.75, None),
        (_obs("STATUS_HALFTIME", "in", 2, 0.0), "in_progress", 0.5, None),
        (_obs("STATUS_IN_PROGRESS", "in", 3, 450.0), "in_progress", 0.375, None),
        (_obs("STATUS_IN_PROGRESS", "in", 5, 300.0), "in_progress", None, "overtime"),
        (_obs("STATUS_END_PERIOD", "in", 4, 0.0, 20, 20), "in_progress", None, "overtime_possible"),
        (_obs("STATUS_END_PERIOD", "in", 4, 0.0, 20, 27), "in_progress", 0.0, None),
        (_obs("STATUS_FINAL", "post", 4, 0.0), "completed", 0.0, None),
        (_obs("STATUS_DELAYED", "in", 3, 400.0), "in_progress", None, "delayed"),
        (_obs("STATUS_POSTPONED", "pre"), "not_started", None, "postponed"),
        (_obs("STATUS_SOMETHING_NEW", "in", 2, 100.0), "unknown", None, None),
    ],
)
def test_observed_status_maps_to_state_and_fraction(obs, state, fraction, reason):
    _slate_obj, ev = _evidence(obs)
    assert ev.state == state
    assert ev.remaining_fraction == (pytest.approx(fraction) if fraction is not None else None)
    if reason is not None:
        assert ev.remaining_reason == reason
    assert ev.source == "espn:scoreboard"


def test_a_stale_observation_withholds_in_game_progress():
    slate, ev = _evidence(_obs("STATUS_IN_PROGRESS", "in", 3, 450.0, age_s=600.0))
    assert slate.stale
    assert ev.state == "in_progress"
    assert ev.remaining_fraction is None
    assert ev.remaining_reason == "stale_live_state"


def test_a_stale_final_is_still_final():
    slate, ev = _evidence(_obs("STATUS_FINAL", "post", 4, 0.0, age_s=3600.0))
    assert ev.state == "completed"
    assert ev.remaining_fraction == 0.0


def test_a_scoreboard_for_another_week_is_refused_whole():
    slate = observed_game_evidence(
        _slate(_obs("STATUS_HALFTIME", "in", 2, 0.0), week=4),
        schedule_rows=[],
        season=2026,
        week=3,
        now=NOW.timestamp(),
    )
    assert slate.state == "week_mismatch"
    assert slate.evidence == {}


def test_disabled_and_failed_feeds_carry_no_evidence():
    off = lgs.ScoreboardSnapshot(
        observed_at=NOW, enabled=False, source_url=None, http_status=None, error="flag_disabled"
    )
    assert observed_game_evidence(
        off, schedule_rows=[], season=2026, week=3, now=NOW.timestamp()
    ) == ObservedSlate({}, "disabled", "flag_disabled", None)
    failed = observed_game_evidence(
        _slate(ok=False), schedule_rows=[], season=2026, week=3, now=NOW.timestamp()
    )
    assert failed.state == "unavailable" and failed.evidence == {}


def test_observed_game_joins_the_schedule_game_id():
    rows = [
        {
            "season": 2026,
            "week": 3,
            "game_type": "REG",
            "gameday": "2026-09-24",
            "gametime": "20:15",
            "home_team": "ATL",
            "away_team": "GB",
        }
    ]
    slate = observed_game_evidence(
        _slate(_obs("STATUS_HALFTIME", "in", 2, 0.0)),
        schedule_rows=rows,
        season=2026,
        week=3,
        now=NOW.timestamp(),
    )
    assert slate.evidence["GB"].game_id == "2026_3_GB_ATL"
    assert slate.unmatched_game_ids == ()


# ── Resolver: remaining production ────────────────────────────────────────

LEAGUE = {"settings": {"best_ball": 1, "league_average_match": 0, "num_teams": 2}}
META = {
    "p1": {"full_name": "Ann Alpha", "position": "QB", "fantasy_positions": ["QB"], "team": "GB"},
    "p2": {"full_name": "Bob Bravo", "position": "RB", "fantasy_positions": ["RB"], "team": "MIN"},
}


def _resolve(evidence, *, points=None, now=10_000.0):
    return resolve_scoring_week(
        league_key="synthetic",
        league_payload=LEAGUE,
        rosters=[{"roster_id": 1, "players": ["p1", "p2"]}, {"roster_id": 2, "players": []}],
        matchups=[
            {
                "roster_id": 1,
                "matchup_id": 1,
                "points": 6.0,
                "players_points": points or {"p1": 6.0, "p2": 0.0},
            },
            {"roster_id": 2, "matchup_id": 1, "points": 0.0, "players_points": {}},
        ],
        players_meta=META,
        starter_slots=["QB", "RB"],
        estimates_by_player_id={"p1": 20.0, "p2": 12.0},
        estimate_source="synthetic",
        game_evidence=evidence,
        now=now,
    )


def _ev(state, **kw):
    return GameEvidence(state, "espn:scoreboard", 9_000.0, **kw)


def test_observed_clock_scales_the_baseline_and_never_subtracts_actuals():
    res = _resolve(
        {
            "GB": _ev("in_progress", phase="IN_PROGRESS", remaining_fraction=0.5, game_id="g"),
            "MIN": _ev("not_started", phase="SCHEDULED", remaining_fraction=1.0, game_id="h"),
        }
    )
    p1 = next(p for p in res.week.teams[0].players if p.player_id == "p1")
    assert p1.points_scored == 6.0
    assert p1.projected_remaining == 10.0  # 20 x 0.5, NOT 20 - 6
    assert res.remaining_basis["p1"] == "observed_clock"
    assert res.remaining_basis["p2"] == "pregame_full_baseline"
    assert p1.nfl_game_id == "g"


def test_observed_overtime_is_withheld_with_its_reason_not_invented():
    res = _resolve(
        {
            "GB": _ev("in_progress", phase="IN_PROGRESS", remaining_reason="overtime"),
            "MIN": _ev("not_started", phase="SCHEDULED", remaining_fraction=1.0),
        }
    )
    assert res.progress_unavailable_reasons == {"p1": "overtime"}
    p1 = next(p for p in res.week.teams[0].players if p.player_id == "p1")
    assert p1.projected_remaining is None and p1.points_scored == 6.0


def test_wall_time_fallback_is_labelled_and_cannot_finish_a_game():
    kickoff = 1_000.0
    half = _resolve(
        {"GB": _ev("in_progress", kickoff_at=kickoff), "MIN": _ev("not_started")},
        now=kickoff + _ASSUMED_GAME_DURATION_SECONDS / 2,
    )
    assert half.remaining_basis["p1"] == "wall_time_fallback"
    p1 = next(p for p in half.week.teams[0].players if p.player_id == "p1")
    assert p1.projected_remaining == pytest.approx(10.0)
    over = _resolve(
        {"GB": _ev("in_progress", kickoff_at=kickoff), "MIN": _ev("not_started")},
        now=kickoff + _ASSUMED_GAME_DURATION_SECONDS + 60,
    )
    assert over.progress_unavailable_reasons["p1"] == "wall_time_exhausted_without_observed_final"


def test_pregame_current_lineup_is_not_an_all_zero_tie_break():
    res = _resolve(
        {
            "GB": _ev("not_started", phase="SCHEDULED", remaining_fraction=1.0),
            "MIN": _ev("not_started", phase="SCHEDULED", remaining_fraction=1.0),
        },
        points={"p1": 0.0, "p2": 0.0},
    )
    lineup = actual_lineup(res.week.teams[0], res.week.rules, META)
    assert lineup["lineupState"] == "not_started"
    assert lineup["slots"] == []
    assert lineup["total"] == 0.0
    assert set(lineup["notStartedPlayerIds"]) == {"p1", "p2"}


# ── Weekly baselines: kickoff lock, imputation, fallback ─────────────────

CARD = {"pass_yd": 0.04, "pass_td": 4.0, "rec": 1.0, "rec_yd": 0.1, "bonus_fd_qb": 0.67}
KICK = datetime(2026, 9, 27, 17, 0, tzinfo=timezone.utc)


def _row(pid, stats, *, team="BAL", position="QB"):
    return {
        "player_id": pid,
        "game_id": "g1",
        "team": team,
        "opponent": "DAL",
        "company": "rotowire",
        "season": "2026",
        "week": 3,
        "season_type": "regular",
        "updated_at": 1_790_000_000_000,
        "player": {"position": position, "fantasy_positions": [position]},
        "stats": stats,
    }


def _fetch(rows, at):
    return FetchResult("ok", 2026, 3, "fixture", at.isoformat(), tuple(rows))


def _estimates(fetches, *, meta=None, preseason=None, card=CARD):
    meta = meta or {"q": {"full_name": "Quinn Brady", "position": "QB", "team": "BAL"}}
    return resolve_game_day_estimates(
        player_ids=list(meta),
        players_meta=meta,
        scoring_settings=card,
        season=2026,
        week=3,
        now=(KICK + timedelta(hours=1)).timestamp(),
        preseason_by_name=preseason or {},
        preseason_source="synthetic:preseason" if preseason else None,
        weekly_fetches=fetches,
        weekly_state="ok",
        kickoffs_by_team={"BAL": KICK.timestamp()},
    )


def test_weekly_baseline_is_locked_at_kickoff_and_first_downs_are_ours():
    pre = _fetch([_row("q", {"pass_yd": 250.0, "pass_td": 2.0})], KICK - timedelta(minutes=5))
    in_game = _fetch([_row("q", {"pass_yd": 90.0, "pass_td": 0.5})], KICK + timedelta(minutes=30))
    est = _estimates([pre, in_game]).by_player_id["q"]
    assert est.basis == BASIS_WEEKLY
    assert est.provider_points == pytest.approx(250 * 0.04 + 2 * 4.0)  # the PRE read
    fd = 250.0 * FIRST_DOWNS_PER_YARD["QB"]
    assert est.imputed_keys == ("bonus_fd_qb",)
    assert est.imputed_points == pytest.approx(fd * 0.67)
    assert est.points == pytest.approx(est.provider_points + est.imputed_points)
    assert est.kickoff_locked is True


def test_a_player_seen_only_after_kickoff_falls_back_labelled():
    in_game = _fetch([_row("q", {"pass_yd": 250.0})], KICK + timedelta(minutes=30))
    est = _estimates([in_game], preseason={"quinn brady": 17.5})
    assert est.by_player_id["q"].basis == BASIS_PRESEASON
    assert est.by_player_id["q"].points == 17.5
    assert est.weekly_counts["noPreKickoffObservation"] == 1


def test_no_basis_at_all_is_missing_not_zero():
    in_game = _fetch([_row("q", {"pass_yd": 250.0})], KICK + timedelta(minutes=30))
    assert "q" not in _estimates([in_game]).by_player_id


def test_ambiguous_preseason_name_is_refused():
    meta = {
        "q": {"full_name": "Josh Allen", "position": "QB", "team": "BUF"},
        "d": {"full_name": "Josh Allen", "position": "LB", "team": "JAX"},
    }
    est = _estimates([], meta=meta, preseason={"josh allen": 22.0})
    assert est.by_player_id == {}
    assert set(est.ambiguous_name_player_ids) == {"q", "d"}


def test_a_card_paying_provider_fd_keys_refuses_the_weekly_line():
    """Provider *_fd keys are yards/10, not first downs: never priced."""
    card = dict(CARD, pass_fd=1.0)
    pre = _fetch([_row("q", {"pass_yd": 250.0, "pass_fd": 25.0})], KICK - timedelta(minutes=5))
    est = _estimates([pre], card=card)
    assert "q" not in est.by_player_id
    assert est.weekly_counts["refusedProviderFirstDownKeys"] == 1


def test_first_down_bonus_imputation_reuses_the_canonical_fit():
    key, count, points = imputed_sleeper_first_down_bonus(
        {"rush_yd": 60.0, "rec_yd": 40.0}, "RB", {"bonus_fd_rb": 1.0}
    )
    assert key == "bonus_fd_rb"
    assert count == pytest.approx(100.0 * FIRST_DOWNS_PER_YARD["RB"])
    assert points == pytest.approx(count)
    assert imputed_sleeper_first_down_bonus({"rush_yd": 60.0}, "RB", {}) is None
    assert imputed_sleeper_first_down_bonus({"bonus_fd_rb": 3.0}, "RB", {"bonus_fd_rb": 1}) is None
    assert imputed_sleeper_first_down_bonus({"idp_tkl": 5.0}, "LB", {"bonus_fd_lb": 1}) is None


# ── Further weekly sources: one vote per provider family ───────────────


def _fake_adapter(family_value: float, *, source_key: str):
    """SYNTHETIC adapter: prices player "q" at ``family_value``."""
    from src.ros.game_day_estimates import WeeklyBaseline

    def adapter(fetches, *, provider_family, **_kw):
        return (
            {
                "q": WeeklyBaseline(
                    player_id="q",
                    source_key=source_key,
                    provider_family=provider_family,
                    basis=f"weekly:{source_key}",
                    position="QB",
                    season=2026,
                    points=family_value,
                    provider_points=family_value,
                    observed_at=(KICK - timedelta(minutes=1)).isoformat(),
                    locked=True,
                )
            },
            {"baselines": 1},
            None,
        )

    return adapter


def _with_extra_source(monkeypatch, key, family, value):
    from src.ros import game_day_estimates as gde

    real_census = gde._census
    monkeypatch.setitem(gde.WEEKLY_SOURCE_ADAPTERS, key, _fake_adapter(value, source_key=key))

    def census(k):
        if k == key:
            return {"providerFamily": family, "evidenceClass": "PROJECTION_MODEL"}
        return real_census(k)

    monkeypatch.setattr(gde, "_census", census)


def _estimates_multi(extra_key):
    pre = _fetch([_row("q", {"pass_yd": 250.0, "pass_td": 2.0})], KICK - timedelta(minutes=5))
    return resolve_game_day_estimates(
        player_ids=["q"],
        players_meta={"q": {"full_name": "Quinn Brady", "position": "QB", "team": "BAL"}},
        scoring_settings=CARD,
        season=2026,
        week=3,
        now=(KICK + timedelta(hours=1)).timestamp(),
        weekly_fetches_by_source={"sleeperWeeklyProjections": [pre], extra_key: ["fixture"]},
        kickoffs_by_team={"BAL": KICK.timestamp()},
    )


def test_a_same_family_second_source_never_votes_twice(monkeypatch):
    """SYNTHETIC: another RotoWire product is the SAME evidence as RotoWire via Sleeper."""
    _with_extra_source(monkeypatch, "rotowireDirectFake", "rotowire", 99.0)
    est = _estimates_multi("rotowireDirectFake")
    q = est.by_player_id["q"]
    assert q.basis == BASIS_WEEKLY  # the first adapter's single family vote
    assert q.families == ("rotowire",)
    assert q.provider_points == pytest.approx(250 * 0.04 + 2 * 4.0)
    assert est.weekly_counts["sameFamilyDuplicates"] == 1


def test_independent_families_combine_through_the_ensemble_owner(monkeypatch):
    """SYNTHETIC: a second, independent family -> equal-family mean, not a sum."""
    _with_extra_source(monkeypatch, "otherVendorFake", "otherVendor", 10.0)
    est = _estimates_multi("otherVendorFake")
    q = est.by_player_id["q"]
    rotowire = 250 * 0.04 + 2 * 4.0 + 250.0 * FIRST_DOWNS_PER_YARD["QB"] * 0.67
    assert q.basis == "weekly:ensemble"
    assert q.families == ("otherVendor", "rotowire")
    assert q.points == pytest.approx((rotowire + 10.0) / 2)
