"""Unified Sharp Tracker cohort and market HTTP services.

Sleeper discovery remains the existing outward graph. FFPC is an optional,
read-only upstream. Both feed platform-neutral evidence/movements before
Sharp Score v2 and the single market table are computed.
"""

from __future__ import annotations

import hmac
import logging
import os
import sys
from datetime import datetime, timezone
from typing import Any

from fastapi import Request
from fastapi.responses import JSONResponse
from starlette.concurrency import run_in_threadpool

from src.intel import ledger, platform_ledger
from src.sharp import discovery
from src.sharp import market as sharp_market
from src.sharp import platform_records
from src.sharp import score as sharp_score

log = logging.getLogger(__name__)
STATUS_OK = "ok"
STATUS_BUILDING = "cohort_building"

# Shared secret for the "Verify Sharp Production Population" workflow
# (.github/workflows/verify-sharp-production.yml). Same bearer-auth
# pattern as server.py's SIGNAL_ALERT_CRON_TOKEN / INTEL_REFRESH_TOKEN:
# when set, a matching ``Authorization: Bearer <token>`` header is
# accepted on ``GET /api/sharp/cohort`` and ``GET /api/sharp/market`` in
# place of a browser session, so CI can measure real population health
# instead of reporting unverifiable_unauthenticated on every run. Empty
# (the default) = disabled — both endpoints stay session-only, exactly
# their behavior before this token existed.
SHARP_SMOKE_TOKEN = os.getenv("SHARP_SMOKE_TOKEN", "").strip()


def sharp_smoke_bearer_auth_ok(request: Request) -> bool:
    """True when the request carries the Sharp production-smoke bearer
    token. An unset token means this can never pass (cron auth disabled,
    session-only) — the endpoints' behavior before the token existed.
    """
    if not SHARP_SMOKE_TOKEN:
        return False
    header = (request.headers.get("authorization") or "").strip()
    if not header.lower().startswith("bearer "):
        return False
    presented = header.split(None, 1)[1].strip()
    # Compare as bytes: header values can be non-ASCII and
    # hmac.compare_digest raises TypeError on non-ASCII str input.
    presented_b = presented.encode("utf-8", "surrogateescape")
    configured_b = SHARP_SMOKE_TOKEN.encode("utf-8", "surrogateescape")
    return hmac.compare_digest(presented_b, configured_b)


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def load_manager_records() -> tuple[list[sharp_score.ManagerRecord], dict[str, Any]]:
    try:
        return platform_records.build_manager_records()
    except Exception:  # noqa: BLE001 — status must not 500
        log.exception("sharp: platform-neutral manager records unavailable")
        return [], {}


def _records_coverage(
    records: list[sharp_score.ManagerRecord], evidence: dict[str, Any]
) -> dict[str, Any]:
    try:
        # Pass the already-computed population through rather than letting
        # coverage() re-run build_manager_records() (the same joins +
        # aggregates over manager_seasons/asset_movements this request
        # already paid for once, a few lines up).
        return platform_records.coverage(records=records, evidence=evidence)
    except Exception:  # noqa: BLE001
        log.exception("sharp: records coverage failed")
        return {}


def cohort_status() -> dict[str, Any]:
    # The cohort endpoint is declared directly in ``server.py`` and remains
    # reachable even when this module was imported transitively before the
    # FastAPI app existed. Re-running the idempotent registrar here turns
    # that guaranteed request into a production self-heal: the next market
    # retry sees the route instead of remaining a permanent 404.
    _register_http_routes()

    try:
        coverage = ledger.coverage()
    except Exception:  # noqa: BLE001
        log.exception("sharp: legacy ledger coverage failed")
        coverage = {}
    try:
        source_coverage = platform_ledger.platform_coverage()
    except Exception:  # noqa: BLE001
        log.exception("sharp: platform coverage failed")
        source_coverage = {"sleeper": {}, "ffpc": {}}
    try:
        graph = discovery.graph_stats()
    except Exception:  # noqa: BLE001
        log.exception("sharp: Sleeper graph stats failed")
        graph = {}

    manager_records, manager_evidence = load_manager_records()
    scored = sharp_score.score_managers(manager_records) if manager_records else []
    tiers = (
        sharp_score.cohort_tiers(scored)
        if scored
        else {
            "observableManagers": graph.get("observedUsers", coverage.get("managerCount", 0)),
            "evaluableManagers": 0,
            "qualifiedManagers": 0,
            "uncertainManagers": 0,
        }
    )
    if scored:
        sleeper_observable = int(graph.get("observedUsers") or 0)
        ffpc_observable = int((source_coverage.get("ffpc") or {}).get("managers") or 0)
        scoreable = int(tiers["observableManagers"])
        tiers["observableManagers"] = max(scoreable, sleeper_observable + ffpc_observable)
        tiers["managersWithRecords"] = scoreable
        total = tiers["observableManagers"]
        tiers["qualifiedShareOfObservable"] = (
            round(tiers["qualifiedManagers"] / total, 4) if total else None
        )

    config = sharp_market.load_ffpc_config()
    curated = (
        sharp_market.curated_members(config) if config.get("allowCuratedInCombinedSignals") else []
    )
    provisional = sharp_market.provisional_members(config)
    status = (
        STATUS_OK
        if tiers.get("qualifiedManagers", 0) > 0 or curated or provisional
        else STATUS_BUILDING
    )
    return {
        "status": status,
        "methodologyVersion": sharp_score.methodology_version(),
        "generatedAt": _utc_now_iso(),
        "cohort": {
            **tiers,
            "curatedManagers": len(curated),
            "provisionalManagers": len(provisional),
            "observedLeagues": graph.get("observedLeagues", coverage.get("leagueCount", 0))
            + int((source_coverage.get("ffpc") or {}).get("leagues") or 0),
            "signalEligibleLeagues": graph.get("signalEligibleLeagues", 0),
            "discoveryOnlyLeagues": graph.get("discoveryOnlyLeagues", 0),
            "observedTransactions": sum(
                int((value or {}).get("transactions") or 0) for value in source_coverage.values()
            ),
        },
        "graph": graph,
        "records": _records_coverage(manager_records, manager_evidence),
        "coverage": {"legacy": coverage, "platforms": source_coverage},
        "ffpc": {
            "enabled": bool(config.get("enabled")),
            "mode": config.get("mode", "public_only"),
            "curatedContributionEnabled": bool(config.get("allowCuratedInCombinedSignals")),
            "provisionalContributionEnabled": bool(
                config.get("allowProvisionalPublicInCombinedSignals")
            ),
        },
        "note": (
            "Coverage is an observable subset. Sleeper grows through its public graph; "
            "FFPC includes only explicitly configured public pages. Curated and "
            "provisional FFPC members are never represented as Sharp Score v2 qualifiers."
        ),
    }


def market_payload(**kwargs: Any) -> dict[str, Any]:
    return sharp_market.market_payload(**kwargs)


def market_audit_payload(asset_id: str, **kwargs: Any) -> dict[str, Any]:
    return sharp_market.audit_payload(asset_id, **kwargs)


def roster_percentage_payload(**kwargs: Any) -> dict[str, Any]:
    """Sharp Roster Percentage board.

    Same cohort as :func:`market_payload` — both resolve their manager
    pool through ``src/sharp/cohort.py``.
    """
    from src.sharp import roster_percentage

    return roster_percentage.build_board(**kwargs)


def roster_percentage_audit_payload(asset_id: str, **kwargs: Any) -> dict[str, Any]:
    from src.sharp import roster_percentage

    return roster_percentage.audit_player(asset_id, **kwargs)


def _running_session_check(request: Request):
    """Best-effort delegate to server.py's session-cookie check.

    Mirrors :func:`_server_app`'s ``sys.modules`` lookup rather than a
    direct ``import server`` — server.py imports THIS module, so a
    top-level import here would be circular. Looked up lazily at
    request time, by which point the server module is fully loaded.
    Returns ``None`` (never raises) if it isn't reachable; the bearer
    path in :func:`sharp_smoke_bearer_auth_ok` still works either way.
    """
    for module_name in ("server", "__main__"):
        module = sys.modules.get(module_name)
        checker = getattr(module, "_get_auth_session", None)
        if callable(checker):
            try:
                return checker(request)
            except Exception:  # noqa: BLE001
                return None
    return None


def _server_app():
    """Return the FastAPI app whether ``server.py`` was imported or executed.

    Production starts the backend with ``python server.py``, which places the
    module in ``sys.modules['__main__']`` rather than ``sys.modules['server']``.
    Looking only for ``server`` silently skipped the market route registration
    while the explicitly declared cohort endpoint continued to work.
    """
    for module_name in ("server", "__main__"):
        module = sys.modules.get(module_name)
        app = getattr(module, "app", None)
        if app is not None:
            return app
    return None


def _register_http_routes() -> None:
    """Register the sharp market routes onto the running FastAPI app.

    Keeping registration here avoids a second API application or a
    parallel FFPC router while preserving ``/api/sharp/cohort`` exactly.

    IDEMPOTENT, and called from three places on purpose: the module-level
    call below (the original path), ``server.py`` right after it imports
    this module (the RELIABLE path — the module-level call is a no-op
    whenever something imported this module before the app existed), and
    ``cohort_status`` as a production self-heal.

    Prefer the public :func:`register_http_routes` from outside.

    ``Request`` is imported at module scope because postponed annotations
    resolve handler types through module globals. A function-local import made
    FastAPI treat ``request`` as a required query parameter and return 422 for
    every real market request.
    """
    app = _server_app()
    if app is None:
        return
    existing = {getattr(route, "path", None) for route in getattr(app, "routes", [])}
    if "/api/sharp/market" in existing:
        return

    async def get_market(request: Request):
        # Registered in server.py's _SELF_AUTHED_API_EXACT (alongside
        # /api/sharp/cohort) so the cookie-only middleware lets the
        # request through — this check is what actually gates it: a
        # browser session OR the SHARP_SMOKE_TOKEN bearer used by the
        # production-smoke workflow. Neither present -> 401, same as
        # every other private endpoint.
        if not _running_session_check(request) and not sharp_smoke_bearer_auth_ok(request):
            return JSONResponse(
                status_code=401,
                content={"error": "auth_required"},
                headers={"Cache-Control": "no-store"},
            )
        query = request.query_params
        try:
            payload = await run_in_threadpool(
                sharp_market.market_payload,
                window=str(query.get("window") or "30d"),
                sort=str(query.get("sort") or "strength"),
                asset_type=str(query.get("assetType") or "all"),
                platform=str(query.get("platform") or "all"),
                qualification=str(query.get("qualification") or "all"),
                limit=int(query.get("limit") or 100),
            )
        except (ValueError, TypeError) as exc:
            return JSONResponse(
                status_code=400,
                content={"error": "bad_request", "message": str(exc)},
                headers={"Cache-Control": "no-store"},
            )
        except Exception as exc:  # noqa: BLE001
            log.exception("sharp market failed")
            return JSONResponse(
                status_code=503,
                content={"error": "sharp_market_unavailable", "message": str(exc)},
                headers={"Cache-Control": "no-store"},
            )
        return JSONResponse(
            content=payload,
            headers={"Cache-Control": "private, max-age=120, stale-while-revalidate=300"},
        )

    async def get_market_audit(request: Request):
        asset_id = str(request.query_params.get("assetId") or "").strip()
        if not asset_id:
            return JSONResponse(
                status_code=400,
                content={"error": "missing_param", "message": "assetId required"},
                headers={"Cache-Control": "no-store"},
            )
        try:
            payload = await run_in_threadpool(
                sharp_market.audit_payload,
                asset_id,
                window=str(request.query_params.get("window") or "30d"),
                qualification=str(request.query_params.get("qualification") or "all"),
            )
        except (ValueError, TypeError) as exc:
            return JSONResponse(
                status_code=400, content={"error": "bad_request", "message": str(exc)}
            )
        except Exception as exc:  # noqa: BLE001
            log.exception("sharp market audit failed")
            return JSONResponse(
                status_code=503, content={"error": "sharp_market_unavailable", "message": str(exc)}
            )
        return JSONResponse(content=payload, headers={"Cache-Control": "private, max-age=60"})

    app.add_api_route("/api/sharp/market", get_market, methods=["GET"], name="get_sharp_market")
    app.add_api_route(
        "/api/sharp/market/audit",
        get_market_audit,
        methods=["GET"],
        name="get_sharp_market_audit",
    )


def register_http_routes() -> None:
    """Public entry point for :func:`_register_http_routes`.

    ``server.py`` calls this immediately after importing the module, so
    registration never depends on which importer happened to be first.
    """
    _register_http_routes()


_register_http_routes()
