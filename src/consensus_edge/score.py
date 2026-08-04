"""The composite, its confidence, and the states that refuse to score.

Most of this file is about NOT producing a number.  That is the point.
A buy/sell score is trivial to compute and dangerous to compute badly,
and the failure modes are all quiet ones:

* **Missing evidence rendered as zero.**  A player with no sharp data
  scoring 0.0 on that component is indistinguishable from a player whom
  qualified managers are actively ignoring.  Weights are renormalised
  over PRESENT components, and absent ones are listed by name.
* **Conflict averaged into neutrality.**  +0.8 mispricing against −0.8
  sharp flow averages to zero and renders as "Neutral", which is the
  opposite of the truth: the evidence is strong and it disagrees.  Any
  such pair forces ``Conflicted`` regardless of the arithmetic.
* **A confident label on thin evidence.**  Direction and confidence are
  computed separately and the label requires both, so an extreme score
  from one stale source cannot present as Strong Buy.
* **A composite laundering unmeasured components.**  Mispricing has an
  out-of-sample result; Sharp Flow and Opportunity do not.  Every payload
  therefore carries per-component scores and a ``validated`` flag per
  component, so a reader can see which parts have earned belief.

Confidence is a geometric mean, deliberately: it is a conjunction (fresh
AND covered AND agreeing), and an arithmetic mean would let three strong
factors hide one absent one.
"""

from __future__ import annotations

import math
from typing import Any

# Classification labels.
STRONG_BUY = "Strong Buy"
BUY = "Buy"
NEUTRAL = "Neutral"
SELL = "Sell"
STRONG_SELL = "Strong Sell"
CONFLICTED = "Conflicted"
INSUFFICIENT = "Insufficient Evidence"
NO_MARKET_PRICE = "No Market Price"
WITHHELD = "Withheld"

# Which components currently have an out-of-sample result behind them.
# Consumed by the API and the UI so "validated" is a property of the
# data, not a claim in a docstring that can drift from reality.
COMPONENT_VALIDATION: dict[str, dict[str, Any]] = {
    "mispricing": {
        "validated": True,
        "evidence": "docs/measurements/consensus-edge-backtest-2026-08-04-h14.json",
        "note": "rho +0.126 over 7 non-overlapping folds; beat market-value benchmark 7/7",
    },
    "sharpFlow": {
        "validated": False,
        "evidence": None,
        "note": "no ledger outside production; never checked against an outcome",
    },
    "opportunity": {
        "validated": False,
        "evidence": None,
        "note": "no forward-projection feed; contributes only where evidenced",
    },
}


def _clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


def confidence(
    *,
    params: dict[str, Any],
    components_present: int,
    components_possible: int,
    cohort_level: str | None,
    source_count: int,
    hours_stale: float | None,
) -> dict[str, Any]:
    """Confidence in ``[0, 100]``, with its factors exposed.

    Returns the factors alongside the score so a low number can be
    explained ("stale data") rather than merely asserted.
    """
    cfg = params.get("confidence") or {}
    half_life = float(cfg.get("stalenessHalfLifeHours") or 48.0)
    level_penalty = cfg.get("cohortLevelPenalty") or {}

    # Coverage: how much of the intended evidence base actually showed up.
    coverage = components_present / components_possible if components_possible else 0.0
    # Reliability: source depth, discounted when the mispricing cohort
    # had to fall back to a coarser peer group.
    depth = _clamp(source_count / 6.0, 0.0, 1.0)
    reliability = depth * float(level_penalty.get(str(cohort_level or "specific"), 1.0))
    # Freshness: halves every half_life hours. Unknown staleness is
    # treated as stale, not as fresh — the safer direction when the
    # answer is "we don't know how old this is".
    if hours_stale is None:
        freshness = 0.5
    else:
        freshness = math.exp(-math.log(2.0) * max(0.0, hours_stale) / half_life)

    factors = {
        "coverage": _clamp(coverage, 0.0, 1.0),
        "reliability": _clamp(reliability, 0.0, 1.0),
        "freshness": _clamp(freshness, 0.0, 1.0),
    }
    product = 1.0
    for value in factors.values():
        product *= value
    score = 100.0 * (product ** (1.0 / len(factors)))
    return {"score": score, "factors": factors}


def composite(
    components: dict[str, float | None],
    params: dict[str, Any],
) -> dict[str, Any]:
    """Blend present components into a score in ``[-100, 100]``.

    ``components`` maps name → score in ``[-1, 1]`` or ``None`` when the
    component could not be computed.  Absent components are dropped and
    the remaining weights renormalised, so a missing component neither
    drags the score toward zero nor silently keeps its weight.

    Returns ``score = None`` when no *core* component is present.  An
    opportunity signal on its own describes a player without saying
    anything about whether he is mispriced, and calling that a Buy would
    be a category error.
    """
    cfg = params.get("composite") or {}
    weights = cfg.get("weights") or {}
    core = set(cfg.get("coreComponents") or [])
    require_core = bool(cfg.get("requireCoreComponent", True))

    present = {k: v for k, v in components.items() if isinstance(v, (int, float))}
    absent = sorted(k for k in components if k not in present)

    out: dict[str, Any] = {
        "score": None,
        "componentsPresent": sorted(present),
        "componentsAbsent": absent,
        "effectiveWeights": {},
        "reason": None,
    }

    if not present:
        out["reason"] = "no components available"
        return out
    if require_core and core and not (core & set(present)):
        out["reason"] = "no core component available (need one of " + ", ".join(sorted(core)) + ")"
        return out

    total_weight = sum(float(weights.get(k) or 0.0) for k in present)
    if total_weight <= 0:
        out["reason"] = "present components carry no weight"
        return out

    blended = 0.0
    for key, value in present.items():
        w = float(weights.get(key) or 0.0) / total_weight
        out["effectiveWeights"][key] = w
        blended += w * _clamp(float(value), -1.0, 1.0)

    # tanh keeps the scale bounded and compresses extremes, so a single
    # component pinned at its clip cannot saturate the composite on its
    # own.
    out["score"] = 100.0 * math.tanh(blended)
    return out


def detect_conflict(
    components: dict[str, float | None],
    params: dict[str, Any],
) -> dict[str, Any]:
    """Flag strong evidence pointing in opposite directions."""
    threshold = float((params.get("conflict") or {}).get("minMagnitude") or 0.5)
    strong = {
        k: float(v)
        for k, v in components.items()
        if isinstance(v, (int, float)) and abs(float(v)) >= threshold
    }
    positive = sorted(k for k, v in strong.items() if v > 0)
    negative = sorted(k for k, v in strong.items() if v < 0)
    conflicted = bool(positive and negative)
    return {
        "conflicted": conflicted,
        "threshold": threshold,
        "opposing": {"positive": positive, "negative": negative} if conflicted else None,
    }


def classify(
    score: float | None,
    conf: float | None,
    conflict: dict[str, Any],
    params: dict[str, Any],
    *,
    has_market_price: bool = True,
    quarantined: bool = False,
) -> dict[str, Any]:
    """Turn a score into a label, refusing where refusal is correct.

    Order matters and encodes a precedence of failure modes: a
    quarantined identity beats everything, a missing price beats a
    conflict, and a conflict beats the arithmetic.  A player is never
    labelled Neutral because strong opposing evidence happened to cancel.
    """
    cfg = params.get("classification") or {}
    min_strong = float(cfg.get("minConfidenceForStrong") or 70.0)
    min_directional = float(cfg.get("minConfidenceForDirectional") or 50.0)
    floor = float(cfg.get("insufficientEvidenceBelowConfidence") or 35.0)

    if quarantined:
        return {"label": WITHHELD, "reason": "identity quarantined"}
    if not has_market_price:
        return {"label": NO_MARKET_PRICE, "reason": "no market anchor prices this asset"}
    if score is None:
        return {"label": INSUFFICIENT, "reason": "no composite score could be computed"}
    if conf is None or conf < floor:
        return {
            "label": INSUFFICIENT,
            "reason": f"confidence {conf:.0f} below floor {floor:.0f}"
            if conf is not None
            else "confidence unavailable",
        }
    if conflict.get("conflicted"):
        opposing = conflict.get("opposing") or {}
        return {
            "label": CONFLICTED,
            "reason": (
                "strong opposing evidence: "
                + ", ".join(opposing.get("positive") or [])
                + " vs "
                + ", ".join(opposing.get("negative") or [])
            ),
        }

    strong_buy = float(cfg.get("strongBuy") or 60.0)
    buy = float(cfg.get("buy") or 30.0)
    sell = float(cfg.get("sell") or -30.0)
    strong_sell = float(cfg.get("strongSell") or -60.0)

    if score >= strong_buy:
        if conf >= min_strong:
            return {"label": STRONG_BUY, "reason": None}
        return {
            "label": BUY,
            "reason": f"score reaches Strong Buy but confidence {conf:.0f} < {min_strong:.0f}",
        }
    if score >= buy:
        if conf >= min_directional:
            return {"label": BUY, "reason": None}
        return {
            "label": NEUTRAL,
            "reason": f"score reaches Buy but confidence {conf:.0f} < {min_directional:.0f}",
        }
    if score <= strong_sell:
        if conf >= min_strong:
            return {"label": STRONG_SELL, "reason": None}
        return {
            "label": SELL,
            "reason": f"score reaches Strong Sell but confidence {conf:.0f} < {min_strong:.0f}",
        }
    if score <= sell:
        if conf >= min_directional:
            return {"label": SELL, "reason": None}
        return {
            "label": NEUTRAL,
            "reason": f"score reaches Sell but confidence {conf:.0f} < {min_directional:.0f}",
        }
    return {"label": NEUTRAL, "reason": None}
