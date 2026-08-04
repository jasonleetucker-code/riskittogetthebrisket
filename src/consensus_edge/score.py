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
        # Was `validated: True, outcome: "positive"` on the strength of
        # rho +0.126. That rho was measured on a board where every IDP
        # fair value came off a leave-one-out build with no IDP backbone
        # — numbers on no scale at all (ADR-021). With those rows refused
        # and the same backtest re-run, the result is a null. The
        # component still ranks the board; nothing measured says it ranks
        # it usefully.
        "validated": False,
        "measured": True,
        "outcome": "null",
        "evidence": "docs/measurements/consensus-edge-backtest-2026-08-04-h14.json",
        "note": (
            "no effect detected: rho +0.031 over 6 non-overlapping folds at 14d "
            "(+0.040 over 12 at 7d), and the market-value benchmark — a plain "
            "'buy cheap players' rule — beat it in 5 of 6 and 9 of 12. The "
            "earlier +0.126 was measured on a board that priced IDP rows on a "
            "scale that does not exist."
        ),
    },
    "sharpFlow": {
        "validated": False,
        # Not merely unmeasured — unmeasurABLE with the code as it
        # stands. The qualified cohort is recomputed live on every
        # request and `src/sharp/` has no as-of concept at all, so a
        # historical value cannot be reconstructed however much ledger
        # data accumulates.
        "measured": False,
        "outcome": None,
        "evidence": None,
        "note": (
            "no ledger outside production; never checked against an outcome, and "
            "cannot be until the qualified cohort can be frozen as-of a date"
        ),
    },
    "opportunity": {
        # `validated` stays False, and that is deliberate. This component
        # WAS measured — which `measured` says — but the result was a
        # null: it did not earn a weight. `validated` drives the UI's
        # "unvalidated" badge, so flipping it True for a negative result
        # would tell a user the component is trustworthy on the strength
        # of evidence that it is not. "Measured" and "validated" are
        # different claims and this is exactly the case that separates
        # them.
        "validated": False,
        "measured": True,
        "outcome": "null",
        "evidence": "docs/measurements/consensus-edge-composite-2026-08-04-h7.json",
        "note": (
            "measured and rejected: adding the board-momentum axis lowered mean "
            "rho (7d -0.010 over 11 folds, 14d -0.009 over 5) and beat mispricing "
            "alone in only 3/11 and 2/5 folds. Weight is zero; the axis is "
            "displayed as evidence but does not move the score. The snapTrend "
            "axis is replayable since 2026-08-04 (nflverse publishes snap "
            "counts per game; src/playerctx/asof.py bounds the read to the "
            "weeks completed before each origin) but is not yet MEASURED: "
            "every date in the current all-offseason panel resolves to the "
            "same completed season, so the axis is one frozen cross-section "
            "rather than a signal varying across folds."
        ),
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

    Three sets, deliberately distinct, all reported:

    ``componentsAbsent``
        no value at all — the data did not exist.
    ``componentsZeroWeight``
        a real value the model does not act on.  Excluded from
        ``componentsPresent``, and therefore from coverage, confidence
        and conflict — see :func:`detect_conflict`.
    ``componentsPresent``
        what actually produced the score.

    Collapsing the middle set into either of the others is the bug this
    shape exists to prevent: into ``absent`` it hides a real measurement,
    into ``present`` it lets a rejected signal raise confidence.
    """
    cfg = params.get("composite") or {}
    weights = cfg.get("weights") or {}
    core = set(cfg.get("coreComponents") or [])
    require_core = bool(cfg.get("requireCoreComponent", True))

    valued = {k: v for k, v in components.items() if isinstance(v, (int, float))}
    # A component carrying a value but ZERO weight is not evidence. It
    # is a measurement we deliberately decided not to act on, and it must
    # not enter `componentsPresent` — that list feeds `confidence` as the
    # coverage numerator, so counting it would raise a player's
    # confidence on the strength of a signal contributing exactly nothing
    # to his score. Reported separately so it also cannot be mistaken for
    # missing data.
    zero_weight = sorted(k for k in valued if float(weights.get(k) or 0.0) == 0.0)
    present = {k: v for k, v in valued.items() if k not in zero_weight}
    absent = sorted(k for k in components if k not in valued)

    out: dict[str, Any] = {
        "score": None,
        "componentsPresent": sorted(present),
        "componentsAbsent": absent,
        "componentsZeroWeight": zero_weight,
        "effectiveWeights": {},
        "reason": None,
    }

    if not valued:
        out["reason"] = "no components available"
        return out
    # The core check reads `valued`, not `present`, and runs FIRST. It is
    # a statement about the KIND of evidence — an opportunity signal
    # alone describes a player without saying whether he is mispriced —
    # and that holds whatever the weights happen to be. Checking it
    # against the post-weight set would report "everything carries zero
    # weight" for a case whose real defect is that no core component was
    # supplied at all.
    if require_core and core and not (core & set(valued)):
        out["reason"] = "no core component available (need one of " + ", ".join(sorted(core)) + ")"
        return out
    if not present:
        out["reason"] = "every available component carries zero weight"
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
    """Flag strong evidence pointing in opposite directions.

    Zero-weight components are excluded, for the same reason
    :func:`composite` excludes them from ``componentsPresent``. Conflict
    is a refusal mechanism — it suppresses a directional call — so a
    component that was measured and rejected must not be able to veto a
    call it is not allowed to contribute to. Letting it would mean a
    signal we decided is non-predictive still steers the output, just
    through a different door.
    """
    threshold = float((params.get("conflict") or {}).get("minMagnitude") or 0.5)
    weights = (params.get("composite") or {}).get("weights") or {}
    strong = {
        k: float(v)
        for k, v in components.items()
        if isinstance(v, (int, float))
        and abs(float(v)) >= threshold
        and float(weights.get(k) or 0.0) > 0.0
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
