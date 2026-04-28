"""Per-team buyer/seller deadline dashboard.

Combines:
  - Cached ROS team-strength snapshot (data/ros/team_strength/latest.json)
  - Cached ROS playoff sim output (or recomputes if cache is missing)
  - Cached ROS championship sim output
  - Sleeper roster age profile (from the live overlay)

Returns one row per team with the direction label + recommendation.
Lazy-section friendly — call ``build_section(snapshot)`` from the
public contract.
"""
from __future__ import annotations

import json
import logging
from typing import Any

from src.ros import ROS_DATA_DIR
from src.ros.direction import build_roster_age_profile, classify_team
from src.ros.team_strength import load_team_strength_snapshot

LOG = logging.getLogger("ros.trade_deadline")


def _load_playoff_odds_map() -> dict[str, dict[str, float]]:
    """Read the latest cached ROS playoff-odds output, keyed by ownerId."""
    path = ROS_DATA_DIR / "sims" / "latest_playoff.json"
    if not path.exists():
        return {}
    try:
        payload = json.loads(path.read_text())
    except (json.JSONDecodeError, OSError):
        return {}
    rows = payload.get("playoffOdds") or []
    return {
        str(r.get("ownerId") or ""): r
        for r in rows
        if r.get("ownerId")
    }


def _load_championship_map() -> dict[str, dict[str, float]]:
    path = ROS_DATA_DIR / "sims" / "latest_championship.json"
    if not path.exists():
        return {}
    try:
        payload = json.loads(path.read_text())
    except (json.JSONDecodeError, OSError):
        return {}
    rows = payload.get("championshipOdds") or []
    return {
        str(r.get("ownerId") or ""): r
        for r in rows
        if r.get("ownerId")
    }


def build_team_directions(
    *,
    teams: list[dict[str, Any]] | None = None,
    playoff_odds_map: dict[str, dict[str, float]] | None = None,
    championship_map: dict[str, dict[str, float]] | None = None,
    team_strength_map: dict[str, dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    """Compose direction labels for every team that has any input data.

    All maps are keyed by ownerId.  When a map is empty (e.g. no
    cached sim yet), the missing dimension defaults to 0 — the
    classifier degrades cleanly.
    """
    playoffs = playoff_odds_map or _load_playoff_odds_map()
    champs = championship_map or _load_championship_map()
    strengths = team_strength_map or {}
    if not strengths:
        snap = load_team_strength_snapshot() or []
        strengths = {
            str(r.get("ownerId") or ""): r for r in snap if r.get("ownerId")
        }

    owner_ids = sorted(
        set(playoffs) | set(champs) | set(strengths)
    )
    if not owner_ids:
        return []

    out: list[dict[str, Any]] = []
    for owner in owner_ids:
        po = float((playoffs.get(owner) or {}).get("playoffOdds") or 0.0)
        co = float((champs.get(owner) or {}).get("championshipOdds") or 0.0)
        strength_row = strengths.get(owner) or {}
        # team_strength snapshot doesn't carry a percentile by itself;
        # rank/length is the cheapest proxy.
        rank = float(strength_row.get("rank") or 0.0)
        total = max(1.0, float(len(strengths) or 1))
        strength_pct = (
            (total - rank + 1) / total if rank > 0 else 0.0
        )
        team_obj = (
            next((t for t in (teams or []) if t.get("ownerId") == owner), None)
        )
        roster_age = (
            build_roster_age_profile(team_obj.get("players") or [])
            if team_obj
            else {}
        )
        direction = classify_team(
            playoff_odds_pct=po,
            championship_odds_pct=co,
            team_ros_strength_percentile=strength_pct,
            roster_age_profile=roster_age,
        )
        out.append(
            {
                "ownerId": owner,
                "displayName": strength_row.get("teamName")
                or (champs.get(owner) or {}).get("displayName")
                or owner,
                "playoffOdds": po,
                "championshipOdds": co,
                "rosStrengthPercentile": round(strength_pct, 4),
                "rank": rank,
                **direction,
            }
        )

    out.sort(key=lambda r: -r["championshipOdds"])
    return out


def build_section(snapshot: Any) -> dict[str, Any]:
    """Lazy-section builder for /api/public/league/rosTradeDeadline."""
    _ = snapshot  # roster ages come from team_strength snapshot directly
    return {
        "teams": build_team_directions(),
    }
