"""Master-site-audit W12-F002 regression (CW-40, 2026-11-06) -- PARTIAL closure.

August claim: the /rankings Edge label was a positional level offset, not a
mispricing -- EVERY SELL in the top 250 was a tight end -- because the gap
compared one TE++ retail board against 13 expert boards by RANK.

What this pins (offline, synthetic rows through the real production stamper,
no archive/market data, so a KTC refresh cannot flip it): the gap is OUR
``rankDerivedValue`` against KTC Market in value space and is position-blind.
What it does NOT pin: the residual TE SELL skew (a methodology/calibration
question routed to CW-36), which is a property of live board values.
"""

from __future__ import annotations

import inspect

from src.api import data_contract
from src.sources import ktc_market

_MIN_RATIO = 0.05  # frontend/lib/thresholds.js::MARKET_GAP_MIN_VALUE_RATIO


def _row(name: str, position: str, model: float, ktc_raw: float) -> dict:
    return {
        "displayName": name,
        "position": position,
        "rankDerivedValue": model,
        "canonicalSiteValues": {ktc_market.KTC_MARKET_KEY: ktc_raw},
    }


def _stamp(*specs):
    # Anchor pins KTC Market's own maximum at 9999 so normalized == raw.
    rows = [_row("Anchor QB", "QB", 9999.0, 9999.0)]
    rows += [_row(*s) for s in specs]
    data_contract._stamp_ktc_market_benchmark(rows)
    return {r["displayName"]: r for r in rows}


def _is_sell(row: dict) -> bool:
    return (
        row.get("marketGapDirection") == ktc_market.MARKET_PREMIUM
        and (row.get("marketGapValueRatio") or 0) >= _MIN_RATIO
    )


def test_te_and_wr_with_the_same_gap_get_the_same_label():
    out = _stamp(("TE x", "TE", 5000.0, 6500.0), ("WR x", "WR", 5000.0, 6500.0))
    te, wr = out["TE x"], out["WR x"]
    assert _is_sell(te) and _is_sell(wr)
    assert (te["marketGapDirection"], te["marketGapValueRatio"]) == (
        wr["marketGapDirection"],
        wr["marketGapValueRatio"],
    )


def test_a_sub_threshold_gap_is_not_sell_for_any_position():
    out = _stamp(("TE s", "TE", 5000.0, 5100.0), ("WR s", "WR", 5000.0, 5100.0))
    for name in ("TE s", "WR s"):
        assert out[name]["marketGapValueRatio"] < _MIN_RATIO
        assert not _is_sell(out[name])


def test_the_opposite_sign_is_a_model_premium_not_sell():
    out = _stamp(("TE o", "TE", 6500.0, 5000.0), ("WR o", "WR", 6500.0, 5000.0))
    for name in ("TE o", "WR o"):
        assert out[name]["marketGapDirection"] == ktc_market.MODEL_PREMIUM
        assert not _is_sell(out[name])


def test_missing_market_is_no_gap_not_zero():
    row = {
        "displayName": "No KTC",
        "position": "TE",
        "rankDerivedValue": 5000.0,
        "canonicalSiteValues": {},
    }
    anchor = _row("Anchor QB", "QB", 9999.0, 9999.0)
    data_contract._stamp_ktc_market_benchmark([anchor, row])
    assert row["marketGapDirection"] == ktc_market.NO_GAP
    assert row["marketGapValueRatio"] is None


def test_the_gap_function_takes_no_position_or_rank():
    params = set(inspect.signature(ktc_market.compute_market_gap).parameters)
    assert params == {"model_value", "market_normalized"}
