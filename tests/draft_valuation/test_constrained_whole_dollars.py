"""Constrained minimum-deviation whole dollars (owner decision 2026-10-18).

Step A (largest remainder) is used unchanged whenever it satisfies every
constraint; otherwise Step B solves the constrained integer problem exactly.
Verified here against two methods that share nothing with production: an
exhaustive brute force on small instances and a forward scalarised DP on the
72-pick curve (``reference_workbook_formulas``).
"""

from __future__ import annotations

import random
from fractions import Fraction

import pytest

from src.draft.rookie_auction.apportion import (
    METHOD_CONSTRAINED,
    METHOD_LARGEST_REMAINDER,
    OBJECTIVE,
    ApportionmentRefused,
    apportion_whole_dollars,
)
from src.draft.rookie_auction.curve import compute_curve
from tests.draft_valuation import _workbook as wb
from tests.draft_valuation import reference_workbook_formulas as ref
from tests.draft_valuation.test_curve_properties import _case


def test_hand_built_case_where_rounding_fails_but_an_allocation_exists():
    r = [Fraction(7, 2), Fraction(3, 2), Fraction(3, 2), Fraction(3, 2)]
    floors = [1, 2, 2, 2]
    # Simple rounding: floors 3,1,1,1, residual 2 -> 4,2,1,1 -> below the floor.
    with pytest.raises(ref.Refused):
        ref.whole_dollars(r, 8, floors)
    out = apportion_whole_dollars(r, 8, floors=floors)
    assert out.method == METHOD_CONSTRAINED
    assert out.step_a_dollars == (4, 2, 1, 1)
    assert out.dollars == (2, 2, 2, 2)
    assert out.total_deviation == 3 and out.max_deviation == Fraction(3, 2)
    assert out.repairs == ((0, -2), (2, 1), (3, 1))
    assert out.step_a_violations == ("below_floor@2", "below_floor@3")
    assert ref.brute_force_min_deviation(r, 8, floors) == (Fraction(3), (2, 2, 2, 2))


def test_step_a_is_used_unchanged_when_it_satisfies_everything():
    rows = wb.rows()
    res = compute_curve([r["B"] for r in rows], [[r[c] for r in rows] for c in "FGH"])
    w = res.whole_dollars
    assert w.method == METHOD_LARGEST_REMAINDER and w.repairs == ()
    assert w.dollars == w.step_a_dollars  # the 2027 workbook output does not move
    assert w.total_deviation == 14  # 28 half-dollar picks x 0.50


def _random_instance(rng: random.Random):
    n = rng.randint(2, 6)
    total = rng.randint(n, 18)
    cuts = sorted(rng.randint(0, 4 * total) for _ in range(n - 1))
    parts = [b - a for a, b in zip([0, *cuts], [*cuts, 4 * total])]
    r = sorted((Fraction(p, 4) for p in parts), reverse=True)
    floors = [rng.choice([None, 0, 1, 2]) for _ in range(n)]
    caps = [rng.choice([None, None, rng.randint(1, total)]) for _ in range(n)]
    return r, total, floors, caps


def test_matches_exhaustive_brute_force_on_500_small_instances():
    rng = random.Random(20261018)
    counts = {"step_a": 0, "constrained": 0, "infeasible": 0}
    for _ in range(500):
        r, total, floors, caps = _random_instance(rng)
        brute = ref.brute_force_min_deviation(r, total, floors, caps)
        try:
            out = apportion_whole_dollars(r, total, floors=floors, caps=caps)
        except ApportionmentRefused as exc:
            assert exc.conflict == "infeasible", exc
            assert brute is None
            counts["infeasible"] += 1
            continue
        assert brute is not None
        assert (out.total_deviation, out.dollars) == brute
        assert ref.check_whole_dollar_invariants(list(out.dollars), r, total, floors, caps) == []
        counts["step_a" if out.method == METHOD_LARGEST_REMAINDER else "constrained"] += 1
    assert all(v > 0 for v in counts.values()), counts


def test_a_recovered_simulated_class():
    res = compute_curve(*_case(25))
    w = res.whole_dollars
    floors, caps = ref.dynasty_main_whole_dollar_bounds()
    half = [Fraction(u, 2) for u in res.units]
    with pytest.raises(ref.Refused):  # simple rounding fails
        ref.whole_dollars(half, 1200, floors, caps)
    assert w.method == METHOD_CONSTRAINED and any(
        v.startswith("below_floor") for v in w.step_a_violations
    )
    assert sum(w.dollars) == 1200 and w.max_deviation == Fraction(1, 2)
    assert sum(d for _, d in w.repairs) == 0  # no dollars created or removed
    dev, vec = ref.forward_dp_min_deviation(half, 1200, floors, caps, bound=w.total_deviation)
    assert (dev, vec) == (w.total_deviation, w.dollars)


def test_receipt_states_the_method_objective_and_repairs():
    res = compute_curve(*_case(25))
    rec = res.whole_dollars.receipt([r.label for r in res.rows])
    assert rec["method"] == "constrained_min_deviation" and rec["objective"] == OBJECTIVE
    assert rec["objectiveValue"] == str(res.whole_dollars.total_deviation)
    assert rec["repairs"] and all({"pick", "delta"} <= set(x) for x in rec["repairs"])
    assert rec["stepAViolations"] and rec["bindingConstraints"]
    assert sum(rec["finalWholeDollars"]) == 1200
