"""THE draft-capital generation reader — one answer per (league, draft class).

Batch F of the draft-valuation workstream (owner directive 2026-10-18,
``docs/draft/DRAFT_VALUATION_WORKSTREAM.md``).  Every consumer of rookie-auction
dollars reads them here:

* **A class's 72 pick dollars** — :func:`read_class_generation`.  The class's
  candidate is the owner-approved spreadsheet formula
  (``curve.compute_curve``) over the class's rookie inputs (the frozen 2026
  provisional baseline until Batch D promotes the class's own inputs) and the
  three most recent completed classes before it
  (``snapshots.select_spine_years``).  The candidate goes to the canonical
  resolver (``published.resolve_published_allocation``), which verifies the
  whole dollars, stores them create-only, and otherwise serves THAT year's
  last verified allocation (``last_known_good``) or ``unavailable`` with a
  named reason.  Never another year's curve, never $0.  A promoted generation
  (Batch D's pointer) is served by the resolver ahead of the candidate.
* **What the served record says it is** — :func:`generation_receipt`: the
  receipt fields every response carries (``generationHash``,
  ``curveVersion``, ``targetDraftYear``, ``actualInputClassYear``,
  ``spineYears``, ``inputMode``, ``allocationState``), read from the SERVED
  record's own provenance — a last-known-good answer describes the curve it
  actually serves, not the one this request tried to compute.  A field the
  record does not state is ``None``, never guessed.
* **A ranked rookie list on the same dollar curve** — :func:`rookie_ladder`.
  ``/draft``'s per-rookie pre-draft dollars (``rookieKtcValue``) are the same
  formula evaluated over the auction's rookie values instead of the class's
  inputs.  This used to be a float copy of the formula inside ``server.py``
  (``_rookie_dollars_from_values``) that read the workbook's cached spine,
  fell back to a flat spine when the workbook was unreadable, and accepted
  any number of rookies.  Here it is the canonical calculation, at the
  formula's own size (72), over the canonical spine of the class being
  auctioned; anything else is refused with a reason (dollars ``None``).

Out of scope, deliberately: which leagues are configured (``league_scope`` —
``dynasty_main`` only), who owns a pick (``src/identity/picks.py``), the draft
order (``src/public_league/draft_order.py``), and canonical 0-9999 pick
values / the trade package model, which are a different quantity and never
read from here.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence

from src.draft.rookie_auction import published as _published
from src.draft.rookie_auction import snapshots as _snap
from src.draft.rookie_auction.curve import (
    FORMULA_VERSION,
    WORKBOOK_PARAMS,
    CurveInputError,
    CurveInvariantError,
    compute_curve,
    curve_receipt,
)
from src.draft.rookie_auction.league_scope import LeagueNotConfiguredError, league_scope

__all__ = [
    "INPUT_MODE_ACTUAL",
    "INPUT_MODE_FROZEN_FALLBACK",
    "LADDER_COMPUTED",
    "LADDER_METHOD",
    "LADDER_REFUSED",
    "PROMOTED_CLASS_SNAPSHOT_SOURCE",
    "RECEIPT_FIELDS",
    "ClassCurveInputs",
    "DraftCapitalGeneration",
    "RookieLadder",
    "class_curve_candidate",
    "class_curve_inputs",
    "curve_id",
    "generation_health",
    "generation_receipt",
    "input_mode_of",
    "read_class_generation",
    "read_generation",
    "rookie_ladder",
]

INPUT_MODE_FROZEN_FALLBACK = "frozen_fallback"
INPUT_MODE_ACTUAL = "actual"

#: Provenance ``source`` of an allocation computed from a class's OWN
#: canonical rookie snapshot (Batch D's promotion path).
PROMOTED_CLASS_SNAPSHOT_SOURCE = "canonical_class_snapshot"

#: The receipt every draft-capital response carries per class (Batch F).
RECEIPT_FIELDS = (
    "generationHash",
    "curveVersion",
    "targetDraftYear",
    "actualInputClassYear",
    "spineYears",
    "inputMode",
    "allocationState",
)

LADDER_METHOD = "canonical_rookie_auction_curve"
LADDER_COMPUTED = "computed"
LADDER_REFUSED = "refused"


# --- the served record's receipt ------------------------------------------------------


def _provenance(allocation: Any) -> Mapping[str, Any]:
    receipt = getattr(allocation, "receipt", None) or {}
    prov = receipt.get("provenance") if isinstance(receipt, Mapping) else None
    return prov if isinstance(prov, Mapping) else {}


def input_mode_of(allocation: Any) -> str | None:
    """The ``inputMode`` the SERVED record states, or ``None``.

    A promoted record (Batch D, ``source: canonical_class_snapshot``) was
    computed from its class's own snapshot, so it is ``actual``.
    """
    prov = _provenance(allocation)
    mode = prov.get("inputsMode")
    if mode in (INPUT_MODE_FROZEN_FALLBACK, INPUT_MODE_ACTUAL):
        return str(mode)
    if prov.get("source") == PROMOTED_CLASS_SNAPSHOT_SOURCE:
        return INPUT_MODE_ACTUAL
    return None


def generation_receipt(allocation: Any, target_draft_year: int) -> dict[str, Any]:
    """The Batch F receipt of one served class allocation.

    ``generationHash`` is the served record's checksum (the identity of the
    generation actually published; ``None`` when nothing is served).
    ``curveVersion`` is the record's formula version.  ``spineYears``,
    ``inputMode`` and ``actualInputClassYear`` come from the record's
    provenance; a promoted class snapshot IS its class, so its input class is
    the target year.  Nothing is taken from what this request computed.
    """
    prov = _provenance(allocation)
    receipt = getattr(allocation, "receipt", None) or {}
    formula = receipt.get("formulaVersion") if isinstance(receipt, Mapping) else None
    spine = prov.get("spineYears")
    spine_years = [int(y) for y in spine] if isinstance(spine, (list, tuple)) else None
    mode = input_mode_of(allocation)
    actual_year = prov.get("actualInputClassYear")
    if actual_year is None and prov.get("source") == PROMOTED_CLASS_SNAPSHOT_SOURCE:
        actual_year = int(target_draft_year)
    has_record = bool(getattr(allocation, "record_checksum", None))
    return {
        "generationHash": getattr(allocation, "record_checksum", None),
        "curveVersion": formula if has_record else None,
        "targetDraftYear": int(target_draft_year),
        "actualInputClassYear": int(actual_year) if actual_year is not None else None,
        "spineYears": spine_years if has_record else None,
        "inputMode": mode if has_record else None,
        "allocationState": getattr(allocation, "allocation_state", None),
    }


@dataclass(frozen=True)
class DraftCapitalGeneration:
    """One class's served allocation plus its receipt (dollars by draft position only)."""

    league_key: str
    target_draft_year: int
    allocation: Any  # published.PublishedAllocation

    @property
    def allocation_state(self) -> str | None:
        return getattr(self.allocation, "allocation_state", None)

    @property
    def final_whole_dollars(self) -> tuple[int, ...] | None:
        return getattr(self.allocation, "final_whole_dollars", None)

    @property
    def available(self) -> bool:
        return self.final_whole_dollars is not None

    def receipt(self) -> dict[str, Any]:
        return generation_receipt(self.allocation, self.target_draft_year)


# --- the class candidate ----------------------------------------------------------------


@dataclass(frozen=True)
class ClassCurveInputs:
    """The rookie inputs one class's curve is computed from, and what they are."""

    values: tuple[Decimal, ...]
    input_mode: str
    inputs_id: str
    actual_input_class_year: int | None
    provenance: Mapping[str, Any]


def class_curve_inputs(league_key: str, draft_year: int) -> ClassCurveInputs:
    """The FALLBACK candidate's rookie inputs for one class.

    Owner decision 3: every class uses the frozen owner-approved 2026
    provisional inputs until THAT class's real inputs pass Batch D (readiness
    + owner-gated promotion).  This module never decides that a class is
    ready: Batch D publishes a promoted generation that the resolver serves
    ahead of any candidate.  Raises ``LeagueNotConfiguredError`` for any league
    but ``dynasty_main`` and ``SnapshotIntegrityError`` for a tampered baseline.
    """
    from src.draft.rookie_auction.class_snapshot import frozen_fallback_snapshot  # noqa: PLC0415

    snap = frozen_fallback_snapshot(int(draft_year), league_key=league_key)
    prov = dict(snap.provenance)
    return ClassCurveInputs(
        values=tuple(e.value for e in snap.entries),
        input_mode=str(snap.mode),
        inputs_id=str(prov.get("frozenSnapshotId") or "unknown"),
        actual_input_class_year=snap.actual_input_class_year,
        provenance=prov,
    )


def curve_id(
    formula_version: str, input_mode: str | None, inputs_id: str | None, spine_years: Sequence[int]
) -> str:
    """A readable identity for one class curve: formula | inputs | spine."""
    spine = "-".join(str(int(y)) for y in spine_years)
    return f"{formula_version}|{input_mode}:{inputs_id}|spine:{spine}"


def class_curve_candidate(
    league_key: str,
    draft_year: int,
    *,
    now: str | None = None,
    config_dir: Path | None = None,
    inputs_fn: Callable[[str, int], ClassCurveInputs] | None = None,
):
    """The class's own candidate: an ``AllocationCandidate``, a ``CandidateFailure``
    naming why none could be computed, or ``None`` for an unconfigured league
    (the resolver then answers ``league_not_configured``)."""
    year = int(draft_year)
    key = str(league_key) if league_key else ""
    at = now or datetime.now(timezone.utc).isoformat()
    try:
        league_scope(key)
    except LeagueNotConfiguredError:
        return None
    cfg = config_dir if config_dir is not None else _snap.CONFIG_DIR
    read_inputs = inputs_fn if inputs_fn is not None else class_curve_inputs
    try:
        inputs = read_inputs(key, year)
        spine_years = _snap.select_spine_years(year, league_key=key, config_dir=cfg)
        spine = [
            _snap.load_completed_class_curve(y, league_key=key, config_dir=cfg) for y in spine_years
        ]
        result = compute_curve(list(inputs.values), [c.dollars for c in spine])
    except (
        CurveInputError,
        CurveInvariantError,
        _snap.SnapshotIntegrityError,
        _snap.SpineUnavailableError,
        LeagueNotConfiguredError,
        OSError,
    ) as exc:
        return _published.CandidateFailure(
            draft_year=year, reason=f"class_curve_unavailable:{type(exc).__name__}:{exc}", at=at
        )
    cid = curve_id(FORMULA_VERSION, inputs.input_mode, inputs.inputs_id, spine_years)
    receipt = curve_receipt(
        result, spine_years=spine_years, input_provenance=dict(inputs.provenance)
    )
    return _published.AllocationCandidate.from_curve(
        result,
        draft_year=year,
        effective_at=at,
        provenance={
            "source": "rookie_auction_curve",
            "curveId": cid,
            "inputsMode": inputs.input_mode,
            "inputsId": inputs.inputs_id,
            "frozenInputsChecksum": inputs.provenance.get("frozenChecksum"),
            "actualInputClassYear": inputs.actual_input_class_year,
            "spineYears": list(spine_years),
            "spineChecksums": {str(c.draft_class): c.checksum for c in spine},
            "curveReceiptSha256": receipt["receiptSha256"],
        },
    )


# --- the reader -----------------------------------------------------------------------


def read_generation(
    league_key: str,
    draft_year: int,
    *,
    candidate: Any = None,
    store_dirs: Sequence[Any] | None = None,
    write_dir: Any = None,
    persist: bool = True,
    lifecycle: Any = None,
) -> DraftCapitalGeneration:
    """Resolve ``(league_key, draft_year)`` through the canonical resolver."""
    kwargs: dict[str, Any] = {"persist": persist}
    if store_dirs is not None:
        kwargs["store_dirs"] = store_dirs
    if write_dir is not None:
        kwargs["write_dir"] = write_dir
    if lifecycle is not None:
        kwargs["lifecycle"] = lifecycle
    key = str(league_key) if league_key else ""
    allocation = _published.resolve_published_allocation(
        key, int(draft_year), candidate=candidate, **kwargs
    )
    return DraftCapitalGeneration(
        league_key=key, target_draft_year=int(draft_year), allocation=allocation
    )


def read_class_generation(
    league_key: str,
    draft_year: int,
    *,
    now: str | None = None,
    config_dir: Path | None = None,
    inputs_fn: Callable[[str, int], ClassCurveInputs] | None = None,
    store_dirs: Sequence[Any] | None = None,
    write_dir: Any = None,
    persist: bool = True,
    lifecycle: Any = None,
) -> DraftCapitalGeneration:
    """THE reader: the class's canonical candidate, resolved to its served generation."""
    candidate = class_curve_candidate(
        league_key, draft_year, now=now, config_dir=config_dir, inputs_fn=inputs_fn
    )
    return read_generation(
        league_key,
        draft_year,
        candidate=candidate,
        store_dirs=store_dirs,
        write_dir=write_dir,
        persist=persist,
        lifecycle=lifecycle,
    )


#: ``unavailable`` reasons that are an expected, correct answer rather than a
#: failure worth an operator alert.
_EXPECTED_UNAVAILABLE_PREFIXES = ("league_not_configured", "draft_class_retired")


def generation_health(
    league_key: str, draft_years: Sequence[int], *, persist: bool = True
) -> list[dict[str, Any]]:
    """One health row per class, for the operator alert sweep.

    ``degraded`` is true when a class is served from its last known good
    (a refresh failed) or is unavailable for an unexpected reason.  Never
    raises: an unexpected error becomes a degraded row naming it.
    """
    rows: list[dict[str, Any]] = []
    for year in sorted({int(y) for y in draft_years}):
        try:
            gen = read_class_generation(league_key, year, persist=persist)
        except Exception as exc:  # noqa: BLE001 — the sweep must report, not raise
            rows.append(
                {
                    "leagueKey": league_key,
                    "draftYear": year,
                    "allocationState": None,
                    "degraded": True,
                    "reason": f"reader_error:{type(exc).__name__}:{exc}",
                    "failedRefresh": None,
                    "lastValidAt": None,
                    "generationHash": None,
                }
            )
            continue
        alloc = gen.allocation
        state = gen.allocation_state
        reason = getattr(alloc, "unavailable_reason", None)
        failed = getattr(alloc, "failed_refresh", None)
        degraded = state == _published.STATE_LAST_KNOWN_GOOD or (
            state == _published.STATE_UNAVAILABLE
            and not str(reason or "").startswith(_EXPECTED_UNAVAILABLE_PREFIXES)
        )
        rows.append(
            {
                "leagueKey": league_key,
                "draftYear": year,
                "allocationState": state,
                "degraded": bool(degraded),
                "reason": reason or (failed or {}).get("reason"),
                "failedRefresh": dict(failed) if failed else None,
                "lastValidAt": getattr(alloc, "last_valid_at", None),
                "generationHash": getattr(alloc, "record_checksum", None),
            }
        )
    return rows


# --- a ranked rookie list on the class's dollar curve --------------------------------------


@dataclass(frozen=True)
class RookieLadder:
    """Pre-draft dollars for a ranked rookie list, or a refusal with its reason."""

    dollars: tuple[float, ...] | None
    state: str
    reason: str | None
    receipt: Mapping[str, Any]


def rookie_ladder(
    values: Sequence[object],
    *,
    league_key: str,
    draft_year: int,
    input_source: str,
    config_dir: Path | None = None,
) -> RookieLadder:
    """The class formula evaluated over a ranked rookie list (best first).

    Returns the half-dollar reference curve (``referenceDollars``, the
    formula's own precision) as floats — the quantity ``/draft``'s pre-draft
    ladder always published.  Refused (``dollars: None`` + reason) for an
    unconfigured league, a list that is not exactly the formula's 72 picks, a
    non-positive value, or a class whose spine is not on file — never a
    flat-spine curve, never a curve stretched over fewer picks, never $0.
    """
    key = str(league_key) if league_key else ""
    year = int(draft_year)
    base = {
        "method": LADDER_METHOD,
        "curveVersion": FORMULA_VERSION,
        "targetDraftYear": year,
        "inputSource": input_source,
        "inputCount": len(values),
        "spineYears": None,
        "precision": "half_dollar_reference",
    }

    def refused(reason: str) -> RookieLadder:
        return RookieLadder(
            None, LADDER_REFUSED, reason, {**base, "state": LADDER_REFUSED, "reason": reason}
        )

    n = WORKBOOK_PARAMS.pick_count
    if len(values) != n:
        return refused(f"inputs_incomplete:need_{n}_rookies_have_{len(values)}")
    cfg = config_dir if config_dir is not None else _snap.CONFIG_DIR
    try:
        league_scope(key)
        spine_years = _snap.select_spine_years(year, league_key=key, config_dir=cfg)
        spine = [
            _snap.load_completed_class_curve(y, league_key=key, config_dir=cfg).dollars
            for y in spine_years
        ]
        result = compute_curve(list(values), spine)
    except LeagueNotConfiguredError:
        return refused(f"league_not_configured:{key}")
    except (
        CurveInputError,
        CurveInvariantError,
        _snap.SnapshotIntegrityError,
        _snap.SpineUnavailableError,
        OSError,
    ) as exc:
        return refused(f"curve_unavailable:{type(exc).__name__}:{exc}")
    dollars = tuple(float(d) for d in result.reference_dollars)
    return RookieLadder(
        dollars,
        LADDER_COMPUTED,
        None,
        {**base, "state": LADDER_COMPUTED, "reason": None, "spineYears": list(spine_years)},
    )
