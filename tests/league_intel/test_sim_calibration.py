"""Tests for ``src/league_intel/sim_calibration.py`` (LI-8).

The points model is the bridge between rosValue (unitless composite)
and fantasy points (what the sim actually needs).  These pin:

  * the fallback path — a missing/corrupt artifact must degrade, never
    raise, and must SAY it degraded;
  * the calibration math — through-origin scale fit, per-position CV,
    and the sample floor that stops a 3-week sample masquerading as
    evidence;
  * that no test touches the network (the fetcher is injected).
"""

from __future__ import annotations

import json
import random

from src.league_intel.sim_calibration import (
    CV_CLAMP,
    FALLBACK_CV_BY_POSITION,
    FALLBACK_ROS_VALUE_PER_POINT,
    MIN_SAMPLES_PER_POSITION,
    SCHEMA_VERSION,
    PointsModel,
    build_calibration,
    calibrate_positions,
    calibrate_scale,
    fetch_stat_lines,
    load_points_model,
    write_calibration,
)


# ── Fallback behavior ──────────────────────────────────────────────


def test_missing_artifact_degrades_to_documented_fallback(tmp_path):
    model = load_points_model(tmp_path / "nope.json")
    assert model.source == "fallback-constants"
    assert model.ros_value_per_point == FALLBACK_ROS_VALUE_PER_POINT
    assert model.cv_for("QB") == FALLBACK_CV_BY_POSITION["QB"]


def test_corrupt_artifact_degrades_without_raising(tmp_path):
    p = tmp_path / "model.json"
    p.write_text("{not json", encoding="utf-8")
    assert load_points_model(p).source == "fallback-constants"


def test_schema_mismatch_degrades(tmp_path):
    p = tmp_path / "model.json"
    p.write_text(json.dumps({"schemaVersion": 999, "scale": {"rosValuePerPoint": 3}}))
    assert load_points_model(p).source == "fallback-constants"


def test_artifact_without_usable_scale_degrades(tmp_path):
    p = tmp_path / "model.json"
    p.write_text(json.dumps({"schemaVersion": SCHEMA_VERSION, "scale": {"rosValuePerPoint": 0}}))
    assert load_points_model(p).source == "fallback-constants"


def test_valid_artifact_loads_as_calibrated(tmp_path):
    p = tmp_path / "model.json"
    p.write_text(
        json.dumps(
            {
                "schemaVersion": SCHEMA_VERSION,
                "generatedAt": "2026-07-26T00:00:00+00:00",
                "sampleSize": 1415,
                "scale": {"rosValuePerPoint": 3.1, "r2": 0.6, "n": 400},
                "byPosition": {"QB": {"cv": 0.28, "n": 100, "measured": True}},
            }
        )
    )
    model = load_points_model(p)
    assert model.source == "calibrated"
    assert model.ros_value_per_point == 3.1
    assert model.cv_for("QB") == 0.28
    # Positions absent from the artifact keep the documented fallback.
    assert model.cv_for("RB") == FALLBACK_CV_BY_POSITION["RB"]
    assert model.sample_size == 1415


# ── Draw behavior ──────────────────────────────────────────────────


def test_draw_is_deterministic_for_a_seeded_rng():
    m = PointsModel()
    a = [m.draw(50.0, "RB", random.Random(7)) for _ in range(3)]
    b = [m.draw(50.0, "RB", random.Random(7)) for _ in range(3)]
    assert a == b


def test_draw_never_returns_negative_points():
    m = PointsModel(ros_value_per_point=2.7, cv_by_position={"WR": 1.2})
    rng = random.Random(1)
    assert all(m.draw(5.0, "WR", rng) >= 0.0 for _ in range(200))


def test_zero_value_player_draws_zero():
    assert PointsModel().draw(0.0, "QB", random.Random(1)) == 0.0


def test_mean_points_scales_inversely_with_divisor():
    assert PointsModel(ros_value_per_point=2.0).mean_points(50.0) == 25.0
    assert PointsModel(ros_value_per_point=5.0).mean_points(50.0) == 10.0


# ── Calibration math ───────────────────────────────────────────────


def test_scale_fit_recovers_a_known_linear_relationship():
    # rosValue = 3 × points, exactly.
    pairs = [(3.0 * pts, pts) for pts in range(1, 30)]
    out = calibrate_scale(pairs)
    assert abs(out["rosValuePerPoint"] - 3.0) < 1e-6
    assert out["r2"] > 0.99
    assert out["n"] == 29


def test_scale_fit_reports_weak_r2_on_noise():
    rng = random.Random(3)
    pairs = [(rng.uniform(1, 100), rng.uniform(1, 30)) for _ in range(200)]
    out = calibrate_scale(pairs)
    # Random pairs must not be sold as a good fit.
    assert out["r2"] < 0.5


def test_scale_fit_falls_back_on_insufficient_pairs():
    out = calibrate_scale([(10.0, 3.0)])
    assert out["rosValuePerPoint"] == FALLBACK_ROS_VALUE_PER_POINT
    assert out["n"] == 1


def test_position_cv_is_measured_above_the_sample_floor():
    # Constant-mean series with known spread.
    pts = [10.0, 20.0] * (MIN_SAMPLES_PER_POSITION // 2 + 5)
    cals = calibrate_positions({"RB": pts})
    rb = cals["RB"]
    assert rb.measured is True
    assert rb.n == len(pts)
    # mean 15, pstdev 5 ⇒ cv ≈ 0.333
    assert abs(rb.cv - (5.0 / 15.0)) < 1e-6


def test_thin_sample_keeps_fallback_cv_and_says_so():
    cals = calibrate_positions({"TE": [10.0, 20.0, 30.0]})
    te = cals["TE"]
    assert te.measured is False
    assert te.cv == FALLBACK_CV_BY_POSITION["TE"]
    assert te.n == 3


def test_cv_is_clamped_to_a_sane_band():
    # Wildly dispersed sample would otherwise produce cv > 1.2.
    pts = ([0.1] * 60) + ([500.0] * 60)
    cals = calibrate_positions({"WR": pts})
    assert cals["WR"].cv <= CV_CLAMP[1]
    # And a near-constant sample must not produce a ~0 cv.
    steady = [20.0] * 60
    assert calibrate_positions({"QB": steady})["QB"].cv >= CV_CLAMP[0]


# ── End-to-end artifact build ──────────────────────────────────────

_SCORING = {"pass_yd": 0.04, "pass_td": 4.0, "rec": 0.5, "rec_yd": 0.1}


def test_build_calibration_scores_through_the_exact_scorer():
    # Two players, three weeks. QB scores 0.04/yd + 4/td.
    stat_lines = {
        1: {"qb1": {"pass_yd": 300, "pass_td": 2}, "wr1": {"rec": 6, "rec_yd": 80}},
        2: {"qb1": {"pass_yd": 250, "pass_td": 1}, "wr1": {"rec": 4, "rec_yd": 50}},
        3: {"qb1": {"pass_yd": 350, "pass_td": 3}, "wr1": {"rec": 8, "rec_yd": 110}},
    }
    payload = build_calibration(
        stat_lines_by_week=stat_lines,
        positions={"qb1": "QB", "wr1": "WR"},
        ros_values={"qb1": 60.0, "wr1": 40.0},
        config=_SCORING,
        season="2025",
    )
    assert payload["schemaVersion"] == SCHEMA_VERSION
    assert payload["season"] == "2025"
    assert payload["weeks"] == [1, 2, 3]
    assert payload["sampleSize"] == 6
    # QB wk1 = 300*0.04 + 2*4 = 20.0 — straight from the exact scorer.
    assert abs(payload["byPosition"]["QB"]["meanPoints"] - ((20.0 + 14.0 + 26.0) / 3)) < 1e-6
    # Thin samples ⇒ not measured, and the artifact admits it.
    assert payload["byPosition"]["QB"]["measured"] is False
    assert "provenance" in payload and payload["provenance"]["scorer"].endswith("score_stat_line")


def test_build_calibration_ignores_players_without_a_position():
    payload = build_calibration(
        stat_lines_by_week={1: {"ghost": {"pass_yd": 100}}},
        positions={},
        ros_values={},
        config=_SCORING,
        season="2025",
    )
    assert payload["sampleSize"] == 0
    assert payload["byPosition"] == {}


def test_write_calibration_round_trips(tmp_path):
    target = tmp_path / "sim_points_model.json"
    payload = {
        "schemaVersion": SCHEMA_VERSION,
        "scale": {"rosValuePerPoint": 2.9},
        "byPosition": {"RB": {"cv": 0.5, "n": 99, "measured": True}},
    }
    written = write_calibration(payload, target)
    assert written.exists()
    assert load_points_model(written).ros_value_per_point == 2.9
    # No temp files left behind.
    assert list(tmp_path.glob("*.tmp")) == []


# ── Fetch policy ───────────────────────────────────────────────────


def test_fetch_uses_injected_fetcher_and_never_touches_network():
    seen: list[str] = []

    def fake(url: str):
        seen.append(url)
        return {"p1": {"pass_yd": 100}}

    out = fetch_stat_lines("2025", [1, 2], fetcher=fake, sleep_s=0)
    assert len(seen) == 2
    assert all(u.startswith("https://api.sleeper.app/v1/stats/nfl/regular/2025/") for u in seen)
    assert set(out) == {1, 2}


def test_one_failing_week_does_not_abort_the_run():
    def flaky(url: str):
        if url.endswith("/2"):
            raise RuntimeError("sleeper 500")
        return {"p1": {"pass_yd": 100}}

    out = fetch_stat_lines("2025", [1, 2, 3], fetcher=flaky, sleep_s=0)
    assert set(out) == {1, 3}
