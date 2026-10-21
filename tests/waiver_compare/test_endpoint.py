"""GET /api/public/waiver-compare — public, read-only, isolated."""

from __future__ import annotations

import copy
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

import server
from src.api import league_registry
from src.waiver_compare.service import WaiverCompareService
from tests.waiver_compare.test_service import CONTRACT, NFL, ROSTERS, USERS


@pytest.fixture
def client(monkeypatch):
    svc = WaiverCompareService(
        fetch_rosters=lambda _lid: ("ok", ROSTERS),
        fetch_users=lambda _lid: ("ok", USERS),
        fetch_players=lambda: NFL,
    )
    monkeypatch.setattr(server, "_waiver_compare_service", svc)
    monkeypatch.setattr(server, "latest_contract_data", CONTRACT)
    # tests/conftest.py points the registry at a missing file; stand in the
    # one league this page serves.
    cfg = SimpleNamespace(
        key="dynasty_main",
        display_name="Risk It To Get The Brisket",
        sleeper_league_id="L1",
        active=True,
    )
    monkeypatch.setattr(
        league_registry, "get_league_by_key", lambda key: cfg if key == "dynasty_main" else None
    )
    # No ``with``: skip the lifespan (it starts scrape threads).
    return TestClient(server.app)


def test_reachable_without_a_session(client):
    res = client.get("/api/public/waiver-compare")
    assert res.status_code == 200, res.text[:300]
    body = res.json()
    assert body["ok"] is True
    assert body["league"]["key"] == "dynasty_main"
    assert res.headers["x-robots-tag"].startswith("noindex")


def test_payload_carries_no_canonical_value(client):
    text = client.get("/api/public/waiver-compare").text
    assert "rankDerivedValue" not in text
    assert "9999" not in text  # the canonical value planted in the fixture


def test_source_settings_are_the_requested_ones(client):
    sources = client.get("/api/public/waiver-compare").json()["values"]["sources"]
    assert sources["ktc"]["sourceKey"] == "ktcCrowdTradesSfTep"
    assert "Crowd+Trades" in sources["ktc"]["settings"]
    assert "TE++" in sources["ktc"]["settings"]
    assert sources["idptc"]["sourceKey"] == "idpTradeCalc"


def test_only_get_is_served(client):
    assert client.post("/api/public/waiver-compare", json={}).status_code in (401, 405)


def test_contract_is_not_mutated(client):
    before = copy.deepcopy(CONTRACT)
    client.get("/api/public/waiver-compare")
    assert CONTRACT == before
