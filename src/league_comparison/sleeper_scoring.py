"""Fetch ``scoring_settings`` for arbitrary Sleeper league IDs.

This module deliberately bypasses ``src.api.league_registry`` because
the league-comparison feature only needs scoring rules — never rosters,
teams, or any other registry-bound data.  Adding leagues to the registry
just to compare their scoring would be unnecessary coupling.

Cache strategy: 1-hour in-memory per league_id.  Scoring settings change
rarely (commissioner edits) — a 1h TTL means a refresh after a settings
change picks up the next hit, while normal traffic doesn't repeatedly
hit Sleeper.
"""

from __future__ import annotations

import hashlib
import json
import logging
import threading
import time
import urllib.error
import urllib.request
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

_LOGGER = logging.getLogger(__name__)

_SLEEPER_API_ROOT = "https://api.sleeper.app/v1"
_CACHE_TTL_SEC = 3600
_HTTP_TIMEOUT = 8.0

_cache: dict[str, tuple[float, "LeagueScoringInfo"]] = {}
_cache_lock = threading.Lock()


@dataclass(frozen=True)
class LeagueScoringInfo:
    league_id: str
    name: str
    season: str
    season_type: str
    scoring_settings: dict[str, float]
    scoring_hash: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "leagueId": self.league_id,
            "name": self.name,
            "season": self.season,
            "seasonType": self.season_type,
            "scoringSettings": dict(self.scoring_settings),
            "scoringHash": self.scoring_hash,
        }


def _scoring_hash(scoring: dict[str, Any]) -> str:
    """Display hash for the league-comparison UI — "did anything change?".

    Deliberately NOT the compatibility identity; see
    :func:`scoring_fingerprint` for why promoting this one would
    manufacture false incompatibility.  Its four consumers live in
    ``src/league_comparison/service.py``.
    """
    payload = json.dumps(scoring, sort_keys=True, default=str)
    return hashlib.sha1(payload.encode("utf-8")).hexdigest()[:12]


#: Bumped when :func:`normalize_scoring_settings` changes.  Carried in the
#: fingerprint string so a stamp produced under older rules can never
#: silently compare equal to one produced under newer rules — it fails
#: closed instead, which is the whole posture of W18-F001.
FINGERPRINT_VERSION = "sf1"


def normalize_scoring_settings(scoring: Any) -> dict[str, float] | None:
    """The valuation-affecting rules of a scoring card, canonicalised.

    Returns ``None`` — never ``{}`` — when there is no card to speak of.
    Missing is never zero.

    Three normalizations, each of which the raw mapping gets wrong:

    * **numeric form** — Sleeper mixes ``1`` and ``1.0`` for the same
      rule; both become the same float.
    * **absent == explicit zero** — Sleeper scores a rule it does not
      list as zero, so a league that lists ``pts_allow_21_27: 0.0`` and
      one that omits it score identically.  Zero-valued rules are
      dropped rather than recorded.
    * **non-scoring keys** — anything whose value is not a number is not
      a scoring rule.  Filtering by *type* rather than by an allowlist is
      deliberate: Sleeper adds scoring keys over time, and an allowlist
      would silently ignore a real difference on a new rule, which is
      failing open on exactly the question this answers.

    ``bool`` is excluded explicitly: it is an ``int`` subclass in Python,
    and a flag is not a scoring rule.
    """
    if not isinstance(scoring, Mapping):
        return None
    out: dict[str, float] = {}
    for key, value in scoring.items():
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            continue
        num = float(value)
        if num != num:  # NaN — not a usable rule
            continue
        if num == 0.0:
            continue
        out[str(key)] = num
    return out or None


def scoring_fingerprint(scoring: Any) -> str | None:
    """A FACTUAL identity for "which scoring rules are these?".

    This is the answer to league-to-league ranking compatibility
    (W18-F001).  ``scoringProfile`` in ``config/leagues/registry.json`` is
    a hand-typed label with its own consumers and is not repurposed for
    it: the repo's two live leagues both carry ``superflex_tep15_ppr1``
    while their hosts differ on 35 of 48 shared keys.

    Returns ``None`` when the card is missing, empty or unusable, so an
    unverifiable identity can be told apart from a verified one and made
    to fail closed by the caller.  A hash of ``{}`` would be
    indistinguishable from a real answer.
    """
    normalized = normalize_scoring_settings(scoring)
    if normalized is None:
        return None
    payload = ";".join(f"{k}={float(v)!r}" for k, v in sorted(normalized.items()))
    digest = hashlib.sha1(payload.encode("utf-8")).hexdigest()[:16]
    return f"{FINGERPRINT_VERSION}:{digest}"


def _fetch_raw(league_id: str) -> dict[str, Any]:
    url = f"{_SLEEPER_API_ROOT}/league/{league_id}"
    req = urllib.request.Request(url, headers={"User-Agent": "riskit-league-compare/1.0"})
    with urllib.request.urlopen(req, timeout=_HTTP_TIMEOUT) as resp:  # noqa: S310
        body = resp.read()
    return json.loads(body)


def fetch_league_scoring(league_id: str, *, refresh: bool = False) -> LeagueScoringInfo:
    """Fetch scoring settings for a Sleeper league.

    Raises ``ValueError`` if the league_id is missing or the API
    response is malformed (no ``scoring_settings`` key).  Network errors
    propagate as ``urllib.error.URLError``; the orchestrator catches and
    converts them to a 503 in the API layer.
    """
    league_id = (league_id or "").strip()
    if not league_id:
        raise ValueError("league_id is required")

    if not refresh:
        with _cache_lock:
            cached = _cache.get(league_id)
            if cached:
                fetched_at, info = cached
                if (time.time() - fetched_at) < _CACHE_TTL_SEC:
                    return info

    try:
        raw = _fetch_raw(league_id)
    except urllib.error.HTTPError as exc:
        if exc.code == 404:
            raise ValueError(f"Sleeper league {league_id!r} not found") from exc
        raise

    if not isinstance(raw, dict):
        raise ValueError(f"Sleeper returned non-dict for {league_id!r}")

    if "scoring_settings" not in raw:
        raise ValueError(f"Sleeper {league_id!r} has no scoring_settings")
    scoring_raw = raw.get("scoring_settings")
    if not isinstance(scoring_raw, dict):
        raise ValueError(f"Sleeper {league_id!r} scoring_settings is not a dict")

    # Coerce all values to float; Sleeper sometimes mixes ints and floats.
    scoring: dict[str, float] = {}
    for k, v in scoring_raw.items():
        try:
            scoring[str(k)] = float(v)
        except (TypeError, ValueError):
            continue

    info = LeagueScoringInfo(
        league_id=league_id,
        name=str(raw.get("name") or "(unnamed)"),
        season=str(raw.get("season") or ""),
        season_type=str(raw.get("season_type") or ""),
        scoring_settings=scoring,
        scoring_hash=_scoring_hash(scoring),
    )

    with _cache_lock:
        _cache[league_id] = (time.time(), info)

    _LOGGER.info(
        "league_compare.scoring_fetched league_id=%s name=%s keys=%d hash=%s",
        league_id,
        info.name,
        len(scoring),
        info.scoring_hash,
    )
    return info


def evict(league_id: str | None = None) -> None:
    """Clear the cache for one league_id, or all if None."""
    with _cache_lock:
        if league_id is None:
            _cache.clear()
        else:
            _cache.pop(league_id, None)
