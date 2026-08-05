"""The arbitrage score's two terms are on one scale, weighted 5:3.

Audit finding W09-F009 (root cause R7).

`arbitrage = board_gain_norm * 50 + opp_appeal * 30 + …` reads as a
5:3 weighting of "what we gain on our board" against "what the
opponent gains on theirs".  It was not one.  Measured over 480 returned
trades, mean |boardEdge| was 21.81 against mean |ktcAppeal| 4.95 —
80.2% of the ranking signal — because `board_gain_norm` divided by the
GIVE side alone and so was unbounded, while `opp_appeal` is a fraction
gated to be merely positive.  Two multipliers applied to inputs with
different natural ranges do not express a ratio.

The root cause was the unbounded input, not the multipliers, and it is
fixed in `board_gain_norm` (W09-F002).  What this file pins is the
consequence: with both terms expressed as a fraction of a package
total, the weights are the ONLY thing that distinguishes them.
"""

from __future__ import annotations

from src.trade.finder import Asset, _score_trade


def _asset(name: str, model: int, market: int) -> Asset:
    return Asset(
        name=name,
        position="WR",
        team="XX",
        model_value=model,
        market_value=market,
        source_count=6,
    )


def test_equal_fractions_weigh_exactly_fifty_to_thirty():
    """Board gain 20% and opponent appeal 20% must score 10 and 6.

    Constructed so the two INPUTS are equal:
      board_gain_norm = (10000 - 8000) / 10000 = 0.20
      opp_appeal      = (6000  - 5000) /  5000 = 0.20

    Any residual difference in the output is the weighting, and nothing
    else.  Under give-side normalization the board term read
    2000/8000 = 0.25 -> 12.5 against 6.0, a 2.08:1 ratio where the
    constants say 1.67:1.
    """
    tc = _score_trade(
        [_asset("Give", 8000, 6000)],
        [_asset("Get", 10000, 5000)],
    )
    assert tc is not None
    board = tc.ranking_factors["boardEdge"]
    appeal = tc.ranking_factors["ktcAppeal"]
    assert board == 10.0
    assert appeal == 6.0
    assert board / appeal == 50 / 30


def test_neither_term_can_run_away_from_the_other():
    """The board term is bounded; that is what made the ratio real.

    A package built to maximise the old term — tiny give side, large
    receive side — can no longer exceed the weight itself.
    """
    tc = _score_trade(
        [_asset("Tiny", 1000, 4000)],
        [_asset("HugeA", 4000, 1000), _asset("HugeB", 4000, 1000)],
    )
    assert tc is not None
    assert tc.ranking_factors["boardEdge"] <= 50.0
