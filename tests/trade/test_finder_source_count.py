"""The finder's confidence reads the board's blend count, not `_sites`.

Audit finding W09-F008 (root cause R7).

``build_asset_pool`` populated ``Asset.source_count`` from the legacy
players dict's ``_sites`` — the SCRAPER's site count.  On the live
payload that field takes only the values 1 (526 rows), 2 (110), 3 (438)
and null (18): a maximum of 3.  Measured against
``CONFIDENCE_SOURCE_BASELINE = 5`` it caps ``source_confidence`` at 0.60,
so the total confidence score can never reach the 0.75 ``high`` tier —
across 480 returned trades over 12 teams the tier appeared zero times.

The board's real blend count is on the contract row:
``effectiveSourceRanks`` is the post-Hampel voter set and runs to 16.
Lowering the baseline to match ``_sites`` would have hidden this; the
number was wrong, not the threshold.
"""

from __future__ import annotations

from src.trade.finder import (
    _confidence_tier,
    _score_trade,
    build_asset_pool,
    source_counts_from_contract,
)


def _contract() -> dict:
    return {
        "playersArray": [
            {
                "canonicalName": "Blended",
                "legacyRef": "Blended",
                "position": "WR",
                "rankDerivedValue": 8000,
                "effectiveSourceRanks": {f"src{i}": i + 1 for i in range(12)},
            },
            {
                "canonicalName": "Thin",
                "legacyRef": "Thin",
                "position": "WR",
                "rankDerivedValue": 4000,
                "effectiveSourceRanks": {"ktcSfTep": 40},
            },
            {
                "canonicalName": "Unvoted",
                "legacyRef": "Unvoted",
                "position": "WR",
                "rankDerivedValue": 3000,
                "effectiveSourceRanks": {},
            },
        ],
        "players": {},
    }


def _players() -> dict:
    return {
        "Blended": {"_sites": 3, "_canonicalSiteValues": {"ktcSfTep": 8000}},
        "Thin": {"_sites": 1, "_canonicalSiteValues": {"ktcSfTep": 4000}},
        "Unvoted": {"_sites": 2, "_canonicalSiteValues": {"ktcSfTep": 3000}},
    }


def test_the_map_reads_the_post_hampel_voter_set():
    counts = source_counts_from_contract(_contract())
    assert counts["Blended"] == 12
    assert counts["Thin"] == 1
    # Zero voters is neither "unknown" nor "one" — it stays unmapped so
    # the caller's own absent-value path runs.
    assert "Unvoted" not in counts


def test_the_pool_carries_the_blend_count_not_the_site_count():
    contract = _contract()
    pool = build_asset_pool(
        _players(),
        market_top_n=0,
        board_values={r["canonicalName"]: r["rankDerivedValue"] for r in contract["playersArray"]},
        positions={r["canonicalName"]: r["position"] for r in contract["playersArray"]},
        source_counts=source_counts_from_contract(contract),
    )
    by_name = {a.name: a for a in pool}
    assert by_name["Blended"].source_count == 12
    # No contract entry — the scraper count remains the fallback rather
    # than becoming zero.
    assert by_name["Unvoted"].source_count == 2


def test_the_high_confidence_tier_is_reachable_from_a_real_pool():
    """A trade between two well-blended assets must earn the top tier.

    Scored from pool assets, not hand-built ones: the defect was in what
    the POOL put on the asset, so a test that sets ``source_count``
    itself would pass against the broken code.
    """
    rows = [
        {
            "canonicalName": "Give",
            "legacyRef": "Give",
            "position": "WR",
            "rankDerivedValue": 6000,
            "effectiveSourceRanks": {f"s{i}": i + 1 for i in range(12)},
        },
        {
            "canonicalName": "Get",
            "legacyRef": "Get",
            "position": "WR",
            "rankDerivedValue": 7000,
            "effectiveSourceRanks": {f"s{i}": i + 1 for i in range(14)},
        },
    ]
    contract = {"playersArray": rows, "players": {}}
    players = {
        "Give": {"_sites": 3, "_canonicalSiteValues": {"ktcSfTep": 4000}},
        "Get": {"_sites": 3, "_canonicalSiteValues": {"ktcSfTep": 3000}},
    }
    pool = build_asset_pool(
        players,
        market_top_n=0,
        board_values={r["canonicalName"]: r["rankDerivedValue"] for r in rows},
        positions={r["canonicalName"]: r["position"] for r in rows},
        source_counts=source_counts_from_contract(contract),
    )
    by_name = {a.name: a for a in pool}
    tc = _score_trade([by_name["Give"]], [by_name["Get"]])
    assert tc is not None
    assert tc.confidence_tier == "high", tc.confidence_score
    # The value ``_sites`` would have supplied for these same two rows
    # cannot reach the tier at all — the ceiling, not the trade.
    assert _confidence_tier(min(1.0, 3 / 5) * 1.0) != "high"

