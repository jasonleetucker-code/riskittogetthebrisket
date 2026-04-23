"""User-level key/value persistence layer.

A tiny, file-backed durable store keyed by authenticated username.
Replaces scattered ``localStorage`` usage for state that should
follow the user across devices and sessions:

* ``selectedTeam``      — stable team identity (ownerId + name mirror)
* ``watchlist``         — array of player canonical names to watch
* ``dismissedSignals``  — ``{signalKey: expiresAtEpochMs}`` map;
                          entries older than now are auto-pruned on read

Storage model
─────────────
Single JSON file at ``data/user_kv.json`` with shape::

    {
      "<username>": {
        "selectedTeam":    {"ownerId": "...", "name": "..."},
        "watchlist":       ["Ja'Marr Chase", ...],
        "dismissedSignals": {"<signalKey>": 1711234567890, ...},
        "updatedAt":       "2026-04-23T14:02:11Z"
      },
      ...
    }

Writes are atomic (temp file + rename).  The whole file is loaded on
each call — acceptable because the expected population is small
(tens of users, not thousands) and this avoids a database dependency
for what amounts to a preferences blob.

All mutations pass through ``_read_all`` → mutate → ``_write_all``
so concurrent writers race at the file-rename layer, which is
atomic on POSIX.  No locking is needed for the current scale; if
contention becomes an issue the whole module can drop behind an
asyncio.Lock held at the FastAPI layer.

Known fields are namespaced on read (anything we do not recognise is
preserved verbatim — we never clobber unknown keys that a future
client may have written but the current server doesn't understand).
"""
from __future__ import annotations

import json
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

USER_KV_PATH: Path = Path(__file__).resolve().parents[2] / "data" / "user_kv.json"

# Known top-level keys we understand.  Anything else in a user's
# record is preserved but not validated.
KNOWN_KEYS = frozenset({"selectedTeam", "watchlist", "dismissedSignals", "updatedAt"})


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _now_ms() -> int:
    return int(time.time() * 1000)


def _read_all(path: Path | None = None) -> dict[str, dict[str, Any]]:
    path = path or USER_KV_PATH
    if not path.exists():
        return {}
    try:
        with path.open("r", encoding="utf-8") as f:
            data = json.load(f)
        if isinstance(data, dict):
            return {str(k): (v if isinstance(v, dict) else {}) for k, v in data.items()}
    except (json.JSONDecodeError, OSError):
        # Corrupt file: start fresh rather than 500'ing every request.
        # The alternative (refusing writes until a human repairs it)
        # would silently brick every authenticated surface — worse UX
        # than starting empty.
        return {}
    return {}


def _write_all(store: dict[str, dict[str, Any]], path: Path | None = None) -> None:
    path = path or USER_KV_PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    with tmp.open("w", encoding="utf-8") as f:
        json.dump(store, f, ensure_ascii=False, separators=(",", ":"))
    tmp.replace(path)


def _prune_expired_dismissals(entry: dict[str, Any]) -> bool:
    """Drop ``dismissedSignals`` entries whose ``expiresAt`` passed.

    Returns True if any entry was pruned (caller can decide whether
    to persist the write).
    """
    dismissed = entry.get("dismissedSignals")
    if not isinstance(dismissed, dict) or not dismissed:
        return False
    now = _now_ms()
    pruned = False
    keep: dict[str, int] = {}
    for key, expires in dismissed.items():
        try:
            ts = int(expires)
        except (TypeError, ValueError):
            pruned = True
            continue
        if ts <= now:
            pruned = True
            continue
        keep[str(key)] = ts
    if pruned:
        entry["dismissedSignals"] = keep
    return pruned


def get_user_state(username: str, *, path: Path | None = None) -> dict[str, Any]:
    """Return the full state blob for ``username``.

    Expired dismissals are pruned on read.  The pruned state is
    persisted back so future reads are cheap.

    Always returns a dict — missing users surface as ``{}`` rather
    than raising, because the caller (frontend hook) expects a
    durable defaults path.
    """
    if not username:
        return {}
    store = _read_all(path)
    entry = store.get(username)
    if not isinstance(entry, dict):
        return {}
    if _prune_expired_dismissals(entry):
        store[username] = entry
        try:
            _write_all(store, path)
        except OSError:
            # Non-fatal: the read path returns the pruned in-memory
            # view; the next successful write will re-persist.
            pass
    return dict(entry)


def set_user_field(
    username: str,
    field: str,
    value: Any,
    *,
    path: Path | None = None,
) -> dict[str, Any]:
    """Write a single top-level field for ``username``.

    Returns the post-write state blob so callers can echo the server
    view back to the client (useful for the initial hydration round-
    trip).  Unknown keys are accepted and preserved verbatim — future
    clients may rely on them.
    """
    if not username:
        return {}
    store = _read_all(path)
    entry = store.get(username)
    if not isinstance(entry, dict):
        entry = {}
    entry[str(field)] = value
    entry["updatedAt"] = _utc_now_iso()
    # Pruning happens here too so a write doesn't preserve stale
    # dismissals into the next read.
    _prune_expired_dismissals(entry)
    store[username] = entry
    _write_all(store, path)
    return dict(entry)


def merge_user_state(
    username: str,
    patch: dict[str, Any],
    *,
    path: Path | None = None,
) -> dict[str, Any]:
    """Shallow-merge ``patch`` onto ``username``'s state.

    ``None`` values in the patch are treated as deletes for that
    field.  Dismissed-signal entries use dict-merge semantics so a
    patch can add keys without losing unrelated dismissals.
    """
    if not username or not isinstance(patch, dict):
        return get_user_state(username, path=path)
    store = _read_all(path)
    entry = store.get(username)
    if not isinstance(entry, dict):
        entry = {}
    for field, value in patch.items():
        if value is None:
            entry.pop(str(field), None)
            continue
        if field == "dismissedSignals" and isinstance(value, dict):
            current = entry.get("dismissedSignals")
            current = current if isinstance(current, dict) else {}
            for k, v in value.items():
                try:
                    current[str(k)] = int(v)
                except (TypeError, ValueError):
                    continue
            entry["dismissedSignals"] = current
        else:
            entry[str(field)] = value
    entry["updatedAt"] = _utc_now_iso()
    _prune_expired_dismissals(entry)
    store[username] = entry
    _write_all(store, path)
    return dict(entry)


def dismiss_signal(
    username: str,
    signal_key: str,
    *,
    ttl_ms: int = 7 * 24 * 3600 * 1000,
    path: Path | None = None,
) -> dict[str, Any]:
    """Dismiss ``signal_key`` for ``ttl_ms`` milliseconds.

    Default TTL is 7 days — long enough that the user isn't pestered
    again on the next refresh but short enough that a stale
    dismissal doesn't permanently hide a re-armed signal.
    """
    if not username or not signal_key:
        return get_user_state(username, path=path)
    expires_at = _now_ms() + max(1_000, int(ttl_ms))
    return merge_user_state(
        username,
        {"dismissedSignals": {str(signal_key): expires_at}},
        path=path,
    )


def undismiss_signal(
    username: str,
    signal_key: str,
    *,
    path: Path | None = None,
) -> dict[str, Any]:
    """Remove a single dismissal (user chose to re-surface the signal)."""
    if not username or not signal_key:
        return get_user_state(username, path=path)
    store = _read_all(path)
    entry = store.get(username)
    if not isinstance(entry, dict):
        return {}
    dismissed = entry.get("dismissedSignals")
    if isinstance(dismissed, dict) and str(signal_key) in dismissed:
        dismissed.pop(str(signal_key), None)
        entry["dismissedSignals"] = dismissed
        entry["updatedAt"] = _utc_now_iso()
        store[username] = entry
        _write_all(store, path)
    return dict(entry)


def active_dismissals(username: str, *, path: Path | None = None) -> dict[str, int]:
    """Return the ``{signalKey: expiresAtMs}`` dict with expireds pruned."""
    state = get_user_state(username, path=path)
    dismissed = state.get("dismissedSignals")
    if not isinstance(dismissed, dict):
        return {}
    return dict(dismissed)
