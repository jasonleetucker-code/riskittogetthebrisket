"""Batch A — properties of the canonical curve on randomized inputs.

Production (Decimal, ``src/draft/rookie_auction/curve.py``) is compared
against the independent float transcription (``reference_workbook_formulas``)
on seeded random inputs.  Where production reports a decision within 1e-9 of
its boundary, double arithmetic could legitimately decide differently, so
those cases are counted and excluded — and the test requires them to be rare.
"""

from __future__ import annotations

import math
import random
from decimal import Decimal

import pytest

from src.draft.rookie_auction.curve import (
    WORKBOOK_PARAMS,
    CurveInputError,
    CurveParams,
    _excel_mod,
    _excel_quotient,
    compute_curve,
)
from tests.draft_valuation import _workbook as wb
from tests.draft_valuation import reference_workbook_formulas as ref

N = 72
SEEDS = range(250)


def _random_curve(rng: random.Random) -> list[float]:
    """A non-increasing half-dollar curve summing to exactly $1200."""
    shape = sorted(
        (math.exp(-rng.uniform(0.04, 0.12) * i) * rng.uniform(0.7, 1.3) for i in range(N)),
        reverse=True,
    )
    total = sum(shape)
    units = [max(2, int(2400 * s / total)) for s in shape]
    units.sort(reverse=True)
    i = 0
    while sum(units) < 2400:
        units[i % 12] += 1
        i += 1
    while sum(units) > 2400:
        j = max(k for k in range(N) if units[k] > 2)
        units[j] -= 1
    units.sort(reverse=True)
    return [u / 2 for u in units]


def _random_values(rng: random.Random) -> list[float]:
    top = rng.uniform(4000, 9999)
    vals = [
        round(top * math.exp(-rng.uniform(0.01, 0.06) * i) * rng.uniform(0.8, 1.2) * 2) / 2
        for i in range(N)
    ]
    if rng.random() < 0.5:  # the workbook's column B is not sorted either
        return vals
    return sorted(vals, reverse=True)


def _case(seed: int):
    rng = random.Random(seed)
    return _random_values(rng), [_random_curve(rng) for _ in range(3)]


@pytest.fixture(scope="module")
def results():
    return [(seed, *_case(seed), compute_curve(*_case(seed))) for seed in SEEDS]


def test_budget_is_exact_and_values_nonnegative(results):
    for _seed, _b, _c, res in results:
        assert res.total_units == 2400
        assert sum(res.dollars, Decimal(0)) == Decimal(1200)
        assert all(u >= 0 for u in res.units)


def test_curve_is_non_increasing(results):
    for _seed, _b, _c, res in results:
        assert all(res.units[i] <= res.units[i - 1] for i in range(1, N))
        k = [r.monotone_units for r in res.rows]
        assert all(k[i] <= k[i - 1] for i in range(1, N))


def test_round_specific_constraints(results):
    for _seed, _b, _c, res in results:
        for row in res.rows:
            if row.round == 5:
                assert row.final_units <= 4  # $2 cap
            if row.round == 6:
                assert row.final_units <= 2  # $1 cap
            if row.index >= WORKBOOK_PARAMS.carry_picks:
                assert row.carry_units == 0 and row.final_units == row.monotone_units
            assert row.floor_units == int(row.curve_value * 2)
            assert row.curve_value >= row.floor_dollars
        # floors: $1 every pick plus $1 for round 5 — the sheet's literal 84.
        assert res.floor_pool_dollars == 84
        # carry is QUOTIENT/MOD of the post-cap residual over the first M1 picks.
        assert sum(r.carry_units for r in res.rows) == res.residual_after_caps_units


def test_deterministic_and_curve_order_invariant():
    b, curves = _case(7)
    first = compute_curve(b, curves)
    again = compute_curve(list(b), [list(c) for c in curves])
    permuted = compute_curve(b, [curves[2], curves[0], curves[1]])
    assert first == again
    assert first.units == permuted.units


def test_production_equals_independent_reference(results):
    near_boundary = 0
    for _seed, b, curves, res in results:
        if res.precision_margin is not None and res.precision_margin < Decimal("1e-9"):
            near_boundary += 1
            continue
        rows = {i + 2: v for i, v in enumerate(b)}
        f, g, h = ({i + 2: v for i, v in enumerate(c)} for c in curves)
        out = ref.evaluate_sheet(rows, f, g, h, M1=12)
        for row in res.rows:
            r = row.index + 2
            assert row.floor_units == out["I"][r]
            assert row.monotone_units == out["K"][r]
            assert row.final_dollars == Decimal(str(out["D"][r]))
            assert abs(float(row.curve_value) - out["C"][r]) < 1e-8
    assert near_boundary <= len(SEEDS) // 50


def test_workbook_inputs_as_strings_and_decimals_agree():
    rows = wb.rows()
    as_float = compute_curve([r["B"] for r in rows], [[r[c] for r in rows] for c in "FGH"])
    as_str = compute_curve([str(r["B"]) for r in rows], [[str(r[c]) for r in rows] for c in "FGH"])
    as_dec = compute_curve(
        [Decimal(str(r["B"])) for r in rows], [[Decimal(str(r[c])) for r in rows] for c in "FGH"]
    )
    assert as_float.units == as_str.units == as_dec.units


@pytest.mark.parametrize("budget", [1000, 1200, 1500])
@pytest.mark.parametrize("m1", [6, 12])
def test_parameterised_budget_and_m1_still_exact(budget, m1):
    b, curves = _case(3)
    scale = Decimal(budget) / Decimal(1200)
    scaled = [[Decimal(str(v)) * scale for v in c] for c in curves]
    res = compute_curve(b, scaled, CurveParams(budget_dollars=budget, carry_picks=m1))
    assert res.total_units == budget * 2
    assert all(r.carry_units == 0 for r in res.rows[m1:])


# --- input validation: missing is never zero -----------------------------------------


def test_missing_rookie_value_is_refused_not_zeroed():
    b, curves = _case(1)
    b[10] = None
    with pytest.raises(CurveInputError, match="missing"):
        compute_curve(b, curves)


def test_missing_historical_value_is_refused():
    b, curves = _case(1)
    curves[1][40] = None
    with pytest.raises(CurveInputError, match="missing"):
        compute_curve(b, curves)


@pytest.mark.parametrize("bad", [float("nan"), float("inf"), -1.0, 0, 0.0, True, "abc"])
def test_bad_values_are_refused(bad):
    b, curves = _case(1)
    b[5] = bad
    with pytest.raises(CurveInputError):
        compute_curve(b, curves)


def test_wrong_lengths_and_curve_counts_are_refused():
    b, curves = _case(1)
    with pytest.raises(CurveInputError):
        compute_curve(b[:60], curves)
    with pytest.raises(CurveInputError):
        compute_curve(b, curves[:2])
    with pytest.raises(CurveInputError):
        compute_curve(b, [curves[0], curves[1], curves[2][:71]])


def test_invalid_params_are_refused():
    b, curves = _case(1)
    with pytest.raises(CurveInputError):
        compute_curve(b, curves, CurveParams(carry_picks=0))
    with pytest.raises(CurveInputError):
        compute_curve(b, curves, CurveParams(carry_picks=73))


def test_spreadsheet_integer_semantics():
    # QUOTIENT truncates toward zero; MOD takes the divisor's sign.
    assert _excel_quotient(17, 12) == 1 and _excel_mod(17, 12) == 5
    assert _excel_quotient(-1, 12) == 0 and _excel_mod(-1, 12) == 11
    assert _excel_quotient(-13, 12) == -1 and _excel_mod(-13, 12) == 11
