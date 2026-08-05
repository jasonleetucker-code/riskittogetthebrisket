"""Orchestration for the intel pipeline: crawl → merge → store.

``refresh_intel`` is the single entry point for a refresh run.  A
process-wide non-blocking lock rejects concurrent refreshes (the crawl
takes minutes — the API layer runs it on a daemon thread and returns
202 immediately; a second trigger while one is running raises
``RefreshAlreadyRunning`` → 409).

Read helpers build the endpoint payloads from the normalized LEDGER
(``ledger.py`` + ``signals.py``), not from the snapshot's raw event
list.  The snapshot still owns crawl bookkeeping — cursor, fetchState,
current holdings, pool membership — and is cached in-process and
invalidated on file mtime change.

The read path moved off the retired ``aggregate.py``, which counted
waiver claims as trade "buys" and ranked the board by a ``trendScore``
that summed nested windows.  Both defects are gone with it; see
``docs/intel/METRICS.md``.

LEAGUE SCOPING: the ledger is GLOBAL — one file spanning every crawled
league, including the thousands of managers Sharp Tracker's discovery
graph reaches.  Insider Trading is league-scoped, so every ledger query
here is filtered to ``_pool_member_ids(state)``.
"""

from __future__ import annotations

import logging
import threading
import time
from datetime import datetime, timezone
from typing import Any, Sequence

from src.intel import crawler, ingest, ledger, signals, store

log = logging.getLogger(__name__)


class RefreshAlreadyRunning(RuntimeError):
    """A refresh run is already in progress in this process."""


_REFRESH_LOCK = threading.Lock()
_STATUS_LOCK = threading.Lock()
_STATUS: dict[str, Any] = {
    "isRunning": False,
    "startedAt": None,
    "finishedAt": None,
    "lastError": None,
    "lastResult": None,
    "leagueKey": None,
}

# In-process snapshot cache, PER LEAGUE KEY, keyed on file mtime.
_SNAPSHOT_CACHE: dict[str, dict[str, Any]] = {}
_SNAPSHOT_CACHE_LOCK = threading.Lock()


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _set_status(**fields: Any) -> None:
    with _STATUS_LOCK:
        _STATUS.update(fields)


def refresh_status(league_key: str | None = None) -> dict[str, Any]:
    """Run status (process-global — one crawl at a time) plus, when a
    ``league_key`` is given, that league's snapshot staleness."""
    with _STATUS_LOCK:
        status = dict(_STATUS)
    if league_key:
        state = load_state_cached(league_key)
        status["snapshotLeagueKey"] = league_key
        status["snapshotGeneratedAt"] = state.get("generatedAt")
        status["snapshotStaleHours"] = snapshot_stale_hours(state)
    return status


def invalidate_cache() -> None:
    with _SNAPSHOT_CACHE_LOCK:
        _SNAPSHOT_CACHE.clear()
    # Also forget which snapshots have been synced into the ledger: a
    # new snapshot carries new events that must be backfilled.
    with _LEDGER_SYNC_LOCK:
        _LEDGER_SYNCED.clear()


def load_state_cached(league_key: str = store.DEFAULT_LEAGUE_KEY) -> dict[str, Any]:
    """Load one league's snapshot, reusing the in-process copy until
    its file changes on disk.  Missing/corrupt snapshots yield an
    empty state (never raise) — see ``store.load_state``."""
    league_key = str(league_key or store.DEFAULT_LEAGUE_KEY)
    path = store.snapshot_path(league_key)
    try:
        mtime = path.stat().st_mtime
    except OSError:
        mtime = None
    with _SNAPSHOT_CACHE_LOCK:
        cached = _SNAPSHOT_CACHE.get(league_key)
        if cached is not None and cached["mtime"] == mtime:
            return cached["state"]
    state = store.load_state(league_key)
    with _SNAPSHOT_CACHE_LOCK:
        _SNAPSHOT_CACHE[league_key] = {"state": state, "mtime": mtime}
    return state


def snapshot_ready(league_key: str) -> bool:
    """True when a persisted snapshot exists for this league (i.e. at
    least one refresh has completed for it)."""
    return bool(load_state_cached(league_key).get("generatedAt"))


def snapshot_stale_hours(state: dict[str, Any]) -> float | None:
    """Snapshot age in hours, or None when no snapshot exists yet."""
    generated = state.get("generatedAt")
    if not generated:
        return None
    try:
        generated_dt = datetime.fromisoformat(str(generated))
    except (ValueError, TypeError):
        return None
    if generated_dt.tzinfo is None:
        generated_dt = generated_dt.replace(tzinfo=timezone.utc)
    age = datetime.now(timezone.utc) - generated_dt
    return round(age.total_seconds() / 3600.0, 2)


def _resolve_season(http_get: crawler.HttpGet | None) -> str:
    """Sleeper's league season for "now" — from ``/v1/state/nfl`` when
    reachable, else the current UTC year."""
    fetch = http_get or crawler._default_http_get
    nfl_state = fetch(f"{crawler.SLEEPER_BASE}/state/nfl")
    if isinstance(nfl_state, dict):
        season = str(nfl_state.get("league_season") or nfl_state.get("season") or "").strip()
        if season:
            return season
    return str(datetime.now(timezone.utc).year)


def refresh_intel(
    member_ids: list[str] | None = None,
    season: str | None = None,
    *,
    league_key: str = store.DEFAULT_LEAGUE_KEY,
    sleeper_league_id: str | None = None,
    budget: int = crawler.DEFAULT_BUDGET,
    sleep_s: float = crawler.DEFAULT_SLEEP_S,
    http_get: crawler.HttpGet | None = None,
) -> dict[str, Any]:
    """Run one refresh for ONE league's member pool: seed → crawl →
    merge → persist into that league's snapshot partition.

    Rejects concurrent runs via a non-blocking process lock — one
    crawl at a time regardless of league, so two leagues can never
    double Sleeper load (``RefreshAlreadyRunning``).  Synchronous —
    callers that must not block (the API endpoint) use
    ``start_refresh_async``.
    """
    league_key = str(league_key or store.DEFAULT_LEAGUE_KEY)
    if not _REFRESH_LOCK.acquire(blocking=False):
        raise RefreshAlreadyRunning("intel refresh already in progress")
    try:
        _set_status(isRunning=True, startedAt=_utc_now_iso(), lastError=None, leagueKey=league_key)
        result = _refresh_locked(
            member_ids=member_ids,
            season=season,
            league_key=league_key,
            sleeper_league_id=sleeper_league_id,
            budget=budget,
            sleep_s=sleep_s,
            http_get=http_get,
        )
        _set_status(lastResult=result, lastError=None)
        return result
    except Exception as exc:
        _set_status(lastError=str(exc))
        raise
    finally:
        _set_status(isRunning=False, finishedAt=_utc_now_iso())
        _REFRESH_LOCK.release()


def refresh_intel_many(
    leagues: list[dict[str, Any]],
    *,
    season: str | None = None,
    budget: int = crawler.DEFAULT_BUDGET,
    sleep_s: float = crawler.DEFAULT_SLEEP_S,
    http_get: crawler.HttpGet | None = None,
) -> dict[str, Any]:
    """Refresh EVERY given league sequentially under the single
    process lock — one Sleeper crawl at a time, each league with its
    own budget and snapshot partition.  This is the ``leagueKey=all``
    mode the daily cron uses so non-default leagues don't sit at
    ``data_not_ready`` forever.

    ``leagues`` entries: ``{"leagueKey": str, "sleeperLeagueId": str}``.
    One league's failure is isolated — the loop continues, the error
    is recorded per-league, and ``lastError`` is set so the cron's
    failure handler surfaces it.
    """
    cleaned = [
        {
            "leagueKey": str(lg.get("leagueKey") or "").strip(),
            "sleeperLeagueId": str(lg.get("sleeperLeagueId") or "").strip(),
        }
        for lg in leagues or []
        if str(lg.get("leagueKey") or "").strip()
    ]
    if not cleaned:
        raise ValueError("refresh_intel_many needs at least one league")
    if not _REFRESH_LOCK.acquire(blocking=False):
        raise RefreshAlreadyRunning("intel refresh already in progress")
    try:
        _set_status(isRunning=True, startedAt=_utc_now_iso(), lastError=None, leagueKey="all")
        results: list[dict[str, Any]] = []
        errors: list[dict[str, str]] = []
        for lg in cleaned:
            _set_status(leagueKey=lg["leagueKey"])
            try:
                results.append(
                    _refresh_locked(
                        member_ids=None,
                        season=season,
                        league_key=lg["leagueKey"],
                        sleeper_league_id=lg["sleeperLeagueId"] or None,
                        budget=budget,
                        sleep_s=sleep_s,
                        http_get=http_get,
                    )
                )
            except Exception as exc:  # noqa: BLE001 — isolate per league
                log.warning("intel refresh failed for %s: %s", lg["leagueKey"], exc)
                errors.append({"leagueKey": lg["leagueKey"], "error": str(exc)})
        summary = {
            "mode": "all",
            "finishedAt": _utc_now_iso(),
            "leagueKeys": [lg["leagueKey"] for lg in cleaned],
            "leagues": results,
            "errors": errors,
        }
        _set_status(
            lastResult=summary,
            lastError=(
                "; ".join(f"{e['leagueKey']}: {e['error']}" for e in errors) if errors else None
            ),
            leagueKey="all",
        )
        return summary
    finally:
        _set_status(isRunning=False, finishedAt=_utc_now_iso())
        _REFRESH_LOCK.release()


def start_refresh_async(**kwargs: Any) -> dict[str, Any]:
    """Kick off ``refresh_intel`` (or ``refresh_intel_many`` when a
    ``leagues`` list is passed) on a daemon thread.  Returns the
    current status immediately; raises ``RefreshAlreadyRunning`` when
    a run is active (caller maps that to HTTP 409)."""
    with _STATUS_LOCK:
        if _STATUS.get("isRunning"):
            raise RefreshAlreadyRunning("intel refresh already in progress")
    if _REFRESH_LOCK.locked():
        raise RefreshAlreadyRunning("intel refresh already in progress")
    many = kwargs.pop("leagues", None)
    _set_status(isRunning=True, startedAt=_utc_now_iso(), lastError=None)

    def _worker() -> None:
        try:
            if many is not None:
                refresh_intel_many(many, **kwargs)
            else:
                refresh_intel(**kwargs)
        except RefreshAlreadyRunning:
            # Lost the race to a concurrent trigger — that run owns
            # the status now.
            pass
        except Exception as exc:  # noqa: BLE001 — surfaced via status
            log.exception("intel refresh failed: %s", exc)

    thread = threading.Thread(target=_worker, name="intel-refresh", daemon=True)
    thread.start()
    return refresh_status()


def _refresh_locked(
    member_ids: list[str] | None,
    season: str | None,
    league_key: str,
    sleeper_league_id: str | None,
    budget: int,
    sleep_s: float,
    http_get: crawler.HttpGet | None,
) -> dict[str, Any]:
    started = time.time()
    prev_state = store.load_state(league_key)

    member_names: dict[str, str] = dict(prev_state.get("memberNames") or {})
    seeded = [str(m) for m in (member_ids or []) if str(m or "").strip()]
    if not seeded:
        if not sleeper_league_id:
            raise ValueError("refresh_intel needs member_ids or sleeper_league_id to seed")
        seeded, names = crawler.collect_seed_members(sleeper_league_id, http_get=http_get)
        member_names.update(names)
    if not seeded:
        raise RuntimeError("intel seed produced no member ids (Sleeper unreachable?)")

    resolved_season = str(season).strip() if season else _resolve_season(http_get)

    result = crawler.crawl(
        seeded,
        resolved_season,
        prev_state,
        budget=budget,
        sleep_s=sleep_s,
        http_get=http_get,
    )
    merged = store.merge_member_results(prev_state, result.state, result.failed_member_ids)
    # Names follow the pool: drop departed members' names alongside
    # the crawler's member reconciliation.
    pool = set(seeded)
    merged["memberNames"] = {oid: n for oid, n in member_names.items() if oid in pool}
    store.save_state(merged, league_key)
    invalidate_cache()

    # Feed the normalized ledger.  The snapshot keeps the crawl
    # bookkeeping (cursor, fetchState, holdings); the ledger owns
    # history and every window query.  Idempotent — the crawler's
    # deterministic eventId is the ledger's movement_id, so this
    # inserts each movement exactly once no matter how often it runs.
    #
    # It must never take the refresh down: the crawl succeeded and the
    # snapshot is already durably written, so a ledger failure is
    # logged and reported, not raised.
    ledger_report: dict[str, Any] = {}
    try:
        ingested = ingest.ingest_state(merged, league_key=league_key)
        ledger.prune()
        ledger_report = {
            "movementsSeen": ingested.movements_seen,
            "movementsInserted": ingested.movements_inserted,
        }
    except Exception as exc:  # noqa: BLE001 — never fail the refresh
        log.exception("intel: ledger ingest failed for league=%s", league_key)
        ledger_report = {"error": str(exc)}

    summary = {
        "finishedAt": _utc_now_iso(),
        "durationSeconds": round(time.time() - started, 1),
        "leagueKey": league_key,
        "callsUsed": result.calls_used,
        "budgetExhausted": result.budget_exhausted,
        "completed": result.completed,
        "failedMemberIds": result.failed_member_ids,
        "newEventCount": result.new_event_count,
        "memberCount": len(merged.get("members") or {}),
        "leagueCount": len(merged.get("leagues") or {}),
        "eventCount": len(merged.get("events") or []),
        "excludedLeagues": result.excluded_leagues,
        "ledger": ledger_report,
        "season": resolved_season,
    }
    log.info("intel refresh done: %s", summary)
    return summary


# ── Read-side payload builders ──────────────────────────────────────
#
# NOTE: none of these expose raw Sleeper league IDs — the UI gets
# counts and league NAMES only.  ``_public_movement`` below is what
# enforces that for the one builder that returns raw ledger rows.


# The ledger is GLOBAL: one store holding movements from every league
# this platform has crawled, and ``asset_movements_for`` filters by
# pool membership, not by league.  Handing its rows straight to the
# client therefore published the raw Sleeper ``league_id`` of a
# league-mate's OTHER leagues — ones the requester is not in.
#
# An ALLOW-list, not a deny-list: a new identifying column added to the
# ledger later must not reach the wire just because nobody remembered
# to exclude it here.
_PUBLIC_MOVEMENT_FIELDS = (
    "movementId",
    "txId",
    "txType",
    "assetId",
    "assetType",
    "action",
    "userId",
    "ts",
    "week",
    "faabBid",
)


def _public_movement(movement: dict[str, Any]) -> dict[str, Any]:
    """One ledger movement row, reduced to the fields the UI renders."""
    return {k: movement[k] for k in _PUBLIC_MOVEMENT_FIELDS if k in movement}


def _pick_label(asset_id: str) -> str:
    # "pick:2027:2" → "2027 2nd"
    parts = asset_id.split(":")
    if len(parts) != 3:
        return asset_id
    _tag, season, rnd = parts
    suffix = {"1": "1st", "2": "2nd", "3": "3rd"}.get(rnd, f"{rnd}th")
    return f"{season} {suffix}"


def asset_display_name(asset_id: str, id_to_player: dict[str, str] | None) -> str:
    asset_id = str(asset_id)
    if asset_id.startswith("pick:"):
        return _pick_label(asset_id)
    name = (id_to_player or {}).get(asset_id)
    return str(name) if name else f"Player {asset_id}"


def holdings_from_state(state: dict[str, Any]) -> dict[str, dict[str, list[str]]]:
    """``{leagueId: {ownerId: [assetId, ...]}}`` from the crawl state.

    Current ownership stays in the SNAPSHOT rather than the ledger: it is
    a point-in-time fact the crawl overwrites each run, not an append-only
    event, so it has no place in a movement ledger.  (Moved here from the
    retired ``aggregate.py``.)
    """
    out: dict[str, dict[str, list[str]]] = {}
    for lid, league in (state.get("leagues") or {}).items():
        if not isinstance(league, dict):
            continue
        holdings = league.get("holdings")
        if isinstance(holdings, dict) and holdings:
            out[str(lid)] = {
                str(oid): [str(a) for a in assets or []]
                for oid, assets in holdings.items()
                if isinstance(assets, list)
            }
    return out


# Snapshots already synced into the ledger, keyed league → snapshot
# mtime.  Guards the self-heal below so it runs once per snapshot
# version, not once per request.
_LEDGER_SYNCED: dict[str, float | None] = {}
_LEDGER_SYNC_LOCK = threading.Lock()


def ensure_ledger_synced(league_key: str, state: dict[str, Any]) -> None:
    """Backfill this snapshot's events into the ledger if needed.

    WHY THIS EXISTS.  The read path moved from the snapshot's event list
    to the ledger.  Those are populated at different times: the snapshot
    by every crawl, the ledger by the crawl's ingest step (added later)
    or by ``scripts/migrate_intel_ledger.py``.  So on the deploy that
    ships this cutover there is a window where a league has a perfectly
    good snapshot and an empty ledger — and the board would render as
    "no activity", which is indistinguishable from a quiet week and
    would look like the feature broke rather than like a missing
    migration.

    Rather than depend on an operator remembering to run a script, the
    read path heals itself.  Safe to do so because ingestion is
    idempotent by construction: ``movement_id`` is the crawler's
    deterministic event id and every insert is ``INSERT OR IGNORE``, so
    a redundant sync writes nothing and cannot change a count.

    Runs at most once per (league, snapshot mtime).  Failures are
    logged, never raised — a ledger problem must not take down a read.
    """
    events = state.get("events") or []
    if not events:
        return
    try:
        mtime = store.snapshot_path(league_key).stat().st_mtime
    except OSError:
        mtime = None
    with _LEDGER_SYNC_LOCK:
        if _LEDGER_SYNCED.get(league_key) == mtime:
            return
    try:
        result = ingest.ingest_state(state, league_key=league_key)
        if result.movements_inserted:
            log.info(
                "intel.service: backfilled %d movement(s) into the ledger for league=%s",
                result.movements_inserted,
                league_key,
            )
    except Exception:  # noqa: BLE001 — a read must never 500 on this
        log.exception("intel.service: ledger backfill failed for league=%s", league_key)
        return
    with _LEDGER_SYNC_LOCK:
        _LEDGER_SYNCED[league_key] = mtime


def _pool_member_ids(state: dict[str, Any]) -> list[str]:
    """The league's tracked managers.

    THE LEDGER IS GLOBAL — one SQLite file holding movements from every
    league this platform has ever crawled, including the thousands of
    managers Sharp Tracker's discovery graph reaches.  Insider Trading
    is league-scoped, so EVERY ledger query it makes must be filtered to
    this pool.  An unfiltered query would silently serve one league's
    board another league's activity, which is precisely the collapse the
    scoring-profile/leagueKey split in CLAUDE.md exists to prevent.

    The snapshot remains the authority on pool membership: it is
    partitioned per league key and holds the crawl bookkeeping.
    """
    members = state.get("members") or {}
    return [str(oid) for oid in members if str(oid).strip()]


def _held_league_counts(holdings: dict[str, dict[str, list[str]]]) -> dict[str, int]:
    """``{assetId: distinct leagues where a pool member holds it}``.

    Kept STRICTLY separate from traded-league counts.  The predecessor
    unioned the two, so a widely-rostered player was indistinguishable
    from a widely-traded one — the asset most likely to look like a
    signal while carrying none.
    """
    per_asset: dict[str, set[str]] = {}
    for lid, by_owner in (holdings or {}).items():
        for _owner, assets in (by_owner or {}).items():
            for asset_id in assets or []:
                per_asset.setdefault(str(asset_id), set()).add(str(lid))
    return {asset: len(leagues) for asset, leagues in per_asset.items()}


def build_summary_payload(
    league_key: str,
    limit: int = 100,
    id_to_player: dict[str, str] | None = None,
    *,
    window: str = signals.INSIDER_DEFAULT_WINDOW,
    windows: Sequence[str] | None = None,
    sort: str = "net",
    asset_type: str | None = None,
    tx_types: Sequence[str] = ledger.TRADE_TX_TYPES,
) -> dict[str, Any]:
    """Insider Trading board, served from the normalized ledger.

    Each window is its own indexed query over the raw movement rows, so
    a movement 15 days old is returned by the 30d query AND the 90d
    query because it is one movement seen twice — never summed.  There
    is no ``trendScore``: see ``src/intel/signals.py`` for why it was
    retired.

    ``tx_types`` defaults to TRADES ONLY.  Waiver and free-agent
    movements stay in the ledger and are reachable via the separate
    waiver-interest payload, never inside a buy/sell count.
    """
    state = load_state_cached(league_key)
    ensure_ledger_synced(league_key, state)
    pool = _pool_member_ids(state)
    now_ms = int(datetime.now(timezone.utc).timestamp() * 1000)
    window_names = list(windows or signals.INSIDER_WINDOWS)
    if window not in window_names:
        window_names.append(window)

    per_window: dict[str, list[dict[str, Any]]] = {}
    if pool:
        conn = ledger.connect()
        try:
            for name in window_names:
                since, until = signals.window_bounds(name, now_ms)
                per_window[name] = ledger.asset_signals(
                    since_ms=since,
                    until_ms=until,
                    tx_types=tx_types,
                    user_ids=pool,
                    asset_type=asset_type,
                    conn=conn,
                )
        finally:
            conn.close()

    built = signals.build_asset_signals(
        per_window, now_ms=now_ms, primary_window=window, windows=window_names
    )
    # Only assets with activity IN THE ACTIVE WINDOW belong on the
    # board; a row of zeroes is noise, not a signal.
    active = [s for s in built if (s.windows.get(window) or {}).get("volume")]
    ordered = signals.sort_signals(active, sort=sort, primary_window=window)

    held = _held_league_counts(holdings_from_state(state))
    members = state.get("members") or {}
    rows = []
    for sig in ordered[: max(1, int(limit))]:
        row = sig.to_dict()
        row["displayName"] = asset_display_name(sig.asset_id, id_to_player)
        row["heldLeagueCount"] = held.get(sig.asset_id, 0)
        row["lastEventAt"] = (
            datetime.fromtimestamp(sig.last_ts / 1000, tz=timezone.utc).isoformat()
            if sig.last_ts
            else None
        )
        rows.append(row)

    return {
        "leagueKey": league_key,
        "generatedAt": state.get("generatedAt"),
        "staleHours": snapshot_stale_hours(state),
        "season": state.get("season") or None,
        "memberCount": len(members),
        "truncatedMemberCount": sum(
            1 for m in members.values() if isinstance(m, dict) and m.get("truncated")
        ),
        "leagueCount": len(state.get("leagues") or {}),
        "eventCount": len(state.get("events") or []),
        # Which lens produced these numbers.  "This is the 30-day view"
        # and "this field is missing" must never read the same.
        "window": window,
        "windows": window_names,
        "sort": sort,
        "countedTxTypes": list(tx_types),
        "assets": rows,
    }


def build_waiver_interest_payload(
    league_key: str,
    limit: int = 100,
    id_to_player: dict[str, str] | None = None,
    *,
    window: str = signals.INSIDER_DEFAULT_WINDOW,
) -> dict[str, Any]:
    """Waiver and free-agent activity, under its OWN label.

    Separate endpoint payload rather than a flag on the board, so a
    waiver claim can never be rendered as a trade "buy" — the defect
    that made the old board mostly waiver noise.  The field names are
    deliberately ``adds``/``drops``, not ``buys``/``sells``.
    """
    payload = build_summary_payload(
        league_key,
        limit=limit,
        id_to_player=id_to_player,
        window=window,
        windows=[window],
        sort="volume",
        tx_types=ledger.WAIVER_TX_TYPES,
    )
    for row in payload.get("assets") or []:
        for win in (row.get("windows") or {}).values():
            win["adds"] = win.pop("buys", 0)
            win["drops"] = win.pop("sells", 0)
            # "net adds" is not a meaningful waiver concept — a claim and
            # a later drop are two decisions, not a round trip.
            win.pop("net", None)
            win.pop("buyRate", None)
    payload["activityType"] = "waiver_and_free_agent"
    payload["note"] = (
        "Waiver claims and free-agent pickups. These are NOT trades and are "
        "never counted in the buy/sell signal."
    )
    return payload


def build_player_payload(
    league_key: str,
    asset_id: str,
    id_to_player: dict[str, str] | None = None,
    *,
    window: str = signals.INSIDER_DEFAULT_WINDOW,
) -> dict[str, Any] | None:
    """Per-asset intel: window aggregates + member exposure.  Returns
    None when the snapshot has no trace of the asset at all.

    ``window`` MUST match the window the board row was rendered from.
    It used to be hard-wired to ``INSIDER_DEFAULT_WINDOW`` while the
    board offered 7d/30d/90d, so expanding a row whose only movement
    was older than 30 days produced empty exposure and empty movements
    under a row reading "Buys 1" — the drill-down contradicted the
    number it was drilling into, which is exactly the auditability this
    payload exists to provide.
    """
    state = load_state_cached(league_key)
    ensure_ledger_synced(league_key, state)
    asset_id = str(asset_id)
    pool = _pool_member_ids(state)
    holdings = holdings_from_state(state)
    now_ms = int(datetime.now(timezone.utc).timestamp() * 1000)
    window_names = list(signals.INSIDER_WINDOWS)
    if window not in window_names:
        window_names.append(window)

    per_window: dict[str, list[dict[str, Any]]] = {}
    per_member: list[dict[str, Any]] = []
    movements: list[dict[str, Any]] = []
    if pool:
        conn = ledger.connect()
        try:
            for name in window_names:
                since, until = signals.window_bounds(name, now_ms)
                rows = ledger.asset_signals(
                    since_ms=since,
                    until_ms=until,
                    user_ids=pool,
                    conn=conn,
                )
                per_window[name] = [r for r in rows if r["assetId"] == asset_id]

            since, until = signals.window_bounds(window, now_ms)
            per_member = ledger.manager_asset_activity(
                user_ids=pool,
                asset_id=asset_id,
                since_ms=since,
                until_ms=until,
                conn=conn,
            )
            # The receipts: every movement behind the numbers above, so
            # any count on screen can be audited back to its trades.
            # Scoped to the CALLER's window, not the default one — see
            # the docstring.
            movements = ledger.asset_movements_for(
                asset_id, since_ms=since, until_ms=until, user_ids=pool, limit=100, conn=conn
            )
        finally:
            conn.close()

    built = signals.build_asset_signals(
        per_window,
        now_ms=now_ms,
        primary_window=window,
        windows=window_names,
    )
    sig = next((s for s in built if s.asset_id == asset_id), None)

    held_by_owner: dict[str, set[str]] = {}
    for lid, by_owner in holdings.items():
        for oid, assets in (by_owner or {}).items():
            if asset_id in (assets or []):
                held_by_owner.setdefault(str(oid), set()).add(str(lid))

    if sig is None and not per_member and not held_by_owner:
        return None

    member_names = state.get("memberNames") or {}
    activity_by_owner = {str(m["userId"]): m for m in per_member}
    exposure_out = []
    for oid in sorted(set(activity_by_owner) | set(held_by_owner)):
        act = activity_by_owner.get(oid) or {}
        last_ts = act.get("lastTs")
        exposure_out.append(
            {
                "ownerId": oid,
                "displayName": str(member_names.get(oid) or "") or None,
                "heldLeagueCount": len(held_by_owner.get(oid, ())),
                "buys": int(act.get("buys") or 0),
                "sells": int(act.get("sells") or 0),
                "net": int(act.get("net") or 0),
                "volume": int(act.get("volume") or 0),
                "tradedLeagueCount": int(act.get("uniqueLeagues") or 0),
                "lastEventAt": (
                    datetime.fromtimestamp(last_ts / 1000, tz=timezone.utc).isoformat()
                    if last_ts
                    else None
                ),
            }
        )
    exposure_out.sort(key=lambda m: (-m["volume"], -m["heldLeagueCount"], m["ownerId"]))

    if sig is None:
        sig = signals.AssetSignal(
            asset_id=asset_id,
            asset_type="pick" if asset_id.startswith("pick:") else "player",
        )
        for name in window_names:
            sig.windows[name] = {
                "buys": 0,
                "sells": 0,
                "net": 0,
                "volume": 0,
                "buyRate": None,
                "uniqueBuyers": 0,
                "uniqueSellers": 0,
                "uniqueManagers": 0,
                "uniqueLeagues": 0,
                "tradeCount": 0,
                "movementCount": 0,
            }

    payload = sig.to_dict()
    payload["displayName"] = asset_display_name(asset_id, id_to_player)
    payload["lastEventAt"] = (
        datetime.fromtimestamp(sig.last_ts / 1000, tz=timezone.utc).isoformat()
        if sig.last_ts
        else None
    )
    payload["leagueKey"] = league_key
    payload["window"] = window
    payload["memberExposure"] = exposure_out
    payload["holderCount"] = sum(1 for m in exposure_out if m["heldLeagueCount"] > 0)
    payload["heldLeagueTotal"] = sum(m["heldLeagueCount"] for m in exposure_out)
    # Held and traded stay SEPARATE — the predecessor unioned them, so a
    # widely-rostered player was indistinguishable from a traded one.
    payload["heldLeagueCount"] = len({lid for lids in held_by_owner.values() for lid in lids})
    payload["movements"] = [_public_movement(mv) for mv in movements]
    payload["generatedAt"] = state.get("generatedAt")
    payload["staleHours"] = snapshot_stale_hours(state)
    return payload


def build_member_payload(
    league_key: str,
    owner_id: str,
    id_to_player: dict[str, str] | None = None,
    limit: int = 50,
) -> dict[str, Any] | None:
    """One pool member's cross-league profile + recent activity."""
    state = load_state_cached(league_key)
    ensure_ledger_synced(league_key, state)
    owner_id = str(owner_id)
    members = state.get("members") or {}
    entry = members.get(owner_id)
    if not isinstance(entry, dict):
        return None
    now_ms = int(datetime.now(timezone.utc).timestamp() * 1000)
    since, until = signals.window_bounds(signals.INSIDER_DEFAULT_WINDOW, now_ms)
    # Scoped to THIS member only — a per-manager revealed-preference log.
    rows = ledger.manager_asset_activity(user_ids=[owner_id], since_ms=since, until_ms=until)
    rows.sort(key=lambda r: (-r["volume"], -(r["lastTs"] or 0), r["assetId"]))
    trade_count = sum(r["tradeCount"] for r in rows)
    league_names = []
    for lid in entry.get("leagues") or []:
        league = (state.get("leagues") or {}).get(str(lid))
        if isinstance(league, dict) and league.get("name"):
            league_names.append(str(league["name"]))
    member_names = state.get("memberNames") or {}
    return {
        "leagueKey": league_key,
        "ownerId": owner_id,
        "displayName": str(member_names.get(owner_id) or "") or None,
        "leagueCount": len(entry.get("leagues") or []),
        "leagueNames": league_names,
        "truncated": bool(entry.get("truncated")),
        "lastCrawledAt": entry.get("lastCrawledAt"),
        "lastError": entry.get("lastError"),
        "window": signals.INSIDER_DEFAULT_WINDOW,
        # Movements, not "events" — the unit is named so it cannot be
        # confused with transactions (see docs/intel/METRICS.md).
        "movementCount": sum(r["volume"] for r in rows),
        "tradeCount": trade_count,
        "assets": [
            {
                **{k: v for k, v in row.items() if k not in ("userId", "lastTs")},
                "displayName": asset_display_name(row["assetId"], id_to_player),
                "lastEventAt": (
                    datetime.fromtimestamp(row["lastTs"] / 1000, tz=timezone.utc).isoformat()
                    if row.get("lastTs")
                    else None
                ),
            }
            for row in rows[: max(1, int(limit))]
        ],
        "generatedAt": state.get("generatedAt"),
        "staleHours": snapshot_stale_hours(state),
    }
