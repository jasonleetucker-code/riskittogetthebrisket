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
from bisect import bisect_right
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
    and "empty ledger" indistinguishable on disk — and it must not
    write AT ALL, so this opens SQLite in true read-only mode rather
    than routing through the schema-ensuring write connector."""
    target = Path(path or store.DB_PATH)
    if not target.exists():
        return None
    conn = sqlite3.connect(f"file:{target}?mode=ro", uri=True, timeout=10.0)
    conn.row_factory = sqlite3.Row
    return conn


def _instant_at_or_before(observed_at: Any, instant_utc: datetime) -> bool:
    """True only when ``observed_at`` is a PROVEN instant at or before
    ``instant_utc``.

    Proven means the stamp carries an explicit time component
    (``store.has_time_component`` — a date-only string parses as
    midnight and would promote an unknown scrape time to "provably
    before every moment of its day", the leak the final review
    reproduced).  Comparison is on PARSED datetimes, never
    lexicographic text (a zone-qualified stamp with a negative UTC
    offset would defeat a string compare): zone-aware stamps convert
    to UTC.

    Naive stamps are compared under a naive-means-UTC assumption.  As of
    audit F-28 that applies to LEGACY rows only — ``scrapeTimestamp`` is
    now tz-aware UTC at the source, so rows recorded after it carry their
    zone explicitly (``observed_at_zone``).  For the legacy rows the
    assumption is known to be wrong by two hours where the producer was
    the production VPS, and it is kept rather than tightened because
    refusing every naive stamp would make the entire pre-F-28 ledger
    unreadable to as-of queries.  The zone column records which rows are
    affected.
    """
    s = str(observed_at or "").strip()
    if not store.has_time_component(s):
        return False
    try:
        parsed = datetime.fromisoformat(s)
    except ValueError:
        return False
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed <= instant_utc


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
    return _selection_order(rows)[0]


def _selection_order(rows: list[sqlite3.Row]) -> list[sqlite3.Row]:
    """``rows`` in :func:`_select_best`'s preference order, best first.

    Python's sort is stable; do it in passes, least significant first,
    all ascending-normalized.  Because every pass is stable, the order
    this imposes on any SUBSET of ``rows`` is exactly the order sorting
    that subset alone would produce (input order breaks full ties in
    both) — the property :class:`_KnownBeforeIndex` rests on.
    """
    ordered = sorted(rows, key=lambda r: str(r["content_hash"]))
    ordered = sorted(ordered, key=lambda r: origin_rank(str(r["origin"])))
    ordered = sorted(
        ordered,
        key=lambda r: (1, str(r["observed_at"])) if r["observed_at"] else (0, ""),
        reverse=True,
    )
    return sorted(ordered, key=lambda r: str(r["observed_date"]), reverse=True)


class _KnownBeforeIndex:
    """One asset's candidate rows, indexed so each instant-strict request
    is answered without re-filtering and re-sorting the whole history.

    :func:`_select_best` ranks ``observed_date`` first, so the best
    admissible row lives in the LATEST date that has one: ``requested``'s
    own day when one of its rows carries a PROVEN instant at or before the
    request, otherwise the latest earlier day (every row of an earlier day
    is admissible).  Rows are grouped by date in their fetch order and a
    group is put in :func:`_selection_order` only when a request reaches
    it; by the subset property that equals the group's order inside the
    full sort, so the first admissible row of the first admissible group
    IS ``_select_best`` of the per-request filter.  Pinned against the
    retired per-request form by
    ``tests/history/test_batch_known_before_selection_equivalence.py``.
    """

    __slots__ = ("_by_date", "_dates", "_ordered")

    def __init__(self, rows: list[sqlite3.Row]) -> None:
        self._by_date: dict[str, list[sqlite3.Row]] = {}
        for r in rows:
            self._by_date.setdefault(str(r["observed_date"]), []).append(r)
        self._dates = sorted(self._by_date)
        self._ordered: dict[str, list[sqlite3.Row]] = {}

    def _group(self, day: str) -> list[sqlite3.Row]:
        group = self._ordered.get(day)
        if group is None:
            group = _selection_order(self._by_date[day])
            self._ordered[day] = group
        return group

    def best(self, requested: str, utc: datetime) -> sqlite3.Row | None:
        j = bisect_right(self._dates, requested)
        if j and self._dates[j - 1] == requested:
            for r in self._group(requested):
                if _instant_at_or_before(r["observed_at"], utc):
                    return r
            j -= 1
        if j:
            return self._group(self._dates[j - 1])[0]
        return None


def _fetch_candidates(
    conn: sqlite3.Connection,
    asset_key: str,
    lane: str,
    source_key: str,
    *,
    date_max: str,
    strict_before_date: str | None = None,
    instant_max: datetime | None = None,
) -> list[sqlite3.Row]:
    """Date-bounded candidate rows, superseded observations excluded.

    ``date_max`` bounds ``observed_date <= date_max``.  When
    ``instant_max`` is set (instant-strict mode), rows on the boundary
    date qualify only with a PROVEN ``observed_at`` at or before it
    (:func:`_instant_at_or_before` — a date-only or unparseable stamp
    is an unknown instant and never qualifies); rows on strictly
    earlier dates always qualify.
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
        elif _instant_at_or_before(r["observed_at"], instant_max):
            out.append(r)
        # else: same-day with unknown/unproven/later instant — excluded
        # (conservative)
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
            instant_max=utc,
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


def batch_known_before(
    requests: Sequence[tuple[str, datetime]],
    *,
    lane: str = LANE_CANONICAL,
    source_key: str = "",
    max_age_days: int | None = None,
    path: Path | None = None,
) -> dict[str, Any]:
    """Instant-strict as-of lookup for a batch of ``(asset_key, instant)``
    pairs — the batched sibling of :func:`value_known_before`.

    Unlike :func:`batch_as_of` (day-granular, one shared date for every
    asset), each request here carries its OWN instant — the natural shape
    for historical trade replay, where the same player recurs across many
    trades each with its own timestamp.  ``value_known_before`` per request
    would reopen the ledger and re-query per item; this groups requests by
    distinct ``asset_key`` and issues exactly one SQL fetch per distinct
    key (bounded by the furthest-future instant requested for that key),
    then re-applies the same instant-strict selection
    (:func:`_instant_at_or_before`, :func:`_select_best`) to each request's
    own instant against the shared candidate set in memory.  A key that
    recurs across many requests costs one round trip, not N.

    Every ``instant`` must be timezone-aware; this is validated for the
    WHOLE batch before any connection is opened, matching
    :func:`value_known_before`'s contract.

    Results are returned in request order (positionally aligned to
    ``requests``, not deduplicated — the same ``(asset_key, instant)`` pair
    may legitimately repeat and each occurrence gets its own result), each
    shaped identically to a single :func:`value_known_before` call.
    ``max_age_days`` has no default freshness budget (``None``): staleness
    is a live-serving concept, and historical replay has no owner-approved
    notion of "too old" to invent one.
    """
    normalized: list[tuple[str, datetime]] = []
    for asset_key, instant in requests:
        if instant.tzinfo is None:
            raise ObservationError(
                "naive datetime passed to batch_known_before; as-of instants must be UTC-aware"
            )
        normalized.append((asset_key, instant.astimezone(timezone.utc)))

    results: list[dict[str, Any] | None] = [None] * len(normalized)

    by_key: dict[str, list[int]] = {}
    for i, (asset_key, _utc) in enumerate(normalized):
        by_key.setdefault(asset_key, []).append(i)

    conn = _connect_readonly(path)
    try:
        for asset_key, idxs in by_key.items():
            eligible_idxs: list[int] = []
            for i in idxs:
                utc = normalized[i][1]
                requested = utc.date().isoformat()
                if requested < HISTORY_FLOOR:
                    out = _unavailable(
                        asset_key, lane, source_key, requested, REASON_BEFORE_BOUNDARY
                    )
                    out["requestedInstant"] = utc.isoformat()
                    results[i] = out
                else:
                    eligible_idxs.append(i)
            if not eligible_idxs:
                continue

            if conn is None:
                for i in eligible_idxs:
                    utc = normalized[i][1]
                    requested = utc.date().isoformat()
                    out = _unavailable(asset_key, lane, source_key, requested, REASON_NO_PRIOR)
                    out["requestedInstant"] = utc.isoformat()
                    results[i] = out
                continue

            max_date = max(normalized[i][1].date().isoformat() for i in eligible_idxs)
            rows = _fetch_candidates(conn, asset_key, lane, source_key, date_max=max_date)
            # Indexed ONCE per key, not filtered + re-sorted (four passes
            # over the whole history) once per request.  Same selection.
            index = _KnownBeforeIndex(rows)

            for i in eligible_idxs:
                utc = normalized[i][1]
                requested = utc.date().isoformat()
                best = index.best(requested, utc)
                if best is None:
                    out = _unavailable(asset_key, lane, source_key, requested, REASON_NO_PRIOR)
                    out["requestedInstant"] = utc.isoformat()
                    results[i] = out
                    continue
                result = _result_from_row(best, requested)
                result["requestedInstant"] = utc.isoformat()
                if (
                    max_age_days is not None
                    and result["distanceDays"] is not None
                    and result["distanceDays"] > max_age_days
                ):
                    out = _unavailable(
                        asset_key, lane, source_key, requested, REASON_OUTSIDE_MAX_AGE
                    )
                    out["requestedInstant"] = utc.isoformat()
                    out["nearestPriorDate"] = result["observedDate"]
                    out["nearestPriorDistanceDays"] = result["distanceDays"]
                    results[i] = out
                else:
                    results[i] = result
    finally:
        if conn is not None:
            conn.close()

    n = len(results)
    exact = sum(1 for r in results if r is not None and r["fidelity"] == FIDELITY_EXACT)
    prior = sum(1 for r in results if r is not None and r["fidelity"] == FIDELITY_NEAREST_PRIOR)
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
        "results": results,
        "summary": {
            "items": n,
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


GENERATION_MATCH_INSTANT = "instant"
GENERATION_MATCH_DATE = "date"


def parse_instant_utc(stamp: Any) -> datetime | None:
    """A PROVEN instant as UTC (naive = UTC, the ledger's legacy rule —
    see :func:`_instant_at_or_before`), else ``None``."""
    s = str(stamp or "").strip()
    if not store.has_time_component(s):
        return None
    try:
        parsed = datetime.fromisoformat(s[:-1] + "+00:00" if s.endswith("Z") else s)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def value_at_generation(
    asset_key: str,
    *,
    observed_date: str,
    observed_at: Any,
    lane: str,
    source_key: str = "",
    allow_date_fallback: bool = True,
    path: Path | None = None,
) -> dict[str, Any]:
    """The observation recorded IN one board generation — not merely on its
    date.

    A generation is one recorded scrape: ``(observed_date, observed_at)``.
    Production records every scrape, so several generations share a date,
    and a row from an EARLIER scrape that day is not evidence about a later
    one (a source that failed at 22:00 is absent from the 22:00 generation
    even though it answered at 08:00).  So:

    * the generation carries a proven instant → a row matching that instant
      exactly is ``present`` with ``match: "instant"``; failing that, rows on
      the date with NO instant (legacy / backfill records, whose scrape is
      unknown) answer at ``match: "date"`` — labelled, never passed off as
      instant-exact; rows at a different proven instant never qualify;
    * the generation has no instant → the best row on the date (standard tie
      rule) at ``match: "date"``.

    ``allow_date_fallback=False`` restricts a generation WITH an instant to
    the exact-instant match (the date fallback is for generations whose
    scrape time was never recorded, not a substitute for a recorded one).

    A present answer carries the full point-lookup shape
    (:func:`_result_from_row` — value, rank, tier, confidence, provenance)
    plus ``present`` / ``match``.  ``{"present": False, "match": None}``
    when nothing qualifies.  Read-only; superseded observations are skipped.
    """
    absent: dict[str, Any] = {"present": False, "match": None, "value": None}
    conn = _connect_readonly(path)
    if conn is None:
        return absent
    try:
        rows = conn.execute(
            f"SELECT {_SELECT_COLS} FROM observations "
            "WHERE asset_key=? AND lane=? AND source_key=? AND observed_date=? "
            "AND id NOT IN (SELECT superseded_id FROM corrections)",
            (asset_key, lane, source_key, observed_date),
        ).fetchall()
    finally:
        conn.close()
    if not rows:
        return absent

    gen_instant = parse_instant_utc(observed_at)
    match = GENERATION_MATCH_DATE
    if gen_instant is not None:
        exact = [r for r in rows if parse_instant_utc(r["observed_at"]) == gen_instant]
        if exact:
            rows, match = exact, GENERATION_MATCH_INSTANT
        elif not allow_date_fallback:
            return absent
        else:
            rows = [r for r in rows if parse_instant_utc(r["observed_at"]) is None]
    best = _select_best(rows)
    if best is None:
        return absent
    return {**_result_from_row(best, observed_date), "present": True, "match": match}


def generation_has_instant_rows(
    asset_key: str,
    *,
    observed_date: str,
    observed_at: Any,
    lane: str,
    path: Path | None = None,
) -> bool:
    """Did this generation (``observed_date`` + a proven ``observed_at``)
    record ANY row in ``lane`` for the asset, under any source key?

    When it did, that scrape stamped its rows with its instant, so an
    instant-less row on the same date is NOT this generation's record and
    must not stand in for one by date.  ``False`` for a generation with no
    proven instant, or no ledger.
    """
    gen_instant = parse_instant_utc(observed_at)
    if gen_instant is None:
        return False
    conn = _connect_readonly(path)
    if conn is None:
        return False
    try:
        rows = conn.execute(
            "SELECT observed_at FROM observations "
            "WHERE asset_key=? AND lane=? AND observed_date=? AND observed_at IS NOT NULL "
            "AND id NOT IN (SELECT superseded_id FROM corrections)",
            (asset_key, lane, observed_date),
        ).fetchall()
    finally:
        conn.close()
    return any(parse_instant_utc(r["observed_at"]) == gen_instant for r in rows)


def _previous_board_date(conn: sqlite3.Connection, before_date: Any) -> str | None:
    """The latest canonical board date STRICTLY BEFORE ``before_date`` —
    the one comparator rule :func:`previous_board_ranks` (``rankChange``)
    and :func:`previous_board_date` (value-movement attribution) share."""
    boundary = store.as_of_date(before_date)
    row = conn.execute(
        "SELECT MAX(observed_date) FROM observations WHERE lane=? AND observed_date<?",
        (LANE_CANONICAL, boundary),
    ).fetchone()
    return str(row[0]) if row and row[0] else None


def previous_board_date(
    *,
    before_date: date | datetime | str,
    path: Path | None = None,
) -> str | None:
    """The comparator board generation for ``before_date``: the latest
    canonical board date strictly before it, or ``None`` when no earlier
    generation exists (or no ledger does) — "no comparator", never a
    guessed date.  Same rule ``rankChange`` derives from."""
    boundary = store.as_of_date(before_date)
    conn = _connect_readonly(path)
    if conn is None:
        return None
    try:
        return _previous_board_date(conn, boundary)
    finally:
        conn.close()


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
        prev_date = _previous_board_date(conn, boundary)
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


def source_lane_coverage(path: Path | None = None) -> dict[str, Any]:
    """Read-only observation depth of the ``source_value`` lane, per source key.

    Answers "how many point-in-time days does the ledger hold for this
    vendor's own numbers, and since when" without creating the database
    (``_connect_readonly``).  A missing ledger answers ``exists: False`` with a
    reason -- never zero observations, which would read as "recorded nothing"
    rather than "nothing to read".  Corrected rows still count: this is a depth
    census, not an as-of read.
    """
    conn = _connect_readonly(path)
    if conn is None:
        return {
            "exists": False,
            "historyFloor": HISTORY_FLOOR,
            "reason": "no temporal ledger at this path; nothing can be read",
            "sources": {},
        }
    try:
        rows = conn.execute(
            "SELECT source_key, COUNT(*) AS n, COUNT(DISTINCT observed_date) AS days, "
            "MIN(observed_date) AS first, MAX(observed_date) AS last "
            "FROM observations WHERE lane = ? GROUP BY source_key",
            (store.LANE_SOURCE,),
        ).fetchall()
    finally:
        conn.close()
    return {
        "exists": True,
        "historyFloor": HISTORY_FLOOR,
        "sources": {
            str(r["source_key"]): {
                "observations": int(r["n"]),
                "distinctDates": int(r["days"]),
                "firstDate": r["first"],
                "lastDate": r["last"],
            }
            for r in rows
        },
    }
