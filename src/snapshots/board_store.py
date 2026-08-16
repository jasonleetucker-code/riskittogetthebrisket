"""Immutable as-of records of what the CANONICAL board said.

WHY THIS EXISTS
---------------
The 2026-08-04 decision-intelligence audit's central finding is not any
one of its 531 defects.  It is the condition underneath them:

    "No output on this platform has been validated for accuracy."

Every tuned constant in the core blend was selected against a
*stability* metric — day-to-day board churn — and the repo's own alpha
report says that metric "rewards stability… the optimum drifts toward
using the anchor source alone… That's product-bad."  Accuracy could not
be the objective instead, because measuring accuracy needs to know what
the board said in the past, and **nothing recorded it**.  Every board
was computed, served, and discarded.

So this file is the prerequisite for the audit's Phase 8.3 — replacing
the stability objective with an accuracy one — and it is why the
remediation plan starts it on day one rather than sequencing it.  It
only records, so it blocks nothing, and every day it is not running is
a day of evidence that cannot be recovered later.

WHAT IT IS NOT
--------------
**No decision path may read this.**  It is evidence about the board,
not an input to it: a value that fed back into the board it records
would make the record a function of itself, and every measurement taken
from it circular — which is precisely the defect V-2 records for the
Hill-curve promotion gate, whose four "held-out" boards are all live
blend sources.  ``coverage()`` exists for operators and tests.  That is
the whole read surface, deliberately.

RELATIONSHIP TO ``src/consensus_edge/snapshot.py``
--------------------------------------------------
That module is an excellent as-of store and this one deliberately does
not extend it.  Two reasons, both structural:

* **Different subject.**  It records the Consensus Edge feature's own
  scores and its retail ``market_value`` anchor.  It does not carry
  ``rankDerivedValue``, ``canonicalConsensusRank``, ``canonicalTierId``
  or ``confidenceBucket`` — the canonical board quantities that every
  remediation batch moves and that an accuracy objective must score.
* **Different lifecycle.**  ``consensus_edge`` is feature-flagged and
  its flag defaults to **False**, so its snapshot job records nothing
  in production today.  Hanging the canonical board's permanent
  historical record off a dormant, retirable feature would reproduce
  the B-1 pattern exactly — nine timer pairs shipped, two installed,
  and a deploy that reported success the whole time.  This store is
  unconditional and has no flag.

What IS taken from it is its design, which was already corrected once
under audit:

* versions belong in the KEY, not in metadata — two boards for one date
  under different pipeline versions are two different claims;
* the write path names the columns it owns and no others, so a re-run
  can never clear an outcome label (``INSERT OR REPLACE`` is
  DELETE-then-INSERT in SQLite and silently nulls every unlisted
  column);
* outcome columns are nullable and filled later, because the board is
  knowable today and whether it was right is not.

The outcome columns are present and NOT filled by anything yet.  That
is intentional: labelling is a measurement, it belongs to Phase 8.3,
and shipping an unlabelled record now is what makes that phase possible
at all.

Idempotent per ``(as_of, player_key, contract_version)``: re-running on
a date replaces that date's rows for the same pipeline version and
leaves every other row alone.
"""

from __future__ import annotations

import json
import sqlite3
import threading
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

# Moved to the temporal-ledger owner (C1-U4) and re-imported so this
# module's callers keep their name.  One implementation, and the
# labeller lives where provenance semantics are owned — see
# ``src/history/provenance.py``.
from src.history.provenance import pipeline_version  # noqa: F401
from src.utils.name_clean import canonical_player_key

DB_PATH: Path = Path(__file__).resolve().parents[2] / "data" / "board_history.sqlite"

SCHEMA_VERSION = 1

_SETUP_LOCK = threading.Lock()
_SETUP_DONE: dict[str, bool] = {}

_SCHEMA = """
CREATE TABLE IF NOT EXISTS meta (
    key   TEXT PRIMARY KEY,
    value TEXT
);

CREATE TABLE IF NOT EXISTS board_history (
    as_of              TEXT NOT NULL,
    player_key         TEXT NOT NULL,
    -- The pipeline version that produced the row.  In the key because
    -- two boards for one date under different versions are two
    -- different claims, and keeping only the latest would erase the
    -- comparison a revaluation decision depends on -- which is the
    -- whole point of recording the C6 board move.
    contract_version   TEXT NOT NULL,

    player_id          TEXT,
    display_name       TEXT,
    position           TEXT,
    asset_class        TEXT,

    -- The canonical board.  These are the quantities the remediation
    -- batches move and the ones an accuracy objective scores.
    rank_derived_value       REAL,
    canonical_consensus_rank INTEGER,
    canonical_tier_id        INTEGER,
    confidence_bucket        TEXT,
    source_count             INTEGER,
    is_single_source         INTEGER,
    market_gap_direction     TEXT,
    market_gap_magnitude     REAL,

    -- The retail anchors, stored beside our board rather than derived
    -- from it.  Forward "did the market move toward us" is the honest
    -- baseline the audit names (current market value, no-change,
    -- equal-weight blend, position average), and it cannot be
    -- reconstructed later from a row that only kept our own number.
    ktc_sf_tep         REAL,
    idp_trade_calc     REAL,

    -- Provenance.  hours_stale and the scrape stamp are what let a
    -- future study exclude days when an input was frozen -- finding
    -- Z-2 is that a preserved CSV mints a fresh success stamp, so
    -- "the board was current" is not safe to assume retrospectively.
    scraped_at         TEXT,
    hours_stale        REAL,
    written_at         TEXT NOT NULL,

    -- Filled in later, by the accuracy work in Phase 8.3.  NULL until
    -- the horizon has actually elapsed.  The write path never touches
    -- these; see the module docstring.
    fwd_value_7d       REAL,
    fwd_value_30d      REAL,
    fwd_market_7d      REAL,
    fwd_market_30d     REAL,

    PRIMARY KEY (as_of, player_key, contract_version)
);

CREATE INDEX IF NOT EXISTS idx_bh_player ON board_history(player_key, as_of);
CREATE INDEX IF NOT EXISTS idx_bh_asof   ON board_history(as_of);
"""


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


def connect(path: Path | None = None) -> sqlite3.Connection:
    target = path or DB_PATH
    _ensure_schema(target)
    return sqlite3.connect(str(target), timeout=5.0)


_KEY_COLUMNS = ("as_of", "player_key", "contract_version")

# Everything the SNAPSHOT path owns.  The ``fwd_*`` columns are
# deliberately absent: they belong to the labelling pass and a write
# here must never clear them.
_OWNED_COLUMNS = (
    "player_id",
    "display_name",
    "position",
    "asset_class",
    "rank_derived_value",
    "canonical_consensus_rank",
    "canonical_tier_id",
    "confidence_bucket",
    "source_count",
    "is_single_source",
    "market_gap_direction",
    "market_gap_magnitude",
    "ktc_sf_tep",
    "idp_trade_calc",
    "scraped_at",
    "hours_stale",
    "written_at",
)

_ALL_COLUMNS = _KEY_COLUMNS + _OWNED_COLUMNS

_INSERT = (
    f"INSERT INTO board_history ({', '.join(_ALL_COLUMNS)}) "
    f"VALUES ({', '.join('?' for _ in _ALL_COLUMNS)}) "
    f"ON CONFLICT({', '.join(_KEY_COLUMNS)}) DO UPDATE SET "
    + ", ".join(f"{c}=excluded.{c}" for c in _OWNED_COLUMNS)
)


def _num(value: Any) -> float | None:
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    return None


def _int(value: Any) -> int | None:
    n = _num(value)
    return int(n) if n is not None else None


def _retail(row: dict[str, Any], key: str) -> float | None:
    """Read a per-source retail value off whichever block carries it.

    The contract exposes raw source values under more than one name
    depending on the row's provenance, and a store that reads only one
    of them records ``None`` for a value that is present — a silent
    hole in exactly the baseline series the accuracy work needs.

    ONLY SAFE FOR VALUE-SIGNAL SOURCES.  ``canonicalSiteValues`` mixes
    genuine vendor values with the SYNTHETIC encodings the pipeline
    manufactures for rank-signal sources, and recording one of those as
    a retail price would put a number the market never published into
    the baseline every future measurement is scored against.  The two
    keys this is called with — ``ktcSfTep`` and ``idpTradeCalc`` — are
    the value-direct sources (``_VALUE_BASED_SOURCES``), which is the
    same restriction BDVM's market layer states for the same block.
    Do not widen this to a rank-signal source without converting it
    first.
    """
    for block_name in ("rawSourceValues", "canonicalSiteValues", "sourceValues"):
        block = row.get(block_name)
        if isinstance(block, dict) and key in block:
            got = _num(block.get(key))
            if got is not None:
                return got
    return _num(row.get(key))


def _row_values(
    row: dict[str, Any],
    as_of: str,
    contract_version: str,
    scraped_at: str | None,
    written_at: str,
) -> tuple | None:
    name = str(row.get("displayName") or row.get("canonicalName") or "").strip()
    if not name:
        return None
    position = row.get("position")
    player_key = canonical_player_key(name, position if isinstance(position, str) else None)
    if not player_key:
        return None

    single = row.get("isSingleSource")
    return (
        as_of,
        player_key,
        contract_version,
        str(row.get("playerId") or "") or None,
        name,
        str(position or "") or None,
        str(row.get("assetClass") or "") or None,
        _num(row.get("rankDerivedValue")),
        _int(row.get("canonicalConsensusRank")),
        _int(row.get("canonicalTierId")),
        str(row.get("confidenceBucket") or "") or None,
        _int(row.get("sourceCount")),
        (1 if single else 0) if single is not None else None,
        str(row.get("marketGapDirection") or "") or None,
        _num(row.get("marketGapMagnitude")),
        _retail(row, "ktcSfTep"),
        _retail(row, "idpTradeCalc"),
        scraped_at,
        _num((row.get("dataFreshness") or {}).get("hoursStale"))
        if isinstance(row.get("dataFreshness"), dict)
        else None,
        written_at,
    )


def write_board(
    contract: dict[str, Any],
    *,
    as_of: str | date | None = None,
    path: Path | None = None,
) -> dict[str, Any]:
    """Persist one day's canonical board.  Idempotent per (date, version).

    Returns a summary rather than raising on an empty board: this runs
    on a timer beside the refresh, and a recording job that takes the
    process down is worse than one that reports it did nothing.
    """
    rows = (contract or {}).get("playersArray")
    if not isinstance(rows, list) or not rows:
        return {"written": 0, "skipped": True, "reason": "no playersArray"}

    if as_of is None:
        as_of_str = datetime.now(timezone.utc).date().isoformat()
    elif isinstance(as_of, date):
        as_of_str = as_of.isoformat()
    else:
        as_of_str = str(as_of)

    contract_version = pipeline_version(contract)
    scraped_at = str(contract.get("scrapeTimestamp") or contract.get("date") or "") or None
    written_at = datetime.now(timezone.utc).isoformat()

    payloads = []
    skipped_unkeyed = 0
    for row in rows:
        if not isinstance(row, dict):
            continue
        values = _row_values(row, as_of_str, contract_version, scraped_at, written_at)
        if values is None:
            skipped_unkeyed += 1
            continue
        payloads.append(values)

    if not payloads:
        return {"written": 0, "skipped": True, "reason": "no keyable rows"}

    conn = connect(path)
    try:
        conn.executemany(_INSERT, payloads)
        conn.commit()
    finally:
        conn.close()

    return {
        "written": len(payloads),
        "skipped": False,
        "asOf": as_of_str,
        "contractVersion": contract_version,
        # Surfaced rather than swallowed: a row the store cannot key is a
        # row missing from every future measurement, and the count is the
        # only place that would ever show up.
        "unkeyableRows": skipped_unkeyed,
    }


def coverage(path: Path | None = None) -> dict[str, Any]:
    """Operator/test diagnostic: how much history exists, and how dense.

    Not a decision input.  See the module docstring.
    """
    target = path or DB_PATH
    if not target.exists():
        return {"dates": 0, "rows": 0, "firstDate": None, "lastDate": None, "versions": []}
    conn = connect(target)
    try:
        rows, dates, first, last = conn.execute(
            "SELECT COUNT(*), COUNT(DISTINCT as_of), MIN(as_of), MAX(as_of) FROM board_history"
        ).fetchone()
        versions = [
            r[0]
            for r in conn.execute(
                "SELECT DISTINCT contract_version FROM board_history ORDER BY contract_version"
            ).fetchall()
        ]
        priced = conn.execute(
            "SELECT COUNT(*) FROM board_history WHERE rank_derived_value IS NOT NULL"
        ).fetchone()[0]
    finally:
        conn.close()
    return {
        "dates": dates or 0,
        "rows": rows or 0,
        "priced": priced or 0,
        "firstDate": first,
        "lastDate": last,
        "versions": versions,
    }


def summary_json(path: Path | None = None) -> str:
    return json.dumps(coverage(path), indent=1, sort_keys=True)
