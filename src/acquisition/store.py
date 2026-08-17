"""The three acquisition tables, and the rules that make them a ledger.

IDEMPOTENCE, STATED AS THREE DIFFERENT PROMISES
───────────────────────────────────────────────
``acquisition_events`` is INSERT-only.  Re-ingesting the identical event
is a no-op; re-ingesting the same key with DIFFERENT facts is a
**conflict that is reported and not applied**, because silently taking
the newer value would make the ledger's history depend on how many
times a collector happened to run.

``holdings`` and ``pick_lineage`` are **pure replay derivations**.
Rebuilding them from the same events is byte-identical, so the backfill
is always safe to re-run and there is no migration to get wrong.  They
are rebuilt wholesale per league rather than patched in place — a
derivation that can be patched is a derivation that can drift from the
events it claims to summarise.

PRIVACY
───────
``data/retention/acquisition.sqlite`` — same root as
``league_events.sqlite`` so one env var redirects both, separate FILE so
backup and publication stay different gestures.  Mode 0600, gitignored,
never read by ``/api/public/*``.
"""

from __future__ import annotations

import sqlite3
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Sequence

from src.acquisition.events import AcquisitionEvent
from src.retention.evidence_store import RETENTION_DIR

DB_PATH: Path = RETENTION_DIR / "acquisition.sqlite"

SCHEMA_VERSION = 2

PRIVACY_CLASS = "private"

_SETUP_LOCK = threading.Lock()
_SETUP_DONE: dict[str, bool] = {}

_SCHEMA = """
CREATE TABLE IF NOT EXISTS meta (
    key   TEXT PRIMARY KEY,
    value TEXT
);

CREATE TABLE IF NOT EXISTS acquisition_events (
    -- Identity.  An asset moves at most once inside one transaction,
    -- so these three are a natural key.  A three-team trade is N rows
    -- sharing one source_ref -- the multi-party shape is preserved,
    -- never flattened into fictional two-party trades.
    league_key        TEXT NOT NULL,
    source_ref        TEXT NOT NULL,   -- 'tx:<id>' | 'draft:<draft_id>:<pick_no>'
    asset_id          TEXT NOT NULL,   -- 'player:<sleeperId>' | canonical league-pick id

    asset_kind        TEXT NOT NULL,   -- 'player' | 'pick'
    event_type        TEXT NOT NULL,   -- an ACQUISITION_METHODS / DISPOSAL_METHODS value
    after_owner_rid   INTEGER,         -- NULL = left every roster
    before_owner_rid  INTEGER,         -- NULL = came from outside the league

    -- MANAGER identity.  A roster id is stable only WITHIN one Sleeper
    -- league id, and a registry league spans several across seasons, so
    -- roster id alone cannot answer "which human".  NULL = the
    -- roster->owner map could not be resolved: unattributed, not guessed.
    after_owner_user_id  TEXT,
    before_owner_user_id TEXT,

    -- Sleeper's own draft ``type`` for a DRAFT event (rookie / startup /
    -- auction / ...).  A startup auction and a rookie draft are
    -- different acquisition facts with different cost-basis semantics.
    -- NULL for non-draft events and for a draft that reported no type.
    draft_kind        TEXT,

    -- The pick slot this event realized, for a pick asset.  Load-bearing
    -- for cost basis: with a slot, market_resolution distinguishes the
    -- exact-slot grade from the tier grade USING THE CLOCK AS OF THE
    -- EVENT; without one it answers the generic grade and never reads
    -- the clock.  NULL = slot genuinely unknown.  Never 0.
    realized_slot     INTEGER,

    sleeper_league_id TEXT,
    season            TEXT,
    week              INTEGER,

    -- NULL when Sleeper gave us no stamp.  An undated event is not an
    -- event dated zero, and time_fidelity says which this is.
    occurred_at_ms    INTEGER,
    time_fidelity     TEXT NOT NULL,   -- 'exact' | 'undated'

    -- NULL = not a waiver / not an auction.  0 = a waiver that cost
    -- nothing / a $0 auction price.  These are different facts.
    faab_bid          INTEGER,
    auction_amount    INTEGER,

    source            TEXT NOT NULL,
    content_hash      TEXT NOT NULL,
    first_recorded_at TEXT NOT NULL,
    last_seen_at      TEXT NOT NULL,

    PRIMARY KEY (league_key, source_ref, asset_id)
);

CREATE INDEX IF NOT EXISTS idx_acq_asset
    ON acquisition_events(league_key, asset_id, occurred_at_ms);
CREATE INDEX IF NOT EXISTS idx_acq_owner
    ON acquisition_events(league_key, after_owner_rid, occurred_at_ms);

CREATE TABLE IF NOT EXISTS holdings (
    league_key      TEXT NOT NULL,
    asset_id        TEXT NOT NULL,
    owner_rid       INTEGER NOT NULL,
    -- Manager identity for this holding period.  NULL when the
    -- roster->owner map could not be resolved.
    owner_user_id   TEXT,
    -- Reacquisition opens a NEW period rather than editing the old
    -- one, so "he owned him twice" is representable.
    sequence_num    INTEGER NOT NULL,

    -- Carried onto the holding so cost basis can hand it to
    -- market_resolution; see the acquisition_events column comment.
    realized_slot   INTEGER,

    acquired_at_ms  INTEGER,
    acquired_ref    TEXT NOT NULL,
    acquired_method TEXT NOT NULL,

    disposed_at_ms  INTEGER,
    disposed_ref    TEXT,
    disposed_method TEXT,

    -- Cost basis: what the asset was known to be worth at acquisition.
    -- NULL + a reason, never 0 and never today's value.
    basis_value          REAL,
    basis_fidelity       TEXT,
    basis_missing_reason TEXT,

    -- 'ordered' when every contributing event carried a timestamp;
    -- names the degradation when one did not.
    order_fidelity  TEXT NOT NULL,

    PRIMARY KEY (league_key, asset_id, owner_rid, sequence_num)
);

CREATE INDEX IF NOT EXISTS idx_hold_owner
    ON holdings(league_key, owner_rid, acquired_at_ms);

CREATE TABLE IF NOT EXISTS pick_lineage (
    league_key     TEXT NOT NULL,
    -- LeaguePickIdentity.canonical_id: survives ownership transfer AND
    -- slot realization by construction, which is why C1-U3 is a hard
    -- dependency and no acquisition-local pick id is ever minted.
    pick_id        TEXT NOT NULL,
    hop_num        INTEGER NOT NULL,
    from_rid       INTEGER,
    to_rid         INTEGER NOT NULL,
    from_user_id   TEXT,
    to_user_id     TEXT,
    -- Slot at the moment of this hop, when known.  A pick keeps ONE
    -- identity across realization (C1-U3: owner and slot are STATE), so
    -- this is hop state, never a second asset.
    realized_slot  INTEGER,
    source_ref     TEXT NOT NULL,
    occurred_at_ms INTEGER,

    PRIMARY KEY (league_key, pick_id, hop_num)
);
"""

_EVENT_COLS: Sequence[str] = (
    "league_key",
    "source_ref",
    "asset_id",
    "asset_kind",
    "event_type",
    "after_owner_rid",
    "before_owner_rid",
    "after_owner_user_id",
    "before_owner_user_id",
    "sleeper_league_id",
    "season",
    "week",
    "occurred_at_ms",
    "time_fidelity",
    "faab_bid",
    "auction_amount",
    "draft_kind",
    "realized_slot",
    "source",
    "content_hash",
)


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


def write_events(events: Iterable[AcquisitionEvent], *, path: Path | None = None) -> dict[str, Any]:
    """INSERT-only write.  Returns a report, and NEVER raises on data.

    ``conflicts`` lists keys already present with a different
    ``content_hash``.  They are reported and **not applied**: a ledger
    whose past changes when a collector re-runs is not a ledger.
    Resolving one is a deliberate act (a correction row, or a fix to the
    normaliser), not a side effect of collection.
    """
    rows = list(events)
    if not rows:
        return {"inserted": 0, "unchanged": 0, "conflicts": []}

    now = _utc_now()
    conn = connect(path)
    inserted = 0
    unchanged = 0
    conflicts: list[dict[str, Any]] = []
    try:
        for ev in rows:
            existing = conn.execute(
                "SELECT content_hash FROM acquisition_events "
                "WHERE league_key = ? AND source_ref = ? AND asset_id = ?",
                (ev.league_key, ev.source_ref, ev.asset_id),
            ).fetchone()
            digest = ev.content_hash()
            if existing is not None:
                if existing[0] == digest:
                    conn.execute(
                        "UPDATE acquisition_events SET last_seen_at = ? "
                        "WHERE league_key = ? AND source_ref = ? AND asset_id = ?",
                        (now, ev.league_key, ev.source_ref, ev.asset_id),
                    )
                    unchanged += 1
                else:
                    conflicts.append(
                        {
                            "leagueKey": ev.league_key,
                            "sourceRef": ev.source_ref,
                            "assetId": ev.asset_id,
                            "storedHash": existing[0],
                            "offeredHash": digest,
                        }
                    )
                continue

            conn.execute(
                f"INSERT INTO acquisition_events ({', '.join(_EVENT_COLS)}, "
                f"first_recorded_at, last_seen_at) "
                f"VALUES ({', '.join('?' * len(_EVENT_COLS))}, ?, ?)",
                (
                    ev.league_key,
                    ev.source_ref,
                    ev.asset_id,
                    ev.asset_kind,
                    ev.event_type,
                    ev.after_owner_rid,
                    ev.before_owner_rid,
                    ev.after_owner_user_id,
                    ev.before_owner_user_id,
                    ev.sleeper_league_id,
                    ev.season,
                    ev.week,
                    ev.occurred_at_ms,
                    ev.time_fidelity,
                    ev.faab_bid,
                    ev.auction_amount,
                    ev.draft_kind,
                    ev.realized_slot,
                    ev.source,
                    digest,
                    now,
                    now,
                ),
            )
            inserted += 1
        conn.commit()
    finally:
        conn.close()

    return {
        "inserted": inserted,
        "unchanged": unchanged,
        "conflicts": conflicts,
        "offered": len(rows),
    }


def read_events(league_key: str, *, path: Path | None = None) -> list[dict[str, Any]]:
    """Every recorded event for one league, in REPLAY order.

    Undated events sort FIRST, and the derivation stamps
    ``order_fidelity`` when any are present.  They cannot be ordered
    against dated ones, so treating them as the earliest baseline is the
    conservative reading — and the flag means a consumer is never told a
    partially-unorderable history is fully ordered.  Ties break on
    ``source_ref`` then ``asset_id``, so out-of-order ingestion and
    identical timestamps both converge on one state.
    """
    conn = connect(path)
    try:
        cur = conn.execute(
            f"SELECT {', '.join(_EVENT_COLS)} FROM acquisition_events "
            "WHERE league_key = ? "
            "ORDER BY (occurred_at_ms IS NULL) DESC, occurred_at_ms ASC, "
            "source_ref ASC, asset_id ASC",
            (league_key,),
        )
        cols = [c[0] for c in cur.description]
        return [dict(zip(cols, row)) for row in cur.fetchall()]
    finally:
        conn.close()


def replace_derivations(
    league_key: str,
    holdings: Sequence[dict[str, Any]],
    lineage: Sequence[dict[str, Any]],
    *,
    path: Path | None = None,
) -> dict[str, int]:
    """Rebuild one league's derived tables, wholesale and atomically.

    Wholesale rather than incremental because these are derivations: a
    partial update is how a summary silently stops agreeing with the
    events it summarises.  Scoped to one league so rebuilding one
    cannot touch another's rows.
    """
    conn = connect(path)
    try:
        conn.execute("BEGIN")
        conn.execute("DELETE FROM holdings WHERE league_key = ?", (league_key,))
        conn.execute("DELETE FROM pick_lineage WHERE league_key = ?", (league_key,))
        conn.executemany(
            "INSERT INTO holdings (league_key, asset_id, owner_rid, owner_user_id, "
            "sequence_num, realized_slot, acquired_at_ms, acquired_ref, acquired_method, "
            "disposed_at_ms, disposed_ref, disposed_method, basis_value, basis_fidelity, "
            "basis_missing_reason, order_fidelity) VALUES (:league_key, :asset_id, "
            ":owner_rid, :owner_user_id, :sequence_num, :realized_slot, :acquired_at_ms, "
            ":acquired_ref, :acquired_method, :disposed_at_ms, :disposed_ref, "
            ":disposed_method, :basis_value, :basis_fidelity, :basis_missing_reason, "
            ":order_fidelity)",
            list(holdings),
        )
        conn.executemany(
            "INSERT INTO pick_lineage (league_key, pick_id, hop_num, from_rid, to_rid, "
            "from_user_id, to_user_id, realized_slot, source_ref, occurred_at_ms) "
            "VALUES (:league_key, :pick_id, :hop_num, :from_rid, :to_rid, :from_user_id, "
            ":to_user_id, :realized_slot, :source_ref, :occurred_at_ms)",
            list(lineage),
        )
        conn.commit()
    finally:
        conn.close()
    return {"holdings": len(holdings), "lineage": len(lineage)}


def coverage(*, path: Path | None = None) -> dict[str, Any]:
    """What the ledger holds.  Counts and stamps only — never rows.

    A health surface that echoed private acquisition contents would
    move the privacy boundary every time someone checked whether the
    collector was alive.
    """
    target = path or DB_PATH
    if not target.exists():
        return {"present": False, "path": str(target), "privacyClass": PRIVACY_CLASS}

    conn = connect(target)
    try:
        events = conn.execute("SELECT COUNT(*) FROM acquisition_events").fetchone()[0]
        leagues = conn.execute(
            "SELECT COUNT(DISTINCT league_key) FROM acquisition_events"
        ).fetchone()[0]
        undated = conn.execute(
            "SELECT COUNT(*) FROM acquisition_events WHERE occurred_at_ms IS NULL"
        ).fetchone()[0]
        holdings = conn.execute("SELECT COUNT(*) FROM holdings").fetchone()[0]
        unknown = conn.execute(
            "SELECT COUNT(*) FROM holdings WHERE acquired_method = 'IMPORT_UNKNOWN'"
        ).fetchone()[0]
        priced = conn.execute(
            "SELECT COUNT(*) FROM holdings WHERE basis_value IS NOT NULL"
        ).fetchone()[0]
        lineage = conn.execute("SELECT COUNT(*) FROM pick_lineage").fetchone()[0]
        picks = conn.execute("SELECT COUNT(DISTINCT pick_id) FROM pick_lineage").fetchone()[0]
        newest = conn.execute(
            "SELECT MAX(occurred_at_ms) FROM acquisition_events WHERE occurred_at_ms IS NOT NULL"
        ).fetchone()[0]
        oldest = conn.execute(
            "SELECT MIN(occurred_at_ms) FROM acquisition_events WHERE occurred_at_ms IS NOT NULL"
        ).fetchone()[0]
    finally:
        conn.close()

    return {
        "present": True,
        "path": str(target),
        "privacyClass": PRIVACY_CLASS,
        "events": int(events or 0),
        "leagues": int(leagues or 0),
        "undatedEvents": int(undated or 0),
        "holdings": int(holdings or 0),
        "holdingsImportUnknown": int(unknown or 0),
        "holdingsWithBasis": int(priced or 0),
        "lineageHops": int(lineage or 0),
        "picksWithLineage": int(picks or 0),
        "oldestOccurredAtMs": oldest,
        "newestOccurredAtMs": newest,
    }
