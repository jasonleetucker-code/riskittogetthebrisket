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
                        "appliedWeight": 1.0,
                        "effectiveWeight": 1.0,
                        "method": "value_direct",
                        "percentile": 0.0001,
                        "valueContributionPath": "value_direct",
                        "isAnchor": True,
                        "tepBoostApplied": False,
                        "ladderDepth": 320,
                    },
                    # The two weights differ here on purpose: the live
                    # contract has 147 such entries and this fixture
                    # used to carry neither the field nor the case,
                    # which is how the compact view came to ship only
                    # the diagnostic one.  See
                    # tests/api/test_compact_view_weights.py.
                    "dlfSf": {
                        "valueContribution": 8800,
                        "appliedWeight": 1.0,
                        "effectiveWeight": 0.4667,
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
                        "appliedWeight": 1.0,
                        "effectiveWeight": 0.8,
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
    assert "siteStats" not in out
    # ``methodology`` is NOT pruned.  It is rendered by
    # ``app/rankings/page.jsx`` (<MethodologySection methodology=...>), so
    # pruning it deleted a whole section on mobile and nowhere else — a
    # board difference, not a byte saving.
    assert "methodology" in out
    # Meta is preserved + stamped with view.
    assert out["meta"]["view"] == "compact"
    # Sleeper block preserved for team switcher.
    assert "sleeper" in out


def test_drops_the_legacy_players_dict_when_the_array_is_present():
    """The dict and ``playersArray`` are parallel encodings of the same
    rows, and ``buildRows`` prefers the array whenever it is present.
    Carrying both is what made the "compact" mobile view LARGER than the
    desktop ``array`` view (735.0 KB gz vs 631.8 KB gz on a 1,109-row
    contract, 2026-08-18)."""
    out = cv.compact_contract(_sample_contract())
    assert "players" not in out
    assert isinstance(out["playersArray"], list)


def test_keeps_the_dict_when_there_is_no_array_to_replace_it():
    """A payload carrying the dict ALONE is a legitimate shape — the
    runtime view strips ``playersArray``.  Dropping the dict there would
    turn a size optimization into data loss, so the drop is conditional
    on the array actually being present."""
    contract = _sample_contract()
    contract.pop("playersArray")
    out = cv.compact_contract(contract)
    assert "players" in out
    assert out["players"]["Josh Allen"]["rankDerivedValue"] == 9200


def test_prunes_player_level_fields():
    """Applied to the dict encoding, on the runtime-view shape where it is
    the only encoding present."""
    contract = _sample_contract()
    contract.pop("playersArray")
    out = cv.compact_contract(contract)
    player = out["players"]["Josh Allen"]
    # ``sourceRankMeta`` and ``canonicalSiteValues`` are kept on the
    # compact view — the trade per-source winner card and the
    # rankings audit popover both read them.
    assert "sourceRankMeta" in player
    assert "canonicalSiteValues" in player
    # ``anomalyFlags`` is NO LONGER pruned: the materializer reads it and
    # /edge's "Flagged" stat tile counts it, so pruning made that tile
    # read 0 on mobile and the real count on desktop.
    assert "anomalyFlags" in player
    # Still pruned — no frontend consumer reads it off a player row.
    assert "pickDetails" not in player
    # Kept fields.
    assert player["name"] == "Josh Allen"
    assert player["rankDerivedValue"] == 9200
    assert player["canonicalConsensusRank"] == 1


def test_prunes_players_array_fields():
    out = cv.compact_contract(_sample_contract())
    arr_player = out["playersArray"][0]
    assert "sourceRankMeta" in arr_player
    assert "canonicalSiteValues" in arr_player
    assert "anomalyFlags" in arr_player
    assert arr_player["rankDerivedValue"] == 9200


def test_source_rank_meta_is_slimmed():
    """``sourceRankMeta`` survives the compact pass but each per-source
    entry is reduced to the fields the mobile UI actually consumes —
    valueContribution (drives the trade per-source winner row), both
    weights, method.  Audit-only stamps are dropped."""
    contract = _sample_contract()
    contract.pop("playersArray")
    out = cv.compact_contract(contract)
    player = out["players"]["Josh Allen"]
    ktc_meta = player["sourceRankMeta"]["ktcSfTep"]
    # Kept fields.
    assert ktc_meta["valueContribution"] == 9100
    assert ktc_meta["appliedWeight"] == 1.0
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
