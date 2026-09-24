"""The market gap compares OUR MODEL against KTC MARKET — and nothing else.

HISTORY (B10-T3a)
─────────────────
``marketGapDirection`` / ``marketGapValueRatio`` used to split the sources
on a row into a "retail" side (the KTC family, incl. the KTC-derived
``fantasyNavigatorSf``) and a "consensus" side (every other source).  B10-T3a
fixed a real defect in that design — Fantasy Navigator had landed on the
consensus side, so retail was measured against itself on 437 rows and the
direction flipped on 72 when corrected.

THE CURRENT DEFINITION (owner directive 2026-09-23)
───────────────────────────────────────────────────
"Difference from market" means OUR MODEL VALUE (``rankDerivedValue``)
against CANONICAL KTC MARKET — KTC's own published Crowd+Trades value,
normalized onto the board scale — owned by ``src/sources/ktc_market.py``.
The anti-circularity requirement survives in a stronger form: the market
side is a single published number, so no other source (Fantasy Navigator,
IDPTC, DLF, …) can ever enter it, and KTC Market can never enter the model
as a vote (it is derived from the two KTC inputs that already do).
"""

from __future__ import annotations

import json
import pathlib

import pytest

from src.api.data_contract import (
    _RANKING_SOURCES,
    _compute_market_gap,
    build_api_data_contract,
    expand_correlation_groups,
)
from src.sources.ktc_market import (
    KTC_CROWD_KEY,
    KTC_MARKET_KEY,
    KTC_TRADES_KEY,
    build_market_blocks,
    compute_market_gap,
)

REPO = pathlib.Path(__file__).resolve().parents[2]


def _contract() -> dict:
    candidates = sorted((REPO / "exports" / "latest").glob("dynasty_data*.json"), reverse=True)
    if not candidates:
        pytest.skip("no export available in this environment")
    return build_api_data_contract(json.loads(candidates[0].read_text(encoding="utf-8")))


def _row(name: str, **sites: float) -> dict:
    return {"displayName": name, "position": "WR", "canonicalSiteValues": dict(sites)}


class TestTheMarketSideIsOnlyKtcMarket:
    def test_other_sources_cannot_move_the_market_block(self):
        base = [_row("A", ktcCrowdTradesSfTep=8000.0), _row("B", ktcCrowdTradesSfTep=4000.0)]
        noisy = [
            _row(
                "A",
                ktcCrowdTradesSfTep=8000.0,
                fantasyNavigatorSf=1.0,
                idpTradeCalc=9999.0,
                dlfSf=5.0,
            ),
            _row("B", ktcCrowdTradesSfTep=4000.0, fantasyNavigatorSf=9999.0),
        ]
        build_market_blocks(base)
        build_market_blocks(noisy)
        assert [r["ktcMarket"] for r in base] == [r["ktcMarket"] for r in noisy]

    def test_crowd_and_trades_alone_do_not_manufacture_a_market(self):
        """KTC Market is KTC's PUBLISHED blend; we never reconstruct it."""
        rows = [_row("A", ktcCrowdSfTep=8000.0, ktcTradesSfTep=7000.0)]
        build_market_blocks(rows)
        assert rows[0]["ktcMarket"]["value"] is None
        assert rows[0]["ktcMarket"]["available"] is False

    def test_the_gap_is_model_against_market(self):
        assert compute_market_gap(7000.0, 9000.0) == _compute_market_gap(7000.0, 9000.0)
        direction, ratio = _compute_market_gap(7000.0, 9000.0)
        assert direction == "retail_premium"
        assert ratio == pytest.approx(0.25)


class TestKtcMarketIsNeverAModelInput:
    def test_market_key_is_not_registered(self):
        keys = {str(s.get("key") or "") for s in _RANKING_SOURCES}
        assert KTC_MARKET_KEY not in keys
        assert {KTC_CROWD_KEY, KTC_TRADES_KEY} <= keys

    def test_removing_the_market_removes_all_ktc_lineage(self):
        """Consensus Edge's leave-one-out board excludes the anchor; for KTC
        Market that must drop BOTH inputs it is derived from and the
        KTC-derived republisher, or the "anchor-free" board still carries
        KTC."""
        assert expand_correlation_groups([KTC_MARKET_KEY]) >= {
            KTC_MARKET_KEY,
            KTC_CROWD_KEY,
            KTC_TRADES_KEY,
            "fantasyNavigatorSf",
        }


class TestOnTheLiveBoard:
    def test_every_published_gap_is_model_vs_ktc_market(self):
        contract = _contract()
        checked = 0
        for row in contract["playersArray"]:
            market = row.get("ktcMarket") or {}
            expected = _compute_market_gap(
                row.get("rankDerivedValue"), market.get("normalizedValue")
            )
            assert (row.get("marketGapDirection"), row.get("marketGapValueRatio")) == expected, row[
                "displayName"
            ]
            if expected[1] is not None:
                checked += 1
        assert checked > 0
