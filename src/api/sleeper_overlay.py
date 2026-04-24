"""On-demand per-league Sleeper overlay.

Problem this solves
───────────────────
The dynasty scraper only runs once per cycle against the
registry's *default* league (see ``Dynasty Scraper.py`` →
``fetch_sleeper_rosters``).  The resulting contract's ``sleeper``
block — ``teams``, ``trades``, roster_positions, league settings
— is therefore for one league only.

When the user switches to a non-default league via the UI, the
``/api/data`` endpoint correctly refuses to render League A's
teams under League B's name.  But the rankings + values are
*scoring-profile-bound* (global), so the UI is left showing
"data not ready" for every team-dependent widget — team command
header, portfolio, trade history, team-scoped signals, etc.

This module closes the gap without running the full scraper per
league.  It fetches only the league-specific Sleeper data
(rosters, users, league metadata, trades) — no ranking pipeline,
no 5MB /v1/players/nfl download (we reuse the player-ID → name
map from the already-loaded contract, since that map is NFL-wide
and not league-specific).

Out of scope
────────────
* Draft-capital / pick-ownership blocks (``team.pickDetails``,
  ``tradeWindow*``).  The ``/api/draft-capital`` endpoint still
  503s for non-loaded leagues — a separate fix.
* Per-league scoring settings + roster positions.  Not needed by
  the terminal or trades page; can be layered in later.

Caching
───────
One Sleeper call = one HTTP round-trip.  Cache each league's
overlay for 15 minutes so steady-state traffic doesn't hammer
Sleeper.  ``invalidate_overlay_cache()`` is exposed for tests +
a potential future admin "refresh" endpoint.
"""
from __future__ import annotations

import datetime as _dt
import json
import logging
import threading
import time
import urllib.error
import urllib.request
from typing import Any

log = logging.getLogger(__name__)

_CACHE: dict[str, dict[str, Any]] = {}
_CACHE_LOCK = threading.Lock()
_CACHE_TTL_SEC = 15 * 60
_HTTP_TIMEOUT_SEC = 8.0
_USER_AGENT = "brisket-sleeper-overlay/1.0"


def _utc_now_ms() -> int:
    return int(time.time() * 1000)


def _http_get_json(url: str) -> Any:
    """Fetch a Sleeper endpoint and parse JSON.  Returns ``None`` on
    any failure — callers treat missing data as "no overlay available"
    and serve the data-not-ready state.
    """
    try:
        req = urllib.request.Request(url, headers={"User-Agent": _USER_AGENT})
        with urllib.request.urlopen(req, timeout=_HTTP_TIMEOUT_SEC) as resp:
            body = resp.read()
    except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError) as exc:
        log.warning("sleeper_overlay: fetch %s failed: %s", url, exc)
        return None
    try:
        return json.loads(body)
    except (json.JSONDecodeError, ValueError):
        log.warning("sleeper_overlay: non-JSON response from %s", url)
        return None


def _walk_league_chain(root_league_id: str, max_depth: int = 2) -> list[str]:
    """Walk backwards through previous_league_id so trade history
    covers multiple seasons when the ``/transactions`` endpoint
    only returns current-season trades.  Mirrors the scraper's
    ``_league_chain_ids`` helper (Dynasty Scraper.py ~line 1109)
    but capped at 2 levels to keep the overlay fetch fast.
    """
    out: list[str] = []
    seen: set[str] = set()
    cur = str(root_league_id or "").strip()
    while cur and cur not in seen and len(out) < max_depth:
        seen.add(cur)
        out.append(cur)
        info = _http_get_json(f"https://api.sleeper.app/v1/league/{cur}")
        if not isinstance(info, dict):
            break
        prev = info.get("previous_league_id") or info.get("previous_league")
        if not prev:
            break
        cur = str(prev).strip()
    return out


def _build_teams_block(
    sleeper_league_id: str,
    id_to_player: dict[str, str] | None,
) -> list[dict[str, Any]] | None:
    """Assemble the ``sleeper.teams`` array for one league.

    Returns None on any fetch failure.  The ``id_to_player`` map is
    the NFL-wide Sleeper-ID → display-name lookup (globally unique,
    safe to reuse from the primary league's contract).  When a
    roster references an ID not in the map, we fall back to the
    raw ID so the UI at least renders a row.
    """
    rosters = _http_get_json(
        f"https://api.sleeper.app/v1/league/{sleeper_league_id}/rosters"
    )
    users = _http_get_json(
        f"https://api.sleeper.app/v1/league/{sleeper_league_id}/users"
    )
    if not isinstance(rosters, list) or not isinstance(users, list):
        return None

    # owner_id → team-display-name.
    user_map: dict[str, str] = {}
    for u in users:
        if not isinstance(u, dict):
            continue
        uid = str(u.get("user_id") or "")
        if not uid:
            continue
        name = (
            (u.get("metadata") or {}).get("team_name")
            or u.get("display_name")
            or f"Team {uid}"
        )
        user_map[uid] = str(name)

    id_map = id_to_player or {}

    teams: list[dict[str, Any]] = []
    for r in rosters:
        if not isinstance(r, dict):
            continue
        owner_id = str(r.get("owner_id") or "")
        roster_id = r.get("roster_id")
        player_ids = r.get("players") or []
        if not isinstance(player_ids, list):
            player_ids = []
        # Convert IDs → display names via the shared NFL map.  Keep
        # raw IDs for callers that need them (consistent with the
        # scraper's ``playerIds`` field).
        names: list[str] = []
        for pid in player_ids:
            pid_str = str(pid or "")
            if not pid_str:
                continue
            mapped = id_map.get(pid_str)
            names.append(mapped if mapped else pid_str)
        teams.append({
            "name": user_map.get(owner_id, f"Team {roster_id}"),
            "ownerId": owner_id,
            "roster_id": roster_id,
            "players": names,
            "playerIds": [str(pid) for pid in player_ids if pid],
            # ``picks`` + ``pickDetails`` require /traded_picks + a
            # pick-owner resolver — out of scope for the minimal
            # overlay.  Empty list is safe: draft-capital panels
            # gracefully render blank, /api/draft-capital still
            # 503s for non-loaded leagues.
            "picks": [],
            "pickDetails": [],
        })
    return teams


def _build_trades_block(
    sleeper_league_id: str,
    window_days: int = 365,
) -> list[dict[str, Any]]:
    """Fetch the rolling trade history for the league chain.

    Sleeper's ``/v1/league/<id>/transactions/<week>`` only exposes
    the current season.  We walk the ``previous_league_id`` chain
    back one level so the rolling window captures inter-season
    trades too.  Trades outside the ``window_days`` cutoff are
    dropped so ``/trades`` doesn't show stale moves.
    """
    cutoff_ms = _utc_now_ms() - int(window_days) * 24 * 3600 * 1000
    chain = _walk_league_chain(sleeper_league_id, max_depth=2)
    if not chain:
        return []

    trades: list[dict[str, Any]] = []
    for lid in chain:
        # Weeks 1..18 cover the regular + postseason transaction
        # calendar; preseason/offseason Sleeper uses weeks 0 (and
        # sometimes -1) — 0 is cheap to include.
        for week in range(0, 19):
            url = (
                f"https://api.sleeper.app/v1/league/{lid}"
                f"/transactions/{week}"
            )
            txs = _http_get_json(url)
            if not isinstance(txs, list):
                continue
            for tx in txs:
                if not isinstance(tx, dict):
                    continue
                if tx.get("type") != "trade":
                    continue
                status_ts = tx.get("status_updated") or tx.get("created")
                ts_ms = _normalize_ts_ms(status_ts)
                if ts_ms and ts_ms < cutoff_ms:
                    continue
                # Pass the raw Sleeper trade shape through — the
                # frontend's ``analyzeSleeperTradeHistory`` already
                # handles the Sleeper schema; the scraper just
                # de-duplicates + tags with an in-window flag.
                trades.append({
                    **tx,
                    "_leagueId": lid,
                    "_statusUpdatedMs": ts_ms or 0,
                })

    # De-dup by transaction_id across the league chain (a trade
    # that bridged seasons can appear twice).
    seen: set[str] = set()
    deduped: list[dict[str, Any]] = []
    for t in trades:
        tid = str(t.get("transaction_id") or "")
        if tid and tid in seen:
            continue
        if tid:
            seen.add(tid)
        deduped.append(t)
    # Newest first — the /trades UI sorts by recency.
    deduped.sort(key=lambda t: t.get("_statusUpdatedMs", 0), reverse=True)
    return deduped


def _normalize_ts_ms(v: Any) -> int:
    """Coerce a Sleeper timestamp to milliseconds.  Some endpoints
    return seconds, others milliseconds; defensively normalize."""
    try:
        n = int(v)
    except (TypeError, ValueError):
        return 0
    if n <= 0:
        return 0
    # Values < 1e12 are seconds (≤ 2001 in ms); scale up.
    if n < 1_000_000_000_000:
        n *= 1000
    return n


def _fetch_league_name(sleeper_league_id: str) -> str | None:
    info = _http_get_json(f"https://api.sleeper.app/v1/league/{sleeper_league_id}")
    if not isinstance(info, dict):
        return None
    name = info.get("name")
    return str(name) if name else None


def fetch_sleeper_overlay(
    *,
    sleeper_league_id: str,
    id_to_player: dict[str, str] | None = None,
    trade_window_days: int = 365,
    force_refresh: bool = False,
) -> dict[str, Any] | None:
    """Return a ``sleeper`` overlay block for a non-loaded league.

    Shape matches the subset of the scraper's ``sleeper`` that the
    terminal + /trades page read:

    .. code-block:: python

        {
            "leagueId":    str,
            "leagueName":  str,
            "teams":       [{name, ownerId, roster_id, players, playerIds, picks=[], pickDetails=[]}],
            "trades":      [<raw sleeper trade dicts>],
            "tradeWindowDays":  int,
            "tradeWindowStart": iso-str,
            "tradeWindowCutoffMs": int,
            "overlaySource": "live",
            "overlayFetchedAt": iso-str,
        }

    Returns None if the fetch failed end-to-end (no teams could
    be loaded).  Partial fetches are acceptable — e.g. trades
    empty but teams populated.

    Caches per ``sleeper_league_id`` for 15 minutes.  Pass
    ``force_refresh=True`` to bust the cache (used by tests).
    """
    sleeper_league_id = str(sleeper_league_id or "").strip()
    if not sleeper_league_id:
        return None

    now = time.time()
    if not force_refresh:
        with _CACHE_LOCK:
            cached = _CACHE.get(sleeper_league_id)
            if cached and (now - float(cached.get("_cached_at") or 0)) < _CACHE_TTL_SEC:
                return dict(cached["payload"])

    teams = _build_teams_block(sleeper_league_id, id_to_player)
    if teams is None:
        # Hard fetch failure — nothing useful to return.
        return None

    league_name = _fetch_league_name(sleeper_league_id) or ""
    trades = _build_trades_block(sleeper_league_id, window_days=trade_window_days)

    cutoff_dt = _dt.datetime.now(_dt.timezone.utc) - _dt.timedelta(
        days=int(trade_window_days)
    )
    payload: dict[str, Any] = {
        "leagueId": sleeper_league_id,
        "leagueName": league_name,
        "teams": teams,
        "trades": trades,
        "tradeWindowDays": int(trade_window_days),
        "tradeWindowStart": cutoff_dt.isoformat(),
        "tradeWindowCutoffMs": int(cutoff_dt.timestamp() * 1000),
        "overlaySource": "live",
        "overlayFetchedAt": _dt.datetime.now(_dt.timezone.utc).isoformat(),
    }

    with _CACHE_LOCK:
        _CACHE[sleeper_league_id] = {"payload": dict(payload), "_cached_at": now}
    return payload


def invalidate_overlay_cache(sleeper_league_id: str | None = None) -> None:
    """Drop cached overlay(s).  ``None`` clears everything."""
    with _CACHE_LOCK:
        if sleeper_league_id is None:
            _CACHE.clear()
            return
        _CACHE.pop(str(sleeper_league_id), None)
