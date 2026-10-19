"""Structural eligibility: every excluded row is named, nothing is written."""

from __future__ import annotations

import copy

from src.league_valuation.contracts import load_params
from src.league_valuation.population import eligible_rows, scope_of_position
from tests.league_valuation._builders import row


def test_scope_positions_match_the_config():
    cfg = load_params()["scopes"]
    for scope, positions in cfg.items():
        for pos in positions:
            assert scope_of_position(pos) == scope, pos
    for pos in ("K", "P", "PICK", "", None):
        assert scope_of_position(pos) is None


def test_exclusion_reasons_and_order():
    rows = [
        row("1", "QB", 9000, 1),
        row("2", "LB", 5000, 2),
        row("3", "K", 1000, 3),
        row("4", "WR", None, 4),
        row("5", "WR", 4000, 5, quarantined=True, singleSourceValuePenaltyApplied=True),
        row("6", "RB", 3000, 6, anomalyFlags=["blend_integrity_violation"]),
        row("7", "RB", 2900, 7, singleSourceValuePenaltyApplied=True),
        row("8", "WR", 2800, 8, twoWayPlayerBoost={"applied": False}),
        row("9", "WR", 400, None, offCapPlayerValue=True),
        row("10", "WR", 0, 9),
        {
            "canonicalName": "2026 Pick 1.06",
            "assetClass": "pick",
            "rankDerivedValue": 3000,
            "canonicalConsensusRank": 10,
        },
        row("11", "TE", 2000, 11),
        row("11", "TE", 1900, 12),
    ]
    before = copy.deepcopy(rows)
    pops, excluded = eligible_rows(rows)
    assert rows == before
    assert [r["playerId"] for r in pops["OFFENSE"]] == ["1"]
    assert [r["playerId"] for r in pops["IDP"]] == ["2"]
    assert excluded == {
        "player:3": "unsupported_position",
        "player:4": "no_market_value",
        "player:5": "quarantined",
        "player:6": "blend_integrity_violation",
        "player:7": "single_source_haircut",
        "player:8": "two_way_player",
        "player:9": "off_cap_value_only",
        "player:10": "no_market_value",
        "mpick:2026:r1:s6": "pick",
        "player:11": "duplicate_asset_key",
    }


def test_every_reason_is_declared_in_the_config():
    declared = set(load_params()["exclusions"])
    rows = [row("3", "K", 1000, 3), row("9", "WR", 400, None)]
    _, excluded = eligible_rows(rows)
    assert set(excluded.values()) <= declared


def test_sub_unit_market_value_is_missing_not_zero():
    from src.league_valuation.population import market_value_of

    assert market_value_of({"rankDerivedValue": 0.4}) is None
    assert market_value_of({"rankDerivedValue": 0}) is None
    assert market_value_of({"rankDerivedValue": 0.6}) == 1
    pops, excluded = eligible_rows([row("77", "RB", 1, 1) | {"rankDerivedValue": 0.4}])
    assert excluded == {"player:77": "no_market_value"}
    assert not pops["OFFENSE"]
