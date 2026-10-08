"""Two-generation value-movement attribution — a READ over the temporal ledger.

Answers "why did this asset's value move between two board generations?" with
the CONTRIBUTING EVIDENCE the ledger actually stores, never an asserted cause
(owner learning-loop item IC-7; ``docs/ui/CALCULATOR_UI_IMPLEMENTATION_CONTRACT.md``
§10).  It is a consumer of :mod:`src.history.asof` — every lookup goes through
the canonical as-of contract, so the never-future rule, the permanent
``before_history_boundary`` floor, the deterministic tie rule and the fidelity
labels are inherited rather than reimplemented.

What one answer contains:

* **Generations.**  The CURRENT generation is the asset's latest
  ``canonical_board`` observation at or before the requested board date; the
  COMPARATOR is the latest canonical board date strictly before the current
  one — the same rule ``rankChange`` derives from
  (:func:`asof.previous_board_date`), so the movement and the published rank
  change always diff the same two boards.  Generations are UTC board dates;
  within a date the as-of tie rule picks the latest recorded scrape.
* **Canonical change.**  Value / rank / tier / confidence at both ends, with
  each end's own observed date and fidelity.  A missing end makes the change
  ``None`` — "no comparator" is not ``0``.
* **Per-source deltas** from the ``source_value`` lane (vendor-published
  numbers only — what :mod:`src.history.record` admits).  A source counts as
  PRESENT at a generation only when it was recorded ON that generation's date;
  a nearest-prior carry is not presence.  A source present at one end only is
  ``appeared`` / ``disappeared`` with ``delta: None`` — absent is never a zero
  delta.
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


def _source_at(asset_key: str, source_key: str, on: str, path: Path | None) -> dict[str, Any]:
    """A source's recorded value AT one generation date.

    Present only when recorded on that exact date (fidelity ``exact``); a
    nearest-prior hit is reported as ``lastObservedDate`` context, never as a
    value at this generation.
    """
    got = asof.value_as_of(asset_key, on, lane=store.LANE_SOURCE, source_key=source_key, path=path)
    if got.get("fidelity") == asof.FIDELITY_EXACT and got.get("value") is not None:
        return {"present": True, "value": got["value"], "observedDate": got["observedDate"]}
    last = got.get("observedDate") if got.get("fidelity") == asof.FIDELITY_NEAREST_PRIOR else None
    return {"present": False, "value": None, "lastObservedDate": last}


def _source_rows(
    asset_key: str,
    previous_date: str,
    current_date: str,
    source_keys: Iterable[str],
    path: Path | None,
) -> tuple[list[dict[str, Any]], list[str]]:
    rows: list[dict[str, Any]] = []
    neither: list[str] = []
    for skey in source_keys:
        prev = _source_at(asset_key, skey, previous_date, path)
        cur = _source_at(asset_key, skey, current_date, path)
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


def value_movement(
    asset_key: str,
    *,
    as_of: date | datetime | str | None = None,
    source_keys: Iterable[str] = LEDGER_SOURCE_KEYS,
    path: Path | None = None,
) -> dict[str, Any]:
    """Two-generation movement evidence for one asset.  Read-only.

    ``as_of`` is the board date the reader is looking at (default today UTC).
    Never selects an observation after it.
    """
    requested = store.as_of_date(as_of if as_of is not None else _today_utc())
    out: dict[str, Any] = {
        "schema": MOVEMENT_SCHEMA,
        "assetKey": asset_key,
        "requestedDate": requested,
        "historyFloor": store.HISTORY_FLOOR,
        "additive": False,
        "nonAdditiveNote": NON_ADDITIVE_NOTE,
        "evidenceNotCause": True,
        "unobserved": [dict(u) for u in UNOBSERVED],
        "recordedSourceKeys": list(LEDGER_SOURCE_KEYS),
        "granularity": (
            "generations are UTC board dates; within a date the latest recorded "
            "scrape is selected by the as-of tie rule"
        ),
        "status": None,
        "missingReason": None,
        "current": None,
        "previous": None,
        "comparatorBoardDate": None,
        "change": None,
        "methodology": None,
        "sources": [],
        "sourcesNotObservedAtEitherGeneration": [],
    }

    current = asof.value_as_of(asset_key, requested, path=path)
    if current.get("fidelity") == asof.FIDELITY_UNAVAILABLE:
        out["status"] = STATUS_NO_CURRENT
        out["missingReason"] = current.get("missingReason")
        return out
    out["current"] = _end(current)
    current_date = str(current["observedDate"])

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
    cur_end = out["current"]

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
    sources, neither = _source_rows(
        asset_key, str(prev_end["observedDate"]), current_date, source_keys, path
    )
    out["sources"] = sources
    out["sourcesNotObservedAtEitherGeneration"] = neither
    out["status"] = STATUS_OK
    return out
