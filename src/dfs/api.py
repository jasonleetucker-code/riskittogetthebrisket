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

from src.dfs import duplication as dfs_duplication
from src.dfs import ownership as dfs_ownership
from src.dfs import jobs as dfs_jobs
from src.dfs import pit, store
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
    apply_ownership_csv,
    apply_platform_average,
    apply_projection_csv,
    content_hash,
)
from src.dfs.outcomes import attach_outcomes
from src.dfs.portfolio import summarize as summarize_portfolio
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


async def _json_body(
    request: Request, max_bytes: int = MAX_BODY_BYTES
) -> dict[str, Any] | JSONResponse:
    raw = await request.body()
    if len(raw) > max_bytes:
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
            proj_report = apply_projection_csv(
                athletes,
                body["projectionCsv"],
                floor_percentile=body.get("floorPercentile"),
                ceiling_percentile=body.get("ceilingPercentile"),
            )
        averaged = apply_platform_average(athletes) if body.get("usePlatformAverage") else 0
        own_report = None
        if body.get("ownershipCsv"):
            own_report = apply_ownership_csv(
                athletes, body["ownershipCsv"], str(body.get("ownershipUnit") or "")
            )
            own_report["marginalCheck"] = _ownership_marginals(athletes, rs)
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
        "ownershipReport": own_report,
        "platformAverageApplied": averaged,
        "positionsNotInRuleset": sorted({p for a in athletes for p in a.positions} - rs.positions),
    }


def _ownership_marginals(athletes: list[SlateAthlete], rs: Any) -> dict[str, Any]:
    """Projected ownership must sum to ~100% per roster slot (e.g. 900% for nine slots).

    Only meaningful with full coverage; a partial file is reported as partial,
    never extrapolated.  Showdown rows (CPT vs FLEX) are summed per row label.
    """
    covered = [a for a in athletes if a.ownership is not None]
    expected = 100.0 * len(rs.slots)
    total = round(sum(a.ownership for a in covered), 2)  # type: ignore[misc]
    if len(covered) < len(athletes):
        state = "partial_coverage"
    elif abs(total - expected) <= 0.15 * expected:
        state = "plausible"
    else:
        state = "implausible"
    return {
        "covered": len(covered),
        "athletes": len(athletes),
        "totalPercent": total,
        "expectedPercent": expected,
        "state": state,
        "note": "Marginal ownership is a diagnostic; it is not a joint lineup probability.",
    }


async def _save_snapshot(owner: str, rs: Any, snapshot_body: dict[str, Any]) -> JSONResponse:
    h = content_hash({"ruleset": rs.key, "athletes": snapshot_body["athletes"]})
    meta = await run_in_threadpool(store.put_snapshot, owner, rs.key, h, snapshot_body)
    # Point-in-time ledger (ADR-DFS-013): index the slate and record what was imported, when.
    pit_record = await run_in_threadpool(
        pit.capture_snapshot,
        owner,
        {
            "id": meta["id"],
            "ruleset": rs.key,
            "contentHash": h,
            "createdAt": meta["createdAt"],
            "body": snapshot_body,
        },
    )
    view = _snapshot_view(meta["id"], meta["createdAt"], h, snapshot_body)
    view["pointInTime"] = {
        "lockAt": pit_record["slate"]["lockAt"],
        "observations": pit_record["observations"],
    }
    return _ok(view, 201)


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
    rows = _freshness_rows(created, body, prov, athletes, projected, sources, none)
    if prov.get("sourceKind") == "auto_derived":
        rows = _auto_freshness(rows, prov, athletes, projected)
    return rows


def _auto_freshness(
    rows: list[dict[str, Any]], prov: dict[str, Any], athletes: list[dict[str, Any]], projected: int
) -> list[dict[str, Any]]:
    """An automatically populated slate: each class says which source filled it, as of when."""
    src = prov.get("sources") or {}
    sal = src.get("salaries") or {}
    proj = src.get("projections") or {}
    families = [k for k, v in proj.items() if (v or {}).get("state") == "ok"]
    statused = sum(1 for a in athletes if a.get("status"))
    replace = {
        "salary": {
            "state": "automatic",
            "source": f"{sal.get('source')} ("
            + ("platform week pool" if prov.get("adapter") == "dfs.auto.nfl" else "listed slate")
            + ")",
            "asOf": sal.get("publishedAt") or sal.get("fetchedAt"),
            "coverage": f"{len(athletes)} players",
            "note": (prov.get("slateDerivationNote") or "Slate game set derived from the schedule.")
            + " Platform player IDs unavailable, so upload files are refused for this slate.",
        },
        "projection": {
            "state": "automatic" if projected else "unavailable",
            "source": " + ".join(families) or None,
            "asOf": src.get("builtAt"),
            "coverage": f"{projected} of {len(athletes)}",
            "note": "Independent families, rescored per platform from stat lines where available. "
            "Players ruled out are left unprojected, never scored 0.",
        },
        "sportsbook": {
            "state": "context_only",
            "source": "dailyfantasyfuel spread/total"
            + (" + nflverse lines" if prov.get("adapter") == "dfs.auto.nfl" else ""),
            "asOf": sal.get("publishedAt") or sal.get("fetchedAt"),
            "coverage": None,
            "note": "Shown as game context; not an input to any projection here.",
        },
        "lineups_status": {
            "state": "automatic" if statused else "unavailable",
            "source": (src.get("status") or {}).get("source"),
            "asOf": src.get("builtAt"),
            "coverage": f"{statused} flagged",
            "note": " ".join(
                ["Injury designations; a player listed Out/IR is withheld from builds."]
                + [str(n) for n in prov.get("notes") or []]
            ),
        },
    }
    return [replace.get(r["class"], r) | {"class": r["class"]} for r in rows]


def _freshness_rows(
    created: str,
    body: dict[str, Any],
    prov: dict[str, Any],
    athletes: list[dict[str, Any]],
    projected: int,
    sources: list[str],
    none: str,
) -> list[dict[str, Any]]:
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
        _distribution_freshness(created, athletes),
        _ownership_freshness(created, body, none),
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


def _distribution_freshness(created: str, athletes: list[dict[str, Any]]) -> dict[str, Any]:
    usable = sum(
        1
        for a in athletes
        if (d := a.get("distribution")) and (d.get("sd") is not None or d.get("quantiles"))
    )
    unassigned = sum(1 for a in athletes if (d := a.get("distribution")) and d.get("unassigned"))
    note = None
    if not usable:
        note = "No outcome ranges imported: builds use the mean projection only."
    if unassigned:
        note = (
            f"{unassigned} floor/ceiling value(s) kept but unused: say which percentiles they are."
        )
    return {
        "class": "distribution",
        "state": "as_imported" if usable else "unavailable",
        "source": "owner_import" if usable else None,
        "asOf": created if usable else None,
        "coverage": f"{usable} of {len(athletes)}" if usable else None,
        "note": note,
    }


def _ownership_freshness(created: str, body: dict[str, Any], none: str) -> dict[str, Any]:
    athletes = body.get("athletes") or []
    owned = sum(1 for a in athletes if a.get("ownership") is not None)
    if not owned:
        return {
            "class": "ownership",
            "state": "unavailable",
            "source": None,
            "asOf": None,
            "coverage": None,
            "note": none,
        }
    check = (body.get("ownershipReport") or {}).get("marginalCheck") or {}
    return {
        "class": "ownership",
        "state": "as_imported",
        "source": "owner_import (projected)",
        "asOf": created,
        "coverage": f"{owned} of {len(athletes)}",
        "note": f"Marginal total {check.get('totalPercent')}% vs {check.get('expectedPercent')}% expected: {check.get('state')}.",
    }


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
        "ownershipReport": body.get("ownershipReport"),
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
    context = await _build_context(owner, body, snap, rs)
    if isinstance(context, JSONResponse):
        return context
    athletes = _athletes_from(snap["body"]["athletes"])
    try:
        constraints = parse_constraints(body.get("constraints"), rs, athletes)
        result = await run_in_threadpool(optimize, rs, athletes, constraints)
        with_range = attach_outcomes(result, athletes)
        result["portfolio"] = summarize_portfolio(result["lineups"])
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
            + (
                " A minimum exposure is forced only once every remaining lineup must carry the player, so "
                "forced appearances sit at the end of the set."
                if constraints.player_min_exposure
                else ""
            )
        ),
        "solver": solver_version(),
        "seed": None,
        "constraints": body.get("constraints") or {},
        "constraintsHash": content_hash(body.get("constraints") or {}),
        "result": result,
        "limits": [
            "Projections are only as good as their source."
            + (
                " Outcome ranges come from your imported player ranges, assume players are independent "
                "(stacked lineups really swing more) and use a normal approximation."
                if with_range
                else " No outcome range: import player ranges (StDev or percentiles) to see one."
            ),
            "No ownership, duplication, field or payout modelling — no ROI or EV is implied.",
            "Rule set not verified against official platform rules — research only."
            if rs.readiness != "money_ready"
            else "Rule set verified.",
        ],
        "submitted": False,
        "contest": context["contest"],
        "preset": context["preset"],
        "disclosures": context["disclosures"],
    }
    saved = await run_in_threadpool(store.put_build, owner, snap["id"], record)
    return _ok(saved, 201)


async def _build_context(
    owner: str, body: dict[str, Any], snap: dict[str, Any], rs: Any
) -> dict[str, Any] | JSONResponse:
    """The contest / preset a build was made FOR, and what the build could not do about it.

    Recorded for provenance and disclosed — this build still maximizes projected
    points; it never pretends to have evaluated the contest.
    """
    contest_view = None
    preset_view = None
    disclosures: list[str] = []
    cid = body.get("contestId")
    if cid is not None:
        if not isinstance(cid, str):
            return _err("INVALID_CONTEST", "contestId must be a string.", 400)
        rec = await run_in_threadpool(store.get_contest, owner, cid)
        if rec is None:
            return _err("NOT_FOUND", "No such contest.", 404)
        c = rec["contest"]
        if (c["platform"], c["sport"], c["format"]) != (rs.platform, rs.sport, rs.format):
            return _err(
                "INVALID_CONTEST",
                "That contest is for a different platform, sport or format than this slate.",
                422,
            )
        if c.get("slate_id") and c["slate_id"] != snap["id"]:
            return _err("INVALID_CONTEST", "That contest is linked to a different slate.", 422)
        derived = rec["report"]["derived"]
        contest_view = {
            "contestId": cid,
            "version": rec["version"],
            "name": c["name"],
            "payoutShape": derived["payoutShape"]["shape"],
            "exactEvAllowed": derived["exactEvAllowed"],
            "evaluated": False,
        }
        disclosures.append(
            "Contest-aware evaluation is unavailable (no validated outcome, ownership or field model yet): "
            f"lineups maximize projected points. \"{c['name']}\" is recorded for provenance only."
        )
        if not derived["exactEvAllowed"]:
            disclosures.append(
                "This contest's payout data is incomplete or hypothetical, so exact contest value could not be computed even with those models."
            )
    pid = body.get("presetId")
    if pid is not None:
        data = json.loads(PRESETS_PATH.read_text(encoding="utf-8"))
        preset = next((p for p in data["presets"] if p["id"] == pid), None)
        if preset is None:
            return _err("INVALID_PRESET", "Unknown strategy preset.", 400)
        preset_view = {
            "id": pid,
            "version": preset["version"],
            "label": preset["label"],
            "validationState": preset["validationState"],
        }
        if preset["validationState"] != "validated":
            disclosures.append(
                f"The {preset['label']} strategy is not available yet ({preset['unsupportedReason']}) — "
                "built with the transparent projection baseline instead."
            )
    if contest_view is None and preset_view is None:
        disclosures.append(
            "No contest or strategy selected: lineups maximize projected points only."
        )
    return {"contest": contest_view, "preset": preset_view, "disclosures": disclosures}


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


# ── automated slates (DFS-AUTO: zero-upload primary workflow) ──────────


@router.get("/auto/slates")
async def auto_slates(request: Request):
    """Automatically populated slates, each with its freshness.  When anything is
    due, a background refresh is queued (the page never waits on a scrape)."""
    owner = _owner(request)
    if isinstance(owner, JSONResponse):
        return owner
    from src.dfs.auto import SYSTEM_OWNER
    from src.dfs.auto import live as auto_live  # registers the refresh job
    from src.dfs.auto import refresh as auto_refresh

    if not auto_live.enabled():
        return _err(
            "FEATURE_DISABLED",
            "Automatic slates are switched off; load the platform file under Advanced.",
            503,
        )
    sport = request.query_params.get("sport") or "nfl"
    platform = request.query_params.get("platform") or None
    if sport not in auto_refresh.AUTO_SPORTS:
        return _ok(
            {
                "sport": sport,
                "state": "UNAVAILABLE",
                "slates": [],
                "reason": "Automatic slates are live for NFL, NBA and NHL; this sport still needs "
                "its platform file (Advanced).",
            }
        )
    if platform is not None and platform not in ("draftkings", "fanduel"):
        return _err("INVALID_QUERY", "platform must be draftkings or fanduel.", 400)
    if not auto_live.sport_approved(sport):
        from src.dfs.auto import approval

        return _ok(
            {
                "sport": sport,
                "state": "AWAITING_APPROVAL",
                "slates": [],
                "reason": approval.awaiting_reason(sport),
                "pendingDecision": approval.sport_status(sport),
            }
        )
    refresh_job = None
    if await run_in_threadpool(auto_refresh.is_due, sport):
        try:
            refresh_job = (
                await run_in_threadpool(
                    dfs_jobs.submit, SYSTEM_OWNER, "dfs_auto_refresh", {"sport": sport}
                )
            )["state"]
        except dfs_jobs.JobError as exc:
            refresh_job = exc.code  # QUEUE_FULL = one is already running
    out = await run_in_threadpool(auto_refresh.list_slates, sport, platform)
    out["refreshQueued"] = refresh_job
    return _ok(out)


@router.post("/auto/slates/select")
async def auto_slate_select(request: Request):
    """Put an automatic slate into the owner's workspace (an owner-scoped copy, so
    every build, simulation and portfolio stays private and reproducible)."""
    owner = _owner(request)
    if isinstance(owner, JSONResponse):
        return owner
    body = await _json_body(request)
    if isinstance(body, JSONResponse):
        return body
    from src.dfs.auto import SYSTEM_OWNER
    from src.dfs.auto import live as auto_live
    from src.dfs.auto import refresh as auto_refresh

    if not auto_live.enabled():
        return _err("FEATURE_DISABLED", "Automatic slates are switched off.", 503)
    row = await run_in_threadpool(auto_refresh.get_row, str(body.get("autoSlateId") or ""))
    if row is None:
        return _err("NOT_FOUND", "No such automatic slate.", 404)
    if not auto_live.sport_approved(row["sport"]):
        from src.dfs.auto import approval

        return _err("AWAITING_OWNER_APPROVAL", approval.awaiting_reason(row["sport"]), 409)
    src_snap = await run_in_threadpool(store.get_snapshot, SYSTEM_OWNER, row["snapshotId"])
    if src_snap is None:
        return _err("NOT_FOUND", "The automatic slate's data is missing; refresh again.", 404)
    rs = get_ruleset(src_snap["ruleset"].split("@", 1)[0])
    if rs is None or rs.key != src_snap["ruleset"]:
        return _err("RULESET_SUPERSEDED", "This slate was built under an older rule set.", 409)
    existing = await run_in_threadpool(store.find_snapshot, owner, src_snap["contentHash"], rs.key)
    if existing:
        snap = await run_in_threadpool(store.get_snapshot, owner, existing)
        view = _snapshot_view(snap["id"], snap["createdAt"], snap["contentHash"], snap["body"])
        view["reused"] = True
        return _ok(view)
    return await _save_snapshot(owner, rs, src_snap["body"])


# ── entry files (existing platform entries; nothing is ever submitted) ────


def _entries_error(exc: ImportError_) -> JSONResponse:
    return _err(exc.code, exc.message, 422, exc.detail)


@router.post("/entries/parse")
async def entries_parse(request: Request):
    owner = _owner(request)
    if isinstance(owner, JSONResponse):
        return owner
    body = await _json_body(request)
    if isinstance(body, JSONResponse):
        return body
    snap = await run_in_threadpool(store.get_snapshot, owner, str(body.get("snapshotId") or ""))
    if snap is None:
        return _err("NOT_FOUND", "No such slate.", 404)
    rs = get_ruleset(snap["ruleset"].split("@", 1)[0])
    if rs is None:
        return _err(
            "RULESET_SUPERSEDED", "This slate's rule-set version is no longer current.", 409
        )
    from src.dfs.entries import parse_entries

    try:
        parsed = parse_entries(
            body.get("entriesCsv") or "", rs, _athletes_from(snap["body"]["athletes"])
        )
    except ImportError_ as exc:
        return _entries_error(exc)
    return _ok(parsed)


@router.post("/ownership/forecast")
async def ownership_forecast(request: Request):
    """Projected ownership for one slate as of a time before lock (default: now)."""
    owner = _owner(request)
    if isinstance(owner, JSONResponse):
        return owner
    body = await _json_body(request)
    if isinstance(body, JSONResponse):
        return body
    snap = await run_in_threadpool(store.get_snapshot, owner, str(body.get("snapshotId") or ""))
    if snap is None:
        return _err("NOT_FOUND", "No such slate.", 404)
    rs = get_ruleset(snap["ruleset"].split("@", 1)[0])
    if rs is None:
        return _err(
            "RULESET_SUPERSEDED", "This slate's rule-set version is no longer current.", 409
        )
    overrides = body.get("overrides") or {}
    if not isinstance(overrides, dict) or not all(
        isinstance(v, (int, float)) and not isinstance(v, bool) and 0 <= v <= 100
        for v in overrides.values()
    ):
        return _err("INVALID_BODY", "overrides must map player ID to a percent from 0 to 100.", 400)
    if await run_in_threadpool(pit.get_slate, owner, snap["id"]) is None:
        await run_in_threadpool(pit.capture_snapshot, owner, snap)
    try:
        fc = await run_in_threadpool(
            lambda: dfs_ownership.forecast(
                owner, snap, rs, body.get("asOf") or pit.now(), overrides=overrides
            )
        )
    except pit.PitError as exc:
        return _err(
            exc.code, exc.message, 409 if exc.code in ("AFTER_LOCK", "LOCK_UNKNOWN") else 422
        )
    except ValueError:
        return _err("INVALID_CLOCK", "asOf must be an ISO time with a timezone.", 422)
    return _ok(fc)


@router.post("/simulate")
async def simulate_build(request: Request):
    """Contest Monte Carlo for a build's lineups in one exact contest (bounded; model output only)."""
    from src.dfs import pipeline
    from src.dfs.contests import contest_from_dict

    owner = _owner(request)
    if isinstance(owner, JSONResponse):
        return owner
    body = await _json_body(request)
    if isinstance(body, JSONResponse):
        return body

    def bounded(key: str, default: int, hi: int) -> int | None:
        v = body.get(key, default)
        return v if isinstance(v, int) and not isinstance(v, bool) and 1 <= v <= hi else None

    sims = bounded("sims", 1000, pipeline.API_MAX_SIMS)
    sample = bounded("fieldSample", 2000, pipeline.API_MAX_FIELD_SAMPLE)
    seed = bounded("seed", 1, 2**31 - 1)
    if sims is None or sample is None or seed is None:
        return _err(
            "INVALID_BODY",
            f"sims 1..{pipeline.API_MAX_SIMS}, fieldSample 1..{pipeline.API_MAX_FIELD_SAMPLE}, seed a positive integer.",
            400,
        )
    b = await run_in_threadpool(store.get_build, owner, str(body.get("buildId") or ""))
    if b is None:
        return _err("NOT_FOUND", "No such build.", 404)
    snap = await run_in_threadpool(store.get_snapshot, owner, b["snapshot"]["id"])
    rs = get_ruleset(b["ruleset"]["key"].split("@", 1)[0])
    if snap is None or rs is None or rs.key != b["ruleset"]["key"]:
        return _err(
            "RULESET_SUPERSEDED",
            "This build's slate or rule-set version is no longer current.",
            409,
        )
    ctx = await _build_context(owner, {"contestId": body.get("contestId")}, snap, rs)
    if isinstance(ctx, JSONResponse):
        return ctx
    rec = await run_in_threadpool(store.get_contest, owner, str(body.get("contestId") or ""))
    if rec is None:
        return _err("NOT_FOUND", "Choose a saved contest to simulate against.", 404)
    lineups = [tuple(p["playerId"] for p in lu["players"]) for lu in b["result"]["lineups"]]
    if not lineups:
        return _err("NOTHING_TO_SIMULATE", "This build has no lineups.", 409)

    def run():
        prep = pipeline.prepare(
            owner,
            snap,
            rs,
            contest_from_dict(rec["contest"]),
            body.get("asOf") or pit.now(),
            sims=sims,
            field_sample=sample,
            seed=seed,
            allow_priors=bool(body.get("allowPriors")),
            must_cover={p for lu in lineups for p in lu},
        )
        return pipeline.simulate_lineups(prep, lineups)

    try:
        out = await run_in_threadpool(run)
    except pipeline.PipelineError as exc:
        return _err(exc.code, exc.message, 422, exc.detail)
    except pit.PitError as exc:
        return _err(
            exc.code, exc.message, 409 if exc.code in ("AFTER_LOCK", "LOCK_UNKNOWN") else 422
        )
    out["buildId"] = b["buildId"]
    out["contest"] = {
        "contestId": body.get("contestId"),
        "version": rec["version"],
        "name": rec["contest"]["name"],
    }
    return _ok(out)


@router.post("/portfolio")
async def build_contest_portfolio(request: Request):
    """Contest-aware portfolio: candidates → simulated payouts → objective → frozen decision.

    Decision support only: it enters nothing.  Bounded like ``/simulate``.
    """
    from src.dfs import pipeline, portfolio_opt
    from src.dfs.contests import ContestError, contest_from_dict, dollars_to_cents

    owner = _owner(request)
    if isinstance(owner, JSONResponse):
        return owner
    body = await _json_body(request)
    if isinstance(body, JSONResponse):
        return body

    def bounded(key: str, default: int, hi: int) -> int | None:
        v = body.get(key, default)
        return v if isinstance(v, int) and not isinstance(v, bool) and 1 <= v <= hi else None

    sims = bounded("sims", 800, pipeline.API_MAX_SIMS)
    sample = bounded("fieldSample", 1500, pipeline.API_MAX_FIELD_SAMPLE)
    seed = bounded("seed", 1, 2**31 - 1)
    entries = bounded("entries", 1, portfolio_opt.MAX_ENTRIES)
    objective = body.get("objective", "ev")
    if None in (sims, sample, seed, entries) or objective not in portfolio_opt.OBJECTIVES:
        return _err(
            "INVALID_BODY",
            f"entries 1..{portfolio_opt.MAX_ENTRIES}, sims 1..{pipeline.API_MAX_SIMS}, fieldSample 1.."
            f"{pipeline.API_MAX_FIELD_SAMPLE}, objective one of {', '.join(portfolio_opt.OBJECTIVES)}.",
            400,
        )
    try:
        bankroll = dollars_to_cents(body["bankroll"], "Bankroll") if body.get("bankroll") else None
        spend = (
            dollars_to_cents(body["spendLimit"], "Spend limit") if body.get("spendLimit") else None
        )
    except ContestError as exc:
        return _err(exc.code, exc.message, 400)
    snap = await run_in_threadpool(store.get_snapshot, owner, str(body.get("snapshotId") or ""))
    if snap is None:
        return _err("NOT_FOUND", "No such slate.", 404)
    rs = get_ruleset(snap["ruleset"].split("@", 1)[0])
    if rs is None or rs.key != snap["ruleset"]:
        return _err(
            "RULESET_SUPERSEDED", "This slate's rule-set version is no longer current.", 409
        )
    ctx = await _build_context(owner, {"contestId": body.get("contestId")}, snap, rs)
    if isinstance(ctx, JSONResponse):
        return ctx
    rec = await run_in_threadpool(store.get_contest, owner, str(body.get("contestId") or ""))
    if rec is None:
        return _err("NOT_FOUND", "Choose a saved contest.", 404)
    athletes = _athletes_from(snap["body"]["athletes"])
    try:
        base = parse_constraints(body.get("constraints"), rs, athletes)
    except ConstraintError as exc:
        return _err(exc.code, exc.message, 422, exc.detail)

    def run():
        return portfolio_opt.build_portfolio(
            owner,
            snap,
            rs,
            contest_from_dict(rec["contest"]),
            body.get("asOf") or pit.now(),
            base=base,
            entries=entries,
            objective=objective,
            bankroll=bankroll,
            sims=sims,
            field_sample=sample,
            seed=seed,
            allow_priors=bool(body.get("allowPriors")),
            spend_limit_cents=spend,
        )

    try:
        out = await run_in_threadpool(run)
    except pipeline.PipelineError as exc:
        return _err(exc.code, exc.message, 422, exc.detail)
    except pit.PitError as exc:
        return _err(
            exc.code, exc.message, 409 if exc.code in ("AFTER_LOCK", "LOCK_UNKNOWN") else 422
        )
    except ValueError as exc:
        return _err("INVALID_BODY", str(exc), 400)
    return _ok(out)


def _backtest_params(body: dict[str, Any]) -> dict[str, Any] | JSONResponse:
    from src.dfs import pipeline

    items = body.get("items") or []
    replay = bool(body.get("replayPortfolio"))
    limit = 10 if replay else 200
    if (
        not isinstance(items, list)
        or not 1 <= len(items) <= limit
        or not all(isinstance(i, dict) and isinstance(i.get("resultId"), str) for i in items)
    ):
        return _err("INVALID_BODY", f"items: 1..{limit} objects with a resultId.", 400)
    sims = body.get("sims", 400)
    sample = body.get("fieldSample", 800)
    if not (isinstance(sims, int) and 1 <= sims <= pipeline.API_MAX_SIMS) or not (
        isinstance(sample, int) and 1 <= sample <= pipeline.API_MAX_FIELD_SAMPLE
    ):
        return _err("INVALID_BODY", "sims / fieldSample out of range.", 400)
    return {
        "items": [
            {
                "resultId": i["resultId"],
                **({"contestId": i["contestId"]} if isinstance(i.get("contestId"), str) else {}),
            }
            for i in items
        ],
        "replayPortfolio": replay,
        "entries": int(body.get("entries") or 3),
        "sims": sims,
        "fieldSample": sample,
        "allowPriors": bool(body.get("allowPriors")),
    }


def _backtest_job(owner: str, p: dict[str, Any]) -> dict[str, Any]:
    from src.dfs import backtest

    return backtest.run(
        owner,
        p["items"],
        replay_portfolio=p["replayPortfolio"],
        entries=p["entries"],
        sims=p["sims"],
        field_sample=p["fieldSample"],
        allow_priors=p["allowPriors"],
    )


dfs_jobs.register("backtest")(_backtest_job)


@router.post("/backtest")
async def run_backtest(request: Request):
    """Chronological point-in-time replay over the owner's settled contests (historical evidence).

    Synchronous and bounded; long replays belong in ``POST /api/dfs/jobs`` (kind ``backtest``).
    """
    owner = _owner(request)
    if isinstance(owner, JSONResponse):
        return owner
    body = await _json_body(request)
    if isinstance(body, JSONResponse):
        return body
    params = _backtest_params(body)
    if isinstance(params, JSONResponse):
        return params
    try:
        out = await run_in_threadpool(_backtest_job, owner, params)
    except pit.PitError as exc:
        return _err(exc.code, exc.message, 422)
    return _ok(out)


@router.post("/jobs")
async def submit_job(request: Request):
    """Queue long DFS work; answers 202 with a job id to poll."""
    owner = _owner(request)
    if isinstance(owner, JSONResponse):
        return owner
    body = await _json_body(request)
    if isinstance(body, JSONResponse):
        return body
    if body.get("kind") != "backtest":
        return _err("UNKNOWN_JOB_KIND", "Supported job kinds: backtest.", 400)
    params = _backtest_params(body.get("params") or {})
    if isinstance(params, JSONResponse):
        return params
    try:
        job = await run_in_threadpool(dfs_jobs.submit, owner, "backtest", params)
    except dfs_jobs.JobError as exc:
        return _err(exc.code, exc.message, 429 if exc.code == "QUEUE_FULL" else 400)
    return _ok(job, 202)


@router.get("/jobs/{job_id}")
async def read_job(job_id: str, request: Request):
    owner = _owner(request)
    if isinstance(owner, JSONResponse):
        return owner
    job = await run_in_threadpool(dfs_jobs.get, owner, job_id)
    return _ok(job) if job else _err("NOT_FOUND", "No such job.", 404)


@router.get("/evaluations")
async def list_evaluations(request: Request):
    """Stored forecast / model evaluations (scorecards), each with its sample size."""
    owner = _owner(request)
    if isinstance(owner, JSONResponse):
        return owner
    kind = request.query_params.get("kind")
    if kind is not None and kind not in ("ownership", "duplication", "backtest"):
        return _err("INVALID_QUERY", "kind must be ownership, duplication or backtest.", 400)
    rows = await run_in_threadpool(pit.list_evaluations, owner, kind)
    return _ok({"evaluations": rows[-200:], "total": len(rows)})


@router.post("/sources/dailyfantasyfuel/pull")
async def pull_dailyfantasyfuel(request: Request):
    """Owner-triggered, cached pull of Daily Fantasy Fuel projections + game context for a slate."""
    from src.dfs import sources_dff

    owner = _owner(request)
    if isinstance(owner, JSONResponse):
        return owner
    body = await _json_body(request)
    if isinstance(body, JSONResponse):
        return body
    snap = await run_in_threadpool(store.get_snapshot, owner, str(body.get("snapshotId") or ""))
    if snap is None:
        return _err("NOT_FOUND", "No such slate.", 404)
    rs = get_ruleset(snap["ruleset"].split("@", 1)[0])
    if rs is None:
        return _err(
            "RULESET_SUPERSEDED", "This slate's rule-set version is no longer current.", 409
        )
    athletes = _athletes_from(snap["body"]["athletes"])
    try:
        out = await run_in_threadpool(
            sources_dff.pull, owner, snap, rs.sport, rs.platform, athletes
        )
    except sources_dff.SourceError as exc:
        status = 503 if exc.code == "PROVIDER_UNAVAILABLE" else 422
        return _err(exc.code, exc.message, status)
    return _ok(out)


@router.post("/results")
async def import_results(request: Request):
    """Import a finished contest's standings for one slate and evaluate the owner's forecasts."""
    from src.dfs.contests import contest_from_dict
    from src.dfs.results import MAX_RESULTS_BYTES, evaluate, parse_standings
    from src.dfs.settlement import settle

    owner = _owner(request)
    if isinstance(owner, JSONResponse):
        return owner
    body = await _json_body(request, max_bytes=MAX_RESULTS_BYTES + 64 * 1024)
    if isinstance(body, JSONResponse):
        return body
    snap = await run_in_threadpool(store.get_snapshot, owner, str(body.get("snapshotId") or ""))
    if snap is None:
        return _err("NOT_FOUND", "No such slate.", 404)
    rs = get_ruleset(snap["ruleset"].split("@", 1)[0])
    if rs is None:
        return _err(
            "RULESET_SUPERSEDED", "This slate's rule-set version is no longer current.", 409
        )
    athletes = _athletes_from(snap["body"]["athletes"])
    owner_ids = body.get("ownerEntryIds") or []
    username = body.get("ownerUsername")
    if not isinstance(owner_ids, list) or not all(isinstance(x, str) for x in owner_ids):
        return _err("INVALID_BODY", "ownerEntryIds must be a list of entry IDs.", 400)
    if username is not None and (not isinstance(username, str) or len(username) > 80):
        return _err("INVALID_BODY", "ownerUsername must be a short string.", 400)
    contest = None
    if body.get("contestId") is not None:
        # Same ownership / platform / slate-link checks a build applies.
        ctx = await _build_context(owner, {"contestId": body["contestId"]}, snap, rs)
        if isinstance(ctx, JSONResponse):
            return ctx
        rec = await run_in_threadpool(store.get_contest, owner, body["contestId"])
        contest = contest_from_dict(rec["contest"])
    try:
        parsed = await run_in_threadpool(
            lambda: parse_standings(
                body.get("standingsCsv") or "",
                rs,
                athletes,
                owner_entry_ids=owner_ids[:1000],
                owner_username=username,
            )
        )
    except ImportError_ as exc:
        return _err(exc.code, exc.message, 422, exc.detail)
    if not parsed["realized"]:
        return _err(
            "NO_PLAYERS_MATCHED",
            "No player in the results file matched this slate.",
            422,
            {"quarantined": parsed["quarantined"][:20]},
        )
    own_eval = await run_in_threadpool(
        dfs_ownership.evaluate_against_results, owner, snap, rs, parsed["realized"]
    )
    dup_eval = {"state": "unavailable", "reason": "no pre-lock ownership forecast"}
    if own_eval.get("state") == "evaluated" and parsed.get("duplication"):
        field_size = sum(c for _, c in parsed["pointsCounts"]) + parsed["unscoredEntries"]
        rows = dfs_duplication.rows_from_result(
            parsed["duplication"].get("fitSample"),
            own_eval["forecastOwnership"],
            {a.player_id: a.salary for a in athletes},
            rs.salary_cap,
            field_size,
        )
        dup_eval = dfs_duplication.evaluate_result(owner, own_eval["scope"], own_eval["refs"], rows)
    record = {
        **parsed,
        "evaluation": evaluate(athletes, parsed["realized"]),
        # DFS-MOD-02/10: each source, the ensemble and the structural baseline,
        # each forecast as of lock, scored against realized ownership.
        "ownershipEvaluation": {k: v for k, v in own_eval.items() if k != "forecastOwnership"},
        "duplicationEvaluation": dup_eval,
        "settlement": (
            settle(
                contest,
                parsed["pointsCounts"],
                parsed["ownerEntries"],
                unscored_entries=parsed["unscoredEntries"],
            )
            if contest is not None
            else None
        ),
        "contestRef": (
            {"contestId": body["contestId"], "version": rec["version"]}
            if contest is not None
            else None
        ),
        "evidenceClaim": "shadow",  # evaluation evidence; it changes no model or weight
    }
    saved = await run_in_threadpool(store.put_result, owner, snap["id"], record)
    return _ok(saved, 201)


@router.get("/results/{result_id}")
async def read_result(result_id: str, request: Request):
    owner = _owner(request)
    if isinstance(owner, JSONResponse):
        return owner
    r = await run_in_threadpool(store.get_result, owner, result_id)
    return _ok(r) if r else _err("NOT_FOUND", "No such result.", 404)


async def _late_swap_inputs(request: Request):
    """(owner, ruleset, athletes, parsed entries, clock, clock source) or an error response."""
    from datetime import datetime, timezone

    from src.dfs.entries import parse_entries

    owner = _owner(request)
    if isinstance(owner, JSONResponse):
        return owner
    body = await _json_body(request)
    if isinstance(body, JSONResponse):
        return body
    snap = await run_in_threadpool(store.get_snapshot, owner, str(body.get("snapshotId") or ""))
    if snap is None:
        return _err("NOT_FOUND", "No such slate.", 404)
    rs = get_ruleset(snap["ruleset"].split("@", 1)[0])
    if rs is None or rs.key != snap["ruleset"]:
        return _err(
            "RULESET_SUPERSEDED", "This slate's rule-set version is no longer current.", 409
        )
    clock_source = "server"
    now = datetime.now(timezone.utc)
    if body.get("asOf") is not None:
        # A what-if clock ("plan as of 4:05 PM") — labelled, never the default.
        try:
            now = datetime.fromisoformat(str(body["asOf"]).replace("Z", "+00:00"))
        except ValueError:
            now = None  # type: ignore[assignment]
        if now is None or now.tzinfo is None:
            return _err("INVALID_CLOCK", "asOf must be an ISO time with a timezone.", 422)
        clock_source = "owner_supplied"
    athletes = _athletes_from(snap["body"]["athletes"])
    try:
        parsed = parse_entries(body.get("entriesCsv") or "", rs, athletes)
    except ImportError_ as exc:
        return _entries_error(exc)
    return rs, athletes, parsed, now, clock_source


@router.post("/late-swap")
async def late_swap_plan(request: Request):
    """Plan late swaps for the owner's imported entries.  Recommends; never submits."""
    got = await _late_swap_inputs(request)
    if isinstance(got, JSONResponse):
        return got
    rs, athletes, parsed, now, clock_source = got
    from src.dfs.lateswap import plan_late_swap

    plan = await run_in_threadpool(plan_late_swap, rs, athletes, parsed["entries"], now)
    return _ok(
        {**plan, "clockSource": clock_source, "layoutVerification": parsed["layoutVerification"]}
    )


@router.post("/late-swap/export")
async def late_swap_export(request: Request):
    """The planned final lineups as an entry file the owner uploads themselves."""
    got = await _late_swap_inputs(request)
    if isinstance(got, JSONResponse):
        return got
    rs, athletes, parsed, now, clock_source = got
    from src.dfs.lateswap import export_late_swap, plan_late_swap

    plan = await run_in_threadpool(plan_late_swap, rs, athletes, parsed["entries"], now)
    try:
        text, report = export_late_swap(
            rs, plan, parsed["entries"], athletes, parsed.get("exportLayout")
        )
    except ImportError_ as exc:
        return _entries_error(exc)
    if not report["written"]:
        return _err("NOTHING_TO_EXPORT", "No entry could be planned.", 409, report)
    return Response(
        content=text,
        media_type="text/csv; charset=utf-8",
        headers={
            "Content-Disposition": f'attachment; filename="{rs.platform}-{rs.sport}-{rs.format}-LATE-SWAP-UNVERIFIED-FORMAT.csv"',
            "Cache-Control": "no-store",
            "X-DFS-Export-Verified": "false",
            "X-DFS-Clock-Source": clock_source,
            "X-DFS-Entries-Written": str(len(report["written"])),
            "X-DFS-Entries-Skipped": str(len(report["skipped"])),
        },
    )


@router.post("/builds/{build_id}/export-entries")
async def export_build_into_entries(build_id: str, request: Request):
    """Fill this build's lineups into the owner's existing entry IDs (re-validated)."""
    owner = _owner(request)
    if isinstance(owner, JSONResponse):
        return owner
    body = await _json_body(request)
    if isinstance(body, JSONResponse):
        return body
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
    from src.dfs.entries import export_into_entries, parse_entries

    athletes = _athletes_from(snap["body"]["athletes"])
    try:
        parsed = parse_entries(body.get("entriesCsv") or "", rs, athletes)
        text, report = export_into_entries(
            rs, b["result"]["lineups"], parsed["entries"], athletes, parsed.get("exportLayout")
        )
    except ImportError_ as exc:
        return _entries_error(exc)
    if not report["assigned"]:
        return _err(
            "NOTHING_TO_EXPORT", "No usable entries or no lineups to place in them.", 409, report
        )
    return Response(
        content=text,
        media_type="text/csv; charset=utf-8",
        headers={
            "Content-Disposition": f'attachment; filename="{rs.platform}-{rs.sport}-{rs.format}-{build_id}-ENTRIES-UNVERIFIED-FORMAT.csv"',
            "Cache-Control": "no-store",
            "X-DFS-Export-Verified": "false",
            "X-DFS-Entries-Assigned": str(len(report["assigned"])),
            "X-DFS-Entries-Untouched": str(len(report["untouchedEntries"])),
        },
    )
