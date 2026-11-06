"""Independent expected-result oracle for the ACTIVE package model ``geom_q078_v1``.

Oracle sources (never the function under test):

* hand-computed known answers in ``tests/fixtures/package_model_oracle_cases.json``
  (arithmetic written out per row; the same table is pinned on the JS owner by
  ``frontend/__tests__/package-model-oracle.test.js``);
* an exact-rational reference implementation written below from the SPEC
  (CLAUDE.md "Trade comparison" + ``docs/valuation/PACKAGE_MODEL_OWNER_ACTIVATION_2026-10-17.md``):
  ``U = sum q^(i-1) * v_i`` over positive values sorted descending, ``q = 78/100``;
  per-side discarded depth ``D = raw - U``; the side that discarded LESS depth
  receives ``|D1 - D2|`` rounded half-UP (JavaScript ``Math.round``), so
  ``adjusted_1 - adjusted_2 == U_1 - U_2`` up to that integer rounding.

QA directive 2026-11-06 (CW-49 Phase 2).  Offline, deterministic.
"""

from __future__ import annotations

import json
import math
import random
from fractions import Fraction
from pathlib import Path

import pytest

from src.valuation_math import package_model as pm
from src.valuation_math.ktc_va_core import js_round

REPO = Path(__file__).resolve().parents[2]
ORACLE = json.loads(
    (REPO / "tests/fixtures/package_model_oracle_cases.json").read_text(encoding="utf-8")
)
GEOM = "geom_q078_v1"
Q = Fraction(78, 100)


# ── reference implementation, from the spec only ──────────────────────
def ref_utility(values) -> Fraction:
    pos = sorted((Fraction(v) for v in values if v > 0), reverse=True)
    return sum((Q**i * v for i, v in enumerate(pos)), Fraction(0))


def ref_raw(values) -> Fraction:
    return sum((Fraction(v) for v in values if v > 0), Fraction(0))


def ref_adjust(a, b):
    """-> (value, side, exact_abs_diff).  side 1 = team1 receives."""
    if not any(v > 0 for v in a) or not any(v > 0 for v in b):
        return 0, 0, Fraction(0)
    d1 = ref_raw(a) - ref_utility(a)
    d2 = ref_raw(b) - ref_utility(b)
    diff = abs(d1 - d2)
    value = math.floor(diff + Fraction(1, 2))
    if value <= 0:
        return 0, 0, diff
    return value, (1 if d2 > d1 else 2), diff


def _near_half(diff: Fraction) -> bool:
    return abs((diff % 1) - Fraction(1, 2)) < Fraction(1, 10**6)


def _prod(a, b):
    value, side, _ = pm.adjust_pair(a, b, model_id=GEOM)
    return value, side


def _gap(a, b):
    value, side, shown = pm.adjust_pair(a, b, model_id=GEOM)
    va_a = value if shown and side == 1 else 0
    va_b = value if shown and side == 2 else 0
    return (sum(v for v in a if v > 0) + va_a) - (sum(v for v in b if v > 0) + va_b)


def _sweep(seed: int, n: int):
    rng = random.Random(seed)
    for _ in range(n):
        a = [rng.randint(0, 9999) for _ in range(rng.randint(0, 6))]
        b = [rng.randint(0, 9999) for _ in range(rng.randint(0, 6))]
        yield a, b


# ── the active model really is the one under test ─────────────────────
def test_active_model_is_geom_q078():
    assert pm.active_model_id() == GEOM
    assert pm.PACKAGE_MODELS[GEOM]["q"] == 0.78
    assert ORACLE["q"] == 0.78


# ── hand-computed known answers ───────────────────────────────────────
@pytest.mark.parametrize("case", ORACLE["handCases"], ids=lambda c: c["name"])
def test_hand_computed_known_answer(case):
    value, side, shown = pm.adjust_pair(case["team1"], case["team2"], model_id=GEOM)
    assert (value, side) == (case["value"], case["side"]), case["arithmetic"]
    assert shown is (case["value"] > 0)
    # The default (active) dispatch is the same model.
    assert pm.adjust_pair(case["team1"], case["team2"])[:2] == (case["value"], case["side"])


@pytest.mark.parametrize("case", ORACLE["handCases"], ids=lambda c: c["name"])
def test_reference_agrees_with_hand_table(case):
    """Guards the table itself: the independent exact reference reproduces it."""
    value, side, _ = ref_adjust(case["team1"], case["team2"])
    assert (value, side) == (case["value"], case["side"])


def test_adjusted_totals_known_answer():
    # 2v1: [5000,4000] vs [8000]: team2 receives +880 -> 9000 vs 8880 (hand).
    small, large, va_s, va_l = pm.adjusted_pair_totals([8000], [5000, 4000], model_id=GEOM)
    assert (small, large, va_s, va_l) == (8880.0, 9000.0, 880.0, 0.0)
    # U gap = U_A - U_B = 8120 - 8000 = 120 = 9000 - 8880.
    assert large - small == pytest.approx(120.0)


@pytest.mark.parametrize(
    "x,expected",
    [(0.5, 1), (1.5, 2), (2.5, 3), (3.5, 4), (880.5, 881), (0.49999, 0), (5.5, 6), (0.0, 0)],
)
def test_js_round_is_half_up_never_bankers(x, expected):
    assert js_round(x) == expected  # Python round(2.5) == 2; Math.round(2.5) == 3


# ── sweeps against the independent reference ──────────────────────────
def test_fixture_random_sweep_matches():
    for c in ORACLE["randomSweep"]:
        assert _prod(c["team1"], c["team2"]) == (c["value"], c["side"]), c


def test_seeded_sweep_matches_exact_reference():
    checked = 0
    for a, b in _sweep(7001, 4000):
        value, side, diff = ref_adjust(a, b)
        got = _prod(a, b)
        if _near_half(diff):
            assert abs(got[0] - value) <= 1  # float noise on an exact half only
            continue
        assert got == (value, side), (a, b)
        checked += 1
    assert checked > 3500


# ── properties ────────────────────────────────────────────────────────
def test_permutation_invariance():
    rng = random.Random(11)
    for a, b in _sweep(7002, 600):
        a2, b2 = a[:], b[:]
        rng.shuffle(a2)
        rng.shuffle(b2)
        assert _prod(a, b) == _prod(a2, b2)


def test_adding_a_positive_piece_never_lowers_that_sides_utility():
    rng = random.Random(12)
    for a, _ in _sweep(7003, 1000):
        extra = rng.randint(1, 9999)
        assert ref_utility(a + [extra]) >= ref_utility(a)  # spec property of U
        assert pm.geom_utility(a + [extra]) >= pm.geom_utility(a) - 1e-9  # owner agrees
        # and strictly higher by at least the discounted floor of the new piece
        assert ref_utility(a + [extra]) - ref_utility(a) > 0


def test_gap_antisymmetry_when_sides_swap():
    for a, b in _sweep(7004, 1500):
        assert _gap(a, b) == -_gap(b, a)
        va, sa, _ = pm.adjust_pair(a, b, model_id=GEOM)
        vb, sb, _ = pm.adjust_pair(b, a, model_id=GEOM)
        assert va == vb and sa == ({0: 0, 1: 2, 2: 1})[sb]


def test_adjusted_gap_equals_utility_gap_up_to_integer_rounding():
    for a, b in _sweep(7005, 2000):
        if not any(v > 0 for v in a) or not any(v > 0 for v in b):
            continue
        u_gap = ref_utility(a) - ref_utility(b)
        assert abs(Fraction(_gap(a, b)) - u_gap) <= Fraction(1, 2) + Fraction(1, 10**6), (a, b)


def test_one_for_one_never_adjusts_and_zeros_never_matter():
    rng = random.Random(13)
    for _ in range(300):
        x, y = rng.randint(1, 9999), rng.randint(1, 9999)
        assert _prod([x], [y]) == (0, 0)
        a, b = [rng.randint(0, 9999) for _ in range(3)], [rng.randint(0, 9999) for _ in range(2)]
        assert _prod(a + [0, 0], b + [0]) == _prod(a, b)


def test_positive_homogeneity_within_rounding():
    # Spec: the model is positively homogeneous (U is linear in the values).
    for a, b in _sweep(7006, 400):
        if not any(v > 0 for v in a) or not any(v > 0 for v in b):
            continue
        _, _, d = ref_adjust(a, b)
        _, _, d2 = ref_adjust([2 * v for v in a], [2 * v for v in b])
        assert d2 == 2 * d
