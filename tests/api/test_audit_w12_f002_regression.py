"""Master-site-audit W12-F002 regression (CW-40, 2026-11-06).

August claim: the /rankings Edge label was a positional level offset, not a
mispricing -- 32 of 35 top-250 tight ends read SELL and EVERY SELL in the top
250 was a tight end -- because the gap compared one TE++ retail board against
13 expert boards by RANK.

Closed by the 2026-09-23 redefinition (``src/sources/ktc_market.py``): the
gap is OUR published ``rankDerivedValue`` against KTC Market's normalized
value, in value space, and takes no position and no rank.  This pins that
structure and the symptom on a real board from the tracked archive.
"""

from __future__ import annotations

import inspect

import pytest

from src.api import data_contract
from src.sources import ktc_market
from tests.archive_fixtures import newest_complete_contract

_MIN_RATIO = 0.05  # frontend/lib/thresholds.js::MARKET_GAP_MIN_VALUE_RATIO


def test_the_gap_function_is_position_blind_and_value_space():
    params = set(inspect.signature(ktc_market.compute_market_gap).parameters)
    assert params == {"model_value", "market_normalized"}
    # Same model and market value -> same verdict whatever the asset is.
    assert ktc_market.compute_market_gap(5000.0, 5000.0)[1] == 0.0
    assert ktc_market.compute_market_gap(5000.0, 6000.0)[0] == ktc_market.MARKET_PREMIUM
    assert ktc_market.compute_market_gap(6000.0, 5000.0)[0] == ktc_market.MODEL_PREMIUM
    # Missing is never a zero gap.
    assert ktc_market.compute_market_gap(None, 5000.0) == (ktc_market.NO_GAP, None)
    assert ktc_market.compute_market_gap(5000.0, None) == (ktc_market.NO_GAP, None)


def test_the_contract_stamp_is_exactly_model_versus_ktc_market():
    contract, _name = newest_complete_contract()
    if contract is None:
        pytest.skip("no complete archived board available")
    checked = 0
    for row in contract["playersArray"]:
        market = row.get("ktcMarket") or {}
        if row.get("marketGapDirection") in (None, "none"):
            continue
        expected = data_contract._compute_market_gap(
            row.get("rankDerivedValue"), market.get("normalizedValue")
        )
        assert (row["marketGapDirection"], row["marketGapValueRatio"]) == expected
        checked += 1
    assert checked > 50


def test_sell_is_not_a_tight_end_only_label():
    contract, _name = newest_complete_contract()
    if contract is None:
        pytest.skip("no complete archived board available")
    sells = [
        r
        for r in contract["playersArray"]
        if isinstance(r.get("canonicalConsensusRank"), int)
        and r["canonicalConsensusRank"] <= 250
        and r.get("marketGapDirection") == "retail_premium"
        and (r.get("marketGapValueRatio") or 0) >= _MIN_RATIO
    ]
    positions = {r.get("position") for r in sells}
    assert len(sells) >= 10, "check would be vacuous"
    assert positions - {"TE"}, f"every top-250 SELL is a TE again: {positions}"
