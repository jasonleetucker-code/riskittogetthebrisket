"""Effective auction power — a relative draft-capital concentration lens.

WHY THIS EXISTS
---------------
This league's rookie draft is a *linear* draft auctioned for dollars:
72 picks, a fixed $1200 league-wide pool, redistributed by ownership.
Raw draft capital is purely additive (``sum of pick $``).  But because
picks can be **traded and stacked**, the strategic value of a given
team's capital is *not* linear in its dollar total:

  * Far below the field: dollars are nearly face value (you can't win
    contested rookies anyway), with a small haircut for stranded budgets.
  * Crossing above the field into the biggest stack: a convex premium —
    each extra dollar here is what lets you guarantee the #1 rookie and
    *leapfrog* the team directly above you.
  * Already dominant: the premium **saturates** — once your budget is
    enough to buy anything, extra picks are worth *less* than face to
    you (dead budget).  A dominant-stack team is therefore a natural
    pick *seller*; this falls out of the S-curve automatically.

This is a per-league, roster-aware *display lens*.  It NEVER touches the
canonical per-pick dollar values, the $1200 sum, or the global rankings
board (which is scoring-profile-scoped and owner-agnostic — see
CLAUDE.md "Rankings vs. league context").  The transform is **zero-sum**:
a premium for one team is implicitly a discount for the field, so the
league still sums to exactly the original total — no dollars are minted.

PHASE 1 (implemented here): a closed-form S-curve heuristic.
  effective_i ∝ T_i · (1 + GAIN · tanh(z_i / CURVATURE)) + leapfrog,
  renormalized to preserve the league total.  Cheap, explainable,
  tunable via three named constants, zero risk to trusted numbers.

PHASE 2 (spec only — DO NOT build here without sign-off): replace the
heuristic with a Monte-Carlo mini rookie-auction.  Simulate each team
valuing rookies off the *live board*, budget = its pick dollars,
bidding under a roster-need behavioral model; resolve sequentially;
run current vs. post-trade ownership; the delta in board-value of the
rookies a team actually wins = the true marginal value of those picks
*to that team*.
  Inputs: live board rookie values, per-team budgets, per-team roster
    needs (starter gaps by position), reservation-price model.
  Key risk: the bidding/roster-need behavioral model — a poorly tuned
    simulator is strictly worse than a good heuristic, so Phase 2 is
    gated on a tuning + backtest pass against real completed drafts.
  Stochastic: average over many runs (target stable to <1% across
    seeds) before surfacing.
  Integration: Phase 2 replaces (does not duplicate) Phase 1 behind the
    SAME ``effective_auction_power`` signature and the same
    ``effectiveCapital`` API field, so no caller changes.
"""

from __future__ import annotations

import math
import statistics
from dataclasses import dataclass


@dataclass(frozen=True)
class AuctionPowerConstants:
    """Tuning knobs for the Phase 1 heuristic. Conservative defaults.

    * ``premium_gain`` — max fractional swing of the S-curve.  The
      per-team multiplier is bounded to ``[1 - gain, 1 + gain]`` so the
      lens can never wildly distort the trusted raw numbers.
    * ``curvature`` — z-score divisor inside ``tanh``.  Larger ⇒ the
      curve saturates more slowly (you must be further above the field
      before the premium maxes out).
    * ``leapfrog_weight`` — bounded bonus for the single largest stack's
      lead over the 2nd-largest (the "$175 vs $180 → push past them"
      effect).  Also saturates (``tanh``) so a commanding lead doesn't
      keep paying.
    """

    premium_gain: float = 0.35
    curvature: float = 1.25
    leapfrog_weight: float = 0.15


_DEFAULTS = AuctionPowerConstants()


def _round_preserving_total(values: list[float], total: int) -> list[int]:
    """Largest-remainder rounding to a list of ints summing to *total*.

    Mirrors ``server.py::_round_to_budget`` so the effective column
    honours the same exact-budget invariant as raw draft capital.
    """
    floors = [math.floor(v) for v in values]
    deficit = total - sum(floors)
    if deficit <= 0:
        return floors
    remainders = sorted(
        ((v - math.floor(v), i) for i, v in enumerate(values)),
        key=lambda x: (-x[0], x[1]),
    )
    for k in range(int(deficit)):
        floors[remainders[k][1]] += 1
    return floors


def effective_auction_power(
    team_totals: dict[str, float],
    *,
    enabled: bool = True,
    constants: AuctionPowerConstants | None = None,
) -> dict[str, int]:
    """Map raw per-team draft-capital dollars → effective auction power.

    Properties (see module docstring for the economic rationale):

    * **Zero-sum**: the returned values sum to ``round(sum(team_totals))``
      — identical to the raw league total.  Strategic value is
      redistributed, never created.
    * **S-shaped**: below the field → ≈ face / small haircut; crossing
      above → convex premium; already-dominant → saturating (extra
      picks worth *less* than face to that team).
    * **Identity when uninformative**: ``enabled=False``, fewer than two
      teams, or a degenerate (zero-spread) field returns the raw totals
      rounded to the same exact total — guaranteeing the raw path is
      provably unchanged.

    Returns a ``{team: effective_dollars}`` dict of ints.
    """
    k = constants or _DEFAULTS
    names = list(team_totals.keys())
    raw = [float(team_totals[n]) for n in names]
    grand_total = int(round(sum(raw)))

    if not enabled or len(names) < 2 or grand_total <= 0:
        return dict(zip(names, _round_preserving_total(raw, max(grand_total, 0))))

    median = statistics.median(raw)
    # Robust spread: scaled MAD, floored so a near-degenerate field
    # doesn't blow up the z-scores.  Fall back to identity when the
    # field carries no concentration signal at all.
    abs_dev = [abs(v - median) for v in raw]
    mad = statistics.median(abs_dev)
    spread = max(mad * 1.4826, 0.01 * (grand_total / len(names)))
    if spread <= 0:
        return dict(zip(names, _round_preserving_total(raw, grand_total)))

    # S-curve premium: bounded, symmetric, saturating both directions.
    weighted: list[float] = []
    for v in raw:
        z = (v - median) / spread
        mult = 1.0 + k.premium_gain * math.tanh(z / k.curvature)
        weighted.append(v * mult)

    # Leapfrog: bounded, saturating bonus to the single biggest stack
    # for its lead over the 2nd-biggest.  Added pre-renormalization so
    # it stays zero-sum (the field absorbs it on rescale).
    if len(raw) >= 2:
        order = sorted(range(len(raw)), key=lambda i: -raw[i])
        leader, runner = order[0], order[1]
        lead = raw[leader] - raw[runner]
        if lead > 0:
            bonus = (
                k.leapfrog_weight
                * spread
                * math.tanh(lead / spread)
            )
            weighted[leader] += bonus

    # Renormalize so the league still sums to the exact raw total —
    # this is what makes the premium zero-sum across the field.
    wsum = sum(weighted)
    if wsum <= 0:
        return dict(zip(names, _round_preserving_total(raw, grand_total)))
    scaled = [w * (sum(raw) / wsum) for w in weighted]
    return dict(zip(names, _round_preserving_total(scaled, grand_total)))
