"""Low-value-asset research treatments (owner directive 2026-10-20).

Pins the mathematical properties each shadow treatment claims, at full strength,
including where the replacement anchor differs by position.  Research only —
the production package model is asserted unchanged.
"""

from __future__ import annotations

import importlib.util
import random
import sys
from pathlib import Path

import pytest

from src.valuation_math import package_model as pm

REPO = Path(__file__).resolve().parents[2]
_spec = importlib.util.spec_from_file_location(
    "low_value_asset_treatments", REPO / "scripts" / "low_value_asset_treatments.py"
)
T = importlib.util.module_from_spec(_spec)
sys.modules["low_value_asset_treatments"] = T
_spec.loader.exec_module(T)

POS = ["QB", "RB", "WR", "TE", "DL", "LB", "DB", "K", None]
REP = {
    "QB": 2600.0,
    "RB": 1900.0,
    "WR": 2100.0,
    "TE": 1500.0,
    "DL": 700.0,
    "LB": 800.0,
    "DB": 650.0,
    "K": 300.0,
    "*": 1800.0,
}


def _side(rng, n):
    return [(float(rng.randint(1, 9999)), rng.choice(POS)) for _ in range(n)]


def test_production_dispatch_unchanged():
    assert pm.active_model_id() == pm.GEOM_Q078_V1
    assert pm.PACKAGE_MODELS[pm.GEOM_Q078_V1]["q"] == 0.78


def test_currency_curve_shape():
    assert T.g(0, 2000) == 0.0
    assert T.g(1000, 0) == 1000.0
    for v in (50.0, 500.0, 2000.0, 9000.0):
        assert 0 < T.g(v, 2000) < v
    # exact identity: g(v) = v - c + c^2 / (v + c), so g -> v - c as v grows
    assert T.g(9000, 2000) == pytest.approx(9000 - 2000 + 2000**2 / 11000)
    assert T.g(90000, 2000) == pytest.approx(90000 - 2000, rel=0.001)
    xs = [T.g(v, 2000) for v in range(1, 9999, 37)]
    assert all(b > a for a, b in zip(xs, xs[1:]))  # strictly increasing


@pytest.mark.parametrize("name", sorted(T.TREATMENTS))
def test_mandatory_properties(name):
    rng = random.Random(len(name) * 101)
    for _ in range(600):
        A, B = _side(rng, rng.randint(1, 8)), _side(rng, rng.randint(1, 8))
        g = T.gap(name, A, B, REP)
        x = (float(rng.randint(1, 9999)), rng.choice(POS))
        added = T.gap(name, A + [x], B, REP)
        assert g - 1e-6 <= added <= g + x[0] + 1e-6  # adding never hurts, adds <= its value
        assert T.gap(name, A, B + [x], REP) <= g + 1e-6
        i = rng.randrange(len(A))
        raised = A[:i] + [(A[i][0] + x[0], A[i][1])] + A[i + 1 :]
        assert T.gap(name, raised, B, REP) >= g - 1e-6  # raising a value never hurts
        assert T.gap(name, B, A, REP) == pytest.approx(-g, abs=1e-6)
        assert T.gap(name, A[::-1], B[::-1], REP) == pytest.approx(g, abs=1e-6)
        # continuity: a tiny piece changes almost nothing
        assert abs(T.gap(name, A + [(0.01, "WR")], B, REP) - g) <= 0.01 + 1e-9


def test_one_for_one_is_raw_except_the_curve_approach():
    for name, spec in T.TREATMENTS.items():
        g = T.gap(name, [(1500.0, "WR")], [(1200.0, "LB")], REP)
        if spec["approach"] == "A":
            assert g != pytest.approx(300.0)  # A re-prices the assets themselves
        else:
            assert g == pytest.approx(300.0)


def test_not_homogeneous_is_reported_not_hidden():
    a, b = [(6000.0, "WR")], [(4000.0, "RB"), (2500.0, "WR")]
    for name in ("B_currency_market", "A_curve_market"):
        g1 = T.gap(name, a, b, REP)
        g3 = T.gap(name, [(3 * v, p) for v, p in a], [(3 * v, p) for v, p in b], REP)
        assert g3 != pytest.approx(3 * g1)
    assert T.gap("GEOM_78", [(18000.0, "WR")], [(12000.0, "RB"), (7500.0, "WR")]) == pytest.approx(
        3 * T.gap("GEOM_78", a, b)
    )


def test_replacement_anchor_keeps_usable_idp_depth_and_discounts_wr_filler():
    star = [(6000.0, "WR")]
    lb_depth = [(4800.0, "RB"), (1500.0, "LB")]  # LB 1500 is well above LB replacement (800)
    wr_filler = [(4800.0, "RB"), (1500.0, "WR")]  # WR 1500 is below WR replacement (2100)
    g_lb = T.gap("B_currency_replacement", star, lb_depth, REP)
    g_wr = T.gap("B_currency_replacement", star, wr_filler, REP)
    assert g_lb < g_wr  # the usable LB moves the trade more than the WR filler
    assert T.gap("B_currency_market", star, lb_depth, REP) == pytest.approx(
        T.gap("B_currency_market", star, wr_filler, REP)
    )


def test_unknown_position_falls_back_to_league_level_not_zero():
    assert T.anchor_for("B_currency_replacement", None, REP) == REP["*"]
    assert T.anchor_for("B_currency_replacement", "XX", REP) == REP["*"]
    assert T.anchor_for("GEOM_78", "WR", REP) == 0.0
