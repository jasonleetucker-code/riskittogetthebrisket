"""CW-49 independent oracles — Game Day Win Matchup % and Beat League Median %.

Owner directive 2026-11-07 (sitewide feature verification), workstream CW-49.
Expected values are computed HERE from the documented model, never by calling
``src.ros.game_day_sim`` helpers, and the production simulation
(``simulate_league_week``) is compared against them.

The documented model (``game_day_sim`` / ``sim_calibration.PointsModel``):

* a ``completed`` / ``inactive`` player contributes his banked points, no draw;
* an ``in_progress`` player contributes banked points plus a draw of the
  REMAINDER; a ``not_started`` player a draw of his whole projection;
* a draw is ``max(0, N(r, max(0.5, r * cv)))`` for remaining mean ``r``;
* a managed league sums the declared starters; best ball takes the exact
  optimal lineup of each draw;
* the median leg (when on) compares each team with the average of the middle
  two scores of the SAME draw; exactly on it is a tie, never a win
  (``docs/GAME_DAY_PROBABILITY_SPEC.md`` §§2-3, §8).

Every scenario keeps ``r / sd >= 6`` so the zero floor has probability < 1e-9;
a team score is then a sum of independent normals, so ``P(A beats B) =
Phi((mu_A - mu_B) / sqrt(var_A + var_B))`` (``statistics.NormalDist``).  The
median leg with distinct strengths is integrated numerically (Simpson) over the
order statistics; with identical rosters every ordering of the league's scores
is equally likely, which gives exact combinatorial answers whatever the
per-player distribution is.  Tolerance: ``4.5 * sqrt(p(1-p)/n)`` plus the
2-decimal rounding of published percentages.
"""

from __future__ import annotations

import itertools
import math
from statistics import NormalDist

import pytest

from src.league_intel.sim_calibration import PointsModel
from src.ros.game_day_sim import LeagueWeekRules, PlayerWeek, TeamWeek, simulate_league_week

_Z = 4.5
_PCT_SLACK = 0.006  # percentages are published to 2 dp
_CV = 0.12
_MODEL = PointsModel(ros_value_per_point=1.0, cv_by_position={}, default_cv=_CV, source="oracle")


# ── the independent oracle ─────────────────────────────────────────────


def _player_sd(remaining: float) -> float:
    return max(0.5, remaining * _CV)


def _team_normal(players: list[tuple[str, float | None, float | None]]) -> tuple[float, float]:
    """``(mean, sd)`` of a managed team's score from ``(state, banked, remaining)``."""
    mean, var = 0.0, 0.0
    for state, banked, remaining in players:
        mean += 0.0 if banked is None else banked
        if state in ("in_progress", "not_started"):
            assert remaining is not None and remaining / _player_sd(remaining) >= 6.0
            mean += remaining
            var += _player_sd(remaining) ** 2
    return mean, math.sqrt(var)


def _phi_beats(a: tuple[float, float], b: tuple[float, float]) -> float:
    return 1.0 - NormalDist(a[0] - b[0], math.hypot(a[1], b[1])).cdf(0.0)


def _simpson(f, lo: float, hi: float, steps: int = 2000) -> float:
    h = (hi - lo) / steps
    total = f(lo) + f(hi)
    for k in range(1, steps):
        total += (4 if k % 2 else 2) * f(lo + k * h)
    return total * h / 3.0


def _at_most(probs: list[float], k: int) -> float:
    """P(at most ``k`` of independent events with ``probs`` happen)."""
    dp = [1.0] + [0.0] * len(probs)
    for p in probs:
        for j in range(len(dp) - 1, 0, -1):
            dp[j] = dp[j] * (1.0 - p) + dp[j - 1] * p
        dp[0] *= 1.0 - p
    return sum(dp[: k + 1])


def _median_oracle(dists: dict[str, tuple[float, float]], team: str, opp: str) -> dict[str, float]:
    """Exact (by quadrature) weekly outcomes for ``team`` in an even league.

    With continuous scores, a team beats the average of the middle two exactly
    when it is in the top half; it wins its matchup when its opponent scores
    less.  Integrating over the team's own score ``x``, the other teams are
    independent, each above ``x`` with probability ``1 - F_j(x)``.
    """
    n = len(dists)
    assert n % 2 == 0
    me = NormalDist(*dists[team])
    others = {o: NormalDist(*d) for o, d in dists.items() if o != team}
    slots_above = n // 2 - 1

    def top_half(x):
        return _at_most([1.0 - d.cdf(x) for d in others.values()], slots_above)

    def two_zero(x):
        rest = [1.0 - d.cdf(x) for o, d in others.items() if o != opp]
        return others[opp].cdf(x) * _at_most(rest, slots_above)

    lo, hi = me.mean - 12 * me.stdev, me.mean + 12 * me.stdev
    p_top = _simpson(lambda x: me.pdf(x) * top_half(x), lo, hi)
    p_win = _simpson(lambda x: me.pdf(x) * others[opp].cdf(x), lo, hi)
    p_20 = _simpson(lambda x: me.pdf(x) * two_zero(x), lo, hi)
    return {
        "win": p_win,
        "median": p_top,
        "2_0": p_20,
        "1_1_h2h": p_win - p_20,
        "1_1_med": p_top - p_20,
        "0_2": 1.0 - p_win - p_top + p_20,
    }


def _exchangeable_oracle(n: int) -> dict[str, float]:
    """``n`` i.i.d. teams: every ordering of the week's scores is equally
    likely.  Team 0 plays team 1.  Enumerated over all orderings."""
    counts = dict.fromkeys(("win", "median", "2_0", "1_1_h2h", "1_1_med", "0_2"), 0)
    total = 0
    for order in itertools.permutations(range(n)):
        rank = {t: i for i, t in enumerate(order)}  # 0 = highest score
        win = rank[0] < rank[1]
        med = rank[0] < n // 2
        total += 1
        counts["win"] += win
        counts["median"] += med
        key = "2_0" if win and med else "1_1_h2h" if win else "1_1_med" if med else "0_2"
        counts[key] += 1
    return {k: v / total for k, v in counts.items()}


def _close_pct(engine_pct, exact_p, n, what, *, var=None):
    var = max(exact_p * (1.0 - exact_p) if var is None else var, 0.0)
    tol = 100.0 * _Z * math.sqrt(var / n) + _PCT_SLACK
    assert (
        abs(engine_pct - 100.0 * exact_p) <= tol
    ), f"{what}: engine {engine_pct} vs exact {100 * exact_p:.4f} (tolerance {tol:.4f})"


# ── helpers building production inputs ─────────────────────────────────


def _p(pid, state, *, banked=None, remaining=None, pos="WR"):
    return PlayerWeek(
        player_id=pid,
        position=pos,
        state=state,
        points_scored=banked,
        projected_remaining=remaining,
    )


def _managed_team(tid, spec, bench=()):
    players = tuple(
        _p(f"{tid}_{i}", *s[:1], banked=s[1], remaining=s[2]) for i, s in enumerate(spec)
    )
    bench_players = tuple(
        _p(f"{tid}_bn{i}", *s[:1], banked=s[1], remaining=s[2]) for i, s in enumerate(bench)
    )
    return TeamWeek(
        team_id=tid,
        players=players + bench_players,
        declared_starters=tuple(p.player_id for p in players),
    )


def _managed_rules(team_count, median=True):
    return LeagueWeekRules(
        league_key="oracle_league",
        starter_slots=("QB", "RB", "WR"),
        best_ball=False,
        median_enabled=median,
        team_count=team_count,
    )


def _by_id(sim):
    return {t.team_id: t for t in sim.teams}


# A completed starter, a starter mid-game (banked + remainder) and two who have
# not kicked off, per team.  Bench players are NOT summed in a managed league.
_SPEC = {
    "A": [("not_started", None, 22.0), ("in_progress", 9.0, 8.0), ("completed", 14.0, None)],
    "B": [("not_started", None, 30.0), ("not_started", None, 12.0), ("in_progress", 3.0, 6.0)],
    "C": [("not_started", None, 26.0), ("completed", 21.5, None), ("not_started", None, 7.0)],
    "D": [("in_progress", 11.0, 15.0), ("not_started", None, 20.0), ("completed", 4.0, None)],
}
_BENCH = {"A": [("not_started", None, 40.0)], "C": [("completed", 30.0, None)]}
_OPP = {"A": "B", "B": "A", "C": "D", "D": "C"}


def _four_team_week(draws=40000, seed=4242):
    teams = [_managed_team(t, _SPEC[t], _BENCH.get(t, ())) for t in "ABCD"]
    return simulate_league_week(
        rules=_managed_rules(4),
        teams=teams,
        opponents=_OPP,
        season=2026,
        week=9,
        draws=draws,
        seed=seed,
        points_model=_MODEL,
    )


# ── analytic: win matchup, partial games, projected range ──────────────


def test_win_matchup_and_projected_range_match_the_normal_closed_form():
    sim = _four_team_week()
    n = sim.draws
    out = _by_id(sim)
    dists = {t: _team_normal(_SPEC[t]) for t in "ABCD"}
    # The worked case: A = 22 + (9 + 8) + 14 = 53 ± √(2.64² + 0.96²);
    # B = 30 + 12 + (3 + 6) = 51 ± √(3.6² + 1.44² + 0.72²).
    assert dists["A"][0] == pytest.approx(53.0) and dists["B"][0] == pytest.approx(51.0)
    for t in "ABCD":
        mu, sd = dists[t]
        o = out[t]
        _close_pct(o.win_matchup_pct, _phi_beats(dists[t], dists[_OPP[t]]), n, f"{t} win")
        assert o.tie_matchup_pct == 0.0
        assert abs(o.projected_mean - mu) <= _Z * sd / math.sqrt(n) + 0.006, (t, o.projected_mean)
        # Sample quantiles: SE = sqrt(q(1-q)) / (pdf(x_q) sqrt(n)).
        norm = NormalDist(mu, sd)
        for q, got in ((0.10, o.projected_p10), (0.50, o.projected_p50), (0.90, o.projected_p90)):
            x_q = norm.inv_cdf(q)
            se = math.sqrt(q * (1 - q)) / (norm.pdf(x_q) * math.sqrt(n))
            assert abs(got - x_q) <= _Z * se + 0.006 + sd * 2.0 / n, (t, q, got, x_q)
    # Banked = the declared starters' points already scored — never the bench.
    assert out["A"].points_banked == 23.0
    assert out["B"].points_banked == 3.0
    assert out["C"].points_banked == 21.5
    assert out["D"].points_banked == 15.0


def test_beat_median_and_joint_outcomes_match_order_statistic_quadrature():
    sim = _four_team_week()
    n = sim.draws
    out = _by_id(sim)
    dists = {t: _team_normal(_SPEC[t]) for t in "ABCD"}
    for t in "ABCD":
        exact = _median_oracle(dists, t, _OPP[t])
        o = out[t]
        assert o.beat_median_state == "OK"
        _close_pct(o.beat_median_pct, exact["median"], n, f"{t} beat median")
        _close_pct(o.joint_2_0_pct, exact["2_0"], n, f"{t} 2-0")
        _close_pct(o.joint_1_1_h2h_pct, exact["1_1_h2h"], n, f"{t} 1-1 via H2H")
        _close_pct(o.joint_1_1_median_pct, exact["1_1_med"], n, f"{t} 1-1 via median")
        _close_pct(o.joint_0_2_pct, exact["0_2"], n, f"{t} 0-2")
        assert o.median_tie_pct == 0.0
    # Exactly half the league beats the median in every draw.
    assert sum(out[t].beat_median_pct for t in "ABCD") == pytest.approx(200.0, abs=0.03)


def test_exchangeable_league_gives_the_exact_combinatorial_answers():
    """Six identical best-ball rosters under the real fallback points model
    (wide CVs, zero floor active): every ordering of the week is equally
    likely, so the answers are exact fractions whatever the score shape."""
    slots = ("QB", "RB", "RB", "WR", "WR", "TE", "FLEX", "SUPER_FLEX")
    shape = [
        ("QB", 18.0),
        ("QB", 14.0),
        ("RB", 13.0),
        ("RB", 11.0),
        ("RB", 7.0),
        ("WR", 14.0),
        ("WR", 10.0),
        ("WR", 8.0),
        ("TE", 9.0),
        ("TE", 5.0),
    ]
    teams = [
        TeamWeek(
            team_id=f"t{k}",
            players=tuple(
                _p(f"t{k}_{i}", "not_started", remaining=r, pos=pos)
                for i, (pos, r) in enumerate(shape)
            ),
        )
        for k in range(6)
    ]
    opponents = {"t0": "t1", "t1": "t0", "t2": "t3", "t3": "t2", "t4": "t5", "t5": "t4"}
    rules = LeagueWeekRules(
        league_key="oracle_league",
        starter_slots=slots,
        best_ball=True,
        median_enabled=True,
        team_count=6,
    )
    n = 6000
    sim = simulate_league_week(
        rules=rules,
        teams=teams,
        opponents=opponents,
        season=2026,
        week=9,
        draws=n,
        seed=777,
        points_model=PointsModel(),  # the documented fallback constants
    )
    exact = _exchangeable_oracle(6)
    assert exact["2_0"] == pytest.approx(12 / 30) and exact["1_1_h2h"] == pytest.approx(3 / 30)
    for o in sim.teams:
        _close_pct(o.win_matchup_pct, exact["win"], n, f"{o.team_id} win")
        _close_pct(o.beat_median_pct, exact["median"], n, f"{o.team_id} median")
        _close_pct(o.joint_2_0_pct, exact["2_0"], n, f"{o.team_id} 2-0")
        _close_pct(o.joint_1_1_h2h_pct, exact["1_1_h2h"], n, f"{o.team_id} 1-1 h2h")
        _close_pct(o.joint_1_1_median_pct, exact["1_1_med"], n, f"{o.team_id} 1-1 median")
        _close_pct(o.joint_0_2_pct, exact["0_2"], n, f"{o.team_id} 0-2")
    # Pairwise exact: in every draw the two sides of a matchup split it.
    out = _by_id(sim)
    for a, b in (("t0", "t1"), ("t2", "t3"), ("t4", "t5")):
        total = out[a].win_matchup_pct + out[b].win_matchup_pct + out[a].tie_matchup_pct
        assert total == pytest.approx(100.0, abs=0.02)


def test_a_two_team_league_median_is_the_matchup_itself():
    """With two teams the middle-two average is the average of both scores, so
    a team beats the median exactly when it wins: the two legs must agree draw
    for draw, and the split-result buckets must be empty."""
    spec = {
        "A": [("not_started", None, 24.0), ("in_progress", 6.0, 10.0)],
        "B": [("not_started", None, 28.0), ("completed", 9.5, None)],
    }
    teams = [_managed_team(t, spec[t]) for t in "AB"]
    n = 30000
    sim = simulate_league_week(
        rules=_managed_rules(2),
        teams=teams,
        opponents={"A": "B", "B": "A"},
        season=2026,
        week=9,
        draws=n,
        seed=99,
        points_model=_MODEL,
    )
    out = _by_id(sim)
    dists = {t: _team_normal(spec[t]) for t in "AB"}
    for t, opp in (("A", "B"), ("B", "A")):
        o = out[t]
        assert o.beat_median_pct == o.win_matchup_pct
        assert o.joint_1_1_h2h_pct == 0.0 and o.joint_1_1_median_pct == 0.0
        _close_pct(o.win_matchup_pct, _phi_beats(dists[t], dists[opp]), n, f"{t} win")


def test_a_finished_week_is_certain_on_both_legs():
    """Every player completed: the outcome is a fact, published as 100 / 0,
    and the projected range collapses onto the banked total."""
    finals = {"A": 100.0, "B": 90.0, "C": 80.0, "D": 70.0}  # median = 85
    teams = [_managed_team(t, [("completed", finals[t], None)]) for t in "ABCD"]
    sim = simulate_league_week(
        rules=_managed_rules(4),
        teams=teams,
        opponents=_OPP,
        season=2026,
        week=9,
        draws=500,
        seed=1,
        points_model=_MODEL,
    )
    out = _by_id(sim)
    expected = {
        "A": (100.0, 100.0, "joint_2_0_pct"),
        "B": (0.0, 100.0, "joint_1_1_median_pct"),
        "C": (100.0, 0.0, "joint_1_1_h2h_pct"),
        "D": (0.0, 0.0, "joint_0_2_pct"),
    }
    for t, (win, med, bucket) in expected.items():
        o = out[t]
        assert (o.win_matchup_pct, o.beat_median_pct, getattr(o, bucket)) == (win, med, 100.0)
        assert o.projected_p10 == o.projected_p50 == o.projected_p90 == finals[t]
    assert sim.median_distribution["p10"] == sim.median_distribution["p90"] == 85.0


def test_a_finished_week_on_the_median_is_a_certain_tie_never_a_win():
    """B and C finish exactly on the middle-two average (90): each has a
    certain median TIE (half a result), so neither beats the median and
    neither week lands in a win/loss joint bucket."""
    finals = {"A": 100.0, "B": 90.0, "C": 90.0, "D": 70.0}
    teams = [_managed_team(t, [("completed", finals[t], None)]) for t in "ABCD"]
    sim = simulate_league_week(
        rules=_managed_rules(4),
        teams=teams,
        opponents=_OPP,
        season=2026,
        week=9,
        draws=200,
        seed=1,
        points_model=_MODEL,
    )
    out = _by_id(sim)
    for t in "BC":
        o = out[t]
        assert (o.beat_median_pct, o.median_tie_pct) == (0.0, 100.0)
        joint = (o.joint_2_0_pct, o.joint_1_1_h2h_pct, o.joint_1_1_median_pct, o.joint_0_2_pct)
        assert joint == (0.0, 0.0, 0.0, 0.0)
    assert (out["A"].beat_median_pct, out["D"].beat_median_pct) == (100.0, 0.0)


def test_best_ball_takes_the_better_of_two_players_closed_form():
    """One QB slot, best ball: team A rosters two QBs and scores the larger
    draw.  P(A wins) = 1 - ∫ F1(y) F2(y) f_B(y) dy; E[A] is Clark's exact mean
    of a maximum of two normals; QB1 is in A's final lineup with probability
    P(X1 > X2)."""
    m1, m2, mb = 20.0, 19.0, 21.0
    s1, s2, sb = (_player_sd(m) for m in (m1, m2, mb))
    teams = [
        TeamWeek(
            team_id="A",
            players=(
                _p("a_qb1", "not_started", remaining=m1, pos="QB"),
                _p("a_qb2", "not_started", remaining=m2, pos="QB"),
            ),
        ),
        TeamWeek(team_id="B", players=(_p("b_qb1", "not_started", remaining=mb, pos="QB"),)),
    ]
    rules = LeagueWeekRules(
        league_key="oracle_league",
        starter_slots=("QB",),
        best_ball=True,
        median_enabled=False,
        team_count=2,
    )
    n = 30000
    sim = simulate_league_week(
        rules=rules,
        teams=teams,
        opponents={"A": "B", "B": "A"},
        season=2026,
        week=9,
        draws=n,
        seed=31,
        points_model=_MODEL,
    )
    out = _by_id(sim)
    x1, x2, y = NormalDist(m1, s1), NormalDist(m2, s2), NormalDist(mb, sb)
    p_a = 1.0 - _simpson(lambda v: x1.cdf(v) * x2.cdf(v) * y.pdf(v), mb - 12 * sb, mb + 12 * sb)
    _close_pct(out["A"].win_matchup_pct, p_a, n, "A (best of two QBs) win")
    theta = math.hypot(s1, s2)
    alpha = (m1 - m2) / theta
    std = NormalDist()
    e_max = m1 * std.cdf(alpha) + m2 * std.cdf(-alpha) + theta * std.pdf(alpha)
    e_max2 = (
        (m1**2 + s1**2) * std.cdf(alpha)
        + (m2**2 + s2**2) * std.cdf(-alpha)
        + (m1 + m2) * theta * std.pdf(alpha)
    )
    sd_max = math.sqrt(e_max2 - e_max**2)
    assert abs(out["A"].projected_mean - e_max) <= _Z * sd_max / math.sqrt(n) + 0.006
    _close_pct(out["A"].player_lineup_pct["a_qb1"], std.cdf(alpha), n, "QB1 in lineup")
    assert out["A"].player_lineup_pct["a_qb1"] + out["A"].player_lineup_pct["a_qb2"] == (
        pytest.approx(100.0, abs=0.02)
    )
    assert out["A"].beat_median_state == "NOT_APPLICABLE" and out["A"].beat_median_pct is None


# ── metamorphic properties ─────────────────────────────────────────────


def test_renaming_teams_changes_nothing_and_reordering_only_reshuffles_noise():
    base = _by_id(_four_team_week(draws=20000, seed=5))
    rename = {"A": "w", "B": "x", "C": "y", "D": "z"}
    teams = [
        TeamWeek(team_id=rename[t], players=tm.players, declared_starters=tm.declared_starters)
        for t, tm in ((t, _managed_team(t, _SPEC[t], _BENCH.get(t, ()))) for t in "ABCD")
    ]
    renamed = _by_id(
        simulate_league_week(
            rules=_managed_rules(4),
            teams=teams,
            opponents={rename[a]: rename[b] for a, b in _OPP.items()},
            season=2026,
            week=9,
            draws=20000,
            seed=5,
            points_model=_MODEL,
        )
    )
    for t, new in rename.items():
        a, b = base[t], renamed[new]
        assert (a.win_matchup_pct, a.beat_median_pct, a.projected_mean, a.joint_2_0_pct) == (
            b.win_matchup_pct,
            b.beat_median_pct,
            b.projected_mean,
            b.joint_2_0_pct,
        )
    # Reversing the team order hands every draw to a different team; both
    # orderings must still agree with the closed form.
    reordered = _by_id(
        simulate_league_week(
            rules=_managed_rules(4),
            teams=list(reversed(teams)),
            opponents={rename[a]: rename[b] for a, b in _OPP.items()},
            season=2026,
            week=9,
            draws=20000,
            seed=5,
            points_model=_MODEL,
        )
    )
    dists = {t: _team_normal(_SPEC[t]) for t in "ABCD"}
    for t, new in rename.items():
        exact = _phi_beats(dists[t], dists[_OPP[t]])
        _close_pct(reordered[new].win_matchup_pct, exact, 20000, f"{t} reordered")


def test_more_banked_points_never_lower_either_probability():
    """A completed player draws nothing, so the draws are identical with and
    without extra banked points: team A's score rises by the same amount in
    every draw, the league median by at most that much, so A's win and
    beat-median counts cannot fall — draw for draw, hence exactly."""
    before = _by_id(_four_team_week(draws=20000, seed=8))
    spec = dict(_SPEC)
    spec["A"] = [s if s[0] != "completed" else ("completed", s[1] + 2.5, None) for s in _SPEC["A"]]
    teams = [_managed_team(t, spec[t], _BENCH.get(t, ())) for t in "ABCD"]
    after = _by_id(
        simulate_league_week(
            rules=_managed_rules(4),
            teams=teams,
            opponents=_OPP,
            season=2026,
            week=9,
            draws=20000,
            seed=8,
            points_model=_MODEL,
        )
    )
    assert after["A"].win_matchup_pct >= before["A"].win_matchup_pct
    assert after["A"].beat_median_pct >= before["A"].beat_median_pct
    assert after["B"].win_matchup_pct <= before["B"].win_matchup_pct
    # And it moved: 2.5 points is a visible shift in a ~5-point-sd matchup.
    assert after["A"].win_matchup_pct > before["A"].win_matchup_pct + 5.0
