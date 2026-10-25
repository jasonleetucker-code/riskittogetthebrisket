"""Private, read-only MCP surface for Chase Upside.

The ChatGPT Sites worker enforces Site owner access and forwards requests with
the backend service token. This module deliberately calls the existing league,
identity, roster, and trade owners; it does not create a parallel valuation or
trade model.
"""

from __future__ import annotations

import hmac
import json
import os
from typing import Any

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

router = APIRouter()
MAX_REQUEST_BYTES = 64 * 1024
PROTOCOL_VERSION = "2026-07-28"
_PYTHON_TYPES = {"string": str, "integer": int, "null": type(None)}

TOOLS = [
    {
        "name": "get_player_rankings",
        "description": "Read the current Chase Upside player rankings for a league.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "leagueKey": {"type": "string"},
                "position": {"type": "string"},
                "limit": {"type": "integer", "minimum": 1, "maximum": 100},
                "offset": {"type": "integer", "minimum": 0},
            },
            "additionalProperties": False,
        },
    },
    {
        "name": "resolve_player_identity",
        "description": "Resolve a player name or platform ID using Chase Upside's canonical identity resolver.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "name": {"type": "string"},
                "sleeperId": {"type": "string"},
                "position": {"type": "string"},
                "team": {"type": "string"},
            },
            "additionalProperties": False,
        },
    },
    {
        "name": "get_league_context",
        "description": "Read league scoring and roster settings without exposing Sleeper league credentials.",
        "inputSchema": {
            "type": "object",
            "properties": {"leagueKey": {"type": "string"}},
            "required": ["leagueKey"],
            "additionalProperties": False,
        },
    },
    {
        "name": "get_team_roster",
        "description": "Read a team's current roster and available player identifiers for a league.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "leagueKey": {"type": "string"},
                "teamName": {"type": "string"},
                "rosterId": {"type": "integer"},
            },
            "required": ["leagueKey"],
            "additionalProperties": False,
        },
    },
    {
        "name": "analyze_trade",
        "description": "Analyze a proposed trade with the current Chase Upside trade engine; this does not save or publish the result.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "leagueKey": {"type": "string"},
                "rosterId": {"type": "integer"},
                "playersIn": {"type": "array", "items": {"type": "string"}},
                "playerIdsIn": {"type": "array", "items": {"type": ["string", "null"]}},
                "playersOut": {"type": "array", "items": {"type": "string"}},
                "playerIdsOut": {"type": "array", "items": {"type": ["string", "null"]}},
                "picksIn": {"type": "array", "items": {"type": "string"}},
                "pickAssetIdsIn": {"type": "array", "items": {"type": ["string", "null"]}},
                "picksOut": {"type": "array", "items": {"type": "string"}},
                "pickAssetIdsOut": {"type": "array", "items": {"type": ["string", "null"]}},
                "teamGoal": {"type": "string", "enum": ["WIN_NOW", "BALANCED", "LONG_TERM"]},
            },
            "required": ["leagueKey", "rosterId"],
            "additionalProperties": False,
        },
    },
]


def _server() -> Any:
    # Imported only after FastAPI has finished importing server.py.
    import server  # noqa: PLC0415

    return server


def _metadata(contract: dict[str, Any] | None, *, provenance: list[str]) -> dict[str, Any]:
    meta = (contract or {}).get("meta") or {}
    freshness = (contract or {}).get("dataFreshness") or {}
    source_states = freshness.get("sourceTimestamps") or {}
    methodology_sources = ((contract or {}).get("methodology") or {}).get("sources") or []
    return {
        "dataAsOf": (contract or {}).get("generatedAt") or meta.get("generatedAt"),
        "sourceProvenance": provenance,
        "rankingSources": [
            str(source.get("key") or source.get("name"))
            for source in methodology_sources
            if isinstance(source, dict)
        ],
        "sourceFreshness": [
            {
                "source": key,
                "status": value.get("staleness") or "unknown",
                "ageHours": value.get("ageHours"),
            }
            for key, value in source_states.items()
            if isinstance(value, dict)
        ],
        "confidence": "source-reported",
        "missingData": [],
    }


def _missing(reason: str, *, missing: list[str] | None = None) -> dict[str, Any]:
    return {
        "status": "unavailable",
        "reason": reason,
        "dataAsOf": None,
        "confidence": None,
        "sourceProvenance": [],
        "missingData": missing or [reason],
    }


def _tool_result(value: dict[str, Any]) -> dict[str, Any]:
    return {
        "content": [{"type": "text", "text": json.dumps(value, ensure_ascii=False)}],
        "structuredContent": value,
    }


def _validate_arguments(name: str, arguments: dict[str, Any]) -> None:
    tool = next((item for item in TOOLS if item["name"] == name), None)
    if tool is None:
        raise ValueError("unknown_tool")
    schema = tool["inputSchema"]
    properties = schema.get("properties") or {}
    if set(arguments) - set(properties):
        raise ValueError("unexpected_argument")
    if any(key not in arguments for key in schema.get("required", [])):
        raise ValueError("required_argument_missing")
    for key, value in arguments.items():
        if value is None:
            continue
        definition = properties[key]
        kind = definition.get("type")
        if kind == "string" and not isinstance(value, str):
            raise ValueError("invalid_argument_type")
        if kind == "integer" and (not isinstance(value, int) or isinstance(value, bool)):
            raise ValueError("invalid_argument_type")
        if kind == "integer" and not definition.get("minimum", 0) <= value <= definition.get(
            "maximum", 2**31
        ):
            raise ValueError("invalid_argument_range")
        if kind == "array":
            if not isinstance(value, list) or len(value) > 100:
                raise ValueError("invalid_argument_type")
            item_types = definition.get("items", {}).get("type", "string")
            item_types = item_types if isinstance(item_types, list) else [item_types]
            allowed = tuple(_PYTHON_TYPES.get(item_type, object) for item_type in item_types)
            if any(not isinstance(item, allowed) for item in value):
                raise ValueError("invalid_argument_type")
    if name == "analyze_trade":
        if not any(
            arguments.get(key) for key in ("playersIn", "playersOut", "picksIn", "picksOut")
        ):
            raise ValueError("trade_assets_required")
        goal = arguments.get("teamGoal")
        if goal is not None and goal not in {"WIN_NOW", "BALANCED", "LONG_TERM"}:
            raise ValueError("invalid_team_goal")
    if name == "resolve_player_identity" and not any(
        arguments.get(key) for key in ("name", "sleeperId")
    ):
        raise ValueError("player_identity_required")
    if name == "get_team_roster" and not any(
        arguments.get(key) is not None for key in ("rosterId", "teamName")
    ):
        raise ValueError("team_identifier_required")


def _league(server: Any, key: str | None) -> Any:
    return server._league_registry.get_league_by_key(str(key or ""))


def _rankings(server: Any, args: dict[str, Any]) -> dict[str, Any]:
    contract = server.latest_contract_data
    if not isinstance(contract, dict):
        return _missing("rankings_not_ready", missing=["ranking_contract"])
    league = _league(server, args.get("leagueKey") or (contract.get("meta") or {}).get("leagueKey"))
    if league is None:
        return _missing("unknown_league", missing=["league_context"])
    mismatch = server._scoring_identity_error(contract, league)
    if mismatch is not None:
        return _missing("league_scoring_mismatch", missing=["league_compatible_rankings"])
    rows = contract.get("playersArray")
    if not isinstance(rows, list):
        return _missing("rankings_missing", missing=["playersArray"])
    position = str(args.get("position") or "").strip().upper()
    if position:
        rows = [row for row in rows if str(row.get("position") or "").upper() == position]
    # Preserve the canonical board's precomputed tie order.
    offset = max(0, int(args.get("offset") or 0))
    limit = min(100, max(1, int(args.get("limit") or 50)))
    selected = rows[offset : offset + limit]
    fields = (
        "playerId",
        "sleeperId",
        "name",
        "displayName",
        "position",
        "team",
        "age",
        "rank",
        "rankDerivedValue",
        "valueConfidence",
        "confidence",
        "confidenceLabel",
        "valueState",
    )
    players = []
    missing = []
    for row in selected:
        player = {key: row[key] for key in fields if key in row}
        if not player.get("sleeperId") and row.get("_sleeperId"):
            player["sleeperId"] = row["_sleeperId"]
        if not player.get("playerId") and not player.get("sleeperId"):
            missing.append(
                {"name": row.get("name") or row.get("displayName"), "reason": "player_id_missing"}
            )
        if player.get("confidence") is None:
            player["confidence"] = row.get("confidenceLabel")
        players.append(player)
    return {
        "status": "partial" if missing else "ok",
        "leagueKey": league.key,
        "total": len(rows),
        "offset": offset,
        "players": players,
        **_metadata(contract, provenance=["Chase Upside canonical rankings contract"]),
        "missingData": missing,
    }


def _identity(args: dict[str, Any]) -> dict[str, Any]:
    from datetime import datetime, timezone  # noqa: PLC0415

    from src.identity.directory_cache import get_default_sleeper_index  # noqa: PLC0415
    from src.identity.resolution import RESOLVED, resolve_canonical_v2  # noqa: PLC0415
    from src.identity.directory_cache import default_directory_path  # noqa: PLC0415

    index = get_default_sleeper_index()
    if index is None:
        return _missing("identity_directory_unavailable", missing=["Sleeper player directory"])
    result = resolve_canonical_v2(
        index,
        sleeper_id=args.get("sleeperId"),
        name=args.get("name"),
        position=args.get("position"),
        team=args.get("team"),
    )
    try:
        data_as_of = datetime.fromtimestamp(
            default_directory_path().stat().st_mtime, tz=timezone.utc
        ).isoformat()
    except OSError:
        data_as_of = None
    if result.status != RESOLVED:
        return {
            "status": result.status,
            "reason": result.reason,
            "candidates": list(result.candidate_ids),
            "confidence": result.confidence,
            "dataAsOf": data_as_of,
            "sourceProvenance": ["Sleeper player directory", "canonical identity resolver"],
            "missingData": [result.reason or "identity_unresolved"],
        }
    return {
        "status": result.status,
        "playerId": result.sleeper_id,
        "sleeperId": result.sleeper_id,
        "name": result.display_name,
        "position": result.position,
        "team": result.team,
        "confidence": result.confidence,
        "dataAsOf": data_as_of,
        "method": result.method,
        "sourceProvenance": ["Sleeper player directory", "canonical identity resolver"],
        "missingData": [],
    }


def _league_context(server: Any, args: dict[str, Any]) -> dict[str, Any]:
    league = _league(server, args.get("leagueKey"))
    if league is None:
        return _missing("unknown_league", missing=["league_context"])
    return {
        "status": "ok",
        "league": league.public_dict(),
        "dataAsOf": None,
        "dataTimestampState": "registry_does_not_stamp_updated_at",
        "sourceProvenance": ["Chase Upside league registry"],
        "confidence": "configured",
        "missingData": [{"field": "dataAsOf", "reason": "registry_does_not_stamp_updated_at"}],
    }


async def _team_roster(server: Any, args: dict[str, Any]) -> dict[str, Any]:
    contract = server.latest_contract_data
    league = _league(server, args.get("leagueKey"))
    if not isinstance(contract, dict):
        return _missing("rosters_not_ready", missing=["league_snapshot"])
    if league is None:
        return _missing("unknown_league", missing=["league_context"])
    mismatch = server._scoring_identity_error(contract, league)
    if mismatch is not None:
        return _missing("league_scoring_mismatch", missing=["league_compatible_rosters"])
    sleeper = contract.get("sleeper") or {}
    try:
        overlay = await server.run_in_threadpool(
            server._sleeper_overlay.fetch_sleeper_overlay,
            sleeper_league_id=league.sleeper_league_id,
            id_to_player=sleeper.get("idToPlayer")
            if isinstance(sleeper.get("idToPlayer"), dict)
            else {},
        )
    except Exception:  # noqa: BLE001 — stale contract fallback is explicit below
        server.log.warning("Chase Upside MCP roster overlay unavailable", exc_info=True)
        overlay = None
    overlay_ready = bool(overlay and overlay.get("teams"))
    teams = (overlay.get("teams") if overlay_ready else sleeper.get("teams")) or []
    roster_id = args.get("rosterId")
    team = next(
        (t for t in teams if roster_id is not None and str(t.get("roster_id")) == str(roster_id)),
        None,
    )
    if team is None and args.get("teamName"):
        team = next(
            (
                t
                for t in teams
                if str(t.get("name") or "").casefold() == str(args["teamName"]).casefold()
            ),
            None,
        )
    if team is None:
        return _missing("team_not_found", missing=["team roster"])
    player_by_id = {}
    for row in contract.get("playersArray") or []:
        for key in ("playerId", "sleeperId", "_sleeperId"):
            value = str(row.get(key) or "").strip()
            if value:
                player_by_id[value] = row
    player_ids = [str(value) for value in (team.get("playerIds") or [])]
    players = []
    missing = []
    for player_id in player_ids:
        row = player_by_id.get(player_id)
        if row is None:
            missing.append(player_id)
            players.append({"playerId": player_id, "status": "unpriced"})
        else:
            players.append(
                {
                    "playerId": player_id,
                    "name": row.get("name") or row.get("displayName"),
                    "position": row.get("position"),
                    "team": row.get("team"),
                    "value": row.get("rankDerivedValue"),
                    "valueState": row.get("valueState", "available"),
                }
            )
    missing_data = [{"playerId": pid, "reason": "ranking_row_missing"} for pid in missing]
    if not overlay_ready:
        missing_data.append(
            {"field": "rosterFreshness", "reason": "live_sleeper_overlay_unavailable"}
        )
    source_provenance = [
        "Sleeper live overlay" if overlay_ready else "Sleeper contract snapshot",
        "Chase Upside canonical rankings contract",
    ]
    result = {
        "status": "partial" if missing_data else "ok",
        "leagueKey": league.key,
        "rosterId": team.get("roster_id"),
        "teamName": team.get("name"),
        "players": players,
        "sourceProvenance": source_provenance,
        "missingData": missing_data,
        "confidence": "live-overlay" if overlay_ready else "snapshot-fallback",
        "dataAsOf": (overlay or {}).get("overlayFetchedAt")
        if overlay_ready
        else sleeper.get("rosterFetchedAt"),
        "rosterDataSource": "live-overlay"
        if overlay_ready
        else sleeper.get("rosterSource") or "unknown",
    }
    result.update(
        {
            key: value
            for key, value in _metadata(contract, provenance=result["sourceProvenance"]).items()
            if key not in {"missingData", "dataAsOf"}
        }
    )
    return result


async def _trade_analysis(server: Any, args: dict[str, Any]) -> dict[str, Any]:
    contract = server.latest_contract_data
    league = _league(server, args.get("leagueKey"))
    if not isinstance(contract, dict):
        return _missing("trade_data_not_ready", missing=["ranking_contract"])
    if league is None:
        return _missing("unknown_league", missing=["league_context"])
    mismatch = server._scoring_identity_error(contract, league)
    if mismatch is not None:
        return _missing("league_scoring_mismatch", missing=["league_compatible_trade_analysis"])
    loaded_league_key = str((contract.get("meta") or {}).get("leagueKey") or "")
    roster_data_as_of = (contract.get("sleeper") or {}).get("rosterFetchedAt")
    if loaded_league_key and loaded_league_key != league.key:
        try:
            overlay = await server.run_in_threadpool(
                server._sleeper_overlay.fetch_sleeper_overlay,
                sleeper_league_id=league.sleeper_league_id,
                id_to_player=(contract.get("sleeper") or {}).get("idToPlayer") or {},
            )
        except Exception:  # noqa: BLE001 — report unavailable rather than cross-league fallback
            server.log.warning("Chase Upside MCP trade overlay unavailable", exc_info=True)
            overlay = None
        if not overlay or not overlay.get("teams"):
            return _missing("league_roster_overlay_unavailable", missing=["live_league_rosters"])
        sleeper, _ready = server._sleeper_overlay.merge_cross_league_sleeper_block(
            loaded_sleeper=contract.get("sleeper") or {},
            overlay=overlay,
            requested_league_config=overlay.get("leagueConfig"),
        )
        contract = {**contract, "sleeper": sleeper}
        roster_data_as_of = overlay.get("overlayFetchedAt")
    team = next(
        (
            t
            for t in ((contract.get("sleeper") or {}).get("teams") or [])
            if str(t.get("roster_id")) == str(args.get("rosterId"))
        ),
        None,
    )
    if team is None:
        return _missing("team_not_found", missing=["team roster"])
    from src.trade import analyze_service  # noqa: PLC0415

    simulation = await server.run_in_threadpool(
        analyze_service.simulate_for_team,
        contract,
        league_key=league.key,
        roster_settings=dict(league.roster_settings or {}),
        resolved_team=team,
        players_in=args.get("playersIn") or [],
        player_ids_in=args.get("playerIdsIn"),
        players_out=args.get("playersOut") or [],
        player_ids_out=args.get("playerIdsOut"),
        picks_in=args.get("picksIn") or [],
        pick_ids_in=args.get("pickAssetIdsIn"),
        picks_out=args.get("picksOut") or [],
        pick_ids_out=args.get("pickAssetIdsOut"),
        team_context=True,
        for_analysis=True,
    )
    analysis = analyze_service.analyze_for_team(
        simulation,
        contract=contract,
        team_goal=args.get("teamGoal"),
        counterfactuals=False,
    )
    return {
        "status": "ok",
        "leagueKey": league.key,
        "rosterId": team.get("roster_id"),
        "teamName": team.get("name"),
        "simulation": simulation,
        "analysis": analysis,
        "sourceProvenance": [
            "Chase Upside canonical rankings contract",
            "Chase Upside trade simulation and decision engine",
        ],
        "confidence": analysis.get("confidence"),
        "missingData": analysis.get("unavailableDimensions") or [],
        "dataAsOf": contract.get("generatedAt") or (contract.get("meta") or {}).get("generatedAt"),
        "dataTimestamps": {
            "rankings": contract.get("generatedAt")
            or (contract.get("meta") or {}).get("generatedAt"),
            "rosters": roster_data_as_of,
        },
    }


async def call_tool(name: str, arguments: dict[str, Any], request: Request) -> dict[str, Any]:
    _validate_arguments(name, arguments)
    server = _server()
    if name == "get_player_rankings":
        return _rankings(server, arguments)
    if name == "resolve_player_identity":
        return _identity(arguments)
    if name == "get_league_context":
        return _league_context(server, arguments)
    if name == "get_team_roster":
        return await _team_roster(server, arguments)
    if name == "analyze_trade":
        return await _trade_analysis(server, arguments)
    raise ValueError("unknown_tool")


@router.post("/api/chase-upside/mcp")
async def mcp_endpoint(request: Request):
    expected = os.getenv("CHASE_UPSIDE_MCP_API_TOKEN", "")
    owner_id = os.getenv("CHASE_UPSIDE_MCP_OWNER_USER_ID", "")
    supplied = request.headers.get("authorization", "")
    bearer = supplied[7:] if supplied.lower().startswith("bearer ") else ""
    if len(expected) < 32 or not hmac.compare_digest(bearer, expected):
        return JSONResponse(
            {"error": "unauthorized"}, status_code=401, headers={"Cache-Control": "no-store"}
        )
    if not owner_id or not hmac.compare_digest(
        request.headers.get("x-chase-upside-owner-id", ""), owner_id
    ):
        return JSONResponse(
            {"error": "forbidden"}, status_code=403, headers={"Cache-Control": "no-store"}
        )
    raw = bytearray()
    async for chunk in request.stream():
        raw.extend(chunk)
        if len(raw) > MAX_REQUEST_BYTES:
            return JSONResponse({"error": "request_too_large"}, status_code=413)
    try:
        message = json.loads(raw)
    except (UnicodeDecodeError, json.JSONDecodeError):
        return JSONResponse({"error": "invalid_json"}, status_code=400)
    if not isinstance(message, dict):
        return JSONResponse({"error": "invalid_request"}, status_code=400)
    if message.get("jsonrpc") != "2.0" or not isinstance(message.get("method"), str):
        return JSONResponse(
            {
                "jsonrpc": "2.0",
                "id": message.get("id"),
                "error": {"code": -32600, "message": "Invalid Request"},
            },
            status_code=200,
            headers={"Cache-Control": "no-store"},
        )
    method = message.get("method")
    request_id = message.get("id")
    params = message.get("params") or {}
    if method == "server/discover":
        result = {"supportedVersions": [PROTOCOL_VERSION], "capabilities": {"tools": {}}}
    elif method == "tools/list":
        result = {"tools": TOOLS}
    elif method == "tools/call":
        name = params.get("name") if isinstance(params, dict) else None
        arguments = params.get("arguments") if isinstance(params, dict) else None
        if not isinstance(arguments, dict):
            arguments = {}
        try:
            result = _tool_result(await call_tool(str(name or ""), arguments, request))
        except ValueError as exc:
            result = _tool_result(
                {"status": "unavailable", "reason": str(exc), "missingData": [str(exc)]}
            )
            result["isError"] = True
        except Exception:  # noqa: BLE001 — never return backend details or secrets
            server = _server()
            server.log.exception("Chase Upside MCP tool failed")
            result = _tool_result(
                {
                    "status": "unavailable",
                    "reason": "tool_execution_failed",
                    "missingData": ["backend_error"],
                }
            )
            result["isError"] = True
    elif method == "ping":
        result = {}
    else:
        return JSONResponse(
            {
                "jsonrpc": "2.0",
                "id": request_id,
                "error": {"code": -32601, "message": "Method not found"},
            },
            status_code=200,
            headers={"Cache-Control": "no-store"},
        )
    return JSONResponse(
        {"jsonrpc": "2.0", "id": request_id, "result": result},
        headers={"Cache-Control": "no-store"},
    )
