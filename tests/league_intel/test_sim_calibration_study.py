"""Tests for ``scripts/sim_calibration_study.py`` (preregistered, shadow-only study).

Three things the preregistration depends on, pinned here:

* **split integrity** — no holdout or confirmation week ever reaches ``build_calibration``;
* **the output-path guard** — the study refuses ``data/league_intel/`` (whose files auto-load into
  served numbers) and the served artifact's file name anywhere;
* **the metric computations** — closed forms checked against numeric integration and against draws
  from ``PointsModel`` itself, on synthetic fixtures only (no network, no live data).
"""

from __future__ import annotations

import math
import random
import statistics
from datetime import datetime, timezone

import pytest

from scripts import sim_calibration_study as st
from src.league_intel import sim_calibration as sc

# ── split integrity ────────────────────────────────────────────────────────────────────────────


def test_preregistered_split_is_disjoint_and_ordered():
    split = st.preregistered_split()
    fit = set(split.fit)
    assert fit.isdisjoint(split.holdout)
    assert fit.isdisjoint(split.confirm)
    assert max(fit) < min(split.holdout) <= min(split.confirm)
    assert split.holdout == ((2026, 5), (2026, 6))
    assert split.confirm == ((2026, 7),)
    assert (2025, 18) not in fit  # the 2025 fantasy season has no week-18 rosters
    assert {(2026, w) for w in (1, 2, 3, 4)} <= fit


def test_split_integrity_refuses_overlap_and_misorder():
    with pytest.raises(st.StudyRefusal, match="overlap"):
        st.assert_split_integrity(st.Split(fit=((2026, 5),), holdout=((2026, 5),), confirm=()))
    with pytest.raises(st.StudyRefusal, match="order"):
        st.assert_split_integrity(st.Split(fit=((2026, 6),), holdout=((2026, 5),), confirm=()))


def _pw(season, week, pid, pos, pts, status=st.APPEARED):
    return st.PlayerWeek(season, week, pid, pos, status, pts)


def _synthetic_player_weeks():
    """40 QB fit weeks at ~20 points, plus holdout / confirmation weeks at an absurd 1000."""
    rng = random.Random(7)
    out = []
    for season, weeks in ((2025, range(1, 18)), (2026, range(1, 5))):
        for w in weeks:
            for i in range(3):
                out.append(_pw(season, w, f"q{i}", "QB", 20.0 + rng.gauss(0, 4)))
    for w in (5, 6, 7):
        for i in range(3):
            out.append(_pw(2026, w, f"q{i}", "QB", 1000.0))
    out.append(_pw(2026, 2, "x", "QB", None, status=st.NO_STAT_LINE))
    return out


def test_no_holdout_week_reaches_build_calibration(monkeypatch):
    calls = []
    real = sc.build_calibration

    def spy(**kwargs):
        calls.append(kwargs)
        return real(**kwargs)

    monkeypatch.setattr(st.sc, "build_calibration", spy)
    split = st.preregistered_split()
    pws = _synthetic_player_weeks()
    st.fit_candidate(pws, {"q0": 60.0, "q1": 50.0, "q2": 40.0}, split)

    assert len(calls) == 2, "the candidate is exactly two build_calibration calls"
    fit_keys = {st.week_key(s, w) for s, w in split.fit}
    evaluated = {st.week_key(s, w) for s, w in (*split.holdout, *split.confirm)}
    for call in calls:
        keys = set(call["stat_lines_by_week"])
        assert keys <= fit_keys
        assert keys.isdisjoint(evaluated)
        for lines in call["stat_lines_by_week"].values():
            for line in lines.values():
                assert line[st.POINTS_KEY] < 1000.0, "a holdout point total leaked into the fit"
    variance, scale = calls
    assert variance["ros_values"] == {}
    assert {k // 100 for k in variance["stat_lines_by_week"]} == {2025, 2026}
    assert set(scale["stat_lines_by_week"]) == {st.week_key(2026, w) for w in (1, 2, 3, 4)}
    assert set(scale["ros_values"]) == {"q0", "q1", "q2"}


def test_candidate_carries_host_native_points_unchanged_and_composes_both_calls():
    split = st.preregistered_split()
    pws = _synthetic_player_weeks()
    cand, receipts = st.fit_candidate(pws, {"q0": 60.0, "q1": 50.0, "q2": 40.0}, split)

    fit_pts = [
        p.points for p in pws if p.status == st.APPEARED and (p.season, p.week) in set(split.fit)
    ]
    qb = cand["byPosition"]["QB"]
    assert qb["n"] == len(fit_pts) == 63
    assert qb["meanPoints"] == pytest.approx(statistics.fmean(fit_pts), abs=1e-3)
    assert qb["cv"] == pytest.approx(
        statistics.pstdev(fit_pts) / statistics.fmean(fit_pts), abs=1e-4
    )
    # Scale comes from the 2026 call only, and it is not the fallback 2.7.
    assert cand["scale"] == receipts["scaleCall"]["scale"]
    assert cand["scale"]["n"] == 3
    assert receipts["varianceCall"]["scaleDiscarded"]["n"] == 0


def test_unpriced_players_never_enter_the_scale_fit():
    split = st.preregistered_split()
    pws = _synthetic_player_weeks()
    _cand, receipts = st.fit_candidate(pws, {"q0": 60.0, "q1": 0.0}, split)
    assert receipts["scaleCall"]["pricedPlayers"] == 1
    # q1 (rosValue 0) and q2 (no rosValue) each have 4 appeared 2026 fit weeks.
    assert receipts["scaleCall"]["unpricedPlayerWeeksExcluded"] == 8


# ── output-path guard ──────────────────────────────────────────────────────────────────────────


def test_guard_targets_the_loader_directory():
    assert st.FORBIDDEN_OUTPUT_DIR == sc.DATA_DIR
    assert sc.MODEL_PATH.parent == sc.DATA_DIR


@pytest.mark.parametrize(
    "target",
    [
        sc.DATA_DIR,
        sc.MODEL_PATH,
        sc.DATA_DIR / "candidate_sim_points_model.json",
        sc.DATA_DIR / "nested" / "evaluation.json",
        sc.DATA_DIR.parent / "elsewhere" / ".." / "league_intel" / "x.json",
    ],
)
def test_guard_refuses_data_league_intel(target):
    with pytest.raises(st.UnsafeOutputPath):
        st.assert_safe_output(target)


def test_guard_refuses_the_served_file_name_anywhere(tmp_path):
    with pytest.raises(st.UnsafeOutputPath):
        st.assert_safe_output(tmp_path / sc.MODEL_PATH.name)


def test_guard_allows_the_evidence_directory_and_tmp(tmp_path):
    assert st.assert_safe_output(st.OUT_DIR / st.CANDIDATE_NAME).name == st.CANDIDATE_NAME
    assert (
        st.assert_safe_output(tmp_path / "evaluation.json")
        == (tmp_path / "evaluation.json").resolve()
    )


def test_write_json_refuses_before_creating_anything():
    existed = sc.DATA_DIR.exists()
    with pytest.raises(st.UnsafeOutputPath):
        st.write_json(sc.DATA_DIR / "probe_should_never_exist.json", {"x": 1})
    assert not (sc.DATA_DIR / "probe_should_never_exist.json").exists()
    assert sc.DATA_DIR.exists() == existed


def test_main_refuses_a_league_intel_out_dir_before_any_fetch(tmp_path):
    existed = sc.DATA_DIR.exists()
    code = st.main(
        ["--out-dir", str(sc.DATA_DIR), "--offline", "--cache-dir", str(tmp_path / "empty")]
    )
    assert code == 2
    assert sc.DATA_DIR.exists() == existed
    assert not (tmp_path / "empty").exists(), "the refusal happened after the fetcher started"


# ── population / scoring ───────────────────────────────────────────────────────────────────────

CARD = {"pass_td": 6.0, "pass_yd": 0.04, "rec": 1.0, "rec_yd": 0.1, "idp_tkl_solo": 1.33}


def test_classification_never_turns_missing_into_zero():
    meta_qb = {"position": "QB"}
    assert st.classify_player_week("1", None, meta_qb, CARD, 2026, 5).status == st.NO_STAT_LINE
    assert st.classify_player_week("1", None, meta_qb, CARD, 2026, 5).points is None
    unknown = st.classify_player_week(
        "1", {"gp": 1, "pass_td": 2}, {"position": "OL"}, CARD, 2026, 5
    )
    assert unknown.status == st.UNKNOWN_POSITION and unknown.points is None
    assert (
        st.classify_player_week("1", {"gp": 1}, None, CARD, 2026, 5).status == st.UNKNOWN_POSITION
    )
    ranks_only = st.classify_player_week(
        "1", {"pos_rank_ppr": 999, "gms_active": 1}, meta_qb, CARD, 2026, 5
    )
    assert ranks_only.status == st.NO_APPEARANCE and ranks_only.points == 0.0
    team = st.classify_player_week("TEAM_KC", {"gp": 1, "pass_td": 1}, meta_qb, CARD, 2026, 5)
    assert team.status == st.TEAM_ENTRY


def test_appeared_points_are_the_host_native_score():
    row = {"gp": 1, "pass_td": 2, "pass_yd": 250}
    pw = st.classify_player_week("4034", row, {"position": "QB"}, CARD, 2026, 5)
    assert pw.status == st.APPEARED
    assert pw.points == pytest.approx(2 * 6.0 + 250 * 0.04)
    zero_game = st.classify_player_week("4034", {"gp": 1}, {"position": "QB"}, CARD, 2026, 5)
    assert zero_game.status == st.APPEARED and zero_game.points == 0.0, "a played 0 is a real 0"


def test_schedule_finality_and_kickoff_in_utc():
    games = [
        {
            "season": "2026",
            "game_type": "REG",
            "week": "7",
            "gameday": "2026-10-22",
            "gametime": "20:15",
            "result": "6",
        },
        {
            "season": "2026",
            "game_type": "REG",
            "week": "7",
            "gameday": "2026-10-26",
            "gametime": "20:15",
            "result": "",
        },
        {
            "season": "2026",
            "game_type": "REG",
            "week": "6",
            "gameday": "2026-10-15",
            "gametime": "20:15",
            "result": "3",
        },
    ]
    sched = st.schedule_by_week(games, 2026)
    assert not sched[7].is_final and sched[6].is_final
    assert sched[7].first_kickoff_utc == datetime(2026, 10, 23, 0, 15, tzinfo=timezone.utc)


def test_snapshot_is_strictly_before_the_cutoff(tmp_path):
    for name in (
        "2026-10-08T20-15-39.079400+00-00.json",
        "2026-10-09T00-15-00.000000+00-00.json",
        "2026-10-09T06-00-00.000000+00-00.json",
    ):
        (tmp_path / name).write_text('{"players": []}', encoding="utf-8")
    cutoff = datetime(2026, 10, 9, 0, 15, tzinfo=timezone.utc)
    assert st.snapshot_before(cutoff, tmp_path).name.startswith("2026-10-08T20-15-39")
    with pytest.raises(st.StudyRefusal):
        st.snapshot_before(datetime(2026, 1, 1, tzinfo=timezone.utc), tmp_path)


# ── metric computations (synthetic) ────────────────────────────────────────────────────────────


def _numeric_censored_crps(y, mu, sigma, steps=50_000):
    """Midpoint rule on each piece between the two jumps (x = 0 and x = y), so no cell straddles one."""
    lo = min(y, 0.0) - 1.0
    hi = max(y, mu + 12 * sigma) + 1.0
    cuts = sorted({lo, 0.0, y, hi})
    tot = 0.0
    for a, b in zip(cuts, cuts[1:]):
        h = (b - a) / steps
        for i in range(steps):
            x = a + (i + 0.5) * h
            f = 0.0 if x < 0 else st.norm_cdf((x - mu) / sigma)
            ind = 1.0 if x >= y else 0.0
            tot += (f - ind) ** 2 * h
    return tot


@pytest.mark.parametrize(
    "y,mu,sigma",
    [
        (12.0, 10.0, 4.0),
        (0.0, 10.0, 4.0),
        (0.0, 0.4, 0.5),
        (3.0, 1.0, 0.5),
        (-2.5, 8.0, 5.0),
        (40.0, 18.0, 9.0),
    ],
)
def test_censored_crps_matches_numeric_integration(y, mu, sigma):
    assert st.censored_crps(y, mu, sigma) == pytest.approx(
        _numeric_censored_crps(y, mu, sigma), abs=2e-4
    )


def test_censored_log_score_is_a_proper_density():
    mu, sigma = 3.0, 2.5
    mass0 = math.exp(st.censored_log_score(0.0, mu, sigma))
    assert mass0 == pytest.approx(st.norm_cdf(-mu / sigma))
    h = 1e-3
    cont = sum(
        math.exp(st.censored_log_score((i + 0.5) * h, mu, sigma)) * h for i in range(int(30 / h))
    )
    assert mass0 + cont == pytest.approx(1.0, abs=1e-4)
    assert st.censored_log_score(-4.0, mu, sigma) == st.censored_log_score(0.0, mu, sigma)


def test_predictive_params_match_the_points_model_draw():
    model = sc.PointsModel()
    mu, sigma = st.predictive_params(model, 54.0, "QB")
    assert mu == pytest.approx(54.0 / 2.7)
    assert sigma == pytest.approx(mu * 0.32)
    assert st.predictive_params(model, 0.5, "WR")[1] == 0.5, "the 0.5-point sd floor"
    # The draw itself is max(0, N(mu, sigma)) with exactly these parameters.
    a = model.draw(54.0, "QB", random.Random(3))
    b = max(0.0, random.Random(3).gauss(mu, sigma))
    assert a == b


def test_coverage_and_pit_are_nominal_on_the_models_own_draws():
    model = sc.PointsModel()
    rng = random.Random(11)
    rows = []
    for i in range(12000):
        ros = 5.0 + (i % 60)
        pos = ("QB", "WR", "LB", "DB")[i % 4]
        rows.append((f"p{i}", 5, pos, ros, model.draw(ros, pos, rng)))
    scored = st.score_predictions(rows, {"C": model, "F": model}, seed=5)
    cov80 = statistics.fmean(1.0 if r.cov80["C"] else 0.0 for r in scored)
    cov95 = statistics.fmean(1.0 if r.cov95["C"] else 0.0 for r in scored)
    assert cov80 == pytest.approx(0.80, abs=0.015)
    assert cov95 == pytest.approx(0.95, abs=0.01)
    ks = st.ks_uniform([r.pit["C"] for r in scored])
    assert ks["ksD"] < 0.02 and ks["ksP"] > 0.01


def test_ks_and_kolmogorov_reference_values():
    assert st.ks_uniform([0.5])["ksD"] == 0.5
    assert st.ks_uniform([(i + 0.5) / 100 for i in range(100)])["ksD"] == pytest.approx(0.005)
    scipy_special = pytest.importorskip("scipy.special")
    for d, n in ((0.05, 400), (0.1, 100), (0.03, 1500)):
        lam = (math.sqrt(n) + 0.12 + 0.11 / math.sqrt(n)) * d
        assert st.kolmogorov_p(d, n) == pytest.approx(
            float(scipy_special.kolmogorov(lam)), abs=1e-9
        )


def test_sample_metrics():
    assert st.sample_crps([5.0] * 10, 8.0) == pytest.approx(3.0)
    rng = random.Random(2)
    draws = [rng.gauss(10, 3) for _ in range(40000)]
    exact = 3.0 * (
        2 * st.norm_pdf(0.5 / 3)
        + (0.5 / 3) * (2 * st.norm_cdf(0.5 / 3) - 1)
        - 1 / math.sqrt(math.pi)
    )
    assert st.sample_crps(draws, 10.5) == pytest.approx(exact, abs=0.02)
    np = pytest.importorskip("numpy")
    xs = sorted(rng.random() for _ in range(101))
    for q in (0.025, 0.1, 0.5, 0.9, 0.975):
        assert st.sample_quantile(xs, q) == pytest.approx(float(np.quantile(xs, q)))
    assert st.sample_pit([1.0, 2.0, 3.0, 4.0], 2.5, 0.0) == 0.5
    assert st.sample_pit([1.0, 2.0, 2.0, 4.0], 2.0, 0.5) == 0.5


def test_cluster_bootstrap_is_deterministic_and_exact_on_constants():
    vals = [1.5] * 30
    res = st.cluster_bootstrap(vals, [f"p{i // 3}" for i in range(30)], b=200, seed=9)
    assert res["mean"] == 1.5 and res["ci95"] == [1.5, 1.5] and res["clusters"] == 10
    rng = random.Random(4)
    vals = [rng.gauss(0.2, 1) for _ in range(300)]
    cl = [f"p{i // 2}" for i in range(300)]
    a = st.cluster_bootstrap(vals, cl, b=300, seed=1)
    assert a == st.cluster_bootstrap(vals, cl, b=300, seed=1)
    assert a["ci95"][0] < a["mean"] < a["ci95"][1]


# ── gates ──────────────────────────────────────────────────────────────────────────────────────


def _fam(n, cov80=0.8, cov95=0.95, ks=0.03, dls=(0.1, 0.05, 0.2), dcrps=(0.1, 0.05, 0.2)):
    return {
        "n": n,
        "C": {"coverage80": cov80, "coverage95": cov95, "pit": {"ksD": ks}},
        "F": {"coverage80": 0.6, "coverage95": 0.8, "pit": {"ksD": 0.2}},
        "deltaLogScore": {"mean": dls[0], "ci95": [dls[1], dls[2]]},
        "deltaCrps": {"mean": dcrps[0], "ci95": [dcrps[1], dcrps[2]]},
    }


def _team(cov80=0.8, cov95=0.95, crps_c=10.0, crps_f=12.0):
    return {
        "n": 24,
        "C": {"coverage80": cov80, "coverage95": cov95, "meanCrps": crps_c},
        "F": {"coverage80": 0.5, "coverage95": 0.7, "meanCrps": crps_f},
    }


def test_all_gates_pass_on_a_well_calibrated_fixture():
    player = {
        "pooled": _fam(400, ks=0.02),
        "byFamily": {"QB": _fam(80), "LB": _fam(120), "K": _fam(20, cov80=0.2)},
    }
    out = st.apply_gates(player, _team())
    assert out["verdict"] == "CANDIDATE_BEATS_FALLBACK", out["failingGates"]
    assert out["gates"]["SC-G1"]["gatedFamilies"] == [
        "QB",
        "LB",
    ], "K (n < 50) is reported, not gated"


@pytest.mark.parametrize(
    "player_kw,team_kw,gate",
    [
        ({"fam": {"cov80": 0.70}}, {}, "SC-G1"),
        ({"fam": {"cov95": 0.89}}, {}, "SC-G1"),
        ({"pooled": {"dls": (0.1, -0.01, 0.2)}}, {}, "SC-G2"),
        ({"fam": {"dls": (-0.3, -0.5, -0.1)}}, {}, "SC-G2"),
        ({"pooled": {"dcrps": (0.1, -0.01, 0.2)}}, {}, "SC-G3"),
        ({"fam": {"ks": 0.09}}, {}, "SC-G4"),
        ({"pooled": {"ks": 0.25}}, {}, "SC-G4"),
        ({}, {"cov80": 0.6}, "SC-G5"),
        ({}, {"cov95": 0.8}, "SC-G5"),
        ({}, {"crps_c": 12.5}, "SC-G5"),
    ],
)
def test_each_gate_fails_on_its_own_condition(player_kw, team_kw, gate):
    pooled = _fam(400, **{"ks": 0.02, **player_kw.get("pooled", {})})
    player = {"pooled": pooled, "byFamily": {"QB": _fam(80, **player_kw.get("fam", {}))}}
    out = st.apply_gates(player, _team(**team_kw))
    assert out["verdict"] == "CANDIDATE_DOES_NOT_BEAT_FALLBACK"
    assert out["failingGates"] == [gate]
