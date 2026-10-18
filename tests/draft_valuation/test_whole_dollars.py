"""Whole-dollar final step (owner decision 2026-10-18) — production vs independent reference.

The half-dollar curve (workbook column L) stays the mathematical reference;
``apportion_whole_dollars`` is the separately identified final step: floor,
residual, +1 to the largest remainders with ties to the earlier draft
position, then verify sum / monotonicity / floors / caps or refuse.
"""

from __future__ import annotations

from decimal import Decimal
from fractions import Fraction

import pytest

from src.draft.rookie_auction.apportion import ApportionmentRefused, apportion_whole_dollars
from src.draft.rookie_auction.curve import (
    CurveInvariantError,
    compute_curve,
    curve_receipt,
    whole_dollar_constraints,
)
from tests.draft_valuation import _workbook as wb
from tests.draft_valuation import reference_workbook_formulas as ref

#: The 72 published whole-dollar values for the 2026-10-17 workbook inputs.
EXPECTED_WHOLE = [
    135, 101, 93, 81, 76, 69, 55, 54, 46, 45, 41, 36,
    30, 29, 27, 24, 22, 19, 18, 16, 14, 13, 11, 10,
    9, 9, 7, 7, 6, 6, 5, 5, 4, 4, 4, 4,
    3, 3, 3, 3, 3, 2, 2, 2, 2, 2, 2, 2,
    2, 2, 2, 2, 2, 2, 2, 2, 2, 2, 2, 2,
    1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1,
]  # fmt: skip
EXPECTED_PLUS_ONE = [
    "1.01", "1.02", "1.04", "1.05", "1.06", "1.07", "1.08",
    "1.10", "1.12", "2.01", "2.02", "2.03", "2.05", "2.07",
]  # fmt: skip


@pytest.fixture(scope="module")
def production():
    rows = wb.rows()
    return compute_curve([r["B"] for r in rows], [[r[c] for r in rows] for c in "FGH"])


def _half_dollar_reference():
    return [Fraction(str(r["L"])) for r in wb.rows()]


# --- the real workbook ------------------------------------------------------------


def test_workbook_whole_dollars_exact(production):
    assert list(production.final_whole_dollars) == EXPECTED_WHOLE
    assert sum(EXPECTED_WHOLE) == 1200
    assert all(isinstance(d, int) for d in production.final_whole_dollars)
    assert all(EXPECTED_WHOLE[i] <= EXPECTED_WHOLE[i - 1] for i in range(1, 72))


def test_half_dollar_reference_is_preserved(production):
    assert list(production.dollars) == [Decimal(str(r["L"])) for r in wb.rows()]
    assert sum(1 for r in wb.rows() if float(r["L"]) % 1) == 28


def test_the_28_half_dollar_picks_resolve_deterministically(production):
    w = production.whole_dollars
    labels = [r.label for r in production.rows]
    halves = [labels[i] for i in range(72) if production.rows[i].final_units % 2]
    assert len(halves) == 28
    assert (sum(w.floored), w.residual) == (1186, 14)
    plus = [labels[i] for i in w.plus_one_indices]
    assert plus == EXPECTED_PLUS_ONE == halves[:14]  # all tied at 0.5: earlier picks first


def test_independent_reference_agrees_on_the_workbook(production):
    floors, caps = ref.dynasty_main_whole_dollar_bounds()
    out, plus = ref.whole_dollars(_half_dollar_reference(), 1200, floors, caps)
    assert out == EXPECTED_WHOLE
    assert plus == list(production.whole_dollars.plus_one_indices)
    # And the reference's bounds are the production constraints.
    assert (floors, caps) == tuple(list(x) for x in whole_dollar_constraints())


def test_slot_budgets_are_integers_summing_to_1200(production):
    d = production.final_whole_dollars
    slots = [sum(d[r * 12 + s] for r in range(6)) for s in range(12)]
    assert slots == [180, 145, 133, 118, 110, 99, 83, 80, 69, 67, 61, 55]
    assert sum(slots) == 1200
    assert [sum(d[r * 12 : (r + 1) * 12]) for r in range(6)] == [832, 233, 70, 29, 24, 12]


def test_receipt_carries_both_curves(production):
    r = curve_receipt(production)
    assert r["totalDollars"] == "1200" and sum(r["finalUnits"]) == 2400
    wd = r["wholeDollars"]
    assert wd["finalWholeDollars"] == EXPECTED_WHOLE
    assert wd["residual"] == 14 and wd["flooredSum"] == 1186
    assert wd["plusOne"] == EXPECTED_PLUS_ONE
    assert r["tieRule"] == "earlier_pick_first"


# --- edge cases: production primitive and independent reference agree --------------


def _both(values, total, floors=None, caps=None):
    prod = apportion_whole_dollars(values, total, floors=floors, caps=caps)
    out, plus = ref.whole_dollars([Fraction(v) for v in values], total, floors, caps)
    assert list(prod.dollars) == out and list(prod.plus_one_indices) == plus
    return prod


def test_all_integer_input_is_a_no_op():
    p = _both([Fraction(5), Fraction(3), Fraction(2)], 10)
    assert p.dollars == (5, 3, 2) and p.residual == 0 and p.plus_one_indices == ()


def test_every_remainder_tied_goes_to_earlier_picks():
    p = _both([Fraction(5, 2)] * 4, 10)
    assert p.dollars == (3, 3, 2, 2) and p.plus_one_indices == (0, 1)


def test_tie_straddling_the_residual_cutoff():
    vals = [Fraction(13, 4), Fraction(5, 2), Fraction(5, 2), Fraction(7, 4)]
    p = _both(vals, 10)
    # remainders .25 .5 .5 .75; residual 2 -> .75 (idx 3) then the EARLIER .5 (idx 1)
    assert p.plus_one_indices == (1, 3) and p.dollars == (3, 3, 2, 2)


def test_largest_remainder_wins_regardless_of_position():
    p = _both([Fraction(41, 10), Fraction(39, 10), Fraction(2)], 10)
    assert p.dollars == (4, 4, 2) and p.plus_one_indices == (1,)


@pytest.mark.parametrize(
    "values,total,conflict",
    [
        ([Fraction(5), Fraction(3)], 10, "sum_not_total"),
        ([Fraction(1), Fraction(2), Fraction(3)], 6, "not_non_increasing"),
        ([Fraction(-1), Fraction(11)], 10, "negative_value"),
        ([Decimal("NaN"), Fraction(10)], 10, "non_finite"),
        ([Decimal("Infinity"), Fraction(10)], 10, "non_finite"),
        ([float("nan"), Fraction(10)], 10, "float_input"),
        ([0.5, Fraction(19, 2)], 10, "float_input"),
        ([None, Fraction(10)], 10, "missing_value"),
        (["abc", Fraction(10)], 10, "not_a_number"),
        ([True, Fraction(9)], 10, "not_a_number"),
    ],
)
def test_refusals_name_the_conflict(values, total, conflict):
    with pytest.raises(ApportionmentRefused) as exc:
        apportion_whole_dollars(values, total)
    assert exc.value.conflict == conflict


def test_reference_refuses_the_same_cases():
    for values, total in (
        ([Fraction(5), Fraction(3)], 10),
        ([Fraction(1), Fraction(2), Fraction(3)], 6),
        ([0.5, Fraction(19, 2)], 10),
    ):
        with pytest.raises(ref.Refused):
            ref.whole_dollars(values, total)


def test_floor_and_cap_violations_refuse():
    with pytest.raises(ApportionmentRefused) as exc:
        apportion_whole_dollars([Fraction(5), Fraction(3), Fraction(2)], 10, caps=[None, 2, None])
    assert exc.value.conflict == "above_cap"
    with pytest.raises(ApportionmentRefused) as exc:
        apportion_whole_dollars([Fraction(5), Fraction(3), Fraction(2)], 10, floors=[1, 1, 3])
    assert exc.value.conflict == "below_floor"
    with pytest.raises(ref.Refused):
        ref.whole_dollars([Fraction(5), Fraction(3), Fraction(2)], 10, caps=[None, 2, None])


def test_total_is_never_changed():
    with pytest.raises(ApportionmentRefused):
        apportion_whole_dollars([Fraction(1201, 2), Fraction(1201, 2)], 1200)


# --- seeded random cases through the whole-dollar step ------------------------------


def test_random_cases_through_the_whole_dollar_step():
    from tests.draft_valuation.test_curve_properties import SEEDS, _case

    floors, caps = ref.dynasty_main_whole_dollar_bounds()
    accepted = refused = 0
    for seed in SEEDS:
        res = compute_curve(*_case(seed))
        half = [Fraction(u, 2) for u in res.units]
        try:
            out, plus = ref.whole_dollars(half, 1200, floors, caps)
        except ref.Refused:
            out = None
        if out is None:
            refused += 1
            assert res.whole_dollars is None and res.whole_dollars_refusal
            with pytest.raises(CurveInvariantError):
                res.final_whole_dollars
            continue
        accepted += 1
        assert list(res.final_whole_dollars) == out
        assert list(res.whole_dollars.plus_one_indices) == plus
        assert sum(out) == 1200 and all(out[i] <= out[i - 1] for i in range(1, 72))
    # Refusals happen only where the half-dollar curve itself dips below the
    # round-5 $2 floor (round 4 ending under $2 in the synthetic shapes).
    assert accepted > refused > 0
