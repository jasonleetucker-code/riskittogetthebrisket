"""User-level key/value persistence layer (SQLite-backed).

A tiny durable store keyed by authenticated username.  Replaces
scattered ``localStorage`` usage for state that should follow the
user across devices and sessions:

* ``selectedTeam``       — stable team identity (ownerId + name mirror)
* ``watchlist``          — array of player canonical names to watch
* ``dismissedSignals``   — ``{signalKey: expiresAtEpochMs}`` map;
                           entries older than now are auto-pruned on read
* ``dismissalAliases``   — ``{displayName: sleeperId}`` records the
                           sleeperId that was active at the moment a
                           signal was dismissed, so a later rename of
                           the player doesn't silently break the
                           dismissal (the UI can re-associate by
                           sleeperId).

Storage
───────
Single SQLite database at ``data/user_kv.sqlite``.  One row per
authenticated user; the full state blob is serialised as JSON in a
``state_json`` column plus an ``updated_at`` timestamp for
administration.

SQLite picks up three wins over the prior single-JSON-file store:

1. **Concurrent writes** — the DB serialises via its own locks; a
   burst of hooks firing simultaneously (e.g. many users dismissing
   signals at once) no longer races at the file-rename layer.
2. **Crash durability** — the prior store rewrote the whole file on
   every write; a process crash mid-write could truncate the file,
   and the corrupt-file handler (silently start fresh) discards
   every user's state.  SQLite's WAL + fsync-on-commit preserves
   partial writes cleanly.
3. **Row-level reads** — ``get_user_state(user)`` no longer loads
   every user's blob into memory just to read one; it reads the one
   row it needs.

Schema::

    CREATE TABLE user_state (
      username    TEXT PRIMARY KEY,
      state_json  TEXT NOT NULL,
      updated_at  TEXT NOT NULL
    );

All public call-sites take the same arguments as the prior JSON-
backed module; the migration is a pure drop-in.  Legacy
``data/user_kv.json`` files are imported once on first boot (see
``_migrate_legacy_json_if_present``).
"""
from __future__ import annotations

import json
import sqlite3
import time
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

USER_KV_PATH: Path = Path(__file__).resolve().parents[2] / "data" / "user_kv.sqlite"
_LEGACY_JSON_PATH: Path = Path(__file__).resolve().parents[2] / "data" / "user_kv.json"

# Known top-level keys we understand.  Anything else in a user's
# record is preserved but not validated.
KNOWN_KEYS = frozenset({
    "selectedTeam",
    "watchlist",
    "dismissedSignals",
    "dismissalAliases",
    "updatedAt",
})

# Process-wide lock around connection setup / migration so module
# import is thread-safe.  SQLite itself handles per-transaction
# locking.
_SETUP_LOCK = threading.Lock()
_SETUP_DONE: dict[str, bool] = {}


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _now_ms() -> int:
    return int(time.time() * 1000)


def _connect(path: Path | None = None) -> sqlite3.Connection:
    path = path or USER_KV_PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    _ensure_schema(path)
    # ``isolation_level=None`` + manual BEGIN/COMMIT would give us
    # explicit control, but for this blob-per-user workload the
    # default deferred-transaction mode is fine and simpler.  WAL
    # mode is set in ``_ensure_schema`` once per file.
    return sqlite3.connect(str(path), timeout=5.0)


def _ensure_schema(path: Path) -> None:
    """Create the schema + apply SQLite pragmas.  Idempotent.

    If the path already exists but isn't a valid SQLite database
    (e.g. a stray JSON blob or leftover text file), we rename it to
    ``<name>.corrupt`` and start fresh.  Matches the JSON-store
    era's "corrupt → start fresh" behaviour: a broken store must
    not brick every authenticated surface.
    """
    key = str(path)
    if _SETUP_DONE.get(key):
        return
    with _SETUP_LOCK:
        if _SETUP_DONE.get(key):
            return
        _open_or_reset(path)
        _migrate_legacy_json_if_present(path)
        _SETUP_DONE[key] = True


def _open_or_reset(path: Path) -> None:
    def _apply_schema(conn: sqlite3.Connection) -> None:
        conn.execute("PRAGMA journal_mode=WAL;")
        conn.execute("PRAGMA synchronous=NORMAL;")
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS user_state (
              username   TEXT PRIMARY KEY,
              state_json TEXT NOT NULL,
              updated_at TEXT NOT NULL
            )
            """
        )
        conn.commit()

    conn = sqlite3.connect(str(path), timeout=5.0)
    try:
        _apply_schema(conn)
        return
    except sqlite3.DatabaseError:
        conn.close()
        # The file exists but isn't valid SQLite — most likely a
        # leftover JSON store or a text file someone dropped into
        # ``data/``.  Rename it and rebuild.
        if path.exists():
            try:
                path.rename(path.with_suffix(path.suffix + ".corrupt"))
            except OSError:
                path.unlink(missing_ok=True)
        conn = sqlite3.connect(str(path), timeout=5.0)
        try:
            _apply_schema(conn)
        finally:
            conn.close()
        return
    finally:
        try:
            conn.close()
        except sqlite3.ProgrammingError:
            pass


def _migrate_legacy_json_if_present(path: Path) -> None:
    """One-shot migration from the pre-SQLite JSON store.

    If ``data/user_kv.json`` exists, read it, insert every user row
    into the SQLite DB (skipping users that already exist — the DB
    wins on conflict), and rename the legacy file to ``.migrated``
    so a second boot is a no-op.  Failures here are silent-and-
    logged: a broken migration shouldn't brick authenticated
    surfaces, and the legacy file is left in place so an operator
    can inspect it.
    """
    if not _LEGACY_JSON_PATH.exists():
        return
    if path != USER_KV_PATH:
        # Test paths don't share the legacy file — only migrate on
        # the real production location.
        return
    try:
        with _LEGACY_JSON_PATH.open("r", encoding="utf-8") as f:
            legacy = json.load(f)
    except (OSError, json.JSONDecodeError):
        return
    if not isinstance(legacy, dict):
        return

    conn = sqlite3.connect(str(path), timeout=5.0)
    try:
        for username, state in legacy.items():
            if not isinstance(username, str) or not isinstance(state, dict):
                continue
            state_json = json.dumps(state, separators=(",", ":"), ensure_ascii=False)
            conn.execute(
                "INSERT OR IGNORE INTO user_state (username, state_json, updated_at) "
                "VALUES (?, ?, ?)",
                (username, state_json, state.get("updatedAt") or _utc_now_iso()),
            )
        conn.commit()
    finally:
        conn.close()

    # Rename rather than delete so an operator can inspect in case
    # of a bad migration.
    try:
        _LEGACY_JSON_PATH.rename(_LEGACY_JSON_PATH.with_suffix(".json.migrated"))
    except OSError:
        pass


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


def _read_row(conn: sqlite3.Connection, username: str) -> dict[str, Any]:
    cursor = conn.execute(
        "SELECT state_json FROM user_state WHERE username = ?",
        (username,),
    )
    row = cursor.fetchone()
    if not row:
        return {}
    try:
        parsed = json.loads(row[0])
    except (json.JSONDecodeError, TypeError):
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _write_row(conn: sqlite3.Connection, username: str, entry: dict[str, Any]) -> None:
    entry["updatedAt"] = _utc_now_iso()
    state_json = json.dumps(entry, separators=(",", ":"), ensure_ascii=False)
    conn.execute(
        "INSERT INTO user_state (username, state_json, updated_at) "
        "VALUES (?, ?, ?) "
        "ON CONFLICT(username) DO UPDATE SET "
        "state_json=excluded.state_json, updated_at=excluded.updated_at",
        (username, state_json, entry["updatedAt"]),
    )
    conn.commit()


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
    conn = _connect(path)
    try:
        entry = _read_row(conn, username)
        if not entry:
            return {}
        if _prune_expired_dismissals(entry):
            try:
                _write_row(conn, username, entry)
            except sqlite3.Error:
                # Non-fatal: the read path returns the pruned in-
                # memory view; the next successful write persists.
                pass
        return dict(entry)
    finally:
        conn.close()


def set_user_field(
    username: str,
    field: str,
    value: Any,
    *,
    path: Path | None = None,
) -> dict[str, Any]:
    """Write a single top-level field for ``username``.

    Returns the post-write state blob so callers can echo the server
    view back to the client.  Unknown keys are accepted and preserved
    verbatim — future clients may rely on them.
    """
    if not username:
        return {}
    conn = _connect(path)
    try:
        entry = _read_row(conn, username)
        entry[str(field)] = value
        _prune_expired_dismissals(entry)
        _write_row(conn, username, entry)
        return dict(entry)
    finally:
        conn.close()


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
    ``dismissalAliases`` merges the same way.
    """
    if not username or not isinstance(patch, dict):
        return get_user_state(username, path=path)
    conn = _connect(path)
    try:
        entry = _read_row(conn, username)
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
            elif field == "dismissalAliases" and isinstance(value, dict):
                current = entry.get("dismissalAliases")
                current = current if isinstance(current, dict) else {}
                for k, v in value.items():
                    if v is None:
                        current.pop(str(k), None)
                    else:
                        current[str(k)] = str(v)
                entry["dismissalAliases"] = current
            else:
                entry[str(field)] = value
        _prune_expired_dismissals(entry)
        _write_row(conn, username, entry)
        return dict(entry)
    finally:
        conn.close()


def dismiss_signal(
    username: str,
    signal_key: str,
    *,
    ttl_ms: int = 7 * 24 * 3600 * 1000,
    alias_sleeper_id: str | None = None,
    alias_display_name: str | None = None,
    path: Path | None = None,
) -> dict[str, Any]:
    """Dismiss ``signal_key`` for ``ttl_ms`` milliseconds.

    Default TTL is 7 days — long enough that the user isn't pestered
    again on the next refresh but short enough that a stale
    dismissal doesn't permanently hide a re-armed signal.

    Optional ``alias_sleeper_id`` + ``alias_display_name`` record a
    rename-resistant mapping: the UI can pass the Sleeper ID of the
    player whose signal was dismissed, and when the player later
    appears under a different display name the dismissal can still
    be matched by looking up the alias.  Stored in a separate
    ``dismissalAliases`` map so the primary dismissal key (``name::
    tag``) stays a pure string key — existing consumers don't have
    to change.
    """
    if not username or not signal_key:
        return get_user_state(username, path=path)
    expires_at = _now_ms() + max(1_000, int(ttl_ms))
    patch: dict[str, Any] = {"dismissedSignals": {str(signal_key): expires_at}}
    if alias_sleeper_id and alias_display_name:
        patch["dismissalAliases"] = {str(alias_display_name): str(alias_sleeper_id)}
    return merge_user_state(username, patch, path=path)


def undismiss_signal(
    username: str,
    signal_key: str,
    *,
    path: Path | None = None,
) -> dict[str, Any]:
    """Remove a single dismissal (user chose to re-surface the signal)."""
    if not username or not signal_key:
        return get_user_state(username, path=path)
    conn = _connect(path)
    try:
        entry = _read_row(conn, username)
        dismissed = entry.get("dismissedSignals")
        if isinstance(dismissed, dict) and str(signal_key) in dismissed:
            dismissed.pop(str(signal_key), None)
            entry["dismissedSignals"] = dismissed
            _write_row(conn, username, entry)
        return dict(entry)
    finally:
        conn.close()


def active_dismissals(username: str, *, path: Path | None = None) -> dict[str, int]:
    """Return the ``{signalKey: expiresAtMs}`` dict with expireds pruned."""
    state = get_user_state(username, path=path)
    dismissed = state.get("dismissedSignals")
    if not isinstance(dismissed, dict):
        return {}
    return dict(dismissed)


def dismissal_aliases(username: str, *, path: Path | None = None) -> dict[str, str]:
    """Return the ``{displayName: sleeperId}`` alias map.

    Used by the frontend rename-tolerance pass: when a dismissal key
    encodes the OLD display name of a player, the UI looks up the
    corresponding Sleeper ID here and checks whether any live row
    has the same Sleeper ID under a new display name — if yes, the
    dismissal still applies.
    """
    state = get_user_state(username, path=path)
    aliases = state.get("dismissalAliases")
    if not isinstance(aliases, dict):
        return {}
    return {str(k): str(v) for k, v in aliases.items()}


def all_user_states(*, path: Path | None = None) -> dict[str, dict[str, Any]]:
    """Return every stored user's state, keyed by username.

    Used by admin / background jobs (e.g. the signal-alerts timer)
    that need to walk every user.  Expired dismissals are pruned
    per-row on read — cheap, and keeps the returned dict honest.
    The caller gets fresh copies so they can safely mutate without
    writing back.

    Returns an empty dict if the DB is missing or empty.
    """
    target = path or USER_KV_PATH
    # If the DB file doesn't exist yet (e.g. fresh install),
    # ``_connect`` will create it.  But if the parent dir also
    # doesn't exist and we aren't pointed at a temp path, that's
    # fine too — the create is idempotent.
    try:
        conn = _connect(target)
    except Exception:
        return {}
    try:
        rows = conn.execute("SELECT username, state_json FROM user_state").fetchall()
    except sqlite3.OperationalError:
        return {}
    finally:
        conn.close()

    out: dict[str, dict[str, Any]] = {}
    for username, state_json in rows:
        try:
            state = json.loads(state_json) if state_json else {}
        except (TypeError, ValueError):
            continue
        if not isinstance(state, dict):
            continue
        _prune_expired_dismissals(state)
        out[str(username)] = state
    return out
