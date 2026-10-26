"""The evaluation receipt — the first shared learning artifact (AL-0, plan §19.2).

One shape for "how did this model perform against its declared target", for every
model family: Hill holdouts, Batch 3 evaluators, and later Game Day calibration,
projection scorecards and playoff calibration.

Rules (each test-pinned in ``tests/model_registry/test_evaluation_receipt.py``):

* **Fixed verdict vocabulary** (:data:`VERDICTS`). A producer's own disposition is
  mapped onto it by its adapter; an unmapped disposition is refused, never
  guessed.
* **A verdict promotes nothing** (A5). ``challenger_better_pending_policy`` is a
  statement about evidence; the receipt carries ``promotes: False`` as a
  constant and names the family policy that would have to act. No code path here
  writes a PROMOTION RECORD or moves a champion pointer.
* **Missing is never zero** (A3). ``n``, coverage and missing counts are explicit.
  ``n`` is an ``int >= 0`` or ``None`` with a stated reason — never coerced. An
  EMPTY cohort (``n == 0``, or a producer-stated insufficient stratum) yields
  ``insufficient_sample`` with no metric at all, not a 0 score. When the overall
  population is empty the receipt's verdict is ``insufficient_sample`` whatever
  the producer proposed, and the override is recorded.
* **Pins are explicit.** Each input pin is a value or an explicit
  ``not_applicable`` / ``unobserved`` with a reason.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Mapping, Sequence

from src.model_registry.learning_receipt import (
    KIND_EVALUATION,
    LearningReceipt,
    NotApplicable,
    ReceiptError,
    Slot,
    StoreRef,
    Unobserved,
    build_receipt,
    iso,
)

VERDICT_CHAMPION_RETAINED = "champion_retained"
VERDICT_CHALLENGER_BETTER = "challenger_better_pending_policy"
VERDICT_INCONCLUSIVE = "inconclusive"
VERDICT_INSUFFICIENT = "insufficient_sample"

#: The fixed verdict vocabulary of plan §19.2. Nothing else is a verdict.
VERDICTS: tuple[str, ...] = (
    VERDICT_CHAMPION_RETAINED,
    VERDICT_CHALLENGER_BETTER,
    VERDICT_INCONCLUSIVE,
    VERDICT_INSUFFICIENT,
)

ROLES: tuple[str, ...] = ("champion", "challenger", "baseline")

#: Holdout designs (plan §19.2). ``source_family`` covers "boards from families the
#: fit never read" (Hill) and leave-family-out targets (#1589).
HOLDOUT_DESIGNS: frozenset[str] = frozenset({"chronological", "league", "player", "source_family"})

COHORT_OK = "ok"
COHORT_INSUFFICIENT = "insufficient_sample"

#: The input pins every evaluation must account for (plan §19.2).
PIN_KEYS: tuple[str, ...] = ("codeSha", "sourceHashes", "snapshotHash", "scoringFingerprint")


@dataclass(frozen=True)
class Estimate:
    """A point estimate with its uncertainty, or an explicit absence of one."""

    point: float
    interval: tuple[float, float] | None = None
    level: float | None = None  # e.g. 0.90
    method: str | None = None  # e.g. "date-block bootstrap, 8 blocks x 400"

    def __post_init__(self) -> None:
        if not isinstance(self.point, (int, float)) or isinstance(self.point, bool):
            raise ReceiptError(f"estimate point must be a number, not {self.point!r}")
        if not math.isfinite(float(self.point)):
            raise ReceiptError("estimate point must be finite")
        if self.interval is not None:
            lo, hi = self.interval
            if lo is None or hi is None or not (float(lo) <= float(hi)):
                raise ReceiptError(f"interval must be (lo <= hi), not {self.interval!r}")
            if self.method is None or self.level is None:
                raise ReceiptError("an interval must state its level and method")

    def to_dict(self) -> dict[str, Any]:
        return {
            "point": float(self.point),
            "interval": None if self.interval is None else [float(v) for v in self.interval],
            "level": self.level,
            "method": self.method,
        }


def _check_n(n: Any, what: str) -> int | None:
    if n is None:
        return None
    if isinstance(n, bool) or not isinstance(n, int) or n < 0:
        raise ReceiptError(f"{what} must be an int >= 0 or None, not {n!r}")
    return n


@dataclass(frozen=True)
class CohortResult:
    cohort: Mapping[str, str]
    n: int | None
    status: str
    metrics: Mapping[str, Estimate]
    n_reason: str | None = None  # why n is None
    missing_count: int | None = None
    coverage: float | None = None
    note: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "cohort": dict(sorted(self.cohort.items())),
            "n": self.n,
            "nReason": self.n_reason,
            "status": self.status,
            "metrics": {k: v.to_dict() for k, v in sorted(self.metrics.items())},
            "missingCount": self.missing_count,
            "coverage": self.coverage,
            "note": self.note,
        }


def cohort_result(
    cohort: Mapping[str, str],
    *,
    n: int | None,
    metrics: Mapping[str, Estimate] | None = None,
    n_reason: str | None = None,
    insufficient: bool = False,
    missing_count: int | None = None,
    coverage: float | None = None,
    note: str | None = None,
) -> CohortResult:
    """A3. An empty or producer-declared-insufficient cohort carries NO metric."""
    n_checked = _check_n(n, "cohort n")
    if n_checked is None and not str(n_reason or "").strip():
        raise ReceiptError("a cohort whose n is unknown must say why (missing is never zero)")
    _check_n(missing_count, "missing count")
    if coverage is not None and not (0.0 <= float(coverage) <= 1.0):
        raise ReceiptError(f"coverage must be in [0, 1], not {coverage!r}")
    if insufficient or n_checked == 0:
        return CohortResult(
            cohort=dict(cohort),
            n=n_checked,
            status=COHORT_INSUFFICIENT,
            metrics={},
            n_reason=n_reason,
            missing_count=missing_count,
            coverage=coverage,
            note=note,
        )
    if not metrics:
        raise ReceiptError("a cohort with a sample must report at least one metric")
    return CohortResult(
        cohort=dict(cohort),
        n=n_checked,
        status=COHORT_OK,
        metrics=dict(metrics),
        n_reason=n_reason,
        missing_count=missing_count,
        coverage=coverage,
        note=note,
    )


def _pin_dict(pins: Mapping[str, Any]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for key in PIN_KEYS:
        if key not in pins:
            raise ReceiptError(f"input pin {key!r} must be stated (a value or an explicit absence)")
        value = pins[key]
        if isinstance(value, (Unobserved, NotApplicable)):
            out[key] = value.to_dict()
        elif value is None or value == "" or value == {}:
            raise ReceiptError(f"input pin {key!r} is empty; say not_applicable or unobserved")
        else:
            out[key] = value
    return out


@dataclass(frozen=True)
class EvaluationReceipt:
    producer: str
    native_id: str
    model_family: str
    model_version_id: str
    role: str
    task: str
    target: str
    horizon: str
    cohort_keys: Sequence[str]
    cutoff: datetime | None
    point_in_time_rule: str
    feature_manifest_hash: str | Unobserved | NotApplicable
    input_pins: Mapping[str, Any]
    prediction_set: Slot
    outcome_set: Slot
    preregistration: Slot
    overall: CohortResult
    cohorts: Sequence[CohortResult]
    holdout_design: Sequence[str]
    proposed_verdict: str
    verdict_basis: str
    champion_model_version_id: str | None = None
    #: The instant of the event the target measures (e.g. a game's final, the
    #: end of a forecast horizon). Carried onto the learning receipt's
    #: ``targetEventAt`` so an ``outcome`` ref is checked as dated at or after
    #: the target event and not before the prediction cutoff. ``None`` when the
    #: evaluation has no single target instant — then no outcome ref is accepted.
    target_event_at: datetime | None = None
    family_policy: str = "explicit owner approval (no automatic policy for this family)"
    refs: Sequence[StoreRef] = ()
    extra: Mapping[str, Any] = field(default_factory=dict)

    @property
    def verdict(self) -> str:
        """A3: an empty overall population is ``insufficient_sample``, whatever was proposed."""
        if self.overall.status == COHORT_INSUFFICIENT:
            return VERDICT_INSUFFICIENT
        return self.proposed_verdict

    def body(self) -> dict[str, Any]:
        if self.role not in ROLES:
            raise ReceiptError(f"role must be one of {ROLES}, not {self.role!r}")
        if self.proposed_verdict not in VERDICTS:
            raise ReceiptError(f"verdict must be one of {VERDICTS}, not {self.proposed_verdict!r}")
        bad = [d for d in self.holdout_design if d not in HOLDOUT_DESIGNS]
        if not self.holdout_design or bad:
            raise ReceiptError(
                f"holdout design must be drawn from {sorted(HOLDOUT_DESIGNS)}: {bad}"
            )
        if not str(self.point_in_time_rule or "").strip():
            raise ReceiptError("an evaluation must state the point-in-time rule it applied")
        fmh = self.feature_manifest_hash
        verdict = self.verdict
        return {
            "role": self.role,
            "championModelVersionId": self.champion_model_version_id,
            "task": self.task,
            "target": self.target,
            "horizon": self.horizon,
            "cohortKeys": list(self.cohort_keys),
            "cutoff": iso(self.cutoff),
            "targetEventAt": iso(self.target_event_at),
            "pointInTimeRule": self.point_in_time_rule,
            "featureManifestHash": fmh if isinstance(fmh, str) else fmh.to_dict(),
            "inputPins": _pin_dict(self.input_pins),
            "overallResult": self.overall.to_dict(),
            "cohorts": [c.to_dict() for c in self.cohorts],
            "holdoutDesign": sorted(self.holdout_design),
            "verdict": verdict,
            "proposedVerdict": self.proposed_verdict,
            "verdictOverridden": verdict != self.proposed_verdict,
            "verdictBasis": self.verdict_basis,
            # A5: evidence, never activation.
            "promotes": False,
            "promotionRequires": self.family_policy,
            "extra": dict(self.extra),
        }

    def to_learning_receipt(self) -> LearningReceipt:
        return build_receipt(
            kind=KIND_EVALUATION,
            producer=self.producer,
            native_id=self.native_id,
            model_family=self.model_family,
            model_version_id=self.model_version_id,
            cutoff=self.cutoff,
            target_event_at=self.target_event_at,
            slots={
                "predictionSet": self.prediction_set,
                "outcomeSet": self.outcome_set,
                "preregistration": self.preregistration,
            },
            refs=tuple(self.refs),
            body=self.body(),
        )
