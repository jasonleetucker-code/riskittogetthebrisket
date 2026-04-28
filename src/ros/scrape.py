"""ROS scrape orchestrator.

Runs every enabled adapter in sequence, persists per-source CSVs +
per-run JSON metadata, and rebuilds the aggregate.  Designed to be
invoked from:

    1. ``.github/workflows/scheduled-refresh.yml`` (every 2h cron)
    2. ``POST /api/ros/refresh`` (admin)
    3. ``python -m src.ros.scrape`` (local dev)

Failure isolation:

    * Each adapter is invoked behind a try/except.  A crashing adapter
      logs and continues; the previous CSV stays on disk so the
      aggregate keeps the last-known-good values.
    * A non-fatal adapter outcome ("partial" — fewer rows than
      expected, but the file still wrote) reduces the source's
      availability_multiplier to 0.5 in the next aggregation.
    * If every adapter fails, we log the error count but still write
      ``data/ros/runs/index.json`` so the API can surface "all sources
      failed today; using yesterday's snapshot".
"""
from __future__ import annotations

import argparse
import importlib
import json
import logging
import sys
import traceback
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from src.ros import ROS_DATA_DIR
from src.ros.aggregate import RankedRow, SourceSnapshot, aggregate
from src.ros.mapping import resolve_player
from src.ros.sources import enabled_ros_sources

LOG = logging.getLogger("ros.scrape")


@dataclass
class ScrapeResult:
    """Adapter return value.  Adapters MUST construct one of these
    rather than raising: failures are reported via ``status``.
    """

    source_key: str
    status: str  # "ok" | "partial" | "failed"
    rows: list[dict[str, Any]] = field(default_factory=list)
    error: str | None = None
    started_at: str = ""
    completed_at: str = ""
    player_count: int = 0


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _runs_dir() -> Path:
    p = ROS_DATA_DIR / "runs"
    p.mkdir(parents=True, exist_ok=True)
    return p


def _sources_dir() -> Path:
    p = ROS_DATA_DIR / "sources"
    p.mkdir(parents=True, exist_ok=True)
    return p


def _aggregate_dir() -> Path:
    p = ROS_DATA_DIR / "aggregate"
    p.mkdir(parents=True, exist_ok=True)
    (p / "history").mkdir(parents=True, exist_ok=True)
    return p


def _csv_path(source_key: str) -> Path:
    return _sources_dir() / f"{source_key}.csv"


def _has_valid_cache(source_key: str) -> bool:
    """True if a previous CSV exists with at least one data row."""
    path = _csv_path(source_key)
    if not path.exists():
        return False
    try:
        with path.open() as f:
            return sum(1 for _ in f) >= 2  # header + at least one row
    except OSError:
        return False


def _write_csv(source_key: str, rows: list[dict[str, Any]]) -> int:
    """Write ROS rows to data/ros/sources/<key>.csv.

    Schema: ``canonicalName,sourceName,position,team,rank,total_ranked,projection``
    Returns the number of rows written.
    """
    path = _csv_path(source_key)
    keep_existing = (not rows) and path.exists()
    if keep_existing:
        # Adapter returned no rows but we already have a valid file —
        # leave it untouched so the aggregate keeps using yesterday's
        # values.  Status will mark it stale on the next pass.
        return 0
    fieldnames = [
        "canonicalName",
        "sourceName",
        "position",
        "team",
        "rank",
        "total_ranked",
        "projection",
    ]
    import csv

    with path.open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames)
        w.writeheader()
        for row in rows:
            w.writerow({k: row.get(k, "") for k in fieldnames})
    return len(rows)


def _write_run_json(result: ScrapeResult, src_meta: dict[str, Any]) -> Path:
    runs = _runs_dir()
    target = runs / f"{result.source_key}__{result.completed_at.replace(':', '-')}.json"
    payload = {
        **asdict(result),
        "source_id": src_meta.get("key"),
        "source_name": src_meta.get("display_name"),
        "source_url": src_meta.get("source_url"),
        "source_type": src_meta.get("source_type"),
        "scoring_format": src_meta.get("scoring_format"),
        "is_superflex": bool(src_meta.get("is_superflex")),
        "is_2qb": bool(src_meta.get("is_2qb")),
        "is_te_premium": bool(src_meta.get("is_te_premium")),
        "is_idp": bool(src_meta.get("is_idp")),
        "is_ros": bool(src_meta.get("is_ros")),
        "is_dynasty": bool(src_meta.get("is_dynasty")),
        "is_projection_source": bool(src_meta.get("is_projection_source")),
        "stale_after_hours": int(src_meta.get("stale_after_hours") or 168),
    }
    # Drop the heavy rows blob — it's already in the CSV; the run JSON
    # is for status / debugging only.
    payload.pop("rows", None)
    target.write_text(json.dumps(payload, indent=2))
    return target


def _rebuild_index(latest_runs: dict[str, dict[str, Any]]) -> Path:
    index_path = _runs_dir() / "index.json"
    index_path.write_text(
        json.dumps(
            {
                "rebuiltAt": _now(),
                "sources": latest_runs,
            },
            indent=2,
        )
    )
    return index_path


def _build_snapshot(src_meta: dict[str, Any], result: ScrapeResult) -> SourceSnapshot:
    rows = [
        RankedRow(
            canonical_name=row["canonicalName"],
            position=row.get("position"),
            rank=int(row.get("rank") or 0),
            total_ranked=int(row.get("total_ranked") or len(result.rows)),
            projection_value=(
                float(row["projection"])
                if row.get("projection") not in (None, "", 0)
                else None
            ),
            confidence=float(row.get("confidence") or 1.0),
        )
        for row in result.rows
        if row.get("canonicalName")
    ]
    return SourceSnapshot(
        source_key=str(src_meta.get("key") or ""),
        base_weight=float(src_meta.get("base_weight") or 0.0),
        is_ros=bool(src_meta.get("is_ros")),
        is_dynasty=bool(src_meta.get("is_dynasty")),
        is_te_premium=bool(src_meta.get("is_te_premium")),
        is_superflex=bool(src_meta.get("is_superflex")),
        is_2qb=bool(src_meta.get("is_2qb")),
        is_idp=bool(src_meta.get("is_idp")),
        status=result.status,
        scraped_at=result.completed_at or None,
        player_count=result.player_count,
        has_valid_cache=_has_valid_cache(str(src_meta.get("key") or "")),
        rows=rows,
    )


def _invoke_adapter(src_meta: dict[str, Any]) -> ScrapeResult:
    """Import + invoke an adapter by module path; never raise."""
    key = str(src_meta.get("key") or "")
    started = _now()
    try:
        module = importlib.import_module(str(src_meta["scraper"]))
        result = module.scrape(src_meta=src_meta)
        if not isinstance(result, ScrapeResult):
            return ScrapeResult(
                source_key=key,
                status="failed",
                error="adapter returned wrong type",
                started_at=started,
                completed_at=_now(),
            )
        return result
    except Exception as exc:  # noqa: BLE001 — adapter MUST NOT crash the orchestrator
        LOG.warning("[ros] adapter %s crashed: %s", key, exc)
        return ScrapeResult(
            source_key=key,
            status="failed",
            error=f"{type(exc).__name__}: {exc}\n{traceback.format_exc()}",
            started_at=started,
            completed_at=_now(),
        )


def run_all(
    *,
    overrides: dict[str, dict[str, Any]] | None = None,
    league: dict[str, Any] | None = None,
    canonical_universe: set[str] | None = None,
) -> dict[str, Any]:
    """Run every enabled adapter and rebuild the aggregate.

    Returns a status dict suitable for printing or returning from the
    admin endpoint.
    """
    sources = enabled_ros_sources(overrides)
    LOG.info("[ros] running %d adapters", len(sources))
    results_by_key: dict[str, dict[str, Any]] = {}
    snapshots: list[SourceSnapshot] = []

    for src in sources:
        key = str(src.get("key") or "")
        result = _invoke_adapter(src)

        # Re-resolve canonical names when the adapter didn't already.
        # Keeps the resolver in one place; per-adapter mapping is not
        # required.
        for row in result.rows:
            if not row.get("canonicalName"):
                resolved = resolve_player(
                    row.get("sourceName") or "",
                    canonical_universe=canonical_universe,
                )
                if resolved.canonical_name and resolved.confidence >= 0.7:
                    row["canonicalName"] = resolved.canonical_name
                    row["confidence"] = resolved.confidence

        # Drop rows that didn't resolve (quarantine).
        result.rows = [r for r in result.rows if r.get("canonicalName")]
        result.player_count = len(result.rows)

        if result.status == "ok" and result.player_count == 0:
            result.status = "partial"

        # Persist CSV + run JSON.
        try:
            written = _write_csv(key, result.rows)
        except OSError as exc:
            LOG.error("[ros] failed to write CSV for %s: %s", key, exc)
            written = 0
            result.status = "failed"
            result.error = f"csv-write: {exc}"
        result.completed_at = result.completed_at or _now()
        run_path = _write_run_json(result, src)

        results_by_key[key] = {
            "status": result.status,
            "player_count": result.player_count,
            "rows_written": written,
            "started_at": result.started_at,
            "completed_at": result.completed_at,
            "error": result.error,
            "run_path": str(run_path.relative_to(ROS_DATA_DIR)),
        }
        snapshots.append(_build_snapshot(src, result))

    _rebuild_index(results_by_key)

    league_ctx = league or {
        "is_superflex": True,
        "is_2qb": False,
        "is_te_premium": True,
        "idp_enabled": True,
    }
    aggregated = aggregate(snapshots, league=league_ctx, now_iso=_now())

    # Write the aggregate snapshot.
    agg_dir = _aggregate_dir()
    (agg_dir / "latest.json").write_text(
        json.dumps(
            {
                "aggregatedAt": _now(),
                "league": league_ctx,
                "sourceCount": len(snapshots),
                "playerCount": len(aggregated),
                "players": aggregated,
            },
            indent=2,
        )
    )
    # Archive history copy keyed by completion timestamp.
    archive = agg_dir / "history" / f"{_now().replace(':', '-')}.json"
    archive.write_text(json.dumps({"players": aggregated}, indent=2))

    return {
        "ranSources": list(results_by_key.keys()),
        "results": results_by_key,
        "playerCount": len(aggregated),
        "aggregateAt": _now(),
    }


def main() -> int:
    parser = argparse.ArgumentParser(prog="ros.scrape")
    parser.add_argument("--source", help="run only one source by key (debug)")
    parser.add_argument(
        "-v", "--verbose", action="store_true", help="DEBUG logging"
    )
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )

    overrides: dict[str, dict[str, Any]] | None = None
    if args.source:
        overrides = {
            s["key"]: {"enabled": s["key"] == args.source}
            for s in enabled_ros_sources(None)
        }

    summary = run_all(overrides=overrides)
    print(json.dumps(summary, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
