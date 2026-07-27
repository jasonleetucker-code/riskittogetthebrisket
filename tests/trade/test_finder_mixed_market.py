"""T4-2: a trade whose delta spans two retail markets must say so.

`ktcDelta` sums `ktcValue` across every asset in a trade. The per-market
gate prices offense and picks on KTC but IDP on IDPTradeCalc, so a mixed
trade's delta adds two publishers' numbers together — and nothing in the
payload disclosed that.

The sum itself is defensible. CLAUDE.md records the two boards as
directly comparable: both top out at 9999 and their median cross-board
value ratio is 1.000 over the 475 players they share. But the p10-p90 is
0.888-1.054, so +/-10% per-player disagreement is normal, and a
mixed-market delta smaller than that is not distinguishable from the two
boards simply disagreeing with each other.

That caveat is unusable unless the reader knows it applies, which is
what these pin.
"""

from __future__ import annotations

from src.trade.finder import Asset, TradeCandidate


def _asset(name: str, position: str, market_source: str | None) -> Asset:
    """``has_market`` is a derived property, so an unpriced asset is one
    with ``market_value=None`` — not a flag set alongside a value."""
    return Asset(
        name=name,
        position=position,
        team="TST",
        model_value=5000,
        market_value=5000 if market_source else None,
        market_rank=10 if market_source else None,
        market_source=market_source,
    )


def test_an_offense_only_trade_is_not_flagged_mixed():
    trade = TradeCandidate(
        give=[_asset("WR A", "WR", "ktcSfTep")],
        receive=[_asset("RB B", "RB", "ktcSfTep")],
    )
    d = trade.to_dict()
    assert d["marketsUsed"] == ["ktc"]
    assert d["mixedMarket"] is False


def test_an_idp_only_trade_is_not_flagged_mixed():
    trade = TradeCandidate(
        give=[_asset("LB A", "LB", "idpTradeCalc")],
        receive=[_asset("DL B", "DL", "idpTradeCalc")],
    )
    d = trade.to_dict()
    assert d["marketsUsed"] == ["idpTradeCalc"]
    assert d["mixedMarket"] is False


def test_a_trade_spanning_both_markets_is_flagged():
    """The case the disclosure exists for: the delta on this trade is
    KTC minus IDPTradeCalc."""
    trade = TradeCandidate(
        give=[_asset("WR A", "WR", "ktcSfTep")],
        receive=[_asset("LB B", "LB", "idpTradeCalc")],
    )
    d = trade.to_dict()
    assert d["marketsUsed"] == ["idpTradeCalc", "ktc"]
    assert d["mixedMarket"] is True


def test_the_legacy_ktc_key_is_the_same_market_not_a_third_one():
    """`ktc` and `ktcSfTep` are one publisher's board. Counting them as
    two markets would flag ordinary offense trades as mixed and train
    readers to ignore the flag."""
    trade = TradeCandidate(
        give=[_asset("WR A", "WR", "ktcSfTep")],
        receive=[_asset("WR B", "WR", "ktc")],
    )
    d = trade.to_dict()
    assert d["marketsUsed"] == ["ktc"]
    assert d["mixedMarket"] is False


def test_unpriced_assets_contribute_no_market():
    """An asset with no market source cannot make a trade mixed — it
    contributes nothing to the delta either."""
    trade = TradeCandidate(
        give=[_asset("WR A", "WR", "ktcSfTep")],
        receive=[_asset("Nobody", "WR", None)],
    )
    d = trade.to_dict()
    assert d["marketsUsed"] == ["ktc"]
    assert d["mixedMarket"] is False


def test_a_trade_with_no_priced_assets_reports_no_markets():
    trade = TradeCandidate(give=[_asset("A", "WR", None)], receive=[_asset("B", "WR", None)])
    d = trade.to_dict()
    assert d["marketsUsed"] == []
    assert d["mixedMarket"] is False
