"""TC-A — Analyze Trade never counts an unpriced asset as 0, and never drops
one silently.

A board row the canonical pipeline declined to price (``rankDerivedValue``
null) resolves in the simulator with ``value`` 0 (or None).  The market lens
used to keep the 0 in the package math -- shifting the raw gap AND the
package model's piece count -- and say nothing.  Now it leaves the asset out
of the math, names it in ``unpricedIn`` / ``unpricedOut``, flags the lens
``incomplete`` and adds an uncertainty line (which caps confidence).
"""

from __future__ import annotations

from src.trade.analyze_trade import _market_lens, analyze_trade
from src.valuation_math.package_model import adjusted_pair_totals


def _sim(recv, send):
    return {
        "receiving": [{"name": n, "value": v} for n, v in recv],
        "sending": [{"name": n, "value": v} for n, v in send],
        "teamContext": {"applied": False},
    }


def test_unpriced_assets_are_reported_not_counted_as_zero() -> None:
    sim = _sim([("Star", 6000), ("Ghost Rookie", 0)], [("Vet", 5500), ("Null Pick", None)])
    lens = _market_lens(sim)
    d = lens.detail
    assert d["unpricedIn"] == ["Ghost Rookie"]
    assert d["unpricedOut"] == ["Null Pick"]
    assert d["incomplete"] is True
    # The math is exactly the priced pieces' math: no 0 piece reaches the
    # package model.
    send_adj, recv_adj, _, _ = adjusted_pair_totals([5500], [6000])
    assert d["vaAdjustedGap"] == round(recv_adj - send_adj)
    assert d["receivingValue"] == 6000 and d["sendingValue"] == 5500


def test_the_uncertainty_list_names_them() -> None:
    packet = analyze_trade(_sim([("Star", 6000), ("Ghost Rookie", 0)], [("Vet", 5500)]))
    joined = " | ".join(packet["uncertainty"])
    assert "Ghost Rookie" in joined
    assert "unpriced" in joined


def test_a_fully_priced_trade_is_complete() -> None:
    lens = _market_lens(_sim([("Star", 6000)], [("Vet", 5500)]))
    assert lens.detail["unpricedIn"] == [] and lens.detail["unpricedOut"] == []
    assert lens.detail["incomplete"] is False


def test_nothing_priced_still_names_what_was_unpriced() -> None:
    lens = _market_lens(_sim([("Ghost", 0)], [("Other Ghost", None)]))
    assert lens.available is False
    assert lens.unavailable_reason == "no_priced_assets_either_side"
    assert lens.detail == {"unpricedIn": ["Ghost"], "unpricedOut": ["Other Ghost"]}
