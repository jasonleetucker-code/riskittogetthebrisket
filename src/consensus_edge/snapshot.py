"""Immutable as-of records of what the board said, and what happened.

An audit found that the previous implementation had **no persistence at
all** — no table, no writer, no INSERT anywhere in the package. Every
board was computed, served, and discarded. That makes three things
impossible:

* answering "what did we say about this player on that date"
* measuring whether a call was right, because the call is gone
* reproducing a past result, because nothing recorded the model version,
  parameter set, or input timestamps that produced it

``panel.py`` reconstructs history by replaying git, which is a genuinely
good capability and a *different* one: it replays today's model over past
inputs. It cannot tell you what the model actually said at the time,
because the model has changed since. Both are needed.

Design notes worth keeping:

**Idempotent per (asOf, playerKey), and non-destructive.** A re-run on
the same date replaces that date's rows for the same model+params, and
touches nothing else. Historical rows written by an older model version
are never rewritten — they are the record of what that model said, and
overwriting them would destroy the only evidence of it.

**Versions are part of the key, not metadata.** Two boards for the same
date under different parameter sets are two different claims and both
are worth keeping. Storing only the latest would silently erase the
comparison a promotion decision depends on.

**Outcomes are labelled later, in place.** The score is knowable today;
whether it was right is not. ``label_outcomes`` fills the forward-return
columns once enough time has passed, which is why they are nullable and
why the write path never touches them.
"""

from __future__ import annotations

import json
import sqlite3
import threading
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, Iterable

DB_PATH: Path = Path(__file__).resolve().parents[2] / "data" / "consensus_edge.sqlite"

SCHEMA_VERSION = 1

_SETUP_LOCK = threading.Lock()
_SETUP_DONE: dict[str, bool] = {}

_SCHEMA = """
CREATE TABLE IF NOT EXISTS board_snapshots (
    as_of              TEXT NOT NULL,
    player_key         TEXT NOT NULL,
    model_version      TEXT NOT NULL,
    param_set_id       TEXT NOT NULL,

    display_name       TEXT,
    position           TEXT,
    asset_class        TEXT,

    score              REAL,
    label              TEXT,
    label_reason       TEXT,
    qualified          INTEGER,
    confidence         REAL,

    component_mispricing  REAL,
    component_sharp_flow  REAL,
    component_opportunity REAL,
    components_absent     TEXT,

    fair_value         REAL,
    market_value       REAL,
    anchor_key         TEXT,
    pct_gap            REAL,
    unpriced_reason    TEXT,

    conflicted         INTEGER,
    confidence_factors TEXT,
    hours_stale        REAL,
    contract_scraped_at TEXT,
    written_at         TEXT NOT NULL,

    -- Filled in later by label_outcomes(); NULL until the horizon has
    -- actually elapsed. Never written by the snapshot path.
    fwd_market_7d      REAL,
    fwd_market_14d     REAL,
    fwd_market_30d     REAL,

    PRIMARY KEY (as_of, player_key, model_version, param_set_id)
);

CREATE INDEX IF NOT EXISTS idx_ce_as_of   ON board_snapshots(as_of);
CREATE INDEX IF NOT EXISTS idx_ce_player  ON board_snapshots(player_key, as_of);
CREATE INDEX IF NOT EXISTS idx_ce_label   ON board_snapshots(as_of, label);

CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT);
"""


def _ensure_schema(path: Path) -> None:
    key = str(path)
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


def _row_values(row: dict[str, Any], as_of: str, board: dict[str, Any]) -> tuple:
    components = row.get("components") or {}
    mis = row.get("mispricing") or {}
    return (
        as_of,
        str(row.get("playerKey") or ""),
        str(board.get("modelVersion") or ""),
        str(board.get("paramSetId") or ""),
        row.get("displayName"),
        row.get("position"),
        row.get("assetClass"),
        row.get("score"),
        row.get("label"),
        row.get("labelReason"),
        1 if row.get("qualified") else 0,
        row.get("confidence"),
        components.get("mispricing"),
        components.get("sharpFlow"),
        components.get("opportunity"),
        json.dumps(row.get("componentsAbsent") or []),
        row.get("fairValue"),
        row.get("marketValue"),
        row.get("anchorKey"),
        mis.get("pctGap"),
        row.get("unpricedReason"),
        1 if (row.get("conflict") or {}).get("conflicted") else 0,
        json.dumps(row.get("confidenceFactors") or {}),
        (board.get("inputs") or {}).get("hoursStale"),
        board.get("contractScrapedAt"),
        datetime.now(timezone.utc).isoformat(),
    )


_INSERT = """
INSERT OR REPLACE INTO board_snapshots (
    as_of, player_key, model_version, param_set_id,
    display_name, position, asset_class,
    score, label, label_reason, qualified, confidence,
    component_mispricing, component_sharp_flow, component_opportunity,
    components_absent,
    fair_value, market_value, anchor_key, pct_gap, unpriced_reason,
    conflicted, confidence_factors, hours_stale, contract_scraped_at, written_at
) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
"""


def write_board(
    board: dict[str, Any],
    *,
    as_of: str | date | None = None,
    path: Path | None = None,
) -> dict[str, Any]:
    """Persist one board. Idempotent for the same (date, model, params).

    ``INSERT OR REPLACE`` on the composite key means re-running a day
    updates that day's rows rather than duplicating them, while rows
    under a different model or parameter version are left untouched —
    they record what a different model said and are not ours to rewrite.
    """
    if not board or board.get("status") != "ok":
        return {"written": 0, "skipped": True, "reason": board.get("status") or "no board"}

    if as_of is None:
        as_of_str = datetime.now(timezone.utc).date().isoformat()
    elif isinstance(as_of, date):
        as_of_str = as_of.isoformat()
    else:
        as_of_str = str(as_of)

    players = [r for r in (board.get("players") or []) if r.get("playerKey")]
    rows = [_row_values(r, as_of_str, board) for r in players]

    conn = connect(path)
    try:
        conn.executemany(_INSERT, rows)
        conn.commit()
    finally:
        conn.close()

    return {
        "written": len(rows),
        "asOf": as_of_str,
        "modelVersion": board.get("modelVersion"),
        "paramSetId": board.get("paramSetId"),
        "skipped": False,
    }


def coverage(path: Path | None = None) -> dict[str, Any]:
    """What is actually stored — the answer to "is this working?".

    Exists for the same reason ``rank_history.coverage`` does: a writer
    that silently stops is invisible until a study needs the history and
    finds it absent, a year later.
    """
    target = path or DB_PATH
    if not target.exists():
        return {"exists": False, "snapshots": 0, "reason": "no snapshot database on disk"}
    conn = connect(target)
    try:
        total = conn.execute("SELECT COUNT(*) FROM board_snapshots").fetchone()[0]
        dates = conn.execute(
            "SELECT MIN(as_of), MAX(as_of), COUNT(DISTINCT as_of) FROM board_snapshots"
        ).fetchone()
        labelled = conn.execute(
            "SELECT COUNT(*) FROM board_snapshots WHERE fwd_market_14d IS NOT NULL"
        ).fetchone()[0]
        versions = [
            r[0]
            for r in conn.execute(
                "SELECT DISTINCT model_version FROM board_snapshots ORDER BY model_version"
            ).fetchall()
        ]
    finally:
        conn.close()
    return {
        "exists": True,
        "rows": total,
        "firstDate": dates[0],
        "lastDate": dates[1],
        "distinctDates": dates[2],
        "rowsWithOutcomeLabels": labelled,
        "modelVersions": versions,
    }


def history_for_player(
    player_key: str, *, limit: int = 90, path: Path | None = None
) -> list[dict[str, Any]]:
    """What we said about one player over time."""
    target = path or DB_PATH
    if not target.exists():
        return []
    conn = connect(target)
    try:
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            """
            SELECT as_of, score, label, confidence, fair_value, market_value,
                   model_version, param_set_id, fwd_market_14d
              FROM board_snapshots
             WHERE player_key = ?
             ORDER BY as_of DESC
             LIMIT ?
            """,
            (player_key, int(limit)),
        ).fetchall()
    finally:
        conn.close()
    return [dict(r) for r in rows]


def label_outcomes(
    *,
    horizon_days: int,
    prices_by_date: dict[str, dict[str, float]],
    path: Path | None = None,
) -> dict[str, Any]:
    """Fill forward-return columns for rows whose horizon has elapsed.

    Separate from the write path on purpose: the score is knowable on the
    day, the outcome is not, and a schema that pretended otherwise would
    invite writing an outcome before it happened. ``prices_by_date`` is
    supplied by the caller (from the panel or the live board) rather than
    fetched here, so this function cannot accidentally reach forward past
    the horizon it was asked for.
    """
    column = {7: "fwd_market_7d", 14: "fwd_market_14d", 30: "fwd_market_30d"}.get(horizon_days)
    if column is None:
        raise ValueError(f"unsupported horizon {horizon_days}; expected one of 7, 14, 30")

    target = path or DB_PATH
    if not target.exists():
        return {"updated": 0, "reason": "no snapshot database"}

    conn = connect(target)
    updated = 0
    try:
        rows = conn.execute(
            f"SELECT as_of, player_key, market_value FROM board_snapshots "  # noqa: S608
            f"WHERE {column} IS NULL AND market_value IS NOT NULL"
        ).fetchall()
        for as_of, player_key, market_value in rows:
            origin = datetime.strptime(as_of, "%Y-%m-%d").date()
            horizon = origin.toordinal() + horizon_days
            horizon_key = date.fromordinal(horizon).isoformat()
            future = (prices_by_date.get(horizon_key) or {}).get(player_key)
            if future is None or not market_value or market_value <= 0:
                continue
            conn.execute(
                f"UPDATE board_snapshots SET {column} = ? "  # noqa: S608
                f"WHERE as_of = ? AND player_key = ? AND {column} IS NULL",
                ((future - market_value) / market_value, as_of, player_key),
            )
            updated += 1
        conn.commit()
    finally:
        conn.close()
    return {"updated": updated, "horizonDays": horizon_days, "column": column}


def distinct_dates(path: Path | None = None) -> Iterable[str]:
    target = path or DB_PATH
    if not target.exists():
        return []
    conn = connect(target)
    try:
        return [r[0] for r in conn.execute("SELECT DISTINCT as_of FROM board_snapshots").fetchall()]
    finally:
        conn.close()
