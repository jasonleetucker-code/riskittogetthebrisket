"""Tests for per-source value history persistence + backfill."""
from __future__ import annotations

import json

import pytest

from src.api import source_history


@pytest.fixture()
def path(tmp_path):
    return tmp_path / "source_value_history.jsonl"


def _make_contract(players, *, date="2026-04-23"):
    """Build a minimal contract with ``playersArray`` rows.  Each
    player is given both ``sourceRankMeta.valueContribution`` and a
    ``canonicalSiteValues`` fallback so tests cover both code paths.
    """
    arr = []
    for entry in players:
        row = {
            "displayName": entry["name"],
            "canonicalName": entry["name"],
            "position": entry.get("pos", "WR"),
            "assetClass": entry.get("assetClass", "offense"),
            "rankDerivedValue": entry.get("blended"),
            "canonicalConsensusRank": entry.get("rank"),
        }
        if "sources" in entry:
            row["sourceRankMeta"] = {
                k: {"valueContribution": v} for k, v in entry["sources"].items()
            }
        if "canonicalSites" in entry:
            row["canonicalSiteValues"] = entry["canonicalSites"]
        arr.append(row)
    return {"date": date, "playersArray": arr}


def test_append_then_load(path):
    contract = _make_contract(
        [
            {
                "name": "Malik Nabers",
                "blended": 8154,
                "rank": 17,
                "sources": {"ktcSfTep": 7844, "fp_sf": 8580, "dlf_sf": 9720},
            },
        ],
        date="2026-04-23",
    )
    assert source_history.append_snapshot(contract, date="2026-04-23", path=path) is True

    hist = source_history.load_player_history("Malik Nabers", path=path)
    assert hist["dates"] == ["2026-04-23"]
    assert hist["blended"][0]["value"] == 8154
    assert hist["blended"][0]["rank"] == 17
    assert hist["blended"][0]["derived"] is False
    assert hist["sources"]["ktcSfTep"][0]["value"] == 7844
    assert hist["sources"]["fp_sf"][0]["value"] == 8580


def test_dedupe_same_date(path):
    # Two writes on the same date — the second wins.
    source_history.append_snapshot(
        _make_contract([{"name": "A", "blended": 1000, "sources": {"ktcSfTep": 900}}], date="2026-04-23"),
        path=path,
    )
    source_history.append_snapshot(
        _make_contract([{"name": "A", "blended": 1200, "sources": {"ktcSfTep": 1100}}], date="2026-04-23"),
        path=path,
    )
    hist = source_history.load_player_history("A", path=path)
    assert len(hist["blended"]) == 1
    assert hist["blended"][0]["value"] == 1200
    assert hist["sources"]["ktcSfTep"][0]["value"] == 1100


def test_multiple_dates_sorted(path):
    # NOTE: ``append_snapshot`` uses ``_today_utc()`` when no ``date=``
    # kwarg is passed (it never reads ``contract['date']`` — server.py
    # relies on the wall clock).  Tests must pass ``date=`` explicitly
    # to simulate historical writes.
    source_history.append_snapshot(
        _make_contract([{"name": "A", "blended": 1000, "sources": {"ktcSfTep": 900}}]),
        date="2026-04-22",
        path=path,
    )
    source_history.append_snapshot(
        _make_contract([{"name": "A", "blended": 1050, "sources": {"ktcSfTep": 950}}]),
        date="2026-04-23",
        path=path,
    )
    source_history.append_snapshot(
        _make_contract([{"name": "A", "blended": 1100, "sources": {"ktcSfTep": 1000}}]),
        date="2026-04-24",
        path=path,
    )
    hist = source_history.load_player_history("A", path=path)
    assert hist["dates"] == ["2026-04-22", "2026-04-23", "2026-04-24"]
    assert [e["value"] for e in hist["blended"]] == [1000, 1050, 1100]


def test_retention_trims_to_max_snapshots(path):
    # Simulate 200 DISTINCT dates, retention = 180.  Use a deterministic
    # iteration that avoids the Jan/Feb modulo collision an earlier
    # version of this test had.
    from datetime import date as _date, timedelta
    base = _date(2026, 1, 1)
    for i in range(200):
        d = (base + timedelta(days=i)).isoformat()
        source_history.append_snapshot(
            _make_contract([{"name": "A", "blended": 1000 + i, "sources": {"ktcSfTep": 900 + i}}]),
            date=d,
            path=path,
            max_snapshots=180,
        )
    with path.open("r", encoding="utf-8") as f:
        lines = [json.loads(l) for l in f if l.strip()]
    assert len(lines) == 180


def test_case_insensitive_name_lookup(path):
    source_history.append_snapshot(
        _make_contract([{"name": "Ja'Marr Chase", "blended": 9999, "sources": {"ktcSfTep": 9900}}], date="2026-04-23"),
        path=path,
    )
    hist = source_history.load_player_history("ja'marr chase", path=path)
    assert hist["blended"][0]["value"] == 9999
    assert hist["sources"]["ktcSfTep"][0]["value"] == 9900


def test_derived_blend_from_median_when_blended_missing(path):
    # No ``rankDerivedValue`` on the row — loader should synthesize a
    # blended entry from the per-source median.
    contract = _make_contract(
        [{"name": "X", "sources": {"ktcSfTep": 7000, "fp_sf": 7500, "dlf_sf": 8000}}],
        date="2026-04-23",
    )
    # Strip the blended stamp.
    for row in contract["playersArray"]:
        row.pop("rankDerivedValue", None)
    source_history.append_snapshot(contract, path=path)
    hist = source_history.load_player_history("X", path=path)
    assert hist["blended"][0]["derived"] is True
    # Median of 7000/7500/8000 is 7500.
    assert hist["blended"][0]["value"] == 7500


def test_canonical_sites_fallback(path):
    # Row has no sourceRankMeta, only canonicalSiteValues — the
    # legacy export shape.
    contract = _make_contract(
        [{"name": "L", "canonicalSites": {"ktcSfTep": 8100, "fp_sf": 8400}}],
        date="2026-04-23",
    )
    source_history.append_snapshot(contract, path=path)
    hist = source_history.load_player_history("L", path=path)
    assert hist["sources"]["ktcSfTep"][0]["value"] == 8100
    assert hist["sources"]["fp_sf"][0]["value"] == 8400


def test_asset_class_disambiguation(path):
    # Two players with the same name, different asset classes — the
    # composite key prevents collision.  ``asset_class`` param picks
    # the one the caller wants.
    contract = _make_contract(
        [
            {
                "name": "James Williams",
                "blended": 5000,
                "assetClass": "offense",
                "sources": {"ktcSfTep": 5200},
            },
            {
                "name": "James Williams",
                "blended": 3000,
                "assetClass": "idp",
                "sources": {"ktcSfTep": 3100},
            },
        ],
        date="2026-04-23",
    )
    source_history.append_snapshot(contract, path=path)
    off = source_history.load_player_history("James Williams", asset_class="offense", path=path)
    idp = source_history.load_player_history("James Williams", asset_class="idp", path=path)
    assert off["blended"][0]["value"] == 5000
    assert idp["blended"][0]["value"] == 3000


def test_missing_player_returns_empty(path):
    source_history.append_snapshot(
        _make_contract([{"name": "A", "blended": 1000, "sources": {"ktcSfTep": 900}}]),
        path=path,
    )
    hist = source_history.load_player_history("Unknown", path=path)
    assert hist["dates"] == []
    assert hist["blended"] == []
    assert hist["sources"] == {}


def test_backfill_from_exports_merges_with_existing(tmp_path, path):
    # Seed an existing snapshot for 2026-04-23 via the live path.
    source_history.append_snapshot(
        _make_contract([{"name": "A", "blended": 9999, "sources": {"ktcSfTep": 9000}}], date="2026-04-23"),
        date="2026-04-23",
        path=path,
    )
    # Now point backfill at a historical export dated earlier.
    export = tmp_path / "dynasty_data_2026-04-20.json"
    export.write_text(json.dumps({
        "date": "2026-04-20",
        "players": {"A": {"ktcSfTep": 8000, "dlfSf": 8500, "_canonicalSiteValues": {"ktcSfTep": 8000, "dlfSf": 8500}}},
    }))

    written = source_history.backfill_from_exports([export], path=path)
    assert written == 1
    hist = source_history.load_player_history("A", path=path)
    dates = [b["date"] for b in hist["blended"]]
    assert "2026-04-20" in dates
    # Newer snapshot preserved verbatim.
    latest = [b for b in hist["blended"] if b["date"] == "2026-04-23"][0]
    assert latest["value"] == 9999


def test_append_returns_false_for_empty_contract(path):
    assert source_history.append_snapshot({"date": "2026-04-23", "playersArray": []}, path=path) is False
    assert not path.exists() or path.read_text() == ""
