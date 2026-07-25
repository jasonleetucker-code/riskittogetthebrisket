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

from src.intel import aggregate, crawler, store

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
}

# In-process snapshot cache keyed on file mtime.
_SNAPSHOT_CACHE: dict[str, Any] = {"state": None, "mtime": None}
_SNAPSHOT_CACHE_LOCK = threading.Lock()


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _set_status(**fields: Any) -> None:
    with _STATUS_LOCK:
        _STATUS.update(fields)


def refresh_status() -> dict[str, Any]:
    with _STATUS_LOCK:
        status = dict(_STATUS)
    state = load_state_cached()
    status["snapshotGeneratedAt"] = state.get("generatedAt")
    status["snapshotStaleHours"] = snapshot_stale_hours(state)
    return status


def invalidate_cache() -> None:
    with _SNAPSHOT_CACHE_LOCK:
        _SNAPSHOT_CACHE["state"] = None
        _SNAPSHOT_CACHE["mtime"] = None


def load_state_cached() -> dict[str, Any]:
    """Load the snapshot, reusing the in-process copy until the file
    changes on disk.  Missing/corrupt snapshots yield an empty state
    (never raise) — see ``store.load_state``."""
    path = store.SNAPSHOT_PATH
    try:
        mtime = path.stat().st_mtime
    except OSError:
        mtime = None
    with _SNAPSHOT_CACHE_LOCK:
        if _SNAPSHOT_CACHE["state"] is not None and _SNAPSHOT_CACHE["mtime"] == mtime:
            return _SNAPSHOT_CACHE["state"]
    state = store.load_state()
    with _SNAPSHOT_CACHE_LOCK:
        _SNAPSHOT_CACHE["state"] = state
        _SNAPSHOT_CACHE["mtime"] = mtime
    return state


def snapshot_stale_hours(state: dict[str, Any] | None = None) -> float | None:
    """Snapshot age in hours, or None when no snapshot exists yet."""
    state = state if state is not None else load_state_cached()
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
    sleeper_league_id: str | None = None,
    budget: int = crawler.DEFAULT_BUDGET,
    sleep_s: float = crawler.DEFAULT_SLEEP_S,
    http_get: crawler.HttpGet | None = None,
) -> dict[str, Any]:
    """Run one refresh: seed → crawl → merge → persist.

    Rejects concurrent runs via a non-blocking process lock
    (``RefreshAlreadyRunning``).  Synchronous — callers that must not
    block (the API endpoint) use ``start_refresh_async``.
    """
    if not _REFRESH_LOCK.acquire(blocking=False):
        raise RefreshAlreadyRunning("intel refresh already in progress")
    try:
        _set_status(isRunning=True, startedAt=_utc_now_iso(), lastError=None)
        result = _refresh_locked(
            member_ids=member_ids,
            season=season,
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


def start_refresh_async(**kwargs: Any) -> dict[str, Any]:
    """Kick off ``refresh_intel`` on a daemon thread.  Returns the
    current status immediately; raises ``RefreshAlreadyRunning`` when
    a run is active (caller maps that to HTTP 409)."""
    with _STATUS_LOCK:
        if _STATUS.get("isRunning"):
            raise RefreshAlreadyRunning("intel refresh already in progress")
    if _REFRESH_LOCK.locked():
        raise RefreshAlreadyRunning("intel refresh already in progress")
    _set_status(isRunning=True, startedAt=_utc_now_iso(), lastError=None)

    def _worker() -> None:
        try:
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
    sleeper_league_id: str | None,
    budget: int,
    sleep_s: float,
    http_get: crawler.HttpGet | None,
) -> dict[str, Any]:
    started = time.time()
    prev_state = store.load_state()

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
    merged["memberNames"] = member_names
    store.save_state(merged)
    invalidate_cache()

    summary = {
        "finishedAt": _utc_now_iso(),
        "durationSeconds": round(time.time() - started, 1),
        "callsUsed": result.calls_used,
        "budgetExhausted": result.budget_exhausted,
        "completed": result.completed,
        "failedMemberIds": result.failed_member_ids,
        "newEventCount": result.new_event_count,
        "memberCount": len(merged.get("members") or {}),
        "leagueCount": len(merged.get("leagues") or {}),
        "eventCount": len(merged.get("events") or []),
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
    limit: int = 100,
    id_to_player: dict[str, str] | None = None,
) -> dict[str, Any]:
    state = load_state_cached()
    now = datetime.now(timezone.utc)
    holdings = aggregate.holdings_from_state(state)
    summaries = aggregate.build_asset_summary(state.get("events"), now, holdings=holdings)
    # Only assets with actual trade activity belong on the tracker
    # board — pure holdings (no events in 30d) carry no trend signal.
    active = [
        s for s in summaries.values() if any(w["buys"] or w["sells"] for w in s["windows"].values())
    ]
    active.sort(key=lambda s: (-s["trendScore"], -(s["lastEventTs"] or 0)))
    members = state.get("members") or {}
    return {
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
    asset_id: str,
    id_to_player: dict[str, str] | None = None,
) -> dict[str, Any] | None:
    """Per-asset intel: window aggregates + member exposure.  Returns
    None when the snapshot has no trace of the asset at all."""
    state = load_state_cached()
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
            "trendScore": 0,
            "lastEventTs": None,
        }
    payload = _serialize_asset(entry, id_to_player)
    payload["memberExposure"] = exposure_out
    payload["holderCount"] = sum(1 for m in exposure_out if m["heldLeagueCount"] > 0)
    payload["heldLeagueTotal"] = sum(m["heldLeagueCount"] for m in exposure_out)
    payload["generatedAt"] = state.get("generatedAt")
    payload["staleHours"] = snapshot_stale_hours(state)
    return payload


def build_member_payload(
    owner_id: str,
    id_to_player: dict[str, str] | None = None,
    limit: int = 50,
) -> dict[str, Any] | None:
    """One pool member's cross-league profile + recent activity."""
    state = load_state_cached()
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
