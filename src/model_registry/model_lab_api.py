"""HTTP surface for the Model Lab: ``GET /api/model-lab`` and ``/api/model-lab/{family}``.

PRIVATE and ADMIN-ONLY (plan §33: "private / admin"; development metrics are not
shown to ordinary league users).  Two layers, both deny-by-default:

1. ``server.py::_private_api_gate`` 401s any ``/api/*`` request without a session
   (``/api/model-lab`` is deliberately absent from every public allowlist);
2. every handler here calls the authorizer ``server.py`` injects —
   ``_require_admin_session`` (401 without a session, 403 for a signed-in user who
   is not on the private-app allowlist).  With no authorizer configured the
   handlers answer 401: an unwired router never serves.

Read-only: GET handlers only, no request body, ``Cache-Control: no-store``.  The
payload is assembled by ``model_lab.cached_model_lab`` (60 s per-process memo), which
reads the existing owners' files and writes nothing.
"""

from __future__ import annotations

import logging
from typing import Any, Callable

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from starlette.concurrency import run_in_threadpool

from src.model_registry import model_lab

log = logging.getLogger("model_lab.api")

router = APIRouter(prefix="/api/model-lab", tags=["model-lab"])

_NO_STORE = {"Cache-Control": "no-store"}

#: ``request -> session dict | JSONResponse``; ``server.py`` injects
#: ``_require_admin_session``.  ``None`` = not wired = refuse.
_authorizer: Callable[[Request], Any] | None = None


def configure_authorizer(fn: Callable[[Request], Any] | None) -> None:
    """``server.py`` injects its admin-session check; tests inject a fake."""
    global _authorizer
    _authorizer = fn


def _err(status: int, code: str, message: str, **extra: Any) -> JSONResponse:
    return JSONResponse(
        status_code=status,
        content={"error": code, "message": message, **extra},
        headers=_NO_STORE,
    )


def _authorize(request: Request) -> JSONResponse | None:
    """``None`` when the caller may read the Lab, else the refusal to return."""
    if _authorizer is None:
        return _err(401, "auth_required", "Sign-in required.")
    try:
        verdict = _authorizer(request)
    except Exception:  # noqa: BLE001 — an authorizer fault never grants access
        log.exception("model-lab authorizer failed")
        return _err(401, "auth_required", "Sign-in required.")
    if isinstance(verdict, JSONResponse):
        verdict.headers["Cache-Control"] = "no-store"
        return verdict
    if not verdict:
        return _err(401, "auth_required", "Sign-in required.")
    return None


async def _payload() -> dict[str, Any]:
    return await run_in_threadpool(model_lab.cached_model_lab)


@router.get("")
async def get_model_lab(request: Request) -> JSONResponse:
    refused = _authorize(request)
    if refused is not None:
        return refused
    return JSONResponse(content=await _payload(), headers=_NO_STORE)


@router.get("/{family}")
async def get_model_lab_family(family: str, request: Request) -> JSONResponse:
    refused = _authorize(request)
    if refused is not None:
        return refused
    payload = await _payload()
    for block in payload.get("families") or []:
        if block.get("family") == family:
            return JSONResponse(
                content={
                    "schema": payload.get("schema"),
                    "generatedAt": payload.get("generatedAt"),
                    "private": True,
                    "readOnly": True,
                    "labStates": payload.get("labStates"),
                    "fieldVocabulary": payload.get("fieldVocabulary"),
                    "family": block,
                },
                headers=_NO_STORE,
            )
    return _err(
        404,
        "unknown_family",
        f"No model family {family!r}.",
        families=[b.get("family") for b in payload.get("families") or []],
    )
