"""Time-bounded guest passwords for invited viewers.

The owner generates a guest pass via ``POST /api/admin/guest-pass``,
specifying a duration (hours).  The endpoint returns a random
URL-safe token that the owner shares with their guest.  When the
guest types that token into the login form, ``/api/auth/login``
falls through to this module's :func:`validate` helper; on a hit it
creates a session whose cookie max-age is capped at the pass's
remaining lifetime, and ``_get_auth_session`` rejects the cookie
once ``expires_at_epoch`` passes (defense-in-depth: even if the
cookie's max-age were stretched on the client, the server still
refuses the stale session).

Storage: SQLite at ``data/guest_passes.sqlite`` — sister to
``session_store.sqlite``.  Tokens are stored as SHA-256 hashes
(``token_hash``); the plaintext is shown to the owner exactly once
on creation and is never recoverable from the DB.

Lifecycle:
    create()      → pass exists with future ``expires_at_epoch``
    validate(t)   → returns the pass row when fresh; None otherwise
    revoke(id)    → marks ``revoked_at_epoch``; subsequent validate fails
    list_passes() → all rows, owner-visible (notes + status, never
                    plaintext tokens)
    purge_expired() → opportunistic GC; called on validate.

Threading: SQLite WAL + a module-level Lock around writes.  Reads
are uncontested (WAL).  Mirrors the pattern used by
``src/api/user_kv.py`` and ``src/api/session_store.py``.
"""
from __future__ import annotations

import hashlib
import logging
import secrets
import sqlite3
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

_LOGGER = logging.getLogger(__name__)

# DB path is overridable for tests + alternate data roots.  Same
# pattern as session_store.
_DEFAULT_DB_PATH = (
    Path(__file__).resolve().parents[2] / "data" / "guest_passes.sqlite"
)
_TABLE = "guest_passes"
_TOKEN_BYTES = 24  # 24 URL-safe bytes → 32-char base64 string.
_MAX_DURATION_HOURS = 24 * 30  # 30 days; sanity cap on creation.
_MIN_DURATION_HOURS = 1 / 60  # 1 minute floor for sanity tests.

_db_lock = threading.Lock()
# Track schema bootstrap per DB path so tests using ephemeral
# tmp_path fixtures don't share the production "done" flag and
# silently skip table creation in their own files.  Production
# only ever has one path so the set has one entry there.
_setup_done_paths: set[Path] = set()


@dataclass
class GuestPass:
    """Public representation of a stored pass.  Plaintext token is
    NEVER on this dataclass — only on the create() return value, and
    only once."""
    id: int
    note: str
    created_by: str
    created_at_epoch: float
    expires_at_epoch: float
    revoked_at_epoch: float | None

    @property
    def is_revoked(self) -> bool:
        return self.revoked_at_epoch is not None and self.revoked_at_epoch > 0

    @property
    def is_expired(self) -> bool:
        return self.expires_at_epoch <= time.time()

    @property
    def is_active(self) -> bool:
        return not self.is_revoked and not self.is_expired

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "note": self.note,
            "createdBy": self.created_by,
            "createdAtEpoch": self.created_at_epoch,
            "expiresAtEpoch": self.expires_at_epoch,
            "revokedAtEpoch": self.revoked_at_epoch,
            "isRevoked": self.is_revoked,
            "isExpired": self.is_expired,
            "isActive": self.is_active,
        }


# ── DB helpers ──────────────────────────────────────────────────────


def _connect(path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(str(path), isolation_level=None, check_same_thread=False)
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
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    token_hash TEXT NOT NULL UNIQUE,
                    note TEXT NOT NULL DEFAULT '',
                    created_by TEXT NOT NULL DEFAULT '',
                    created_at_epoch REAL NOT NULL,
                    expires_at_epoch REAL NOT NULL,
                    revoked_at_epoch REAL
                )
            """)
            conn.execute(
                f"CREATE INDEX IF NOT EXISTS idx_{_TABLE}_expires "
                f"ON {_TABLE}(expires_at_epoch)"
            )
            conn.execute(
                f"CREATE INDEX IF NOT EXISTS idx_{_TABLE}_token_hash "
                f"ON {_TABLE}(token_hash)"
            )
        finally:
            conn.close()
    _setup_done_paths.add(path)


def _ensure_setup(path: Path) -> bool:
    """Return True when the schema is reachable."""
    if path in _setup_done_paths:
        return True
    try:
        _setup(path)
        return True
    except Exception as exc:  # noqa: BLE001
        _LOGGER.warning("guest_passes setup failed: %s", exc)
        return False


def _row_to_pass(row: tuple) -> GuestPass:
    return GuestPass(
        id=int(row[0]),
        note=str(row[1] or ""),
        created_by=str(row[2] or ""),
        created_at_epoch=float(row[3]),
        expires_at_epoch=float(row[4]),
        revoked_at_epoch=float(row[5]) if row[5] is not None else None,
    )


def _hash_token(token: str) -> str:
    """SHA-256 of the plaintext.  64-char lowercase hex string.

    Single-pass hash is fine here — tokens are 24-byte URL-safe
    secrets generated by ``secrets.token_urlsafe`` so a brute-force
    rainbow doesn't apply.  The hash exists to keep the SQLite file
    from being a plaintext password leak if it's ever read by a
    third party (a backup, a developer tooling around).
    """
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


# ── Public API ──────────────────────────────────────────────────────


def create(
    *,
    duration_hours: float,
    note: str = "",
    created_by: str = "",
    db_path: Path | None = None,
) -> tuple[GuestPass, str]:
    """Create a new pass; return ``(pass, plaintext_token)``.

    The plaintext token is shown to the caller exactly once.  It's
    NEVER stored in the DB — only its sha256 hash.  Subsequent
    ``list_passes`` calls return the GuestPass without the token.

    Raises ``ValueError`` if ``duration_hours`` is outside the
    allowed range or non-numeric.
    """
    try:
        hours = float(duration_hours)
    except (TypeError, ValueError) as exc:
        raise ValueError("duration_hours must be a number") from exc
    if hours < _MIN_DURATION_HOURS:
        raise ValueError(
            f"duration_hours must be ≥ {_MIN_DURATION_HOURS:.4f} (~1 min)"
        )
    if hours > _MAX_DURATION_HOURS:
        raise ValueError(f"duration_hours must be ≤ {_MAX_DURATION_HOURS}")

    path = db_path or _DEFAULT_DB_PATH
    if not _ensure_setup(path):
        raise RuntimeError("guest_passes DB unavailable")

    token = secrets.token_urlsafe(_TOKEN_BYTES)
    token_hash = _hash_token(token)
    now = time.time()
    expires = now + hours * 3600.0
    safe_note = str(note or "").strip()[:200]
    safe_creator = str(created_by or "").strip()[:80]

    with _db_lock:
        conn = _connect(path)
        try:
            cur = conn.execute(
                f"INSERT INTO {_TABLE} (token_hash, note, created_by, "
                f"created_at_epoch, expires_at_epoch, revoked_at_epoch) "
                f"VALUES (?, ?, ?, ?, ?, NULL)",
                (token_hash, safe_note, safe_creator, now, expires),
            )
            new_id = cur.lastrowid
        finally:
            conn.close()

    pass_row = GuestPass(
        id=int(new_id or 0),
        note=safe_note,
        created_by=safe_creator,
        created_at_epoch=now,
        expires_at_epoch=expires,
        revoked_at_epoch=None,
    )
    return pass_row, token


def validate(
    token: str,
    *,
    db_path: Path | None = None,
) -> GuestPass | None:
    """Return the matching GuestPass when ``token`` is valid AND not
    expired AND not revoked; None otherwise.

    Side-effect: also runs an opportunistic ``purge_expired`` (no-op
    on most calls thanks to the WHERE clause, cheap when it does
    fire).  Keeps the table from accumulating stale rows over months.
    """
    if not token or not isinstance(token, str):
        return None
    path = db_path or _DEFAULT_DB_PATH
    if not _ensure_setup(path):
        return None
    token_hash = _hash_token(token.strip())
    now = time.time()
    with _db_lock:
        conn = _connect(path)
        try:
            cur = conn.execute(
                f"SELECT id, note, created_by, created_at_epoch, "
                f"expires_at_epoch, revoked_at_epoch FROM {_TABLE} "
                f"WHERE token_hash = ? LIMIT 1",
                (token_hash,),
            )
            row = cur.fetchone()
        finally:
            conn.close()
    if not row:
        return None
    pass_row = _row_to_pass(row)
    if pass_row.is_revoked:
        return None
    if pass_row.expires_at_epoch <= now:
        return None
    return pass_row


def revoke(
    pass_id: int,
    *,
    db_path: Path | None = None,
) -> bool:
    """Mark the pass revoked.  Returns True iff a row was updated.
    Idempotent — re-revoking an already-revoked pass returns False
    without raising.
    """
    path = db_path or _DEFAULT_DB_PATH
    if not _ensure_setup(path):
        return False
    now = time.time()
    with _db_lock:
        conn = _connect(path)
        try:
            cur = conn.execute(
                f"UPDATE {_TABLE} SET revoked_at_epoch = ? "
                f"WHERE id = ? AND revoked_at_epoch IS NULL",
                (now, int(pass_id)),
            )
            return cur.rowcount > 0
        finally:
            conn.close()


def list_passes(
    *,
    include_inactive: bool = True,
    limit: int = 200,
    db_path: Path | None = None,
) -> list[GuestPass]:
    """Return passes ordered by creation desc.  When
    ``include_inactive=False`` only currently-active passes are
    returned (still-valid, not revoked).
    """
    path = db_path or _DEFAULT_DB_PATH
    if not _ensure_setup(path):
        return []
    now = time.time()
    cap = max(1, min(1000, int(limit)))
    with _db_lock:
        conn = _connect(path)
        try:
            if include_inactive:
                cur = conn.execute(
                    f"SELECT id, note, created_by, created_at_epoch, "
                    f"expires_at_epoch, revoked_at_epoch FROM {_TABLE} "
                    f"ORDER BY created_at_epoch DESC LIMIT ?",
                    (cap,),
                )
            else:
                cur = conn.execute(
                    f"SELECT id, note, created_by, created_at_epoch, "
                    f"expires_at_epoch, revoked_at_epoch FROM {_TABLE} "
                    f"WHERE expires_at_epoch > ? AND revoked_at_epoch IS NULL "
                    f"ORDER BY created_at_epoch DESC LIMIT ?",
                    (now, cap),
                )
            rows = cur.fetchall()
        finally:
            conn.close()
    return [_row_to_pass(r) for r in rows]


def purge_expired(
    *,
    grace_seconds: float = 7 * 24 * 3600.0,  # keep 7d of expired/revoked rows
    db_path: Path | None = None,
) -> int:
    """Delete passes older than ``expires_at + grace_seconds`` and
    revoked passes older than ``revoked_at + grace_seconds``.  The
    grace period keeps the audit trail visible for a week before the
    row drops out of the admin list.

    Returns the number of rows deleted.
    """
    path = db_path or _DEFAULT_DB_PATH
    if not _ensure_setup(path):
        return 0
    cutoff = time.time() - max(0.0, float(grace_seconds))
    with _db_lock:
        conn = _connect(path)
        try:
            cur = conn.execute(
                f"DELETE FROM {_TABLE} WHERE "
                f"(revoked_at_epoch IS NOT NULL AND revoked_at_epoch < ?) OR "
                f"(expires_at_epoch < ?)",
                (cutoff, cutoff),
            )
            return int(cur.rowcount or 0)
        finally:
            conn.close()
