"""Direct nflverse-data fetcher — bypasses nfl_data_py entirely.

Why this exists
---------------
``nfl_data_py`` 0.3.x (latest on PyPI) pins ``pandas<2.0``.  On
Python 3.12 that forces a from-source build of pandas 1.5.3 which
fails on modern setuptools (``pkg_resources`` removed).

This module replaces nfl_data_py for our use case by fetching
nflverse-data release CSVs directly via stdlib + parsing into
``list[dict]``.  Zero third-party deps.  Same shape we already
consume — the ``ingest.py`` adapter only sees rows of dicts.

When nfl_data_py IS installed (e.g. on a Python 3.11 box, or with
the ``--no-deps`` workaround), ``ingest.py`` prefers it.  This
module is the universal fallback that always works.

Data sources
------------
nflverse-data releases live at::

    https://github.com/nflverse/nflverse-data/releases

Each release has CSV + parquet variants.  We pull CSV because
parsing it is a stdlib one-liner.

Caching
-------
This module does NOT cache — it's just the fetch layer.
``src/nfl_data/cache.py`` wraps it with TTL on the consumer side.

No-throw contract
-----------------
Every public function returns ``[]`` on any failure: network,
HTTP error, parse error, empty CSV.  Logs a structured warning
on failure paths so ops can grep ``nflverse_direct=`` for
upstream issues.
"""

from __future__ import annotations

import csv
import io
import logging
import re
import urllib.error
import urllib.request
from datetime import date, datetime, timezone
from typing import Any

_LOGGER = logging.getLogger(__name__)


# nflverse-data release URL patterns.  These are stable — verified
# 2026-04-25.  When nflverse re-organizes a release path the test
# fixture catches it; bump the URL here and ship.
_RELEASE_BASE = "https://github.com/nflverse/nflverse-data/releases/download"

# Per-dataset URL templates.  ``{year}`` is the season year.
_URL_TEMPLATES = {
    # nflverse RENAMED and UNIFIED this release in 2025.  The old
    # ``player_stats/player_stats_{year}.csv`` 404s for 2025+ while
    # still serving <=2024, so the break was invisible: ``_fetch_csv``
    # swallows the 404, returns [], and every downstream consumer sees
    # "no rows for 2025" as though the season had no data.  Probed
    # 2026-07-27:
    #
    #     player_stats/player_stats_2024.csv          200
    #     player_stats/player_stats_2025.csv          404
    #     player_stats/player_stats_def_2024.csv      200
    #     player_stats/player_stats_def_2025.csv      404
    #     stats_player/stats_player_week_2024.csv     200
    #     stats_player/stats_player_week_2025.csv     200
    #
    # The new file serves BOTH years and unifies offense and defense —
    # it carries 15 ``def_*`` columns (``def_tackles_solo``,
    # ``def_sacks``, ``def_tackles_for_loss``, ``def_pass_defended``,
    # …) alongside the offensive ones.  So both keys point at one URL
    # and the two fetch functions differ only in how they filter, not
    # in what they request.  Keeping both templates (rather than one)
    # preserves the public API its callers in ``ingest.py`` depend on.
    "weekly_stats": (f"{_RELEASE_BASE}/stats_player/stats_player_week_{{year}}.csv"),
    "weekly_defensive_stats": (f"{_RELEASE_BASE}/stats_player/stats_player_week_{{year}}.csv"),
    "snap_counts": (f"{_RELEASE_BASE}/snap_counts/snap_counts_{{year}}.csv"),
    "id_map": (f"{_RELEASE_BASE}/players/players.csv"),
    "pbp": (f"{_RELEASE_BASE}/pbp/play_by_play_{{year}}.csv"),
    # Moved here from ``src/bdvm/schedule.py``, which fetched it with its
    # own ``urllib.request.urlopen`` and therefore had no TTL cache, no
    # single-flight and no feature gate — a second nflverse downloader
    # beside this one.  ``schedules_all`` is the combined file and is the
    # fallback when the per-season file is not published yet (observed:
    # ``sched_2026.csv`` 404s while ``games.csv`` already carries the
    # 2026 slate).
    "schedules": (f"{_RELEASE_BASE}/schedules/sched_{{year}}.csv"),
    "schedules_all": (f"{_RELEASE_BASE}/schedules/games.csv"),
}

_HTTP_TIMEOUT_SEC = 30.0
_USER_AGENT = "brisket-nflverse-direct/1.0"

# Seasons whose assets nflverse cannot have published yet.
#
# A 404 has two causes and they need opposite responses.  The one the
# module was written for is a stale template (the 2025 rename below) —
# permanent, our fault, and worth shouting about.  The other is asking
# for a season that has not started: nflverse publishes a season's
# release assets once it is under way, so every `*_{next_year}.csv`
# 404s for the whole Feb–Aug window by design.
#
# Measured 2026-07-29, with the 2026 season not yet begun:
#
#     stats_player/stats_player_week_2025.csv     200
#     stats_player/stats_player_week_2026.csv     404
#     snap_counts/snap_counts_2025.csv            200
#     snap_counts/snap_counts_2026.csv            404
#     pbp/play_by_play_2025.csv                   200
#     pbp/play_by_play_2026.csv                   404
#
# Treating that as a failure was wrong twice over.  It logged
# "the URL template needs updating" at ERROR for a URL that is
# correct and will start working in September, and — the part that
# actually bites — it fed `report_failure` on a breaker scoped to the
# WHOLE module (threshold 3 / 180s).  Three future-season datasets
# probed together is exactly three failures inside the window, which
# opens the breaker for 300s and blocks the 2025 fetches that were
# working fine.  A permanent, predictable, correct-by-design 404 is
# not a transient fault and must not be counted as one.


def _latest_published_season(today: "date | None" = None) -> int:
    """Most recent season nflverse can plausibly have published.

    September onward the current year's assets exist; before that the
    newest complete release is last year's.  Deliberately NOT
    ``current_nfl_season`` from ``src.bdvm.actuals``: that one answers
    "is a season being played right now" and returns None Feb–Aug,
    which is the wrong question here — nflverse still serves last
    season's finished data all offseason.
    """
    d = today or datetime.now(timezone.utc).date()
    return d.year if d.month >= 9 else d.year - 1


def _season_in_url(url: str) -> int | None:
    """The 4-digit season a release URL asks for, if it names one.

    Anchored to the filename so a year inside the host or release base
    can never be mistaken for the requested season.
    """
    m = re.search(r"_(\d{4})\.csv$", url)
    return int(m.group(1)) if m else None


def _fetch_csv(url: str, *, label: str) -> list[dict[str, Any]]:
    """Fetch a CSV URL and parse to list[dict].  Returns [] on
    any failure with a structured log line."""
    # Circuit breaker pre-check.
    bp = None
    try:
        from src.utils import circuit_breaker as _cb

        bp = _cb.get_or_create(
            "nflverse_direct",
            failure_threshold=3,
            failure_window_sec=180.0,
            open_duration_sec=300.0,
        )
        if not bp.can_call():
            _LOGGER.warning(
                "nflverse_direct=circuit_open label=%s url=%s",
                label,
                url,
            )
            return []
    except Exception:  # noqa: BLE001
        bp = None

    try:
        req = urllib.request.Request(url, headers={"User-Agent": _USER_AGENT})
        with urllib.request.urlopen(req, timeout=_HTTP_TIMEOUT_SEC) as resp:
            body = resp.read().decode("utf-8", errors="replace")
    except urllib.error.HTTPError as exc:
        status = getattr(exc, "code", 0)
        # A 404 is categorically different from a 5xx or a timeout.
        # The host answered and said this path does not exist, which
        # means OUR URL template is wrong — nflverse renamed or moved
        # the release. Retrying will never fix it, and the caller sees
        # the same empty list it would see for a genuinely dataless
        # season. That is exactly how the 2025 rename went unnoticed:
        # `player_stats_{year}.csv` kept serving <=2024 while 404ing
        # 2025, so the break looked like "no data yet".
        if status == 404:
            season = _season_in_url(url)
            if season is not None and season > _latest_published_season():
                # Not published yet, not broken. Return [] as always,
                # but do NOT report to the breaker — see the note above
                # _latest_published_season for why that matters.
                _LOGGER.info(
                    "nflverse_direct=season_unpublished label=%s url=%s status=404 "
                    "— season %d has not started; nflverse publishes its assets "
                    "once it is under way. Returning no rows; nothing to fix.",
                    label,
                    url,
                    season,
                )
                return []
            _LOGGER.error(
                "nflverse_direct=url_stale label=%s url=%s status=404 "
                "— the release path no longer exists; the URL template in "
                "_URL_TEMPLATES needs updating. Returning no rows.",
                label,
                url,
            )
        else:
            _LOGGER.warning(
                "nflverse_direct=http label=%s url=%s status=%d",
                label,
                url,
                status,
            )
        if bp is not None:
            bp.report_failure(exc)
        return []
    except (urllib.error.URLError, TimeoutError) as exc:
        _LOGGER.warning(
            "nflverse_direct=network label=%s url=%s err=%r",
            label,
            url,
            exc,
        )
        if bp is not None:
            bp.report_failure(exc)
        return []
    except Exception as exc:  # noqa: BLE001
        _LOGGER.warning(
            "nflverse_direct=unexpected label=%s url=%s err=%r",
            label,
            url,
            exc,
        )
        if bp is not None:
            bp.report_failure(exc)
        return []

    try:
        reader = csv.DictReader(io.StringIO(body))
        rows = list(reader)
    except Exception as exc:  # noqa: BLE001
        _LOGGER.warning(
            "nflverse_direct=parse label=%s err=%r",
            label,
            exc,
        )
        if bp is not None:
            bp.report_failure(exc)
        return []

    _LOGGER.info(
        "nflverse_direct=ok label=%s url=%s rows=%d",
        label,
        url,
        len(rows),
    )
    if bp is not None:
        bp.report_success()
    return rows


def _coerce_numerics(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """CSV rows arrive as strings.  Coerce numeric fields to int/float
    where the value parses cleanly; leave strings otherwise.

    The downstream consumers (realized_points, opportunity_stats,
    usage_windows) all use ``_num()`` helpers that tolerate both
    string and numeric inputs, but coercing here keeps the contract
    closer to nfl_data_py's DataFrame.to_dict() output."""
    if not rows:
        return rows
    # Sniff numeric columns from the first row's keys.
    out = []
    for row in rows:
        new_row: dict[str, Any] = {}
        for k, v in row.items():
            if v is None or v == "":
                new_row[k] = None
                continue
            # Try int, then float, fall back to string.
            try:
                if "." in v or "e" in v.lower():
                    new_row[k] = float(v)
                else:
                    new_row[k] = int(v)
            except (TypeError, ValueError):
                new_row[k] = v
        out.append(new_row)
    return out


def fetch_weekly_stats(years: list[int]) -> list[dict[str, Any]]:
    """Fetch weekly OFFENSIVE stat rows for a list of years.

    Returns the concatenated list across all years.  Defensive stats
    are in a separate file — use :func:`fetch_weekly_defensive_stats`.
    """
    out: list[dict[str, Any]] = []
    for year in years:
        url = _URL_TEMPLATES["weekly_stats"].format(year=year)
        rows = _fetch_csv(url, label=f"weekly_stats:{year}")
        out.extend(_coerce_numerics(rows))
    return out


def fetch_weekly_defensive_stats(years: list[int]) -> list[dict[str, Any]]:
    """Fetch weekly DEFENSIVE stat rows for a list of years.

    nflverse splits offense vs. defense across two release files; the
    defensive file's columns are prefixed ``def_``
    (``def_tackles_solo``, ``def_sacks``, ``def_qb_hits``,
    ``def_pass_defended``, ``def_interceptions``,
    ``def_interception_yards``, ``def_fumbles_forced``,
    ``def_fumble_recovery_own``, ``def_fumble_recovery_yards_own``,
    ``def_tds``, ``def_safety``, ``def_tackles_for_loss``,
    ``def_tackles_for_loss_yards``, ``def_sack_yards``).

    Returns the concatenated list across all years.  Empty list on
    any failure.
    """
    out: list[dict[str, Any]] = []
    for year in years:
        url = _URL_TEMPLATES["weekly_defensive_stats"].format(year=year)
        rows = _fetch_csv(url, label=f"weekly_defensive_stats:{year}")
        out.extend(_coerce_numerics(rows))
    return out


def fetch_snap_counts(years: list[int]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for year in years:
        url = _URL_TEMPLATES["snap_counts"].format(year=year)
        rows = _fetch_csv(url, label=f"snap_counts:{year}")
        out.extend(_coerce_numerics(rows))
    return out


def fetch_schedules(years: list[int]) -> list[dict[str, Any]]:
    """Schedule rows for the given seasons.

    Per-season file first, then the combined ``games.csv`` filtered to
    the season — the exact two-rung order the retired
    ``bdvm/schedule.py`` downloader used, preserved so the rows this
    returns are the rows that module always saw.
    """
    out: list[dict[str, Any]] = []
    for year in years:
        rows = _fetch_csv(_URL_TEMPLATES["schedules"].format(year=year), label=f"schedules:{year}")
        if not rows:
            combined = _fetch_csv(_URL_TEMPLATES["schedules_all"], label="schedules:all")
            rows = [r for r in combined if str(r.get("season") or "").strip() == str(year)]
        out.extend(_coerce_numerics(rows))
    return out


def fetch_id_map() -> list[dict[str, Any]]:
    url = _URL_TEMPLATES["id_map"]
    return _coerce_numerics(_fetch_csv(url, label="id_map"))


def fetch_pbp(years: list[int]) -> list[dict[str, Any]]:
    """Play-by-play is the heaviest dataset (~50k rows × season).
    Caller should aggregate before storing."""
    out: list[dict[str, Any]] = []
    for year in years:
        url = _URL_TEMPLATES["pbp"].format(year=year)
        rows = _fetch_csv(url, label=f"pbp:{year}")
        out.extend(_coerce_numerics(rows))
    return out
