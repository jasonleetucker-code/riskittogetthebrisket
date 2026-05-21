"""Bet lifecycle persistence (SQLite-backed).

A durable per-user store for betting "call sheet" entries.  Modeled on
``src/api/user_kv.py`` (WAL journal, corrupt→reset, process-wide setup
lock) so it inherits the same crash-durability and concurrency wins.

Bets are **per-user** — keyed by authenticated ``username`` only.  They
are NOT league-scoped or scoring-profile-scoped: betting is independent
of the dynasty league context (see CLAUDE.md scoping rules).

Lifecycle
─────────
``proposed`` → ``approved`` → ``resting`` → ``filled`` → ``settled``
with terminal branches ``canceled`` / ``rejected``.

In practice the server inserts a row directly as ``resting`` once a
Kalshi limit order is placed; ``proposed``/``approved`` exist for
callers that want to stage a bet before placing it.  The background
reconciliation loop walks ``open_bets`` and advances ``resting`` →
``filled`` → ``settled`` from Kalshi fills/positions.

Schema::

    CREATE TABLE bets (
      id              TEXT PRIMARY KEY,   -- uuid4 hex
      username        TEXT NOT NULL,
      created_at      TEXT NOT NULL,
      updated_at      TEXT NOT NULL,
      sport           TEXT,
      game            TEXT,               -- human label, e.g. "Knicks @ Spurs"
      side_label      TEXT,               -- human label, e.g. "Knicks ML"
      kalshi_ticker   TEXT,
      kalshi_side     TEXT,               -- 'yes' | 'no'
      target_price    INTEGER,            -- limit price in cents (1-99)
      stake_usd       REAL,               -- intended dollar stake
      count           INTEGER,            -- contracts ordered
      status          TEXT NOT NULL,
      kalshi_order_id TEXT,
      filled_count    INTEGER DEFAULT 0,
      filled_price    INTEGER,            -- avg fill price in cents
      env             TEXT,               -- 'demo' | 'prod' at placement time
      note            TEXT
    );
"""

from __future__ import annotations

import sqlite3
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

BETS_DB_PATH: Path = Path(__file__).resolve().parents[2] / "data" / "bets.sqlite"

OPEN_STATUSES = frozenset({"proposed", "approved", "resting"})
TERMINAL_STATUSES = frozenset({"filled", "settled", "canceled", "rejected"})
ALL_STATUSES = OPEN_STATUSES | TERMINAL_STATUSES

_COLUMNS = (
    "id",
    "username",
    "created_at",
    "updated_at",
    "sport",
    "game",
    "side_label",
    "kalshi_ticker",
    "kalshi_side",
    "target_price",
    "stake_usd",
    "count",
    "status",
    "kalshi_order_id",
    "filled_count",
    "filled_price",
    "env",
    "note",
)

_SETUP_LOCK = threading.Lock()
_SETUP_DONE: dict[str, bool] = {}


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _connect(path: Path | None = None) -> sqlite3.Connection:
    path = path or BETS_DB_PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    _ensure_schema(path)
    conn = sqlite3.connect(str(path), timeout=5.0)
    conn.row_factory = sqlite3.Row
    return conn


def _ensure_schema(path: Path) -> None:
    key = str(path)
    if _SETUP_DONE.get(key):
        return
    with _SETUP_LOCK:
        if _SETUP_DONE.get(key):
            return
        _open_or_reset(path)
        _SETUP_DONE[key] = True


def _open_or_reset(path: Path) -> None:
    def _apply(conn: sqlite3.Connection) -> None:
        conn.execute("PRAGMA journal_mode=WAL;")
        conn.execute("PRAGMA synchronous=NORMAL;")
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS bets (
              id              TEXT PRIMARY KEY,
              username        TEXT NOT NULL,
              created_at      TEXT NOT NULL,
              updated_at      TEXT NOT NULL,
              sport           TEXT,
              game            TEXT,
              side_label      TEXT,
              kalshi_ticker   TEXT,
              kalshi_side     TEXT,
              target_price    INTEGER,
              stake_usd       REAL,
              count           INTEGER,
              status          TEXT NOT NULL,
              kalshi_order_id TEXT,
              filled_count    INTEGER DEFAULT 0,
              filled_price    INTEGER,
              env             TEXT,
              note            TEXT
            )
            """
        )
        conn.execute("CREATE INDEX IF NOT EXISTS idx_bets_user ON bets(username)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_bets_status ON bets(status)")
        conn.commit()

    conn = sqlite3.connect(str(path), timeout=5.0)
    try:
        _apply(conn)
        return
    except sqlite3.DatabaseError:
        conn.close()
        if path.exists():
            try:
                path.rename(path.with_suffix(path.suffix + ".corrupt"))
            except OSError:
                path.unlink(missing_ok=True)
        conn = sqlite3.connect(str(path), timeout=5.0)
        try:
            _apply(conn)
        finally:
            conn.close()
        return
    finally:
        try:
            conn.close()
        except sqlite3.ProgrammingError:
            pass


def _row_to_dict(row: sqlite3.Row) -> dict[str, Any]:
    return {col: row[col] for col in _COLUMNS}


def create_bet(
    username: str,
    *,
    sport: str = "",
    game: str = "",
    side_label: str = "",
    kalshi_ticker: str = "",
    kalshi_side: str = "yes",
    target_price: int = 0,
    stake_usd: float = 0.0,
    count: int = 0,
    status: str = "proposed",
    kalshi_order_id: str | None = None,
    env: str = "demo",
    note: str = "",
    path: Path | None = None,
) -> dict[str, Any]:
    """Insert a new bet row and return it."""
    if not username:
        raise ValueError("username required")
    if status not in ALL_STATUSES:
        raise ValueError(f"invalid status {status!r}")
    bet_id = uuid.uuid4().hex
    now = _utc_now_iso()
    conn = _connect(path)
    try:
        conn.execute(
            f"INSERT INTO bets ({','.join(_COLUMNS)}) VALUES ({','.join('?' for _ in _COLUMNS)})",
            (
                bet_id,
                username,
                now,
                now,
                sport,
                game,
                side_label,
                kalshi_ticker,
                kalshi_side,
                int(target_price),
                float(stake_usd),
                int(count),
                status,
                kalshi_order_id,
                0,
                None,
                env,
                note,
            ),
        )
        conn.commit()
        row = conn.execute("SELECT * FROM bets WHERE id = ?", (bet_id,)).fetchone()
        return _row_to_dict(row)
    finally:
        conn.close()


def get_bet(bet_id: str, *, path: Path | None = None) -> dict[str, Any] | None:
    conn = _connect(path)
    try:
        row = conn.execute("SELECT * FROM bets WHERE id = ?", (bet_id,)).fetchone()
        return _row_to_dict(row) if row else None
    finally:
        conn.close()


def list_bets(
    username: str,
    *,
    statuses: frozenset[str] | None = None,
    path: Path | None = None,
) -> list[dict[str, Any]]:
    """All bets for a user, newest first.  Optionally filter by status set."""
    conn = _connect(path)
    try:
        if statuses:
            placeholders = ",".join("?" for _ in statuses)
            rows = conn.execute(
                f"SELECT * FROM bets WHERE username = ? AND status IN ({placeholders}) "
                "ORDER BY created_at DESC",
                (username, *sorted(statuses)),
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM bets WHERE username = ? ORDER BY created_at DESC",
                (username,),
            ).fetchall()
        return [_row_to_dict(r) for r in rows]
    finally:
        conn.close()


def open_bets(*, path: Path | None = None) -> list[dict[str, Any]]:
    """Every open bet across all users — for the reconciliation loop."""
    conn = _connect(path)
    try:
        placeholders = ",".join("?" for _ in OPEN_STATUSES)
        rows = conn.execute(
            f"SELECT * FROM bets WHERE status IN ({placeholders}) ORDER BY created_at ASC",
            tuple(sorted(OPEN_STATUSES)),
        ).fetchall()
        return [_row_to_dict(r) for r in rows]
    finally:
        conn.close()


def update_bet(
    bet_id: str, patch: dict[str, Any], *, path: Path | None = None
) -> dict[str, Any] | None:
    """Update mutable fields on a bet.  Unknown keys are ignored."""
    mutable = {
        "status",
        "kalshi_order_id",
        "filled_count",
        "filled_price",
        "target_price",
        "stake_usd",
        "count",
        "note",
        "side_label",
        "kalshi_ticker",
        "kalshi_side",
        "env",
    }
    sets = {k: v for k, v in patch.items() if k in mutable}
    if "status" in sets and sets["status"] not in ALL_STATUSES:
        raise ValueError(f"invalid status {sets['status']!r}")
    if not sets:
        return get_bet(bet_id, path=path)
    sets["updated_at"] = _utc_now_iso()
    conn = _connect(path)
    try:
        assignments = ", ".join(f"{k} = ?" for k in sets)
        conn.execute(
            f"UPDATE bets SET {assignments} WHERE id = ?",
            (*sets.values(), bet_id),
        )
        conn.commit()
        row = conn.execute("SELECT * FROM bets WHERE id = ?", (bet_id,)).fetchone()
        return _row_to_dict(row) if row else None
    finally:
        conn.close()


def stake_committed_today(username: str, *, path: Path | None = None) -> float:
    """Sum of stake_usd for bets created today (UTC) that aren't rejected/canceled.

    Used by the daily-exposure guardrail.
    """
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    conn = _connect(path)
    try:
        rows = conn.execute(
            "SELECT stake_usd FROM bets WHERE username = ? "
            "AND created_at LIKE ? AND status NOT IN ('rejected','canceled')",
            (username, f"{today}%"),
        ).fetchall()
        return float(sum(float(r["stake_usd"] or 0.0) for r in rows))
    finally:
        conn.close()
