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

Read-only, ``Cache-Control: no-store``.  ``POST /api/manager-scout/offer-evidence``
(TC-B / TCM-O12) answers the same question the generated-trade cards answer —
how the counterparty's OWN completed trades line up with ONE package — for the
trade being built on /trade.  It is a POST only because a package is a body;
it writes nothing.  The payload is assembled by
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
    # Today's values only from a board loaded for THIS league's scoring —
    # the same gate that admits its team names.
    board = contract if teams else None
    try:
        payload = await run_in_threadpool(
            manager_scout.cached_manager_scout,
            league_cfg.key,
            league_cfg=league_cfg,
            current_teams=teams,
            contract=board,
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


# ── POST /api/manager-scout/offer-evidence (TC-B / TCM-O12) ──────────────

#: A calculator package is bounded (the finder's largest shapes are 3 pieces;
#: the calculator allows more).  A larger body is refused, never truncated.
MAX_EVIDENCE_ASSETS = 40
_MAX_NAME_LEN = 120


class _BadBody(ValueError):
    def __init__(self, field: str, reason: str) -> None:
        super().__init__(f"{field}: {reason}")
        self.field = field
        self.reason = reason


def _team_name(value: Any, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise _BadBody(field, "required text")
    text = value.strip()
    if len(text) > _MAX_NAME_LEN:
        raise _BadBody(field, f"longer than {_MAX_NAME_LEN}")
    return text


def _package_side(value: Any, field: str) -> list[dict[str, Any]]:
    """``[{name, position?, isPick?}]`` -> the shape ``offer_evidence`` reads."""
    if not isinstance(value, list):
        raise _BadBody(field, "must be a list")
    if len(value) > MAX_EVIDENCE_ASSETS:
        raise _BadBody(field, f"at most {MAX_EVIDENCE_ASSETS} assets")
    out: list[dict[str, Any]] = []
    for item in value:
        if not isinstance(item, dict):
            raise _BadBody(field, "asset must be an object")
        name = item.get("name")
        if not isinstance(name, str) or not name.strip() or len(name) > _MAX_NAME_LEN:
            raise _BadBody(f"{field}.name", "required text")
        position = item.get("position")
        out.append(
            {
                "name": name.strip(),
                "position": position.strip()[:8] if isinstance(position, str) else None,
                "isPick": bool(item.get("isPick")),
            }
        )
    return out


def evidence_request(body: Any) -> dict[str, Any]:
    """Validate an offer-evidence request body (raises ``_BadBody``)."""
    if not isinstance(body, dict):
        raise _BadBody("body", "must be an object")
    my_team = _team_name(body.get("myTeam"), "myTeam")
    opponent = _team_name(body.get("opponent"), "opponent")
    if my_team == opponent:
        raise _BadBody("opponent", "must be another team")
    return {
        "myTeam": my_team,
        "opponent": opponent,
        "theyReceive": _package_side(body.get("theyReceive"), "theyReceive"),
        "theySend": _package_side(body.get("theySend"), "theySend"),
    }


@router.post("/offer-evidence")
async def post_offer_evidence(request: Request) -> JSONResponse:
    """The counterparty's trade-history evidence for one calculator package.

    Body (``leagueKey`` travels in the QUERY string, like every scout call)::

        {"myTeam": str, "opponent": str,
         "theyReceive": [{"name", "position"?, "isPick"?}],
         "theySend":    [{"name", "position"?, "isPick"?}]}

    ``theyReceive`` is what the OPPONENT would get (what the user gives).  The
    answer is ``manager_scout.offer_evidence`` verbatim — descriptive counts
    with their samples, never a fit grade or an acceptance probability — plus
    ``leagueKey`` / ``opponent``.  Team names are this league's CURRENT
    display names from the contract loaded for it; an unknown name is a 400,
    never another team's history.
    """
    if _league_resolver is None:
        return JSONResponse(
            status_code=401,
            content={"error": "auth_required", "message": "Sign-in required."},
            headers=_NO_STORE,
        )
    try:
        body = await request.json()
    except Exception:  # noqa: BLE001 — a body that is not JSON is a client error
        body = None
    try:
        req = evidence_request(body)
    except _BadBody as bad:
        return JSONResponse(
            status_code=400,
            content={"error": "invalid_body", "field": bad.field, "reason": bad.reason},
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
        log.exception("manager-scout offer-evidence league resolution failed")
        return JSONResponse(
            status_code=503,
            content={"error": "manager_scout_unavailable", "message": "League unresolved."},
            headers=_NO_STORE,
        )

    contract = _contract_provider() if _contract_provider is not None else None
    teams = _current_teams(contract, league_cfg.key)
    owner_of = {
        str(t.get("name") or ""): str(t.get("ownerId") or "").strip()
        for t in teams
        if str(t.get("name") or "")
    }
    for field in ("myTeam", "opponent"):
        if req[field] not in owner_of:
            return JSONResponse(
                status_code=400,
                content={
                    "error": "unknown_team",
                    "field": field,
                    "message": "That team is not in this league's loaded rosters.",
                    "leagueKey": league_cfg.key,
                },
                headers=_NO_STORE,
            )
    try:
        scout = await run_in_threadpool(
            manager_scout.cached_manager_scout,
            league_cfg.key,
            league_cfg=league_cfg,
            current_teams=teams,
            contract=contract,
        )
    except Exception:  # noqa: BLE001 — a store fault is an unavailable state
        log.exception("manager-scout offer-evidence build failed for %s", league_cfg.key)
        scout = None
    evidence = manager_scout.offer_evidence(
        scout,
        opponent_owner_id=owner_of.get(req["opponent"]) or None,
        requester_owner_id=owner_of.get(req["myTeam"]) or None,
        they_receive=req["theyReceive"],
        they_send=req["theySend"],
    )
    return JSONResponse(
        content={**evidence, "leagueKey": league_cfg.key, "opponent": req["opponent"]},
        headers=_NO_STORE,
    )
