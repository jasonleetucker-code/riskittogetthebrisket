"""The immutable temporal ledger — append-only observation storage.

``data/temporal_ledger.sqlite`` holds one row per **observation**: a
quantity (canonical board value/rank, a provider's raw value, or the
scraper's own blend) claimed for one asset on one UTC date by one
producer.  The write path is INSERT-only:

* an identical re-ingest (same identity, same content) is a silent
  no-op — every ingest is idempotent;
* a conflicting re-ingest (same identity, different content) NEVER
  replaces the stored row.  It is surfaced in the write summary as a
  ``contentConflicts`` entry, because a historical record that can be
  silently rewritten is not a record;
* corrections, should one ever be needed, are explicit rows in the
  ``corrections`` table pointing at the superseded observation — the
  original is retained, readable, and marked, never mutated.

Identity of an observation is
``(asset_key, lane, source_key, observed_date, observed_at, origin)``.
``origin`` is part of identity deliberately: the live recorder, the
archive backfill and the legacy-store migrations can each honestly
observe the same fact, and keeping their records distinct is what
lets a query state which producer its answer came from.  Queries
resolve cross-origin duplicates with the deterministic preference
order in :data:`ORIGIN_PRIORITY`.

Lanes — an observation names WHICH quantity it is, and the as-of
query layer never mixes them:

* ``canonical_board`` — what the canonical pipeline served
  (``rankDerivedValue`` / ``canonicalConsensusRank`` / tier /
  confidence).  The only lane a canonical-value query reads.
* ``source_value`` — a value-direct provider's raw number (``ktc``,
  ``ktcSfTep``, ``idpTradeCalc``).  Never a rank-signal source's
  synthetic encoding — same restriction ``board_store._retail``
  documents, for the same reason.
* ``scraper_blend`` — the scraper's own composite
  (``_composite`` / ``_finalAdjusted``).  A different, named quantity
  from canonical value; retained as evidence, never served as
  canonical history.

Timestamps: ``observed_date`` is the producer's own UTC date claim for
the board day and is the primary temporal key (every feed is
day-granular).  ``observed_at`` is the scrape instant where known;
``observed_at_zone`` records whether that instant was zone-qualified
(``utc``) or naive (``naive`` — the scraper's export stamps carry no
zone; the recording host has run UTC for the whole covered window, and
the assumption is recorded rather than silently normalized).
``recorded_at`` is ledger-write provenance and is never a query key.

The permanent coverage boundary: ``exports/archive/`` begins
2026-07-14 and nothing earlier survives.  :data:`HISTORY_FLOOR` is
enforced at BOTH ends — the write path refuses observations dated
before it (a pre-boundary row could only be fabricated), and the
query layer answers pre-boundary requests with an explicit
``before_history_boundary`` missing reason.
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
import threading
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, Iterable

from src.history.keys import is_valid_asset_key

DB_PATH: Path = Path(__file__).resolve().parents[2] / "data" / "temporal_ledger.sqlite"

SCHEMA_VERSION = 1

# The permanent history boundary.  Retained evidence starts here; the
# gap before it is PERMANENT and is represented as missing, never
# interpolated, reconstructed from later data, or backdated.  Changing
# this constant is an owner decision requiring newly proven
# contemporaneous evidence, not a code cleanup.
HISTORY_FLOOR: str = "2026-07-14"

LANE_CANONICAL = "canonical_board"
LANE_SOURCE = "source_value"
LANE_SCRAPER = "scraper_blend"
VALID_LANES = frozenset({LANE_CANONICAL, LANE_SOURCE, LANE_SCRAPER})

# Deterministic cross-origin preference for queries: when the same
# fact was recorded by more than one producer, the earlier entry in
# this list wins.  Unlisted origins rank after listed ones,
# alphabetically, so the order is total and replay-stable.
ORIGIN_PRIORITY: tuple[str, ...] = (
    "live:server",
    "migration:board_history",
    "migration:rank_history",
    "backfill:archive",
)

_SETUP_LOCK = threading.Lock()
_SETUP_DONE: dict[str, bool] = {}

_SCHEMA = """
CREATE TABLE IF NOT EXISTS meta (
    key   TEXT PRIMARY KEY,
    value TEXT
);

CREATE TABLE IF NOT EXISTS observations (
    id               INTEGER PRIMARY KEY,
    asset_key        TEXT NOT NULL,
    asset_class      TEXT NOT NULL,
    lane             TEXT NOT NULL,
    source_key       TEXT NOT NULL DEFAULT '',
    observed_date    TEXT NOT NULL,
    observed_at      TEXT,
    observed_at_zone TEXT,
    value            REAL,
    rank             INTEGER,
    tier             INTEGER,
    confidence       TEXT,
    display_name     TEXT,
    position         TEXT,
    player_id        TEXT,
    scope            TEXT,
    pipeline_version TEXT,
    origin           TEXT NOT NULL,
    recorded_at      TEXT NOT NULL,
    content_hash     TEXT NOT NULL
);

-- Identity uniqueness lives in an EXPRESSION index rather than an
-- inline UNIQUE constraint: ``observed_at`` is nullable (a migrated
-- rank-history row has no instant), and SQLite's UNIQUE treats NULLs
-- as pairwise distinct — an inline constraint would silently admit
-- duplicate identities on every re-ingest of instant-less rows.
-- COALESCE to '' makes "no instant" one identity, which is what makes
-- every ingest idempotent (pinned by the backfill/migration tests).
CREATE UNIQUE INDEX IF NOT EXISTS uq_obs_identity
    ON observations(asset_key, lane, source_key, observed_date,
                    COALESCE(observed_at, ''), origin);

CREATE INDEX IF NOT EXISTS idx_obs_asof
    ON observations(asset_key, lane, source_key, observed_date);
CREATE INDEX IF NOT EXISTS idx_obs_date
    ON observations(observed_date, lane);

CREATE TABLE IF NOT EXISTS corrections (
    superseded_id  INTEGER NOT NULL REFERENCES observations(id),
    superseding_id INTEGER NOT NULL REFERENCES observations(id),
    reason         TEXT NOT NULL,
    recorded_at    TEXT NOT NULL,
    PRIMARY KEY (superseded_id)
);
"""


def _ensure_schema(path: Path) -> None:
    key = str(path)
    if _SETUP_DONE.get(key):
        return
    with _SETUP_LOCK:
        if _SETUP_DONE.get(key):
            return
        path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(str(path), timeout=10.0)
        try:
            conn.execute("PRAGMA journal_mode=WAL;")
            conn.execute("PRAGMA synchronous=NORMAL;")
            conn.executescript(_SCHEMA)
            conn.execute(
                "INSERT OR REPLACE INTO meta(key, value) VALUES ('schema_version', ?)",
                (str(SCHEMA_VERSION),),
            )
            conn.execute(
                "INSERT OR IGNORE INTO meta(key, value) VALUES ('history_floor', ?)",
                (HISTORY_FLOOR,),
            )
            conn.commit()
        finally:
            conn.close()
        _SETUP_DONE[key] = True


def connect(path: Path | None = None) -> sqlite3.Connection:
    target = path or DB_PATH
    _ensure_schema(target)
    conn = sqlite3.connect(str(target), timeout=10.0)
    conn.row_factory = sqlite3.Row
    return conn


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


# ── Observation construction ────────────────────────────────────────────

_CONTENT_FIELDS = (
    "value",
    "rank",
    "tier",
    "confidence",
    "display_name",
    "position",
    "player_id",
    "scope",
    "pipeline_version",
)

_IDENTITY_FIELDS = (
    "asset_key",
    "lane",
    "source_key",
    "observed_date",
    "observed_at",
    "origin",
)

_ALL_FIELDS = _IDENTITY_FIELDS + ("asset_class", "observed_at_zone") + _CONTENT_FIELDS


def content_hash(obs: dict[str, Any]) -> str:
    """Hash of the fields that constitute the observation's CONTENT.

    Two ingests of the same identity with equal content hashes are one
    fact (idempotent rerun); unequal hashes are a conflict the write
    path must surface rather than resolve silently.
    """
    payload = {k: obs.get(k) for k in _CONTENT_FIELDS}
    blob = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()[:16]


class ObservationError(ValueError):
    """A record that must not enter the ledger (fail closed)."""


def has_time_component(stamp: Any) -> bool:
    """True only for a parseable ISO stamp that actually CARRIES a time.

    Load-bearing for the never-future guarantee: a date-only string
    ("2026-08-16") parses as midnight and lexicographically precedes
    every instant of its own day, so treating it as a proven instant
    would promote an UNKNOWN scrape time to "provably at-or-before any
    moment today" — the exact leak the final review reproduced
    (``board_store`` can stamp ``scraped_at`` with the bare contract
    date when ``scrapeTimestamp`` is absent).  An instant is proven
    only when the text contains an explicit time separator and parses.
    """
    s = str(stamp or "").strip()
    if len(s) <= 10 or (s[10] not in ("T", " ")):
        return False
    try:
        datetime.fromisoformat(s)
    except ValueError:
        return False
    return True


def _normalize_observation(obs: dict[str, Any]) -> dict[str, Any]:
    """Write-path normalization — the store owns these rules so every
    writer (live, backfill, migrations, future ones) inherits them:

    * ``source_key`` ``None`` → ``''`` (the column is NOT NULL; without
      this a None would be dropped by OR IGNORE and then misreported by
      the conflict probe);
    * ``observed_at`` without a real time component → ``None``
      (an unparseable or date-only stamp IS no instant; storing it
      would poison the instant-strict query per
      :func:`has_time_component`), and ``''`` → ``None`` so the
      identity index's COALESCE cannot make an empty string and a NULL
      two spellings of one identity.
    """
    out = dict(obs)
    if out.get("source_key") is None:
        out["source_key"] = ""
    oa = out.get("observed_at")
    if oa is not None and not has_time_component(oa):
        out["observed_at"] = None
        out["observed_at_zone"] = None
    return out


def validate_observation(obs: dict[str, Any]) -> None:
    key = obs.get("asset_key")
    if not is_valid_asset_key(str(key or "")):
        raise ObservationError(f"invalid asset_key: {key!r}")
    lane = obs.get("lane")
    if lane not in VALID_LANES:
        raise ObservationError(f"invalid lane: {lane!r}")
    od = str(obs.get("observed_date") or "")
    try:
        parsed = datetime.strptime(od, "%Y-%m-%d")
    except ValueError as exc:
        raise ObservationError(f"invalid observed_date: {od!r}") from exc
    # strptime accepts non-zero-padded forms ("2026-7-15") that would
    # corrupt every lexicographic date comparison in the query layer —
    # require the canonical ISO spelling exactly.
    if parsed.date().isoformat() != od:
        raise ObservationError(f"observed_date not canonical ISO (YYYY-MM-DD): {od!r}")
    if od < HISTORY_FLOOR:
        # A pre-boundary observation cannot exist: nothing earlier than
        # the archive floor survives, so a row claiming to is
        # fabricated by construction.
        raise ObservationError(
            f"observed_date {od} precedes the permanent history floor {HISTORY_FLOOR}"
        )
    if not obs.get("origin"):
        raise ObservationError("origin is required")
    if obs.get("value") is None and obs.get("rank") is None:
        raise ObservationError("observation carries neither value nor rank")


_INSERT = (
    "INSERT OR IGNORE INTO observations ("
    + ", ".join(_ALL_FIELDS)
    + ", recorded_at, content_hash) VALUES ("
    + ", ".join("?" for _ in _ALL_FIELDS)
    + ", ?, ?)"
)


def write_observations(
    observations: Iterable[dict[str, Any]],
    *,
    path: Path | None = None,
    recorded_at: str | None = None,
) -> dict[str, Any]:
    """Append observations.  Idempotent; conflicts surfaced, never applied.

    Returns ``{written, duplicates, contentConflicts, rejected}`` —
    ``rejected`` carries ``(reason, asset_key/date)`` pairs for rows
    that failed validation (the caller decides whether that is fatal;
    backfill counts them, the live recorder logs them).
    """
    stamp = recorded_at or utc_now_iso()
    written = 0
    duplicates = 0
    conflicts: list[dict[str, Any]] = []
    rejected: list[dict[str, Any]] = []

    conn = connect(path)
    try:
        for raw_obs in observations:
            obs = _normalize_observation(raw_obs)
            try:
                validate_observation(obs)
            except ObservationError as exc:
                rejected.append(
                    {
                        "reason": str(exc),
                        "assetKey": obs.get("asset_key"),
                        "observedDate": obs.get("observed_date"),
                        "origin": obs.get("origin"),
                    }
                )
                continue
            ch = content_hash(obs)
            row = [obs.get(f) for f in _ALL_FIELDS] + [stamp, ch]
            cur = conn.execute(_INSERT, row)
            if cur.rowcount == 1:
                written += 1
                continue
            # Identity already present: idempotent rerun or conflict?
            existing = conn.execute(
                "SELECT content_hash FROM observations WHERE "
                "asset_key=? AND lane=? AND source_key=? AND observed_date=? "
                "AND (observed_at IS ? OR observed_at = ?) AND origin=?",
                (
                    obs.get("asset_key"),
                    obs.get("lane"),
                    obs.get("source_key") or "",
                    obs.get("observed_date"),
                    obs.get("observed_at"),
                    obs.get("observed_at"),
                    obs.get("origin"),
                ),
            ).fetchone()
            if existing is not None and existing["content_hash"] == ch:
                duplicates += 1
            else:
                conflicts.append(
                    {
                        "assetKey": obs.get("asset_key"),
                        "lane": obs.get("lane"),
                        "observedDate": obs.get("observed_date"),
                        "origin": obs.get("origin"),
                        "storedHash": existing["content_hash"] if existing else None,
                        "incomingHash": ch,
                    }
                )
        conn.commit()
    finally:
        conn.close()

    return {
        "written": written,
        "duplicates": duplicates,
        "contentConflicts": conflicts,
        "rejected": rejected,
    }


def record_correction(
    superseded_id: int,
    superseding_id: int,
    reason: str,
    *,
    path: Path | None = None,
) -> None:
    """Explicitly supersede one observation with another.

    The superseded row is retained and readable; queries prefer the
    superseding row.  ``reason`` is mandatory — an unexplained
    correction is indistinguishable from tampering.
    """
    if not reason or not reason.strip():
        raise ObservationError("a correction requires a reason")
    if superseded_id == superseding_id:
        raise ObservationError("an observation cannot supersede itself")
    conn = connect(path)
    try:
        for oid in (superseded_id, superseding_id):
            row = conn.execute("SELECT id FROM observations WHERE id=?", (oid,)).fetchone()
            if row is None:
                raise ObservationError(f"correction references missing observation id {oid}")
        # A superseding row must itself be live evidence: allowing a
        # superseded row to supersede would let a two-row cycle remove
        # both from every query surface — evidence deletion by another
        # name.
        if conn.execute(
            "SELECT 1 FROM corrections WHERE superseded_id=?", (superseding_id,)
        ).fetchone():
            raise ObservationError(
                f"observation {superseding_id} is itself superseded and cannot supersede"
            )
        conn.execute(
            "INSERT INTO corrections(superseded_id, superseding_id, reason, recorded_at) "
            "VALUES (?, ?, ?, ?)",
            (superseded_id, superseding_id, reason.strip(), utc_now_iso()),
        )
        conn.commit()
    finally:
        conn.close()


def origin_rank(origin: str) -> tuple[int, str]:
    """Total, replay-stable ordering key for cross-origin selection."""
    base = origin.split(":zip=")[0]
    try:
        return (ORIGIN_PRIORITY.index(base), origin)
    except ValueError:
        return (len(ORIGIN_PRIORITY), origin)


def coverage(path: Path | None = None) -> dict[str, Any]:
    """Operator/test diagnostic: what the ledger actually holds."""
    target = path or DB_PATH
    if not target.exists():
        return {
            "exists": False,
            "rows": 0,
            "historyFloor": HISTORY_FLOOR,
            "reason": "no temporal ledger on disk; nothing has been recorded",
        }
    conn = connect(target)
    try:
        rows, dates, first, last = conn.execute(
            "SELECT COUNT(*), COUNT(DISTINCT observed_date), "
            "MIN(observed_date), MAX(observed_date) FROM observations"
        ).fetchone()
        by_lane = {
            r["lane"]: r["n"]
            for r in conn.execute(
                "SELECT lane, COUNT(*) AS n FROM observations GROUP BY lane"
            ).fetchall()
        }
        by_class = {
            r["asset_class"]: r["n"]
            for r in conn.execute(
                "SELECT asset_class, COUNT(*) AS n FROM observations GROUP BY asset_class"
            ).fetchall()
        }
        origins = {
            r["origin"]: r["n"]
            for r in conn.execute(
                "SELECT origin, COUNT(*) AS n FROM observations GROUP BY origin"
            ).fetchall()
        }
        assets = conn.execute("SELECT COUNT(DISTINCT asset_key) FROM observations").fetchone()[0]
        corrections_n = conn.execute("SELECT COUNT(*) FROM corrections").fetchone()[0]
    finally:
        conn.close()
    return {
        "exists": True,
        "rows": rows or 0,
        "dates": dates or 0,
        "firstDate": first,
        "lastDate": last,
        "assets": assets or 0,
        "byLane": by_lane,
        "byAssetClass": by_class,
        "byOrigin": origins,
        "corrections": corrections_n,
        "historyFloor": HISTORY_FLOOR,
        "schemaVersion": SCHEMA_VERSION,
    }


def _reset_setup_cache_for_tests() -> None:
    """Test seam: forget which paths have had schema setup."""
    with _SETUP_LOCK:
        _SETUP_DONE.clear()


def as_of_date(value: date | datetime | str) -> str:
    """Normalize a caller-supplied date to the ledger's UTC date string.

    A string spelling of an instant answers exactly what the equivalent
    ``datetime`` object answers — the string branch DELEGATES rather than
    reimplementing, so the two cannot drift.

    F-5: this used to be ``strptime(s, "%Y-%m-%d")`` and nothing else, so
    an ISO-8601 *datetime* string escaped as a raw
    ``ValueError: unconverted data remains: T23:00:00``.  That is not this
    module's error type — a caller cannot catch it with
    ``except ObservationError`` — and it said nothing about the
    UTC-awareness rule that actually governs instants here.
    """
    if isinstance(value, datetime):
        if value.tzinfo is None:
            raise ObservationError(
                "naive datetime passed to the temporal ledger; as-of instants must be UTC-aware"
            )
        return value.astimezone(timezone.utc).date().isoformat()
    if isinstance(value, date):
        return value.isoformat()

    text = str(value).strip()
    try:
        return date.fromisoformat(text).isoformat()
    except ValueError:
        pass
    try:
        # ``Z`` is valid ISO-8601 but predates fromisoformat's support on
        # some versions; normalise it rather than depend on the runtime.
        parsed = datetime.fromisoformat(text[:-1] + "+00:00" if text.endswith("Z") else text)
    except ValueError:
        raise ObservationError(
            f"unparseable as-of date {value!r}; expected YYYY-MM-DD or a UTC-aware ISO-8601 instant"
        ) from None
    # Delegate, so a datetime STRING and a datetime OBJECT can never
    # disagree — including on the naive-instant refusal.
    return as_of_date(parsed)
