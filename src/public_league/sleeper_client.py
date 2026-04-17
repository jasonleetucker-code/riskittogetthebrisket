"""Thin, side-effect-free Sleeper HTTP client for the public pipeline.

The public league snapshot pulls exclusively from the documented
Sleeper v1 endpoints.  No internal scraper state, no CSV, no cached
private payload.  Every call degrades gracefully — a network failure
returns ``None`` / ``[]`` rather than raising, so the snapshot can
still render with partial sections instead of failing the whole
page.

Exactly two dynasty seasons are supported right now: the current
league and its direct ``previous_league_id``.  The chain walk is
capped so a badly-configured league cannot recurse forever.
"""
from __future__ import annotations

import json
import logging
import urllib.error
import urllib.request
from typing import Any

log = logging.getLogger(__name__)

SLEEPER_BASE = "https://api.sleeper.app/v1"

# Max dynasty seasons the public pipeline surfaces.  The prompt fixes
# the horizon at "exactly the last 2 dynasty seasons for now" — bumping
# this value will automatically widen every section module because they
# iterate ``snapshot.seasons``.
PUBLIC_MAX_SEASONS = 2

_DEFAULT_TIMEOUT = 8.0


def _request_json(url: str, timeout: float = _DEFAULT_TIMEOUT) -> Any:
    """GET ``url`` and return parsed JSON, or ``None`` on any failure."""
    req = urllib.request.Request(
        url,
        headers={"User-Agent": "brisket-public-league/1.0"},
        method="GET",
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            body = resp.read()
    except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError) as exc:
        log.warning("sleeper_client GET failed for %s: %s", url, exc)
        return None
    except Exception as exc:  # noqa: BLE001 — belt-and-suspenders
        log.warning("sleeper_client GET unexpected error for %s: %s", url, exc)
        return None
    try:
        return json.loads(body.decode("utf-8") or "null")
    except (ValueError, UnicodeDecodeError) as exc:
        log.warning("sleeper_client JSON decode failed for %s: %s", url, exc)
        return None


def fetch_league(league_id: str) -> dict[str, Any] | None:
    data = _request_json(f"{SLEEPER_BASE}/league/{league_id}")
    return data if isinstance(data, dict) else None


def fetch_users(league_id: str) -> list[dict[str, Any]]:
    data = _request_json(f"{SLEEPER_BASE}/league/{league_id}/users")
    return data if isinstance(data, list) else []


def fetch_rosters(league_id: str) -> list[dict[str, Any]]:
    data = _request_json(f"{SLEEPER_BASE}/league/{league_id}/rosters")
    return data if isinstance(data, list) else []


def fetch_matchups(league_id: str, week: int) -> list[dict[str, Any]]:
    data = _request_json(f"{SLEEPER_BASE}/league/{league_id}/matchups/{week}")
    return data if isinstance(data, list) else []


def fetch_transactions(league_id: str, week: int) -> list[dict[str, Any]]:
    data = _request_json(f"{SLEEPER_BASE}/league/{league_id}/transactions/{week}")
    return data if isinstance(data, list) else []


def fetch_drafts(league_id: str) -> list[dict[str, Any]]:
    data = _request_json(f"{SLEEPER_BASE}/league/{league_id}/drafts")
    return data if isinstance(data, list) else []


def fetch_draft_detail(draft_id: str) -> dict[str, Any] | None:
    data = _request_json(f"{SLEEPER_BASE}/draft/{draft_id}")
    return data if isinstance(data, dict) else None


def fetch_draft_picks(draft_id: str) -> list[dict[str, Any]]:
    data = _request_json(f"{SLEEPER_BASE}/draft/{draft_id}/picks")
    return data if isinstance(data, list) else []


def fetch_traded_picks(league_id: str) -> list[dict[str, Any]]:
    data = _request_json(f"{SLEEPER_BASE}/league/{league_id}/traded_picks")
    return data if isinstance(data, list) else []


def fetch_winners_bracket(league_id: str) -> list[dict[str, Any]]:
    data = _request_json(f"{SLEEPER_BASE}/league/{league_id}/winners_bracket")
    return data if isinstance(data, list) else []


def fetch_losers_bracket(league_id: str) -> list[dict[str, Any]]:
    data = _request_json(f"{SLEEPER_BASE}/league/{league_id}/losers_bracket")
    return data if isinstance(data, list) else []


# Module-level cache for the (large) NFL players dump.  Fetched lazily
# the first time a section needs player position data and shared across
# every subsequent snapshot build.  ~5 MB from Sleeper — we cache it
# for the life of the process.
_nfl_players_cache: dict[str, Any] | None = None


def fetch_nfl_players() -> dict[str, Any]:
    """Return Sleeper's ``players/nfl`` dump keyed by player_id.

    Graceful fallback: empty dict on any network or parse error so the
    public pipeline can still render without position breakdowns.
    """
    global _nfl_players_cache
    if _nfl_players_cache is not None:
        return _nfl_players_cache
    data = _request_json(f"{SLEEPER_BASE}/players/nfl", timeout=30.0)
    _nfl_players_cache = data if isinstance(data, dict) else {}
    return _nfl_players_cache


def reset_nfl_players_cache() -> None:
    """Test hook — clear the cached NFL players dump."""
    global _nfl_players_cache
    _nfl_players_cache = None


def walk_league_chain(start_league_id: str, max_seasons: int = PUBLIC_MAX_SEASONS) -> list[dict[str, Any]]:
    """Follow ``previous_league_id`` links up to ``max_seasons`` hops.

    Returns a list of league objects ordered current → previous.  When
    the chain is shorter than ``max_seasons`` (e.g. league only has one
    completed dynasty season), the returned list is simply shorter —
    callers must handle the short case.

    Graceful fallback: any missing league object or broken link ends
    the walk without raising.
    """
    if max_seasons <= 0:
        return []
    chain: list[dict[str, Any]] = []
    seen: set[str] = set()
    cur = str(start_league_id or "").strip()
    while cur and cur not in seen and len(chain) < max_seasons:
        seen.add(cur)
        league = fetch_league(cur)
        if not league:
            break
        chain.append(league)
        nxt = league.get("previous_league_id") or league.get("previous_league") or ""
        cur = str(nxt or "").strip()
    return chain
