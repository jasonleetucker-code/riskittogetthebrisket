"""Tests for the normalization validator."""
from __future__ import annotations

import logging

from src.canonical import normalization_validator as nv


def test_valid_contract_reports_healthy():
    contract = {
        "playersArray": [
            {
                "displayName": "Josh Allen", "canonicalName": "Josh Allen",
                "position": "QB", "assetClass": "offense",
            },
            {
                "displayName": "2027 Mid 4th", "canonicalName": "2027 Mid 4th",
                "position": "PICK", "assetClass": "pick",
            },
        ],
    }
    result = nv.validate_contract(contract)
    assert result["healthy"] is True
    assert result["playersArray"]["total"] == 2


def test_detects_display_canonical_drift(caplog):
    contract = {
        "playersArray": [
            {
                "displayName": "Joshua Allen", "canonicalName": "Josh Allen",
                "position": "QB", "assetClass": "offense",
            },
        ],
    }
    with caplog.at_level(logging.WARNING):
        result = nv.validate_contract(contract)
    assert result["healthy"] is False
    assert result["playersArray"]["playerNameDrift"] == 1
    # Structured log line emitted.
    assert any(
        "normalization_mismatch=player_name_drift" in rec.message
        for rec in caplog.records
    )


def test_detects_malformed_pick_name():
    contract = {
        "playersArray": [
            {
                "displayName": "not a real pick", "canonicalName": "not a real pick",
                "position": "PICK", "assetClass": "pick",
            },
        ],
    }
    result = nv.validate_contract(contract)
    assert result["healthy"] is False
    assert result["playersArray"]["pickNameMalformed"] == 1


def test_detects_asset_class_mismatch():
    contract = {
        "playersArray": [
            {
                "displayName": "Josh Allen", "canonicalName": "Josh Allen",
                "position": "QB",
                "assetClass": "idp",  # wrong — QB is offense
            },
        ],
    }
    result = nv.validate_contract(contract)
    assert result["healthy"] is False
    assert result["playersArray"]["assetClassMismatch"] == 1


def test_detects_duplicate_keys():
    contract = {
        "playersArray": [
            {"displayName": "Josh Allen", "position": "QB", "assetClass": "offense"},
            {"displayName": "Josh Allen", "position": "QB", "assetClass": "offense"},
        ],
    }
    result = nv.validate_contract(contract)
    assert result["playersArray"]["dupKeys"] == 1


def test_sample_cap_limits_output_size():
    contract = {
        "playersArray": [
            {
                "displayName": f"Bad {i}", "canonicalName": f"Real {i}",
                "position": "QB", "assetClass": "offense",
            }
            for i in range(50)
        ],
    }
    result = nv.validate_contract(contract)
    assert len(result["playersArray"]["samples"]) <= 20


def test_valid_pick_patterns_accepted():
    names = [
        "2027 Mid 4th", "2026 Early 1st", "2027 Late 6th",
        "2026 Pick 1.01", "2027 Pick 2.12",
        "2026 1st Round", "2027 4th Round",
    ]
    for name in names:
        assert nv.is_valid_pick_name(name), name


def test_invalid_pick_patterns_rejected():
    for name in ["", "2027 4th", "Josh Allen", "just garbage", "2027"]:
        assert not nv.is_valid_pick_name(name), name


def test_empty_contract_is_healthy():
    assert nv.validate_contract({})["healthy"] is True
    assert nv.validate_contract(None)["healthy"] is True


def test_malformed_rows_dont_crash():
    contract = {"playersArray": [None, "garbage", 42, {}]}
    result = nv.validate_contract(contract)
    # Counter doesn't advance for non-dict rows.
    assert result["playersArray"]["total"] == 1  # only {} counts


def test_legacy_dict_shape_validated():
    contract = {
        "players": {
            "Josh Allen": {"_canonicalName": "Joshua Allen"},  # drift
        },
    }
    result = nv.validate_contract(contract)
    assert result["playersDict"]["playerNameDrift"] == 1
