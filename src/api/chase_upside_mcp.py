"""Private, read-only MCP surface for Chase Upside.

The ChatGPT Sites worker enforces Site owner access and forwards requests with
the backend service token. This module is an ADAPTER: every answer comes from
an existing canonical owner, and it creates no parallel valuation, identity,
roster, history or trade model.

Owners consumed (never re-implemented here):

* rankings / values — the loaded canonical contract (``playersArray``,
  ``canonicalConsensusRank`` / ``rankDerivedValue`` / ``confidenceBucket``);
  cross-league reuse is decided by ``server._scoring_identity_error`` only;
* player identity — ``src.identity.resolution.resolve_canonical_v2`` (explicit
  refusal is acceptable for a lookup tool; see CLAUDE.md "Player identity");
* rosters — the contract's own ``sleeper`` block for the loaded league, else
  ``sleeper_overlay.merge_cross_league_sleeper_block`` over a live overlay;
  freshness from ``src.api.roster_freshness``; pick values from
  ``src.api.pick_value_resolution.resolve_pick_asset_value``;
* trade analysis — ``src.trade.trade_ledger`` (one snapshot, canonical asset
  ids, ownership verified against that snapshot) +
  ``src.trade.analyze_service.analyze_trade_n`` (the ONE composer of the
  per-team steps).  It writes nothing: no decision receipt, no run id;
* value history — ``src.history.asof`` over the ``canonical_board`` lane only.

Licensing boundary: no tool returns a third-party source's own values or
ranks (``canonicalSiteValues``, ``rawSourceValues``, ``sourceNativeValues``,
``sourceRanks``, ``ktcMarket``, the ``source_value`` history lane).  Only the
Chase Upside canonical quantities and source NAMES / freshness leave here.
``analyze_trade``'s ``includeDetail`` returns the engine's ``analysis`` /
``simulation`` whole EXCEPT that every per-source evidence key
(``SOURCE_EVIDENCE_KEYS``) is removed at any depth and named in
``detailRedactedKeys`` -- defense in depth, since that subtree is not
allowlisted field by field.

Error and resource bounds: only this module's own argument validation
(``ToolArgumentError``) echoes a reason to the caller; any other exception
from an engine answers a generic reason code.  The JSON body is bounded in
bytes (``MAX_REQUEST_BYTES``) and nesting depth (``MAX_JSON_DEPTH``); a tool
call answers within ``TOOL_TIME_BUDGET_SECONDS`` (below the Sites Worker's
20 s abort), and trade computations take a slot of the private multi-team
route's admission bound (``src.api.compute_admission``).  Work already in a
worker thread cannot be interrupted: it finishes in the background.

MISSING IS NEVER ZERO: an unpriced asset is ``value: null`` with a reason, an
unranked row is excluded and counted, an unknown freshness is ``unknown``.
"""

from __future__ import annotations

import asyncio
import hmac
import json
import os
from typing import Any

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

router = APIRouter()
MAX_REQUEST_BYTES = 64 * 1024
#: Deepest JSON nesting a request may carry.  The deepest legitimate body is
#: ~6 levels (message -> params -> arguments -> assets -> leg); 32 leaves room
#: for client ``_meta`` capabilities while keeping ``json.loads`` far from
#: Python's recursion limit.
MAX_JSON_DEPTH = 32
#: How long the caller waits for one tool call.  Below the Sites Worker's
#: 20 s abort (``sites/chase-upside-mcp/worker/index.js``) so the owner gets a
#: stable, retryable reason instead of a proxy abort.
TOOL_TIME_BUDGET_SECONDS = 18.0
PROTOCOL_VERSION = "2026-07-28"
SERVER_INFO = {"name": "Chase Upside MCP", "version": "1.1.0"}
SERVER_INFO_META = {"io.modelcontextprotocol/serverInfo": SERVER_INFO}
MAX_RANKINGS_PAGE = 100
MAX_HISTORY_POINTS = 400
_TEAM_GOALS = ["WIN_NOW", "BALANCED", "LONG_TERM"]
_READ_ONLY = {"readOnlyHint": True, "destructiveHint": False, "idempotentHint": True}

#: Per-source evidence keys that never leave this endpoint, at any depth.
#: The allowlists below already exclude them from rankings / roster rows; this
#: set is the second line of defense for subtrees served whole (trade detail).
SOURCE_EVIDENCE_KEYS = frozenset(
    {
        "canonicalSiteValues",
        "rawSourceValues",
        "sourceNativeValues",
        "sourceRanks",
        "sourceOriginalRanks",
        "effectiveSourceRanks",
        "sourceRankMeta",
        "sourceAudit",
        "ktcMarket",
        "ktcRank",
        "ktcValueSources",
        "marketGapDirection",
        "marketGapMagnitude",
        "marketGapValueRatio",
    }
)


class ToolArgumentError(ValueError):
    """A caller-input refusal raised by THIS module's validators.

    Its message is a stable reason code that never echoes input, so it is
    the only exception text returned to the caller.  Any other exception
    (including a ``ValueError`` from an engine) answers a generic reason.
    """


#: Board fields a rankings / roster row may carry.  An ALLOWLIST: anything
#: per-source (values, ranks, native numbers, KTC Market) never leaves.
_RANKING_ROW_FIELDS = (
    "playerId",
    "displayName",
    "canonicalName",
    "position",
    "team",
    "age",
    "rookie",
    "assetClass",
    "canonicalConsensusRank",
    "rankDerivedValue",
    "canonicalTierId",
    "confidenceBucket",
    "confidenceLabel",
    "quarantined",
)

TOOLS = [
    {
        "name": "get_player_rankings",
        "description": (
            "Read the current Chase Upside canonical rankings for a league, ordered by "
            "canonical consensus rank, with paging, confidence and data freshness."
        ),
        "annotations": _READ_ONLY,
        "inputSchema": {
            "type": "object",
            "properties": {
                "leagueKey": {"type": "string", "maxLength": 64},
                "position": {"type": "string", "maxLength": 8},
                "limit": {"type": "integer", "minimum": 1, "maximum": MAX_RANKINGS_PAGE},
                "offset": {"type": "integer", "minimum": 0},
            },
            "additionalProperties": False,
        },
    },
    {
        "name": "resolve_player_identity",
        "description": (
            "Resolve a player name or Sleeper ID with Chase Upside's canonical identity "
            "resolver. Ambiguous or unknown names are refused with candidates, never guessed."
        ),
        "annotations": _READ_ONLY,
        "inputSchema": {
            "type": "object",
            "properties": {
                "name": {"type": "string", "maxLength": 80},
                "sleeperId": {"type": "string", "maxLength": 32},
                "position": {"type": "string", "maxLength": 8},
                "team": {"type": "string", "maxLength": 8},
            },
            "additionalProperties": False,
        },
    },
    {
        "name": "get_league_context",
        "description": (
            "Read league scoring and roster settings and the scoring-evidence state, "
            "without exposing Sleeper league identifiers."
        ),
        "annotations": _READ_ONLY,
        "inputSchema": {
            "type": "object",
            "properties": {"leagueKey": {"type": "string", "maxLength": 64}},
            "additionalProperties": False,
        },
    },
    {
        "name": "get_team_roster",
        "description": (
            "Read one team's roster and owned draft picks with canonical asset ids "
            "(p:<sleeperId> / pick:...), canonical values and roster freshness."
        ),
        "annotations": _READ_ONLY,
        "inputSchema": {
            "type": "object",
            "properties": {
                "leagueKey": {"type": "string", "maxLength": 64},
                "teamName": {"type": "string", "maxLength": 80},
                "rosterId": {"type": "integer", "minimum": 1, "maximum": 64},
            },
            "additionalProperties": False,
        },
    },
    {
        "name": "analyze_trade",
        "description": (
            "Analyze a proposed trade between league teams with the Chase Upside trade "
            "engine. Assets are canonical ids from get_team_roster; ownership is verified. "
            "Recommendation only: nothing is saved, published or executed."
        ),
        "annotations": _READ_ONLY,
        "inputSchema": {
            "type": "object",
            "properties": {
                "leagueKey": {"type": "string", "maxLength": 64},
                "teams": {
                    "type": "array",
                    "items": {"type": "integer", "minimum": 1, "maximum": 64},
                    "minItems": 2,
                    "maxItems": 4,
                },
                "assets": {
                    "type": "array",
                    "minItems": 1,
                    "maxItems": 64,
                    "items": {
                        "type": "object",
                        "properties": {
                            "id": {"type": "string", "maxLength": 64},
                            "from": {"type": "integer", "minimum": 1, "maximum": 64},
                            "to": {"type": "integer", "minimum": 1, "maximum": 64},
                        },
                        "required": ["id", "from", "to"],
                        "additionalProperties": False,
                    },
                },
                "useTeamContext": {"type": "boolean"},
                "teamGoals": {
                    "type": "object",
                    "additionalProperties": {"type": "string", "enum": _TEAM_GOALS},
                },
                "perspectiveRosterId": {"type": "integer", "minimum": 1, "maximum": 64},
                "includeDetail": {"type": "boolean"},
            },
            "required": ["teams", "assets"],
            "additionalProperties": False,
        },
    },
    {
        "name": "get_value_history",
        "description": (
            "Read the recorded history of one asset's Chase Upside canonical board value "
            "and rank. Never interpolated; dates before the history floor are unavailable."
        ),
        "annotations": _READ_ONLY,
        "inputSchema": {
            "type": "object",
            "properties": {
                "leagueKey": {"type": "string", "maxLength": 64},
                "playerId": {"type": "string", "maxLength": 32},
                "pickName": {
                    "type": "string",
                    "maxLength": 40,
                },  # board row name, e.g. "2027 Early 1st"
                "asOfDate": {"type": "string", "maxLength": 10},
                "start": {"type": "string", "maxLength": 10},
                "end": {"type": "string", "maxLength": 10},
            },
            "additionalProperties": False,
        },
    },
]
_TOOLS_BY_NAME = {tool["name"]: tool for tool in TOOLS}


def _server() -> Any:
    # Imported only after FastAPI has finished importing server.py.
    import server  # noqa: PLC0415

    return server


# ── shared result shapes ─────────────────────────────────────────────────


def _contract_stamp(contract: dict[str, Any] | None) -> str | None:
    c = contract or {}
    return c.get("generatedAt") or (c.get("meta") or {}).get("generatedAt")


def _board_metadata(contract: dict[str, Any] | None) -> dict[str, Any]:
    """Board provenance: when it was built, which sources it names, and each
    source's freshness STATE.  Source names and freshness only — never a
    source's values, and never the box-local file paths the stamp carries."""
    c = contract or {}
    freshness = c.get("dataFreshness") if isinstance(c.get("dataFreshness"), dict) else {}
    states = freshness.get("sourceTimestamps") or {}
    methodology = c.get("methodology") if isinstance(c.get("methodology"), dict) else {}
    return {
        "dataAsOf": _contract_stamp(c),
        "rankingSources": [
            str(s.get("key") or s.get("name"))
            for s in methodology.get("sources") or []
            if isinstance(s, dict) and (s.get("key") or s.get("name"))
        ],
        "sourceFreshness": [
            {
                "source": str(key),
                "status": value.get("staleness") or "unknown",
                "ageHours": value.get("ageHours"),
            }
            for key, value in states.items()
            if isinstance(value, dict)
        ],
    }


def _missing(reason: str, *, missing: list[Any] | None = None, **extra: Any) -> dict[str, Any]:
    return {
        "status": "unavailable",
        "reason": reason,
        "dataAsOf": None,
        "confidence": None,
        "sourceProvenance": [],
        "missingData": missing or [reason],
        **extra,
    }


def _tool_result(value: dict[str, Any]) -> dict[str, Any]:
    return {
        "resultType": "complete",
        "_meta": SERVER_INFO_META,
        "content": [{"type": "text", "text": json.dumps(value, ensure_ascii=False, default=str)}],
        "structuredContent": json.loads(json.dumps(value, default=str)),
    }


def _cacheable_result(result: dict[str, Any]) -> dict[str, Any]:
    return {
        **result,
        "resultType": "complete",
        "ttlMs": 0,
        "cacheScope": "private",
        "_meta": SERVER_INFO_META,
    }


def _protocol_error(request_id: Any, code: int, message: str) -> JSONResponse:
    return JSONResponse(
        {"jsonrpc": "2.0", "id": request_id, "error": {"code": code, "message": message}},
        status_code=400,
        headers={"Cache-Control": "no-store"},
    )


def _plain_error(status: int, error: str) -> JSONResponse:
    return JSONResponse({"error": error}, status_code=status, headers={"Cache-Control": "no-store"})


def _decode_request_name(value: str) -> str:
    prefix, suffix = "=?base64?", "?="
    if value.startswith(prefix) and value.endswith(suffix):
        import base64  # noqa: PLC0415

        try:
            return base64.b64decode(value[len(prefix) : -len(suffix)], validate=True).decode(
                "utf-8"
            )
        except (ValueError, UnicodeDecodeError) as exc:
            raise ValueError("invalid_header_encoding") from exc
    return value


def _validate_protocol_request(request: Request, message: dict[str, Any]) -> JSONResponse | None:
    request_id = message.get("id")
    params = message.get("params")
    if not isinstance(params, dict):
        return _protocol_error(request_id, -32602, "Invalid params")
    meta = params.get("_meta")
    version = (
        meta.get("io.modelcontextprotocol/protocolVersion") if isinstance(meta, dict) else None
    )
    header_version = request.headers.get("mcp-protocol-version")
    if header_version != version:
        return _protocol_error(request_id, -32020, "Header mismatch")
    if version != PROTOCOL_VERSION:
        return JSONResponse(
            {
                "jsonrpc": "2.0",
                "id": request_id,
                "error": {
                    "code": -32022,
                    "message": "Unsupported protocol version",
                    "data": {"supported": [PROTOCOL_VERSION], "requested": version},
                },
            },
            status_code=400,
            headers={"Cache-Control": "no-store"},
        )
    if not isinstance(meta, dict) or not isinstance(
        meta.get("io.modelcontextprotocol/clientCapabilities"), dict
    ):
        return _protocol_error(request_id, -32602, "Invalid params")
    method = message.get("method")
    if request.headers.get("mcp-method") != method:
        return _protocol_error(request_id, -32020, "Header mismatch")
    if method == "tools/call":
        try:
            header_name = _decode_request_name(request.headers.get("mcp-name", ""))
        except ValueError:
            return _protocol_error(request_id, -32020, "Header mismatch")
        if header_name != params.get("name"):
            return _protocol_error(request_id, -32020, "Header mismatch")
    return None


# ── argument validation (the published inputSchema IS the validator) ────

_JSON_TYPES: dict[str, Any] = {
    "string": lambda v: isinstance(v, str),
    "integer": lambda v: isinstance(v, int) and not isinstance(v, bool),
    "boolean": lambda v: isinstance(v, bool),
    "object": lambda v: isinstance(v, dict),
    "array": lambda v: isinstance(v, list),
    "null": lambda v: v is None,
}


def _check(schema: dict[str, Any], value: Any) -> None:
    """Validate ``value`` against the subset of JSON Schema TOOLS uses.

    Raises ``ToolArgumentError`` with a stable reason code that never echoes the
    caller's input.  Any keyword this validator does not implement is
    refused at import (``_assert_supported``), so the advertised schema and
    the enforced one cannot drift apart.
    """
    kind = schema.get("type")
    kinds = kind if isinstance(kind, list) else [kind]
    if not any(_JSON_TYPES[k](value) for k in kinds):
        raise ToolArgumentError("invalid_argument_type")
    if value is None:
        return
    if "enum" in schema and value not in schema["enum"]:
        raise ToolArgumentError("invalid_argument_value")
    if isinstance(value, str) and len(value) > schema.get("maxLength", 256):
        raise ToolArgumentError("invalid_argument_range")
    if _JSON_TYPES["integer"](value) and not (
        schema.get("minimum", -(2**31)) <= value <= schema.get("maximum", 2**31)
    ):
        raise ToolArgumentError("invalid_argument_range")
    if isinstance(value, list):
        if not schema.get("minItems", 0) <= len(value) <= schema.get("maxItems", 100):
            raise ToolArgumentError("invalid_argument_range")
        for item in value:
            _check(schema.get("items") or {"type": "string"}, item)
    if isinstance(value, dict):
        properties = schema.get("properties") or {}
        extra = schema.get("additionalProperties", False)
        if len(value) > 64:
            raise ToolArgumentError("invalid_argument_range")
        for key in schema.get("required", []):
            if key not in value:
                raise ToolArgumentError("required_argument_missing")
        for key, item in value.items():
            if not isinstance(key, str) or len(key) > 64:
                raise ToolArgumentError("unexpected_argument")
            if key in properties:
                _check(properties[key], item)
            elif isinstance(extra, dict):
                _check(extra, item)
            else:
                raise ToolArgumentError("unexpected_argument")


_SUPPORTED_KEYWORDS = frozenset(
    {
        "type",
        "properties",
        "required",
        "additionalProperties",
        "items",
        "minimum",
        "maximum",
        "minItems",
        "maxItems",
        "maxLength",
        "enum",
    }
)


def _assert_supported(schema: Any) -> None:
    if not isinstance(schema, dict):
        return
    unknown = set(schema) - _SUPPORTED_KEYWORDS
    if unknown:
        raise RuntimeError(f"MCP inputSchema uses unvalidated keywords: {sorted(unknown)}")
    for sub in (schema.get("properties") or {}).values():
        _assert_supported(sub)
    _assert_supported(schema.get("items"))
    _assert_supported(schema.get("additionalProperties"))


for _tool in TOOLS:
    _assert_supported(_tool["inputSchema"])


def _validate_arguments(name: str, arguments: dict[str, Any]) -> None:
    tool = _TOOLS_BY_NAME.get(name)
    if tool is None:
        raise ToolArgumentError("unknown_tool")
    _check(tool["inputSchema"], arguments)
    if name == "resolve_player_identity" and not any(
        arguments.get(key) for key in ("name", "sleeperId")
    ):
        raise ToolArgumentError("player_identity_required")
    if name == "get_team_roster" and not any(
        arguments.get(key) is not None for key in ("rosterId", "teamName")
    ):
        raise ToolArgumentError("team_identifier_required")
    if name == "get_value_history":
        if bool(arguments.get("playerId")) == bool(arguments.get("pickName")):
            raise ToolArgumentError("exactly_one_asset_required")
        if arguments.get("asOfDate") and (arguments.get("start") or arguments.get("end")):
            raise ToolArgumentError("as_of_or_range_not_both")


# ── league / contract resolution ─────────────────────────────────────────


def _resolve_league(server: Any, key: Any) -> tuple[Any, dict[str, Any] | None]:
    registry = server._league_registry
    league = registry.get_league_by_key(str(key)) if key else registry.get_default_league()
    if league is None:
        return None, _missing(
            "unknown_league" if key else "no_leagues_configured", missing=["league_context"]
        )
    if getattr(league, "active", True) is False:
        return None, _missing("inactive_league", missing=["league_context"])
    return league, None


def _board_for_league(server: Any, league: Any) -> tuple[dict[str, Any] | None, dict | None]:
    """The canonical board, only when it may be served for ``league``."""
    contract = server.latest_contract_data
    if not isinstance(contract, dict) or not contract.get("playersArray"):
        return None, _missing("rankings_not_ready", missing=["ranking_contract"])
    if server._scoring_identity_error(contract, league) is not None:
        return None, _missing(
            "league_scoring_mismatch",
            missing=["league_compatible_rankings"],
            leagueKey=league.key,
        )
    return contract, None


async def _contract_with_league_rosters(
    server: Any, league: Any
) -> tuple[dict[str, Any] | None, dict[str, Any] | None, dict[str, Any] | None]:
    """``(contract, rosterProvenance, None)`` or ``(None, None, missing)``.

    The loaded league's own rosters come from the contract.  Any other league
    (scoring proven identical) gets a live overlay spliced in through the one
    merge owner — never the loaded league's teams, which would be a chimera.
    An unstamped contract cannot prove whose rosters it holds, so it takes
    the overlay path too (fail closed).
    """
    from src.api.roster_freshness import roster_freshness  # noqa: PLC0415

    contract, missing = _board_for_league(server, league)
    if missing is not None:
        return None, None, missing
    meta = contract.get("meta") if isinstance(contract.get("meta"), dict) else {}
    loaded_key = str(meta.get("leagueKey") or "")
    if loaded_key and loaded_key == league.key:
        if meta.get("sleeperDataReady") is False:
            return None, None, _missing("league_rosters_not_ready", missing=["league_rosters"])
        fresh = roster_freshness(contract)
        return contract, {**fresh, "delivery": "contract_snapshot"}, None
    loaded_sleeper = contract.get("sleeper") if isinstance(contract.get("sleeper"), dict) else {}
    id_map = loaded_sleeper.get("idToPlayer")
    try:
        overlay = await server.run_in_threadpool(
            server._sleeper_overlay.fetch_sleeper_overlay,
            sleeper_league_id=league.sleeper_league_id,
            id_to_player=id_map if isinstance(id_map, dict) else {},
        )
    except Exception:  # noqa: BLE001 — reported as unavailable, never a fallback
        server.log.warning("Chase Upside MCP roster overlay unavailable", exc_info=True)
        overlay = None
    if not overlay or not overlay.get("teams"):
        return None, None, _missing("league_roster_overlay_unavailable", missing=["league_rosters"])
    sleeper, ready = server._sleeper_overlay.merge_cross_league_sleeper_block(
        loaded_sleeper=loaded_sleeper,
        overlay=overlay,
        requested_league_config=overlay.get("leagueConfig"),
    )
    merged = {
        **contract,
        "sleeper": sleeper,
        "meta": {**meta, "leagueKey": league.key, "sleeperDataReady": bool(ready)},
    }
    return (
        merged,
        {
            **roster_freshness(merged),
            "delivery": "live_overlay",
            "overlayFetchedAt": overlay.get("overlayFetchedAt"),
            "leagueConfigComplete": bool(ready),
        },
        None,
    )


def _roster_provenance_missing(roster_provenance: dict[str, Any]) -> list[dict[str, Any]]:
    """Explicit missing states a roster delivery carries: stale/unknown
    freshness, and an overlay whose league config came back incomplete
    (``merge_cross_league_sleeper_block`` withheld the league-specific
    fields, so that league's roster / scoring context is not proven)."""
    out: list[dict[str, Any]] = []
    if roster_provenance.get("state") != "current":
        out.append(
            {"field": "rosterFreshness", "reason": f"rosters_{roster_provenance.get('state')}"}
        )
    if roster_provenance.get("leagueConfigComplete") is False:
        out.append(
            {
                "field": "leagueConfig",
                "reason": "league_config_incomplete",
                "leagueConfigComplete": False,
            }
        )
    return out


def _ranking_row(row: dict[str, Any]) -> dict[str, Any]:
    out = {key: row[key] for key in _RANKING_ROW_FIELDS if key in row}
    pid = str(row.get("playerId") or "").strip()
    out["assetId"] = f"p:{pid}" if pid else None
    if out.get("rankDerivedValue") is None:
        out["valueState"] = "unpriced"
    return out


# ── tools ────────────────────────────────────────────────────────────────


def _rankings(server: Any, args: dict[str, Any]) -> dict[str, Any]:
    league, missing = _resolve_league(server, args.get("leagueKey"))
    if missing is not None:
        return missing
    contract, missing = _board_for_league(server, league)
    if missing is not None:
        return missing
    rows = [r for r in contract.get("playersArray") or [] if isinstance(r, dict)]
    position = str(args.get("position") or "").strip().upper()
    if position:
        rows = [r for r in rows if str(r.get("position") or "").upper() == position]
    # The board's own rank decides the order; rows the board left unranked
    # (past OVERALL_RANK_LIMIT, suppressed aliases) are counted, not shown.
    ranked = [r for r in rows if isinstance(r.get("canonicalConsensusRank"), int)]
    ranked.sort(key=lambda r: r["canonicalConsensusRank"])
    offset = args.get("offset", 0)
    limit = args.get("limit", 50)
    page = ranked[offset : offset + limit]
    players = [_ranking_row(r) for r in page]
    missing_data: list[Any] = [
        {"name": p.get("displayName"), "reason": "player_id_missing"}
        for p in players
        if p.get("assetClass") != "pick" and not p.get("assetId")
    ]
    next_offset = offset + len(page)
    return {
        "status": "partial" if missing_data else "ok",
        "leagueKey": league.key,
        "position": position or None,
        "total": len(ranked),
        "unrankedRowsExcluded": len(rows) - len(ranked),
        "offset": offset,
        "limit": limit,
        "nextOffset": next_offset if next_offset < len(ranked) else None,
        "players": players,
        "rankBasis": "canonicalConsensusRank",
        "valueScale": "rankDerivedValue 1-9999 (Chase Upside canonical board)",
        "confidence": "per_row_confidenceBucket",
        "sourceProvenance": ["Chase Upside canonical rankings contract"],
        **_board_metadata(contract),
        "missingData": missing_data,
    }


def _identity(args: dict[str, Any]) -> dict[str, Any]:
    from datetime import datetime, timezone  # noqa: PLC0415

    from src.identity.directory_cache import (  # noqa: PLC0415
        default_directory_path,
        get_default_sleeper_index,
    )
    from src.identity.resolution import RESOLVED, resolve_canonical_v2  # noqa: PLC0415

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
    base = {
        "confidence": result.confidence,
        "dataAsOf": data_as_of,
        "policy": "CANONICAL_V2 (explicit refusal on ambiguity; not the served board join)",
        "sourceProvenance": ["Sleeper player directory", "canonical identity resolver"],
    }
    if result.status != RESOLVED:
        return {
            "status": result.status,
            "reason": result.reason,
            "candidates": list(result.candidate_ids),
            **base,
            "missingData": [result.reason or "identity_unresolved"],
        }
    return {
        "status": result.status,
        "playerId": result.sleeper_id,
        "sleeperId": result.sleeper_id,
        "assetId": f"p:{result.sleeper_id}",
        "name": result.display_name,
        "position": result.position,
        "team": result.team,
        "method": result.method,
        **base,
        "missingData": [],
    }


def _league_context(server: Any, args: dict[str, Any]) -> dict[str, Any]:
    league, missing = _resolve_league(server, args.get("leagueKey"))
    if missing is not None:
        return missing
    try:
        scoring_state = server._league_registry.scoring_evidence_state(league)
    except Exception:  # noqa: BLE001 — unknown, never "fresh"
        scoring_state = "unknown"
    return {
        "status": "ok",
        "league": league.public_dict(),
        "scoringEvidence": scoring_state,
        "dataAsOf": None,
        "dataTimestampState": "registry_does_not_stamp_updated_at",
        "sourceProvenance": ["Chase Upside league registry", "league scoring snapshot state"],
        "confidence": "configured",
        "missingData": [{"field": "dataAsOf", "reason": "registry_does_not_stamp_updated_at"}],
    }


def _roster_player(row: dict[str, Any] | None, pid: str, id_to_player: dict) -> dict[str, Any]:
    if row is None:
        return {
            "assetId": f"p:{pid}",
            "playerId": pid,
            "name": id_to_player.get(pid),
            "value": None,
            "valueState": "unpriced",
            "reason": "ranking_row_missing",
        }
    value = row.get("rankDerivedValue")
    out = {
        "assetId": f"p:{pid}",
        "playerId": pid,
        "name": row.get("displayName") or row.get("canonicalName"),
        "position": row.get("position"),
        "team": row.get("team"),
        "rank": row.get("canonicalConsensusRank"),
        "value": value,
        "valueState": "priced" if value is not None else "unpriced",
        "confidenceBucket": row.get("confidenceBucket"),
    }
    if value is None:
        out["reason"] = "board_row_unpriced"
    return out


def _roster_picks(team: dict[str, Any], contract: dict[str, Any]) -> tuple[Any, dict[str, Any]]:
    from src.api.pick_value_resolution import (  # noqa: PLC0415
        pick_rows_by_name,
        resolve_pick_asset_value,
    )
    from src.identity.picks import team_pick_ownership_unavailable_reason  # noqa: PLC0415

    reason = team_pick_ownership_unavailable_reason(team)
    if reason:
        return None, {"state": "unavailable", "reason": reason}
    details = team.get("pickDetails")
    if not isinstance(details, list):
        return None, {"state": "unavailable", "reason": "pick_details_missing"}
    rows_by_name = pick_rows_by_name(contract)
    year = contract.get("currentDraftYear")
    picks = []
    for d in details:
        if not isinstance(d, dict):
            continue
        pv = (
            resolve_pick_asset_value(
                asset_id=d.get("assetId"),
                slot=d.get("slot"),
                label=d.get("baseLabel") or d.get("label"),
                rows_by_name=rows_by_name,
                current_draft_year=int(year),
            )
            if isinstance(year, int)
            else None
        )
        value = pv.value if pv is not None else None
        picks.append(
            {
                "assetId": d.get("assetId"),
                "label": d.get("label"),
                "season": d.get("season"),
                "round": d.get("round"),
                "slot": d.get("slot"),
                "originalTeam": d.get("fromTeam"),
                "value": value,
                "valueState": "priced" if value is not None else "unpriced",
                "valueBasis": pv.basis if pv is not None else None,
                "reason": (pv.reason if pv is not None else "current_draft_year_unknown")
                if value is None
                else None,
            }
        )
    return picks, {"state": team.get("pickOwnershipState") or "observed", "reason": None}


async def _team_roster(server: Any, args: dict[str, Any]) -> dict[str, Any]:
    league, missing = _resolve_league(server, args.get("leagueKey"))
    if missing is not None:
        return missing
    contract, roster_provenance, missing = await _contract_with_league_rosters(server, league)
    if missing is not None:
        return missing
    sleeper = contract.get("sleeper") or {}
    teams = [t for t in sleeper.get("teams") or [] if isinstance(t, dict)]
    roster_id = args.get("rosterId")
    team = next(
        (t for t in teams if roster_id is not None and str(t.get("roster_id")) == str(roster_id)),
        None,
    )
    if team is None and args.get("teamName"):
        wanted = str(args["teamName"]).casefold()
        matches = [t for t in teams if str(t.get("name") or "").casefold() == wanted]
        if len(matches) > 1:
            return _missing("team_name_ambiguous", missing=["team roster"])
        team = matches[0] if matches else None
    if team is None:
        return _missing(
            "team_not_found",
            missing=["team roster"],
            teams=[{"rosterId": t.get("roster_id"), "teamName": t.get("name")} for t in teams],
        )
    rows_by_id: dict[str, dict[str, Any]] = {}
    for row in contract.get("playersArray") or []:
        pid = str((row or {}).get("playerId") or "").strip()
        if pid and pid not in rows_by_id:
            rows_by_id[pid] = row
    id_to_player = sleeper.get("idToPlayer") if isinstance(sleeper.get("idToPlayer"), dict) else {}
    players = [
        _roster_player(rows_by_id.get(pid), pid, id_to_player)
        for pid in (str(p) for p in team.get("playerIds") or [])
    ]
    picks, pick_ownership = _roster_picks(team, contract)
    missing_data: list[Any] = [
        {"assetId": p["assetId"], "reason": p.get("reason")}
        for p in players
        if p["valueState"] == "unpriced"
    ]
    if pick_ownership["state"] == "unavailable":
        missing_data.append({"field": "picks", "reason": pick_ownership["reason"]})
    else:
        missing_data += [
            {"assetId": p["assetId"], "reason": p["reason"]}
            for p in picks or []
            if p["valueState"] == "unpriced"
        ]
    missing_data += _roster_provenance_missing(roster_provenance)
    return {
        "status": "partial" if missing_data else "ok",
        "leagueKey": league.key,
        "rosterId": team.get("roster_id"),
        "teamName": team.get("name"),
        "players": players,
        "picks": picks,
        "pickOwnership": pick_ownership,
        "rosters": roster_provenance,
        "confidence": f"rosters_{roster_provenance.get('state')}",
        "sourceProvenance": [
            "Sleeper live overlay"
            if roster_provenance["delivery"] == "live_overlay"
            else "Sleeper roster snapshot in the canonical contract",
            "Chase Upside canonical rankings contract",
            "canonical pick value resolver",
        ],
        **_board_metadata(contract),
        "dataTimestamps": {
            "rankings": _contract_stamp(contract),
            "rosters": roster_provenance.get("asOf"),
        },
        "missingData": missing_data,
    }


def _trade_team_summary(entry: dict[str, Any], *, detail: bool) -> dict[str, Any]:
    analysis = entry.get("analysis") if isinstance(entry.get("analysis"), dict) else {}
    out = {
        "rosterId": entry.get("rosterId"),
        "team": entry.get("team"),
        "gives": entry.get("gives"),
        "receives": entry.get("receives"),
        "category": entry.get("category"),
        "categoryText": entry.get("categoryText"),
        "categoryReason": entry.get("categoryReason"),
        "fairness": entry.get("fairness"),
        "decision": analysis.get("decision"),
        "confidence": analysis.get("confidence"),
        "unavailableDimensions": analysis.get("unavailableDimensions"),
        "unverifiableAssetIds": entry.get("unverifiableAssetIds"),
    }
    if detail:
        redacted: set[str] = set()
        out["analysis"] = _without_source_evidence(analysis, redacted)
        out["simulation"] = _without_source_evidence(entry.get("simulation"), redacted)
        out["detailRedactedKeys"] = sorted(redacted)
    return out


def _without_source_evidence(value: Any, redacted: set[str]) -> Any:
    """A copy of ``value`` with every ``SOURCE_EVIDENCE_KEYS`` key removed at
    any depth; removed key names are added to ``redacted``."""
    if isinstance(value, dict):
        out = {}
        for key, item in value.items():
            if key in SOURCE_EVIDENCE_KEYS:
                redacted.add(key)
                continue
            out[key] = _without_source_evidence(item, redacted)
        return out
    if isinstance(value, (list, tuple)):
        return [_without_source_evidence(item, redacted) for item in value]
    return value


async def _trade_analysis(server: Any, args: dict[str, Any]) -> dict[str, Any]:
    from src.api import compute_admission  # noqa: PLC0415
    from src.api.feature_flags import is_enabled  # noqa: PLC0415
    from src.trade import analyze_service  # noqa: PLC0415
    from src.trade import trade_ledger  # noqa: PLC0415

    league, missing = _resolve_league(server, args.get("leagueKey"))
    if missing is not None:
        return missing
    # One body parser for every N-team surface: the private route's own.
    parsed, bad_field = server._parse_multi_body(
        {
            "teams": args.get("teams"),
            "assets": args.get("assets"),
            "useTeamContext": args.get("useTeamContext", True),
            "teamGoals": args.get("teamGoals") or {},
            "counterfactuals": False,
            "perspectiveRosterId": args.get("perspectiveRosterId"),
        }
    )
    if parsed is None:
        return _missing("invalid_trade_request", missing=[bad_field])
    if len(set(parsed["teams"])) >= 3 and not is_enabled("trade_multi_team_analysis"):
        # The 2-team analysis is the War Room's; 3+ teams is behind the
        # owner's multi-team flag everywhere, including here.
        return _missing("multi_team_analysis_disabled", missing=["trade_multi_team_analysis"])
    if not analyze_service.package_model_ready():
        return _missing("package_model_unavailable", missing=["active_package_model"])
    contract, roster_provenance, missing = await _contract_with_league_rosters(server, league)
    if missing is not None:
        return missing
    try:
        snap = trade_ledger.snapshot_for(
            contract,
            league_key=league.key,
            roster_settings=dict(league.roster_settings or {}),
        )
    except LookupError:
        return _missing("league_rosters_not_ready", missing=["league_rosters"])
    try:
        ledger = trade_ledger.validate_ledger(
            snap, teams=parsed["teams"], legs=parsed["legs"], policy=trade_ledger.private_policy()
        )
    except trade_ledger.LedgerError as err:
        return _missing(
            err.reason,
            missing=[err.reason],
            assetIds=list(err.asset_ids),
            rosterIds=list(err.roster_ids),
        )
    perspective = parsed["perspective"]
    if perspective is not None and perspective not in ledger.teams:
        return _missing("perspective_not_in_trade", missing=["perspectiveRosterId"])
    goals = {rid: g for rid, g in parsed["teamGoals"].items() if rid in ledger.teams}
    # The same engine as the private multi-team route, so the same process
    # bound on concurrent (GIL-bound) computations: a full route refuses at
    # once, retryably, instead of queueing.
    admission = compute_admission.admission_for(compute_admission.ROUTE_ANALYZE_MULTI)
    try:
        result = await admission.admit(
            lambda: server.run_in_threadpool(
                analyze_service.analyze_trade_n,
                snap,
                ledger,
                mode="team_context" if parsed["useTeamContext"] else "asset_only",
                counterfactuals=False,
                team_goals=goals,
            )
        )
    except compute_admission.AdmissionRejected as exc:
        return _missing(
            f"analysis_{exc.reason}",
            missing=["trade_analysis_capacity"],
            retryable=True,
            retryAfterSeconds=exc.retry_after_seconds,
        )
    except analyze_service.PackageModelUnavailable:
        return _missing("package_model_unavailable", missing=["active_package_model"])
    except analyze_service.ConservationViolation:
        server.log.error("Chase Upside MCP trade analysis failed its conservation check")
        return _missing("trade_analysis_refused", missing=["ledger_conservation"])
    payload = analyze_service.multi_team_payload(
        result,
        snap=snap,
        ledger=ledger,
        league_key=league.key,
        perspective=perspective,
        expected_generation=None,
    )
    detail = bool(args.get("includeDetail"))
    teams = [_trade_team_summary(t, detail=detail) for t in payload["teams"]]
    missing_data: list[Any] = []
    for t in teams:
        for dim in t.get("unavailableDimensions") or []:
            missing_data.append({"rosterId": t["rosterId"], "dimension": dim})
        for aid in t.get("unverifiableAssetIds") or []:
            missing_data.append(
                {"rosterId": t["rosterId"], "assetId": aid, "reason": "ownership_unverifiable"}
            )
    missing_data += _roster_provenance_missing(roster_provenance)
    return {
        "status": "partial" if missing_data else "ok",
        "leagueKey": league.key,
        "mode": payload["mode"],
        "teamCount": payload["teamCount"],
        "perspectiveRosterId": perspective,
        "teams": teams,
        "summary": payload["summary"],
        "ledger": payload["ledger"],
        "packageModel": payload["packageModel"],
        "recommendationOnly": True,
        "recorded": False,
        "confidence": "per_team_decision",
        "sourceProvenance": [
            "Chase Upside canonical rankings contract",
            "Chase Upside trade ledger (ownership verified against one roster snapshot)",
            "Chase Upside trade analysis engine (analyze_trade_n)",
        ],
        "rosters": roster_provenance,
        **_board_metadata(contract),
        "dataTimestamps": {
            "rankings": _contract_stamp(contract),
            "boardGeneration": payload["generation"],
            "rosters": payload["rosters"].get("asOf"),
        },
        "missingData": missing_data,
    }


def _value_history(server: Any, args: dict[str, Any]) -> dict[str, Any]:
    from datetime import date  # noqa: PLC0415

    from src.history import asof  # noqa: PLC0415
    from src.history.keys import pick_asset_key, player_asset_key  # noqa: PLC0415

    league, missing = _resolve_league(server, args.get("leagueKey"))
    if missing is not None:
        return missing
    # The ledger's canonical lane records THIS scoring profile's board, so a
    # league whose scoring is not proven identical gets no history either.
    _contract, missing = _board_for_league(server, league)
    if missing is not None:
        return missing
    for key in ("asOfDate", "start", "end"):
        if args.get(key):
            try:
                date.fromisoformat(args[key])
            except ValueError:
                return _missing("invalid_date", missing=[key])
    asset_key = (
        player_asset_key(args["playerId"], None, None)
        if args.get("playerId")
        else pick_asset_key(args.get("pickName"))
    )
    if not asset_key:
        return _missing("asset_key_unresolvable", missing=["asset"])
    base = {
        "leagueKey": league.key,
        "assetKey": asset_key,
        "lane": asof.LANE_CANONICAL,
        "historyFloor": asof.HISTORY_FLOOR,
        "confidence": "recorded_observations",
        "sourceProvenance": ["Chase Upside temporal ledger (canonical_board lane)"],
    }
    if args.get("asOfDate"):
        point = asof.value_as_of(asset_key, args["asOfDate"])
        available = point.get("fidelity") != asof.FIDELITY_UNAVAILABLE
        return {
            "status": "ok" if available else "unavailable",
            **base,
            "point": point,
            "dataAsOf": point.get("observedAt") or point.get("observedDate"),
            "missingData": [] if available else [point.get("missingReason")],
        }
    hist = asof.series(asset_key, start=args.get("start"), end=args.get("end"))
    points = hist.get("points") or []
    truncated = len(points) > MAX_HISTORY_POINTS
    points = points[-MAX_HISTORY_POINTS:]
    return {
        "status": "ok" if points else "unavailable",
        **base,
        "start": hist.get("start"),
        "end": hist.get("end"),
        "points": [
            {
                "date": p.get("observedDate"),
                "value": p.get("value"),
                "rank": p.get("rank"),
                "tier": p.get("tier"),
                "confidence": p.get("confidence"),
            }
            for p in points
        ],
        "truncatedToLatest": MAX_HISTORY_POINTS if truncated else None,
        "gapsPreserved": True,
        "dataAsOf": points[-1].get("observedDate") if points else None,
        "missingData": [] if points else ["no_recorded_observations"],
    }


async def call_tool(name: str, arguments: dict[str, Any], request: Request) -> dict[str, Any]:
    del request  # identity is the service token + owner header, checked upstream
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
    if name == "get_value_history":
        return _value_history(server, arguments)
    raise ToolArgumentError("unknown_tool")


class ToolTimeBudgetExceeded(Exception):
    """The tool call did not answer within ``TOOL_TIME_BUDGET_SECONDS``."""


def _retrieve_quietly(task: asyncio.Future) -> None:
    # A call that outlived its caller still finishes; consume its outcome so
    # it is never "exception was never retrieved" (class only, no content).
    if not task.cancelled() and task.exception() is not None:
        _server().log.warning(
            "Chase Upside MCP tool finished after its time budget: %s",
            type(task.exception()).__name__,
        )


async def _call_tool_within_budget(
    name: str, arguments: dict[str, Any], request: Request
) -> dict[str, Any]:
    task = asyncio.ensure_future(call_tool(name, arguments, request))
    try:
        return await asyncio.wait_for(asyncio.shield(task), TOOL_TIME_BUDGET_SECONDS)
    except TimeoutError:
        task.add_done_callback(_retrieve_quietly)
        raise ToolTimeBudgetExceeded from None


def _json_depth_exceeds(raw: bytes | bytearray, limit: int) -> bool:
    """True when ``raw`` nests arrays/objects deeper than ``limit``.

    A linear byte scan (the body is already bounded by ``MAX_REQUEST_BYTES``)
    that skips string contents, run BEFORE ``json.loads`` so a deeply nested
    body is refused without recursing.  Malformed input is left to the parser.
    """
    depth = 0
    in_string = False
    escaped = False
    for byte in raw:
        if in_string:
            if escaped:
                escaped = False
            elif byte == 0x5C:  # backslash
                escaped = True
            elif byte == 0x22:  # quote
                in_string = False
        elif byte == 0x22:
            in_string = True
        elif byte in (0x5B, 0x7B):  # [ {
            depth += 1
            if depth > limit:
                return True
        elif byte in (0x5D, 0x7D):  # ] }
            depth -= 1
    return False


def _secret_matches(supplied: str, expected: str) -> bool:
    # Bytes, so a non-ASCII header cannot raise inside compare_digest.
    return hmac.compare_digest(
        supplied.encode("utf-8", "surrogateescape"), expected.encode("utf-8", "surrogateescape")
    )


@router.post("/api/chase-upside/mcp")
async def mcp_endpoint(request: Request):
    expected = os.getenv("CHASE_UPSIDE_MCP_API_TOKEN", "")
    owner_id = os.getenv("CHASE_UPSIDE_MCP_OWNER_USER_ID", "")
    supplied = request.headers.get("authorization", "")
    bearer = supplied[7:] if supplied.lower().startswith("bearer ") else ""
    if len(expected) < 32 or not _secret_matches(bearer, expected):
        return _plain_error(401, "unauthorized")
    if not owner_id or not _secret_matches(
        request.headers.get("x-chase-upside-owner-id", ""), owner_id
    ):
        return _plain_error(403, "forbidden")
    raw = bytearray()
    async for chunk in request.stream():
        raw.extend(chunk)
        if len(raw) > MAX_REQUEST_BYTES:
            return _plain_error(413, "request_too_large")
    if _json_depth_exceeds(raw, MAX_JSON_DEPTH):
        return _plain_error(400, "json_too_deep")
    try:
        message = json.loads(raw)
    except RecursionError:
        return _plain_error(400, "json_too_deep")
    except (UnicodeDecodeError, json.JSONDecodeError):
        return _plain_error(400, "invalid_json")
    if not isinstance(message, dict):
        return _plain_error(400, "invalid_request")
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
    if request_id is None or isinstance(request_id, (dict, list, bool)):
        return _protocol_error(None, -32600, "Invalid Request")
    protocol_error = _validate_protocol_request(request, message)
    if protocol_error is not None:
        return protocol_error
    params = message.get("params")
    if method == "server/discover":
        result = _cacheable_result(
            {"supportedVersions": [PROTOCOL_VERSION], "capabilities": {"tools": {}}}
        )
    elif method == "tools/list":
        result = _cacheable_result({"tools": TOOLS})
    elif method == "tools/call":
        name = params.get("name") if isinstance(params, dict) else None
        arguments = params.get("arguments") if isinstance(params, dict) else None
        if arguments is None:
            arguments = {}
        try:
            if not isinstance(arguments, dict):
                raise ToolArgumentError("invalid_argument_type")
            result = _tool_result(
                await _call_tool_within_budget(str(name or ""), arguments, request)
            )
        except ToolArgumentError as exc:
            result = _tool_result(
                {"status": "unavailable", "reason": str(exc), "missingData": [str(exc)]}
            )
            result["isError"] = True
        except ToolTimeBudgetExceeded:
            result = _tool_result(
                {
                    "status": "unavailable",
                    "reason": "tool_time_budget_exceeded",
                    "retryable": True,
                    "missingData": ["tool_time_budget_exceeded"],
                }
            )
            result["isError"] = True
        except ValueError:
            # An engine's own ValueError text is internal; never echo it.
            _server().log.warning("Chase Upside MCP tool rejected its input", exc_info=True)
            result = _tool_result(
                {
                    "status": "unavailable",
                    "reason": "tool_request_rejected",
                    "missingData": ["tool_request_rejected"],
                }
            )
            result["isError"] = True
        except Exception:  # noqa: BLE001 — never return backend details or secrets
            _server().log.exception("Chase Upside MCP tool failed")
            result = _tool_result(
                {
                    "status": "unavailable",
                    "reason": "tool_execution_failed",
                    "missingData": ["backend_error"],
                }
            )
            result["isError"] = True
    elif method == "ping":
        result = {"resultType": "complete", "_meta": SERVER_INFO_META}
    else:
        return JSONResponse(
            {
                "jsonrpc": "2.0",
                "id": request_id,
                "error": {"code": -32601, "message": "Method not found"},
            },
            status_code=404,
            headers={"Cache-Control": "no-store"},
        )
    return JSONResponse(
        {"jsonrpc": "2.0", "id": request_id, "result": result},
        headers={"Cache-Control": "no-store"},
    )
