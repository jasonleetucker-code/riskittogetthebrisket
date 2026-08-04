"""The separately-visible Consensus Edge components.

Each component answers ONE question and is reported on its own. The composite in
``score.py`` combines them, but never replaces them: a user who sees only
"+62 Buy" cannot tell whether that is a mispricing bet, a crowd-behaviour bet or
a role bet, and those fail in different ways.

──────────────────────────────────────────────────────────────────────
What the evidence actually says
──────────────────────────────────────────────────────────────────────
Measured on this repository's own 99-day / 45,935-row panel with rolling
out-of-sample folds (``src/edge/backtest.py``, results in
``docs/edge/BACKTEST.md``):

    predictor            14d target, mean out-of-sample Spearman
    trailing_30d         +0.38   (all folds positive)
    trailing_7d          +0.25
    log_gap              +0.09 strict / +0.12 family   (all folds positive)
    market_value         +0.02   (not a signal)

Three consequences are baked into the code below rather than left as advice:

1. **Mispricing is real but weak.** ``log_gap`` was positive in every
   out-of-sample fold, which is why it is the primary component — but at
   rho ~0.1 it earns a modest weight, not a confident one.

2. **Momentum is much stronger and is NOT a buy signal.** Trailing price change
   predicts future price change about four times better than mispricing does.
   It is included ONLY as ``momentum`` — a context/confirmation field that can
   temper or corroborate a thesis — and it is deliberately excluded from the
   directional score. A system that let momentum drive the recommendation would
   score best on the market target while telling users to buy whatever already
   went up, which is precisely the "momentum alone is not proof of a good buy"
   failure this design is required to avoid.

3. **A naive sum of components is WORSE than its best part.** Blending
   ``log_gap`` and ``trailing_30d`` 1:1 scored +0.17-0.20 against momentum's
   +0.38, because unstandardized components on different scales let the weaker
   one drown the stronger. Every component here is therefore squashed onto a
   common [-1, 1] before any combination happens.

``sharp_flow`` cannot be validated at all — the movement ledger keeps no as-of
history and is empty in a fresh checkout — so it ships computed, displayed, and
explicitly labelled unvalidated.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from statistics import median
from typing import Any, Mapping, Sequence

#: Squash constant for the mispricing z-score. A |z| of this size maps to about
#: 0.76 of full scale, so ordinary disagreement uses the middle of the range and
#: only genuine outliers approach the ends.
MISPRICING_Z_SCALE = 2.0

#: Robust-sigma conversion for the median absolute deviation.
MAD_TO_SIGMA = 1.4826

#: Below this many cohort members a robust z-score is not meaningful, so the
#: component returns None rather than a confident-looking number from four
#: observations.
MIN_COHORT_SIZE = 20

#: Ceiling on the un-normalized fallback's magnitude. A row we could not
#: cohort-normalize must never outrank one we could: without this the fallback
#: path produced |value| near 1.0 while properly normalized rows sat near 0.5,
#: and the live sell list filled up entirely with ``cohortZ: None`` rows.
UNNORMALIZED_SHRINKAGE = 0.45

#: Beta prior for the Sharp Flow posterior. (2, 2) is a weak symmetric prior
#: centred on 50/50: it pulls a 1-buy/0-sell asset back toward neutral instead
#: of letting one transaction read as unanimous conviction, while washing out
#: quickly once real volume arrives.
SHARP_PRIOR_ALPHA = 2.0
SHARP_PRIOR_BETA = 2.0

#: Confidence floors. Below this a label is downgraded to Insufficient Evidence
#: no matter how extreme the score.
MIN_CONFIDENCE_FOR_ANY_CALL = 35.0
MIN_CONFIDENCE_FOR_STRONG_CALL = 70.0

#: A component this large in one direction, opposed by one this large in the
#: other, is a genuine disagreement rather than a net-zero neutral.
CONFLICT_THRESHOLD = 0.40


@dataclass
class ComponentScore:
    """One component's answer, plus everything needed to explain or distrust it."""

    key: str
    #: Directional, [-1, 1]. None when the component could not be computed —
    #: never 0.0, which would be indistinguishable from "genuinely neutral".
    value: float | None
    #: [0, 1]. How much this particular component's own inputs support it.
    confidence: float
    #: Whether this component may contribute to the directional score at all.
    directional: bool
    evidence: dict[str, Any] = field(default_factory=dict)
    warnings: tuple[str, ...] = field(default_factory=tuple)

    @property
    def available(self) -> bool:
        return self.value is not None

    def to_dict(self) -> dict[str, Any]:
        return {
            "key": self.key,
            "value": None if self.value is None else round(self.value, 4),
            "confidence": round(self.confidence, 4),
            "directional": self.directional,
            "evidence": self.evidence,
            "warnings": list(self.warnings),
        }


def robust_z(value: float, cohort: Sequence[float]) -> float | None:
    """Median/MAD z-score — robust because these distributions have fat tails.

    A mean/stdev z would let a handful of extreme mispricings define "normal"
    and flatten everyone else toward zero.
    """
    if len(cohort) < MIN_COHORT_SIZE:
        return None
    centre = median(cohort)
    deviations = [abs(item - centre) for item in cohort]
    mad = median(deviations)
    if mad <= 0:
        return None
    return (value - centre) / (MAD_TO_SIGMA * mad)


def cohort_key(position: str | None, asset_class: str, market_value: float) -> str:
    """Which population a player's mispricing is judged against.

    Conditioning matters more than it looks: 500 points of gap is a rounding
    error on an elite quarterback and a re-rating on a depth linebacker, so a
    raw gap ranked across the whole board is mostly a ranking of expensive
    players. Position plus a coarse value tier removes both effects.
    """
    tier = "elite" if market_value >= 5000 else "mid" if market_value >= 1500 else "deep"
    return f"{asset_class}:{position or 'UNK'}:{tier}"


def mispricing_component(
    *,
    log_gap: float | None,
    cohort_gaps: Sequence[float],
    fair_value_source_count: int,
    fair_value_dispersion: float | None,
    market_is_stale: bool,
) -> ComponentScore:
    """Independent fair value versus the acquisition market.

    THE primary directional component — the only one this repository has
    out-of-sample evidence for. Positive means the market is below independent
    fair value (a buy).
    """
    warnings: list[str] = []
    if log_gap is None:
        return ComponentScore(
            key="mispricing",
            value=None,
            confidence=0.0,
            directional=True,
            warnings=("no_independent_fair_value",),
        )

    z = robust_z(log_gap, cohort_gaps)
    cohort_relative = z is not None
    if z is None:
        warnings.append("cohort_too_small_for_normalization")
        # Fall back to the raw log gap rather than refusing — the direction is
        # still meaningful, only its calibration is not — but SHRINK it.
        #
        # The first version scaled by 0.35, which made the un-normalized path
        # produce LARGER magnitudes than the normalized one: every top sell on
        # the live board came back with ``cohortZ: None``, i.e. the rows with
        # the least trustworthy evidence had crowded out the rows with the most.
        # A fallback must never be able to outrank the real measurement.
        value = UNNORMALIZED_SHRINKAGE * math.tanh(log_gap / 1.2)
        confidence = 0.25
    else:
        value = math.tanh(z / MISPRICING_Z_SCALE)
        confidence = 0.60

    # More independent boards agreeing is more evidence. Saturating rather than
    # linear: the fifth source adds much less than the second.
    confidence *= fair_value_source_count / (fair_value_source_count + 2.0)

    if fair_value_dispersion is not None and fair_value_dispersion > 0:
        # Sources that disagree wildly produce the same centre as sources that
        # agree, and it is not the same evidence.
        spread_penalty = min(0.5, fair_value_dispersion / 2000.0)
        confidence *= 1.0 - spread_penalty
        if spread_penalty > 0.25:
            warnings.append("sources_disagree_widely")

    if market_is_stale:
        confidence *= 0.5
        warnings.append("market_price_is_stale")

    return ComponentScore(
        key="mispricing",
        value=max(-1.0, min(1.0, value)),
        confidence=max(0.0, min(1.0, confidence)),
        directional=True,
        evidence={
            "logGap": round(log_gap, 4),
            "cohortZ": None if z is None else round(z, 3),
            "cohortRelative": cohort_relative,
            "independentSourceCount": fair_value_source_count,
        },
        warnings=tuple(warnings),
    )


def sharp_flow_component(
    *,
    buys: int,
    sells: int,
    unique_managers: int,
    unique_leagues: int,
    manager_concentration: float | None = None,
) -> ComponentScore:
    """Qualified-manager acquisition direction, as a posterior rather than a ratio.

    A Beta-Binomial posterior instead of ``(buys - sells) / volume`` for one
    reason that matters at this sample size: the ratio reports 1 buy and 0 sells
    as +1.0, indistinguishable from 40-0. The posterior mean of Beta(3, 2) is
    0.6, which is what one observation actually justifies.

    **UNVALIDATED.** There is no historical sharp data in this repository to fit
    or test against, so this component's contribution is an assumption. It is
    computed and shown; it is not evidence that has earned a weight.
    """
    warnings: list[str] = ["unvalidated_component"]
    volume = buys + sells
    if volume <= 0:
        return ComponentScore(
            key="sharp_flow",
            value=None,
            confidence=0.0,
            directional=True,
            warnings=("no_sharp_activity", "unvalidated_component"),
        )

    alpha = SHARP_PRIOR_ALPHA + buys
    beta = SHARP_PRIOR_BETA + sells
    posterior_mean = alpha / (alpha + beta)
    direction = 2.0 * posterior_mean - 1.0

    # Posterior standard deviation — the honest width of what we know.
    variance = (alpha * beta) / (((alpha + beta) ** 2) * (alpha + beta + 1.0))
    stdev = math.sqrt(variance)

    # Breadth: one manager trading ten times is one opinion, not ten.
    breadth = unique_managers / (unique_managers + 3.0)
    league_breadth = unique_leagues / (unique_leagues + 2.0)
    confidence = breadth * league_breadth * (1.0 - min(0.9, stdev * 3.0))

    if unique_managers <= 1:
        warnings.append("single_manager")
        confidence *= 0.4
    if unique_leagues <= 1:
        warnings.append("single_league")
        confidence *= 0.5
    if manager_concentration is not None and manager_concentration > 0.5:
        warnings.append("dominated_by_one_manager")
        confidence *= 1.0 - min(0.6, manager_concentration - 0.5)

    return ComponentScore(
        key="sharp_flow",
        value=max(-1.0, min(1.0, direction)),
        confidence=max(0.0, min(1.0, confidence)),
        directional=True,
        evidence={
            "buys": buys,
            "sells": sells,
            "posteriorBuyRate": round(posterior_mean, 4),
            "posteriorStdev": round(stdev, 4),
            "uniqueManagers": unique_managers,
            "uniqueLeagues": unique_leagues,
            # A sharp acquisition says a sharp WANTED the asset. It says nothing
            # about what they paid, and the ledger stores no trade consideration
            # from which a price could be derived.
            "priceAware": False,
        },
        warnings=tuple(warnings),
    )


def momentum_component(
    *,
    trailing_log_change_30d: float | None,
    trailing_log_change_7d: float | None,
) -> ComponentScore:
    """Recent market movement. CONTEXT ONLY — never a directional buy reason.

    ``directional=False`` is the whole point of this component and is enforced
    by ``score.py``, not merely documented here.

    The awkward fact is that momentum is the best market-outcome predictor in
    the panel by a wide margin (+0.38 vs mispricing's +0.09-0.12). Letting it
    into the directional score would raise every backtest number on the market
    target — and would turn Consensus Edge into a device that recommends buying
    whatever just went up, at the top of its move, which is the opposite of the
    product. It is surfaced so a user can see "this is already running" beside a
    mispricing call, and to flag the case where a large gap exists only because
    the price is falling fast.
    """
    if trailing_log_change_30d is None and trailing_log_change_7d is None:
        return ComponentScore(
            key="momentum",
            value=None,
            confidence=0.0,
            directional=False,
            warnings=("no_price_history",),
        )
    primary = (
        trailing_log_change_30d if trailing_log_change_30d is not None else trailing_log_change_7d
    )
    return ComponentScore(
        key="momentum",
        value=max(-1.0, min(1.0, math.tanh((primary or 0.0) / 0.20))),
        confidence=0.5,
        directional=False,
        evidence={
            "trailing30d": (
                None if trailing_log_change_30d is None else round(trailing_log_change_30d, 4)
            ),
            "trailing7d": (
                None if trailing_log_change_7d is None else round(trailing_log_change_7d, 4)
            ),
        },
        warnings=("context_only_not_a_buy_reason",),
    )


def data_quality_component(
    *,
    market_is_stale: bool,
    market_age_days: int,
    fair_value_available: bool,
    sharp_available: bool,
    position_known: bool,
) -> ComponentScore:
    """How much of the required evidence is actually present and current.

    Never directional. Its job is to be able to say "do not act on this".
    """
    warnings: list[str] = []
    score = 1.0
    if not fair_value_available:
        score *= 0.35
        warnings.append("no_independent_fair_value")
    if not sharp_available:
        score *= 0.8
        warnings.append("no_sharp_activity")
    if market_is_stale:
        score *= 0.4
        warnings.append(f"market_price_{market_age_days}d_old")
    if not position_known:
        score *= 0.9
        warnings.append("position_unknown")
    return ComponentScore(
        key="data_quality",
        value=None,
        confidence=max(0.0, min(1.0, score)),
        directional=False,
        evidence={"marketAgeDays": market_age_days},
        warnings=tuple(warnings),
    )


def detect_conflict(components: Mapping[str, ComponentScore]) -> dict[str, Any]:
    """Strong opposing directional evidence must not average into Neutral.

    A score near zero has two completely different meanings — "everything agrees
    this is fairly priced" and "half the evidence screams buy while the other
    half screams sell" — and collapsing them is how a system loses trust.
    """
    directional = [
        component
        for component in components.values()
        if component.directional and component.value is not None
    ]
    positive = [c for c in directional if c.value is not None and c.value >= CONFLICT_THRESHOLD]
    negative = [c for c in directional if c.value is not None and c.value <= -CONFLICT_THRESHOLD]
    conflicted = bool(positive and negative)
    return {
        "conflicted": conflicted,
        "positiveComponents": [c.key for c in positive],
        "negativeComponents": [c.key for c in negative],
    }
