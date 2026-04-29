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

    Protected by the ``sleeper_api`` circuit breaker: after repeated
    failures the breaker OPENs and this call fails fast (returns
    None) for 60s, preventing a Sleeper outage from turning into 10
    minutes of /api/data timeouts.
    """
    # Circuit breaker: fail fast when Sleeper is tripped.
    try:
        from src.utils import circuit_breaker as _cb
        bp = _cb.get_or_create(
            "sleeper_api",
            failure_threshold=5, failure_window_sec=60.0,
            open_duration_sec=60.0,
        )
        if not bp.can_call():
            log.warning("sleeper_overlay: breaker OPEN, fast-fail %s", url)
            return None
    except Exception:  # noqa: BLE001 — never let CB itself break the fetch
        bp = None

    try:
        req = urllib.request.Request(url, headers={"User-Agent": _USER_AGENT})
        with urllib.request.urlopen(req, timeout=_HTTP_TIMEOUT_SEC) as resp:
            body = resp.read()
    except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError) as exc:
        log.warning("sleeper_overlay: fetch %s failed: %s", url, exc)
        if bp is not None:
            bp.report_failure(exc)
        return None
    try:
        parsed = json.loads(body)
        if bp is not None:
            bp.report_success()
        return parsed
    except (json.JSONDecodeError, ValueError):
        log.warning("sleeper_overlay: non-JSON response from %s", url)
        if bp is not None:
            # JSON-parse failure counts as a failure — Sleeper returning
            # an HTML challenge page means they're blocking us.
            bp.report_failure("non_json")
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


def _round_suffix(n: int) -> str:
    """1 → '1st', 2 → '2nd', 3 → '3rd', 4+ → 'Nth'.  Matches the
    scraper's convention for pick labels (``2027 1st``)."""
    if n == 1:
        return "1st"
    if n == 2:
        return "2nd"
    if n == 3:
        return "3rd"
    return f"{n}th"


def _format_pick_label(season: str, round_num: int, slot: int | None = None) -> str:
    """Build a human-readable pick asset name matching what the
    rankings board renders: ``"2027 1.05"`` when slot is known,
    ``"2027 1st"`` otherwise (traded-future picks usually have no
    slot yet).  The rankings pipeline emits both shapes so the UI
    resolves either."""
    if slot is not None and slot > 0:
        return f"{season} {round_num}.{str(slot).zfill(2)}"
    return f"{season} {_round_suffix(round_num)}"


def _build_pick_ownership(
    sleeper_league_id: str,
    roster_ids: list[int],
    num_rounds: int = 6,
    num_years: int = 3,
) -> dict[int, list[dict[str, Any]]]:
    """Return ``{rosterId: [pickDetail, ...]}`` — which future picks
    each roster currently owns based on the league's
    ``/traded_picks`` endpoint.

    Default ownership: each roster owns its own pick in every round
    of every upcoming year.  ``/traded_picks`` returns the diffs —
    swap ``original`` → ``owner`` per entry to get current
    ownership.  Matches the scraper's team_pick_details construction
    in Dynasty Scraper.py (fetch_sleeper_rosters).

    Returns an empty map on any fetch failure — callers degrade to
    the data-not-ready state for draft-capital widgets.
    """
    import datetime as _dt
    if not roster_ids:
        return {}
    current_year = _dt.datetime.now(_dt.timezone.utc).year
    years = [str(current_year + y) for y in range(num_years)]

    # Seed: every roster owns its own picks by default.
    ownership: dict[tuple[str, int, int], int] = {}
    for year in years:
        for rnd in range(1, num_rounds + 1):
            for rid in roster_ids:
                ownership[(year, rnd, rid)] = rid

    traded = _http_get_json(
        f"https://api.sleeper.app/v1/league/{sleeper_league_id}/traded_picks"
    )
    if isinstance(traded, list):
        for tp in traded:
            if not isinstance(tp, dict):
                continue
            try:
                season = str(tp.get("season") or "")
                rnd = int(tp.get("round") or 0)
                original = int(tp.get("roster_id") or 0)
                owner = int(tp.get("owner_id") or 0)
            except (TypeError, ValueError):
                continue
            if not season or rnd < 1 or not original or not owner:
                continue
            key = (season, rnd, original)
            if key in ownership:
                ownership[key] = owner

    # Re-pivot to {current_owner: [pickDetail...]}.
    per_roster: dict[int, list[dict[str, Any]]] = {rid: [] for rid in roster_ids}
    for (season, rnd, original), current_owner in ownership.items():
        per_roster.setdefault(current_owner, []).append({
            "season": season,
            "round": rnd,
            "slot": None,
            "original_roster_id": original,
            "owner_roster_id": current_owner,
            "label": _format_pick_label(season, rnd),
        })
    # Sort each team's picks year-then-round for deterministic output.
    for rid, plist in per_roster.items():
        plist.sort(key=lambda p: (p.get("season", ""), p.get("round", 0)))
    return per_roster


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

    Also populates ``picks`` (list of pick labels) + ``pickDetails``
    (raw {season, round, ...} dicts) per team by resolving
    ``/traded_picks`` against each roster's default ownership.
    This is what unblocks /api/draft-capital + angle-finder for
    non-default leagues.
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
    roster_ids: list[int] = []
    for r in rosters:
        if isinstance(r, dict) and r.get("roster_id") is not None:
            try:
                roster_ids.append(int(r["roster_id"]))
            except (TypeError, ValueError):
                continue
    pick_ownership = _build_pick_ownership(sleeper_league_id, roster_ids)

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
        try:
            rid_int = int(roster_id) if roster_id is not None else 0
        except (TypeError, ValueError):
            rid_int = 0
        pick_details = pick_ownership.get(rid_int, [])
        pick_labels = [p["label"] for p in pick_details]
        teams.append({
            "name": user_map.get(owner_id, f"Team {roster_id}"),
            "ownerId": owner_id,
            "roster_id": roster_id,
            "players": names,
            "playerIds": [str(pid) for pid in player_ids if pid],
            "picks": pick_labels,
            "pickDetails": pick_details,
        })
    return teams


def _safe_int(v: Any) -> int | None:
    """Defensive int coerce — Sleeper sometimes returns roster ids as
    strings, sometimes as ints."""
    try:
        return int(v)
    except (TypeError, ValueError):
        return None


def _league_rid_lookup(
    target_league_id: str,
) -> tuple[dict[Any, str], dict[Any, str]]:
    """Per-league roster lookup: ``(rid_to_name, rid_to_owner_id)``.

    Mirrors the offline scraper's helper of the same name in
    ``Dynasty Scraper.py`` so trade-side construction emits BOTH the
    display name at that point in time AND the Sleeper user id that
    owned the roster at that point.  Owner-id is the authoritative
    aggregation key for trade history — it stays stable for the same
    human across league chains and correctly splits trades when an
    orphaned roster changes hands.

    Both maps are keyed under the raw Sleeper ``roster_id`` AND its
    string + int forms so callers can look up either way without
    coercing first.  Empty maps on any fetch failure (the trade
    builder degrades gracefully).
    """
    rid_to_name: dict[Any, str] = {}
    rid_to_owner: dict[Any, str] = {}
    rosters = _http_get_json(
        f"https://api.sleeper.app/v1/league/{target_league_id}/rosters"
    )
    users = _http_get_json(
        f"https://api.sleeper.app/v1/league/{target_league_id}/users"
    )
    if not isinstance(rosters, list):
        return rid_to_name, rid_to_owner
    user_map: dict[str, str] = {}
    if isinstance(users, list):
        for u in users:
            if not isinstance(u, dict):
                continue
            uid = str(u.get("user_id") or "")
            if not uid:
                continue
            metadata = u.get("metadata") if isinstance(u.get("metadata"), dict) else {}
            name = (
                (metadata or {}).get("team_name")
                or u.get("display_name")
                or f"Team {uid}"
            )
            user_map[uid] = str(name)
    for r in rosters:
        if not isinstance(r, dict):
            continue
        rid = r.get("roster_id")
        oid = str(r.get("owner_id") or "")
        rid_int = _safe_int(rid)
        team_name = user_map.get(oid, f"Team {rid}" if rid is not None else "Team")
        if rid is not None:
            rid_to_name[rid] = team_name
        if rid_int is not None:
            rid_to_name[rid_int] = team_name
            rid_to_name[str(rid_int)] = team_name
        if oid:
            if rid is not None:
                rid_to_owner[rid] = oid
            if rid_int is not None:
                rid_to_owner[rid_int] = oid
                rid_to_owner[str(rid_int)] = oid
    return rid_to_name, rid_to_owner


def _league_draft_slot_lookup(
    target_league_id: str,
) -> dict[tuple[int, int], int]:
    """Build ``{(season, origin_roster_id): slot}`` from each draft's
    ``slot_to_roster_id`` map.  Used to format pick labels with the
    canonical ``"YYYY R.SS"`` slot suffix that the rankings board's
    pick rows match — without the slot, labels degrade to the
    tier-rounded ``"YYYY 1st"`` form which still resolves via
    ``buildPickLookupCandidates`` on the frontend, just less
    precisely.

    Mirrors the offline scraper's draft enumeration (Dynasty
    Scraper.py ~870-915) but trimmed to just the slot map.  Empty on
    any fetch failure.
    """
    out: dict[tuple[int, int], int] = {}
    drafts = _http_get_json(
        f"https://api.sleeper.app/v1/league/{target_league_id}/drafts"
    )
    if not isinstance(drafts, list):
        return out
    for d in drafts:
        if not isinstance(d, dict):
            continue
        season = _safe_int(d.get("season"))
        slot_map = d.get("slot_to_roster_id")
        if not isinstance(slot_map, dict) or season is None:
            continue
        for slot_str, rid_val in slot_map.items():
            slot_num = _safe_int(slot_str)
            rid_num = _safe_int(rid_val)
            if slot_num is None or rid_num is None or slot_num <= 0:
                continue
            out[(season, rid_num)] = slot_num
    return out


def _format_trade_pick_label(
    pick: dict[str, Any],
    rid_to_name: dict[Any, str],
    draft_slot_by_origin: dict[tuple[int, int], int],
) -> str:
    """Canonical pick label for trade-history valuation.  Matches the
    offline scraper's ``_format_trade_pick_label`` so the resulting
    string resolves through the same frontend ``resolvePickRow``
    pipeline as the baked trades.

    Format precedence:
      1. ``YYYY R.SS (from Team)`` — when the draft slot is known.
      2. ``YYYY R{th} (from Team)`` — slot unknown (typical for
         current-year picks before the draft has happened, or future
         years).
    """
    season = _safe_int(pick.get("season"))
    round_num = _safe_int(pick.get("round"))
    origin_rid = _safe_int(pick.get("roster_id") or pick.get("origin_roster_id"))

    from_team: str | None = None
    if origin_rid is not None:
        from_team = (
            rid_to_name.get(origin_rid)
            or rid_to_name.get(str(origin_rid))
            or f"Team {origin_rid}"
        )

    base_label: str | None = None
    if season is not None and round_num is not None and round_num > 0:
        slot = (
            draft_slot_by_origin.get((season, origin_rid))
            if origin_rid is not None else None
        )
        if isinstance(slot, int) and slot > 0:
            base_label = f"{season} {round_num}.{str(slot).zfill(2)}"
        else:
            base_label = f"{season} {_round_suffix(round_num)}"

    if not base_label:
        season_txt = str(pick.get("season", "")).strip()
        round_txt = str(pick.get("round", "?")).strip()
        base_label = f"{season_txt} Round {round_txt}".strip()

    return f"{base_label} (from {from_team})" if from_team else base_label


def _append_trade_side_item(
    side_map: dict[Any, list[str]], rid: Any, label: str,
) -> None:
    """Append ``label`` under both string and int keys for ``rid`` so
    later side construction can find the entries however it indexes.
    Skips empty labels and dedupes within a single side.
    """
    if not label:
        return
    keys: list[Any] = []
    if rid is not None:
        keys.append(rid)
    rid_int = _safe_int(rid)
    if rid_int is not None:
        keys.extend([rid_int, str(rid_int)])
    for k in keys:
        arr = side_map.setdefault(k, [])
        if label not in arr:
            arr.append(label)


def _build_trades_block(
    sleeper_league_id: str,
    window_days: int = 365,
    id_to_player: dict[str, str] | None = None,
) -> list[dict[str, Any]]:
    """Fetch the rolling trade history for the league chain and
    PROCESS each trade into the same shape the offline scraper bakes
    into ``sleeper.trades``::

        {leagueId, week, timestamp, sides: [{team, rosterId, ownerId,
                                              got: [...], gave: [...]}, ...]}

    ``got`` / ``gave`` are arrays of canonical asset labels (player
    display names + pick labels) — the shape that
    ``frontend/lib/league-analysis.js::analyzeSleeperTradeHistory``
    consumes on /trades.  Earlier versions returned the raw Sleeper
    transaction shape (``transaction_id``, ``adds``, ``drops``,
    ``draft_picks``, ...) which the frontend couldn't grade — that's
    the bug we're fixing here.

    Sleeper's ``/v1/league/<id>/transactions/<week>`` only exposes
    the current season; we walk the ``previous_league_id`` chain
    (depth 2) so inter-season trades stay in the rolling window.
    Trades outside ``window_days`` are dropped.

    ``id_to_player`` is the NFL-wide Sleeper-ID → display-name map,
    typically reused from the loaded contract.  When absent, player
    labels fall back to the raw Sleeper id.
    """
    cutoff_ms = _utc_now_ms() - int(window_days) * 24 * 3600 * 1000
    chain = _walk_league_chain(sleeper_league_id, max_depth=2)
    if not chain:
        return []

    id_map = id_to_player if isinstance(id_to_player, dict) else {}

    trades: list[dict[str, Any]] = []
    seen: set[str] = set()

    for lid in chain:
        # Per-league lookups: roster-id → team name, → owner_id, and
        # the season-rooted draft-slot map.  Each league chain entry
        # has its own roster identity (a roster_id can change human
        # ownership across seasons).
        rid_to_name, rid_to_owner = _league_rid_lookup(lid)
        draft_slot_by_origin = _league_draft_slot_lookup(lid)

        # Weeks 0..18 cover preseason/regular/postseason transaction
        # calendar.  0 is cheap to include and catches preseason
        # trades that happened before week 1.
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
                # Match the offline scraper: only completed trades.
                # Mid-flight proposals shouldn't show up on /trades.
                if tx.get("status") != "complete":
                    continue
                status_ts = tx.get("status_updated") or tx.get("created")
                ts_ms = _normalize_ts_ms(status_ts)
                if ts_ms and ts_ms < cutoff_ms:
                    continue
                tx_id = str(tx.get("transaction_id") or "")
                if tx_id and tx_id in seen:
                    continue
                if tx_id:
                    seen.add(tx_id)

                roster_ids = tx.get("roster_ids") or []
                adds = tx.get("adds") if isinstance(tx.get("adds"), dict) else {}
                drops = tx.get("drops") if isinstance(tx.get("drops"), dict) else {}
                draft_picks = tx.get("draft_picks") or []

                team_got: dict[Any, list[str]] = {}
                team_gave: dict[Any, list[str]] = {}

                # adds/drops keyed by sleeper player_id → roster_id.
                for pid, rid in (adds or {}).items():
                    label = id_map.get(str(pid)) or str(pid)
                    _append_trade_side_item(team_got, rid, str(label))
                for pid, rid in (drops or {}).items():
                    label = id_map.get(str(pid)) or str(pid)
                    _append_trade_side_item(team_gave, rid, str(label))

                # Draft picks: owner gained, previous_owner lost.
                for pick in draft_picks:
                    if not isinstance(pick, dict):
                        continue
                    owner = pick.get("owner_id")
                    prev = pick.get("previous_owner_id")
                    label = _format_trade_pick_label(
                        pick, rid_to_name, draft_slot_by_origin,
                    )
                    if owner is not None:
                        _append_trade_side_item(team_got, owner, label)
                    if prev is not None:
                        _append_trade_side_item(team_gave, prev, label)

                sides: list[dict[str, Any]] = []
                for rid in roster_ids:
                    rid_key = rid if rid in rid_to_name else _safe_int(rid)
                    team_name = (
                        rid_to_name.get(rid_key)
                        or rid_to_name.get(str(rid))
                        or f"Team {rid}"
                    )
                    owner_id = (
                        rid_to_owner.get(rid)
                        or rid_to_owner.get(_safe_int(rid))
                        or rid_to_owner.get(str(rid))
                        or ""
                    )
                    sides.append({
                        "team": team_name,
                        "rosterId": rid,
                        "ownerId": owner_id,
                        "got": team_got.get(rid, []) or team_got.get(_safe_int(rid), []),
                        "gave": team_gave.get(rid, []) or team_gave.get(_safe_int(rid), []),
                    })

                if sides:
                    trades.append({
                        "leagueId": str(lid),
                        "week": week,
                        "timestamp": ts_ms or 0,
                        "sides": sides,
                    })

    # Newest first — /trades UI sorts by recency.
    trades.sort(key=lambda t: -int(t.get("timestamp", 0) or 0))
    return trades


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
    trades = _build_trades_block(
        sleeper_league_id,
        window_days=trade_window_days,
        id_to_player=id_to_player,
    )

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
