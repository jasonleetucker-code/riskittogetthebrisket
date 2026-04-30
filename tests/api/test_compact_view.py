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
                "sourceRankMeta": {
                    "ktcSfTep": {
                        "valueContribution": 9100,
                        "effectiveWeight": 1.0,
                        "method": "value_direct",
                        "percentile": 0.0001,
                        "valueContributionPath": "value_direct",
                        "isAnchor": True,
                        "tepBoostApplied": False,
                        "ladderDepth": 320,
                    },
                    "dlfSf": {
                        "valueContribution": 8800,
                        "effectiveWeight": 1.0,
                        "method": "rank_hill",
                        "percentile": 0.002,
                        "isAnchor": False,
                        "ladderDepth": 280,
                    },
                },
                "canonicalSiteValues": {"ktcSfTep": 9000},
                "droppedSources": [],
                "effectiveSourceRanks": {"ktcSfTep": 2},
                "sourceOriginalRanks": {"ktcSfTep": 2},
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
                "sourceRankMeta": {
                    "ktcSfTep": {
                        "valueContribution": 9100,
                        "effectiveWeight": 1.0,
                        "method": "value_direct",
                        "percentile": 0.0001,
                        "isAnchor": True,
                    },
                },
                "canonicalSiteValues": {"ktcSfTep": 9000},
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
    # ``sourceRankMeta`` and ``canonicalSiteValues`` are kept on the
    # compact view — the trade per-source winner card and the
    # rankings audit popover both read them.  Other audit-only fields
    # are still pruned.
    assert "sourceRankMeta" in player
    assert "canonicalSiteValues" in player
    assert "anomalyFlags" not in player
    # Kept fields.
    assert player["name"] == "Josh Allen"
    assert player["rankDerivedValue"] == 9200
    assert player["canonicalConsensusRank"] == 1


def test_prunes_players_array_fields():
    out = cv.compact_contract(_sample_contract())
    arr_player = out["playersArray"][0]
    assert "sourceRankMeta" in arr_player
    assert "canonicalSiteValues" in arr_player
    assert "anomalyFlags" not in arr_player
    assert arr_player["rankDerivedValue"] == 9200


def test_source_rank_meta_is_slimmed():
    """``sourceRankMeta`` survives the compact pass but each per-source
    entry is reduced to the fields the mobile UI actually consumes —
    valueContribution (drives the trade per-source winner row),
    effectiveWeight, method.  Audit-only stamps are dropped."""
    out = cv.compact_contract(_sample_contract())
    player = out["players"]["Josh Allen"]
    ktc_meta = player["sourceRankMeta"]["ktcSfTep"]
    # Kept fields.
    assert ktc_meta["valueContribution"] == 9100
    assert ktc_meta["effectiveWeight"] == 1.0
    assert ktc_meta["method"] == "value_direct"
    # Dropped audit-only fields.
    assert "percentile" not in ktc_meta
    assert "valueContributionPath" not in ktc_meta
    assert "isAnchor" not in ktc_meta
    assert "tepBoostApplied" not in ktc_meta
    assert "ladderDepth" not in ktc_meta
    # Same slimming applied per-source.
    dlf_meta = player["sourceRankMeta"]["dlfSf"]
    assert dlf_meta["valueContribution"] == 8800
    assert "percentile" not in dlf_meta


def test_source_rank_meta_slimming_on_players_array():
    out = cv.compact_contract(_sample_contract())
    arr_meta = out["playersArray"][0]["sourceRankMeta"]["ktcSfTep"]
    assert arr_meta["valueContribution"] == 9100
    assert "percentile" not in arr_meta
    assert "isAnchor" not in arr_meta


def test_non_destructive():
    orig = _sample_contract()
    _ = cv.compact_contract(orig)
    # Input unchanged: original audit fields still present.
    assert "poolAudit" in orig
    assert "percentile" in orig["players"]["Josh Allen"]["sourceRankMeta"]["ktcSfTep"]


def test_byte_savings_reports_positive_number():
    full = _sample_contract()
    compact = cv.compact_contract(full)
    stats = cv.byte_savings(full, compact)
    assert stats["savedBytes"] > 0
    assert stats["savedPct"] > 0


def test_compact_player_on_non_dict_is_passthrough():
    assert cv.compact_player(None) is None
    assert cv.compact_player("string") == "string"
