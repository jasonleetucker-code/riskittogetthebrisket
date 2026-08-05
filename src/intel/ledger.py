"""Normalized SQLite ledger for Sleeper transaction intelligence.

This is the shared substrate under BOTH products — Sharp Tracker
(global qualified cohort) and Insider Trading (one league's members).
Neither product's logic lives here; this module only stores movements
and answers indexed window queries over them.

──────────────────────────────────────────────────────────────────────
Why this exists
──────────────────────────────────────────────────────────────────────
The predecessor kept every observation in one JSON snapshot per league
and re-aggregated the whole file on every read.  That works at 12
managers and stops working at a discovery graph.  It also capped
history at 45 days, so "last 90 days" was unanswerable.

The ledger stores normalized rows with indexes, so a window query
touches only the rows in the window.

──────────────────────────────────────────────────────────────────────
The three units, which are NEVER interchangeable
──────────────────────────────────────────────────────────────────────
Mixing these is the single easiest way to produce a wrong number, so
they are separate tables and separate count functions:

    transaction     one Sleeper transaction.  A 4-player trade is ONE.
    asset_movement  one asset changing hands within a transaction.
                    A 4-player trade is FOUR.
    observation     one (manager, asset, direction) pair.  A 4-player
                    trade between two tracked managers is EIGHT — each
                    manager observes each asset from their own side.

``trade_count`` counts distinct ``tx_id``.  ``asset_movement_count``
counts distinct ``movement_id``.  ``buy_count`` / ``sell_count`` count
observations.  See ``docs/intel/METRICS.md``.

──────────────────────────────────────────────────────────────────────
Deduplication
──────────────────────────────────────────────────────────────────────
``movement_id`` is the deterministic key inherited from the crawler:

    <tx_id>:<user_id>:<action>:<asset_id>[:<discriminator>]

Sleeper's ``transaction_id`` is stable and authoritative, so no hashing
is required.  The discriminator disambiguates multiple picks of the
same season+round in one trade.  Every write is ``INSERT OR IGNORE``,
so re-ingesting identical source data is a no-op and aggregate counts
cannot move.  That invariant is pinned by
``tests/intel/test_ledger.py::TestIdempotency``.

──────────────────────────────────────────────────────────────────────
Time windows are OVERLAPPING VIEWS, never additive buckets
──────────────────────────────────────────────────────────────────────
Every window query is independent and evaluated against the raw rows:
a movement 15 days old is returned by the 30d query AND the 90d query
AND the all-time query, because it is one movement seen through three
lenses.  Totals are NEVER computed by adding windows together — there
is deliberately no function in this module that accepts two window
results and sums them.
"""

from __future__ import annotations

import logging
import sqlite3
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Sequence

log = logging.getLogger(__name__)

REPO_ROOT = Path(__file__).resolve().parents[2]
LEDGER_FILENAME = "ledger.sqlite3"


def default_path() -> Path:
    """The ledger file, resolved from ``store.DATA_DIR`` AT CALL TIME.

    Deliberately not a module constant.  ``store.DATA_DIR`` is what the
    test suite monkeypatches to redirect intel data into a tmp dir, and
    a path captured at import time would sail straight past that and
    write to the real ``data/intel/`` during tests — which is exactly
    what happened before this was made dynamic.  One source of truth
    for "where does intel data live" also means an operator moving the
    data dir moves the ledger with it.
    """
    from src.intel import store

    return Path(store.DATA_DIR) / LEDGER_FILENAME


# Bumping this REBUILDS the ledger on next open (see ``_open_or_reset``).
#
# 2 — D10.  ``movement_id`` used to embed the *attributed* owner, which
#     is recomputed from live ``/rosters`` each run, so a co-ownership
#     change re-keyed an already-ingested movement and let the same
#     transaction be counted twice.  It is now keyed on the roster slot
#     (``src/intel/crawler.py::emit``).  Existing rows carry the old key
#     and cannot be recomputed — they never stored a roster_id — so the
#     migration CLEARS THE MOVEMENT TABLES rather than rewriting keys.
#
#     Deliberately not a whole-file rebuild.  The discovery graph
#     (``leagues``, ``sleeper_users``, ``league_memberships``) and the
#     season records (``manager_seasons``) live in this same file and
#     cost hundreds of Sleeper calls to rebuild; they are unaffected by
#     the key change, so they are preserved.  Movements are the cheap
#     part: league-mate rows heal on the next read via
#     ``service.ensure_ledger_synced``, and sharp rows re-crawl.
#
#     "and sharp rows re-crawl" was NOT TRUE as first written, and the
#     omission was silent and permanent.  ``sharp_league_fetch`` is the
#     sharp crawl's per-league cursor: it records the last week already
#     fetched so a budgeted run resumes instead of restarting.  Clearing
#     the movements while leaving that cursor told the crawler it had
#     already collected weeks whose rows had just been deleted, so it
#     advanced past them forever and the wiped history was unrecoverable
#     without hand-editing the database.  The cursor is therefore cleared
#     in the same step.  It is the cheap thing to lose — losing it costs
#     one re-crawl, whereas keeping it costs the data.
SCHEMA_VERSION = 2

# Tables whose rows are invalidated by each schema step.  Anything not
# listed here SURVIVES the migration.
#
# A cursor that points into deleted data is itself invalid — any table
# recording "how far we already got" MUST be listed beside the table it
# points into, or the migration quietly becomes destructive.
_MIGRATION_CLEARS: dict[int, tuple[str, ...]] = {
    2: ("asset_movements", "transactions", "sharp_league_fetch"),
}

# Retention.  The predecessor's 45 days made "last 90 days" and any
# season-level view structurally unanswerable.  Rows are small and
# bounded by (leagues x transactions), not by time, so a much longer
# horizon costs little and makes the longer windows real.
MOVEMENT_RETENTION_DAYS = 400

# The transaction types Sleeper reports that we ingest.  ALL of them
# are stored; what differs is how they are COUNTED.
TX_TYPE_TRADE = "trade"
TX_TYPE_WAIVER = "waiver"
TX_TYPE_FREE_AGENT = "free_agent"
INGESTED_TX_TYPES = (TX_TYPE_TRADE, TX_TYPE_WAIVER, TX_TYPE_FREE_AGENT)

# Buy/sell counting is TRADES ONLY.  This is the fix for the defect
# where the previous aggregator bucketed purely on add/drop and never
# read ``txType`` at all, so every waiver claim and free-agent pickup
# was reported to users as a "buy".  Waiver and free-agent movements
# remain in the ledger and are queryable, but only under an explicitly
# separate label — never inside a buy/sell number.
TRADE_TX_TYPES = (TX_TYPE_TRADE,)
WAIVER_TX_TYPES = (TX_TYPE_WAIVER, TX_TYPE_FREE_AGENT)

ACTION_BUY = "add"
ACTION_SELL = "drop"

_SETUP_LOCK = threading.Lock()
_SETUP_DONE: dict[str, bool] = {}


def _now_ms() -> int:
    return int(time.time() * 1000)


# ── schema ───────────────────────────────────────────────────────────

_SCHEMA = """
CREATE TABLE IF NOT EXISTS transactions (
  tx_id        TEXT PRIMARY KEY,
  league_id    TEXT NOT NULL,
  season       TEXT,
  week         INTEGER,
  tx_type      TEXT NOT NULL,
  status       TEXT,
  created_ms   INTEGER NOT NULL,
  ingested_ms  INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS asset_movements (
  movement_id   TEXT PRIMARY KEY,
  tx_id         TEXT NOT NULL,
  league_id     TEXT NOT NULL,
  tx_type       TEXT NOT NULL,
  asset_id      TEXT NOT NULL,
  asset_type    TEXT NOT NULL,
  action        TEXT NOT NULL,
  user_id       TEXT NOT NULL,
  roster_id     TEXT,
  counterparty_user_id TEXT,
  ts            INTEGER NOT NULL,
  week          INTEGER,
  faab_bid      INTEGER,
  ingested_ms   INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS sleeper_users (
  user_id          TEXT PRIMARY KEY,
  current_username TEXT,
  display_name     TEXT,
  username_history TEXT,
  first_seen_ms    INTEGER,
  last_seen_ms     INTEGER
);

CREATE TABLE IF NOT EXISTS leagues (
  league_id          TEXT PRIMARY KEY,
  season             TEXT,
  previous_league_id TEXT,
  name               TEXT,
  total_rosters      INTEGER,
  settings_json      TEXT,
  first_seen_ms      INTEGER,
  last_crawled_ms    INTEGER
);

CREATE TABLE IF NOT EXISTS league_memberships (
  league_id TEXT NOT NULL,
  user_id   TEXT NOT NULL,
  roster_id TEXT,
  last_seen_ms INTEGER,
  PRIMARY KEY (league_id, user_id)
);

-- One manager's result in one league-season.  Populated by the Sharp
-- records crawl (src/sharp/records.py) and consumed by the Sharp Score,
-- which needs completed-season history that transactions cannot supply.
-- PK is (league_id, season, user_id): a manager holds at most one roster
-- per league-season, so a re-crawl overwrites rather than duplicating.
CREATE TABLE IF NOT EXISTS manager_seasons (
  league_id      TEXT NOT NULL,
  season         TEXT NOT NULL,
  user_id        TEXT NOT NULL,
  roster_id      TEXT,
  wins           INTEGER,
  losses         INTEGER,
  ties           INTEGER,
  points_for     REAL,
  points_against REAL,
  made_playoffs  INTEGER,
  is_champion    INTEGER,
  is_runner_up   INTEGER,
  finish_rank    INTEGER,
  team_count     INTEGER,
  is_complete    INTEGER,
  sharp_eligible INTEGER,
  crawled_ms     INTEGER,
  PRIMARY KEY (league_id, season, user_id)
);

-- Per-league transaction cursor for the SHARP crawl
-- (src/sharp/transactions.py).  Deliberately separate from Insider
-- Trading's snapshot ``fetchState``: the two crawls cover different
-- league sets on different schedules, and sharing a cursor would let
-- one advance past transactions the other never fetched.
CREATE TABLE IF NOT EXISTS sharp_league_fetch (
  league_id       TEXT PRIMARY KEY,
  max_created_ms  INTEGER,
  boundary_tx_ids TEXT,
  backfilled      INTEGER,
  last_fetched_ms INTEGER,
  last_error      TEXT
);

CREATE TABLE IF NOT EXISTS meta (
  key   TEXT PRIMARY KEY,
  value TEXT
);

-- Window queries filter on ts and group by asset or user, so the
-- leading column of each index is the equality/grouping key and ts
-- is the range key.
CREATE INDEX IF NOT EXISTS idx_mv_asset_ts   ON asset_movements(asset_id, ts);
CREATE INDEX IF NOT EXISTS idx_mv_user_ts    ON asset_movements(user_id, ts);
CREATE INDEX IF NOT EXISTS idx_mv_league_ts  ON asset_movements(league_id, ts);
CREATE INDEX IF NOT EXISTS idx_mv_type_ts    ON asset_movements(tx_type, ts);
CREATE INDEX IF NOT EXISTS idx_mv_ts         ON asset_movements(ts);
CREATE INDEX IF NOT EXISTS idx_mv_tx         ON asset_movements(tx_id);
CREATE INDEX IF NOT EXISTS idx_tx_ts         ON transactions(created_ms);
CREATE INDEX IF NOT EXISTS idx_lm_user       ON league_memberships(user_id);
CREATE INDEX IF NOT EXISTS idx_ms_user       ON manager_seasons(user_id);
CREATE INDEX IF NOT EXISTS idx_ms_league     ON manager_seasons(league_id, season);
-- The sharp crawl orders leagues by staleness so a budget-capped run
-- makes progress across the graph instead of re-walking the same head.
CREATE INDEX IF NOT EXISTS idx_slf_fetched   ON sharp_league_fetch(last_fetched_ms);
"""


def _apply_schema(conn: sqlite3.Connection) -> None:
    conn.execute("PRAGMA journal_mode=WAL;")
    conn.execute("PRAGMA synchronous=NORMAL;")
    conn.executescript(_SCHEMA)
    conn.execute(
        "INSERT OR REPLACE INTO meta(key, value) VALUES ('schema_version', ?)",
        (str(SCHEMA_VERSION),),
    )
    conn.commit()


def _migrate(conn: sqlite3.Connection, from_version: int) -> None:
    """Clear only the tables each schema step invalidates.

    A whole-file rebuild would be far more destructive than it looks:
    the discovery graph and the season records share this file and cost
    hundreds of Sleeper calls, and neither is affected by a movement-key
    change.  So each step names the tables it invalidates and everything
    else is carried forward untouched.

    Steps run in order, so a file several versions behind lands on the
    union of what each intervening step invalidated.
    """
    for version in sorted(_MIGRATION_CLEARS):
        if from_version < version <= SCHEMA_VERSION:
            for table in _MIGRATION_CLEARS[version]:
                try:
                    conn.execute(f"DELETE FROM {table}")  # noqa: S608 — fixed literals above
                except sqlite3.OperationalError as exc:
                    # A brand-new file has no version recorded, so it arrives
                    # here as version 0 with none of these tables created yet.
                    # There is nothing to clear and nothing wrong; logging a
                    # traceback for it would cry wolf on every fresh ledger.
                    if "no such table" not in str(exc).lower():
                        log.exception(
                            "intel.ledger: migration v%s could not clear %s", version, table
                        )
                except sqlite3.DatabaseError:
                    log.exception("intel.ledger: migration v%s could not clear %s", version, table)
    conn.commit()


def _stored_schema_version(conn: sqlite3.Connection) -> int | None:
    """The schema version recorded in the file, or None if absent.

    Absent means either a brand-new file or one written before the
    version was tracked; both are handled by the caller as "no
    migration needed".
    """
    try:
        row = conn.execute("SELECT value FROM meta WHERE key = 'schema_version'").fetchone()
    except sqlite3.DatabaseError:
        return None
    if not row:
        return None
    try:
        return int(row[0])
    except (TypeError, ValueError):
        return None


def _is_corrupt_database_error(exc: sqlite3.DatabaseError) -> bool:
    """Return True only for errors that prove the file itself is corrupt.

    ``OperationalError`` is a ``DatabaseError`` subclass. Treating every
    database error as corruption meant a routine ``database is locked``
    during a collector write renamed the live ledger and rebuilt an empty
    one underneath the writer. Busy/locked errors must propagate so the
    caller can retry; only SQLite CORRUPT/NOTADB conditions may quarantine
    and rebuild this derived store.
    """
    code = getattr(exc, "sqlite_errorcode", None)
    corrupt_codes = {
        getattr(sqlite3, "SQLITE_CORRUPT", 11),
        getattr(sqlite3, "SQLITE_NOTADB", 26),
    }
    if code in corrupt_codes:
        return True
    message = str(exc).lower()
    return any(
        marker in message
        for marker in (
            "database disk image is malformed",
            "file is not a database",
            "file is encrypted or is not a database",
            "malformed database schema",
        )
    )


def _schema_is_current(conn: sqlite3.Connection) -> bool:
    """Check an existing schema without taking a write lock."""
    try:
        row = conn.execute("SELECT value FROM meta WHERE key='schema_version'").fetchone()
    except sqlite3.OperationalError as exc:
        if "no such table" in str(exc).lower():
            return False
        raise
    return row is not None and str(row[0]) == str(SCHEMA_VERSION)


def _open_or_reset(path: Path) -> None:
    """Open the ledger, migrating on a version bump and rebuilding only on corruption.

    Existing, current ledgers are checked read-only. This lets API readers
    start while a collector owns the write lock. A busy or locked database
    is never renamed, deleted, or rebuilt.

    ``SCHEMA_VERSION`` was written into ``meta`` from the start but never
    *checked*. That was harmless while the version never moved; it stops
    being harmless the moment the movement key changes, because old rows
    keyed the old way would sit beside new ones and double-count by a
    different route than D10 itself. So a stale version now runs
    ``_migrate``, which clears only the tables the step invalidates —
    never the whole file.
    """
    conn = sqlite3.connect(str(path), timeout=30.0)
    conn.execute("PRAGMA busy_timeout=30000")
    try:
        if _schema_is_current(conn):
            return
        # ``None`` means the file predates version tracking, so treat it as
        # version 0: its movement rows carry the old key and must go.
        stored = _stored_schema_version(conn)
        if stored != SCHEMA_VERSION:
            log.warning(
                "intel.ledger: %s is schema v%s, expected v%s — migrating",
                path,
                stored,
                SCHEMA_VERSION,
            )
            _migrate(conn, stored if stored is not None else 0)
        _apply_schema(conn)
        return
    except sqlite3.DatabaseError as exc:
        if not _is_corrupt_database_error(exc):
            raise
        conn.close()
        quarantine = path.with_suffix(path.suffix + f".corrupt-{int(time.time() * 1000)}")
        log.warning(
            "intel.ledger: %s failed SQLite corruption checks — quarantining as %s",
            path,
            quarantine,
        )
        if path.exists():
            try:
                path.rename(quarantine)
            except OSError:
                path.unlink(missing_ok=True)
        conn = sqlite3.connect(str(path), timeout=30.0)
        conn.execute("PRAGMA busy_timeout=30000")
        try:
            _apply_schema(conn)
        finally:
            conn.close()
        return
    finally:
        try:
            conn.close()
        except Exception:  # noqa: BLE001 — best effort
            pass


def _ensure_schema(path: Path) -> None:
    key = str(path)
    if _SETUP_DONE.get(key):
        return
    with _SETUP_LOCK:
        if _SETUP_DONE.get(key):
            return
        path.parent.mkdir(parents=True, exist_ok=True)
        _open_or_reset(path)
        _SETUP_DONE[key] = True


def connect(path: Path | None = None) -> sqlite3.Connection:
    target = Path(path) if path else default_path()
    _ensure_schema(target)
    conn = sqlite3.connect(str(target), timeout=30.0)
    conn.execute("PRAGMA busy_timeout=30000")
    conn.row_factory = sqlite3.Row
    return conn


def reset_setup_cache() -> None:
    """Test hook — forget which paths have had their schema applied."""
    with _SETUP_LOCK:
        _SETUP_DONE.clear()


# ── ingestion ────────────────────────────────────────────────────────


@dataclass(frozen=True)
class IngestResult:
    movements_seen: int = 0
    movements_inserted: int = 0
    transactions_inserted: int = 0

    @property
    def movements_skipped(self) -> int:
        """Rows already present — the dedup hit count.  A re-ingest of
        identical data has ``movements_inserted == 0`` and this equal
        to ``movements_seen``."""
        return self.movements_seen - self.movements_inserted


def _norm_tx_type(value: Any) -> str:
    tx_type = str(value or "").strip().lower()
    return tx_type if tx_type in INGESTED_TX_TYPES else ""


def ingest_events(
    events: Iterable[dict[str, Any]],
    *,
    conn: sqlite3.Connection | None = None,
    path: Path | None = None,
) -> IngestResult:
    """Insert crawler events as normalized movements.  Idempotent.

    Accepts the crawler's event shape verbatim (``eventId``, ``txId``,
    ``leagueId``, ``ownerId``, ``assetId``, ``assetType``, ``action``,
    ``txType``, ``ts``, ``week``, ``faabBid``) so the crawler needs no
    changes to feed the ledger, and so existing JSON snapshots migrate
    through the same path.

    Every insert is ``INSERT OR IGNORE`` on the deterministic
    ``movement_id``.  Re-ingesting the same events inserts nothing.

    That guarantee is only as good as the key.  Since D10 the crawler
    keys ``eventId`` on the roster SLOT rather than the attributed
    owner, so a co-ownership change can no longer manufacture a second
    id for a movement already stored — see ``crawler.py::emit``.
    """
    own_conn = conn is None
    conn = conn or connect(path)
    now = _now_ms()
    seen = 0
    inserted = 0
    tx_inserted = 0
    try:
        for event in events or []:
            if not isinstance(event, dict):
                continue
            movement_id = str(event.get("eventId") or "").strip()
            tx_id = str(event.get("txId") or "").strip()
            asset_id = str(event.get("assetId") or "").strip()
            user_id = str(event.get("ownerId") or "").strip()
            action = str(event.get("action") or "").strip()
            tx_type = _norm_tx_type(event.get("txType"))
            ts_raw = event.get("ts")
            if not movement_id or not tx_id or not asset_id or not user_id:
                continue
            if action not in (ACTION_BUY, ACTION_SELL):
                continue
            if not tx_type:
                continue
            if not isinstance(ts_raw, (int, float)) or ts_raw <= 0:
                continue
            ts = int(ts_raw)
            week = event.get("week")
            week = int(week) if isinstance(week, (int, float)) else None
            faab = event.get("faabBid")
            faab = int(faab) if isinstance(faab, (int, float)) else None
            asset_type = str(event.get("assetType") or "").strip() or (
                "pick" if asset_id.startswith("pick:") else "player"
            )
            league_id = str(event.get("leagueId") or "").strip()

            seen += 1
            cur = conn.execute(
                """
                INSERT OR IGNORE INTO transactions
                  (tx_id, league_id, season, week, tx_type, status, created_ms, ingested_ms)
                VALUES (?, ?, ?, ?, ?, 'complete', ?, ?)
                """,
                (
                    tx_id,
                    league_id,
                    str(event.get("season") or "") or None,
                    week,
                    tx_type,
                    ts,
                    now,
                ),
            )
            tx_inserted += cur.rowcount if cur.rowcount and cur.rowcount > 0 else 0

            cur = conn.execute(
                """
                INSERT OR IGNORE INTO asset_movements
                  (movement_id, tx_id, league_id, tx_type, asset_id, asset_type,
                   action, user_id, roster_id, counterparty_user_id, ts, week,
                   faab_bid, ingested_ms)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    movement_id,
                    tx_id,
                    league_id,
                    tx_type,
                    asset_id,
                    asset_type,
                    action,
                    user_id,
                    str(event.get("rosterId") or "") or None,
                    str(event.get("counterpartyUserId") or "") or None,
                    ts,
                    week,
                    faab,
                    now,
                ),
            )
            if cur.rowcount and cur.rowcount > 0:
                inserted += 1
        conn.commit()
    finally:
        if own_conn:
            conn.close()
    return IngestResult(
        movements_seen=seen,
        movements_inserted=inserted,
        transactions_inserted=tx_inserted,
    )


def upsert_users(
    users: Iterable[dict[str, Any]],
    *,
    conn: sqlite3.Connection | None = None,
    path: Path | None = None,
) -> int:
    """Record Sleeper users, keyed on the STABLE global ``user_id``.

    Usernames change; the id does not.  When a known user turns up
    under a new username the old one is appended to
    ``username_history`` rather than overwritten, so a rename never
    looks like a new manager and never silently rewrites history.
    """
    own_conn = conn is None
    conn = conn or connect(path)
    now = _now_ms()
    written = 0
    try:
        for user in users or []:
            if not isinstance(user, dict):
                continue
            user_id = str(user.get("user_id") or user.get("userId") or "").strip()
            if not user_id:
                continue
            username = str(user.get("username") or "").strip() or None
            display = str(user.get("display_name") or user.get("displayName") or "").strip() or None
            row = conn.execute(
                "SELECT current_username, username_history, first_seen_ms FROM sleeper_users WHERE user_id = ?",
                (user_id,),
            ).fetchone()
            if row is None:
                conn.execute(
                    """
                    INSERT INTO sleeper_users
                      (user_id, current_username, display_name, username_history,
                       first_seen_ms, last_seen_ms)
                    VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    (user_id, username, display, "", now, now),
                )
                written += 1
                continue
            history = [h for h in str(row["username_history"] or "").split("\n") if h]
            prior = row["current_username"]
            if username and prior and username != prior and prior not in history:
                history.append(prior)
            conn.execute(
                """
                UPDATE sleeper_users
                   SET current_username = COALESCE(?, current_username),
                       display_name     = COALESCE(?, display_name),
                       username_history = ?,
                       last_seen_ms     = ?
                 WHERE user_id = ?
                """,
                (username, display, "\n".join(history), now, user_id),
            )
            written += 1
        conn.commit()
    finally:
        if own_conn:
            conn.close()
    return written


def upsert_leagues(
    leagues: Iterable[dict[str, Any]],
    *,
    conn: sqlite3.Connection | None = None,
    path: Path | None = None,
) -> int:
    own_conn = conn is None
    conn = conn or connect(path)
    now = _now_ms()
    written = 0
    try:
        for league in leagues or []:
            if not isinstance(league, dict):
                continue
            league_id = str(league.get("league_id") or league.get("leagueId") or "").strip()
            if not league_id:
                continue
            conn.execute(
                """
                INSERT INTO leagues
                  (league_id, season, previous_league_id, name, total_rosters,
                   settings_json, first_seen_ms, last_crawled_ms)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(league_id) DO UPDATE SET
                  season             = COALESCE(excluded.season, leagues.season),
                  previous_league_id = COALESCE(excluded.previous_league_id, leagues.previous_league_id),
                  name               = COALESCE(excluded.name, leagues.name),
                  total_rosters      = COALESCE(excluded.total_rosters, leagues.total_rosters),
                  settings_json      = COALESCE(excluded.settings_json, leagues.settings_json),
                  last_crawled_ms    = excluded.last_crawled_ms
                """,
                (
                    league_id,
                    str(league.get("season") or "") or None,
                    str(league.get("previous_league_id") or "") or None,
                    str(league.get("name") or "") or None,
                    league.get("total_rosters"),
                    league.get("settings_json"),
                    now,
                    now,
                ),
            )
            written += 1
        conn.commit()
    finally:
        if own_conn:
            conn.close()
    return written


def upsert_memberships(
    rows: Iterable[tuple[str, str, str | None]],
    *,
    conn: sqlite3.Connection | None = None,
    path: Path | None = None,
) -> int:
    """``(league_id, user_id, roster_id)`` triples."""
    own_conn = conn is None
    conn = conn or connect(path)
    now = _now_ms()
    written = 0
    try:
        for league_id, user_id, roster_id in rows or []:
            lid = str(league_id or "").strip()
            uid = str(user_id or "").strip()
            if not lid or not uid:
                continue
            conn.execute(
                """
                INSERT INTO league_memberships (league_id, user_id, roster_id, last_seen_ms)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(league_id, user_id) DO UPDATE SET
                  roster_id    = COALESCE(excluded.roster_id, league_memberships.roster_id),
                  last_seen_ms = excluded.last_seen_ms
                """,
                (lid, uid, str(roster_id or "") or None, now),
            )
            written += 1
        conn.commit()
    finally:
        if own_conn:
            conn.close()
    return written


def prune(
    *,
    now_ms: int | None = None,
    retention_days: int = MOVEMENT_RETENTION_DAYS,
    conn: sqlite3.Connection | None = None,
    path: Path | None = None,
) -> int:
    """Drop movements older than the retention horizon, then any
    transaction left with no movements.  Returns movements removed."""
    own_conn = conn is None
    conn = conn or connect(path)
    now = now_ms if now_ms is not None else _now_ms()
    cutoff = now - int(retention_days) * 24 * 3600 * 1000
    try:
        cur = conn.execute("DELETE FROM asset_movements WHERE ts < ?", (cutoff,))
        removed = cur.rowcount or 0
        conn.execute(
            "DELETE FROM transactions WHERE tx_id NOT IN (SELECT DISTINCT tx_id FROM asset_movements)"
        )
        conn.commit()
    finally:
        if own_conn:
            conn.close()
    return removed


# ── queries ──────────────────────────────────────────────────────────


def _placeholders(values: Sequence[Any]) -> str:
    return ",".join("?" for _ in values)


def _window_clause(
    *,
    since_ms: int | None,
    until_ms: int | None,
    tx_types: Sequence[str],
    league_ids: Sequence[str] | None,
    user_ids: Sequence[str] | None,
    asset_type: str | None,
) -> tuple[str, list[Any]]:
    clauses: list[str] = []
    params: list[Any] = []
    if since_ms is not None:
        clauses.append("ts >= ?")
        params.append(int(since_ms))
    if until_ms is not None:
        clauses.append("ts <= ?")
        params.append(int(until_ms))
    if tx_types:
        clauses.append(f"tx_type IN ({_placeholders(tx_types)})")
        params.extend(tx_types)
    if league_ids:
        clauses.append(f"league_id IN ({_placeholders(league_ids)})")
        params.extend(league_ids)
    if user_ids:
        clauses.append(f"user_id IN ({_placeholders(user_ids)})")
        params.extend(user_ids)
    if asset_type:
        clauses.append("asset_type = ?")
        params.append(asset_type)
    where = (" WHERE " + " AND ".join(clauses)) if clauses else ""
    return where, params


def asset_signals(
    *,
    since_ms: int | None = None,
    until_ms: int | None = None,
    tx_types: Sequence[str] = TRADE_TX_TYPES,
    league_ids: Sequence[str] | None = None,
    user_ids: Sequence[str] | None = None,
    asset_type: str | None = None,
    limit: int | None = None,
    conn: sqlite3.Connection | None = None,
    path: Path | None = None,
) -> list[dict[str, Any]]:
    """Per-asset buy/sell aggregation for ONE window.

    This is a single independent query over the raw movement rows.  To
    get several windows, call it several times — each result stands
    alone and they are NEVER added together.  A movement 15 days old
    appears in the 30d result and the 90d result because it is one
    movement viewed twice, not two movements.

    ``tx_types`` defaults to trades only.  Passing waiver types here
    produces a waiver-activity report, which callers must label as
    such — the returned keys are still ``buys``/``sells`` structurally,
    so the LABEL is the caller's responsibility and the default keeps
    the dangerous case out of reach.

    Returned per asset::

        assetId, assetType,
        buys, sells, net, volume, buyRate,
        uniqueBuyers, uniqueSellers, uniqueManagers,
        uniqueLeagues, tradeCount, movementCount, lastTs
    """
    own_conn = conn is None
    conn = conn or connect(path)
    where, params = _window_clause(
        since_ms=since_ms,
        until_ms=until_ms,
        tx_types=tuple(tx_types or ()),
        league_ids=league_ids,
        user_ids=user_ids,
        asset_type=asset_type,
    )
    sql = f"""
        SELECT
          asset_id,
          MIN(asset_type)                                                AS asset_type,
          SUM(CASE WHEN action = 'add'  THEN 1 ELSE 0 END)               AS buys,
          SUM(CASE WHEN action = 'drop' THEN 1 ELSE 0 END)               AS sells,
          COUNT(DISTINCT CASE WHEN action = 'add'  THEN user_id END)     AS unique_buyers,
          COUNT(DISTINCT CASE WHEN action = 'drop' THEN user_id END)     AS unique_sellers,
          COUNT(DISTINCT user_id)                                        AS unique_managers,
          COUNT(DISTINCT league_id)                                      AS unique_leagues,
          COUNT(DISTINCT tx_id)                                          AS trade_count,
          COUNT(*)                                                       AS movement_count,
          MAX(ts)                                                        AS last_ts
        FROM asset_movements
        {where}
        GROUP BY asset_id
    """
    try:
        rows = conn.execute(sql, params).fetchall()
    finally:
        if own_conn:
            conn.close()

    out: list[dict[str, Any]] = []
    for row in rows:
        buys = int(row["buys"] or 0)
        sells = int(row["sells"] or 0)
        volume = buys + sells
        out.append(
            {
                "assetId": row["asset_id"],
                "assetType": row["asset_type"],
                "buys": buys,
                "sells": sells,
                "net": buys - sells,
                "volume": volume,
                "buyRate": (buys / volume) if volume else None,
                "uniqueBuyers": int(row["unique_buyers"] or 0),
                "uniqueSellers": int(row["unique_sellers"] or 0),
                "uniqueManagers": int(row["unique_managers"] or 0),
                "uniqueLeagues": int(row["unique_leagues"] or 0),
                "tradeCount": int(row["trade_count"] or 0),
                "movementCount": int(row["movement_count"] or 0),
                "lastTs": int(row["last_ts"] or 0) or None,
            }
        )
    out.sort(key=lambda a: (-a["volume"], -abs(a["net"]), a["assetId"]))
    if limit is not None:
        out = out[: max(0, int(limit))]
    return out


def asset_movements_for(
    asset_id: str,
    *,
    since_ms: int | None = None,
    until_ms: int | None = None,
    tx_types: Sequence[str] = TRADE_TX_TYPES,
    league_ids: Sequence[str] | None = None,
    user_ids: Sequence[str] | None = None,
    limit: int = 200,
    conn: sqlite3.Connection | None = None,
    path: Path | None = None,
) -> list[dict[str, Any]]:
    """The underlying movement rows behind an asset's counts, so any
    number on screen can be audited back to its transactions."""
    own_conn = conn is None
    conn = conn or connect(path)
    where, params = _window_clause(
        since_ms=since_ms,
        until_ms=until_ms,
        tx_types=tuple(tx_types or ()),
        league_ids=league_ids,
        user_ids=user_ids,
        asset_type=None,
    )
    joiner = " AND " if where else " WHERE "
    sql = f"""
        SELECT movement_id, tx_id, league_id, tx_type, asset_id, asset_type,
               action, user_id, counterparty_user_id, ts, week, faab_bid
          FROM asset_movements
          {where}{joiner}asset_id = ?
         ORDER BY ts DESC
         LIMIT ?
    """
    params = [*params, str(asset_id), max(1, int(limit))]
    try:
        rows = conn.execute(sql, params).fetchall()
    finally:
        if own_conn:
            conn.close()
    return [
        {
            "movementId": r["movement_id"],
            "txId": r["tx_id"],
            "leagueId": r["league_id"],
            "txType": r["tx_type"],
            "assetId": r["asset_id"],
            "assetType": r["asset_type"],
            "action": r["action"],
            "userId": r["user_id"],
            "counterpartyUserId": r["counterparty_user_id"],
            "ts": int(r["ts"]),
            "week": r["week"],
            "faabBid": r["faab_bid"],
        }
        for r in rows
    ]


def manager_asset_activity(
    *,
    user_ids: Sequence[str],
    asset_id: str | None = None,
    since_ms: int | None = None,
    until_ms: int | None = None,
    tx_types: Sequence[str] = TRADE_TX_TYPES,
    exclude_league_ids: Sequence[str] | None = None,
    conn: sqlite3.Connection | None = None,
    path: Path | None = None,
) -> list[dict[str, Any]]:
    """Per-(manager, asset) buy/sell counts — the revealed-preference
    primitive Insider Trading is built on.

    ``exclude_league_ids`` removes the league the user is asking about,
    so "has my league-mate bought this player ELSEWHERE" never counts
    activity from the league we are already looking at.
    """
    if not user_ids:
        return []
    own_conn = conn is None
    conn = conn or connect(path)
    where, params = _window_clause(
        since_ms=since_ms,
        until_ms=until_ms,
        tx_types=tuple(tx_types or ()),
        league_ids=None,
        user_ids=tuple(str(u) for u in user_ids),
        asset_type=None,
    )
    extra = ""
    if asset_id:
        extra += " AND asset_id = ?"
        params.append(str(asset_id))
    if exclude_league_ids:
        extra += f" AND league_id NOT IN ({_placeholders(exclude_league_ids)})"
        params.extend(str(lid) for lid in exclude_league_ids)
    sql = f"""
        SELECT user_id,
               asset_id,
               MIN(asset_type)                                          AS asset_type,
               SUM(CASE WHEN action = 'add'  THEN 1 ELSE 0 END)         AS buys,
               SUM(CASE WHEN action = 'drop' THEN 1 ELSE 0 END)         AS sells,
               COUNT(DISTINCT league_id)                                AS unique_leagues,
               COUNT(DISTINCT tx_id)                                    AS trade_count,
               MAX(ts)                                                  AS last_ts
          FROM asset_movements
          {where or " WHERE 1=1"}{extra}
         GROUP BY user_id, asset_id
    """
    try:
        rows = conn.execute(sql, params).fetchall()
    finally:
        if own_conn:
            conn.close()
    return [
        {
            "userId": r["user_id"],
            "assetId": r["asset_id"],
            "assetType": r["asset_type"],
            "buys": int(r["buys"] or 0),
            "sells": int(r["sells"] or 0),
            "net": int(r["buys"] or 0) - int(r["sells"] or 0),
            "volume": int(r["buys"] or 0) + int(r["sells"] or 0),
            "uniqueLeagues": int(r["unique_leagues"] or 0),
            "tradeCount": int(r["trade_count"] or 0),
            "lastTs": int(r["last_ts"] or 0) or None,
        }
        for r in rows
    ]


def counts(
    *,
    since_ms: int | None = None,
    until_ms: int | None = None,
    tx_types: Sequence[str] = TRADE_TX_TYPES,
    league_ids: Sequence[str] | None = None,
    user_ids: Sequence[str] | None = None,
    conn: sqlite3.Connection | None = None,
    path: Path | None = None,
) -> dict[str, int]:
    """The three units, counted separately and correctly, for one
    window.  Never add two of these results together."""
    own_conn = conn is None
    conn = conn or connect(path)
    where, params = _window_clause(
        since_ms=since_ms,
        until_ms=until_ms,
        tx_types=tuple(tx_types or ()),
        league_ids=league_ids,
        user_ids=user_ids,
        asset_type=None,
    )
    sql = f"""
        SELECT COUNT(DISTINCT tx_id)                                  AS trade_count,
               COUNT(DISTINCT movement_id)                            AS movement_count,
               SUM(CASE WHEN action = 'add'  THEN 1 ELSE 0 END)       AS buy_count,
               SUM(CASE WHEN action = 'drop' THEN 1 ELSE 0 END)       AS sell_count,
               COUNT(DISTINCT user_id)                                AS unique_managers,
               COUNT(DISTINCT league_id)                              AS unique_leagues
          FROM asset_movements
          {where}
    """
    try:
        row = conn.execute(sql, params).fetchone()
    finally:
        if own_conn:
            conn.close()
    return {
        "tradeCount": int(row["trade_count"] or 0),
        "assetMovementCount": int(row["movement_count"] or 0),
        "buyCount": int(row["buy_count"] or 0),
        "sellCount": int(row["sell_count"] or 0),
        "uniqueManagerCount": int(row["unique_managers"] or 0),
        "uniqueLeagueCount": int(row["unique_leagues"] or 0),
    }


def coverage(
    *,
    conn: sqlite3.Connection | None = None,
    path: Path | None = None,
) -> dict[str, Any]:
    """What the ledger actually observes — so the UI can say "across
    the leagues and window available to us" instead of implying global
    Sleeper coverage."""
    own_conn = conn is None
    conn = conn or connect(path)
    try:
        row = conn.execute(
            """
            SELECT MIN(ts) AS earliest, MAX(ts) AS latest,
                   COUNT(*) AS movements,
                   COUNT(DISTINCT league_id) AS leagues,
                   COUNT(DISTINCT user_id) AS managers,
                   COUNT(DISTINCT tx_id) AS transactions
              FROM asset_movements
            """
        ).fetchone()
        by_type = {
            r["tx_type"]: int(r["n"] or 0)
            for r in conn.execute(
                "SELECT tx_type, COUNT(*) AS n FROM asset_movements GROUP BY tx_type"
            ).fetchall()
        }
    finally:
        if own_conn:
            conn.close()
    return {
        "earliestObservedTs": int(row["earliest"]) if row["earliest"] else None,
        "latestObservedTs": int(row["latest"]) if row["latest"] else None,
        "movementCount": int(row["movements"] or 0),
        "leagueCount": int(row["leagues"] or 0),
        "managerCount": int(row["managers"] or 0),
        "transactionCount": int(row["transactions"] or 0),
        "movementsByTxType": by_type,
        "retentionDays": MOVEMENT_RETENTION_DAYS,
        "complete": False,
        "coverageNote": (
            "Observations are limited to the leagues this platform has crawled "
            "and to the retention horizon; they are not a complete view of Sleeper."
        ),
    }
