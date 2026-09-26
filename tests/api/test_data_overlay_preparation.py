"""Regression: cached overlay bytes must not repeat canonical lineup preparation."""

from contextlib import asynccontextmanager
from copy import deepcopy

import pytest
from fastapi.testclient import TestClient

import server
from src.api import league_registry
from tests.api.test_league_routing import (
    _install_contract_with_profile,
    shared_scoring_registry,  # noqa: F401
)


@pytest.mark.usefixtures("shared_scoring_registry")
def test_overlay_hit_and_304_share_lineup_preparation(monkeypatch):
    @asynccontextmanager
    async def isolated_lifespan(app):
        yield

    # Exercise the real handler/middleware without starting unrelated collectors.
    monkeypatch.setattr(server.app.router, "lifespan_context", isolated_lifespan)
    overlay = {
        "teams": [{"ownerId": "oA", "name": "Team A", "players": ["p1"]}],
        "leagueId": "L-MAIN",
        "overlayFetchedAt": "2026-09-26T00:00:00Z",
    }
    monkeypatch.setattr(server._sleeper_overlay, "fetch_sleeper_overlay", lambda **kw: overlay)
    calls = []
    stamp = server._stamp_optimal_lineups_owner

    def counted(*args, **kwargs):
        calls.append(1)
        return stamp(*args, **kwargs)

    with TestClient(server.app) as client:
        _install_contract_with_profile(monkeypatch, "main", "superflex_tep15_ppr1")
        server.latest_contract_data["playersArray"] = [
            {"canonicalName": "p1", "displayName": "p1", "rankDerivedValue": 10}
        ]
        server.latest_contract_data["sleeper"].update(
            {"rosterPositions": ["QB"], "positions": {"p1": "QB"}}
        )
        monkeypatch.setattr(server, "latest_data_etag", "base-etag-repro")
        monkeypatch.setattr(server, "_OVERLAY_RESPONSE_CACHE", {})
        monkeypatch.setattr(server, "_OVERLAY_ENCODE_LOCKS", {})
        monkeypatch.setattr(server, "_stamp_optimal_lineups_owner", counted)
        first = client.get("/api/data?leagueKey=main")
        second = client.get("/api/data?leagueKey=main")
        third = client.get(
            "/api/data?leagueKey=main", headers={"If-None-Match": first.headers["etag"]}
        )
    assert [first.status_code, second.status_code, third.status_code] == [200, 200, 304]
    assert first.content == second.content
    assert first.headers["etag"] == second.headers["etag"] == third.headers["etag"]
    assert third.content == b""
    lineup = first.json()["sleeper"]["teams"][0]["optimalLineup"]
    assert lineup["available"] is True
    assert lineup["starters"] == ["p1"]
    assert "optimalLineup" not in overlay["teams"][0]
    assert len(calls) == 1, f"Observed {len(calls)} lineup preparations across 200/200/304"


@pytest.mark.usefixtures("shared_scoring_registry")
@pytest.mark.parametrize("mutation", ["slots", "eligibility"])
def test_same_stamp_roster_rules_change_served_lineup(monkeypatch, mutation):
    @asynccontextmanager
    async def isolated_lifespan(app):
        yield

    monkeypatch.setattr(server.app.router, "lifespan_context", isolated_lifespan)
    overlay = {
        "teams": [{"ownerId": "oA", "players": ["rb", "wr", "unknown"]}],
        "overlayFetchedAt": "unchanged-observation",
    }
    monkeypatch.setattr(server._sleeper_overlay, "fetch_sleeper_overlay", lambda **kw: overlay)
    settings = {"starters": {"FLEX": 1}, "flexEligible": ["RB", "WR"]}
    monkeypatch.setattr(league_registry, "get_league_roster_settings", lambda key: settings)
    with TestClient(server.app) as client:
        _install_contract_with_profile(monkeypatch, "main", "superflex_tep15_ppr1")
        server.latest_contract_data["playersArray"] = [
            {"displayName": "rb", "rankDerivedValue": 10},
            {"displayName": "wr", "rankDerivedValue": 0},
        ]
        server.latest_contract_data["sleeper"]["positions"] = {
            "rb": "RB",
            "wr": "WR",
            "unknown": "RB",
        }
        monkeypatch.setattr(server, "latest_data_etag", "fixed-base-generation")
        monkeypatch.setattr(server, "_OVERLAY_RESPONSE_CACHE", {})
        monkeypatch.setattr(server, "_OVERLAY_ENCODE_LOCKS", {})
        first = client.get("/api/data?leagueKey=main")
        assert first.json()["sleeper"]["teams"][0]["optimalLineup"]["starters"] == ["rb"]
        if mutation == "slots":
            settings["starters"] = {"WR": 1}
        else:
            settings["flexEligible"] = ["WR"]
        second = client.get("/api/data?leagueKey=main")
        server._OVERLAY_RESPONSE_CACHE.clear()
        control = client.get("/api/data?leagueKey=main")
        fresh = control.json()["sleeper"]["teams"][0]["optimalLineup"]
        assert fresh["starters"] == ["wr"]
        assert fresh["unpriced"] == ["unknown"]
    assert second.status_code == 200
    lineup = second.json()["sleeper"]["teams"][0]["optimalLineup"]
    assert lineup["starters"] == ["wr"]
    assert lineup["unpriced"] == ["unknown"]
    assert first.headers["etag"] != second.headers["etag"]


@pytest.fixture
def overlay_case(request, monkeypatch):
    request.getfixturevalue("shared_scoring_registry")

    @asynccontextmanager
    async def isolated(app):
        yield

    monkeypatch.setattr(server.app.router, "lifespan_context", isolated)
    _install_contract_with_profile(monkeypatch, "main", "superflex_tep15_ppr1")
    contract = server.latest_contract_data
    contract["playersArray"] = [
        {"displayName": "rb", "rankDerivedValue": 10},
        {"displayName": "wr", "rankDerivedValue": 0},
    ]
    contract["sleeper"]["positions"] = {"rb": "RB", "wr": "WR"}
    settings = {"starters": {"FLEX": 1}, "flexEligible": ["RB", "WR"]}
    monkeypatch.setattr(league_registry, "get_league_roster_settings", lambda key: settings)
    overlay = {
        "teams": [{"ownerId": "fixture", "players": ["rb", "wr"]}],
        "overlayFetchedAt": "fixed-observation",
    }
    monkeypatch.setattr(server._sleeper_overlay, "fetch_sleeper_overlay", lambda **kw: overlay)
    monkeypatch.setattr(server, "latest_data_etag", "canonical-A")
    monkeypatch.setattr(server, "_OVERLAY_RESPONSE_CACHE", {})
    monkeypatch.setattr(server, "_OVERLAY_ENCODE_LOCKS", {})
    return contract, settings, overlay


def starters(response):
    assert response.status_code == 200
    return response.json()["sleeper"]["teams"][0]["optimalLineup"]["starters"]


def test_missing_canonical_identity_does_not_cache_reduced_view(overlay_case, monkeypatch):
    contract, _, _ = overlay_case
    view = deepcopy(contract)
    monkeypatch.setattr(server, "latest_array_data", view)
    monkeypatch.setattr(server, "latest_array_data_bytes", b"fixture")
    monkeypatch.setattr(server, "latest_array_data_etag", "view-A")
    monkeypatch.setattr(server, "latest_data_etag", None)
    with TestClient(server.app) as client:
        assert starters(client.get("/api/data?leagueKey=main&view=array")) == ["rb"]
        changed = deepcopy(contract)
        changed["playersArray"][0]["rankDerivedValue"] = None
        monkeypatch.setattr(server, "latest_contract_data", changed)
        assert starters(client.get("/api/data?leagueKey=main&view=array")) == ["wr"]
    assert server._OVERLAY_RESPONSE_CACHE == {}


def test_registry_change_after_capture_uses_captured_facts(overlay_case, monkeypatch):
    _, settings, _ = overlay_case
    real = server._serialize_overlaid_response

    async def change_then_encode(*args, **kwargs):
        settings["flexEligible"][:] = ["WR"]
        return await real(*args, **kwargs)

    monkeypatch.setattr(server, "_serialize_overlaid_response", change_then_encode)
    with TestClient(server.app) as client:
        assert starters(client.get("/api/data?leagueKey=main")) == ["rb"]
        assert starters(client.get("/api/data?leagueKey=main")) == ["wr"]


def test_canonical_replacement_during_overlay_keeps_captured_rows(overlay_case, monkeypatch):
    contract, _, overlay = overlay_case
    changed = deepcopy(contract)
    changed["playersArray"][0]["rankDerivedValue"] = None

    def replace(**kwargs):
        server.latest_contract_data = changed
        server.latest_data_etag = "canonical-B"
        return overlay

    monkeypatch.setattr(server._sleeper_overlay, "fetch_sleeper_overlay", replace)
    with TestClient(server.app) as client:
        first = client.get("/api/data?leagueKey=main")
        assert starters(first) == ["rb"]
        assert first.json()["playersArray"][0]["rankDerivedValue"] == 10
        assert starters(client.get("/api/data?leagueKey=main")) == ["wr"]


def test_cross_league_fallback_uses_requested_registry(overlay_case, monkeypatch):
    monkeypatch.setattr(
        league_registry,
        "get_league_roster_settings",
        lambda key: {"starters": {"WR" if key == "twin" else "RB": 1}},
    )
    with TestClient(server.app) as client:
        response = client.get("/api/data?leagueKey=twin")
        assert starters(response) == ["wr"]
        assert response.json()["meta"]["leagueKey"] == "twin"
        assert client.get("/api/data?leagueKey=stranger").status_code == 503


def test_concurrent_overlay_misses_prepare_once(overlay_case, monkeypatch):
    import asyncio
    import httpx
    import time

    calls = []
    real = server._stamp_optimal_lineups_owner

    def blocked(*args, **kwargs):
        calls.append(1)
        time.sleep(0.03)
        return real(*args, **kwargs)

    monkeypatch.setattr(server, "_stamp_optimal_lineups_owner", blocked)

    async def run():
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=server.app), base_url="http://fixture"
        ) as client:
            return await asyncio.gather(*[client.get("/api/data?leagueKey=main") for _ in range(6)])

    results = asyncio.run(run())
    assert [starters(response) for response in results] == [["rb"]] * 6
    assert len({response.content for response in results}) == 1
    assert len(calls) == 1


def test_unknown_slots_remain_unavailable_and_conditional(overlay_case):
    _, settings, _ = overlay_case
    settings.clear()
    with TestClient(server.app) as client:
        first = client.get("/api/data?leagueKey=main")
        lineup = first.json()["sleeper"]["teams"][0]["optimalLineup"]
        assert lineup == {"available": False, "reason": "no_starter_slots", "slotSource": None}
        second = client.get(
            "/api/data?leagueKey=main", headers={"If-None-Match": first.headers["etag"]}
        )
        assert second.status_code == 304
        assert second.content == b""
