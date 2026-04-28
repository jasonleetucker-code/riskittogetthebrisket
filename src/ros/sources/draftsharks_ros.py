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
DS_SF_CSV = REPO_ROOT / "CSVs" / "site_raw" / "draftSharksSf.csv"
DS_IDP_CSV = REPO_ROOT / "CSVs" / "site_raw" / "draftSharksIdp.csv"

LOG = logging.getLogger("ros.adapter.draftsharks")


def _read_rank_signal_csv(path: Path) -> list[dict[str, Any]]:
    """Read a DraftSharks rank-signal CSV into adapter row shape.

    The dynasty CSVs use the schema written by
    ``scripts/fetch_draftsharks.py`` — see the ``CSV_HEADER`` constant
    there.  We extract Player, Fantasy Position, and the implicit row
    order as the rank signal.  Missing files / unreadable rows are
    treated as soft failures (zero rows) rather than crashes.
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
                # First match wins for split positions like "EDGE/DL".
                position = position.split("/")[0]
                team = (raw.get("Team") or raw.get("team") or "").strip()
                rank_field = raw.get("Rank") or raw.get("rank")
                try:
                    rank = int(rank_field) if rank_field else i
                except (TypeError, ValueError):
                    rank = i
                # Three-digit-value column "3D Value +" has the
                # cross-market projection signal we'd otherwise treat
                # as a projection_value; preserve when numeric.
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
                        "canonicalName": "",  # filled by orchestrator
                        "position": position,
                        "team": team,
                        "rank": rank,
                        "total_ranked": 0,  # patched below after we know N
                        "projection": projection,
                    }
                )
    except OSError as exc:
        LOG.warning("[ros] DS proxy read failed for %s: %s", path, exc)
        return []

    # Re-stamp total_ranked once we know N.
    n = len(rows)
    for r in rows:
        r["total_ranked"] = n
    return rows


def scrape(src_meta: dict[str, Any]) -> ScrapeResult:
    """PR 1: DS dynasty SF + IDP CSV reuse as ROS proxy."""
    started = datetime.now(timezone.utc).isoformat()
    key = str(src_meta.get("key") or "draftSharksRosSf")

    sf_rows = _read_rank_signal_csv(DS_SF_CSV)
    idp_rows = _read_rank_signal_csv(DS_IDP_CSV)
    rows = sf_rows + idp_rows

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
