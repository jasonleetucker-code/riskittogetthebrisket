"""The hierarchical decision engine v3 (SHADOW challenger).

``evaluate_team`` answers "should THIS team make this trade?" from that team's
own layers; ``evaluate_two_sided`` runs it once per team, independently -- no
zero-sum inference -- and names the trade's shape.

Steps, never a weighted sum and never an aggregate utility:

1. classify the terms in their own units (``terms``);
2. pick the ONE league_scored_projection vote (C unless a promoted outcome
   layer replaces it) and validate the voting set against the lineage
   registry -- a violation RAISES;
3. INSUFFICIENT_EVIDENCE when an essential input for the strategy is not
   available (each missing item named; nothing imputed);
4. read the policy row strategy x A-class x P-class (``policy``); a TIE is NO
   with ``neutral_tag`` and LOW confidence;
5. confidence label (weakest axis), reasons, what-would-change, key numbers,
   double-count guard, receipt.

It emits verdict CODES only.  It computes no canonical value, resolves no
league, reads no file except its own config, writes nothing and executes
nothing (``executes`` is always ``False``).  The served headline stays with
``src/trade/trade_decision.py``; nothing in production imports this package
in batch 1.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict
from typing import Any, Mapping

from src.evidence_lineage.registry import REGISTRY_VERSION, assert_voting_terms_valid
from src.trade.decision_engine import confidence as confidence_mod
from src.trade.decision_engine.contracts import (
    ENGINE_VERSION,
    STRATEGIES,
    TeamDecision,
    TeamLayers,
    TermResult,
    TwoSidedDecision,
)
from src.trade.decision_engine.policy import class_key, decide_row
from src.trade.decision_engine.reasons import build_reasons, what_would_change
from src.trade.decision_engine.terms import (
    classify_asset,
    classify_horizon,
    classify_lineup,
    classify_title,
    get,
    num,
    select_p_term,
)
from src.valuation_math import fairness_bands

#: Known biases of the served champion (``trade_decision.decide``), stamped on
#: every receipt so an agreement-rate diagnostic is read with them in view.
KNOWN_CHAMPION_BIASES = (
    {
        "code": "worsens_overage_no_release_charge",
        "detail": "trade_decision._objective_value charges the forced release only when "
        "overLimitBefore == 0, so a trade that worsens an existing overage is charged "
        "nothing; this engine reads the marginal roster_capacity.forced_drop_cost.",
    },
    {
        "code": "roster_band_grows_with_standard_error",
        "detail": "the champion's roster band is max(materialityPpg, 2 x SE): imprecision "
        "widens the band instead of being reported as low precision.",
    },
    {
        "code": "agreement_counted_as_corroboration",
        "detail": "the champion rates market + roster agreement HIGH although both share "
        "current-season production (evidence_lineage partial overlap).",
    },
)


def _hash(obj: Any) -> str:
    blob = json.dumps(obj, sort_keys=True, separators=(",", ":"), default=str, ensure_ascii=True)
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()[:16]


def _unavailable(reason: str | None, state: str = "unavailable") -> dict[str, Any]:
    return {"state": state, "reason": reason or state}


def _pair(
    m: Mapping[str, Any],
    before: tuple[str, str],
    after: tuple[str, str],
    unit: str,
    why: str | None,
):
    b, a = num(get(m, *before)), num(get(m, *after))
    if b is None or a is None:
        return _unavailable(why or "not_reported")
    return {"before": b, "after": a, "unit": unit}


def _key_numbers(
    layers: TeamLayers,
    a: TermResult,
    a_detail: Mapping[str, Any],
    c: TermResult,
    d1: TermResult,
    d2: TermResult,
) -> dict[str, Any]:
    asset, lineup = layers.asset or {}, layers.lineup or {}
    out: dict[str, Any] = {
        "market": _pair(
            asset,
            ("sendRaw", "send_raw"),
            ("recvRaw", "recv_raw"),
            "canonical value (raw sum)",
            a.reason,
        ),
        "vaGap": (
            {"value": a_detail["vaGap"], "unit": "canonical value (adjusted package)"}
            if num(a_detail.get("vaGap")) is not None
            else _unavailable(a.reason)
        ),
        "lineupPpg": _pair(
            lineup, ("beforePpg", "before_ppg"), ("afterPpg", "after_ppg"), "lineup ppg", c.reason
        ),
        "depth": _pair(
            lineup,
            ("depthBefore", "depth_before"),
            ("depthAfter", "depth_after"),
            "depth ppg",
            c.reason,
        ),
    }
    q10 = num(get(lineup, "downsideQ10", "downside_q10"))
    out["riskDownsideQ10"] = (
        {"value": q10, "unit": "lineup ppg"}
        if q10 is not None
        else _unavailable("no_predictive_uncertainty")
    )
    for key, t in (("championshipDelta", d1), ("multiYear", d2)):
        if t.counted_as_vote and t.value is not None:
            out[key] = {"value": t.value, "unit": t.unit}
        elif t.state == "available":
            out[key] = _unavailable("not_promoted", state="not_promoted")
        else:
            out[key] = _unavailable(t.reason, state=t.state)
    return out


def evaluate_team(
    layers: TeamLayers,
    *,
    params: Mapping[str, Any],
    promoted_families: frozenset[str] = frozenset(),
) -> TeamDecision:
    a, a_detail = classify_asset(layers.asset or {}, params)
    c, d1, d2, chosen = select_p_term(
        classify_lineup(layers.lineup or {}, params),
        classify_title(layers.title or {}, params),
        classify_horizon(layers.horizon or {}, params),
        promoted_families=frozenset(promoted_families),
        params=params,
    )
    terms = {"A": a, "C": c, "D1": d1, "D2": d2}
    p = terms[chosen] if chosen else None
    lineage = assert_voting_terms_valid([asdict(t) for t in terms.values()])

    strategy = layers.strategy if layers.strategy in STRATEGIES else None
    c_not_applicable = (
        c.state != "available" and c.reason in params["terms"]["C"]["notApplicableReasons"]
    )

    def p_satisfied(s: str, p_voting: bool) -> bool:
        return "P" not in params["essentials"][s] or p_voting or c_not_applicable

    missing: list[dict[str, Any]] = []
    if strategy is None:
        missing.append(
            {"code": "strategy_unknown", "layer": "strategy", "source": layers.strategy_source}
        )
    if not a.counted_as_vote:
        gates = a_detail.get("gateCodes") or []
        if gates:
            missing.extend({"code": str(g), "layer": "A"} for g in gates)
        else:
            missing.append({"code": f"asset_term_{a.state}", "layer": "A", "reason": a.reason})
    if strategy is not None and not p_satisfied(strategy, p is not None):
        missing.append({"code": f"roster_term_{c.state}", "layer": "C", "reason": c.reason})
    if layers.roster_known is not True:
        missing.append({"code": "roster_unknown", "layer": "roster"})
    if layers.roster_limit_known is not True:
        missing.append({"code": "roster_limit_unknown", "layer": "rosterLimit"})

    key_numbers = _key_numbers(layers, a, a_detail, c, d1, d2)
    base_receipt = {
        "engineVersion": ENGINE_VERSION,
        "paramSetId": params["paramSetId"],
        "inputHashes": {
            "asset": _hash(layers.asset),
            "lineup": _hash(layers.lineup),
            "title": _hash(layers.title),
            "horizon": _hash(layers.horizon),
            "strategy": _hash([layers.strategy, layers.strategy_source, layers.posture_label]),
        },
        "packageModel": {
            "id": (get(layers.asset, "packageModel") or {}).get("id"),
            "configState": (get(layers.asset, "packageModel") or {}).get("configState"),
        },
        "fairnessBands": fairness_bands.receipt(),
        "promotedFamilies": sorted(promoted_families),
        "lineageRegistryVersion": REGISTRY_VERSION,
        "lineageVerdict": lineage.to_dict(),
        "knownChampionBiases": [dict(b) for b in KNOWN_CHAMPION_BIASES],
        "isProbability": False,
        "predictiveProbability": None,
    }
    guard = {
        "lineageVerdict": lineage.to_dict(),
        "votingTerms": [t.term for t in terms.values() if t.counted_as_vote],
        "agreementNeverCorroborates": bool(lineage.partial_overlaps),
    }

    if missing:
        wwc = [{"kind": "availability", "requires": [m["code"] for m in missing], "flipsTo": None}]
        return TeamDecision(
            team_id=layers.team_id,
            verdict="INSUFFICIENT_EVIDENCE",
            neutral_tag=False,
            strategy=strategy or "UNKNOWN",
            strategy_source=layers.strategy_source,
            terms=tuple(terms.values()),
            policy_row="insufficient",
            predictive_probability=None,
            confidence="low",
            confidence_bottleneck="coverage",
            confidence_axes={"coverage": "low"},
            reasons=(),
            key_numbers=key_numbers,
            what_would_change=tuple(wwc),
            missing_evidence=tuple(missing),
            double_count_guard={**guard, "vaRelation": None},
            receipt={**base_receipt, "policyRow": "insufficient"},
        )

    assert strategy is not None
    outcome = decide_row(params, strategy, class_key(a, voting_required=True), class_key(p))
    conf = confidence_mod.assess(
        insufficient=False,
        raw_verdict=outcome.raw_verdict,
        decided_by=outcome.decided_by,
        a=a,
        p=p,
        # An offseason (not-applicable) roster term is not missing evidence.
        p_required="P" in params["essentials"][strategy] and not c_not_applicable,
        agreement_cap=lineage.agreement_cap,
        asset=layers.asset or {},
        asset_detail=a_detail,
        freshness=layers.freshness or {},
        params=params,
    )
    reasons = build_reasons(
        raw_verdict=outcome.raw_verdict,
        decided_by=outcome.decided_by,
        strategy=strategy,
        a=a,
        p=p,
        asset_detail=a_detail,
        va_relation=conf["vaRelation"],
    )
    wwc = what_would_change(
        params=params,
        asset=layers.asset or {},
        asset_detail=a_detail,
        strategy=strategy,
        a=a,
        p=p,
        terms=terms,
        outcome=outcome,
        p_satisfied=p_satisfied,
    )
    return TeamDecision(
        team_id=layers.team_id,
        verdict=outcome.verdict,  # type: ignore[arg-type]
        neutral_tag=outcome.neutral_tag,
        strategy=strategy,
        strategy_source=layers.strategy_source,
        terms=tuple(terms.values()),
        policy_row=outcome.row_key,
        predictive_probability=None,
        confidence=conf["level"],
        confidence_bottleneck=conf["bottleneck"],
        confidence_axes=dict(conf["axes"]),
        reasons=reasons,
        key_numbers=key_numbers,
        what_would_change=wwc,
        missing_evidence=(),
        double_count_guard={
            **guard,
            "vaRelation": conf["vaRelation"],
            "overlapGuardCap": "medium" if conf["vaRelation"] == "aligned" else None,
        },
        receipt={
            **base_receipt,
            "policyRow": outcome.row_key,
            "decidedBy": outcome.decided_by,
            "confidenceWhy": dict(conf["why"]),
        },
    )


def shape_of(a: TeamDecision, b: TeamDecision) -> str:
    verdicts = (a.verdict, b.verdict)
    if "INSUFFICIENT_EVIDENCE" in verdicts:
        return "insufficient"
    yes = verdicts.count("YES")
    return {2: "good_for_both", 1: "good_for_one", 0: "bad_for_both"}[yes]


def evaluate_two_sided(
    team_a: TeamLayers,
    team_b: TeamLayers,
    *,
    params: Mapping[str, Any],
    promoted_families: frozenset[str] = frozenset(),
) -> TwoSidedDecision:
    """Each team evaluated from its OWN layers; one side's gain is never
    inferred from the other's loss."""
    da = evaluate_team(team_a, params=params, promoted_families=promoted_families)
    db = evaluate_team(team_b, params=params, promoted_families=promoted_families)
    return TwoSidedDecision(
        engine_version=ENGINE_VERSION,
        param_set_id=params["paramSetId"],
        teams=(da, db),
        shape=shape_of(da, db),  # type: ignore[arg-type]
    )
