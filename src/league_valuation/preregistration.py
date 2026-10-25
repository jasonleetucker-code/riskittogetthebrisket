"""Preregistration and evaluation receipts for the league fair value challenger.

Machine-readable twin of
``docs/valuation/evidence/league_fair_value_v1/PREREGISTRATION.md`` (a test
pins the two together). Thresholds are TO-FREEZE: until they are frozen and the
preregistration is committed, every receipt says ``insufficient_sample`` --
whatever the results look like. That is the anti-adaptive rule: a threshold
chosen after seeing the holdout is not a threshold.

Receipts are ``src.model_registry.evaluation_receipt.EvaluationReceipt``
verbatim, so ``promotes`` is the constant ``False`` and the verdict is drawn
from ``evaluation_receipt.VERDICTS`` only. Preregistered dispositions map::

    ELIGIBLE      -> challenger_better_pending_policy
    NOT_ELIGIBLE  -> champion_retained
    INSUFFICIENT  -> insufficient_sample
    INCONCLUSIVE  -> inconclusive

The PRIMARY metric is a dynasty-horizon target. Forward rest-of-season realized
points and future market movement are SECONDARY and descriptive: they are
carried in ``extra`` and can never move a verdict (ROS favours the
projection-built challenger; market movement is circular with the champion).
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Mapping

from src.league_valuation.contracts import MODEL_VERSION
from src.model_registry.evaluation_receipt import (
    VERDICT_CHALLENGER_BETTER,
    VERDICT_CHAMPION_RETAINED,
    VERDICT_INCONCLUSIVE,
    VERDICT_INSUFFICIENT,
    VERDICTS,
    EvaluationReceipt,
    Estimate,
    cohort_result,
)
from src.model_registry.learning_receipt import (
    NotApplicable,
    ReceiptError,
    StoreRef,
    Unobserved,
    model_version_id,
)

MODEL_FAMILY = "league_fair_value"
PRODUCER = "league_fair_value_shadow"
PREREGISTRATION_PATH = "docs/valuation/evidence/league_fair_value_v1/PREREGISTRATION.md"

#: The one primary metric (dynasty horizon).
PRIMARY_METRIC = "within_position_spearman_delta_vs_canonical_realized_por_2plus_seasons"
PRIMARY_TARGET = (
    "realized league-scored points over replacement summed over at least 2 forward "
    "seasons (each season scored with its own card), or an owner-approved independent "
    "target registered through model_registry.independent_validation"
)
#: Descriptive only; never a gate.
SECONDARY_METRICS: tuple[str, ...] = (
    "forward_ros_realized_points_spearman_delta",
    "future_market_movement_spearman_delta",
)
MIN_FORWARD_SEASONS = 2
COHORTS: tuple[str, ...] = ("QB", "RB", "WR", "TE", "DL", "LB", "DB")

#: Owner preconditions recorded before ANY promotion path. Both start unrecorded.
OWNER_PRECONDITIONS: tuple[str, ...] = (
    "projectionUtilityInDynastyRuling",
    "canonicalIdentityArchitecture",
)

#: Fields that must be fixed before the holdout is examined.
TO_FREEZE_FIELDS: tuple[str, ...] = (
    "min_ci_lower_bound",
    "ci_level",
    "bootstrap_iterations",
    "min_n_per_cohort",
    "max_cohort_regression",
    "holdout_window",
    "preregistration_commit",
    "preregistration_committed_at",
)

ELIGIBLE = "ELIGIBLE"
NOT_ELIGIBLE = "NOT_ELIGIBLE"
INSUFFICIENT = "INSUFFICIENT"
INCONCLUSIVE = "INCONCLUSIVE"
DISPOSITION_TO_VERDICT: Mapping[str, str] = {
    ELIGIBLE: VERDICT_CHALLENGER_BETTER,
    NOT_ELIGIBLE: VERDICT_CHAMPION_RETAINED,
    INSUFFICIENT: VERDICT_INSUFFICIENT,
    INCONCLUSIVE: VERDICT_INCONCLUSIVE,
}
assert set(DISPOSITION_TO_VERDICT.values()) <= set(VERDICTS)

#: Extended pins every receipt must state beyond ``evaluation_receipt.PIN_KEYS``.
EXTENDED_PIN_KEYS: tuple[str, ...] = (
    "formatFingerprint",
    "bdvmParamSetId",
    "hillMasterParamSet",
    "challengerParamSetId",
)

_FULL_SHA = re.compile(r"[0-9a-f]{40}")


class PreregistrationError(ValueError):
    """A preregistration that must not be used (fail closed)."""


def _unrecorded_preconditions() -> dict[str, str | None]:
    return {k: None for k in OWNER_PRECONDITIONS}


@dataclass(frozen=True)
class GateThresholds:
    """Preregistered gate. ``frozen=False`` (the committed state) gates nothing.

    Freezing requires every :data:`TO_FREEZE_FIELDS` value, a full 40-hex
    preregistration commit and an aware commit instant. Git ancestry (strict
    ancestor of HEAD, blob unchanged) is verified by the evaluator through
    ``model_registry.independent_validation.git_preregistration_committed``.
    """

    frozen: bool = False
    primary_metric: str = PRIMARY_METRIC
    forward_seasons: int = MIN_FORWARD_SEASONS
    min_ci_lower_bound: float | None = None
    ci_level: float | None = None
    bootstrap_iterations: int | None = None
    min_n_per_cohort: int | None = None
    max_cohort_regression: float | None = None
    holdout_window: str | None = None
    preregistration_path: str = PREREGISTRATION_PATH
    preregistration_commit: str | None = None
    preregistration_committed_at: datetime | None = None
    owner_preconditions: Mapping[str, str | None] = field(default_factory=_unrecorded_preconditions)

    def __post_init__(self) -> None:
        if self.primary_metric != PRIMARY_METRIC:
            raise PreregistrationError("the primary metric is fixed by the preregistration")
        if int(self.forward_seasons) < MIN_FORWARD_SEASONS:
            raise PreregistrationError(f"the target spans at least {MIN_FORWARD_SEASONS} seasons")
        if set(self.owner_preconditions) != set(OWNER_PRECONDITIONS):
            raise PreregistrationError(f"owner preconditions are exactly {OWNER_PRECONDITIONS}")
        if not self.frozen:
            return
        unset = [f for f in TO_FREEZE_FIELDS if getattr(self, f) in (None, "")]
        if unset:
            raise PreregistrationError(f"cannot freeze with TO-FREEZE fields unset: {unset}")
        if not _FULL_SHA.fullmatch(str(self.preregistration_commit)):
            raise PreregistrationError("preregistration_commit must be a full 40-hex SHA")
        at = self.preregistration_committed_at
        if not isinstance(at, datetime) or at.tzinfo is None:
            raise PreregistrationError("preregistration_committed_at must be an aware datetime")
        if not (0.5 < float(self.ci_level) < 1.0):  # type: ignore[arg-type]
            raise PreregistrationError("ci_level must lie in (0.5, 1)")
        if int(self.min_n_per_cohort) < 1 or int(self.bootstrap_iterations) < 1:  # type: ignore[arg-type]
            raise PreregistrationError("sample-size fields must be positive")

    @property
    def preconditions_recorded(self) -> bool:
        return all(str(v or "").strip() for v in self.owner_preconditions.values())

    def to_dict(self) -> dict[str, Any]:
        return {
            "frozen": self.frozen,
            "primaryMetric": self.primary_metric,
            "forwardSeasons": self.forward_seasons,
            "minCiLowerBound": self.min_ci_lower_bound,
            "ciLevel": self.ci_level,
            "bootstrapIterations": self.bootstrap_iterations,
            "minNPerCohort": self.min_n_per_cohort,
            "maxCohortRegression": self.max_cohort_regression,
            "holdoutWindow": self.holdout_window,
            "preregistrationPath": self.preregistration_path,
            "preregistrationCommit": self.preregistration_commit,
            "preregistrationCommittedAt": (
                None
                if self.preregistration_committed_at is None
                else self.preregistration_committed_at.isoformat()
            ),
            "ownerPreconditions": dict(sorted(self.owner_preconditions.items())),
        }


#: The committed state: nothing frozen, nothing recorded.
UNFROZEN = GateThresholds()


def _estimate(block: Mapping[str, Any], method_default: str) -> Estimate:
    point = block.get("point")
    lo, hi = block.get("ciLow"), block.get("ciHigh")
    interval = None if lo is None or hi is None else (float(lo), float(hi))
    return Estimate(
        point=float(point),  # type: ignore[arg-type]
        interval=interval,
        level=block.get("level") if interval else None,
        method=(block.get("method") or method_default) if interval else None,
    )


def _finite(x: Any) -> bool:
    return isinstance(x, (int, float)) and not isinstance(x, bool) and math.isfinite(float(x))


def disposition(results: Mapping[str, Any], thresholds: GateThresholds) -> tuple[str, str]:
    """``(disposition, basis)`` under the preregistered gate. Pure."""
    if not thresholds.frozen:
        return INSUFFICIENT, "gate thresholds are TO-FREEZE (unfrozen preregistration)"
    primary = results.get("primary")
    if not isinstance(primary, Mapping) or primary.get("n") is None:
        return INSUFFICIENT, "no primary-metric result"
    if primary.get("metric") != thresholds.primary_metric:
        raise ReceiptError(
            f"primary metric {primary.get('metric')!r} is not the preregistered "
            f"{thresholds.primary_metric!r}"
        )
    min_n = int(thresholds.min_n_per_cohort)  # type: ignore[arg-type]
    cohorts = {str(c.get("position")): c for c in results.get("cohorts") or []}
    thin = [p for p in COHORTS if (cohorts.get(p) or {}).get("n") is None]
    thin += [p for p in COHORTS if p not in thin and int(cohorts[p]["n"]) < min_n]
    if thin:
        return INSUFFICIENT, f"cohorts below the preregistered n ({min_n}): {sorted(thin)}"
    inv = results.get("invariants") or {}
    if int(inv.get("outOfRangeCount", 1)) != 0:
        return NOT_ELIGIBLE, "out-of-range values present"
    if int(inv.get("lineageViolations", 1)) != 0:
        return NOT_ELIGIBLE, "lineage violations present"
    if inv.get("reproducibleFromPins") is not True:
        return NOT_ELIGIBLE, "not byte-reproducible from pins"
    lo, hi = primary.get("ciLow"), primary.get("ciHigh")
    if not (_finite(lo) and _finite(hi)):
        return INSUFFICIENT, "primary metric has no interval"
    tol = float(thresholds.max_cohort_regression)  # type: ignore[arg-type]
    regressed = [p for p in COHORTS if float(cohorts[p].get("point", -math.inf)) < -tol]
    if regressed:
        return NOT_ELIGIBLE, f"cohort regression beyond {tol}: {regressed}"
    if float(hi) < 0.0:
        return NOT_ELIGIBLE, "challenger worse than the champion on the primary metric"
    if float(lo) > float(thresholds.min_ci_lower_bound):  # type: ignore[arg-type]
        if not thresholds.preconditions_recorded:
            return (
                INCONCLUSIVE,
                "primary gate passed but owner preconditions are unrecorded "
                f"({list(OWNER_PRECONDITIONS)})",
            )
        return ELIGIBLE, "primary CI lower bound clears the preregistered bound"
    return INCONCLUSIVE, "primary interval straddles the preregistered bound"


def _pins(pins: Mapping[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    base = {
        k: pins.get(k) for k in ("codeSha", "sourceHashes", "snapshotHash", "scoringFingerprint")
    }
    extended: dict[str, Any] = {}
    for key in EXTENDED_PIN_KEYS:
        value = pins.get(key)
        if isinstance(value, (Unobserved, NotApplicable)):
            extended[key] = value.to_dict()
        elif str(value or "").strip():
            extended[key] = value
        else:
            raise ReceiptError(f"pin {key!r} must be stated (a value or an explicit absence)")
    return base, extended


def build_evaluation_receipt(
    results: Mapping[str, Any],
    thresholds: GateThresholds,
    *,
    pins: Mapping[str, Any],
) -> EvaluationReceipt:
    """One evaluation receipt. Evidence, never activation (``promotes=False``)."""
    base_pins, extended_pins = _pins(pins)
    disp, basis = disposition(results, thresholds)
    verdict = DISPOSITION_TO_VERDICT[disp]
    cutoff = results.get("cutoff")
    if thresholds.frozen:
        at = thresholds.preregistration_committed_at
        if not isinstance(cutoff, datetime) or at is None or at > cutoff:
            raise ReceiptError("a frozen preregistration must precede the evaluated cutoff")
        prereg: Any = StoreRef(
            store="preregistration",
            key=f"{thresholds.preregistration_path}@{thresholds.preregistration_commit}",
            role="input",
            known_at=at,
            fidelity="exact",
            basis="git commit instant of the preregistration",
        )
    else:
        prereg = Unobserved("preregistration thresholds are TO-FREEZE; nothing is frozen yet")

    method = "paired bootstrap over players (board_holdout.paired_bootstrap)"
    primary = results.get("primary") if isinstance(results.get("primary"), Mapping) else None
    if primary is None or primary.get("n") is None or primary.get("point") is None:
        overall = cohort_result(
            {"position": "ALL"},
            n=None if primary is None else primary.get("n"),
            n_reason=(primary or {}).get("nReason")
            or "no forward multi-season outcomes exist yet for this target",
            insufficient=True,
        )
    else:
        overall = cohort_result(
            {"position": "ALL"},
            n=int(primary["n"]),
            metrics={PRIMARY_METRIC: _estimate(primary, method)},
        )
    min_n = thresholds.min_n_per_cohort
    cohorts = []
    for block in results.get("cohorts") or []:
        n = block.get("n")
        thin = n is None or n == 0 or (min_n is not None and int(n) < int(min_n))
        cohorts.append(
            cohort_result(
                {"position": str(block.get("position"))},
                n=n,
                n_reason=block.get("nReason") or ("unobserved" if n is None else None),
                metrics=None if thin else {PRIMARY_METRIC: _estimate(block, method)},
                insufficient=thin,
            )
        )

    param_set = str(extended_pins.get("challengerParamSetId") or "")
    native = str(results.get("nativeId") or f"{MODEL_VERSION}:{param_set}")
    return EvaluationReceipt(
        producer=PRODUCER,
        native_id=native,
        model_family=MODEL_FAMILY,
        model_version_id=model_version_id(MODEL_FAMILY, param_set.replace(":", "-") or "unpinned"),
        role="challenger",
        champion_model_version_id=results.get("championModelVersionId"),
        task="league_fair_value_dynasty_ranking",
        target=PRIMARY_TARGET,
        horizon=f">= {thresholds.forward_seasons} forward seasons",
        cohort_keys=("position",),
        cutoff=cutoff if isinstance(cutoff, datetime) else None,
        target_event_at=results.get("targetEventAt"),
        point_in_time_rule=(
            "board and BDVM snapshot dated strictly before the first forward season's kickoff; "
            "each season scored with its own card; asof knowledge_cutoff; holdout examined once"
        ),
        feature_manifest_hash=Unobserved(
            "feature-dictionary registration lands with the model_lab registration (later PR)"
        ),
        input_pins=base_pins,
        prediction_set=Unobserved("the shadow ledger lands in PR-3"),
        outcome_set=Unobserved("forward multi-season outcomes are not yet observable"),
        preregistration=prereg,
        overall=overall,
        cohorts=tuple(cohorts),
        holdout_design=("chronological",),
        proposed_verdict=verdict,
        verdict_basis=f"{disp}: {basis}",
        family_policy=(
            "explicit owner approval through model_registry.family_gates (registered, passing, "
            "owner-approved gate) after both owner preconditions are recorded; never automatic"
        ),
        extra={
            "disposition": disp,
            "thresholds": thresholds.to_dict(),
            "inputPinsExtended": extended_pins,
            "secondaryDescriptive": dict(results.get("secondary") or {}),
            "secondaryMetricsGate": False,
            "challengerVersion": MODEL_VERSION,
        },
    )
