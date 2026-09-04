"""CE-20 — the canonical league-aware current-week scoring simulation.

Covers the acceptance matrix in `docs/GAME_DAY_PROBABILITY_SPEC.md` §12
and contract rows W1-18..W1-24: one simulation family for both
outcomes, the per-draw league-wide median threshold, exact league
scoring/slot rules, best-ball displacement, every player game state, and
the missing/unavailable semantics that must never read as zero.

Network-free and deterministic — every input is a literal and the sim is
seeded, so these run in the hard gate.
"""

from __future__ import annotations

import pytest

from src.league_intel.sim_calibration import PointsModel
from src.ros.game_day_sim import (
    GameDaySimError,
    LeagueWeekRules,
    PlayerWeek,
    TeamWeek,
    rules_from_league,
    simulate_league_week,
)

# A tight points model so simulated scores are predictable enough to
# assert on without being deterministic.
_MODEL = PointsModel(ros_value_per_point=1.0, cv_by_position={}, default_cv=0.20)

_SF_SLOTS = ("QB", "RB", "RB", "WR", "WR", "TE", "FLEX", "SUPER_FLEX")


def _p(pid, pos, state, scored=None, remaining=None, fpos=()):
    return PlayerWeek(
        player_id=pid,
        position=pos,
        state=state,
        points_scored=scored,
        projected_remaining=remaining,
        fantasy_positions=fpos,
    )


def _full_roster(prefix, base=10.0):
    """A roster that can fill every slot in _SF_SLOTS."""
    spec = [
        ("qb1", "QB"),
        ("qb2", "QB"),
        ("rb1", "RB"),
        ("rb2", "RB"),
        ("rb3", "RB"),
        ("wr1", "WR"),
        ("wr2", "WR"),
        ("wr3", "WR"),
        ("te1", "TE"),
        ("te2", "TE"),
    ]
    return tuple(_p(f"{prefix}_{pid}", pos, "not_started", remaining=base) for pid, pos in spec)


def _rules(**kw):
    base = dict(
        league_key="test_league",
        starter_slots=_SF_SLOTS,
        best_ball=True,
        median_enabled=True,
        team_count=4,
    )
    base.update(kw)
    return LeagueWeekRules(**base)


def _league(n=4, base=10.0, rules=None, draws=400):
    rules = rules or _rules()
    teams = [
        TeamWeek(team_id=f"t{i}", players=_full_roster(f"t{i}", base + i)) for i in range(1, n + 1)
    ]
    opponents = {}
    for i in range(1, n + 1, 2):
        opponents[f"t{i}"] = f"t{i+1}"
        opponents[f"t{i+1}"] = f"t{i}"
    return simulate_league_week(
        rules=rules,
        teams=teams,
        opponents=opponents,
        season=2026,
        week=1,
        draws=draws,
        points_model=_MODEL,
    )


# ── one simulation family, both outcomes ───────────────────────────


def test_both_outcomes_come_from_one_simulation():
    sim = _league()
    for t in sim.teams:
        assert t.win_matchup_pct is not None
        assert t.beat_median_pct is not None
        assert t.beat_median_state == "OK"


def test_probabilities_are_bounded():
    sim = _league()
    for t in sim.teams:
        for v in (t.win_matchup_pct, t.tie_matchup_pct, t.beat_median_pct):
            assert v is not None and 0.0 <= v <= 100.0


def test_a_matchup_pair_win_probabilities_are_complementary():
    """Both sides come from the same draws, so their win/tie shares must
    account for every draw — a property two independent formulas would
    not guarantee."""
    sim = _league()
    by_id = {t.team_id: t for t in sim.teams}
    a, b = by_id["t1"], by_id["t2"]
    total = a.win_matchup_pct + b.win_matchup_pct + a.tie_matchup_pct
    assert total == pytest.approx(100.0, abs=0.5)


def test_beat_median_across_the_league_sums_to_about_half():
    """The threshold is the median OF EACH DRAW, so across a whole league
    roughly half the team-draws clear it. This is the property that
    fails if the threshold is a fixed historical number."""
    sim = _league(n=4)
    assert sum(t.beat_median_pct for t in sim.teams) == pytest.approx(200.0, abs=15.0)


def test_joint_outcomes_sum_to_one_hundred():
    """Spec §8: the four mutually exclusive weekly outcomes come from the
    same draws and must sum to ~100%."""
    sim = _league()
    for t in sim.teams:
        total = t.joint_2_0_pct + t.joint_1_1_h2h_pct + t.joint_1_1_median_pct + t.joint_0_2_pct
        assert total == pytest.approx(100.0, abs=1.0), t.team_id


def test_joint_outcomes_agree_with_the_headline_numbers():
    sim = _league()
    for t in sim.teams:
        assert t.joint_2_0_pct + t.joint_1_1_h2h_pct == pytest.approx(t.win_matchup_pct, abs=1.0)
        assert t.joint_2_0_pct + t.joint_1_1_median_pct == pytest.approx(t.beat_median_pct, abs=1.0)


def test_a_stronger_team_wins_more_often():
    sim = _league()
    by_id = {t.team_id: t for t in sim.teams}
    # t2's roster is built on a higher base than t1's.
    assert by_id["t2"].win_matchup_pct > by_id["t1"].win_matchup_pct


def test_the_simulation_is_deterministic_for_one_seed():
    a, b = _league(), _league()
    assert [t.win_matchup_pct for t in a.teams] == [t.win_matchup_pct for t in b.teams]


# ── median ON / OFF / UNKNOWN ──────────────────────────────────────


def test_median_disabled_is_not_applicable_not_zero():
    sim = _league(rules=_rules(median_enabled=False))
    for t in sim.teams:
        assert t.beat_median_pct is None
        assert t.beat_median_state == "NOT_APPLICABLE"
        assert t.joint_2_0_pct is None


def test_median_unknown_is_unverified_not_disabled():
    """Spec §9: an unknown median setting is STANDINGS_RULE_UNVERIFIED,
    a distinct state from the median game being off."""
    sim = _league(rules=_rules(median_enabled=None))
    for t in sim.teams:
        assert t.beat_median_pct is None
        assert t.beat_median_state == "STANDINGS_RULE_UNVERIFIED"
    assert any("unverified" in n for n in sim.notes)


def test_the_three_median_states_are_distinguishable():
    states = {
        _league(rules=_rules(median_enabled=v)).teams[0].beat_median_state
        for v in (True, False, None)
    }
    assert states == {"OK", "NOT_APPLICABLE", "STANDINGS_RULE_UNVERIFIED"}


# ── missing opponent ───────────────────────────────────────────────


def test_a_missing_opponent_is_unsimulable_not_fifty_percent():
    rules = _rules()
    teams = [
        TeamWeek(team_id="solo", players=_full_roster("solo")),
        TeamWeek(team_id="other", players=_full_roster("other")),
    ]
    sim = simulate_league_week(
        rules=rules,
        teams=teams,
        opponents={"solo": None, "other": None},
        season=2026,
        week=1,
        draws=200,
        points_model=_MODEL,
    )
    for t in sim.teams:
        assert t.win_matchup_pct is None
        assert any("UNSIMULABLE" in n for n in t.notes)
        # The median leg still works — a team with no opponent still has
        # a weekly score.
        assert t.beat_median_pct is not None


# ── player game states ─────────────────────────────────────────────


def _one_team_sim(players, **kw):
    rules = kw.pop("rules", _rules(median_enabled=False))
    teams = [
        TeamWeek(team_id="a", players=tuple(players), **kw),
        TeamWeek(team_id="b", players=_full_roster("b")),
    ]
    return simulate_league_week(
        rules=rules,
        teams=teams,
        opponents={"a": "b", "b": "a"},
        season=2026,
        week=1,
        draws=300,
        points_model=_MODEL,
    )


def test_a_completed_player_is_banked_and_never_redrawn():
    """A finished game is a fact. Re-projecting it would put uncertainty
    on something already known."""
    players = [_p("done", "QB", "completed", scored=25.0)]
    sim = _one_team_sim(players)
    a = next(t for t in sim.teams if t.team_id == "a")
    assert a.points_banked == 25.0
    # One player, one slot, no randomness at all.
    assert a.projected_p10 == a.projected_p90 == 25.0


def test_an_in_progress_player_keeps_banked_points_and_draws_only_the_rest():
    players = [_p("live", "QB", "in_progress", scored=8.0, remaining=10.0)]
    sim = _one_team_sim(players)
    a = next(t for t in sim.teams if t.team_id == "a")
    assert a.points_banked == 8.0
    # Never below what is already banked, and centred above it.
    assert a.projected_p10 >= 8.0
    assert a.projected_mean > 8.0


def test_a_not_started_player_is_fully_uncertain():
    players = [_p("soon", "QB", "not_started", remaining=15.0)]
    sim = _one_team_sim(players)
    a = next(t for t in sim.teams if t.team_id == "a")
    assert a.points_banked == 0.0
    assert a.projected_p90 > a.projected_p10


def test_an_inactive_player_contributes_a_known_zero_not_a_projection():
    """Truthful availability: a player who will not play is a known zero,
    which is a different statement from a missing estimate."""
    players = [_p("out", "QB", "inactive", remaining=20.0)]
    sim = _one_team_sim(players)
    a = next(t for t in sim.teams if t.team_id == "a")
    assert a.projected_mean == 0.0
    assert "out" not in a.unsimulable_player_ids


def test_an_unknown_player_is_excluded_and_reported_not_drawn_as_zero():
    players = [_p("ghost", "QB", "unknown"), _p("real", "QB", "not_started", remaining=12.0)]
    sim = _one_team_sim(players)
    a = next(t for t in sim.teams if t.team_id == "a")
    assert a.unsimulable_player_ids == ("ghost",)
    assert any("excluded rather than drawn as zero" in n for n in a.notes)


def test_a_player_with_no_remaining_estimate_is_unsimulable():
    players = [_p("noproj", "RB", "not_started"), _p("ok", "QB", "not_started", remaining=9.0)]
    sim = _one_team_sim(players)
    a = next(t for t in sim.teams if t.team_id == "a")
    assert "noproj" in a.unsimulable_player_ids


def test_a_bad_state_is_refused():
    with pytest.raises(GameDaySimError, match="state"):
        PlayerWeek(player_id="x", position="QB", state="probably")


# ── best ball vs managed lineup ────────────────────────────────────


def test_best_ball_lets_a_bench_score_displace_a_starter():
    """The non-negotiable best-ball property: a player outside the
    provisional best lineup still matters, because a big draw can
    displace one already in it."""
    rules = LeagueWeekRules(
        league_key="bb",
        starter_slots=("QB",),
        best_ball=True,
        median_enabled=False,
        team_count=2,
    )
    players = [
        _p("starter", "QB", "completed", scored=10.0),
        _p("bench", "QB", "completed", scored=30.0),
    ]
    teams = [
        TeamWeek(team_id="a", players=tuple(players)),
        TeamWeek(team_id="b", players=(_p("x", "QB", "completed", scored=1.0),)),
    ]
    sim = simulate_league_week(
        rules=rules,
        teams=teams,
        opponents={"a": "b", "b": "a"},
        season=2026,
        week=1,
        draws=50,
        points_model=_MODEL,
    )
    a = next(t for t in sim.teams if t.team_id == "a")
    assert a.projected_mean == 30.0, "best ball must take the higher score"


def test_a_managed_league_sums_the_submitted_lineup_only():
    """Re-optimizing a managed lineup would award points nobody could
    have earned."""
    rules = LeagueWeekRules(
        league_key="mg",
        starter_slots=("QB",),
        best_ball=False,
        median_enabled=False,
        team_count=2,
    )
    players = [
        _p("started", "QB", "completed", scored=10.0),
        _p("benched", "QB", "completed", scored=30.0),
    ]
    teams = [
        TeamWeek(team_id="a", players=tuple(players), declared_starters=("started",)),
        TeamWeek(
            team_id="b", players=(_p("x", "QB", "completed", scored=1.0),), declared_starters=("x",)
        ),
    ]
    sim = simulate_league_week(
        rules=rules,
        teams=teams,
        opponents={"a": "b", "b": "a"},
        season=2026,
        week=1,
        draws=50,
        points_model=_MODEL,
    )
    a = next(t for t in sim.teams if t.team_id == "a")
    assert a.projected_mean == 10.0, "managed lineup must not re-optimize"


def test_superflex_flex_te_and_idp_slots_are_all_fillable():
    rules = LeagueWeekRules(
        league_key="idp",
        starter_slots=("QB", "SUPER_FLEX", "FLEX", "TE", "DL", "LB", "DB", "IDP_FLEX"),
        best_ball=True,
        median_enabled=False,
        team_count=2,
    )
    players = [
        _p(f"p{i}", pos, "completed", scored=10.0)
        for i, pos in enumerate(["QB", "QB", "RB", "TE", "DL", "LB", "DB", "LB"])
    ]
    teams = [
        TeamWeek(team_id="a", players=tuple(players)),
        TeamWeek(team_id="b", players=(_p("x", "QB", "completed", scored=1.0),)),
    ]
    sim = simulate_league_week(
        rules=rules,
        teams=teams,
        opponents={"a": "b", "b": "a"},
        season=2026,
        week=1,
        draws=20,
        points_model=_MODEL,
    )
    a = next(t for t in sim.teams if t.team_id == "a")
    assert a.projected_mean == 80.0, "all eight slots must fill at 10.0 each"


def test_a_hybrid_defender_fills_either_slot():
    rules = LeagueWeekRules(
        league_key="idp",
        starter_slots=("DL", "LB"),
        best_ball=True,
        median_enabled=False,
        team_count=2,
    )
    players = [
        _p("hybrid", "DL", "completed", scored=10.0, fpos=("DL", "LB")),
        _p("pure", "DL", "completed", scored=10.0),
    ]
    teams = [
        TeamWeek(team_id="a", players=tuple(players)),
        TeamWeek(team_id="b", players=(_p("x", "DL", "completed", scored=1.0),)),
    ]
    sim = simulate_league_week(
        rules=rules,
        teams=teams,
        opponents={"a": "b", "b": "a"},
        season=2026,
        week=1,
        draws=20,
        points_model=_MODEL,
    )
    a = next(t for t in sim.teams if t.team_id == "a")
    assert a.projected_mean == 20.0, "the hybrid must fill LB so both slots score"


# ── league rules are the REQUESTED league's ────────────────────────


def test_rules_are_read_from_the_league_payload_never_defaulted():
    r = rules_from_league(
        league_key="k",
        league_payload={"settings": {"best_ball": 1, "league_average_match": 1, "num_teams": 12}},
        starter_slots=("QB",),
    )
    assert (r.best_ball, r.median_enabled, r.team_count) == (True, True, 12)

    r2 = rules_from_league(
        league_key="k2",
        league_payload={"settings": {"best_ball": 0, "league_average_match": 0, "num_teams": 10}},
        starter_slots=("QB",),
    )
    assert (r2.best_ball, r2.median_enabled, r2.team_count) == (False, False, 10)


def test_an_absent_median_setting_is_unknown_not_disabled():
    r = rules_from_league(
        league_key="k",
        league_payload={"settings": {"best_ball": 1}},
        starter_slots=("QB",),
    )
    assert r.median_enabled is None


def test_an_absent_best_ball_flag_is_refused_not_defaulted():
    """The lineup semantic decides whether the week is scored by
    re-solving the optimal lineup or summing the submitted one, so
    guessing it would score every team under the wrong rule."""
    with pytest.raises(GameDaySimError, match="best_ball"):
        rules_from_league(
            league_key="k",
            league_payload={"settings": {"league_average_match": 1}},
            starter_slots=("QB",),
        )


def test_a_non_flag_best_ball_value_is_refused():
    with pytest.raises(GameDaySimError, match="not a flag"):
        rules_from_league(
            league_key="k",
            league_payload={"settings": {"best_ball": "maybe"}},
            starter_slots=("QB",),
        )


def test_an_absent_team_count_is_none_not_zero():
    """Descriptive, but still not fabricated — nothing decides on it and
    a 0-team league is not what an absent field means."""
    r = rules_from_league(
        league_key="k",
        league_payload={"settings": {"best_ball": 1}},
        starter_slots=("QB",),
    )
    assert r.team_count is None


def test_no_starter_slots_is_refused():
    with pytest.raises(GameDaySimError, match="starter slots"):
        LeagueWeekRules(
            league_key="k", starter_slots=(), best_ball=True, median_enabled=True, team_count=2
        )


# ── truth metadata ─────────────────────────────────────────────────


def test_every_result_carries_its_provenance():
    sim = _league()
    assert sim.model_version
    assert sim.points_model_source
    assert sim.threshold_semantics == "median"
    assert sim.seed and sim.draws


def test_threshold_semantics_are_declared_unverified():
    """Reconciling 2025 against Sleeper's own records reproduced at most
    3 of 10 teams, because Sleeper's stored historical points no longer
    reproduce its own season totals. Until a human reads the rule off
    the host, this must not claim fidelity."""
    assert _league().threshold_semantics_verified is False


def test_a_fallback_points_model_is_declared():
    sim = _league()
    assert sim.points_model_source == "fallback-constants"
    assert any("FALLBACK" in n for n in sim.notes)


def test_zero_draws_is_refused():
    with pytest.raises(GameDaySimError, match="draws"):
        _league(draws=0)
