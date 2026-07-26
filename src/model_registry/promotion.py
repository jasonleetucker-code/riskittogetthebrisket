"""The champion-challenger decision.

A refit produces a CHALLENGER.  It becomes champion only by beating the
incumbent on the held-out criterion by a margin larger than the
criterion's own noise.  Everything else is rejected and kept.

Why a margin, and why the comparison must be PAIRED
───────────────────────────────────────────────────
The criterion's absolute level is not stable: re-scoring the committed
OFFENSE master against 30 consecutive FantasyCalc snapshots (2026-04-03
to 04-08) gave 584.90 to 653.04 — a 68-point range, sd 19.28.  A rule
that compared this week's challenger to last week's champion SCORE
would be reading five days of market drift as model quality.

That drift is common-mode, so the comparison is always made on ONE
snapshot with both curves scored against it.  Measured on the same 30
snapshots, the paired delta is near-deterministic:

    challenger        mean delta    sd    sign flips
    c + 0.001            -13.39   0.01        0/29
    c + 0.005            -66.81   0.08        0/29
    c - 0.020           +257.51   1.51        0/29
    s + 0.200            +37.95   0.95        0/29

So the noise a margin must clear is ~1.5 points, not ~19.  Ties still
go to the INCUMBENT: the cost of holding a slightly stale curve is
bounded, while churning production constants weekly is not — every
promotion invalidates the pins, the caches, and any human's mental
model of the board.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

# Minimum improvement in mean per-source RMSE for a challenger to win.
#
# Measured, not picked round.  Worst observed paired-delta sd across the
# 30-snapshot series above is 1.51 points, so 25 sits ~16x above the
# noise floor.  For scale in parameter terms, a c shift of 0.001 moves
# the criterion ~13 points, so the margin corresponds to roughly
# c +/- 0.002 — tight enough that genuine refits clear it (a real
# c 0.118 -> 0.098 shift moves the criterion ~258) and loose enough
# that a rescrape cannot.
PROMOTION_MARGIN: float = 25.0

# A challenger this much WORSE than the champion is not merely rejected
# — it is evidence the fit itself misbehaved (bad scrape, collapsed
# source) and the run deserves a human.
REGRESSION_ALARM: float = 250.0


@dataclass(frozen=True)
class PromotionDecision:
    """The verdict, with the arithmetic that produced it."""

    promote: bool
    reason: str
    champion_criterion: float | None
    challenger_criterion: float
    margin_required: float
    improvement: float | None
    alarm: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "promote": self.promote,
            "reason": self.reason,
            "championCriterion": (
                round(self.champion_criterion, 4) if self.champion_criterion is not None else None
            ),
            "challengerCriterion": round(self.challenger_criterion, 4),
            "improvement": (round(self.improvement, 4) if self.improvement is not None else None),
            "marginRequired": self.margin_required,
            "alarm": self.alarm,
            "_semantics": {
                "improvement": "champion criterion minus challenger criterion; positive is better",
                "warning": (
                    "a promotion means the challenger generalizes better across "
                    "held-out dynasty markets, NOT that it is more accurate"
                ),
            },
        }


def decide_promotion(
    champion_criterion: float | None,
    challenger_criterion: float,
    *,
    margin: float = PROMOTION_MARGIN,
    alarm_threshold: float = REGRESSION_ALARM,
) -> PromotionDecision:
    """Compare a challenger to the incumbent on the held-out criterion.

    ``champion_criterion is None`` means the incumbent has never been
    evaluated out of sample.  That does NOT hand the win to the
    challenger: an unmeasured incumbent is unknown, not bad, and
    promoting past it would be exactly the autonomous rewrite the
    directive prohibits.  Evaluate the champion first.
    """
    if champion_criterion is None:
        return PromotionDecision(
            promote=False,
            reason=(
                "incumbent has no out-of-sample score; evaluate the champion "
                "before comparing (an unmeasured incumbent is unknown, not beaten)"
            ),
            champion_criterion=None,
            challenger_criterion=challenger_criterion,
            margin_required=margin,
            improvement=None,
        )

    improvement = champion_criterion - challenger_criterion

    if improvement <= -alarm_threshold:
        return PromotionDecision(
            promote=False,
            reason=(
                f"challenger is {-improvement:.1f} points WORSE than the champion "
                f"(alarm threshold {alarm_threshold:.0f}); this is large enough to "
                "suggest the fit or its inputs misbehaved — investigate before refitting"
            ),
            champion_criterion=champion_criterion,
            challenger_criterion=challenger_criterion,
            margin_required=margin,
            improvement=improvement,
            alarm=True,
        )

    if improvement < margin:
        return PromotionDecision(
            promote=False,
            reason=(
                f"improvement {improvement:+.1f} does not clear the {margin:.0f}-point "
                "margin; within criterion noise, so the incumbent keeps the tie"
            ),
            champion_criterion=champion_criterion,
            challenger_criterion=challenger_criterion,
            margin_required=margin,
            improvement=improvement,
        )

    return PromotionDecision(
        promote=True,
        reason=(
            f"challenger improves the held-out criterion by {improvement:.1f} points "
            f"({champion_criterion:.1f} -> {challenger_criterion:.1f}), clearing the "
            f"{margin:.0f}-point margin"
        ),
        champion_criterion=champion_criterion,
        challenger_criterion=challenger_criterion,
        margin_required=margin,
        improvement=improvement,
    )
