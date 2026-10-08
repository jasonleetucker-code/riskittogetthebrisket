"""``GET /api/players/{player}/value-movement`` — IC-7 route.

Private (session-gated like ``value-explain``), 503 with no board, 404 for an
unknown player, and an answer that carries source ROLES from their canonical
owners, the live board beside the ledger generations, and current-only context
labelled as current.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

import server
from src.api import value_movement
from src.history import store

PID = "4034"


def _row() -> dict:
    return {
        "playerId": PID,
        "displayName": "Test Player",
        "canonicalName": "Test Player",
        "position": "RB",
        "assetClass": "offense",
        "rankDerivedValue": 6400,
        "canonicalConsensusRank": 31,
        "rankChange": 9,
        "anomalyFlags": [],
        "canonicalSiteValues": {
            "ktcCrowdSfTep": 6500,
            "dlfSf": 6200,
            "fantasyCalc": 0,
            "yahooBoone": 5900,
            "fantasyNavigatorSf": 6000,
        },
        "sourceRankMeta": {
            "dlfSf": {"contributedToBlend": True},
            "yahooBoone": {"contributedToBlend": False},
        },
    }


def _contract() -> dict:
    return {
        "date": "2026-09-02",
        "scrapeTimestamp": "2026-09-02T11:00:00+00:00",
        "playersArray": [_row()],
    }


def _obs(date: str, *, lane: str, source_key: str = "", value: float, rank: int | None = None):
    return {
        "asset_key": f"player:{PID}",
        "asset_class": "offense",
        "lane": lane,
        "source_key": source_key,
        "observed_date": date,
        "observed_at": f"{date}T11:00:00+00:00",
        "observed_at_zone": "utc",
        "value": value,
        "rank": rank,
        "origin": "live:server",
        "pipeline_version": "v2+aaaa1111" if lane == store.LANE_CANONICAL else None,
    }


@pytest.fixture()
def ledger(tmp_path: Path, monkeypatch) -> Path:
    store._reset_setup_cache_for_tests()
    path = tmp_path / "temporal_ledger.sqlite"
    monkeypatch.setattr(store, "DB_PATH", path)
    result = store.write_observations(
        [
            _obs("2026-09-01", lane=store.LANE_CANONICAL, value=6000, rank=40),
            _obs("2026-09-02", lane=store.LANE_CANONICAL, value=6400, rank=31),
            _obs("2026-09-01", lane=store.LANE_SOURCE, source_key="ktcCrowdSfTep", value=6100),
            _obs("2026-09-02", lane=store.LANE_SOURCE, source_key="ktcCrowdSfTep", value=6500),
            _obs(
                "2026-09-02",
                lane=store.LANE_SOURCE,
                source_key="ktcCrowdTradesSfTep",
                value=6300,
            ),
        ],
        path=path,
    )
    assert not result["rejected"]
    return path


@pytest.fixture()
def client(monkeypatch):
    monkeypatch.setattr(server, "latest_contract_data", _contract())
    return TestClient(server.app)


def test_requires_a_session(client):
    res = client.get(f"/api/players/{PID}/value-movement")
    assert res.status_code == 401


def test_movement_payload(client, ledger, monkeypatch):
    monkeypatch.setattr(server, "_is_authenticated", lambda r: True)
    res = client.get(f"/api/players/{PID}/value-movement")
    assert res.status_code == 200
    assert "private" in res.headers.get("cache-control", "")
    body = res.json()
    assert body["schema"] == "value-movement/v1"
    assert body["status"] == "ok"
    assert body["additive"] is False
    assert body["change"]["value"] == 400
    assert body["currentGenerationIsLiveBoard"] is True
    assert body["currentGenerationIsLiveBoardBasis"] == "instant"
    assert body["currentSelection"] == "known_before_served_instant"
    assert body["liveBoard"] == {
        "boardDate": "2026-09-02",
        "scrapeTimestamp": "2026-09-02T11:00:00+00:00",
        "value": 6400.0,
        "rank": 31,
        "rankChange": 9,
    }
    roles = {s["source"]: s["role"] for s in body["sources"]}
    assert roles["ktcCrowdSfTep"] == value_movement.ROLE_MODEL_INPUT
    assert roles["ktcCrowdTradesSfTep"] == value_movement.ROLE_BENCHMARK
    ctx = body["currentContext"]
    assert ctx["scope"] == "current_board_only"
    # A zero site value is missing, not a source that voted today; each
    # unrecorded source carries its role TODAY, never a blanket "priced by".
    assert ctx["sourcesNotRecordedInLedger"] == [
        {"source": "dlfSf", "role": value_movement.TODAY_VOTED},
        {"source": "fantasyNavigatorSf", "role": value_movement.TODAY_VOTE_UNPUBLISHED},
        {"source": "yahooBoone", "role": value_movement.TODAY_NOT_VOTING},
    ]


def test_by_display_name(client, ledger, monkeypatch):
    monkeypatch.setattr(server, "_is_authenticated", lambda r: True)
    res = client.get("/api/players/Test%20Player/value-movement")
    assert res.status_code == 200
    assert res.json()["playerId"] == PID


def test_unknown_player_is_404(client, ledger, monkeypatch):
    monkeypatch.setattr(server, "_is_authenticated", lambda r: True)
    res = client.get("/api/players/nobody/value-movement")
    assert res.status_code == 404
    assert res.json()["error"] == "player_not_found"


def test_no_board_is_503(monkeypatch):
    monkeypatch.setattr(server, "latest_contract_data", {})
    monkeypatch.setattr(server, "_is_authenticated", lambda r: True)
    res = TestClient(server.app).get(f"/api/players/{PID}/value-movement")
    assert res.status_code == 503
    assert res.json()["error"] == "data_not_ready"


def test_held_signals_idp_board_is_labelled_held():
    assert value_movement.source_role("signalsIdpLb") == value_movement.ROLE_HELD
    assert value_movement.source_role("idpTradeCalc") == value_movement.ROLE_MODEL_INPUT


def test_unkeyable_row_reports_unkeyed_not_an_empty_movement():
    row = {"displayName": "", "assetClass": "", "position": None}
    got = value_movement.player_value_movement({"date": "2026-09-02"}, row)
    assert got["status"] == "unkeyed"
    assert got["additive"] is False


def test_later_unrecorded_scrape_reads_behind_on_the_instant(ledger, monkeypatch):
    """Same date, but the served scrape is not in the ledger yet: compared on
    the instant, not the date (review F2)."""
    contract = {**_contract(), "scrapeTimestamp": "2026-09-02T21:00:00+00:00"}
    got = value_movement.player_value_movement(contract, _row())
    assert got["currentGenerationIsLiveBoard"] is False
    assert got["currentGenerationIsLiveBoardBasis"] == "instant"
