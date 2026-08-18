"""Angle's package construction is the substrate's, and produces the same sides.

``find_angle_packages`` / ``find_acquisition_packages`` had three hand-rolled
``combinations`` enumerations.  They now delegate to
``src/packages::enumerate_sides``.  This is a MECHANICS refactor, so the proof
that matters is equivalence: the same pool and sizes must yield the same sides
as the retired ``combinations`` loops, in the same order.
"""

from __future__ import annotations

from itertools import combinations

import pytest

from src.trade.angle import _angle_pool_assets, _angle_sides


def _pool(n: int = 8):
    return [
        {"name": f"P{i:02d}", "position": "RB", "my_value": 5000 - i * 100, "row": {"i": i}}
        for i in range(n)
    ]


def _retired(pool, sizes):
    """The enumeration this replaced, verbatim."""
    out = []
    for size in sizes:
        if len(pool) < size:
            continue
        for combo in combinations(pool, size):
            out.append(combo)
    return out


@pytest.mark.parametrize("sizes", [[1], [2], [1, 2], [1, 2, 3], [2, 3]])
def test_produces_exactly_the_sides_the_retired_loops_did(sizes):
    pool = _pool()
    got = list(_angle_sides(_angle_pool_assets(pool), sizes))
    assert got == _retired(pool, sizes)


def test_the_pool_entries_come_back_unchanged():
    """``_make_candidate`` reads the caller's dicts, not a projection."""
    pool = _pool(3)
    (side,) = [s for s in _angle_sides(_angle_pool_assets(pool), [3])]
    assert [x is y for x, y in zip(side, pool)] == [True, True, True]


def test_a_size_larger_than_the_pool_is_skipped():
    pool = _pool(2)
    assert list(_angle_sides(_angle_pool_assets(pool), [5])) == []


def test_seeds_appear_in_every_side_and_count_against_the_size():
    """The seed/filler split, which was its own third enumeration."""
    pool = _pool(5)
    seeds, fillers = pool[:1], pool[1:]
    sides = list(_angle_sides(_angle_pool_assets(fillers), [3], required=_angle_pool_assets(seeds)))
    assert sides, "expected some sides"
    for side in sides:
        assert len(side) == 3
        assert side[0] is seeds[0]
    # One seed + two of four fillers.
    assert len(sides) == len(list(combinations(fillers, 2)))


def test_a_seed_is_never_duplicated_by_also_being_in_the_pool():
    """The retired code removed seeds from the filler pool by name.

    The substrate removes them by identity, which is the same answer here and
    a stronger one when two entries share a name.
    """
    pool = _pool(4)
    sides = list(_angle_sides(_angle_pool_assets(pool), [2], required=_angle_pool_assets(pool[:1])))
    for side in sides:
        assert len({id(x) for x in side}) == 2
        assert [x["name"] for x in side].count(pool[0]["name"]) == 1


def test_angle_keeps_entries_a_generic_eligibility_gate_would_drop():
    """Angle decides eligibility upstream; the substrate must not re-filter.

    A positionless pick row and a zero-value entry both survive, because
    dropping them here would silently change what angle offers.
    """
    pool = [
        {"name": "2027 Early 1st", "position": "", "my_value": 4000, "row": {}},
        {"name": "Zero", "position": "WR", "my_value": 0, "row": {}},
    ]
    sides = list(_angle_sides(_angle_pool_assets(pool), [2]))
    assert len(sides) == 1
    assert {x["name"] for x in sides[0]} == {"2027 Early 1st", "Zero"}


def test_a_missing_value_is_unknown_and_a_measured_zero_is_zero():
    """``float(x or 0.0) or None`` collapsed both to unknown.

    Pool order decides what survives truncation, so "we have no number" and
    "the number is zero" must not become the same thing — and a known zero
    must sort ABOVE an unknown, not beside it.
    """
    absent = {"name": "No Value", "position": "WR", "row": {}}
    zero = {"name": "Measured Zero", "position": "WR", "my_value": 0, "row": {}}
    real = {"name": "Real", "position": "WR", "my_value": 500, "row": {}}
    projected = {a.name: a for a in _angle_pool_assets([absent, zero, real])}
    assert projected["No Value"].value is None
    assert projected["No Value"].value_known is False
    assert projected["Measured Zero"].value == 0.0
    assert projected["Measured Zero"].value_known is True

    from src.packages import by_value_desc

    ordered = sorted(_angle_pool_assets([absent, zero, real]), key=by_value_desc)
    assert [a.name for a in ordered] == ["Real", "Measured Zero", "No Value"]
