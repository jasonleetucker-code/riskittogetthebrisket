"""HTTP surface for Manager Intelligence: ``GET /api/manager-intel/profile``.

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

from src.intel import manager_portfolio

log = logging.getLogger("manager_intel.api")

router = APIRouter(prefix="/api/manager-intel", tags=["manager-intel"])

_NO_STORE = {"Cache-Control": "no-store"}

#: Sleeper usernames are letters, digits and underscores; a user id is digits.
_USERNAME_RE = re.compile(r"^[A-Za-z0-9_]{1,40}$")
_SEASON_RE = re.compile(r"^20\d\d$")

RATE_CAPACITY = 30
RATE_WINDOW_SECONDS = 600.0

_session_provider: Callable[[Request], Any] | None = None
_contract_provider: Callable[[], Any] | None = None


def configure(
    *,
    session_provider: Callable[[Request], Any] | None,
    contract_provider: Callable[[], Any] | None,
) -> None:
    """``server.py`` injects its session reader and live-contract accessor."""
    global _session_provider, _contract_provider
    _session_provider = session_provider
    _contract_provider = contract_provider


def _error(code: str, message: str, status: int, **extra: Any) -> JSONResponse:
    return JSONResponse(
        {"error": code, "message": message, **extra}, status_code=status, headers=_NO_STORE
    )


@router.get("/profile")
async def get_profile(request: Request) -> JSONResponse:
    from src.api import rate_limit as _rl  # noqa: PLC0415
    from src.api.feature_flags import is_enabled  # noqa: PLC0415

    if not is_enabled("manager_intelligence"):
        return _error("feature_disabled", "Manager Intelligence is switched off.", 503)
    if _session_provider is None or _contract_provider is None:
        return _error("auth_required", "Sign-in required.", 401)
    session = _session_provider(request)
    if not session:
        return _error("auth_required", "Sign-in required.", 401)
    if session.get("auth_method") == "guest_pass":
        return _error("guest_read_only", "Guest passes cannot run manager lookups.", 403)

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
    limited, retry_after = _rl.should_rate_limit_key(
        f"manager-intel:{who}", capacity=RATE_CAPACITY, window_seconds=RATE_WINDOW_SECONDS
    )
    if limited:
        return JSONResponse(
            {
                "error": "rate_limited",
                "message": "Too many lookups — wait a moment and try again.",
                "retryAfterSeconds": retry_after,
            },
            status_code=429,
            headers={**_NO_STORE, "Retry-After": str(retry_after)},
        )

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

    status = payload.get("status")
    if status == manager_portfolio.STATUS_NOT_FOUND:
        return _error("not_found", f"No Sleeper user named {username!r}.", 404)
    if status == manager_portfolio.STATUS_RATE_LIMITED:
        return _error(
            "upstream_rate_limited", "Sleeper is rate-limiting us — try again shortly.", 429
        )
    if status == manager_portfolio.STATUS_UPSTREAM_UNAVAILABLE:
        return _error("upstream_unavailable", "Sleeper could not be reached.", 503)
    payload = dict(payload)
    payload["hasBoard"] = bool((contract or {}).get("playersArray"))
    return JSONResponse(payload, headers=_NO_STORE)
