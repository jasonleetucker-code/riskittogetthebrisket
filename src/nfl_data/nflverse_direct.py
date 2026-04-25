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
import urllib.error
import urllib.request
from typing import Any

_LOGGER = logging.getLogger(__name__)


# nflverse-data release URL patterns.  These are stable — verified
# 2026-04-25.  When nflverse re-organizes a release path the test
# fixture catches it; bump the URL here and ship.
_RELEASE_BASE = "https://github.com/nflverse/nflverse-data/releases/download"

# Per-dataset URL templates.  ``{year}`` is the season year.
_URL_TEMPLATES = {
    "weekly_stats": (
        f"{_RELEASE_BASE}/player_stats/player_stats_{{year}}.csv"
    ),
    "snap_counts": (
        f"{_RELEASE_BASE}/snap_counts/snap_counts_{{year}}.csv"
    ),
    "id_map": (
        f"{_RELEASE_BASE}/players/players.csv"
    ),
    "pbp": (
        f"{_RELEASE_BASE}/pbp/play_by_play_{{year}}.csv"
    ),
}

_HTTP_TIMEOUT_SEC = 30.0
_USER_AGENT = "brisket-nflverse-direct/1.0"


def _fetch_csv(url: str, *, label: str) -> list[dict[str, Any]]:
    """Fetch a CSV URL and parse to list[dict].  Returns [] on
    any failure with a structured log line."""
    # Circuit breaker pre-check.
    bp = None
    try:
        from src.utils import circuit_breaker as _cb
        bp = _cb.get_or_create(
            "nflverse_direct",
            failure_threshold=3, failure_window_sec=180.0,
            open_duration_sec=300.0,
        )
        if not bp.can_call():
            _LOGGER.warning(
                "nflverse_direct=circuit_open label=%s url=%s",
                label, url,
            )
            return []
    except Exception:  # noqa: BLE001
        bp = None

    try:
        req = urllib.request.Request(url, headers={"User-Agent": _USER_AGENT})
        with urllib.request.urlopen(req, timeout=_HTTP_TIMEOUT_SEC) as resp:
            body = resp.read().decode("utf-8", errors="replace")
    except urllib.error.HTTPError as exc:
        _LOGGER.warning(
            "nflverse_direct=http label=%s url=%s status=%d",
            label, url, getattr(exc, "code", 0),
        )
        if bp is not None:
            bp.report_failure(exc)
        return []
    except (urllib.error.URLError, TimeoutError) as exc:
        _LOGGER.warning(
            "nflverse_direct=network label=%s url=%s err=%r",
            label, url, exc,
        )
        if bp is not None:
            bp.report_failure(exc)
        return []
    except Exception as exc:  # noqa: BLE001
        _LOGGER.warning(
            "nflverse_direct=unexpected label=%s url=%s err=%r",
            label, url, exc,
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
            label, exc,
        )
        if bp is not None:
            bp.report_failure(exc)
        return []

    _LOGGER.info(
        "nflverse_direct=ok label=%s url=%s rows=%d",
        label, url, len(rows),
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
    """Fetch weekly stat rows for a list of years.  Returns the
    concatenated list across all years."""
    out: list[dict[str, Any]] = []
    for year in years:
        url = _URL_TEMPLATES["weekly_stats"].format(year=year)
        rows = _fetch_csv(url, label=f"weekly_stats:{year}")
        out.extend(_coerce_numerics(rows))
    return out


def fetch_snap_counts(years: list[int]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for year in years:
        url = _URL_TEMPLATES["snap_counts"].format(year=year)
        rows = _fetch_csv(url, label=f"snap_counts:{year}")
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
