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


def _flatten_starter_slots(starters: dict[str, Any] | None) -> list[str]:
    """Expand ``{"QB": 1, "RB": 2, ...}`` → ``["QB", "RB", "RB", ...]``.

    Mirrors how `compute_team_strength`'s ``starter_slots`` argument
    expects a flat list (one entry per slot) rather than a count map.
    """
    if not starters:
        return []
    out: list[str] = []
    alias = {"SFLEX": "SUPER_FLEX"}
    for slot, count in starters.items():
        try:
            n = int(count)
        except (TypeError, ValueError):
            continue
        if n <= 0:
            continue
        out.extend([alias.get(str(slot).upper(), str(slot).upper())] * n)
    return out


def _hydrate_overlay_players(
    teams: list[dict[str, Any]],
    nfl_players: dict[str, Any],
) -> list[dict[str, Any]]:
    """Convert overlay teams (with playerIds + name strings) into the
    shape ``compute_team_strength`` expects, with canonicalName already
    resolved against the dynasty identity layer so the lookup matches
    the aggregate's keying.
    """
    from src.utils.name_clean import normalize_player_name  # noqa: PLC0415

    out: list[dict[str, Any]] = []
    for team in teams:
        ids = team.get("playerIds") or []
        names = team.get("players") or []
        players: list[dict[str, Any]] = []
        for i, pid in enumerate(ids):
            pid_str = str(pid or "")
            meta = nfl_players.get(pid_str) or {}
            # Prefer NFL-dump full name over the overlay's mapped name —
            # the overlay falls back to the raw pid when its id_map is
            # empty, which would poison the canonical lookup.
            full_name = (meta.get("full_name") or "").strip()
            if not full_name:
                full_name = (
                    f"{meta.get('first_name','')} {meta.get('last_name','')}".strip()
                    or (names[i] if i < len(names) else pid_str)
                )
            position = (meta.get("position") or "").upper()
            injury = (meta.get("injury_status") or "").upper()
            canonical = normalize_player_name(full_name) or full_name.lower()
            players.append(
                {
                    "playerId": pid_str,
                    "name": full_name,
                    "displayName": full_name,
                    "canonicalName": canonical,
                    "position": position,
                    "injured": injury in {"OUT", "IR", "PUP", "DOUBTFUL"},
                    "bye": False,
                }
            )
        out.append(
            {
                "ownerId": team.get("ownerId"),
                "rosterId": team.get("roster_id") or team.get("rosterId"),
                "teamName": team.get("name") or team.get("teamName") or "",
                "players": players,
            }
        )
    return out


def _sim_paths(league_key: str | None, default_key: str | None) -> tuple[Path, Path]:
    """Resolve sim cache paths.  Default-league sims keep the historical
    ``latest_playoff.json`` / ``latest_championship.json`` filenames
    so existing readers (build_section, /api/ros/health) keep working.
    Non-default leagues get ``<leagueKey>_playoff.json`` / etc.
    """
    sims_dir = ROS_DATA_DIR / "sims"
    if not league_key or league_key == default_key:
        return (
            sims_dir / "latest_playoff.json",
            sims_dir / "latest_championship.json",
        )
    safe = "".join(c for c in league_key if c.isalnum() or c in {"_", "-"})
    return (
        sims_dir / f"{safe}_playoff.json",
        sims_dir / f"{safe}_championship.json",
    )


def _refresh_team_strength_for_league(
    cfg: Any,
    aggregated: list[dict[str, Any]],
    nfl_players: dict[str, Any],
) -> Path | None:
    """Compute team-strength for a single league and persist."""
    try:
        from src.api.sleeper_overlay import fetch_sleeper_overlay  # noqa: PLC0415
        from src.ros.team_strength import (  # noqa: PLC0415
            compute_team_strength,
            write_team_strength_snapshot,
        )

        if not cfg or not cfg.sleeper_league_id:
            return None
        overlay = fetch_sleeper_overlay(
            sleeper_league_id=cfg.sleeper_league_id,
            force_refresh=True,
        )
        if not overlay or not overlay.get("teams"):
            LOG.warning(
                "[ros] team-strength %s: overlay fetch returned no teams",
                cfg.key,
            )
            return None
        teams = _hydrate_overlay_players(overlay["teams"], nfl_players)
        starter_slots = _flatten_starter_slots(
            (cfg.roster_settings or {}).get("starters")
        )
        if not starter_slots:
            LOG.warning(
                "[ros] team-strength %s: no starter slots configured",
                cfg.key,
            )
            return None
        rows = compute_team_strength(
            teams,
            aggregated_players=aggregated,
            starter_slots=starter_slots,
        )
        path = write_team_strength_snapshot(rows, league_key=cfg.key)
        LOG.info(
            "[ros] team-strength %s: wrote %d teams to %s",
            cfg.key, len(rows), path,
        )
        return path
    except Exception as exc:  # noqa: BLE001
        LOG.warning(
            "[ros] team-strength refresh for %s failed: %s",
            getattr(cfg, "key", "?"), exc,
        )
        LOG.debug(
            "[ros] team-strength %s traceback: %s",
            getattr(cfg, "key", "?"), traceback.format_exc(),
        )
        return None


def _refresh_team_strength_snapshot(aggregated: list[dict[str, Any]]) -> dict[str, Path]:
    """Iterate every active league in the registry and write a per-league
    team-strength snapshot.  Default-league output keeps the historical
    ``team_strength/latest.json`` filename for backward compat.
    """
    out: dict[str, Path] = {}
    try:
        from src.api.league_registry import active_leagues  # noqa: PLC0415
        from src.public_league.sleeper_client import fetch_nfl_players  # noqa: PLC0415

        leagues = active_leagues()
        if not leagues:
            LOG.info("[ros] team-strength: no active leagues; skipping")
            return out
        nfl_players = fetch_nfl_players() or {}
        for cfg in leagues:
            path = _refresh_team_strength_for_league(cfg, aggregated, nfl_players)
            if path:
                out[cfg.key] = path
    except Exception as exc:  # noqa: BLE001
        LOG.warning("[ros] team-strength refresh failed: %s", exc)
        LOG.debug("[ros] team-strength traceback: %s", traceback.format_exc())
    return out


def _refresh_sim_caches_for_league(cfg: Any, default_key: str | None) -> dict[str, Path] | None:
    """Run playoff + championship sims for a single league."""
    try:
        from src.public_league.snapshot import build_public_snapshot  # noqa: PLC0415
        from src.ros import championship, playoff_sim  # noqa: PLC0415

        if not cfg or not cfg.sleeper_league_id:
            return None
        snap = build_public_snapshot(
            cfg.sleeper_league_id,
            include_nfl_players=False,
        )
        if not snap or not snap.seasons:
            LOG.warning(
                "[ros] sim-cache %s: snapshot empty; skipping",
                cfg.key,
            )
            return None
        playoff_path, champ_path = _sim_paths(cfg.key, default_key)
        playoff_path.parent.mkdir(parents=True, exist_ok=True)

        out: dict[str, Path] = {}
        # Best-ball flag is per-league; the simulator auto-detects when
        # not passed but we thread it explicitly so the right behavior
        # picks up for each league in the multi-league iteration.
        bb = bool(getattr(cfg, "best_ball", False))
        playoff_payload = playoff_sim.simulate_playoff_odds(snap, best_ball=bb)
        playoff_path.write_text(
            json.dumps({"computedAt": _now(), **playoff_payload}, indent=2)
        )
        out["playoff"] = playoff_path

        championship_payload = championship.simulate_championship_odds(snap, best_ball=bb)
        champ_path.write_text(
            json.dumps({"computedAt": _now(), **championship_payload}, indent=2)
        )
        out["championship"] = champ_path

        LOG.info(
            "[ros] sim-cache %s: wrote playoff + championship",
            cfg.key,
        )
        return out
    except Exception as exc:  # noqa: BLE001
        LOG.warning(
            "[ros] sim-cache refresh for %s failed: %s",
            getattr(cfg, "key", "?"), exc,
        )
        LOG.debug(
            "[ros] sim-cache %s traceback: %s",
            getattr(cfg, "key", "?"), traceback.format_exc(),
        )
        return None


def _refresh_sim_caches() -> dict[str, dict[str, Path]]:
    """Iterate active leagues and persist sim caches per league."""
    out: dict[str, dict[str, Path]] = {}
    try:
        from src.api.league_registry import active_leagues, default_league_key  # noqa: PLC0415

        default_key = default_league_key()
        for cfg in active_leagues():
            paths = _refresh_sim_caches_for_league(cfg, default_key)
            if paths:
                out[cfg.key] = paths
    except Exception as exc:  # noqa: BLE001
        LOG.warning("[ros] sim-cache refresh failed: %s", exc)
        LOG.debug("[ros] sim-cache traceback: %s", traceback.format_exc())
    return out


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
        # Duck-type the result.  ``isinstance(result, ScrapeResult)``
        # would fail when the orchestrator runs as ``__main__`` (Python
        # loads ``src.ros.scrape`` twice — once as ``__main__`` and once
        # as ``src.ros.scrape`` when adapters import ScrapeResult — so
        # the two ScrapeResult classes are distinct).  Field-presence
        # check works regardless of the loader.
        required = {"source_key", "status", "rows", "started_at", "completed_at"}
        missing = required - set(getattr(result, "__dict__", {}).keys())
        if missing:
            return ScrapeResult(
                source_key=key,
                status="failed",
                error=f"adapter returned wrong type (missing: {sorted(missing)})",
                started_at=started,
                completed_at=_now(),
            )
        return result  # type: ignore[return-value]
    except Exception as exc:  # noqa: BLE001 — adapter MUST NOT crash the orchestrator
        LOG.warning("[ros] adapter %s crashed: %s", key, exc)
        return ScrapeResult(
            source_key=key,
            status="failed",
            error=f"{type(exc).__name__}: {exc}\n{traceback.format_exc()}",
            started_at=started,
            completed_at=_now(),
        )


def _build_default_canonical_universe() -> set[str]:
    """Derive a set of normalized canonical names from Sleeper's NFL
    player dump.  Used when the orchestrator caller doesn't supply a
    universe — without one the resolver's fuzzy/exact-match guards
    can't fire (it accepts every input at confidence 1.0), so every
    typo silently lands in the aggregate as its own row.

    Failure-isolated: a network blip on the Sleeper fetch returns an
    empty set, which is equivalent to ``canonical_universe=None``
    (the prior behaviour) — a regression away from validation, never
    a regression toward dropping rows.
    """
    try:
        from src.public_league.sleeper_client import fetch_nfl_players  # noqa: PLC0415
        from src.utils.name_clean import normalize_player_name  # noqa: PLC0415

        nfl = fetch_nfl_players() or {}
        names: set[str] = set()
        for meta in nfl.values():
            if not isinstance(meta, dict):
                continue
            full = (meta.get("full_name") or "").strip()
            if not full:
                continue
            normalized = normalize_player_name(full)
            if normalized:
                names.add(normalized)
        LOG.info("[ros] canonical universe: %d names from Sleeper", len(names))
        return names
    except Exception as exc:  # noqa: BLE001 — best-effort only
        LOG.warning("[ros] canonical universe build failed: %s", exc)
        return set()


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

    # Default the canonical universe to Sleeper's NFL pool when the
    # caller doesn't supply one.  The resolver auto-accepts every name
    # at confidence 1.0 with universe=None, which silently routes
    # source-side typos into their own aggregate rows.  Pulling the
    # universe from Sleeper means a misspelled "Achane" still gets
    # fuzzy-matched to canonical "De'Von Achane" instead of becoming
    # a phantom 1.0-confidence entry.
    if canonical_universe is None:
        canonical_universe = _build_default_canonical_universe() or None

    results_by_key: dict[str, dict[str, Any]] = {}
    snapshots: list[SourceSnapshot] = []

    for src in sources:
        key = str(src.get("key") or "")
        result = _invoke_adapter(src)

        # Re-resolve canonical names when the adapter didn't already.
        # Keeps the resolver in one place; per-adapter mapping is not
        # required.  Per-row confidence multiplies (resolver × source)
        # so an adapter can express low-signal-row confidence (e.g.
        # DraftSharks rows lacking a 1yr proj) without being clobbered
        # by the resolver's high-confidence exact-match score.
        for row in result.rows:
            if not row.get("canonicalName"):
                resolved = resolve_player(
                    row.get("sourceName") or "",
                    canonical_universe=canonical_universe,
                )
                if resolved.canonical_name and resolved.confidence >= 0.7:
                    row["canonicalName"] = resolved.canonical_name
                    existing = float(row.get("confidence") or 1.0)
                    row["confidence"] = existing * resolved.confidence

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

    # Warm derived caches per active league.  Both helpers are best-
    # effort and never raise — a network blip during sim cache refresh
    # shouldn't lose the aggregate write that just landed.
    team_strength_paths = _refresh_team_strength_snapshot(aggregated)
    sim_paths_by_league = _refresh_sim_caches()

    return {
        "ranSources": list(results_by_key.keys()),
        "results": results_by_key,
        "playerCount": len(aggregated),
        "aggregateAt": _now(),
        # Per-league outputs.  Keys are leagueKey strings; values are
        # repo-relative paths.  The default league still writes to the
        # historical ``team_strength/latest.json`` + ``sims/latest_*.json``
        # filenames so existing readers keep working.
        "teamStrengthPaths": {
            k: str(p.relative_to(ROS_DATA_DIR))
            for k, p in team_strength_paths.items()
        },
        "simPathsByLeague": {
            league_key: {
                kind: str(p.relative_to(ROS_DATA_DIR))
                for kind, p in paths.items()
            }
            for league_key, paths in sim_paths_by_league.items()
        },
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
