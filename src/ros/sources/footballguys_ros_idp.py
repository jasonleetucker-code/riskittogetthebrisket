"""Footballguys IDP adapter (ROS proxy).

Reuses the existing CSV at ``CSVs/site_raw/footballGuysIdp.csv``.  FBG
scrapes are authenticated via Playwright in
``scripts/fetch_footballguys.py`` — we just read the resulting CSV.
"""
from __future__ import annotations

import csv
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from src.ros.scrape import ScrapeResult


REPO_ROOT = Path(__file__).resolve().parents[3]
CSV_PATH = REPO_ROOT / "CSVs" / "site_raw" / "footballGuysIdp.csv"

LOG = logging.getLogger("ros.adapter.footballguys_idp")


def scrape(src_meta: dict[str, Any]) -> ScrapeResult:
    started = datetime.now(timezone.utc).isoformat()
    key = str(src_meta.get("key") or "footballGuysRosIdp")

    if not CSV_PATH.exists():
        return ScrapeResult(
            source_key=key,
            status="failed",
            error="footballGuysIdp.csv missing",
            started_at=started,
            completed_at=datetime.now(timezone.utc).isoformat(),
        )

    rows: list[dict[str, Any]] = []
    try:
        with CSV_PATH.open(newline="") as f:
            reader = csv.DictReader(f)
            for i, raw in enumerate(reader, start=1):
                name = (raw.get("name") or raw.get("Player") or "").strip()
                if not name:
                    continue
                position = (raw.get("position") or "").strip().upper().split("/")[0]
                value_str = raw.get("value") or raw.get("Value")
                projection = ""
                try:
                    if value_str and float(value_str) > 0:
                        projection = str(float(value_str))
                except (TypeError, ValueError):
                    pass
                rows.append(
                    {
                        "sourceName": name,
                        "canonicalName": "",
                        "position": position,
                        "team": "",
                        "rank": i,
                        "total_ranked": 0,
                        "projection": projection,
                    }
                )
    except OSError as exc:
        LOG.warning("[ros] FBG IDP read failed: %s", exc)
        return ScrapeResult(
            source_key=key,
            status="failed",
            error=f"csv-read: {exc}",
            started_at=started,
            completed_at=datetime.now(timezone.utc).isoformat(),
        )

    n = len(rows)
    for r in rows:
        r["total_ranked"] = n
    completed = datetime.now(timezone.utc).isoformat()
    if not rows:
        return ScrapeResult(
            source_key=key,
            status="failed",
            error="footballGuysIdp.csv empty",
            started_at=started,
            completed_at=completed,
        )
    return ScrapeResult(
        source_key=key,
        status="ok",
        rows=rows,
        started_at=started,
        completed_at=completed,
        player_count=len(rows),
    )
