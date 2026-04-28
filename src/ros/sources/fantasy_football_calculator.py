"""Fantasy Football Calculator 2QB ADP adapter.

FFC publishes a public JSON ADP API at
``https://fantasyfootballcalculator.com/api/v1/adp/<format>`` with
no auth.  We pull the 2QB-PPR list as a low-weight ROS proxy:
ADP is market data, not true ROS, but it's the deepest free 2QB
ranking available without scraping.

Per spec weight: 0.70 (low because ADP is draft-market data).

API shape (subset):
    {
      "status": "Success",
      "players": [
        {"player_id": ..., "name": "...", "position": "...",
         "team": "...", "adp": 5.2, "stdev": 1.8},
        ...
      ]
    }
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from typing import Any

import requests

from src.ros.scrape import ScrapeResult

LOG = logging.getLogger("ros.adapter.ffc")

_URL = "https://fantasyfootballcalculator.com/api/v1/adp/2qb"
_UA = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/127.0.0.0 Safari/537.36"
)


def scrape(src_meta: dict[str, Any]) -> ScrapeResult:
    started = datetime.now(timezone.utc).isoformat()
    key = str(src_meta.get("key") or "ffc2qbAdp")
    headers = {"User-Agent": _UA, "Accept": "application/json"}
    try:
        resp = requests.get(_URL, headers=headers, timeout=20)
        resp.raise_for_status()
        payload = resp.json()
    except (requests.RequestException, json.JSONDecodeError) as exc:
        return ScrapeResult(
            source_key=key,
            status="failed",
            error=f"http: {exc}",
            started_at=started,
            completed_at=datetime.now(timezone.utc).isoformat(),
        )

    players = payload.get("players") if isinstance(payload, dict) else None
    if not isinstance(players, list):
        return ScrapeResult(
            source_key=key,
            status="failed",
            error="response missing 'players' array",
            started_at=started,
            completed_at=datetime.now(timezone.utc).isoformat(),
        )

    # Sort by ADP ascending (rank 1 = lowest ADP).
    sorted_players = sorted(
        [p for p in players if isinstance(p, dict) and p.get("name")],
        key=lambda p: float(p.get("adp", 999) or 999),
    )

    rows: list[dict[str, Any]] = []
    total = len(sorted_players)
    for i, p in enumerate(sorted_players, start=1):
        name = str(p.get("name") or "").strip()
        if not name:
            continue
        rows.append(
            {
                "sourceName": name,
                "canonicalName": "",
                "position": str(p.get("position") or "").strip().upper(),
                "team": str(p.get("team") or "").strip(),
                "rank": i,
                "total_ranked": total,
                "projection": "",
            }
        )

    completed = datetime.now(timezone.utc).isoformat()
    return ScrapeResult(
        source_key=key,
        status="ok" if rows else "failed",
        rows=rows,
        error=None if rows else "no rows parsed",
        started_at=started,
        completed_at=completed,
        player_count=len(rows),
    )
