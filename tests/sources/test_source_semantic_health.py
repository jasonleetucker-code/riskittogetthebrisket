from __future__ import annotations

import json
from pathlib import Path

from scripts.check_source_health import (
    measure_ktc_semantic_integrity,
    measure_registered_source_integrity,
)


def _write_provenance(root: Path, *, fmt=None, captures=None):
    path = root / "data" / "scrape_state" / "ktc_value_sources.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "provider": "KeepTradeCut",
        "canonicalMarketSource": "crowd_trades",
        "operatorFormat": fmt
        or {
            "gameType": "DYNASTY",
            "superflex": True,
            "tePremium": "TE++",
            "tePremiumLevel": 2,
        },
        "captures": captures
        or {
            "crowd": {
                "selectedLabel": "Crowdsourced Values",
                "selectedControlValue": "1",
                "superflex": True,
                "tePremium": "TE++",
                "tePremiumLevel": 2,
                "rowCount": 500,
                "pricedCount": 500,
                "contentHash": "crowd-hash",
            },
            "trades": {
                "selectedLabel": "Tradesourced Values",
                "selectedControlValue": "3",
                "superflex": True,
                "tePremium": "TE++",
                "tePremiumLevel": 2,
                "rowCount": 450,
                "pricedCount": 420,
                "contentHash": "trades-hash",
            },
            "crowd_trades": {
                "selectedLabel": "Crowd + Trade Values",
                "selectedControlValue": "2",
                "superflex": True,
                "tePremium": "TE++",
                "tePremiumLevel": 2,
                "rowCount": 500,
                "pricedCount": 500,
                "contentHash": "combined-hash",
            },
        },
    }
    path.write_text(json.dumps(payload), encoding="utf-8")


def test_ktc_semantic_health_distinguishes_missing_provenance_from_healthy(tmp_path):
    missing = measure_ktc_semantic_integrity(tmp_path)
    assert missing["measurable"] is False
    assert missing["state"] == "UNAVAILABLE"

    _write_provenance(tmp_path)
    healthy = measure_ktc_semantic_integrity(tmp_path)
    assert healthy["measurable"] is True
    assert healthy["state"] == "HEALTHY"
    assert healthy["errors"] == []
    assert healthy["coverageErrors"] == []
    assert healthy["parserErrors"] == []


def test_successful_fetch_of_wrong_ktc_configuration_fails_semantic_health(tmp_path):
    _write_provenance(
        tmp_path,
        fmt={
            "gameType": "DYNASTY",
            "superflex": False,
            "tePremium": "TE+",
            "tePremiumLevel": 1,
        },
    )
    report = measure_ktc_semantic_integrity(tmp_path)
    assert report["state"] == "SCHEMA_CHANGED"
    assert report["category"] == "semantic_configuration"
    assert any("superflex" in msg.lower() for msg in report["errors"])
    assert any("tePremium" in msg for msg in report["errors"])


def test_partial_board_is_coverage_degraded_not_fetch_stale(tmp_path):
    captures = {
        "crowd": {
            "selectedLabel": "Crowdsourced",
            "selectedControlValue": "1",
            "superflex": True,
            "tePremium": "TE++",
            "tePremiumLevel": 2,
            "rowCount": 500,
            "pricedCount": 500,
            "contentHash": "crowd",
        },
        "trades": {
            "selectedLabel": "Tradesourced",
            "selectedControlValue": "3",
            "superflex": True,
            "tePremium": "TE++",
            "tePremiumLevel": 2,
            "rowCount": 80,
            "pricedCount": 70,
            "contentHash": "trades",
        },
        "crowd_trades": {
            "selectedLabel": "Crowd+Trades",
            "selectedControlValue": "2",
            "superflex": True,
            "tePremium": "TE++",
            "tePremiumLevel": 2,
            "rowCount": 500,
            "pricedCount": 500,
            "contentHash": "combined",
        },
    }
    _write_provenance(tmp_path, captures=captures)
    report = measure_ktc_semantic_integrity(tmp_path)
    assert report["state"] == "PARTIAL"
    assert report["category"] == "coverage_degraded"
    assert report["coverageErrors"]


def test_selector_label_change_without_board_change_is_parser_drift(tmp_path):
    captures = {
        key: {
            "selectedLabel": label,
            "selectedControlValue": {
                "crowd": "1",
                "trades": "3",
                "crowd_trades": "2",
            }[key],
            "superflex": True,
            "tePremium": "TE++",
            "tePremiumLevel": 2,
            "rowCount": 500,
            "pricedCount": 500,
            "contentHash": "same-board",
        }
        for key, label in {
            "crowd": "Crowdsourced",
            "trades": "Tradesourced",
            "crowd_trades": "Crowd+Trades",
        }.items()
    }
    _write_provenance(tmp_path, captures=captures)
    report = measure_ktc_semantic_integrity(tmp_path)
    assert report["state"] == "SCHEMA_CHANGED"
    assert report["category"] == "parser_drift"
    assert report["parserErrors"]


def test_registered_source_integrity_distinguishes_schema_and_coverage(tmp_path):
    good = tmp_path / "good.csv"
    good.write_text(
        "name,rank,value\nElite,1,9000\nMiddle,50,4000\nDeep,100,1000\n",
        encoding="utf-8",
    )
    bad = tmp_path / "bad.csv"
    bad.write_text("name,wrong\nOnly,1\n", encoding="utf-8")

    sources = [
        {
            "key": "goodRank",
            "scope": "overall_offense",
            "correlation_group": "good",
            "game_type": "DYNASTY",
            "game_type_evidence": "fixture dynasty source",
            "is_tep_premium": False,
        },
        {
            "key": "badRank",
            "scope": "overall_offense",
            "correlation_group": "bad",
            "game_type": "DYNASTY",
            "game_type_evidence": "fixture dynasty source",
            "is_tep_premium": False,
        },
    ]
    paths = {
        "goodRank": {"path": "good.csv", "signal": "rank"},
        "badRank": {"path": "bad.csv", "signal": "rank"},
    }
    report = measure_registered_source_integrity(
        tmp_path,
        sources=sources,
        source_paths=paths,
        floors={"goodRank": 2, "badRank": 2},
    )

    assert report["goodRank"]["state"] == "HEALTHY"
    assert report["goodRank"]["rowCount"] == 3
    assert report["goodRank"]["numericSignalRows"] == 3
    assert report["goodRank"]["contentHash"]
    assert report["goodRank"]["sampleNames"] == ["Elite", "Middle", "Deep"]

    assert report["badRank"]["state"] == "DEGRADED"
    assert any("rank column" in msg for msg in report["badRank"]["errors"])
    assert any("below floor" in msg for msg in report["badRank"]["errors"])


def test_registered_source_integrity_catches_wrong_game_type_and_missing_file(tmp_path):
    report = measure_registered_source_integrity(
        tmp_path,
        sources=[
            {
                "key": "wrong",
                "scope": "overall_offense",
                "game_type": "REDRAFT",
                "game_type_evidence": "fixture intentionally wrong",
            }
        ],
        source_paths={"wrong": {"path": "missing.csv", "signal": "value"}},
        floors={"wrong": 10},
    )
    item = report["wrong"]
    assert item["state"] == "DEGRADED"
    assert "source CSV missing" in item["errors"]
    assert any("REDRAFT" in msg for msg in item["errors"])
