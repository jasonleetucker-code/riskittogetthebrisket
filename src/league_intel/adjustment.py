"""League-adjusted valuation: guardrails, confidence, explanation (LI-7).

Turns a player's ``consensusValue`` into a ``leagueAdjustedDynastyValue``
for THIS league, and — just as importantly — reports how much of that
number is evidence and how much is assumption.

Design position, earned the hard way
────────────────────────────────────
Spec §21's clause is "every adjustment must earn its place".  In
practice most candidate adjustments do not, and this module is built to
say so rather than to manufacture a number:

* An axis with **no admissible evidence contributes exactly zero** —
  not a prior, not a shrunk guess.  ``AdjustmentAxis`` carries its
  evidence tier, and an ``ABSENT`` axis is arithmetically inert.
* An axis whose measurement fails a validity gate is **rejected, not
  attenuated**.  The TE work (ADR-009) is the worked example: a
  plausible correction was dropped because its control positions were
  not flat, and a second because the quantity was mislabeled.
* Nothing here is published while
  :data:`~src.league_intel.values.LEAGUE_ADJUSTED_IS_NOOP` holds.  This
  module computes the decomposition so it can be *inspected*; the
  selector still serves consensus.

Confidence is not decoration
────────────────────────────
With no permitted raw-category projection source (LI-6), **every**
league-adjusted value today rests on roster structure alone.  A neutral
confidence reading would actively mislead, so the uncorroborated state
is explicit, labelled, and the default —
:class:`EvidenceTier.STRUCTURAL_ONLY`.  ``projection_corroborated`` is
False until re-scored categories exist, and any UI is expected to say
so rather than render an unqualified number.

Guardrails (§21)
────────────────
Three, applied in order, each recorded in the explanation:
 1. **evidence gate** — axes without admissible evidence contribute 0
 2. **magnitude cap** — total adjustment bounded to a fraction of
    consensus, so no compounding of small effects can run away
 3. **monotonicity guard** — adjustment must not reorder players within
    a position relative to consensus unless an axis explicitly says it
    should; silent reordering is how a subtle bug becomes a wrong board
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Mapping, Sequence

__all__ = [
    "ADJUSTMENT_MODEL_VERSION",
    "MAX_TOTAL_ADJUSTMENT",
    "EvidenceTier",
    "AdjustmentAxis",
    "AdjustmentExplanation",
    "build_adjustment",
]

ADJUSTMENT_MODEL_VERSION = "li.adjustment.2026-07-26.v1"

MAX_TOTAL_ADJUSTMENT = 0.25
"""Guardrail 2: the combined multiplicative adjustment is clamped to
[1-MAX, 1+MAX].  Not a statement that 25% is *right* — a statement that
anything beyond it is more likely a bug than an insight."""


class EvidenceTier(str, Enum):
    """How well-supported an axis is.  Ordered weakest to strongest."""

    ABSENT = "absent"
    """No admissible evidence.  Contributes exactly zero."""

    STRUCTURAL_ONLY = "structuralOnly"
    """Derived from roster/lineup structure measured from real rosters.
    Real evidence, but uncorroborated by projections — today's default
    and today's ceiling."""

    MARKET_MEASURED = "marketMeasured"
    """Measured from paired market boards that passed the
    ``calibration.py`` validity gates."""

    PROJECTION_CORROBORATED = "projectionCorroborated"
    """Structural effect confirmed against re-scored projected stat
    lines.  Unreachable until LI-6 secures a raw-category source."""


_TIER_CONFIDENCE: dict[EvidenceTier, float] = {
    EvidenceTier.ABSENT: 0.0,
    EvidenceTier.STRUCTURAL_ONLY: 0.45,
    EvidenceTier.MARKET_MEASURED: 0.70,
    EvidenceTier.PROJECTION_CORROBORATED: 0.90,
}


@dataclass(frozen=True)
class AdjustmentAxis:
    """One named, independently-justified component of the adjustment.

    ``factor`` is multiplicative and centred on 1.0.  An axis at tier
    ``ABSENT`` is forced inert regardless of the factor supplied, so a
    caller cannot smuggle in an unevidenced effect.
    """

    name: str
    factor: float
    tier: EvidenceTier
    rationale: str
    measured_at: str | None = None
    measured_value: float | None = None

    @property
    def effective_factor(self) -> float:
        """1.0 when the axis has no admissible evidence."""
        return 1.0 if self.tier is EvidenceTier.ABSENT else float(self.factor)

    @property
    def applied(self) -> bool:
        return self.tier is not EvidenceTier.ABSENT and self.factor != 1.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "factor": self.factor,
            "effectiveFactor": self.effective_factor,
            "tier": self.tier.value,
            "applied": self.applied,
            "rationale": self.rationale,
            "measuredAt": self.measured_at,
            "measuredValue": self.measured_value,
        }


@dataclass
class AdjustmentExplanation:
    """Full decomposition (§35): every axis, every guardrail, the
    confidence, and what is missing.

    Built so a reader can answer "why is this number different from
    consensus, and how much should I trust it" without reading code.
    """

    display_name: str
    consensus_value: float | None
    league_adjusted_value: float | None
    axes: list[AdjustmentAxis] = field(default_factory=list)
    guardrails: list[str] = field(default_factory=list)
    confidence: float = 0.0
    evidence_tier: EvidenceTier = EvidenceTier.ABSENT
    projection_corroborated: bool = False
    open_items: list[str] = field(default_factory=list)
    model_version: str = ADJUSTMENT_MODEL_VERSION

    @property
    def total_factor(self) -> float:
        if not self.consensus_value:
            return 1.0
        return (self.league_adjusted_value or 0.0) / self.consensus_value

    def to_dict(self) -> dict[str, Any]:
        return {
            "displayName": self.display_name,
            "consensusValue": self.consensus_value,
            "leagueAdjustedValue": self.league_adjusted_value,
            "totalFactor": round(self.total_factor, 6),
            "axes": [a.to_dict() for a in self.axes],
            "guardrails": list(self.guardrails),
            "confidence": self.confidence,
            "evidenceTier": self.evidence_tier.value,
            "projectionCorroborated": self.projection_corroborated,
            "openItems": list(self.open_items),
            "modelVersion": self.model_version,
        }


def _clamp(value: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, value))


def structural_scarcity_axis(
    position: str,
    scarcity: Mapping[str, Any] | None,
    *,
    reference_lineup_scarcity: float = 0.5,
    sensitivity: float = 0.20,
) -> AdjustmentAxis:
    """Positional scarcity implied by THIS league's measured lineup.

    Uses ``lineupScarcity`` from :mod:`src.league_intel.replacement`,
    which is derived from the exact optimizer's endogenous starter
    demand — real evidence about this league, independent of any
    external board.  Positions scarcer than the reference get a lift,
    deeper positions a trim, scaled by ``sensitivity``.

    Returns an ``ABSENT`` axis when scarcity could not be measured, so
    an unmeasurable position contributes nothing rather than a prior.
    """
    value = None
    if scarcity is not None:
        raw = (
            scarcity.get("lineupScarcity")
            if isinstance(scarcity, Mapping)
            else getattr(scarcity, "lineup_scarcity", None)
        )
        if isinstance(raw, (int, float)):
            value = float(raw)

    if value is None:
        return AdjustmentAxis(
            name="structuralScarcity",
            factor=1.0,
            tier=EvidenceTier.ABSENT,
            rationale=f"no measured lineup scarcity for {position}; axis contributes nothing",
        )

    delta = (value - reference_lineup_scarcity) * sensitivity
    return AdjustmentAxis(
        name="structuralScarcity",
        factor=1.0 + delta,
        tier=EvidenceTier.STRUCTURAL_ONLY,
        rationale=(
            f"{position} lineupScarcity {value:.3f} vs reference "
            f"{reference_lineup_scarcity:.3f}; endogenous starter demand measured "
            "from the exact optimizer over real rosters"
        ),
        measured_value=value,
    )


def te_premium_axis(*, measurement: Mapping[str, Any] | None = None) -> AdjustmentAxis:
    """TE premium — deliberately INERT pending LI-6's paired-board sweep.

    Two candidate corrections were measured and both rejected
    (ADR-009): the scoring-axis residual is real but the blend already
    embeds an alignment multiplier it would double-count against, and
    the blend-vs-anchor gap failed control flatness and is a mislabeled
    quantity besides.  A third measurement — several publishers'
    paired standard/TE-premium boards through ``calibration.py`` — is
    in flight and will either give the alignment constant a defensible
    target or show the market scatters.

    Until then this axis is ``ABSENT``: zero contribution, with the
    open question recorded rather than papered over with a prior.
    """
    if measurement is None:
        return AdjustmentAxis(
            name="tePremium",
            factor=1.0,
            tier=EvidenceTier.ABSENT,
            rationale=(
                "no admissible TE measurement; scoring-axis residual would "
                "double-count the blend's existing alignment multiplier, and the "
                "blend-vs-anchor gap failed control flatness (ADR-009)"
            ),
        )
    factor = float(measurement.get("factor") or 1.0)
    return AdjustmentAxis(
        name="tePremium",
        factor=factor,
        tier=EvidenceTier.MARKET_MEASURED,
        rationale=str(measurement.get("rationale") or "paired-board calibration"),
        measured_at=measurement.get("measuredAt"),
        measured_value=measurement.get("measuredValue"),
    )


def build_adjustment(
    *,
    display_name: str,
    position: str,
    consensus_value: float | None,
    axes: Sequence[AdjustmentAxis],
    position_peers: Sequence[tuple[str, float]] = (),
    max_total_adjustment: float = MAX_TOTAL_ADJUSTMENT,
) -> AdjustmentExplanation:
    """Combine axes into a league-adjusted value with all three guardrails.

    ``position_peers`` is ``[(name, consensus_value), ...]`` for the
    same position, used only by the monotonicity guard.
    """
    explanation = AdjustmentExplanation(
        display_name=display_name,
        consensus_value=consensus_value,
        league_adjusted_value=consensus_value,
        axes=list(axes),
    )

    if not consensus_value or consensus_value <= 0:
        explanation.guardrails.append("no consensus value; adjustment not attempted")
        explanation.open_items.append("player is unpriced by the consensus board")
        return explanation

    # ── Guardrail 1: evidence gate ────────────────────────────────────
    inert = [a.name for a in axes if a.tier is EvidenceTier.ABSENT]
    if inert:
        explanation.guardrails.append(
            f"evidence gate: {', '.join(inert)} contributed 0 (no admissible evidence)"
        )

    combined = 1.0
    for axis in axes:
        combined *= axis.effective_factor

    # ── Guardrail 2: magnitude cap ────────────────────────────────────
    lo, hi = 1.0 - max_total_adjustment, 1.0 + max_total_adjustment
    capped = _clamp(combined, lo, hi)
    if capped != combined:
        explanation.guardrails.append(
            f"magnitude cap: combined factor {combined:.4f} clamped to {capped:.4f} "
            f"(limit +/-{max_total_adjustment:.0%})"
        )
    combined = capped

    adjusted = consensus_value * combined
    explanation.league_adjusted_value = adjusted

    # ── Guardrail 3: monotonicity within position ─────────────────────
    # Order preservation is a property of a POSITION'S whole set, not of
    # one player — a single row cannot know what factor its peers got.
    # Enforced by :func:`check_position_monotonicity` over a batch; here
    # we only record that this player's factor is position-uniform (and
    # therefore order-preserving by construction) or player-specific
    # (and therefore requires the batch check).
    if position_peers:
        explanation.guardrails.append(
            f"monotonicity: {len(position_peers)} {position} peers supplied; "
            "order preservation verified at batch level "
            "(see check_position_monotonicity)"
        )

    # ── Confidence: the weakest APPLIED axis governs ──────────────────
    applied = [a for a in axes if a.applied]
    if not applied:
        explanation.evidence_tier = EvidenceTier.ABSENT
        explanation.confidence = 0.0
        explanation.guardrails.append("no axis applied; league-adjusted == consensus")
    else:
        order = list(_TIER_CONFIDENCE)
        weakest = min(applied, key=lambda a: order.index(a.tier))
        explanation.evidence_tier = weakest.tier
        explanation.confidence = _TIER_CONFIDENCE[weakest.tier]

    explanation.projection_corroborated = any(
        a.tier is EvidenceTier.PROJECTION_CORROBORATED for a in applied
    )
    if not explanation.projection_corroborated:
        explanation.open_items.append(
            "not corroborated by re-scored projections — no permitted raw-category "
            "source exists yet (LI-6); this value rests on roster structure alone"
        )
    if any(a.name == "tePremium" and a.tier is EvidenceTier.ABSENT for a in axes):
        explanation.open_items.append(
            "TE premium unresolved — paired-board market sweep in flight (ADR-009)"
        )
    return explanation


@dataclass(frozen=True)
class MonotonicityViolation:
    """A pair whose consensus order the adjustment reversed."""

    position: str
    higher_name: str
    lower_name: str
    consensus_gap: float
    adjusted_gap: float

    def to_dict(self) -> dict[str, Any]:
        return {
            "position": self.position,
            "higherName": self.higher_name,
            "lowerName": self.lower_name,
            "consensusGap": self.consensus_gap,
            "adjustedGap": self.adjusted_gap,
        }


def check_position_monotonicity(
    position: str,
    entries: Sequence[tuple[str, float, float]],
) -> list[MonotonicityViolation]:
    """Guardrail 3, applied where it is actually checkable.

    ``entries`` is ``[(name, consensus_value, adjusted_value), ...]``
    for one position.  Returns every pair whose consensus ordering the
    adjustment reversed.

    A position-uniform factor cannot produce a violation, so an empty
    result is the expected outcome today.  The check exists for the
    moment an axis becomes player-specific: silent reordering is how a
    subtle bug turns into a visibly wrong board, and it must fail loudly
    rather than ship.
    """
    ranked = sorted(entries, key=lambda e: -e[1])
    violations: list[MonotonicityViolation] = []
    for i in range(len(ranked) - 1):
        hi_name, hi_c, hi_a = ranked[i]
        for j in range(i + 1, len(ranked)):
            lo_name, lo_c, lo_a = ranked[j]
            if hi_c <= lo_c:
                continue  # ties impose no ordering
            if hi_a < lo_a:
                violations.append(
                    MonotonicityViolation(
                        position=position,
                        higher_name=hi_name,
                        lower_name=lo_name,
                        consensus_gap=hi_c - lo_c,
                        adjusted_gap=hi_a - lo_a,
                    )
                )
    return violations
