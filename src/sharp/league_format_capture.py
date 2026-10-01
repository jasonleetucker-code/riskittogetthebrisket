"""Point-in-time league FORMAT captures for Sharp-discovered Sleeper leagues.

WHY THIS EXISTS
───────────────
The completed-trade ledger (``src/trade/market_trade_normalize.py``) can only
classify a trade's format — superflex or 1QB, IDP starter depth and DL/LB/DB
structure, TE demand, the exact scoring card — when it holds the HOST league's
real roster slots and scoring.  The production bootstrap census (2026-10-01)
measured 9,583 of 10,095 underlying trades in the ``sleeper_sharp_discovery``
lane, across 3,493 leagues, with every one of those axes UNKNOWN: the discovery
row only ever carried ``type`` / ``best_ball`` / roster count.

This module is the ONE owner of "what format was this Sharp league in, and
when did we see it".  It is part of the Sharp acquisition owner, not a second
crawler:

* **Captures piggyback on fetches the Sharp crawls already make.**  Discovery
  records the league objects ``/user/{id}/leagues/nfl/{season}`` returns, and
  the roster crawl records the ``/league/{id}`` payload it already fetches for
  its own format filter.  Neither costs a request.
* **The only extra requests are a bounded catch-up pass**
  (:func:`capture_league_formats`) for leagues those two never reach — one
  ``GET /v1/league/{id}`` per league, paced and budgeted exactly like the other
  Sharp crawls (``crawler._CallBudget``), ordered by the shared fair queue
  (``record_queue.prioritize_league_ids``: never-checked first, then oldest).
  It runs inside the transaction-crawl timer, because that crawl is the one
  whose trades the ledger reads.

APPEND-ONLY, DATED
──────────────────
``sharp_league_format_captures`` never updates or deletes a row.  A payload is
recorded when it DIFFERS from the capture in force just before it for the same
``(league_id, season)``; an identical re-observation inserts nothing.  So a
mid-season settings change is a new dated row beside the old one, and the
ledger can ask what was in force AT a trade's timestamp
(:func:`capture_in_force`).  When a league was last LOOKED AT is a separate,
mutable cursor (``sharp_league_format_checks``) — the same split as
``sharp_league_fetch`` beside ``asset_movements``.

The hash covers the format payload only (roster slots, the normalized numeric
scoring card, the format settings, season, roster count).  League ``status``
moves pre_draft → drafting → in_season → complete without the format moving, so
it is stored beside each row (``league_status``) and never hashed.

A payload missing ``roster_positions`` or ``scoring_settings`` is NOT recorded:
an incomplete object would hash differently from a complete one of the same
league and manufacture a "settings change" out of a transport difference.

EXACT AT TRADE TIME = A BRACKET
───────────────────────────────
The nearest prior capture SELECTS the format a trade is read in
(:func:`capture_in_force`), but on its own it proves only what the settings
were when it was taken — a capture months old certifies nothing about a trade
today.  A trade's format is exact at trade time only when it is BRACKETED:

* a capture at or before the trade, AND
* a later observation of the same league-season, at or after the trade, that
  saw the SAME payload hash, with no different hash in between
  (:func:`confirm_after_trade`).

Every unchanged re-observation is therefore logged, with its payload hash, in
the append-only ``sharp_league_format_observations`` (near-duplicate repeats within
:data:`OBSERVATION_LOG_MIN_INTERVAL_MS` of each other are collapsed); a changed payload is a
new capture row, which is itself an observation.  A different hash after the
trade → ``changed_after_trade``; nothing yet → ``unconfirmed_after_trade``.
Both are capped below NATIVE_COMPARABLE by the ledger
(``market_trade_format.format_timing_cap``) while the in-force capture still
supplies the axes.  Latency: a Sharp trade becomes exact at the next
observation of its league — discovery or the roster crawl when they touch it
(daily), else the catch-up pass's weekly re-check
(:data:`DEFAULT_REFRESH_AFTER_HOURS`).  The residual, named rather than hidden:
a change AND a revert both strictly between two observations are invisible to
any sampler.

WHICH LEAGUES ARE CAPTURED
──────────────────────────
Only DYNASTY leagues (Sleeper ``settings.type == 2``, the code
``src/intel/league_filter.py`` keys on), plus leagues whose type is not stated
(the payload is what would classify them).  Redraft and keeper leagues are
checked and skipped (``not_dynasty``): the ledger's ``dynastyState`` axis can
never MATCH them, so storing their 3-6 KB payloads would only grow the ledger.
This is deliberately a DYNASTY filter, not a target-format filter: non-target
dynasty formats (1QB, offense-only, other team counts) are kept for
BROAD_CONTEXT and translator research.  Best ball is NOT a filter either — it
is a format axis, and the owner's own target league is a dynasty best-ball
league.

RETENTION
─────────
:func:`prune_captures` (run from ``src/intel/ledger.prune``, the ledger's one
retention pass) removes a capture only when ALL of: it is older than the
movement retention horizon (``ledger.MOVEMENT_RETENTION_DAYS``); it is not the
capture in force for any trade the ledger still retains; and it is either
superseded by a later capture of the same league-season or its league has not
been checked inside the horizon.  So the capture in force NOW for a live league
is never pruned however old it is (an unchanged league inserts nothing, so its
one row can legitimately be years old).  The observation log is pruned in the
same pass (:func:`prune_observations`): rows older than both the horizon and
the earliest retained trade, plus a lossless per-run compaction.

LEGACY SNAPSHOTS
────────────────
Between #1586 and this owner, discovery wrote ``settings_json.marketFormat``,
and ``ledger.upsert_leagues`` replaces ``settings_json`` wholesale on every
re-discovery.  :func:`migrate_legacy_settings_snapshots` (one-shot, idempotent,
run by :func:`ensure_schema`, which discovery calls BEFORE it upserts leagues)
copies each snapshot into the capture table at its original ``capturedAt`` so
the earlier date survives the overwrite.

RATE LIMITS
───────────
The catch-up pass stops at the first HTTP 429 (``stopped_reason =
"rate_limited"``) and never mistakes it for a deleted league.  It shares the
box's public IP with every other Sharp crawl, so a large one-shot backfill
(``--formats-only --format-budget 4000``) must not be run while another Sharp
timer (discovery, records, rosters, transactions) is running.

WHAT THIS DOES NOT DO
─────────────────────
It computes no format axis (``src/trade/market_trade_format.py`` does, through
the canonical slot / scoring / TE owners) and touches no value.  The data is
box-local in the intel ledger (``data/intel/``, gitignored), from Sleeper's
public, unauthenticated API.
"""

from __future__ import annotations

import hashlib
import json
import logging
import sqlite3
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Iterable, Mapping, Sequence

from src.intel import ledger

log = logging.getLogger(__name__)

SLEEPER_BASE = "https://api.sleeper.app/v1"

#: Capture provenance — which fetch produced the payload.
SOURCE_DISCOVERY = "discovery_user_leagues"
SOURCE_ROSTER_CRAWL = "roster_crawl_league_endpoint"
SOURCE_LEAGUE_ENDPOINT = "format_pass_league_endpoint"

#: Calls per catch-up pass.  Half the transaction crawl's 600: the pass runs
#: inside that timer (4x/day), so its total cost there is bounded by this.
DEFAULT_BUDGET = 300
DEFAULT_SLEEP_S = 0.12
#: A captured league is re-checked at most this often.  League settings are
#: near-static in season; discovery and the roster crawl re-capture for free
#: in between whenever they touch the league.
DEFAULT_REFRESH_AFTER_HOURS = 168
#: Consecutive fetch ERRORS (transport failure / unexpected status) that stop
#: a pass: a run of them is far more likely an outage than a run of bad ids,
#: and spending the rest of the budget on it would only make it worse.  A
#: deleted league (200 + ``null``, or 404) is an ANSWER, not an error, and does
#: not count; a 429 stops the pass at once (``rate_limited``).
MAX_CONSECUTIVE_FAILURES = 10

RESULT_NOT_DYNASTY = "not_dynasty"
RESULT_NOT_FOUND = "not_found"
#: Check results that settle a never-captured league until its refresh window
#: (it was looked at and has nothing to capture), instead of re-fetching it on
#: every pass.
_SETTLED_RESULTS = frozenset({RESULT_NOT_DYNASTY, RESULT_NOT_FOUND})


class RateLimited(RuntimeError):
    """Sleeper answered HTTP 429.  Raised by the pass's fetcher to stop it."""


class _FetchErrorMarker:
    def __repr__(self) -> str:  # pragma: no cover — debugging aid
        return "FETCH_ERROR"


#: What a pass fetcher returns for a transport failure / unexpected status —
#: distinct from ``None``, which means the league does not exist.
FETCH_ERROR = _FetchErrorMarker()

#: A league whose last observed status is ``complete`` is frozen: its season
#: is over and its settings no longer govern any trade.  Captured once, it
#: leaves the refresh queue.
_FROZEN_STATUSES = frozenset({"complete"})

TIMING_AT_OR_BEFORE = "at_or_before_trade"
TIMING_POST_TRADE = "post_trade_capture"
TIMING_TRADE_TIME_UNKNOWN = "trade_time_unknown"

_SCHEMA = """
CREATE TABLE IF NOT EXISTS sharp_league_format_captures (
  capture_id      INTEGER PRIMARY KEY AUTOINCREMENT,
  league_id       TEXT NOT NULL,
  season          TEXT,
  payload_sha256  TEXT NOT NULL,
  captured_ms     INTEGER NOT NULL,
  capture_source  TEXT NOT NULL,
  league_status   TEXT,
  payload_json    TEXT NOT NULL
);
CREATE UNIQUE INDEX IF NOT EXISTS uq_slfc_point
  ON sharp_league_format_captures(league_id, season, payload_sha256, captured_ms);
CREATE INDEX IF NOT EXISTS idx_slfc_league_time
  ON sharp_league_format_captures(league_id, captured_ms);
CREATE INDEX IF NOT EXISTS idx_slfc_captured
  ON sharp_league_format_captures(captured_ms);

CREATE TABLE IF NOT EXISTS sharp_league_format_checks (
  league_id        TEXT PRIMARY KEY,
  last_checked_ms  INTEGER NOT NULL,
  last_result      TEXT,
  last_status      TEXT,
  last_error       TEXT
);
CREATE INDEX IF NOT EXISTS idx_slfk_checked ON sharp_league_format_checks(last_checked_ms);

CREATE TABLE IF NOT EXISTS sharp_league_format_observations (
  observation_id  INTEGER PRIMARY KEY AUTOINCREMENT,
  league_id       TEXT NOT NULL,
  season          TEXT,
  payload_sha256  TEXT NOT NULL,
  observed_ms     INTEGER NOT NULL,
  observe_source  TEXT NOT NULL
);
CREATE UNIQUE INDEX IF NOT EXISTS uq_slfo_point
  ON sharp_league_format_observations(league_id, season, payload_sha256, observed_ms);
CREATE INDEX IF NOT EXISTS idx_slfo_league_time
  ON sharp_league_format_observations(league_id, observed_ms);

CREATE TABLE IF NOT EXISTS sharp_league_format_migrations (
  name        TEXT PRIMARY KEY,
  applied_ms  INTEGER NOT NULL,
  detail      TEXT
);
"""

#: The only tables this module writes.  Pinned by a structural test.
WRITE_TABLES = (
    "sharp_league_format_captures",
    "sharp_league_format_checks",
    "sharp_league_format_observations",
    "sharp_league_format_migrations",
)

#: An unchanged re-observation is logged (``sharp_league_format_observations``)
#: only when no observation of the same payload is newer than this.  It exists
#: only to collapse the near-simultaneous repeats of one crawl pass (discovery
#: sees a league once per member, seconds apart).  It is deliberately SHORT:
#: a suppressed same-hash observation is the only evidence that could confirm a
#: trade falling inside the window, and a league that is never observed again
#: (e.g. frozen ``complete``) would lose that confirmation permanently.  The
#: residual is therefore a trade inside a 2-minute window after a same-hash
#: observation of a league never seen again -- fail-closed (unconfirmed), never
#: fabricated: a differing payload is always recorded (as a capture).
OBSERVATION_LOG_MIN_INTERVAL_MS = 120_000

#: ``formatEvidence.confirmationAfterTrade`` — the bracket's verdict
#: (:func:`confirm_after_trade`).
CONFIRMED = "confirmed"
CONFIRMATION_CHANGED = "changed_after_trade"
CONFIRMATION_MISSING = "unconfirmed_after_trade"

MIGRATION_LEGACY_SNAPSHOTS = "legacy_discovery_market_format_v1"
SOURCE_LEGACY_SNAPSHOT = "legacy_discovery_settings_snapshot"
#: A legacy snapshot with no ``capturedAt``: stored at the MIGRATION instant,
#: which is an upper bound on when it was taken (it existed by then).  A trade
#: after that instant genuinely had it in force; a trade before it reads as
#: post-trade.  Never placed earlier than can be proven.
SOURCE_LEGACY_SNAPSHOT_TIME_UNKNOWN = "legacy_discovery_settings_snapshot_time_unknown"


def ensure_schema(conn: sqlite3.Connection) -> None:
    """Additive ``CREATE TABLE IF NOT EXISTS`` — deliberately NOT wired to
    ``ledger.SCHEMA_VERSION``: a version bump runs ``_migrate`` and its table
    clears on every deployed ledger, to add tables nothing else reads.
    (Same posture as ``roster_store.ensure_roster_schema``.)

    Also runs the one-shot legacy-snapshot migration
    (:func:`migrate_legacy_settings_snapshots`), which commits itself the one
    time it does work.  ``executescript`` commits too, so call this ONCE per
    run, before any transaction that must stay open — never per league."""
    conn.executescript(_SCHEMA)
    migrate_legacy_settings_snapshots(conn)


def _iso(ms: int) -> str:
    return datetime.fromtimestamp(ms / 1000, tz=timezone.utc).isoformat()


def _parse_iso_ms(value: Any) -> int | None:
    if not value:
        return None
    try:
        dt = datetime.fromisoformat(str(value))
    except (TypeError, ValueError):
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return int(dt.timestamp() * 1000)


# ── payload ───────────────────────────────────────────────────────────────


def capture_payload(league: Mapping[str, Any]) -> dict[str, Any] | None:
    """The hashable format payload of one Sleeper league object, or ``None``
    when the object is not a complete format statement.

    Delegates the field selection to the format owner
    (``market_trade_format.capture_sleeper_league_format``) so the stored
    shape is exactly what ``format_from_sleeper_league`` reads back.
    """
    if not isinstance(league, Mapping):
        return None
    from src.trade.market_trade_format import capture_sleeper_league_format  # noqa: PLC0415

    cap = capture_sleeper_league_format(league, captured_at="")
    cap.pop("capturedAt", None)
    if not cap.get("roster_positions") or not cap.get("scoring_settings"):
        return None
    return cap


def payload_sha256(payload: Mapping[str, Any]) -> str:
    blob = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


def _season(league: Mapping[str, Any]) -> str | None:
    raw = league.get("season")
    text = str(raw).strip() if raw is not None else ""
    return text or None


def _touch_check(
    conn: sqlite3.Connection,
    league_id: str,
    *,
    checked_ms: int,
    result: str,
    status: str | None,
    error: str | None = None,
) -> None:
    conn.execute(
        """
        INSERT INTO sharp_league_format_checks
          (league_id, last_checked_ms, last_result, last_status, last_error)
        VALUES (?, ?, ?, ?, ?)
        ON CONFLICT(league_id) DO UPDATE SET
          last_checked_ms = MAX(sharp_league_format_checks.last_checked_ms,
                                excluded.last_checked_ms),
          last_result     = excluded.last_result,
          last_status     = COALESCE(excluded.last_status, sharp_league_format_checks.last_status),
          last_error      = excluded.last_error
        """,
        (league_id, int(checked_ms), result, status, error),
    )


def capture_exclusion_reason(league: Mapping[str, Any]) -> str | None:
    """``"not_dynasty"`` for a league whose stated Sleeper type is redraft or
    keeper; ``None`` (capture it) for dynasty and for an unstated type."""
    from src.intel import league_filter  # noqa: PLC0415

    lt = league_filter.league_type(dict(league))
    if lt is None or lt == league_filter.LEAGUE_TYPE_DYNASTY:
        return None
    return RESULT_NOT_DYNASTY


def record_capture(
    conn: sqlite3.Connection,
    league: Mapping[str, Any],
    *,
    captured_ms: int,
    source: str,
    league_id: str | None = None,
) -> str:
    """Record one observed league object.  Returns what happened:

    ``"new"`` (a dated row was appended), ``"unchanged"`` (identical to the
    capture in force at ``captured_ms``), ``"incomplete"`` (not a full format
    statement — nothing recorded), ``"not_dynasty"`` (a redraft / keeper
    league — checked, nothing recorded) or ``"no_league_id"``.

    Never commits: the caller owns its transaction, so a crawl keeps its own
    commit cadence.  The schema must already exist (:func:`ensure_schema`).
    """
    lid = str(league_id or league.get("league_id") or "").strip()
    if not lid:
        return "no_league_id"
    status_raw = league.get("status")
    status = str(status_raw).strip() if status_raw else None
    excluded = capture_exclusion_reason(league)
    if excluded is not None:
        _touch_check(conn, lid, checked_ms=captured_ms, result=excluded, status=status)
        return excluded
    payload = capture_payload(league)
    if payload is None:
        _touch_check(conn, lid, checked_ms=captured_ms, result="incomplete", status=status)
        return "incomplete"
    season = _season(league)
    sha = payload_sha256(payload)
    prior = conn.execute(
        """
        SELECT payload_sha256, captured_ms FROM sharp_league_format_captures
         WHERE league_id = ? AND season IS ? AND captured_ms <= ?
         ORDER BY captured_ms DESC, capture_id DESC LIMIT 1
        """,
        (lid, season, int(captured_ms)),
    ).fetchone()
    if prior is not None and str(prior[0]) == sha:
        _log_observation(
            conn,
            lid,
            season=season,
            sha=sha,
            observed_ms=int(captured_ms),
            source=source,
            last_capture_ms=int(prior[1]),
        )
        _touch_check(conn, lid, checked_ms=captured_ms, result="unchanged", status=status)
        return "unchanged"
    conn.execute(
        """
        INSERT OR IGNORE INTO sharp_league_format_captures
          (league_id, season, payload_sha256, captured_ms, capture_source,
           league_status, payload_json)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        (
            lid,
            season,
            sha,
            int(captured_ms),
            source,
            status,
            json.dumps(payload, sort_keys=True, separators=(",", ":")),
        ),
    )
    _touch_check(conn, lid, checked_ms=captured_ms, result="new", status=status)
    return "new"


def _log_observation(
    conn: sqlite3.Connection,
    league_id: str,
    *,
    season: str | None,
    sha: str,
    observed_ms: int,
    source: str,
    last_capture_ms: int,
) -> None:
    """Append one unchanged re-observation (payload hash + instant) to
    ``sharp_league_format_observations`` -- the evidence the bracket rule
    (:func:`confirm_after_trade`) reads to prove a format did not change across
    a trade.  A CHANGED payload is a capture row, which is itself an
    observation, so only unchanged ones are logged here.  Throttled by
    :data:`OBSERVATION_LOG_MIN_INTERVAL_MS` against the newest observation of
    the same payload (capture or log row).  Append-only: never updates."""
    floor = observed_ms - OBSERVATION_LOG_MIN_INTERVAL_MS
    if last_capture_ms > floor:
        return
    last = conn.execute(
        """
        SELECT MAX(observed_ms) FROM sharp_league_format_observations
         WHERE league_id = ? AND season IS ? AND payload_sha256 = ? AND observed_ms <= ?
        """,
        (league_id, season, sha, observed_ms),
    ).fetchone()
    if last is not None and last[0] is not None and int(last[0]) > floor:
        return
    conn.execute(
        """
        INSERT OR IGNORE INTO sharp_league_format_observations
          (league_id, season, payload_sha256, observed_ms, observe_source)
        VALUES (?, ?, ?, ?, ?)
        """,
        (league_id, season, sha, observed_ms, source),
    )


def record_captures(
    conn: sqlite3.Connection,
    observed: Iterable[tuple[Mapping[str, Any], int]],
    *,
    source: str,
) -> dict[str, int]:
    """:func:`record_capture` over ``(league, captured_ms)`` pairs; counts by outcome."""
    ensure_schema(conn)
    counts: dict[str, int] = {}
    for league, captured_ms in observed:
        outcome = record_capture(conn, league, captured_ms=captured_ms, source=source)
        counts[outcome] = counts.get(outcome, 0) + 1
    return counts


# ── read side (used by the trade ledger, read-only) ──────────────────────


def load_capture_index(conn: sqlite3.Connection) -> dict[str, list[dict[str, Any]]]:
    """``{league_id: [capture, ...]}`` oldest-first.  ``{}`` when the table is
    absent (a ledger no capture has reached yet), so a read-only reader never
    needs to migrate anything."""
    try:
        rows = conn.execute(
            """
            SELECT capture_id, league_id, season, payload_sha256, captured_ms,
                   capture_source, league_status, payload_json
              FROM sharp_league_format_captures
             ORDER BY league_id, captured_ms, capture_id
            """
        ).fetchall()
    except sqlite3.OperationalError as exc:
        if "no such table" in str(exc).lower():
            return {}
        raise
    out: dict[str, list[dict[str, Any]]] = {}
    for r in rows:
        try:
            payload = json.loads(r[7])
        except (TypeError, ValueError):
            continue
        out.setdefault(str(r[1]), []).append(
            {
                "captureId": int(r[0]),
                "leagueId": str(r[1]),
                "season": r[2],
                "payloadSha256": r[3],
                "capturedMs": int(r[4]),
                "capturedAt": _iso(int(r[4])),
                "captureSource": r[5],
                "leagueStatus": r[6],
                "payload": payload,
            }
        )
    return out


def load_observation_index(conn: sqlite3.Connection) -> dict[str, list[dict[str, Any]]]:
    """``{league_id: [observation, ...]}`` oldest-first, from the append-only
    observation log.  ``{}`` when the table is absent (a store no re-check has
    reached yet) -- every bracket then reads as unconfirmed, never confirmed."""
    try:
        rows = conn.execute(
            """
            SELECT league_id, season, payload_sha256, observed_ms
              FROM sharp_league_format_observations
             ORDER BY league_id, observed_ms, observation_id
            """
        ).fetchall()
    except sqlite3.OperationalError as exc:
        if "no such table" in str(exc).lower():
            return {}
        raise
    out: dict[str, list[dict[str, Any]]] = {}
    for lid, season, sha, ms in rows:
        out.setdefault(str(lid), []).append(
            {"season": season, "payloadSha256": sha, "observedMs": int(ms)}
        )
    return out


def _legacy_snapshot(settings: Any) -> tuple[dict[str, Any], int | None, str | None] | None:
    """``(payload, captured_ms | None, season)`` of a legacy
    ``settings_json.marketFormat`` snapshot, or ``None`` when absent."""
    mf = settings.get("marketFormat") if isinstance(settings, Mapping) else None
    if not isinstance(mf, Mapping) or not mf.get("roster_positions"):
        return None
    payload = {k: v for k, v in mf.items() if k != "capturedAt"}
    season = str(mf.get("season")).strip() if mf.get("season") is not None else None
    return payload, _parse_iso_ms(mf.get("capturedAt")), (season or None)


def migrate_legacy_settings_snapshots(
    conn: sqlite3.Connection, *, now_ms: int | None = None
) -> dict[str, int] | None:
    """One-shot, idempotent copy of every legacy ``marketFormat`` snapshot still
    in ``leagues.settings_json`` into the capture table, at its ORIGINAL
    ``capturedAt`` — before a re-discovery's wholesale ``settings_json``
    overwrite can erase the earlier date.

    Returns the counts the one time it runs, ``None`` once already applied.
    A snapshot without ``capturedAt`` is stored at the migration instant (an
    upper bound — see :data:`SOURCE_LEGACY_SNAPSHOT_TIME_UNKNOWN`).  A snapshot
    missing roster slots or the scoring card is skipped, by the same
    completeness rule :func:`record_capture` applies.  Re-running inserts
    nothing (``INSERT OR IGNORE`` on the point key), and the marker row makes
    every later call a single primary-key read.
    """
    done = conn.execute(
        "SELECT 1 FROM sharp_league_format_migrations WHERE name = ?",
        (MIGRATION_LEGACY_SNAPSHOTS,),
    ).fetchone()
    if done is not None:
        return None
    now = int(now_ms if now_ms is not None else time.time() * 1000)
    try:
        rows = conn.execute(
            "SELECT league_id, season, settings_json FROM leagues "
            "WHERE settings_json LIKE '%marketFormat%'"
        ).fetchall()
    except sqlite3.OperationalError as exc:
        if "no such table" not in str(exc).lower():
            raise
        rows = []
    counts = {"copied": 0, "copiedTimeUnknown": 0, "skippedIncomplete": 0, "unparseable": 0}
    for league_id, league_season, settings_json in rows:
        try:
            settings = json.loads(settings_json or "{}")
        except (TypeError, ValueError):
            counts["unparseable"] += 1
            continue
        snap = _legacy_snapshot(settings)
        if snap is None:
            continue
        payload, ms, season = snap
        if not payload.get("roster_positions") or not payload.get("scoring_settings"):
            counts["skippedIncomplete"] += 1
            continue
        source = SOURCE_LEGACY_SNAPSHOT
        if ms is None:
            ms, source = now, SOURCE_LEGACY_SNAPSHOT_TIME_UNKNOWN
        conn.execute(
            """
            INSERT OR IGNORE INTO sharp_league_format_captures
              (league_id, season, payload_sha256, captured_ms, capture_source,
               league_status, payload_json)
            VALUES (?, ?, ?, ?, ?, NULL, ?)
            """,
            (
                str(league_id),
                season or (str(league_season) if league_season else None),
                payload_sha256(payload),
                int(ms),
                source,
                json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str),
            ),
        )
        counts["copied" if source == SOURCE_LEGACY_SNAPSHOT else "copiedTimeUnknown"] += 1
    conn.execute(
        "INSERT OR IGNORE INTO sharp_league_format_migrations (name, applied_ms, detail) "
        "VALUES (?, ?, ?)",
        (MIGRATION_LEGACY_SNAPSHOTS, now, json.dumps(counts, sort_keys=True)),
    )
    conn.commit()
    if any(counts.values()):
        log.info("sharp.league_format_capture: legacy snapshot migration %s", counts)
    return counts


def legacy_settings_capture(league_id: str, settings: Mapping[str, Any]) -> dict[str, Any] | None:
    """A pre-capture-table ``settings_json.marketFormat`` snapshot (written by
    discovery between #1586 and this change) as a dated candidate, so it obeys
    the same timing rule as every other capture.  ``None`` if absent/undated.

    Read-side fallback for a ledger the migration has not reached yet; once
    migrated the same snapshot is also a capture row (same payload, same
    instant — the stored row wins the tie in :func:`capture_in_force`)."""
    snap = _legacy_snapshot(settings)
    if snap is None or snap[1] is None:
        return None
    payload, ms, season = snap
    return {
        "captureId": None,
        "leagueId": str(league_id),
        "season": season or None,
        "payloadSha256": payload_sha256(payload),
        "capturedMs": ms,
        "capturedAt": _iso(ms),
        "captureSource": "legacy_discovery_settings_snapshot",
        "leagueStatus": None,
        "payload": payload,
    }


def _capture_order(c: Mapping[str, Any]) -> tuple[int, bool, int]:
    """Oldest first; at the same instant a STORED row (``captureId`` set) sorts
    after a read-side legacy candidate (``captureId`` None), so the stored row
    wins the tie.  The missing id is ordered by the boolean, not coerced."""
    cid = c.get("captureId")
    return (int(c["capturedMs"]), cid is not None, int(cid) if cid is not None else -1)


def capture_in_force(
    captures: Sequence[Mapping[str, Any]] | None,
    at_ms: int | None,
    *,
    season: str | None = None,
) -> tuple[Mapping[str, Any] | None, str | None]:
    """``(capture, timing)`` — the capture that describes a trade at ``at_ms``.

    * the NEAREST PRIOR capture (``capturedMs <= at_ms``) →
      ``at_or_before_trade``;
    * else, when only LATER captures exist for the same season, the earliest of
      them → ``post_trade_capture`` (used, never presented as exact-at-time);
    * an undated trade → the earliest capture, ``trade_time_unknown``;
    * no capture → ``(None, None)``: the format stays UNKNOWN.

    A capture from a different season than the trade's league is never used.

    This SELECTS the format.  It does not by itself prove the format at trade
    time: exactness additionally needs a later observation confirming the same
    payload (the bracket, :func:`confirm_after_trade` / :func:`bracketed_capture`).
    """
    cands = [
        c
        for c in (captures or ())
        if not (season and c.get("season") and str(c.get("season")) != str(season))
    ]
    if not cands:
        return None, None
    cands = sorted(cands, key=_capture_order)
    if at_ms is None:
        return cands[0], TIMING_TRADE_TIME_UNKNOWN
    prior = [c for c in cands if int(c["capturedMs"]) <= int(at_ms)]
    if prior:
        return prior[-1], TIMING_AT_OR_BEFORE
    return cands[0], TIMING_POST_TRADE


def _season_ok(row: Mapping[str, Any], season: str | None) -> bool:
    return not (season and row.get("season") and str(row.get("season")) != str(season))


def confirm_after_trade(
    capture: Mapping[str, Any],
    start_ms: int,
    end_ms: int | None = None,
    *,
    captures: Sequence[Mapping[str, Any]] | None = None,
    observations: Sequence[Mapping[str, Any]] | None = None,
    season: str | None = None,
) -> dict[str, Any]:
    """The BRACKET verdict for an in-force capture: did a later observation of
    the same league-season confirm the same payload across the trade?

    ``capture`` is the capture in force at ``start_ms`` (the trade, or the
    earliest instant a day-dated trade can have happened).  ``end_ms`` (default
    ``start_ms``) is the latest instant the trade can have happened.  Every
    observation at or after ``start_ms`` -- captures (each is an observation of
    its payload) and the unchanged re-observation log -- is walked in time
    order:

    * a DIFFERENT payload hash before a confirming one -> ``changed_after_trade``
      (the format moved; the in-force capture still describes the axes, but is
      not proven at trade time);
    * the first observation at or after ``end_ms`` carrying the SAME hash, with
      no different hash before it -> ``confirmed``;
    * neither -> ``unconfirmed_after_trade``.

    At one instant a differing hash sorts first (fails closed).  Residual,
    named rather than hidden: a change AND a revert both strictly between the
    capture and the confirming observation are invisible to any sampler -- the
    two observations agree.
    """
    end = int(end_ms if end_ms is not None else start_ms)
    sha = capture.get("payloadSha256")
    points: list[tuple[int, bool]] = []
    for c in captures or ():
        if _season_ok(c, season) and int(c["capturedMs"]) >= int(start_ms):
            points.append((int(c["capturedMs"]), c.get("payloadSha256") == sha))
    for o in observations or ():
        if _season_ok(o, season) and int(o["observedMs"]) >= int(start_ms):
            points.append((int(o["observedMs"]), o.get("payloadSha256") == sha))
    for ms, same in sorted(points):
        if not same or sha is None:
            return {"state": CONFIRMATION_CHANGED, "observedMs": ms, "observedAt": _iso(ms)}
        if ms >= end:
            return {"state": CONFIRMED, "observedMs": ms, "observedAt": _iso(ms)}
    return {"state": CONFIRMATION_MISSING, "observedMs": None, "observedAt": None}


def bracketed_capture(
    captures: Sequence[Mapping[str, Any]] | None,
    observations: Sequence[Mapping[str, Any]] | None,
    at_ms: int | None,
    *,
    season: str | None = None,
    end_ms: int | None = None,
) -> tuple[Mapping[str, Any] | None, str | None, dict[str, Any] | None]:
    """``(capture, timing, confirmation)``: :func:`capture_in_force` SELECTS
    the format; the bracket (:func:`confirm_after_trade`) decides exactness.
    ``confirmation`` is ``None`` unless the capture is ``at_or_before_trade``."""
    cap, timing = capture_in_force(captures, at_ms, season=season)
    if cap is None or timing != TIMING_AT_OR_BEFORE or at_ms is None:
        return cap, timing, None
    return (
        cap,
        timing,
        confirm_after_trade(
            cap, at_ms, end_ms, captures=captures, observations=observations, season=season
        ),
    )


def evidence_dict(
    capture: Mapping[str, Any] | None,
    timing: str | None,
    confirmation: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """The inspectable ``formatEvidence`` an observation carries.

    ``exactAtTradeTime`` is the BRACKET: a capture at or before the trade AND
    a later observation confirming the same payload (``confirmation`` from
    :func:`confirm_after_trade`).  Without a confirmation it is never exact."""
    if capture is None:
        return {"timing": None, "reason": "no_league_format_capture"}
    state = confirmation.get("state") if confirmation else None
    return {
        "timing": timing,
        "exactAtTradeTime": timing == TIMING_AT_OR_BEFORE and state == CONFIRMED,
        "confirmationAfterTrade": (
            (state or CONFIRMATION_MISSING) if timing == TIMING_AT_OR_BEFORE else None
        ),
        "confirmedAt": confirmation.get("observedAt")
        if confirmation and state == CONFIRMED
        else None,
        "captureId": capture.get("captureId"),
        "capturedAt": capture.get("capturedAt"),
        "captureSource": capture.get("captureSource"),
        "payloadSha256": capture.get("payloadSha256"),
        "leagueStatusAtCapture": capture.get("leagueStatus"),
    }


# ── catch-up pass ─────────────────────────────────────────────────────────


@dataclass
class FormatCaptureResult:
    leagues_targeted: int = 0
    leagues_due: int = 0
    leagues_checked: int = 0
    captures_new: int = 0
    captures_unchanged: int = 0
    incomplete_payloads: int = 0
    not_dynasty: int = 0
    not_found: int = 0
    fetch_failures: int = 0
    leagues_pending: int = 0
    calls_used: int = 0
    budget_exhausted: bool = False
    stopped_reason: str | None = None
    errors: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "leaguesTargeted": self.leagues_targeted,
            "leaguesDue": self.leagues_due,
            "leaguesChecked": self.leagues_checked,
            "capturesNew": self.captures_new,
            "capturesUnchanged": self.captures_unchanged,
            "incompletePayloads": self.incomplete_payloads,
            "notDynasty": self.not_dynasty,
            "notFound": self.not_found,
            "fetchFailures": self.fetch_failures,
            "leaguesPending": self.leagues_pending,
            "callsUsed": self.calls_used,
            "budgetExhausted": self.budget_exhausted,
            "stoppedReason": self.stopped_reason,
            "errors": self.errors[:20],
        }


def _default_http_get(url: str) -> Any:
    """The pass's fetcher: the league payload, ``None`` for a league that does
    not exist (200 + ``null`` / 404), :data:`FETCH_ERROR` for a transport
    failure or unexpected status, and :class:`RateLimited` raised on a 429.

    Same client the records and roster crawls use (a paced batch job must not
    ride the user-request circuit breaker — see ``records.py``), through its
    status-classifying variant so a 429 never reads as a deleted league."""
    from src.public_league import sleeper_client  # noqa: PLC0415

    kind, payload = sleeper_client.request_json_classified(url)
    if kind == sleeper_client.FETCH_RATE_LIMITED:
        raise RateLimited(url)
    if kind == sleeper_client.FETCH_ERROR:
        return FETCH_ERROR
    if kind == sleeper_client.FETCH_NOT_FOUND:
        return None
    return payload


def _target_league_ids(conn: sqlite3.Connection, *, ledger_path: Path | None) -> list[str]:
    """Leagues whose trades the ledger reads, plus every sharp-eligible league
    (the transaction crawl's targets, which will produce trades next)."""
    from src.sharp import discovery  # noqa: PLC0415 — discovery imports this module

    with_trades = {
        str(r[0])
        for r in conn.execute(
            "SELECT DISTINCT league_id FROM asset_movements WHERE tx_type = 'trade'"
        ).fetchall()
        if r[0]
    }
    eligible = set(discovery.sharp_eligible_league_ids(ledger_path=ledger_path))
    return sorted(with_trades | eligible)


def _check_state(conn: sqlite3.Connection) -> dict[str, tuple[int, str | None, str | None]]:
    return {
        str(r[0]): (int(r[1]), r[2], r[3])
        for r in conn.execute(
            "SELECT league_id, last_checked_ms, last_status, last_result "
            "FROM sharp_league_format_checks"
        ).fetchall()
    }


def _captured_league_ids(conn: sqlite3.Connection) -> set[str]:
    return {
        str(r[0])
        for r in conn.execute(
            "SELECT DISTINCT league_id FROM sharp_league_format_captures"
        ).fetchall()
    }


def due_league_ids(
    league_ids: Sequence[str],
    *,
    checks: Mapping[str, tuple[Any, ...]],
    captured: set[str],
    now_ms: int,
    refresh_after_hours: float,
) -> list[str]:
    """Which leagues a pass should look at, in fair order.

    Never-captured leagues are due — unless their last check SETTLED them
    (``not_dynasty`` / ``not_found``: looked at, nothing to capture), in which
    case they follow the refresh rule below like a captured league.  A captured
    league is due once its last check is older than ``refresh_after_hours`` —
    unless its last observed status is ``complete`` (frozen season).  Ordering
    is the shared ``record_queue.prioritize_league_ids``: never-checked first,
    then the oldest check, ties by id.

    ``checks`` values are ``(last_checked_ms, last_status[, last_result])``.
    """
    from src.sharp import record_queue  # noqa: PLC0415

    cutoff = now_ms - int(refresh_after_hours * 3600 * 1000)
    due: list[str] = []
    for lid in league_ids:
        state = checks.get(lid)
        if state is None:
            due.append(lid)
            continue
        last_ms, status = state[0], state[1]
        last_result = state[2] if len(state) > 2 else None
        if lid not in captured and last_result not in _SETTLED_RESULTS:
            due.append(lid)
            continue
        if status and str(status).lower() in _FROZEN_STATUSES:
            continue
        if last_ms <= cutoff:
            due.append(lid)
    last_checked = {lid: checks[lid][0] for lid in due if lid in checks}
    return record_queue.prioritize_league_ids(due, last_checked)


def capture_league_formats(
    league_ids: Sequence[str] | None = None,
    *,
    budget: int = DEFAULT_BUDGET,
    sleep_s: float = DEFAULT_SLEEP_S,
    http_get: Callable[[str], Any] | None = None,
    ledger_path: Path | None = None,
    now_ms: int | None = None,
    refresh_after_hours: float = DEFAULT_REFRESH_AFTER_HOURS,
    sleep_fn: Callable[[float], None] = time.sleep,
    clock_ms: Callable[[], int] | None = None,
) -> FormatCaptureResult:
    """One budgeted ``GET /v1/league/{id}`` pass over leagues that are due.

    Never raises on a fetch failure: the league is recorded as checked-and-
    failed (so the fair queue rotates past it) and the pass continues, up to
    :data:`MAX_CONSECUTIVE_FAILURES` errors in a row.  A league that does not
    exist (``None`` from the fetcher) is recorded ``not_found`` and is not an
    error.  A 429 (:class:`RateLimited` from the fetcher) stops the pass at
    once with ``stopped_reason="rate_limited"`` and leaves the league due.
    Commits per league, so the SQLite writer lock is never held across network
    I/O.  Must not overlap another Sharp crawl (shared public IP).
    """
    from src.intel import crawler  # noqa: PLC0415

    now = int(now_ms if now_ms is not None else time.time() * 1000)
    if clock_ms is not None:
        tick = clock_ms
    elif now_ms is not None:
        tick = lambda: now  # noqa: E731 — a pinned clock for deterministic runs
    else:
        tick = lambda: int(time.time() * 1000)  # noqa: E731
    b = crawler._CallBudget(budget, sleep_s, http_get or _default_http_get, sleep_fn)
    result = FormatCaptureResult()

    conn = ledger.connect(ledger_path)
    try:
        ensure_schema(conn)
        conn.commit()
        targets = (
            sorted({str(x).strip() for x in league_ids if str(x or "").strip()})
            if league_ids is not None
            else _target_league_ids(conn, ledger_path=ledger_path)
        )
        result.leagues_targeted = len(targets)
        due = due_league_ids(
            targets,
            checks=_check_state(conn),
            captured=_captured_league_ids(conn),
            now_ms=now,
            refresh_after_hours=refresh_after_hours,
        )
        result.leagues_due = len(due)
        consecutive = 0
        for idx, lid in enumerate(due):
            if not b.can_call():
                result.budget_exhausted = True
                result.leagues_pending = len(due) - idx
                break
            try:
                league = b.get(f"{SLEEPER_BASE}/league/{lid}")
            except RateLimited:
                result.stopped_reason = "rate_limited"
                result.errors.append(f"rate_limited:{lid}")
                result.leagues_pending = len(due) - idx
                break
            fetched_ms = tick()
            result.leagues_checked += 1
            if league is None:
                # An answer, not a failure: the league id no longer exists.
                result.not_found += 1
                _touch_check(conn, lid, checked_ms=fetched_ms, result=RESULT_NOT_FOUND, status=None)
                conn.commit()
                consecutive = 0
                continue
            if not isinstance(league, dict) or str(league.get("league_id") or lid) != lid:
                result.fetch_failures += 1
                result.errors.append(f"league_fetch_failed:{lid}")
                _touch_check(
                    conn,
                    lid,
                    checked_ms=fetched_ms,
                    result="fetch_failed",
                    status=None,
                    error="league_fetch_failed_or_absent",
                )
                conn.commit()
                consecutive += 1
                if consecutive >= MAX_CONSECUTIVE_FAILURES:
                    result.stopped_reason = "consecutive_fetch_failures"
                    result.leagues_pending = len(due) - idx - 1
                    break
                continue
            consecutive = 0
            outcome = record_capture(
                conn, league, captured_ms=fetched_ms, source=SOURCE_LEAGUE_ENDPOINT, league_id=lid
            )
            if outcome == "new":
                result.captures_new += 1
            elif outcome == "unchanged":
                result.captures_unchanged += 1
            elif outcome == "incomplete":
                result.incomplete_payloads += 1
            elif outcome == RESULT_NOT_DYNASTY:
                result.not_dynasty += 1
            conn.commit()
        conn.commit()
    finally:
        conn.close()
    result.calls_used = b.used
    log.info("sharp.league_format_capture: %s", result.to_dict())
    return result


def capture_coverage(*, ledger_path: Path | None = None) -> dict[str, Any]:
    """How much of the trade-bearing / sharp-eligible graph has a format
    capture — reported so "format unknown" and "not captured yet" never read
    the same."""
    conn = ledger.connect(ledger_path)
    try:
        ensure_schema(conn)
        conn.commit()
        targets = set(_target_league_ids(conn, ledger_path=ledger_path))
        with_trades = {
            str(r[0])
            for r in conn.execute(
                "SELECT DISTINCT league_id FROM asset_movements WHERE tx_type = 'trade'"
            ).fetchall()
            if r[0]
        }
        captured = _captured_league_ids(conn)
        capture_rows = int(
            conn.execute("SELECT COUNT(*) FROM sharp_league_format_captures").fetchone()[0]
        )
        by_source = {
            str(r[0]): int(r[1])
            for r in conn.execute(
                "SELECT capture_source, COUNT(*) FROM sharp_league_format_captures "
                "GROUP BY capture_source"
            ).fetchall()
        }
        oldest = conn.execute(
            "SELECT MIN(last_checked_ms) FROM sharp_league_format_checks"
        ).fetchone()
    finally:
        conn.close()
    return {
        "targetLeagues": len(targets),
        "targetLeaguesCaptured": len(targets & captured),
        "targetLeaguesUncaptured": len(targets - captured),
        "tradeBearingLeagues": len(with_trades),
        "tradeBearingLeaguesCaptured": len(with_trades & captured),
        "captureRows": capture_rows,
        "captureRowsBySource": by_source,
        "oldestCheckMs": int(oldest[0]) if oldest and oldest[0] is not None else None,
    }


# ── retention ─────────────────────────────────────────────────────────────

_PRUNE_CHUNK = 400


def prune_captures(
    conn: sqlite3.Connection,
    *,
    now_ms: int | None = None,
    retention_days: int | None = None,
) -> int:
    """Remove captures no retained trade and no live league needs.  Returns
    the number of capture rows removed; ``0`` on a ledger with no capture table
    (never creates it).

    A capture is removed only when ALL hold:

    1. ``captured_ms`` is older than the horizon (``retention_days``, default
       ``ledger.MOVEMENT_RETENTION_DAYS`` — the same horizon ``ledger.prune``
       drops movements at; this runs after it);
    2. it is not the capture :func:`capture_in_force` selects for any trade the
       ledger still holds in that league (the reader's exact rule: trade time
       ``created_ms`` falling back to the movement ``ts``, the league's
       season);
    3. it is superseded by a later capture of the same league-season, OR the
       league has not been checked inside the horizon.  The capture in force
       NOW for a league still being looked at is kept however old it is — an
       unchanged league inserts nothing, so its single row can be years old.

    Commits when it removes anything.
    """
    days = int(retention_days if retention_days is not None else ledger.MOVEMENT_RETENTION_DAYS)
    now = int(now_ms if now_ms is not None else time.time() * 1000)
    cutoff = now - days * 24 * 3600 * 1000
    try:
        league_ids = [
            str(r[0])
            for r in conn.execute(
                "SELECT DISTINCT league_id FROM sharp_league_format_captures WHERE captured_ms < ?",
                (cutoff,),
            ).fetchall()
        ]
    except sqlite3.OperationalError as exc:
        if "no such table" in str(exc).lower():
            return 0
        raise
    doomed: list[int] = []
    for start in range(0, len(league_ids), _PRUNE_CHUNK):
        chunk = league_ids[start : start + _PRUNE_CHUNK]
        ph = ",".join("?" for _ in chunk)
        caps: dict[str, list[dict[str, Any]]] = {}
        for r in conn.execute(
            "SELECT capture_id, league_id, season, captured_ms FROM sharp_league_format_captures "
            f"WHERE league_id IN ({ph})",
            chunk,
        ).fetchall():
            caps.setdefault(str(r[1]), []).append(
                {"captureId": int(r[0]), "season": r[2], "capturedMs": int(r[3])}
            )
        seasons = {
            str(r[0]): (str(r[1]) if r[1] else None)
            for r in conn.execute(
                f"SELECT league_id, season FROM leagues WHERE league_id IN ({ph})", chunk
            ).fetchall()
        }
        trades: dict[str, list[int | None]] = {}
        for r in conn.execute(
            "SELECT m.league_id, COALESCE(t.created_ms, MIN(m.ts)) "
            "FROM asset_movements m LEFT JOIN transactions t ON t.tx_id = m.tx_id "
            f"WHERE m.tx_type = 'trade' AND m.league_id IN ({ph}) "
            "GROUP BY m.league_id, m.tx_id",
            chunk,
        ).fetchall():
            trades.setdefault(str(r[0]), []).append(int(r[1]) if r[1] is not None else None)
        checked = {
            str(r[0]): int(r[1])
            for r in conn.execute(
                "SELECT league_id, last_checked_ms FROM sharp_league_format_checks "
                f"WHERE league_id IN ({ph})",
                chunk,
            ).fetchall()
        }
        for lid in chunk:
            league_caps = caps.get(lid) or []
            keep: set[int] = set()
            for trade_ms in trades.get(lid, ()):
                cap, _timing = capture_in_force(league_caps, trade_ms, season=seasons.get(lid))
                if cap is not None:
                    keep.add(int(cap["captureId"]))
            if checked.get(lid, -1) >= cutoff:
                latest: dict[Any, dict[str, Any]] = {}
                for c in league_caps:
                    cur = latest.get(c["season"])
                    if cur is None or (c["capturedMs"], c["captureId"]) > (
                        cur["capturedMs"],
                        cur["captureId"],
                    ):
                        latest[c["season"]] = c
                keep.update(int(c["captureId"]) for c in latest.values())
            doomed.extend(
                int(c["captureId"])
                for c in league_caps
                if c["capturedMs"] < cutoff and int(c["captureId"]) not in keep
            )
    for start in range(0, len(doomed), _PRUNE_CHUNK):
        chunk_ids = doomed[start : start + _PRUNE_CHUNK]
        conn.execute(
            "DELETE FROM sharp_league_format_captures WHERE capture_id IN ("
            + ",".join("?" for _ in chunk_ids)
            + ")",
            chunk_ids,
        )
    observations_removed = prune_observations(conn, cutoff_ms=cutoff)
    if doomed or observations_removed:
        conn.commit()
        log.info(
            "sharp.league_format_capture: pruned %d captures, %d observations",
            len(doomed),
            observations_removed,
        )
    return len(doomed)


def prune_observations(conn: sqlite3.Connection, *, cutoff_ms: int) -> int:
    """Retention + lossless compaction of the observation log.  Returns rows
    removed; never commits (``prune_captures`` does); ``0`` when the table is
    absent.

    1. Rows older than both the horizon and the earliest retained trade go: a
       confirmation is always at or after its trade.
    2. Compaction.  A RUN is the stretch from one capture of a league-season
       to the next.  For the bracket only the LATEST same-payload observation
       of a run matters (an observation in the run at or after a trade exists
       iff the latest one is at or after it), so the earlier same-payload rows
       of each run are dropped.  A row whose payload differs from its run's
       capture, or that precedes every capture, is always kept -- dropping it
       could only ever turn a ``changed`` verdict into a ``confirmed`` one.
    """
    try:
        conn.execute("SELECT 1 FROM sharp_league_format_observations LIMIT 1").fetchall()
    except sqlite3.OperationalError as exc:
        if "no such table" in str(exc).lower():
            return 0
        raise
    floor = int(cutoff_ms)
    try:
        row = conn.execute(
            "SELECT MIN(COALESCE(t.created_ms, m.ts)) FROM asset_movements m "
            "LEFT JOIN transactions t ON t.tx_id = m.tx_id WHERE m.tx_type = 'trade'"
        ).fetchone()
        if row is not None and row[0] is not None:
            floor = min(floor, int(row[0]))
    except sqlite3.OperationalError as exc:
        if "no such table" not in str(exc).lower():
            raise
    removed = conn.execute(
        "DELETE FROM sharp_league_format_observations WHERE observed_ms < ?", (floor,)
    ).rowcount
    league_ids = [
        str(r[0])
        for r in conn.execute(
            "SELECT league_id FROM sharp_league_format_observations "
            "GROUP BY league_id HAVING COUNT(*) > 1"
        ).fetchall()
    ]
    doomed: list[int] = []
    for start in range(0, len(league_ids), _PRUNE_CHUNK):
        chunk = league_ids[start : start + _PRUNE_CHUNK]
        ph = ",".join("?" for _ in chunk)
        caps: dict[tuple[str, Any], list[tuple[int, int, str]]] = {}
        for lid, season, ms, cid, sha in conn.execute(
            "SELECT league_id, season, captured_ms, capture_id, payload_sha256 "
            f"FROM sharp_league_format_captures WHERE league_id IN ({ph})",
            chunk,
        ).fetchall():
            caps.setdefault((str(lid), season), []).append((int(ms), int(cid), str(sha)))
        for runs in caps.values():
            runs.sort()
        latest: dict[tuple[str, Any, int], tuple[int, int]] = {}
        members: dict[tuple[str, Any, int], list[int]] = {}
        for oid, lid, season, ms, sha in conn.execute(
            "SELECT observation_id, league_id, season, observed_ms, payload_sha256 "
            f"FROM sharp_league_format_observations WHERE league_id IN ({ph})",
            chunk,
        ).fetchall():
            runs = caps.get((str(lid), season)) or []
            run = None
            for cap_ms, cap_id, cap_sha in runs:
                if cap_ms <= int(ms):
                    run = (cap_id, cap_sha)
                else:
                    break
            if run is None or run[1] != str(sha):
                continue
            key = (str(lid), season, run[0])
            members.setdefault(key, []).append(int(oid))
            cur = latest.get(key)
            if cur is None or (int(ms), int(oid)) > cur:
                latest[key] = (int(ms), int(oid))
        for key, ids in members.items():
            keep = latest[key][1]
            doomed.extend(i for i in ids if i != keep)
    for start in range(0, len(doomed), _PRUNE_CHUNK):
        chunk_ids = doomed[start : start + _PRUNE_CHUNK]
        conn.execute(
            "DELETE FROM sharp_league_format_observations WHERE observation_id IN ("
            + ",".join("?" for _ in chunk_ids)
            + ")",
            chunk_ids,
        )
    return int(removed) + len(doomed)
