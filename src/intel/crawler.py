"""Budgeted, resumable Sleeper crawl for the intel pipeline.

Pool = the active league's members (``member_ids``).  For each member
we discover their other Sleeper leagues via
``/v1/user/<owner_id>/leagues/nfl/<season>`` (public, unauthenticated),
dedupe leagues across members, then fetch rosters + incremental
transactions per league.

Identity: everything keys on ``owner_id`` — Sleeper's GLOBAL user id,
stable for the same human across every league.  Roster co-owners are
matched too; orphaned rosters (no ``owner_id``) are skipped.

Budget: hard cap of ``budget`` HTTP calls per run (default 900),
single-threaded, ``sleep_s`` between calls.  Steady state is roughly
1 (nfl state) + N members (league lists) + 3 per league (rosters +
traded picks + current-week transactions) ≈ 460 calls for a
12-member pool tracking ~150 leagues.  When the budget exhausts
mid-run the cursor (``state["cursor"]``) records the unfinished
members/leagues so the next run resumes round-robin where this one
stopped.

Incremental transactions: ``fetchState[leagueId] = {maxCreatedSeen,
boundaryTxIds}``.  We fetch only the current week (plus the previous
week within 48h of a week rollover) and skip transactions at or below
the boundary — ``boundaryTxIds`` disambiguates created-timestamp ties
at exactly ``maxCreatedSeen``.  This also handles the offseason
degeneracy where transactions pile into the week-0 (preseason
trades) and week-1 buckets: whenever the current week is <= 1 BOTH
buckets are fetched, and refetches re-see old transactions that the
boundary (plus a global event-id dedupe) drops.  First-run backfill
walks back at most ``BACKFILL_MAX_WEEKS`` weeks or
``BACKFILL_MAX_DAYS`` days, reaching week 0.
"""

from __future__ import annotations

import copy
import logging
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Callable

from src.intel import league_filter
from src.intel.store import EVENT_RETENTION_DAYS, default_state

log = logging.getLogger(__name__)

SLEEPER_BASE = "https://api.sleeper.app/v1"
PER_MEMBER_LEAGUE_CAP = 25
DEFAULT_BUDGET = 900
DEFAULT_SLEEP_S = 0.12
BACKFILL_MAX_WEEKS = 6
BACKFILL_MAX_DAYS = 30
WEEK_ROLLOVER_GRACE_HOURS = 48
# Default pick-ownership horizon — mirrors
# ``sleeper_overlay._build_pick_ownership`` (3 upcoming seasons) and
# the scraper's draft_rounds clamp (1..6, default 4).
PICK_HOLDINGS_YEARS = 3
DEFAULT_DRAFT_ROUNDS = 4
MAX_DRAFT_ROUNDS = 6

HttpGet = Callable[[str], Any]


def _default_http_get(url: str) -> Any:
    """Live fetch through the sleeper overlay's urllib + circuit
    breaker plumbing (returns parsed JSON or None on any failure)."""
    from src.api import sleeper_overlay

    return sleeper_overlay._http_get_json(url)


def _iso(ms: int) -> str:
    return datetime.fromtimestamp(ms / 1000, tz=timezone.utc).isoformat()


def _parse_iso_ms(value: Any) -> int | None:
    if not value:
        return None
    try:
        return int(datetime.fromisoformat(str(value)).timestamp() * 1000)
    except (ValueError, TypeError):
        return None


class _CallBudget:
    """Hard call-count budget with an inter-call sleep."""

    def __init__(
        self,
        budget: int,
        sleep_s: float,
        http_get: HttpGet,
        sleep_fn: Callable[[float], None] = time.sleep,
    ) -> None:
        self.remaining = max(0, int(budget))
        self.used = 0
        self._sleep_s = max(0.0, float(sleep_s))
        self._http_get = http_get
        self._sleep_fn = sleep_fn

    def can_call(self, n: int = 1) -> bool:
        return self.remaining >= n

    def get(self, url: str) -> Any:
        if self.remaining <= 0:  # pragma: no cover — callers check can_call first
            raise RuntimeError("intel crawl budget exhausted")
        if self.used > 0 and self._sleep_s > 0:
            self._sleep_fn(self._sleep_s)
        self.remaining -= 1
        self.used += 1
        return self._http_get(url)


@dataclass
class CrawlResult:
    state: dict[str, Any]
    calls_used: int = 0
    budget_exhausted: bool = False
    completed: bool = True
    failed_member_ids: list[str] = field(default_factory=list)
    new_event_count: int = 0
    # Leagues the dynasty filter declined, by label
    # ({"redraft": 4, "best_ball": 1}).  Reported rather than dropped
    # silently: a shrinking tracked-league count must be explainable.
    excluded_leagues: dict[str, int] = field(default_factory=dict)


def _tx_created_ms(tx: dict[str, Any]) -> int:
    for key in ("status_updated", "created"):
        raw = tx.get(key)
        if isinstance(raw, (int, float)) and raw > 0:
            return int(raw)
    return 0


def _roster_owner_map(
    rosters: list[Any],
    pool: set[str],
) -> tuple[dict[str, str], dict[str, list[str]]]:
    """(roster_id → attributed owner_id, pool holdings).

    Attribution prefers the primary ``owner_id``; when the primary is
    not a pool member but a ``co_owners`` entry is, the pool co-owner
    is credited (so co-owned teams still show up in the tracker).
    Orphaned rosters (no owner) are skipped entirely.
    """
    rid_to_owner: dict[str, str] = {}
    holdings: dict[str, list[str]] = {}
    for roster in rosters:
        if not isinstance(roster, dict):
            continue
        owner = str(roster.get("owner_id") or "").strip()
        if not owner:
            continue  # orphaned roster
        co_owners = [
            str(c).strip() for c in (roster.get("co_owners") or []) if str(c or "").strip()
        ]
        attributed = owner
        if owner not in pool:
            pool_co = next((c for c in co_owners if c in pool), None)
            if pool_co:
                attributed = pool_co
        rid = roster.get("roster_id")
        if rid is None:
            continue
        rid_to_owner[str(rid)] = attributed
        if attributed in pool:
            players = [str(p) for p in (roster.get("players") or []) if str(p or "").strip()]
            holdings[attributed] = players
    return rid_to_owner, holdings


def _pick_holdings(
    roster_ids: list[str],
    traded_picks: Any,
    draft_rounds: int,
    now_year: int,
    num_years: int = PICK_HOLDINGS_YEARS,
    *,
    season_year: int | None = None,
    draft_status: str | None = None,
) -> dict[str, list[str]]:
    """``{rosterId: ["pick:<season>:<round>", ...]}`` — current pick
    ownership per roster.

    Default ownership: every roster owns its own pick in each round
    of the next ``num_years`` seasons; ``/traded_picks`` entries are
    the diffs, keyed ``(season, round, original roster_id)`` → new
    ``owner_id``.  Mirrors the convention in
    ``src/api/sleeper_overlay.py::_build_pick_ownership`` and the
    scraper's ``team_pick_details`` (Dynasty Scraper.py).  Asset ids
    use the SAME ``pick:<season>:<round>`` naming as
    ``_events_from_tx`` so holdings and trade events join in
    drill-downs.
    """
    if not roster_ids:
        return {}
    rounds = max(1, min(MAX_DRAFT_ROUNDS, int(draft_rounds or DEFAULT_DRAFT_ROUNDS)))
    # D9: start the horizon at the FIRST SEASON WHOSE PICKS STILL EXIST.
    #
    # Two things used to be wrong here.  The base year came from the
    # wall clock, which disagrees with the league's own season for most
    # of the calendar (Sleeper rolls a league over around Aug/Sept, so
    # Jan-Aug 2027 has now_year=2027 while the league still says 2026).
    # And the current season's picks were seeded even after that
    # season's rookie draft had been held, crediting every roster with
    # assets that no longer exist.
    #
    # Both are answered by data already in the league payload the crawl
    # fetches — ``season`` and ``status`` — so this costs no extra API
    # call.  ``pre_draft``/``drafting`` mean this season's picks are
    # still live assets; anything later means they have been spent.
    base_year = int(season_year if season_year is not None else now_year)
    if str(draft_status or "").strip().lower() not in ("", "pre_draft", "drafting"):
        base_year += 1
    seasons = [str(base_year + y) for y in range(num_years)]
    ownership: dict[tuple[str, int, str], str] = {}
    for season in seasons:
        for rnd in range(1, rounds + 1):
            for rid in roster_ids:
                ownership[(season, rnd, rid)] = rid
    if isinstance(traded_picks, list):
        for tp in traded_picks:
            if not isinstance(tp, dict):
                continue
            season = str(tp.get("season") or "")
            try:
                rnd = int(tp.get("round") or 0)
            except (TypeError, ValueError):
                continue
            original = str(tp.get("roster_id") or "")
            owner = str(tp.get("owner_id") or "")
            if not season or rnd < 1 or not original or not owner:
                continue
            key = (season, rnd, original)
            if key in ownership:
                ownership[key] = owner
    out: dict[str, list[str]] = {}
    for (season, rnd, _original), owner in sorted(ownership.items()):
        out.setdefault(owner, []).append(f"pick:{season}:{rnd}")
    return out


def _events_from_tx(
    tx: dict[str, Any],
    league_id: str,
    week: int,
    rid_to_owner: dict[str, str],
    pool: set[str],
    known_event_ids: set[str],
) -> list[dict[str, Any]]:
    """Extract pool-member add/drop events from one transaction.

    Trades emit paired add+drop events per side (players AND picks);
    waiver / free-agent moves emit single-sided events.  Only
    ``status == "complete"`` transactions count.  Events are deduped
    globally by ``eventId`` so refetching a week (offseason week-1
    degeneracy, budget-interrupted runs) never double-counts.
    """
    if tx.get("status") != "complete":
        return []
    tx_type = str(tx.get("type") or "")
    if tx_type not in ("trade", "waiver", "free_agent"):
        return []
    tx_id = str(tx.get("transaction_id") or "")
    if not tx_id:
        return []
    created = _tx_created_ms(tx)
    if created <= 0:
        return []

    settings = tx.get("settings") if isinstance(tx.get("settings"), dict) else {}
    faab_bid: int | None = None
    if tx_type == "waiver":
        try:
            faab_bid = int(settings.get("waiver_bid") or 0)
        except (TypeError, ValueError):
            faab_bid = 0

    events: list[dict[str, Any]] = []

    def emit(
        rid: Any, action: str, asset_id: str, asset_type: str, discriminator: str = ""
    ) -> None:
        owner = rid_to_owner.get(str(rid))
        if not owner or owner not in pool:
            return
        event_id = f"{tx_id}:{owner}:{action}:{asset_id}"
        if discriminator:
            event_id = f"{event_id}:{discriminator}"
        if event_id in known_event_ids:
            return
        known_event_ids.add(event_id)
        events.append(
            {
                "eventId": event_id,
                "txId": tx_id,
                "leagueId": str(league_id),
                "ownerId": owner,
                "assetId": asset_id,
                "assetType": asset_type,
                "action": action,
                "txType": tx_type,
                "ts": created,
                "week": int(week),
                "faabBid": faab_bid if (tx_type == "waiver" and action == "add") else None,
            }
        )

    adds = tx.get("adds") if isinstance(tx.get("adds"), dict) else {}
    drops = tx.get("drops") if isinstance(tx.get("drops"), dict) else {}
    for player_id, rid in adds.items():
        emit(rid, "add", str(player_id), "player")
    for player_id, rid in drops.items():
        emit(rid, "drop", str(player_id), "player")

    # Traded draft picks — Sleeper's ``draft_picks`` entries carry
    # ROSTER ids: ``owner_id`` receives the pick, ``previous_owner_id``
    # gives it up.  The EVENT id carries the pick's original-roster
    # identity (``roster_id`` — the slot the pick belongs to) so a
    # trade that sends one manager MULTIPLE picks of the same
    # season+round produces distinct events instead of collapsing in
    # the eventId dedupe; the ASSET id stays grouped
    # (``pick:<season>:<round>``) for aggregation.
    for pick_idx, pick in enumerate(tx.get("draft_picks") or []):
        if not isinstance(pick, dict):
            continue
        season = str(pick.get("season") or "").strip()
        rnd = pick.get("round")
        if not season or rnd is None:
            continue
        asset_id = f"pick:{season}:{rnd}"
        original = pick.get("roster_id")
        # roster_id is stable across refetches; the enumerate index is
        # a last-resort fallback for malformed entries.
        discriminator = f"o{original}" if original is not None else f"i{pick_idx}"
        emit(pick.get("owner_id"), "add", asset_id, "pick", discriminator)
        emit(pick.get("previous_owner_id"), "drop", asset_id, "pick", discriminator)
    return events


def _weeks_to_fetch(
    league_entry: dict[str, Any],
    current_week: int,
    week_first_seen_ms: int | None,
    now_ms: int,
) -> list[int]:
    """Which transaction weeks to pull for a league this run.

    Steady state: the current week only, plus the previous week for
    the first 48h after a week rollover (late transactions land in the
    old week's bucket for a while).  First run for a league (no
    ``backfilled`` stamp): walk back ``BACKFILL_MAX_WEEKS`` weeks —
    the caller applies the ``BACKFILL_MAX_DAYS`` age stop.
    """
    fetch_state = league_entry.get("fetchState") or {}
    if not fetch_state.get("backfilled"):
        # Walk down to week 0: Sleeper stores PRESEASON trades in the
        # week-0 bucket (the overlay's trade-history path fetches
        # weeks 0..18 for the same reason — see sleeper_overlay.py's
        # transactions loop), so a backfill that stops at 1 silently
        # loses them.
        lo = max(0, current_week - BACKFILL_MAX_WEEKS + 1)
        weeks = list(range(current_week, lo - 1, -1))
        if current_week <= 1:
            # Offseason/preseason: transactions split across the
            # week-0 (preseason trades) and week-1 (offseason
            # degeneracy) buckets — always cover both.
            for w in (1, 0):
                if w not in weeks:
                    weeks.append(w)
        return weeks
    if current_week <= 1:
        # Offseason/preseason steady state: both degenerate buckets.
        return [current_week, 1 - current_week]
    weeks = [current_week]
    if week_first_seen_ms is not None:
        grace_ms = WEEK_ROLLOVER_GRACE_HOURS * 3600 * 1000
        if now_ms - week_first_seen_ms <= grace_ms:
            weeks.append(current_week - 1)
    return weeks


def collect_seed_members(
    sleeper_league_id: str,
    http_get: HttpGet | None = None,
) -> tuple[list[str], dict[str, str]]:
    """Seed the member pool from the active league's rosters.

    Reuses the sleeper overlay's owner-id source (rosters ``owner_id``
    + ``co_owners``): per the authority note on
    ``src/api/sleeper_overlay.py::_league_rid_lookup``, owner-id is the
    stable aggregation key for a human across league chains.  Orphaned
    rosters are skipped.  Returns ``(member_ids, display_names)``.
    """
    fetch = http_get or _default_http_get
    rosters = fetch(f"{SLEEPER_BASE}/league/{sleeper_league_id}/rosters")
    users = fetch(f"{SLEEPER_BASE}/league/{sleeper_league_id}/users")
    member_ids: list[str] = []
    seen: set[str] = set()
    if isinstance(rosters, list):
        for roster in rosters:
            if not isinstance(roster, dict):
                continue
            owner = str(roster.get("owner_id") or "").strip()
            if not owner:
                continue  # orphaned roster — no owner to track
            candidates = [owner] + [
                str(c).strip() for c in (roster.get("co_owners") or []) if str(c or "").strip()
            ]
            for oid in candidates:
                if oid not in seen:
                    seen.add(oid)
                    member_ids.append(oid)
    names: dict[str, str] = {}
    if isinstance(users, list):
        for user in users:
            if not isinstance(user, dict):
                continue
            uid = str(user.get("user_id") or "").strip()
            if uid and uid in seen:
                names[uid] = str(user.get("display_name") or "").strip()
    return member_ids, names


def crawl(
    member_ids: list[str],
    season: str | int,
    prev_state: dict[str, Any] | None,
    budget: int = DEFAULT_BUDGET,
    sleep_s: float = DEFAULT_SLEEP_S,
    *,
    http_get: HttpGet | None = None,
    now_ms: int | None = None,
    sleep_fn: Callable[[float], None] = time.sleep,
) -> CrawlResult:
    """One budgeted crawl pass.  Returns the updated state (built on a
    deep copy of ``prev_state`` so failed fetches preserve prior data)
    plus run metadata.  Never raises on fetch failures — failed
    members are isolated and reported in ``failed_member_ids``."""
    season = str(season)
    now = now_ms if now_ms is not None else int(time.time() * 1000)
    fetch = http_get or _default_http_get
    b = _CallBudget(budget, sleep_s, fetch, sleep_fn)

    state = (
        copy.deepcopy(prev_state)
        if isinstance(prev_state, dict) and prev_state
        else default_state(season)
    )
    for key, value in default_state(season).items():
        state.setdefault(key, value)
    state["season"] = season

    members = [str(m).strip() for m in member_ids or [] if str(m or "").strip()]
    pool = set(members)

    known_event_ids: set[str] = {
        str(e.get("eventId"))
        for e in state.get("events") or []
        if isinstance(e, dict) and e.get("eventId")
    }

    failed_members: list[str] = []
    new_event_count = 0

    # ── 1. NFL state → current week ────────────────────────────────
    # Week 0 is REAL: Sleeper reports it during the offseason and
    # stores preseason trades in the week-0 transactions bucket, so
    # it must never be coerced to 1 (``_weeks_to_fetch`` covers both
    # degenerate buckets whenever week <= 1).
    week: int | None = None
    if b.can_call():
        nfl_state = b.get(f"{SLEEPER_BASE}/state/nfl")
        if isinstance(nfl_state, dict):
            try:
                week = int(nfl_state.get("week"))
            except (TypeError, ValueError):
                week = None
    if week is None or week < 0:
        prev_week = state.get("week")
        week = prev_week if isinstance(prev_week, int) and prev_week >= 0 else 1
    week = max(0, min(18, int(week)))
    seen_at = state.get("weekFirstSeenAt") or {}
    if str(week) not in seen_at:
        seen_at[str(week)] = _iso(now)
    # Keep only the stamps that matter for the rollover-grace check.
    state["weekFirstSeenAt"] = {k: v for k, v in seen_at.items() if k in (str(week), str(week - 1))}
    state["week"] = week
    week_first_seen_ms = _parse_iso_ms(state["weekFirstSeenAt"].get(str(week)))

    # ── 2. Member phase — league discovery, pending-first order ────
    cursor = state.get("cursor") if isinstance(state.get("cursor"), dict) else {}
    prev_pending_members = [str(m) for m in (cursor.get("pendingMembers") or []) if str(m) in pool]
    ordered_members = prev_pending_members + [
        m for m in members if m not in set(prev_pending_members)
    ]

    members_block = state.setdefault("members", {})
    leagues_block = state.setdefault("leagues", {})
    discovered_this_run: list[str] = []
    pending_members: list[str] = []
    # {"redraft": n, "best_ball": n, ...} — what the dynasty filter
    # dropped this run, surfaced on the crawl result so the tracked
    # league count is always explainable.
    excluded_leagues: dict[str, int] = {}

    for idx, oid in enumerate(ordered_members):
        if not b.can_call():
            pending_members = ordered_members[idx:]
            break
        raw = b.get(f"{SLEEPER_BASE}/user/{oid}/leagues/nfl/{season}")
        entry = members_block.get(oid)
        if not isinstance(entry, dict):
            entry = {
                "leagues": [],
                "truncated": False,
                "lastCrawledAt": None,
                "lastError": None,
            }
        if not isinstance(raw, list):
            entry["lastError"] = f"leagues_fetch_failed@{_iso(now)}"
            members_block[oid] = entry
            failed_members.append(oid)
            continue
        league_objs = [lg for lg in raw if isinstance(lg, dict) and lg.get("league_id")]
        # Dynasty signal, dynasty leagues.  Redraft/best-ball trade
        # behaviour is the OPPOSITE of dynasty behaviour for the same
        # player, so mixing them cancels real signal rather than
        # adding to it.  Excluded counts are recorded (never silently
        # dropped) so a smaller tracked-league number is explainable.
        league_objs, excluded_by_type = league_filter.partition(league_objs)
        for label, n in excluded_by_type.items():
            excluded_leagues[label] = excluded_leagues.get(label, 0) + n
        truncated = len(league_objs) > PER_MEMBER_LEAGUE_CAP
        league_objs = league_objs[:PER_MEMBER_LEAGUE_CAP]
        entry.update(
            {
                "leagues": [str(lg["league_id"]) for lg in league_objs],
                "truncated": truncated,
                "lastCrawledAt": _iso(now),
                "lastError": None,
            }
        )
        members_block[oid] = entry
        for lg in league_objs:
            lid = str(lg["league_id"])
            league_entry = leagues_block.get(lid)
            if not isinstance(league_entry, dict):
                league_entry = {
                    "name": "",
                    "season": season,
                    "totalRosters": None,
                    "memberOwnerIds": [],
                    "holdings": {},
                    "fetchState": {},
                    "lastError": None,
                }
            # League metadata comes free with the leagues-list call.
            league_entry["name"] = str(lg.get("name") or league_entry.get("name") or "")
            league_entry["season"] = str(lg.get("season") or season)
            # Captured for the pick horizon (D9): once a league is past
            # drafting, the current season's picks are spent assets.
            league_entry["status"] = str(lg.get("status") or league_entry.get("status") or "")
            league_entry["totalRosters"] = lg.get("total_rosters") or league_entry.get(
                "totalRosters"
            )
            lg_settings = lg.get("settings") if isinstance(lg.get("settings"), dict) else {}
            try:
                draft_rounds = int(lg_settings.get("draft_rounds") or 0)
            except (TypeError, ValueError):
                draft_rounds = 0
            league_entry["draftRounds"] = (
                max(1, min(MAX_DRAFT_ROUNDS, draft_rounds))
                if draft_rounds
                else league_entry.get("draftRounds") or DEFAULT_DRAFT_ROUNDS
            )
            league_entry["memberOwnerIds"] = sorted(
                set(str(m) for m in league_entry.get("memberOwnerIds") or []) | {oid}
            )
            leagues_block[lid] = league_entry
            if lid not in discovered_this_run:
                discovered_this_run.append(lid)

    # ── 3. League phase — rosters + incremental transactions ───────
    prev_pending_leagues = [
        str(lid) for lid in (cursor.get("pendingLeagues") or []) if str(lid) in leagues_block
    ]
    league_order = prev_pending_leagues + [
        lid for lid in discovered_this_run if lid not in set(prev_pending_leagues)
    ]
    pending_leagues: list[str] = []
    # Leagues whose fetch was INCOMPLETE this run (roster or week
    # fetch returned garbage, or a backfill week failed).  They go
    # back into the cursor so the next run retries them —
    # budget-aware, since cursor leagues are processed first.
    retry_leagues: list[str] = []

    backfill_cutoff = now - BACKFILL_MAX_DAYS * 24 * 3600 * 1000

    now_year = datetime.fromtimestamp(now / 1000, tz=timezone.utc).year

    for idx, lid in enumerate(league_order):
        # A league costs at least 3 calls (rosters + traded picks +
        # 1 tx week); stop cleanly rather than half-fetching.
        if not b.can_call(3):
            pending_leagues = league_order[idx:]
            break
        league_entry = leagues_block[lid]
        rosters = b.get(f"{SLEEPER_BASE}/league/{lid}/rosters")
        rosters_ok = isinstance(rosters, list)
        if rosters_ok:
            rid_to_owner, holdings = _roster_owner_map(rosters, pool)
            prev_holdings = (
                league_entry.get("holdings")
                if isinstance(league_entry.get("holdings"), dict)
                else {}
            )
            # Fold pick holdings (default ownership + /traded_picks
            # diffs) into the same per-member holdings structure so
            # pick assets get real holder/held-league counts.
            traded_picks = b.get(f"{SLEEPER_BASE}/league/{lid}/traded_picks")
            if isinstance(traded_picks, list):
                try:
                    league_season_year = int(str(league_entry.get("season") or "").strip())
                except (TypeError, ValueError):
                    league_season_year = None
                pick_map = _pick_holdings(
                    sorted(rid_to_owner.keys()),
                    traded_picks,
                    int(league_entry.get("draftRounds") or DEFAULT_DRAFT_ROUNDS),
                    now_year,
                    season_year=league_season_year,
                    draft_status=league_entry.get("status"),
                )
                for rid, picks in pick_map.items():
                    owner = rid_to_owner.get(str(rid))
                    if owner in pool:
                        holdings.setdefault(owner, []).extend(picks)
                league_entry["pickHoldingsAt"] = _iso(now)
                league_entry["lastError"] = None
            else:
                # Failed /traded_picks fetch: NEVER publish derived
                # defaults — fabricating default ownership would
                # overwrite previously-correct traded-pick holdings
                # until a later crawl happened to succeed.  Carry the
                # last known pick holdings forward instead; if this
                # league has never had a successful pick fetch
                # (no ``pickHoldingsAt`` stamp), keep it in the retry
                # cursor so pick data arrives on the next run.
                for owner, assets in prev_holdings.items():
                    if owner not in pool:
                        continue
                    prior_picks = [a for a in assets or [] if str(a).startswith("pick:")]
                    if prior_picks:
                        holdings.setdefault(owner, []).extend(prior_picks)
                league_entry["lastError"] = f"traded_picks_fetch_failed@{_iso(now)}"
                if not league_entry.get("pickHoldingsAt") and lid not in retry_leagues:
                    retry_leagues.append(lid)
            league_entry["rosterOwners"] = rid_to_owner
            league_entry["holdings"] = holdings
        else:
            # Roster fetch failed — without the CURRENT owner map we
            # cannot attribute events safely: a roster may have
            # changed hands since the last snapshot, and ingesting
            # with the stale map would make the wrong attribution
            # PERMANENT once fetchState advances past those
            # transactions.  Skip the league entirely — no
            # transaction fetch, no fetchState advance — and retry
            # next run with fresh owners.
            league_entry["lastError"] = f"rosters_fetch_failed@{_iso(now)}"
            if lid not in retry_leagues:
                retry_leagues.append(lid)
            continue

        fetch_state = (
            league_entry.get("fetchState")
            if isinstance(league_entry.get("fetchState"), dict)
            else {}
        )
        max_seen = int(fetch_state.get("maxCreatedSeen") or 0)
        boundary_ids = {str(t) for t in fetch_state.get("boundaryTxIds") or []}
        is_backfill = not fetch_state.get("backfilled")

        weeks = _weeks_to_fetch(league_entry, week, week_first_seen_ms, now)
        fetched_all_weeks = True
        weeks_clean = True
        fetched_txs: list[tuple[int, dict[str, Any]]] = []
        for w in weeks:
            if not b.can_call():
                fetched_all_weeks = False
                break
            txs = b.get(f"{SLEEPER_BASE}/league/{lid}/transactions/{w}")
            if not isinstance(txs, list):
                # Transient failure for this week.  During backfill
                # this would otherwise silently and PERMANENTLY lose
                # the week's activity once ``backfilled`` is stamped —
                # so mark the fetch dirty and retry the league next
                # run instead of advancing fetchState.
                weeks_clean = False
                continue
            week_created = [
                _tx_created_ms(t) for t in txs if isinstance(t, dict) and _tx_created_ms(t) > 0
            ]
            for tx in txs:
                if isinstance(tx, dict):
                    fetched_txs.append((w, tx))
            # Backfill age stop: once a whole (non-empty) week is
            # older than the backfill window, stop walking back.  The
            # degenerate offseason buckets (weeks 0-1) are exempt —
            # fresh offseason activity piles into week 1 even when
            # week 0 holds only stale preseason rows, so a stale
            # week 0 must not stop the walk.
            if is_backfill and w > 1 and week_created and max(week_created) < backfill_cutoff:
                break

        if not fetched_all_weeks:
            # Budget died mid-league: don't advance fetchState (the
            # global event-id dedupe makes the refetch safe) and
            # resume with this league next run.
            pending_leagues = [lid] + league_order[idx + 1 :]
            break

        # Ingest whatever we DID fetch cleanly — the eventId dedupe
        # makes re-ingesting on the retry pass a no-op.
        new_max = max_seen
        for w, tx in fetched_txs:
            created = _tx_created_ms(tx)
            tx_id = str(tx.get("transaction_id") or "")
            if created < max_seen:
                continue
            if created == max_seen and tx_id in boundary_ids:
                continue
            # Advance the boundary over EVERYTHING seen (including
            # backfill rows too old to ingest) so the next run doesn't
            # re-surface them as "new".
            if created > new_max:
                new_max = created
            if is_backfill and created < backfill_cutoff:
                continue
            events = _events_from_tx(tx, lid, w, rid_to_owner, pool, known_event_ids)
            if events:
                state.setdefault("events", []).extend(events)
                new_event_count += len(events)

        if not weeks_clean:
            # Incomplete fetch: do NOT advance fetchState (advancing
            # ``maxCreatedSeen`` past a failed week's transactions
            # would filter them out forever) and do NOT stamp
            # ``backfilled``.  Retry next run.
            league_entry["lastError"] = f"transactions_fetch_failed@{_iso(now)}"
            if lid not in retry_leagues:
                retry_leagues.append(lid)
            continue

        new_boundary = {
            str(tx.get("transaction_id") or "")
            for _w, tx in fetched_txs
            if _tx_created_ms(tx) == new_max and tx.get("transaction_id")
        }
        if new_max == max_seen:
            new_boundary |= boundary_ids
        league_entry["fetchState"] = {
            "maxCreatedSeen": new_max,
            "boundaryTxIds": sorted(new_boundary),
            "backfilled": True,
            "lastFetchedAt": _iso(now),
        }

    all_pending_leagues = pending_leagues + [
        lid for lid in retry_leagues if lid not in set(pending_leagues)
    ]

    # ── 4. Reconciliation — successful fetches only ────────────────
    # The pool (seed league rosters) is authoritative for WHO we
    # track; each member's fresh league list is authoritative for
    # WHERE.  Members who left the seed league are dropped, and
    # leagues no longer referenced by any tracked member are dropped
    # (along with both groups' events/holdings).  Failed fetches never
    # trigger removal: a failed member keeps their previous league
    # list (preserve-on-failure above), so their leagues stay
    # referenced, and the seed itself is validated by the caller
    # before crawl runs.
    #
    # SEASON ROLLOVER: ``/v1/user/<id>/leagues/nfl/<season>`` only
    # returns the NEW season's league ids, so at rollover every
    # prior-season league becomes unreferenced at once — dropping
    # them immediately would wipe recent (<45d) events out of the
    # rolling trends.  Unreferenced leagues that still have pool
    # events inside the retention window are therefore RETAINED as
    # inactive: no further crawling (they never re-enter the fetch
    # order), holdings cleared (the rolled-over roster no longer
    # exists), events kept until normal retention expires them —
    # after which the league entry disappears too.  Same intent as
    # the overlay's ``previous_league_id`` chain walk
    # (sleeper_overlay.py) without spending crawl budget on dead
    # leagues.
    members_block = {oid: entry for oid, entry in members_block.items() if oid in pool}
    state["members"] = members_block
    referenced_leagues: set[str] = set()
    for entry in members_block.values():
        referenced_leagues.update(str(lg) for lg in entry.get("leagues") or [])
    referenced_leagues |= set(all_pending_leagues)

    retention_cutoff = now - EVENT_RETENTION_DAYS * 24 * 3600 * 1000
    recent_event_leagues = {
        str(e.get("leagueId") or "")
        for e in state.get("events") or []
        if isinstance(e, dict)
        and str(e.get("ownerId") or "") in pool
        and isinstance(e.get("ts"), (int, float))
        and e["ts"] >= retention_cutoff
    }
    retained_inactive = {
        lid
        for lid in leagues_block
        if lid not in referenced_leagues and lid in recent_event_leagues
    }
    leagues_block = {
        lid: e
        for lid, e in leagues_block.items()
        if lid in referenced_leagues or lid in retained_inactive
    }
    state["leagues"] = leagues_block
    for lid, entry in leagues_block.items():
        if lid in retained_inactive:
            entry["inactive"] = True
            entry["holdings"] = {}
            continue
        entry["inactive"] = False
        current_members = sorted(
            oid for oid, m in members_block.items() if lid in (m.get("leagues") or [])
        )
        entry["memberOwnerIds"] = current_members
        entry["holdings"] = {
            oid: h
            for oid, h in (entry.get("holdings") or {}).items()
            if oid in set(current_members)
        }
    state["events"] = [
        e
        for e in state.get("events") or []
        if isinstance(e, dict)
        and str(e.get("ownerId") or "") in pool
        and str(e.get("leagueId") or "") in leagues_block
        and isinstance(e.get("ts"), (int, float))
        and e["ts"] >= retention_cutoff
    ]

    budget_exhausted = bool(pending_members or pending_leagues)
    has_pending = bool(pending_members or all_pending_leagues)
    state["cursor"] = (
        {"pendingMembers": pending_members, "pendingLeagues": all_pending_leagues}
        if has_pending
        else None
    )
    state["lastRun"] = {
        "startedAt": _iso(now),
        "callsUsed": b.used,
        "budgetExhausted": budget_exhausted,
        "retryLeagueIds": retry_leagues,
        "failedMemberIds": failed_members,
        "newEventCount": new_event_count,
        "week": week,
    }

    return CrawlResult(
        state=state,
        calls_used=b.used,
        budget_exhausted=budget_exhausted,
        completed=not has_pending,
        failed_member_ids=failed_members,
        new_event_count=new_event_count,
        excluded_leagues=excluded_leagues,
    )
