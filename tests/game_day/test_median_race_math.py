"""Live Median Race — the median mathematics, pinned to the canonical draw loop.

The owner requirement (2026-09-26): the league median is ENDOGENOUS to every
league-wide simulation draw.  For draw d, M(d) is the median of every team's
S(t, d) in that same draw, and

    P(team t beats the median) = P[ S(t, d) > M(d) ]

with an exact equality a TIE (the host's rule), never a win.  The published
median distribution comes from the M(d) series and each team's margin from
D(t, d) = S(t, d) - M(d) — never from team projected means.

The central test spies on the canonical ``_threshold`` call INSIDE the real
simulation, captures every draw's full league-wide scores and its M(d), and
independently re-derives every published number from those same draws.
"""

from __future__ import annotations

import statistics

import pytest

from src.league_intel.sim_calibration import PointsModel
from src.ros import game_day_sim
from src.ros.game_day_sim import LeagueWeekRules, PlayerWeek, TeamWeek, simulate_league_week

_MODEL = PointsModel(ros_value_per_point=1.0, cv_by_position={}, default_cv=0.35)
_SLOTS = ("QB", "RB", "WR", "FLEX")


def _p(pid, pos, state, scored=None, remaining=None):
    return PlayerWeek(
        player_id=pid,
        position=pos,
        state=state,
        points_scored=scored,
        projected_remaining=remaining,
    )


def _team(i, base):
    return TeamWeek(
        team_id=f"t{i}",
        players=(
            _p(f"t{i}_qb", "QB", "not_started", remaining=base + 4),
            _p(f"t{i}_rb", "RB", "in_progress", scored=3.0, remaining=base),
            _p(f"t{i}_wr", "WR", "not_started", remaining=base - 1),
            _p(f"t{i}_wr2", "WR", "completed", scored=base / 2),
        ),
    )


def _rules(n, median_enabled=True):
    return LeagueWeekRules(
        league_key="median_race",
        starter_slots=_SLOTS,
        best_ball=True,
        median_enabled=median_enabled,
        team_count=n,
    )


def _pairs(n):
    opp = {}
    for i in range(1, n + 1, 2):
        if i + 1 <= n:
            opp[f"t{i}"], opp[f"t{i+1}"] = f"t{i+1}", f"t{i}"
        else:
            opp[f"t{i}"] = None
    return opp


def _simulate(n=6, draws=300, median_enabled=True, bases=None):
    bases = bases or [8.0 + 1.5 * i for i in range(n)]
    teams = [_team(i + 1, b) for i, b in enumerate(bases)]
    return simulate_league_week(
        rules=_rules(n, median_enabled),
        teams=teams,
        opponents=_pairs(n),
        season=2026,
        week=4,
        draws=draws,
        points_model=_MODEL,
    )


@pytest.fixture
def spied(monkeypatch):
    """Every canonical threshold call: (the draw's league-wide scores, M(d))."""
    calls: list[tuple[list[float], float]] = []
    real = game_day_sim._threshold

    def spy(scores, semantics=game_day_sim.THRESHOLD_SEMANTICS):
        m = real(scores, semantics)
        calls.append((list(scores), m))
        return m

    monkeypatch.setattr(game_day_sim, "_threshold", spy)
    return calls


def _pct(k, n):
    return round(100.0 * k / n, 2)


def test_every_draw_recomputes_the_median_from_all_teams(spied):
    _simulate(n=6, draws=300)
    assert len(spied) == 300  # once per draw, never a fixed cutoff
    assert all(len(scores) == 6 for scores, _ in spied)  # every team, same draw
    assert len({m for _, m in spied}) > 50  # it moves with each draw's scores


def test_published_numbers_are_exactly_the_same_draw_outcomes(spied):
    sim = _simulate(n=6, draws=300)
    order = [t.team_id for t in sim.teams]  # teams are scored in input order
    for idx, team in enumerate(sim.teams):
        s = [scores[idx] for scores, _ in spied]
        m = [thr for _, thr in spied]
        wins = sum(1 for a, b in zip(s, m) if a > b)
        ties = sum(1 for a, b in zip(s, m) if a == b)
        d = [a - b for a, b in zip(s, m)]
        assert team.beat_median_pct == _pct(wins, 300), order[idx]
        assert team.median_tie_pct == _pct(ties, 300)
        assert team.median_margin_mean == round(statistics.fmean(d), 2)
        assert team.median_margin_p50 == round(statistics.median(d), 2)


def test_median_distribution_comes_from_m_of_d_not_team_means(spied):
    sim = _simulate(n=6, draws=300)
    m = sorted(thr for _, thr in spied)
    dist = sim.median_distribution
    assert dist == {
        "mean": round(statistics.fmean(m), 2),
        "p10": round(m[int(0.10 * 299)], 2),
        "p50": round(statistics.median(m), 2),
        "p90": round(m[int(0.90 * 299)], 2),
        "draws": 300,
    }
    assert dist["p10"] <= dist["p50"] <= dist["p90"]


def test_margin_is_paired_not_a_difference_of_means():
    sim = _simulate(n=6, draws=400)
    for team in sim.teams:
        naive = round(team.projected_mean - sim.median_distribution["mean"], 2)
        # Mathematically equal in expectation (linearity), so they agree to
        # rounding — but the published figure is the paired one, and its
        # median (p50) is NOT recoverable from the means at all.
        assert abs(team.median_margin_mean - naive) <= 0.02
    assert any(
        t.median_margin_p50 != round(t.projected_p50 - sim.median_distribution["p50"], 2)
        for t in sim.teams
    )


def _fixed(scores):
    n = len(scores)
    teams = [
        TeamWeek(team_id=f"t{i}", players=(_p(f"p{i}", "QB", "completed", scored=float(sc)),))
        for i, sc in enumerate(scores, start=1)
    ]
    return simulate_league_week(
        rules=LeagueWeekRules(
            league_key="fixed",
            starter_slots=("QB",),
            best_ball=True,
            median_enabled=True,
            team_count=n,
        ),
        teams=teams,
        opponents=_pairs(n),
        season=2026,
        week=4,
        draws=5,
        points_model=_MODEL,
    )


def test_an_exact_median_score_is_a_tie_never_a_win():
    sim = _fixed([10, 20, 20, 30])  # even: M = (20 + 20) / 2 = 20
    by = {t.team_id: t for t in sim.teams}
    assert by["t2"].beat_median_pct == 0.0 and by["t2"].median_tie_pct == 100.0
    assert by["t4"].beat_median_pct == 100.0 and by["t4"].median_tie_pct == 0.0
    assert sim.median_distribution["p50"] == 20.0


def test_even_league_median_is_the_middle_two_average():
    sim = _fixed([0, 10, 20, 100])
    assert sim.median_distribution["mean"] == 15.0  # not the arithmetic mean 32.5


def test_odd_league_median_is_the_middle_score():
    sim = _fixed([10, 20, 30])
    by = {t.team_id: t for t in sim.teams}
    assert sim.median_distribution["p50"] == 20.0
    assert by["t2"].median_tie_pct == 100.0
    assert by["t3"].beat_median_pct == 100.0


def test_a_real_zero_is_zero_not_missing():
    sim = _fixed([0, 12, 18, 25])
    by = {t.team_id: t for t in sim.teams}
    assert by["t1"].projected_mean == 0.0
    assert by["t1"].beat_median_pct == 0.0
    assert by["t1"].median_margin_mean == -15.0


@pytest.mark.parametrize(
    "enabled,state", [(False, "NOT_APPLICABLE"), (None, "STANDINGS_RULE_UNVERIFIED")]
)
def test_no_median_leg_fabricates_nothing(enabled, state):
    sim = _simulate(n=4, draws=50, median_enabled=enabled)
    assert sim.median_distribution is None
    for t in sim.teams:
        assert t.beat_median_state == state
        assert t.beat_median_pct is None
        assert t.median_margin_mean is None and t.median_margin_p50 is None
        assert t.median_tie_pct is None


def test_probabilities_stay_in_range():
    sim = _simulate(n=8, draws=200)
    for t in sim.teams:
        assert 0.0 <= t.beat_median_pct <= 100.0
        assert 0.0 <= t.median_tie_pct <= 100.0
        assert t.beat_median_pct + t.median_tie_pct <= 100.0


def test_existing_outputs_are_unchanged_by_the_new_summaries(monkeypatch):
    # The summaries only READ the draw loop: switching them off (by
    # simulating a league with no median leg) must not move any number the
    # median does not own.
    on = _simulate(n=6, draws=200, median_enabled=True)
    off = _simulate(n=6, draws=200, median_enabled=False)
    for a, b in zip(on.teams, off.teams):
        assert a.projected_mean == b.projected_mean
        assert a.win_matchup_pct == b.win_matchup_pct
        assert a.player_lineup_pct == b.player_lineup_pct
