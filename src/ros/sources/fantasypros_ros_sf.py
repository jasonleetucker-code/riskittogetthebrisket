"""FantasyPros Dynasty Superflex adapter (ROS proxy).

Status: dynasty_proxy.  The ECR ROS Superflex page sits behind a soft
paywall, so PR1 uses the existing dynasty SF rankings as a low-weight
proxy — the adapter shape is identical and PR5 swaps the URL once the
ROS page is accessible without breaking the registry.

Adapter contract (per ``src/ros/scrape.py::ScrapeResult``):

    scrape(src_meta) -> ScrapeResult
        status: "ok" | "partial" | "failed"
        rows: list of {sourceName, canonicalName, position, team, rank,
                       total_ranked, projection}

Returning ``status="failed"`` with ``error`` set is the right way to
signal an outage — the orchestrator will keep yesterday's CSV + mark
the source stale, and the aggregator will downgrade availability to
0.5 (or 0.0 if no cache exists).
"""
from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from typing import Any

import requests

from src.ros.scrape import ScrapeResult


_URL = "https://www.fantasypros.com/nfl/rankings/dynasty-superflex.php"
_UA = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/127.0.0.0 Safari/537.36"
)
_ECR_RE = re.compile(
    r"var\s+ecrData\s*=\s*(\{.*?\})\s*;\s*var\s",
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
    """Pull the inline ``ecrData`` JSON blob from the page HTML.

    FantasyPros publishes their ranks as a JS variable rather than
    server-rendered HTML, so a simple regex extract gives us a clean
    JSON array without a real DOM parse.
    """
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
    key = str(src_meta.get("key") or "fantasyProsRosSf")
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
                "canonicalName": "",  # filled by orchestrator's resolver
                "position": position,
                "team": str(team),
                "rank": rank,
                "total_ranked": total,
                "projection": "",  # rank-only source
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
