"""HTTP surface for Manager Intelligence: ``GET /api/manager-intel/profile``
and ``GET /api/manager-intel/activity`` (Batches B1 + B2 + the feed).

PRIVATE decision intelligence (MASTER_PRODUCT_PLAN §5; owner directive
2026-10-16).  ``server.py::_private_api_gate`` 401s any request without a
session because ``/api/manager-intel`` is on no public allowlist, and this
router additionally refuses guest passes and unwired deployments.

Query: ``username`` (a Sleeper username or numeric user id), optional
``scope`` (``dynasty`` default / ``keeper`` / ``redraft`` / ``unknown``) and
``season``.  Rate-limited per signed-in user, because every lookup spends
real calls against Sleeper's public API.  Behind the ``manager_intelligence``
feature flag (off → 503 ``feature_disabled``).

Status mapping: ``not_found`` → 404; ``rate_limited`` (Sleeper's 429 or ours)
→ 429; ``upstream_unavailable`` → 503; ``ok`` / ``partial`` → 200 (a partial
answer names its unreadable leagues instead of hiding them).
"""

from __future__ import annotations

import logging
import re
from typing import Any, Callable

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from starlette.concurrency import run_in_threadpool

from src.intel import manager_activity, manager_portfolio

log = logging.getLogger("manager_intel.api")

router = APIRouter(prefix="/api/manager-intel", tags=["manager-intel"])

_NO_STORE = {"Cache-Control": "no-store"}

#: Sleeper usernames are letters, digits and underscores; a user id is digits.
_USERNAME_RE = re.compile(r"^[A-Za-z0-9_]{1,40}$")
_SEASON_RE = re.compile(r"^20\d\d$")
_LEAGUE_ID_RE = re.compile(r"^\d{1,24}$")

RATE_CAPACITY = 30
RATE_WINDOW_SECONDS = 600.0

#: Activity lookups read every week of every league (hundreds of Sleeper
#: calls), so they get their own, tighter per-user bucket.
ACTIVITY_RATE_CAPACITY = 10
ACTIVITY_RATE_WINDOW_SECONDS = 600.0

_session_provider: Callable[[Request], Any] | None = None
_contract_provider: Callable[[], Any] | None = None
_asof_resolver_provider: Callable[[], Any] | None = None


def configure(
    *,
    session_provider: Callable[[Request], Any] | None,
    contract_provider: Callable[[], Any] | None,
    asof_resolver_provider: Callable[[], Any] | None = None,
) -> None:
    """``server.py`` injects its session reader, live-contract accessor and
    (optionally) the at-the-time resolver FACTORY provider — the same one
    ``POST /api/trades/asof-grades`` uses; it returns ``None`` when the
    temporal ledger does not exist."""
    global _session_provider, _contract_provider, _asof_resolver_provider
    _session_provider = session_provider
    _contract_provider = contract_provider
    _asof_resolver_provider = asof_resolver_provider


def _error(code: str, message: str, status: int, **extra: Any) -> JSONResponse:
    return JSONResponse(
        {"error": code, "message": message, **extra}, status_code=status, headers=_NO_STORE
    )


def _gate(request: Request) -> tuple[dict[str, Any] | None, JSONResponse | None]:
    """Flag, wiring, session and guest checks shared by every route."""
    from src.api.feature_flags import is_enabled  # noqa: PLC0415

    if not is_enabled("manager_intelligence"):
        return None, _error("feature_disabled", "Manager Intelligence is switched off.", 503)
    if _session_provider is None or _contract_provider is None:
        return None, _error("auth_required", "Sign-in required.", 401)
    session = _session_provider(request)
    if not session:
        return None, _error("auth_required", "Sign-in required.", 401)
    if session.get("auth_method") == "guest_pass":
        return None, _error("guest_read_only", "Guest passes cannot run manager lookups.", 403)
    return session, None


def _rate_limited(key: str, capacity: int, window: float) -> JSONResponse | None:
    from src.api import rate_limit as _rl  # noqa: PLC0415

    limited, retry_after = _rl.should_rate_limit_key(key, capacity=capacity, window_seconds=window)
    if not limited:
        return None
    return JSONResponse(
        {
            "error": "rate_limited",
            "message": "Too many lookups — wait a moment and try again.",
            "retryAfterSeconds": retry_after,
        },
        status_code=429,
        headers={**_NO_STORE, "Retry-After": str(retry_after)},
    )


def _status_error(payload: dict[str, Any], username: str) -> JSONResponse | None:
    status = payload.get("status")
    if status == manager_portfolio.STATUS_NOT_FOUND:
        return _error("not_found", f"No Sleeper user named {username!r}.", 404)
    if status == manager_portfolio.STATUS_RATE_LIMITED:
        return _error(
            "upstream_rate_limited", "Sleeper is rate-limiting us — try again shortly.", 429
        )
    if status == manager_portfolio.STATUS_UPSTREAM_UNAVAILABLE:
        return _error("upstream_unavailable", "Sleeper could not be reached.", 503)
    return None


@router.get("/profile")
async def get_profile(request: Request) -> JSONResponse:
    session, refusal = _gate(request)
    if refusal is not None:
        return refusal

    username = str(request.query_params.get("username") or "").strip()
    if not _USERNAME_RE.match(username):
        return _error(
            "invalid_username",
            "Enter a Sleeper username (letters, numbers and underscores).",
            400,
        )
    scope = str(request.query_params.get("scope") or manager_portfolio.SCOPE_DYNASTY).lower()
    if scope not in manager_portfolio.SCOPES:
        return _error(
            "invalid_scope", f"scope must be one of {list(manager_portfolio.SCOPES)}.", 400
        )
    season = str(request.query_params.get("season") or "").strip() or None
    if season is not None and not _SEASON_RE.match(season):
        return _error("invalid_season", "season must be a four-digit year.", 400)

    who = str(session.get("username") or "").strip().lower()
    limited = _rate_limited(f"manager-intel:{who}", RATE_CAPACITY, RATE_WINDOW_SECONDS)
    if limited is not None:
        return limited

    contract = _contract_provider()
    try:
        payload = await run_in_threadpool(
            manager_portfolio.cached_manager_profile,
            username,
            contract=contract,
            scope=scope,
            season=season,
        )
    except Exception:  # noqa: BLE001 — never a 500 page for an upstream fault
        log.exception("manager intel profile failed")
        return _error("upstream_unavailable", "Sleeper could not be reached.", 503)

    failed = _status_error(payload, username)
    if failed is not None:
        return failed
    payload = dict(payload)
    payload["hasBoard"] = bool((contract or {}).get("playersArray"))
    return JSONResponse(payload, headers=_NO_STORE)


@router.get("/activity")
async def get_activity(request: Request) -> JSONResponse:
    """Recent trades, acquisitions and the unified activity feed.

    Query: ``username``; optional ``window`` (``7d`` / ``30d`` default /
    ``90d`` / ``season``), ``season`` (four digits), ``league`` (a Sleeper
    league id the manager plays in) and ``scope``.  Same gates and status
    mapping as ``/profile``; its own tighter per-user rate-limit bucket.
    """
    session, refusal = _gate(request)
    if refusal is not None:
        return refusal

    q = request.query_params
    username = str(q.get("username") or "").strip()
    if not _USERNAME_RE.match(username):
        return _error(
            "invalid_username",
            "Enter a Sleeper username (letters, numbers and underscores).",
            400,
        )
    window = str(q.get("window") or manager_activity.DEFAULT_WINDOW).lower()
    if window not in manager_activity.WINDOWS:
        return _error(
            "invalid_window", f"window must be one of {list(manager_activity.WINDOWS)}.", 400
        )
    scope = str(q.get("scope") or manager_portfolio.SCOPE_DYNASTY).lower()
    if scope not in manager_portfolio.SCOPES:
        return _error(
            "invalid_scope", f"scope must be one of {list(manager_portfolio.SCOPES)}.", 400
        )
    season = str(q.get("season") or "").strip() or None
    if season is not None and not _SEASON_RE.match(season):
        return _error("invalid_season", "season must be a four-digit year.", 400)
    league = str(q.get("league") or "").strip() or None
    if league is not None and not _LEAGUE_ID_RE.match(league):
        return _error("invalid_league", "league must be a Sleeper league id.", 400)

    who = str(session.get("username") or "").strip().lower()
    limited = _rate_limited(
        f"manager-intel-activity:{who}", ACTIVITY_RATE_CAPACITY, ACTIVITY_RATE_WINDOW_SECONDS
    )
    if limited is not None:
        return limited

    contract = _contract_provider()
    asof_factory = None
    if _asof_resolver_provider is not None:
        try:
            asof_factory = _asof_resolver_provider()
        except Exception:  # noqa: BLE001 — no ledger means "at-time unavailable", not a 500
            log.exception("manager intel asof resolver provider failed")
            asof_factory = None
    try:
        payload = await run_in_threadpool(
            manager_activity.cached_manager_activity,
            username,
            contract=contract,
            window=window,
            season=season,
            league_id=league,
            scope=scope,
            asof_factory=asof_factory,
        )
    except Exception:  # noqa: BLE001 — never a 500 page for an upstream fault
        log.exception("manager intel activity failed")
        return _error("upstream_unavailable", "Sleeper could not be reached.", 503)

    failed = _status_error(payload, username)
    if failed is not None:
        return failed
    return JSONResponse(payload, headers=_NO_STORE)
