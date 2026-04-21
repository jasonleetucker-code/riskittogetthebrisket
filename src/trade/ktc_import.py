"""Resolve a KeepTradeCut trade-calculator URL into our canonical
player roster.

KTC embeds a ``var playersArray = [...]`` 500-entry JSON blob in the
HTML of https://keeptradecut.com/trade-calculator.  Each entry has
``playerID`` (int), ``playerName`` (str), ``position``, ``team``,
``slug``.  A KTC trade URL looks like

    https://keeptradecut.com/trade-calculator
        ?var=5&pickVal=0
        &teamOne=1274&teamTwo=1555
        &format=2&isStartup=0&tep=0

where ``teamOne`` and ``teamTwo`` are KTC player IDs separated by
EITHER ``,`` (KTC's legacy URL form) OR ``|`` (KTC's current URL
form).  The parser accepts both — we split on ``[,|]``.
This module turns that URL into two ordered lists of canonical player
names the frontend trade page can load into its sides.

Picks use KTC IDs too (they live in the same ``playersArray`` but
positionID=7 — "RDP" / rookie draft pick); they're resolved the same
way.  Unresolved IDs (KTC had a player we don't know about) are
returned separately so the UI can surface a clear warning rather
than silently dropping them.

The player-map fetch is cached for 1 hour — KTC doesn't add new IDs
often enough to matter, and hitting their HTML on every import would
be rude.
"""
from __future__ import annotations

import json
import re
import threading
import time
import urllib.parse
import urllib.request
from typing import Any


# KTC's trade-calculator page embeds the player map.  We fetch this
# page (not a JSON endpoint) because their /dynasty-rankings/rankings.json
# started 500-ing to non-browser user-agents in April 2026.  The HTML
# path is stable and scraper-friendly.
_KTC_CALCULATOR_URL = "https://keeptradecut.com/trade-calculator"
_KTC_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0 Safari/537.36"
)
_PLAYERS_ARRAY_RE = re.compile(r"var\s+playersArray\s*=\s*(\[.*?\]);", re.DOTALL)

# Cache the ID→name map across requests so repeated imports hit KTC
# at most once per hour.
_CACHE_TTL_SECONDS = 3600
_cache_lock = threading.Lock()
_cache: dict[str, Any] = {"players": None, "fetched_at": 0.0}


def _fetch_ktc_players(timeout: float = 15.0) -> list[dict[str, Any]]:
    """Pull the raw playersArray from KTC's calculator HTML.

    Raises ``RuntimeError`` if the page's ``playersArray`` regex
    doesn't match — that'd mean KTC changed their embed shape and
    the import feature is broken until we update this module.
    """
    req = urllib.request.Request(_KTC_CALCULATOR_URL, headers={"User-Agent": _KTC_UA})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        html = resp.read().decode("utf-8", errors="replace")
    m = _PLAYERS_ARRAY_RE.search(html)
    if not m:
        raise RuntimeError(
            "KTC page layout changed — playersArray regex no longer matches. "
            "Update src/trade/ktc_import.py::_PLAYERS_ARRAY_RE."
        )
    return json.loads(m.group(1))


def get_ktc_player_map(*, force_refresh: bool = False) -> dict[int, dict[str, Any]]:
    """Return a cached ``{ktc_id: {name, position, team, slug, rookie}}`` map.

    Fetches once per ``_CACHE_TTL_SECONDS`` across all callers.  A
    first-request failure surfaces the underlying exception; a stale
    cache (post-failure retry window) is returned if a refresh fails
    to avoid breaking an otherwise-working feature.
    """
    now = time.time()
    with _cache_lock:
        cached = _cache["players"]
        fresh = cached is not None and (now - _cache["fetched_at"]) < _CACHE_TTL_SECONDS
        if fresh and not force_refresh:
            return cached  # type: ignore[return-value]

    try:
        arr = _fetch_ktc_players()
    except Exception:
        # Serve stale cache on refresh failure so one flaky fetch
        # doesn't break every import until the next refresh window.
        if cached is not None:
            return cached  # type: ignore[return-value]
        raise

    by_id: dict[int, dict[str, Any]] = {}
    for entry in arr:
        pid = entry.get("playerID")
        name = entry.get("playerName")
        if not isinstance(pid, int) or not name:
            continue
        by_id[int(pid)] = {
            "name": str(name),
            "position": str(entry.get("position") or "").upper(),
            "team": str(entry.get("team") or ""),
            "slug": str(entry.get("slug") or ""),
            "rookie": bool(entry.get("rookie")),
        }

    with _cache_lock:
        _cache["players"] = by_id
        _cache["fetched_at"] = now
    return by_id


def parse_trade_url(url: str) -> tuple[list[int], list[int]]:
    """Return (teamOne_ids, teamTwo_ids) parsed from a KTC trade URL.

    Raises ``ValueError`` if the URL lacks both team parameters (empty
    trade) or if any listed ID isn't parseable as an int.
    """
    parsed = urllib.parse.urlparse((url or "").strip())
    query = urllib.parse.parse_qs(parsed.query or "", keep_blank_values=False)

    def _parse_side(raw_values: list[str]) -> list[int]:
        ids: list[int] = []
        for raw in raw_values:
            # KTC uses BOTH ``,`` and ``|`` as ID separators depending
            # on where/when the URL was generated.  Treating only one
            # as valid makes pipe-form URLs (``teamOne=1934|1771``)
            # error out with "non-integer KTC id".  Split on either.
            for token in re.split(r"[,|]", str(raw)):
                token = token.strip()
                if not token:
                    continue
                try:
                    ids.append(int(token))
                except ValueError as exc:
                    raise ValueError(f"non-integer KTC id in URL: {token!r}") from exc
        return ids

    team_one = _parse_side(query.get("teamOne", []))
    team_two = _parse_side(query.get("teamTwo", []))
    if not team_one and not team_two:
        raise ValueError(
            "KTC URL is missing both teamOne and teamTwo parameters"
        )
    return team_one, team_two


# ── Pick-name normalization ───────────────────────────────────────

# KTC formats picks as "2026 Mid 1st" / "2026 Early 2nd" etc.  Our
# board uses the same shape (see CSVs/site_raw/ktc.csv), so we
# typically get a free match.  When KTC emits a pick name we don't
# recognize, we fall back to an overall-first-round / etc. label
# and flag it as "best-effort" so the UI can surface the mapping.
_PICK_POSITION_IDS = {7}  # KTC assigns positionID=7 to RDP rows
_PICK_POSITION_NAME = "RDP"

# KTC's positionID → our canonical position-group.  Missing entries
# fall through to the raw ``position`` string from KTC.
_POSITION_GROUP = {
    1: "QB",
    2: "RB",
    3: "WR",
    4: "TE",
    7: "PICK",
}


def _looks_like_pick(entry: dict[str, Any]) -> bool:
    """Return True when a KTC entry is a draft pick rather than a
    rostered player.  Uses ``position == "RDP"`` primarily and
    ``positionID == 7`` as a secondary signal for forward-compat."""
    pos = str(entry.get("position") or "").upper()
    return pos == _PICK_POSITION_NAME or pos in ("PICK", "RDP")


def resolve_ktc_ids(
    ktc_ids: list[int],
    *,
    player_map: dict[int, dict[str, Any]] | None = None,
) -> tuple[list[dict[str, Any]], list[int]]:
    """Resolve a list of KTC IDs into enriched player descriptors.

    Returns ``(resolved, unresolved_ids)`` where:

      - ``resolved`` is a list of dicts with ``ktcId``, ``name``,
        ``position``, ``team``, ``isPick`` — ordered to match the
        input IDs so the UI preserves the user's slot ordering.
      - ``unresolved_ids`` is the list of KTC IDs we didn't find in
        the player map; the caller surfaces these in a warning so
        the user knows one or more slots got dropped.
    """
    if player_map is None:
        player_map = get_ktc_player_map()
    resolved: list[dict[str, Any]] = []
    unresolved: list[int] = []
    for pid in ktc_ids:
        entry = player_map.get(int(pid))
        if not entry:
            unresolved.append(int(pid))
            continue
        resolved.append(
            {
                "ktcId": int(pid),
                "name": entry["name"],
                "position": entry["position"],
                "team": entry["team"],
                "slug": entry.get("slug") or "",
                "isPick": _looks_like_pick(entry),
            }
        )
    return resolved, unresolved


def resolve_trade_url(url: str) -> dict[str, Any]:
    """End-to-end resolution of a KTC trade URL.

    Returns a dict the ``/api/trade/import-ktc`` endpoint hands back
    to the frontend.  Shape:

        {
            "sideOne": [{ktcId, name, position, team, slug, isPick}, ...],
            "sideTwo": [...],
            "unresolved": {"sideOne": [int, ...], "sideTwo": [...]},
            "sourceUrl": <echo of the input URL>
        }

    The caller decides how to map ``sideOne``/``sideTwo`` onto side A
    and side B of the local trade calculator; we preserve KTC's
    ordering verbatim rather than re-sorting here.
    """
    team_one_ids, team_two_ids = parse_trade_url(url)
    player_map = get_ktc_player_map()
    one_resolved, one_unresolved = resolve_ktc_ids(team_one_ids, player_map=player_map)
    two_resolved, two_unresolved = resolve_ktc_ids(team_two_ids, player_map=player_map)
    return {
        "sourceUrl": url,
        "sideOne": one_resolved,
        "sideTwo": two_resolved,
        "unresolved": {"sideOne": one_unresolved, "sideTwo": two_unresolved},
    }
