"""Private HTTP service for curated Sharp people and identity review."""

from __future__ import annotations

import logging
import sys
from typing import Any

from fastapi import Request
from fastapi.responses import JSONResponse
from starlette.concurrency import run_in_threadpool

from src.sharp import curated

log = logging.getLogger(__name__)


def _server_app():
    for module_name in ("server", "__main__"):
        module = sys.modules.get(module_name)
        app = getattr(module, "app", None)
        if app is not None:
            return app
    return None


def _int_param(value: Any, default: int, *, minimum: int = 0, maximum: int = 1000) -> int:
    try:
        return max(minimum, min(maximum, int(value)))
    except (TypeError, ValueError):
        return default


def _require_admin(request: Request) -> JSONResponse | None:
    """Return an error response when the caller is not an allowlisted admin.

    Resolved through the running server module rather than imported, because
    ``server.py`` imports THIS module -- a module-level import back into it
    would be circular. If the helper is unavailable (a bare app in a test),
    the request is refused rather than allowed: failing closed is the only
    safe default for a route that can verify an identity.
    """
    for module_name in ("server", "__main__"):
        module = sys.modules.get(module_name)
        require_admin = getattr(module, "_require_admin_session", None)
        if require_admin is not None:
            result = require_admin(request)
            return result if isinstance(result, JSONResponse) else None
    return _error(503, "admin_gate_unavailable", "Admin authorization is unavailable.")


def _error(status: int, code: str, message: str) -> JSONResponse:
    return JSONResponse(
        status_code=status,
        content={"error": code, "message": message},
        headers={"Cache-Control": "no-store"},
    )


def _refresh_pipeline(*, sleeper_budget: int = 50) -> dict[str, Any]:
    result: dict[str, Any] = {}
    result["import"] = curated.import_snapshot()
    result["verifiedSleeper"] = curated.resolve_verified_sleeper_accounts()
    if sleeper_budget > 0:
        result["sleeperCandidates"] = curated.inspect_sleeper_candidates(budget=sleeper_budget)
    result["ffpcCandidates"] = curated.match_ffpc_candidates()
    result["membership"] = curated.refresh_memberships()
    result["reconciliation"] = curated.reconciliation_report()
    return result


def _register_http_routes() -> None:
    app = _server_app()
    if app is None:
        return
    existing = {getattr(route, "path", None) for route in getattr(app, "routes", [])}
    if "/api/sharp/people" in existing:
        return

    async def get_people(request: Request):
        query = request.query_params
        try:
            payload = await run_in_threadpool(
                curated.people_payload,
                membership=str(query.get("membership") or "all"),
                platform=str(query.get("platform") or "all"),
                specialty=str(query.get("specialty") or "all"),
                identity=str(query.get("identity") or "all"),
                search=str(query.get("search") or ""),
                limit=_int_param(query.get("limit"), 250, minimum=1),
                offset=_int_param(query.get("offset"), 0),
            )
        except (ValueError, TypeError) as exc:
            return _error(400, "bad_request", str(exc))
        except Exception as exc:  # noqa: BLE001
            log.exception("curated Sharp people request failed")
            return _error(503, "curated_sharp_unavailable", str(exc))
        return JSONResponse(payload, headers={"Cache-Control": "private, max-age=60"})

    async def get_person(person_id: str):
        try:
            payload = await run_in_threadpool(curated.person_payload, person_id)
        except Exception as exc:  # noqa: BLE001
            log.exception("curated Sharp person request failed")
            return _error(503, "curated_sharp_unavailable", str(exc))
        if payload is None:
            return _error(404, "sharp_person_not_found", "Sharp person not found")
        return JSONResponse(payload, headers={"Cache-Control": "private, max-age=60"})

    async def get_review_queue(request: Request):
        query = request.query_params
        try:
            payload = await run_in_threadpool(
                curated.review_queue_payload,
                platform=str(query.get("platform") or "all"),
                status=str(query.get("status") or "open"),
                limit=_int_param(query.get("limit"), 500, minimum=1),
            )
        except Exception as exc:  # noqa: BLE001
            log.exception("Sharp identity review queue failed")
            return _error(503, "sharp_review_unavailable", str(exc))
        return JSONResponse(payload, headers={"Cache-Control": "private, no-store"})

    async def decide_candidate(candidate_id: str, request: Request):
        # Verifying an identity is the single most consequential write in this
        # model -- it is what turns a curated person into a Super Sharp whose
        # trades vote. The private-API gate only proves *a* logged-in user, so
        # this needs the allowlist on top.
        guard = _require_admin(request)
        if guard is not None:
            return guard
        try:
            body = await request.json()
        except Exception:  # noqa: BLE001
            body = {}
        try:
            payload = await run_in_threadpool(
                curated.review_candidate,
                candidate_id,
                str((body or {}).get("decision") or ""),
                reviewer=str((body or {}).get("reviewer") or "admin"),
                reason=str((body or {}).get("reason") or "") or None,
            )
        except KeyError:
            return _error(404, "identity_candidate_not_found", "Identity candidate not found")
        except ValueError as exc:
            return _error(409, "identity_review_conflict", str(exc))
        except Exception as exc:  # noqa: BLE001
            log.exception("Sharp identity review failed")
            return _error(503, "sharp_review_unavailable", str(exc))
        return JSONResponse(payload, headers={"Cache-Control": "private, no-store"})

    async def get_curated_summary():
        try:
            payload = await run_in_threadpool(curated.summary_payload)
            payload["reconciliation"] = await run_in_threadpool(curated.reconciliation_report)
        except Exception as exc:  # noqa: BLE001
            log.exception("curated Sharp summary failed")
            return _error(503, "curated_sharp_unavailable", str(exc))
        return JSONResponse(payload, headers={"Cache-Control": "private, max-age=60"})

    async def refresh_curated(request: Request):
        # Spends a real outbound call budget against Sleeper's public API.
        guard = _require_admin(request)
        if guard is not None:
            return guard
        try:
            body = await request.json()
        except Exception:  # noqa: BLE001
            body = {}
        budget = _int_param((body or {}).get("sleeperBudget"), 50, maximum=250)
        try:
            payload = await run_in_threadpool(_refresh_pipeline, sleeper_budget=budget)
        except Exception as exc:  # noqa: BLE001
            log.exception("curated Sharp refresh failed")
            return _error(503, "curated_sharp_refresh_failed", str(exc))
        return JSONResponse(payload, headers={"Cache-Control": "private, no-store"})

    app.add_api_route("/api/sharp/people", get_people, methods=["GET"], name="get_sharp_people")
    app.add_api_route(
        "/api/sharp/people/{person_id}",
        get_person,
        methods=["GET"],
        name="get_sharp_person",
    )
    app.add_api_route(
        "/api/sharp/review",
        get_review_queue,
        methods=["GET"],
        name="get_sharp_identity_review_queue",
    )
    app.add_api_route(
        "/api/sharp/review/{candidate_id}",
        decide_candidate,
        methods=["POST"],
        name="review_sharp_identity_candidate",
    )
    app.add_api_route(
        "/api/sharp/curated/summary",
        get_curated_summary,
        methods=["GET"],
        name="get_curated_sharp_summary",
    )
    app.add_api_route(
        "/api/sharp/curated/refresh",
        refresh_curated,
        methods=["POST"],
        name="refresh_curated_sharps",
    )


_register_http_routes()
