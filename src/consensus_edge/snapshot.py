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

Three defects an audit found in the first version of this file, all
fixed here and each pinned by a test, because every one of them was
described *correctly* in prose while the code did the opposite:

1. **``INSERT OR REPLACE`` destroyed the labels this file said it never
   touches.** SQLite implements it as DELETE-then-INSERT, so the
   conflicting row is removed outright and every column absent from the
   insert list — which is exactly the ``fwd_*`` columns — comes back
   NULL. Re-running an already-labelled day silently unlabelled it. Now
   an explicit ``ON CONFLICT ... DO UPDATE SET`` naming only the columns
   the write path owns.
2. **``label_outcomes`` keyed on half the primary key.** The key is four
   columns *because* two parameter sets on one date are two different
   claims; SELECT and UPDATE used two, so the first row's market value
   became the forward return for both, corrupting precisely the
   comparison the wide key exists to enable.
3. **The outcome was a raw return** while every other measurement in the
   package uses cohort-excess. A player who rose 3% in a market that
   rose 3% has told us nothing, and storing it as a positive outcome
   makes any signal look predictive in exactly the periods it was least
   useful. Both are now stored: ``fwd_market_*`` (raw, as before) and
   ``fwd_excess_*`` (cohort-excess, the one to analyse).
"""

from __future__ import annotations

import json
import sqlite3
import threading
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, Iterable

DB_PATH: Path = Path(__file__).resolve().parents[2] / "data" / "consensus_edge.sqlite"

# 2 (2026-08-04): added the cohort-excess outcome columns and the four
# fields that made a stored row impossible to analyse — see
# ``_ADDED_COLUMNS``.  Bumped rather than silently extended so a database
# written by the old code is identifiable.
SCHEMA_VERSION = 2

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
    -- The RANKING key (score x confidence/100), not a derived nicety:
    -- it is what the API serves in and what every measurement ranks on,
    -- so a stored row that lacks it cannot be put back in order.
    conviction         REAL,

    component_mispricing  REAL,
    component_sharp_flow  REAL,
    component_opportunity REAL,
    components_absent     TEXT,
    -- Measured-and-rejected is not the same as missing, and collapsing
    -- them is the exact distinction ``score.composite`` exists to keep.
    -- With opportunity at weight zero this is non-empty on EVERY row.
    components_zero_weight TEXT,
    -- Without the weights, no stored row can be recomputed from its own
    -- components — the composite is unreproducible from the record of it.
    effective_weights     TEXT,

    fair_value         REAL,
    market_value       REAL,
    anchor_key         TEXT,
    pct_gap            REAL,
    unpriced_reason    TEXT,
    -- The biggest single discriminator in the confidence score (the
    -- cohort-level penalty is 1.0 vs 0.75) and the control any study of
    -- panel heterogeneity needs. Both were dropped.
    cohort_level       TEXT,
    source_count       INTEGER,

    conflicted         INTEGER,
    confidence_factors TEXT,
    hours_stale        REAL,
    contract_scraped_at TEXT,
    written_at         TEXT NOT NULL,

    -- Filled in later by label_outcomes(); NULL until the horizon has
    -- actually elapsed. Never written by the snapshot path — which is
    -- what INSERT OR REPLACE used to violate, since SQLite implements it
    -- as DELETE-then-INSERT.
    fwd_market_7d      REAL,
    fwd_market_14d     REAL,
    fwd_market_30d     REAL,
    -- Cohort-excess, the quantity every other measurement in this
    -- package uses. Raw return is kept beside it rather than replaced:
    -- the two answer different questions and one is recoverable from
    -- neither the other nor the row.
    fwd_excess_7d      REAL,
    fwd_excess_14d     REAL,
    fwd_excess_30d     REAL,

    PRIMARY KEY (as_of, player_key, model_version, param_set_id)
);

CREATE INDEX IF NOT EXISTS idx_ce_as_of   ON board_snapshots(as_of);
CREATE INDEX IF NOT EXISTS idx_ce_player  ON board_snapshots(player_key, as_of);
CREATE INDEX IF NOT EXISTS idx_ce_label   ON board_snapshots(as_of, label);

CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT);
"""


# Columns added after v1.  ``CREATE TABLE IF NOT EXISTS`` is a no-op
# against an existing table, so a database written by the old code would
# keep its old shape forever and every write naming a new column would
# fail.  Additive ALTERs only: this never drops or retypes, so the
# migration cannot lose a row that is by definition irreplaceable.
_ADDED_COLUMNS: tuple[tuple[str, str], ...] = (
    ("conviction", "REAL"),
    ("components_zero_weight", "TEXT"),
    ("effective_weights", "TEXT"),
    ("cohort_level", "TEXT"),
    ("source_count", "INTEGER"),
    ("fwd_excess_7d", "REAL"),
    ("fwd_excess_14d", "REAL"),
    ("fwd_excess_30d", "REAL"),
)


def _migrate(conn: sqlite3.Connection) -> list[str]:
    """Bring an existing table up to the current column set.

    Returns the columns it added, so a caller (or a test) can tell a
    migration from a fresh create.
    """
    have = {row[1] for row in conn.execute("PRAGMA table_info(board_snapshots)").fetchall()}
    added: list[str] = []
    for name, decl in _ADDED_COLUMNS:
        if name in have:
            continue
        conn.execute(f"ALTER TABLE board_snapshots ADD COLUMN {name} {decl}")  # noqa: S608
        added.append(name)
    return added


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
            _migrate(conn)
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


# The columns the SNAPSHOT path owns, in order.  The four key columns
# come first; everything after them is what an upsert overwrites.  The
# ``fwd_*`` columns are deliberately absent from both lists — they belong
# to ``label_outcomes`` and no write here may touch them.
_KEY_COLUMNS = ("as_of", "player_key", "model_version", "param_set_id")
_OWNED_COLUMNS = (
    "display_name",
    "position",
    "asset_class",
    "score",
    "label",
    "label_reason",
    "qualified",
    "confidence",
    "conviction",
    "component_mispricing",
    "component_sharp_flow",
    "component_opportunity",
    "components_absent",
    "components_zero_weight",
    "effective_weights",
    "fair_value",
    "market_value",
    "anchor_key",
    "pct_gap",
    "unpriced_reason",
    "cohort_level",
    "source_count",
    "conflicted",
    "confidence_factors",
    "hours_stale",
    "contract_scraped_at",
    "written_at",
)


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
        row.get("conviction"),
        components.get("mispricing"),
        components.get("sharpFlow"),
        components.get("opportunity"),
        json.dumps(row.get("componentsAbsent") or []),
        json.dumps(row.get("componentsZeroWeight") or []),
        json.dumps(row.get("effectiveWeights") or {}),
        row.get("fairValue"),
        row.get("marketValue"),
        row.get("anchorKey"),
        mis.get("pctGap"),
        row.get("unpricedReason"),
        mis.get("cohortLevel"),
        row.get("sourceCount"),
        1 if (row.get("conflict") or {}).get("conflicted") else 0,
        json.dumps(row.get("confidenceFactors") or {}),
        (board.get("inputs") or {}).get("hoursStale"),
        board.get("contractScrapedAt"),
        datetime.now(timezone.utc).isoformat(),
    )


def _build_insert() -> str:
    """Upsert that leaves the outcome columns alone.

    ``INSERT OR REPLACE`` is DELETE-then-INSERT in SQLite, so it nulled
    every column the insert did not name — including the forward returns
    this module's own docstring says the write path never touches. An
    explicit ``DO UPDATE SET`` over the owned columns is the only form
    that keeps that promise.
    """
    columns = _KEY_COLUMNS + _OWNED_COLUMNS
    placeholders = ",".join("?" * len(columns))
    assignments = ",\n    ".join(f"{name} = excluded.{name}" for name in _OWNED_COLUMNS)
    return (
        f"INSERT INTO board_snapshots ({', '.join(columns)})\n"
        f"VALUES ({placeholders})\n"
        f"ON CONFLICT({', '.join(_KEY_COLUMNS)}) DO UPDATE SET\n    {assignments}"
    )


_INSERT = _build_insert()


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
        # Reported separately from ``labelled``: a row can have a raw
        # return and no cohort-excess (fewer than three measurable peers),
        # and the excess is the column an analysis actually reads. A
        # store that is 100% labelled and 0% analysable should not look
        # healthy.
        with_excess = conn.execute(
            "SELECT COUNT(*) FROM board_snapshots WHERE fwd_excess_14d IS NOT NULL"
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
        "rowsWithCohortExcess": with_excess,
        "modelVersions": versions,
        "schemaVersion": SCHEMA_VERSION,
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
            SELECT as_of, score, label, confidence, conviction,
                   fair_value, market_value, cohort_level, source_count,
                   model_version, param_set_id, fwd_market_14d, fwd_excess_14d
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


def prices_by_date(path: Path | None = None) -> dict[str, dict[str, dict[str, Any]]]:
    """Every anchor price this store has recorded, keyed by date.

    The shape :func:`outcomes.market_prices` returns, so it drops
    straight into :func:`label_outcomes` and into ``forward_returns``.

    **The store labels itself.** This is why ``label_outcomes`` could go
    a whole release with no production caller: the obvious source of past
    prices is the git panel, which is expensive, needs an unshallow clone
    and does not exist on the box that runs the timer. But the snapshot
    rows already carry ``market_value`` per (date, player) — the price
    the board was judged against on the day, written by the same code
    path that will write the horizon's. Origin and horizon prices are
    therefore the same quantity by construction, which is the property
    ``outcomes`` insists on and the one a second source would risk.

    De-duplicated per (date, player) by taking the first row seen: the
    anchor price is a property of the market, not of the model version
    that recorded it, so two parameter sets on one date agree on it.
    """
    target = path or DB_PATH
    if not target.exists():
        return {}
    conn = connect(target)
    try:
        rows = conn.execute(
            "SELECT as_of, player_key, market_value, asset_class, position "
            "FROM board_snapshots WHERE market_value IS NOT NULL AND market_value > 0"
        ).fetchall()
    finally:
        conn.close()
    out: dict[str, dict[str, dict[str, Any]]] = {}
    for as_of, player_key, market_value, asset_class, position in rows:
        day = out.setdefault(str(as_of), {})
        if player_key in day:
            continue
        day[str(player_key)] = {
            "price": float(market_value),
            "assetClass": asset_class,
            "position": position,
        }
    return out


_RAW_COLUMN = {7: "fwd_market_7d", 14: "fwd_market_14d", 30: "fwd_market_30d"}
_EXCESS_COLUMN = {7: "fwd_excess_7d", 14: "fwd_excess_14d", 30: "fwd_excess_30d"}


def label_outcomes(
    *,
    horizon_days: int,
    prices_by_date: dict[str, dict[str, dict[str, Any]]],
    path: Path | None = None,
) -> dict[str, Any]:
    """Fill forward-return columns for rows whose horizon has elapsed.

    Separate from the write path on purpose: the score is knowable on the
    day, the outcome is not, and a schema that pretended otherwise would
    invite writing an outcome before it happened. ``prices_by_date`` is
    supplied by the caller (from the panel or the live board) rather than
    fetched here, so this function cannot accidentally reach forward past
    the horizon it was asked for.

    ``prices_by_date`` maps an ISO date to the map
    :func:`outcomes.market_prices` returns — ``{playerKey: {price,
    assetClass, position}}``. It used to be a bare ``{playerKey: price}``,
    which is why the stored outcome was a RAW return: a cohort cannot be
    formed without the position and the origin price. Both are now
    stored, and the excess is what an analysis should read.

    **ORIGIN dates must be in the map, not just horizons.** The cohort
    median is computed across the origin's whole population, so a map
    holding only the future is a map with no baseline.
    :func:`prices_by_date` supplies both by construction.

    Three things this gets right that the first version did not:

    * **The full four-part key.** Two parameter sets on one date are two
      different claims. Keying the UPDATE on ``(as_of, player_key)``
      alone wrote the first row's return onto both.
    * **The horizon snaps FORWARD.** Requiring an exact ``origin + N``
      hit silently skipped every row whose horizon fell on a day the
      panel does not have; snapping forward keeps the holding period at
      least as long as asked, never shorter.
    * **Cohort-excess.** Computed by ``outcomes.forward_returns``, the
      same function every other measurement uses, rather than a second
      definition of "what happened next".
    """
    from src.consensus_edge import outcomes as oc

    raw_column = _RAW_COLUMN.get(horizon_days)
    excess_column = _EXCESS_COLUMN.get(horizon_days)
    if raw_column is None or excess_column is None:
        raise ValueError(f"unsupported horizon {horizon_days}; expected one of 7, 14, 30")

    target = path or DB_PATH
    if not target.exists():
        return {"updated": 0, "reason": "no snapshot database"}

    available = sorted(date.fromisoformat(d) for d in prices_by_date)

    conn = connect(target)
    updated = 0
    considered = 0
    no_horizon_date = 0
    try:
        rows = conn.execute(
            "SELECT as_of, player_key, model_version, param_set_id "  # noqa: S608
            f"FROM board_snapshots WHERE {raw_column} IS NULL AND market_value IS NOT NULL"
        ).fetchall()
        considered = len(rows)

        # One forward-returns pass per (origin, horizon) pair rather than
        # per row: the cohort median is a property of the pair, and
        # recomputing it per row would be both slow and — if the row set
        # differed — inconsistent between rows of the same cohort.
        returns_cache: dict[tuple[str, str], dict[str, dict[str, Any]]] = {}
        for as_of, player_key, model_version, param_set_id in rows:
            try:
                origin = date.fromisoformat(as_of)
            except ValueError:
                continue
            horizon = oc.horizon_date(origin, horizon_days, available)
            if horizon is None:
                no_horizon_date += 1
                continue
            cache_key = (as_of, horizon.isoformat())
            if cache_key not in returns_cache:
                returns_cache[cache_key] = oc.forward_returns(
                    prices_by_date.get(as_of) or {},
                    prices_by_date.get(horizon.isoformat()) or {},
                )
            entry = returns_cache[cache_key].get(player_key)
            if not entry or entry.get("rawReturn") is None:
                continue
            conn.execute(
                f"UPDATE board_snapshots SET {raw_column} = ?, {excess_column} = ? "  # noqa: S608
                "WHERE as_of = ? AND player_key = ? "
                "AND model_version = ? AND param_set_id = ?",
                (
                    entry["rawReturn"],
                    entry.get("excessReturn"),
                    as_of,
                    player_key,
                    model_version,
                    param_set_id,
                ),
            )
            updated += 1
        conn.commit()
    finally:
        conn.close()
    return {
        "updated": updated,
        "considered": considered,
        "noHorizonDate": no_horizon_date,
        "horizonDays": horizon_days,
        "column": raw_column,
        "excessColumn": excess_column,
    }


def distinct_dates(path: Path | None = None) -> Iterable[str]:
    target = path or DB_PATH
    if not target.exists():
        return []
    conn = connect(target)
    try:
        return [r[0] for r in conn.execute("SELECT DISTINCT as_of FROM board_snapshots").fetchall()]
    finally:
        conn.close()
