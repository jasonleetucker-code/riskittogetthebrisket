"""Seeded randomized property tests for the pure math owners (MD-101, Priority 14).

``hypothesis`` is not a project dependency, so these are seeded ``random``
sweeps: fixed seeds, small example counts, deterministic, offline.  Every
property is checked against an expected result that does not come from the code
under test (a hand computation, a closed form, a brute-force enumeration or a
declared eligibility table written here).

The weighted mean-median blend (equal weights == unweighted rule, monotone in the
values, continuous in the weights, near-zero weight cannot become the median) is
already pinned with an exact ``Fraction`` oracle by
``tests/api/test_blend_median_oracle.py``; it is deliberately not duplicated here.
"""

from __future__ import annotations

import itertools
import random

import pytest

from src.canonical import player_valuation as pv
from src.canonical import tail_policy
from src.ros import lineup as L
from src.valuation_math import package_model as pm

Q = 0.78  # the declared geom_q078_v1 discount; also asserted against the owner below
N_EXAMPLES = 150


def _values(rng: random.Random, lo: int = 1, hi: int = 6) -> list[float]:
    return [round(rng.uniform(1.0, 9999.0), 3) for _ in range(rng.randint(lo, hi))]


# ── package model ────────────────────────────────────────────────────────────


def _oracle_utility(values: list[float]) -> float:
    """sum q**i * v_i over the descending order, using ``**`` (the owner iterates)."""
    return sum(v * Q**i for i, v in enumerate(sorted(values, reverse=True)))


def test_package_q_is_the_declared_constant():
    assert pm.PACKAGE_MODELS[pm.GEOM_Q078_V1]["q"] == Q


def test_utility_hand_computed_cases():
    assert pm.geom_utility([]) == 0.0
    assert pm.geom_utility([100.0]) == 100.0
    # 100 + 0.78*50
    assert pm.geom_utility([50.0, 100.0]) == pytest.approx(139.0)
    # 100 + 0.78*60 + 0.78**2*10 = 100 + 46.8 + 6.084
    assert pm.geom_utility([10.0, 100.0, 60.0]) == pytest.approx(152.884)
    # non-positive entries are not assets
    assert pm.geom_utility([100.0, 0.0, -5.0]) == 100.0


def test_adjust_pair_hand_computed_case():
    # side 1 sends one 100; side 2 sends 60+50.  Depth discarded: side 1 = 100-100 = 0,
    # side 2 = 110 - (60 + 0.78*50) = 11, so side 1 (less depth discarded) is credited 11.
    assert pm.adjust_pair([100.0], [60.0, 50.0], model_id=pm.GEOM_Q078_V1) == (11, 1, True)
    # mirrored sides credit side 2
    assert pm.adjust_pair([60.0, 50.0], [100.0], model_id=pm.GEOM_Q078_V1) == (11, 2, True)
    # two equal singletons discard no depth: nothing to show
    assert pm.adjust_pair([70.0], [70.0], model_id=pm.GEOM_Q078_V1) == (0, 0, False)


def test_utility_matches_independent_formula_permutation_invariant():
    rng = random.Random(20261108)
    for _ in range(N_EXAMPLES):
        vals = _values(rng, 0, 8)
        expect = _oracle_utility(vals)
        shuffled = list(vals)
        rng.shuffle(shuffled)
        assert pm.geom_utility(vals) == pytest.approx(expect, rel=1e-12)
        assert pm.geom_utility(shuffled) == pytest.approx(expect, rel=1e-12)


def test_utility_is_monotone_in_each_asset_value():
    rng = random.Random(7)
    for _ in range(N_EXAMPLES):
        vals = _values(rng, 1, 7)
        base = pm.geom_utility(vals)
        i = rng.randrange(len(vals))
        raised = list(vals)
        raised[i] += rng.uniform(0.001, 3000.0)  # may reorder the package
        assert pm.geom_utility(raised) >= base - 1e-9


def test_adding_a_positive_asset_never_lowers_utility():
    rng = random.Random(11)
    for _ in range(N_EXAMPLES):
        vals = _values(rng, 0, 7)
        extra = rng.uniform(0.001, 9999.0)
        assert pm.geom_utility([*vals, extra]) >= pm.geom_utility(vals) - 1e-9


def test_adjusted_totals_are_raw_plus_nonnegative_va_and_side_symmetric():
    rng = random.Random(13)
    for _ in range(N_EXAMPLES):
        a, b = _values(rng, 1, 5), _values(rng, 1, 5)
        sa, sb, va_a, va_b = pm.adjusted_pair_totals(a, b, model_id=pm.GEOM_Q078_V1)
        assert sa == pytest.approx(sum(a) + va_a) and sb == pytest.approx(sum(b) + va_b)
        assert va_a >= 0 and va_b >= 0 and (va_a == 0 or va_b == 0)
        # swapping the sides swaps the answer
        sb2, sa2, vb2, va2 = pm.adjusted_pair_totals(b, a, model_id=pm.GEOM_Q078_V1)
        assert (sa, sb, va_a, va_b) == pytest.approx((sa2, sb2, va2, vb2))


# ── rank -> percentile -> value ──────────────────────────────────────────────

N_REF = pv.PERCENTILE_REFERENCE_N
SAT = tail_policy.TAIL_SATURATION_RANK  # documented: 904


def test_rank_to_percentile_hand_computed_points():
    assert pv.rank_to_percentile(1) == 0.0
    assert pv.rank_to_percentile(250.5) == pytest.approx(0.5)  # (250.5 - 1) / 499
    assert pv.rank_to_percentile(500) == pytest.approx(
        1.0
    )  # 499 / 499: 500 is the unit, not the tail
    assert pv.rank_to_percentile(501) > 1.0  # ranks past 500 keep resolving


def test_rank_to_percentile_monotone_and_saturates_at_documented_rank():
    assert SAT == 904
    rng = random.Random(3)
    ranks = sorted(rng.uniform(1.0, 1500.0) for _ in range(N_EXAMPLES))
    ps = [pv.rank_to_percentile(r) for r in ranks]
    assert all(b >= a for a, b in zip(ps, ps[1:]))
    cap = (SAT - 1) / (N_REF - 1)
    assert all(0.0 <= p <= cap + 1e-12 for p in ps)
    assert pv.rank_to_percentile(SAT) == pytest.approx(cap)
    # strictly increasing right up to saturation, then flat
    assert pv.rank_to_percentile(SAT - 1) < pv.rank_to_percentile(SAT)
    assert (
        pv.rank_to_percentile(SAT) == pv.rank_to_percentile(SAT + 1) == pv.rank_to_percentile(5000)
    )


def test_percentile_to_value_bounded_monotone_and_anchored():
    assert pv.percentile_to_value(0.0) == 9999
    rng = random.Random(5)
    ps = sorted(rng.uniform(0.0, 2.5) for _ in range(N_EXAMPLES))
    for c, s in (
        (pv.HILL_PERCENTILE_C, pv.HILL_PERCENTILE_S),
        (pv.IDP_HILL_PERCENTILE_C, pv.IDP_HILL_PERCENTILE_S),
    ):
        vals = [pv.percentile_to_value(p, midpoint=c, slope=s) for p in ps]
        assert all(1 <= v <= 9999 for v in vals)
        assert all(b <= a for a, b in zip(vals, vals[1:]))  # non-increasing
        # closed form at the midpoint: V(c) = 9999 / 2
        assert abs(pv.percentile_to_value(c, midpoint=c, slope=s) - 9999 / 2) <= 1
        # closed form at 2c (inside the tail cap): 9999 / (1 + 2**s)
        assert abs(pv.percentile_to_value(2 * c, midpoint=c, slope=s) - 9999 / (1 + 2**s)) <= 1


def test_rank_through_value_is_monotone_and_shares_one_tail_value():
    vals = [pv.percentile_to_value(pv.rank_to_percentile(r)) for r in range(1, 1200)]
    assert vals[0] == 9999
    assert all(b <= a for a, b in zip(vals, vals[1:]))
    assert all(1 <= v <= 9999 for v in vals)
    # every rank at or past saturation prices identically; ranks just before it do not
    assert len({vals[r - 1] for r in range(SAT, 1200)}) == 1
    assert vals[SAT - 2] >= vals[SAT - 1]


# ── lineup assignment ────────────────────────────────────────────────────────

# Declared here from the league-rules vocabulary (independent of the owner's tables).
ELIGIBLE = {
    "QB": {"QB"},
    "RB": {"RB"},
    "WR": {"WR"},
    "TE": {"TE"},
    "FLEX": {"RB", "WR", "TE"},
    "SUPER_FLEX": {"QB", "RB", "WR", "TE"},
}
SLOT_SETS = [
    ["QB", "RB", "RB", "WR", "WR", "TE", "FLEX", "SUPER_FLEX"],
    ["QB", "RB", "WR", "TE", "FLEX", "FLEX"],
    ["SUPER_FLEX", "SUPER_FLEX", "RB", "WR"],
    ["QB", "WR", "WR", "FLEX"],
]


def _roster(rng: random.Random, n: int) -> list[L.RosterPlayer]:
    return [
        L.RosterPlayer(
            player_id=f"p{i}",
            canonical_name=f"Player {i}",
            position=rng.choice(["QB", "RB", "WR", "TE"]),
            ros_value=float(rng.randint(0, 400)),
        )
        for i in range(n)
    ]


def _greedy_total(pool, slots) -> float:
    """Slot-order greedy: each slot takes the best still-free eligible player."""
    used: set[str] = set()
    total = 0.0
    for slot in slots:
        cands = [p for p in pool if p.player_id not in used and p.position in ELIGIBLE[slot]]
        if cands:
            best = max(cands, key=lambda p: p.ros_value)
            used.add(best.player_id)
            total += best.ros_value
    return total


def _brute_total(pool, slots) -> float:
    """Exhaustive maximum over every injective slot->player-or-empty choice."""
    best = 0.0
    options = [[None] + [p for p in pool if p.position in ELIGIBLE[s]] for s in slots]
    for combo in itertools.product(*options):
        chosen = [p.player_id for p in combo if p is not None]
        if len(chosen) == len(set(chosen)):
            best = max(best, sum(p.ros_value for p in combo if p is not None))
    return best


def test_lineup_never_assigns_ineligible_or_duplicate_and_beats_greedy():
    rng = random.Random(41)
    for _ in range(80):
        slots = rng.choice(SLOT_SETS)
        pool = _roster(rng, rng.randint(3, 16))
        got = L.solve_optimal_assignment(pool, slots)
        ids = [p.player_id for p in got.values()]
        assert len(ids) == len(set(ids)), "a player filled two slots"
        for idx, player in got.items():
            assert 0 <= idx < len(slots)
            assert player.position in ELIGIBLE[slots[idx]], (slots[idx], player.position)
            # and the owner's own predicate agrees
            assert L.player_eligible_for_slot(slots[idx], player)
        total = sum(p.ros_value for p in got.values())
        assert total >= _greedy_total(pool, slots) - 1e-9


def test_lineup_total_equals_brute_force_optimum_on_small_rosters():
    rng = random.Random(43)
    for _ in range(40):
        slots = rng.choice(SLOT_SETS)[:5]
        pool = _roster(rng, rng.randint(2, 6))
        got = L.solve_optimal_assignment(pool, slots)
        assert sum(p.ros_value for p in got.values()) == pytest.approx(_brute_total(pool, slots))


def test_lineup_greedy_is_strictly_beaten_by_the_documented_flex_case():
    # Slot order [FLEX, RB]: greedy gives FLEX the best RB (300) and RB the 100 RB = 400;
    # the optimum puts the WR (250) in FLEX and the 300 RB at RB = 550.
    pool = [
        L.RosterPlayer("a", "A", "RB", 300.0),
        L.RosterPlayer("b", "B", "RB", 100.0),
        L.RosterPlayer("c", "C", "WR", 250.0),
    ]
    got = L.solve_optimal_assignment(pool, ["FLEX", "RB"])
    assert sum(p.ros_value for p in got.values()) == 550.0
    assert _greedy_total(pool, ["FLEX", "RB"]) == 400.0
