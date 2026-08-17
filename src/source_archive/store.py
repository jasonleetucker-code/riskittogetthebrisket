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

from src.utils.config_loader import repo_root

DB_PATH: Path = repo_root() / "data" / "source_archive" / "boards.sqlite"

SCHEMA_VERSION = 1

#: Format variants we ARCHIVE. Deliberately a different set from
#: :data:`PRODUCTION_ELIGIBLE` — see the package docstring. Nothing in
#: this module can move a key from one to the other; production
#: eligibility is membership of ``data_contract._RANKING_SOURCES``, which
#: lives in a module that does not import this one.
ARCHIVE_ELIGIBLE: frozenset[str] = frozenset(
    {
        # KTC's four TE-premium calibration states. All four already ship
        # in every scrape response; three are currently discarded.
        "ktc:sf_off",
        "ktc:sf_tep",
        "ktc:sf_tepp",
        "ktc:sf_teppp",
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
    content_hash    TEXT NOT NULL,
    first_seen_at   TEXT NOT NULL,

    PRIMARY KEY (provider, endpoint, format_key, run_id, captured_date)
);

CREATE INDEX IF NOT EXISTS idx_archive_family
    ON archived_boards(provider_family, captured_date);
CREATE INDEX IF NOT EXISTS idx_archive_run
    ON archived_boards(run_id);
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

    @property
    def captured_date(self) -> str:
        return (self.captured_at or _utc_now())[:10]

    def compute_hash(self) -> str:
        blob = json.dumps(
            {"rows": self.rows, "format_key": self.format_key, "game_type": self.game_type},
            sort_keys=True,
            separators=(",", ":"),
        )
        return hashlib.sha256(blob.encode("utf-8")).hexdigest()[:32]


class ArchiveRefused(ValueError):
    """A board that must not enter the archive (fail closed)."""


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
            conn.executescript(_SCHEMA)
            conn.execute(
                "INSERT OR REPLACE INTO meta(key, value) VALUES ('schema_version', ?)",
                (str(SCHEMA_VERSION),),
            )
            conn.commit()
        finally:
            conn.close()
        _SETUP_DONE[key] = True


def connect(path: Path | None = None) -> sqlite3.Connection:
    target = path or DB_PATH
    _ensure_schema(target)
    return sqlite3.connect(str(target), timeout=5.0)


def _reset_setup_cache_for_tests() -> None:
    with _SETUP_LOCK:
        _SETUP_DONE.clear()


def archive_board(board: ArchivedBoard, *, path: Path | None = None) -> dict[str, Any]:
    """Archive one native-format board.

    Refuses anything not proven ``DYNASTY`` — the same fail-closed rule
    the blend gate applies (``C1-SRC-02``). A board we cannot prove is
    dynasty does not become dynasty by being stored, and quarantining it
    "for diagnostics" inside the dynasty archive is exactly how it later
    gets used.
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

    now = _utc_now()
    captured_at = board.captured_at or now
    digest = board.compute_hash()

    conn = connect(path)
    try:
        existing = conn.execute(
            "SELECT content_hash FROM archived_boards WHERE provider = ? AND endpoint = ? "
            "AND format_key = ? AND run_id = ? AND captured_date = ?",
            (board.provider, board.endpoint, board.format_key, board.run_id, captured_at[:10]),
        ).fetchone()
        if existing is not None:
            return {
                "archived": 0,
                "unchanged": int(existing[0] == digest),
                "conflict": None if existing[0] == digest else digest,
            }
        conn.execute(
            "INSERT INTO archived_boards (provider, provider_family, endpoint, format_key, "
            "game_type, run_id, captured_date, captured_at, source_as_of, row_count, "
            "rows_json, content_hash, first_seen_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                board.provider,
                board.provider_family,
                board.endpoint,
                board.format_key,
                board.game_type,
                board.run_id,
                captured_at[:10],
                captured_at,
                board.source_as_of,
                len(board.rows),
                json.dumps(board.rows, sort_keys=True, separators=(",", ":")),
                digest,
                now,
            ),
        )
        conn.commit()
    finally:
        conn.close()
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
            "captured_at, source_as_of, rows_json, content_hash FROM archived_boards"
            + clause
            + " ORDER BY captured_at DESC, format_key ASC",
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
            content_hash=r[9],
        )
        for r in rows
    ]


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
