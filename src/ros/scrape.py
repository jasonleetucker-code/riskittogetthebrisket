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

Reporting honesty (REPORTING ONLY -- nothing here feeds a weight):

    * ``status`` / ``completed_at`` are the FETCH clock: "did we retrieve
      something".  They say nothing about whether the vendor published
      anything new.
    * A zero-row fetch leaves the previous CSV in place; the run status
      now says so (``kept_previous: "zero_rows"``) instead of leaving the
      reader to infer it from ``rows_written: 0``.
    * A CONTENT clock sits beside the fetch clock: a hash of each source
      CSV and ``last_content_change`` (when that hash was last observed to
      change), persisted in ``data/ros/content_clock.json``.  A source whose
      fetch succeeds every run while its content never moves reads
      ``status: ok`` with a ``last_content_change`` that stays put.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib
import json
import logging
import sys
import traceback
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

# Imported for its side effect: ``PROCESS_BUILD`` is captured at import, so the
# forecast archive's code SHA is the commit this process loaded -- the runner's
# checkout here, the server's start-time commit when ``run_all`` runs in-server.
from src.api import build_identity as _build_identity  # noqa: F401
from src.ros import ROS_DATA_DIR
from src.ros.aggregate import RankedRow, SourceSnapshot, aggregate
from src.ros.lineup import flatten_starter_slots
from src.ros.mapping import resolve_player
from src.ros.sources import enabled_ros_sources
from src.sources.dataset_state import load_state, save_state

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


#: ``kept_previous`` value: the adapter produced no usable rows, so the
#: previous CSV was left untouched (the aggregate keeps reading it).
KEPT_PREVIOUS_ZERO_ROWS = "zero_rows"

#: Content-clock ledger (see :func:`advance_content_clock`).
CONTENT_CLOCK_FILENAME = "content_clock.json"
CONTENT_CLOCK_SCHEMA_VERSION = 1


@dataclass(frozen=True)
class CsvWriteOutcome:
    """What :func:`_write_csv_outcome` did to ``data/ros/sources/<key>.csv``."""

    rows_written: int
    #: ``KEPT_PREVIOUS_ZERO_ROWS`` when an existing file was left untouched
    #: because the adapter returned no rows; ``None`` when the file was written.
    kept_previous: str | None = None
    #: Data rows in the file that was kept (``0`` for a header-only file, so a
    #: kept file with nothing in it cannot read as reassurance).
    kept_previous_rows: int | None = None


def _csv_data_rows(path: Path) -> int:
    """Data rows (excluding the header) in an existing CSV; 0 if unreadable."""
    try:
        with path.open() as f:
            return max(0, sum(1 for _ in f) - 1)
    except OSError:
        return 0


def _write_csv_outcome(source_key: str, rows: list[dict[str, Any]]) -> CsvWriteOutcome:
    """Write ROS rows to data/ros/sources/<key>.csv and say what happened.

    Schema: ``canonicalName,sourceName,position,team,rank,total_ranked,projection``

    No rows + an existing file = the file is kept untouched and the outcome
    says so (``kept_previous``).  That is a different statement from "wrote
    zero rows", which the bare row count (``0``) cannot distinguish.
    """
    path = _csv_path(source_key)
    keep_existing = (not rows) and path.exists()
    if keep_existing:
        # Adapter returned no rows but we already have a file -- leave it
        # untouched so the aggregate keeps using yesterday's values.  The
        # caller records ``kept_previous`` in the run status and logs it.
        return CsvWriteOutcome(
            rows_written=0,
            kept_previous=KEPT_PREVIOUS_ZERO_ROWS,
            kept_previous_rows=_csv_data_rows(path),
        )
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
    return CsvWriteOutcome(rows_written=len(rows))


def _write_csv(source_key: str, rows: list[dict[str, Any]]) -> int:
    """Write ROS rows to data/ros/sources/<key>.csv.

    Returns the number of rows written (``0`` when the previous file was kept;
    use :func:`_write_csv_outcome` to tell that apart from an empty write).
    """
    return _write_csv_outcome(source_key, rows).rows_written


def _csv_content_hash(source_key: str) -> str | None:
    """SHA-256 of the source CSV as it sits on disk, or ``None`` if absent.

    Line endings are normalized first: the file is written with CRLF by the
    csv module but may be checked out with either ending, and a hash that
    moved on checkout alone would manufacture a content change.  The CSV
    carries no timestamps, so identical vendor data is an identical hash.
    """
    try:
        raw = _csv_path(source_key).read_bytes()
    except OSError:
        return None
    return hashlib.sha256(raw.replace(b"\r\n", b"\n")).hexdigest()


def advance_content_clock(
    prior: dict[str, Any] | None,
    content_hash: str | None,
    observed_at: str,
) -> tuple[dict[str, Any] | None, str]:
    """Fold one observation of a source CSV into its content clock.  Pure.

    Returns ``(entry, state)``:

    * ``"baseline"`` -- first hash ever seen for this source.  Observing a
      file is not observing a change, so ``last_content_change`` stays
      ``None`` (UNKNOWN -- never ``observed_at``, never zero); the entry
      records ``first_observed_at`` so a reader can still bound the
      unchanged period from below.
    * ``"unchanged"`` -- same hash as before.  ``last_content_change`` is
      carried untouched: a successful re-fetch of identical content moves
      no content clock.
    * ``"changed"`` -- a different hash.  ``last_content_change`` becomes
      ``observed_at``.
    * ``"no_file"`` -- there is no CSV to hash.  The prior entry is returned
      as-is; a missing file is a failed observation, not a content change.

    This is a REPORTING clock.  No weight, multiplier or threshold reads it.
    """
    if content_hash is None:
        return prior, "no_file"
    prior_hash = prior.get("content_hash") if isinstance(prior, dict) else None
    if not prior_hash:
        return (
            {
                "content_hash": content_hash,
                "first_observed_at": observed_at,
                "last_content_change": None,
            },
            "baseline",
        )
    if prior_hash == content_hash:
        return prior, "unchanged"
    return {**prior, "content_hash": content_hash, "last_content_change": observed_at}, "changed"


def _content_clock_path() -> Path:
    return ROS_DATA_DIR / CONTENT_CLOCK_FILENAME


def _load_content_clock() -> dict[str, Any]:
    """Read the persisted per-source content clocks (empty when absent/unreadable).

    An unreadable ledger re-baselines every source -- the honest outcome, since
    no prior hash is known -- rather than failing the scrape: this is reporting.
    """
    path = _content_clock_path()
    raw = load_state(path)
    if raw is None and path.exists():
        LOG.warning("[ros] content clock %s unreadable; sources will re-baseline", path)
    sources = raw.get("sources") if isinstance(raw, dict) else None
    return {
        "schema_version": CONTENT_CLOCK_SCHEMA_VERSION,
        "sources": dict(sources) if isinstance(sources, dict) else {},
    }


def _save_content_clock(ledger: dict[str, Any]) -> None:
    """Persist the ledger (write-if-changed, atomic).  Never raises."""
    try:
        save_state(_content_clock_path(), ledger)
    except OSError as exc:
        LOG.warning("[ros] failed to persist content clock: %s", exc)


def _write_run_json(
    result: ScrapeResult,
    src_meta: dict[str, Any],
    status_extra: dict[str, Any] | None = None,
) -> Path:
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
    # Additive reporting fields (kept_previous + content clock).  Merged last
    # and never over an existing key, so they cannot rewrite what a reader
    # already relies on.
    for extra_key, extra_value in (status_extra or {}).items():
        payload.setdefault(extra_key, extra_value)
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


# Canonical flattener lives in ``src.ros.lineup`` (LI-8) — this module
# used to carry a byte-identical copy alongside a third in
# ``playoff_sim``.  Re-exported under the old private name so existing
# callers and tests keep working.
_flatten_starter_slots = flatten_starter_slots


# Canonical hydration lives in ``src.ros.team_strength`` (2026-09) — moved
# there so the scheduled-scrape overlay path and the live-fallback path
# (``compute_team_strength_from_snapshot`` / ``compute_team_strength_live``)
# share one implementation instead of two copies drifting.  Re-exported
# under the historical private name so this module's one call site
# (``_refresh_team_strength_for_league`` below) and any existing test
# monkeypatch of ``scrape._hydrate_overlay_players`` keep working.
def _hydrate_overlay_players(
    teams: list[dict[str, Any]],
    nfl_players: dict[str, Any],
) -> list[dict[str, Any]]:
    from src.ros.team_strength import hydrate_overlay_players  # noqa: PLC0415

    return hydrate_overlay_players(teams, nfl_players)


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
    failures: dict[str, str] | None = None,
) -> Path | None:
    """Compute team-strength for a single league and persist.

    Keep-last-good: rows with no ROS evidence (every team at 0) are NOT
    written, so the previous snapshot survives, and the reason is recorded
    in ``failures`` (keyed by league) for the run summary.
    """

    def _fail(reason: str) -> None:
        if failures is not None and cfg is not None:
            failures[str(getattr(cfg, "key", "?"))] = reason

    try:
        from src.api.sleeper_overlay import fetch_sleeper_overlay  # noqa: PLC0415
        from src.ros.team_strength import (  # noqa: PLC0415
            compute_team_strength,
            team_strength_has_evidence,
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
            _fail("overlay_returned_no_teams")
            return None
        teams = _hydrate_overlay_players(overlay["teams"], nfl_players)
        starter_slots = _flatten_starter_slots((cfg.roster_settings or {}).get("starters"))
        if not starter_slots:
            LOG.warning(
                "[ros] team-strength %s: no starter slots configured",
                cfg.key,
            )
            _fail("no_starter_slots")
            return None
        rows = compute_team_strength(
            teams,
            aggregated_players=aggregated,
            starter_slots=starter_slots,
        )
        if not team_strength_has_evidence(rows):
            LOG.error(
                "[ros] team-strength %s: no team has positive ROS strength; keeping "
                "the last good snapshot instead of writing %d all-zero rows",
                cfg.key,
                len(rows),
            )
            _fail("no_team_strength_evidence")
            return None
        path = write_team_strength_snapshot(rows, league_key=cfg.key)
        LOG.info(
            "[ros] team-strength %s: wrote %d teams to %s",
            cfg.key,
            len(rows),
            path,
        )
        return path
    except Exception as exc:  # noqa: BLE001
        LOG.warning(
            "[ros] team-strength refresh for %s failed: %s",
            getattr(cfg, "key", "?"),
            exc,
        )
        _fail(f"exception: {type(exc).__name__}")
        LOG.debug(
            "[ros] team-strength %s traceback: %s",
            getattr(cfg, "key", "?"),
            traceback.format_exc(),
        )
        return None


def _refresh_team_strength_snapshot(
    aggregated: list[dict[str, Any]],
    failures: dict[str, str] | None = None,
) -> dict[str, Path]:
    """Iterate every active league in the registry and write a per-league
    team-strength snapshot.  Default-league output keeps the historical
    ``team_strength/latest.json`` filename for backward compat.

    **A failed NFL player download is a failure, not an empty universe.**
    This used to read ``fetch_nfl_players() or {}`` and carry on: every
    rostered player's name fell back to its raw Sleeper id, nothing joined
    the ROS aggregate, every team scored 0, and those zeros were written
    over the last good snapshot (refresh run 36220954196, 2026-09-26) --
    which then drove flat coin-flip championship odds stamped
    ``rosStrengthAvailable: true``.  Now nothing is written for any league
    (the last good snapshot stands) and each league is reported in
    ``failures`` so ``run_all`` can surface it.
    """
    out: dict[str, Path] = {}
    try:
        from src.api.league_registry import active_leagues  # noqa: PLC0415
        from src.public_league.sleeper_client import fetch_nfl_players  # noqa: PLC0415
        from src.ros.team_strength import nfl_player_dump_is_usable  # noqa: PLC0415

        leagues = active_leagues()
        if not leagues:
            LOG.info("[ros] team-strength: no active leagues; skipping")
            return out
        nfl_players = fetch_nfl_players()
        if not nfl_player_dump_is_usable(nfl_players):
            LOG.error(
                "[ros] team-strength: Sleeper NFL player dump unavailable; keeping "
                "the last good snapshot for all %d leagues",
                len(leagues),
            )
            if failures is not None:
                for cfg in leagues:
                    failures[str(cfg.key)] = "nfl_player_dump_unavailable"
            return out
        for cfg in leagues:
            path = _refresh_team_strength_for_league(cfg, aggregated, nfl_players, failures)
            if path:
                out[cfg.key] = path
    except Exception as exc:  # noqa: BLE001
        LOG.warning("[ros] team-strength refresh failed: %s", exc)
        LOG.debug("[ros] team-strength traceback: %s", traceback.format_exc())
        if failures is not None:
            failures["*"] = f"exception: {type(exc).__name__}"
    return out


def _power_week_is_complete(snapshot: Any, season_label: str, week: int) -> bool:
    """True only when the target league-week has a complete scored matchup set.

    The Sleeper NFL clock advancing is necessary but not sufficient evidence
    for an official fantasy publication. A stale/partial matchup response (or
    an unresolved postponed-game state) must not freeze an incomplete Power
    ranking forever, so require every current roster owner to appear in a
    fully-scored H2H pair before finalization.
    """
    from src.public_league import metrics  # noqa: PLC0415

    season = next(
        (s for s in snapshot.seasons if str(s.season) == str(season_label)),
        None,
    )
    if season is None:
        return False

    expected_owners: set[str] = set()
    for roster in season.rosters or []:
        rid = metrics.roster_id_of(roster)
        if rid is None:
            continue
        oid = metrics.resolve_owner(snapshot.managers, season.league_id, rid)
        if oid:
            expected_owners.add(oid)
    if not expected_owners:
        return False

    # FINAL is the same question Power's own aggregation asks
    # (``metrics.final_regular_season_weeks``: the host clock, or every roster
    # reporting). Inside a final week ``0.0`` is an observation and only an
    # absent score is missing -- the previous per-entry ``is_scored``
    # (points > 0) withheld a finished week whenever a roster genuinely scored
    # zero, and under the one-window rule below (``week == host_week - 1``) a
    # withheld week is never published, so the NEXT week's arrows all read NEW.
    if int(week) not in metrics.final_regular_season_weeks(season):
        return False

    rows = season.matchups_by_week.get(int(week)) or []
    pairs = metrics.matchup_pairs(rows)
    if len(pairs) * 2 != len(expected_owners):
        return False

    observed: set[str] = set()
    for a, b in pairs:
        if a.get("points") is None or b.get("points") is None:
            return False
        for entry in (a, b):
            oid = metrics.resolve_owner(
                snapshot.managers,
                season.league_id,
                entry.get("roster_id"),
            )
            if oid:
                observed.add(oid)

    return observed == expected_owners


def _refresh_power_snapshots() -> dict[str, Path]:
    """Finalize at most one canonical weekly Power publication per league.

    A scored week is publishable only after Sleeper's NFL clock has advanced
    beyond it. If a run was missed, we do NOT back-fill an older week with
    today's ROS strength; append-only truth is better than fake as-of history.
    """
    out: dict[str, Path] = {}
    try:
        from src.api.league_registry import active_leagues  # noqa: PLC0415
        from src.public_league.snapshot import build_public_snapshot  # noqa: PLC0415
        from src.public_league.sleeper_client import fetch_nfl_state  # noqa: PLC0415
        from src.ros import power_snapshots, power_v2  # noqa: PLC0415

        nfl_state = fetch_nfl_state() or {}
        host_season = str(nfl_state.get("season") or "")
        raw_host_week = nfl_state.get("week")
        try:
            host_week = int(raw_host_week) if raw_host_week is not None else None
        except (TypeError, ValueError):
            host_week = None
        if not host_season or host_week is None or host_week < 2:
            return out

        for cfg in active_leagues():
            if not cfg or not cfg.sleeper_league_id:
                continue
            try:
                snap = build_public_snapshot(
                    cfg.sleeper_league_id,
                    include_nfl_players=False,
                )
                section = power_v2.build_section(snap, lens=power_v2.LENS_CANONICAL)
                season = str(section.get("asOfSeason") or "")
                raw_week = section.get("asOfWeek")
                try:
                    week = int(raw_week) if raw_week is not None else None
                except (TypeError, ValueError):
                    week = None
                if (
                    season != host_season
                    or week is None
                    or week < 1
                    or host_week <= week
                    or section.get("unrankable")
                ):
                    continue
                # Only the immediately completed host week is legitimate.
                # If week < host_week - 1, the run missed publication time;
                # today's ROS data cannot be back-dated into that gap.
                if week != host_week - 1:
                    LOG.warning(
                        "[ros] power snapshot %s: latest scored week %s lags host week %s; "
                        "refusing historical ROS back-fill",
                        cfg.key,
                        week,
                        host_week,
                    )
                    continue
                if not _power_week_is_complete(snap, season, week):
                    LOG.warning(
                        "[ros] power snapshot %s: %s week %d is not a complete scored "
                        "matchup set; refusing official publication",
                        cfg.key,
                        season,
                        week,
                    )
                    continue
                current = next(
                    (s for s in snap.seasons if str(s.season) == season),
                    None,
                )
                active_ids = {m.owner_id for m in snap.managers.ordered_managers()}
                expected_owner_ids = {
                    str(r.get("owner_id") or "").strip()
                    for r in ((current.rosters if current is not None else None) or [])
                    if str(r.get("owner_id") or "").strip() in active_ids
                }
                path, created = power_snapshots.record_snapshot(
                    league_key=cfg.key,
                    section=section,
                    scoring_fingerprint=power_snapshots.scoring_config_fingerprint(snap),
                    expected_owner_ids=expected_owner_ids,
                )
                if created:
                    LOG.info(
                        "[ros] power snapshot %s: finalized %s week %d -> %s",
                        cfg.key,
                        season,
                        week,
                        path,
                    )
                out[cfg.key] = path
            except Exception as exc:  # noqa: BLE001
                LOG.warning(
                    "[ros] power snapshot refresh for %s failed: %s",
                    getattr(cfg, "key", "?"),
                    exc,
                )
                LOG.debug(
                    "[ros] power snapshot %s traceback: %s",
                    getattr(cfg, "key", "?"),
                    traceback.format_exc(),
                )
    except Exception as exc:  # noqa: BLE001
        LOG.warning("[ros] power snapshot refresh failed: %s", exc)
        LOG.debug("[ros] power snapshot traceback: %s", traceback.format_exc())
    return out


def _archive_forecast(
    league_key: str | None,
    snap: Any,
    best_ball: bool,
    kind: str,
    doc: dict[str, Any],
    path: Path,
) -> None:
    """Point-in-time forecast archive (``src/ros/forecast_archive.py``). Never raises.

    Capture only: it reads the forecast already written and writes a private
    archive record plus an identity sidecar; the served sim file is untouched.
    Identity is collected per forecast, right after that forecast's simulation,
    so the input hashes describe the files that simulation could have read.
    """
    try:
        from src.ros import forecast_archive  # noqa: PLC0415

        forecast_archive.archive_safely(
            league_key=league_key,
            kind=kind,
            forecast=doc,
            context=forecast_archive.collect_context(snap, best_ball=best_ball),
            sim_path=path,
        )
    except Exception as exc:  # noqa: BLE001 -- the archive must never fail a refresh
        LOG.warning("[ros] forecast archive for %s %s failed: %s", league_key, kind, exc)


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
        # ``computedAt`` is stamped AFTER each simulation returns, exactly as
        # before this seam existed: the served bytes must not change.
        playoff_payload = playoff_sim.simulate_playoff_odds(snap, best_ball=bb)
        playoff_doc = {"computedAt": _now(), **playoff_payload}
        playoff_path.write_text(json.dumps(playoff_doc, indent=2))
        out["playoff"] = playoff_path
        # AL-P6: archive each forecast, as written, with its model identity --
        # only AFTER the served file is on disk, and never able to fail this
        # refresh (``_archive_forecast`` catches everything).
        _archive_forecast(cfg.key, snap, bb, "playoff", playoff_doc, playoff_path)

        # ONE simulation (C5-PLAY-01): the championship file is the playoff
        # forecast above, reshaped — not a second Monte Carlo.  It carries
        # that forecast's ``computedAt`` because that is when its numbers
        # were produced.
        championship_payload = championship.championship_from_forecast(playoff_payload)
        champ_doc = {"computedAt": playoff_doc["computedAt"], **championship_payload}
        champ_path.write_text(json.dumps(champ_doc, indent=2))
        out["championship"] = champ_path
        _archive_forecast(cfg.key, snap, bb, "championship", champ_doc, champ_path)

        LOG.info(
            "[ros] sim-cache %s: wrote playoff + championship",
            cfg.key,
        )
        return out
    except Exception as exc:  # noqa: BLE001
        LOG.warning(
            "[ros] sim-cache refresh for %s failed: %s",
            getattr(cfg, "key", "?"),
            exc,
        )
        LOG.debug(
            "[ros] sim-cache %s traceback: %s",
            getattr(cfg, "key", "?"),
            traceback.format_exc(),
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


def _is_blank(value: Any) -> bool:
    """Absent at an ingestion boundary: ``None`` or an empty CSV cell."""
    return value is None or (isinstance(value, str) and not value.strip())


def _row_confidence(value: Any) -> float:
    """An adapter row's per-row confidence multiplier (``RankedRow.confidence``).

    A stated value is kept as stated — ``0`` included; ``float(x or 1.0)``
    used to read a real zero as full confidence.  Blank means the adapter
    stated no per-row reduction, which is the multiplicative identity
    ``1.0`` — the same value ``RankedRow.confidence`` defaults to.
    """
    return 1.0 if _is_blank(value) else float(value)


def _row_projection(value: Any) -> float | None:
    """An adapter row's projection: blank is missing (``None``); ``0`` is a
    projection of zero points, never missing.  The numeric row the live
    snapshot is built from and its CSV text (``"0"``) mean the same thing."""
    return None if _is_blank(value) else float(value)


def _build_snapshot(src_meta: dict[str, Any], result: ScrapeResult) -> SourceSnapshot:
    rows = [
        RankedRow(
            canonical_name=row["canonicalName"],
            position=row.get("position"),
            rank=int(row.get("rank") or 0),
            total_ranked=int(row.get("total_ranked") or len(result.rows)),
            projection_value=_row_projection(row.get("projection")),
            confidence=_row_confidence(row.get("confidence")),
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

        nfl = fetch_nfl_players()
        if not isinstance(nfl, dict) or not nfl:
            # A failed download, not an empty league: say so rather than
            # logging "canonical universe: 0 names" as if it were a count.
            LOG.error("[ros] canonical universe: Sleeper NFL player dump unavailable")
            return set()
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
    failures: dict[str, Any] = {}
    if canonical_universe is None:
        canonical_universe = _build_default_canonical_universe() or None
        if canonical_universe is None:
            failures["canonicalUniverse"] = "nfl_player_dump_unavailable"

    results_by_key: dict[str, dict[str, Any]] = {}
    snapshots: list[SourceSnapshot] = []
    # Content clocks persist across runs (and across a source being disabled for
    # one run), so they live in their own ledger rather than in the index, which
    # is rebuilt from only the sources that ran.
    content_clock = _load_content_clock()
    content_clock_dirty = False

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
                    existing = _row_confidence(row.get("confidence"))
                    row["confidence"] = existing * resolved.confidence

        # Drop rows that didn't resolve (quarantine).
        result.rows = [r for r in result.rows if r.get("canonicalName")]
        result.player_count = len(result.rows)

        if result.status == "ok" and result.player_count == 0:
            result.status = "partial"

        # Persist CSV + run JSON.
        try:
            outcome = _write_csv_outcome(key, result.rows)
        except OSError as exc:
            LOG.error("[ros] failed to write CSV for %s: %s", key, exc)
            outcome = CsvWriteOutcome(rows_written=0)
            result.status = "failed"
            result.error = f"csv-write: {exc}"
        written = outcome.rows_written
        result.completed_at = result.completed_at or _now()
        if outcome.kept_previous:
            # A zero-row fetch is not a successful one, and the previous file
            # now standing in for it is not fresh data.  ``status`` is left as
            # the existing rules set it (an "ok" with no rows is already
            # demoted to "partial" above); this says what ELSE happened.
            LOG.warning(
                "[ros] %s: adapter returned no usable rows (status=%s, error=%s); "
                "kept previous CSV (%s data rows), nothing written",
                key,
                result.status,
                result.error,
                # None (unreadable kept file) is logged as None, never as 0.
                outcome.kept_previous_rows,
            )

        # Content clock: a different question from the fetch clock above.
        # ``status`` / ``completed_at`` say we retrieved something; this says
        # whether the stored content differs from last time.  Reporting only.
        content_hash = _csv_content_hash(key)
        prior_clock = content_clock["sources"].get(key)
        clock_entry, clock_state = advance_content_clock(
            prior_clock, content_hash, result.completed_at
        )
        if clock_entry is not None and clock_entry != prior_clock:
            content_clock["sources"][key] = clock_entry
            content_clock_dirty = True
        if clock_state in ("baseline", "changed"):
            LOG.info("[ros] %s: content %s (hash %s)", key, clock_state, (content_hash or "")[:12])
        status_extra = {
            "kept_previous": outcome.kept_previous,
            "kept_previous_rows": outcome.kept_previous_rows,
            "content_hash": content_hash,
            "content_state": clock_state,
            "content_first_observed_at": (clock_entry or {}).get("first_observed_at"),
            "last_content_change": (clock_entry or {}).get("last_content_change"),
        }
        run_path = _write_run_json(result, src, status_extra)

        results_by_key[key] = {
            "status": result.status,
            "player_count": result.player_count,
            "rows_written": written,
            "started_at": result.started_at,
            "completed_at": result.completed_at,
            "error": result.error,
            "run_path": str(run_path.relative_to(ROS_DATA_DIR)),
            **status_extra,
        }
        snapshots.append(_build_snapshot(src, result))

    if content_clock_dirty:
        _save_content_clock(content_clock)
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
    team_strength_failures: dict[str, str] = {}
    team_strength_paths = _refresh_team_strength_snapshot(aggregated, team_strength_failures)
    if team_strength_failures:
        failures["teamStrength"] = team_strength_failures
    # Power publication runs AFTER team-strength refresh so the finalized
    # canonical week captures the ROS information genuinely available at
    # publication time, never a stale pre-refresh value.
    power_snapshot_paths = _refresh_power_snapshots()
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
            k: str(p.relative_to(ROS_DATA_DIR)) for k, p in team_strength_paths.items()
        },
        "powerSnapshotPaths": {
            k: str(p.relative_to(ROS_DATA_DIR)) for k, p in power_snapshot_paths.items()
        },
        "simPathsByLeague": {
            league_key: {kind: str(p.relative_to(ROS_DATA_DIR)) for kind, p in paths.items()}
            for league_key, paths in sim_paths_by_league.items()
        },
        # Derived-artifact failures this run.  Empty when everything that
        # should have refreshed did.  ``main`` exits non-zero when present so
        # the scheduled workflow raises its "ROS scrape failed" warning
        # instead of reporting a run whose team strength silently did not
        # refresh.
        "failures": failures,
    }


def main() -> int:
    parser = argparse.ArgumentParser(prog="ros.scrape")
    parser.add_argument("--source", help="run only one source by key (debug)")
    parser.add_argument("-v", "--verbose", action="store_true", help="DEBUG logging")
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )

    overrides: dict[str, dict[str, Any]] | None = None
    if args.source:
        overrides = {
            s["key"]: {"enabled": s["key"] == args.source} for s in enabled_ros_sources(None)
        }

    summary = run_all(overrides=overrides)
    print(json.dumps(summary, indent=2))
    if summary.get("failures"):
        LOG.error("[ros] refresh completed with failures: %s", summary["failures"])
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
