"""The Market Trade Ledger's RAW acquisition archive — append-only.

``docs/MARKET_TRADE_LEDGER_ACTIONABILITY_SPEC.md`` §19.4: "Preserve every
source-native observation append-only in the raw acquisition archive with
its own source ID, timestamp, source payload hash and provenance.  Then map
those observations into canonical underlying-trade groups for analytics."

This module is the first half of that sentence and nothing else.  It stores
what a source said, verbatim, and the evidence of when we heard it.  It does
not resolve identity, group trades or value anything — that is
``src.trade.market_trade_normalize`` / ``market_trade_groups`` /
``market_trade_eval``, all of which READ this archive and none of which
write it.

APPEND-ONLY IS STRUCTURAL, NOT A CONVENTION
───────────────────────────────────────────
Every table carries ``BEFORE UPDATE`` / ``BEFORE DELETE`` triggers that
abort.  A collector bug, a hand-run ``sqlite3`` session or a future
"cleanup" cannot rewrite history without first dropping a trigger — which is
a deliberate act, not an accident.

Three promises, stated separately because they are different:

* **Identical re-observation is a no-op.**  The natural key is
  ``(source_family, source_native_id, payload_sha256)``; the rolling window
  serves the same row on many consecutive fetches and it is stored once.
  That it was seen again is recorded in the FETCH log (``known_count``), not
  by touching the observation.
* **A changed payload under the same native id is a REVISION, kept.**  It
  gets its own row; the earlier one is never overwritten.  Both are visible
  to the normalizer, which decides what a revision means (today: the latest
  revision is the current statement, and the revision count is reported).
* **A fetch is atomic.**  The fetch row, the identity snapshot and every new
  observation commit in ONE transaction, so a crash mid-fetch leaves the
  archive exactly as it was before the fetch began.

PRIVACY
───────
``data/market_trades/archive.sqlite``.  ``data/`` is gitignored repo-wide and
nothing force-adds this path (pinned by
``tests/trade/test_market_trade_privacy.py``).  The repo is public; a vendor's
trade feed, and the league ids inside it, must never ride a commit.  Mode
0600 where the platform supports it.
"""

from __future__ import annotations

import hashlib
import json
import os
import sqlite3
import threading
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_DIR = REPO_ROOT / "data" / "market_trades"
DB_FILENAME = "archive.sqlite"

SCHEMA_VERSION = 1
PRIVACY_CLASS = "private"

_SETUP_LOCK = threading.Lock()
_SETUP_DONE: dict[str, bool] = {}

_APPEND_ONLY_TABLES = ("fetches", "raw_observations", "identity_snapshots")

_SCHEMA = """
CREATE TABLE IF NOT EXISTS meta (
    key   TEXT PRIMARY KEY,
    value TEXT
);

-- One row per collection attempt that reached the network (or decided not
-- to).  The audit trail for "did we look, and what happened".
CREATE TABLE IF NOT EXISTS fetches (
    fetch_id          TEXT PRIMARY KEY,
    source_family     TEXT NOT NULL,
    url               TEXT,
    fetched_at        TEXT NOT NULL,
    http_status       INTEGER,
    outcome           TEXT NOT NULL,
    raw_sha256        TEXT,
    parser_version    TEXT,
    identity_sha256   TEXT,
    row_count         INTEGER,
    new_count         INTEGER,
    revised_count     INTEGER,
    known_count       INTEGER,
    -- 1 = this fetch shared NO native id with anything previously archived
    -- while the archive was non-empty: the rolling window turned over
    -- completely between runs and rows were probably missed.  NULL = not
    -- determinable (first fetch, or no rows).
    turnover_suspected INTEGER,
    detail_json       TEXT
);

-- Source-native observations, verbatim.  A revision is a new row.
CREATE TABLE IF NOT EXISTS raw_observations (
    source_family     TEXT NOT NULL,
    source_native_id  TEXT NOT NULL,
    payload_sha256    TEXT NOT NULL,
    payload_json      TEXT NOT NULL,
    -- The date the SOURCE says the trade happened, as the source wrote it.
    observed_date     TEXT,
    first_fetch_id    TEXT NOT NULL,
    first_fetched_at  TEXT NOT NULL,
    -- The identity snapshot in force when this payload was first fetched,
    -- so references can be re-resolved as they were, not as they are.
    identity_sha256   TEXT,
    parser_version    TEXT,
    PRIMARY KEY (source_family, source_native_id, payload_sha256)
);

-- Content-addressed vendor identity index (id -> name/position/kind).
CREATE TABLE IF NOT EXISTS identity_snapshots (
    identity_sha256   TEXT PRIMARY KEY,
    source_family     TEXT NOT NULL,
    captured_at       TEXT NOT NULL,
    entry_count       INTEGER NOT NULL,
    entries_json      TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_rawobs_native ON raw_observations(source_family, source_native_id);
CREATE INDEX IF NOT EXISTS idx_rawobs_date   ON raw_observations(source_family, observed_date);
CREATE INDEX IF NOT EXISTS idx_fetch_time    ON fetches(source_family, fetched_at);
"""


def _trigger_sql() -> str:
    parts = []
    for table in _APPEND_ONLY_TABLES:
        for verb in ("UPDATE", "DELETE"):
            parts.append(
                f"CREATE TRIGGER IF NOT EXISTS trg_{table}_no_{verb.lower()} "
                f"BEFORE {verb} ON {table} BEGIN "
                f"SELECT RAISE(ABORT, 'market_trade_archive is append-only: {verb} on {table}'); "
                "END;"
            )
    return "\n".join(parts)


def default_path() -> Path:
    """Resolved at CALL time so a test's monkeypatch of ``DEFAULT_DIR`` holds."""
    return Path(DEFAULT_DIR) / DB_FILENAME


def _ensure_schema(path: Path) -> None:
    key = str(path.resolve())
    with _SETUP_LOCK:
        if _SETUP_DONE.get(key):
            return
        path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(path)
        try:
            conn.executescript(_SCHEMA)
            conn.executescript(_trigger_sql())
            conn.execute(
                "INSERT OR IGNORE INTO meta(key, value) VALUES ('schema_version', ?)",
                (str(SCHEMA_VERSION),),
            )
            conn.commit()
        finally:
            conn.close()
        try:
            os.chmod(path, 0o600)
        except OSError:  # pragma: no cover - best effort on platforms without POSIX modes
            pass
        _SETUP_DONE[key] = True


def _reset_setup_cache_for_tests() -> None:
    with _SETUP_LOCK:
        _SETUP_DONE.clear()


def connect(path: Path | None = None) -> sqlite3.Connection:
    p = Path(path) if path is not None else default_path()
    _ensure_schema(p)
    conn = sqlite3.connect(p)
    conn.row_factory = sqlite3.Row
    return conn


def connect_readonly(path: Path | None = None) -> sqlite3.Connection | None:
    """Read-only handle, or ``None`` when no archive exists yet.

    Readers (the normalizer, the report) must never CREATE an archive as a
    side effect of asking whether one exists — an empty file would read as
    "we collected and found nothing", which is a different statement.
    """
    p = Path(path) if path is not None else default_path()
    if not p.exists():
        return None
    conn = sqlite3.connect(f"file:{p.as_posix()}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    return conn


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def canonical_json(obj: Any) -> str:
    return json.dumps(obj, sort_keys=True, ensure_ascii=False, separators=(",", ":"))


def payload_sha256(payload: Any) -> str:
    """Hash of the canonical JSON form — key order and whitespace never
    manufacture a revision."""
    return hashlib.sha256(canonical_json(payload).encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class RawObservation:
    source_native_id: str
    payload: Mapping[str, Any]
    observed_date: str | None = None


@dataclass
class FetchRecord:
    fetch_id: str
    source_family: str
    fetched_at: str
    outcome: str
    url: str | None = None
    http_status: int | None = None
    raw_sha256: str | None = None
    parser_version: str | None = None
    detail: dict[str, Any] = field(default_factory=dict)


@dataclass
class ArchiveWriteResult:
    fetch_id: str
    row_count: int = 0
    new_count: int = 0
    revised_count: int = 0
    known_count: int = 0
    turnover_suspected: bool | None = None
    identity_sha256: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "fetchId": self.fetch_id,
            "rowCount": self.row_count,
            "newCount": self.new_count,
            "revisedCount": self.revised_count,
            "knownCount": self.known_count,
            "turnoverSuspected": self.turnover_suspected,
            "identitySha256": self.identity_sha256,
        }


def record_fetch(
    fetch: FetchRecord,
    observations: Sequence[RawObservation] = (),
    *,
    identity_entries: Sequence[Mapping[str, Any]] | None = None,
    path: Path | None = None,
) -> ArchiveWriteResult:
    """Persist one fetch and its observations in a single transaction.

    Observations already archived with the identical payload are counted as
    ``known``; a new payload for a known native id is a ``revision``; a new
    native id is ``new``.  Duplicate native ids WITHIN one fetch are stored
    once per distinct payload.
    """
    result = ArchiveWriteResult(fetch_id=fetch.fetch_id, row_count=len(observations))
    conn = connect(path)
    try:
        with conn:  # one transaction: all of it or none of it
            identity_sha: str | None = None
            if identity_entries:
                entries = sorted(
                    (dict(e) for e in identity_entries),
                    key=lambda e: canonical_json(e),
                )
                identity_sha = payload_sha256(entries)
                conn.execute(
                    "INSERT OR IGNORE INTO identity_snapshots "
                    "(identity_sha256, source_family, captured_at, entry_count, entries_json) "
                    "VALUES (?, ?, ?, ?, ?)",
                    (
                        identity_sha,
                        fetch.source_family,
                        fetch.fetched_at,
                        len(entries),
                        canonical_json(entries),
                    ),
                )
            result.identity_sha256 = identity_sha

            archive_was_empty = (
                conn.execute(
                    "SELECT 1 FROM raw_observations WHERE source_family = ? LIMIT 1",
                    (fetch.source_family,),
                ).fetchone()
                is None
            )

            seen_in_fetch: set[tuple[str, str]] = set()
            for obs in observations:
                native = str(obs.source_native_id)
                sha = payload_sha256(obs.payload)
                if (native, sha) in seen_in_fetch:
                    continue
                seen_in_fetch.add((native, sha))
                existing = conn.execute(
                    "SELECT payload_sha256 FROM raw_observations "
                    "WHERE source_family = ? AND source_native_id = ?",
                    (fetch.source_family, native),
                ).fetchall()
                shas = {row[0] for row in existing}
                if sha in shas:
                    result.known_count += 1
                    continue
                conn.execute(
                    "INSERT INTO raw_observations "
                    "(source_family, source_native_id, payload_sha256, payload_json, "
                    " observed_date, first_fetch_id, first_fetched_at, identity_sha256, "
                    " parser_version) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (
                        fetch.source_family,
                        native,
                        sha,
                        canonical_json(obs.payload),
                        obs.observed_date,
                        fetch.fetch_id,
                        fetch.fetched_at,
                        identity_sha,
                        fetch.parser_version,
                    ),
                )
                if shas:
                    result.revised_count += 1
                else:
                    result.new_count += 1

            if observations and not archive_was_empty:
                result.turnover_suspected = result.known_count == 0 and result.revised_count == 0
            else:
                result.turnover_suspected = None

            conn.execute(
                "INSERT INTO fetches (fetch_id, source_family, url, fetched_at, http_status, "
                " outcome, raw_sha256, parser_version, identity_sha256, row_count, new_count, "
                " revised_count, known_count, turnover_suspected, detail_json) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    fetch.fetch_id,
                    fetch.source_family,
                    fetch.url,
                    fetch.fetched_at,
                    fetch.http_status,
                    fetch.outcome,
                    fetch.raw_sha256,
                    fetch.parser_version,
                    identity_sha,
                    len(observations),
                    result.new_count,
                    result.revised_count,
                    result.known_count,
                    None if result.turnover_suspected is None else int(result.turnover_suspected),
                    canonical_json(fetch.detail or {}),
                ),
            )
    finally:
        conn.close()
    return result


def read_observations(source_family: str, *, path: Path | None = None) -> list[dict[str, Any]]:
    """Every archived revision for one source family, oldest fetch first.

    Each entry carries ``revision`` (1-based, by first-fetch time) and
    ``revisionCount`` so a consumer can pick the latest statement without
    losing that earlier ones exist.  Empty list when no archive exists.
    """
    conn = connect_readonly(path)
    if conn is None:
        return []
    try:
        rows = conn.execute(
            "SELECT source_native_id, payload_sha256, payload_json, observed_date, "
            "first_fetch_id, first_fetched_at, identity_sha256, parser_version "
            "FROM raw_observations WHERE source_family = ? "
            "ORDER BY first_fetched_at ASC, source_native_id ASC, payload_sha256 ASC",
            (source_family,),
        ).fetchall()
    finally:
        conn.close()
    counts: dict[str, int] = {}
    for r in rows:
        counts[r["source_native_id"]] = counts.get(r["source_native_id"], 0) + 1
    seen: dict[str, int] = {}
    out: list[dict[str, Any]] = []
    for r in rows:
        native = r["source_native_id"]
        seen[native] = seen.get(native, 0) + 1
        out.append(
            {
                "sourceFamily": source_family,
                "sourceNativeId": native,
                "payloadSha256": r["payload_sha256"],
                "payload": json.loads(r["payload_json"]),
                "observedDate": r["observed_date"],
                "firstFetchId": r["first_fetch_id"],
                "firstFetchedAt": r["first_fetched_at"],
                "identitySha256": r["identity_sha256"],
                "parserVersion": r["parser_version"],
                "revision": seen[native],
                "revisionCount": counts[native],
            }
        )
    return out


def read_identity_snapshot(
    identity_sha256: str, *, path: Path | None = None
) -> list[dict[str, Any]] | None:
    conn = connect_readonly(path)
    if conn is None:
        return None
    try:
        row = conn.execute(
            "SELECT entries_json FROM identity_snapshots WHERE identity_sha256 = ?",
            (identity_sha256,),
        ).fetchone()
    finally:
        conn.close()
    if row is None:
        return None
    entries = json.loads(row["entries_json"])
    return entries if isinstance(entries, list) else None


def identity_snapshot_sha_at(
    source_family: str, at: str | None, *, path: Path | None = None
) -> str | None:
    """The newest identity snapshot captured AT OR BEFORE ``at`` — for a
    revision whose own fetch carried no index.  Never a later snapshot."""
    if not at:
        return None
    conn = connect_readonly(path)
    if conn is None:
        return None
    try:
        row = conn.execute(
            "SELECT identity_sha256 FROM identity_snapshots WHERE source_family = ? "
            "AND captured_at <= ? ORDER BY captured_at DESC LIMIT 1",
            (source_family, at),
        ).fetchone()
    finally:
        conn.close()
    return row[0] if row else None


def read_fetches(
    source_family: str, *, path: Path | None = None, limit: int | None = None
) -> list[dict[str, Any]]:
    conn = connect_readonly(path)
    if conn is None:
        return []
    try:
        sql = "SELECT * FROM fetches WHERE source_family = ? ORDER BY fetched_at DESC" + (
            " LIMIT ?" if limit else ""
        )
        params: tuple[Any, ...] = (source_family, int(limit)) if limit else (source_family,)
        rows = conn.execute(sql, params).fetchall()
    finally:
        conn.close()
    return [dict(r) for r in rows]


def coverage(source_family: str, *, path: Path | None = None) -> dict[str, Any]:
    """Counts and stamps only — never payload contents."""
    conn = connect_readonly(path)
    if conn is None:
        return {
            "sourceFamily": source_family,
            "archiveExists": False,
            "observations": 0,
            "distinctNativeIds": 0,
            "fetches": 0,
        }
    try:
        obs = conn.execute(
            "SELECT COUNT(*), COUNT(DISTINCT source_native_id), MIN(observed_date), "
            "MAX(observed_date) FROM raw_observations WHERE source_family = ?",
            (source_family,),
        ).fetchone()
        fetch_rows = conn.execute(
            "SELECT outcome, COUNT(*) FROM fetches WHERE source_family = ? GROUP BY outcome",
            (source_family,),
        ).fetchall()
        last = conn.execute(
            "SELECT fetched_at, outcome FROM fetches WHERE source_family = ? "
            "ORDER BY fetched_at DESC LIMIT 1",
            (source_family,),
        ).fetchone()
        turnover = conn.execute(
            "SELECT COUNT(*) FROM fetches WHERE source_family = ? AND turnover_suspected = 1",
            (source_family,),
        ).fetchone()
    finally:
        conn.close()
    return {
        "sourceFamily": source_family,
        "archiveExists": True,
        "observations": int(obs[0]),
        "distinctNativeIds": int(obs[1]),
        "oldestObservedDate": obs[2],
        "newestObservedDate": obs[3],
        "fetches": sum(int(r[1]) for r in fetch_rows),
        "fetchOutcomes": {str(r[0]): int(r[1]) for r in fetch_rows},
        "lastFetchAt": last[0] if last else None,
        "lastFetchOutcome": last[1] if last else None,
        "fetchesWithSuspectedTurnover": int(turnover[0]),
    }


def iter_native_ids(rows: Iterable[RawObservation]) -> list[str]:
    return [str(r.source_native_id) for r in rows]
