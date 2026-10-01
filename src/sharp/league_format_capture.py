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
#: Consecutive fetch failures that stop a pass: a run of ``None`` is far more
#: likely Sleeper refusing us (rate limit, outage) than a run of deleted
#: leagues, and spending the rest of the budget on it would only make it worse.
MAX_CONSECUTIVE_FAILURES = 10

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

CREATE TABLE IF NOT EXISTS sharp_league_format_checks (
  league_id        TEXT PRIMARY KEY,
  last_checked_ms  INTEGER NOT NULL,
  last_result      TEXT,
  last_status      TEXT,
  last_error       TEXT
);
CREATE INDEX IF NOT EXISTS idx_slfk_checked ON sharp_league_format_checks(last_checked_ms);
"""

#: The only tables this module writes.  Pinned by a structural test.
WRITE_TABLES = ("sharp_league_format_captures", "sharp_league_format_checks")


def ensure_schema(conn: sqlite3.Connection) -> None:
    """Additive ``CREATE TABLE IF NOT EXISTS`` — deliberately NOT wired to
    ``ledger.SCHEMA_VERSION``: a version bump runs ``_migrate`` and its table
    clears on every deployed ledger, to add two tables nothing else reads.
    (Same posture as ``roster_store.ensure_roster_schema``.)"""
    conn.executescript(_SCHEMA)


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
    statement — nothing recorded) or ``"no_league_id"``.

    Never commits: the caller owns its transaction, so a crawl keeps its own
    commit cadence.  The schema must already exist (:func:`ensure_schema`).
    """
    lid = str(league_id or league.get("league_id") or "").strip()
    if not lid:
        return "no_league_id"
    status_raw = league.get("status")
    status = str(status_raw).strip() if status_raw else None
    payload = capture_payload(league)
    if payload is None:
        _touch_check(conn, lid, checked_ms=captured_ms, result="incomplete", status=status)
        return "incomplete"
    season = _season(league)
    sha = payload_sha256(payload)
    prior = conn.execute(
        """
        SELECT payload_sha256 FROM sharp_league_format_captures
         WHERE league_id = ? AND season IS ? AND captured_ms <= ?
         ORDER BY captured_ms DESC, capture_id DESC LIMIT 1
        """,
        (lid, season, int(captured_ms)),
    ).fetchone()
    if prior is not None and str(prior[0]) == sha:
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


def legacy_settings_capture(league_id: str, settings: Mapping[str, Any]) -> dict[str, Any] | None:
    """A pre-capture-table ``settings_json.marketFormat`` snapshot (written by
    discovery between #1586 and this change) as a dated candidate, so it obeys
    the same timing rule as every other capture.  ``None`` if absent/undated."""
    mf = settings.get("marketFormat") if isinstance(settings, Mapping) else None
    if not isinstance(mf, Mapping) or not mf.get("roster_positions"):
        return None
    ms = _parse_iso_ms(mf.get("capturedAt"))
    if ms is None:
        return None
    payload = {k: v for k, v in mf.items() if k != "capturedAt"}
    season = str(mf.get("season")).strip() if mf.get("season") is not None else None
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
    """
    cands = [
        c
        for c in (captures or ())
        if not (season and c.get("season") and str(c.get("season")) != str(season))
    ]
    if not cands:
        return None, None
    cands = sorted(cands, key=lambda c: (int(c["capturedMs"]), c.get("captureId") or 0))
    if at_ms is None:
        return cands[0], TIMING_TRADE_TIME_UNKNOWN
    prior = [c for c in cands if int(c["capturedMs"]) <= int(at_ms)]
    if prior:
        return prior[-1], TIMING_AT_OR_BEFORE
    return cands[0], TIMING_POST_TRADE


def evidence_dict(capture: Mapping[str, Any] | None, timing: str | None) -> dict[str, Any]:
    """The inspectable ``formatEvidence`` an observation carries."""
    if capture is None:
        return {"timing": None, "reason": "no_league_format_capture"}
    return {
        "timing": timing,
        "exactAtTradeTime": timing == TIMING_AT_OR_BEFORE,
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
            "fetchFailures": self.fetch_failures,
            "leaguesPending": self.leagues_pending,
            "callsUsed": self.calls_used,
            "budgetExhausted": self.budget_exhausted,
            "stoppedReason": self.stopped_reason,
            "errors": self.errors[:20],
        }


def _default_http_get(url: str) -> Any:
    # Same client the records and roster crawls use: a paced batch job must
    # not ride the user-request circuit breaker (see ``records.py``).
    from src.public_league import sleeper_client  # noqa: PLC0415

    return sleeper_client._request_json(url)


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


def _check_state(conn: sqlite3.Connection) -> dict[str, tuple[int, str | None]]:
    return {
        str(r[0]): (int(r[1]), r[2])
        for r in conn.execute(
            "SELECT league_id, last_checked_ms, last_status FROM sharp_league_format_checks"
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
    checks: Mapping[str, tuple[int, str | None]],
    captured: set[str],
    now_ms: int,
    refresh_after_hours: float,
) -> list[str]:
    """Which leagues a pass should look at, in fair order.

    Never-captured leagues are always due.  A captured league is due once its
    last check is older than ``refresh_after_hours`` — unless its last observed
    status is ``complete`` (frozen season).  Ordering is the shared
    ``record_queue.prioritize_league_ids``: never-checked first, then the
    oldest check, ties by id.
    """
    from src.sharp import record_queue  # noqa: PLC0415

    cutoff = now_ms - int(refresh_after_hours * 3600 * 1000)
    due: list[str] = []
    for lid in league_ids:
        state = checks.get(lid)
        if lid not in captured:
            due.append(lid)
            continue
        if state is None:
            due.append(lid)
            continue
        last_ms, status = state
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
    :data:`MAX_CONSECUTIVE_FAILURES` in a row.  Commits per league, so the
    SQLite writer lock is never held across network I/O.
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
            league = b.get(f"{SLEEPER_BASE}/league/{lid}")
            fetched_ms = tick()
            result.leagues_checked += 1
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
