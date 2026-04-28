"""FastAPI router for /api/ros/* endpoints.

Mounted from server.py via ``app.include_router(ros_router)``.

Endpoints (all read-only on the authenticated league context):

    GET  /api/ros/sources         — registry + per-source enable state
    GET  /api/ros/status          — last-run metadata per source
    GET  /api/ros/player-values   — aggregated player values
    GET  /api/ros/team-strength   — per-team composite + lineup breakdown
    POST /api/ros/refresh         — admin only; runs the orchestrator

Isolation invariant: this router writes to ``data/ros/*`` only.  It
never touches ``data/exports/*``, ``CSVs/site_raw/*``, or any dynasty
contract path.
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse

from src.ros import ROS_DATA_DIR
from src.ros.sources import ROS_SOURCES, enabled_ros_sources
from src.ros.team_strength import (
    compute_team_strength,
    load_team_strength_snapshot,
    write_team_strength_snapshot,
)

LOG = logging.getLogger("ros.api")

router = APIRouter(prefix="/api/ros", tags=["ros"])


def _read_json(path) -> Any:
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text())
    except (json.JSONDecodeError, OSError):
        return None


def _registry_payload(overrides: dict[str, dict[str, Any]] | None = None) -> list[dict[str, Any]]:
    """Strip internal fields (scraper module path) from the registry."""
    enabled = {s["key"] for s in enabled_ros_sources(overrides)}
    out: list[dict[str, Any]] = []
    for src in ROS_SOURCES:
        public = {
            k: v for k, v in src.items() if k not in {"scraper"}
        }
        public["effectivelyEnabled"] = src["key"] in enabled
        out.append(public)
    return out


@router.get("/sources")
async def get_sources() -> JSONResponse:
    return JSONResponse({"sources": _registry_payload()})


@router.get("/status")
async def get_status() -> JSONResponse:
    """Last-run metadata per source — drives source-health UI."""
    index = _read_json(ROS_DATA_DIR / "runs" / "index.json")
    if not index:
        return JSONResponse(
            {
                "rebuiltAt": None,
                "sources": {},
                "freshness": "no_runs",
            }
        )
    return JSONResponse(
        {
            "rebuiltAt": index.get("rebuiltAt"),
            "sources": index.get("sources") or {},
            "freshness": _classify_overall_freshness(index),
        }
    )


def _classify_overall_freshness(index: dict[str, Any]) -> str:
    rebuilt = index.get("rebuiltAt")
    if not rebuilt:
        return "no_runs"
    try:
        when = datetime.fromisoformat(rebuilt.replace("Z", "+00:00"))
    except ValueError:
        return "unknown"
    age_h = (
        datetime.now(timezone.utc) - when.astimezone(timezone.utc)
    ).total_seconds() / 3600
    if age_h < 24:
        return "fresh"
    if age_h < 72:
        return "amber"
    return "stale"


@router.get("/player-values")
async def get_player_values(limit: int = 500) -> JSONResponse:
    """Aggregated player values; defaults to top 500 by ros_value."""
    payload = _read_json(ROS_DATA_DIR / "aggregate" / "latest.json")
    if not payload:
        return JSONResponse(
            {"aggregatedAt": None, "players": [], "error": "no_aggregate"}
        )
    players = payload.get("players") or []
    return JSONResponse(
        {
            "aggregatedAt": payload.get("aggregatedAt"),
            "league": payload.get("league"),
            "playerCount": payload.get("playerCount") or len(players),
            "sourceCount": payload.get("sourceCount"),
            "players": players[: max(1, min(limit, len(players)))],
        }
    )


@router.get("/team-strength")
async def get_team_strength(request: Request, leagueKey: str | None = None) -> JSONResponse:
    """Per-team ROS strength composite.

    PR 1 reads the latest cached snapshot.  Real-time recomputation
    against the live Sleeper roster ships in PR 2 once the public
    contract's lazy section builder is wired.
    """
    _ = leagueKey  # PR 1 single-league only; PR 2 routes per-league
    snapshot = load_team_strength_snapshot()
    if snapshot is None:
        return JSONResponse(
            {"teams": [], "error": "no_snapshot"}, status_code=200
        )
    return JSONResponse({"teams": snapshot, "leagueKey": leagueKey})


@router.post("/refresh")
async def post_refresh(request: Request) -> JSONResponse:
    """Admin-only manual scrape trigger.

    PR 1 gates on the same admin session check the rest of /api/admin
    uses.  Long-running so we run it on the threadpool to avoid
    blocking the event loop.
    """
    # Late import to keep test environments happy: server.py owns the
    # admin auth helper and hosts the FastAPI app.
    from server import _require_admin_session  # type: ignore[attr-defined]
    from fastapi.concurrency import run_in_threadpool

    if not _require_admin_session(request):
        raise HTTPException(status_code=401, detail="admin_required")

    from src.ros.scrape import run_all  # late import to avoid circulars

    summary = await run_in_threadpool(run_all)
    return JSONResponse(summary)


# Public function surfaced to public_contract for the lazy section
# builder.  Signature matches the existing
# ``Callable[[PublicLeagueSnapshot], dict[str, Any]]`` shape so the
# section can be registered alongside playoffOdds in
# ``_LAZY_SECTION_BUILDERS``.  The snapshot is currently unused — PR1
# reads only the cached ``data/ros/team_strength/latest.json`` — but
# threading it through keeps the contract consistent for PR2 when
# we'll recompute from live rosters.
def build_section(snapshot: Any) -> dict[str, Any]:
    """Lazy-section builder: return the cached ROS team-strength snapshot."""
    _ = snapshot  # PR2 uses snapshot for live recomputation
    payload = load_team_strength_snapshot()
    return {
        "teams": payload or [],
        "computedAt": datetime.now(timezone.utc).isoformat(),
        "stale": payload is None,
    }
