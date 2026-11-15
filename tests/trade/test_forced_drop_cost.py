"""Wave B (B2) — forced-drop opportunity cost as a named ranking component.

``roster_capacity.forced_drop_cost`` is what the releases a trade FORCES are
known to cost (``ForcedDrop.release_cost`` — base x scarcity, the rule Perfect
Draft and Analyze Trade read).  The finder charges it on the board-edge scale
and reranks lazily; these tests pin the arithmetic, the missing-is-never-zero
states and that the lazy top-K equals brute force.
"""

from __future__ import annotations

import random

from src.trade.finder import (
    _BOARD_EDGE_WEIGHT,
    _FORCED_DROP_RERANK_WINDOW_MULT,
    Asset,
    TradeCandidate,
    _forced_drop_factor,
    _rerank_with_forced_drop_cost,
)
from src.trade.roster_capacity import ForcedDrop, RosterCapacity, forced_drop_cost


def _drop(name: str, release: float, value: float | None = 1000.0) -> ForcedDrop:
    return ForcedDrop(
        player_id=name,
        name=name,
        position="WR",
        value=value,
        effective_cut_cost=0.0,
        value_basis="board",
        rung=1,
        release_cost=release,
    )


def _capacity(**kw) -> RosterCapacity:
    base = dict(
        roster_limit=58,
        taxi_size=0,
        size_before=58,
        size_after=59,
        incoming=2,
        outgoing=1,
        open_spots_before=0,
        open_spots_after=-1,
        over_limit_before=0,
        over_limit_after=1,
    )
    base.update(kw)
    return RosterCapacity(**base)


def test_unknown_cap_is_unknown_not_free():
    cost, basis = forced_drop_cost(_capacity(roster_limit=None, over_limit_after=None))
    assert cost is None and basis["state"] == "unknown"


def test_proven_legal_roster_costs_zero():
    cost, basis = forced_drop_cost(_capacity(over_limit_after=0, size_after=58))
    assert cost == 0.0 and basis["state"] == "none"


def test_exact_cost_is_the_sum_of_the_added_releases():
    cost, basis = forced_drop_cost(
        _capacity(
            size_after=60,
            incoming=3,
            over_limit_after=2,
            forced_drops=[_drop("a", 700), _drop("b", 300)],
        )
    )
    assert cost == 1000.0 and basis["state"] == "exact"


def test_an_existing_overage_is_not_charged_to_the_trade():
    # 60/58 before, 1-for-1: the roster owes two releases whether or not it
    # trades, so the trade adds none.
    cap = _capacity(
        size_before=60,
        size_after=60,
        incoming=1,
        over_limit_before=2,
        over_limit_after=2,
        forced_drops=[_drop("a", 700), _drop("b", 300)],
    )
    assert forced_drop_cost(cap)[0] == 0.0


def test_growth_into_an_existing_overage_charges_only_the_added_rung():
    drops = [
        ForcedDrop(**{**_drop(f"r{i}", c).__dict__, "rung": i})
        for i, c in enumerate([100, 200, 900], start=1)
    ]
    cap = _capacity(
        size_before=60,
        size_after=61,
        over_limit_before=2,
        over_limit_after=3,
        forced_drops=drops,
    )
    # Rungs 1-2 were owed already; the trade adds rung 3.
    assert forced_drop_cost(cap)[0] == 900.0


def test_unknown_taxi_charges_only_the_guaranteed_drops():
    cap = _capacity(
        certainty="partial",
        over_limit_after=None,
        over_limit_after_min=1,
        over_limit_after_max=3,
        forced_drops=[_drop("a", 900), _drop("b", 200), _drop("c", 500)],
    )
    cost, basis = forced_drop_cost(cap)
    assert cost == 200.0  # the cheapest one guaranteed release
    assert basis["state"] == "lower_bound"


def test_straddling_taxi_range_is_unknown():
    cap = _capacity(
        certainty="partial",
        over_limit_after=None,
        over_limit_after_min=0,
        over_limit_after_max=2,
        forced_drops=[_drop("a", 900)],
    )
    assert forced_drop_cost(cap)[0] is None


def test_unpriced_drop_is_excluded_and_marked_lower_bound():
    cost, basis = forced_drop_cost(
        _capacity(
            size_after=60,
            over_limit_after=2,
            forced_drops=[_drop("a", 400), _drop("x", 999, value=None)],
        )
    )
    assert cost == 400.0
    assert "unpriced_forced_drops_excluded" in basis["lowerBoundReasons"]


def _tc(score: float, give_total: int = 5000, full: bool = True) -> TradeCandidate:
    a = Asset(name=f"g{score}", position="WR", team="", model_value=give_total, market_value=1)
    return TradeCandidate(
        give=[a],
        receive=[a],
        give_model_total=give_total,
        arbitrage_score=score,
        ktc_coverage="full" if full else "partial",
        ranking_factors={},
        flags=[],
    )


def test_factor_is_the_board_edge_formula():
    tc = _tc(20.0, give_total=4000)
    factor = _forced_drop_factor(tc, _capacity(forced_drops=[_drop("a", 800)]))
    assert factor == -(800 / 4000) * _BOARD_EDGE_WEIGHT
    assert tc.arbitrage_score == 20.0 + factor
    assert "forced_drop_cost" in tc.flags


def test_unknown_cost_moves_nothing():
    tc = _tc(20.0)
    assert _forced_drop_factor(tc, None) == 0.0
    assert tc.arbitrage_score == 20.0
    assert tc.ranking_factors["forcedDropCost"] is None


def test_lazy_rerank_equals_brute_force():
    rng = random.Random(7)
    for _trial in range(200):
        n, k = rng.randint(1, 40), rng.randint(1, 10)
        specs = [
            (rng.uniform(0, 60), rng.random() < 0.8, rng.choice([0, 0, 300, 2500]))
            for _ in range(n)
        ]

        def build():
            tcs = [_tc(s, full=f) for s, f, _c in specs]
            caps = {
                id(t): _capacity(
                    over_limit_after=1 if c else 0,
                    forced_drops=[_drop("d", c)] if c else [],
                )
                for t, (_s, _f, c) in zip(tcs, specs)
            }
            tcs.sort(key=lambda t: (t.ktc_coverage == "full", t.arbitrage_score), reverse=True)
            return tcs, caps

        lazy_tcs, lazy_caps = build()
        lazy = _rerank_with_forced_drop_cost(lazy_tcs, k, lambda t: lazy_caps[id(t)])
        brute_tcs, brute_caps = build()
        for t in brute_tcs[: k * _FORCED_DROP_RERANK_WINDOW_MULT]:
            _forced_drop_factor(t, brute_caps[id(t)])
        window = brute_tcs[: k * _FORCED_DROP_RERANK_WINDOW_MULT]
        brute = sorted(
            window, key=lambda t: (t.ktc_coverage == "full", t.arbitrage_score), reverse=True
        )[:k]
        assert [round(t.arbitrage_score, 9) for t in lazy] == [
            round(t.arbitrage_score, 9) for t in brute
        ]


def test_added_releases_are_chosen_by_release_cost_not_rung():
    # Independent-review repro: on a full roster every ECC ties, so rungs are
    # alphabetical.  The trade adds one release onto a 2-release overage; the
    # added one is the most EXPENSIVE of the three (Amy, 900), not rung 3.
    drops = [
        ForcedDrop(**{**_drop("Amy", 900).__dict__, "rung": 1}),
        ForcedDrop(**{**_drop("Bob", 500).__dict__, "rung": 2}),
        ForcedDrop(**{**_drop("Zed", 100).__dict__, "rung": 3}),
    ]
    cap = _capacity(
        size_before=60,
        size_after=61,
        over_limit_before=2,
        over_limit_after=3,
        forced_drops=drops,
    )
    cost, basis = forced_drop_cost(cap)
    assert cost == 900.0 and basis["state"] == "exact"


def test_an_exhausted_ladder_keeps_every_modelled_release():
    cap = _capacity(
        size_after=61,
        over_limit_after=3,
        ladder_exhausted=True,
        forced_drops=[_drop("a", 400), _drop("b", 600)],
    )
    cost, basis = forced_drop_cost(cap)
    assert cost == 1000.0
    assert basis["state"] == "lower_bound"
    assert "fewer_drops_modelled_than_added" in basis["lowerBoundReasons"]
