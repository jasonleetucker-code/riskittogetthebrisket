"""The canonical as-of query contract — fidelity-labelled, never future.

This module is THE answer to "what did we actually know / store / serve
at or before time T?" for asset values, ranks and their provenance.  It
never answers the different question "what do we know today about the
past" — no code path here can select an observation dated after the
requested time, structurally: every SQL predicate is ``<=`` /
``<`` against the requested bound and there is no API that accepts an
undirected "nearest".

Fidelity vocabulary (the canonical labels from
``docs/C_SERIES_SCOPE_MANIFEST.md`` row `C1-HIST-01` and the replay
spec §6):

* ``exact`` — an observation exists on the requested UTC date.
* ``nearest-prior`` — the latest observation strictly before the
  requested date, with its distance stated.
* ``reconstructed`` — DEFINED but NOT PRODUCED by this layer.  No
  approved reconstruction methodology exists (re-deriving old values
  through today's Hill constants is exactly what the aging spec §6
  forbids), so nothing here mints the label.  It exists in the
  vocabulary so a future owner-approved reconstruction has a name that
  is not ``exact``.
* ``partial`` — a MULTI-asset result in which some assets resolved and
  some did not (batch queries stamp it on the summary, never on a
  single-asset result).
* ``unavailable`` — no observation at or before T, with an explicit
  machine-readable reason:
    - ``before_history_boundary`` — T precedes the permanent
      2026-07-14 coverage floor.  Nothing can ever change this answer.
    - ``no_prior_observation`` — T is inside the covered window but
      this asset has no observation at or before it.
    - ``outside_max_age`` — a prior observation exists but the caller
      declared a freshness budget and the observation is older.

Two temporal modes, because "at or before date D" and "known before
instant T" are different questions:

* :func:`value_as_of` — day granularity.  An observation dated D
  answers a query for D (``exact``) even though the scrape instant may
  have been later the same day; day-granular feeds cannot support a
  finer claim, and the result carries ``observedAt`` so a caller that
  cares can see the instant when it is known.
* :func:`value_known_before` — instant-strict.  Only observations
  provably at-or-before the instant qualify: rows with a known
  ``observed_at <= T``, or rows on a strictly earlier UTC date (a
  day-D-1 observation precedes every instant on day D).  Same-day rows
  with an unknown instant are EXCLUDED — conservatively missing rather
  than optimistically contemporaneous.  This is the mode historical
  trade replay (C3-U9) should consume for at-the-time grades.

Tie behavior, fully specified so replay is deterministic: within one
``observed_date`` the selection order is (1) known instant over unknown,
latest instant first; (2) origin priority (``store.ORIGIN_PRIORITY``);
(3) ``content_hash`` ascending as the final total-order tiebreak.
Corrections: an observation superseded via ``store.record_correction``
is skipped by selection (the superseding row stands on its own; the
original stays readable in the store).
"""

from __future__ import annotations

import sqlite3
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, Sequence

from src.history import store
from src.history.store import (
    HISTORY_FLOOR,
    LANE_CANONICAL,
    ObservationError,
    origin_rank,
)


def _connect_readonly(path: Path | None) -> sqlite3.Connection | None:
    """Open the ledger for a READ, or return ``None`` when it does not
    exist.  A query must never create the database file as a side
    effect — an empty ledger created by a read would make "no ledger"
    and "empty ledger" indistinguishable on disk."""
    target = path or store.DB_PATH
    if not Path(target).exists():
        return None
    return store.connect(target)


FIDELITY_EXACT = "exact"
FIDELITY_NEAREST_PRIOR = "nearest-prior"
FIDELITY_RECONSTRUCTED = "reconstructed"  # defined; never produced here
FIDELITY_PARTIAL = "partial"
FIDELITY_UNAVAILABLE = "unavailable"

REASON_BEFORE_BOUNDARY = "before_history_boundary"
REASON_NO_PRIOR = "no_prior_observation"
REASON_OUTSIDE_MAX_AGE = "outside_max_age"

_SELECT_COLS = (
    "id, asset_key, asset_class, lane, source_key, observed_date, observed_at, "
    "observed_at_zone, value, rank, tier, confidence, display_name, position, "
    "player_id, scope, pipeline_version, origin, recorded_at, content_hash"
)


def _unavailable(
    asset_key: str,
    lane: str,
    source_key: str,
    requested: str,
    reason: str,
) -> dict[str, Any]:
    return {
        "assetKey": asset_key,
        "lane": lane,
        "sourceKey": source_key,
        "requestedDate": requested,
        "fidelity": FIDELITY_UNAVAILABLE,
        "missingReason": reason,
        "historyFloor": HISTORY_FLOOR,
        "value": None,
        "rank": None,
        "observedDate": None,
    }


def _result_from_row(
    row: sqlite3.Row,
    requested: str,
) -> dict[str, Any]:
    observed = str(row["observed_date"])
    exact = observed == requested
    try:
        distance = (date.fromisoformat(requested) - date.fromisoformat(observed)).days
    except ValueError:
        distance = None
    return {
        "assetKey": row["asset_key"],
        "assetClass": row["asset_class"],
        "lane": row["lane"],
        "sourceKey": row["source_key"],
        "requestedDate": requested,
        "fidelity": FIDELITY_EXACT if exact else FIDELITY_NEAREST_PRIOR,
        "value": row["value"],
        "rank": row["rank"],
        "tier": row["tier"],
        "confidence": row["confidence"],
        "observedDate": observed,
        "observedAt": row["observed_at"],
        "distanceDays": distance,
        "historyFloor": HISTORY_FLOOR,
        "provenance": {
            "origin": row["origin"],
            "pipelineVersion": row["pipeline_version"],
            "recordedAt": row["recorded_at"],
            "contentHash": row["content_hash"],
            "displayName": row["display_name"],
            "playerId": row["player_id"],
        },
    }


def _select_best(rows: list[sqlite3.Row]) -> sqlite3.Row | None:
    """Deterministic pick among candidate rows (already date-bounded).

    Ordering: latest observed_date first; within a date, known instant
    over unknown (latest first), then origin priority, then
    content_hash — a total order, so replay cannot flap.
    """
    if not rows:
        return None

    def sort_key(r: sqlite3.Row):
        return (
            str(r["observed_date"]),
            (1, str(r["observed_at"])) if r["observed_at"] else (0, ""),
            # origin_rank sorts ascending-preferred; negate via tuple trick
        )

    # Python's sort is stable; do it in three passes, least significant
    # first, all ascending-normalized.
    ordered = sorted(rows, key=lambda r: str(r["content_hash"]))
    ordered = sorted(ordered, key=lambda r: origin_rank(str(r["origin"])))
    ordered = sorted(
        ordered,
        key=lambda r: (1, str(r["observed_at"])) if r["observed_at"] else (0, ""),
        reverse=True,
    )
    ordered = sorted(ordered, key=lambda r: str(r["observed_date"]), reverse=True)
    return ordered[0]


def _fetch_candidates(
    conn: sqlite3.Connection,
    asset_key: str,
    lane: str,
    source_key: str,
    *,
    date_max: str,
    strict_before_date: str | None = None,
    instant_max: str | None = None,
) -> list[sqlite3.Row]:
    """Date-bounded candidate rows, superseded observations excluded.

    ``date_max`` bounds ``observed_date <= date_max``.  When
    ``instant_max`` is set (instant-strict mode), rows on the boundary
    date qualify only with a known ``observed_at <= instant_max``;
    rows on strictly earlier dates always qualify.
    """
    q = (
        f"SELECT {_SELECT_COLS} FROM observations "
        "WHERE asset_key=? AND lane=? AND source_key=? AND observed_date<=? "
        "AND id NOT IN (SELECT superseded_id FROM corrections)"
    )
    params: list[Any] = [asset_key, lane, source_key, date_max]
    if strict_before_date is not None:
        q += " AND observed_date<?"
        params.append(strict_before_date)
    rows = conn.execute(q, params).fetchall()
    if instant_max is None:
        return rows
    boundary = date_max
    out = []
    for r in rows:
        if str(r["observed_date"]) < boundary:
            out.append(r)
        elif r["observed_at"] and str(r["observed_at"]) <= instant_max:
            out.append(r)
        # else: same-day with unknown/later instant — excluded (conservative)
    return out


def value_as_of(
    asset_key: str,
    on_date: date | datetime | str,
    *,
    lane: str = LANE_CANONICAL,
    source_key: str = "",
    max_age_days: int | None = None,
    path: Path | None = None,
) -> dict[str, Any]:
    """Day-granular as-of lookup.  Never selects a future observation."""
    requested = store.as_of_date(on_date)
    if requested < HISTORY_FLOOR:
        return _unavailable(asset_key, lane, source_key, requested, REASON_BEFORE_BOUNDARY)

    conn = _connect_readonly(path)
    if conn is None:
        return _unavailable(asset_key, lane, source_key, requested, REASON_NO_PRIOR)
    try:
        rows = _fetch_candidates(conn, asset_key, lane, source_key, date_max=requested)
    finally:
        conn.close()

    best = _select_best(rows)
    if best is None:
        return _unavailable(asset_key, lane, source_key, requested, REASON_NO_PRIOR)

    result = _result_from_row(best, requested)
    if (
        max_age_days is not None
        and result["distanceDays"] is not None
        and result["distanceDays"] > max_age_days
    ):
        out = _unavailable(asset_key, lane, source_key, requested, REASON_OUTSIDE_MAX_AGE)
        out["nearestPriorDate"] = result["observedDate"]
        out["nearestPriorDistanceDays"] = result["distanceDays"]
        return out
    return result


def value_known_before(
    asset_key: str,
    instant: datetime,
    *,
    lane: str = LANE_CANONICAL,
    source_key: str = "",
    max_age_days: int | None = None,
    path: Path | None = None,
) -> dict[str, Any]:
    """Instant-strict as-of lookup for at-the-time analyses (C3-U9).

    Only observations provably at-or-before ``instant`` qualify; a
    same-day observation whose scrape instant is unknown does NOT.
    ``instant`` must be timezone-aware (UTC semantics are the ledger's
    contract; a naive instant is refused rather than guessed).
    """
    if instant.tzinfo is None:
        raise ObservationError(
            "naive datetime passed to value_known_before; as-of instants must be UTC-aware"
        )
    utc = instant.astimezone(timezone.utc)
    requested = utc.date().isoformat()
    if requested < HISTORY_FLOOR:
        return _unavailable(asset_key, lane, source_key, requested, REASON_BEFORE_BOUNDARY)

    conn = _connect_readonly(path)
    if conn is None:
        out = _unavailable(asset_key, lane, source_key, requested, REASON_NO_PRIOR)
        out["requestedInstant"] = utc.isoformat()
        return out
    try:
        rows = _fetch_candidates(
            conn,
            asset_key,
            lane,
            source_key,
            date_max=requested,
            instant_max=utc.isoformat(),
        )
    finally:
        conn.close()

    best = _select_best(rows)
    if best is None:
        return _unavailable(asset_key, lane, source_key, requested, REASON_NO_PRIOR)
    result = _result_from_row(best, requested)
    result["requestedInstant"] = utc.isoformat()
    if (
        max_age_days is not None
        and result["distanceDays"] is not None
        and result["distanceDays"] > max_age_days
    ):
        out = _unavailable(asset_key, lane, source_key, requested, REASON_OUTSIDE_MAX_AGE)
        out["requestedInstant"] = utc.isoformat()
        out["nearestPriorDate"] = result["observedDate"]
        out["nearestPriorDistanceDays"] = result["distanceDays"]
        return out
    return result


def batch_as_of(
    asset_keys: Sequence[str],
    on_date: date | datetime | str,
    *,
    lane: str = LANE_CANONICAL,
    source_key: str = "",
    max_age_days: int | None = None,
    path: Path | None = None,
) -> dict[str, Any]:
    """As-of lookup for a package of assets (a trade's two sides, a
    roster).  Per-asset results plus an honest aggregate: the summary
    fidelity is ``exact`` only when every asset resolved exactly,
    ``partial`` when coverage is mixed, ``unavailable`` when nothing
    resolved.  Coverage arithmetic is by asset count; value-weighted
    coverage gates are consumer policy (aging spec §5), not ledger
    policy."""
    results: dict[str, dict[str, Any]] = {}
    for key in asset_keys:
        results[key] = value_as_of(
            key,
            on_date,
            lane=lane,
            source_key=source_key,
            max_age_days=max_age_days,
            path=path,
        )
    n = len(results)
    exact = sum(1 for r in results.values() if r["fidelity"] == FIDELITY_EXACT)
    prior = sum(1 for r in results.values() if r["fidelity"] == FIDELITY_NEAREST_PRIOR)
    missing = n - exact - prior
    if n == 0 or missing == n:
        agg = FIDELITY_UNAVAILABLE
    elif missing == 0 and prior == 0:
        agg = FIDELITY_EXACT
    elif missing == 0:
        agg = FIDELITY_NEAREST_PRIOR
    else:
        agg = FIDELITY_PARTIAL
    return {
        "requestedDate": store.as_of_date(on_date),
        "results": results,
        "summary": {
            "assets": n,
            "exact": exact,
            "nearestPrior": prior,
            "unavailable": missing,
            "coverage": (exact + prior) / n if n else 0.0,
            "fidelity": agg,
        },
    }


def series(
    asset_key: str,
    *,
    lane: str = LANE_CANONICAL,
    source_key: str = "",
    start: date | datetime | str | None = None,
    end: date | datetime | str | None = None,
    path: Path | None = None,
) -> dict[str, Any]:
    """Ordered per-date history for one asset.  Gaps are preserved —
    a missing date is data, never interpolated.  At most one point per
    date, chosen by the same deterministic tie rule as point lookups."""
    start_s = store.as_of_date(start) if start is not None else HISTORY_FLOOR
    end_s = store.as_of_date(end) if end is not None else None
    if start_s < HISTORY_FLOOR:
        start_s = HISTORY_FLOOR

    conn = _connect_readonly(path)
    if conn is None:
        return {
            "assetKey": asset_key,
            "lane": lane,
            "sourceKey": source_key,
            "historyFloor": HISTORY_FLOOR,
            "start": start_s,
            "end": end_s,
            "points": [],
        }
    try:
        q = (
            f"SELECT {_SELECT_COLS} FROM observations "
            "WHERE asset_key=? AND lane=? AND source_key=? AND observed_date>=? "
            "AND id NOT IN (SELECT superseded_id FROM corrections)"
        )
        params: list[Any] = [asset_key, lane, source_key, start_s]
        if end_s is not None:
            q += " AND observed_date<=?"
            params.append(end_s)
        rows = conn.execute(q, params).fetchall()
    finally:
        conn.close()

    by_date: dict[str, list[sqlite3.Row]] = {}
    for r in rows:
        by_date.setdefault(str(r["observed_date"]), []).append(r)

    points = []
    for d in sorted(by_date):
        best = _select_best(by_date[d])
        if best is not None:
            points.append(_result_from_row(best, d))
    return {
        "assetKey": asset_key,
        "lane": lane,
        "sourceKey": source_key,
        "historyFloor": HISTORY_FLOOR,
        "start": start_s,
        "end": end_s,
        "points": points,
    }


def previous_board_ranks(
    *,
    before_date: date | datetime | str,
    path: Path | None = None,
) -> dict[str, tuple[str, int]]:
    """``{asset_key: (observed_date, rank)}`` from the latest canonical
    board date STRICTLY BEFORE ``before_date``.

    This is the deterministic comparator ``rankChange`` derives from
    (C1-HIST-03): the horizon is a dated observation in the durable
    ledger, never the previous build's own output — so rebuilding the
    same board any number of times yields the same comparator, and a
    board dated D always diffs against the latest distinct date < D.

    Only rows with a rank participate (a rank delta needs two ranks);
    the selection among same-date duplicates follows the standard tie
    rule.  Returns ``{}`` when no prior board date exists — the caller
    stamps ``rankChange: None``, because "no historical comparator" is
    not ``0``.
    """
    boundary = store.as_of_date(before_date)
    conn = _connect_readonly(path)
    if conn is None:
        return {}
    try:
        prev_date_row = conn.execute(
            "SELECT MAX(observed_date) FROM observations WHERE lane=? AND observed_date<?",
            (LANE_CANONICAL, boundary),
        ).fetchone()
        prev_date = prev_date_row[0] if prev_date_row else None
        if not prev_date:
            return {}
        rows = conn.execute(
            f"SELECT {_SELECT_COLS} FROM observations "
            "WHERE lane=? AND observed_date=? AND rank IS NOT NULL "
            "AND id NOT IN (SELECT superseded_id FROM corrections)",
            (LANE_CANONICAL, prev_date),
        ).fetchall()
    finally:
        conn.close()

    by_key: dict[str, list[sqlite3.Row]] = {}
    for r in rows:
        by_key.setdefault(str(r["asset_key"]), []).append(r)
    out: dict[str, tuple[str, int]] = {}
    for key, candidates in by_key.items():
        best = _select_best(candidates)
        if best is not None and best["rank"] is not None:
            out[key] = (str(best["observed_date"]), int(best["rank"]))
    return out
