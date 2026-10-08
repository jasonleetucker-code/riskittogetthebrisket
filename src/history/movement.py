"""Two-generation value-movement attribution — a READ over the temporal ledger.

Answers "why did this asset's value move between two board generations?" with
the CONTRIBUTING EVIDENCE the ledger actually stores, never an asserted cause
(owner learning-loop item IC-7; ``docs/ui/CALCULATOR_UI_IMPLEMENTATION_CONTRACT.md``
§10).  It is a consumer of :mod:`src.history.asof` — every lookup goes through
the canonical as-of contract, so the never-future rule, the permanent
``before_history_boundary`` floor, the deterministic tie rule and the fidelity
labels are inherited rather than reimplemented.

What one answer contains:

* **Generations.**  A generation is ONE recorded scrape — production records
  every scrape, so several generations share a date.  The CURRENT end is the
  asset's latest ``canonical_board`` observation known at or before the
  SERVED scrape instant (instant-strict, :func:`asof.value_known_before`;
  day-granular :func:`asof.value_as_of` only when the served board carries no
  instant, labelled ``currentSelection``).  The COMPARATOR is the latest
  canonical board date strictly before the current end's date
  (:func:`asof.previous_board_date`, the rule ``rankChange`` uses), and the
  previous end is the latest scrape on it.  ``rankChangeAlignment`` says
  whether this diffs the same two boards the published ``rankChange`` does,
  and if not, why (ledger behind the served board; asset absent from the
  comparator board, so the previous end fell back to an older observation).
* **Canonical change.**  Value / rank / tier / confidence at both ends, with
  each end's own observed date, instant and fidelity.  A missing end makes the
  change ``None`` — "no comparator" is not ``0``.
* **Per-source deltas** from the ``source_value`` lane (vendor-published
  numbers only — what :mod:`src.history.record` admits).  A source counts as
  PRESENT at a generation only when it was recorded IN that generation — the
  canonical end's own scrape instant (:func:`asof.value_at_generation`;
  ``record.observations_from_contract`` stamps both lanes with the same
  ``scrapeTimestamp``).  Instant-less legacy / backfill rows match by date and
  are labelled ``generationMatch: "date"``.  An earlier scrape the same day is
  not presence: a source that failed at 22:00 is ``disappeared`` from the 22:00
  generation however it answered at 08:00.  A source present at one end only
  is ``appeared`` / ``disappeared`` with ``delta: None`` — absent is never a
  zero delta.
* **Methodology evidence** — ``pipelineVersion`` at both ends (contract shape
  + Hill-curve content hash).  A change there is evidence the valuation
  constants moved between the generations; it covers ONLY what that version
  hashes.
* **Explicitly unobserved** quantities.  The ledger stores no per-generation
  source weights, freshness factors, vote/exclusion state, quarantine or
  anomaly flags, and no values for rank-signal sources.  Those are named as
  unobserved — never recomputed with today's configuration and presented as
  historical.

**Non-additive, always.**  Per-source deltas do not sum to the value change:
rank-signal sources pass through percentile → Hill, the blend is a trimmed
weighted mean-median, single-source rows take a haircut, and IDP / picks
shrink toward an anchor.  No decomposition is published, and every answer
says so.
"""

from __future__ import annotations

from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, Iterable

from src.history import asof, store
from src.history.record import LEDGER_SOURCE_KEYS

MOVEMENT_SCHEMA = "value-movement/v1"

STATUS_OK = "ok"
STATUS_NO_CURRENT = "no_current_generation"
STATUS_NO_COMPARATOR = "no_comparator"

REASON_NO_PRIOR_BOARD = "no_prior_board_generation"

SELECTION_SERVED_GENERATION = "served_generation_exact"
SELECTION_KNOWN_BEFORE_INSTANT = "known_before_served_instant"
SELECTION_AS_OF_DATE = "as_of_date"

ALIGN_LEDGER_BEHIND_SERVED_BOARD = "ledger_behind_served_board"
ALIGN_ABSENT_FROM_COMPARATOR_BOARD = "asset_absent_from_comparator_board"

SOURCE_MOVED = "moved"
SOURCE_UNCHANGED = "unchanged"
SOURCE_APPEARED = "appeared"
SOURCE_DISAPPEARED = "disappeared"

NON_ADDITIVE_NOTE = (
    "Per-source deltas do not sum to the value change and must not be read as "
    "shares of it: rank-signal sources pass through percentile and the Hill "
    "curve, the blend is a trimmed weighted mean-median, single-source rows "
    "take a haircut, and IDP and pick values shrink toward an anchor. This is "
    "the evidence that moved, not a decomposition of the move."
)

# What the ledger does NOT store per generation.  Named so a reader can tell
# "unchanged" from "never recorded"; nothing here is recomputed from today's
# configuration (that would present current settings as history).
UNOBSERVED: tuple[dict[str, str], ...] = (
    {
        "quantity": "sourceWeights",
        "reason": "the temporal ledger stores no per-generation base or effective source weights",
    },
    {
        "quantity": "sourceFreshness",
        "reason": "the temporal ledger stores no per-generation freshness factors or source clocks",
    },
    {
        "quantity": "voteState",
        "reason": (
            "the temporal ledger stores no per-generation vote / exclusion state "
            "(Hampel, family cap, stale exclusion)"
        ),
    },
    {
        "quantity": "anomalyFlags",
        "reason": "the temporal ledger stores no per-generation quarantine or anomaly flags",
    },
    {
        "quantity": "rankSignalSourceValues",
        "reason": (
            "the temporal ledger's source_value lane records vendor-published values "
            "for value-direct and native sources only; rank-signal sources have no "
            "per-generation record"
        ),
    },
)


def _today_utc() -> str:
    return datetime.now(timezone.utc).date().isoformat()


def _end(result: dict[str, Any]) -> dict[str, Any]:
    """One generation's canonical observation, trimmed to what is shown."""
    prov = result.get("provenance") or {}
    return {
        "observedDate": result.get("observedDate"),
        "observedAt": result.get("observedAt"),
        "fidelity": result.get("fidelity"),
        "missingReason": result.get("missingReason"),
        "value": result.get("value"),
        "rank": result.get("rank"),
        "tier": result.get("tier"),
        "confidence": result.get("confidence"),
        "pipelineVersion": prov.get("pipelineVersion"),
        "origin": prov.get("origin"),
    }


def _diff(a: Any, b: Any) -> float | None:
    if isinstance(a, bool) or isinstance(b, bool):
        return None
    if isinstance(a, (int, float)) and isinstance(b, (int, float)):
        return float(b) - float(a)
    return None


def _changed(a: Any, b: Any) -> bool | None:
    """``None`` when either end is unrecorded — unknown is not "unchanged"."""
    if a is None or b is None:
        return None
    return a != b


def _source_at(
    asset_key: str,
    source_key: str,
    end: dict[str, Any],
    path: Path | None,
    *,
    allow_date_fallback: bool = True,
) -> dict[str, Any]:
    """A source's recorded value IN one generation (the canonical end's own
    scrape), via :func:`asof.value_at_generation`.

    Present only when recorded in that generation: the same scrape instant as
    the canonical end (``generationMatch: "instant"``), or — for instant-less
    legacy / backfill rows — the same date, labelled ``"date"``.  A row from an
    earlier scrape that day, or an earlier day, is reported as ``lastObserved*``
    context, never as a value at this generation.
    """
    gen = asof.value_at_generation(
        asset_key,
        observed_date=str(end["observedDate"]),
        observed_at=end.get("observedAt"),
        lane=store.LANE_SOURCE,
        source_key=source_key,
        allow_date_fallback=allow_date_fallback,
        path=path,
    )
    if gen["present"] and gen.get("value") is not None:
        return {
            "present": True,
            "value": gen["value"],
            "observedDate": gen["observedDate"],
            "observedAt": gen["observedAt"],
            "generationMatch": gen["match"],
        }
    instant = asof.parse_instant_utc(end.get("observedAt"))
    if instant is not None:
        last = asof.value_known_before(
            asset_key, instant, lane=store.LANE_SOURCE, source_key=source_key, path=path
        )
    else:
        last = asof.value_as_of(
            asset_key,
            str(end["observedDate"]),
            lane=store.LANE_SOURCE,
            source_key=source_key,
            path=path,
        )
    seen = last.get("fidelity") in (asof.FIDELITY_EXACT, asof.FIDELITY_NEAREST_PRIOR)
    return {
        "present": False,
        "value": None,
        "lastObservedDate": last.get("observedDate") if seen else None,
        "lastObservedAt": last.get("observedAt") if seen else None,
    }


def _source_rows(
    asset_key: str,
    previous: dict[str, Any],
    current: dict[str, Any],
    source_keys: Iterable[str],
    path: Path | None,
) -> tuple[list[dict[str, Any]], list[str]]:
    rows: list[dict[str, Any]] = []
    neither: list[str] = []

    # A date-granular source match is admissible only when the end's own
    # scrape recorded no instant-stamped source rows for this asset: if it
    # did, that scrape's evidence is instant-tracked, and an instant-less
    # row the same day is some other record, not this generation's.
    def _date_ok(end: dict[str, Any]) -> bool:
        return not asof.generation_has_instant_rows(
            asset_key,
            observed_date=str(end["observedDate"]),
            observed_at=end.get("observedAt"),
            lane=store.LANE_SOURCE,
            path=path,
        )

    prev_date_ok, cur_date_ok = _date_ok(previous), _date_ok(current)
    for skey in source_keys:
        prev = _source_at(asset_key, skey, previous, path, allow_date_fallback=prev_date_ok)
        cur = _source_at(asset_key, skey, current, path, allow_date_fallback=cur_date_ok)
        if not prev["present"] and not cur["present"]:
            neither.append(skey)
            continue
        if prev["present"] and cur["present"]:
            delta = _diff(prev["value"], cur["value"])
            status = SOURCE_UNCHANGED if delta == 0 else SOURCE_MOVED
        elif cur["present"]:
            delta, status = None, SOURCE_APPEARED
        else:
            delta, status = None, SOURCE_DISAPPEARED
        rows.append(
            {
                "source": skey,
                "status": status,
                "previous": prev,
                "current": cur,
                "delta": delta,
            }
        )
    return rows, neither


def _same_generation(
    end: dict[str, Any], served_date: str, served_instant: datetime | None
) -> tuple[bool, str]:
    """Is the ledger's current end the generation being served?  Compared on
    the scrape instant when both sides carry one, else on the date — and the
    basis is returned so a date-only answer is never read as instant-exact."""
    end_instant = asof.parse_instant_utc(end.get("observedAt"))
    if served_instant is not None and end_instant is not None:
        return end_instant == served_instant, asof.GENERATION_MATCH_INSTANT
    return end.get("observedDate") == served_date, asof.GENERATION_MATCH_DATE


def value_movement(
    asset_key: str,
    *,
    as_of: date | datetime | str | None = None,
    served_instant: Any = None,
    source_keys: Iterable[str] = LEDGER_SOURCE_KEYS,
    path: Path | None = None,
) -> dict[str, Any]:
    """Two-generation movement evidence for one asset.  Read-only.

    ``as_of`` is the board date the reader is looking at (default today UTC);
    ``served_instant`` is that board's scrape instant when known.  With an
    instant, the current end is selected INSTANT-STRICT
    (:func:`asof.value_known_before`) — nothing recorded after the served
    scrape can answer, not even later the same day.  Without one, selection is
    day-granular (:func:`asof.value_as_of`) and labelled so.
    """
    requested = store.as_of_date(as_of if as_of is not None else _today_utc())
    instant = asof.parse_instant_utc(served_instant)
    out: dict[str, Any] = {
        "schema": MOVEMENT_SCHEMA,
        "assetKey": asset_key,
        "requestedDate": requested,
        "servedInstant": instant.isoformat() if instant is not None else None,
        "currentSelection": (
            SELECTION_KNOWN_BEFORE_INSTANT if instant is not None else SELECTION_AS_OF_DATE
        ),
        "historyFloor": store.HISTORY_FLOOR,
        "additive": False,
        "nonAdditiveNote": NON_ADDITIVE_NOTE,
        "evidenceNotCause": True,
        "unobserved": [dict(u) for u in UNOBSERVED],
        "recordedSourceKeys": list(LEDGER_SOURCE_KEYS),
        "granularity": (
            "a generation is one recorded scrape; source values are matched to the "
            "canonical end's own scrape instant (generationMatch 'instant'), or by "
            "date only for instant-less legacy rows (generationMatch 'date'); the "
            "previous end is the latest scrape on the comparator board date"
        ),
        "status": None,
        "missingReason": None,
        "current": None,
        "previous": None,
        "comparatorBoardDate": None,
        "currentIsServedGeneration": None,
        "currentIsServedGenerationBasis": None,
        "rankChangeAlignment": None,
        "change": None,
        "methodology": None,
        "sources": [],
        "sourcesNotObservedAtEitherGeneration": [],
    }

    if instant is not None:
        # The served generation itself, matched exactly on (board date,
        # scrape instant).  ``observed_date`` is the producer's board-date
        # claim, which can sit on the next UTC date from its instant (a
        # host clock ahead of UTC), so an instant-bounded search alone can
        # miss a board the ledger HAS.  An exact match is the served scrape
        # — never a future one.  Only when it is absent fall back to the
        # instant-strict lookup.
        served = asof.value_at_generation(
            asset_key,
            observed_date=requested,
            observed_at=instant.isoformat(),
            lane=store.LANE_CANONICAL,
            allow_date_fallback=False,
            path=path,
        )
        if served["present"]:
            current = served
            out["currentSelection"] = SELECTION_SERVED_GENERATION
        else:
            current = asof.value_known_before(asset_key, instant, path=path)
    else:
        current = asof.value_as_of(asset_key, requested, path=path)
    if current.get("fidelity") == asof.FIDELITY_UNAVAILABLE:
        out["status"] = STATUS_NO_CURRENT
        out["missingReason"] = current.get("missingReason")
        return out
    out["current"] = _end(current)
    cur_end = out["current"]
    current_date = str(current["observedDate"])
    same, basis = _same_generation(cur_end, requested, instant)
    out["currentIsServedGeneration"] = same
    out["currentIsServedGenerationBasis"] = basis

    comparator = asof.previous_board_date(before_date=current_date, path=path)
    if comparator is None:
        out["status"] = STATUS_NO_COMPARATOR
        out["missingReason"] = REASON_NO_PRIOR_BOARD
        return out
    out["comparatorBoardDate"] = comparator

    previous = asof.value_as_of(asset_key, comparator, path=path)
    if previous.get("fidelity") == asof.FIDELITY_UNAVAILABLE:
        out["status"] = STATUS_NO_COMPARATOR
        out["missingReason"] = previous.get("missingReason")
        return out
    prev_end = _end(previous)
    out["previous"] = prev_end

    # Does this diff the same two boards the published ``rankChange`` does?
    # rankChange compares the SERVED board date against the latest board date
    # strictly before it, and is None for an asset absent from that board.
    rank_change_comparator = asof.previous_board_date(before_date=requested, path=path)
    reasons: list[str] = []
    if cur_end["observedDate"] != requested:
        reasons.append(ALIGN_LEDGER_BEHIND_SERVED_BOARD)
    if prev_end["observedDate"] != comparator:
        reasons.append(ALIGN_ABSENT_FROM_COMPARATOR_BOARD)
    out["rankChangeAlignment"] = {
        "sameBoardsAsRankChange": (
            not reasons and prev_end["observedDate"] == rank_change_comparator
        ),
        "rankChangeComparatorDate": rank_change_comparator,
        "reasons": reasons,
    }

    prev_rank, cur_rank = prev_end["rank"], cur_end["rank"]
    out["change"] = {
        "value": _diff(prev_end["value"], cur_end["value"]),
        # Same sign convention as the published ``rankChange``: positive =
        # moved UP the board (smaller rank number).
        "rank": (
            int(prev_rank) - int(cur_rank)
            if isinstance(prev_rank, int) and isinstance(cur_rank, int)
            else None
        ),
        "tierChanged": _changed(prev_end["tier"], cur_end["tier"]),
        "confidenceChanged": _changed(prev_end["confidence"], cur_end["confidence"]),
    }
    out["methodology"] = {
        "previousPipelineVersion": prev_end["pipelineVersion"],
        "currentPipelineVersion": cur_end["pipelineVersion"],
        "pipelineVersionChanged": _changed(prev_end["pipelineVersion"], cur_end["pipelineVersion"]),
        "covers": "contract shape version + Hill-curve constants (content hash)",
    }
    sources, neither = _source_rows(asset_key, prev_end, cur_end, source_keys, path)
    out["sources"] = sources
    out["sourcesNotObservedAtEitherGeneration"] = neither
    out["status"] = STATUS_OK
    return out
