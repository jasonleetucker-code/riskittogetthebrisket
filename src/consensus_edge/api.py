"""FastAPI router for /api/consensus-edge/*.

Mounted from ``server.py`` via ``app.include_router`` — the same pattern
as ``src/ros/api.py``, which is the one clean router precedent among 80
inline route declarations.

Isolation invariant: these handlers read ``latest_contract_data`` and
never mutate it, never write ``rankDerivedValue``, and never touch an
existing route's output.  Every response is gated on the
``consensus_edge`` flag (default OFF) and stamps ``experimental: true``,
its model version, and its parameter-set id.

The board is expensive — three pipeline passes over the payload — so it
is cached per (contract identity, params) and recomputed only when one
of those changes.
"""

from __future__ import annotations

import threading
from typing import Any

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from starlette.concurrency import run_in_threadpool

from src.consensus_edge import (
    MODEL_VERSION,
    inputs as inputs_mod,
    params as params_mod,
    score as score_mod,
    service,
)

router = APIRouter(prefix="/api/consensus-edge", tags=["consensus-edge"])

_CACHE_LOCK = threading.Lock()
_CACHE: dict[str, Any] = {}


def _flag_enabled() -> bool:
    from src.api import feature_flags  # noqa: PLC0415 — read at call time so tests can toggle

    return bool(feature_flags.is_enabled("consensus_edge"))


def _disabled_response() -> JSONResponse:
    return JSONResponse(
        status_code=503,
        content={
            "error": "feature_disabled",
            "flag": "consensus_edge",
            "message": (
                "Consensus Edge is switched off. Only one of its three "
                "components has an out-of-sample result, so it ships "
                "behind a flag until the others do."
            ),
        },
    )


def _contract() -> dict[str, Any] | None:
    import sys  # noqa: PLC0415

    server = sys.modules.get("server") or sys.modules.get("__main__")
    return getattr(server, "latest_contract_data", None) if server else None


def _board(contract: dict[str, Any]) -> dict[str, Any]:
    """Build or reuse the board for this contract.

    Keyed on the scrape timestamp plus the parameter-set id, so a new
    scrape or a parameter edit invalidates it and nothing else does.

    This function is where the feature's largest defect lived: it called
    ``build_board(contract, params=params)`` and passed none of the
    optional inputs, so Sharp Flow and Opportunity were permanently
    absent and freshness permanently unknown — pinning confidence at a
    55.03 ceiling and making Strong labels unreachable. They are now
    resolved by ``consensus_edge.inputs``, shared with the daily
    snapshot job so the board we record cannot be built from less
    evidence than the board we serve. Each still degrades honestly to
    None when its data does not exist.
    """
    params = params_mod.load()
    key = f"{contract.get('scrapeTimestamp')}|{params.get('paramSetId')}"
    with _CACHE_LOCK:
        if _CACHE.get("key") == key:
            return _CACHE["board"]
    board = service.build_board(
        contract,
        params=params,
        hours_stale=service.resolve_hours_stale(contract),
        **inputs_mod.resolve(contract),
    )
    with _CACHE_LOCK:
        _CACHE["key"] = key
        _CACHE["board"] = board
    return board


def _envelope(extra: dict[str, Any]) -> dict[str, Any]:
    base = {
        "modelVersion": MODEL_VERSION,
        "paramSetId": params_mod.load().get("paramSetId"),
        "experimental": True,
    }
    base.update(extra)
    return base


@router.get("/players")
async def get_players(request: Request):
    """The full scored board."""
    if not _flag_enabled():
        return _disabled_response()
    contract = _contract()
    if not contract:
        return JSONResponse(
            status_code=503,
            content={"error": "data_not_ready", "message": "No contract loaded yet."},
        )
    board = await run_in_threadpool(_board, contract)
    return JSONResponse(content=_envelope(board))


@router.get("/top")
async def get_top(request: Request):
    """Top qualifying buys and sells, merit-ranked.

    No positional quota: a player is never promoted into this list to
    represent his position. Positions with nothing qualifying are simply
    absent, and the client says so rather than reaching further down.
    """
    if not _flag_enabled():
        return _disabled_response()
    contract = _contract()
    if not contract:
        return JSONResponse(
            status_code=503,
            content={"error": "data_not_ready", "message": "No contract loaded yet."},
        )
    try:
        limit = max(1, min(50, int(request.query_params.get("limit") or 20)))
    except (TypeError, ValueError):
        limit = 20
    board = await run_in_threadpool(_board, contract)
    movers = service.top_movers(board, limit=limit)
    return JSONResponse(
        content=_envelope(
            {
                "buys": movers["buys"],
                "sells": movers["sells"],
                "limit": limit,
                "coverage": board.get("coverage"),
                "sharpFlowStatus": board.get("sharpFlowStatus"),
                "caveats": board.get("caveats"),
            }
        )
    )


@router.get("/player/{player_key:path}")
async def get_player(player_key: str, request: Request):
    """One player's full evidence."""
    if not _flag_enabled():
        return _disabled_response()
    contract = _contract()
    if not contract:
        return JSONResponse(
            status_code=503,
            content={"error": "data_not_ready", "message": "No contract loaded yet."},
        )
    board = await run_in_threadpool(_board, contract)
    for row in board.get("players") or []:
        if row.get("playerKey") == player_key:
            return JSONResponse(content=_envelope({"player": row}))
    return JSONResponse(
        status_code=404,
        content={"error": "not_found", "message": f"No Consensus Edge row for {player_key!r}."},
    )


@router.get("/methodology")
async def get_methodology(request: Request):
    """What each component is, and which have been validated.

    Served even when the flag is off: a user who cannot see the board
    should still be able to read why it exists and what it does not
    claim.
    """
    params = params_mod.load()
    return JSONResponse(
        content=_envelope(
            {
                "components": score_mod.COMPONENT_VALIDATION,
                "compositeWeights": (params.get("composite") or {}).get("weights"),
                "weightsAreFitted": False,
                "classification": params.get("classification"),
                "docs": [
                    "docs/consensus-edge/METHODOLOGY.md",
                    "docs/consensus-edge/DECISIONS.md",
                ],
                "validationTarget": "market movement, not fantasy production",
                "enabled": _flag_enabled(),
            }
        )
    )


@router.get("/health")
async def get_health(request: Request):
    """Coverage and degradation, for monitoring."""
    if not _flag_enabled():
        return _disabled_response()
    contract = _contract()
    if not contract:
        return JSONResponse(
            content=_envelope({"status": "data_not_ready", "coverage": None}),
            status_code=503,
        )
    board = await run_in_threadpool(_board, contract)
    players = board.get("players") or []
    labels: dict[str, int] = {}
    for row in players:
        labels[str(row.get("label"))] = labels.get(str(row.get("label")), 0) + 1
    return JSONResponse(
        content=_envelope(
            {
                "status": board.get("status"),
                "playersScored": sum(1 for r in players if r.get("score") is not None),
                "playersTotal": len(players),
                "labelDistribution": labels,
                "coverage": board.get("coverage"),
                "sharpFlowStatus": board.get("sharpFlowStatus"),
                "generatedAt": board.get("generatedAt"),
                # Which components are live, what confidence ceiling that
                # implies, and whether Strong labels can appear at all.
                # Without these, a board with two dark components is
                # indistinguishable from one that simply found nothing.
                "componentAvailability": board.get("componentAvailability"),
                "confidenceCeiling": board.get("confidenceCeiling"),
                "strongLabelThreshold": board.get("strongLabelThreshold"),
                "strongLabelsReachable": board.get("strongLabelsReachable"),
                # Whether the served board is running the configuration
                # the published measurement was produced under. A monitor
                # that cannot see this cannot tell a board whose numbers
                # are still described by the committed rho from one whose
                # numbers are not.
                "validationScope": board.get("validationScope"),
                "inputs": board.get("inputs"),
                "contractScrapedAt": contract.get("scrapeTimestamp"),
            }
        )
    )
