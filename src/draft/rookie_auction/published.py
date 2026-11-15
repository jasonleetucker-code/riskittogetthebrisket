"""Published draft-year allocations with last-known-good safety (owner addendum 2026-10-18).

The one answer to "which whole-dollar curve does ``dynasty_main`` publish for
draft year Y right now, and is it current or a fallback?"::

    from src.draft.rookie_auction.published import resolve_published_allocation
    alloc = resolve_published_allocation("dynasty_main", 2027, candidate=...)

Rules (owner addendum 2026-10-18):

* A candidate (a freshly computed reference curve plus provenance) is turned
  into whole dollars by ``apportion.apportion_whole_dollars`` and checked by
  the independent ``verify.verify_whole_dollar_allocation``.  Only a verified,
  complete 72-pick allocation totalling exactly $1,200 is published and
  stored.
* Storage is append-only and immutable: one create-only, checksummed JSON
  record per verified allocation; a record identical in content to the
  newest one is not re-written.  "Current" is DERIVED (the newest eligible
  record for that league and year), never a mutable copy.  Repo-tracked
  records (``config/draft_valuation/published_allocations/``) hold the
  workbook-derived allocations; production-computed ones go to the box-local
  store (``data/draft_valuation/published_allocations/``, gitignored).
* If a refresh fails (missing inputs, an infeasible constraint system, a
  failed verification, a formula-version change), the newest verified record
  for THE SAME year is served as ``last_known_good`` with ``failedRefresh``
  (reason + attempt time) and ``lastValidAt``.  With none, the answer is
  ``unavailable`` with a named reason — never zero dollars, never another
  year's curve (no cross-year fallback: no provisional-class policy exists).
* A stored record stops being eligible when its draft class is retired
  (``pick_lifecycle``) or its ``formulaVersion`` differs from the running
  formula — the answer is then ``unavailable``, not a stale curve.
* PROMOTED GENERATIONS (Batch D, owner decision 12, 2026-10-18).  The
  policy-driven promotion path (``promotion.py``) publishes a class's own
  candidate as a new create-only allocation under
  ``config/draft_valuation/promoted_allocations/`` and then switches to it by
  writing ONE create-only, sequence-numbered pointer record under
  ``config/draft_valuation/promotion_pointers/`` — the pointer write is the
  atomic switch.  Promoted records are invisible to the newest-record rule
  above; only a pointer makes one current.  Rollback is another pointer
  (back to the generation before), never a deletion.  With no pointer, or a
  pointer back to the fallback, resolution is exactly the rule above.  An
  unreadable pointer history or a missing promoted record degrades to the
  rule above with a note — never zero, never another year.
* DOLLARS ONLY, by draft position.  A record never contains ownership; the
  loader refuses one that does, and :class:`PublishedAllocation` has no
  ownership field, so old ownership cannot be read from it.  The consumer
  joins ownership from the live Sleeper fold.
"""

from __future__ import annotations

import json
import os
import tempfile
from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from fractions import Fraction
from pathlib import Path
from typing import Any, Mapping, Sequence

from src.draft.rookie_auction.apportion import ApportionmentRefused, apportion_whole_dollars
from src.draft.rookie_auction.curve import (
    FORMULA_VERSION,
    WORKBOOK_PARAMS,
    CurveResult,
    iter_labels,
    whole_dollar_constraints,
)
from src.draft.rookie_auction.league_scope import LeagueNotConfiguredError, league_scope
from src.draft.rookie_auction.snapshots import CONFIG_DIR, canonical_checksum
from src.draft.rookie_auction.verify import verify_whole_dollar_allocation
from src.identity.pick_lifecycle import ClassLifecycle, is_retired

__all__ = [
    "ACTION_PROMOTE",
    "ACTION_RESUME",
    "ACTION_ROLLBACK",
    "BOX_STORE",
    "PROMOTION_ROOT",
    "REPO_STORE",
    "STATE_CURRENT",
    "STATE_LAST_KNOWN_GOOD",
    "STATE_UNAVAILABLE",
    "AllocationCandidate",
    "CandidateFailure",
    "GenerationError",
    "GenerationState",
    "PromotionPreview",
    "PublishedAllocation",
    "allocation_history",
    "generation_state",
    "load_promoted_record",
    "preview_promotion",
    "publish_promoted_generation",
    "resolve_published_allocation",
    "resume_generation",
    "rollback_generation",
]

SCHEMA = "draft_valuation_published_allocation_v1"
REPO_STORE = CONFIG_DIR / "published_allocations"
BOX_STORE = (
    Path(__file__).resolve().parents[3] / "data" / "draft_valuation" / "published_allocations"
)

#: Root of the repo-tracked promotion stores (pointers + promoted allocations).
#: Read at call time, so the test suite can redirect it
#: (``tests/runtime_data_isolation.py``).
PROMOTION_ROOT = CONFIG_DIR
POINTER_DIR_NAME = "promotion_pointers"
PROMOTED_DIR_NAME = "promoted_allocations"
POINTER_SCHEMA = "draft_valuation_promotion_pointer_v1"
ACTION_PROMOTE = "promote"
ACTION_ROLLBACK = "rollback"
ACTION_RESUME = "resume"
_POINTER_ACTIONS = frozenset({ACTION_PROMOTE, ACTION_ROLLBACK, ACTION_RESUME})

STATE_CURRENT = "current"
STATE_LAST_KNOWN_GOOD = "last_known_good"
STATE_UNAVAILABLE = "unavailable"

#: Keys that would carry ownership.  A record containing any of them, at any
#: depth, is refused — the store holds dollar curves only.
OWNERSHIP_KEYS = frozenset(
    {
        "owner",
        "ownerId",
        "ownerName",
        "rosterId",
        "originRosterId",
        "currentOwnerRosterId",
        "team",
        "teamName",
        "teamTotals",
        "manager",
        "managerName",
        "ownership",
        "assetId",
        "picksOwned",
    }
)


@dataclass(frozen=True)
class AllocationCandidate:
    """A freshly computed reference curve for one draft year, plus provenance."""

    draft_year: int
    reference_dollars: Sequence[object]
    effective_at: str
    provenance: Mapping[str, Any]
    formula_version: str = FORMULA_VERSION

    @classmethod
    def from_curve(
        cls,
        result: CurveResult,
        *,
        draft_year: int,
        effective_at: str,
        provenance: Mapping[str, Any],
    ) -> "AllocationCandidate":
        return cls(
            draft_year=int(draft_year),
            reference_dollars=tuple(result.reference_dollars),
            effective_at=effective_at,
            provenance=dict(provenance),
            formula_version=result.formula_version,
        )


@dataclass(frozen=True)
class CandidateFailure:
    """An upstream refresh that could not even produce a reference curve."""

    draft_year: int
    reason: str
    at: str


@dataclass(frozen=True)
class PublishedAllocation:
    league_key: str
    draft_year: int
    allocation_state: str
    picks: tuple[str, ...]
    final_whole_dollars: tuple[int, ...] | None
    reference_dollars: tuple[str, ...] | None
    effective_at: str | None
    last_valid_at: str | None
    failed_refresh: Mapping[str, str] | None
    unavailable_reason: str | None
    warning: str | None
    record_checksum: str | None
    receipt: Mapping[str, Any] | None
    notes: tuple[str, ...] = field(default_factory=tuple)

    def dollars_by_slot(self) -> dict[str, int]:
        """``{"1.01": 135, ...}``.  Refuses when nothing verified is available."""
        if self.final_whole_dollars is None:
            raise LookupError(f"no published allocation: {self.unavailable_reason}")
        return dict(zip(self.picks, self.final_whole_dollars))

    def to_dict(self) -> dict[str, Any]:
        return {
            "leagueKey": self.league_key,
            "draftYear": self.draft_year,
            "allocationState": self.allocation_state,
            "finalWholeDollars": None
            if self.final_whole_dollars is None
            else [{"pick": p, "dollars": d} for p, d in zip(self.picks, self.final_whole_dollars)],
            "referenceDollars": None
            if self.reference_dollars is None
            else [{"pick": p, "dollars": d} for p, d in zip(self.picks, self.reference_dollars)],
            "totalDollars": None
            if self.final_whole_dollars is None
            else sum(self.final_whole_dollars),
            "effectiveAt": self.effective_at,
            "lastValidAt": self.last_valid_at,
            "failedRefresh": None if self.failed_refresh is None else dict(self.failed_refresh),
            "unavailableReason": self.unavailable_reason,
            "warning": self.warning,
            "recordChecksum": self.record_checksum,
            "receipt": None if self.receipt is None else dict(self.receipt),
            "notes": list(self.notes),
        }


# --- records ------------------------------------------------------------------------


def _ts(value: str) -> datetime:
    ts = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    if ts.tzinfo is None:
        raise ValueError(f"timestamp without timezone: {value!r}")
    return ts


def _contains_ownership(obj: Any) -> bool:
    if isinstance(obj, Mapping):
        return any(k in OWNERSHIP_KEYS or _contains_ownership(v) for k, v in obj.items())
    if isinstance(obj, list):
        return any(_contains_ownership(v) for v in obj)
    return False


def _dstr(v: Fraction) -> str:
    d = Decimal(v.numerator) / Decimal(v.denominator)
    return format(d.normalize(), "f")


def _content_key(record: Mapping[str, Any]) -> str:
    """The allocation itself — the dollars and the formula — not its provenance.

    A refresh that reproduces the newest record's dollars (the 2-hourly
    workbook sync re-downloads identical cells under new file bytes) changes
    nothing: the existing record, verified first, stays current and no new
    record is written.
    """
    return canonical_checksum(
        {k: record.get(k) for k in ("formulaVersion", "referenceDollars", "finalWholeDollars")}
    )


def _build_record(
    league_key: str,
    candidate: AllocationCandidate,
    reference: list[Fraction],
    apportionment,
    verification,
) -> dict[str, Any]:
    labels = list(iter_labels(WORKBOOK_PARAMS))
    record: dict[str, Any] = {
        "schema": SCHEMA,
        "leagueKey": league_key,
        "draftYear": int(candidate.draft_year),
        "formulaVersion": candidate.formula_version,
        "effectiveAt": candidate.effective_at,
        "totalDollars": sum(apportionment.dollars),
        "referenceDollars": [{"pick": p, "dollars": _dstr(r)} for p, r in zip(labels, reference)],
        "finalWholeDollars": [
            {"pick": p, "dollars": d} for p, d in zip(labels, apportionment.dollars)
        ],
        "provenance": dict(candidate.provenance),
        "validation": {
            "apportionment": apportionment.receipt(labels),
            "verifier": verification.receipt(),
        },
    }
    record["checksum"] = {"algorithm": "sha256", "value": canonical_checksum(record)}
    return record


def _load_record(path: Path, league_key: str, draft_year: int) -> dict[str, Any]:
    record = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(record, dict) or record.get("schema") != SCHEMA:
        raise ValueError(f"{path.name}: not a published allocation")
    if (record.get("checksum") or {}).get("value") != canonical_checksum(record):
        raise ValueError(f"{path.name}: checksum mismatch — record was edited")
    if record.get("leagueKey") != league_key or record.get("draftYear") != draft_year:
        raise ValueError(f"{path.name}: filed under the wrong league or year")
    if _contains_ownership(record):
        raise ValueError(f"{path.name}: carries ownership — the store holds dollars only")
    whole = [r.get("dollars") for r in record.get("finalWholeDollars") or []]
    labels = [r.get("pick") for r in record.get("finalWholeDollars") or []]
    if labels != list(iter_labels(WORKBOOK_PARAMS)) or any(
        isinstance(d, bool) or not isinstance(d, int) for d in whole
    ):
        raise ValueError(f"{path.name}: finalWholeDollars malformed")
    if sum(whole) != WORKBOOK_PARAMS.budget_dollars or record.get("totalDollars") != sum(whole):
        raise ValueError(f"{path.name}: does not total the class pool")
    if (record.get("validation") or {}).get("verifier", {}).get("result") != "pass":
        raise ValueError(f"{path.name}: not independently verified")
    _ts(record["effectiveAt"])
    return record


def allocation_history(
    league_key: str,
    draft_year: int,
    *,
    store_dirs: Sequence[Path] | None = None,
) -> list[tuple[Path, dict[str, Any] | None, str | None]]:
    """Every record for (league, year), oldest first: ``(path, record|None, error|None)``."""
    out = []
    for base in store_dirs if store_dirs is not None else (REPO_STORE, BOX_STORE):
        d = Path(base) / league_key / str(int(draft_year))
        if not d.is_dir():
            continue
        for p in sorted(d.glob("*.json")):
            try:
                out.append((p, _load_record(p, league_key, int(draft_year)), None))
            except (OSError, ValueError, KeyError, TypeError) as exc:
                out.append((p, None, str(exc)))
    out.sort(
        key=lambda t: (1, _ts(t[1]["effectiveAt"]).timestamp(), t[1]["checksum"]["value"])
        if t[1]
        else (0, 0.0, t[0].name)
    )
    return out


def _persist(record: dict[str, Any], write_dir: Path, league_key: str) -> Path:
    d = Path(write_dir) / league_key / str(record["draftYear"])
    d.mkdir(parents=True, exist_ok=True)
    stamp = _ts(record["effectiveAt"]).strftime("%Y%m%dT%H%M%SZ")
    final = d / f"{stamp}__{record['checksum']['value'][:16]}.json"
    fd, tmp_name = tempfile.mkstemp(prefix=".alloc.", suffix=".tmp", dir=d)
    tmp = Path(tmp_name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(json.dumps(record, indent=1, ensure_ascii=False) + "\n")
            fh.flush()
            os.fsync(fh.fileno())
        try:
            os.link(tmp, final)
        except FileExistsError:
            existing = json.loads(final.read_text(encoding="utf-8"))
            if (existing.get("checksum") or {}).get("value") != record["checksum"]["value"]:
                raise
    finally:
        tmp.unlink(missing_ok=True)
    return final


# --- promoted generations + the pointer (Batch D) ---------------------------------


class GenerationError(RuntimeError):
    """A promotion / rollback / resume could not be written; nothing switched."""


@dataclass(frozen=True)
class GenerationState:
    """What the pointer history says for one (league, year).

    ``stack`` is the generation stack: a promote pushes its record checksum, a
    rollback pops it.  ``active_checksum`` is the top (``None`` = no promoted
    generation: the fallback rule serves).  ``held`` is true while the newest
    pointer is a rollback (cleared by an explicit resume).  ``error`` names an
    unreadable history; the resolver then ignores every pointer.
    """

    league_key: str
    draft_year: int
    active_checksum: str | None
    stack: tuple[str, ...]
    held: bool
    last_action: str | None
    last_action_at: str | None
    last_sequence: int
    pointers: tuple[Mapping[str, Any], ...]
    error: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "leagueKey": self.league_key,
            "draftYear": self.draft_year,
            "activeRecordChecksum": self.active_checksum,
            "generationStack": list(self.stack),
            "held": self.held,
            "lastAction": self.last_action,
            "lastActionAt": self.last_action_at,
            "lastSequence": self.last_sequence,
            "error": self.error,
        }


@dataclass(frozen=True)
class PromotionPreview:
    """A candidate turned into the record a promotion WOULD publish."""

    record: Mapping[str, Any] | None
    refusal: str | None
    same_as_active: bool


def _root(root: Path | None) -> Path:
    return Path(root) if root is not None else PROMOTION_ROOT


def _pointer_dir(root: Path, league_key: str, year: int) -> Path:
    return root / POINTER_DIR_NAME / league_key / str(int(year))


def _promoted_dir(root: Path, league_key: str, year: int) -> Path:
    return root / PROMOTED_DIR_NAME / league_key / str(int(year))


def _read_pointer(path: Path, league_key: str, year: int) -> dict[str, Any]:
    p = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(p, dict) or p.get("schema") != POINTER_SCHEMA:
        raise ValueError(f"{path.name}: not a promotion pointer")
    if (p.get("checksum") or {}).get("value") != canonical_checksum(p):
        raise ValueError(f"{path.name}: checksum mismatch — pointer was edited")
    if p.get("leagueKey") != league_key or p.get("draftYear") != year:
        raise ValueError(f"{path.name}: filed under the wrong league or year")
    if p.get("action") not in _POINTER_ACTIONS:
        raise ValueError(f"{path.name}: unknown action {p.get('action')!r}")
    if path.name != f"{int(p.get('sequence', -1)):06d}.json":
        raise ValueError(f"{path.name}: sequence does not match the file name")
    _ts(p["at"])
    return p


def generation_state(
    league_key: str, draft_year: int, *, root: Path | None = None
) -> GenerationState:
    """Fold the pointer history for ``(league_key, draft_year)``.  Never raises."""
    year = int(draft_year)
    d = _pointer_dir(_root(root), league_key, year)
    pointers: list[dict[str, Any]] = []
    error = None
    if d.is_dir():
        for path in sorted(d.glob("*.json")):
            try:
                pointers.append(_read_pointer(path, league_key, year))
            except (OSError, ValueError, KeyError, TypeError) as exc:
                error = str(exc)
                break
    if error is None:
        seqs = [int(p["sequence"]) for p in pointers]
        if seqs != list(range(1, len(seqs) + 1)):
            error = f"pointer sequence not contiguous from 1: {seqs}"
    stack: list[str] = []
    held = False
    if error is None:
        for p in pointers:
            if p["action"] == ACTION_PROMOTE:
                if not p.get("activeRecordChecksum"):
                    error = f"promote pointer {p['sequence']} names no record"
                    break
                stack.append(p["activeRecordChecksum"])
                held = False
            elif p["action"] == ACTION_ROLLBACK:
                if not stack:
                    error = f"rollback pointer {p['sequence']} with nothing to roll back"
                    break
                stack.pop()
                held = True
            else:  # resume
                held = False
            if (stack[-1] if stack else None) != p.get("activeRecordChecksum"):
                error = f"pointer {p['sequence']} disagrees with the folded generation stack"
                break
    last = pointers[-1] if pointers else None
    if error is not None:
        stack, held = [], False
    return GenerationState(
        league_key=league_key,
        draft_year=year,
        active_checksum=stack[-1] if stack else None,
        stack=tuple(stack),
        held=held,
        last_action=last["action"] if last else None,
        last_action_at=last["at"] if last else None,
        last_sequence=int(last["sequence"]) if last else 0,
        pointers=tuple(pointers),
        error=error,
    )


def load_promoted_record(
    league_key: str, draft_year: int, checksum: str, *, root: Path | None = None
) -> dict[str, Any] | None:
    """The promoted allocation record with ``checksum``, validated; else ``None``."""
    d = _promoted_dir(_root(root), league_key, int(draft_year))
    if not d.is_dir() or not checksum:
        return None
    for path in sorted(d.glob(f"*__{checksum[:16]}.json")):
        try:
            record = _load_record(path, league_key, int(draft_year))
        except (OSError, ValueError, KeyError, TypeError):
            continue
        if record["checksum"]["value"] == checksum:
            return record
    return None


def _write_pointer(
    root: Path,
    state: GenerationState,
    *,
    action: str,
    active: str | None,
    at: str,
    reason: str,
    extra: Mapping[str, Any] | None,
) -> dict[str, Any]:
    if state.error is not None:
        raise GenerationError(f"pointer history unreadable: {state.error}")
    _ts(at)
    seq = state.last_sequence + 1
    pointer: dict[str, Any] = {
        "schema": POINTER_SCHEMA,
        "leagueKey": state.league_key,
        "draftYear": state.draft_year,
        "sequence": seq,
        "action": action,
        "activeRecordChecksum": active,
        "previousRecordChecksum": state.active_checksum,
        "at": at,
        "reason": reason,
        "context": dict(extra or {}),
    }
    if _contains_ownership(pointer):
        raise GenerationError("pointer context carries ownership")
    pointer["checksum"] = {"algorithm": "sha256", "value": canonical_checksum(pointer)}
    d = _pointer_dir(root, state.league_key, state.draft_year)
    d.mkdir(parents=True, exist_ok=True)
    final = d / f"{seq:06d}.json"
    fd, tmp_name = tempfile.mkstemp(prefix=".ptr.", suffix=".tmp", dir=d)
    tmp = Path(tmp_name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(json.dumps(pointer, indent=1, ensure_ascii=False) + "\n")
            fh.flush()
            os.fsync(fh.fileno())
        try:
            os.link(tmp, final)  # THE switch: atomic, create-only
        except FileExistsError as exc:
            raise GenerationError(f"pointer {seq} already exists (concurrent writer)") from exc
    finally:
        tmp.unlink(missing_ok=True)
    return pointer


def preview_promotion(
    league_key: str, candidate: AllocationCandidate, *, root: Path | None = None
) -> PromotionPreview:
    """Verify ``candidate`` exactly as a promotion would, writing nothing."""
    try:
        league_scope(league_key)
    except LeagueNotConfiguredError:
        return PromotionPreview(None, f"league_not_configured:{league_key}", False)
    record, reason = _evaluate(league_key, candidate)
    if record is None:
        return PromotionPreview(None, reason, False)
    state = generation_state(league_key, candidate.draft_year, root=root)
    same = False
    if state.active_checksum:
        active = load_promoted_record(
            league_key, candidate.draft_year, state.active_checksum, root=root
        )
        same = active is not None and _content_key(active) == _content_key(record)
    return PromotionPreview(record, None, same)


def publish_promoted_generation(
    league_key: str,
    candidate: AllocationCandidate,
    *,
    at: str,
    reason: str,
    context: Mapping[str, Any] | None = None,
    root: Path | None = None,
) -> dict[str, Any] | None:
    """Atomically switch ``(league, year)`` to ``candidate``.  Returns the pointer.

    Step 1 writes the verified allocation create-only under
    ``promoted_allocations/`` (invisible until pointed at); step 2 writes the
    next pointer (the switch).  A failure in either step raises
    :class:`GenerationError` and leaves the previous generation serving.
    ``None`` when the candidate's dollars equal the active generation's
    (nothing to switch).
    """
    league_scope(league_key)
    base = _root(root)
    state = generation_state(league_key, candidate.draft_year, root=base)
    if state.error is not None:
        raise GenerationError(f"pointer history unreadable: {state.error}")
    if state.held:
        raise GenerationError("class is held after a rollback; resume it first")
    preview = preview_promotion(league_key, candidate, root=base)
    if preview.record is None:
        raise GenerationError(f"candidate refused: {preview.refusal}")
    if preview.same_as_active:
        return None
    record = dict(preview.record)
    try:
        _persist(record, base / PROMOTED_DIR_NAME, league_key)
    except OSError as exc:
        raise GenerationError(f"promoted allocation not written: {exc}") from exc
    return _write_pointer(
        base,
        state,
        action=ACTION_PROMOTE,
        active=record["checksum"]["value"],
        at=at,
        reason=reason,
        extra=context,
    )


def rollback_generation(
    league_key: str,
    draft_year: int,
    *,
    at: str,
    reason: str,
    context: Mapping[str, Any] | None = None,
    root: Path | None = None,
) -> dict[str, Any]:
    """Restore the generation before the active one; the class is then held."""
    league_scope(league_key)
    base = _root(root)
    state = generation_state(league_key, draft_year, root=base)
    if state.error is not None:
        raise GenerationError(f"pointer history unreadable: {state.error}")
    if not state.stack:
        raise GenerationError("no promoted generation to roll back (the fallback is serving)")
    restored = state.stack[-2] if len(state.stack) > 1 else None
    return _write_pointer(
        base, state, action=ACTION_ROLLBACK, active=restored, at=at, reason=reason, extra=context
    )


def resume_generation(
    league_key: str,
    draft_year: int,
    *,
    at: str,
    reason: str,
    context: Mapping[str, Any] | None = None,
    root: Path | None = None,
) -> dict[str, Any]:
    """Clear a rollback hold so automatic promotion may run again."""
    league_scope(league_key)
    base = _root(root)
    state = generation_state(league_key, draft_year, root=base)
    if state.error is not None:
        raise GenerationError(f"pointer history unreadable: {state.error}")
    if not state.held:
        raise GenerationError("class is not held")
    return _write_pointer(
        base,
        state,
        action=ACTION_RESUME,
        active=state.active_checksum,
        at=at,
        reason=reason,
        extra=context,
    )


# --- the resolver -------------------------------------------------------------------


def _unavailable(league_key, year, reason, failed=None, notes=()) -> PublishedAllocation:
    return PublishedAllocation(
        league_key=league_key,
        draft_year=year,
        allocation_state=STATE_UNAVAILABLE,
        picks=tuple(iter_labels(WORKBOOK_PARAMS)),
        final_whole_dollars=None,
        reference_dollars=None,
        effective_at=None,
        last_valid_at=None,
        failed_refresh=failed,
        unavailable_reason=reason,
        warning=f"no verified {year} draft allocation is available ({reason})",
        record_checksum=None,
        receipt=None,
        notes=tuple(notes),
    )


def _from_record(league_key, year, record, state, failed=None, notes=()) -> PublishedAllocation:
    warning = None
    if state == STATE_LAST_KNOWN_GOOD and failed:
        warning = (
            f"refresh at {failed['at']} failed ({failed['reason']}); serving the last verified "
            f"{year} allocation from {record['effectiveAt']}"
        )
    return PublishedAllocation(
        league_key=league_key,
        draft_year=year,
        allocation_state=state,
        picks=tuple(r["pick"] for r in record["finalWholeDollars"]),
        final_whole_dollars=tuple(r["dollars"] for r in record["finalWholeDollars"]),
        reference_dollars=tuple(r["dollars"] for r in record["referenceDollars"]),
        effective_at=record["effectiveAt"],
        last_valid_at=record["effectiveAt"],
        failed_refresh=failed,
        unavailable_reason=None,
        warning=warning,
        record_checksum=record["checksum"]["value"],
        receipt={
            "formulaVersion": record["formulaVersion"],
            "provenance": record["provenance"],
            "validation": record["validation"],
        },
        notes=tuple(notes),
    )


def _evaluate(league_key: str, candidate: AllocationCandidate):
    """``(record, None)`` for a verified candidate, else ``(None, reason)``."""
    if candidate.formula_version != FORMULA_VERSION:
        return None, f"formula_version_mismatch:{candidate.formula_version}"
    n = WORKBOOK_PARAMS.pick_count
    if candidate.reference_dollars is None or len(candidate.reference_dollars) != n:
        return None, f"inputs_incomplete:expected {n} reference values"
    try:
        _ts(candidate.effective_at)
    except (TypeError, ValueError) as exc:
        return None, f"effective_at_unreadable:{exc}"
    floors, caps = whole_dollar_constraints(WORKBOOK_PARAMS)
    try:
        apportionment = apportion_whole_dollars(
            candidate.reference_dollars, WORKBOOK_PARAMS.budget_dollars, floors=floors, caps=caps
        )
    except ApportionmentRefused as exc:
        return None, f"apportionment_refused:{exc}"
    reference = [Fraction(v) for v in candidate.reference_dollars]
    verification = verify_whole_dollar_allocation(
        reference,
        apportionment.dollars,
        WORKBOOK_PARAMS.budget_dollars,
        floors=floors,
        caps=caps,
    )
    if not verification.ok:
        return None, f"verification_failed:{','.join(verification.failures)}"
    record = _build_record(league_key, candidate, reference, apportionment, verification)
    if _contains_ownership(record):
        return None, "provenance_carries_ownership"
    return record, None


def resolve_published_allocation(
    league_key: str,
    draft_year: int,
    *,
    candidate: AllocationCandidate | CandidateFailure | None = None,
    lifecycle: ClassLifecycle | None = None,
    store_dirs: Sequence[Path] | None = None,
    write_dir: Path | None = None,
    persist: bool = True,
    promotion_root: Path | None = None,
) -> PublishedAllocation:
    """The published whole-dollar allocation for ``(league_key, draft_year)``.

    ``candidate`` — a fresh :class:`AllocationCandidate`, a
    :class:`CandidateFailure` naming why none could be computed, or ``None``
    (read the store only).  ``lifecycle`` — the class's
    ``pick_lifecycle`` verdict; a retired class publishes nothing.

    ``promotion_root`` — where the promotion pointer and promoted records
    live.  Defaults to :data:`PROMOTION_ROOT` when ``store_dirs`` is also
    defaulted; a caller that names its own ``store_dirs`` and no
    ``promotion_root`` reads no pointer (it chose its stores).  An active
    promoted generation is served as ``current`` and the candidate is not
    used; otherwise the rule below applies unchanged.
    """
    year = int(draft_year)
    try:
        league_scope(league_key)
    except LeagueNotConfiguredError:
        return _unavailable(league_key, year, f"league_not_configured:{league_key}")
    if is_retired(lifecycle):
        return _unavailable(league_key, year, "draft_class_retired")

    dirs = list(store_dirs) if store_dirs is not None else [REPO_STORE, BOX_STORE]
    target = Path(write_dir) if write_dir is not None else BOX_STORE

    notes: list[str] = []
    proot = (
        promotion_root
        if promotion_root is not None
        else (PROMOTION_ROOT if store_dirs is None else None)
    )
    if proot is not None:
        gen = generation_state(league_key, year, root=proot)
        if gen.error is not None:
            notes.append(f"promotion_pointer_unreadable:{gen.error}")
        elif gen.active_checksum:
            promoted = load_promoted_record(league_key, year, gen.active_checksum, root=proot)
            if promoted is not None and promoted["formulaVersion"] == FORMULA_VERSION:
                notes.append(f"promoted_generation:{gen.last_sequence}")
                if candidate is not None:
                    notes.append("candidate_not_used:promoted_generation_active")
                return _from_record(league_key, year, promoted, STATE_CURRENT, notes=notes)
            notes.append(f"promoted_generation_unavailable:{gen.active_checksum[:16]}")
    history = allocation_history(league_key, year, store_dirs=dirs)
    eligible = []
    for path, record, error in history:
        if record is None:
            notes.append(f"ignored_record:{path.name}:{error}")
        elif record["formulaVersion"] != FORMULA_VERSION:
            notes.append(f"ineligible_record:{path.name}:formula_version_mismatch")
        else:
            eligible.append(record)
    newest = eligible[-1] if eligible else None

    failed: dict[str, str] | None = None
    if isinstance(candidate, AllocationCandidate):
        if int(candidate.draft_year) != year:
            return _unavailable(
                league_key, year, f"draft_year_mismatch:{candidate.draft_year}!={year}", notes=notes
            )
        record, reason = _evaluate(league_key, candidate)
        if record is not None:
            if newest is not None and _content_key(newest) == _content_key(record):
                return _from_record(league_key, year, newest, STATE_CURRENT, notes=notes)
            if newest is not None and _ts(record["effectiveAt"]) <= _ts(newest["effectiveAt"]):
                notes.append("candidate_older_than_newest_record_ignored")
                return _from_record(league_key, year, newest, STATE_CURRENT, notes=notes)
            else:
                if persist:
                    try:
                        _persist(record, target, league_key)
                    except OSError as exc:
                        notes.append(f"not_persisted:{exc}")
                return _from_record(league_key, year, record, STATE_CURRENT, notes=notes)
        else:
            failed = {"at": candidate.effective_at, "reason": reason}
    elif isinstance(candidate, CandidateFailure):
        if int(candidate.draft_year) != year:
            return _unavailable(
                league_key, year, f"draft_year_mismatch:{candidate.draft_year}!={year}", notes=notes
            )
        failed = {"at": candidate.at, "reason": candidate.reason}
    elif candidate is not None:
        raise TypeError("candidate must be an AllocationCandidate, a CandidateFailure or None")

    if newest is None:
        if any("formula_version_mismatch" in n for n in notes):
            reason = "stored_allocation_formula_version_mismatch"
        else:
            reason = "no_verified_allocation"
        return _unavailable(league_key, year, reason, failed=failed, notes=notes)
    state = STATE_CURRENT if failed is None else STATE_LAST_KNOWN_GOOD
    return _from_record(league_key, year, newest, state, failed=failed, notes=notes)
