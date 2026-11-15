"""Manager Intelligence Batch F — saved managers (per signed-in user).

A signed-in user keeps a short list of Sleeper managers to follow.  The list
lives in ``user_kv`` under :data:`SAVED_FIELD`, one blob per user (the same
store the watchlist and Trade Desk use), and is written only through
:func:`save_manager` / :func:`remove_manager` under the user_kv write lock.

Identity is the manager's PERMANENT Sleeper ``user_id``, never the username:
Sleeper lets a manager rename, and a username can later be taken by someone
else.  The stored ``username`` / ``displayName`` are a display mirror only.
:func:`list_saved` re-reads each manager by id (memoised per process) and
refreshes the mirror, so a rename keeps the entry and shows the new name; the
names the manager used before are kept in ``previousUsernames``.  When the
re-read fails, the stored name is served with ``nameState`` saying so — it is
never presented as freshly verified.

Activity-alert state for each saved manager lives beside it under
:data:`ALERT_FIELD` (owned by :mod:`src.intel.manager_alerts`); removing a
manager removes that state too, so re-saving later baseline-seeds again.
"""

from __future__ import annotations

import re
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any, Callable

from src.api import user_kv as _user_kv
from src.public_league import sleeper_client

#: user_kv field holding ``{"managers": [entry, ...]}``.
SAVED_FIELD = "managerIntelSaved"
#: user_kv field holding ``{userId: alert state}`` (see manager_alerts).
ALERT_FIELD = "managerIntelAlertState"

#: Per-user cap.  Every saved manager may be read by the daily alert sweep,
#: so the cap bounds Sleeper calls as much as it bounds storage.
MAX_SAVED = 50
#: How many former usernames are remembered per entry.
MAX_PREVIOUS_USERNAMES = 5

#: A successful by-id re-read is reused for an hour; a failed one for a
#: minute, so a Sleeper outage is not hammered by every page load.
NAME_TTL_SECONDS = 60 * 60
NAME_FAILURE_TTL_SECONDS = 60
NAME_WORKERS = 4

USER_ID_RE = re.compile(r"^\d{1,24}$")

#: ``nameState`` values.
NAME_CURRENT = "current"  # re-read by id within NAME_TTL_SECONDS
NAME_STORED = "stored"  # the re-read failed (rate limit / error): stored mirror
NAME_NOT_FOUND = "not_found"  # Sleeper no longer knows this id
NAME_ID_MISMATCH = "id_mismatch"  # Sleeper answered for a different id

Fetch = Callable[[str], tuple[str, Any]]


class SavedError(Exception):
    """A refused write: ``code`` is the API error code."""

    def __init__(self, code: str, detail: Any = None) -> None:
        super().__init__(code)
        self.code = code
        self.detail = detail


def _now_ms(now: Callable[[], float]) -> int:
    return int(now() * 1000)


def entries_from_state(state: dict[str, Any] | None) -> list[dict[str, Any]]:
    """The valid saved entries in ``state``, in saved order (copies)."""
    block = (state or {}).get(SAVED_FIELD)
    raw = block.get("managers") if isinstance(block, dict) else None
    out: list[dict[str, Any]] = []
    seen: set[str] = set()
    for item in raw if isinstance(raw, list) else []:
        if not isinstance(item, dict):
            continue
        uid = str(item.get("userId") or "")
        if not USER_ID_RE.match(uid) or uid in seen:
            continue
        seen.add(uid)
        out.append(dict(item))
    return out


def alert_states(state: dict[str, Any] | None) -> dict[str, dict[str, Any]]:
    block = (state or {}).get(ALERT_FIELD)
    if not isinstance(block, dict):
        return {}
    return {str(k): v for k, v in block.items() if isinstance(v, dict)}


def _write_entries(state: dict[str, Any], entries: list[dict[str, Any]]) -> None:
    # ``nameState`` describes ONE response (was the name re-read just now?);
    # it is never persisted, so a stored entry cannot claim a fresh read.
    state[SAVED_FIELD] = {
        "version": 1,
        "managers": [{k: v for k, v in e.items() if k != "nameState"} for e in entries],
    }


def _apply_names(entry: dict[str, Any], user: dict[str, Any], now_ms: int) -> bool:
    """Refresh the display mirror from a Sleeper user object; ``True`` when
    anything changed.  A changed username is remembered."""
    username = str(user.get("username") or "").strip() or None
    display = str(user.get("display_name") or "").strip() or username
    changed = False
    old = entry.get("username")
    if username and old and old.lower() != username.lower():
        prev = [p for p in entry.get("previousUsernames") or [] if isinstance(p, str)]
        prev = [p for p in prev if p.lower() != old.lower() and p.lower() != username.lower()]
        entry["previousUsernames"] = [old, *prev][:MAX_PREVIOUS_USERNAMES]
        changed = True
    if username and entry.get("username") != username:
        entry["username"] = username
        changed = True
    if display and entry.get("displayName") != display:
        entry["displayName"] = display
        changed = True
    entry["nameCheckedAt"] = now_ms
    return changed


def _entry_from_user(user: dict[str, Any], *, alerts: bool, now_ms: int) -> dict[str, Any]:
    entry: dict[str, Any] = {
        "userId": str(user["user_id"]),
        "username": None,
        "displayName": None,
        "savedAt": now_ms,
        "alerts": bool(alerts),
        "previousUsernames": [],
    }
    _apply_names(entry, user, now_ms)
    return entry


def save_manager(
    kv_user: str,
    user: dict[str, Any],
    *,
    alerts: bool | None = None,
    path: Path | None = None,
    now: Callable[[], float] = time.time,
) -> tuple[dict[str, Any], bool, list[dict[str, Any]]]:
    """Save (or update) one manager for ``kv_user``.

    ``user`` is the Sleeper user object the ROUTE resolved (never a
    client-supplied name).  Returns ``(entry, created, entries)``.  Saving a
    manager already on the list refreshes its names (and ``alerts`` when
    given) and is not a second entry.  Raises :class:`SavedError`
    ``saved_limit_reached`` at :data:`MAX_SAVED`.
    """
    uid = str((user or {}).get("user_id") or "")
    if not USER_ID_RE.match(uid):
        raise SavedError("invalid_user")
    now_ms = _now_ms(now)
    result: list[Any] = []

    def _mutate(state: dict[str, Any]) -> None:
        result.clear()
        entries = entries_from_state(state)
        for entry in entries:
            if entry["userId"] == uid:
                _apply_names(entry, user, now_ms)
                if alerts is not None:
                    entry["alerts"] = bool(alerts)
                _write_entries(state, entries)
                entry["nameState"] = NAME_CURRENT
                result.extend([dict(entry), False, entries])
                return
        if len(entries) >= MAX_SAVED:
            raise SavedError("saved_limit_reached", {"limit": MAX_SAVED})
        entry = _entry_from_user(user, alerts=True if alerts is None else alerts, now_ms=now_ms)
        entries.append(entry)
        _write_entries(state, entries)
        entry["nameState"] = NAME_CURRENT
        result.extend([dict(entry), True, entries])

    _user_kv.mutate_user_state(kv_user, _mutate, path=path)
    return result[0], result[1], result[2]


def remove_manager(
    kv_user: str, user_id: str, *, path: Path | None = None
) -> tuple[bool, list[dict[str, Any]]]:
    """Remove one saved manager and its alert state.  ``(removed, entries)``;
    removing a manager that is not saved is not an error."""
    uid = str(user_id or "")
    result: list[Any] = []

    def _mutate(state: dict[str, Any]) -> None:
        result.clear()
        entries = entries_from_state(state)
        kept = [e for e in entries if e["userId"] != uid]
        removed = len(kept) != len(entries)
        if removed:
            _write_entries(state, kept)
        alerts = alert_states(state)
        if uid in alerts:
            alerts.pop(uid)
            state[ALERT_FIELD] = alerts
        result.extend([removed, kept])

    _user_kv.mutate_user_state(kv_user, _mutate, path=path)
    return result[0], result[1]


# ── by-id name refresh (memoised per process) ───────────────────────────

_name_memo: dict[str, tuple[float, str, Any]] = {}
_name_lock = threading.Lock()


def resolve_user(
    handle: str, *, fetch_user: Fetch, now: Callable[[], float] = time.time
) -> tuple[str, Any]:
    """``(kind, user)`` for a username or user id through the per-process
    memo (``kind`` is a ``sleeper_client.FETCH_*``)."""
    key = str(handle or "").strip().lower()
    t = now()
    with _name_lock:
        hit = _name_memo.get(key)
        if hit is not None:
            ttl = (
                NAME_TTL_SECONDS if hit[1] == sleeper_client.FETCH_OK else NAME_FAILURE_TTL_SECONDS
            )
            if t - hit[0] < ttl:
                return hit[1], hit[2]
    kind, user = fetch_user(handle)
    with _name_lock:
        if len(_name_memo) > 4096:
            _name_memo.clear()
        _name_memo[key] = (t, kind, user)
        if kind == sleeper_client.FETCH_OK and isinstance(user, dict) and user.get("user_id"):
            _name_memo[str(user["user_id"])] = (t, kind, user)
    return kind, user


def reset_name_memo() -> None:
    with _name_lock:
        _name_memo.clear()


def _name_state(uid: str, kind: str, user: Any) -> str:
    if kind == sleeper_client.FETCH_OK:
        if isinstance(user, dict) and str(user.get("user_id") or "") == uid:
            return NAME_CURRENT
        return NAME_ID_MISMATCH
    if kind == sleeper_client.FETCH_NOT_FOUND:
        return NAME_NOT_FOUND
    return NAME_STORED


def _public_entry(entry: dict[str, Any], alert: dict[str, Any] | None) -> dict[str, Any]:
    alert = alert or {}
    snapshot = alert.get("snapshot") if isinstance(alert.get("snapshot"), dict) else None
    return {
        "userId": entry["userId"],
        "username": entry.get("username"),
        "displayName": entry.get("displayName") or entry.get("username"),
        "previousUsernames": list(entry.get("previousUsernames") or []),
        "savedAt": entry.get("savedAt"),
        "alerts": entry.get("alerts") is not False,
        "nameState": entry.get("nameState") or NAME_STORED,
        "nameCheckedAt": entry.get("nameCheckedAt"),
        "alertState": {
            "seeded": bool(alert.get("seededAt")),
            "seededAt": alert.get("seededAt"),
            "lastCheckedAt": alert.get("lastCheckedAt"),
            "lastStatus": alert.get("lastStatus"),
            "lastAlertAt": alert.get("lastAlertAt"),
            "lastNewCount": alert.get("lastNewCount"),
            "snapshotAsOf": snapshot.get("asOf") if snapshot else None,
        },
    }


def saved_payload(
    entries: list[dict[str, Any]], alerts: dict[str, dict[str, Any]]
) -> dict[str, Any]:
    return {
        "managers": [_public_entry(e, alerts.get(e["userId"])) for e in entries],
        "count": len(entries),
        "limit": MAX_SAVED,
        "identity": (
            "Saved managers are keyed by their permanent Sleeper user id; the username shown "
            "is re-read from Sleeper, so a rename keeps the entry."
        ),
    }


def list_saved(
    kv_user: str,
    *,
    fetch_user: Fetch = sleeper_client.fetch_user_classified,
    path: Path | None = None,
    now: Callable[[], float] = time.time,
    refresh_names: bool = True,
) -> dict[str, Any]:
    """The user's saved managers with each display name re-read by id.

    Names that changed are written back (the mirror is a cache of Sleeper,
    keyed by the id).  A failed re-read leaves the stored name in place with
    ``nameState`` ``stored`` / ``not_found`` / ``id_mismatch``.
    """
    state = _user_kv.get_user_state(kv_user, path=path)
    entries = entries_from_state(state)
    alerts = alert_states(state)
    if not entries or not refresh_names:
        return saved_payload(entries, alerts)

    now_ms = _now_ms(now)
    with ThreadPoolExecutor(max_workers=max(1, min(NAME_WORKERS, len(entries)))) as pool:
        answers = list(
            pool.map(
                lambda e: resolve_user(e["userId"], fetch_user=fetch_user, now=now),
                entries,
            )
        )
    renamed: dict[str, dict[str, Any]] = {}
    for entry, (kind, user) in zip(entries, answers):
        entry["nameState"] = _name_state(entry["userId"], kind, user)
        if entry["nameState"] == NAME_CURRENT:
            before = (entry.get("username"), entry.get("displayName"))
            _apply_names(entry, user, now_ms)
            if (entry.get("username"), entry.get("displayName")) != before:
                renamed[entry["userId"]] = user

    if renamed:

        def _mutate(current: dict[str, Any]) -> None:
            fresh = entries_from_state(current)
            for e in fresh:
                user = renamed.get(e["userId"])
                if user is not None:
                    _apply_names(e, user, now_ms)
            _write_entries(current, fresh)

        try:
            _user_kv.mutate_user_state(kv_user, _mutate, path=path)
        except Exception:  # noqa: BLE001 — the served list is already refreshed
            pass
    return saved_payload(entries, alerts)


__all__ = [
    "ALERT_FIELD",
    "MAX_SAVED",
    "SAVED_FIELD",
    "SavedError",
    "alert_states",
    "entries_from_state",
    "list_saved",
    "remove_manager",
    "resolve_user",
    "save_manager",
    "saved_payload",
]
