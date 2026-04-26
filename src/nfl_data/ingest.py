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


@dataclass(frozen=True)
class WeeklyDefensiveStatRow:
    """Normalized per-IDP-per-week defensive box-score stats.

    Mirrors the column names used in nflverse's
    ``player_stats_def_{year}.csv`` file (the defensive sibling of
    ``player_stats_{year}.csv``).  Every field is `def_`-prefixed in
    the source CSV; we drop the prefix here so the dataclass reads
    naturally, but the underlying fetcher reads from the prefixed
    columns.
    """

    player_id_gsis: str
    player_name: str
    position: str
    team: str
    season: int
    week: int
    # Tackle volume
    tackles_solo: float
    tackles_assist: float
    tackles_combined: float
    tackles_for_loss: float
    tackles_for_loss_yards: float
    # Pressure / disruption
    sacks: float
    sack_yards: float
    qb_hits: float
    # Pass-defense
    passes_defended: float
    interceptions: float
    interception_yards: float
    # Turnovers
    fumbles_forced: float
    fumble_recovery_own: float
    fumble_recovery_opp: float
    fumble_recovery_yards_own: float
    fumble_recovery_yards_opp: float
    # Splash
    def_tds: float
    safeties: float


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


def _nflverse_direct():
    """Return the direct-fetch module — always succeeds; pure stdlib.
    Used as the fallback when ``nfl_data_py`` isn't installed (e.g.,
    its pandas<2.0 pin can't be satisfied on Python 3.12)."""
    try:
        from src.nfl_data import nflverse_direct
        return nflverse_direct
    except Exception as exc:  # noqa: BLE001
        _LOGGER.warning("nflverse_direct import failed: %s", exc)
        return None


def _gated() -> bool:
    """Return True when the feature flag for NFL data is on.
    Calls below early-return [] when this is False."""
    return feature_flags.is_enabled("nfl_data_ingest")


def _try_fetch_with_fallback(
    years: list[int] | None,
    provider: Callable | None,
    *,
    nfl_method: str,
    direct_method: str,
    label: str,
) -> list[dict[str, Any]] | None:
    """Three-rung fetch ladder with graceful degradation:

       1. If a test ``provider`` is given, use it.
       2. Else if ``nfl_data_py`` is installed AND its method works
          at runtime, use it.  Pandas 3.x API mismatches with
          nfl_data_py 0.3.x are caught here and fall through.
       3. Else use the stdlib ``nflverse_direct`` fetcher.

    Returns the rows list, or ``None`` to signal an empty/error
    state (so caller doesn't pollute cache with a bad payload).

    Logs each rung's outcome with structured prefixes so ops can
    trace which provider is in use.
    """
    if not _gated():
        return None
    # Rung 1: test provider.
    if provider is not None:
        try:
            df = provider(years) if years is not None else provider()
            rows = _dataframe_to_rows(df)
            _LOGGER.debug("nfl_data_fetch=test_provider label=%s rows=%d", label, len(rows))
            return rows
        except Exception as exc:  # noqa: BLE001
            _LOGGER.warning("nfl_data_fetch=test_provider_failed label=%s err=%r", label, exc)
            return None

    # Rung 2: nfl_data_py.
    mod = _nfl_data_py_or_none()
    if mod is not None:
        method = getattr(mod, nfl_method, None)
        if method is not None:
            try:
                df = method(years) if years is not None else method()
                rows = _dataframe_to_rows(df)
                _LOGGER.info(
                    "nfl_data_fetch=nfl_data_py label=%s rows=%d",
                    label, len(rows),
                )
                return rows
            except Exception as exc:  # noqa: BLE001
                # Runtime failure (likely pandas API mismatch).  Fall
                # through to the direct fetcher.
                _LOGGER.warning(
                    "nfl_data_fetch=nfl_data_py_runtime_failed label=%s err=%r — "
                    "falling back to nflverse_direct",
                    label, exc,
                )
        else:
            _LOGGER.warning(
                "nfl_data_fetch=nfl_data_py_method_missing label=%s method=%s — "
                "falling back to nflverse_direct",
                label, nfl_method,
            )

    # Rung 3: nflverse_direct (stdlib CSV).
    fb = _nflverse_direct()
    if fb is None:
        _LOGGER.warning("nfl_data_fetch=no_provider_available label=%s", label)
        return None
    direct_fn = getattr(fb, direct_method, None)
    if direct_fn is None:
        _LOGGER.warning(
            "nfl_data_fetch=direct_method_missing label=%s method=%s",
            label, direct_method,
        )
        return None
    try:
        rows = direct_fn(years) if years is not None else direct_fn()
        _LOGGER.info(
            "nfl_data_fetch=nflverse_direct label=%s rows=%d",
            label, len(rows),
        )
        return rows
    except Exception as exc:  # noqa: BLE001
        _LOGGER.warning(
            "nfl_data_fetch=nflverse_direct_failed label=%s err=%r",
            label, exc,
        )
        return None


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
    rows = _try_fetch_with_fallback(
        years, _provider,
        nfl_method="import_weekly_data",
        direct_method="fetch_weekly_stats",
        label="weekly_stats",
    )
    if rows is None:
        return []
    _cache.put(key, rows, cache_dir=cache_dir)
    return rows


def fetch_weekly_defensive_stats(
    years: list[int],
    *,
    _provider: Callable[[list[int]], Any] | None = None,
    cache_dir=None,
) -> list[dict[str, Any]]:
    """Per-IDP-per-week defensive stat rows for the given years.

    Same fall-through ladder as :func:`fetch_weekly_stats`: test
    provider → ``nfl_data_py.import_weekly_data_def`` (when
    available) → ``nflverse_direct.fetch_weekly_defensive_stats``
    (always works, stdlib-only).

    Each row carries ``def_*`` prefixed columns straight from
    nflverse — callers should normalize via
    :class:`WeeklyDefensiveStatRow` or read directly.
    """
    if not _gated():
        return []
    key = f"weekly_def_stats:{','.join(str(y) for y in sorted(years))}"
    cached = _cache.get(key, ttl_seconds=_WEEKLY_STATS_TTL, cache_dir=cache_dir)
    if cached is not None:
        return cached
    rows = _try_fetch_with_fallback(
        years, _provider,
        # ``import_weekly_data_def`` was added in nfl_data_py 0.3.5;
        # earlier versions don't expose it.  The fall-through to the
        # direct fetcher handles that case.
        nfl_method="import_weekly_data_def",
        direct_method="fetch_weekly_defensive_stats",
        label="weekly_def_stats",
    )
    if rows is None:
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

    Prefers ``nfl_data_py.import_snap_counts``; falls back to direct
    nflverse CSV fetch when nfl_data_py isn't installed.
    """
    if not _gated():
        return []
    key = f"snap_counts:{','.join(str(y) for y in sorted(years))}"
    cached = _cache.get(key, ttl_seconds=_SNAP_COUNTS_TTL, cache_dir=cache_dir)
    if cached is not None:
        return cached
    rows = _try_fetch_with_fallback(
        years, _provider,
        nfl_method="import_snap_counts",
        direct_method="fetch_snap_counts",
        label="snap_counts",
    )
    if rows is None:
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
    rows = _try_fetch_with_fallback(
        None, _provider,
        nfl_method="import_ids",
        direct_method="fetch_id_map",
        label="id_map",
    )
    if rows is None:
        return []
    _cache.put(key, rows, cache_dir=cache_dir)
    return rows


def provider_status() -> dict[str, Any]:
    """Diagnostic: which provider is active + cache writable?
    Surfaced via /api/status so ops can see if the direct-fetch
    fallback is in use vs. nfl_data_py."""
    installed = _nfl_data_py_or_none() is not None
    direct_available = _nflverse_direct() is not None
    return {
        "feature_flag": feature_flags.is_enabled("nfl_data_ingest"),
        "active_provider": (
            "nfl_data_py" if installed
            else ("nflverse_direct" if direct_available else "none")
        ),
        "nfl_data_py_installed": installed,
        "nflverse_direct_available": direct_available,
        "cache_dir_exists": (_cache._default_cache_dir()).exists(),  # noqa: SLF001
    }


def _provider_status_orig() -> dict[str, Any]:
    """[deprecated] Old shape kept for backward compat in case
    /api/status consumers expect it.  No callers today."""
    installed = _nfl_data_py_or_none() is not None
    return {
        "feature_flag": feature_flags.is_enabled("nfl_data_ingest"),
        "nfl_data_py_installed": installed,
        "cache_dir_exists": (_cache._default_cache_dir()).exists(),  # noqa: SLF001
    }
