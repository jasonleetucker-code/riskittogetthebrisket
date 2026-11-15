"""Resolve a KeepTradeCut trade-calculator URL into our canonical
player roster.

A KTC trade URL looks like

    https://keeptradecut.com/trade-calculator
        ?var=5&pickVal=0
        &teamOne=1274&teamTwo=1555
        &format=2&isStartup=0&tep=0

where ``teamOne`` and ``teamTwo`` are KTC player IDs separated by
EITHER ``,`` (KTC's legacy URL form) OR ``|`` (KTC's current URL
form).  The parser accepts both — we split on ``[,|]``.
This module turns that URL into two ordered lists of KTC assets (name,
position, pick flag) the frontend trade page joins onto its board.

The id -> asset map is KTC's own id index, read from page HTML through
``src/sources/ktc_identity.extract_embedded_array`` (see
``_ID_INDEX_PAGES`` for which pages and why).  Picks use KTC IDs too
(``position == "RDP"``) and resolve the same way.  KTC publishes no IDP
players at all, so a KTC trade URL can never carry one.  Unresolved IDs
are returned separately so the UI can surface a clear warning rather
than silently dropping them.

The map is cached in memory for 1 hour and saved box-locally as a
last-known-good copy; every response says which of live / memory /
saved copy it used and how old that is (``playerMap``).
"""

from __future__ import annotations

import json
import os
import re
import threading
import time
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from src.sources.ktc_identity import (
    SEARCH_INDEX_VAR,
    VALUE_BOARD_VAR,
    KtcIdentityCollision,
    extract_embedded_array,
    identity_from_rows,
    identity_rows,
)


# Where the KTC playerID -> asset map comes from, in preference order.
#
# KTC's trade-calculator URL references assets by bare playerID.  Two pages
# carry an id index we can read without a browser:
#
#   * ``/dynasty/trade-database`` -> ``allPlayerSearchValues`` — KTC's whole
#     search index (2,011 rows on 2026-10-13: every player with an id, plus the
#     36 RDP pick rows).  ``src/sources/ktc_identity`` measured this as the
#     correct id population; the value board misses real ids.
#   * ``/trade-calculator`` -> ``playersArray`` — the 500-row value board.  A
#     trade can reference ids deeper than the board, so this is a recorded
#     fallback, never the preferred map.
#
# Both are read through ``ktc_identity.extract_embedded_array``, the one reader
# that understands KTC's inline-literal AND JSON-script-element embeds.  The
# private regex this module used to carry only knew the first; when KTC moved
# the calculator to ``<script id="ktc-players">`` in 2026-10 every import
# failed with "Failed to fetch KTC player map." (we fetch HTML, not a JSON
# endpoint, because /dynasty-rankings/rankings.json 500s to non-browser
# user-agents since April 2026).
_KTC_CALCULATOR_URL = "https://keeptradecut.com/trade-calculator"
_KTC_TRADE_DATABASE_URL = "https://keeptradecut.com/dynasty/trade-database"
_ID_INDEX_PAGES: tuple[tuple[str, str, str], ...] = (
    ("trade_database_search_index", _KTC_TRADE_DATABASE_URL, SEARCH_INDEX_VAR),
    ("trade_calculator_value_board", _KTC_CALCULATOR_URL, VALUE_BOARD_VAR),
)
_KTC_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0 Safari/537.36"
)

# Cache the ID->asset map across requests so repeated imports hit KTC at most
# once per hour.
_CACHE_TTL_SECONDS = 3600
_cache_lock = threading.Lock()
_cache: dict[str, Any] = {"players": None, "fetched_at": 0.0, "index": None}

# Box-local last-known-good copy of the id map (``data/`` is gitignored), written
# after every successful live parse so a restart during a KTC outage or a KTC
# layout change does not take the import down with it.  An id map ages
# gracefully — existing ids keep meaning the same asset, and an id newer than
# the copy comes back ``unresolved``, which the UI already reports — but not
# forever, so a copy older than this is refused rather than served.  This bounds
# an operational cache; it values nothing.
_LAST_GOOD_PATH = (
    Path(__file__).resolve().parents[2] / "data" / "sources" / "ktc" / "ktc_id_index_last_good.json"
)
_LAST_GOOD_MAX_AGE_HOURS = 24 * 14
_LAST_GOOD_SCHEMA = "ktc-id-index/v1"


class KtcPlayerMapError(RuntimeError):
    """The KTC id map could not be obtained.  ``user_message`` is safe to show."""

    status_code = 502
    user_message = "KeepTradeCut's player list could not be loaded."


class KtcLayoutChanged(KtcPlayerMapError):
    user_message = (
        "KeepTradeCut changed its page layout, so its player list could not be read. "
        "The importer needs an update."
    )


class KtcUnreachable(KtcPlayerMapError):
    status_code = 503
    user_message = (
        "KeepTradeCut could not be reached and no saved copy of its player list is "
        "available. Try again in a few minutes."
    )


class KtcCircuitOpen(KtcUnreachable):
    user_message = (
        "KeepTradeCut failed several times in a row, so imports are paused for two "
        "minutes. Try again shortly."
    )


class KtcIdConflict(KtcPlayerMapError):
    user_message = (
        "KeepTradeCut's player list gives one id to two different assets, so the "
        "import was refused rather than guessing."
    )


def _breaker():
    try:
        from src.utils import circuit_breaker as _cb

        return _cb.get_or_create(
            "ktc_scraper",
            failure_threshold=3,
            failure_window_sec=120.0,
            open_duration_sec=120.0,
        )
    except Exception:  # noqa: BLE001 — the breaker is protection, never a dependency
        return None


def _fetch_html(url: str, timeout: float) -> str:
    req = urllib.request.Request(url, headers={"User-Agent": _KTC_UA})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.read().decode("utf-8", errors="replace")


def _fetch_ktc_players(timeout: float = 15.0) -> tuple[list[dict[str, Any]], str]:
    """Fetch KTC's id index live.  Returns ``(rows, index_label)``.

    Tries each page in ``_ID_INDEX_PAGES`` in order and returns the first that
    yields rows.  Raises :class:`KtcUnreachable` when no page could be fetched,
    :class:`KtcLayoutChanged` when pages were fetched but none carried a
    readable array, :class:`KtcCircuitOpen` when the breaker is open.

    Protected by the ``ktc_scraper`` circuit breaker — prevents a KTC outage
    from stalling every trade-import request.
    """
    bp = _breaker()
    if bp is not None and not bp.can_call():
        raise KtcCircuitOpen("ktc_scraper circuit breaker is OPEN")

    fetch_errors: list[str] = []
    shape_misses: list[str] = []
    for label, url, var_name in _ID_INDEX_PAGES:
        try:
            html = _fetch_html(url, timeout)
        except Exception as exc:  # noqa: BLE001 — every transport failure is "unreachable"
            fetch_errors.append(f"{label}: {type(exc).__name__}: {exc}")
            continue
        rows = extract_embedded_array(html, var_name)
        if rows:
            if bp is not None:
                bp.report_success()
            return [r for r in rows if isinstance(r, dict)], label
        shape_misses.append(f"{label}: no readable {var_name}")

    if shape_misses:
        # A page answered but carried nothing we can read — the endpoint is
        # "up" but unusable, which counts as a failure for the breaker.
        if bp is not None:
            bp.report_failure("shape_drift")
        raise KtcLayoutChanged("; ".join(shape_misses + fetch_errors))
    if bp is not None:
        bp.report_failure("; ".join(fetch_errors))
    raise KtcUnreachable("; ".join(fetch_errors))


def _build_player_map(rows: list[dict[str, Any]]) -> dict[int, dict[str, Any]]:
    """Rows -> ``{ktc_id: {name, position, team, slug, rookie}}``.

    Identity (which name and position an id IS, and whether it is a pick) comes
    from the one KTC identity owner, ``ktc_identity.identity_from_rows`` —
    including its collision rule: one id claimed by two names fails closed
    (:class:`KtcIdConflict`) instead of silently picking a winner.  Only the
    display extras (team, slug, rookie) are read here, by id.
    """
    try:
        identity = identity_from_rows(rows)
    except KtcIdentityCollision as exc:
        raise KtcIdConflict(str(exc)) from exc

    extras: dict[int, dict[str, Any]] = {}
    for row in rows:
        try:
            extras[int(row.get("playerID"))] = row
        except (TypeError, ValueError):
            continue

    def _entry(pid: int, name: str, position: str) -> dict[str, Any]:
        extra = extras.get(pid, {})
        return {
            "name": name,
            "position": position,
            "team": str(extra.get("team") or ""),
            "slug": str(extra.get("slug") or ""),
            "rookie": bool(extra.get("rookie")),
        }

    by_id: dict[int, dict[str, Any]] = {}
    for pid, name in identity.players.items():
        by_id[pid] = _entry(pid, name, identity.position_for(pid) or "")
    for pid, name in identity.picks.items():
        by_id[pid] = _entry(pid, name, _PICK_POSITION_NAME)
    return by_id


def _write_last_good(rows: list[dict[str, Any]], index_label: str, fetched_at: float) -> None:
    """Persist the live identity rows atomically.  Never raises — a failed
    write only means the next cold start has no fallback.  Stores the identity
    owner's minimal rows (id, name, position), so a saved copy carries no team
    or slug."""
    try:
        payload = {
            "schema": _LAST_GOOD_SCHEMA,
            "fetchedAt": datetime.fromtimestamp(fetched_at, tz=timezone.utc).isoformat(),
            "index": index_label,
            "players": identity_rows(rows),
        }
        _LAST_GOOD_PATH.parent.mkdir(parents=True, exist_ok=True)
        tmp = _LAST_GOOD_PATH.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
        os.replace(tmp, _LAST_GOOD_PATH)
    except Exception:  # noqa: BLE001
        pass


def _read_last_good(now: float) -> tuple[dict[int, dict[str, Any]], dict[str, Any]] | None:
    """The saved id map, or ``None`` when absent, unreadable, or too old."""
    try:
        payload = json.loads(_LAST_GOOD_PATH.read_text(encoding="utf-8"))
        if payload.get("schema") != _LAST_GOOD_SCHEMA:
            return None
        fetched = datetime.fromisoformat(str(payload["fetchedAt"])).timestamp()
        rows = [r for r in payload.get("players") or [] if isinstance(r, dict)]
        player_map = _build_player_map(rows)
    except Exception:  # noqa: BLE001 — a broken copy is no copy
        return None
    age_hours = (now - fetched) / 3600.0
    if not player_map or age_hours > _LAST_GOOD_MAX_AGE_HOURS or age_hours < -1:
        return None
    return player_map, _map_meta("last_good", payload.get("index"), fetched, now, len(player_map))


def _map_meta(
    source: str, index: Any, fetched_at: float, now: float, entries: int
) -> dict[str, Any]:
    """Where the map came from and how old it is — so a saved copy is never
    presented as a live read."""
    return {
        "source": source,
        "index": index,
        "asOf": datetime.fromtimestamp(fetched_at, tz=timezone.utc).isoformat(),
        "ageHours": round(max(0.0, (now - fetched_at) / 3600.0), 2),
        "entries": entries,
    }


def get_ktc_player_map_with_meta(
    *, force_refresh: bool = False
) -> tuple[dict[int, dict[str, Any]], dict[str, Any]]:
    """Return ``(player_map, meta)``.

    Ladder: in-memory map younger than ``_CACHE_TTL_SECONDS`` -> live fetch ->
    the in-memory map regardless of age -> the box-local last-known-good file
    (bounded by ``_LAST_GOOD_MAX_AGE_HOURS``) -> the live failure is raised.
    ``meta["source"]`` is ``live`` / ``memory`` / ``last_good``.
    """
    now = time.time()
    with _cache_lock:
        cached = _cache["players"]
        fetched_at = _cache["fetched_at"]
        index = _cache["index"]
    if cached is not None and not force_refresh and (now - fetched_at) < _CACHE_TTL_SECONDS:
        return cached, _map_meta("memory", index, fetched_at, now, len(cached))

    try:
        rows, label = _fetch_ktc_players()
        by_id = _build_player_map(rows)
        if not by_id:
            raise KtcLayoutChanged(f"{label}: array present but no usable id rows")
    except KtcPlayerMapError:
        # Serve what we already hold so one flaky fetch doesn't break every
        # import — but say how old it is.
        if cached is not None:
            return cached, _map_meta("memory", index, fetched_at, now, len(cached))
        saved = _read_last_good(now)
        if saved is not None:
            with _cache_lock:
                _cache["players"] = saved[0]
                # Keep the copy's real age so the next request retries live
                # instead of treating the copy as fresh for an hour.
                _cache["fetched_at"] = now - _CACHE_TTL_SECONDS
                _cache["index"] = saved[1]["index"]
            return saved
        raise

    with _cache_lock:
        _cache["players"] = by_id
        _cache["fetched_at"] = now
        _cache["index"] = label
    _write_last_good(rows, label, now)
    return by_id, _map_meta("live", label, now, now, len(by_id))


def get_ktc_player_map(*, force_refresh: bool = False) -> dict[int, dict[str, Any]]:
    """Return a cached ``{ktc_id: {name, position, team, slug, rookie}}`` map.

    See :func:`get_ktc_player_map_with_meta` for the source ladder.
    """
    return get_ktc_player_map_with_meta(force_refresh=force_refresh)[0]


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
        raise ValueError("KTC URL is missing both teamOne and teamTwo parameters")
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
            "sourceUrl": <echo of the input URL>,
            "playerMap": {source, index, asOf, ageHours, entries}
        }

    The caller decides how to map ``sideOne``/``sideTwo`` onto side A
    and side B of the local trade calculator; we preserve KTC's
    ordering verbatim rather than re-sorting here.
    """
    team_one_ids, team_two_ids = parse_trade_url(url)
    player_map, map_meta = get_ktc_player_map_with_meta()
    one_resolved, one_unresolved = resolve_ktc_ids(team_one_ids, player_map=player_map)
    two_resolved, two_unresolved = resolve_ktc_ids(team_two_ids, player_map=player_map)
    return {
        "sourceUrl": url,
        "sideOne": one_resolved,
        "sideTwo": two_resolved,
        "unresolved": {"sideOne": one_unresolved, "sideTwo": two_unresolved},
        "playerMap": map_meta,
    }


# ── Inverse: canonical names → KTC trade URL ──────────────────────
_SUFFIX_RE = re.compile(r"\s+(jr|sr|ii|iii|iv|v)$", re.IGNORECASE)


def _norm_name(s: str) -> str:
    """Private lookup key over KTC's OWN name vocabulary.

    Family 4 (private one-off) in the ``src/utils/name_clean`` registry.
    Lowercase → drop ``.`` and straight ``'`` → collapse whitespace →
    strip a trailing generational suffix.  Hyphens survive on purpose
    (``"Amon-Ra St. Brown" → "amon-ra st brown"``) and curly
    apostrophes are NOT handled (``"Ja’Marr" → "ja’marr"``), because
    both sides of every lookup are KTC player-map names.

    Used only by :func:`build_ktc_url`, which builds ``by_norm`` from
    the KTC player map and resolves against this same function; the key
    never escapes this module, so it is intentionally not one of the
    shared families.

    (The previous docstring claimed to "mirror the import resolver's
    normalization ladder".  It does not — :func:`resolve_ktc_ids`
    resolves purely by integer KTC ID and normalizes no names at all.)
    """
    out = str(s or "").lower()
    out = re.sub(r"[.']", "", out)
    out = re.sub(r"\s+", " ", out).strip()
    out = _SUFFIX_RE.sub("", out).strip()
    return out


def build_ktc_url(side_one_names, side_two_names, *, player_map=None):
    """Inverse of resolve_trade_url: canonical names -> a KTC
    trade-calculator URL.  Reuses the cached player map + the same
    exact -> case-insensitive -> normalized ladder import uses.
    Unmatched names returned in ``unresolved`` (honest, no silent drop).
    """
    if player_map is None:
        player_map = get_ktc_player_map()
    by_exact, by_lower, by_norm = {}, {}, {}
    for pid, entry in player_map.items():
        nm = entry.get("name") or ""
        if not nm:
            continue
        by_exact.setdefault(nm, int(pid))
        by_lower.setdefault(nm.lower(), int(pid))
        by_norm.setdefault(_norm_name(nm), int(pid))

    def _resolve(names):
        ids, missing = [], []
        for raw in names or []:
            nm = str(raw or "").strip()
            if not nm:
                continue
            pid = by_exact.get(nm) or by_lower.get(nm.lower()) or by_norm.get(_norm_name(nm))
            if pid is None:
                missing.append(nm)
            else:
                ids.append(int(pid))
        return ids, missing

    one_ids, one_missing = _resolve(side_one_names)
    two_ids, two_missing = _resolve(side_two_names)
    params = {
        "var": "5",
        "pickVal": "0",
        "teamOne": "|".join(str(i) for i in one_ids),
        "teamTwo": "|".join(str(i) for i in two_ids),
        "format": "2",
        "isStartup": "0",
        "tep": "0",
    }
    url = _KTC_CALCULATOR_URL + "?" + urllib.parse.urlencode(params, safe="|")
    return {
        "url": url,
        "unresolved": {"sideOne": one_missing, "sideTwo": two_missing},
        "resolvedCount": {"sideOne": len(one_ids), "sideTwo": len(two_ids)},
    }
