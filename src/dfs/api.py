"""HTTP surface for the DFS workspace: ``/api/dfs/*``.

Private: the prefix sits behind ``server.py::_private_api_gate`` (401 without
a site session) AND every handler resolves the owner itself — records are
scoped by owner, so a hidden id is never access control.

Capability honesty is enforced here, not in the UI:

* ``objective: "contest_ev"`` answers ``409 CAPABILITY_UNAVAILABLE`` — there is
  no validated field/ownership/payout model yet.  The client must explicitly
  choose ``"projection_baseline"``; it is never substituted silently.
* ``mode: "money"`` on a rule set that is not ``money_ready`` answers
  ``409 RULESET_UNVERIFIED``.  ``mode: "research"`` builds, labelled.

DFS data never touches the dynasty board: this module imports nothing from
``src/api/data_contract.py`` or any valuation owner, and writes only under
``data/dfs/``.
"""

from __future__ import annotations

import logging
from typing import Any, Callable

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse, Response
from starlette.concurrency import run_in_threadpool

from src.dfs import store
from src.dfs.export import ExportError, build_upload_csv
from src.dfs.imports import (
    SALARY_PARSERS,
    ImportError_,
    SlateAthlete,
    apply_platform_average,
    apply_projection_csv,
    content_hash,
)
from src.dfs.optimizer import ConstraintError, optimize, parse_constraints, solver_version
from src.dfs.rules import capability_matrix, get_ruleset, load_rulesets

log = logging.getLogger("dfs.api")

router = APIRouter(prefix="/api/dfs", tags=["dfs"])

MAX_BODY_BYTES = 5 * 1024 * 1024

OBJECTIVES = [
    {
        "id": "projection_baseline",
        "label": "Highest projected points",
        "available": True,
        "description": "Maximizes the sum of projected fantasy points under the rule set and your constraints. "
        "Deterministic; certified optimal for this objective when the solver reports 'optimal'. "
        "Not contest-aware: no field, ownership, duplication or payout modelling.",
    },
    {
        "id": "contest_ev",
        "label": "Contest-aware (cash / GPP)",
        "available": False,
        "description": "Requires validated outcome distributions, an opponent-field model and the contest's "
        "payout ladder. Not built yet (docs/dfs/ROADMAP.md, DFS-P4/P5). Never substituted silently.",
    },
]

_session_resolver: Callable[[Request], dict | None] | None = None


def configure_session_resolver(fn: Callable[[Request], dict | None]) -> None:
    """``server.py`` injects its session lookup; tests inject a fake."""
    global _session_resolver
    _session_resolver = fn


def _err(
    code: str, message: str, status: int, detail: dict[str, Any] | None = None
) -> JSONResponse:
    body: dict[str, Any] = {"error": code, "message": message}
    if detail:
        body["detail"] = detail
    return JSONResponse(status_code=status, content=body, headers={"Cache-Control": "no-store"})


def _ok(body: Any, status: int = 200) -> JSONResponse:
    return JSONResponse(status_code=status, content=body, headers={"Cache-Control": "no-store"})


def _flag_enabled() -> bool:
    try:
        from src.api import feature_flags

        return feature_flags.is_enabled("dfs_workspace")
    except Exception:  # noqa: BLE001
        return False


def _owner(request: Request) -> str | JSONResponse:
    if not _flag_enabled():
        return _err("FEATURE_DISABLED", "The DFS workspace is switched off.", 503)
    session = _session_resolver(request) if _session_resolver else None
    return owner_key(session)


def owner_key(session: dict | None) -> str | JSONResponse:
    """The storage owner for a session.

    A username is NOT always a person: every guest-pass session carries the
    literal username ``"guest"``.  Keying on it would put every guest in one
    shared namespace, so guests are keyed by their pass id and refused when
    the session cannot say which pass it came from.
    """
    session = session or {}
    username = str(session.get("username") or "").strip()
    if not username:
        return _err("AUTH_REQUIRED", "Sign-in required.", 401)
    if session.get("auth_method") == "guest_pass" or username.lower() == "guest":
        pass_id = session.get("guest_pass_id")
        if not isinstance(pass_id, int) or isinstance(pass_id, bool) or pass_id <= 0:
            return _err(
                "GUEST_UNSCOPED",
                "This guest session cannot be tied to a single guest pass, so DFS records cannot be kept private to it.",
                403,
            )
        return f"guest-pass:{pass_id}"
    return f"user:{username}"


def _reject_constant(name: str) -> Any:
    raise ValueError(f"non-JSON constant {name}")


async def _json_body(request: Request) -> dict[str, Any] | JSONResponse:
    raw = await request.body()
    if len(raw) > MAX_BODY_BYTES:
        return _err("RESOURCE_BUDGET_EXCEEDED", "Request body too large.", 413)
    try:
        import json

        # NaN / Infinity are not JSON: accepted, they would be stored verbatim
        # and then fail every later render of the record.
        body = json.loads(raw or b"{}", parse_constant=_reject_constant)
    except ValueError:
        return _err("INVALID_JSON", "Body must be JSON.", 400)
    if not isinstance(body, dict):
        return _err("INVALID_JSON", "Body must be a JSON object.", 400)
    return body


@router.get("/capabilities")
async def capabilities(request: Request):
    owner = _owner(request)
    if isinstance(owner, JSONResponse):
        return owner
    return _ok(
        {
            "matrix": capability_matrix(),
            "rulesets": [rs.to_public() for rs in load_rulesets().values()],
            "objectives": OBJECTIVES,
            "solver": solver_version(),
            "projectionSources": [
                {"id": "owner_import", "label": "Your projection file", "kind": "forecast"},
                {
                    "id": "platform_season_average",
                    "label": "Platform season average",
                    "kind": "observation",
                    "note": "The platform's published average — a past-performance observation, not a forecast. Used only where you opt in.",
                },
            ],
        }
    )


def _athletes_from(body: list[dict[str, Any]]) -> list[SlateAthlete]:
    return [SlateAthlete(**a) for a in body]


@router.post("/slates")
async def create_slate(request: Request):
    owner = _owner(request)
    if isinstance(owner, JSONResponse):
        return owner
    body = await _json_body(request)
    if isinstance(body, JSONResponse):
        return body
    rs = get_ruleset(str(body.get("ruleset") or ""))
    if rs is None:
        return _err("RULESET_UNKNOWN", "Choose a supported platform, sport and format.", 400)
    parser = SALARY_PARSERS.get(rs.salary_import)
    if parser is None:
        return _err("RULESET_UNVERIFIED", "No salary importer exists for this rule set.", 409)
    try:
        athletes, report = parser(body.get("salaryCsv") or "")
        proj_report = None
        if body.get("projectionCsv"):
            proj_report = apply_projection_csv(athletes, body["projectionCsv"])
        averaged = apply_platform_average(athletes) if body.get("usePlatformAverage") else 0
    except ImportError_ as exc:
        return _err(exc.code, exc.message, 422, exc.detail)
    if not athletes:
        return _err(
            "EMPTY_SLATE", "No usable players were found in the salary file.", 422, report.to_dict()
        )
    off_ruleset = sorted({p for a in athletes for p in a.positions} - rs.positions)
    snapshot_body = {
        "ruleset": rs.key,
        "label": str(body.get("label") or "")[:80] or None,
        "athletes": [a.to_dict() for a in athletes],
        "importReport": report.to_dict(),
        "projectionReport": proj_report,
        "platformAverageApplied": averaged,
        "positionsNotInRuleset": off_ruleset,
    }
    h = content_hash({"ruleset": rs.key, "athletes": snapshot_body["athletes"]})
    meta = await run_in_threadpool(store.put_snapshot, owner, rs.key, h, snapshot_body)
    return _ok(_snapshot_view(meta["id"], meta["createdAt"], h, snapshot_body), 201)


def _snapshot_view(sid: str, created: str, h: str, body: dict[str, Any]) -> dict[str, Any]:
    rs_id = body["ruleset"].split("@", 1)[0]
    rs = get_ruleset(rs_id)
    athletes = body["athletes"]
    games = sorted({a["game"] for a in athletes if a.get("game")})
    return {
        "snapshotId": sid,
        "createdAt": created,
        "contentHash": h,
        "ruleset": rs.to_public() if rs else {"key": body["ruleset"]},
        "label": body.get("label"),
        "athletes": athletes,
        "games": games,
        "importReport": body.get("importReport"),
        "projectionReport": body.get("projectionReport"),
        "platformAverageApplied": body.get("platformAverageApplied", 0),
        "positionsNotInRuleset": body.get("positionsNotInRuleset", []),
        "coverage": {
            "athletes": len(athletes),
            "projected": sum(1 for a in athletes if a.get("projection") is not None),
            "unprojected": sum(1 for a in athletes if a.get("projection") is None),
        },
    }


@router.get("/slates/{snapshot_id}")
async def read_slate(snapshot_id: str, request: Request):
    owner = _owner(request)
    if isinstance(owner, JSONResponse):
        return owner
    snap = await run_in_threadpool(store.get_snapshot, owner, snapshot_id)
    if snap is None:
        return _err("NOT_FOUND", "No such slate.", 404)
    return _ok(_snapshot_view(snap["id"], snap["createdAt"], snap["contentHash"], snap["body"]))


@router.post("/builds")
async def create_build(request: Request):
    owner = _owner(request)
    if isinstance(owner, JSONResponse):
        return owner
    body = await _json_body(request)
    if isinstance(body, JSONResponse):
        return body
    objective = body.get("objective")
    if objective == "contest_ev":
        return _err(
            "CAPABILITY_UNAVAILABLE",
            "Contest-aware optimization is not available yet: it needs validated outcome distributions, "
            "an opponent-field model and the contest's payout ladder. Choose 'Highest projected points' "
            "explicitly to build the transparent baseline.",
            409,
            {"available": ["projection_baseline"]},
        )
    if objective != "projection_baseline":
        return _err("INVALID_OBJECTIVE", "objective must be 'projection_baseline'.", 400)
    mode = body.get("mode", "research")
    if mode not in ("research", "money"):
        return _err("INVALID_MODE", "mode must be 'research' or 'money'.", 400)
    snap = await run_in_threadpool(store.get_snapshot, owner, str(body.get("snapshotId") or ""))
    if snap is None:
        return _err("NOT_FOUND", "No such slate.", 404)
    rs = get_ruleset(snap["ruleset"].split("@", 1)[0])
    if rs is None or rs.key != snap["ruleset"]:
        return _err(
            "RULESET_SUPERSEDED",
            "This slate was imported under a rule-set version that is no longer current. Re-import it.",
            409,
        )
    if mode == "money" and rs.readiness != "money_ready":
        return _err(
            "RULESET_UNVERIFIED",
            "Money-ready builds are refused until the rule set and export format are verified against "
            "official platform evidence. Research builds remain available.",
            409,
            {"verification": rs.verification, "exportVerification": rs.export.get("verification")},
        )
    athletes = _athletes_from(snap["body"]["athletes"])
    try:
        constraints = parse_constraints(body.get("constraints"), rs, athletes)
        result = await run_in_threadpool(optimize, rs, athletes, constraints)
    except ConstraintError as exc:
        return _err(exc.code, exc.message, 422, exc.detail)
    except ImportError as exc:  # scipy missing on this host
        log.error("dfs solver unavailable: %s", exc)
        return _err(
            "SOLVER_UNAVAILABLE", "The optimizer's solver is not installed on this server.", 503
        )
    record = {
        "ruleset": {
            "key": rs.key,
            "label": rs.label,
            "readiness": rs.readiness,
            "verification": rs.verification.get("state"),
            "exportVerification": (rs.export.get("verification") or {}).get("state"),
        },
        "snapshot": {
            "id": snap["id"],
            "contentHash": snap["contentHash"],
            "importedAt": snap["createdAt"],
        },
        "objective": "projection_baseline",
        "mode": mode,
        "researchOnly": rs.readiness != "money_ready",
        "capabilityLevel": "projection_only",
        "contestEvaluated": False,
        "method": "single_lineup_milp" if constraints.lineups == 1 else "sequential_milp",
        "methodNote": (
            "One lineup: the highest projected total satisfying every rule and constraint."
            if constraints.lineups == 1
            else "Lineup k is the highest projected lineup that keeps the uniqueness rule against lineups 1..k-1 "
            "and the exposure caps. The set is built sequentially, not jointly optimized as a portfolio."
        ),
        "solver": solver_version(),
        "seed": None,
        "constraints": body.get("constraints") or {},
        "constraintsHash": content_hash(body.get("constraints") or {}),
        "result": result,
        "limits": [
            "Projections are only as good as their source; this build does not estimate uncertainty.",
            "No ownership, duplication, field or payout modelling — no ROI or EV is implied.",
            "Rule set not verified against official platform rules — research only."
            if rs.readiness != "money_ready"
            else "Rule set verified.",
        ],
        "submitted": False,
    }
    saved = await run_in_threadpool(store.put_build, owner, snap["id"], record)
    return _ok(saved, 201)


@router.get("/builds")
async def builds(request: Request):
    owner = _owner(request)
    if isinstance(owner, JSONResponse):
        return owner
    return _ok({"builds": await run_in_threadpool(store.list_builds, owner)})


@router.get("/builds/{build_id}")
async def read_build(build_id: str, request: Request):
    owner = _owner(request)
    if isinstance(owner, JSONResponse):
        return owner
    b = await run_in_threadpool(store.get_build, owner, build_id)
    if b is None:
        return _err("NOT_FOUND", "No such build.", 404)
    return _ok(b)


@router.get("/builds/{build_id}/export")
async def export_build(build_id: str, request: Request):
    owner = _owner(request)
    if isinstance(owner, JSONResponse):
        return owner
    b = await run_in_threadpool(store.get_build, owner, build_id)
    if b is None:
        return _err("NOT_FOUND", "No such build.", 404)
    rs = get_ruleset(b["ruleset"]["key"].split("@", 1)[0])
    if rs is None or rs.key != b["ruleset"]["key"]:
        return _err(
            "RULESET_SUPERSEDED", "The rule-set version this build used is no longer current.", 409
        )
    snap = await run_in_threadpool(store.get_snapshot, owner, b["snapshot"]["id"])
    if snap is None:
        return _err("NOT_FOUND", "The slate behind this build is missing.", 404)
    lineups = b["result"]["lineups"]
    if not lineups:
        return _err("NOTHING_TO_EXPORT", "This build produced no lineups.", 409)
    try:
        text = build_upload_csv(rs, lineups, _athletes_from(snap["body"]["athletes"]))
    except ExportError as exc:
        return _err(exc.code, exc.message, 409, exc.detail)
    verified = rs.export_verified
    fname = f"{rs.platform}-{rs.sport}-{rs.format}-{build_id}{'' if verified else '-UNVERIFIED-FORMAT'}.csv"
    return Response(
        content=text,
        media_type="text/csv; charset=utf-8",
        headers={
            "Content-Disposition": f'attachment; filename="{fname}"',
            "Cache-Control": "no-store",
            "X-DFS-Export-Verified": "true" if verified else "false",
        },
    )
