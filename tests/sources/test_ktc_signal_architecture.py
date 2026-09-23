"""KTC signal architecture — owner directive 2026-09-23.

    OUR MODEL INPUTS            MARKET BENCHMARK
    KTC Crowd  (ktcCrowdSfTep)  KTC Market (ktcCrowdTradesSfTep)
    KTC Trades (ktcTradesSfTep)   = KTC's PUBLISHED Crowd+Trades
    + every other source          (benchmark-only, never a vote)

KTC Market is derived from Crowd + Trades, so registering it beside them
would count the same KTC information twice.  These tests fail if that ever
happens, or if anything other than KTC's own published number reaches the
market side.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

from src.api import data_contract as dc
from src.sources import ktc_market as km

REPO = Path(__file__).resolve().parents[2]


def _registry_keys() -> list[str]:
    return [str(s.get("key") or "") for s in dc._RANKING_SOURCES]


class TestModelInputs:
    def test_crowd_is_a_separate_model_input(self):
        assert km.KTC_CROWD_KEY in _registry_keys()

    def test_trades_is_a_separate_model_input(self):
        assert km.KTC_TRADES_KEY in _registry_keys()

    def test_market_is_not_a_third_input(self):
        keys = _registry_keys()
        ktc_inputs = [k for k in keys if k in km.KTC_ALL_KEYS]
        assert ktc_inputs == [km.KTC_CROWD_KEY, km.KTC_TRADES_KEY]
        assert ktc_inputs != [km.KTC_CROWD_KEY, km.KTC_TRADES_KEY, km.KTC_MARKET_KEY]

    def test_registering_the_market_fails_at_import(self, monkeypatch):
        monkeypatch.setattr(
            dc, "_RANKING_SOURCES", [*dc._RANKING_SOURCES, {"key": km.KTC_MARKET_KEY}]
        )
        with pytest.raises(RuntimeError, match="non-voting source keys registered"):
            dc._assert_non_voting_keys_unregistered()

    def test_crowd_and_trades_are_separate_families(self):
        assert dc.correlation_group_for(km.KTC_CROWD_KEY) != dc.correlation_group_for(
            km.KTC_TRADES_KEY
        )

    def test_fantasy_navigator_is_never_a_hidden_third_ktc_vote(self):
        fn_family = dc.correlation_group_for("fantasyNavigatorSf")
        assert fn_family in {
            dc.correlation_group_for(km.KTC_CROWD_KEY),
            dc.correlation_group_for(km.KTC_TRADES_KEY),
        }

    def test_both_inputs_vote_value_direct_with_their_own_weight(self):
        by_key = {s["key"]: s for s in dc._RANKING_SOURCES}
        for key in km.KTC_MODEL_INPUT_KEYS:
            assert key in dc._VALUE_BASED_SOURCES
            assert by_key[key]["weight"] == 1.0
        assert km.KTC_MARKET_KEY not in dc._VALUE_BASED_SOURCES


class TestMarketBenchmark:
    def test_market_is_kt_published_crowd_trades(self):
        rows = [
            {
                "displayName": "A",
                "position": "WR",
                "canonicalSiteValues": {"ktcCrowdTradesSfTep": 5000},
            }
        ]
        km.build_market_blocks(rows)
        assert rows[0]["ktcMarket"]["value"] == 5000.0

    def test_non_ktc_sources_never_leak_into_the_market(self):
        a = [
            {
                "displayName": "A",
                "position": "WR",
                "canonicalSiteValues": {"ktcCrowdTradesSfTep": 5000},
            }
        ]
        b = [
            {
                "displayName": "A",
                "position": "WR",
                "canonicalSiteValues": {
                    "ktcCrowdTradesSfTep": 5000,
                    "idpTradeCalc": 9999,
                    "idpShowCombined": 1,
                    "dlfSf": 3,
                    "fantasyNavigatorSf": 9000,
                },
            }
        ]
        km.build_market_blocks(a)
        km.build_market_blocks(b)
        assert a[0]["ktcMarket"] == b[0]["ktcMarket"]

    def test_missing_market_is_missing_not_zero(self):
        rows = [
            {"displayName": "LB", "position": "LB", "canonicalSiteValues": {"idpTradeCalc": 4000}}
        ]
        km.build_market_blocks(rows)
        assert rows[0]["ktcMarket"]["value"] is None
        assert rows[0]["ktcMarket"]["reason"] == km.MARKET_UNAVAILABLE_NO_COVERAGE
        assert km.compute_market_gap(4000, None) == ("none", None)

    def test_out_of_range_market_value_is_refused(self):
        rows = [
            {
                "displayName": "X",
                "position": "WR",
                "canonicalSiteValues": {"ktcCrowdTradesSfTep": 99990},
            }
        ]
        km.build_market_blocks(rows)
        assert rows[0]["ktcMarket"]["value"] is None
        assert rows[0]["ktcMarket"]["reason"] == km.MARKET_UNAVAILABLE_OUT_OF_RANGE

    def test_model_vs_market_differences(self):
        diff = km.model_vs_market(
            6000.0, {"value": 5000.0, "normalizedValue": 5200.0, "available": True}
        )
        assert diff["absoluteDifference"] == 1000.0
        assert diff["percentDifference"] == 0.2
        assert diff["normalizedDifference"] == 800.0
        assert diff["direction"] == "consensus_premium"


class TestOneMarketDefinition:
    """No module outside the owner may spell the KTC Market key as a literal:
    every consumer must import it, so there is exactly one definition."""

    ALLOWED = {
        "src/sources/ktc_market.py",  # the owner
        "src/sources/ktc_value_sources.py",  # the capture writer (#1391 claim)
        "src/api/data_contract.py",  # CSV path table + non-voting declaration
        "src/api/source_history.py",  # chart raw-value key set
        "src/history/record.py",  # ledger lane key list (records all three modes)
    }

    def test_no_second_literal_market_definition(self):
        offenders = []
        for path in (REPO / "src").rglob("*.py"):
            rel = str(path.relative_to(REPO))
            if rel in self.ALLOWED:
                continue
            tree = ast.parse(path.read_text(encoding="utf-8"))
            for node in ast.walk(tree):
                if isinstance(node, ast.Constant) and node.value == km.KTC_MARKET_KEY:
                    offenders.append(f"{rel}:{node.lineno}")
        assert offenders == [], offenders
