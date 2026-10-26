"""Shared pinned inputs + a polite cached fetcher for the IDP-accuracy research lane.

Research-only (owner directive ``docs/owner/IDP_VALUATION_ACCURACY_DIRECTIVE_2026-10-25.md``).
Nothing in ``src/`` imports this, and it writes nothing outside ``data/idp_accuracy/``
(gitignored) and ``docs/valuation/idp_accuracy/``.

The fetcher only ever issues public, unauthenticated GETs to the Sleeper read API,
throttled under 5 requests/second, and caches each response once.  A cached
response is REUSED by default (``max_age_s=None``) so a re-run reproduces the same
inputs; the manifest records the sha256 of every cached body it relied on.
"""

from __future__ import annotations

import hashlib
import json
import time
from pathlib import Path
from typing import Any

import requests

REPO = Path(__file__).resolve().parents[2]

# ── pinned inputs (task + directive; change only with a new manifest) ─────────
PINNED_REPO_SHA = "bdbc83a1fba1b1278c7862362f9a18a2da69b970"
LEAGUE_KEY = "dynasty_main"
LEAGUE_ID = "1312006700437352448"
SEASON = 2026
#: regular-season weeks whose games were all final on 2026-10-25; week 7 is
#: in progress and is EXCLUDED.
WEEKS = (1, 2, 3, 4, 5, 6)
PINNED_ARCHIVE = REPO / "exports/archive/dynasty_export_20261025_120337.zip"
HISTORY_FLOOR = "2026-07-14"

SLEEPER = "https://api.sleeper.app/v1"
CACHE_DIR = REPO / "data/idp_accuracy/cache"
OUT_DIR = REPO / "docs/valuation/idp_accuracy"

IDP_GROUPS = ("DL", "LB", "DB")


def sha256_bytes(blob: bytes) -> str:
    return hashlib.sha256(blob).hexdigest()


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


class Fetcher:
    """Cached, throttled GET of public Sleeper endpoints (never authenticated)."""

    MIN_INTERVAL_S = 0.25  # < 5 req/s

    def __init__(self, cache_dir: Path = CACHE_DIR, *, offline: bool = False) -> None:
        self.cache_dir = cache_dir
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.offline = offline
        self.session = requests.Session()
        self._last = 0.0
        self.calls = 0
        #: url -> {"sha256", "fetchedAt", "cachePath"} for every body served
        self.receipts: dict[str, dict[str, Any]] = {}

    def _path(self, url: str) -> Path:
        key = hashlib.sha256(url.encode()).hexdigest()[:24]
        return self.cache_dir / f"{key}.json"

    def get(self, url: str, *, max_age_s: float | None = None) -> Any:
        path = self._path(url)
        fresh = path.exists() and (
            max_age_s is None or time.time() - path.stat().st_mtime < max_age_s
        )
        if not fresh:
            if self.offline:
                raise RuntimeError(f"offline and not cached: {url}")
            wait = self.MIN_INTERVAL_S - (time.time() - self._last)
            if wait > 0:
                time.sleep(wait)
            resp = self.session.get(url, timeout=60)
            self._last = time.time()
            resp.raise_for_status()
            self.calls += 1
            path.write_bytes(resp.content)
        blob = path.read_bytes()
        self.receipts[url] = {
            "sha256": sha256_bytes(blob),
            "fetchedAtUtc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(path.stat().st_mtime)),
            "bytes": len(blob),
        }
        return json.loads(blob)

    # convenience
    def league(self) -> dict:
        return self.get(f"{SLEEPER}/league/{LEAGUE_ID}")

    def rosters(self) -> list:
        return self.get(f"{SLEEPER}/league/{LEAGUE_ID}/rosters")

    def matchups(self, week: int) -> list:
        return self.get(f"{SLEEPER}/league/{LEAGUE_ID}/matchups/{week}")

    def stats(self, week: int, season: int = SEASON) -> dict:
        return self.get(f"{SLEEPER}/stats/nfl/regular/{season}/{week}")

    def players(self) -> dict:
        return self.get(f"{SLEEPER}/players/nfl")
