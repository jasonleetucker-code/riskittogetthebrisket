"""The shared learning receipt (Adaptive Learning AL-0, plan §19 / §23).

What this is
────────────
One small, versioned contract that every adaptive system in Calculator uses to say
*what was known, what was predicted, what happened, and how well it did* — without
a parallel platform, a universal table, or a feature store. Observations stay in
their native canonical stores. A receipt only POINTS into them
(:class:`StoreRef`): ``(store, key, knownAt, fidelity)``, never a copy of the
observation.

Twelve kinds (:data:`RECEIPT_KINDS`, plan §19.1). Every kind slot is either a
reference into a registered native store (:data:`NATIVE_STORES`) or an explicit
:class:`Unobserved` / :class:`NotApplicable` with a reason. There is no third,
fabricated state.

Invariants enforced here, each pinned by ``tests/model_registry/test_learning_receipt.py``:

* **Point in time** (A1). A reference whose role is ``input`` must carry a proven
  instant at or before the receipt's ``cutoff``; a reference whose role is
  ``outcome`` must be at or after the receipt's ``targetEventAt`` AND not before
  its ``cutoff`` (and a target event may not precede the cutoff). An instant
  that cannot be proven (no time component, unparseable, naive) is refused — the
  same rule as ``src.history.store.has_time_component`` and
  ``training_run._require_aware``: an unknown instant cannot be proven to precede
  anything.
* **The role is not the caller's to choose** (A1). ``artifact`` — the one role
  the time guard does not bound, because a producer's own output is legitimately
  written after its cutoff — is accepted only for a ref into a producer ARTIFACT
  store (:data:`ARTIFACT_STORES`). A temporal-ledger, dataset-state, board,
  panel or repo-file ref can never be an ``artifact``, so a future-dated
  observation cannot be relabelled past the guard. OBSERVATION and FEATURES
  receipts — the receipts that describe what fed a model — accept ``input``
  refs only; no pre-cutoff kind (:data:`PRE_CUTOFF_KINDS`) may carry an
  ``outcome`` ref.
* **Corrections are revisions, never overwrites** (plan §19.1 ``outcomeRevision``).
  A receipt's identity is ``(kind, producer, nativeId)`` plus its ``revision``
  when it has one. A corrected outcome is a NEW receipt with a new ``revision``,
  linked to the original through ``receipt_store.record_correction`` — the
  precedent is ``src.history.store.record_correction``: append-only, a reason is
  mandatory, the original stays stored and readable, and a superseded receipt
  cannot supersede.
* **Fidelity is the as-of vocabulary** of ``src.history.asof``. ``reconstructed``
  is refused: no approved reconstruction methodology exists (C1-U4), and a
  receipt must never present a re-derived value as an observation.
* **No promotion** (A5). A ``PROMOTION_RECORD`` receipt cannot be built in AL-0.
  Promotion belongs to a model family's own approved policy (Hill Autopilot,
  Batch 3 §N, or explicit owner approval), never to the learning substrate.
* **Drift triggers nothing** (A8). A drift receipt carries exactly one of the six
  classes in :data:`DRIFT_CLASSES` and a fixed ``automaticActions: []``.
* **Facts and rules do not learn** (plan §18, A7). This module reads nothing from,
  and writes nothing to, canonical value, league config, identity mappings or
  contract stamps. ``tests/model_registry/test_learning_boundary.py`` proves it.

Determinism (A10). A receipt's identity (``receiptId``) and ``contentHash`` are
functions of its content only — no wall clock. Re-deriving receipts from the same
pinned producer evidence gives byte-identical receipts.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Mapping, Sequence

from src.history.asof import (
    FIDELITY_EXACT,
    FIDELITY_NEAREST_PRIOR,
    FIDELITY_PARTIAL,
    FIDELITY_RECONSTRUCTED,
    FIDELITY_UNAVAILABLE,
)
from src.history.store import has_time_component

#: Bump on any change to a receipt's serialized shape.
RECEIPT_SCHEMA_VERSION: int = 1

KIND_OBSERVATION = "OBSERVATION"
KIND_FEATURES = "FEATURES"
KIND_PREDICTION = "PREDICTION"
KIND_DECISION = "DECISION"
KIND_ACTION = "ACTION"
KIND_NON_ACTION = "NON_ACTION"
KIND_MODEL = "MODEL"
KIND_OUTCOME = "OUTCOME"
KIND_EVALUATION = "EVALUATION"
KIND_CHALLENGER = "CHALLENGER"
KIND_PROMOTION_RECORD = "PROMOTION_RECORD"
KIND_DRIFT = "DRIFT"

#: The twelve receipt kinds of plan §19.1, in loop order.
RECEIPT_KINDS: tuple[str, ...] = (
    KIND_OBSERVATION,
    KIND_FEATURES,
    KIND_PREDICTION,
    KIND_DECISION,
    KIND_ACTION,
    KIND_NON_ACTION,
    KIND_MODEL,
    KIND_OUTCOME,
    KIND_EVALUATION,
    KIND_CHALLENGER,
    KIND_PROMOTION_RECORD,
    KIND_DRIFT,
)

#: Kinds AL-0 may build. ``PROMOTION_RECORD`` is defined (so the vocabulary is
#: complete and stable) but writable only by a family's approved promotion policy,
#: which does not live in the learning substrate.
AL0_BUILDABLE_KINDS: frozenset[str] = frozenset(RECEIPT_KINDS) - {KIND_PROMOTION_RECORD}

#: Fidelity vocabulary — exactly ``src.history.asof``'s, minus ``reconstructed``.
ALLOWED_FIDELITY: frozenset[str] = frozenset(
    {FIDELITY_EXACT, FIDELITY_NEAREST_PRIOR, FIDELITY_PARTIAL, FIDELITY_UNAVAILABLE}
)

ROLE_INPUT = "input"  # known before the cutoff, consumed by the model
ROLE_ARTIFACT = "artifact"  # the producer's own output (prediction set, run record, ...)
ROLE_OUTCOME = "outcome"  # what happened after the target event
REF_ROLES: frozenset[str] = frozenset({ROLE_INPUT, ROLE_ARTIFACT, ROLE_OUTCOME})

#: Native stores a receipt may point into, and the module that owns each. A
#: reference to a store not listed here is refused: a receipt must be resolvable
#: by someone who has never seen the producer.
NATIVE_STORES: Mapping[str, str] = {
    # temporal ledger (values / ranks / picks as of a date)
    "temporal_ledger": "src.history.store",
    # a file at an exact git commit, or a content-addressed repo file
    "repo_file": "git (path@sha256 content address)",
    # Hill model registry document (versions, holdouts, champion pointer)
    "model_registry": "src.model_registry.versioning",
    # Hill pinned training-run records / summaries
    "hill_training_run": "src.model_registry.training_run",
    # Hill board snapshot pinned by a training run
    "board_snapshot": "src.model_registry.training_run (snapshot pin)",
    # #1589 source-quality: archive lines, full results, point-in-time panel
    "source_quality_evaluations": "src.source_quality.evaluate.archive_records",
    "source_quality_results": "scripts/source_quality_eval.py",
    "source_quality_panel": "src.source_quality.panel.ObservationPanel",
    # #1590 robust-filter shadow ledger (registered for AL-1a; no adapter in AL-0)
    "robust_filter_shadow_ledger": "src.robust_filter_shadow.ledger",
    # Source dataset state clocks
    "dataset_state": "src.sources.dataset_state",
    # a producer's preregistration document, pinned by sha256 (and commit) by that producer
    "preregistration": "the producer's own preregistration pin (e.g. source-quality pins.preregistration)",
}

#: Stores that hold a PRODUCER'S OWN OUTPUT (plan §19.1: the model registry,
#: training-run records, evaluation archives and results, shadow ledgers, and the
#: preregistration a producer pins). Only these may be referenced with role
#: ``artifact``. Every other store holds evidence that existed in the world —
#: observations, source data, boards, panels, dataset clocks, repo files — and a
#: ref into it is an ``input`` (bounded by the cutoff) or an ``outcome`` (bounded
#: by the target event); it is never exempt from the time guard.
ARTIFACT_STORES: frozenset[str] = frozenset(
    {
        "model_registry",
        "hill_training_run",
        "source_quality_evaluations",
        "source_quality_results",
        "robust_filter_shadow_ledger",
        "preregistration",
    }
)

#: Kinds whose refs describe what FED a model; every ref must be ``input``.
INPUT_ONLY_KINDS: frozenset[str] = frozenset({KIND_OBSERVATION, KIND_FEATURES})
#: Kinds made at or before their cutoff; none may point at an ``outcome``.
PRE_CUTOFF_KINDS: frozenset[str] = frozenset(
    {KIND_OBSERVATION, KIND_FEATURES, KIND_PREDICTION, KIND_DECISION}
)

#: The six drift classes of plan §20 — exactly these, and nothing else.
DRIFT_CLASSES: tuple[str, ...] = (
    "schema_data",
    "source",
    "calibration",
    "performance",
    "behavioral",
    "season_regime",
)


class ReceiptError(ValueError):
    """A receipt that must not exist (fail closed)."""


class PointInTimeViolation(ReceiptError):
    """A reference known after the cutoff, or an outcome dated before its target."""


class PromotionNotPermitted(ReceiptError):
    """AL-0 never writes a PROMOTION RECORD (plan §23 A5)."""


# ── time ─────────────────────────────────────────────────────────────────────


def parse_instant(value: Any, *, what: str) -> datetime:
    """A proven, timezone-aware UTC instant, or :class:`ReceiptError`.

    Date-only and naive stamps are refused rather than assumed: a date parses as
    midnight and would claim to precede every instant of its own day."""
    if isinstance(value, datetime):
        if value.tzinfo is None:
            raise ReceiptError(f"{what}: naive datetime; an instant must carry a zone")
        return value.astimezone(timezone.utc)
    text = str(value or "").strip()
    if not has_time_component(text.replace("Z", "+00:00")):
        raise ReceiptError(f"{what}: {value!r} is not a proven instant (no time component)")
    dt = datetime.fromisoformat(text.replace("Z", "+00:00"))
    if dt.tzinfo is None:
        raise ReceiptError(f"{what}: {value!r} has no zone; an instant must carry a zone")
    return dt.astimezone(timezone.utc)


def iso(dt: datetime | None) -> str | None:
    return None if dt is None else dt.astimezone(timezone.utc).isoformat()


# ── references ───────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class StoreRef:
    """A typed pointer into a native store. Never a copy of the observation."""

    store: str
    key: str
    role: str
    known_at: datetime | None
    fidelity: str
    basis: str | None = None  # how known_at was established
    revision: str | None = None  # e.g. outcomeRevision: corrections are revisions

    def __post_init__(self) -> None:
        if self.store not in NATIVE_STORES:
            raise ReceiptError(f"unregistered native store {self.store!r}")
        if not str(self.key or "").strip():
            raise ReceiptError("a store reference needs a key")
        if self.role not in REF_ROLES:
            raise ReceiptError(f"unknown reference role {self.role!r}")
        if self.role == ROLE_ARTIFACT and self.store not in ARTIFACT_STORES:
            raise ReceiptError(
                f"a {self.store!r} ref cannot be an 'artifact': only a producer's own artifact "
                f"stores {sorted(ARTIFACT_STORES)} are exempt from the point-in-time guard; "
                "evidence from any other store is an 'input' or an 'outcome'"
            )
        if self.fidelity == FIDELITY_RECONSTRUCTED:
            raise ReceiptError(
                "fidelity 'reconstructed' is refused: no approved reconstruction "
                "methodology exists, and a re-derived value is not an observation"
            )
        if self.fidelity not in ALLOWED_FIDELITY:
            raise ReceiptError(f"unknown fidelity {self.fidelity!r}")
        if self.known_at is not None and self.known_at.tzinfo is None:
            raise ReceiptError("known_at must be timezone-aware")
        if self.known_at is None and self.fidelity != FIDELITY_UNAVAILABLE:
            raise ReceiptError("a reference without known_at must have fidelity 'unavailable'")

    def to_dict(self) -> dict[str, Any]:
        return {
            "store": self.store,
            "key": self.key,
            "role": self.role,
            "knownAt": iso(self.known_at),
            "fidelity": self.fidelity,
            "basis": self.basis,
            "revision": self.revision,
        }


@dataclass(frozen=True)
class Unobserved:
    """The slot exists but its evidence could not be observed. Never inferred."""

    reason: str

    def to_dict(self) -> dict[str, Any]:
        return {"state": "unobserved", "reason": self.reason}


@dataclass(frozen=True)
class NotApplicable:
    """The slot does not apply to this producer."""

    reason: str

    def to_dict(self) -> dict[str, Any]:
        return {"state": "not_applicable", "reason": self.reason}


Slot = StoreRef | Unobserved | NotApplicable


def slot_to_dict(slot: Slot) -> dict[str, Any]:
    if not isinstance(slot, (StoreRef, Unobserved, NotApplicable)):
        raise ReceiptError(f"a slot is a StoreRef, Unobserved or NotApplicable, not {slot!r}")
    if isinstance(slot, (Unobserved, NotApplicable)) and not str(slot.reason or "").strip():
        raise ReceiptError("an unobserved / not-applicable slot must say why")
    return slot.to_dict()


# ── identifiers ──────────────────────────────────────────────────────────────


def canonical_json(obj: Any) -> str:
    return json.dumps(
        obj, sort_keys=True, separators=(",", ":"), ensure_ascii=True, allow_nan=False
    )


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _token(value: str, what: str) -> str:
    text = str(value or "").strip()
    if not text or ":" in text or any(c.isspace() for c in text):
        raise ReceiptError(f"{what} must be a non-empty token without ':' or whitespace: {value!r}")
    return text


def model_version_id(model_family: str, version_token: str) -> str:
    """``mv:<family>:<token>`` — the generic, registry-backed model identity."""
    return f"mv:{_token(model_family, 'modelFamily')}:{_token(version_token, 'version token')}"


def prediction_id(producer: str, native_id: str) -> str:
    """A stable prediction identity minted from the producer's OWN native id.

    Deterministic: the same producer output always mints the same id, so a
    re-ingest is idempotent rather than a second prediction."""
    return f"pred:{_token(producer, 'producer')}:{sha256_text(str(native_id))[:24]}"


# ── the receipt ──────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class LearningReceipt:
    kind: str
    producer: str
    native_id: str  # the producer's own identity for what this receipt describes
    model_family: str
    model_version_id: str | None
    slots: Mapping[str, Slot]
    body: Mapping[str, Any] = field(default_factory=dict)
    refs: Sequence[StoreRef] = ()
    cutoff: datetime | None = None
    target_event_at: datetime | None = None
    prediction_id: str | None = None
    #: ``None`` for an original. A correction carries a new, non-empty revision
    #: (e.g. an ``outcomeRevision``) and therefore a distinct identity.
    revision: str | None = None

    @property
    def receipt_id(self) -> str:
        """Identity: kind + producer + native id (+ revision). No content, no clock."""
        basis = f"{self.kind}|{self.producer}|{self.native_id}"
        if self.revision is not None:
            basis += f"|rev={self.revision}"
        return f"rcpt:{self.kind.lower()}:{sha256_text(basis)[:32]}"

    def to_dict(self) -> dict[str, Any]:
        return {
            "schemaVersion": RECEIPT_SCHEMA_VERSION,
            "receiptId": self.receipt_id,
            "kind": self.kind,
            "producer": self.producer,
            "nativeId": self.native_id,
            "modelFamily": self.model_family,
            "modelVersionId": self.model_version_id,
            "predictionId": self.prediction_id,
            "revision": self.revision,
            "cutoff": iso(self.cutoff),
            "targetEventAt": iso(self.target_event_at),
            "slots": {k: slot_to_dict(v) for k, v in sorted(self.slots.items())},
            "refs": [r.to_dict() for r in self.refs],
            "body": dict(self.body),
        }

    def content_hash(self) -> str:
        return sha256_text(canonical_json(self.to_dict()))


def _all_refs(receipt: LearningReceipt) -> list[StoreRef]:
    return [*receipt.refs, *(s for s in receipt.slots.values() if isinstance(s, StoreRef))]


def check_point_in_time(receipt: LearningReceipt) -> None:
    """A1. Nothing known after the cutoff is selectable; no outcome precedes its target.

    The declared role is checked against the receipt kind BEFORE any time
    comparison, so a role cannot be chosen to dodge the comparison."""
    if (
        receipt.cutoff is not None
        and receipt.target_event_at is not None
        and receipt.target_event_at < receipt.cutoff
    ):
        raise PointInTimeViolation(
            f"target event {iso(receipt.target_event_at)} precedes the cutoff "
            f"{iso(receipt.cutoff)}: a prediction cannot be made after the event it predicts"
        )
    for ref in _all_refs(receipt):
        if receipt.kind in INPUT_ONLY_KINDS and ref.role != ROLE_INPUT:
            raise PointInTimeViolation(
                f"{receipt.kind} ref {ref.store}:{ref.key} is {ref.role!r}; everything an "
                f"{receipt.kind} receipt points at fed the model and must be an 'input'"
            )
        if receipt.kind in PRE_CUTOFF_KINDS and ref.role == ROLE_OUTCOME:
            raise PointInTimeViolation(
                f"a {receipt.kind} receipt cannot point at outcome {ref.store}:{ref.key}"
            )
        if ref.role == ROLE_INPUT:
            if receipt.cutoff is None:
                raise PointInTimeViolation(
                    f"{ref.store}:{ref.key} is an input but the receipt has no cutoff to bound it"
                )
            if ref.known_at is None:
                raise PointInTimeViolation(
                    f"input {ref.store}:{ref.key} has no proven knownAt; an unknown instant "
                    "cannot be proven to precede the cutoff"
                )
            if ref.known_at > receipt.cutoff:
                raise PointInTimeViolation(
                    f"input {ref.store}:{ref.key} known at {iso(ref.known_at)} is after the "
                    f"cutoff {iso(receipt.cutoff)}"
                )
        elif ref.role == ROLE_OUTCOME:
            if receipt.target_event_at is None:
                raise PointInTimeViolation(
                    f"outcome {ref.store}:{ref.key} needs the receipt's targetEventAt"
                )
            if ref.known_at is None:
                raise PointInTimeViolation(f"outcome {ref.store}:{ref.key} has no proven knownAt")
            if ref.known_at < receipt.target_event_at:
                raise PointInTimeViolation(
                    f"outcome {ref.store}:{ref.key} dated {iso(ref.known_at)} precedes its "
                    f"target event {iso(receipt.target_event_at)}"
                )
            if receipt.cutoff is not None and ref.known_at < receipt.cutoff:
                raise PointInTimeViolation(
                    f"outcome {ref.store}:{ref.key} dated {iso(ref.known_at)} precedes the "
                    f"prediction cutoff {iso(receipt.cutoff)}"
                )


def validate_receipt(receipt: LearningReceipt) -> LearningReceipt:
    """Every structural rule, then the point-in-time guard. Returns the receipt."""
    if receipt.kind not in RECEIPT_KINDS:
        raise ReceiptError(f"unknown receipt kind {receipt.kind!r}")
    if receipt.kind == KIND_PROMOTION_RECORD:
        raise PromotionNotPermitted(
            "AL-0 writes no PROMOTION RECORD; promotion belongs to the family's approved "
            "policy (Hill Autopilot, Batch 3 §N, or explicit owner approval)"
        )
    _token(receipt.producer, "producer")
    _token(receipt.model_family, "modelFamily")
    if not str(receipt.native_id or "").strip():
        raise ReceiptError("a receipt needs the producer's native id")
    if receipt.revision is not None and not str(receipt.revision).strip():
        raise ReceiptError("a revision, when present, must be non-empty")
    if receipt.model_version_id is not None and not receipt.model_version_id.startswith(
        f"mv:{receipt.model_family}:"
    ):
        raise ReceiptError("modelVersionId must belong to the receipt's modelFamily")
    for at, what in ((receipt.cutoff, "cutoff"), (receipt.target_event_at, "targetEventAt")):
        if at is not None and at.tzinfo is None:
            raise ReceiptError(f"{what} must be timezone-aware")
    if not receipt.slots:
        raise ReceiptError("a receipt must declare its slots (reference or explicit absence)")
    receipt.to_dict()  # every slot well-formed, body JSON-serializable
    canonical_json(receipt.to_dict())
    check_point_in_time(receipt)
    return receipt


def build_receipt(**kwargs: Any) -> LearningReceipt:
    """Construct and validate. The only sanctioned way to make a receipt."""
    return validate_receipt(LearningReceipt(**kwargs))


# ── drift ────────────────────────────────────────────────────────────────────


def build_drift_receipt(
    *,
    producer: str,
    model_family: str,
    drift_class: str,
    signal: str,
    observed_at: datetime,
    evidence: Sequence[StoreRef],
    affected_model_version_id: str | None = None,
    detail: Mapping[str, Any] | None = None,
) -> LearningReceipt:
    """A8. One of the six classes; reevaluation is RECOMMENDED; nothing is triggered.

    ``observed_at`` is the receipt's cutoff: drift observed at T may rest only on
    evidence known at or before T.

    The receipt is inert data. This function calls nothing, schedules nothing and
    returns the receipt — drift opens an evaluation cycle only when a human or an
    approved policy reads it (plan §20 rule 7)."""
    if drift_class not in DRIFT_CLASSES:
        raise ReceiptError(f"drift class must be one of {DRIFT_CLASSES}, not {drift_class!r}")
    if not evidence:
        raise ReceiptError("a drift receipt must point at the evidence that shows the drift")
    at = parse_instant(observed_at, what="observedAt")
    return build_receipt(
        kind=KIND_DRIFT,
        producer=producer,
        native_id=f"{drift_class}|{signal}|{iso(at)}",
        model_family=model_family,
        model_version_id=affected_model_version_id,
        cutoff=at,
        slots={"evidence": evidence[0]},
        refs=tuple(evidence[1:]),
        body={
            "driftClass": drift_class,
            "signal": signal,
            "observedAt": iso(at),
            "response": "reevaluation_recommended",
            "automaticActions": [],
            "detail": dict(detail or {}),
        },
    )
