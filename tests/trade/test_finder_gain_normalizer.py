"""The finder's board gain is normalized against the larger side.

Audit finding W09-F002 (root cause R7).

``board_gain_norm = board_delta / give_model`` divided by the GIVE side
only, so shrinking the give side inflated the dominant ranking term
(``f_board_edge = board_gain_norm * 50``) without bound, against a flat
``-(pkg_size - 2) * 3`` counterweight.  Measured on the live payload,
every one of the 480 trades the engine returned across 12 teams was a
1-for-2; the first 1-for-1 sat at rank 43 of 5,733 qualified candidates
and 2-for-1 never surfaced at all.

A ratio whose denominator is one side of a subtraction is not a rate of
gain — it is a lopsidedness score.  Dividing by the larger side bounds
it at 1.0 ("you gained the entire receive side"), which is what the
0.25 / 0.10 edge labels were always read as meaning.
"""

from __future__ import annotations

from src.trade.finder import Asset, TradeCandidate, _fill_by_shape, _score_trade


def _asset(name: str, model: int, market: int, position: str = "WR") -> Asset:
    return Asset(
        name=name,
        position=position,
        team="XX",
        model_value=model,
        market_value=market,
        source_count=3,
    )


def test_gain_is_a_fraction_of_the_larger_side():
    give = [_asset("Mine", 3000, 3000)]
    receive = [_asset("Theirs", 4000, 2500)]
    tc = _score_trade(give, receive)
    assert tc is not None
    # 1000 / 4000 = 0.25 → 0.25 * 50.  Against the give side it would
    # have been 1000 / 3000 = 0.333 → 16.67.
    assert tc.ranking_factors["boardEdge"] == 12.5


def test_the_gain_ratio_cannot_exceed_one():
    """A one-for-many package used to score an unbounded edge."""
    give = [_asset("Cheap", 1200, 1200)]
    receive = [
        _asset("BigA", 3000, 500),
        _asset("BigB", 3000, 500),
    ]
    tc = _score_trade(give, receive)
    assert tc is not None
    # board_edge = norm * 50, so norm <= 1 means board_edge <= 50.
    # Pre-fix this package scored 4800/1200 = 4.0 → 200.0.
    assert tc.ranking_factors["boardEdge"] <= 50.0


def test_shrinking_the_give_side_no_longer_buys_a_higher_edge():
    """Same receive side, smaller give side, LOWER gain is not rewarded harder.

    Both packages take the same assets off the same board.  The one
    that gives up more should not score a worse board edge than the one
    that gives up less for the same return — under give-side
    normalization it did exactly that, monotonically.
    """
    receive = [_asset("Target", 6000, 3000)]
    thin = _score_trade([_asset("Thin", 2000, 3500)], receive)
    thick = _score_trade([_asset("Thick", 5000, 3500)], receive)
    assert thin is not None and thick is not None
    # Giving less for the same return IS a bigger edge — that ordering
    # is correct and preserved.  What must not survive is the size of
    # the gap: under give-normalization thin scored 100.0 against
    # thick's 10.0, a 10x advantage from a 2.5x difference in what was
    # given up.
    assert thin.ranking_factors["boardEdge"] > thick.ranking_factors["boardEdge"]
    ratio = thin.ranking_factors["boardEdge"] / thick.ranking_factors["boardEdge"]
    assert ratio < 5.0, ratio


def test_the_summary_names_the_basis_of_its_percentage():
    give = [_asset("Mine", 3000, 3000)]
    receive = [_asset("Theirs", 4000, 2500)]
    tc = _score_trade(give, receive)
    assert tc is not None
    assert "larger side" in tc.summary, tc.summary


def _candidate(n_give: int, n_recv: int, score: float) -> TradeCandidate:
    return TradeCandidate(
        give=[_asset(f"g{i}-{score}", 3000, 3000) for i in range(n_give)],
        receive=[_asset(f"r{i}-{score}", 3000, 3000) for i in range(n_recv)],
        give_model_total=3000 * n_give,
        receive_model_total=3000 * n_recv,
        give_ktc_total=3000 * n_give,
        receive_ktc_total=3000 * n_recv,
        board_delta=100,
        ktc_delta=100,
        opponent_ktc_appeal=0.1,
        arbitrage_score=score,
    )


class TestShapeRepresentation:
    """The returned list is not the arg-max over an unbalanced generator.

    ``_generate_1for2`` enumerates my assets × opponent PAIRS, so it
    produces ~30x more candidates than ``_generate_1for1``.  Taking the
    straight top-N of one merged ranking therefore returns one shape
    almost by construction — on the live payload, 480 of 480.
    """

    def test_every_available_shape_reaches_the_returned_list(self):
        ranked = [_candidate(1, 2, 100 - i) for i in range(50)]
        ranked += [_candidate(1, 1, 20 - i * 0.1) for i in range(10)]
        ranked += [_candidate(2, 1, 10 - i * 0.1) for i in range(4)]
        ranked.sort(key=lambda t: -t.arbitrage_score)

        out = _fill_by_shape(ranked, 12)
        shapes = {t.package_shape() for t in out}
        assert shapes == {"1-for-2", "1-for-1", "2-for-1"}

    def test_rank_order_is_preserved_inside_each_shape(self):
        ranked = [_candidate(1, 2, 100 - i) for i in range(20)]
        ranked += [_candidate(1, 1, 50 - i) for i in range(20)]
        ranked.sort(key=lambda t: -t.arbitrage_score)

        out = _fill_by_shape(ranked, 10)
        for shape in ("1-for-2", "1-for-1"):
            got = [t.arbitrage_score for t in out if t.package_shape() == shape]
            assert got == sorted(got, reverse=True)

    def test_a_shape_that_runs_out_does_not_shorten_the_list(self):
        ranked = [_candidate(1, 2, 100 - i) for i in range(20)]
        ranked += [_candidate(1, 1, 5.0)]
        out = _fill_by_shape(ranked, 10)
        assert len(out) == 10

    def test_the_dominant_shape_still_leads(self):
        ranked = [_candidate(1, 2, 100 - i) for i in range(20)]
        ranked += [_candidate(1, 1, 500.0)]
        out = _fill_by_shape(ranked, 6)
        assert out[0].package_shape() == "1-for-2"

    def test_no_candidates_returns_nothing_rather_than_looping(self):
        assert _fill_by_shape([], 10) == []
