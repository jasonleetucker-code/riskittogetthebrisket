"""FantasyPros Dynasty IDP adapter (ROS proxy).

Reuses the existing CSV at ``CSVs/site_raw/fantasyProsIdp.csv`` written
every 2h by ``scripts/fetch_fantasypros_idp.py``.  Treats it as a
medium-weight ROS proxy until a true FantasyPros ROS-IDP page is
verified accessible.
"""
from __future__ import annotations

import csv
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from src.ros.scrape import ScrapeResult


REPO_ROOT = Path(__file__).resolve().parents[3]
CSV_PATH = REPO_ROOT / "CSVs" / "site_raw" / "fantasyProsIdp.csv"

LOG = logging.getLogger("ros.adapter.fantasypros_idp")


def _read_csv() -> list[dict[str, Any]]:
    if not CSV_PATH.exists():
        return []
    rows: list[dict[str, Any]] = []
    try:
        with CSV_PATH.open(newline="") as f:
            reader = csv.DictReader(f)
            for i, raw in enumerate(reader, start=1):
                name = (raw.get("name") or raw.get("Player") or "").strip()
                if not name:
                    continue
                position = (
                    raw.get("position")
                    or raw.get("Pos")
                    or raw.get("Position")
                    or ""
                ).strip().upper().split("/")[0]
                rank_field = (
                    raw.get("rank")
                    or raw.get("Rank")
                    or raw.get("effectiveRank")
                )
                try:
                    rank = int(rank_field) if rank_field else i
                except (TypeError, ValueError):
                    rank = i
                rows.append(
                    {
                        "sourceName": name,
                        "canonicalName": "",
                        "position": position,
                        "team": "",
                        "rank": rank,
                        "total_ranked": 0,
                        "projection": "",
                    }
                )
    except OSError as exc:
        LOG.warning("[ros] FP IDP read failed: %s", exc)
        return []
    n = len(rows)
    for r in rows:
        r["total_ranked"] = n
    return rows


def scrape(src_meta: dict[str, Any]) -> ScrapeResult:
    started = datetime.now(timezone.utc).isoformat()
    key = str(src_meta.get("key") or "fantasyProsRosIdp")
    rows = _read_csv()
    completed = datetime.now(timezone.utc).isoformat()
    if not rows:
        return ScrapeResult(
            source_key=key,
            status="failed",
            error=(
                "FantasyPros IDP CSV missing or empty — "
                "scripts/fetch_fantasypros_idp.py must run first."
            ),
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
