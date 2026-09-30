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

import json
from decimal import Decimal
from pathlib import Path

from src.dfs import store
from src.dfs.contests import (
    ContestError,
    dollars_to_cents,
    entry_upper_bound,
    parse_contest,
    tied_payout,
    validate_contest,
)
from src.dfs.export import ExportError, build_upload_csv
from src.dfs.imports import (
    ImportError_,
    SlateAthlete,
    apply_platform_average,
    apply_projection_csv,
    content_hash,
)
from src.dfs.optimizer import ConstraintError, optimize, parse_constraints, solver_version
from src.dfs.rules import capability_matrix, get_ruleset, load_rulesets
from src.dfs.slate import CanonicalSlate, canonical_from_platform_file, detect_platform_file
from src.dfs import providers as dfs_providers

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
        "payout ladder. Not built yet (docs/dfs/ROADMAP.md, Phases D-F). Never substituted silently.",
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


@router.post("/slates/detect")
async def detect_slate(request: Request):
    """Recognise a platform file without saving anything."""
    owner = _owner(request)
    if isinstance(owner, JSONResponse):
        return owner
    body = await _json_body(request)
    if isinstance(body, JSONResponse):
        return body
    try:
        det = detect_platform_file(body.get("salaryCsv") or "")
    except ImportError_ as exc:
        return _err(exc.code, exc.message, 422, exc.detail)
    row = next(
        (
            r
            for r in capability_matrix()
            if (r["platform"], r["sport"], r["format"]) == (det.platform, det.sport, det.format)
        ),
        None,
    )
    return _ok({"detection": det.to_dict(), "capability": row})


def _snapshot_body(
    slate: CanonicalSlate, rs: Any, extra: dict[str, Any], body: dict[str, Any]
) -> dict[str, Any] | JSONResponse:
    """Canonical slate (+ optional owner projections) → the immutable snapshot body."""
    athletes = slate.athletes
    try:
        proj_report = None
        if body.get("projectionCsv"):
            proj_report = apply_projection_csv(athletes, body["projectionCsv"])
        averaged = apply_platform_average(athletes) if body.get("usePlatformAverage") else 0
    except ImportError_ as exc:
        return _err(exc.code, exc.message, 422, exc.detail)
    if not athletes:
        return _err("EMPTY_SLATE", "No usable players were found.", 422, extra.get("importReport"))
    cap_check = None
    if slate.source_salary_cap is not None:
        cap_check = {
            "source": slate.source_salary_cap,
            "ruleset": rs.salary_cap,
            "agrees": slate.source_salary_cap == rs.salary_cap,
        }
    return {
        "ruleset": rs.key,
        "label": (str(body.get("label") or "")[:80] or slate.name),
        "slate": slate.header(),
        "athletes": [a.to_dict() for a in athletes],
        "importReport": extra.get("importReport"),
        "providerReport": extra.get("providerReport"),
        "eligibilityCrossCheck": extra.get("eligibilityCrossCheck"),
        "salaryCapCrossCheck": cap_check,
        "projectionReport": proj_report,
        "platformAverageApplied": averaged,
        "positionsNotInRuleset": sorted({p for a in athletes for p in a.positions} - rs.positions),
    }


async def _save_snapshot(owner: str, rs: Any, snapshot_body: dict[str, Any]) -> JSONResponse:
    h = content_hash({"ruleset": rs.key, "athletes": snapshot_body["athletes"]})
    meta = await run_in_threadpool(store.put_snapshot, owner, rs.key, h, snapshot_body)
    return _ok(_snapshot_view(meta["id"], meta["createdAt"], h, snapshot_body), 201)


@router.post("/slates")
async def create_slate(request: Request):
    """Official platform salary file → canonical slate snapshot.

    With ``ruleset`` the file must match that platform/sport/format
    (``CSV_WRONG_PLATFORM`` otherwise); without it the file is auto-detected.
    """
    owner = _owner(request)
    if isinstance(owner, JSONResponse):
        return owner
    body = await _json_body(request)
    if isinstance(body, JSONResponse):
        return body
    expected = None
    if body.get("ruleset"):
        chosen = get_ruleset(str(body["ruleset"]))
        if chosen is None:
            return _err("RULESET_UNKNOWN", "Choose a supported platform, sport and format.", 400)
        expected = (chosen.platform, chosen.sport, chosen.format)
    try:
        slate, rs, extra = canonical_from_platform_file(
            body.get("salaryCsv") or "", expected, str(body.get("label") or "")[:80] or None
        )
    except ImportError_ as exc:
        status = 409 if exc.code == "CSV_WRONG_PLATFORM" else 422
        return _err(exc.code, exc.message, status, exc.detail)
    snapshot_body = _snapshot_body(slate, rs, extra, body)
    if isinstance(snapshot_body, JSONResponse):
        return snapshot_body
    return await _save_snapshot(owner, rs, snapshot_body)


def _freshness(created: str, body: dict[str, Any]) -> list[dict[str, Any]]:
    """Per information class: where it came from, as of when, and how much it covers.

    A class with no connected source says so; it is never shown as current.
    """
    slate = body.get("slate") or {}
    prov = slate.get("provenance") or {}
    athletes = body.get("athletes") or []
    projected = sum(1 for a in athletes if a.get("projection") is not None)
    sources = sorted({a.get("projection_source") for a in athletes if a.get("projection_source")})
    none = "No source connected yet."
    return [
        {
            "class": "salary",
            "state": "as_imported",
            "source": prov.get("adapter") or "platform file",
            "asOf": prov.get("importedAt") or created,
            "coverage": f"{len(athletes)} players",
            "note": "A file or feed snapshot: salaries can change after this time.",
        },
        {
            "class": "projection",
            "state": "as_imported" if projected else "unavailable",
            "source": ", ".join(sources) or None,
            "asOf": created if projected else None,
            "coverage": f"{projected} of {len(athletes)}",
            "note": None
            if projected
            else "Import projections; missing players are left out, never scored 0.",
        },
        {
            "class": "ownership",
            "state": "unavailable",
            "source": None,
            "asOf": None,
            "coverage": None,
            "note": none,
        },
        {
            "class": "sportsbook",
            "state": "unavailable",
            "source": None,
            "asOf": None,
            "coverage": None,
            "note": none,
        },
        {
            "class": "news",
            "state": "unavailable",
            "source": None,
            "asOf": None,
            "coverage": None,
            "note": none,
        },
        {
            "class": "lineups_status",
            "state": "unavailable",
            "source": None,
            "asOf": None,
            "coverage": None,
            "note": none,
        },
        {
            "class": "podcast",
            "state": "unavailable",
            "source": None,
            "asOf": None,
            "coverage": None,
            "note": none,
        },
    ]


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
        "slate": body.get("slate"),
        "athletes": athletes,
        "games": games,
        "importReport": body.get("importReport"),
        "providerReport": body.get("providerReport"),
        "eligibilityCrossCheck": body.get("eligibilityCrossCheck"),
        "salaryCapCrossCheck": body.get("salaryCapCrossCheck"),
        "projectionReport": body.get("projectionReport"),
        "platformAverageApplied": body.get("platformAverageApplied", 0),
        "positionsNotInRuleset": body.get("positionsNotInRuleset", []),
        "freshness": _freshness(created, body),
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


# ── contests + presets (DFS-§5-05, §6-03, §7-03) ─────────────────────────

PRESETS_PATH = Path(__file__).resolve().parents[2] / "config" / "dfs" / "presets.json"


@router.get("/presets")
async def presets(request: Request):
    owner = _owner(request)
    if isinstance(owner, JSONResponse):
        return owner
    data = json.loads(PRESETS_PATH.read_text(encoding="utf-8"))
    return _ok({"presets": data["presets"]})


def _contest_view(body: dict[str, Any]) -> tuple[Any, dict[str, Any]] | JSONResponse:
    raw = body.get("contest")
    try:
        contest = parse_contest(raw)
    except ContestError as exc:
        return _err(exc.code, exc.message, 422, exc.detail)
    known = {(r["platform"], r["sport"], r["format"]) for r in capability_matrix()}
    if (contest.platform, contest.sport, contest.format) not in known:
        return _err(
            "INVALID_CONTEST", "Choose a platform, sport and format from the capability list.", 422
        )
    report = validate_contest(contest)
    report["tiePreview"] = (
        tied_payout(contest.ladder, 1, 2, contest.tie_rule)
        if contest.ladder and report["ok"]
        else None
    )
    return contest, report


async def _check_slate_link(owner: str, contest: Any) -> JSONResponse | None:
    """A contest may point only at the owner's own slate, for the same platform/sport/format."""
    if contest.slate_id is None:
        return None
    snap = await run_in_threadpool(store.get_snapshot, owner, contest.slate_id)
    if snap is None:
        return _err("NOT_FOUND", "The linked slate does not exist.", 404)
    rs = get_ruleset(snap["ruleset"].split("@", 1)[0])
    if rs is None or (rs.platform, rs.sport, rs.format) != (
        contest.platform,
        contest.sport,
        contest.format,
    ):
        return _err(
            "INVALID_CONTEST",
            "The contest and the linked slate are for different platforms, sports or formats.",
            422,
        )
    return None


def _spend_limit(body: dict[str, Any]) -> int | None | JSONResponse:
    raw = body.get("spendLimit")
    if raw in (None, ""):
        return None
    try:
        return dollars_to_cents(raw, "Spend limit")
    except ContestError as exc:
        return _err(exc.code, exc.message, 422, exc.detail)


@router.post("/contests/validate")
async def contest_validate(request: Request):
    owner = _owner(request)
    if isinstance(owner, JSONResponse):
        return owner
    body = await _json_body(request)
    if isinstance(body, JSONResponse):
        return body
    view = _contest_view(body)
    if isinstance(view, JSONResponse):
        return view
    spend = _spend_limit(body)
    if isinstance(spend, JSONResponse):
        return spend
    contest, report = view
    bad = await _check_slate_link(owner, contest)
    if bad is not None:
        return bad
    return _ok(
        {
            "contest": contest.to_dict(),
            "report": report,
            "entryCap": entry_upper_bound(contest, spend),
        }
    )


@router.post("/contests")
async def contest_save(request: Request):
    owner = _owner(request)
    if isinstance(owner, JSONResponse):
        return owner
    body = await _json_body(request)
    if isinstance(body, JSONResponse):
        return body
    view = _contest_view(body)
    if isinstance(view, JSONResponse):
        return view
    contest, report = view
    bad = await _check_slate_link(owner, contest)
    if bad is not None:
        return bad
    cid = body.get("contestId")
    if cid is not None and not isinstance(cid, str):
        return _err("INVALID_CONTEST", "contestId must be a string.", 400)
    saved = await run_in_threadpool(
        store.put_contest, owner, cid, {"contest": contest.to_dict(), "report": report}
    )
    if saved is None:
        return _err("NOT_FOUND", "No such contest.", 404)
    return _ok(saved, 201)


@router.get("/contests")
async def contest_list(request: Request):
    owner = _owner(request)
    if isinstance(owner, JSONResponse):
        return owner
    return _ok({"contests": await run_in_threadpool(store.list_contests, owner)})


@router.get("/contests/{contest_id}")
async def contest_read(contest_id: str, request: Request):
    owner = _owner(request)
    if isinstance(owner, JSONResponse):
        return owner
    c = await run_in_threadpool(store.get_contest, owner, contest_id)
    if c is None:
        return _err("NOT_FOUND", "No such contest.", 404)
    return _ok(c)


@router.post("/contests/{contest_id}/entry-cap")
async def contest_entry_cap(contest_id: str, request: Request):
    owner = _owner(request)
    if isinstance(owner, JSONResponse):
        return owner
    body = await _json_body(request)
    if isinstance(body, JSONResponse):
        return body
    spend = _spend_limit(body)
    if isinstance(spend, JSONResponse):
        return spend
    rec = await run_in_threadpool(store.get_contest, owner, contest_id)
    if rec is None:
        return _err("NOT_FOUND", "No such contest.", 404)
    contest = parse_contest(_contest_payload(rec["contest"]))
    return _ok(
        {
            "contestId": contest_id,
            "version": rec["version"],
            "entryCap": entry_upper_bound(contest, spend),
        }
    )


def _cents_str(cents: int) -> str:
    """Exact decimal dollars for integer cents — money never passes through a float."""
    return str((Decimal(cents) / 100).quantize(Decimal("0.01")))


def _contest_payload(d: dict[str, Any]) -> dict[str, Any]:
    """Stored (snake_case, cents) contest → the owner payload shape ``parse_contest`` reads."""
    return {
        "name": d["name"],
        "platform": d["platform"],
        "sport": d["sport"],
        "format": d["format"],
        "entryMethod": d["entry_method"],
        "entryFee": None if d["entry_method"] == "free" else _cents_str(d["entry_fee_cents"]),
        "capacity": d["capacity"],
        "currentEntries": d["current_entries"],
        "guaranteed": d["guaranteed"],
        "maxEntriesPerUser": d["max_entries_per_user"],
        "existingUserEntries": d["existing_user_entries"],
        "tieRule": d["tie_rule"],
        "ladderSource": d["ladder_source"],
        "platformContestId": d["platform_contest_id"],
        "notes": d["notes"],
        "slateId": d.get("slate_id"),
        "ladder": [
            {
                "minRank": b["min_rank"],
                "maxRank": b["max_rank"],
                "prize": _cents_str(b["prize_cents"]),
                "kind": b["kind"],
                "value": None if b["value_cents"] is None else _cents_str(b["value_cents"]),
            }
            for b in d["ladder"]
        ],
    }


# ── providers (owner addendum: platform / slate ingestion, DFS-ADD-02/24) ─

PROVIDERS_PATH = Path(__file__).resolve().parents[2] / "config" / "dfs" / "providers.json"


@router.get("/providers")
async def providers_view(request: Request):
    owner = _owner(request)
    if isinstance(owner, JSONResponse):
        return owner
    data = json.loads(PROVIDERS_PATH.read_text(encoding="utf-8"))
    return _ok(
        {
            "providers": data["providers"],
            "matrix": data["matrix"],
            "checkedOn": data.get("checkedOn"),
            "status": {"sportsdataio": dfs_providers.provider_status()},
        }
    )


def _provider_err(exc: "dfs_providers.ProviderError") -> JSONResponse:
    return _err(
        exc.code,
        exc.message,
        exc.status,
        {
            "fallback": "Download the platform's salary CSV and import it — that path is always available."
        },
    )


@router.get("/provider-slates")
async def provider_slates(request: Request, sport: str = "", date: str = "", platform: str = ""):
    owner = _owner(request)
    if isinstance(owner, JSONResponse):
        return owner
    try:
        raw = await run_in_threadpool(dfs_providers.fetch_slates, sport, date)
    except dfs_providers.ProviderError as exc:
        return _provider_err(exc)
    summaries = [dfs_providers.slate_summary(r) for r in raw if isinstance(r, dict)]
    if platform:
        summaries = [x for x in summaries if x["platform"] == platform]
    return _ok({"provider": "sportsdataio", "sport": sport, "date": date, "slates": summaries})


@router.post("/provider-slates/import")
async def provider_slate_import(request: Request):
    owner = _owner(request)
    if isinstance(owner, JSONResponse):
        return owner
    body = await _json_body(request)
    if isinstance(body, JSONResponse):
        return body
    sport, date = str(body.get("sport") or ""), str(body.get("date") or "")
    try:
        raw = await run_in_threadpool(dfs_providers.fetch_slates, sport, date)
        match = [
            r
            for r in raw
            if isinstance(r, dict) and r.get("SlateID") == body.get("providerSlateId")
        ]
        if not match:
            return _err("NOT_FOUND", "That slate is not in the provider's list for this date.", 404)
        slate, report = dfs_providers.canonical_from_sportsdataio(match[0], sport)
    except dfs_providers.ProviderError as exc:
        return _provider_err(exc)
    row = next(
        (
            r
            for r in capability_matrix()
            if (r["platform"], r["sport"], r["format"])
            == (slate.platform, slate.sport, slate.format)
        ),
        None,
    )
    rs = get_ruleset(row["ruleset"].split("@", 1)[0]) if row and row["ruleset"] else None
    if rs is None:
        return _err(
            "UNSUPPORTED_FORMAT",
            f"The provider slate is {slate.platform} {slate.sport.upper()} {slate.format}, whose rules are not encoded yet.",
            422,
        )
    from src.dfs.slate import eligibility_cross_check

    extra = {
        "providerReport": report,
        "eligibilityCrossCheck": eligibility_cross_check(slate.athletes, rs),
    }
    snapshot_body = _snapshot_body(slate, rs, extra, body)
    if isinstance(snapshot_body, JSONResponse):
        return snapshot_body
    return await _save_snapshot(owner, rs, snapshot_body)
