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
  30) — matches the cookie ``max_age``.
* Invalidation on allowlist change: every session row stores
  ``allowlist_version`` (a hash of PRIVATE_APP_ALLOWED_USERNAMES).
  On hydrate, sessions whose stored version doesn't match the
  current are treated as invalid — prevents a session outliving
  its allowlist entry.
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
import json
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
        str(path), timeout=5.0, isolation_level=None, check_same_thread=False,
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
                f"CREATE INDEX IF NOT EXISTS idx_{_TABLE}_created "
                f"ON {_TABLE}(created_at)"
            )
        finally:
            conn.close()
    _setup_done.set()


def _allowlist_version(allowlist: Iterable[str] | None) -> str:
    """Stable hash of the allowlist — used to invalidate sessions
    on roster change without manually rotating them."""
    items = sorted({s.strip().lower() for s in (allowlist or []) if s})
    raw = ",".join(items).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()[:16]


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
    )
    try:
        with _db_lock:
            conn = _connect(path)
            try:
                conn.execute(
                    f"INSERT INTO {_TABLE} "
                    f"(session_id, username, sleeper_user_id, display_name, "
                    f"avatar, auth_method, allowlist_version, created_at, last_seen_at) "
                    f"VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?) "
                    f"ON CONFLICT(session_id) DO UPDATE SET "
                    f"last_seen_at=excluded.last_seen_at, "
                    f"allowlist_version=excluded.allowlist_version",
                    row,
                )
            finally:
                conn.close()
    except Exception as exc:  # noqa: BLE001
        _LOGGER.warning("session_store persist failed: %s", exc)


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
                    f"DELETE FROM {_TABLE} WHERE session_id = ?", (str(session_id),),
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
    """Load every non-expired, allowlist-current session into an
    in-memory dict — call once at startup.

    Sessions whose stored ``allowlist_version`` doesn't match the
    CURRENT allowlist are dropped (and removed from disk) so a
    rotation invalidates every session instantly.
    """
    path = db_path or _DEFAULT_DB_PATH
    if not _setup_done.is_set():
        try:
            _setup(path)
        except Exception as exc:  # noqa: BLE001
            _LOGGER.warning("session_store setup on hydrate failed: %s", exc)
            return {}

    current_ver = _allowlist_version(allowlist)
    cutoff = time.time() - _SESSION_TTL_SECONDS
    out: dict[str, dict[str, Any]] = {}
    expired_ids: list[str] = []
    try:
        with _db_lock:
            conn = _connect(path)
            try:
                rows = conn.execute(
                    f"SELECT session_id, username, sleeper_user_id, display_name, "
                    f"avatar, auth_method, allowlist_version, created_at, last_seen_at "
                    f"FROM {_TABLE}"
                ).fetchall()
            finally:
                conn.close()
        for (sid, user, sluid, dn, av, am, ver, created, last) in rows:
            if created < cutoff:
                expired_ids.append(sid)
                continue
            if ver != current_ver:
                expired_ids.append(sid)
                continue
            out[sid] = {
                "username": user,
                "sleeper_user_id": sluid,
                "display_name": dn,
                "avatar": av,
                "auth_method": am,
                "created_at": time.strftime(
                    "%Y-%m-%dT%H:%M:%S+00:00", time.gmtime(created),
                ),
                "created_at_epoch": created,
            }
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
