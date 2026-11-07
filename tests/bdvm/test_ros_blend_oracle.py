"""Independent oracle for BDVM in-season ROS math (CW-49; BDVM §5.13 / §8.4).

Expected values are hand-computed from the documented formulas:

    w         = n_prior / (n_prior + weeks_played)       (n_prior 6 offense / 8 IDP)
    mu_post   = w * mu_prior + (1 - w) * mu_recent
    ros_value = sum over non-bye weeks of
                clamp(p_active, 0, 1) * E[max(0, X - R)] * (1 + playoff_weight if playoff)
    X ~ Normal(mu, sigma), E[max(0, X-R)] evaluated by NUMERICAL INTEGRATION
    here (Simpson on the density), never by the engine's closed form.

The spec constants 6 and 8 are pinned literally and the shipped parameter set is
asserted equal to them.
"""

from __future__ import annotations

import math

import pytest

from src.bdvm.params import load_param_set
from src.bdvm.ros import RosWeek, blend_ros_mu, ros_projection_weight, ros_value

PARAMS = load_param_set("params_v1")
N_PRIOR = {False: 6.0, True: 8.0}


def _o_w(weeks, idp):
    return N_PRIOR[idp] / (N_PRIOR[idp] + max(0.0, weeks))


def _o_mu(prior, recent, weeks, idp):
    w = _o_w(weeks, idp)
    return w * prior + (1 - w) * recent


def _o_surplus(mu, sigma, r, n=20000):
    """E[max(0, X - R)] by composite Simpson over [R, mu + 12 sigma]."""
    if sigma <= 1e-9:
        return max(0.0, mu - r)
    lo, hi = r, max(r, mu + 12 * sigma)
    if hi <= lo:
        return 0.0
    h = (hi - lo) / n

    def f(x):
        z = (x - mu) / sigma
        return (x - r) * math.exp(-0.5 * z * z) / (sigma * math.sqrt(2 * math.pi))

    s = f(lo) + f(hi)
    for i in range(1, n):
        s += f(lo + i * h) * (4 if i % 2 else 2)
    return s * h / 3


def test_param_set_matches_documented_priors():
    assert PARAMS["ros"]["n_prior_offense"] == 6.0
    assert PARAMS["ros"]["n_prior_idp"] == 8.0


@pytest.mark.parametrize("idp", [False, True])
@pytest.mark.parametrize("weeks", [0, 1, 3, 4, 8, 17])
def test_weight_matches_hand_formula(idp, weeks):
    assert ros_projection_weight(weeks, is_idp=idp, params=PARAMS) == pytest.approx(
        _o_w(weeks, idp), abs=1e-15
    )


def test_hand_computed_posteriors():
    # offense, 4 weeks: w = 6/10 = 0.6 -> 0.6*12 + 0.4*20 = 15.2
    assert blend_ros_mu(12.0, 20.0, 4, is_idp=False, params=PARAMS) == pytest.approx(15.2)
    # IDP, 8 weeks: w = 8/16 = 0.5 -> midpoint of 10 and 4 = 7.0
    assert blend_ros_mu(10.0, 4.0, 8, is_idp=True, params=PARAMS) == pytest.approx(7.0)
    # offense, 6 weeks: w = 0.5 exactly
    assert blend_ros_mu(8.0, 16.0, 6, is_idp=False, params=PARAMS) == pytest.approx(12.0)


@pytest.mark.parametrize("idp", [False, True])
@pytest.mark.parametrize("prior,recent", [(12.0, 20.0), (18.5, 7.25), (0.0, 9.0), (-1.0, 3.0)])
@pytest.mark.parametrize("weeks", [0, 2, 5, 10])
def test_posterior_matches_oracle(idp, prior, recent, weeks):
    assert blend_ros_mu(prior, recent, weeks, is_idp=idp, params=PARAMS) == pytest.approx(
        _o_mu(prior, recent, weeks, idp), abs=1e-12
    )


# ---- metamorphic properties -------------------------------------------------


@pytest.mark.parametrize("idp", [False, True])
def test_preseason_is_an_exact_noop(idp):
    assert blend_ros_mu(13.37, 99.0, 0, is_idp=idp, params=PARAMS) == 13.37
    assert ros_projection_weight(0, is_idp=idp, params=PARAMS) == 1.0


@pytest.mark.parametrize("idp", [False, True])
def test_identical_prior_and_recent_leave_the_posterior_unchanged(idp):
    for weeks in (0, 1, 7, 16):
        assert blend_ros_mu(11.1, 11.1, weeks, is_idp=idp, params=PARAMS) == pytest.approx(11.1)


@pytest.mark.parametrize("idp", [False, True])
def test_more_weeks_move_the_posterior_monotonically_toward_recent_form(idp):
    for prior, recent in ((12.0, 20.0), (20.0, 12.0)):
        path = [blend_ros_mu(prior, recent, w, is_idp=idp, params=PARAMS) for w in range(0, 18)]
        dist = [abs(m - recent) for m in path]
        assert dist == sorted(dist, reverse=True) and dist[-1] < dist[0]
        weights = [ros_projection_weight(w, is_idp=idp, params=PARAMS) for w in range(0, 18)]
        assert weights == sorted(weights, reverse=True) and weights[0] == 1.0
        for m in path:  # a convex combination never leaves the interval
            assert min(prior, recent) - 1e-12 <= m <= max(prior, recent) + 1e-12


def test_idp_trusts_its_preseason_prior_longer_than_offense():
    for weeks in (1, 4, 10):
        assert ros_projection_weight(weeks, is_idp=True, params=PARAMS) > ros_projection_weight(
            weeks, is_idp=False, params=PARAMS
        )


def test_negative_weeks_are_treated_as_preseason():
    assert ros_projection_weight(-3, is_idp=False, params=PARAMS) == 1.0


def test_sigma_shrink_factor_sqrt_w_is_in_unit_interval_and_falls_with_evidence():
    # service.py shrinks sigma by sqrt(w_prior); pin the oracle numbers it must reproduce.
    sq = [math.sqrt(_o_w(w, False)) for w in (0, 4, 12)]
    assert (
        sq[0] == 1.0
        and sq[1] == pytest.approx(math.sqrt(0.6))
        and sq[2] == pytest.approx(math.sqrt(1 / 3))
    )
    assert sq == sorted(sq, reverse=True)


# ---- ros_value --------------------------------------------------------------


def _wk(n, bye=None, playoffs=()):
    return [
        RosWeek(week=w, is_bye=(w == bye), p_active=1.0, is_league_playoff=(w in playoffs))
        for w in range(1, n + 1)
    ]


@pytest.mark.parametrize(
    "mu,sigma,r", [(15, 4, 10), (10, 4, 10), (6, 3, 10), (20, 0.0, 12), (9, 5, 9)]
)
def test_per_game_surplus_matches_numerical_integration(mu, sigma, r):
    got = ros_value(mu, sigma, r, _wk(1))
    assert got == pytest.approx(_o_surplus(mu, sigma, r), rel=1e-6, abs=1e-6)


def test_known_closed_points():
    # mu == R: E[max(0, X-R)] = sigma / sqrt(2 pi)
    assert ros_value(10, 4, 10, _wk(1)) == pytest.approx(4 / math.sqrt(2 * math.pi), rel=1e-6)
    # sigma -> 0: plain positive part
    assert ros_value(14, 0.0, 10, _wk(1)) == pytest.approx(4.0)
    assert ros_value(8, 0.0, 10, _wk(1)) == 0.0


def test_weekly_sum_skips_byes_clamps_availability_and_weights_playoffs():
    mu, sigma, r = 14.0, 4.0, 10.0
    g = _o_surplus(mu, sigma, r)
    weeks = [
        RosWeek(1, False, 1.0),
        RosWeek(2, True, 1.0),  # bye contributes nothing
        RosWeek(3, False, 0.5),
        RosWeek(4, False, 1.7),  # clamped to 1
        RosWeek(5, False, -0.4),  # clamped to 0
        RosWeek(6, False, 1.0, is_league_playoff=True),
    ]
    expect = g * (1.0 + 0.5 + 1.0 + 0.0 + (1 + 0.8))
    assert ros_value(mu, sigma, r, weeks, playoff_weight=0.8) == pytest.approx(expect, rel=1e-6)


def test_metamorphic_properties_of_ros_value():
    base = ros_value(13, 4, 10, _wk(14))
    assert base == pytest.approx(14 * _o_surplus(13, 4, 10), rel=1e-6)  # linear in weeks
    assert ros_value(13, 4, 10, _wk(14, bye=5)) == pytest.approx(
        13 * _o_surplus(13, 4, 10), rel=1e-6
    )
    assert ros_value(13, 4, 10, []) == 0.0  # nothing remaining -> exactly zero, not a default
    # higher mean or lower replacement never lowers the value; surplus is nonnegative
    assert ros_value(14, 4, 10, _wk(14)) > base > ros_value(12, 4, 10, _wk(14))
    assert ros_value(13, 4, 9, _wk(14)) > base
    assert ros_value(2, 1, 30, _wk(14)) >= 0.0
    # option value: more uncertainty never hurts a starter near replacement (convex payoff)
    assert ros_value(10, 6, 10, _wk(14)) > ros_value(10, 2, 10, _wk(14))
