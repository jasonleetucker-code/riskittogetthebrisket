"""PRIVATE durable ledger of our own leagues' transactions.

``C1-RET-06``.  The manifest records the live path as PARTIAL:
``src/api/sleeper_overlay.py::_build_trades_block`` fetches a **365-day
rolling window** across a depth-2 league chain and emits a processed
display shape that drops ``transaction_id`` entirely.  Two consequences,
both irreversible:

* a trade older than the window simply stops being fetched, and Sleeper
  is the only place it existed;
* without a stable id, nothing downstream can say "this is the same
  trade I saw last week" — so a trade cannot be graded at-the-time,
  cannot be re-graded later, and cannot be deduped across the chain
  except by the in-memory ``seen`` set that dies with the request.

``docs/TRADE_HISTORY_AGING_SPEC.md`` needs all three of Current Grade,
At-the-Time Grade and How It Aged.  None of them are reachable from a
window that forgets.  Recording the event now is what keeps the option
open; it is explicitly **not** authorization to build Trade History,
which stays unauthorized.

WHAT IS STORED, AND WHY THE WHOLE PAYLOAD
─────────────────────────────────────────
The raw Sleeper transaction, verbatim, alongside the few fields worth
indexing.  Extracting only what today's consumer needs is how the live
path lost ``transaction_id`` in the first place: a question asked later
about a field nobody thought to keep is unanswerable, and the source
window has already turned over by then.

PRIVACY — READ THIS BEFORE MOVING ANYTHING
──────────────────────────────────────────
**PRIVATE.**  This is real managers, real rosters, real trades in our
own leagues.  It is a separate database file from
``src/retention/evidence_store.py`` specifically so that "back this up"
and "publish this" can never be the same gesture by accident.

* primary store: ``data/retention/league_events.sqlite`` — gitignored;
* backup: ``deploy/backup/riskit-state-backup.sh``, on-box, mode 0600,
  off-box only to the operator's own configured rsync destination;
* it must **never** be force-added into public Git history, and no
  ``/api/public/*`` surface may read it.  The B8 boundary treats
  factual retrospective league content as publishable only through the
  public-league surfaces, which build from their own snapshots.

IDEMPOTENCE
───────────
Keyed ``(sleeper_league_id, transaction_id)``, so re-recording the same
window is structurally a no-op rather than a matter of caller
discipline.  ``first_recorded_at`` is never overwritten — it is our
evidence of when the platform first *saw* the event, which is a
different fact from when Sleeper says it happened, and re-running a
collector must not restate it.

A completed Sleeper transaction is immutable, but a transaction can be
observed while still ``pending``.  Later observations therefore update
the status/payload columns while preserving ``first_recorded_at`` — a
strict existing-wins rule would pin a trade at ``pending`` forever.
"""

from __future__ import annotations

import json
import sqlite3
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

DB_PATH: Path = Path(__file__).resolve().parents[2] / "data" / "retention" / "league_events.sqlite"

SCHEMA_VERSION = 1

PRIVACY_CLASS = "private"

_SETUP_LOCK = threading.Lock()
_SETUP_DONE: dict[str, bool] = {}

_SCHEMA = """
CREATE TABLE IF NOT EXISTS meta (
    key   TEXT PRIMARY KEY,
    value TEXT
);

CREATE TABLE IF NOT EXISTS league_transactions (
    -- The Sleeper league the event was observed IN.  A depth-2 chain
    -- means one registry league spans several Sleeper ids across
    -- seasons; keying on the chain member keeps the event attached to
    -- the season it actually happened in.
    sleeper_league_id TEXT NOT NULL,
    transaction_id    TEXT NOT NULL,

    -- The registry key that was doing the observing.  A column, not
    -- part of the key: a league renamed in the registry must not
    -- duplicate its own history.
    league_key        TEXT,

    type              TEXT,
    status            TEXT,
    week              INTEGER,
    season            TEXT,
    -- Sleeper's own stamp, normalised to ms.  NULL when absent -- an
    -- undated event is not an event dated zero.
    occurred_at_ms    INTEGER,

    -- The transaction verbatim.  See the module docstring.
    payload_json      TEXT NOT NULL,

    first_recorded_at TEXT NOT NULL,
    last_seen_at      TEXT NOT NULL,

    PRIMARY KEY (sleeper_league_id, transaction_id)
);

CREATE INDEX IF NOT EXISTS idx_ltx_league_time
    ON league_transactions(sleeper_league_id, occurred_at_ms);
CREATE INDEX IF NOT EXISTS idx_ltx_type
    ON league_transactions(type, occurred_at_ms);
CREATE INDEX IF NOT EXISTS idx_ltx_key
    ON league_transactions(league_key, occurred_at_ms);
"""


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _ensure_schema(path: Path) -> None:
    key = str(path)
    if _SETUP_DONE.get(key):
        return
    with _SETUP_LOCK:
        if _SETUP_DONE.get(key):
            return
        path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(str(path), timeout=5.0)
        try:
            conn.execute("PRAGMA journal_mode=WAL;")
            conn.execute("PRAGMA synchronous=NORMAL;")
            conn.executescript(_SCHEMA)
            conn.execute(
                "INSERT OR REPLACE INTO meta(key, value) VALUES ('schema_version', ?)",
                (str(SCHEMA_VERSION),),
            )
            conn.commit()
        finally:
            conn.close()
        _SETUP_DONE[key] = True
    try:
        # Private data: never group/world readable.  Best-effort -- a
        # filesystem that cannot express this (or a non-owner process)
        # must not take the recorder down.
        path.chmod(0o600)
    except OSError:
        pass


def connect(path: Path | None = None) -> sqlite3.Connection:
    target = path or DB_PATH
    _ensure_schema(target)
    return sqlite3.connect(str(target), timeout=5.0)


def _reset_setup_cache_for_tests() -> None:
    """Forget which paths have been initialised.  Tests only."""
    with _SETUP_LOCK:
        _SETUP_DONE.clear()


def _normalise_ms(value: Any) -> int | None:
    """Sleeper stamps are seconds on some endpoints, ms on others."""
    try:
        n = int(value)
    except (TypeError, ValueError):
        return None
    if n <= 0:
        return None
    # Anything below ~2001 in ms is really a seconds stamp.
    return n * 1000 if n < 10_000_000_000 else n


def record_transactions(
    sleeper_league_id: str,
    transactions: Iterable[dict[str, Any]],
    *,
    league_key: str | None = None,
    week: int | None = None,
    season: str | None = None,
    path: Path | None = None,
) -> dict[str, Any]:
    """Record raw Sleeper transactions.  Returns a small write report.

    Best-effort by contract: callers run this beside a live feature and
    a ledger failure must never take that feature down.  It raises only
    on programmer error (a bad path), never on a malformed row — rows
    without a ``transaction_id`` are counted in ``skipped`` rather than
    stored under a synthesised key, because a fabricated id would defeat
    the deduplication the ledger exists to provide.
    """
    lid = str(sleeper_league_id or "").strip()
    if not lid:
        return {"recorded": 0, "updated": 0, "skipped": 0, "reason": "no_league_id"}

    now = _utc_now()
    rows: list[tuple[Any, ...]] = []
    skipped = 0
    for tx in transactions or []:
        if not isinstance(tx, dict):
            skipped += 1
            continue
        tx_id = str(tx.get("transaction_id") or "").strip()
        if not tx_id:
            skipped += 1
            continue
        tx_week = tx.get("leg") if tx.get("leg") is not None else week
        try:
            tx_week_i = int(tx_week) if tx_week is not None else None
        except (TypeError, ValueError):
            tx_week_i = None
        rows.append(
            (
                lid,
                tx_id,
                str(league_key) if league_key else None,
                str(tx.get("type") or "") or None,
                str(tx.get("status") or "") or None,
                tx_week_i,
                str(season) if season is not None else None,
                _normalise_ms(tx.get("status_updated") or tx.get("created")),
                json.dumps(tx, sort_keys=True, separators=(",", ":")),
                now,
                now,
            )
        )

    if not rows:
        return {"recorded": 0, "updated": 0, "skipped": skipped}

    conn = connect(path)
    try:
        before = conn.execute(
            "SELECT COUNT(*) FROM league_transactions WHERE sleeper_league_id = ?",
            (lid,),
        ).fetchone()[0]
        conn.executemany(
            """
            INSERT INTO league_transactions (
                sleeper_league_id, transaction_id, league_key, type, status,
                week, season, occurred_at_ms, payload_json,
                first_recorded_at, last_seen_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(sleeper_league_id, transaction_id) DO UPDATE SET
                league_key     = COALESCE(excluded.league_key, league_key),
                type           = COALESCE(excluded.type, type),
                status         = COALESCE(excluded.status, status),
                week           = COALESCE(excluded.week, week),
                season         = COALESCE(excluded.season, season),
                occurred_at_ms = COALESCE(excluded.occurred_at_ms, occurred_at_ms),
                payload_json   = excluded.payload_json,
                last_seen_at   = excluded.last_seen_at
            """,
            rows,
        )
        conn.commit()
        after = conn.execute(
            "SELECT COUNT(*) FROM league_transactions WHERE sleeper_league_id = ?",
            (lid,),
        ).fetchone()[0]
    finally:
        conn.close()

    recorded = int(after) - int(before)
    return {
        "recorded": recorded,
        "updated": len(rows) - recorded,
        "skipped": skipped,
        "offered": len(rows),
    }


def transaction_coverage(*, path: Path | None = None) -> dict[str, Any]:
    """What the ledger holds.  Feeds ``src/retention/health.py``.

    Reports counts and stamps only — never payloads.  A health surface
    that echoed private trade contents would move the privacy boundary
    every time someone checked whether the recorder was alive.
    """
    target = path or DB_PATH
    if not target.exists():
        return {"present": False, "path": str(target), "privacyClass": PRIVACY_CLASS}

    conn = connect(target)
    try:
        total = conn.execute("SELECT COUNT(*) FROM league_transactions").fetchone()[0]
        leagues = conn.execute(
            "SELECT COUNT(DISTINCT sleeper_league_id) FROM league_transactions"
        ).fetchone()[0]
        trades = conn.execute(
            "SELECT COUNT(*) FROM league_transactions WHERE type = 'trade'"
        ).fetchone()[0]
        last_seen = conn.execute("SELECT MAX(last_seen_at) FROM league_transactions").fetchone()[0]
        oldest_ms = conn.execute(
            "SELECT MIN(occurred_at_ms) FROM league_transactions WHERE occurred_at_ms IS NOT NULL"
        ).fetchone()[0]
        newest_ms = conn.execute(
            "SELECT MAX(occurred_at_ms) FROM league_transactions WHERE occurred_at_ms IS NOT NULL"
        ).fetchone()[0]
    finally:
        conn.close()

    return {
        "present": True,
        "path": str(target),
        "privacyClass": PRIVACY_CLASS,
        "transactions": int(total or 0),
        "trades": int(trades or 0),
        "leagues": int(leagues or 0),
        "lastSeenAt": last_seen,
        "oldestOccurredAtMs": oldest_ms,
        "newestOccurredAtMs": newest_ms,
    }
