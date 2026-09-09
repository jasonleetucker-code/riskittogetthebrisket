from __future__ import annotations

from src.api.data_contract import (
    _RANKING_SOURCES,
    _SOURCE_CSV_PATHS,
    _VALUE_BASED_SOURCES,
    _stamp_ktc_value_source_diagnostics,
)


def test_only_crowd_trades_is_a_ktc_voter():
    keys = {str(source.get("key") or "") for source in _RANKING_SOURCES}
    assert "ktcCrowdTradesSfTep" in keys
    assert "ktcCrowdSfTep" not in keys
    assert "ktcTradesSfTep" not in keys
    assert "ktcSfTep" not in keys

    assert "ktcCrowdTradesSfTep" in _VALUE_BASED_SOURCES
    assert "ktcCrowdSfTep" not in _VALUE_BASED_SOURCES
    assert "ktcTradesSfTep" not in _VALUE_BASED_SOURCES
    assert "ktcSfTep" not in _VALUE_BASED_SOURCES


def test_all_three_source_modes_and_historical_crowd_pair_remain_loadable():
    assert "ktcCrowdSfTep" in _SOURCE_CSV_PATHS
    assert "ktcTradesSfTep" in _SOURCE_CSV_PATHS
    assert "ktcCrowdTradesSfTep" in _SOURCE_CSV_PATHS

    # Historical calibration keys remain readable and retain their old meaning.
    assert "ktc" in _SOURCE_CSV_PATHS
    assert "ktcSfTep" in _SOURCE_CSV_PATHS


def test_contract_exposes_numeric_crowd_trade_divergence_without_extra_vote():
    rows = [
        {
            "canonicalName": "Example RB",
            "canonicalSiteValues": {
                "ktcCrowdSfTep": 4800,
                "ktcTradesSfTep": 5100,
                "ktcCrowdTradesSfTep": 4950,
            },
        }
    ]
    _stamp_ktc_value_source_diagnostics(rows)
    block = rows[0]["ktcValueSources"]

    assert block["canonicalMarketSource"] == "crowd_trades"
    assert block["format"] == {
        "gameType": "DYNASTY",
        "superflex": True,
        "tePremium": "TE++",
        "tePremiumLevel": 2,
    }
    assert block["crowd"]["value"] == 4800
    assert block["trades"]["value"] == 5100
    assert block["crowdTrades"]["value"] == 4950
    assert block["divergence"]["delta"] == 300
    assert block["divergence"]["percentDelta"] == 6.25
    assert block["divergence"]["direction"] == "trade_premium"


def test_missing_tradesourced_contract_value_stays_missing_not_zero():
    rows = [
        {
            "canonicalName": "Low-volume Rookie",
            "canonicalSiteValues": {
                "ktcCrowdSfTep": 2000,
                "ktcCrowdTradesSfTep": 2100,
            },
        }
    ]
    _stamp_ktc_value_source_diagnostics(rows)
    block = rows[0]["ktcValueSources"]
    assert block["trades"]["value"] is None
    assert block["divergence"] == {
        "delta": None,
        "percentDelta": None,
        "direction": None,
    }
