"""Independent oracle for the count-aware (weighted) blend median.

Reference implementation written below from the SPEC only (CLAUDE.md "Live
Value Pipeline" steps 4b and 7):

* n=1 passthrough; n=2 mean; n=3-4 untrimmed mean-median; n>=5 trimmed
  mean-median (drop one max + one min);
* weighted form: one unit throughout — one average observation's mass W/n.
  The n>=5 trim removes that much weight from each end (the MEAN only); the
  weighted median is the mean of the weighted quantile function over
  ``[1/2 - 1/(2n), 1/2 + 1/(2n)]``; exactly the unweighted rule under equal
  weights; monotone in the values; continuous in the weights; a near-zero-weight
  source cannot become the median.

All reference arithmetic is exact (``Fraction``).  QA directive 2026-11-06
(CW-49 Phase 2).  Offline and deterministic.
"""

from __future__ import annotations

import random
from fractions import Fraction

import pytest

from src.api.data_contract import (
    count_aware_mean_median_blend,
    weighted_count_aware_mean_median_blend,
)

F = Fraction


# ── reference implementation, from the spec only ──────────────────────
def ref_unweighted(values):
    v = sorted(F(x) for x in values)
    n = len(v)
    if n == 1:
        return v[0]
    if n == 2:
        return (v[0] + v[1]) / 2
    used = v[1:-1] if n >= 5 else v
    mean = sum(used) / len(used)
    m = len(used)
    med = used[m // 2] if m % 2 else (used[m // 2 - 1] + used[m // 2]) / 2
    return (mean + med) / 2


def _quantile_mean(pairs, lo, hi):
    """Mean of the weighted quantile function over [lo, hi]; pairs value-sorted."""
    total = sum(w for _, w in pairs)
    acc, cum = F(0), F(0)
    for value, weight in pairs:
        a, b = cum / total, (cum + weight) / total
        overlap = min(b, hi) - max(a, lo)
        if overlap > 0:
            acc += value * overlap
        cum += weight
    return acc / (hi - lo)


def ref_weighted(values, weights):
    pairs = sorted((F(v), F(w)) for v, w in zip(values, weights))
    n = len(pairs)
    total = sum(w for _, w in pairs)
    if n == 1:
        return pairs[0][0]
    if n == 2:
        return sum(v * w for v, w in pairs) / total
    used = [[v, w] for v, w in pairs]
    if n >= 5:
        mass = total / n
        for order in (range(n), range(n - 1, -1, -1)):
            remaining = mass
            for i in order:
                take = min(used[i][1], remaining)
                used[i][1] -= take
                remaining -= take
    used_w = sum(w for _, w in used)
    wmean = sum(v * w for v, w in used) / used_w
    wmed = _quantile_mean(pairs, F(1, 2) - F(1, 2 * n), F(1, 2) + F(1, 2 * n))
    return (wmean + wmed) / 2


def _close(got, want, tol=1e-9):
    return abs(got - float(want)) <= tol * max(1.0, abs(float(want)))


def _panel(rng, n, equal=False):
    values = [rng.randint(100, 9999) + rng.random() for _ in range(n)]
    weights = [1.0] * n if equal else [rng.uniform(0.05, 1.0) for _ in range(n)]
    return values, weights


# ── hand-computed anchors ─────────────────────────────────────────────
def test_hand_computed_known_answers():
    # n=1 passthrough
    assert count_aware_mean_median_blend([4321.0])[0] == 4321.0
    # n=2 mean: (1000+3000)/2 = 2000
    assert count_aware_mean_median_blend([1000.0, 3000.0])[0] == 2000.0
    # n=3 equal: mean 2000, median 2000 -> 2000 ; skewed [1000,2000,6000]:
    # mean 3000, median 2000 -> 2500
    assert count_aware_mean_median_blend([1000.0, 2000.0, 6000.0])[0] == 2500.0
    # n=4 [1000,2000,3000,10000]: mean 4000, median 2500 -> 3250
    assert count_aware_mean_median_blend([1000.0, 2000.0, 3000.0, 10000.0])[0] == 3250.0
    # n=5 [1,2,3,4,100]: drop 1 and 100 -> [2,3,4] mean 3 median 3 -> 3
    assert count_aware_mean_median_blend([1.0, 2.0, 3.0, 4.0, 100.0])[0] == 3.0
    # n=6 [1,2,3,4,5,60]: used [2,3,4,5] mean 3.5 median 3.5 -> 3.5 ;
    # skewed [1,2,3,4,20,60]: used [2,3,4,20] mean 7.25 median 3.5 -> 5.375
    assert count_aware_mean_median_blend([1.0, 2.0, 3.0, 4.0, 20.0, 60.0])[0] == 5.375
    # weighted n=2: (1000*1 + 3000*3)/4 = 2500
    assert weighted_count_aware_mean_median_blend([1000.0, 3000.0], [1.0, 3.0])[0] == 2500.0
    # weighted n=3 [0,10,20] w [1,1,2]: wmean=(0+10+40)/4=12.5;
    # window [1/3,2/3]; slices [0,.25],[.25,.5],[.5,1] -> mean Q over window =
    # (10*(.5-1/3)+20*(2/3-.5))/(1/3) = (10*(1/6)+20*(1/6))*3 = 15 ; -> (12.5+15)/2
    got = weighted_count_aware_mean_median_blend([0.0, 10.0, 20.0], [1.0, 1.0, 2.0])[0]
    assert got == pytest.approx(13.75, abs=1e-12)


# ── differential vs the independent reference ────────────────────────
@pytest.mark.parametrize("n", range(1, 10))
def test_weighted_matches_reference_seeded_sweep(n):
    rng = random.Random(9000 + n)
    for _ in range(300):
        values, weights = _panel(rng, n)
        got, _ = weighted_count_aware_mean_median_blend(values, weights)
        want = ref_weighted(values, weights)
        assert _close(got, want), (values, weights, got, float(want))


@pytest.mark.parametrize("n", range(1, 10))
def test_unweighted_matches_reference_seeded_sweep(n):
    rng = random.Random(9100 + n)
    for _ in range(300):
        values, _w = _panel(rng, n, equal=True)
        got, _ = count_aware_mean_median_blend(values)
        assert _close(got, ref_unweighted(values)), (values, got)


@pytest.mark.parametrize("n", range(1, 10))
def test_equal_weights_are_exactly_the_ordinary_rule(n):
    """Spec: exactly the unweighted rule under equal weights — checked three ways."""
    rng = random.Random(9200 + n)
    for _ in range(200):
        values, _w = _panel(rng, n, equal=True)
        ordinary = count_aware_mean_median_blend(values)[0]
        assert weighted_count_aware_mean_median_blend(values, [1.0] * n)[0] == ordinary
        assert weighted_count_aware_mean_median_blend(values, [0.37] * n)[0] == ordinary
        # the spec's weighted reading with equal weights IS the ordinary rule
        assert ref_weighted(values, [1] * n) == ref_unweighted(values)
        # and the genuinely weighted code path, with weights split by 1e-6, agrees
        nudged = [1.0 + (1e-6 if i == 0 else 0.0) for i in range(n)]
        assert _close(weighted_count_aware_mean_median_blend(values, nudged)[0], ordinary, 1e-5)


# ── properties ────────────────────────────────────────────────────────
@pytest.mark.parametrize("n", range(1, 10))
def test_permutation_invariance(n):
    rng = random.Random(9300 + n)
    for _ in range(150):
        values, weights = _panel(rng, n)
        idx = list(range(n))
        rng.shuffle(idx)
        a = weighted_count_aware_mean_median_blend(values, weights)[0]
        b = weighted_count_aware_mean_median_blend(
            [values[i] for i in idx], [weights[i] for i in idx]
        )[0]
        assert _close(a, b, 1e-12)


@pytest.mark.parametrize("n", range(1, 10))
def test_monotone_in_values(n):
    rng = random.Random(9400 + n)
    for _ in range(300):
        values, weights = _panel(rng, n)
        base = weighted_count_aware_mean_median_blend(values, weights)[0]
        i = rng.randrange(n)
        raised = list(values)
        raised[i] += rng.uniform(0.0, 3000.0)
        assert weighted_count_aware_mean_median_blend(raised, weights)[0] >= base - 1e-9


@pytest.mark.parametrize("n", range(1, 10))
def test_monotone_in_values_equal_weights(n):
    rng = random.Random(9450 + n)
    for _ in range(200):
        values, _w = _panel(rng, n, equal=True)
        base = count_aware_mean_median_blend(values)[0]
        raised = list(values)
        raised[rng.randrange(n)] += rng.uniform(0.0, 3000.0)
        assert count_aware_mean_median_blend(raised)[0] >= base - 1e-9


@pytest.mark.parametrize("n", range(2, 10))
def test_continuous_in_weights(n):
    rng = random.Random(9500 + n)
    for _ in range(200):
        values, weights = _panel(rng, n)
        spread = max(values) - min(values)
        base = weighted_count_aware_mean_median_blend(values, weights)[0]
        w2 = list(weights)
        w2[rng.randrange(n)] += 1e-7
        moved = weighted_count_aware_mean_median_blend(values, w2)[0]
        assert abs(moved - base) <= 1e-4 * spread + 1e-9, (values, weights)


@pytest.mark.parametrize("n", range(3, 9))
def test_bounded_influence_of_near_zero_weight_source(n):
    """A source with weight -> 0 cannot become the result (or drag it far)."""
    rng = random.Random(9600 + n)
    for _ in range(200):
        values, weights = _panel(rng, n)
        spread = max(values) - min(values)
        base = weighted_count_aware_mean_median_blend(values, weights)[0]
        for outlier in (max(values) + 10 * spread, min(values) - 10 * spread):
            got = weighted_count_aware_mean_median_blend(values + [outlier], weights + [1e-6])[0]
            assert min(values) <= got <= max(values), (values, weights, outlier, got)
            assert abs(got - base) <= 0.1 * spread + 1e-6, (values, weights, outlier, got, base)


def test_result_stays_inside_the_value_hull():
    rng = random.Random(9700)
    for n in range(1, 10):
        for _ in range(200):
            values, weights = _panel(rng, n)
            got = weighted_count_aware_mean_median_blend(values, weights)[0]
            assert min(values) - 1e-9 <= got <= max(values) + 1e-9


def test_n1_passthrough_and_n2_mean_weighted():
    rng = random.Random(9800)
    for _ in range(100):
        v = rng.uniform(1, 9999)
        assert weighted_count_aware_mean_median_blend([v], [rng.uniform(0.1, 2)])[0] == v
        a, b = rng.uniform(1, 9999), rng.uniform(1, 9999)
        wa, wb = rng.uniform(0.1, 2), rng.uniform(0.1, 2)
        got = weighted_count_aware_mean_median_blend([a, b], [wa, wb])[0]
        assert got == pytest.approx((a * wa + b * wb) / (wa + wb), rel=1e-12)
