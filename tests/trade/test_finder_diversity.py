"""40 trade ideas, not 40 variations of four.

Audit finding W09-F012 (root cause R7).

``_deduplicate`` collapses exact repeats — the same asset set enumerated
in a different order — and nothing else.  Nothing pruned dominated
packages (same give side, a receive side another package strictly
contains, worse score) and nothing bounded how often one asset could
own the list.  Measured on the live payload, the 40 trades returned for
one team drew their give side from 4 distinct players, one of them
appearing in 20 of the 40.
"""

from __future__ import annotations

from src.trade.finder import (
    MAX_GIVE_ASSET_APPEARANCES,
    Asset,
    TradeCandidate,
    _fill_by_shape,
    _prune_dominated,
)


def _asset(name: str) -> Asset:
    return Asset(name=name, position="WR", team="XX", model_value=3000, market_value=3000)


def _tc(give: list[str], receive: list[str], score: float) -> TradeCandidate:
    return TradeCandidate(
        give=[_asset(n) for n in give],
        receive=[_asset(n) for n in receive],
        give_model_total=3000 * len(give),
        receive_model_total=3000 * len(receive),
        give_ktc_total=3000 * len(give),
        receive_ktc_total=3000 * len(receive),
        board_delta=100,
        ktc_delta=100,
        opponent_ktc_appeal=0.1,
        arbitrage_score=score,
    )


class TestDominancePruning:
    def test_a_strictly_worse_package_is_dropped(self):
        better = _tc(["A"], ["X", "Y"], 40.0)
        worse = _tc(["A"], ["X"], 20.0)
        kept = _prune_dominated([better, worse])
        assert kept == [better]

    def test_a_smaller_return_that_scores_BETTER_survives(self):
        """Dominance is about the engine's own verdict, not package size."""
        small = _tc(["A"], ["X"], 60.0)
        big = _tc(["A"], ["X", "Y"], 20.0)
        kept = _prune_dominated([small, big])
        assert len(kept) == 2
        assert kept[0] is small and kept[1] is big

    def test_disjoint_receive_sides_are_both_real_options(self):
        one = _tc(["A"], ["X"], 40.0)
        two = _tc(["A"], ["Y"], 20.0)
        assert len(_prune_dominated([one, two])) == 2

    def test_a_different_give_side_is_never_dominated(self):
        one = _tc(["A"], ["X", "Y"], 40.0)
        two = _tc(["B"], ["X"], 20.0)
        assert len(_prune_dominated([one, two])) == 2

    def test_nothing_to_compare_is_a_no_op(self):
        assert _prune_dominated([]) == []


class TestGiveAssetCap:
    def test_one_asset_cannot_own_the_list(self):
        """Its 20 top-scoring packages take 3 slots, not all 10."""
        ranked = [_tc(["Hoarded"], [f"R{i}"], 100 - i) for i in range(20)]
        ranked += [_tc([f"Other{i}"], [f"Z{i}"], 50 - i) for i in range(20)]
        ranked.sort(key=lambda t: -t.arbitrage_score)
        out = _fill_by_shape(ranked, 10, max_give_appearances=3)
        appearances = sum(1 for t in out if t.give[0].name == "Hoarded")
        assert appearances == 3
        assert len(out) == 10

    def test_the_cap_is_soft_rather_than_a_short_list(self):
        """A real trade is never withheld to satisfy a diversity rule."""
        ranked = [_tc(["Hoarded"], [f"R{i}"], 100 - i) for i in range(20)]
        out = _fill_by_shape(ranked, 10, max_give_appearances=3)
        assert len(out) == 10
        # The three under the cap lead; the rest follow in rank order.
        assert [t.receive[0].name for t in out[:3]] == ["R0", "R1", "R2"]
        assert [t.receive[0].name for t in out[3:]] == [f"R{i}" for i in range(3, 10)]

    def test_diverse_candidates_are_preferred_over_a_repeat(self):
        ranked = [_tc(["Hoarded"], [f"R{i}"], 100 - i) for i in range(20)]
        ranked += [_tc(["Other"], ["Z"], 1.0)]
        out = _fill_by_shape(ranked, 5, max_give_appearances=3)
        assert "Other" in {a.name for t in out for a in t.give}

    def test_a_cap_of_zero_disables_it(self):
        ranked = [_tc(["Hoarded"], [f"R{i}"], 100 - i) for i in range(5)]
        out = _fill_by_shape(ranked, 5, max_give_appearances=0)
        assert len(out) == 5

    def test_the_default_cap_is_the_documented_one(self):
        assert MAX_GIVE_ASSET_APPEARANCES == 3
