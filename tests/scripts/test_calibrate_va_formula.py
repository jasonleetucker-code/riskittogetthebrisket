"""Smoke + math tests for ``scripts/calibrate_va_formula.py``.

Pins the V7 → V8 collapse property: with ``stud_coeff = 0`` and
matching base params, V8 must produce identical predictions to V7.
That's the safety property — the grid search can't pick a
"stud factor that hurts" because the stud-coeff=0 variant is
strictly equivalent to V7 and will be in the search space.

Also verifies the predict_v8 monotonicity: increasing
``stud_coeff`` increases the prediction for elite-top trades and
leaves sub-threshold trades unchanged.
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
SCRIPT = REPO_ROOT / "scripts" / "calibrate_va_formula.py"


@pytest.fixture(scope="module")
def cal():
    """Import the calibration script as a module so its predict_*
    functions + DataPoint class are reachable from tests without
    a __init__.py in scripts/."""
    spec = importlib.util.spec_from_file_location("calibrate_va", SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    sys.modules["calibrate_va"] = mod
    spec.loader.exec_module(mod)
    return mod


def _point(cal, *, small, large, label="test"):
    return cal.DataPoint(
        label=label,
        small=tuple(sorted(small, reverse=True)),
        large=tuple(sorted(large, reverse=True)),
        ktc_va=0.0,  # not used by predict_*
        topology=f"{len(small)}v{len(large)}",
    )


def _v7_params():
    return {
        "slope": 4.0, "intercept": 0.30, "cap": 0.60,
        "decay": 0.50, "boost": 1.0, "effective_cap": 1.10,
    }


def _v8_params(stud_coeff=0.0, stud_threshold=7000.0):
    return {**_v7_params(), "stud_coeff": stud_coeff, "stud_threshold": stud_threshold}


def test_v8_collapses_to_v7_when_stud_coeff_zero(cal):
    """Critical safety property: V8 with stud_coeff=0 == V7 exactly.
    Means the grid search can never pick a 'V8 worse than V7' —
    the V7 result is in V8's parameter space."""
    pt = _point(cal, small=[8500], large=[6800, 4200])
    v7_pred = cal.predict_v7_full_loop(pt, _v7_params())
    v8_pred = cal.predict_v8_stud_factor(pt, _v8_params(stud_coeff=0.0))
    assert abs(v7_pred - v8_pred) < 1e-6, (
        f"V8 with stud_coeff=0 must equal V7: v7={v7_pred} v8={v8_pred}"
    )


def test_v8_collapses_when_top_below_threshold(cal):
    """Stud factor only kicks in above stud_threshold.  A trade with
    top_small < threshold gets no stud bonus regardless of coeff."""
    pt = _point(cal, small=[5000], large=[4500, 3000])
    v7_pred = cal.predict_v7_full_loop(pt, _v7_params())
    v8_pred = cal.predict_v8_stud_factor(
        pt, _v8_params(stud_coeff=1.5, stud_threshold=7000.0),
    )
    # top_small (5000) < threshold (7000) → stud_excess = 0 → mult = 1
    assert abs(v7_pred - v8_pred) < 1e-6


def test_v8_amplifies_for_elite_top(cal):
    """Elite top-piece trades get amplified relative to V7."""
    pt = _point(cal, small=[9500], large=[7500, 5000])
    v7_pred = cal.predict_v7_full_loop(pt, _v7_params())
    v8_pred = cal.predict_v8_stud_factor(
        pt, _v8_params(stud_coeff=1.0, stud_threshold=7000.0),
    )
    assert v8_pred > v7_pred, (
        f"V8 should amplify elite trades: v7={v7_pred} v8={v8_pred}"
    )


def test_v8_returns_zero_when_small_larger(cal):
    """Inverted shape (small.length > large.length) returns 0
    same as V7."""
    pt = _point(cal, small=[5000, 4000, 3000], large=[8000])
    v8_pred = cal.predict_v8_stud_factor(
        pt, _v8_params(stud_coeff=0.5),
    )
    assert v8_pred == 0.0


def test_v8_handles_equal_count_smoothly(cal):
    """V8's full-loop structure handles equal-count trades — no
    discontinuity at the count boundary (which is the whole point
    of moving to V7/V8 from V3)."""
    pt_2v2 = _point(cal, small=[8500, 4000], large=[7800, 5200])
    pt_2v3 = _point(cal, small=[8500, 4000], large=[7800, 5200, 1500])
    v8_2v2 = cal.predict_v8_stud_factor(pt_2v2, _v8_params(stud_coeff=0.5))
    v8_2v3 = cal.predict_v8_stud_factor(pt_2v3, _v8_params(stud_coeff=0.5))
    # Both should be > 0; 2v3 should be larger (extra piece adds VA).
    assert v8_2v2 > 0
    assert v8_2v3 > v8_2v2


def test_v8_monotonic_in_stud_coeff(cal):
    """For an elite-top trade, prediction is monotonically
    non-decreasing in stud_coeff."""
    pt = _point(cal, small=[9000], large=[7500, 4500])
    base = _v8_params(stud_coeff=0.0)
    coeffs = [0.0, 0.25, 0.5, 1.0, 1.5]
    preds = [
        cal.predict_v8_stud_factor(pt, {**base, "stud_coeff": c})
        for c in coeffs
    ]
    for i in range(len(preds) - 1):
        assert preds[i + 1] >= preds[i], (
            f"V8 must be monotonic in stud_coeff: {preds}"
        )


def test_v8_in_main_candidates_list(cal):
    """V8 must be wired into main()'s candidate list so the ranking
    summary includes it.  We don't run main() (it's a 2-min grid
    search) — just verify the source contains the registration."""
    src = SCRIPT.read_text(encoding="utf-8")
    assert "predict_v8_stud_factor" in src
    assert '("V8"' in src or "'V8'" in src
