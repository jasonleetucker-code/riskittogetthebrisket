"""Analyze Trade — the ONE canonical decision-synthesis owner (V1-43 / C7-DESK-01, V1 depth).

Binding design record: ``docs/trade/TRADE_DECISION_SYNTHESIS_PLAN_2026-08-11.md``.
That plan describes a much larger eventual surface (CE-05 Trade Desk): canonical
equity, market corroboration, Monte Carlo uncertainty, roster marginal impact,
future/window context, optional intelligence context, and constraints/owner
policy, synthesized by UNIQUE INFORMATION rather than by weighting every visible
panel (the naive-average trap the plan names explicitly: value + MC + second
opinions + team impact would double/triple-count the same canonical sources).

This module is deliberately narrower than that full vision — "V1 depth" per
``docs/VERSION_1_COMPLETION_CONTRACT.md`` row V1-43 — and says so rather than
quietly presenting a partial synthesis as the finished product:

* **Included** (both already single-owner, already VERIFIED elsewhere, and
  genuinely INDEPENDENT information):
    1. canonical equity — KTC's Value Adjustment applied to the trade's two
       sides (``src.trade.ktc_va.adjusted_pair_totals`` — the same function
       ``suggestions._va_gap`` wraps; this module calls the owner directly
       rather than re-deriving anything);
    2. roster marginal impact — the Team Strength before/after delta from
       ``finalRosterSimulation`` (V1-42 / C2-SIM-01, already wired into
       ``/api/trade/simulate``).  A DIFFERENT canonical field
       (``strengthBefore.total`` / ``strengthAfter.total``) from a DIFFERENT
       computation (lineup-aware exact assignment, not asset value) than
       dimension 1 — the two cannot double-count each other structurally,
       not merely by convention. See ``tests/trade/test_analyze_trade.py::
       test_dimensions_read_disjoint_canonical_fields`` for the guard.

* **Explicitly NOT included, named rather than silently absent**:
    - market corroboration / comparable trades (plan §B, §C.2) — the backing
      infrastructure (``C4-MTL-01`` real-market-trade ledger, ``C4-MTL-03``
      comparable-trade matching) is ABSENT per
      ``docs/C_SERIES_SCOPE_MANIFEST.md`` and C7-DESK-01's own declared
      dependency list; there is no data to synthesize;
    - Monte Carlo uncertainty (plan §A) — the plan's own audit section lists
      open concerns (synthetic flat ±15% bands on unstamped rows, an
      unvalidated same-team/same-position correlation model) that have not
      been revalidated; folding an unaudited uncertainty model into a new
      canonical recommendation surface would import that debt rather than
      resolve it;
    - owner constraint vetoes (plan dimension 7) beyond what
      ``src.trade.constraints`` (C3-CON-01) already enforces upstream of
      trade GENERATION — this module analyzes a trade the user typed in
      (the manual Trade Calculator's free-form, deliberately unconstrained
      surface per that owner's own docstring), so LOCK/EXCLUDE does not
      apply here by design, not by omission.

No weight-tuning.  Per the plan's own governance rule ("do not tune weights
simply until recommendations look right"), the two included dimensions are
combined by an explicit, auditable RULE TABLE over each dimension's SIGN
(favors / opposes / neutral) plus the equity dimension's existing canonical
magnitude bucket (``suggestions._fairness_label`` — even / lean / stretch,
already calibrated and used everywhere else a gap is shown to a user) —
never a fabricated numeric weight or a normalized sum of two differently
scaled quantities.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from src.trade.ktc_va import adjusted_pair_totals
from src.trade.suggestions import _fairness_label

#: The five product-facing verdicts (plan §C, "Product job").
RECOMMENDATIONS = ("MAKE", "LEAN_MAKE", "TOO_CLOSE", "LEAN_PASS", "PASS")

#: Dimensions this V1-depth pass deliberately does not compute, named so
#: "not included" and "computed and found neutral" never look the same.
_UNAVAILABLE_DIMENSIONS = (
    {
        "dimension": "marketCorroboration",
        "reason": "no_backing_ledger",
        "notes": "C4-MTL-01 (real market trades) and C4-MTL-03 (comparable-trade "
        "matching) are ABSENT — there is no independent vendor/comp evidence to synthesize.",
    },
    {
        "dimension": "uncertainty",
        "reason": "unaudited_model",
        "notes": "Monte Carlo value-uncertainty bands/correlation have open revalidation "
        "items (see docs/trade/TRADE_DECISION_SYNTHESIS_PLAN_2026-08-11.md §A) and are not "
        "folded into this recommendation until that audit closes.",
    },
)


def _direction(value: float, *, epsilon: float = 0.0) -> str:
    if value > epsilon:
        return "favors"
    if value < -epsilon:
        return "opposes"
    return "neutral"


@dataclass
class DimensionResult:
    """One independent piece of evidence, normalized per the plan's own shape:
    direction / magnitude / confidence-relevant detail — never a raw score
    meant to be summed with another dimension's raw score."""

    name: str
    available: bool
    direction: str | None = None
    detail: dict[str, Any] = field(default_factory=dict)
    unavailable_reason: str | None = None

    def to_dict(self) -> dict[str, Any]:
        out: dict[str, Any] = {"dimension": self.name, "available": self.available}
        if self.available:
            out["direction"] = self.direction
            out["detail"] = self.detail
        else:
            out["unavailableReason"] = self.unavailable_reason
        return out


@dataclass
class AnalyzeTradeResult:
    recommendation: str
    confidence: str
    reasons_for: list[str]
    reasons_against: list[str]
    dimensions: list[DimensionResult]
    unavailable_dimensions: list[dict[str, str]]

    def to_dict(self) -> dict[str, Any]:
        return {
            "recommendation": self.recommendation,
            "confidence": self.confidence,
            "reasonsFor": self.reasons_for,
            "reasonsAgainst": self.reasons_against,
            "dimensions": [d.to_dict() for d in self.dimensions],
            "unavailableDimensions": list(self.unavailable_dimensions),
        }


def _equity_dimension(
    sending_values: list[float], receiving_values: list[float]
) -> DimensionResult:
    """Canonical equity, VA-adjusted.  Calls the owner directly — no re-derivation."""
    if not sending_values and not receiving_values:
        return DimensionResult(
            name="equity", available=False, unavailable_reason="no_priced_assets_either_side"
        )
    send_adj, recv_adj, _send_va, _recv_va = adjusted_pair_totals(sending_values, receiving_values)
    gap = recv_adj - send_adj  # positive = the selected team comes out ahead
    magnitude = _fairness_label(gap)
    return DimensionResult(
        name="equity",
        available=True,
        direction=_direction(gap),
        detail={
            "vaAdjustedGap": int(round(gap)),
            "magnitude": magnitude,
            "sendingAdjusted": round(send_adj, 1),
            "receivingAdjusted": round(recv_adj, 1),
        },
    )


def _roster_impact_dimension(final_roster_simulation: dict[str, Any] | None) -> DimensionResult:
    """Team Strength before/after delta from the already-VERIFIED V1-42
    simulation.  A DIFFERENT canonical computation than equity — lineup-aware
    exact assignment over the post-trade roster, not a value sum."""
    if not final_roster_simulation or final_roster_simulation.get("available", True) is not True:
        reason = "no_team_selected_or_uncomputable"
        if isinstance(final_roster_simulation, dict):
            reason = (
                final_roster_simulation.get("unavailableReason")
                or final_roster_simulation.get("unavailable")
                or reason
            )
        return DimensionResult(name="rosterImpact", available=False, unavailable_reason=str(reason))
    strength_before = (final_roster_simulation.get("strengthBefore") or {}).get("total")
    strength_after = (final_roster_simulation.get("strengthAfter") or {}).get("total")
    if strength_before is None or strength_after is None:
        return DimensionResult(
            name="rosterImpact", available=False, unavailable_reason="team_strength_not_stamped"
        )
    delta = float(strength_after) - float(strength_before)
    return DimensionResult(
        name="rosterImpact",
        available=True,
        direction=_direction(delta),
        detail={
            "teamStrengthBefore": round(float(strength_before), 1),
            "teamStrengthAfter": round(float(strength_after), 1),
            "teamStrengthDelta": round(delta, 1),
        },
    )


def _recommend(equity: DimensionResult, roster: DimensionResult) -> tuple[str, str]:
    """The rule table.  No numeric weights — direction + the equity
    dimension's own pre-existing magnitude bucket only."""
    if not equity.available:
        return "TOO_CLOSE", "LOW"

    magnitude = equity.detail.get("magnitude", "even")
    eq_dir = equity.direction

    if not roster.available:
        # Single available dimension: confidence can never reach HIGH.
        if eq_dir == "favors":
            return ("MAKE" if magnitude == "stretch" else "LEAN_MAKE"), "MEDIUM"
        if eq_dir == "opposes":
            return ("PASS" if magnitude == "stretch" else "LEAN_PASS"), "MEDIUM"
        return "TOO_CLOSE", "LOW"

    roster_dir = roster.direction
    agree = eq_dir == roster_dir or roster_dir == "neutral" or eq_dir == "neutral"
    conflict = (eq_dir == "favors" and roster_dir == "opposes") or (
        eq_dir == "opposes" and roster_dir == "favors"
    )

    if conflict:
        return "TOO_CLOSE", "MEDIUM"

    if eq_dir == "favors" or (eq_dir == "neutral" and roster_dir == "favors"):
        if magnitude == "stretch" and roster_dir == "favors":
            return "MAKE", "HIGH"
        if magnitude != "even" or roster_dir == "favors":
            return "LEAN_MAKE", "HIGH" if agree and magnitude != "even" else "MEDIUM"
        return "TOO_CLOSE", "LOW"

    if eq_dir == "opposes" or (eq_dir == "neutral" and roster_dir == "opposes"):
        if magnitude == "stretch" and roster_dir == "opposes":
            return "PASS", "HIGH"
        if magnitude != "even" or roster_dir == "opposes":
            return "LEAN_PASS", "HIGH" if agree and magnitude != "even" else "MEDIUM"
        return "TOO_CLOSE", "LOW"

    return "TOO_CLOSE", "LOW"


def _reasons(equity: DimensionResult, roster: DimensionResult) -> tuple[list[str], list[str]]:
    reasons_for: list[str] = []
    reasons_against: list[str] = []

    if equity.available:
        gap = equity.detail["vaAdjustedGap"]
        if equity.direction == "favors":
            reasons_for.append(
                f"+{gap} value to your side after KTC Value Adjustment ({equity.detail['magnitude']} gap)"
            )
        elif equity.direction == "opposes":
            reasons_against.append(
                f"{gap} value against your side after KTC Value Adjustment "
                f"({equity.detail['magnitude']} gap)"
            )

    if roster.available:
        delta = roster.detail["teamStrengthDelta"]
        if roster.direction == "favors":
            reasons_for.append(f"Team Strength improves by {delta:+.0f} after the re-solved lineup")
        elif roster.direction == "opposes":
            reasons_against.append(
                f"Team Strength declines by {delta:+.0f} after the re-solved lineup"
            )
    else:
        reasons_against.append(
            f"Roster marginal impact unavailable ({roster.unavailable_reason}) — recommendation "
            "is based on equity alone"
        )

    return reasons_for, reasons_against


def analyze_trade(simulation: dict[str, Any]) -> dict[str, Any]:
    """Synthesize one Analyze Trade verdict from an already-computed
    ``src.api.trade_simulator.simulate_trade`` payload.

    Pure composition: reads ``receiving`` / ``sending`` (for equity) and
    ``finalRosterSimulation`` (for roster impact) verbatim off that payload.
    Computes no canonical value and calls no engine simulation itself does
    not already call — this is a synthesis layer, not a third trade engine.
    """
    receiving = simulation.get("receiving") or []
    sending = simulation.get("sending") or []
    sending_values = [a["value"] for a in sending if a.get("value") is not None]
    receiving_values = [a["value"] for a in receiving if a.get("value") is not None]

    equity = _equity_dimension(sending_values, receiving_values)
    roster = _roster_impact_dimension(simulation.get("finalRosterSimulation"))

    recommendation, confidence = _recommend(equity, roster)
    reasons_for, reasons_against = _reasons(equity, roster)

    result = AnalyzeTradeResult(
        recommendation=recommendation,
        confidence=confidence,
        reasons_for=reasons_for,
        reasons_against=reasons_against,
        dimensions=[equity, roster],
        unavailable_dimensions=list(_UNAVAILABLE_DIMENSIONS),
    )
    return result.to_dict()
