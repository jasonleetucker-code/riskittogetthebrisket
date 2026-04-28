"""Draft Sharks ROS adapter.

PR 1 strategy: read the existing dynasty Superflex + IDP CSVs that
``scripts/fetch_draftsharks.py`` already maintains every 2h via the
authenticated Playwright path.  Treat them as a ROS proxy with the
spec-defined weight.  Zero new auth dependency, zero double-scraping.

PR 2 swap: when DraftSharks' actual /rankings/rest-of-season page is
verified accessible to our login, replace ``_load_existing_csvs`` with
an actual scrape.  The adapter contract stays the same so the registry
weight + aggregator behavior don't change.

NOTE on weight: the spec calls Draft Sharks ROS the highest-confidence
source (1.25).  Until PR 2's actual ROS scrape lands, the dynasty SF
read is technically a season-long proxy — but DS's dynasty values
already incorporate ROS context (their internal model blends them),
so the 1.25 weight is still reasonable for PR 1.  Document the proxy
status in run JSON so the source-health UI flags it.
"""
from __future__ import annotations

import csv
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from src.ros.scrape import ScrapeResult


REPO_ROOT = Path(__file__).resolve().parents[3]

# Real DraftSharks ROS data (written by scripts/fetch_draftsharks_ros.py
# via authenticated Playwright on /ros-rankings/superflex + /idp).
# When these CSVs exist they take precedence over the dynasty-page
# proxies registered below — this is the actual ROS-specific signal
# the adapter was designed for.
DS_ROS_SF_CSV = REPO_ROOT / "CSVs" / "site_raw" / "draftSharksRosSf.csv"
DS_ROS_IDP_CSV = REPO_ROOT / "CSVs" / "site_raw" / "draftSharksRosIdp.csv"

# Dynasty-page CSVs maintained by scripts/fetch_draftsharks.py — used
# as a fallback when the real ROS pages haven't been fetched yet
# (e.g. fresh checkout, ROS fetcher temporarily down).  These pages
# carry deeper coverage but mix in season-long valuation context.
DS_DYNASTY_SF_CSV = REPO_ROOT / "CSVs" / "site_raw" / "draftSharksSf.csv"
DS_DYNASTY_IDP_CSV = REPO_ROOT / "CSVs" / "site_raw" / "draftSharksIdp.csv"

LOG = logging.getLogger("ros.adapter.draftsharks")


def _read_ros_csv(path: Path) -> list[dict[str, Any]]:
    """Read the real ROS-page CSV (written by fetch_draftsharks_ros.py).

    Schema is the orchestrator's standard format:
    ``canonicalName,sourceName,position,team,rank,total_ranked,projection``.
    """
    if not path.exists():
        return []
    rows: list[dict[str, Any]] = []
    try:
        with path.open(newline="") as f:
            reader = csv.DictReader(f)
            for raw in reader:
                name = (raw.get("sourceName") or "").strip()
                if not name:
                    continue
                position = (raw.get("position") or "").strip().upper().split("/")[0]
                team = (raw.get("team") or "").strip()
                try:
                    rank = int(raw.get("rank") or 0)
                except (TypeError, ValueError):
                    rank = 0
                if rank <= 0:
                    continue
                rows.append(
                    {
                        "sourceName": name,
                        "canonicalName": "",
                        "position": position,
                        "team": team,
                        "rank": rank,
                        "total_ranked": 0,  # patched below
                        "projection": (raw.get("projection") or "").strip(),
                    }
                )
    except OSError as exc:
        LOG.warning("[ros] DS ROS read failed for %s: %s", path, exc)
        return []
    n = len(rows)
    for r in rows:
        r["total_ranked"] = n
    return rows


def _read_dynasty_proxy_csv(path: Path) -> list[dict[str, Any]]:
    """Fallback reader: dynasty Superflex / IDP CSV used as a ROS proxy.

    Schema is the dynasty-page schema written by
    ``scripts/fetch_draftsharks.py`` (Player, Fantasy Position, etc.).
    """
    if not path.exists():
        return []
    rows: list[dict[str, Any]] = []
    try:
        with path.open(newline="") as f:
            reader = csv.DictReader(f)
            for i, raw in enumerate(reader, start=1):
                name = (raw.get("Player") or raw.get("name") or "").strip()
                if not name:
                    continue
                position = (
                    raw.get("Fantasy Position")
                    or raw.get("position")
                    or ""
                ).strip().upper()
                position = position.split("/")[0]
                team = (raw.get("Team") or raw.get("team") or "").strip()
                rank_field = raw.get("Rank") or raw.get("rank")
                try:
                    rank = int(rank_field) if rank_field else i
                except (TypeError, ValueError):
                    rank = i
                projection: str = ""
                proj_field = raw.get("3D Value +") or raw.get("projection")
                if proj_field:
                    try:
                        f_val = float(proj_field)
                        if f_val > 0:
                            projection = str(f_val)
                    except (TypeError, ValueError):
                        pass
                rows.append(
                    {
                        "sourceName": name,
                        "canonicalName": "",
                        "position": position,
                        "team": team,
                        "rank": rank,
                        "total_ranked": 0,
                        "projection": projection,
                    }
                )
    except OSError as exc:
        LOG.warning("[ros] DS dynasty-proxy read failed for %s: %s", path, exc)
        return []
    n = len(rows)
    for r in rows:
        r["total_ranked"] = n
    return rows


def scrape(src_meta: dict[str, Any]) -> ScrapeResult:
    """Read DraftSharks ROS data.

    Prefers the real ROS-page output (``draftSharksRosSf.csv`` /
    ``draftSharksRosIdp.csv``) when present — those carry the actual
    rest-of-season expert ranks scraped from
    ``draftsharks.com/ros-rankings/...`` via the authenticated
    Playwright fetcher.

    Falls back to the dynasty Superflex + IDP CSVs as a season-long
    proxy when the ROS fetcher hasn't run yet (fresh checkout, ROS
    page outage, etc.).
    """
    started = datetime.now(timezone.utc).isoformat()
    key = str(src_meta.get("key") or "draftSharksRosSf")

    # Prefer real ROS data when both CSVs are populated.
    sf_rows = _read_ros_csv(DS_ROS_SF_CSV)
    idp_rows = _read_ros_csv(DS_ROS_IDP_CSV)
    source_mode = "ros"
    if not sf_rows and not idp_rows:
        sf_rows = _read_dynasty_proxy_csv(DS_DYNASTY_SF_CSV)
        idp_rows = _read_dynasty_proxy_csv(DS_DYNASTY_IDP_CSV)
        source_mode = "dynasty_proxy"

    rows = sf_rows + idp_rows
    LOG.info(
        "[ros] DraftSharks: %d rows (sf=%d, idp=%d, mode=%s)",
        len(rows), len(sf_rows), len(idp_rows), source_mode,
    )

    completed = datetime.now(timezone.utc).isoformat()
    if not rows:
        return ScrapeResult(
            source_key=key,
            status="failed",
            error=(
                "DraftSharks proxy CSVs missing or empty — "
                "scripts/fetch_draftsharks.py must run first.  "
                "Source will fall back to last-known-good if available."
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
