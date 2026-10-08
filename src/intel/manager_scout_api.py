"""HTTP surface for Manager Scout: ``GET /api/manager-scout`` (C6-MGR-01).

PRIVATE.  Manager tendencies are decision intelligence (CLAUDE.md public/
private boundary; OWNER_PRODUCT_BACKLOG_SPEC §7 "Private only"), so:

1. ``server.py::_private_api_gate`` 401s any request without a session —
   ``/api/manager-scout`` is deliberately absent from every public allowlist,
   pinned by ``tests/intel/test_manager_scout_privacy.py``;
2. the handler refuses outright (401) when ``server.py`` has not wired a
   league resolver: an unwired router never serves.

League-scoped through ``server.py::_resolve_league_for_request`` with
``require_loaded_contract=True``: the current display names come from the
loaded contract's ``sleeper.teams``, so a contract built for a different
league is a 503 ``data_not_ready`` rather than another league's names joined
onto this league's history.

Read-only, GET only, ``Cache-Control: no-store``.  The payload is assembled by
``manager_scout.cached_manager_scout`` (5-minute per-process memo keyed by the
input files' signatures); it reads the canonical stores and writes nothing.
"""

from __future__ import annotations

import logging
from typing import Any, Callable

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from starlette.concurrency import run_in_threadpool

from src.intel import manager_scout

log = logging.getLogger("manager_scout.api")

router = APIRouter(prefix="/api/manager-scout", tags=["manager-scout"])

_NO_STORE = {"Cache-Control": "no-store"}

_league_resolver: Callable[[Request], Any] | None = None
_contract_provider: Callable[[], Any] | None = None


def configure(
    *,
    league_resolver: Callable[[Request], Any] | None,
    contract_provider: Callable[[], Any] | None,
) -> None:
    """``server.py`` injects its league resolver and contract accessor.

    ``league_resolver(request)`` returns the resolved ``LeagueConfig`` or
    raises an error carrying ``json_response()`` (``LeagueResolutionError``).
    """
    global _league_resolver, _contract_provider
    _league_resolver = league_resolver
    _contract_provider = contract_provider


def _current_teams(contract: Any, league_key: str) -> list[dict[str, Any]]:
    """This league's current teams from the loaded contract — or none.

    Only when the contract's ``sleeperDataReady`` block belongs to THIS
    league; otherwise names are absent (``displayName: null``), never
    borrowed from whichever league the server happens to hold.
    """
    if not isinstance(contract, dict):
        return []
    meta = contract.get("meta") or {}
    if meta.get("leagueKey") and meta.get("leagueKey") != league_key:
        return []
    if meta.get("sleeperDataReady") is False:
        return []
    teams = (contract.get("sleeper") or {}).get("teams")
    return [t for t in teams if isinstance(t, dict)] if isinstance(teams, list) else []


@router.get("")
async def get_manager_scout(request: Request) -> JSONResponse:
    if _league_resolver is None:
        return JSONResponse(
            status_code=401,
            content={"error": "auth_required", "message": "Sign-in required."},
            headers=_NO_STORE,
        )
    try:
        league_cfg = _league_resolver(request)
    except Exception as err:  # noqa: BLE001
        responder = getattr(err, "json_response", None)
        if callable(responder):
            resp = responder()
            resp.headers["Cache-Control"] = "no-store"
            return resp
        log.exception("manager-scout league resolution failed")
        return JSONResponse(
            status_code=503,
            content={"error": "manager_scout_unavailable", "message": "League unresolved."},
            headers=_NO_STORE,
        )

    contract = _contract_provider() if _contract_provider is not None else None
    teams = _current_teams(contract, league_cfg.key)
    try:
        payload = await run_in_threadpool(
            manager_scout.cached_manager_scout,
            league_cfg.key,
            league_cfg=league_cfg,
            current_teams=teams,
        )
    except Exception:  # noqa: BLE001 — a store fault is an unavailable state
        log.exception("manager-scout build failed for %s", league_cfg.key)
        return JSONResponse(
            status_code=503,
            content={
                "error": "manager_scout_unavailable",
                "message": "Manager Scout could not read its sources.",
                "leagueKey": league_cfg.key,
            },
            headers=_NO_STORE,
        )
    return JSONResponse(content=payload, headers=_NO_STORE)
