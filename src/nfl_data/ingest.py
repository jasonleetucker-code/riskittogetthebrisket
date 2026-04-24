"""Ingest layer for nflverse / nfl_data_py weekly stats + snap
counts + schedule.

Design
------
``nfl_data_py`` is a heavy optional dep (pulls pandas + pyarrow).
We MUST NOT make it a hard requirement — the Brisket backend
runs in containers where installing pandas breaks other wheels.

Pattern:

1. Try to import ``nfl_data_py`` inside each fetch function.
2. If the import fails OR the caller passed a stub via
   ``_provider``, fall back to a no-op that returns an empty
   list.
3. Real users opt in by setting the feature flag AND installing
   the package in their container.

All fetches go through ``src.nfl_data.cache`` so the first call
each day hits nflverse and subsequent calls in the same day
hit disk.  nflverse republishes Tuesday/Wednesday so a 24h TTL
gives us fresh data on the cadence the upstream source actually
changes.

No function raises.  Transient failures log + return [].
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any, Callable

from src.api import feature_flags
from src.nfl_data import cache as _cache

_LOGGER = logging.getLogger(__name__)

# TTL defaults — nflverse republishes Tue/Wed; 24h is the
# natural floor.
_DEFAULT_TTL_SECONDS = 24 * 3600
_SNAP_COUNTS_TTL = 24 * 3600
_WEEKLY_STATS_TTL = 24 * 3600
_ROSTERS_TTL = 24 * 3600


@dataclass(frozen=True)
class WeeklyStatRow:
    """Normalized per-player-per-week box-score stats.

    The column names are chosen to match what ``nfl_data_py``
    exposes (``import_weekly_data``) so the mapper from a
    DataFrame.to_dict(orient='records') entry is trivial.

    We intentionally keep ONLY the fields we need for the
    fantasy-points + usage signal paths.  Adding columns later
    is easy; removing columns once a downstream reads them is
    not.
    """

    player_id_gsis: str
    player_name: str
    position: str
    recent_team: str
    season: int
    week: int
    # Passing
    completions: float
    attempts: float
    passing_yards: float
    passing_tds: float
    interceptions: float
    sacks: float
    # Rushing
    carries: float
    rushing_yards: float
    rushing_tds: float
    # Receiving
    targets: float
    receptions: float
    receiving_yards: float
    receiving_tds: float
    # Fantasy-specific
    fumbles_lost: float
    # Usage
    snap_count: float | None = None
    snap_pct: float | None = None


def _dataframe_to_rows(df: Any) -> list[dict[str, Any]]:
    """Convert a pandas DataFrame to a list of dicts without
    importing pandas at module top.  Handles None / empty /
    non-DataFrame gracefully."""
    if df is None:
        return []
    to_dict = getattr(df, "to_dict", None)
    if to_dict is None:
        return list(df) if isinstance(df, list) else []
    try:
        return list(df.to_dict(orient="records"))
    except Exception:  # noqa: BLE001
        return []


def _nfl_data_py_or_none():
    """Lazy import — returns the module or None.  Catches
    EVERY exception because pandas import errors aren't always
    ImportError (sometimes it's RuntimeError from a broken
    build)."""
    try:
        import nfl_data_py  # type: ignore

        return nfl_data_py
    except Exception as exc:  # noqa: BLE001
        _LOGGER.debug("nfl_data_py not available: %s", exc)
        return None


def _gated() -> bool:
    """Return True when the feature flag for NFL data is on.
    Calls below early-return [] when this is False."""
    return feature_flags.is_enabled("nfl_data_ingest")


def fetch_weekly_stats(
    years: list[int],
    *,
    _provider: Callable[[list[int]], Any] | None = None,
    cache_dir=None,
) -> list[dict[str, Any]]:
    """Return per-player-per-week stat rows for the given years.

    ``_provider`` is a test hook; production code should not pass it.
    """
    if not _gated():
        return []
    key = f"weekly_stats:{','.join(str(y) for y in sorted(years))}"
    cached = _cache.get(key, ttl_seconds=_WEEKLY_STATS_TTL, cache_dir=cache_dir)
    if cached is not None:
        return cached
    try:
        if _provider is not None:
            df = _provider(years)
        else:
            mod = _nfl_data_py_or_none()
            if mod is None:
                return []
            df = mod.import_weekly_data(years)
        rows = _dataframe_to_rows(df)
    except Exception as exc:  # noqa: BLE001
        _LOGGER.warning("fetch_weekly_stats failed for %s: %s", years, exc)
        return []
    _cache.put(key, rows, cache_dir=cache_dir)
    return rows


def fetch_snap_counts(
    years: list[int],
    *,
    _provider: Callable[[list[int]], Any] | None = None,
    cache_dir=None,
) -> list[dict[str, Any]]:
    """Return per-player-per-week snap rows for the given years.

    Pulls from nflverse ``import_snap_counts``.
    """
    if not _gated():
        return []
    key = f"snap_counts:{','.join(str(y) for y in sorted(years))}"
    cached = _cache.get(key, ttl_seconds=_SNAP_COUNTS_TTL, cache_dir=cache_dir)
    if cached is not None:
        return cached
    try:
        if _provider is not None:
            df = _provider(years)
        else:
            mod = _nfl_data_py_or_none()
            if mod is None:
                return []
            df = mod.import_snap_counts(years)
        rows = _dataframe_to_rows(df)
    except Exception as exc:  # noqa: BLE001
        _LOGGER.warning("fetch_snap_counts failed for %s: %s", years, exc)
        return []
    _cache.put(key, rows, cache_dir=cache_dir)
    return rows


def fetch_id_map(
    *,
    _provider: Callable[[], Any] | None = None,
    cache_dir=None,
) -> list[dict[str, Any]]:
    """Return nflverse's own ID cross-walk (GSIS ↔ PFR ↔ Sleeper).

    Used by the unified ID mapper as a precomputed index.  One call
    per day is enough — the table only changes when rookies are
    added post-draft.
    """
    if not _gated():
        return []
    key = "id_map:v1"
    cached = _cache.get(key, ttl_seconds=_ROSTERS_TTL, cache_dir=cache_dir)
    if cached is not None:
        return cached
    try:
        if _provider is not None:
            df = _provider()
        else:
            mod = _nfl_data_py_or_none()
            if mod is None:
                return []
            df = mod.import_ids()
        rows = _dataframe_to_rows(df)
    except Exception as exc:  # noqa: BLE001
        _LOGGER.warning("fetch_id_map failed: %s", exc)
        return []
    _cache.put(key, rows, cache_dir=cache_dir)
    return rows


def provider_status() -> dict[str, Any]:
    """Diagnostic: is the feature flag on + the package installed
    + the cache writable?  Surfaced via /api/status."""
    installed = _nfl_data_py_or_none() is not None
    return {
        "feature_flag": feature_flags.is_enabled("nfl_data_ingest"),
        "nfl_data_py_installed": installed,
        "cache_dir_exists": (_cache._default_cache_dir()).exists(),  # noqa: SLF001
    }
