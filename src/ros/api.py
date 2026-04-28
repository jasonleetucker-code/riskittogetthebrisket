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
    """Per-team ROS strength composite for the requested league.

    Resolves ``leagueKey`` via the standard registry chain (alias →
    canonical → default), then loads the per-league snapshot file.
    Default-league snapshots live at the historical
    ``team_strength/latest.json`` path; non-default keys namespace
    under ``team_strength/<leagueKey>.json``.
    """
    resolved_key = leagueKey
    try:
        from src.api.league_registry import get_league_by_key, default_league_key  # noqa: PLC0415
        if leagueKey:
            cfg = get_league_by_key(leagueKey)
            if cfg and cfg.key:
                resolved_key = cfg.key
        else:
            resolved_key = default_league_key()
    except Exception:  # noqa: BLE001
        pass
    snapshot = load_team_strength_snapshot(resolved_key)
    if snapshot is None:
        return JSONResponse(
            {"teams": [], "leagueKey": resolved_key, "error": "no_snapshot"},
            status_code=200,
        )
    return JSONResponse({"teams": snapshot, "leagueKey": resolved_key})


@router.get("/health")
async def get_health() -> JSONResponse:
    """Combined ROS pipeline health snapshot.

    Bundles per-source last-run state, aggregate freshness, sim
    cache ages, team-strength snapshot age + team count, and total
    unmapped-roster-player counts in one payload so the
    /tools/ros-data-health page renders without N+1 fetches.
    """
    import os
    import time

    index = _read_json(ROS_DATA_DIR / "runs" / "index.json") or {}
    aggregate = _read_json(ROS_DATA_DIR / "aggregate" / "latest.json") or {}
    team_strength = load_team_strength_snapshot() or []
    playoff_path = ROS_DATA_DIR / "sims" / "latest_playoff.json"
    champ_path = ROS_DATA_DIR / "sims" / "latest_championship.json"

    def _file_age_seconds(path) -> float | None:
        try:
            return time.time() - os.path.getmtime(path)
        except OSError:
            return None

    def _iso_to_age_seconds(iso: str | None) -> float | None:
        if not iso:
            return None
        try:
            when = datetime.fromisoformat(str(iso).replace("Z", "+00:00"))
        except ValueError:
            return None
        return (
            datetime.now(timezone.utc) - when.astimezone(timezone.utc)
        ).total_seconds()

    unmapped_total = sum(
        int(t.get("unmappedPlayerCount") or 0) for t in team_strength
    )

    return JSONResponse(
        {
            "rebuiltAt": index.get("rebuiltAt"),
            "freshness": _classify_overall_freshness(index),
            "sources": index.get("sources") or {},
            "aggregate": {
                "aggregatedAt": aggregate.get("aggregatedAt"),
                "playerCount": aggregate.get("playerCount")
                or len(aggregate.get("players") or []),
                "sourceCount": aggregate.get("sourceCount"),
                "ageSeconds": _iso_to_age_seconds(aggregate.get("aggregatedAt")),
            },
            "teamStrength": {
                "teamCount": len(team_strength),
                "unmappedTotal": unmapped_total,
                "perTeam": [
                    {
                        "teamName": t.get("teamName"),
                        "teamRosStrength": t.get("teamRosStrength"),
                        "unmappedPlayerCount": t.get("unmappedPlayerCount"),
                        "rank": t.get("rank"),
                    }
                    for t in team_strength
                ],
            },
            "sims": {
                "playoffAgeSeconds": _file_age_seconds(playoff_path),
                "championshipAgeSeconds": _file_age_seconds(champ_path),
                "playoffExists": playoff_path.exists(),
                "championshipExists": champ_path.exists(),
            },
        }
    )


@router.post("/refresh")
async def post_refresh(request: Request) -> JSONResponse:
    """Admin-only manual scrape trigger.

    Accepts an optional JSON body with ``sourceOverrides`` mirroring the
    dynasty siteWeights shape — ``{<key>: {"enabled": bool, "weight": float}}``
    — so /settings → "Apply ROS overrides" can disable a source or
    rescale its weight without redeploying.

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

    overrides: dict[str, dict[str, Any]] | None = None
    try:
        body = await request.json()
        raw = body.get("sourceOverrides") if isinstance(body, dict) else None
        if isinstance(raw, dict):
            sanitized: dict[str, dict[str, Any]] = {}
            for key, ov in raw.items():
                if not isinstance(ov, dict):
                    continue
                entry: dict[str, Any] = {}
                if "enabled" in ov:
                    entry["enabled"] = bool(ov["enabled"])
                w = ov.get("weight")
                try:
                    if w is not None and float(w) >= 0:
                        entry["weight"] = float(w)
                except (TypeError, ValueError):
                    pass
                if entry:
                    sanitized[str(key)] = entry
            if sanitized:
                overrides = sanitized
    except Exception:  # noqa: BLE001
        # No body / malformed JSON — fall through with no overrides.
        overrides = None

    from src.ros.scrape import run_all  # late import to avoid circulars

    summary = await run_in_threadpool(run_all, overrides=overrides)
    return JSONResponse(summary)


# Public function surfaced to public_contract for the lazy section
# builder.  Signature matches the existing
# ``Callable[[PublicLeagueSnapshot], dict[str, Any]]`` shape so the
# section can be registered alongside playoffOdds in
# ``_LAZY_SECTION_BUILDERS``.  Resolves the snapshot's
# ``root_league_id`` to a registry leagueKey so we serve the
# right per-league snapshot file.
def build_section(snapshot: Any) -> dict[str, Any]:
    """Lazy-section builder: return the cached ROS team-strength snapshot
    for the league the public-contract snapshot was built against."""
    league_key: str | None = None
    try:
        from src.api.league_registry import all_leagues  # noqa: PLC0415
        root_id = str(getattr(snapshot, "root_league_id", "") or "")
        if root_id:
            for cfg in all_leagues():
                if str(cfg.sleeper_league_id) == root_id:
                    league_key = cfg.key
                    break
    except Exception:  # noqa: BLE001
        pass
    payload = load_team_strength_snapshot(league_key)
    return {
        "teams": payload or [],
        "leagueKey": league_key,
        "computedAt": datetime.now(timezone.utc).isoformat(),
        "stale": payload is None,
    }
