"""Orchestration for the player-context data layer.

``refresh_playerctx()`` runs fetch → normalize → join → floor checks
→ atomic store.  ``load_playerctx()`` is the defensive read side the
future player-profile endpoints will call.

Failure taxonomy (mirrors the fetch-script convention pinned in
``scripts/fetch_fantasynavigator.py``):

* soft failure — network down, zero rows, no Sleeper dump: raises
  ordinary exceptions / ``RuntimeError`` → CLI exit 1.
* schema regression — missing columns, row counts under the absolute
  floors, or a collapse vs the last-good snapshot: raises
  :class:`~src.playerctx.normalize.SchemaRegressionError` → CLI exit
  2, and the last-good snapshot on disk is left untouched.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any, Callable

from src.playerctx import fetch as fetch_mod
from src.playerctx import normalize as norm
from src.playerctx import store
from src.playerctx.normalize import SchemaRegressionError

log = logging.getLogger(__name__)

# Absolute row floors on the PARSED datasets.  Baselines from the live
# probes (2026-07-25): contracts ~2.4k active rows after dedupe,
# snap counts ~26.6k game rows → ~1.6k player aggregates, depth charts
# ~2.4k fantasy-slot rows in the newest snapshot.  Floors sit at
# roughly half so a truncated download trips exit 2 instead of
# publishing a hollow snapshot.
_ROW_FLOORS: dict[str, int] = {
    "contracts": 1000,
    "snapCounts": 700,  # player aggregates, not game rows
    "depthCharts": 1200,
}

# Joined-player floor: the snapshot is useless below this.
_MIN_MATCHED_PLAYERS = 400

# A new snapshot may not shed more than 25% of the last-good player
# count (same retention policy as the fetch scripts) — that shape of
# shrink means a partial upstream file, not real roster churn.
_LAST_GOOD_RETENTION = 0.75


def _load_sleeper_pool(path: Path) -> dict[str, dict[str, Any]]:
    try:
        dump = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise RuntimeError(f"sleeper players dump unreadable at {path}: {exc}") from exc
    pool = norm.build_sleeper_pool(dump)
    if not pool:
        raise RuntimeError(f"sleeper players dump at {path} yielded an empty pool")
    return pool


def refresh_playerctx(
    *,
    force: bool = False,
    max_age_hours: float = fetch_mod.DEFAULT_MAX_AGE_HOURS,
    cache_dir: Path | None = None,
    snapshot_path: Path | None = None,
    fetcher: Callable[..., fetch_mod.FetchBundle] | None = None,
    players_dir: dict[str, dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Fetch, normalize, join, and persist the player-context snapshot.

    ``fetcher`` and ``players_dir`` are injectable for tests (no live
    network in the suite).  Returns a summary dict::

        {"snapshotPath": str, "counts": {...}, "sources": {...},
         "warnings": [...]}
    """
    do_fetch = fetcher or fetch_mod.fetch_all
    bundle = do_fetch(cache_dir=cache_dir, max_age_hours=max_age_hours, force=force)

    missing = [
        key
        for key, path in (
            ("contracts", bundle.contracts),
            ("snap_counts", bundle.snap_counts),
            ("depth_charts", bundle.depth_charts),
        )
        if path is None
    ]
    if missing:
        raise RuntimeError(
            f"datasets unavailable: {', '.join(missing)}; warnings={bundle.warnings}"
        )

    if players_dir is None:
        if bundle.sleeper_players is None:
            raise RuntimeError(f"sleeper players dump unavailable; warnings={bundle.warnings}")
        players_dir = _load_sleeper_pool(bundle.sleeper_players)

    contracts = norm.parse_contracts(bundle.contracts)
    snap_rows = norm.parse_snap_counts(bundle.snap_counts)
    snaps = norm.aggregate_snaps(snap_rows)
    depth = norm.parse_depth_charts(bundle.depth_charts)

    parsed_counts = {
        "contracts": len(contracts),
        "snapCounts": len(snaps),
        "depthCharts": len(depth),
    }
    for key, floor in _ROW_FLOORS.items():
        if parsed_counts[key] < floor:
            raise SchemaRegressionError(
                f"{key}: parsed row count {parsed_counts[key]} below floor {floor}"
            )

    records, stats = norm.build_player_context(
        contracts=contracts, snaps=snaps, depth=depth, players_dir=players_dir
    )
    if len(records) < _MIN_MATCHED_PLAYERS:
        raise SchemaRegressionError(
            f"joined player count {len(records)} below floor {_MIN_MATCHED_PLAYERS}"
        )

    target = snapshot_path or store.SNAPSHOT_PATH
    last_good = store.load_snapshot(target)
    if last_good is not None:
        prev_n = len(last_good.get("players") or {})
        if prev_n > 0 and len(records) < prev_n * _LAST_GOOD_RETENTION:
            raise SchemaRegressionError(
                f"new snapshot retains only {len(records)} of {prev_n} last-good players "
                f"(< {_LAST_GOOD_RETENTION:.0%}); keeping last-good"
            )

    sources = {
        "contracts": {"url": fetch_mod.CONTRACTS_URL},
        "snapCounts": {
            "url": fetch_mod.SNAP_COUNTS_URL_TMPL,
            "season": bundle.snap_counts_season,
        },
        "depthCharts": {
            "url": fetch_mod.DEPTH_CHARTS_URL_TMPL,
            "season": bundle.depth_charts_season,
        },
        "sleeperPlayers": {"url": fetch_mod.SLEEPER_PLAYERS_URL},
    }
    written = store.write_snapshot(records, counts=stats, sources=sources, path=target)
    log.info("playerctx: wrote %d players -> %s", len(records), written)
    return {
        "snapshotPath": str(written),
        "counts": stats,
        "sources": sources,
        "warnings": list(bundle.warnings),
    }


def load_playerctx(path: Path | None = None) -> dict[str, Any] | None:
    """Read side for future consumers (player-profile endpoints).

    Returns the full snapshot payload (``schemaVersion``,
    ``generatedAt``, ``counts``, ``sleeperIndex``, ``players``) or
    ``None`` when no valid snapshot exists — never raises.
    """
    return store.load_snapshot(path)
