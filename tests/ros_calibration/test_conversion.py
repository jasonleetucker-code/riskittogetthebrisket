"""Conversion models: fitting rules, fallbacks, and missing-is-never-zero."""

from __future__ import annotations

import math

import pytest

from src.league_intel import sim_calibration as sc
from src.ros_calibration import conversion as cv


def _rows(family: str, n: int, slope: float, intercept: float = 1.0, start: float = 5.0):
    rows = []
    for i in range(n):
        r = start + i
        rows.append(cv.FitRow(family, r, n - i, intercept + slope * r))
    return rows


def test_ols_exact_line():
    a, b = cv.ols([1.0, 2.0, 3.0], [3.0, 5.0, 7.0])
    assert a == pytest.approx(1.0)
    assert b == pytest.approx(2.0)


def test_ols_refuses_no_spread():
    assert cv.ols([2.0, 2.0, 2.0], [1.0, 2.0, 3.0]) is None


def test_fallback_constant_mirrors_production_owner():
    assert cv.FALLBACK_ROS_VALUE_PER_POINT == sc.FALLBACK_ROS_VALUE_PER_POINT


def test_family_fit_and_group_fallback():
    rows = _rows("LB", 40, 0.5) + _rows("DL", 10, 0.2) + _rows("DB", 30, 0.3)
    m = cv.fit_model("CF", rows)
    assert m.fits["LB"].source == "CF:LB"
    assert m.fits["LB"].b == pytest.approx(0.5)
    # DL is below the floor -> its group's (IDP) CG fit, labelled as a fallback.
    assert m.fits["DL"].source.startswith("CG:IDP")
    assert "fallback for DL" in m.fits["DL"].source


def test_wrong_sign_slope_falls_back():
    rows = _rows("QB", 40, -0.3, intercept=30.0) + _rows("WR", 40, 0.4)
    m = cv.fit_model("CF", rows)
    assert m.fits["QB"].source.startswith("CG:OFF")


def test_group_below_floor_takes_pooled_champion():
    rows = _rows("WR", 40, 0.4) + _rows("K", 5, 0.1)
    m = cv.fit_model("CG", rows)
    assert m.fits["K"].source.startswith("C0:*")


def test_champion_is_one_shared_scale():
    rows = _rows("WR", 40, 0.4) + _rows("LB", 40, 0.2)
    m = cv.fit_model("C0", rows)
    assert set(m.fits) == {"*"}
    assert m.predict("WR", 10.0, 3) == m.predict("LB", 10.0, 3)


def test_predict_missing_is_none_not_zero():
    m = cv.fit_model("CG", _rows("WR", 40, 0.4) + _rows("LB", 40, 0.2))
    assert m.predict("WR", None, 1) is None
    assert m.predict("WR", 0.0, 1) is None
    assert m.predict("WR", float("nan"), 1) is None
    assert m.predict("XX", 10.0, 1) is None
    assert m.predict(None, 10.0, 1) is None


def test_reference_f_is_production_fallback():
    m = cv.fit_model("F", [])
    assert m.predict("QB", 27.0, 1) == pytest.approx(10.0)


def test_rank_curve_is_level_step_invariant():
    snap = [{"canonicalName": f"p{i}", "position": "LB", "rosValue": 80.0 - i} for i in range(60)]
    stepped = [{**p, "rosValue": p["rosValue"] * 1.45} for p in snap]
    rows = []
    lad = cv.family_ladders(snap)
    for i, p in enumerate(snap[:40]):
        rows.append(
            cv.FitRow(
                "LB",
                p["rosValue"],
                cv.rank_in_family(lad, "LB", p["rosValue"]),
                20 - 3 * math.log(i + 1),
            )
        )
    m = cv.fit_model("CR", rows)
    assert m.fits["LB"].source == "CR:LB"
    lad2 = cv.family_ladders(stepped)
    for p, q in zip(snap[:10], stepped[:10]):
        a = m.predict("LB", p["rosValue"], cv.rank_in_family(lad, "LB", p["rosValue"]))
        b = m.predict("LB", q["rosValue"], cv.rank_in_family(lad2, "LB", q["rosValue"]))
        assert a == pytest.approx(b)


def test_rank_in_family_competition_rank():
    lad = cv.family_ladders(
        [
            {"position": "CB", "rosValue": 50.0},
            {"position": "S", "rosValue": 40.0},
            {"position": "DB", "rosValue": 40.0},
            {"position": "DB", "rosValue": 0.0},
            {"position": "FB", "rosValue": 99.0},
        ]
    )
    assert lad == {"DB": [50.0, 40.0, 40.0]}
    assert cv.rank_in_family(lad, "DB", 60.0) == 1
    assert cv.rank_in_family(lad, "DB", 50.0) == 1
    assert cv.rank_in_family(lad, "DB", 40.0) == 2
    assert cv.rank_in_family(lad, "DB", 10.0) == 4
    assert cv.rank_in_family(lad, "DB", 0.0) is None
    assert cv.rank_in_family(lad, "LB", 10.0) is None


def test_mu_is_floored_at_zero():
    m = cv.ConversionModel("CF", {"WR": cv.LinearFit(-5.0, 0.1, 40, "CF:WR")})
    assert m.predict("WR", 10.0, 50) == 0.0


def test_unknown_model_refused():
    with pytest.raises(ValueError):
        cv.fit_model("CX", [])
