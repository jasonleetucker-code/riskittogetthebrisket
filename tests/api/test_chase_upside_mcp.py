from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient
from jsonschema import Draft202012Validator

import server

MCP_SCHEMA = json.loads(
    (Path(__file__).resolve().parents[1] / "fixtures/mcp/schema-2026-07-28.json").read_text(
        encoding="utf-8"
    )
)


def _validate_mcp_response(definition, response):
    schema = {
        "$schema": MCP_SCHEMA["$schema"],
        "$defs": MCP_SCHEMA["$defs"],
        "$ref": f"#/$defs/{definition}",
    }
    Draft202012Validator.check_schema(schema)
    Draft202012Validator(schema).validate(response)


def _mcp_client(monkeypatch):
    monkeypatch.setenv("CHASE_UPSIDE_MCP_API_TOKEN", "t" * 48)
    monkeypatch.setenv("CHASE_UPSIDE_MCP_OWNER_USER_ID", "site-owner-1")
    return TestClient(server.app)


def _headers(method="tools/list", name=None):
    headers = {
        "Authorization": f"Bearer {'t' * 48}",
        "X-Chase-Upside-Owner-Id": "site-owner-1",
        "MCP-Protocol-Version": "2026-07-28",
        "Mcp-Method": method,
    }
    if name is not None:
        headers["Mcp-Name"] = name
    return headers


def _request(method, request_id, params=None):
    return {
        "jsonrpc": "2.0",
        "id": request_id,
        "method": method,
        "params": {
            **(params or {}),
            "_meta": {
                "io.modelcontextprotocol/protocolVersion": "2026-07-28",
                "io.modelcontextprotocol/clientCapabilities": {},
            },
        },
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
            headers=_headers("server/discover"),
            json=_request("server/discover", 1),
        )
        tools = client.post(
            "/api/chase-upside/mcp",
            headers=_headers("tools/list"),
            json=_request("tools/list", 2),
        )

    assert discovery.status_code == 200
    _validate_mcp_response("DiscoverResultResponse", discovery.json())
    discover_result = discovery.json()["result"]
    assert discover_result["supportedVersions"] == ["2026-07-28"]
    assert discover_result["resultType"] == "complete"
    assert discover_result["ttlMs"] == 0
    assert discover_result["cacheScope"] == "private"
    assert discover_result["_meta"]["io.modelcontextprotocol/serverInfo"] == {
        "name": "Chase Upside MCP",
        "version": "1.1.0",
    }
    _validate_mcp_response("ListToolsResultResponse", tools.json())
    listed = tools.json()["result"]["tools"]
    assert tools.json()["result"]["resultType"] == "complete"
    assert tools.json()["result"]["ttlMs"] == 0
    assert tools.json()["result"]["cacheScope"] == "private"
    assert tools.json()["result"]["_meta"]["io.modelcontextprotocol/serverInfo"]["name"] == (
        "Chase Upside MCP"
    )
    assert {tool["name"] for tool in listed} == {
        "get_player_rankings",
        "resolve_player_identity",
        "get_league_context",
        "get_team_roster",
        "analyze_trade",
        "get_value_history",
    }
    assert all("write" not in tool["name"] for tool in listed)
    assert all(tool["annotations"]["readOnlyHint"] is True for tool in listed)
    assert all(tool["annotations"]["destructiveHint"] is False for tool in listed)


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
                        "displayName": "Player One",
                        "position": "QB",
                        "canonicalConsensusRank": 1,
                        "rankDerivedValue": 8000,
                        "rawSourceValues": {"ktcSfTep": 9999},
                    },
                    {
                        "playerId": "456",
                        "displayName": "Player Two",
                        "position": "RB",
                        "canonicalConsensusRank": 2,
                        "rankDerivedValue": 7000,
                    },
                ],
            },
        )
        response = client.post(
            "/api/chase-upside/mcp",
            headers=_headers("tools/call", "get_player_rankings"),
            json=_request(
                "tools/call",
                3,
                {
                    "name": "get_player_rankings",
                    "arguments": {"leagueKey": "dynasty_main", "position": "QB"},
                },
            ),
        )
    result = response.json()["result"]["structuredContent"]
    _validate_mcp_response("CallToolResultResponse", response.json())
    assert response.json()["result"]["resultType"] == "complete"
    assert response.json()["result"]["_meta"]["io.modelcontextprotocol/serverInfo"]["name"] == (
        "Chase Upside MCP"
    )
    assert result["dataAsOf"] == "2026-10-25T12:00:00Z"
    assert result["players"] == [
        {
            "playerId": "123",
            "assetId": "p:123",
            "displayName": "Player One",
            "position": "QB",
            "canonicalConsensusRank": 1,
            "rankDerivedValue": 8000,
        }
    ]
    assert "rawSourceValues" not in response.text
    assert result["rankingSources"] == ["ktcSfTep"]
    assert result["sourceFreshness"] == [{"source": "ktcSfTep", "status": "fresh", "ageHours": 2.0}]


def test_rankings_tool_reads_the_loaded_backend_contract(monkeypatch):
    league = SimpleNamespace(key="dynasty_main")
    with _mcp_client(monkeypatch) as client:
        contract = server.latest_contract_data
        if not isinstance(contract, dict) or not contract.get("playersArray"):
            pytest.skip("the local FastAPI startup did not load a rankings contract")
        ranked = [r for r in contract["playersArray"] if r.get("canonicalConsensusRank")]
        first = min(ranked, key=lambda r: r["canonicalConsensusRank"])
        expected_player_id = first.get("playerId")
        monkeypatch.setattr(server._league_registry, "get_league_by_key", lambda _key: league)
        monkeypatch.setattr(server, "_scoring_identity_error", lambda _contract, _league: None)
        response = client.post(
            "/api/chase-upside/mcp",
            headers=_headers("tools/call", "get_player_rankings"),
            json=_request(
                "tools/call",
                33,
                {
                    "name": "get_player_rankings",
                    "arguments": {"leagueKey": "dynasty_main", "limit": 1},
                },
            ),
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
            headers=_headers("tools/call", "get_player_rankings"),
            json=_request(
                "tools/call", 4, {"name": "get_player_rankings", "arguments": {"leak": "private"}}
            ),
        )
        oversized = client.post(
            "/api/chase-upside/mcp",
            headers=_headers("tools/list"),
            content=json.dumps(_request("tools/list", 5, {"payload": "x" * (64 * 1024)})),
        )
    assert invalid.json()["result"]["isError"] is True
    assert "private" not in invalid.text
    assert oversized.status_code == 413


def test_protocol_rejects_header_mismatch_and_explicit_null_offset(monkeypatch):
    with _mcp_client(monkeypatch) as client:
        mismatch = client.post(
            "/api/chase-upside/mcp",
            headers=_headers("tools/list"),
            json=_request("server/discover", 6),
        )
        null_offset = client.post(
            "/api/chase-upside/mcp",
            headers=_headers("tools/call", "get_player_rankings"),
            json=_request(
                "tools/call",
                7,
                {
                    "name": "get_player_rankings",
                    "arguments": {"offset": None},
                },
            ),
        )
    assert mismatch.status_code == 400
    assert mismatch.json()["error"]["code"] == -32020
    assert null_offset.json()["result"]["isError"] is True
    assert null_offset.json()["result"]["structuredContent"]["reason"] == ("invalid_argument_type")


def test_protocol_rejects_unsupported_versions_and_mcp_name_mismatch(monkeypatch):
    with _mcp_client(monkeypatch) as client:
        unsupported_body = _request("tools/list", 8)
        unsupported_body["params"]["_meta"]["io.modelcontextprotocol/protocolVersion"] = (
            "2025-11-25"
        )
        unsupported = client.post(
            "/api/chase-upside/mcp",
            headers={
                **_headers("tools/list"),
                "MCP-Protocol-Version": "2025-11-25",
            },
            json=unsupported_body,
        )
        name_mismatch = client.post(
            "/api/chase-upside/mcp",
            headers=_headers("tools/call", "resolve_player_identity"),
            json=_request(
                "tools/call",
                9,
                {"name": "get_player_rankings", "arguments": {}},
            ),
        )
    assert unsupported.status_code == 400
    assert unsupported.json()["error"]["code"] == -32022
    assert unsupported.json()["error"]["data"]["supported"] == ["2026-07-28"]
    assert name_mismatch.status_code == 400
    assert name_mismatch.json()["error"]["code"] == -32020


def test_engine_value_errors_are_not_echoed(monkeypatch):
    from src.api import chase_upside_mcp as mcp

    async def _boom(name, arguments, request):
        raise ValueError("internal detail C:/secret/path row 17")

    monkeypatch.setattr(mcp, "call_tool", _boom)
    with _mcp_client(monkeypatch) as client:
        response = client.post(
            "/api/chase-upside/mcp",
            headers=_headers("tools/call", "get_player_rankings"),
            json=_request("tools/call", 20, {"name": "get_player_rankings", "arguments": {}}),
        )
    result = response.json()["result"]
    assert result["isError"] is True
    assert result["structuredContent"]["reason"] == "tool_request_rejected"
    assert "secret" not in response.text and "internal detail" not in response.text


def test_deeply_nested_json_is_a_stable_400(monkeypatch):
    from src.api import chase_upside_mcp as mcp

    deep = b"[" * 60_000
    with _mcp_client(monkeypatch) as client:
        scanned = client.post("/api/chase-upside/mcp", headers=_headers(), content=deep)
        # Belt and braces: with the pre-scan disabled, the parser's own
        # RecursionError is still a 400, never a generic 500.
        monkeypatch.setattr(mcp, "MAX_JSON_DEPTH", 10**9)
        parsed = client.post("/api/chase-upside/mcp", headers=_headers(), content=deep)
    for response in (scanned, parsed):
        assert response.status_code == 400
        assert response.json() == {"error": "json_too_deep"}


def test_non_utf8_body_cannot_bypass_the_depth_scan(monkeypatch):
    """A UTF-16 body would slip past a byte-level bracket scan if the parser
    auto-detected its encoding; the body is decoded as UTF-8 first instead."""
    # A VALID JSON-RPC request nesting deeper than MAX_JSON_DEPTH (but nowhere
    # near the recursion limit): json.loads(bytes) would auto-detect UTF-16
    # and accept it, past the byte scan, into the handler.
    nested = "[" * 100 + "]" * 100
    body = '{"jsonrpc": "2.0", "id": 1, "method": "tools/list", "params": {"x": %s}}' % nested
    with _mcp_client(monkeypatch) as client:
        response = client.post(
            "/api/chase-upside/mcp", headers=_headers(), content=body.encode("utf-16")
        )
    assert response.status_code == 400
    assert response.json() == {"error": "invalid_json"}


def test_tool_call_answers_within_its_time_budget(monkeypatch):
    import asyncio

    from src.api import chase_upside_mcp as mcp

    async def _slow(name, arguments, request):
        await asyncio.sleep(2)
        return {"status": "ok"}

    monkeypatch.setattr(mcp, "call_tool", _slow)
    monkeypatch.setattr(mcp, "TOOL_TIME_BUDGET_SECONDS", 0.05)
    with _mcp_client(monkeypatch) as client:
        response = client.post(
            "/api/chase-upside/mcp",
            headers=_headers("tools/call", "get_player_rankings"),
            json=_request("tools/call", 21, {"name": "get_player_rankings", "arguments": {}}),
        )
    result = response.json()["result"]
    assert result["isError"] is True
    assert result["structuredContent"]["reason"] == "tool_time_budget_exceeded"
    assert result["structuredContent"]["retryable"] is True
    assert mcp.TOOL_TIME_BUDGET_SECONDS < 20  # under the Sites Worker's 20 s abort
