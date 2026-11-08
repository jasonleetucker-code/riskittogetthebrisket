"""Study-script guards for the team-level points calibration (F2, 2026-11-08).

Split integrity, output confinement, preregistered constants, and the claim that
the incumbent arm is the SERVED equation (flag OFF, production presim seed,
fallback points model).
"""

from __future__ import annotations

import math
import re
from pathlib import Path

import pytest

from scripts import team_points_calibration_eval as study
from src.league_intel import sim_calibration as sc
from src.ros import playoff_sim
from src.ros_calibration import team_points as tp


def test_split_is_rolling_origin_and_disjoint():
    assert set(study.HOLDOUT).isdisjoint(study.DEVELOPMENT)
    assert max(study.DEVELOPMENT) < min(study.HOLDOUT)
    assert max(study.HOLDOUT) < study.LIVE_WEEK
    assert set(study.HOLDOUT) | set(study.DEVELOPMENT) <= set(study.FINAL_WEEKS)


def test_output_is_confined_to_the_evidence_dir(tmp_path: Path):
    for bad in (
        study.REPO / "data" / "league_intel" / "sim_points_model.json",
        study.REPO / "config" / "league_intel" / "x.json",
        study.REPO / "data" / "ros" / "sims" / "latest.json",
        tmp_path / "evaluation.json",
    ):
        with pytest.raises(study.Refusal):
            study.assert_safe_output(bad)
    assert study.assert_safe_output(study.OUT_DIR / "evaluation.json")


def test_incumbent_is_the_served_equation():
    # Presim seed is production's own literal.
    src = Path(playoff_sim.__file__).read_text(encoding="utf-8")
    assert f"random.Random({study.PRESIM_SEED})" in src
    # The served points model at freeze is the documented fallback.
    model = sc.PointsModel()
    assert model.source == "fallback-constants"
    assert model.ros_value_per_point == sc.FALLBACK_ROS_VALUE_PER_POINT == 2.7
    # The corrected (counted-once) equation is OFF by default, so the incumbent arm
    # (ros_counted_once=False) is what production serves.
    from src.api import feature_flags

    assert feature_flags._DEFAULTS["playoff_ros_counted_once"] is False


def test_incumbent_wrapper_reproduces_the_served_equation_by_hand():
    # One presim-basis team: mean = μ·(1 + 0.20·z), sd = σ·(1.10 + 0.15·r).
    rows = [
        {
            "ownerId": "T01",
            "teamRosStrength": 80.0,
            "startingLineupScore": 100.0,
            "benchDepthScore": 40.0,
        },
        {
            "ownerId": "T02",
            "teamRosStrength": 40.0,
            "startingLineupScore": 100.0,
            "benchDepthScore": 10.0,
        },
    ]
    asof = study.AsOf(9, Path("x"), "", [], rows, "test")
    presim = {"T01": (300.0, 30.0), "T02": (200.0, 20.0)}
    view = tp.RealizedView({}, 9)
    out = study.production_distributions(asof, presim, view, ros_counted_once=False)
    z1 = (80.0 - 60.0) / 20.0  # population sd of (80, 40) is 20
    assert out["T01"][0] == pytest.approx(300.0 * (1 + 0.20 * z1))
    assert out["T01"][1] == pytest.approx(30.0 * (1.10 + 0.15 * 0.40))
    assert out["T02"][0] == pytest.approx(200.0 * (1 - 0.20))
    assert out["T02"][1] == pytest.approx(20.0 * (1.10 + 0.15 * 0.10))
    once = study.production_distributions(asof, presim, view, ros_counted_once=True)
    assert once["T01"] == pytest.approx((300.0, 33.0))


def test_constants_match_the_preregistration():
    prereg = (study.REPO / study.PREREGISTRATION).read_text(encoding="utf-8")
    assert "**5, 6, 7, 8**" in prereg and study.HOLDOUT == (5, 6, 7, 8)
    assert "| development (reported, never gated) | 3, 4 |" in prereg
    assert "B = 2,000, seed 20261108" in prereg
    assert study.BOOTSTRAP_B == 2000 and study.BOOTSTRAP_SEED == 20261108
    assert "20,000 draws, seed `20261108 + k`" in prereg
    assert study.MEDIAN_DRAWS == 20000 and study.MEDIAN_SEED_BASE == 20261108
    assert "\\|bias(X)\\| ≤ 20 points" in prereg and tp.MAX_ABS_BIAS == 20.0
    assert "z-RMS(X) ∈ [0.80, 1.25]" in prereg and tp.ZRMS_BAND == (0.80, 1.25)
    assert "∈ [0.68, 0.92]" in prereg and tp.COVERAGE80_BAND == (0.68, 0.92)
    assert "concordance(I) − 0.02" in prereg and tp.CONCORDANCE_SLACK == 0.02
    assert "within 1.0 CRPS points" in prereg and tp.CRPS_TIE == 1.0
    assert "needs n ≥ 12" in prereg and tp.A_MIN_ROWS == 12
    assert "needs ≥ 24 rows" in prereg and tp.S_MIN_ROWS == 24
    assert "`j ∈ [3, k−1]`" in prereg and tp.S_FIRST_TRAIN_WEEK == 3
    assert "needs n_t ≥ 2" in prereg and tp.B1_MIN_WEEKS == 2
    m = re.search(r"A \((\d)\) < S \((\d)\) < B2 \((\d+)\) < B1 \((\d+)\)", prereg)
    assert m and tuple(int(x) for x in m.groups()) == (
        tp.PARAMETER_COUNT["A"],
        tp.PARAMETER_COUNT["S"],
        tp.PARAMETER_COUNT["B2"],
        tp.PARAMETER_COUNT["B1"],
    )


def test_coverage_band_is_about_two_binomial_standard_errors_at_n48():
    se = math.sqrt(0.8 * 0.2 / 48)
    assert tp.COVERAGE80_BAND[0] == pytest.approx(0.8 - 2 * se, abs=0.01)
    assert tp.COVERAGE80_BAND[1] == pytest.approx(0.8 + 2 * se, abs=0.01)


def test_team_ids_are_anonymous_indexes():
    assert study.team_id(3) == "T03"
    assert study.team_id("12") == "T12"
