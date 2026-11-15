"""Reasons (at most three, one per family) and what would change the verdict.

Reasons carry CODES and text KEYS only; user-facing copy belongs to whichever
surface renders them.  What-would-change is computed by RE-RUNNING the policy
table on perturbed inputs -- a hypothetical added asset re-runs the package
model from scratch (never a raw value subtracted from an adjusted gap).
"""

from __future__ import annotations

from typing import Any, Callable, Mapping

from src.trade.decision_engine.contracts import STRATEGIES, Reason, TermResult
from src.trade.decision_engine.policy import P_CLASSES, class_key, decide_row
from src.trade.decision_engine.terms import a_term_from_values, num
from src.valuation_math import package_model

MAX_REASONS = 3
TIE_REASON = "advantage_indistinguishable_from_current_roster"
VA_PREMIUM_REASON = "va_structural_consolidation_premium"


def _key(code: str) -> str:
    return f"decision_engine.reason.{code}"


def _norm(t: TermResult) -> float | None:
    if t.value is None or not t.band:
        return None
    return round(abs(t.value) / t.band, 3)


def _term_reason(t: TermResult, family: str, words: tuple[str, str, str]) -> Reason:
    gain, loss, even = words
    if t.direction == "favours":
        code, stance = gain, "for"
    elif t.direction == "opposes":
        code, stance = loss, "against"
    else:
        code = even if t.reason in (None, "within_band") else f"{even}_{t.reason}"
        stance = "context"
    return Reason(
        code=code,
        family=family,
        stance=stance,  # type: ignore[arg-type]
        magnitude=_norm(t),
        text_key=_key(code),
        evidence={"term": t.term, "value": t.value, "unit": t.unit, "band": t.band},
    )


def build_reasons(
    *,
    raw_verdict: str,
    decided_by: str,
    strategy: str,
    a: TermResult,
    p: TermResult | None,
    asset_detail: Mapping[str, Any],
    va_relation: str | None,
) -> tuple[Reason, ...]:
    lead: list[Reason] = []
    ranked: list[Reason] = []
    if raw_verdict == "TIE":
        lead.append(
            Reason(
                code=TIE_REASON,
                family="decision_policy",
                stance="against",
                magnitude=None,
                text_key=_key(TIE_REASON),
                evidence={"policy": "conservative_tie"},
            )
        )
    if a.counted_as_vote:
        ranked.append(
            _term_reason(
                a, "market_value", ("market_value_gain", "market_value_loss", "market_value_even")
            )
        )
    if p is not None:
        words = {
            "C": ("lineup_gain", "lineup_loss", "lineup_change_within_band"),
            "D1": ("title_odds_gain", "title_odds_loss", "title_odds_within_band"),
            "D2": ("horizon_gain", "horizon_loss", "horizon_within_band"),
        }[p.term]
        ranked.append(_term_reason(p, "roster_outcome", words))
    charge = num(asset_detail.get("forcedReleaseCharge"))
    if charge is not None and charge > 0 and a.band:
        ranked.append(
            Reason(
                code="forced_release_charged",
                family="roster_capacity",
                stance="against",
                magnitude=round(charge / a.band, 3),
                text_key=_key("forced_release_charged"),
                evidence={"charge": charge, "basis": asset_detail.get("forcedReleaseBasis")},
            )
        )
    context: list[Reason] = []
    if decided_by == "strategy":
        context.append(
            Reason(
                code="strategy_breaks_disagreement",
                family="strategy",
                stance="context",
                magnitude=None,
                text_key=_key("strategy_breaks_disagreement"),
                evidence={"strategy": strategy},
            )
        )
    if va_relation == "opposed":
        context.append(
            Reason(
                code=VA_PREMIUM_REASON,
                family="package_structure",
                stance="context",
                magnitude=None,
                text_key=_key(VA_PREMIUM_REASON),
                evidence={
                    "note": "the geometric VA credits the consolidating side; an expected "
                    "artifact, not evidence against the trade"
                },
            )
        )
    ranked.sort(key=lambda r: -(r.magnitude if r.magnitude is not None else -1.0))
    out: list[Reason] = []
    families: set[str] = set()
    for r in [*lead, *ranked, *context]:
        if r.family in families:
            continue
        families.add(r.family)
        out.append(r)
        if len(out) == MAX_REASONS:
            break
    return tuple(out)


def _code(outcome: Any) -> dict[str, Any]:
    return {"flipsTo": outcome.verdict, "neutralTag": outcome.neutral_tag}


def what_would_change(
    *,
    params: Mapping[str, Any],
    asset: Mapping[str, Any],
    asset_detail: Mapping[str, Any],
    strategy: str,
    a: TermResult,
    p: TermResult | None,
    terms: Mapping[str, TermResult],
    outcome: Any,
    p_satisfied: Callable[[str, bool], bool],
) -> tuple[dict[str, Any], ...]:
    """Each entry names one perturbation and the verdict it would produce."""
    out: list[dict[str, Any]] = []
    a_class = class_key(a, voting_required=True)
    p_class = class_key(p)
    current = (outcome.verdict, outcome.neutral_tag)

    # 1. Price grid: one more asset on the side that would move the answer.
    send = [v for v in (num(x) for x in asset.get("sendValues") or ()) if v is not None and v > 0]
    recv = [v for v in (num(x) for x in asset.get("recvValues") or ()) if v is not None and v > 0]
    model = (asset.get("packageModel") or {}).get("id")
    charge = num(asset_detail.get("forcedReleaseCharge"))
    grid = params["whatWouldChange"]
    if not send and not recv:
        out.append({"kind": "price", "state": "unavailable", "reason": "package_values_missing"})
    elif model not in package_model.PACKAGE_MODELS or charge is None:
        out.append({"kind": "price", "state": "unavailable", "reason": "package_model_unresolved"})
    else:
        side = "receive" if outcome.verdict == "NO" else "send"
        found = None
        for v in range(grid["priceGridStep"], grid["priceGridMax"] + 1, grid["priceGridStep"]):
            s2, r2 = (send, [*recv, float(v)]) if side == "receive" else ([*send, float(v)], recv)
            a2 = a_term_from_values(s2, r2, charge, params, model_id=model)
            o2 = decide_row(params, strategy, class_key(a2, voting_required=True), p_class)
            if (o2.verdict, o2.neutral_tag) != current:
                found = {"kind": "price", "side": side, "assetValue": v, **_code(o2)}
                break
        out.append(
            found
            or {
                "kind": "price",
                "side": side,
                "flipsTo": None,
                "searchedUpTo": grid["priceGridMax"],
            }
        )

    # 2. Strategy flip (only strategies whose essentials this team meets).
    for s in STRATEGIES:
        if s == strategy:
            continue
        if not p_satisfied(s, p is not None):
            out.append({"kind": "strategy", "strategy": s, "flipsTo": "INSUFFICIENT_EVIDENCE"})
            continue
        o2 = decide_row(params, s, a_class, p_class)
        if (o2.verdict, o2.neutral_tag) != current:
            out.append({"kind": "strategy", "strategy": s, **_code(o2)})

    # 3. A currently non-voting layer arriving.
    if p is None:
        by_class = {}
        for pc in P_CLASSES[:-1]:
            o2 = decide_row(params, strategy, a_class, pc)
            by_class[pc] = {"verdict": o2.verdict, "neutralTag": o2.neutral_tag}
        out.append(
            {
                "kind": "layer_arrival",
                "layer": "C",
                "state": terms["C"].state,
                "outcomesByClass": by_class,
            }
        )
    for name in ("D1", "D2"):
        t = terms[name]
        if not t.counted_as_vote:
            out.append(
                {
                    "kind": "layer_arrival",
                    "layer": name,
                    "state": t.state,
                    "flipsTo": None,
                    "note": "votes only after a preregistered, owner-approved promotion",
                }
            )

    # 4. Availability flip: the voting roster term stops voting.
    if p is not None:
        if not p_satisfied(strategy, False):
            out.append(
                {"kind": "availability", "layer": p.term, "flipsTo": "INSUFFICIENT_EVIDENCE"}
            )
        else:
            o2 = decide_row(params, strategy, a_class, "-")
            if (o2.verdict, o2.neutral_tag) != current:
                out.append({"kind": "availability", "layer": p.term, **_code(o2)})
    return tuple(out)
