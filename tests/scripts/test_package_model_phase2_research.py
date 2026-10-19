"""Phase 2 package-model research harness (owner directive 2026-10-19, Phase 2).

Pins what the Phase 2 memo rests on:

* the preregistered challenger ``EFD_78`` is exactly the incumbent-anchored
  effective-depth p-norm and passes every mandatory property, including "a
  1-point asset adds at most 1 point" (Minkowski), at full strength — the tests
  are the Phase 1 tests, not weakened;
* the geometric incumbent is value-blind by rank (the k-th piece keeps q^(k-1)
  whatever it is worth), which is the mechanism behind the deep-package result;
* calibration orients by piece count (Amendment 1), so a 1-for-1 cannot be
  signed by its own values;
* the Trade Finder replay installs a candidate in-process only and ALWAYS
  restores the production dispatch;
* market evidence carries aggregates only — no trade contents.

Nothing here changes the active model (``geom_q078_v1``).
"""

from __future__ import annotations

import importlib.util
import math
import random
import sys
from pathlib import Path

import pytest

from src.valuation_math import package_model as pm

REPO = Path(__file__).resolve().parents[2]


def _load(name: str):
    spec = importlib.util.spec_from_file_location(name, REPO / "scripts" / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


P2 = _load("package_model_phase2_research")
FR = _load("package_model_finder_replay")


def test_production_dispatch_unchanged():
    assert pm.active_model_id() == pm.GEOM_Q078_V1
    assert pm.PACKAGE_MODELS[pm.GEOM_Q078_V1]["q"] == 0.78
    assert set(pm.PACKAGE_MODELS) == {"ktc_2026_04", "geom_q078_v1"}


def test_efd_is_anchored_to_the_incumbent_two_piece_premium():
    assert P2.EFD_P == pytest.approx(1.0 / math.log2(1.78))
    u = P2.UTILITY["EFD_78"]
    # Two equal pieces keep exactly 1 + q of one piece, like the incumbent.
    assert u([5000.0, 5000.0]) == pytest.approx(5000.0 * 1.78, rel=1e-9)
    assert P2.UTILITY["GEOM_78"]([5000.0, 5000.0]) == pytest.approx(5000.0 * 1.78)


def test_efd_equals_total_times_effective_count_power():
    vals = [6000.0, 2500.0, 900.0, 300.0]
    t = sum(vals)
    n = P2.effective_count(vals)
    assert P2.UTILITY["EFD_78"](vals) == pytest.approx(t * n ** (1 / P2.EFD_P - 1), rel=1e-9)
    assert P2.effective_count([7000.0]) == pytest.approx(1.0)
    assert P2.effective_count([1000.0] * 6) == pytest.approx(6.0)


@pytest.mark.parametrize("model", ["EFD_78", "EFD_115", "EFD_130"])
def test_efd_mandatory_properties(model):
    rng = random.Random(77)
    gap = P2.MODELS[model]["gap"]
    for _ in range(400):
        A = [float(rng.randint(1, 9999)) for _ in range(rng.randint(1, 10))]
        B = [float(rng.randint(1, 9999)) for _ in range(rng.randint(1, 10))]
        g = gap(A, B)
        x = float(rng.randint(1, 9999))
        assert g <= gap(A + [x], B) <= g + x + 1e-6  # monotone, gain <= added value
        assert gap(A, B + [x]) <= g + 1e-6
        assert gap(A + [1.0], B) - g <= 1.0 + 1e-9  # the owner's 1-point rule
        assert gap(B, A) == pytest.approx(-g, abs=1e-6)
        assert gap(A[::-1], B[::-1]) == pytest.approx(g, abs=1e-6)
        assert gap([3 * v for v in A], [3 * v for v in B]) == pytest.approx(
            3 * g, rel=1e-9, abs=1e-6
        )
        i = rng.randrange(len(A))
        split = A[:i] + A[i + 1 :] + [A[i] / 2, A[i] / 2]
        assert gap(split, B) <= g + 1e-6  # unbundling never manufactures value
    assert gap([7200.0], [6000.0]) == pytest.approx(1200.0)
    assert gap([7200.0], [6000.0, 1.0]) <= 1200.0


def test_mandatory_case_for_every_monotone_phase2_candidate():
    for m, spec in P2.MODELS.items():
        if not spec["monotoneByConstruction"]:
            continue
        gap = spec["gap"]
        assert gap([7200.0], [6000.0, 1.0]) <= gap([7200.0], [6000.0]) + 1.0, m


def test_incumbent_discount_is_rank_only_value_blind():
    """The k-th piece keeps q^(k-1) of its value whether it is filler or a starter."""
    mp = P2.marginal_piece()
    for k in ("2", "6", "10"):
        ratios = {round(v["dUoverX"], 3) for v in mp["GEOM_78"][k].values()}
        assert len(ratios) == 1
    # EFD discounts a negligible piece far more than a useful one.
    assert mp["EFD_78"]["6"]["1pt"]["dUoverX"] < mp["EFD_78"]["6"]["starter_30pct"]["dUoverX"]


def test_break_even_is_homogeneous_and_ordered():
    be = P2.break_even_table()
    # Even depth needs more raw value than concentrated packages, for every model.
    for m in ("GEOM_78", "EFD_78", "HYBRID_50"):
        assert be[m]["6"]["1.00"] > be[m]["6"]["0.15"]
    # Closed form for the incumbent: n(1-q)/(1-q^n) for an even package.
    assert be["GEOM_78"]["6"]["1.00"] == pytest.approx(6 * 0.22 / (1 - 0.78**6), abs=1e-3)


def test_calibration_orients_by_piece_count():
    A, B = P2.orient([9000.0], [4000.0, 3000.0])
    assert len(A) == 1
    A, B = P2.orient([4000.0, 3000.0], [9000.0])
    assert len(A) == 1
    assert P2.structure_bin([1.0], [1.0]) == "equal"
    assert P2.structure_bin([1.0], [1.0] * 6) == "deep"
    assert P2.structure_bin([1.0], [1.0, 1.0]) == "1vN_small"
    assert P2.structure_bin([1.0, 1.0], [1.0] * 3) == "ordinary"


def test_calibration_sign_convention():
    # The consolidating side receives less raw value: raw residual is negative.
    rows = [{"ts": i, "A": [5000.0], "B": [3500.0, 3000.0]} for i in range(10)]
    cal = P2.calibration(rows, models=["RAW", "GEOM_78"])
    assert cal["byModel"]["RAW"]["all"]["1vN_small"]["meanSigned"] < 0
    # The incumbent's consolidation credit moves it toward zero.
    assert (
        cal["byModel"]["GEOM_78"]["all"]["1vN_small"]["meanSigned"]
        > cal["byModel"]["RAW"]["all"]["1vN_small"]["meanSigned"]
    )


def test_finder_replay_installs_in_process_and_always_restores():
    original = pm._geom_pair
    gap = P2.MODELS["EFD_78"]["gap"]
    with FR.installed(gap):
        assert pm._geom_pair is not original
        value, side, displayed = pm.adjust_pair([6000.0, 6000.0], [10000.0])
        assert displayed and side == 2  # the consolidating side is credited
    assert pm._geom_pair is original
    with pytest.raises(RuntimeError):
        with FR.installed(gap):
            raise RuntimeError("boom")
    assert pm._geom_pair is original
    assert pm.adjust_pair([5000], [3000, 2500]) == (550, 1, True)  # incumbent intact


def test_replay_tags_star_for_pile():
    trade = {
        "give": [{"name": "Star", "modelValue": 9000}],
        "receive": [{"name": f"P{i}", "modelValue": 2400} for i in range(4)],
    }
    tags = FR.classify(trade, P2.MODELS["RAW"]["gap"], P2.level)
    assert tags["starForPile"] is True and tags["shape"] == "1v4"


def test_market_rows_carry_no_trade_contents():
    rows = [{"ts": i, "A": [5000.0], "B": [3000.0, 2500.0], "league": "x"} for i in range(40)]
    cal = P2.calibration(rows, models=["GEOM_78"])
    blob = repr(cal)
    assert "5000" not in blob and "league" not in blob
