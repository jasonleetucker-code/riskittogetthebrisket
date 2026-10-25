from __future__ import annotations

import json
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

import server


def _mcp_client(monkeypatch):
    monkeypatch.setenv("CHASE_UPSIDE_MCP_API_TOKEN", "t" * 48)
    monkeypatch.setenv("CHASE_UPSIDE_MCP_OWNER_USER_ID", "site-owner-1")
    return TestClient(server.app)


def _headers():
    return {
        "Authorization": f"Bearer {'t' * 48}",
        "X-Chase-Upside-Owner-Id": "site-owner-1",
    }


def test_mcp_requires_service_token_and_owner(monkeypatch):
    monkeypatch.delenv("CHASE_UPSIDE_MCP_API_TOKEN", raising=False)
    monkeypatch.setenv("CHASE_UPSIDE_MCP_OWNER_USER_ID", "site-owner-1")
    with TestClient(server.app) as client:
        assert client.post("/api/chase-upside/mcp", json={}).status_code == 401

    monkeypatch.setenv("CHASE_UPSIDE_MCP_API_TOKEN", "t" * 48)
    with TestClient(server.app) as client:
        response = client.post(
            "/api/chase-upside/mcp",
            headers={"Authorization": f"Bearer {'t' * 48}", "X-Chase-Upside-Owner-Id": "other"},
            json={"jsonrpc": "2.0", "id": 1, "method": "tools/list"},
        )
    assert response.status_code == 403


def test_mcp_discovery_and_tool_list_are_read_only(monkeypatch):
    with _mcp_client(monkeypatch) as client:
        discovery = client.post(
            "/api/chase-upside/mcp",
            headers=_headers(),
            json={"jsonrpc": "2.0", "id": 1, "method": "server/discover"},
        )
        tools = client.post(
            "/api/chase-upside/mcp",
            headers=_headers(),
            json={"jsonrpc": "2.0", "id": 2, "method": "tools/list"},
        )

    assert discovery.status_code == 200
    assert discovery.json()["result"]["supportedVersions"] == ["2026-07-28"]
    listed = tools.json()["result"]["tools"]
    assert {tool["name"] for tool in listed} == {
        "get_player_rankings",
        "resolve_player_identity",
        "get_league_context",
        "get_team_roster",
        "analyze_trade",
    }
    assert all("write" not in tool["name"] for tool in listed)


def test_rankings_tool_returns_canonical_rows_and_provenance(monkeypatch):
    league = SimpleNamespace(key="dynasty_main")
    with _mcp_client(monkeypatch) as client:
        monkeypatch.setattr(server._league_registry, "get_league_by_key", lambda _key: league)
        monkeypatch.setattr(server, "_scoring_identity_error", lambda _contract, _league: None)
        monkeypatch.setattr(
            server,
            "latest_contract_data",
            {
                "generatedAt": "2026-10-25T12:00:00Z",
                "meta": {"leagueKey": "dynasty_main"},
                "dataFreshness": {
                    "sourceTimestamps": {"ktcSfTep": {"staleness": "fresh", "ageHours": 2.0}}
                },
                "methodology": {"sources": [{"key": "ktcSfTep"}]},
                "playersArray": [
                    {
                        "playerId": "123",
                        "name": "Player One",
                        "position": "QB",
                        "rankDerivedValue": 8000,
                    },
                    {
                        "playerId": "456",
                        "name": "Player Two",
                        "position": "RB",
                        "rankDerivedValue": 7000,
                    },
                ],
            },
        )
        response = client.post(
            "/api/chase-upside/mcp",
            headers=_headers(),
            json={
                "jsonrpc": "2.0",
                "id": 3,
                "method": "tools/call",
                "params": {
                    "name": "get_player_rankings",
                    "arguments": {"leagueKey": "dynasty_main", "position": "QB"},
                },
            },
        )
    result = response.json()["result"]["structuredContent"]
    assert result["dataAsOf"] == "2026-10-25T12:00:00Z"
    assert result["players"] == [
        {
            "playerId": "123",
            "name": "Player One",
            "position": "QB",
            "rankDerivedValue": 8000,
            "confidence": None,
        }
    ]
    assert result["rankingSources"] == ["ktcSfTep"]
    assert result["sourceFreshness"] == [{"source": "ktcSfTep", "status": "fresh", "ageHours": 2.0}]


def test_rankings_tool_reads_the_loaded_backend_contract(monkeypatch):
    league = SimpleNamespace(key="dynasty_main")
    with _mcp_client(monkeypatch) as client:
        contract = server.latest_contract_data
        if not isinstance(contract, dict) or not contract.get("playersArray"):
            pytest.skip("the local FastAPI startup did not load a rankings contract")
        expected_player_id = contract["playersArray"][0].get("playerId")
        monkeypatch.setattr(server._league_registry, "get_league_by_key", lambda _key: league)
        monkeypatch.setattr(server, "_scoring_identity_error", lambda _contract, _league: None)
        response = client.post(
            "/api/chase-upside/mcp",
            headers=_headers(),
            json={
                "jsonrpc": "2.0",
                "id": 33,
                "method": "tools/call",
                "params": {
                    "name": "get_player_rankings",
                    "arguments": {"leagueKey": "dynasty_main", "limit": 1},
                },
            },
        )
    assert response.status_code == 200
    result = response.json()["result"]["structuredContent"]
    assert result["status"] in {"ok", "partial"}
    if expected_player_id is not None:
        assert result["players"][0]["playerId"] == expected_player_id
    else:
        assert any(item.get("reason") == "player_id_missing" for item in result["missingData"])


def test_tool_arguments_are_allowlisted_and_size_bounded(monkeypatch):
    with _mcp_client(monkeypatch) as client:
        invalid = client.post(
            "/api/chase-upside/mcp",
            headers=_headers(),
            json={
                "jsonrpc": "2.0",
                "id": 4,
                "method": "tools/call",
                "params": {"name": "get_player_rankings", "arguments": {"leak": "private"}},
            },
        )
        oversized = client.post(
            "/api/chase-upside/mcp",
            headers=_headers(),
            content=json.dumps({"payload": "x" * (64 * 1024)}),
        )
    assert invalid.json()["result"]["isError"] is True
    assert "private" not in invalid.text
    assert oversized.status_code == 413
