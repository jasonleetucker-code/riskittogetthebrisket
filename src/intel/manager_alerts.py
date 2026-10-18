"""Manager Intelligence Batch F — alerts on a saved manager's new activity.

For each (signed-in user, saved manager) the detector remembers which
activity events it has already seen and reports only the ones it has not.
Events are the Batch B1/B2 unified feed (``manager_activity``): one event per
completed transaction (``tx:<transaction_id>``) or completed draft pick
(``draft:<draft_id>:<pick_no>``) — so the event id IS the dedupe key, and
running the detector twice over the same activity alerts once.

Rules (each pinned by ``tests/intel/test_manager_alerts.py``):

* **Baseline seeding.**  The first evaluation for a (user, manager) records
  every event it can see WITHOUT alerting, so saving a manager — or the
  feature reaching a user for the first time — never floods them.  The same
  applies per LEAGUE: a league seen fully read for the first time (a new
  league, or one that was unreadable until now) is seeded silently, so its
  older events are not reported as new when it becomes readable.
* **Only fully read leagues count.**  Events of a league whose transactions
  or drafts were not fully read are neither recorded nor alerted; they are
  picked up on a later run.  An unread league is never "no activity".
* **Uncertain attribution is not alerted.**  A move that may belong to the
  roster's previous owner (``attribution.uncertain``) is recorded as seen
  but never reported as this manager's.
* **Seen ids are kept while they can still appear** (every id in the current
  feed is retained) and for :data:`SEEN_RETENTION_MS` after, then pruned.

Delivery reuses the daily ``POST /api/signal-alerts/run`` sweep and its
email channel (:func:`run_sweep`, called from ``server.py``).  The sweep is
bounded: distinct saved managers across all users are read once each,
stalest first, at most :data:`SWEEP_MAX_MANAGERS` per run, each under its own
Sleeper call budget, inside a wall-clock budget, and it stops at the first
Sleeper rate limit.  Users without email notifications are still evaluated
(their seen state stays current, so turning email on later never floods) but
nothing is sent to them.  ``POST /api/manager-intel/saved/refresh`` runs the
same detector for one signed-in user (in-app, no email); events it reports
count as seen.

Each read also stores a small metrics ``snapshot`` (activity counts and
picks held, from the same payload) that the saved-managers leaderboard
ranks (``manager_leaderboard``) — so the leaderboard costs no Sleeper calls.
"""

from __future__ import annotations

import logging
import time
from pathlib import Path
from typing import Any, Callable

from src.api import user_kv as _user_kv
from src.intel import manager_activity as ma
from src.intel import manager_league as ml
from src.intel import manager_portfolio as mp
from src.intel import manager_saved as ms

_LOGGER = logging.getLogger(__name__)

#: The activity window the detector reads.  Short on purpose: it bounds the
#: Sleeper calls per manager (current week legs only).  A manager not read
#: within this window can miss events older than it — the sweep reports
#: ``coverageGapPossible`` when its rotation is slower than the window.
ALERT_WINDOW = "7d"
SEEN_RETENTION_MS = 45 * 24 * 3600 * 1000
MAX_SEEN_IDS = 2000

#: Sweep bounds.
SWEEP_MAX_MANAGERS = 12
SWEEP_CALL_BUDGET_PER_MANAGER = 200
SWEEP_TOTAL_CALL_BUDGET = 2400
SWEEP_WALL_SECONDS = 90.0
#: The per-user manual check reads at most this many saved managers.
REFRESH_MAX_MANAGERS = 3

#: A metrics snapshot older than this is not ranked (stale != current).
SNAPSHOT_STALE_MS = 72 * 3600 * 1000

MODE_BASELINE = "baseline_seeded"
MODE_OK = "ok"
MODE_UNREAD = "unread"

_OK = (mp.STATUS_OK, mp.STATUS_PARTIAL)

Provider = Callable[..., dict[str, Any]]


def _now_ms(now: Callable[[], float]) -> int:
    return int(now() * 1000)


# ── pure evaluation ─────────────────────────────────────────────────────


def read_league_ids(payload: dict[str, Any]) -> set[str]:
    """Leagues whose activity was fully read: rosters read, and (where the
    manager holds a roster) every transaction leg and draft read."""
    out: set[str] = set()
    for row in (payload.get("coverage") or {}).get("leagues") or []:
        lid = str(row.get("leagueId") or "")
        if not lid:
            continue
        held = row.get("rosterHeld")
        if held is False:
            out.add(lid)  # observed: no roster here, so nothing to miss
        elif held is True and row.get("transactions") == ma.COV_COMPLETE:
            if row.get("drafts") == ma.COV_COMPLETE:
                out.add(lid)
    return out


def _activity_complete(payload: dict[str, Any]) -> bool:
    rows = (payload.get("coverage") or {}).get("leagues") or []
    read = read_league_ids(payload)
    return all(str(r.get("leagueId") or "") in read for r in rows)


def build_snapshot(payload: dict[str, Any], now_ms: int) -> dict[str, Any]:
    """Leaderboard metrics from one activity payload — the Batch C activity
    counts (``manager_league._activity_counts``, the same definitions the
    league view ranks) and the B3 draft-capital totals.  A count over a
    partially read stream is ``None`` with a reason, never a low number."""
    feed = payload.get("feed") or []
    counts = ml._activity_counts(  # noqa: SLF001 — one definition of the counts
        feed, payload.get("trades") or [], payload.get("acquisitions") or [], feed
    )
    complete = _activity_complete(payload)
    dc = payload.get("draftCapital") or {}
    totals = dc.get("totals") if dc.get("available") else None
    picks_complete = bool(totals) and not totals.get("leaguesUnavailable")
    if not dc.get("available"):
        picks_reason = dc.get("reason") or "unavailable"
    elif not picks_complete:
        picks_reason = "pick_ownership_unavailable"
    else:
        picks_reason = None
    activity_reason = None if complete else "activity_partially_read"
    return {
        "asOf": now_ms,
        "status": payload.get("status"),
        "window": payload.get("windowApplied") or payload.get("window"),
        "leaguesInScope": len(payload.get("leagues") or []),
        "metrics": {
            "trades": counts["trades"] if complete else None,
            "events": counts["events"] if complete else None,
            "playersAdded": counts["playersAdded"] if complete else None,
            "picksHeld": totals.get("picksHeld") if picks_complete else None,
            "pickValue": totals.get("pricedValue") if picks_complete else None,
        },
        "reasons": {
            "trades": activity_reason,
            "events": activity_reason,
            "playersAdded": activity_reason,
            "picksHeld": picks_reason,
            "pickValue": picks_reason
            or ("unpriced" if picks_complete and totals.get("pricedValue") is None else None),
        },
    }


def _event_summary(item: dict[str, Any]) -> dict[str, Any]:
    def names(assets: list[dict[str, Any]]) -> list[str]:
        out = []
        for a in assets or []:
            label = a.get("name") or a.get("label") or a.get("playerId") or a.get("pickId")
            if label:
                out.append(str(label))
        return out

    return {
        "id": item.get("id"),
        "kind": item.get("kind"),
        "leagueId": item.get("leagueId"),
        "leagueName": item.get("leagueName"),
        "occurredAt": item.get("occurredAt"),
        "added": names(item.get("added")),
        "dropped": names(item.get("dropped")),
        "faabBid": item.get("faabBid"),
        "partners": list(item.get("partners") or []),
    }


def evaluate(
    prior: dict[str, Any] | None, payload: dict[str, Any], now_ms: int
) -> tuple[list[dict[str, Any]], str, dict[str, Any]]:
    """Pure: ``(new events, mode, next state)`` for one (user, manager).

    ``mode`` is ``baseline_seeded`` (first evaluation: everything recorded,
    nothing reported), ``ok`` or ``unread`` (the activity could not be read
    at all: seen state unchanged, so a later first read still seeds).
    """
    prior = dict(prior or {})
    if payload.get("status") not in _OK:
        prior["lastCheckedAt"] = now_ms
        prior["lastStatus"] = payload.get("status") or "unavailable"
        return [], MODE_UNREAD, prior

    existed = bool(prior.get("seededAt"))
    seen_raw = prior.get("seenIds") if isinstance(prior.get("seenIds"), dict) else {}
    seen: dict[str, int] = {str(k): int(v or 0) for k, v in seen_raw.items()}
    seeded = {str(x) for x in prior.get("seededLeagues") or []}
    read = read_league_ids(payload)

    fresh: list[dict[str, Any]] = []
    current_ids: set[str] = set()
    for item in payload.get("feed") or []:
        eid = str(item.get("id") or "")
        lid = str(item.get("leagueId") or "")
        if not eid or lid not in read:
            continue
        current_ids.add(eid)
        if eid in seen:
            continue
        seen[eid] = now_ms
        if not existed or lid not in seeded:
            continue  # baseline: recorded silently
        if (item.get("attribution") or {}).get("uncertain"):
            continue
        fresh.append(_event_summary(item))

    # Retention: never drop an id the feed can still show.
    cutoff = now_ms - SEEN_RETENTION_MS
    kept = {k: v for k, v in seen.items() if k in current_ids or v >= cutoff}
    if len(kept) > MAX_SEEN_IDS:
        order = sorted(kept.items(), key=lambda kv: (kv[0] in current_ids, kv[1]), reverse=True)
        kept = dict(order[:MAX_SEEN_IDS])

    nxt = {
        **prior,
        "seenIds": kept,
        "seededLeagues": sorted(seeded | read),
        "seededAt": prior.get("seededAt") or now_ms,
        "lastCheckedAt": now_ms,
        "lastStatus": payload.get("status"),
        "lastNewCount": len(fresh),
        "snapshot": build_snapshot(payload, now_ms),
    }
    if fresh:
        nxt["lastAlertAt"] = now_ms
    return fresh, (MODE_OK if existed else MODE_BASELINE), nxt


def detect_for_user(
    kv_user: str,
    manager_id: str,
    payload: dict[str, Any],
    *,
    path: Path | None = None,
    now: Callable[[], float] = time.time,
) -> tuple[list[dict[str, Any]], str]:
    """Evaluate one manager's activity for one user inside the user_kv write
    lock.  A manager no longer saved is skipped (``not_saved``).  The read's
    ``manager`` block refreshes the saved display name (same id only)."""
    now_ms = _now_ms(now)
    out: list[Any] = []

    def _mutate(state: dict[str, Any]) -> None:
        out.clear()
        entries = ms.entries_from_state(state)
        entry = next((e for e in entries if e["userId"] == manager_id), None)
        if entry is None:
            out.extend([[], "not_saved"])
            return
        alerts = ms.alert_states(state)
        fresh, mode, nxt = evaluate(alerts.get(manager_id), payload, now_ms)
        alerts[manager_id] = nxt
        state[ms.ALERT_FIELD] = alerts
        manager = payload.get("manager") or {}
        if str(manager.get("userId") or "") == manager_id:
            user = {
                "user_id": manager_id,
                "username": manager.get("username"),
                "display_name": manager.get("displayName"),
            }
            if ms._apply_names(entry, user, now_ms):  # noqa: SLF001 — same owner family
                ms._write_entries(state, entries)  # noqa: SLF001
        out.extend([fresh, mode])

    _user_kv.mutate_user_state(kv_user, _mutate, path=path)
    return out[0], out[1]


# ── email ───────────────────────────────────────────────────────────────

_KIND_LABEL = {
    "trade": "Trade",
    "waiver": "Waiver claim",
    "free_agent": "Free-agent add",
    "drop": "Drop",
    "commissioner": "Commissioner move",
    "draft": "Draft pick",
}


def format_email(display_name: str, by_manager: list[tuple[dict[str, Any], list[dict]]]) -> dict:
    count = sum(len(evs) for _, evs in by_manager)
    subject = f"[Brisket] {count} new move{'' if count == 1 else 's'} by managers you follow"
    lines = [f"Hi {display_name},", "", "New activity by managers you saved:", ""]
    for entry, events in by_manager:
        name = entry.get("displayName") or entry.get("username") or entry["userId"]
        lines.append(f"{name} (@{entry.get('username') or entry['userId']})")
        for ev in events:
            parts = [_KIND_LABEL.get(ev.get("kind"), "Move")]
            if ev.get("leagueName"):
                parts.append(f"in {ev['leagueName']}")
            line = "  • " + " ".join(parts)
            if ev.get("added"):
                line += f" — added {', '.join(ev['added'][:6])}"
            if ev.get("dropped"):
                line += f"; gave up {', '.join(ev['dropped'][:6])}"
            if isinstance(ev.get("faabBid"), int):
                line += f" (FAAB ${ev['faabBid']})"
            lines.append(line)
        lines.append("")
    lines.append("Manager Intelligence:  https://chaseupside.com/managers")
    lines.append("")
    lines.append("You get this because these managers are on your saved list. Remove a manager,")
    lines.append("or turn email notifications off in Settings, to stop it.")
    lines.append("")
    lines.append("— Risk It")
    return {"subject": subject, "body": "\n".join(lines)}


# ── sweep ───────────────────────────────────────────────────────────────


def _followers(
    user_states: dict[str, dict[str, Any]],
) -> tuple[dict[str, list[str]], dict[str, int]]:
    """``{managerId: [kv users with alerts on]}`` and each manager's oldest
    ``lastCheckedAt`` across those users (``0`` = never checked)."""
    followers: dict[str, list[str]] = {}
    staleness: dict[str, int] = {}
    for kv_user, state in user_states.items():
        if not isinstance(state, dict):
            continue
        alerts = ms.alert_states(state)
        for entry in ms.entries_from_state(state):
            if entry.get("alerts") is False:
                continue
            uid = entry["userId"]
            followers.setdefault(uid, []).append(kv_user)
            checked = int((alerts.get(uid) or {}).get("lastCheckedAt") or 0)
            staleness[uid] = min(staleness.get(uid, checked), checked)
    return followers, staleness


def _read_activity(
    provider: Provider, manager_id: str, contract: Any, call_budget: int
) -> dict[str, Any]:
    try:
        return provider(manager_id, contract=contract, window=ALERT_WINDOW, call_budget=call_budget)
    except Exception as exc:  # noqa: BLE001 — one manager never fails the sweep
        _LOGGER.warning("manager intel alert read failed for %s: %s", manager_id, exc)
        return {"status": mp.STATUS_UPSTREAM_UNAVAILABLE}


def run_sweep(
    *,
    contract: Any,
    delivery: Callable[[str, str, str], bool] | None,
    enabled: bool,
    user_states: dict[str, dict[str, Any]] | None = None,
    activity_provider: Provider = ma.cached_manager_activity,
    path: Path | None = None,
    now: Callable[[], float] = time.time,
    clock: Callable[[], float] = time.monotonic,
    max_managers: int = SWEEP_MAX_MANAGERS,
    call_budget_per_manager: int = SWEEP_CALL_BUDGET_PER_MANAGER,
    total_call_budget: int = SWEEP_TOTAL_CALL_BUDGET,
    wall_seconds: float = SWEEP_WALL_SECONDS,
) -> dict[str, Any]:
    """The daily saved-manager sweep.  Never raises for a single manager or
    user; the summary names what was read, skipped and delivered."""
    if not enabled:
        return {"enabled": False}
    if user_states is not None:
        states = user_states
    else:
        states = _user_kv.all_user_states(path=path) if path else _user_kv.all_user_states()
    followers, staleness = _followers(states)
    order = sorted(followers, key=lambda uid: (staleness.get(uid, 0), uid))
    t0 = clock()
    spent = 0
    read: list[str] = []
    skipped: dict[str, str] = {}
    per_user: dict[str, list[tuple[str, list[dict[str, Any]], str]]] = {}
    rate_limited = False
    for uid in order:
        if len(read) >= max_managers:
            skipped[uid] = "sweep_manager_cap"
            continue
        if rate_limited:
            skipped[uid] = "rate_limited"
            continue
        if spent >= total_call_budget:
            skipped[uid] = "sweep_call_budget"
            continue
        if clock() - t0 >= wall_seconds:
            skipped[uid] = "sweep_time_budget"
            continue
        payload = _read_activity(
            activity_provider,
            uid,
            contract,
            min(call_budget_per_manager, total_call_budget - spent),
        )
        spent += int((payload.get("coverage") or {}).get("callsSpent") or 0)
        if payload.get("status") == mp.STATUS_RATE_LIMITED:
            rate_limited = True
            skipped[uid] = "rate_limited"
            continue  # nothing recorded: a later run reads it whole
        read.append(uid)
        for kv_user in followers[uid]:
            try:
                fresh, mode = detect_for_user(kv_user, uid, payload, path=path, now=now)
            except Exception as exc:  # noqa: BLE001
                _LOGGER.warning("manager intel alert state failed for %s: %s", kv_user, exc)
                fresh, mode = [], f"state_error:{type(exc).__name__}"
            per_user.setdefault(kv_user, []).append((uid, fresh, mode))

    users_summary = []
    for kv_user, results in per_user.items():
        # Re-read: detection may have refreshed a saved manager's name.
        state = _user_kv.get_user_state(kv_user, path=path) or states.get(kv_user) or {}
        entries = {e["userId"]: e for e in ms.entries_from_state(state)}
        by_manager = [
            (entries.get(uid) or {"userId": uid}, fresh) for uid, fresh, _m in results if fresh
        ]
        count = sum(len(f) for _, f in by_manager)
        email = str(state.get("notificationsEmail") or "").strip()
        reason = "ok"
        delivered = False
        if not count:
            reason = "no_new_activity"
        elif not state.get("notificationsEnabled") or not email:
            reason = "no_email"
        elif delivery is None:
            reason = "no_delivery_configured"
        else:
            msg = format_email(kv_user, by_manager)
            try:
                delivered = bool(delivery(email, msg["subject"], msg["body"]))
                reason = "ok" if delivered else "delivery_returned_false"
            except Exception as exc:  # noqa: BLE001
                _LOGGER.warning("manager intel alert delivery failed for %s: %s", kv_user, exc)
                reason = f"delivery_error:{type(exc).__name__}"
        users_summary.append(
            {
                "username": kv_user,
                "managers": [{"userId": uid, "mode": m, "new": len(f)} for uid, f, m in results],
                "newEvents": count,
                "delivered": delivered,
                "reason": reason,
            }
        )

    eligible = len(order)
    return {
        "enabled": True,
        "window": ALERT_WINDOW,
        "managersEligible": eligible,
        "managersRead": len(read),
        "skipped": skipped,
        "callsSpent": spent,
        "rateLimited": rate_limited,
        # Each manager is read about every ceil(eligible / max) daily runs;
        # slower than the 7-day window, events can age out unseen.
        "coverageGapPossible": eligible > max_managers * 7,
        "users": users_summary,
    }


def refresh_for_user(
    kv_user: str,
    *,
    contract: Any,
    activity_provider: Provider = ma.cached_manager_activity,
    path: Path | None = None,
    now: Callable[[], float] = time.time,
    max_managers: int = REFRESH_MAX_MANAGERS,
    call_budget_per_manager: int = SWEEP_CALL_BUDGET_PER_MANAGER,
) -> dict[str, Any]:
    """In-app check for one user: read up to ``max_managers`` of their saved
    managers (stalest first), evaluate them, and return what is new.  No
    email; what this returns counts as seen."""
    state = _user_kv.get_user_state(kv_user, path=path)
    entries = ms.entries_from_state(state)
    alerts = ms.alert_states(state)
    order = sorted(
        entries,
        key=lambda e: (int((alerts.get(e["userId"]) or {}).get("lastCheckedAt") or 0), e["userId"]),
    )
    checked = []
    rate_limited = False
    for entry in order[:max_managers]:
        uid = entry["userId"]
        payload = _read_activity(activity_provider, uid, contract, call_budget_per_manager)
        if payload.get("status") == mp.STATUS_RATE_LIMITED:
            rate_limited = True
            checked.append({"userId": uid, "mode": "rate_limited", "newEvents": []})
            break
        fresh, mode = detect_for_user(kv_user, uid, payload, path=path, now=now)
        checked.append(
            {
                "userId": uid,
                "displayName": entry.get("displayName") or entry.get("username"),
                "mode": mode,
                "status": payload.get("status"),
                "newEvents": fresh,
            }
        )
    return {
        "checked": checked,
        "remaining": max(0, len(entries) - len(checked)),
        "rateLimited": rate_limited,
        "window": ALERT_WINDOW,
        "note": (
            "Events reported here count as seen; the daily email will not repeat them. The "
            "first check of a manager records their recent activity without reporting it."
        ),
    }


__all__ = [
    "ALERT_WINDOW",
    "SNAPSHOT_STALE_MS",
    "build_snapshot",
    "detect_for_user",
    "evaluate",
    "format_email",
    "read_league_ids",
    "refresh_for_user",
    "run_sweep",
]
