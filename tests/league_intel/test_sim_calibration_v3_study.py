"""Tests for ``scripts/sim_calibration_v3_study.py`` (preregistered, shadow-only v3 challenger).

All on synthetic fixtures (no network, no live data):

* **as-of split**: the week-``h`` fit and its prequential residuals never read week ``h`` or later;
* **the forward mean fit** recovers a known intercept and slope, and falls back to the level-only ratio
  below the floor or on a non-positive slope;
* **re-anchoring** makes predictions invariant to a family-wide multiplicative step in a snapshot;
* **the censoring-corrected location** makes the censored draw's mean equal the predicted mean;
* **the spread search and the shock moments** recover known parameters;
* **production compatibility**: production ``_bestball_weekly_score`` runs the model unmodified, the
  position-free mean raises, and the production loader refuses the challenger file;
* **the output guard** refuses ``data/league_intel/`` before any fetch;
* **win-probability plumbing**: all-play pairs align draw indices, head-to-head is detected by matchup id,
  and the league-week shock stream is shared across rosters.
"""

from __future__ import annotations

import json
import math
import random
import statistics

import pytest

from scripts import sim_calibration_study as v1
from scripts import sim_calibration_v3_study as v3
from src.league_intel import sim_calibration as sc
from src.ros import playoff_sim

# ── fixtures ───────────────────────────────────────────────────────────────────────────────────

TRUE = {"RB": (2.0, 10.0), "LB": (3.0, 6.0)}  # family -> (a, b) in r~ space


def _rows(weeks=range(1, 8), per_family=20, rosters=4, step=None, noise=0.2, seed=5):
    """Appeared priced rows whose points follow y = a + b * r~ (+ noise), r~ = r / week-family mean."""
    rng = random.Random(seed)
    out = []
    for w in weeks:
        for fam, (a, b) in TRUE.items():
            mult = (step or {}).get((w, fam), 1.0)
            rs = [10.0 + 2.0 * i for i in range(per_family)]
            mean_r = statistics.fmean(rs)
            for i, r in enumerate(rs):
                y = (a + b * r / mean_r) * (1.0 + noise * rng.gauss(0, 1))
                out.append(v3.Obs(w, i % rosters, f"{fam}{i}", fam, fam, r * mult, y))
    return out


# ── as-of split ────────────────────────────────────────────────────────────────────────────────


def test_week_h_fit_never_reads_week_h_or_later():
    rows = _rows()
    clean = [o for o in rows if o.week < 6]
    poisoned = clean + [
        v3.Obs(o.week, o.rid, o.pid, o.position, o.family, o.r, 1e6) for o in rows if o.week >= 6
    ]
    anc = v3.anchors(poisoned)
    a, ra = v3.fit_v3(poisoned, 6, anchor=anc)
    b, rb = v3.fit_v3(clean, 6, anchor=anc)
    assert a.to_dict() == b.to_dict()
    assert ra["fitWeeks"] == [1, 2, 3, 4, 5]
    assert max(ra["prequentialWeeks"]) == 5


def test_prequential_residual_for_week_t_uses_only_earlier_weeks():
    rows = _rows(weeks=range(1, 5))
    anc = v3.anchors(rows)
    res = v3.prequential(rows, 5, anc)
    assert {e.week for e in res} == {2, 3, 4}
    # Changing week-4 outcomes must not move week-2 or week-3 residual predictions.
    bumped = [
        v3.Obs(o.week, o.rid, o.pid, o.position, o.family, o.r, o.y * 50 if o.week == 4 else o.y)
        for o in rows
    ]
    res2 = v3.prequential(bumped, 5, anc)
    early = [(e.pid, e.mu) for e in res if e.week < 4]
    early2 = [(e.pid, e.mu) for e in res2 if e.week < 4]
    assert early == early2


# ── mean model ─────────────────────────────────────────────────────────────────────────────────


def test_forward_fit_recovers_intercept_and_slope():
    rows = _rows(noise=0.0)
    fam, _pooled = v3.fit_mean_model(rows, v3.anchors(rows))
    for f, (a, b) in TRUE.items():
        assert fam[f].mode == "ols"
        assert fam[f].a == pytest.approx(a, abs=1e-6)
        assert fam[f].b == pytest.approx(b, abs=1e-6)


def test_floor_and_nonpositive_slope_fall_back_to_level_ratio():
    few = _rows(weeks=[1], per_family=10)  # 10 < 30 player-weeks per family
    fam, _ = v3.fit_mean_model(few, v3.anchors(few))
    assert all(m.mode == "level" and m.a == 0.0 for m in fam.values())
    flat = [v3.Obs(1, 0, f"p{i}", "RB", "RB", 10.0 + i, 20.0 - 0.1 * i) for i in range(40)]
    fam2, _ = v3.fit_mean_model(flat, v3.anchors(flat))
    assert fam2["RB"].mode == "level"
    xs = [o.r / statistics.fmean(p.r for p in flat) for o in flat]
    assert fam2["RB"].b == pytest.approx(sum(o.y for o in flat) / sum(xs))


def test_re_anchoring_absorbs_a_family_wide_snapshot_step():
    base = _rows(noise=0.0)
    stepped = _rows(noise=0.0, step={(w, "LB"): 1.6 for w in range(2, 8)})
    ma, _ = v3.fit_v3(base, 7, anchor=v3.anchors(base))
    mb, _ = v3.fit_v3(stepped, 7, anchor=v3.anchors(stepped))
    pa = v3.for_week(ma, v3.anchors(base), 7)
    pb = v3.for_week(mb, v3.anchors(stepped), 7)
    for r in (12.0, 20.0, 40.0):
        assert pb.mean_for(r * 1.6, "LB") == pytest.approx(pa.mean_for(r, "LB"), rel=1e-9)
    # Without re-anchoring the same step moves the prediction.
    na, _ = v3.fit_v3(stepped, 7, anchor=None)
    nb = v3.for_week(na, None, 7)
    assert nb.mean_for(40.0 * 1.6, "LB") != pytest.approx(pa.mean_for(40.0, "LB"), rel=1e-3)


# ── spread, location, shocks ───────────────────────────────────────────────────────────────────


def test_censoring_correction_makes_the_draw_mean_equal_mu():
    model = v3.V3PointsModel(
        fam_mean={"RB": v3.FamilyMean(0.0, 10.0, "level", 100)},
        anchor_by_family={"RB": 1.0},
        cv_by_family={"RB": 0.9},
    )
    rng = random.Random(3)
    mu = model.mean_for(1.0, "RB")
    xs = [model.draw(1.0, "RB", rng) for _ in range(200_000)]
    assert statistics.fmean(xs) == pytest.approx(mu, rel=0.01)
    c = 0.9
    assert v3.g_censored_mean(c) == pytest.approx(
        v1.norm_cdf(1 / c) + c * v1.norm_pdf(1 / c), rel=1e-12
    )


def test_best_cv_recovers_a_known_spread():
    rng = random.Random(9)
    c_true = 0.6
    pairs = []
    for _ in range(4000):
        mu = rng.uniform(5, 25)
        m = mu / v3.g_censored_mean(c_true)
        pairs.append((mu, max(0.0, rng.gauss(m, m * c_true))))
    c, _ls = v3.best_cv(pairs)
    assert c == pytest.approx(c_true, abs=0.03)


def test_shock_moments_recover_league_and_roster_components():
    rng = random.Random(21)
    tau_l, tau_r = 0.10, 0.20
    resid = []
    for w in range(2, 40):
        sl = rng.gauss(0, tau_l)
        for rid in range(10):
            sr = rng.gauss(0, tau_r)
            for i in range(15):
                mu = 10.0
                m = mu / v3.g_censored_mean(0.5)
                y = mu + m * (sl + sr) + rng.gauss(0, 2.0)
                resid.append(v3.Resid(w, rid, f"{rid}-{i}", "RB", mu, y))
    sh = v3.fit_shocks(resid, {"RB": 0.5}, 0.5)
    assert sh["tauL2"] == pytest.approx(tau_l**2, abs=0.006)
    assert sh["tauR2"] == pytest.approx(tau_r**2, abs=0.01)


def test_shock_streams_share_the_league_component_across_rosters():
    m = v3.V3PointsModel(tau_l2=0.04, tau_r2=0.0)
    a = v3.shock_streams(7, 1, m, 50)
    b = v3.shock_streams(7, 2, m, 50)
    assert a == b  # tau_R = 0: only the league-week shock, identical for every roster
    m2 = v3.V3PointsModel(tau_l2=0.0, tau_r2=0.04)
    assert v3.shock_streams(7, 1, m2, 50) != v3.shock_streams(7, 2, m2, 50)


# ── production compatibility and guards ────────────────────────────────────────────────────────


def _model():
    rows = _rows()
    anc = v3.anchors(rows)
    m, _ = v3.fit_v3(rows, 7, anchor=anc)
    return v3.for_week(m, anc, 7), m


def test_production_bestball_runs_the_v3_model_and_position_free_mean_raises():
    model, _ = _model()
    pool = [
        {"playerId": f"p{i}", "position": pos, "rosValue": 20.0 + i, "fantasyPositions": [pos]}
        for i, pos in enumerate(["RB", "RB", "LB", "LB", "LB"])
    ]
    score = playoff_sim._bestball_weekly_score(pool, ["RB", "LB"], random.Random(1), model)
    assert score > 0
    with pytest.raises(TypeError):
        model.mean_points(10.0)


def test_challenger_file_refused_by_production_loader_and_round_trips(tmp_path):
    model, fitted = _model()
    p = tmp_path / "challenger_v3_week7.json"
    p.write_text(json.dumps(v3.challenger_payload(fitted, {}, 7)), encoding="utf-8")
    assert sc.load_points_model(p).source == "fallback-constants"
    back = v3.load_challenger(p)
    back = v3.for_week(back, None, 7) if back.anchor_by_family is None else back
    assert back.to_dict()["meanByFamily"] == fitted.to_dict()["meanByFamily"]
    assert back.cv_by_family == pytest.approx(fitted.cv_by_family)


def test_evaluate_refuses_league_intel_output_before_any_fetch(monkeypatch):
    def boom(*a, **k):
        raise AssertionError("fetched before the output guard")

    monkeypatch.setattr(v1, "CachedFetcher", boom)
    args = v3.build_parser().parse_args(["evaluate", "--out-dir", str(sc.DATA_DIR), "--offline"])
    with pytest.raises(v1.UnsafeOutputPath):
        v3.evaluate(args)


# ── win-probability plumbing ───────────────────────────────────────────────────────────────────


def test_allplay_aligns_draws_and_detects_head_to_head():
    res = [
        {"week": 7, "rid": 1, "matchupId": 1, "realized": 100.0, "draws": {"M": [1, 2, 3, 4]}},
        {"week": 7, "rid": 2, "matchupId": 1, "realized": 90.0, "draws": {"M": [0, 3, 2, 4]}},
        {"week": 7, "rid": 3, "matchupId": 2, "realized": 95.0, "draws": {"M": [9, 9, 9, 9]}},
    ]
    ap = v3.allplay(res, "M")
    assert len(ap) == 3
    first = ap[0]
    assert first["h2h"] is True
    assert first["p"] == pytest.approx((1 + 0 + 1 + 0.5) / 4)
    assert first["y"] == 1.0
    assert [r["h2h"] for r in ap[1:]] == [False, False]


def test_rank_statistics():
    assert v3.spearman([1, 2, 3, 4], [10, 20, 30, 40]) == pytest.approx(1.0)
    assert v3.kendall_tau([1, 2, 3], [3, 2, 1]) == pytest.approx(-1.0)
    assert v3.kendall_tau([1, 2, 3], [1, 3, 2]) == pytest.approx(1 / 3)


def test_ratio_bootstrap_brackets_the_point_estimate():
    ys = [10.0, 12.0, 8.0, 11.0] * 10
    mus = [10.0] * 40
    out = v3.cluster_ratio_bootstrap(ys, mus, [str(i) for i in range(40)], b=500, seed=1)
    assert out["ci95"][0] <= out["ratio"] <= out["ci95"][1]
    assert out["ratio"] == pytest.approx(1.025)


def test_g6_equivalence_flags_underpowered_wide_interval():
    vals = [0.0, 80.0, -80.0, 60.0, -60.0, 5.0]
    results = [
        {"week": 7, "rid": i, "realized": 100.0, "draws": {v3.V3: [100.0 + v]}}
        for i, v in enumerate(vals)
    ]
    ci = v3.bias_ci(results, v3.V3, b=500)
    assert ci["mean"] == pytest.approx(statistics.fmean(vals))
    lo, hi = ci["ci95"]
    assert lo < v3.G6_BIAS_BAND[0] or hi > v3.G6_BIAS_BAND[1]
    assert math.isfinite(lo) and math.isfinite(hi)
