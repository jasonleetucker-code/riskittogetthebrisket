"""Orchestration for the intel pipeline: crawl → merge → store.

``refresh_intel`` is the single entry point for a refresh run.  A
process-wide non-blocking lock rejects concurrent refreshes (the crawl
takes minutes — the API layer runs it on a daemon thread and returns
202 immediately; a second trigger while one is running raises
``RefreshAlreadyRunning`` → 409).

Read helpers build the endpoint payloads from the persisted snapshot,
computing window aggregates at read time (see ``aggregate.py``).  The
snapshot is cached in-process and invalidated on file mtime change so
GET traffic doesn't re-parse the JSON per request.
"""

from __future__ import annotations

import logging
import threading
import time
from datetime import datetime, timezone
from typing import Any

from src.intel import aggregate, crawler, ingest, ledger, store

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
# counts and league NAMES only.


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


def _serialize_asset(entry: dict[str, Any], id_to_player: dict[str, str] | None) -> dict[str, Any]:
    out = dict(entry)
    out["displayName"] = asset_display_name(entry["assetId"], id_to_player)
    ts = out.pop("lastEventTs", None)
    out["lastEventAt"] = (
        datetime.fromtimestamp(ts / 1000, tz=timezone.utc).isoformat() if ts else None
    )
    return out


def build_summary_payload(
    league_key: str,
    limit: int = 100,
    id_to_player: dict[str, str] | None = None,
) -> dict[str, Any]:
    state = load_state_cached(league_key)
    now = datetime.now(timezone.utc)
    holdings = aggregate.holdings_from_state(state)
    summaries = aggregate.build_asset_summary(state.get("events"), now, holdings=holdings)
    # Only assets with actual trade activity belong on the tracker
    # board — pure holdings (no events in 30d) carry no trend signal.
    active = [
        s for s in summaries.values() if any(w["buys"] or w["sells"] for w in s["windows"].values())
    ]
    # Rank on the confidence-adjusted directional signal, NEVER on a
    # sum of the nested windows.  ``signalStrength`` is computed over
    # the primary window alone (aggregate.PRIMARY_WINDOW), so a
    # movement an hour old enters the ranking once instead of three
    # times via 48h + 7d + 30d — the retired ``trendScore`` defect.
    # Ties break on primary-window volume then recency, so the order is
    # a deterministic total order rather than dict insertion order.
    def _board_rank_key(summary: dict[str, Any]) -> tuple[float, int, int]:
        primary = summary["windows"].get(aggregate.PRIMARY_WINDOW) or {}
        volume = int(primary.get("buys") or 0) + int(primary.get("sells") or 0)
        return (-float(summary["signalStrength"]), -volume, -(summary["lastEventTs"] or 0))

    active.sort(key=_board_rank_key)
    members = state.get("members") or {}
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
        "assets": [_serialize_asset(s, id_to_player) for s in active[: max(1, int(limit))]],
    }


def build_player_payload(
    league_key: str,
    asset_id: str,
    id_to_player: dict[str, str] | None = None,
) -> dict[str, Any] | None:
    """Per-asset intel: window aggregates + member exposure.  Returns
    None when the snapshot has no trace of the asset at all."""
    state = load_state_cached(league_key)
    now = datetime.now(timezone.utc)
    asset_id = str(asset_id)
    holdings = aggregate.holdings_from_state(state)
    summaries = aggregate.build_asset_summary(state.get("events"), now, holdings=holdings)
    entry = summaries.get(asset_id)
    exposure = aggregate.build_member_exposure(state.get("events"), holdings, asset_id, now)
    if entry is None and not exposure:
        return None
    member_names = state.get("memberNames") or {}
    exposure_out = []
    for member in exposure:
        row = dict(member)
        row["displayName"] = str(member_names.get(member["ownerId"]) or "") or None
        ts = row.pop("lastEventTs", None)
        row["lastEventAt"] = (
            datetime.fromtimestamp(ts / 1000, tz=timezone.utc).isoformat() if ts else None
        )
        exposure_out.append(row)
    if entry is None:
        held_league_ids = {
            lid
            for lid, by_owner in holdings.items()
            if any(asset_id in (assets or []) for assets in (by_owner or {}).values())
        }
        entry = {
            "assetId": asset_id,
            "assetType": "pick" if asset_id.startswith("pick:") else "player",
            "windows": aggregate._empty_windows(),
            "leagueCount": len(held_league_ids),
            "heldLeagueCount": len(held_league_ids),
            "signalStrength": 0.0,
            "confidence": "insufficient",
            "velocity": None,
            "lastEventTs": None,
        }
    payload = _serialize_asset(entry, id_to_player)
    payload["leagueKey"] = league_key
    payload["memberExposure"] = exposure_out
    payload["holderCount"] = sum(1 for m in exposure_out if m["heldLeagueCount"] > 0)
    payload["heldLeagueTotal"] = sum(m["heldLeagueCount"] for m in exposure_out)
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
    owner_id = str(owner_id)
    members = state.get("members") or {}
    entry = members.get(owner_id)
    if not isinstance(entry, dict):
        return None
    now = datetime.now(timezone.utc)
    activity = aggregate.build_member_activity(state.get("events"), owner_id, now)
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
        "eventCount30d": activity["eventCount30d"],
        "assets": [
            _serialize_asset(a, id_to_player) for a in activity["assets"][: max(1, int(limit))]
        ],
        "generatedAt": state.get("generatedAt"),
        "staleHours": snapshot_stale_hours(state),
    }
