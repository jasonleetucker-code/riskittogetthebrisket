"""Persistent session store — SQLite-backed sessions that survive
deploy/restart cycles.

Problem solved
--------------
The in-memory ``auth_sessions: dict`` in ``server.py`` gets wiped
on every process restart (every deploy, every crash).  Users
have to sign back in after each of the 5-8 deploys/day.

Design
------
* Write-through cache: in-memory dict remains the hot path so
  ``/api/data`` reads don't hit disk.  SQLite is the persistence
  layer — written on session create/clear, read once on startup
  to hydrate the in-memory dict.
* TTL: sessions expire after ``SESSION_TTL_DAYS`` days (default
  30) of *inactivity* — the window slides off ``last_seen_at``,
  which every authenticated request bumps (throttled) via
  ``touch``.  An actively-used session never expires; only an
  idle one does.  Matches the cookie ``max_age`` for a fresh
  login.
* Invalidation on allowlist removal: every session row stores the
  session's ``username``.  On hydrate, a session is dropped only
  when *its own* username is no longer in the current allowlist —
  so removing one user signs out only that user, while adding a
  user leaves every existing session intact.  An empty / unset
  allowlist is treated as "no restriction" and never invalidates
  (prevents a mis-deployed empty env var from logging everyone
  out).  ``allowlist_version`` is still recorded for audit.
* Corruption fallback: every call is wrapped in broad try/except;
  any SQLite error → in-memory dict continues working (existing
  behavior, no regression).

Integration
-----------
``server.py`` imports ``session_store`` and wraps its existing
dict writes.  The auth path stays identical in shape so every
existing code-reading session fields (``session.get("username")``)
continues to work unchanged.
"""

from __future__ import annotations

import hashlib
import logging
import os
import sqlite3
import threading
import time
from pathlib import Path
from typing import Any, Iterable

_LOGGER = logging.getLogger(__name__)

_DEFAULT_DB_PATH = Path(__file__).resolve().parents[2] / "data" / "session_store.sqlite"
_TABLE = "auth_sessions"
_SESSION_TTL_SECONDS = float(os.getenv("SESSION_TTL_DAYS", "30")) * 86400.0

_db_lock = threading.RLock()
_setup_done = threading.Event()


def _connect(path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(
        str(path),
        timeout=5.0,
        isolation_level=None,
        check_same_thread=False,
    )
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")
    return conn


def _setup(path: Path) -> None:
    """Idempotent schema bootstrap."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with _db_lock:
        conn = _connect(path)
        try:
            conn.execute(f"""
                CREATE TABLE IF NOT EXISTS {_TABLE} (
                    session_id TEXT PRIMARY KEY,
                    username TEXT NOT NULL,
                    sleeper_user_id TEXT NOT NULL DEFAULT '',
                    display_name TEXT NOT NULL DEFAULT '',
                    avatar TEXT NOT NULL DEFAULT '',
                    auth_method TEXT NOT NULL DEFAULT 'password',
                    allowlist_version TEXT NOT NULL DEFAULT '',
                    created_at REAL NOT NULL,
                    last_seen_at REAL NOT NULL
                )
            """)
            conn.execute(
                f"CREATE INDEX IF NOT EXISTS idx_{_TABLE}_created " f"ON {_TABLE}(created_at)"
            )
            # Additive migration: a time-bounded (guest-pass) session's own
            # expiry and the pass that minted it.  Rows written before these
            # columns existed read back NULL; ``hydrate`` refuses a guest
            # row without them rather than resurrecting it unbounded.
            have = {r[1] for r in conn.execute(f"PRAGMA table_info({_TABLE})").fetchall()}
            for column, decl in (("expires_at_epoch", "REAL"), ("guest_pass_id", "INTEGER")):
                if column in have:
                    continue
                try:
                    conn.execute(f"ALTER TABLE {_TABLE} ADD COLUMN {column} {decl}")
                except sqlite3.OperationalError as exc:
                    # Another process (the revoke CLI, a second worker)
                    # migrated between our PRAGMA and our ALTER.
                    if "duplicate column" not in str(exc).lower():
                        raise
        finally:
            conn.close()
    _setup_done.set()


def _allowlist_version(allowlist: Iterable[str] | None) -> str:
    """Stable hash of the allowlist — recorded per row for audit."""
    items = sorted({s.strip().lower() for s in (allowlist or []) if s})
    raw = ",".join(items).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()[:16]


def _allowlist_set(allowlist: Iterable[str] | None) -> set[str] | None:
    """Normalised set of allowed usernames, or ``None`` when the
    allowlist is empty / unset.

    ``None`` means "no restriction" — hydrate keeps every session.
    A non-empty set means "keep only sessions whose username is a
    member", so removing a user invalidates only that user.
    """
    items = {s.strip().lower() for s in (allowlist or []) if s and s.strip()}
    return items or None


def _positive_float(value: Any) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or value <= 0:
        return None
    return float(value)


def _positive_int(value: Any) -> int | None:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        return None
    return int(value)


def persist(
    session_id: str,
    payload: dict[str, Any],
    *,
    allowlist: Iterable[str] | None = None,
    db_path: Path | None = None,
) -> None:
    """Write a new / updated session row.  Safe to call repeatedly
    (upsert)."""
    path = db_path or _DEFAULT_DB_PATH
    if not _setup_done.is_set():
        try:
            _setup(path)
        except Exception as exc:  # noqa: BLE001
            _LOGGER.warning("session_store setup failed: %s", exc)
            return
    now = time.time()
    row = (
        str(session_id),
        str(payload.get("username") or ""),
        str(payload.get("sleeper_user_id") or ""),
        str(payload.get("display_name") or ""),
        str(payload.get("avatar") or ""),
        str(payload.get("auth_method") or "password"),
        _allowlist_version(allowlist),
        float(payload.get("created_at_epoch") or now),
        now,
        _positive_float(payload.get("expires_at_epoch")),
        _positive_int(payload.get("guest_pass_id")),
    )
    try:
        with _db_lock:
            conn = _connect(path)
            try:
                conn.execute(
                    f"INSERT INTO {_TABLE} "
                    f"(session_id, username, sleeper_user_id, display_name, "
                    f"avatar, auth_method, allowlist_version, created_at, last_seen_at, "
                    f"expires_at_epoch, guest_pass_id) "
                    f"VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?) "
                    f"ON CONFLICT(session_id) DO UPDATE SET "
                    f"last_seen_at=excluded.last_seen_at, "
                    f"allowlist_version=excluded.allowlist_version",
                    row,
                )
            finally:
                conn.close()
    except Exception as exc:  # noqa: BLE001
        _LOGGER.warning("session_store persist failed: %s", exc)


def touch(session_id: str, *, db_path: Path | None = None) -> None:
    """Bump ``last_seen_at`` to now so an active session's sliding
    TTL keeps sliding.  A no-op for unknown session ids.  Best-effort:
    any SQLite error is swallowed (auth still works in-memory)."""
    path = db_path or _DEFAULT_DB_PATH
    if not _setup_done.is_set():
        try:
            _setup(path)
        except Exception as exc:  # noqa: BLE001
            _LOGGER.warning("session_store touch setup failed: %s", exc)
            return
    try:
        with _db_lock:
            conn = _connect(path)
            try:
                conn.execute(
                    f"UPDATE {_TABLE} SET last_seen_at = ? WHERE session_id = ?",
                    (time.time(), str(session_id)),
                )
            finally:
                conn.close()
    except Exception as exc:  # noqa: BLE001
        _LOGGER.warning("session_store touch failed: %s", exc)


def evict(session_id: str, *, db_path: Path | None = None) -> None:
    """Remove a session (user logged out)."""
    path = db_path or _DEFAULT_DB_PATH
    if not _setup_done.is_set():
        try:
            _setup(path)
        except Exception as exc:  # noqa: BLE001
            _LOGGER.warning("session_store evict setup failed: %s", exc)
            return
    try:
        with _db_lock:
            conn = _connect(path)
            try:
                conn.execute(
                    f"DELETE FROM {_TABLE} WHERE session_id = ?",
                    (str(session_id),),
                )
            finally:
                conn.close()
    except Exception as exc:  # noqa: BLE001
        _LOGGER.warning("session_store evict failed: %s", exc)


def hydrate(
    *,
    allowlist: Iterable[str] | None = None,
    db_path: Path | None = None,
) -> dict[str, dict[str, Any]]:
    """Load every non-expired, still-allowed session into an
    in-memory dict — call once at startup.

    A session is dropped (and removed from disk) when either:
      * it has been idle longer than the TTL (``last_seen_at``
        older than the cutoff — a sliding window), or
      * its ``username`` is no longer in the current allowlist.

    An empty / unset allowlist imposes no membership restriction,
    so a mis-deployed blank env var can't sign everyone out.
    """
    path = db_path or _DEFAULT_DB_PATH
    if not _setup_done.is_set():
        try:
            _setup(path)
        except Exception as exc:  # noqa: BLE001
            _LOGGER.warning("session_store setup on hydrate failed: %s", exc)
            return {}

    allowed = _allowlist_set(allowlist)
    cutoff = time.time() - _SESSION_TTL_SECONDS
    out: dict[str, dict[str, Any]] = {}
    expired_ids: list[str] = []
    try:
        with _db_lock:
            conn = _connect(path)
            try:
                rows = conn.execute(
                    f"SELECT session_id, username, sleeper_user_id, display_name, "
                    f"avatar, auth_method, allowlist_version, created_at, last_seen_at, "
                    f"expires_at_epoch, guest_pass_id "
                    f"FROM {_TABLE}"
                ).fetchall()
            finally:
                conn.close()
        now = time.time()
        for sid, user, sluid, dn, av, am, ver, created, last, expires, pass_id in rows:
            # A time-bounded session never outlives its own expiry.
            if expires is not None and float(expires) <= now:
                expired_ids.append(sid)
                continue
            # A guest-pass session is only as good as the pass that minted
            # it: without its expiry AND pass id it cannot be bounded or
            # revoked, so it is dropped (fail closed).  Rows persisted
            # before these columns existed are exactly this case — they
            # used to hydrate as unbounded 30-day sessions.
            if str(am or "") == "guest_pass" and (expires is None or pass_id is None):
                expired_ids.append(sid)
                continue
            # Sliding TTL — expire on idle time, not age.  Fall back
            # to created_at for legacy rows written before touch().
            last_active = last if last and last > 0 else created
            if last_active < cutoff:
                expired_ids.append(sid)
                continue
            if allowed is not None and str(user or "").strip().lower() not in allowed:
                expired_ids.append(sid)
                continue
            out[sid] = {
                "username": user,
                "sleeper_user_id": sluid,
                "display_name": dn,
                "avatar": av,
                "auth_method": am,
                "created_at": time.strftime(
                    "%Y-%m-%dT%H:%M:%S+00:00",
                    time.gmtime(created),
                ),
                "created_at_epoch": created,
                "last_seen_epoch": last_active,
            }
            if expires is not None:
                out[sid]["expires_at_epoch"] = float(expires)
            if pass_id is not None:
                out[sid]["guest_pass_id"] = int(pass_id)
        if expired_ids:
            with _db_lock:
                conn = _connect(path)
                try:
                    conn.executemany(
                        f"DELETE FROM {_TABLE} WHERE session_id = ?",
                        [(sid,) for sid in expired_ids],
                    )
                finally:
                    conn.close()
    except Exception as exc:  # noqa: BLE001
        _LOGGER.warning("session_store hydrate failed: %s", exc)
        return {}
    return out


def evict_guest_pass(pass_id: int, *, db_path: Path | None = None) -> int:
    """Remove every persisted session minted from guest pass ``pass_id``.

    Called by ``guest_passes.revoke``.  Returns the number of rows
    removed (0 on any error — the pass row stays the authority, and
    ``server._get_auth_session`` refuses a revoked pass's session on its
    next request regardless)."""
    path = db_path or _DEFAULT_DB_PATH
    if not _setup_done.is_set():
        try:
            _setup(path)
        except Exception as exc:  # noqa: BLE001
            _LOGGER.warning("session_store evict_guest_pass setup failed: %s", exc)
            return 0
    try:
        with _db_lock:
            conn = _connect(path)
            try:
                cur = conn.execute(
                    f"DELETE FROM {_TABLE} WHERE guest_pass_id = ?",
                    (int(pass_id),),
                )
                # DELETE always reports a count >= 0 (autocommit connection).
                return max(0, cur.rowcount)
            finally:
                conn.close()
    except Exception as exc:  # noqa: BLE001
        _LOGGER.warning("session_store evict_guest_pass failed: %s", exc)
        return 0


def ro_sqlite_uri(path: Path) -> str:
    """A sqlite ``mode=ro`` URI with the path properly escaped.

    ``f"file:{path}?mode=ro"`` breaks on a path holding ``?``, ``#`` or
    ``%`` (the remainder would be parsed as URI query/fragment); ``as_uri``
    percent-encodes it.  Content read-only: sqlite may still create the
    ``-wal``/``-shm`` side files of a WAL database."""
    return Path(path).resolve().as_uri() + "?mode=ro"


#: The two columns a guest-pass session needs to be bounded and revocable.
_GUEST_IDENTITY_COLUMNS = ("expires_at_epoch", "guest_pass_id")


def guest_session_census(
    *,
    db_path: Path | None = None,
    guest_pass_db_path: Path | None = None,
) -> dict[str, Any]:
    """Count-only census of the persisted sessions — the production
    acceptance evidence for the 2026-10-08 guest-session fix.  Content
    read-only (sqlite ``mode=ro``; may create ``-wal``/``-shm``).

    Never calls ``_setup``: migrating here would make
    ``schemaHasGuestColumns`` true by construction and so prove nothing.
    Returns counts and booleans only — no session id, username, cookie or
    pass id ever leaves this function.

    MISSING IS NEVER ZERO: an absent or unreadable store reports ``None``
    counts, and a guest row whose pass cannot be looked up makes the
    pass-state counts ``None`` rather than 0.

    Keys:

    * ``guestSessionsMissingPassIdentity`` — ``auth_method = guest_pass``
      without an expiry or a pass id.  Such a row cannot be bounded or
      revoked; startup hydrate drops it and the per-request check refuses it.
    * ``guestSessionsPassRevoked`` — rows minted from a revoked pass
      (``guest_passes.revoke`` deletes them).
    * ``guestSessionsLiveWithInactivePass`` — rows whose OWN expiry is still
      in the future but whose pass is expired or no longer in the store.
    * ``guestSessionsExpiredAwaitingCleanup`` — rows past their own expiry
      (and not revoked).  Inert: hydrate and ``_get_auth_session`` both
      refuse them; they leave disk at the next restart or request.
    """
    path = db_path or _DEFAULT_DB_PATH
    unknown: dict[str, Any] = {
        "storePresent": path.exists(),
        "schemaHasGuestColumns": None,
        "totalSessions": None,
        "guestSessions": None,
        "guestSessionsMissingPassIdentity": None,
        "guestSessionsPassRevoked": None,
        "guestSessionsLiveWithInactivePass": None,
        "guestSessionsExpiredAwaitingCleanup": None,
        "passStoreReadable": None,
    }
    if not unknown["storePresent"]:
        return unknown
    try:
        conn = sqlite3.connect(ro_sqlite_uri(path), uri=True)
        try:
            columns = {r[1] for r in conn.execute(f"PRAGMA table_info({_TABLE})").fetchall()}
            if not columns:
                return unknown
            has_guest_columns = all(c in columns for c in _GUEST_IDENTITY_COLUMNS)
            total = int(conn.execute(f"SELECT COUNT(*) FROM {_TABLE}").fetchone()[0])
            select = "expires_at_epoch, guest_pass_id" if has_guest_columns else "NULL, NULL"
            guest_rows = conn.execute(
                f"SELECT {select} FROM {_TABLE} WHERE auth_method = 'guest_pass'"
            ).fetchall()
        finally:
            conn.close()
    except sqlite3.Error as exc:
        _LOGGER.warning("session_store guest_session_census failed: %s", exc)
        return unknown

    missing = 0
    bounded: list[tuple[float, int]] = []
    for expires, pass_id in guest_rows:
        exp = _positive_float(expires)
        pid = _positive_int(pass_id)
        if exp is None or pid is None:
            missing += 1
        else:
            bounded.append((exp, pid))

    out = dict(unknown)
    out.update(
        schemaHasGuestColumns=has_guest_columns,
        totalSessions=total,
        guestSessions=len(guest_rows),
        guestSessionsMissingPassIdentity=missing,
    )
    from src.api import guest_passes  # noqa: PLC0415 — guest_passes imports us lazily

    # Always read (even with nothing to classify) so ``passStoreReadable``
    # is a real true/false observation whenever the session store was read.
    states = guest_passes.read_only_pass_states(
        [pid for _, pid in bounded], db_path=guest_pass_db_path
    )
    out["passStoreReadable"] = states is not None
    if not bounded:
        # Nothing to classify: these zeros are observed, whatever the pass
        # store's state.
        out.update(
            guestSessionsPassRevoked=0,
            guestSessionsLiveWithInactivePass=0,
            guestSessionsExpiredAwaitingCleanup=0,
        )
        return out
    if states is None:
        return out
    now = time.time()
    revoked = live_inactive = awaiting = 0
    for exp, pid in bounded:
        state = states.get(pid)  # None: purged / never minted
        if state == "revoked":
            revoked += 1
        elif exp <= now:
            awaiting += 1
        elif state != "active":
            live_inactive += 1
    out.update(
        guestSessionsPassRevoked=revoked,
        guestSessionsLiveWithInactivePass=live_inactive,
        guestSessionsExpiredAwaitingCleanup=awaiting,
    )
    return out


def force_clear_all(*, db_path: Path | None = None) -> int:
    """Emergency sign-out-everyone hammer.  Returns count evicted."""
    path = db_path or _DEFAULT_DB_PATH
    if not _setup_done.is_set():
        try:
            _setup(path)
        except Exception as exc:  # noqa: BLE001
            _LOGGER.warning("session_store force_clear setup failed: %s", exc)
            return 0
    try:
        with _db_lock:
            conn = _connect(path)
            try:
                cursor = conn.execute(f"DELETE FROM {_TABLE}")
                return cursor.rowcount or 0
            finally:
                conn.close()
    except Exception as exc:  # noqa: BLE001
        _LOGGER.warning("session_store force_clear failed: %s", exc)
        return 0


def count_active(*, db_path: Path | None = None) -> int:
    """Return how many sessions are currently persisted (for
    observability)."""
    path = db_path or _DEFAULT_DB_PATH
    if not _setup_done.is_set():
        try:
            _setup(path)
        except Exception as exc:  # noqa: BLE001
            _LOGGER.warning("session_store count_active setup failed: %s", exc)
            return 0
    try:
        with _db_lock:
            conn = _connect(path)
            try:
                row = conn.execute(f"SELECT COUNT(*) FROM {_TABLE}").fetchone()
                return int(row[0]) if row else 0
            finally:
                conn.close()
    except Exception:  # noqa: BLE001
        return 0
