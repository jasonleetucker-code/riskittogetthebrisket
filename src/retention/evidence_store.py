"""Append-only records of observations the live path overwrites.

Covers two C1A retention rows:

``C1-RET-04`` — **scoring card at a date.**  The manifest records this
one as ABSENT BY CONSTRUCTION, and that is literal:
``league_registry.write_scoring_snapshot`` ends in ``tmp.replace(path)``,
so every refresh destroys the previous card.  Sleeper leagues are edited
mid-season and chain year to year under new ids, so "what was this league
scoring on 2026-03-01" is a question the platform could not answer about
its own past — and every retrospective that scores a historical week
under *today's* card silently measures the wrong league.

``C1-RET-05`` — **Sleeper trending adds.**  ``src/adapters/
sleeper_trending.py`` holds a 15-minute TTL cache and persists nothing,
so the waiver-heat series has never existed.  The FAAB market layer
already treats trending as demand evidence; without a series there is
no way to ask whether demand led or lagged a value move.

WHY A CHANGE LOG, NOT A DAILY COPY
──────────────────────────────────
The manifest's acceptance wording for ``C1-RET-04`` is "append-only
history keyed by (league, observed_at)".  A row per observation would
satisfy that literally and produce thousands of identical cards, because
scoring settings change a few times a year and the refresh runs on the
scrape cadence.  This stores **open intervals** instead: one row per
distinct card, carrying the window over which it was observed.

That is strictly more informative, not less — ``scoring_card_at`` answers
the same "card at a date" question, and the interval additionally records
*when it changed*, which a pile of daily copies only implies.  A league
that changes A → B → A gets three rows, not two, because the second A is
a different observation window and collapsing it would invent continuity
across a period the card demonstrably differed.

**A missing interval is not "unchanged".**  Intervals record what was
OBSERVED.  Gaps before ``first_observed_at``, and gaps where the recorder
did not run, are unobserved — ``scoring_card_at`` returns ``None`` for a
date it cannot cover rather than extrapolating the nearest card
backwards.  Missing is never today's value, and it is never zero.

DESIGN TAKEN FROM ``src/snapshots/board_store.py``
──────────────────────────────────────────────────
Deliberately the same shape, because that module already had its design
corrected once under audit and the corrections apply verbatim here:

* the write path **names the columns it owns** and no others.
  ``INSERT OR REPLACE`` is DELETE-then-INSERT in SQLite and silently
  nulls every unlisted column, so it is never used;
* WAL + ``synchronous=NORMAL``, schema created idempotently on connect;
* **no decision path reads this.**  The read functions exist for
  operators, health checks and tests.

Deliberately NOT wired to ``platform_ledger.PLATFORM_SCHEMA_VERSION``:
bumping that re-runs the whole platform migration on every deployed
ledger to add two additive tables, which is the same trade
``src/sharp/roster_store.py`` declined for the same reason.

PRIVACY
───────
INTERNAL.  ``data/`` is gitignored and this file must never be
force-added into public Git history.  Our own leagues' transactions —
real managers, real trades — live in the separate PRIVATE store
``src/retention/league_events.py``, so that backing this up and
publishing it can never be the same gesture.
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

DB_PATH: Path = Path(__file__).resolve().parents[2] / "data" / "retention" / "evidence.sqlite"

SCHEMA_VERSION = 1

_SETUP_LOCK = threading.Lock()
_SETUP_DONE: dict[str, bool] = {}

_SCHEMA = """
CREATE TABLE IF NOT EXISTS meta (
    key   TEXT PRIMARY KEY,
    value TEXT
);

-- C1-RET-04.  One row per DISTINCT card per observation window.  See
-- the module docstring for why this is an interval log rather than a
-- row per observation.
CREATE TABLE IF NOT EXISTS scoring_card_history (
    sleeper_league_id  TEXT NOT NULL,
    -- Interval start doubles as the tie-break in the key: a league that
    -- reverts to an earlier card gets a NEW row, because the second
    -- window is a different observation and merging them would assert
    -- continuity across a period the card demonstrably differed.
    first_observed_at  TEXT NOT NULL,
    last_observed_at   TEXT NOT NULL,
    card_hash          TEXT NOT NULL,

    -- The card itself, stored whole.  A future question about a key we
    -- do not extract today is answerable only if the payload survived.
    scoring_json       TEXT NOT NULL,

    -- The canonical W18-F001 identity when it could be computed, NULL
    -- when it could not.  NULL means "not computed", never "no card" --
    -- scoring_fingerprint() itself returns None rather than hashing {}.
    scoring_fingerprint TEXT,
    season              TEXT,

    observation_count  INTEGER NOT NULL DEFAULT 1,
    PRIMARY KEY (sleeper_league_id, first_observed_at)
);

CREATE INDEX IF NOT EXISTS idx_sch_league_last
    ON scoring_card_history(sleeper_league_id, last_observed_at);
CREATE INDEX IF NOT EXISTS idx_sch_hash
    ON scoring_card_history(sleeper_league_id, card_hash);

-- C1-RET-05.  One row per (source, snapshot, player).  observed_at is
-- the SNAPSHOT's own fetch stamp, not the write time, so re-recording a
-- cached snapshot collides on the primary key and is a no-op.  Dedupe
-- is structural rather than caller discipline.
CREATE TABLE IF NOT EXISTS trending_observations (
    source        TEXT NOT NULL,
    observed_at   TEXT NOT NULL,
    player_id     TEXT NOT NULL,
    count         INTEGER,
    lookback_hours INTEGER,
    recorded_at   TEXT NOT NULL,
    PRIMARY KEY (source, observed_at, player_id)
);

CREATE INDEX IF NOT EXISTS idx_tro_player
    ON trending_observations(player_id, observed_at);
CREATE INDEX IF NOT EXISTS idx_tro_observed
    ON trending_observations(source, observed_at);
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


def connect(path: Path | None = None) -> sqlite3.Connection:
    target = path or DB_PATH
    _ensure_schema(target)
    return sqlite3.connect(str(target), timeout=5.0)


def _reset_setup_cache_for_tests() -> None:
    """Forget which paths have been initialised.  Tests only."""
    with _SETUP_LOCK:
        _SETUP_DONE.clear()


# ── C1-RET-04: scoring cards ─────────────────────────────────────────


def card_hash(scoring: dict[str, Any] | None) -> str:
    """Content hash of a scoring card.

    Key order and numeric form are normalised away so that a re-serialised
    identical card does not read as a change.  This is deliberately NOT
    ``scoring_fingerprint`` from ``src/league_comparison/sleeper_scoring.py``:
    that one answers "may these two leagues share rankings", excludes
    non-numeric metadata and returns ``None`` when it cannot prove an
    answer.  Here the question is "is this byte-for-byte the same card we
    already have", and a card we cannot fingerprint still has to be
    stored under something.
    """
    normalised = {
        str(k): (float(v) if isinstance(v, (int, float)) and not isinstance(v, bool) else v)
        for k, v in sorted((scoring or {}).items())
    }
    blob = json.dumps(normalised, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()[:32]


def observe_scoring_card(
    sleeper_league_id: str,
    scoring: dict[str, Any] | None,
    *,
    observed_at: str | None = None,
    scoring_fingerprint: str | None = None,
    season: str | None = None,
    path: Path | None = None,
) -> dict[str, Any]:
    """Record that this league was observed carrying this card.

    Returns ``{"action": "opened"|"extended"|"skipped", ...}``.

    ``skipped`` is returned for an empty card and nothing is written.
    An absent card is not evidence that a league scores nothing — it is
    the absence of an observation, and storing ``{}`` as a scoring
    interval would let a fetch failure read back as a real settings
    change.
    """
    league_id = str(sleeper_league_id or "").strip()
    if not league_id or not scoring:
        return {"action": "skipped", "reason": "empty_card_or_league"}

    stamp = observed_at or _utc_now()
    digest = card_hash(scoring)
    conn = connect(path)
    try:
        cur = conn.execute(
            """
            SELECT first_observed_at, card_hash, last_observed_at, observation_count
              FROM scoring_card_history
             WHERE sleeper_league_id = ?
             ORDER BY first_observed_at DESC
             LIMIT 1
            """,
            (league_id,),
        )
        latest = cur.fetchone()

        if latest and latest[1] == digest:
            # Same card still in force — extend the open interval.
            # ``max`` guards an out-of-order replay from rewinding the
            # window; a late arrival adds no information about the end.
            new_last = max(str(latest[2] or ""), stamp)
            conn.execute(
                """
                UPDATE scoring_card_history
                   SET last_observed_at  = ?,
                       observation_count = observation_count + 1
                 WHERE sleeper_league_id = ? AND first_observed_at = ?
                """,
                (new_last, league_id, latest[0]),
            )
            conn.commit()
            return {
                "action": "extended",
                "cardHash": digest,
                "firstObservedAt": latest[0],
                "lastObservedAt": new_last,
                "observationCount": int(latest[3] or 0) + 1,
            }

        # A different card (or the first one ever seen) opens a new
        # interval.  Named columns on conflict: a replay of the same
        # stamp must not clear ``observation_count`` or the payload.
        conn.execute(
            """
            INSERT INTO scoring_card_history (
                sleeper_league_id, first_observed_at, last_observed_at,
                card_hash, scoring_json, scoring_fingerprint, season,
                observation_count
            ) VALUES (?, ?, ?, ?, ?, ?, ?, 1)
            ON CONFLICT(sleeper_league_id, first_observed_at) DO UPDATE SET
                last_observed_at    = excluded.last_observed_at,
                card_hash           = excluded.card_hash,
                scoring_json        = excluded.scoring_json,
                scoring_fingerprint = excluded.scoring_fingerprint,
                season              = excluded.season
            """,
            (
                league_id,
                stamp,
                stamp,
                digest,
                json.dumps(dict(scoring), sort_keys=True, separators=(",", ":")),
                scoring_fingerprint,
                str(season) if season is not None else None,
            ),
        )
        conn.commit()
        return {
            "action": "opened",
            "cardHash": digest,
            "firstObservedAt": stamp,
            "lastObservedAt": stamp,
            "observationCount": 1,
            "previousCardHash": latest[1] if latest else None,
        }
    finally:
        conn.close()


_CARD_COLUMNS = """
    first_observed_at, last_observed_at, card_hash,
    scoring_json, scoring_fingerprint, season, observation_count
"""


def _card_row(league_id: str, row: tuple[Any, ...], fidelity: str) -> dict[str, Any]:
    return {
        "sleeperLeagueId": league_id,
        "firstObservedAt": row[0],
        "lastObservedAt": row[1],
        "cardHash": row[2],
        "scoringSettings": json.loads(row[3]),
        "scoringFingerprint": row[4],
        "season": row[5],
        "observationCount": int(row[6] or 0),
        "fidelity": fidelity,
    }


def scoring_card_at(
    sleeper_league_id: str,
    when: str,
    *,
    allow_nearest_prior: bool = False,
    path: Path | None = None,
) -> dict[str, Any] | None:
    """The card this league was observed carrying at ``when``.

    Two answers, and the caller must choose which it can live with.

    **Default — ``exact`` only.**  Returns a card only when an
    observation window actually covers that instant.  ``None``
    otherwise, including for a date before the recorder started.  A
    recorder that ran on Jan 1 and again on Feb 1 under a different card
    proves the change happened *somewhere* in between; it does not prove
    what was in force on Jan 15, and answering "A" would be a guess
    wearing the costume of a measurement.

    **``allow_nearest_prior=True``** additionally returns the most
    recent interval that ENDED before ``when``, stamped
    ``fidelity: "nearest_prior"`` with ``coverageGapEndsAt`` naming the
    next observation that bounds the uncertainty.  Opt-in and labelled,
    because a downgraded answer a caller did not ask for is how
    approximations end up quoted as facts.

    What is never returned is today's card for a historical date.  That
    substitution — missing = current — is the one the retention tranche
    exists to prevent, and no flag enables it.
    """
    league_id = str(sleeper_league_id or "").strip()
    if not league_id or not when:
        return None
    conn = connect(path)
    try:
        row = conn.execute(
            f"""
            SELECT {_CARD_COLUMNS}
              FROM scoring_card_history
             WHERE sleeper_league_id = ?
               AND first_observed_at <= ?
               AND last_observed_at  >= ?
             ORDER BY first_observed_at DESC
             LIMIT 1
            """,
            (league_id, when, when),
        ).fetchone()
        if row:
            return _card_row(league_id, row, "exact")
        if not allow_nearest_prior:
            return None

        prior = conn.execute(
            f"""
            SELECT {_CARD_COLUMNS}
              FROM scoring_card_history
             WHERE sleeper_league_id = ?
               AND last_observed_at < ?
             ORDER BY last_observed_at DESC
             LIMIT 1
            """,
            (league_id, when),
        ).fetchone()
        if not prior:
            return None
        # The next observation of ANY card bounds how far the prior one
        # could have run.  Without it "nearest prior" would look like an
        # unbounded claim rather than a gap of known width.
        next_seen = conn.execute(
            """
            SELECT MIN(first_observed_at)
              FROM scoring_card_history
             WHERE sleeper_league_id = ? AND first_observed_at > ?
            """,
            (league_id, prior[1]),
        ).fetchone()
    finally:
        conn.close()

    out = _card_row(league_id, prior, "nearest_prior")
    out["coverageGapStartsAt"] = prior[1]
    out["coverageGapEndsAt"] = next_seen[0] if next_seen else None
    return out


def scoring_card_history(
    sleeper_league_id: str | None = None,
    *,
    path: Path | None = None,
) -> list[dict[str, Any]]:
    """Every observed interval, oldest first.  Operators and tests only."""
    conn = connect(path)
    try:
        if sleeper_league_id:
            cur = conn.execute(
                """
                SELECT sleeper_league_id, first_observed_at, last_observed_at,
                       card_hash, scoring_fingerprint, season, observation_count
                  FROM scoring_card_history
                 WHERE sleeper_league_id = ?
                 ORDER BY first_observed_at
                """,
                (str(sleeper_league_id).strip(),),
            )
        else:
            cur = conn.execute(
                """
                SELECT sleeper_league_id, first_observed_at, last_observed_at,
                       card_hash, scoring_fingerprint, season, observation_count
                  FROM scoring_card_history
                 ORDER BY sleeper_league_id, first_observed_at
                """
            )
        rows = cur.fetchall()
    finally:
        conn.close()
    return [
        {
            "sleeperLeagueId": r[0],
            "firstObservedAt": r[1],
            "lastObservedAt": r[2],
            "cardHash": r[3],
            "scoringFingerprint": r[4],
            "season": r[5],
            "observationCount": int(r[6] or 0),
        }
        for r in rows
    ]


# ── C1-RET-05: Sleeper trending adds ─────────────────────────────────


def observe_trending_snapshot(
    snapshot: dict[str, Any] | None,
    *,
    source: str = "sleeper_add",
    path: Path | None = None,
) -> dict[str, Any]:
    """Persist one trending-adds snapshot.

    ``snapshot`` is the adapter's payload: ``{"fetchedAt": ..., "counts":
    {player_id: n}, "lookbackHours": n}``.  Recording is keyed on the
    snapshot's OWN ``fetchedAt``, so re-recording the adapter's cached
    snapshot on a later pass writes nothing new instead of inventing a
    second observation of one fetch.

    An empty ``counts`` map writes nothing and reports ``skipped``.  Zero
    recorded players is not evidence that nobody was added; it is the
    absence of a fetch.
    """
    if not isinstance(snapshot, dict):
        return {"action": "skipped", "reason": "no_snapshot"}
    counts = snapshot.get("counts")
    if not isinstance(counts, dict) or not counts:
        return {"action": "skipped", "reason": "no_counts"}
    observed_at = str(snapshot.get("fetchedAt") or "").strip()
    if not observed_at:
        return {"action": "skipped", "reason": "no_fetched_at"}

    lookback = snapshot.get("lookbackHours")
    try:
        lookback_i = int(lookback) if lookback is not None else None
    except (TypeError, ValueError):
        lookback_i = None

    recorded_at = _utc_now()
    rows: list[tuple[Any, ...]] = []
    for player_id, count in counts.items():
        pid = str(player_id or "").strip()
        if not pid:
            continue
        try:
            n = int(count)
        except (TypeError, ValueError):
            continue
        rows.append((source, observed_at, pid, n, lookback_i, recorded_at))
    if not rows:
        return {"action": "skipped", "reason": "no_usable_rows"}

    conn = connect(path)
    try:
        before = conn.execute(
            "SELECT COUNT(*) FROM trending_observations WHERE source = ? AND observed_at = ?",
            (source, observed_at),
        ).fetchone()[0]
        conn.executemany(
            """
            INSERT INTO trending_observations (
                source, observed_at, player_id, count, lookback_hours, recorded_at
            ) VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT(source, observed_at, player_id) DO NOTHING
            """,
            rows,
        )
        conn.commit()
        after = conn.execute(
            "SELECT COUNT(*) FROM trending_observations WHERE source = ? AND observed_at = ?",
            (source, observed_at),
        ).fetchone()[0]
    finally:
        conn.close()

    inserted = int(after) - int(before)
    return {
        "action": "recorded" if inserted else "duplicate",
        "observedAt": observed_at,
        "offered": len(rows),
        "inserted": inserted,
    }


def trending_series(
    player_id: str,
    *,
    source: str = "sleeper_add",
    limit: int = 500,
    path: Path | None = None,
) -> list[dict[str, Any]]:
    """One player's observed trending counts, oldest first.

    Operators and tests.  No decision path may call this — see the
    package docstring.
    """
    pid = str(player_id or "").strip()
    if not pid:
        return []
    conn = connect(path)
    try:
        cur = conn.execute(
            """
            SELECT observed_at, count, lookback_hours
              FROM trending_observations
             WHERE source = ? AND player_id = ?
             ORDER BY observed_at DESC
             LIMIT ?
            """,
            (source, pid, int(limit)),
        )
        rows = cur.fetchall()
    finally:
        conn.close()
    return [
        {
            "observedAt": r[0],
            "count": int(r[1]) if r[1] is not None else None,
            "lookbackHours": r[2],
        }
        for r in reversed(rows)
    ]


# ── Coverage (health signal input) ───────────────────────────────────


def coverage(*, path: Path | None = None) -> dict[str, Any]:
    """What this store actually holds.  Feeds ``src/retention/health.py``.

    Reports ``present: False`` when the database file does not exist —
    distinguishable from a database that exists and is empty, because
    "the recorder never ran" and "the recorder ran and found nothing"
    are different failures with different fixes.
    """
    target = path or DB_PATH
    if not target.exists():
        return {"present": False, "path": str(target)}

    conn = connect(target)
    try:
        cards = conn.execute("SELECT COUNT(*) FROM scoring_card_history").fetchone()[0]
        leagues = conn.execute(
            "SELECT COUNT(DISTINCT sleeper_league_id) FROM scoring_card_history"
        ).fetchone()[0]
        card_last = conn.execute(
            "SELECT MAX(last_observed_at) FROM scoring_card_history"
        ).fetchone()[0]
        trend_rows = conn.execute("SELECT COUNT(*) FROM trending_observations").fetchone()[0]
        trend_snaps = conn.execute(
            "SELECT COUNT(DISTINCT observed_at) FROM trending_observations"
        ).fetchone()[0]
        trend_last = conn.execute("SELECT MAX(observed_at) FROM trending_observations").fetchone()[
            0
        ]
    finally:
        conn.close()

    return {
        "present": True,
        "path": str(target),
        "scoringCards": {
            "intervals": int(cards or 0),
            "leagues": int(leagues or 0),
            "lastObservedAt": card_last,
        },
        "trending": {
            "observations": int(trend_rows or 0),
            "snapshots": int(trend_snaps or 0),
            "lastObservedAt": trend_last,
        },
    }
