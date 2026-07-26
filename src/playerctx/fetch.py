"""Download the raw player-context datasets to ``data/playerctx/``.

Datasets (all public, no auth):

1. **Contracts** — OTC-sourced contracts published by nflverse::

       https://github.com/nflverse/nflverse-data/releases/download/contracts/historical_contracts.csv.gz

   ~32k rows, ~1.2 MB gzipped.  One release-level file (not seasonal).
   Verified 2026-07-25: columns ``player, position, team, is_active,
   year_signed, years, value, apy, guaranteed, ...`` — no gsis_id, so
   the join runs on name+position through the unified mapper.

2. **Snap counts** — PFR-sourced weekly snap counts, one file per
   season::

       https://github.com/nflverse/nflverse-data/releases/download/snap_counts/snap_counts_{season}.csv

   ~27k rows / ~2.4 MB per season.  Keys on ``pfr_player_id`` +
   name/team/position (no gsis_id).  The current calendar year's file
   does not exist until the season starts, so we walk a season
   fallback list newest-first.

3. **Depth charts** — team depth charts, one file per season::

       https://github.com/nflverse/nflverse-data/releases/download/depth_charts/depth_charts_{season}.csv

   Large (35-55 MB — the file appends a dated snapshot per scrape run;
   ``normalize`` keeps only the newest snapshot per team).  Carries
   ``gsis_id`` AND ``espn_id`` → exact-ID join.  Refreshed by nflverse
   through the offseason, so the current-year file usually exists
   before the season starts.

4. **Sleeper players directory** — the join anchor
   (``https://api.sleeper.app/v1/players/nfl``, ~5 MB JSON).  Cached
   like the rest; Sleeper asks integrators to fetch this at most ~once
   a day, which the freshness window enforces.

Caching:
    Every download lands in ``data/playerctx/`` (covered by the
    repo-wide ``data/`` gitignore — nothing to add).  A sidecar
    ``<file>.meta.json`` records the served ETag / Last-Modified, and
    re-fetches are skipped entirely while the local file is younger
    than ``max_age_hours`` (mtime check).  Past the window we issue a
    conditional GET (``If-None-Match`` / ``If-Modified-Since``) and a
    304 just refreshes the mtime.  GitHub's release-asset host serves
    both validators (verified live).
"""

from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import requests

log = logging.getLogger(__name__)

REPO_ROOT = Path(__file__).resolve().parents[2]
CACHE_DIR = REPO_ROOT / "data" / "playerctx"

# Honest UA — this is a low-volume weekly fetcher, not a browser.
USER_AGENT = (
    "riskittogetthebrisket-playerctx/1.0 "
    "(+https://github.com/jasonleetucker-code/riskittogetthebrisket; "
    "dynasty fantasy football research; weekly cadence)"
)

_NFLVERSE_BASE = "https://github.com/nflverse/nflverse-data/releases/download"
CONTRACTS_URL = f"{_NFLVERSE_BASE}/contracts/historical_contracts.csv.gz"
SNAP_COUNTS_URL_TMPL = f"{_NFLVERSE_BASE}/snap_counts/snap_counts_{{season}}.csv"
DEPTH_CHARTS_URL_TMPL = f"{_NFLVERSE_BASE}/depth_charts/depth_charts_{{season}}.csv"
SLEEPER_PLAYERS_URL = "https://api.sleeper.app/v1/players/nfl"

# (connect, read) — the depth-chart file is ~50 MB, give it room.
_TIMEOUT: tuple[int, int] = (15, 180)

# Default freshness window.  These datasets move at most daily; the
# refresh cadence is weekly, so anything younger than 6h is "fresh".
DEFAULT_MAX_AGE_HOURS = 6.0


@dataclass
class FetchResult:
    """Outcome of one dataset fetch."""

    key: str
    path: Path | None
    status: str  # "downloaded" | "not-modified" | "fresh-skip" | "missing" | "error"
    detail: str = ""


@dataclass
class FetchBundle:
    """Everything ``service.refresh_playerctx`` needs from the network."""

    contracts: Path | None = None
    snap_counts: Path | None = None
    snap_counts_season: int | None = None
    depth_charts: Path | None = None
    depth_charts_season: int | None = None
    sleeper_players: Path | None = None
    warnings: list[str] = field(default_factory=list)


def _meta_path(dest: Path) -> Path:
    # NOT ``with_suffix`` — that would eat the ``.gz`` of ``*.csv.gz``.
    return dest.parent / (dest.name + ".meta.json")


def _load_meta(dest: Path) -> dict[str, Any]:
    try:
        raw = json.loads(_meta_path(dest).read_text(encoding="utf-8"))
        return raw if isinstance(raw, dict) else {}
    except (OSError, ValueError):
        return {}


def _save_meta(dest: Path, meta: dict[str, Any]) -> None:
    try:
        _meta_path(dest).write_text(
            json.dumps(meta, ensure_ascii=False, indent=1), encoding="utf-8"
        )
    except OSError as exc:  # meta is an optimization, never fatal
        log.warning("playerctx: could not write meta for %s: %s", dest.name, exc)


def _is_fresh(dest: Path, max_age_hours: float) -> bool:
    try:
        age_sec = time.time() - dest.stat().st_mtime
    except OSError:
        return False
    return age_sec < max_age_hours * 3600.0


def fetch_url(
    url: str,
    dest: Path,
    *,
    key: str = "",
    max_age_hours: float = DEFAULT_MAX_AGE_HOURS,
    force: bool = False,
    session: requests.Session | None = None,
) -> FetchResult:
    """Download ``url`` to ``dest`` with freshness + conditional-GET skip.

    Returns a :class:`FetchResult`; ``path`` is ``None`` only for a 404
    (``status="missing"``) or a hard error with no usable local copy.
    A network error when a stale local copy exists degrades to that
    copy (``status="error"`` but ``path`` set) so a flaky mirror never
    wipes out last-good data.
    """
    key = key or dest.name
    if not force and dest.exists() and _is_fresh(dest, max_age_hours):
        return FetchResult(key=key, path=dest, status="fresh-skip")

    headers = {"User-Agent": USER_AGENT, "Accept": "*/*"}
    meta = _load_meta(dest)
    if dest.exists() and not force:
        if meta.get("etag"):
            headers["If-None-Match"] = str(meta["etag"])
        if meta.get("lastModified"):
            headers["If-Modified-Since"] = str(meta["lastModified"])

    http = session or requests
    try:
        resp = http.get(url, headers=headers, timeout=_TIMEOUT, stream=True)
    except requests.RequestException as exc:
        if dest.exists():
            log.warning("playerctx[%s]: fetch failed (%s); keeping stale local copy", key, exc)
            return FetchResult(key=key, path=dest, status="error", detail=str(exc))
        return FetchResult(key=key, path=None, status="error", detail=str(exc))

    try:
        if resp.status_code == 304:
            dest.touch()
            meta["checkedAt"] = datetime.now(timezone.utc).isoformat()
            _save_meta(dest, meta)
            return FetchResult(key=key, path=dest, status="not-modified")
        if resp.status_code == 404:
            return FetchResult(key=key, path=None, status="missing", detail="404")
        if resp.status_code != 200:
            detail = f"HTTP {resp.status_code}"
            if dest.exists():
                log.warning("playerctx[%s]: %s; keeping stale local copy", key, detail)
                return FetchResult(key=key, path=dest, status="error", detail=detail)
            return FetchResult(key=key, path=None, status="error", detail=detail)

        dest.parent.mkdir(parents=True, exist_ok=True)
        tmp = dest.parent / f"{dest.name}.tmp-{int(time.time() * 1000)}"
        size = 0
        try:
            with tmp.open("wb") as fh:
                for chunk in resp.iter_content(chunk_size=1 << 16):
                    if chunk:
                        fh.write(chunk)
                        size += len(chunk)
            tmp.replace(dest)
        except requests.RequestException as exc:
            # A connection reset MID-STREAM (very possible on the
            # 35-55 MB depth-chart file) must degrade to the stale
            # local copy exactly like a failure at request start —
            # never fail the whole refresh while a usable cache sits
            # on disk.
            tmp.unlink(missing_ok=True)
            if dest.exists():
                log.warning("playerctx[%s]: stream failed (%s); keeping stale local copy", key, exc)
                return FetchResult(key=key, path=dest, status="error", detail=f"stream: {exc}")
            return FetchResult(key=key, path=None, status="error", detail=f"stream: {exc}")
        except BaseException:
            tmp.unlink(missing_ok=True)
            raise
        _save_meta(
            dest,
            {
                "url": url,
                "etag": resp.headers.get("ETag", ""),
                "lastModified": resp.headers.get("Last-Modified", ""),
                "size": size,
                "fetchedAt": datetime.now(timezone.utc).isoformat(),
            },
        )
        log.info("playerctx[%s]: downloaded %d bytes", key, size)
        return FetchResult(key=key, path=dest, status="downloaded", detail=f"{size} bytes")
    finally:
        resp.close()


def _fetch_seasonal(
    url_tmpl: str,
    filename_tmpl: str,
    seasons: list[int],
    cache_dir: Path,
    *,
    key: str,
    max_age_hours: float,
    force: bool,
    session: requests.Session | None,
) -> tuple[Path | None, int | None, list[str]]:
    """Try each season newest-first; first hit wins.

    Only a 404 walks on to the prior season — that is the one signal
    that the season file genuinely doesn't exist upstream yet (normal
    in the offseason for snap counts).  A TRANSIENT failure (timeout /
    5xx / connection error) with no usable local copy STOPS the walk
    and reports no path: mid-season, silently publishing last year's
    snaps or depth charts would look plausible enough to sail past the
    retention guards, so the refresh must fail instead and leave the
    existing last-good snapshot untouched.  A transient failure WITH a
    local copy of that season still degrades to the stale copy
    (``fetch_url`` returns it with ``status="error"``).
    """
    warnings: list[str] = []
    for season in seasons:
        dest = cache_dir / filename_tmpl.format(season=season)
        res = fetch_url(
            url_tmpl.format(season=season),
            dest,
            key=f"{key}:{season}",
            max_age_hours=max_age_hours,
            force=force,
            session=session,
        )
        if res.path is not None:
            if res.status == "error":
                warnings.append(f"{key} {season}: {res.detail} (using stale local copy)")
            return res.path, season, warnings
        if res.status != "missing":
            # Transient / unexpected failure with no local fallback —
            # do NOT mask it with a prior-season download.
            warnings.append(
                f"{key} {season}: {res.status} {res.detail} "
                "(transient failure — refusing prior-season fallback)"
            )
            return None, None, warnings
    warnings.append(f"{key}: no season file available for {seasons}")
    return None, None, warnings


def default_seasons(now: datetime | None = None) -> list[int]:
    """Newest-first season candidates: current calendar year, then the
    prior one.  During the offseason the current-year snap-count file
    does not exist yet and the walk lands on the completed season."""
    year = (now or datetime.now(timezone.utc)).year
    return [year, year - 1]


def fetch_all(
    *,
    cache_dir: Path | None = None,
    seasons: list[int] | None = None,
    max_age_hours: float = DEFAULT_MAX_AGE_HOURS,
    force: bool = False,
    session: requests.Session | None = None,
) -> FetchBundle:
    """Fetch every dataset the player-context snapshot needs.

    Individual dataset failures degrade to ``None`` + a warning rather
    than raising — ``service.refresh_playerctx`` decides what is fatal
    (schema floors) and what is a soft miss.
    """
    cache = cache_dir or CACHE_DIR
    cache.mkdir(parents=True, exist_ok=True)
    season_list = seasons or default_seasons()
    bundle = FetchBundle()

    res = fetch_url(
        CONTRACTS_URL,
        cache / "historical_contracts.csv.gz",
        key="contracts",
        max_age_hours=max_age_hours,
        force=force,
        session=session,
    )
    bundle.contracts = res.path
    if res.path is None or res.status == "error":
        bundle.warnings.append(f"contracts: {res.status} {res.detail}")

    bundle.snap_counts, bundle.snap_counts_season, warns = _fetch_seasonal(
        SNAP_COUNTS_URL_TMPL,
        "snap_counts_{season}.csv",
        season_list,
        cache,
        key="snap_counts",
        max_age_hours=max_age_hours,
        force=force,
        session=session,
    )
    bundle.warnings.extend(warns)

    bundle.depth_charts, bundle.depth_charts_season, warns = _fetch_seasonal(
        DEPTH_CHARTS_URL_TMPL,
        "depth_charts_{season}.csv",
        season_list,
        cache,
        key="depth_charts",
        max_age_hours=max_age_hours,
        force=force,
        session=session,
    )
    bundle.warnings.extend(warns)

    # Sleeper's guidance is ≤ ~1 fetch/day for the full players dump;
    # a wider freshness window enforces that even under --force-free
    # repeat runs.
    res = fetch_url(
        SLEEPER_PLAYERS_URL,
        cache / "sleeper_players.json",
        key="sleeper_players",
        max_age_hours=max(max_age_hours, 20.0),
        force=force,
        session=session,
    )
    bundle.sleeper_players = res.path
    if res.path is None or res.status == "error":
        bundle.warnings.append(f"sleeper_players: {res.status} {res.detail}")

    return bundle
