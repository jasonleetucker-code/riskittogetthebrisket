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
import threading
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
_SCHEDULES_TTL = 24 * 3600

# ── Cache keys and TTLs have ONE owner ─────────────────────────────
# ``src/api/bdvm_api.py`` reports the AGE of these same entries, which
# means it has to name them.  A hand-rolled second copy of the format
# reports MISSING for an artifact that is present the moment either side
# drifts — and it already did: the report asked for ``id_map`` while the
# entry has always been written under ``id_map:v1``.  Both sides now ask
# this function.
ID_MAP_CACHE_KEY = "id_map:v1"

CACHE_TTLS: dict[str, float] = {
    "weekly_stats": _WEEKLY_STATS_TTL,
    "weekly_def_stats": _WEEKLY_STATS_TTL,
    "snap_counts": _SNAP_COUNTS_TTL,
    "schedules": _SCHEDULES_TTL,
    "id_map": _ROSTERS_TTL,
}


def cache_key(feed: str, years: list[int] | None = None) -> str:
    """The cache key one nflverse feed is stored under.

    ``feed`` is a key of :data:`CACHE_TTLS`.  Year-scoped feeds sort
    their years, so ``[2025, 2024]`` and ``[2024, 2025]`` are one entry.
    """
    if feed not in CACHE_TTLS:
        raise KeyError(f"unknown nflverse feed: {feed!r}")
    if feed == "id_map":
        return ID_MAP_CACHE_KEY
    return f"{feed}:{','.join(str(y) for y in sorted(years or []))}"


# ── Cold-cache single-flight ───────────────────────────────────────
# Every fetch below was check-then-fill with nothing in between:
#
#     cached = _cache.get(key, ...)
#     if cached is not None: return cached
#     rows = _try_fetch_with_fallback(...)   # seconds, over the network
#     _cache.put(key, rows, ...)
#
# The TTL comment above says "the first call each day hits nflverse and
# subsequent calls hit disk", and that is true of calls made in
# SEQUENCE.  Concurrently, every caller that arrives before the first
# one finishes its put() also misses, and they all fetch.
#
# Measured on E2E run 31027451127, cold cache, one uvicorn process:
# ``snap_counts_2020.csv`` was downloaded 4 times, ``2022`` 6 times, and
# the full 157,615-row snap set completed 3 times inside 6 seconds
# (16:56:53 / :58 / :59).  Each of those is a multi-MB download from
# github.com plus a CSV parse, and they ran while the suite was trying
# to load /rankings — POST /api/trade/finder measured 66s against 7.7s
# on a quiet run.  Reported as #753.
#
# Same leader/follower shape as ``src/news/service.py`` (and the
# sleeper overlay): the first caller for a key becomes the leader and
# fetches; concurrent callers wait on its Event and then RE-CHECK the
# cache rather than launching their own fetch.
#
# Two properties worth stating because they are what make this safe:
#
#   * A follower never returns the leader's value directly — it
#     re-reads the cache.  So a leader whose fetch FAILED (returns []
#     and deliberately does not put()) does not poison anyone: the
#     follower simply misses and becomes the next leader.  Failures
#     degrade to sequential retries, never to a stampede and never to a
#     shared wrong answer.
#   * The wait is bounded.  The timeout only guards a wedged leader; on
#     expiry the follower re-evaluates and may take leadership itself,
#     so no caller can block forever on a thread that died.
#
# The in-flight key includes ``cache_dir`` because two callers pointed
# at different cache directories are filling different entries and must
# not wait on each other — which is also what keeps tests that pass
# ``cache_dir=tmp_path`` independent.
_INFLIGHT_LOCK = threading.Lock()
_INFLIGHT: dict[tuple[str, str], threading.Event] = {}

# Only guards a wedged leader — see above.  Comfortably longer than a
# real nflverse pull (the slowest observed is ~10s for six seasons of
# snap counts) and far shorter than any request timeout.
_INFLIGHT_WAIT_TIMEOUT_S = 120.0


def _cached_or_fetch(
    key: str,
    *,
    ttl_seconds: float,
    cache_dir,
    fetch: Callable[[], list[dict[str, Any]] | None],
    cache_only: bool = False,
) -> list[dict[str, Any]]:
    """Return ``key`` from cache, fetching at most once across threads.

    Preserves the previous contract exactly: a fetch that fails returns
    ``[]`` and writes nothing, so the next caller retries.

    ``cache_only`` is the REQUEST-PATH mode and it never fetches.  It
    reads the newest artifact on disk — INCLUDING a TTL-expired one —
    and returns ``[]`` when there is none, so the caller degrades
    instead of crawling.

    Why this exists.  Before it, a cache miss on any of these keys meant
    a multi-MB nflverse download plus a CSV parse, wherever the caller
    happened to be.  ``src/api/bdvm_api.py`` calls three of them while
    serving ``/api/bdvm/*``, so the FIRST interactive BDVM request pulled
    six seasons of weekly stats and six of snap counts — ~270,000 rows.
    Parsing that is CPU/GIL-heavy, so it starved ``/api/data``'s response
    streaming in the same uvicorn process and the Next bridge aborted at
    its 4s idle timeout (``backend_idle_timeout``), rendering "Rankings
    unavailable" on a page that had nothing to do with BDVM.
    ``run_in_threadpool`` did not help and could not: the contention is
    the GIL, not the event loop.

    The split this enforces: **the refresh owner decides when to fetch;
    the request path decides only whether an artifact exists, and reports
    its age honestly.**
    """
    inflight_key = (key, str(cache_dir) if cache_dir is not None else "")
    if cache_only:
        # Stale is READABLE here, never relabelled — see ``allow_stale``.
        # No single-flight: nothing is fetched, so there is nothing to
        # serialise and no caller to make wait.
        cached = _cache.get(key, ttl_seconds=ttl_seconds, cache_dir=cache_dir, allow_stale=True)
        return cached if cached is not None else []
    while True:
        cached = _cache.get(key, ttl_seconds=ttl_seconds, cache_dir=cache_dir)
        if cached is not None:
            return cached
        with _INFLIGHT_LOCK:
            waiter = _INFLIGHT.get(inflight_key)
            if waiter is None:
                waiter = threading.Event()
                _INFLIGHT[inflight_key] = waiter
                break  # this thread leads
        # Follower: wait for the leader, then loop to re-check the
        # cache.  On timeout the loop re-evaluates and this thread can
        # take over leadership.
        waiter.wait(timeout=_INFLIGHT_WAIT_TIMEOUT_S)

    try:
        rows = fetch()
        if rows is None:
            return []
        _cache.put(key, rows, cache_dir=cache_dir)
        return rows
    finally:
        with _INFLIGHT_LOCK:
            _INFLIGHT.pop(inflight_key, None)
        waiter.set()


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
    # Individual special teams (#802).  These are paid to the RB, WR, TE
    # and DB this board ranks — not to a team DST — so a stat row that
    # cannot carry them cannot represent a return specialist's production
    # at all.  Defaulted rather than required so existing callers that
    # build this dataclass by hand keep working.
    #
    # Nothing scores from the persisted store today (every realized-points
    # consumer passes RAW rows), so this was latent rather than live.  It
    # is closed here so it cannot quietly become live: the columns exist
    # on the feed, the engine reads them, and only this schema could not
    # hold them.
    kickoff_return_yards: float = 0.0
    punt_return_yards: float = 0.0
    special_teams_tds: float = 0.0
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

    THE THREE TACKLE FIELDS ARE GAMEBOOK VALUES, NOT RAW COLUMNS.
    nflverse's ``def_tackles_solo`` counts *unassisted* tackles only and
    excludes ``def_tackles_with_assist`` (measured: 342 of 9,994 2024
    rows have solo 0 with with_assist > 0).  Its ``def_tackles`` is the
    gamebook SOLO total — ``solo + with_assist``, an exact identity on
    9,994 of 9,994 rows — not combined tackles.  So::

        tackles_solo     = def_tackles_solo + def_tackles_with_assist
        tackles_assist   = def_tackle_assists
        tackles_combined = tackles_solo + tackles_assist

    ``src.nfl_data.actuals_store.normalize_defensive_row`` is the mapper
    that applies this; a caller populating this dataclass by hand from
    raw columns must do the same or it will under-report every defender.
    The unified 2025+ release drops ``def_tackles`` entirely, so reading
    it directly now yields zero.
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
    build).

    The fallback path (``nflverse_direct``) is stdlib-only and
    keeps the feature working when ``nfl_data_py`` can't load,
    but the absence is still operator-relevant — surface it as
    WARNING so it shows up in the live logs once per process,
    rather than vanishing into DEBUG.  ``/api/status`` also
    reports ``nflDataProvider.nfl_data_py_installed`` for the UI.
    """
    try:
        import nfl_data_py  # type: ignore

        return nfl_data_py
    except Exception as exc:  # noqa: BLE001
        _LOGGER.warning(
            "nfl_data_py not importable; falling back to nflverse_direct: %s",
            exc,
        )
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
                    label,
                    len(rows),
                )
                return rows
            except Exception as exc:  # noqa: BLE001
                # Runtime failure (likely pandas API mismatch).  Fall
                # through to the direct fetcher.
                _LOGGER.warning(
                    "nfl_data_fetch=nfl_data_py_runtime_failed label=%s err=%r — "
                    "falling back to nflverse_direct",
                    label,
                    exc,
                )
        else:
            _LOGGER.warning(
                "nfl_data_fetch=nfl_data_py_method_missing label=%s method=%s — "
                "falling back to nflverse_direct",
                label,
                nfl_method,
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
            label,
            direct_method,
        )
        return None
    try:
        rows = direct_fn(years) if years is not None else direct_fn()
        _LOGGER.info(
            "nfl_data_fetch=nflverse_direct label=%s rows=%d",
            label,
            len(rows),
        )
        return rows
    except Exception as exc:  # noqa: BLE001
        _LOGGER.warning(
            "nfl_data_fetch=nflverse_direct_failed label=%s err=%r",
            label,
            exc,
        )
        return None


def fetch_weekly_stats(
    years: list[int],
    *,
    _provider: Callable[[list[int]], Any] | None = None,
    cache_dir=None,
    cache_only: bool = False,
) -> list[dict[str, Any]]:
    """Return per-player-per-week stat rows for the given years.

    ``_provider`` is a test hook; production code should not pass it.
    """
    if not _gated():
        return []
    key = cache_key("weekly_stats", years)
    return _cached_or_fetch(
        key,
        ttl_seconds=_WEEKLY_STATS_TTL,
        cache_dir=cache_dir,
        cache_only=cache_only,
        fetch=lambda: _try_fetch_with_fallback(
            years,
            _provider,
            nfl_method="import_weekly_data",
            direct_method="fetch_weekly_stats",
            label="weekly_stats",
        ),
    )


def fetch_weekly_defensive_stats(
    years: list[int],
    *,
    _provider: Callable[[list[int]], Any] | None = None,
    cache_dir=None,
    cache_only: bool = False,
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
    key = cache_key("weekly_def_stats", years)
    return _cached_or_fetch(
        key,
        ttl_seconds=_WEEKLY_STATS_TTL,
        cache_dir=cache_dir,
        cache_only=cache_only,
        fetch=lambda: _try_fetch_with_fallback(
            years,
            _provider,
            # ``import_weekly_data_def`` was added in nfl_data_py 0.3.5;
            # earlier versions don't expose it.  The fall-through to the
            # direct fetcher handles that case.
            nfl_method="import_weekly_data_def",
            direct_method="fetch_weekly_defensive_stats",
            label="weekly_def_stats",
        ),
    )


def fetch_snap_counts(
    years: list[int],
    *,
    _provider: Callable[[list[int]], Any] | None = None,
    cache_dir=None,
    cache_only: bool = False,
) -> list[dict[str, Any]]:
    """Return per-player-per-week snap rows for the given years.

    Prefers ``nfl_data_py.import_snap_counts``; falls back to direct
    nflverse CSV fetch when nfl_data_py isn't installed.
    """
    if not _gated():
        return []
    key = cache_key("snap_counts", years)
    return _cached_or_fetch(
        key,
        ttl_seconds=_SNAP_COUNTS_TTL,
        cache_dir=cache_dir,
        cache_only=cache_only,
        fetch=lambda: _try_fetch_with_fallback(
            years,
            _provider,
            nfl_method="import_snap_counts",
            direct_method="fetch_snap_counts",
            label="snap_counts",
        ),
    )


def fetch_schedules(
    years: list[int],
    *,
    _provider: Callable[[list[int]], Any] | None = None,
    cache_dir=None,
    cache_only: bool = False,
) -> list[dict[str, Any]]:
    """Schedule rows for the given seasons, cached like every other feed.

    ``src/bdvm/schedule.py`` used to fetch this itself with raw
    ``urllib.request.urlopen`` — a second nflverse downloader with no
    TTL cache, no single-flight and no feature gate, reached from the
    live ``/api/bdvm/*`` request path.  It is retired; this is the one
    owner.

    The ladder is the same one every other feed here uses.
    ``nfl_data_py`` is deliberately absent from ``requirements.txt`` (it
    pins ``pandas<2.0``), and ``_try_fetch_with_fallback`` resolves its
    method with ``getattr``, so in this deployment the rung is skipped
    and the fetch lands on ``nflverse_direct`` — the same release assets
    ``schedule.py`` was downloading by hand.
    """
    if not _gated():
        return []
    key = cache_key("schedules", years)
    return _cached_or_fetch(
        key,
        ttl_seconds=_SCHEDULES_TTL,
        cache_dir=cache_dir,
        cache_only=cache_only,
        fetch=lambda: _try_fetch_with_fallback(
            years,
            _provider,
            nfl_method="import_schedules",
            direct_method="fetch_schedules",
            label="schedules",
        ),
    )


def fetch_id_map(
    *,
    _provider: Callable[[], Any] | None = None,
    cache_dir=None,
    cache_only: bool = False,
) -> list[dict[str, Any]]:
    """Return nflverse's own ID cross-walk (GSIS ↔ PFR ↔ Sleeper).

    Used by the unified ID mapper as a precomputed index.  One call
    per day is enough — the table only changes when rookies are
    added post-draft.
    """
    if not _gated():
        return []
    key = cache_key("id_map")
    return _cached_or_fetch(
        key,
        ttl_seconds=_ROSTERS_TTL,
        cache_dir=cache_dir,
        cache_only=cache_only,
        fetch=lambda: _try_fetch_with_fallback(
            None,
            _provider,
            nfl_method="import_ids",
            direct_method="fetch_id_map",
            label="id_map",
        ),
    )


def provider_status() -> dict[str, Any]:
    """Diagnostic: which provider is active + cache writable?
    Surfaced via /api/status so ops can see if the direct-fetch
    fallback is in use vs. nfl_data_py."""
    installed = _nfl_data_py_or_none() is not None
    direct_available = _nflverse_direct() is not None
    return {
        "feature_flag": feature_flags.is_enabled("nfl_data_ingest"),
        "active_provider": (
            "nfl_data_py" if installed else ("nflverse_direct" if direct_available else "none")
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
