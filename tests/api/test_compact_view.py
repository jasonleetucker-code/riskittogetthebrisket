"""Tests for the compact contract view builder."""
from __future__ import annotations

from src.api import compact_view as cv


def _sample_contract():
    return {
        "players": {
            "Josh Allen": {
                "name": "Josh Allen",
                "rankDerivedValue": 9200,
                "canonicalConsensusRank": 1,
                "sourceRankMeta": {"x": 1, "y": 2},
                "canonicalSiteValues": {"ktc": 9000},
                "droppedSources": [],
                "effectiveSourceRanks": {"ktc": 2},
                "sourceOriginalRanks": {"ktc": 2},
                "anomalyFlags": [],
                "confidenceLabel": "High",
                "pickDetails": None,
                "marketCorridorClamp": None,
                "twoWayPlayerBoost": None,
                "subgroupBlendValue": None,
                "subgroupDelta": None,
                "alphaShrinkage": None,
                "softFallbackCount": 0,
                "hillValueSpread": None,
                "marketDispersionCV": None,
                "blendedSourceRank": None,
                "madPenaltyApplied": None,
                "anchorValue": None,
            }
        },
        "playersArray": [
            {
                "displayName": "Josh Allen",
                "rankDerivedValue": 9200,
                "sourceRankMeta": {"x": 1},
                "canonicalSiteValues": {"ktc": 9000},
                "anomalyFlags": [],
            }
        ],
        "poolAudit": {"big": "object"},
        "methodology": {"long": "text" * 100},
        "siteStats": {"lots": "of data"},
        "meta": {"leagueKey": "dynasty_main"},
        "sleeper": {"teams": []},
    }


def test_prunes_contract_level_fields():
    out = cv.compact_contract(_sample_contract())
    assert "poolAudit" not in out
    assert "methodology" not in out
    assert "siteStats" not in out
    # Meta is preserved + stamped with view.
    assert out["meta"]["view"] == "compact"
    # Sleeper block preserved for team switcher.
    assert "sleeper" in out


def test_prunes_player_level_fields():
    out = cv.compact_contract(_sample_contract())
    player = out["players"]["Josh Allen"]
    assert "sourceRankMeta" not in player
    assert "canonicalSiteValues" not in player
    assert "anomalyFlags" not in player
    # Kept fields.
    assert player["name"] == "Josh Allen"
    assert player["rankDerivedValue"] == 9200
    assert player["canonicalConsensusRank"] == 1


def test_prunes_players_array_fields():
    out = cv.compact_contract(_sample_contract())
    arr_player = out["playersArray"][0]
    assert "sourceRankMeta" not in arr_player
    assert "canonicalSiteValues" not in arr_player
    assert arr_player["rankDerivedValue"] == 9200


def test_non_destructive():
    orig = _sample_contract()
    _ = cv.compact_contract(orig)
    # Input unchanged.
    assert "poolAudit" in orig
    assert "sourceRankMeta" in orig["players"]["Josh Allen"]


def test_byte_savings_reports_positive_number():
    full = _sample_contract()
    compact = cv.compact_contract(full)
    stats = cv.byte_savings(full, compact)
    assert stats["savedBytes"] > 0
    assert stats["savedPct"] > 0


def test_compact_player_on_non_dict_is_passthrough():
    assert cv.compact_player(None) is None
    assert cv.compact_player("string") == "string"
