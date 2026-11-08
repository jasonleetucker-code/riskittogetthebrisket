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


def test_cache_receipts_never_carry_the_league_id():
    receipts = {
        f"{study.SLEEPER}/league/{study.LEAGUE_ID}/matchups/5": {"sha256": "x"},
        f"{study.SLEEPER}/players/nfl": {"sha256": "y"},
    }
    out = study.redacted_receipts(receipts)
    assert all(study.LEAGUE_ID not in url for url in out)
    assert f"{study.SLEEPER}/league/<dynasty_main>/matchups/5" in out
    assert out[f"{study.SLEEPER}/players/nfl"] == {"sha256": "y"}


# ── the incumbent's inputs are point-in-time too (review fix 2026-11-08) ─────────────


def _directory():
    return {
        "1": {"full_name": "Alpha One", "position": "QB", "fantasy_positions": ["QB"]},
        "2": {
            "full_name": "Bravo Two",
            "position": "QB",
            "fantasy_positions": ["QB"],
            "injury_status": "Out",
            "injury_body_part": "Knee",
        },
        "3": {"full_name": "Charlie Three", "position": "RB", "fantasy_positions": ["RB"]},
    }


def test_point_in_time_directory_strips_todays_health_only():
    pit = study.point_in_time_directory(_directory())
    assert "injury_status" not in pit["2"] and "injury_body_part" not in pit["2"]
    assert pit["2"]["full_name"] == "Bravo Two"
    assert pit["2"]["fantasy_positions"] == ["QB"]
    assert _directory()["2"]["injury_status"] == "Out"  # input untouched


def test_incumbent_team_strength_ignores_todays_injury_flags():
    snapshot = [
        {"canonicalName": "alpha one", "position": "QB", "rosValue": 40.0},
        {"canonicalName": "bravo two", "position": "QB", "rosValue": 80.0},
        {"canonicalName": "charlie three", "position": "RB", "rosValue": 30.0},
    ]
    rosters = [{"roster_id": 1, "players": ["1", "2", "3"]}]
    slots = ["QB", "RB"]
    pit = study.team_strength_rows(
        rosters, study.point_in_time_directory(_directory()), snapshot, slots
    )
    leaky = study.team_strength_rows(rosters, _directory(), snapshot, slots)
    clean = {
        k: {kk: vv for kk, vv in v.items() if not kk.startswith("injury")}
        for k, v in _directory().items()
    }
    reference = study.team_strength_rows(rosters, clean, snapshot, slots)
    assert all(not p["injured"] for p in pit[0]["fullRoster"])
    assert pit[0]["teamRosStrength"] == reference[0]["teamRosStrength"]
    # Today's flag would move the incumbent's ROS strength (the look-ahead that was removed).
    assert leaky[0]["teamRosStrength"] != pit[0]["teamRosStrength"]


def test_incumbent_never_reads_realized_weeks_at_or_after_the_target():
    rows = [
        {
            "ownerId": "T01",
            "teamRosStrength": 70.0,
            "startingLineupScore": 100.0,
            "benchDepthScore": 30.0,
        },
        {
            "ownerId": "T02",
            "teamRosStrength": 50.0,
            "startingLineupScore": 100.0,
            "benchDepthScore": 20.0,
        },
    ]
    asof = study.AsOf(5, Path("x"), "", [], rows, "test")
    realized = {w: {"T01": 300.0 + w, "T02": 280.0 - w} for w in range(1, 9)}
    tampered = {w: dict(v) for w, v in realized.items()}
    for w in (5, 6, 7, 8):
        tampered[w] = {"T01": -1e6, "T02": 1e6}
    # Presim basis for T01; T02 has no presim, so it takes the EMPIRICAL basis,
    # the arm that reads realized history.
    presim = {"T01": (290.0, 25.0)}
    for once in (False, True):
        base = study.production_distributions(
            asof, presim, tp.RealizedView(realized, 5), ros_counted_once=once
        )
        again = study.production_distributions(
            asof, presim, tp.RealizedView(tampered, 5), ros_counted_once=once
        )
        assert base == again
    with pytest.raises(tp.LeakageError):
        tp.RealizedView(realized, 5).score(5, "T02")
