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
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

from src.playerctx import fetch as fetch_mod
from src.playerctx import normalize as norm
from src.playerctx import store
from src.playerctx.normalize import SchemaRegressionError

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class AsOf:
    """What was observable at a past point in the season.

    ``season`` / ``through_week`` bound the snap-count read;
    ``depth_as_of`` bounds the depth-chart read (an ISO-8601 prefix at
    any granularity — see :func:`normalize.parse_depth_charts`).  All
    three default to None, which is the unbounded live read.
    """

    season: int | None = None
    through_week: int | None = None
    depth_as_of: str | None = None

    def describe(self) -> dict[str, Any]:
        return {
            "season": self.season,
            "throughWeek": self.through_week,
            "depthAsOf": self.depth_as_of,
        }


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


def _parse_and_join(
    bundle: fetch_mod.FetchBundle,
    players_dir: dict[str, dict[str, Any]],
    *,
    as_of: AsOf | None,
) -> tuple[dict[str, dict[str, Any]], dict[str, Any], dict[str, int]]:
    """Shared parse → join step for the live refresh and the replay.

    ``as_of=None`` is the live read and is what ``refresh_playerctx``
    passes; the parsers' own defaults make that byte-identical to the
    behaviour before the as-of parameters existed.
    """
    window = as_of or AsOf()
    contracts = norm.parse_contracts(bundle.contracts)
    snap_rows = norm.parse_snap_counts(
        bundle.snap_counts,
        season=window.season,
        through_week=window.through_week,
    )
    snaps = norm.aggregate_snaps(snap_rows)
    depth = norm.parse_depth_charts(bundle.depth_charts, as_of=window.depth_as_of)

    records, stats = norm.build_player_context(
        contracts=contracts, snaps=snaps, depth=depth, players_dir=players_dir
    )
    counts = {
        "contracts": len(contracts),
        "snapCounts": len(snaps),
        "depthCharts": len(depth),
    }
    return records, stats, counts


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

    records, stats, parsed_counts = _parse_and_join(bundle, players_dir, as_of=None)
    for key, floor in _ROW_FLOORS.items():
        if parsed_counts[key] < floor:
            raise SchemaRegressionError(
                f"{key}: parsed row count {parsed_counts[key]} below floor {floor}"
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
        # Per-source retention: the union check above can't see one
        # source collapsing semantically (e.g. a contracts naming-
        # convention change producing zero matches) while the other
        # two keep the total player count healthy — that would publish
        # a snapshot silently missing every contract block.  Each
        # source's matched count must hold its own retention ratio
        # against last-good.
        prev_counts = last_good.get("counts") or {}
        for source_key in ("contracts", "snapCounts", "depthCharts"):
            prev_matched = (prev_counts.get(source_key) or {}).get("matched")
            if not isinstance(prev_matched, int) or prev_matched <= 0:
                continue  # older snapshot without per-source counts
            new_matched = stats[source_key]["matched"]
            if new_matched < prev_matched * _LAST_GOOD_RETENTION:
                raise SchemaRegressionError(
                    f"{source_key}: matched {new_matched} retains less than "
                    f"{_LAST_GOOD_RETENTION:.0%} of last-good {prev_matched}; "
                    "keeping last-good"
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


def reconstruct_playerctx(
    *,
    as_of: AsOf,
    cache_dir: Path | None = None,
    fetcher: Callable[..., fetch_mod.FetchBundle] | None = None,
    players_dir: dict[str, dict[str, Any]] | None = None,
    max_age_hours: float = fetch_mod.DEFAULT_MAX_AGE_HOURS,
) -> dict[str, Any]:
    """The snapshot as it would have read at a past point in the season.

    Returns a payload in the same shape ``store.write_snapshot`` builds
    (``players`` + ``sleeperIndex`` + ``counts``), plus an ``asOf`` block
    and a ``survivorship`` block, WITHOUT writing anything.  The caller —
    today, the ``snapTrend`` arm of
    ``scripts/backtest_consensus_edge_composite.py`` — holds it in memory
    for one fold and throws it away.

    **Why this is not a parameter on ``refresh_playerctx``.**  The plan
    this came from said to thread ``as_of`` through the refresh.  Doing
    that would put a historical replay one default argument away from
    overwriting ``data/playerctx/snapshot.json``, which production reads
    live — a call with no ``snapshot_path`` would silently serve week-3
    role data as current.  A separate entry point that cannot write to
    the live path removes the footgun instead of documenting it.  It
    also lets the two disagree where they should: the refresh enforces
    row floors and last-good retention because a live snapshot must
    never be hollow, while a replay at week 2 has *legitimately* few
    rows and would trip both.  Counts are reported rather than enforced
    here.

    **Survivorship, stated rather than hidden.**  The join anchor is the
    Sleeper players dump, which is live-only — there is no historical
    edition of it.  A player who was on a 2025 depth chart and is out of
    the league by the time this runs has no Sleeper record, so he is
    absent from the replay even though he was present in the real
    snapshot at the time.  That biases a replay toward players who
    lasted.  ``survivorship`` reports the unjoined counts per source so a
    study can quantify it (and refuse) rather than assume it away; the
    effect shrinks toward zero as ``as_of`` approaches the present, which
    is the regime the consensus-edge panel actually lives in.
    """
    do_fetch = fetcher or fetch_mod.fetch_all
    bundle = do_fetch(cache_dir=cache_dir, max_age_hours=max_age_hours, force=False)

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

    records, stats, parsed_counts = _parse_and_join(bundle, players_dir, as_of=as_of)

    # `build_player_context` reports parsed + matched; the gap is the
    # survivorship term and is computed here rather than read off a key
    # that does not exist.
    survivorship = {}
    for key in ("contracts", "snapCounts", "depthCharts"):
        parsed = parsed_counts[key]
        matched = int((stats.get(key) or {}).get("matched") or 0)
        survivorship[key] = {
            "parsed": parsed,
            "matched": matched,
            "unjoined": max(0, parsed - matched),
            "joinRate": round(matched / parsed, 4) if parsed else None,
        }
    return {
        "schemaVersion": store.SCHEMA_VERSION,
        "asOf": as_of.describe(),
        "counts": stats,
        "parsedCounts": parsed_counts,
        "survivorship": survivorship,
        "sleeperIndex": {
            rec["sleeperId"]: key for key, rec in records.items() if rec.get("sleeperId")
        },
        "players": records,
        "warnings": list(bundle.warnings),
    }


def load_playerctx(path: Path | None = None) -> dict[str, Any] | None:
    """Read side for future consumers (player-profile endpoints).

    Returns the full snapshot payload (``schemaVersion``,
    ``generatedAt``, ``counts``, ``sleeperIndex``, ``players``) or
    ``None`` when no valid snapshot exists — never raises.
    """
    return store.load_snapshot(path)
