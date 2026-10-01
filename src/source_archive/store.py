"""Append-only store for source-native alternate-format dynasty boards.

Two tables: one row per archived BOARD (its provenance), and one row per
observation within it (the provider's own rank/value, kept in native
units). Identity is
``(provider, endpoint, format_key, run_id, captured_date)``, so the same
provider's four TE-premium states in one scrape cycle are four distinct
boards sharing a ``run_id`` — which is what makes them PAIRED evidence
rather than four snapshots taken at unknown different moments (§8).

Re-archiving an identical board is a no-op; re-archiving the same
identity with different content is surfaced, never silently applied —
the same posture ``src/history/store.py`` and ``src/acquisition/store.py``
already take, for the same reason.
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
import threading
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from src.source_archive.records import ArchivedRow
from src.utils.config_loader import repo_root

DB_PATH: Path = repo_root() / "data" / "source_archive" / "boards.sqlite"

SCHEMA_VERSION = 3

#: Format variants we ARCHIVE. Deliberately a different set from
#: :data:`PRODUCTION_ELIGIBLE` — see the package docstring. Nothing in
#: this module can move a key from one to the other; production
#: eligibility is membership of ``data_contract._RANKING_SOURCES``, which
#: lives in a module that does not import this one.
ARCHIVE_ELIGIBLE: frozenset[str] = frozenset(
    {
        # KTC's four TE-premium calibration states, on BOTH of the
        # quarterback formats KTC ships in every scrape response
        # (``oneQBValues`` / ``superflexValues``, each with
        # ``{value, tep, tepp, teppp}``).  Captured by
        # ``src/sources/ktc_format_archive.py`` (AL-P3) at zero extra
        # requests.  One provider, one family — eight calibration states of
        # one crowd, never eight votes.
        "ktc:sf_off",
        "ktc:sf_tep",
        "ktc:sf_tepp",
        "ktc:sf_teppp",
        "ktc:1qb_off",
        "ktc:1qb_tep",
        "ktc:1qb_tepp",
        "ktc:1qb_teppp",
    }
)

#: What may PRICE a dynasty asset. Empty here on purpose: this package
#: grants nothing. The real production gate is
#: ``data_contract._RANKING_SOURCES``, and the emptiness of this set is
#: the statement that archiving added no production capability.
PRODUCTION_ELIGIBLE: frozenset[str] = frozenset()

_SETUP_LOCK = threading.Lock()
_SETUP_DONE: dict[str, bool] = {}

_SCHEMA = """
CREATE TABLE IF NOT EXISTS meta (
    key   TEXT PRIMARY KEY,
    value TEXT
);

CREATE TABLE IF NOT EXISTS archived_boards (
    provider        TEXT NOT NULL,
    -- The B10 correlation group.  KTC's four TEP states share ONE
    -- family: they are algorithmic transformations of one base crowd
    -- value, not four crowds (spec 4.2).
    provider_family TEXT NOT NULL,
    endpoint        TEXT NOT NULL,
    -- Source-NATIVE format, e.g. sf_tepp / 1qb_off.  Never our
    -- normalized view of it.
    format_key      TEXT NOT NULL,
    game_type       TEXT NOT NULL,
    -- Ties variants captured in ONE cycle together, so paired
    -- comparisons are not contaminated by market movement between
    -- scrape dates (spec 8).
    run_id          TEXT NOT NULL,
    captured_date   TEXT NOT NULL,
    captured_at     TEXT NOT NULL,
    source_as_of    TEXT,
    row_count       INTEGER NOT NULL,
    rows_json       TEXT NOT NULL,
    -- Lane 8 / schema v2.  Per-row source-native records: rank, positional
    -- rank, tier, cardinal value, native unit, vendor id, position.
    -- ``rows_json`` above is one float per name and can hold none of
    -- those, which is fatal for a rank/tier-only source.  ADDITIVE:
    -- nullable, and every v1 reader keeps working off ``rows_json``.
    records_json    TEXT,
    -- Schema v3 (AL-P3).  Board-level provenance the identity columns cannot
    -- carry: e.g. the hash of the whole transferred payload this board was
    -- cut from, the variant's human label, the page URL.  ADDITIVE and
    -- nullable; it is NOT part of ``content_hash`` (that hashes the
    -- observations), so provenance can never make an identical board look
    -- like new evidence.
    provenance_json TEXT,
    content_hash    TEXT NOT NULL,
    first_seen_at   TEXT NOT NULL,

    PRIMARY KEY (provider, endpoint, format_key, run_id, captured_date)
);

CREATE INDEX IF NOT EXISTS idx_archive_family
    ON archived_boards(provider_family, captured_date);
CREATE INDEX IF NOT EXISTS idx_archive_run
    ON archived_boards(run_id);
CREATE INDEX IF NOT EXISTS idx_archive_latest
    ON archived_boards(provider, endpoint, format_key, captured_at);

-- Schema v3 (AL-P3).  "We looked, and the board was byte-identical to the
-- most recent archived board for this variant."  Written ONLY by the opt-in
-- de-duplicating writer (``archive_boards(..., skip_if_latest_identical=True)``)
-- INSTEAD of a second full copy of the same content.  So the absence of a new
-- board on a date never has to be read as "unchanged": for every run the
-- writer saw, either a board or a sighting exists, and the sighting names the
-- board that carries the content (``matched_run_id`` / ``matched_captured_at``).
CREATE TABLE IF NOT EXISTS board_sightings (
    provider            TEXT NOT NULL,
    endpoint            TEXT NOT NULL,
    format_key          TEXT NOT NULL,
    run_id              TEXT NOT NULL,
    captured_date       TEXT NOT NULL,
    captured_at         TEXT NOT NULL,
    content_hash        TEXT NOT NULL,
    matched_run_id      TEXT NOT NULL,
    matched_captured_at TEXT NOT NULL,
    recorded_at         TEXT NOT NULL,

    PRIMARY KEY (provider, endpoint, format_key, run_id, captured_date)
);
"""


@dataclass(frozen=True)
class ArchivedBoard:
    """One provider board, in one native format, from one run."""

    provider: str
    provider_family: str
    endpoint: str
    format_key: str
    game_type: str
    run_id: str
    rows: dict[str, float]
    captured_at: str = ""
    source_as_of: str | None = None
    content_hash: str = field(default="", compare=False)
    #: Source-native per-row records (schema v2).  Empty for a v1 board and
    #: for any source whose whole content really is one number per name.
    records: tuple[ArchivedRow, ...] = ()
    #: Board-level provenance (schema v3).  Deliberately outside
    #: :meth:`compute_hash` and outside equality: it describes HOW the board
    #: was observed, not WHAT was observed.
    provenance: dict[str, Any] = field(default_factory=dict, compare=False)

    @property
    def captured_date(self) -> str:
        return (self.captured_at or _utc_now())[:10]

    def compute_hash(self) -> str:
        payload: dict[str, Any] = {
            "rows": self.rows,
            "format_key": self.format_key,
            "game_type": self.game_type,
        }
        # Only present for v2 boards, so a v1 board's hash is unchanged and
        # re-archiving one stays the no-op it was.
        if self.records:
            payload["records"] = [r.to_dict() for r in self.records]
        blob = json.dumps(payload, sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(blob.encode("utf-8")).hexdigest()[:32]


class ArchiveRefused(ValueError):
    """A board that must not enter the archive (fail closed)."""


def _migrate_v2_to_v3(conn: sqlite3.Connection) -> None:
    """Add ``provenance_json`` to a database created under schema v1/v2.

    Additive and idempotent, for the same reason as :func:`_migrate_v1_to_v2`.
    """
    existing = {row[1] for row in conn.execute("PRAGMA table_info(archived_boards)")}
    if existing and "provenance_json" not in existing:
        conn.execute("ALTER TABLE archived_boards ADD COLUMN provenance_json TEXT")


def _migrate_v1_to_v2(conn: sqlite3.Connection) -> None:
    """Add ``records_json`` to a database created under schema v1.

    Additive and idempotent.  ``CREATE TABLE IF NOT EXISTS`` will not alter an
    existing table, so a v1 archive would otherwise keep its old shape while
    reporting ``schema_version = 2``.
    """
    existing = {row[1] for row in conn.execute("PRAGMA table_info(archived_boards)")}
    if existing and "records_json" not in existing:
        conn.execute("ALTER TABLE archived_boards ADD COLUMN records_json TEXT")


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


#: Default SQLite busy timeout (seconds) per lock acquisition.  A caller with
#: its own time budget passes a smaller ``timeout_s``.
DEFAULT_LOCK_TIMEOUT_SECONDS = 5.0


def _ensure_schema(path: Path, timeout_s: float = DEFAULT_LOCK_TIMEOUT_SECONDS) -> None:
    key = str(path)
    if _SETUP_DONE.get(key):
        return
    with _SETUP_LOCK:
        if _SETUP_DONE.get(key):
            return
        path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(str(path), timeout=timeout_s)
        try:
            conn.execute("PRAGMA journal_mode=WAL;")
            conn.executescript(_SCHEMA)
            _migrate_v1_to_v2(conn)
            _migrate_v2_to_v3(conn)
            conn.execute(
                "INSERT OR REPLACE INTO meta(key, value) VALUES ('schema_version', ?)",
                (str(SCHEMA_VERSION),),
            )
            conn.commit()
        finally:
            conn.close()
        _SETUP_DONE[key] = True


def connect(
    path: Path | None = None, *, timeout_s: float = DEFAULT_LOCK_TIMEOUT_SECONDS
) -> sqlite3.Connection:
    target = path or DB_PATH
    _ensure_schema(target, timeout_s)
    return sqlite3.connect(str(target), timeout=timeout_s)


def _reset_setup_cache_for_tests() -> None:
    with _SETUP_LOCK:
        _SETUP_DONE.clear()


def _refuse_unless_archivable(board: ArchivedBoard) -> None:
    """Fail closed on anything not proven ``DYNASTY``, and on an empty board.

    The same fail-closed rule the blend gate applies (``C1-SRC-02``). A
    board we cannot prove is dynasty does not become dynasty by being
    stored, and quarantining it "for diagnostics" inside the dynasty
    archive is exactly how it later gets used.
    """
    from src.api.data_contract import GAME_TYPE_DYNASTY, GAME_TYPES

    if board.game_type not in GAME_TYPES:
        raise ArchiveRefused(
            f"{board.provider}/{board.format_key}: game_type {board.game_type!r} is not in "
            f"the closed vocabulary {sorted(GAME_TYPES)}"
        )
    if board.game_type != GAME_TYPE_DYNASTY:
        raise ArchiveRefused(
            f"{board.provider}/{board.format_key}: game_type is {board.game_type!r}. "
            f"Only DYNASTY is eligible for the dynasty archive — unverified is never "
            f"dynasty, and a non-dynasty board stored here would be one query away from "
            f"being treated as dynasty evidence."
        )
    if not board.rows:
        raise ArchiveRefused(f"{board.provider}/{board.format_key}: empty board")


def archive_board(board: ArchivedBoard, *, path: Path | None = None) -> dict[str, Any]:
    """Archive one native-format board.

    Refuses anything not proven ``DYNASTY`` (:func:`_refuse_unless_archivable`).
    A one-board :func:`archive_boards` with no cross-run de-duplication, so
    behaviour is unchanged for its existing callers.
    """
    return archive_boards([board], path=path)[0]


def archive_boards(
    boards: list[ArchivedBoard] | tuple[ArchivedBoard, ...],
    *,
    path: Path | None = None,
    timeout_s: float = DEFAULT_LOCK_TIMEOUT_SECONDS,
    skip_if_latest_identical: bool = False,
) -> list[dict[str, Any]]:
    """Archive several boards ALL-OR-NOTHING: one connection, one transaction.

    Every board is validated before the database is touched, so one refused
    board refuses the batch.  The write lock is taken ONCE (``BEGIN
    IMMEDIATE``), waiting at most ``timeout_s``; any failure after that — a
    lock, a full disk, an interrupted write — rolls the whole batch back, so
    a run is never left half-archived for a later run to duplicate.

    ``skip_if_latest_identical``: a board whose ``content_hash`` equals the
    most recent archived board for the same (provider, endpoint, format_key)
    at or before its ``captured_at`` is NOT stored a second time; a
    ``board_sightings`` row records that this run observed it unchanged and
    names the board holding the content.  Opt-in, so existing callers keep
    exact append-every-board behaviour.

    Returns one result dict per input board, in input order.
    """
    batch = list(boards)
    for board in batch:
        _refuse_unless_archivable(board)
    if not batch:
        return []

    now = _utc_now()
    conn = connect(path, timeout_s=timeout_s)
    conn.isolation_level = None  # explicit transaction control below
    results: list[dict[str, Any]] = []
    try:
        conn.execute("BEGIN IMMEDIATE")
        for board in batch:
            results.append(_write_one(conn, board, now=now, dedupe=skip_if_latest_identical))
        conn.execute("COMMIT")
    except BaseException:
        if conn.in_transaction:
            conn.execute("ROLLBACK")
        raise
    finally:
        conn.close()
    return results


def _write_one(
    conn: sqlite3.Connection, board: ArchivedBoard, *, now: str, dedupe: bool
) -> dict[str, Any]:
    """One board inside the caller's open transaction.  Commits nothing."""
    captured_at = board.captured_at or now
    captured_date = captured_at[:10]
    digest = board.compute_hash()
    identity = (board.provider, board.endpoint, board.format_key, board.run_id, captured_date)

    existing = conn.execute(
        "SELECT content_hash FROM archived_boards WHERE provider = ? AND endpoint = ? "
        "AND format_key = ? AND run_id = ? AND captured_date = ?",
        identity,
    ).fetchone()
    if existing is not None:
        return {
            "archived": 0,
            "unchanged": int(existing[0] == digest),
            "conflict": None if existing[0] == digest else digest,
        }

    if dedupe:
        latest = conn.execute(
            "SELECT content_hash, run_id, captured_at FROM archived_boards "
            "WHERE provider = ? AND endpoint = ? AND format_key = ? AND captured_at <= ? "
            "ORDER BY captured_at DESC LIMIT 1",
            (board.provider, board.endpoint, board.format_key, captured_at),
        ).fetchone()
        if latest is not None and latest[0] == digest:
            conn.execute(
                "INSERT OR IGNORE INTO board_sightings (provider, endpoint, format_key, "
                "run_id, captured_date, captured_at, content_hash, matched_run_id, "
                "matched_captured_at, recorded_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (*identity, captured_at, digest, latest[1], latest[2], now),
            )
            return {
                "archived": 0,
                "unchanged": 0,
                "conflict": None,
                "deduplicated": 1,
                "matchedRunId": latest[1],
            }

    conn.execute(
        "INSERT INTO archived_boards (provider, provider_family, endpoint, format_key, "
        "game_type, run_id, captured_date, captured_at, source_as_of, row_count, "
        "rows_json, records_json, provenance_json, content_hash, first_seen_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (
            board.provider,
            board.provider_family,
            board.endpoint,
            board.format_key,
            board.game_type,
            board.run_id,
            captured_date,
            captured_at,
            board.source_as_of,
            len(board.rows),
            json.dumps(board.rows, sort_keys=True, separators=(",", ":")),
            (
                json.dumps(
                    [r.to_dict() for r in board.records],
                    sort_keys=True,
                    separators=(",", ":"),
                )
                if board.records
                else None
            ),
            (
                json.dumps(board.provenance, sort_keys=True, separators=(",", ":"))
                if board.provenance
                else None
            ),
            digest,
            now,
        ),
    )
    return {"archived": 1, "unchanged": 0, "conflict": None}


def read_boards(
    *, provider_family: str | None = None, run_id: str | None = None, path: Path | None = None
) -> list[ArchivedBoard]:
    """Archived boards, newest first.  Native units, never normalized."""
    where, params = [], []
    if provider_family:
        where.append("provider_family = ?")
        params.append(provider_family)
    if run_id:
        where.append("run_id = ?")
        params.append(run_id)
    clause = f" WHERE {' AND '.join(where)}" if where else ""

    conn = connect(path)
    try:
        rows = conn.execute(
            "SELECT provider, provider_family, endpoint, format_key, game_type, run_id, "
            "captured_at, source_as_of, rows_json, records_json, content_hash, "
            "provenance_json "
            "FROM archived_boards" + clause + " ORDER BY captured_at DESC, format_key ASC",
            params,
        ).fetchall()
    finally:
        conn.close()

    return [
        ArchivedBoard(
            provider=r[0],
            provider_family=r[1],
            endpoint=r[2],
            format_key=r[3],
            game_type=r[4],
            run_id=r[5],
            captured_at=r[6],
            source_as_of=r[7],
            rows=json.loads(r[8]),
            records=tuple(ArchivedRow.from_dict(d) for d in json.loads(r[9] or "[]")),
            content_hash=r[10],
            provenance=json.loads(r[11] or "{}"),
        )
        for r in rows
    ]


def archived_format_keys(
    *,
    provider: str,
    endpoint: str,
    captured_date: str,
    path: Path | None = None,
    timeout_s: float = DEFAULT_LOCK_TIMEOUT_SECONDS,
    include_sightings: bool = False,
) -> set[str]:
    """``format_key``s already archived for one provider/endpoint on one date.

    A cheap identity-column read (no ``rows_json``/``records_json`` is loaded),
    so a capture adapter can ask "is today's ladder already preserved?" without
    pulling the archive into memory.  An absent database answers the empty set
    without creating one.  ``include_sightings`` also counts variants a run
    observed unchanged that day (``board_sightings``): preserved, just not
    copied a second time.
    """
    target = path or DB_PATH
    if not target.exists():
        return set()
    conn = connect(target, timeout_s=timeout_s)
    params = (provider, endpoint, captured_date)
    try:
        rows = conn.execute(
            "SELECT DISTINCT format_key FROM archived_boards "
            "WHERE provider = ? AND endpoint = ? AND captured_date = ?",
            params,
        ).fetchall()
        if include_sightings:
            rows += conn.execute(
                "SELECT DISTINCT format_key FROM board_sightings "
                "WHERE provider = ? AND endpoint = ? AND captured_date = ?",
                params,
            ).fetchall()
    finally:
        conn.close()
    return {str(r[0]) for r in rows}


def read_sightings(
    *, provider: str | None = None, run_id: str | None = None, path: Path | None = None
) -> list[dict[str, Any]]:
    """``board_sightings`` rows, newest first: runs that saw a board unchanged."""
    target = path or DB_PATH
    if not target.exists():
        return []
    where, params = [], []
    if provider:
        where.append("provider = ?")
        params.append(provider)
    if run_id:
        where.append("run_id = ?")
        params.append(run_id)
    clause = f" WHERE {' AND '.join(where)}" if where else ""
    conn = connect(target)
    try:
        rows = conn.execute(
            "SELECT provider, endpoint, format_key, run_id, captured_at, content_hash, "
            "matched_run_id, matched_captured_at FROM board_sightings"
            + clause
            + " ORDER BY captured_at DESC, format_key ASC",
            params,
        ).fetchall()
    finally:
        conn.close()
    keys = (
        "provider",
        "endpoint",
        "formatKey",
        "runId",
        "capturedAt",
        "contentHash",
        "matchedRunId",
        "matchedCapturedAt",
    )
    return [dict(zip(keys, r)) for r in rows]


def coverage(*, path: Path | None = None) -> dict[str, Any]:
    """Shape of the archive.  Counts and stamps only."""
    target = path or DB_PATH
    if not target.exists():
        return {"present": False, "path": str(target)}
    conn = connect(target)
    try:
        boards = conn.execute("SELECT COUNT(*) FROM archived_boards").fetchone()[0]
        families = conn.execute(
            "SELECT COUNT(DISTINCT provider_family) FROM archived_boards"
        ).fetchone()[0]
        variants = conn.execute(
            "SELECT COUNT(DISTINCT format_key) FROM archived_boards"
        ).fetchone()[0]
        runs = conn.execute("SELECT COUNT(DISTINCT run_id) FROM archived_boards").fetchone()[0]
        newest = conn.execute("SELECT MAX(captured_at) FROM archived_boards").fetchone()[0]
    finally:
        conn.close()
    return {
        "present": True,
        "path": str(target),
        "boards": int(boards or 0),
        "providerFamilies": int(families or 0),
        "formatVariants": int(variants or 0),
        "runs": int(runs or 0),
        "newestCapturedAt": newest,
        # Stated in the health surface so nobody has to infer it.
        "productionEligible": sorted(PRODUCTION_ELIGIBLE),
    }
