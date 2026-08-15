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

OBSERVATIONS ARE THE STORAGE.  CONTINUITY IS DERIVED.
─────────────────────────────────────────────────────
One row per **actual observation**, keyed ``(league, observed_at)``.
Nothing is merged, compressed or bridged at write time, because the
write path cannot know what happened while it was not looking.

An earlier draft of this module stored **intervals** — one row per
distinct card, extended whenever a later observation matched the same
hash — and owner review rejected it as unsafe.  The defect is worth
recording, because it is subtle and it is the exact failure this whole
tranche exists to prevent:

    Jan 1: observe card A
    (one month with NO observations at all)
    Feb 1: observe card A

Extending the interval produces a single window ``Jan 1 → Feb 1``, and
therefore answers "what was the card on Jan 15?" with **card A, fidelity
exact**.  That is not justified.  During the unobserved month the true
history could have been ``A → B → A``, or collection could simply have
been dead.  **A matching hash across a gap is not evidence of
continuity** — it is two observations with nothing in between, and
inferring a straight line through them manufactures evidence.

    UNOBSERVED MUST REMAIN UNOBSERVED.

There is deliberately **no gap threshold** anywhere in this module.  A
"cards more than N hours apart do not bridge" rule would be a magic
number standing in for a cadence guarantee this platform does not have —
the recorder is best-effort, the scrape cadence drifts, and the whole
reason the row exists is that collection stops silently.  Instead the
read path REPORTS the bracket it used and the gap it spans, and lets a
caller apply whatever standard its own question needs.

Storage is normalised so that recording every observation costs almost
nothing: the card payload is content-addressed in
``scoring_card_payloads`` and each observation stores only its hash.
Deduplicating identical *content* under its own hash loses no evidence —
the hash IS the identity — while deduplicating *observations* would lose
exactly the evidence that decides fidelity.

FIDELITY IS EXPLICIT, AND ``exact`` IS THE STRICT DEFAULT
─────────────────────────────────────────────────────────
``scoring_card_at`` answers at one of four fidelities, and returns only
``exact`` unless a caller opts into more:

``exact``          an observation exists AT that instant.
``reconstructed``  two adjacent observations BRACKET the instant and
                   agree on the card.  Strong evidence, not proof —
                   ``bracketGapHours`` states how wide the unobserved
                   span is, and the caller decides whether that is good
                   enough for its question.
``nearest_prior``  only a prior observation exists, or the bracketing
                   pair DISAGREE so the instant is genuinely
                   indeterminate.  Bounded by ``coverageGapEndsAt``.
``unavailable``    ``None``.  Nothing supports an answer.

What no argument ever produces is today's card returned for a historical
date it has no bearing on.  ``nearest_prior`` looks strictly backwards,
and a later observation can only contribute as one endpoint of an
*agreeing* bracket — never as a standalone answer about the past.

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
ledger to add three additive tables, which is the same trade
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

# 2 — per-observation scoring-card storage.  Schema 1 was the interval
# design rejected in review; it never ran on any host, so there is no
# migration to write.  A developer who exercised it locally is left with
# an unused ``scoring_card_history`` table and loses nothing.
SCHEMA_VERSION = 2

# Fidelity vocabulary.  Ordered weakest-last so a caller can widen what
# it accepts without memorising the strings.
FIDELITY_EXACT = "exact"
FIDELITY_RECONSTRUCTED = "reconstructed"
FIDELITY_NEAREST_PRIOR = "nearest_prior"

#: Default.  Only an observation AT the instant counts.
ACCEPT_EXACT: tuple[str, ...] = (FIDELITY_EXACT,)
#: Also accept an agreeing bracket, labelled with the gap it spans.
ACCEPT_BRACKETED: tuple[str, ...] = (FIDELITY_EXACT, FIDELITY_RECONSTRUCTED)
#: Also accept the most recent prior observation.  Never a later one.
ACCEPT_ANY: tuple[str, ...] = (
    FIDELITY_EXACT,
    FIDELITY_RECONSTRUCTED,
    FIDELITY_NEAREST_PRIOR,
)

_SETUP_LOCK = threading.Lock()
_SETUP_DONE: dict[str, bool] = {}

_SCHEMA = """
CREATE TABLE IF NOT EXISTS meta (
    key   TEXT PRIMARY KEY,
    value TEXT
);

-- C1-RET-04, content half.  Content-addressed, so recording the same
-- card on every scrape costs one row per DISTINCT card rather than one
-- per observation.  Deduplicating identical content under its own hash
-- loses no evidence; deduplicating observations would.
CREATE TABLE IF NOT EXISTS scoring_card_payloads (
    card_hash           TEXT PRIMARY KEY,

    -- The card itself, stored whole.  A future question about a key we
    -- do not extract today is answerable only if the payload survived.
    scoring_json        TEXT NOT NULL,

    -- The canonical W18-F001 identity when it could be computed, NULL
    -- when it could not.  NULL means "not computed", never "no card" --
    -- scoring_fingerprint() itself returns None rather than hashing {}.
    scoring_fingerprint TEXT,

    first_recorded_at   TEXT NOT NULL
);

-- C1-RET-04, evidence half.  ONE ROW PER ACTUAL OBSERVATION.  Nothing
-- is merged or bridged here: see the module docstring for why a
-- matching hash across a gap is not evidence of continuity.
CREATE TABLE IF NOT EXISTS scoring_card_observations (
    sleeper_league_id TEXT NOT NULL,
    observed_at       TEXT NOT NULL,
    card_hash         TEXT NOT NULL,
    season            TEXT,
    recorded_at       TEXT NOT NULL,
    PRIMARY KEY (sleeper_league_id, observed_at)
);

CREATE INDEX IF NOT EXISTS idx_sco_league_time
    ON scoring_card_observations(sleeper_league_id, observed_at);
CREATE INDEX IF NOT EXISTS idx_sco_hash
    ON scoring_card_observations(card_hash);

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


def _parse_iso(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value.strip():
        return None
    text = value.strip().replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed


def _gap_hours(start: Any, end: Any) -> float | None:
    a, b = _parse_iso(start), _parse_iso(end)
    if a is None or b is None:
        return None
    return round((b - a).total_seconds() / 3600.0, 4)


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

    One row per observation, keyed ``(league, observed_at)``.  Nothing is
    merged with a neighbouring observation and no interval is extended —
    the write path cannot know what happened while it was not looking.

    Returns ``{"action": "recorded"|"duplicate"|"skipped", ...}``.
    ``duplicate`` means this exact instant was already recorded, which
    makes a replay of a collection run a structural no-op.

    ``skipped`` is returned for an empty card and nothing is written.
    An absent card is not evidence that a league scores nothing — it is
    the absence of an observation, and storing ``{}`` as a scoring
    observation would let a fetch failure read back as a real settings
    change.
    """
    league_id = str(sleeper_league_id or "").strip()
    if not league_id or not scoring:
        return {"action": "skipped", "reason": "empty_card_or_league"}

    stamp = observed_at or _utc_now()
    digest = card_hash(scoring)
    now = _utc_now()

    conn = connect(path)
    try:
        # Content first: an observation must never reference a payload
        # that is not there.  DO NOTHING preserves the original
        # first_recorded_at and the fingerprint recorded with it.
        conn.execute(
            """
            INSERT INTO scoring_card_payloads (
                card_hash, scoring_json, scoring_fingerprint, first_recorded_at
            ) VALUES (?, ?, ?, ?)
            ON CONFLICT(card_hash) DO NOTHING
            """,
            (
                digest,
                json.dumps(dict(scoring), sort_keys=True, separators=(",", ":")),
                scoring_fingerprint,
                now,
            ),
        )
        cur = conn.execute(
            """
            INSERT INTO scoring_card_observations (
                sleeper_league_id, observed_at, card_hash, season, recorded_at
            ) VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(sleeper_league_id, observed_at) DO NOTHING
            """,
            (league_id, stamp, digest, str(season) if season is not None else None, now),
        )
        inserted = cur.rowcount == 1
        conn.commit()
        total = conn.execute(
            "SELECT COUNT(*) FROM scoring_card_observations WHERE sleeper_league_id = ?",
            (league_id,),
        ).fetchone()[0]
    finally:
        conn.close()

    return {
        "action": "recorded" if inserted else "duplicate",
        "cardHash": digest,
        "observedAt": stamp,
        "observationCount": int(total or 0),
    }


def _observation_at_or_before(
    conn: sqlite3.Connection, league_id: str, when: str
) -> tuple[Any, ...] | None:
    return conn.execute(
        """
        SELECT o.observed_at, o.card_hash, o.season,
               p.scoring_json, p.scoring_fingerprint
          FROM scoring_card_observations o
          JOIN scoring_card_payloads p ON p.card_hash = o.card_hash
         WHERE o.sleeper_league_id = ? AND o.observed_at <= ?
         ORDER BY o.observed_at DESC
         LIMIT 1
        """,
        (league_id, when),
    ).fetchone()


def _observation_at_or_after(
    conn: sqlite3.Connection, league_id: str, when: str
) -> tuple[Any, ...] | None:
    return conn.execute(
        """
        SELECT o.observed_at, o.card_hash, o.season,
               p.scoring_json, p.scoring_fingerprint
          FROM scoring_card_observations o
          JOIN scoring_card_payloads p ON p.card_hash = o.card_hash
         WHERE o.sleeper_league_id = ? AND o.observed_at >= ?
         ORDER BY o.observed_at ASC
         LIMIT 1
        """,
        (league_id, when),
    ).fetchone()


def _answer(league_id: str, row: tuple[Any, ...], fidelity: str) -> dict[str, Any]:
    return {
        "sleeperLeagueId": league_id,
        "observedAt": row[0],
        "cardHash": row[1],
        "season": row[2],
        "scoringSettings": json.loads(row[3]),
        "scoringFingerprint": row[4],
        "fidelity": fidelity,
    }


def scoring_card_at(
    sleeper_league_id: str,
    when: str,
    *,
    accept: tuple[str, ...] = ACCEPT_EXACT,
    path: Path | None = None,
) -> dict[str, Any] | None:
    """The card this league was carrying at ``when``, at a stated fidelity.

    ``accept`` decides how much inference the caller is willing to take,
    and it defaults to none.  Pass ``ACCEPT_BRACKETED`` or ``ACCEPT_ANY``
    to widen it; the answer always carries ``fidelity`` so a widened
    result can never be mistaken for a measured one.

    * ``exact`` — an observation exists at that instant.
    * ``reconstructed`` — the observations immediately before and after
      ``when`` both exist and agree on the card.  ``bracketGapHours``
      states how wide the unobserved span is.  This is **not** exact: the
      card could have changed and changed back inside the gap, and a
      matching pair of endpoints cannot rule that out.
    * ``nearest_prior`` — only a prior observation exists, or the
      bracketing pair DISAGREE (so the instant is genuinely
      indeterminate and the answer is the last thing actually seen).
      ``coverageGapEndsAt`` bounds it.

    ``None`` when nothing supports an answer at the requested fidelity,
    including every date before the recorder started.  No value of
    ``accept`` returns a later card as a standalone answer about an
    earlier date — that substitution, missing = current, is the one this
    tranche exists to prevent.
    """
    league_id = str(sleeper_league_id or "").strip()
    if not league_id or not when:
        return None

    conn = connect(path)
    try:
        prior = _observation_at_or_before(conn, league_id, when)
        later = _observation_at_or_after(conn, league_id, when)
    finally:
        conn.close()

    if prior is not None and str(prior[0]) == str(when):
        return _answer(league_id, prior, FIDELITY_EXACT) if FIDELITY_EXACT in accept else None

    if prior is None:
        # Nothing before it.  A later observation alone says nothing
        # about an earlier date, however recent or however matching.
        return None

    bracketed = later is not None and later[1] == prior[1]
    if bracketed:
        if FIDELITY_RECONSTRUCTED not in accept:
            return None
        out = _answer(league_id, prior, FIDELITY_RECONSTRUCTED)
        out["bracketStartsAt"] = prior[0]
        out["bracketEndsAt"] = later[0]
        out["bracketGapHours"] = _gap_hours(prior[0], later[0])
        return out

    if FIDELITY_NEAREST_PRIOR not in accept:
        return None
    out = _answer(league_id, prior, FIDELITY_NEAREST_PRIOR)
    out["coverageGapStartsAt"] = prior[0]
    # The next observation of ANY card bounds how far the prior one could
    # have run.  Without it "nearest prior" would look like an unbounded
    # claim rather than a gap of known width.
    out["coverageGapEndsAt"] = later[0] if later is not None else None
    out["coverageGapHours"] = _gap_hours(prior[0], later[0]) if later is not None else None
    return out


def scoring_card_observations(
    sleeper_league_id: str | None = None,
    *,
    path: Path | None = None,
) -> list[dict[str, Any]]:
    """Every recorded observation, oldest first.  The raw evidence.

    Operators and tests only — see the package docstring.
    """
    where = "WHERE o.sleeper_league_id = ?" if sleeper_league_id else ""
    params: tuple[Any, ...] = (str(sleeper_league_id).strip(),) if sleeper_league_id else ()
    conn = connect(path)
    try:
        rows = conn.execute(
            f"""
            SELECT o.sleeper_league_id, o.observed_at, o.card_hash, o.season,
                   p.scoring_fingerprint
              FROM scoring_card_observations o
              JOIN scoring_card_payloads p ON p.card_hash = o.card_hash
              {where}
             ORDER BY o.sleeper_league_id, o.observed_at
            """,
            params,
        ).fetchall()
    finally:
        conn.close()
    return [
        {
            "sleeperLeagueId": r[0],
            "observedAt": r[1],
            "cardHash": r[2],
            "season": r[3],
            "scoringFingerprint": r[4],
        }
        for r in rows
    ]


def scoring_card_windows(
    sleeper_league_id: str,
    *,
    path: Path | None = None,
) -> list[dict[str, Any]]:
    """Runs of consecutive observations that agree on the card.

    **Derived, never stored.**  A window is a summary of observations,
    not a claim that the card held continuously across it — which is why
    each one carries ``maxGapHours``, the widest unobserved span inside
    it.  A window whose ``observationCount`` is 2 and whose
    ``maxGapHours`` is 744 is two observations a month apart, and it
    reads as exactly that rather than as a month of coverage.

    ``A → B → A`` is three windows, because the second ``A`` is a
    different run of observations and merging it with the first would
    assert continuity across a period the card demonstrably differed.
    """
    obs = scoring_card_observations(sleeper_league_id, path=path)
    windows: list[dict[str, Any]] = []
    for row in obs:
        if windows and windows[-1]["cardHash"] == row["cardHash"]:
            w = windows[-1]
            gap = _gap_hours(w["lastObservedAt"], row["observedAt"])
            if gap is not None and (w["maxGapHours"] is None or gap > w["maxGapHours"]):
                w["maxGapHours"] = gap
            w["lastObservedAt"] = row["observedAt"]
            w["observationCount"] += 1
            continue
        windows.append(
            {
                "sleeperLeagueId": row["sleeperLeagueId"],
                "cardHash": row["cardHash"],
                "firstObservedAt": row["observedAt"],
                "lastObservedAt": row["observedAt"],
                "observationCount": 1,
                "maxGapHours": None,
                "scoringFingerprint": row["scoringFingerprint"],
            }
        )
    return windows


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
        observations = conn.execute("SELECT COUNT(*) FROM scoring_card_observations").fetchone()[0]
        leagues = conn.execute(
            "SELECT COUNT(DISTINCT sleeper_league_id) FROM scoring_card_observations"
        ).fetchone()[0]
        distinct_cards = conn.execute("SELECT COUNT(*) FROM scoring_card_payloads").fetchone()[0]
        card_last = conn.execute(
            "SELECT MAX(observed_at) FROM scoring_card_observations"
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
            "observations": int(observations or 0),
            "distinctCards": int(distinct_cards or 0),
            "leagues": int(leagues or 0),
            "lastObservedAt": card_last,
        },
        "trending": {
            "observations": int(trend_rows or 0),
            "snapshots": int(trend_snaps or 0),
            "lastObservedAt": trend_last,
        },
    }
