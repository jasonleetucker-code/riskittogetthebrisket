"""Which promotion gate a model family runs — and the generic gate for non-Hill families.

The defect this closes (chaseTradeMarket P5 / gap G10)
──────────────────────────────────────────────────────
``ModelRegistry.promote()`` ran exactly one gate, ``scope_validation.assert_promotable``,
for every model id. That gate knows the eight Hill constants and nothing else, and
it skips any constant the challenger does not carry (``_changed``: ``if name not in
challenger: continue``). So for any non-Hill model every scope read
``UNCHANGED_FROM_CHAMPION`` and promotion passed **vacuously**; and for a Hill
challenger that simply omitted a constant the champion carries, the omission was
indistinguishable from "unchanged". A gate that cannot refuse is documentation.

What this module decides
────────────────────────
:func:`run_promotion_gate` dispatches on the model, fail closed:

* a model id with a registered :class:`FamilyPromotionPolicy` → the **generic
  gate** (:func:`check_generic_family`);
* otherwise, parameters drawn from the Hill scope constants → the **Hill gate**,
  unchanged in what it validates, plus a parameter-completeness check
  (:func:`check_hill_parameters`): every constant the champion carries must be
  present in the challenger, finite, and nothing undeclared may ride along;
* anything else → **refused**: no gate is registered for it, and an unknown
  family is never promoted by default.

The generic gate refuses unless ALL of:

1. **parameters complete** — every declared parameter present, finite and inside
   its declared bounds; no undeclared parameter. A missing parameter is named in
   the refusal, never skipped.
2. **reproducible evaluation** — the challenger's ``holdout`` carries a
   ``reproducible_evaluation.evaluation_record`` and the caller presents the
   receipt itself; its content hash, model version, champion pairing, verdict
   (``challenger_better_pending_policy``), holdout designs and concrete input pins
   are re-verified (``reproducible_evaluation.verify_evaluation_record``).
3. **owner approval** when the family requires it — a non-empty, recorded
   approval reference. Owner *override* of the evidence is not available for a
   generic family: there is no scope to accept the risk of, only evidence.

The outcome is recorded on the promoted version (``ModelVersion.promotion_gate``),
so a reader sees what the gate concluded, not what it would conclude today.

A promotion is never a vote
───────────────────────────
For ``chase_trade_market`` the champion pointer selects which fitted version
writes the SHADOW board. The source's vote hold is declared in
``src/sources/chase_trade_market.py`` and no registry operation reads or lifts
it (:attr:`FamilyPromotionPolicy.voting_effect`).
"""

from __future__ import annotations

import math
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from typing import Any

from src.model_registry.learning_receipt import LearningReceipt, model_version_id
from src.model_registry.reproducible_evaluation import verify_evaluation_record
from src.model_registry.scope_validation import SCOPE_CONSTANTS, assert_promotable
from src.model_registry.versioning import ModelVersion, RegistryError

GATE_HILL_SCOPE = "hill_scope"
GATE_GENERIC_FAMILY = "generic_family"

#: Every Hill scope constant — the one parameter vocabulary the Hill gate knows.
HILL_PARAMETER_NAMES: frozenset[str] = frozenset(
    name for names in SCOPE_CONSTANTS.values() for name in names
)


@dataclass(frozen=True)
class ParameterSpec:
    """One declared parameter: a name, closed bounds, a unit and why it exists."""

    name: str
    lower: float
    upper: float
    unit: str
    description: str

    def __post_init__(self) -> None:
        if not (math.isfinite(self.lower) and math.isfinite(self.upper)):
            raise ValueError(f"{self.name}: bounds must be finite")
        if self.lower > self.upper:
            raise ValueError(f"{self.name}: lower bound exceeds upper bound")


@dataclass(frozen=True)
class FamilyPromotionPolicy:
    """What a non-Hill model family must show before a version can be champion."""

    model_id: str
    model_family: str
    schema_version: int
    parameters: tuple[ParameterSpec, ...]
    #: Input pins (``evaluation_receipt.PIN_KEYS``) that must be concrete values.
    required_pins: tuple[str, ...]
    #: Of those, pins that may instead be an explicit ``not_applicable`` + reason.
    not_applicable_pins: frozenset[str] = frozenset()
    required_holdout_designs: frozenset[str] = frozenset()
    criterion_name: str = ""
    requires_owner_approval: bool = True
    promotion_policy: str = ""
    voting_effect: str = ""
    notes: tuple[str, ...] = field(default_factory=tuple)

    def __post_init__(self) -> None:
        names = [p.name for p in self.parameters]
        if not names or len(set(names)) != len(names):
            raise ValueError(f"{self.model_id}: parameters must be declared, once each")
        if set(names) & HILL_PARAMETER_NAMES:
            raise ValueError(f"{self.model_id}: a generic family may not reuse Hill names")
        if not self.criterion_name:
            raise ValueError(f"{self.model_id}: name the evaluation criterion")
        if not self.not_applicable_pins <= set(self.required_pins):
            raise ValueError(f"{self.model_id}: not_applicable pins must be required pins")

    def version_id(self, version: int) -> str:
        return model_version_id(self.model_family, f"v{version}")


#: chaseTradeMarket — the trade-derived dynasty valuation source (owner directive
#: 2026-10-19, second version). PROVISIONAL schema v1: the estimator (P6,
#: ``src/trade/market_trade_price_model.py``) owns the final parameter set, and any
#: change to names or bounds is a NEW schema version in a reviewed change.
#:
#: Two bounds are directive clauses made structural rather than tuning:
#: ``min_completed_dynasty_seasons`` is pinned to exactly 3 and
#: ``two_season_cohort_weight`` to exactly 0 — the initial model prioritises
#: leagues with three verified completed seasons, and two-season leagues are a
#: separately reported RESEARCH cohort that may not silently enter a promotable
#: champion. Relaxing either is a policy-schema bump an owner can see.
CHASE_TRADE_MARKET_POLICY = FamilyPromotionPolicy(
    model_id="chase_trade_market",
    model_family="chase_trade_market",
    schema_version=1,
    parameters=(
        ParameterSpec(
            "min_completed_dynasty_seasons",
            3.0,
            3.0,
            "verified completed dynasty seasons via the previous_league_id chain",
            "authoritative-cohort maturity floor (V2 directive section 2); never relaxed silently",
        ),
        ParameterSpec(
            "two_season_cohort_weight",
            0.0,
            0.0,
            "weight multiplier on two-season-league trades",
            "two-season leagues are a separately reported research cohort (V2 section 2)",
        ),
        ParameterSpec(
            "recency_half_life_days",
            7.0,
            1095.0,
            "days, measured from the evidence cutoff (never the wall clock)",
            "trade recency weight 0.5^(age/H) (design section 4.5)",
        ),
        ParameterSpec(
            "lineage_cap",
            0.5,
            10000.0,
            "recency-weighted trades per manager-lineage component",
            "w = min(1, C/W) so no league or manager pair dominates (design section 4.6)",
        ),
        ParameterSpec(
            "huber_delta",
            0.5,
            5.0,
            "robust-loss scale units",
            "Huber transition point for the accepted-trade residual (design section 4.4)",
        ),
        ParameterSpec(
            "prior_tau",
            1e-6,
            1e6,
            "log-value units",
            "consensus-free prior scale, chosen by inner CV on training components "
            "(design section 4.7)",
        ),
    ),
    required_pins=("codeSha", "sourceHashes", "snapshotHash", "scoringFingerprint"),
    # The generic voter is post-stratified to a DECLARED reference format, not one
    # league's scoring card (design section 4.11), so a single scoring fingerprint
    # may legitimately not apply — but it must then say so, with a reason.
    not_applicable_pins=frozenset({"scoringFingerprint"}),
    # V2 directive section 8: separate trades by time AND by underlying league.
    required_holdout_designs=frozenset({"chronological", "league"}),
    criterion_name="heldout_trade_loss",
    requires_owner_approval=True,
    promotion_policy=(
        "explicit owner approval after the preregistered validation "
        "(docs/market_trades, design section 5) — no automatic promotion"
    ),
    voting_effect=(
        "none: the champion selects which fitted version writes the SHADOW board; the "
        "vote hold in src/sources/chase_trade_market.py is not read or lifted by any "
        "registry operation"
    ),
)

GENERIC_FAMILY_POLICIES: Mapping[str, FamilyPromotionPolicy] = {
    CHASE_TRADE_MARKET_POLICY.model_id: CHASE_TRADE_MARKET_POLICY,
}


@dataclass(frozen=True)
class GateOutcome:
    """What the gate concluded; stored on the promoted version."""

    kind: str
    scope_validation: dict[str, str]
    promotion_gate: dict[str, str] | None


def gate_kind_for(
    model_id: str, champion: Mapping[str, float], challenger: Mapping[str, float]
) -> str:
    """The gate ``model_id`` runs. Raises when none is registered (fail closed)."""
    if model_id in GENERIC_FAMILY_POLICIES:
        return GATE_GENERIC_FAMILY
    if (set(champion) | set(challenger)) & HILL_PARAMETER_NAMES:
        return GATE_HILL_SCOPE
    raise RegistryError(
        f"no promotion gate is registered for model {model_id!r} (parameters "
        f"{sorted(challenger)}); an unknown family is never promoted by default — "
        "register a FamilyPromotionPolicy in src/model_registry/promotion_gates.py"
    )


def _finite(value: Any) -> bool:
    try:
        return math.isfinite(float(value))
    except (TypeError, ValueError):
        return False


def check_hill_parameters(champion: Mapping[str, float], challenger: Mapping[str, float]) -> None:
    """No silent skip: every constant the champion carries, finite, nothing undeclared.

    ``scope_validation._changed`` treats a constant absent from the challenger as
    unchanged. That is right for comparing two complete sets and wrong for an
    incomplete one: dropping a constant would ship whatever ``apply`` does with a
    missing key while every scope reads ``UNCHANGED_FROM_CHAMPION``."""
    problems: list[str] = []
    undeclared = sorted(set(challenger) - HILL_PARAMETER_NAMES)
    if undeclared:
        problems.append(f"undeclared parameter(s) {undeclared}")
    missing = sorted(set(champion) & HILL_PARAMETER_NAMES - set(challenger))
    if missing:
        problems.append(
            f"missing parameter(s) {missing}: the champion carries them and the "
            "challenger does not; absence is not 'unchanged'"
        )
    bad = sorted(k for k, v in challenger.items() if not _finite(v))
    if bad:
        problems.append(f"non-finite parameter(s) {bad}")
    if problems:
        raise RegistryError("cannot promote: " + "; ".join(problems))


def check_generic_parameters(
    policy: FamilyPromotionPolicy, challenger: Mapping[str, float]
) -> None:
    """Every declared parameter present, finite and in bounds; nothing undeclared."""
    declared = {p.name: p for p in policy.parameters}
    problems: list[str] = []
    missing = sorted(set(declared) - set(challenger))
    if missing:
        problems.append(f"missing declared parameter(s) {missing}")
    undeclared = sorted(set(challenger) - set(declared))
    if undeclared:
        problems.append(f"undeclared parameter(s) {undeclared}")
    for name in sorted(set(declared) & set(challenger)):
        spec, value = declared[name], challenger[name]
        if not _finite(value):
            problems.append(f"{name} is not finite ({value!r})")
        elif not (spec.lower <= float(value) <= spec.upper):
            problems.append(
                f"{name}={float(value)!r} is outside its declared bounds "
                f"[{spec.lower!r}, {spec.upper!r}] ({spec.description})"
            )
    if problems:
        raise RegistryError(
            f"cannot promote {policy.model_id!r} (policy schema v{policy.schema_version}): "
            + "; ".join(problems)
        )


def check_generic_family(
    policy: FamilyPromotionPolicy,
    *,
    incumbent: ModelVersion | None,
    target: ModelVersion,
    evaluation_receipt: LearningReceipt | None,
    owner_approval: str,
) -> dict[str, str]:
    """The generic gate. Returns the recorded outcome, or raises :class:`RegistryError`."""
    check_generic_parameters(policy, target.params)
    expected = policy.version_id(target.version)
    champion_id = policy.version_id(incumbent.version) if incumbent else None
    problems = verify_evaluation_record(
        target.holdout,
        evaluation_receipt,
        expected_model_version_id=expected,
        expected_champion_model_version_id=champion_id,
        required_pins=policy.required_pins,
        not_applicable_pins=policy.not_applicable_pins,
        required_holdout_designs=policy.required_holdout_designs,
    )
    record = target.holdout or {}
    if not problems and record.get("criterionName") != policy.criterion_name:
        problems.append(
            f"the recorded criterion is {record.get('criterionName')!r}; the family "
            f"is judged on {policy.criterion_name!r}"
        )
    if problems:
        raise RegistryError(
            f"cannot promote {policy.model_id!r} v{target.version}: " + "; ".join(problems)
        )
    approval = (owner_approval or "").strip()
    if policy.requires_owner_approval and not approval:
        raise RegistryError(
            f"cannot promote {policy.model_id!r} v{target.version}: the family policy "
            f"requires explicit owner approval ({policy.promotion_policy}); pass "
            "owner_approval= naming the recorded decision"
        )
    if evaluation_receipt is None:  # unreachable: verify refuses a missing receipt
        raise RegistryError("cannot promote without the evaluation receipt")
    return {
        "gate": f"{GATE_GENERIC_FAMILY}:{policy.model_family}",
        "policySchemaVersion": str(policy.schema_version),
        "parameters": f"complete:{len(policy.parameters)}_of_{len(policy.parameters)}",
        "modelVersionId": expected,
        "championModelVersionId": champion_id or "none",
        "evaluationReceiptId": evaluation_receipt.receipt_id,
        "evaluationContentHash": evaluation_receipt.content_hash(),
        "verdict": str(evaluation_receipt.body.get("verdict")),
        "ownerApproval": approval or "not_required",
        "votingEffect": policy.voting_effect,
    }


def run_promotion_gate(
    model_id: str,
    *,
    incumbent: ModelVersion | None,
    target: ModelVersion,
    override_scopes: Iterable[str] = (),
    override_reason: str = "",
    evaluation_receipt: LearningReceipt | None = None,
    owner_approval: str = "",
) -> GateOutcome:
    """Run the one gate ``model_id`` is registered for. Raises on refusal."""
    champion = incumbent.params if incumbent else {}
    kind = gate_kind_for(model_id, champion, target.params)
    overrides = tuple(override_scopes)
    if kind == GATE_GENERIC_FAMILY:
        if overrides or (override_reason or "").strip():
            raise RegistryError(
                f"{model_id!r} runs the generic gate, which has no scope override: "
                "there is no scope risk to accept, only evidence to show"
            )
        policy = GENERIC_FAMILY_POLICIES[model_id]
        recorded = check_generic_family(
            policy,
            incumbent=incumbent,
            target=target,
            evaluation_receipt=evaluation_receipt,
            owner_approval=owner_approval,
        )
        return GateOutcome(kind=kind, scope_validation={}, promotion_gate=recorded)

    if evaluation_receipt is not None or (owner_approval or "").strip():
        raise RegistryError(
            "evaluation_receipt / owner_approval belong to the generic gate; the Hill gate "
            "derives its evidence from the version's holdout record and its owner path is "
            "override_scopes + override_reason"
        )
    check_hill_parameters(champion, target.params)
    states = assert_promotable(
        champion,
        target.params,
        validated_scopes={"OFFENSE"} if target.qualified else (),
        override_scopes=overrides,
        override_reason=override_reason,
    )
    return GateOutcome(kind=kind, scope_validation=states, promotion_gate=None)
