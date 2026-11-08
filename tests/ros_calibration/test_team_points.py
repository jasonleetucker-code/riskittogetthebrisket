"""Team-level points calibration library — independent oracles.

Every expected value here is computed by hand, by a textbook formula written out
independently of the code under test, or by numerical integration.  None calls
the function under test twice and compares it with itself.
"""

from __future__ import annotations

import math
import random
import statistics

import pytest

from src.ros_calibration import team_points as tp


def _median(xs):
    return statistics.median(xs)


# ── closed-form scores ───────────────────────────────────────────────────────────────


def test_two_team_matchup_probability_matches_hand_value():
    # A ~ N(110, 3), B ~ N(100, 4): A − B ~ N(10, 5), so P(A > B) = Φ(2).
    phi_2 = 0.9772498680518208  # standard normal table value
    assert tp.win_probability(110.0, 3.0, 100.0, 4.0) == pytest.approx(phi_2, abs=1e-12)
    assert tp.win_probability(100.0, 4.0, 110.0, 3.0) == pytest.approx(1 - phi_2, abs=1e-12)


def test_equal_teams_are_a_coin_flip():
    assert tp.win_probability(300.0, 40.0, 300.0, 25.0) == pytest.approx(0.5, abs=1e-15)


def test_crps_at_the_mean_is_the_textbook_constant():
    # CRPS(N(μ,σ), μ) = σ (2φ(0) − 1/√π) = σ (√(2/π) − 1/√π).
    sigma = 40.0
    expected = sigma * (math.sqrt(2.0 / math.pi) - 1.0 / math.sqrt(math.pi))
    assert tp.crps_normal(300.0, sigma, 300.0) == pytest.approx(expected, rel=1e-12)


def test_crps_matches_numerical_integration_of_the_definition():
    # CRPS = ∫_{-∞}^{y} F(x)² dx + ∫_{y}^{∞} (1 − F(x))² dx, each piece by the midpoint rule
    # (split at y so the step in the indicator never falls inside a cell).
    mu, sigma, y = 250.0, 30.0, 290.0

    def cdf(x):
        return 0.5 * (1 + math.erf((x - mu) / (sigma * math.sqrt(2))))

    def midpoint(fn, a, b, n=100_000):
        h = (b - a) / n
        return sum(fn(a + (i + 0.5) * h) for i in range(n)) * h

    total = midpoint(lambda x: cdf(x) ** 2, mu - 12 * sigma, y) + midpoint(
        lambda x: (1 - cdf(x)) ** 2, y, mu + 12 * sigma
    )
    assert tp.crps_normal(mu, sigma, y) == pytest.approx(total, rel=1e-7)


def test_log_loss_is_clipped_and_symmetric():
    assert tp.log_loss(0.5, 1.0) == pytest.approx(math.log(2))
    assert tp.log_loss(0.0, 1.0) == pytest.approx(-math.log(1e-6))
    assert tp.log_loss(0.8, 0.5) == pytest.approx(-(0.5 * math.log(0.8) + 0.5 * math.log(0.2)))


# ── OLS ──────────────────────────────────────────────────────────────────────────────


def test_simple_regression_prediction_sd_equals_the_textbook_formula():
    xs = [200.0, 250.0, 300.0, 320.0, 360.0, 410.0]
    ys = [260.0, 300.0, 330.0, 350.0, 390.0, 420.0]
    fit = tp.ols([[1.0, x] for x in xs], ys)
    assert fit is not None
    n = len(xs)
    xbar = sum(xs) / n
    ybar = sum(ys) / n
    sxx = sum((x - xbar) ** 2 for x in xs)
    b = sum((x - xbar) * (y - ybar) for x, y in zip(xs, ys)) / sxx
    a = ybar - b * xbar
    s = math.sqrt(sum((y - a - b * x) ** 2 for x, y in zip(xs, ys)) / (n - 2))
    x0 = 380.0
    mean, sd = fit.predict([1.0, x0])
    assert mean == pytest.approx(a + b * x0, rel=1e-12)
    assert sd == pytest.approx(s * math.sqrt(1 + 1 / n + (x0 - xbar) ** 2 / sxx), rel=1e-10)


def test_ols_refuses_a_singular_design_and_zero_dof():
    assert tp.ols([[1.0, 5.0], [1.0, 5.0], [1.0, 5.0]], [1.0, 2.0, 3.0]) is None
    assert tp.ols([[1.0, 1.0], [1.0, 2.0]], [1.0, 2.0]) is None


def _synthetic(alpha, beta, weeks, teams, noise_sd, seed, gamma=None):
    rng = random.Random(seed)
    presim = {w: {t: 150.0 + 20.0 * i + 7.0 * w for i, t in enumerate(teams)} for w in weeks}
    realized = {}
    for w in weeks:
        realized[w] = {}
        for t in teams:
            realized[w][t] = alpha + beta * presim[w][t] + rng.gauss(0.0, noise_sd)
    return presim, realized


def test_affine_rescale_recovers_known_parameters_exactly_without_noise():
    teams = [f"T{i:02d}" for i in range(1, 13)]
    presim, realized = _synthetic(80.0, 0.9, range(1, 6), teams, 0.0, 1)
    out, fit = tp.forecast_affine(tp.RealizedView(realized, 5), tp.PresimView(presim, 5), teams)
    assert fit is not None
    assert fit.coef[0] == pytest.approx(80.0, abs=1e-8)
    assert fit.coef[1] == pytest.approx(0.9, abs=1e-10)
    assert out["T03"][0] == pytest.approx(80.0 + 0.9 * presim[5]["T03"], abs=1e-8)


def test_affine_rescale_recovers_known_parameters_with_noise():
    teams = [f"T{i:02d}" for i in range(1, 13)]
    presim, realized = _synthetic(60.0, 1.1, range(1, 400), teams, 10.0, 7)
    _out, fit = tp.forecast_affine(
        tp.RealizedView(realized, 399), tp.PresimView(presim, 399), teams
    )
    assert fit.coef[1] == pytest.approx(1.1, abs=0.02)
    assert fit.s == pytest.approx(10.0, rel=0.03)


def test_s_model_recovers_presim_and_trailing_mean_weights():
    # y = 20 + 0.5 P + 0.5 M exactly, where M is the team's mean of earlier weeks.
    teams = [f"T{i:02d}" for i in range(1, 13)]
    presim = {
        w: {t: 100.0 + 13.0 * i + 3.0 * (w * i % 5) for i, t in enumerate(teams)}
        for w in range(1, 9)
    }
    realized: dict[int, dict[str, float]] = {
        1: {t: 200.0 + 5.0 * i for i, t in enumerate(teams)},
        2: {},
    }
    realized[2] = {t: 210.0 + 3.0 * i * i % 17 for i, t in enumerate(teams)}
    for w in range(3, 8):
        realized[w] = {}
        for t in teams:
            m = statistics.fmean(realized[j][t] for j in range(1, w))
            realized[w][t] = 20.0 + 0.5 * presim[w][t] + 0.5 * m
    out, fit = tp.forecast_s(tp.RealizedView(realized, 7), tp.PresimView(presim, 7), teams)
    assert fit is not None
    assert fit.coef == pytest.approx((20.0, 0.5, 0.5), abs=1e-6)
    m7 = statistics.fmean(realized[j]["T05"] for j in range(1, 7))
    assert out["T05"][0] == pytest.approx(20.0 + 0.5 * presim[7]["T05"] + 0.5 * m7, abs=1e-6)


# ── baselines ────────────────────────────────────────────────────────────────────────


def test_b1_and_b2_match_hand_computation():
    realized = {1: {"a": 1.0, "b": 2.0}, 2: {"a": 3.0, "b": 6.0}}
    view = tp.RealizedView(realized, 3)
    b1 = tp.forecast_b1(view, ["a", "b"])
    # a: mean 2, sample sd √2; b: mean 4, sample sd √8; × √(1 + 1/2).
    assert b1["a"] == pytest.approx((2.0, math.sqrt(2) * math.sqrt(1.5)))
    assert b1["b"] == pytest.approx((4.0, math.sqrt(8) * math.sqrt(1.5)))
    b2 = tp.forecast_b2(view, ["a", "b"])
    # pooled within-team SS = (1 + 1) + (4 + 4) = 10 on 2 dof → s_p = √5.
    assert b2["a"] == pytest.approx((2.0, math.sqrt(5) * math.sqrt(1.5)))
    assert b2["b"] == pytest.approx((4.0, math.sqrt(5) * math.sqrt(1.5)))


def test_b0_is_league_climatology():
    realized = {1: {"a": 100.0, "b": 200.0}, 2: {"a": 300.0, "b": 400.0}}
    out = tp.forecast_b0(tp.RealizedView(realized, 3), ["a", "b"])
    sd = statistics.stdev([100.0, 200.0, 300.0, 400.0]) * math.sqrt(1.25)
    assert out["a"] == pytest.approx((250.0, sd))
    assert out["b"] == out["a"]


def test_missing_evidence_is_none_never_zero():
    realized = {1: {"a": 300.0}}
    view = tp.RealizedView(realized, 2)
    assert tp.forecast_b1(view, ["a", "b"]) == {"a": None, "b": None}
    assert tp.forecast_b2(view, ["a"]) == {"a": None}
    presim = {1: {"a": 250.0}, 2: {"a": 260.0}}
    out, fit = tp.forecast_affine(view, tp.PresimView(presim, 2), ["a"])
    assert fit is None and out == {"a": None}
    out_s, fit_s = tp.forecast_s(view, tp.PresimView(presim, 2), ["a"])
    assert fit_s is None and out_s == {"a": None}


# ── leakage guard ────────────────────────────────────────────────────────────────────


def test_realized_view_refuses_the_target_week_and_later():
    view = tp.RealizedView({1: {"a": 1.0}, 2: {"a": 2.0}, 3: {"a": 3.0}}, 3)
    assert view.weeks() == [1, 2]
    assert view.team_scores("a") == [1.0, 2.0]
    with pytest.raises(tp.LeakageError):
        view.score(3, "a")
    with pytest.raises(tp.LeakageError):
        view.score(4, "a")
    with pytest.raises(tp.LeakageError):
        view.team_scores("a", before=4)


def test_presim_view_refuses_later_weeks():
    pv = tp.PresimView({1: {"a": 1.0}, 2: {"a": 2.0}, 3: {"a": 3.0}}, 2)
    assert pv.mean(2, "a") == 2.0
    with pytest.raises(tp.LeakageError):
        pv.mean(3, "a")


def test_week_k_forecasts_never_depend_on_week_k_or_later_data():
    teams = [f"T{i:02d}" for i in range(1, 13)]
    presim, realized = _synthetic(70.0, 0.95, range(1, 9), teams, 30.0, 11)
    k = 6
    base, _ = tp.candidate_forecasts(realized, presim, teams, k)
    tampered_realized = {w: dict(v) for w, v in realized.items()}
    tampered_presim = {w: dict(v) for w, v in presim.items()}
    for w in (6, 7, 8):
        for t in teams:
            tampered_realized[w][t] = -1e6  # outcomes of the target week and later
    for w in (7, 8):
        for t in teams:
            tampered_presim[w][t] = 1e6  # inputs of weeks after the target
    again, _ = tp.candidate_forecasts(tampered_realized, tampered_presim, teams, k)
    assert again == base
    assert all(base[arm][t] is not None for arm in base for t in teams)


# ── week scoring and fail-closed ─────────────────────────────────────────────────────


def _week(forecasts=None, pairs=(("a", "b"),)):
    realized = {"a": 120.0, "b": 100.0, "c": 110.0}
    f = forecasts or {"X": {"a": (115.0, 10.0), "b": (100.0, 10.0), "c": (105.0, 10.0)}}
    return tp.WeekInputs(week=5, realized=realized, pairs=list(pairs), forecasts=f)


def test_require_complete_fails_closed_on_missing_or_invalid_forecasts():
    tp.require_complete(_week(), ["X"])
    with pytest.raises(tp.InsufficientEvidence):
        tp.require_complete(_week(), ["Y"])
    with pytest.raises(tp.InsufficientEvidence):
        tp.require_complete(_week({"X": {"a": (115.0, 10.0), "b": (100.0, 10.0)}}), ["X"])
    with pytest.raises(tp.InsufficientEvidence):
        tp.require_complete(
            _week({"X": {"a": (115.0, 0.0), "b": (100.0, 10.0), "c": (1.0, 1.0)}}), ["X"]
        )
    with pytest.raises(tp.InsufficientEvidence):
        tp.require_complete(
            _week({"X": {"a": (math.nan, 1.0), "b": (100.0, 10.0), "c": (1.0, 1.0)}}), ["X"]
        )
    with pytest.raises(tp.InsufficientEvidence):
        tp.require_complete(_week(pairs=(("a", "z"),)), ["X"])


def test_median_probabilities_with_degenerate_distributions():
    dists = {"a": (10.0, 1e-9), "b": (20.0, 1e-9), "c": (30.0, 1e-9)}
    p = tp.median_win_probabilities(dists, _median, draws=200, seed=1)
    # The median of (10, 20, 30) is b's own score: a loses, c wins, b ties (0.5).
    assert p["a"] == pytest.approx(0.0)
    assert p["c"] == pytest.approx(1.0)
    assert p["b"] == pytest.approx(0.5, abs=1e-12)


def test_score_week_records_hand_values():
    recs, _med = tp.score_week(_week(), ["X"], _median, draws=500, seed=3)
    tw = {r.clusters[0][0]: r.values["X"] for r in recs if r.kind == "team_week"}
    assert tw["a"]["err"] == pytest.approx(5.0)
    assert tw["b"]["abs"] == pytest.approx(0.0)
    assert tw["c"]["z2"] == pytest.approx(0.25)
    assert tw["a"]["cov80"] == 1.0  # 120 inside 115 ± 12.8
    h2h = [r for r in recs if r.kind == "h2h"][0]
    assert h2h.clusters == (("a", 0.5), ("b", 0.5))
    p = 0.5 * (1 + math.erf((15.0 / math.sqrt(200.0)) / math.sqrt(2)))
    assert h2h.values["X"]["p"] == pytest.approx(p)
    assert h2h.values["X"]["y"] == 1.0
    med = {r.clusters[0][0]: r.values["X"]["y"] for r in recs if r.kind == "median"}
    assert med == {"a": 1.0, "b": 0.0, "c": 0.5}  # realized median is c's 110


def test_concordance_hand_example():
    share, n = tp.concordance({"a": 3.0, "b": 2.0, "c": 1.0}, {"a": 30.0, "b": 10.0, "c": 20.0})
    assert n == 3 and share == pytest.approx(2 / 3)
    share_t, n_t = tp.concordance({"a": 1.0, "b": 1.0}, {"a": 5.0, "b": 4.0})
    assert n_t == 1 and share_t == 0.5


# ── bootstrap, horizon, gates ────────────────────────────────────────────────────────


def _rec(kind, clusters, a, b):
    return tp.Record(kind, clusters, {"I": {"m": a}, "X": {"m": b}})


def test_bootstrap_point_is_the_plain_mean_and_identical_arms_give_zero():
    recs = [
        _rec("team_week", (("a", 1.0),), 3.0, 1.0),
        _rec("team_week", (("b", 1.0),), 5.0, 1.0),
        _rec("h2h", (("a", 0.5), ("b", 0.5)), 2.0, 2.0),
    ]
    out = tp.paired_cluster_bootstrap(recs, "I", "X", "m", reps=200, seed=1)
    assert out["delta"] == pytest.approx((2.0 + 4.0 + 0.0) / 3)
    same = [_rec("team_week", ((t, 1.0),), 7.0, 7.0) for t in "abc"]
    z = tp.paired_cluster_bootstrap(same, "I", "X", "m", reps=100, seed=1)
    assert z["delta"] == 0.0 and z["lo95"] == 0.0 and z["hi95"] == 0.0


def test_horizon_errors_on_a_two_team_league():
    realized = {7: {"a": 100.0, "b": 90.0}, 8: {"a": 80.0, "b": 110.0}}
    pairs = {7: [("a", "b")], 8: [("a", "b")]}
    forecasts = {7: {"a": (95.0, 10.0), "b": (95.0, 10.0)}}
    med = {7: {"a": 0.5, "b": 0.5}}
    out = tp.horizon_errors(forecasts, med, realized, pairs, _median, last_week=8)
    # Projected PF: 2 × 95 = 190 each; realized a 180, b 200.
    assert out["projectedPfBias"] == pytest.approx(((180 - 190) + (200 - 190)) / 2)
    assert out["projectedPfMae"] == pytest.approx(10.0)
    # Expected wins: 2 weeks × (0.5 h2h + 0.5 median) = 2 each; realized 2 each.
    assert out["expectedWinsBias"] == pytest.approx(0.0)
    assert out["expectedWinsMae"] == pytest.approx(0.0)


def _summary(**kw):
    base = {
        "crps": 30.0,
        "logLossBinary": 0.6,
        "brierBinary": 0.2,
        "mae": 40.0,
        "bias": 0.0,
        "zRms": 1.0,
        "coverage80": 0.8,
        "concordance": 0.7,
    }
    base.update(kw)
    return base


def _delta(lo):
    return {"delta": lo + 1.0, "lo95": lo, "hi95": lo + 2.0}


def test_gates_require_beating_the_incumbent_and_the_other_baseline():
    summaries = {
        "I": _summary(crps=60.0, logLossBinary=1.1, brierBinary=0.3, mae=80.0, concordance=0.72),
        "B1": _summary(crps=32.0, logLossBinary=0.62, mae=41.0),
        "B2": _summary(crps=31.0, logLossBinary=0.61, mae=40.5),
        "A": _summary(),
        "S": _summary(crps=31.5),
    }
    deltas = {
        x: {"crps": _delta(5.0), "ll": _delta(0.2), "abs": _delta(10.0)} for x in tp.CHALLENGERS
    }
    a = tp.evaluate_gates(summaries, deltas, "A")
    assert a["verdict"] == "PASSES_ALL_GATES"
    # B1 beats the incumbent but not B2 on CRPS / LL / MAE.
    b1 = tp.evaluate_gates(summaries, deltas, "B1")
    assert b1["verdict"] == "DOES_NOT_PASS"
    assert {"TG1", "TG2", "TG3"} <= set(b1["failed"])
    # A CI that touches zero against the incumbent fails even when the point is better.
    deltas["A"]["crps"] = _delta(-0.1)
    assert "TG1" in tp.evaluate_gates(summaries, deltas, "A")["failed"]


def test_spread_and_ordering_gates():
    summaries = {
        "I": _summary(crps=60.0, logLossBinary=1.1, brierBinary=0.3, mae=80.0, concordance=0.75),
        "B1": _summary(crps=40.0, logLossBinary=0.7, mae=50.0),
        "B2": _summary(crps=40.0, logLossBinary=0.7, mae=50.0),
        "A": _summary(zRms=1.3, coverage80=0.66, concordance=0.735),
    }
    deltas = {"A": {"crps": _delta(5.0), "ll": _delta(0.2), "abs": _delta(10.0)}}
    v = tp.evaluate_gates(summaries, deltas, "A")
    assert "TG4" in v["failed"]
    assert "TG5" not in v["failed"]  # 0.735 >= 0.75 − 0.02
    summaries["A"]["concordance"] = 0.729
    assert "TG5" in tp.evaluate_gates(summaries, deltas, "A")["failed"]


def test_recommendation_prefers_fewer_parameters_within_the_tie_band():
    summaries = {"A": {"crps": 30.5}, "S": {"crps": 30.0}, "B2": {"crps": 29.4}}
    verdicts = {c: {"verdict": "PASSES_ALL_GATES"} for c in summaries}
    # B2 is best by 0.6 < 1.0 over S and 1.1 over A: A is outside the band, S is within.
    assert tp.recommend(summaries, verdicts) == "S"
    assert tp.recommend(summaries, {c: {"verdict": "DOES_NOT_PASS"} for c in summaries}) is None
