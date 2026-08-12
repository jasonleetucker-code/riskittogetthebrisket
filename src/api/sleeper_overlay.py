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
from collections.abc import Mapping
from typing import Any

from src.utils.name_clean import strip_display_suffix
from src.utils.owner_names import owner_label

log = logging.getLogger(__name__)

_CACHE: dict[str, dict[str, Any]] = {}
_CACHE_LOCK = threading.Lock()
_CACHE_TTL_SEC = 15 * 60
# Stale-serve ceiling: an expired-but-present overlay is served
# immediately (with a background refresh kicked off) up to this age.
# Past it, the request blocks on a single-flighted rebuild.  Sign-off:
# rosters/trades may briefly render up to 30 min old instead of 15 —
# a freshness-window widening on an already-15-min-stale live overlay,
# never a computation change.  Rankings/values are unaffected (they
# come from the scrape pipeline, not this overlay).
_STALE_SERVE_MAX_SEC = 2 * _CACHE_TTL_SEC
# Per-league build locks: a cold overlay build is ~50-100 Sleeper
# round-trips, and before these locks concurrent expirees each
# launched their own storm.  Exactly one builder per league now runs
# at a time; the rest wait and read its result.
_BUILD_LOCKS: dict[str, threading.Lock] = {}
# League ids with a background refresh in flight (stale-serve path) so
# repeat stale hits don't stack refresh threads.
_REFRESHING: set[str] = set()
_HTTP_TIMEOUT_SEC = 8.0
_USER_AGENT = "brisket-sleeper-overlay/1.0"

# Teams-only fast-path cache (see ``fetch_sleeper_teams_overlay``).
# Separate from the full-overlay cache so a cold full overlay never
# forces the FAAB recommend path to pay the trades+waivers history
# cost; short TTL because FAAB balances move on waiver runs.
_TEAMS_CACHE: dict[str, dict[str, Any]] = {}
_TEAMS_CACHE_TTL_SEC = 5 * 60

# Live-draft caches.  These are deliberately separate from the overlay
# cache so a 2-3s polling loop on /api/sleeper/draft/picks never poisons
# the 15-minute team/trade overlay cache and vice versa.
#
# ``_DRAFT_ID_CACHE`` keys on the *Sleeper league id* (not draft id),
# since draft-id discovery is the first step of every live poll.
#   key: sleeper_league_id (str)
#   value: {"draft_id": str | None, "_cached_at": float}
#
# ``_DRAFT_PICKS_CACHE`` keys on the *draft id* and stores the most
# recent full picks list.  A 2s TTL keeps the auctioneer's tab from
# DDoSing Sleeper while still feeling instantaneous to the user.
_DRAFT_ID_CACHE: dict[str, dict[str, Any]] = {}
_DRAFT_ID_CACHE_TTL_SEC = 60.0
_DRAFT_PICKS_CACHE: dict[str, dict[str, Any]] = {}
_DRAFT_PICKS_CACHE_TTL_SEC = 2.0

# Lazy fallback Sleeper-ID → display-name map.  The primary id→name
# source is the loaded contract's NFL map, which only spans players in
# the rankings pool.  Deep-bench / unranked / retired players (and team
# defenses) that show up in trade, roster or waiver history miss that
# map and would otherwise render as a raw numeric Sleeper id on the UI.
# This is populated from Sleeper's full ``/v1/players/nfl`` dump
# (~5 MB) the first time a miss is hit, then process-cached.  Failed
# attempts are not cached permanently — they are retried (rate-limited)
# so a transient Sleeper blip doesn't disable the fallback for the
# life of the process.
_FALLBACK_NAMES: dict[str, str] | None = None
_FALLBACK_NAMES_LOCK = threading.Lock()
_FALLBACK_ATTEMPT_AT: float = 0.0
_FALLBACK_RETRY_SEC = 300.0


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
            failure_threshold=5,
            failure_window_sec=60.0,
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


class _BuildFetcher:
    """Build-scoped URL memo + parallel prefetch for one overlay build.

    A single overlay build touches several Sleeper URLs more than once:
    the league-chain walk runs for both the trades AND waivers builders,
    rosters/users are fetched by the teams block and again by the
    per-league rid lookup, and — the big one — the 19 weekly
    ``/transactions/{week}`` feeds are iterated by BOTH builders (they
    read the same feed with different type filters).  Memoizing by URL
    within one build halves the round-trips with zero freshness change,
    because every duplicate was previously fetched milliseconds apart
    anyway.

    ``prefetch`` issues a set of URLs concurrently (bounded pool) so
    the serial per-week walk turns into one parallel round-trip wave.

    Resolves ``_http_get_json`` late (module-global lookup at call
    time) so tests that monkeypatch it keep working — including
    through the prefetch pool's worker threads.
    """

    def __init__(self) -> None:
        self._results: dict[str, Any] = {}
        self._lock = threading.Lock()

    def get(self, url: str) -> Any:
        with self._lock:
            if url in self._results:
                return self._results[url]
        val = _http_get_json(url)
        with self._lock:
            return self._results.setdefault(url, val)

    def prefetch(self, urls: list[str], max_workers: int = 8) -> None:
        from concurrent.futures import ThreadPoolExecutor

        with self._lock:
            pending = list(dict.fromkeys(u for u in urls if u not in self._results))
        if not pending:
            return
        with ThreadPoolExecutor(
            max_workers=max_workers, thread_name_prefix="sleeper-prefetch"
        ) as ex:
            list(ex.map(self.get, pending))


def _walk_league_chain(root_league_id: str, max_depth: int = 2, getter=None) -> list[str]:
    """Walk backwards through previous_league_id so trade history
    covers multiple seasons when the ``/transactions`` endpoint
    only returns current-season trades.  Mirrors the scraper's
    ``_league_chain_ids`` helper (Dynasty Scraper.py ~line 1109)
    but capped at 2 levels to keep the overlay fetch fast.
    """
    fetch = getter or _http_get_json
    out: list[str] = []
    seen: set[str] = set()
    cur = str(root_league_id or "").strip()
    while cur and cur not in seen and len(out) < max_depth:
        seen.add(cur)
        out.append(cur)
        info = fetch(f"https://api.sleeper.app/v1/league/{cur}")
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
    getter=None,
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

    traded = (getter or _http_get_json)(
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
        per_roster.setdefault(current_owner, []).append(
            {
                "season": season,
                "round": rnd,
                "slot": None,
                "original_roster_id": original,
                "owner_roster_id": current_owner,
                "label": _format_pick_label(season, rnd),
            }
        )
    # Sort each team's picks year-then-round for deterministic output.
    for rid, plist in per_roster.items():
        plist.sort(key=lambda p: (p.get("season", ""), p.get("round", 0)))
    return per_roster


def _build_teams_block(
    sleeper_league_id: str,
    id_to_player: dict[str, str] | None,
    getter=None,
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
    fetch = getter or _http_get_json
    rosters = fetch(f"https://api.sleeper.app/v1/league/{sleeper_league_id}/rosters")
    users = fetch(f"https://api.sleeper.app/v1/league/{sleeper_league_id}/users")
    if not isinstance(rosters, list) or not isinstance(users, list):
        return None

    # League-level settings carry the season's waiver budget; merge
    # with each roster's ``waiver_budget_used`` to produce remaining
    # FAAB.  When the league call fails (rare) we still emit the
    # block — faabRemaining just falls back to None and the
    # frontend renders "—" instead of a number.
    league_info = fetch(f"https://api.sleeper.app/v1/league/{sleeper_league_id}")
    league_settings = league_info.get("settings") if isinstance(league_info, dict) else None
    league_faab_budget = None
    if isinstance(league_settings, dict):
        try:
            league_faab_budget = int(league_settings.get("waiver_budget"))
        except (TypeError, ValueError):
            league_faab_budget = None

    # owner_id → team-display-name.  Routes Sleeper username →
    # owner first name via ``config/leagues/owner_names.json`` so the
    # UI shows "Jason", not "JasonLeeTucker".  Sleeper usernames win
    # over league-set ``team_name`` because the mapping is meant to
    # surface the human, not the franchise label.
    user_map: dict[str, str] = {}
    # owner_id → the PRE-rename label (Sleeper league ``team_name``,
    # else ``display_name``).  Not displayed anywhere — it exists so
    # ``useTeam`` can still resolve a legacy name-only stored
    # selection (``settings.selectedTeam`` with no ownerId) after the
    # displayed ``name`` flipped to the owner first name.  Without it
    # those users' saved team silently fails to restore until they
    # re-pick (Codex PR #437 P2).
    legacy_name_map: dict[str, str] = {}
    for u in users:
        if not isinstance(u, dict):
            continue
        uid = str(u.get("user_id") or "")
        if not uid:
            continue
        label = owner_label(u) or f"Team {uid}"
        user_map[uid] = label
        legacy_name_map[uid] = str(
            (u.get("metadata") or {}).get("team_name") or u.get("display_name") or f"Team {uid}"
        )

    id_map = id_to_player or {}
    roster_ids: list[int] = []
    for r in rosters:
        if isinstance(r, dict) and r.get("roster_id") is not None:
            try:
                roster_ids.append(int(r["roster_id"]))
            except (TypeError, ValueError):
                continue
    pick_ownership = _build_pick_ownership(sleeper_league_id, roster_ids, getter=getter)

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
            names.append(_resolve_player_label(pid_str, id_map))
        try:
            rid_int = int(roster_id) if roster_id is not None else 0
        except (TypeError, ValueError):
            rid_int = 0
        pick_details = pick_ownership.get(rid_int, [])
        pick_labels = [p["label"] for p in pick_details]

        # FAAB used lives at ``roster.settings.waiver_budget_used``
        # and is reset every season by Sleeper.  Combined with the
        # league-level budget we derived above, that gives us
        # ``remaining`` for the FAAB recommender.  When either
        # piece is missing we surface explicit ``None`` so the
        # frontend can distinguish "not loaded yet" from "0 left".
        roster_settings = r.get("settings")
        faab_used: int | None = None
        if isinstance(roster_settings, dict):
            try:
                faab_used = int(roster_settings.get("waiver_budget_used"))
            except (TypeError, ValueError):
                faab_used = None
        faab_remaining: int | None = None
        if league_faab_budget is not None and faab_used is not None:
            faab_remaining = max(0, league_faab_budget - faab_used)

        teams.append(
            {
                "name": user_map.get(owner_id, f"Team {roster_id}"),
                # Backward-compat only — never rendered.  See legacy_name_map.
                "sleeperTeamName": legacy_name_map.get(owner_id, f"Team {roster_id}"),
                "ownerId": owner_id,
                "roster_id": roster_id,
                "players": names,
                "playerIds": [str(pid) for pid in player_ids if pid],
                "picks": pick_labels,
                "pickDetails": pick_details,
                "faabBudget": league_faab_budget,
                "faabUsed": faab_used,
                "faabRemaining": faab_remaining,
            }
        )
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
    getter=None,
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
    fetch = getter or _http_get_json
    rid_to_name: dict[Any, str] = {}
    rid_to_owner: dict[Any, str] = {}
    rosters = fetch(f"https://api.sleeper.app/v1/league/{target_league_id}/rosters")
    users = fetch(f"https://api.sleeper.app/v1/league/{target_league_id}/users")
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
            name = (metadata or {}).get("team_name") or u.get("display_name") or f"Team {uid}"
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
    rosters: list[dict[str, Any]] | None = None,
    getter=None,
) -> dict[tuple[int, int], int]:
    """Build ``{(season, origin_roster_id): slot}`` for trade-history
    pick labels.

    Sleeper's ``/v1/league/{id}/drafts`` (LIST) endpoint returns each
    draft's metadata but ``slot_to_roster_id`` is frequently empty
    there (the slot map only lands on the per-draft DETAIL endpoint
    once the league commish has set the draft order).  We fetch the
    DETAIL endpoint for every draft in pick years and read both
    ``slot_to_roster_id`` AND ``draft_order`` (the user_id → slot
    map for leagues that authored their order before the slot map
    was committed).

    For ``draft_order`` we need user_id → roster_id, which we derive
    from the roster list's ``owner_id`` field.

    Mirrors the offline scraper's draft enumeration (Dynasty
    Scraper.py ~870-915) so the overlay-fresh and baked pick labels
    converge on the same slot data.  Returns an empty map on any
    fetch failure — callers fall back to round-suffix labels which
    still resolve through ``buildPickLookupCandidates`` on the
    frontend, just less precisely.
    """
    fetch = getter or _http_get_json
    out: dict[tuple[int, int], int] = {}
    drafts = fetch(f"https://api.sleeper.app/v1/league/{target_league_id}/drafts")
    if not isinstance(drafts, list):
        return out

    # owner_id → roster_id, derived from the roster list (passed in
    # by the trade builder so we don't refetch).  Fall back to a
    # fresh fetch when the caller didn't pass rosters.
    owner_to_rid: dict[str, int] = {}
    rs = rosters
    if rs is None:
        rs_resp = fetch(f"https://api.sleeper.app/v1/league/{target_league_id}/rosters")
        rs = rs_resp if isinstance(rs_resp, list) else []
    for r in rs or []:
        if not isinstance(r, dict):
            continue
        oid = str(r.get("owner_id") or "").strip()
        rid_int = _safe_int(r.get("roster_id"))
        if oid and rid_int is not None:
            owner_to_rid[oid] = rid_int

    for d in drafts:
        if not isinstance(d, dict):
            continue
        season = _safe_int(d.get("season"))
        draft_id = str(d.get("draft_id") or "").strip()
        if season is None or not draft_id:
            continue

        # Try the DETAIL endpoint first (slot_to_roster_id usually
        # lands here even when the LIST endpoint's copy is empty).
        detail = fetch(f"https://api.sleeper.app/v1/draft/{draft_id}")
        detail_dict = detail if isinstance(detail, dict) else {}

        # draft_order: { user_id: slot } — needs owner_id → roster_id.
        draft_order = detail_dict.get("draft_order") or d.get("draft_order") or {}
        if isinstance(draft_order, dict):
            for uid, slot in draft_order.items():
                slot_num = _safe_int(slot)
                rid = owner_to_rid.get(str(uid))
                if isinstance(rid, int) and isinstance(slot_num, int) and slot_num > 0:
                    out[(season, rid)] = slot_num

        # slot_to_roster_id: { slot: roster_id } — direct map.
        slot_to_rid = detail_dict.get("slot_to_roster_id") or d.get("slot_to_roster_id") or {}
        if isinstance(slot_to_rid, dict):
            for slot, rid_val in slot_to_rid.items():
                slot_num = _safe_int(slot)
                rid_num = _safe_int(rid_val)
                if isinstance(slot_num, int) and slot_num > 0 and isinstance(rid_num, int):
                    out[(season, rid_num)] = slot_num

    return out


def _slot_to_tier_label(slot: Any, league_size: int = 12) -> str:
    """Bucket a draft slot into Early / Mid / Late thirds.  Mirrors
    the offline scraper's ``_slot_to_tier_label``.  Used for FUTURE-
    year picks where slot exists but the rankings board only carries
    tier-bucketed pick rows (e.g. ``"2027 Early 1st"`` not
    ``"2027 1.03"`` — the rookie crop-by-slot view is reserved for
    the upcoming year).
    """
    n = _safe_int(slot)
    if not isinstance(n, int) or n <= 0:
        return "Mid"
    size = max(3, int(league_size or 12))
    per_tier = max(1, size // 3)
    if n <= per_tier:
        return "Early"
    if n <= min(size, per_tier * 2):
        return "Mid"
    return "Late"


def _format_trade_pick_label(
    pick: dict[str, Any],
    rid_to_name: dict[Any, str],
    draft_slot_by_origin: dict[tuple[int, int], int],
    *,
    current_year: int | None = None,
    league_size: int = 12,
) -> str:
    """Canonical pick label for trade-history valuation.  Matches the
    offline scraper's ``_format_trade_pick_label`` so the resulting
    string resolves through the same frontend ``resolvePickRow``
    pipeline as the baked trades.

    Format precedence (in order, first applicable wins):
      1. ``YYYY R.SS (from Team)`` — current-year picks with known
         slot.  ``rankDerivedValue`` rows are stamped at the slot
         level so a slot-specific label is the strongest match.
      2. ``YYYY {Tier} R{th} (from Team)`` — future-year picks (next
         season +).  The rankings board only carries tier-bucketed
         pick rows for years past the upcoming draft, so a slot-
         specific label would miss the row entirely.  Slot still
         drives the tier (Early/Mid/Late) when known; default Mid.
      3. ``YYYY R{th} (from Team)`` — slot unknown for current year
         (no draft order set yet).  Falls through to the frontend's
         ``buildPickLookupCandidates`` tier-derivation logic which
         resolves to the tier-centre slot.
      4. ``YYYY Round R (from Team)`` — final fallback if season /
         round failed to coerce to ints.
    """
    if current_year is None:
        import datetime as _dt

        current_year = _dt.datetime.now(_dt.timezone.utc).year

    season = _safe_int(pick.get("season"))
    round_num = _safe_int(pick.get("round"))
    origin_rid = _safe_int(pick.get("roster_id") or pick.get("origin_roster_id"))

    from_team: str | None = None
    if origin_rid is not None:
        from_team = (
            rid_to_name.get(origin_rid) or rid_to_name.get(str(origin_rid)) or f"Team {origin_rid}"
        )

    base_label: str | None = None
    if season is not None and round_num is not None and round_num > 0:
        slot = draft_slot_by_origin.get((season, origin_rid)) if origin_rid is not None else None
        if season >= current_year + 1:
            # Future year — tier label, slot-aware when known.
            # ``_round_suffix(1) = "1st"`` already includes the digit
            # so we don't prepend ``round_num`` separately here (the
            # offline scraper's ``_round_suffix`` returns only the
            # suffix and prepends — same output, different code split).
            tier_label = _slot_to_tier_label(slot, league_size=league_size)
            base_label = f"{season} {tier_label} {_round_suffix(round_num)}"
        elif isinstance(slot, int) and slot > 0:
            # Current year (or past) with known slot — slot-specific.
            base_label = f"{season} {round_num}.{str(slot).zfill(2)}"
        else:
            # Current year, slot unknown — round-suffix fallback.
            base_label = f"{season} {_round_suffix(round_num)}"

    if not base_label:
        season_txt = str(pick.get("season", "")).strip()
        round_txt = str(pick.get("round", "?")).strip()
        base_label = f"{season_txt} Round {round_txt}".strip()

    return f"{base_label} (from {from_team})" if from_team else base_label


def _append_trade_side_item(
    side_map: dict[Any, list[str]],
    rid: Any,
    label: str,
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


def _sleeper_fallback_name_map() -> dict[str, str]:
    """Process-cached Sleeper ``player_id`` → ``"First Last"`` map,
    built lazily from the full ``/v1/players/nfl`` dump.

    Consulted ONLY when the loaded contract's NFL id map misses an id
    (so the steady-state hot path never pays for it).  Best-effort:
    returns ``{}`` on any failure so callers degrade to the prior
    raw-id behaviour.  Goes through the module's own ``_http_get_json``
    so it shares the ``sleeper_api`` circuit breaker and stays
    monkeypatchable in tests.
    """
    global _FALLBACK_NAMES, _FALLBACK_ATTEMPT_AT
    if _FALLBACK_NAMES is not None:
        return _FALLBACK_NAMES
    with _FALLBACK_NAMES_LOCK:
        if _FALLBACK_NAMES is not None:
            return _FALLBACK_NAMES
        now = time.time()
        if now - _FALLBACK_ATTEMPT_AT < _FALLBACK_RETRY_SEC:
            # Recent attempt failed — don't hammer Sleeper.  Degrade to
            # raw-id until the retry window elapses.
            return {}
        _FALLBACK_ATTEMPT_AT = now
        dump = _http_get_json("https://api.sleeper.app/v1/players/nfl")
        if not isinstance(dump, dict) or not dump:
            return {}
        out: dict[str, str] = {}
        for pid, rec in dump.items():
            if not isinstance(rec, dict):
                continue
            full = str(rec.get("full_name") or "").strip()
            if not full:
                first = str(rec.get("first_name") or "").strip()
                last = str(rec.get("last_name") or "").strip()
                full = f"{first} {last}".strip()
            if not full and str(rec.get("position") or "") == "DEF":
                # Team defenses key on the team abbr and carry no name
                # fields — synthesise a readable "<ABBR> DEF" label.
                full = f"{str(pid).upper()} DEF"
            if full:
                out[str(pid)] = full
        if not out:
            # Non-empty payload but zero usable records (schema drift /
            # missing name fields).  Treat as a retry-eligible soft
            # failure — do NOT persist {} or every later miss leaks the
            # raw id for the process lifetime.  ``_FALLBACK_ATTEMPT_AT``
            # was stamped above so the retry stays rate-limited.
            return {}
        _FALLBACK_NAMES = out
        return _FALLBACK_NAMES


def _resolve_player_label(pid: Any, id_map: dict[str, str]) -> str:
    """Resolve a Sleeper player id to a display name.

    Resolution order: loaded-contract NFL map → full Sleeper players
    dump (lazy, process-cached) → the raw id string as a last resort
    so the row still renders rather than vanishing.

    VOCABULARY (audit N3, 2026-07-29).  The first branch returns a name
    from the contract, which is already in the contract's vocabulary.
    The Sleeper-dump fallback is NOT: Sleeper's ``full_name`` keeps
    generational suffixes, and the contract's names — produced by
    ``Dynasty Scraper.py::clean_name`` — do not (measured: **0 of 1076**
    contract keys carry one).  Emitting a raw Sleeper name here leaks a
    foreign vocabulary into ``sleeper.teams[].players``, which is
    name-keyed and read by waiver ownership, angle, replacement and FAAB
    contention — so a player who takes this branch silently fails to
    join in all of them.

    ``strip_display_suffix`` puts the fallback into the same vocabulary
    while preserving case, because this value is displayed.  It is a
    display cleanup, NOT one of this repo's lowercased join keys.

    Live exposure when this was written was small — 1 of 666 rostered
    ids missed the contract map, and that id had no contract row, so
    nothing was hidden yet.  It is fixed because the branch is reachable
    by construction, not because it was actively breaking a join.
    """
    pid_str = str(pid if pid is not None else "").strip()
    if not pid_str:
        return ""
    mapped = id_map.get(pid_str)
    if mapped:
        return str(mapped)
    fallback = _sleeper_fallback_name_map().get(pid_str)
    if fallback:
        return strip_display_suffix(fallback) or fallback
    return pid_str


def _build_waivers_block(
    sleeper_league_id: str,
    window_days: int = 365,
    id_to_player: dict[str, str] | None = None,
    getter=None,
) -> list[dict[str, Any]]:
    """Sister to ``_build_trades_block`` — collects ``waiver`` and
    ``free_agent`` transactions across the league chain (same depth-2
    walk so inter-season activity stays in the rolling window).

    Output shape (one dict per completed waiver/FA tx)::

        {
            "leagueId":     str,
            "week":         int,
            "createdAtMs":  int,        # status_updated, falls back to created
            "rosterId":     int,
            "ownerId":      str,
            "added":        [<player display name>, ...],
            "dropped":      [<player display name>, ...],
            "faabBid":      int,        # winning waiver_bid (0 for FA)
            "type":         "waiver" | "free_agent",
            "transactionId": str,
        }

    Sleeper's ``/v1/league/<id>/transactions/<week>`` is the same
    feed used by trades; we just toggle the type filter.  Failed
    waiver bids are NOT exposed by the API — only successful claims
    appear, which is a known limitation we surface in the FAAB
    recommender's UI copy (B6 / B8).

    ``id_to_player`` is the NFL-wide Sleeper-ID → display-name map,
    typically reused from the loaded contract.  When absent, player
    labels fall back to the raw Sleeper id.
    """
    fetch = getter or _http_get_json
    cutoff_ms = _utc_now_ms() - int(window_days) * 24 * 3600 * 1000
    chain = _walk_league_chain(sleeper_league_id, max_depth=2, getter=getter)
    if not chain:
        return []

    id_map = id_to_player if isinstance(id_to_player, dict) else {}

    out: list[dict[str, Any]] = []
    seen: set[str] = set()

    for lid in chain:
        rid_to_name, rid_to_owner = _league_rid_lookup(lid, getter=getter)

        for week in range(0, 19):
            url = f"https://api.sleeper.app/v1/league/{lid}/transactions/{week}"
            txs = fetch(url)
            if not isinstance(txs, list):
                continue
            for tx in txs:
                if not isinstance(tx, dict):
                    continue
                tx_type = tx.get("type")
                if tx_type not in ("waiver", "free_agent"):
                    continue
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

                # Sleeper's waiver / FA shape:
                #   adds:   {player_id: roster_id}
                #   drops:  {player_id: roster_id}  (optional)
                # The owning roster is the same across ``adds`` and
                # ``drops`` — pull it from ``roster_ids`` (single
                # entry for these tx types).
                adds = tx.get("adds") if isinstance(tx.get("adds"), dict) else {}
                drops = tx.get("drops") if isinstance(tx.get("drops"), dict) else {}
                roster_ids = tx.get("roster_ids") or []
                rid = roster_ids[0] if roster_ids else None
                if rid is None:
                    # Some FA transactions encode the roster on the
                    # adds map only — pull the first value as a
                    # fallback.
                    if adds:
                        rid = next(iter(adds.values()), None)
                if rid is None:
                    continue

                added_names = [_resolve_player_label(pid, id_map) for pid in adds.keys()]
                dropped_names = [_resolve_player_label(pid, id_map) for pid in drops.keys()]

                # FAAB bid lives at ``settings.waiver_bid`` for waiver
                # tx; FA tx don't carry a bid (free pickups).
                settings = tx.get("settings") or {}
                bid_raw = settings.get("waiver_bid") if isinstance(settings, dict) else None
                try:
                    bid = int(bid_raw) if bid_raw is not None else 0
                except (TypeError, ValueError):
                    bid = 0

                rid_key = rid if rid in rid_to_name else _safe_int(rid)
                owner_id = (
                    rid_to_owner.get(rid)
                    or rid_to_owner.get(_safe_int(rid))
                    or rid_to_owner.get(str(rid))
                    or ""
                )

                out.append(
                    {
                        "leagueId": str(lid),
                        "week": week,
                        "createdAtMs": ts_ms or 0,
                        "rosterId": rid,
                        "ownerId": owner_id,
                        "added": added_names,
                        "dropped": dropped_names,
                        "faabBid": bid,
                        "type": str(tx_type),
                        "transactionId": tx_id,
                    }
                )

                # rid_key + rid_to_name unused below but kept for
                # potential team-name annotation in a downstream
                # consumer; the frontend maps via ownerId today.
                _ = rid_key

    out.sort(key=lambda w: -int(w.get("createdAtMs", 0) or 0))
    return out


def _build_trades_block(
    sleeper_league_id: str,
    window_days: int = 365,
    id_to_player: dict[str, str] | None = None,
    getter=None,
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
    import datetime as _dt

    fetch = getter or _http_get_json
    cutoff_ms = _utc_now_ms() - int(window_days) * 24 * 3600 * 1000
    chain = _walk_league_chain(sleeper_league_id, max_depth=2, getter=getter)
    if not chain:
        return []

    id_map = id_to_player if isinstance(id_to_player, dict) else {}
    current_year = _dt.datetime.now(_dt.timezone.utc).year

    trades: list[dict[str, Any]] = []
    seen: set[str] = set()

    for lid in chain:
        # Per-league lookups: roster-id → team name, → owner_id,
        # league size for tier bucketing, and the season-rooted
        # draft-slot map.  Each league chain entry has its own
        # roster identity (a roster_id can change human ownership
        # across seasons).  The rosters fetch is reused by the
        # draft-slot lookup so we don't pay the round-trip twice.
        rosters_resp = fetch(f"https://api.sleeper.app/v1/league/{lid}/rosters")
        rosters_list = rosters_resp if isinstance(rosters_resp, list) else []
        rid_to_name, rid_to_owner = _league_rid_lookup(lid, getter=getter)
        draft_slot_by_origin = _league_draft_slot_lookup(
            lid,
            rosters=rosters_list,
            getter=getter,
        )
        # League size drives Early/Mid/Late tier bucketing for
        # future-year picks.  Default to 12-team when the rosters
        # list is empty (any reasonable size between 8 and 14
        # produces the same tier breakpoints for our 1st/2nd/3rd-
        # round labels).
        league_size = max(3, len(rosters_list) or 12)

        # Weeks 0..18 cover preseason/regular/postseason transaction
        # calendar.  0 is cheap to include and catches preseason
        # trades that happened before week 1.
        for week in range(0, 19):
            url = f"https://api.sleeper.app/v1/league/{lid}/transactions/{week}"
            txs = fetch(url)
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
                    _append_trade_side_item(team_got, rid, _resolve_player_label(pid, id_map))
                for pid, rid in (drops or {}).items():
                    _append_trade_side_item(team_gave, rid, _resolve_player_label(pid, id_map))

                # Draft picks: owner gained, previous_owner lost.
                for pick in draft_picks:
                    if not isinstance(pick, dict):
                        continue
                    owner = pick.get("owner_id")
                    prev = pick.get("previous_owner_id")
                    label = _format_trade_pick_label(
                        pick,
                        rid_to_name,
                        draft_slot_by_origin,
                        current_year=current_year,
                        league_size=league_size,
                    )
                    if owner is not None:
                        _append_trade_side_item(team_got, owner, label)
                    if prev is not None:
                        _append_trade_side_item(team_gave, prev, label)

                sides: list[dict[str, Any]] = []
                for rid in roster_ids:
                    rid_key = rid if rid in rid_to_name else _safe_int(rid)
                    team_name = (
                        rid_to_name.get(rid_key) or rid_to_name.get(str(rid)) or f"Team {rid}"
                    )
                    owner_id = (
                        rid_to_owner.get(rid)
                        or rid_to_owner.get(_safe_int(rid))
                        or rid_to_owner.get(str(rid))
                        or ""
                    )
                    sides.append(
                        {
                            "team": team_name,
                            "rosterId": rid,
                            "ownerId": owner_id,
                            "got": team_got.get(rid, []) or team_got.get(_safe_int(rid), []),
                            "gave": team_gave.get(rid, []) or team_gave.get(_safe_int(rid), []),
                        }
                    )

                if sides:
                    trades.append(
                        {
                            "leagueId": str(lid),
                            "week": week,
                            "timestamp": ts_ms or 0,
                            "sides": sides,
                        }
                    )

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


def _fetch_league_name(sleeper_league_id: str, getter=None) -> str | None:
    info = (getter or _http_get_json)(f"https://api.sleeper.app/v1/league/{sleeper_league_id}")
    if not isinstance(info, dict):
        return None
    name = info.get("name")
    return str(name) if name else None


#: Fields of a Sleeper block that belong to ONE league and may never be
#: inherited from another (W18-F002).  The NFL-wide maps — ``positions``,
#: ``playerIds``, ``idToPlayer`` — are deliberately not here: they map
#: player ids to names for the whole league universe and are genuinely
#: league-independent.
LEAGUE_SPECIFIC_SLEEPER_FIELDS: tuple[str, ...] = (
    "scoringSettings",
    "rosterPositions",
    "leagueSettings",
)
NFL_WIDE_SLEEPER_FIELDS: tuple[str, ...] = ("positions", "playerIds", "idToPlayer")


def _fetch_league_config(sleeper_league_id: str, getter=None) -> dict[str, Any] | None:
    """The requested league's OWN scoring/roster/settings block.

    Same league object ``_fetch_league_name`` already reads (memoized per
    build), so this costs no extra round-trip.  Returns ``None`` when the
    fetch fails or the object carries no scoring card — the caller must
    then publish an explicitly NOT-ready block rather than inheriting
    another league's configuration.
    """
    info = (getter or _http_get_json)(f"https://api.sleeper.app/v1/league/{sleeper_league_id}")
    if not isinstance(info, dict):
        return None
    scoring = info.get("scoring_settings")
    if not isinstance(scoring, dict) or not scoring:
        return None
    return {
        "scoringSettings": dict(scoring),
        "rosterPositions": list(info.get("roster_positions") or []),
        "leagueSettings": dict(info.get("settings") or {}),
    }


def merge_cross_league_sleeper_block(
    *,
    loaded_sleeper: Mapping[str, Any] | None,
    overlay: Mapping[str, Any] | None,
    requested_league_config: Mapping[str, Any] | None,
) -> tuple[dict[str, Any], bool]:
    """Build the Sleeper block for a league OTHER than the loaded one.

    Returns ``(block, ready)`` where ``ready`` is the value
    ``meta.sleeperDataReady`` may take.  The invariant:

        ready is true IFF every league-specific field represented as
        ready belongs to the REQUESTED league.

    Before this existed the merge was inline in a request handler and
    carried ``scoringSettings`` / ``rosterPositions`` / ``leagueSettings``
    forward from the loaded league, laid the requested league's teams on
    top, and stamped ready unconditionally — League B's rosters welded to
    League A's scoring card and team count, published as though it were
    League B's own data.  ``useTeam.js`` reads that flag, so the
    data-not-ready state written precisely for this case never rendered.

    Without the requested league's own configuration the fields are left
    ABSENT rather than inherited.  Absent is a state the frontend can
    detect; a plausible wrong value is not.
    """
    loaded = dict(loaded_sleeper or {})
    over = dict(overlay or {})
    block: dict[str, Any] = {k: loaded[k] for k in NFL_WIDE_SLEEPER_FIELDS if k in loaded}
    # The overlay is the requested league's own data and wins outright.
    block.update(over)
    # Never let an overlay carry a league-specific field implicitly; the
    # only source for those is the requested league's config below.
    for field in LEAGUE_SPECIFIC_SLEEPER_FIELDS:
        block.pop(field, None)
    # ``leagueConfig`` is how the overlay TRANSPORTS that config; it is
    # not a contract field, and echoing it would ship a second copy of
    # the scoring card in every cross-league payload.
    config_from_overlay = block.pop("leagueConfig", None)
    if requested_league_config is None:
        requested_league_config = config_from_overlay

    config = requested_league_config if isinstance(requested_league_config, Mapping) else None
    if not config or not config.get("scoringSettings"):
        return block, False
    for field in LEAGUE_SPECIFIC_SLEEPER_FIELDS:
        if field in config:
            block[field] = config[field]
    return block, True


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

    Caching (documented for the perf audit):
      * key: ``sleeper_league_id``.
      * fresh TTL: 15 min (``_CACHE_TTL_SEC``) — unchanged.
      * stale-serve window: 15-30 min (``_STALE_SERVE_MAX_SEC``).  An
        expired entry is served immediately and exactly ONE daemon
        thread refreshes it in the background (``_REFRESHING`` guard),
        so no user request ever blocks on the ~50-100-call rebuild
        while a usable overlay exists.
      * single-flight: the blocking build path (cold cache, or stale
        beyond 30 min) holds a per-league lock, so concurrent misses
        coalesce onto one upstream storm instead of N.
      * invalidation: ``force_refresh=True`` (tests + the background
        refresher) rebuilds unconditionally;
        ``invalidate_overlay_cache`` drops entries.
    """
    sleeper_league_id = str(sleeper_league_id or "").strip()
    if not sleeper_league_id:
        return None

    if not force_refresh:
        now = time.time()
        with _CACHE_LOCK:
            cached = _CACHE.get(sleeper_league_id)
        if cached:
            age = now - float(cached.get("_cached_at") or 0)
            if age < _CACHE_TTL_SEC:
                return dict(cached["payload"])
            if age < _STALE_SERVE_MAX_SEC:
                _kick_overlay_background_refresh(
                    sleeper_league_id,
                    id_to_player=id_to_player,
                    trade_window_days=trade_window_days,
                )
                return dict(cached["payload"])

    lock = _overlay_build_lock(sleeper_league_id)
    with lock:
        # Re-check under the lock: another thread may have completed
        # the build while we waited.
        if not force_refresh:
            with _CACHE_LOCK:
                cached = _CACHE.get(sleeper_league_id)
            if cached and (time.time() - float(cached.get("_cached_at") or 0)) < _CACHE_TTL_SEC:
                return dict(cached["payload"])
        return _build_overlay_and_cache(
            sleeper_league_id,
            id_to_player=id_to_player,
            trade_window_days=trade_window_days,
        )


def _overlay_build_lock(sleeper_league_id: str) -> threading.Lock:
    with _CACHE_LOCK:
        lock = _BUILD_LOCKS.get(sleeper_league_id)
        if lock is None:
            lock = threading.Lock()
            _BUILD_LOCKS[sleeper_league_id] = lock
        return lock


def _kick_overlay_background_refresh(
    sleeper_league_id: str,
    *,
    id_to_player: dict[str, str] | None,
    trade_window_days: int,
) -> None:
    """Start (at most) one daemon refresh for a stale-served league."""
    with _CACHE_LOCK:
        if sleeper_league_id in _REFRESHING:
            return
        _REFRESHING.add(sleeper_league_id)

    def _run() -> None:
        try:
            fetch_sleeper_overlay(
                sleeper_league_id=sleeper_league_id,
                id_to_player=id_to_player,
                trade_window_days=trade_window_days,
                force_refresh=True,
            )
        except Exception as exc:  # noqa: BLE001 — background best-effort
            log.warning("overlay background refresh failed for %s: %s", sleeper_league_id, exc)
        finally:
            with _CACHE_LOCK:
                _REFRESHING.discard(sleeper_league_id)

    threading.Thread(target=_run, daemon=True, name=f"overlay-refresh-{sleeper_league_id}").start()


def _build_overlay_and_cache(
    sleeper_league_id: str,
    *,
    id_to_player: dict[str, str] | None,
    trade_window_days: int,
) -> dict[str, Any] | None:
    """The actual ~league-chain-wide build.  Uses a build-scoped URL
    memo (``_BuildFetcher``) plus one parallel prefetch wave for the
    weekly transaction feeds + per-league lookups, cutting a cold
    build from ~100 sequential round-trips to ~2 short parallel waves.
    Output is byte-identical to the sequential build: the memo only
    dedupes URLs that were fetched multiple times per build, and the
    builders still consume weeks in order."""
    fetcher = _BuildFetcher()

    # Wave 1: the chain walk (1-2 calls, inherently sequential).
    chain = _walk_league_chain(sleeper_league_id, max_depth=2, getter=fetcher.get)

    # Wave 2: everything whose URL is known up front, in parallel —
    # per-league rosters/users/league/drafts/traded_picks and the
    # 19 weekly transaction feeds per chain league that BOTH the
    # trades and waivers builders consume.
    prefetch_urls: list[str] = []
    for lid in chain or [sleeper_league_id]:
        base = f"https://api.sleeper.app/v1/league/{lid}"
        prefetch_urls.extend([f"{base}/rosters", f"{base}/users", base, f"{base}/drafts"])
        prefetch_urls.extend(f"{base}/transactions/{week}" for week in range(0, 19))
    root_base = f"https://api.sleeper.app/v1/league/{sleeper_league_id}"
    prefetch_urls.append(f"{root_base}/traded_picks")
    fetcher.prefetch(prefetch_urls)

    teams = _build_teams_block(sleeper_league_id, id_to_player, getter=fetcher.get)
    if teams is None:
        # Hard fetch failure — nothing useful to return.
        return None

    league_name = _fetch_league_name(sleeper_league_id, getter=fetcher.get) or ""
    trades = _build_trades_block(
        sleeper_league_id,
        window_days=trade_window_days,
        id_to_player=id_to_player,
        getter=fetcher.get,
    )
    waivers = _build_waivers_block(
        sleeper_league_id,
        window_days=trade_window_days,
        id_to_player=id_to_player,
        getter=fetcher.get,
    )

    # The requested league's OWN scoring/roster/settings, read from the
    # same league object ``_fetch_league_name`` just used.  This is what
    # lets a cross-league block be published as ready WITHOUT inheriting
    # the loaded league's configuration (W18-F002); ``None`` here means
    # the block will honestly say it is not ready.
    league_config = _fetch_league_config(sleeper_league_id, getter=fetcher.get)

    cutoff_dt = _dt.datetime.now(_dt.timezone.utc) - _dt.timedelta(days=int(trade_window_days))
    payload: dict[str, Any] = {
        "leagueId": sleeper_league_id,
        "leagueName": league_name,
        "leagueConfig": league_config,
        "teams": teams,
        "trades": trades,
        "waivers": waivers,
        "tradeWindowDays": int(trade_window_days),
        "tradeWindowStart": cutoff_dt.isoformat(),
        "tradeWindowCutoffMs": int(cutoff_dt.timestamp() * 1000),
        "overlaySource": "live",
        "overlayFetchedAt": _dt.datetime.now(_dt.timezone.utc).isoformat(),
        "meta": {
            "tradeCount": len(trades),
            "waiverCount": len(waivers),
        },
    }

    with _CACHE_LOCK:
        _CACHE[sleeper_league_id] = {"payload": dict(payload), "_cached_at": time.time()}
    return payload


def reset_fallback_name_cache() -> None:
    """Test hook — clear the lazy Sleeper fallback name map so a
    monkeypatched ``_http_get_json`` is re-consulted."""
    global _FALLBACK_NAMES, _FALLBACK_ATTEMPT_AT
    with _FALLBACK_NAMES_LOCK:
        _FALLBACK_NAMES = None
        _FALLBACK_ATTEMPT_AT = 0.0


def fetch_sleeper_teams_overlay(
    *,
    sleeper_league_id: str,
    id_to_player: dict[str, str] | None = None,
    force_refresh: bool = False,
) -> dict[str, Any] | None:
    """Teams + FAAB balances ONLY — no trades/waivers history.

    The full :func:`fetch_sleeper_overlay` builds the trade AND
    waiver history on a cold cache — up to dozens of serial
    transaction requests across two seasons — while some callers
    (the FAAB recommend endpoint) only need rosters and balances.
    This fast path answers from, in order:

      1. a FRESH full-overlay cache entry (free — reuse its teams),
      2. its own short teams cache (``_TEAMS_CACHE_TTL_SEC``),
      3. a live ``_build_teams_block`` fetch — rosters + users +
         league settings + traded picks, ~4 requests total.

    Returns ``{"teams": [...], "overlayFetchedAt": iso-str}`` where
    ``overlayFetchedAt`` is when THOSE teams were actually fetched
    (an honest freshness stamp even on the stale-fallback path), or
    ``None`` when nothing is available at all.  On a live fetch
    failure it degrades to the most recent cached teams (stale full
    overlay, then stale teams cache) before giving up.
    """
    sleeper_league_id = str(sleeper_league_id or "").strip()
    if not sleeper_league_id:
        return None

    now = time.time()

    def _from_full_cache(entry: dict[str, Any] | None) -> dict[str, Any] | None:
        payload = (entry or {}).get("payload") or {}
        if payload.get("teams"):
            return {
                "teams": payload["teams"],
                "overlayFetchedAt": payload.get("overlayFetchedAt"),
            }
        return None

    if not force_refresh:
        with _CACHE_LOCK:
            full = _CACHE.get(sleeper_league_id)
            if full and (now - float(full.get("_cached_at") or 0)) < _CACHE_TTL_SEC:
                hit = _from_full_cache(full)
                if hit is not None:
                    return hit
            teams_cached = _TEAMS_CACHE.get(sleeper_league_id)
            if (
                teams_cached
                and (now - float(teams_cached.get("_cached_at") or 0)) < _TEAMS_CACHE_TTL_SEC
            ):
                return dict(teams_cached["payload"])

    teams = _build_teams_block(sleeper_league_id, id_to_player)
    if teams is None:
        # Hard fetch failure — serve the most recent teams we have
        # (stale is better than nothing; the stamp stays honest).
        with _CACHE_LOCK:
            stale_full = _from_full_cache(_CACHE.get(sleeper_league_id))
            if stale_full is not None:
                return stale_full
            teams_cached = _TEAMS_CACHE.get(sleeper_league_id)
            if teams_cached:
                return dict(teams_cached["payload"])
        return None

    payload = {
        "teams": teams,
        "overlayFetchedAt": _dt.datetime.now(_dt.timezone.utc).isoformat(),
    }
    with _CACHE_LOCK:
        _TEAMS_CACHE[sleeper_league_id] = {"payload": dict(payload), "_cached_at": now}
    return payload


def invalidate_overlay_cache(sleeper_league_id: str | None = None) -> None:
    """Drop cached overlay(s).  ``None`` clears everything."""
    with _CACHE_LOCK:
        if sleeper_league_id is None:
            _CACHE.clear()
            _TEAMS_CACHE.clear()
            return
        _CACHE.pop(str(sleeper_league_id), None)
        _TEAMS_CACHE.pop(str(sleeper_league_id), None)


# ── Live draft sync ─────────────────────────────────────────────────────
# Auction draft companion: the /draft route polls
# ``/api/sleeper/draft/picks`` every 2-3s while a draft is in progress
# and feeds new picks into the workspace via ``recordPick`` on the
# frontend, eliminating manual entry while the auctioneer's calling
# bids.  Lives in this module because it shares the urllib + circuit
# breaker plumbing with the overlay; isolated caches keep the two paths
# from interfering.
#
# Out of scope (mentioned for the reader, not implemented here):
#   * Live nomination state (who's currently on the block, mid-bid
#     amounts).  Not exposed by Sleeper's public REST API — only by an
#     undocumented WebSocket used by browser extensions.  We stick to
#     the documented endpoints.
#   * Sub-second latency.  Polling at 2.5s gives ~3s worst-case lag
#     which fully addresses "I can't manually keep up while drafting".


def _current_season_year() -> int:
    return _dt.datetime.now(_dt.timezone.utc).year


def _league_season(sleeper_league_id: str) -> str:
    """Authoritative season for a league: the Sleeper league object's
    ``season`` field (single source of truth, same as the public-league
    pipeline).  Falls back to the calendar year only if the league fetch
    fails — never hard-code or assume the year so season rollover is
    automatic when the league advances.
    """
    info = _http_get_json(f"https://api.sleeper.app/v1/league/{sleeper_league_id}")
    if isinstance(info, dict):
        season = str(info.get("season") or "").strip()
        if season:
            return season
    return str(_current_season_year())


def _resolve_active_draft_id(sleeper_league_id: str) -> str | None:
    """Pick the most relevant draft for a league.

    Sleeper exposes drafts via ``/v1/league/{id}/drafts`` — a league
    can have multiple drafts across seasons (startup + every annual
    rookie draft), so we filter to the current season and prefer
    ``status == "drafting"``, falling back to ``"pre_draft"``, and
    finally ``"complete"`` (so a freshly-finished draft still serves
    its picks for review).  Ties broken by newest ``start_time``.

    Returns ``None`` when no candidate draft exists or the league
    fetch failed.  Cached for 60s per league — long enough to stay
    cheap during a 2-hour auction, short enough that toggling the
    draft live during a session is reflected within a minute.
    """
    sleeper_league_id = str(sleeper_league_id or "").strip()
    if not sleeper_league_id:
        return None

    now = time.time()
    with _CACHE_LOCK:
        cached = _DRAFT_ID_CACHE.get(sleeper_league_id)
        if cached and (now - float(cached.get("_cached_at") or 0)) < _DRAFT_ID_CACHE_TTL_SEC:
            return cached.get("draft_id")

    drafts = _http_get_json(f"https://api.sleeper.app/v1/league/{sleeper_league_id}/drafts")
    draft_id: str | None = None
    if isinstance(drafts, list):
        season = _league_season(sleeper_league_id)
        # Status precedence: drafting > pre_draft > complete.  Lower is
        # better.  Within the same status, newest start_time wins.
        rank = {"drafting": 0, "pre_draft": 1, "complete": 2}
        best: tuple[int, int, str] | None = None
        for d in drafts:
            if not isinstance(d, dict):
                continue
            if str(d.get("sport") or "nfl") != "nfl":
                continue
            d_season = str(d.get("season") or "").strip()
            if d_season != season:
                continue
            status = str(d.get("status") or "").strip()
            if status not in rank:
                continue
            d_id = str(d.get("draft_id") or "").strip()
            if not d_id:
                continue
            try:
                start = int(d.get("start_time") or 0)
            except (TypeError, ValueError):
                start = 0
            key = (rank[status], -start, d_id)
            if best is None or key < best:
                best = key
                draft_id = d_id

    with _CACHE_LOCK:
        _DRAFT_ID_CACHE[sleeper_league_id] = {
            "draft_id": draft_id,
            "_cached_at": now,
        }
    return draft_id


def _fetch_draft_meta(draft_id: str) -> dict[str, Any] | None:
    """Fetch ``/v1/draft/{id}`` — used to surface the draft's current
    status (``drafting``/``pre_draft``/``complete``) so the frontend
    knows when to stop polling.  Result is not cached separately;
    draft-meta TTL piggybacks on ``_DRAFT_PICKS_CACHE_TTL_SEC`` via
    its parent caller.
    """
    if not draft_id:
        return None
    data = _http_get_json(f"https://api.sleeper.app/v1/draft/{draft_id}")
    return data if isinstance(data, dict) else None


def _normalize_live_pick(pick: dict[str, Any]) -> dict[str, Any] | None:
    """Project one Sleeper pick dict into the compact shape the
    frontend hook consumes.

    Returns ``None`` when required fields (pick_no, player_id) are
    missing or unparseable — those picks are skipped so a malformed
    row never breaks the whole stream.

    Output shape::

        {
            "pickNo":  int,     # monotonic cursor
            "playerId": str,    # Sleeper player_id (matches workspace.players[].id)
            "amount":  int,     # auction price; 0 for snake-draft picks
            "ownerId": str,     # Sleeper user_id of the winner ("" when unknown)
            "rosterId": int|None,
            "round":   int|None,
            "pickedAt": int|None,  # epoch seconds when Sleeper recorded the pick
        }
    """
    pick_no = _safe_int(pick.get("pick_no"))
    pid = pick.get("player_id")
    if pick_no is None or pick_no < 1 or pid is None:
        return None

    metadata = pick.get("metadata") if isinstance(pick.get("metadata"), dict) else {}
    amount_raw = metadata.get("amount") if isinstance(metadata, dict) else None
    # Auction picks stamp ``metadata.amount`` as a string ("$23" or
    # "23" depending on draft type).  Strip a leading $ and coerce.
    amount = 0
    if amount_raw is not None:
        try:
            amount = int(str(amount_raw).lstrip("$").strip())
        except (TypeError, ValueError):
            amount = 0

    owner = pick.get("picked_by")
    owner_id = str(owner).strip() if owner else ""

    return {
        "pickNo": pick_no,
        "playerId": str(pid),
        "amount": amount,
        "ownerId": owner_id,
        "rosterId": _safe_int(pick.get("roster_id")),
        "round": _safe_int(pick.get("round")),
        "pickedAt": _safe_int(pick.get("picked_at")),
    }


def fetch_live_draft_picks(
    sleeper_league_id: str,
    after_pick_no: int = 0,
    *,
    force_refresh: bool = False,
) -> dict[str, Any] | None:
    """Return the current live-draft snapshot for a league.

    Shape::

        {
            "draftId":      str,
            "status":       "drafting" | "pre_draft" | "complete" | "unknown",
            "latestPickNo": int,
            "picks":        [<normalized pick>, ...],  # only those with pick_no > after_pick_no
            "fetchedAt":    iso-str,
        }

    Returns ``None`` when no draft can be resolved for the league
    (no current-season draft, league fetch failed).  Callers
    typically degrade to a "live sync not available" UI in that case.

    Caching: the FULL picks list is cached per draft id for 2s so a
    burst of polling tabs against the same draft only round-trips
    Sleeper at most every 2s.  Cursor filtering (``after_pick_no``)
    happens on the cached list.
    """
    sleeper_league_id = str(sleeper_league_id or "").strip()
    if not sleeper_league_id:
        return None

    draft_id = _resolve_active_draft_id(sleeper_league_id)
    if not draft_id:
        return None

    now = time.time()
    cache_key = f"draft_picks:{draft_id}"
    snapshot: dict[str, Any] | None = None
    if not force_refresh:
        with _CACHE_LOCK:
            cached = _DRAFT_PICKS_CACHE.get(cache_key)
            if cached and (now - float(cached.get("_cached_at") or 0)) < _DRAFT_PICKS_CACHE_TTL_SEC:
                snapshot = cached.get("snapshot")

    if snapshot is None:
        meta = _fetch_draft_meta(draft_id)
        status = str(meta.get("status") if isinstance(meta, dict) else "").strip() or "unknown"
        raw_picks = _http_get_json(f"https://api.sleeper.app/v1/draft/{draft_id}/picks")
        if not isinstance(raw_picks, list):
            # Hard fetch failure.  Don't poison the cache — let the
            # next poll retry.  Return None so the route surfaces a
            # graceful "couldn't load" state without 500ing.
            return None
        normalized: list[dict[str, Any]] = []
        for p in raw_picks:
            if not isinstance(p, dict):
                continue
            row = _normalize_live_pick(p)
            if row is not None:
                normalized.append(row)
        normalized.sort(key=lambda r: r["pickNo"])
        latest = normalized[-1]["pickNo"] if normalized else 0
        snapshot = {
            "draftId": draft_id,
            "status": status,
            "latestPickNo": latest,
            "picks": normalized,
            "fetchedAt": _dt.datetime.now(_dt.timezone.utc).isoformat(),
        }
        with _CACHE_LOCK:
            _DRAFT_PICKS_CACHE[cache_key] = {
                "snapshot": snapshot,
                "_cached_at": now,
            }

    # Apply the cursor outside the cache.  The full list lives in the
    # cache; per-client slicing is cheap.
    try:
        after = max(0, int(after_pick_no))
    except (TypeError, ValueError):
        after = 0
    delta_picks = [p for p in snapshot["picks"] if p["pickNo"] > after]
    return {
        "draftId": snapshot["draftId"],
        "status": snapshot["status"],
        "latestPickNo": snapshot["latestPickNo"],
        "picks": delta_picks,
        "fetchedAt": snapshot["fetchedAt"],
    }


def invalidate_live_draft_cache(sleeper_league_id: str | None = None) -> None:
    """Drop the live-draft caches.  Used by tests + a potential future
    admin "force refresh" endpoint.  ``None`` clears everything."""
    with _CACHE_LOCK:
        if sleeper_league_id is None:
            _DRAFT_ID_CACHE.clear()
            _DRAFT_PICKS_CACHE.clear()
            return
        key = str(sleeper_league_id)
        cached = _DRAFT_ID_CACHE.pop(key, None)
        if cached:
            did = cached.get("draft_id")
            if did:
                _DRAFT_PICKS_CACHE.pop(f"draft_picks:{did}", None)
