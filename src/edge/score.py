"""The composite Consensus Edge Score, its confidence, and its refusals.

One number for ranking, the components always visible beside it, and an explicit
vocabulary for the states a single number cannot express.

──────────────────────────────────────────────────────────────────────
Why these weights are PROVISIONAL and the model is SHADOW-ONLY
──────────────────────────────────────────────────────────────────────
Weights must be fitted out-of-sample. This repository's panel can do that for
exactly one component:

* ``mispricing`` — validated. Positive out-of-sample Spearman in every rolling
  fold (+0.09 strict / +0.12 family at the 14-day horizon).
* ``sharp_flow`` — NOT validatable. The movement ledger stores no as-of history
  and is empty in a fresh checkout, so there is nothing to fit against.
* the 30-day horizon — only ONE fold scored on the available history. One fold
  is an observation, not a validation.

So a fitted multi-component weight vector cannot be produced honestly here, and
inventing one is the specific failure this whole exercise exists to prevent.
``PROVISIONAL_WEIGHTS`` is therefore labelled provisional in the code, stamped
into every payload as ``weightsValidated: false``, and the model is not eligible
for production promotion. ``docs/edge/BACKTEST.md`` records what would have to
be true to change that.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any, Mapping, Sequence

from src.edge.components import (
    MIN_CONFIDENCE_FOR_ANY_CALL,
    MIN_CONFIDENCE_FOR_STRONG_CALL,
    ComponentScore,
    detect_conflict,
)

#: Bump on ANY change to weights, thresholds, component definitions or the
#: classification rules. Stamped on every payload so a stored score can always
#: be traced to the code that produced it.
MODEL_VERSION = "consensus-edge-0.1.0-shadow"

#: PROVISIONAL. Not fitted — see the module docstring.
#:
#: ``mispricing`` carries the whole directional weight because it is the only
#: directional component with out-of-sample evidence. ``sharp_flow`` is present
#: at a deliberately small weight so the plumbing is exercised and visible
#: without an unvalidated component being able to drive a recommendation on its
#: own; with the ledger empty it contributes nothing in practice today.
PROVISIONAL_WEIGHTS: dict[str, float] = {
    "mispricing": 0.80,
    "sharp_flow": 0.20,
}

WEIGHTS_VALIDATED = False

#: Score bands. Provisional: calibrating these needs the fitted model that the
#: available history cannot support.
STRONG_BUY_AT = 60.0
BUY_AT = 30.0
SELL_AT = -30.0
STRONG_SELL_AT = -60.0

CLASSIFICATIONS = (
    "Strong Buy",
    "Buy",
    "Neutral",
    "Sell",
    "Strong Sell",
    "Conflicted",
    "Insufficient Evidence",
    "Withheld",
)


@dataclass
class EdgeResult:
    player_key: str
    score: float
    classification: str
    confidence: float
    components: dict[str, ComponentScore]
    conflict: dict[str, Any]
    reasons: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    model_version: str = MODEL_VERSION
    weights_validated: bool = WEIGHTS_VALIDATED

    def to_dict(self) -> dict[str, Any]:
        return {
            "playerKey": self.player_key,
            "score": round(self.score, 2),
            "classification": self.classification,
            "confidence": round(self.confidence, 1),
            "components": {k: v.to_dict() for k, v in self.components.items()},
            "conflict": self.conflict,
            "reasons": self.reasons,
            "warnings": self.warnings,
            "modelVersion": self.model_version,
            "weightsValidated": self.weights_validated,
        }


def combine(components: Mapping[str, ComponentScore]) -> tuple[float, list[str]]:
    """Weighted blend of the DIRECTIONAL components that are actually present.

    Two rules do the real work:

    * A component with no value is skipped and its weight is redistributed
      across the components that do have one. It is never treated as 0.0, which
      would drag a genuine signal toward neutral and make missing data look like
      disagreement.
    * ``directional=False`` components (momentum, data quality) cannot enter
      here at all. That is enforced, not documented: momentum is the strongest
      market-outcome predictor in the panel and would dominate the score if
      allowed in, turning the product into a trend-follower.
    """
    usable = {
        key: component
        for key, component in components.items()
        if component.directional and component.value is not None
    }
    if not usable:
        return 0.0, ["no directional component could be computed"]

    total_weight = sum(PROVISIONAL_WEIGHTS.get(key, 0.0) for key in usable)
    if total_weight <= 0:
        return 0.0, ["no weighted directional component available"]

    blended = 0.0
    notes: list[str] = []
    for key, component in usable.items():
        weight = PROVISIONAL_WEIGHTS.get(key, 0.0) / total_weight
        blended += weight * float(component.value or 0.0)
    missing = [
        key
        for key in PROVISIONAL_WEIGHTS
        if key not in usable and PROVISIONAL_WEIGHTS.get(key, 0.0) > 0
    ]
    if missing:
        notes.append(f"weights renormalized; unavailable: {', '.join(sorted(missing))}")
    return max(-1.0, min(1.0, blended)), notes


def overall_confidence(components: Mapping[str, ComponentScore]) -> float:
    """Geometric-style blend of component confidence and data quality, 0-100.

    Geometric rather than arithmetic so one catastrophic input cannot be
    averaged away by two healthy ones — a stale market price should sink the
    whole answer, not cost it a third.
    """
    directional = [
        component
        for component in components.values()
        if component.directional and component.value is not None
    ]
    if not directional:
        return 0.0
    product = 1.0
    for component in directional:
        product *= max(0.01, component.confidence)
    evidence_confidence = product ** (1.0 / len(directional))

    quality = components.get("data_quality")
    if quality is None:
        # No data-quality assessment must not IMPROVE the answer. Folding in a
        # default 1.0 and taking the geometric mean did exactly that — one
        # component at 0.50 confidence came out at 0.71 overall, enough to clear
        # the Strong-call floor on a single mediocre input. Absent evidence
        # leaves confidence where it was.
        return max(0.0, min(100.0, 100.0 * evidence_confidence))
    return max(
        0.0, min(100.0, 100.0 * math.sqrt(evidence_confidence * max(0.01, quality.confidence)))
    )


def classify(score: float, confidence: float, conflict: Mapping[str, Any]) -> str:
    """Score plus confidence plus conflict — never score alone.

    Ordering is deliberate: refusals are checked BEFORE the bands, so no amount
    of extremity can promote a poorly-evidenced row into a Strong call.
    """
    if conflict.get("conflicted"):
        return "Conflicted"
    if confidence < MIN_CONFIDENCE_FOR_ANY_CALL:
        return "Insufficient Evidence"
    if score >= STRONG_BUY_AT:
        return "Strong Buy" if confidence >= MIN_CONFIDENCE_FOR_STRONG_CALL else "Buy"
    if score >= BUY_AT:
        return "Buy"
    if score <= STRONG_SELL_AT:
        return "Strong Sell" if confidence >= MIN_CONFIDENCE_FOR_STRONG_CALL else "Sell"
    if score <= SELL_AT:
        return "Sell"
    return "Neutral"


def build_reasons(
    components: Mapping[str, ComponentScore],
    classification: str,
    conflict: Mapping[str, Any],
) -> list[str]:
    """Plain-language explanation assembled from structured evidence only.

    Every sentence is generated from a number the payload also carries, so a
    reader can check the prose against the data. Nothing here is free text about
    a player.
    """
    reasons: list[str] = []
    mispricing = components.get("mispricing")
    if mispricing and mispricing.value is not None:
        gap = mispricing.evidence.get("logGap")
        sources = mispricing.evidence.get("independentSourceCount")
        z = mispricing.evidence.get("cohortZ")
        if gap is not None:
            direction = "above" if gap > 0 else "below"
            reasons.append(
                f"Independent fair value is {abs(math.expm1(gap)) * 100:.0f}% {direction} "
                f"the market price, across {sources} board(s) that exclude the market anchor."
            )
        # The score is cohort-RELATIVE, and saying only "fair value is 44% below
        # the market" beside a Buy reads as a contradiction. It is not: the whole
        # cohort can sit below the market (the board carries a systematic
        # position-level offset against KTC), so what earns a Buy is being
        # underpriced RELATIVE TO COMPARABLE PLAYERS. Say that explicitly rather
        # than leaving the reader to reconcile a sign with a label.
        if z is not None:
            stance = "cheaper" if z > 0 else "more expensive"
            reasons.append(
                f"Against comparable players at the same position and value tier he is "
                f"{stance} than typical ({abs(z):.1f} robust deviations). The score is "
                "relative to that cohort, not to the raw gap."
            )
        elif mispricing.evidence.get("cohortRelative") is False:
            reasons.append(
                "Too few comparable players to normalize against, so this rests on the raw "
                "gap and is deliberately damped and low-confidence."
            )

    sharp = components.get("sharp_flow")
    if sharp and sharp.value is not None:
        reasons.append(
            f"Qualified managers: {sharp.evidence.get('buys')} buys / "
            f"{sharp.evidence.get('sells')} sells across "
            f"{sharp.evidence.get('uniqueManagers')} manager(s) and "
            f"{sharp.evidence.get('uniqueLeagues')} league(s). "
            "This measures direction, not the price they paid."
        )

    momentum = components.get("momentum")
    if momentum and momentum.value is not None:
        trailing = momentum.evidence.get("trailing30d")
        if trailing is not None:
            moved = "risen" if trailing > 0 else "fallen"
            reasons.append(
                f"Context: the market price has {moved} "
                f"{abs(math.expm1(trailing)) * 100:.0f}% over 30 days. "
                "Recent movement is shown for context and does not contribute to the score."
            )

    if classification == "Conflicted":
        reasons.append(
            "Withheld from the ranked lists: "
            f"{', '.join(conflict.get('positiveComponents') or [])} point up while "
            f"{', '.join(conflict.get('negativeComponents') or [])} point down."
        )
    if classification == "Insufficient Evidence":
        reasons.append("Confidence is below the floor required to make any call.")
    return reasons


def evaluate(
    *,
    player_key: str,
    components: dict[str, ComponentScore],
) -> EdgeResult:
    """Assemble one player's result from already-computed components."""
    blended, notes = combine(components)
    confidence = overall_confidence(components)
    conflict = detect_conflict(components)
    score = 100.0 * math.tanh(1.5 * blended)
    classification = classify(score, confidence, conflict)

    warnings = list(notes)
    for component in components.values():
        warnings.extend(component.warnings)

    return EdgeResult(
        player_key=player_key,
        score=score,
        classification=classification,
        confidence=confidence,
        components=components,
        conflict=conflict,
        reasons=build_reasons(components, classification, conflict),
        warnings=sorted(set(warnings)),
    )


def qualifies_for_ranked_list(result: EdgeResult, *, direction: str) -> bool:
    """Whether a result may appear in a Top Buys / Top Sells list.

    Deliberately strict. A ranked list is the most-read surface in the product,
    so a row reaches it only by clearing the bar — never by being the best
    available at its position.
    """
    if result.classification in {"Conflicted", "Insufficient Evidence", "Withheld"}:
        return False
    if result.confidence < MIN_CONFIDENCE_FOR_ANY_CALL:
        return False
    if direction == "buy":
        return result.score >= BUY_AT
    if direction == "sell":
        return result.score <= SELL_AT
    return False


def rank(results: Sequence[EdgeResult], *, direction: str, limit: int = 20) -> list[EdgeResult]:
    """Merit-ordered ranked list. No positional quota, by design.

    Padding a list to cover every position means promoting a player who did not
    clear the bar, which is the fastest way to make the whole surface untrusted.
    Callers wanting per-position coverage should ask for position leaders
    separately and render "No qualifying buy" where there is none.
    """
    eligible = [item for item in results if qualifies_for_ranked_list(item, direction=direction)]
    reverse = direction == "buy"
    eligible.sort(key=lambda item: item.score, reverse=reverse)
    return eligible[: max(1, limit)]


def position_leaders(
    results: Sequence[EdgeResult],
    positions: Mapping[str, str | None],
    *,
    direction: str,
) -> dict[str, EdgeResult | None]:
    """Best QUALIFYING result per position, or None.

    ``None`` renders as "No qualifying buy" rather than as the least-bad
    candidate.
    """
    out: dict[str, EdgeResult | None] = {}
    for result in results:
        position = positions.get(result.player_key)
        if not position:
            continue
        if not qualifies_for_ranked_list(result, direction=direction):
            continue
        current = out.get(position)
        if current is None:
            out[position] = result
        elif (direction == "buy" and result.score > current.score) or (
            direction == "sell" and result.score < current.score
        ):
            out[position] = result
    return out
