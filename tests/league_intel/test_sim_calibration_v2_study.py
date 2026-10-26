"""Tests for ``scripts/sim_calibration_v2_study.py`` (preregistered, shadow-only v2 challenger).

Pinned here, all on synthetic fixtures (no network, no live data):

* **split integrity**: no holdout or confirmation week reaches the v2 scale fit, CV fit or raw-family
  table, and a leak is refused rather than filtered silently;
* **the output-path guard**: v2 writes through v1's ``assert_safe_output``, refuses
  ``data/league_intel/`` before any fetch, and its challenger file cannot be served by the production
  loader even if copied into place;
* **the per-family fit**: each family's scale is the owner's fit on that family alone, the floor sends
  a sparse family to the pooled scale, the CV is v1's D2 within-player statistic, and the draw uses the
  family's scale and CV;
* **the gates**: SC-G1 reads PIT coverage, and its literal v1 reading is reported but never gates.
"""

from __future__ import annotations

import json
import random
import statistics

import pytest

from scripts import sim_calibration_study as v1
from scripts import sim_calibration_v2_study as v2
from src.league_intel import sim_calibration as sc
from src.ros import playoff_sim

# ── fixtures ───────────────────────────────────────────────────────────────────────────────────

#: Synthetic truth: points = rosValue / K_TRUE[family], with multiplicative within-player noise.
K_TRUE = {"QB": 1.2, "RB": 2.0, "LB": 1.5}
CV_TRUE = {"QB": 0.30, "RB": 0.60, "LB": 0.45}


def _pw(season, week, pid, pos, fam, pts, status=v1.APPEARED):
    return v1.PlayerWeek(season, week, pid, pos, status, pts, fam)


def _synthetic(players_per_family: int = 12, holdout_value: float = 1000.0):
    """Fit weeks with known per-family scale and CV; holdout / confirmation weeks at an absurd value."""
    rng = random.Random(11)
    pws: list[v1.PlayerWeek] = []
    ros: dict[str, float] = {}
    for fam, k in K_TRUE.items():
        raw = {"QB": "QB", "RB": "RB", "LB": "LB"}[fam]
        for i in range(players_per_family):
            pid = f"{fam}{i}"
            rv = 20.0 + 5.0 * i
            ros[pid] = rv
            mean = rv / k
            for season, weeks in ((2025, range(1, 18)), (2026, range(1, 5))):
                for w in weeks:
                    pts = max(0.1, mean * (1.0 + CV_TRUE[fam] * rng.gauss(0, 1)))
                    pws.append(_pw(season, w, pid, raw, fam, pts))
            for w in (5, 6, 7):
                pws.append(_pw(2026, w, pid, raw, fam, holdout_value))
    # A fullback: raw "FB", family RB via fantasy_positions (v1's lineup_family).
    for w in range(1, 5):
        pws.append(_pw(2026, w, "fb0", "FB", "RB", 2.0))
    ros["fb0"] = 4.0
    return pws, ros


# ── split integrity ────────────────────────────────────────────────────────────────────────────


def test_no_evaluated_week_reaches_any_v2_fit(monkeypatch):
    calls = []
    real = sc.build_calibration

    def spy(**kwargs):
        calls.append(kwargs)
        return real(**kwargs)

    split = v1.preregistered_split()
    pws, ros = _synthetic()
    model, receipts = v2.fit_challenger(pws, ros, split, builder=spy)

    evaluated = {v1.week_key(s, w) for s, w in (*split.holdout, *split.confirm)}
    fit_2026 = {v1.week_key(2026, w) for w in v1.FIT_2026_WEEKS}
    assert calls, "the scale fit goes through build_calibration"
    for kw in calls:
        assert set(kw["stat_lines_by_week"]) <= fit_2026
        assert not set(kw["stat_lines_by_week"]) & evaluated
        for rows in kw["stat_lines_by_week"].values():
            assert all(line[v1.POINTS_KEY] < 1000.0 for line in rows.values())
    # The absurd holdout value would dominate every statistic it reached.
    for fam in K_TRUE:
        assert model.cv_by_family[fam] < 1.0
        # 12 players x (17 + 4) fit weeks; RB also holds the fullback's 4 weeks.
        expected = 12 * 21 + (4 if fam == "RB" else 0)
        assert receipts["cvs"]["byFamily"][fam]["playerWeeks"] == expected


def test_a_leaked_evaluated_week_is_refused_not_filtered():
    leaky = v1.Split(fit=((2026, 4), (2026, 5)), holdout=((2026, 5),), confirm=())
    pws, ros = _synthetic()
    for fn in (
        lambda: v2.fit_family_scales(pws, ros, leaky),
        lambda: v2.fit_family_cvs(pws, leaky),
        lambda: v2.raw_family_table(pws, leaky),
    ):
        with pytest.raises(v1.StudyRefusal, match="evaluated weeks"):
            fn()


def test_non_appearances_never_enter_the_fit():
    split = v1.preregistered_split()
    pws, ros = _synthetic()
    pws = pws + [_pw(2026, w, "QB0", "QB", "QB", None, status=v1.NO_STAT_LINE) for w in (1, 2)]
    base, _ = v2.fit_challenger(_synthetic()[0], ros, split)
    with_missing, _ = v2.fit_challenger(pws, ros, split)
    assert with_missing.to_dict() == base.to_dict()


# ── output-path guard ──────────────────────────────────────────────────────────────────────────


def test_v2_writes_through_v1s_guard():
    assert v2.v1.assert_safe_output is v1.assert_safe_output
    assert v1.FORBIDDEN_OUTPUT_DIR == sc.DATA_DIR
    for name in (v2.CHALLENGER_NAME, v2.EVAL_NAME):
        assert v1.assert_safe_output(v2.OUT_DIR / name).name == name
    with pytest.raises(v1.UnsafeOutputPath):
        v1.assert_safe_output(sc.DATA_DIR / v2.CHALLENGER_NAME)


def test_main_refuses_a_league_intel_out_dir_before_any_fetch(tmp_path):
    existed = sc.DATA_DIR.exists()
    code = v2.main(
        ["--out-dir", str(sc.DATA_DIR), "--offline", "--cache-dir", str(tmp_path / "empty")]
    )
    assert code == 2
    assert sc.DATA_DIR.exists() == existed
    assert not (tmp_path / "empty").exists(), "the refusal happened after the fetcher started"


def test_main_refuses_the_served_file_name_as_out_name(tmp_path):
    code = v2.main(
        [
            "--out-dir",
            str(tmp_path),
            "--out-name",
            sc.MODEL_PATH.name,
            "--offline",
            "--cache-dir",
            str(tmp_path / "empty"),
        ]
    )
    assert code == 2
    assert not (tmp_path / sc.MODEL_PATH.name).exists()


def test_main_refuses_a_v1_candidate_with_the_wrong_hash(tmp_path):
    fake = tmp_path / "candidate.json"
    fake.write_text("{}", encoding="utf-8")
    code = v2.main(
        [
            "--out-dir",
            str(tmp_path / "out"),
            "--v1-candidate",
            str(fake),
            "--offline",
            "--cache-dir",
            str(tmp_path / "empty"),
        ]
    )
    assert code == 2
    assert not (tmp_path / "empty").exists()


def test_challenger_file_cannot_be_served_by_the_production_loader(tmp_path):
    split = v1.preregistered_split()
    pws, ros = _synthetic()
    model, receipts = v2.fit_challenger(pws, ros, split)
    path = v1.write_json(tmp_path / v2.CHALLENGER_NAME, v2.challenger_payload(model, receipts))
    blob = json.loads(path.read_text(encoding="utf-8"))
    assert blob["promotes"] is False and blob["schemaVersion"] == v2.CHALLENGER_SCHEMA
    served = sc.load_points_model(path)
    assert served.source == "fallback-constants", "a copied research file must never be served"
    back = v2.load_challenger(path)
    assert back.to_dict() == model.to_dict()
    with pytest.raises(v1.StudyRefusal):
        v2.load_challenger(
            v1.write_json(tmp_path / "other.json", {"schemaVersion": sc.SCHEMA_VERSION})
        )


# ── per-family fit ─────────────────────────────────────────────────────────────────────────────


def test_each_family_scale_is_the_owner_fit_on_that_family_alone():
    split = v1.preregistered_split()
    pws, ros = _synthetic()
    scales = v2.fit_family_scales(pws, ros, split)
    for fam in K_TRUE:
        pids = sorted(
            {pw.pid for pw in pws if pw.family == fam and pw.season == 2026 and pw.week <= 4}
        )
        pairs = []
        for pid in pids:
            pts = [
                pw.points
                for pw in pws
                if pw.pid == pid and pw.season == 2026 and pw.week <= 4 and pw.family == fam
            ]
            pairs.append((ros[pid], statistics.fmean(pts)))
        expected = sc.calibrate_scale(pairs)
        entry = scales["byFamily"][fam]
        assert entry["used"] == "own"
        assert entry["scale"] == expected
        assert entry["rosValuePerPoint"] == expected["rosValuePerPoint"]
    # The fitted scales are distinct per family and near the synthetic truth. The owner's fit
    # regresses rosValue on NOISY 4-week means, so it is attenuated (k too low, mean too high) and
    # more so at higher CV; that is preregistration §3.4's named risk, and V2 keeps the fit as is.
    ks = {f: scales["byFamily"][f]["rosValuePerPoint"] for f in K_TRUE}
    assert ks["QB"] < ks["LB"] < ks["RB"]
    for fam, k in K_TRUE.items():
        assert ks[fam] == pytest.approx(k, rel=0.15)
        assert ks[fam] <= k * 1.01
    assert ks["RB"] / K_TRUE["RB"] < ks["QB"] / K_TRUE["QB"]


def test_pooled_scale_is_the_single_v1_style_call_over_every_family():
    split = v1.preregistered_split()
    pws, ros = _synthetic()
    scales = v2.fit_family_scales(pws, ros, split)
    cand, receipts = v1.fit_candidate(pws, ros, split)
    assert scales["pooled"]["scale"] == receipts["scaleCall"]["scale"] == cand["scale"]


def test_a_family_below_the_floor_takes_the_pooled_scale():
    split = v1.preregistered_split()
    pws, ros = _synthetic()
    # RB here holds 12 players x 4 weeks = 48 + the FB's 4 = 52; keep only 7 player-weeks of RB.
    keep = {"RB0": 4, "RB1": 3}
    thin = [
        pw
        for pw in pws
        if pw.family != "RB"
        or pw.season != 2026
        or pw.week > 4
        or (pw.pid in keep and pw.week <= keep[pw.pid])
    ]
    scales = v2.fit_family_scales(thin, ros, split)
    rb = scales["byFamily"]["RB"]
    assert rb["playerWeeks"] == 7 < v2.FAMILY_FLOOR
    assert rb["used"] == "pooled" and rb["reason"] == "below_floor"
    assert rb["rosValuePerPoint"] == scales["pooled"]["scale"]["rosValuePerPoint"]
    assert scales["byFamily"]["WR"]["used"] == "pooled"  # no input at all


def test_cv_is_v1s_within_player_d2_statistic_with_floor_and_clamp():
    split = v1.preregistered_split()
    pws, _ros = _synthetic()
    cvs = v2.fit_family_cvs(pws, split)
    fit = [pw for pw in pws if (pw.season, pw.week) in set(split.fit)]
    d2 = v1.within_player_cv(fit)
    for fam in K_TRUE:
        assert cvs["byFamily"][fam]["measured"] is True
        assert cvs["byFamily"][fam]["cv"] == round(d2[fam]["withinPlayerCv"], 4)
        # Within-player spread recovers the generating CV (not the between-player spread).
        assert cvs["byFamily"][fam]["cv"] == pytest.approx(CV_TRUE[fam], abs=0.07)
    # A family with no fit data keeps the documented fallback and says so.
    assert cvs["byFamily"]["WR"] == {"cv": sc.FALLBACK_CV_BY_POSITION["WR"], "measured": False}
    assert cvs["byFamily"]["K"]["cv"] == sc.FALLBACK_DEFAULT_CV
    # Pooled is the same rule over every row: between the family values.
    assert min(CV_TRUE.values()) - 0.1 < cvs["pooled"]["cv"] < max(CV_TRUE.values()) + 0.1


def test_within_player_cv_is_below_the_pooled_cv_when_means_differ():
    """The v1 diagnosis in miniature: build_calibration's pooled CV adds between-player spread."""
    split = v1.preregistered_split()
    pws, ros = _synthetic()
    cvs = v2.fit_family_cvs(pws, split)
    cand, _ = v1.fit_candidate(pws, ros, split)
    for fam in K_TRUE:
        assert cvs["byFamily"][fam]["cv"] < cand["byPosition"][fam]["cv"]


def test_raw_positions_resolve_to_families():
    split = v1.preregistered_split()
    pws, ros = _synthetic()
    model, receipts = v2.fit_challenger(pws, ros, split)
    assert receipts["rawFamily"] == {"FB": "RB"}
    assert model.family_for("CB") == "DB"
    assert model.family_for("DE") == "DL" and model.family_for("NT") == "DL"
    assert model.family_for("SS") == "DB" and model.family_for("PK") == "K"
    assert model.family_for("FB") == "RB"
    assert model.family_for("OL") is None
    assert model.scale_for("FB") == model.scale_for("RB")
    assert model.cv_for("OL") == model.pooled_cv and model.scale_for("OL") == model.pooled_scale


def test_raw_family_table_breaks_ties_in_family_order():
    split = v1.preregistered_split()
    pws = [_pw(2026, 1, "a", "XX", "WR", 5.0), _pw(2026, 1, "b", "XX", "RB", 5.0)]
    assert v2.raw_family_table(pws, split) == {"XX": "RB"}


def test_draw_and_predictive_use_the_family_scale_and_cv():
    model = v2.FamilyScalePointsModel(
        scale_by_family={"QB": 1.0, "LB": 2.0},
        cv_by_family={"QB": 0.2, "LB": 0.5},
        pooled_scale=4.0,
        pooled_cv=0.3,
    )
    assert v2.predictive(model, 30.0, "QB") == (30.0, pytest.approx(6.0))
    assert v2.predictive(model, 30.0, "LB") == (15.0, pytest.approx(7.5))
    assert v2.predictive(model, 1.0, "LB") == (0.5, 0.5)  # sigma floor, as production's draw
    with pytest.raises(TypeError):
        model.mean_points(30.0)
    rng = random.Random(3)
    draws = [model.draw(30.0, "LB", rng) for _ in range(20000)]
    # max(0, N(15, 7.5^2)) in closed form: mu = 15, sigma = 7.5, z = 2.
    z, phi, cdf = 2.0, v1.norm_pdf(2.0), v1.norm_cdf(2.0)
    mean = 15.0 * cdf + 7.5 * phi
    second = (15.0**2 + 7.5**2) * cdf + 15.0 * 7.5 * phi
    assert z == 15.0 / 7.5
    assert statistics.fmean(draws) == pytest.approx(mean, rel=0.01)
    assert statistics.pstdev(draws) == pytest.approx((second - mean**2) ** 0.5, rel=0.02)
    # Identical to draw_from_mean with the family mean, from the same stream.
    a, b = random.Random(9), random.Random(9)
    assert model.draw(30.0, "QB", a) == model.draw_from_mean(30.0, "QB", b)


def test_production_bestball_sim_runs_the_challenger_unmodified():
    model = v2.FamilyScalePointsModel(
        scale_by_family={"QB": 1.0, "LB": 2.0}, cv_by_family={"QB": 0.2, "LB": 0.5}
    )
    pool = [
        {"playerId": "1", "position": "QB", "rosValue": 30.0, "fantasyPositions": ["QB"]},
        {"playerId": "2", "position": "LB", "rosValue": 30.0, "fantasyPositions": ["LB"]},
    ]
    a = playoff_sim._bestball_weekly_score(pool, ["QB", "LB"], random.Random(5), model)
    rng = random.Random(5)
    expected = model.draw(30.0, "QB", rng) + model.draw(30.0, "LB", rng)
    assert a == pytest.approx(expected)


def test_v1_and_fallback_predictions_are_unchanged_by_the_v2_scorer():
    rows = [("1", 5, "QB", "QB", 30.0, 12.0), ("2", 5, "CB", "DB", 20.0, 0.0)]
    models = {"V1": sc.PointsModel(ros_value_per_point=1.5), "F": sc.PointsModel()}
    ours = v2.score_rows(rows, models)
    theirs = v1.score_predictions(rows, models)
    for a, b in zip(ours, theirs):
        for m in models:
            assert (a.mu[m], a.sigma[m], a.ls[m], a.crps[m], a.pit[m]) == (
                b.mu[m],
                b.sigma[m],
                b.ls[m],
                b.crps[m],
                b.pit[m],
            )


# ── gates ──────────────────────────────────────────────────────────────────────────────────────


def _group(n, *, pit80, pit95, cov80, cov95, ks_d=0.05, ls=0.0, crps=0.0):
    def _model(**kw):
        return {
            "pitCoverage80": kw["pit80"],
            "pitCoverage95": kw["pit95"],
            "coverage80": kw["cov80"],
            "coverage95": kw["cov95"],
            "pit": {"ksD": kw["ks_d"]},
        }

    good = _model(pit80=pit80, pit95=pit95, cov80=cov80, cov95=cov95, ks_d=ks_d)
    bad = _model(pit80=0.4, pit95=0.6, cov80=0.4, cov95=0.6, ks_d=0.36)
    ci = {"n": n, "clusters": n, "mean": 1.0, "ci95": [0.5, 1.5]}
    return {
        "n": n,
        "V2": good,
        "F": bad,
        "deltas": {"V2-F": {"deltaLogScore": dict(ci), "deltaCrps": dict(ci)}},
    }


def _team(cov80=0.8, cov95=0.95, crps=30.0):
    return {
        "n": 24,
        "V2": {"coverage80": cov80, "coverage95": cov95, "meanCrps": crps, "meanBias": 0.0},
        "F": {"coverage80": 0.0, "coverage95": 0.1, "meanCrps": 95.0, "meanBias": -100.0},
    }


def test_sc_g1_gates_on_pit_coverage_not_the_censored_interval():
    # Censored intervals over-cover (0.975 at the "95%" level) while PIT coverage is nominal.
    fam = _group(100, pit80=0.80, pit95=0.95, cov80=0.88, cov95=0.98)
    player = {"pooled": fam, "byFamily": {"QB": fam}}
    out = v2.apply_gates_v2(player, _team())
    assert out["gates"]["SC-G1"]["pass"] is True
    assert out["gates"]["SC-G1"]["nonGatingLiteralV1"]["pass"] is False
    assert out["verdict"] == "CHALLENGER_BEATS_FALLBACK"

    fam = _group(100, pit80=0.70, pit95=0.95, cov80=0.80, cov95=0.95)
    player = {"pooled": fam, "byFamily": {"QB": fam}}
    out = v2.apply_gates_v2(player, _team())
    assert out["gates"]["SC-G1"]["pass"] is False
    assert out["gates"]["SC-G1"]["failingFamilies"] == ["QB"]
    assert out["gates"]["SC-G1"]["nonGatingLiteralV1"]["pass"] is True
    assert out["verdict"] == "CHALLENGER_DOES_NOT_BEAT_FALLBACK"
    assert out["failingGates"] == ["SC-G1"]


def test_v2_gates_keep_v1s_thresholds_and_minimum_family_size():
    fam = _group(100, pit80=0.80, pit95=0.95, cov80=0.8, cov95=0.95, ks_d=0.081)
    small = _group(49, pit80=0.2, pit95=0.3, cov80=0.2, cov95=0.3, ks_d=0.5)
    player = {"pooled": fam, "byFamily": {"QB": fam, "K": small}}
    out = v2.apply_gates_v2(player, _team(cov80=0.64))
    assert out["gates"]["SC-G1"]["gatedFamilies"] == ["QB"], "n < 50 is reported, not gated"
    assert out["gates"]["SC-G4"]["pass"] is False  # 0.081 > 0.08
    assert out["gates"]["SC-G5"]["pass"] is False  # 0.64 < 0.65
    assert set(out["failingGates"]) == {"SC-G4", "SC-G5"}


def test_size_aware_reading_and_binomial_range():
    lo, hi = v2.binomial_central_range(100, 0.8)
    assert (
        lo < 0.8 < hi
        and lo == pytest.approx(0.72, abs=0.011)
        and hi == pytest.approx(0.88, abs=0.011)
    )
    assert v2.ks_critical_95(100) == pytest.approx(1.358 / (10 + 0.12 + 0.011), abs=1e-6)
    g = {
        "n": 100,
        "V2": {"pit": {"ksD": 0.1, "ksP": 0.2}, "pitCoverage80": 0.75, "pitCoverage95": 0.97},
    }
    s = v2.size_aware(g)
    assert s["ksDExceedsCritical95"] is False
    assert s["pitCoverage80InsideBinomialRange"] and s["pitCoverage95InsideBinomialRange"]


def test_reproduction_check_flags_any_drift_from_v1():
    pooled = {
        "n": 2,
        "V1": {k: 1.0 for k in v2._REPRO_FIELDS},
        "F": {k: 2.0 for k in v2._REPRO_FIELDS},
        "deltas": {"V1-F": {"deltaLogScore": {"mean": 1}, "deltaCrps": {"mean": 2}}},
    }
    v2_eval = {
        "playerLevel": {"pooled": pooled, "byFamily": {}},
        "teamWeek": {"realizedCrossCheck": {"x": 1}},
        "census": {"D5": {"total": {"appeared": 2}}, "evaluatedPlayerWeeks": 2},
    }
    v1_pooled = {
        "n": 2,
        "C": {k: 1.0 for k in v2._REPRO_FIELDS},
        "F": {k: 2.0 for k in v2._REPRO_FIELDS},
        "deltaLogScore": {"mean": 1},
        "deltaCrps": {"mean": 2},
    }
    v1_eval = {
        "playerLevel": {"pooled": v1_pooled, "byFamily": {}},
        "teamWeek": {"realizedCrossCheck": {"x": 1}},
        "census": {"D5": {"total": {"appeared": 2}}, "evaluatedPlayerWeeks": 2},
    }
    assert v2.reproduction_check(v2_eval, v1_eval)["reproduced"] is True
    v1_eval["playerLevel"]["pooled"]["C"]["meanCrps"] = 1.5
    out = v2.reproduction_check(v2_eval, v1_eval)
    assert out["reproduced"] is False
    assert [m["field"] for m in out["mismatches"]] == ["pooled.V1.meanCrps"]
