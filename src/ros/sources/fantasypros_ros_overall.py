"""FantasyPros ROS Overall adapter.

Unlike ``fantasypros_ros_sf.py`` which reads the dynasty Superflex
page (a season-long proxy), this adapter targets the real
``/nfl/rankings/ros-overall.php`` page — FantasyPros's ECR-blended
rest-of-season consensus across 100+ experts, refreshed weekly.

Same ``ecrData`` JSON blob format as the dynasty page, so the parse
shape is shared and only the URL + source_type differ.
"""
from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from typing import Any

import requests

from src.ros.scrape import ScrapeResult


_URL = "https://www.fantasypros.com/nfl/rankings/ros-overall.php"
_UA = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/127.0.0.0 Safari/537.36"
)
_ECR_RE = re.compile(
    r"ecrData\s*=\s*(\{.*?\})\s*;",
    re.DOTALL,
)


def _fetch_html(url: str, *, timeout: int = 30) -> str:
    headers = {
        "User-Agent": _UA,
        "Accept": "text/html,application/xhtml+xml",
        "Accept-Language": "en-US,en;q=0.9",
    }
    resp = requests.get(url, headers=headers, timeout=timeout)
    resp.raise_for_status()
    return resp.text


def _extract_players(html: str) -> list[dict[str, Any]]:
    """Extract the inline ``ecrData.players`` array."""
    match = _ECR_RE.search(html)
    if not match:
        return []
    try:
        blob = json.loads(match.group(1))
    except json.JSONDecodeError:
        return []
    raw = blob.get("players") if isinstance(blob, dict) else None
    if not isinstance(raw, list):
        return []
    return raw


def scrape(src_meta: dict[str, Any]) -> ScrapeResult:
    """Public adapter entry point invoked by ``src/ros/scrape.py``."""
    started = datetime.now(timezone.utc).isoformat()
    key = str(src_meta.get("key") or "fantasyProsRosOverall")
    try:
        html = _fetch_html(_URL)
    except requests.RequestException as exc:
        return ScrapeResult(
            source_key=key,
            status="failed",
            error=f"http: {exc}",
            started_at=started,
            completed_at=datetime.now(timezone.utc).isoformat(),
        )

    players = _extract_players(html)
    if not players:
        return ScrapeResult(
            source_key=key,
            status="failed",
            error="ecrData blob not found",
            started_at=started,
            completed_at=datetime.now(timezone.utc).isoformat(),
        )

    rows: list[dict[str, Any]] = []
    total = len(players)
    for entry in players:
        if not isinstance(entry, dict):
            continue
        name = (
            entry.get("player_name")
            or entry.get("player_short_name")
            or ""
        )
        if not name:
            continue
        try:
            rank = int(entry.get("rank_ecr") or 0)
        except (TypeError, ValueError):
            continue
        if rank <= 0:
            continue
        position = ""
        pos_id = entry.get("player_position_id") or entry.get("position")
        if isinstance(pos_id, str):
            position = pos_id.upper().split("/")[0]
        team = entry.get("player_team_id") or entry.get("team") or ""
        rows.append(
            {
                "sourceName": str(name),
                "canonicalName": "",
                "position": position,
                "team": str(team),
                "rank": rank,
                "total_ranked": total,
                "projection": "",
            }
        )

    completed = datetime.now(timezone.utc).isoformat()
    return ScrapeResult(
        source_key=key,
        status="ok" if rows else "partial",
        rows=rows,
        started_at=started,
        completed_at=completed,
        player_count=len(rows),
    )
