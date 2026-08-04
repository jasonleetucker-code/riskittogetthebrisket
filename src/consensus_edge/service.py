"""Assemble one Consensus Edge board from a live contract.

The single place components are combined, so no frontend and no second
endpoint can reimplement the formula and drift from it — the failure the
repo already lived through with ``computeUnifiedRanks`` on the client.

Explanations are generated here too, from the structured evidence and
nothing else.  A sentence is only emitted when the number backing it is
present, so the prose cannot claim more than the data supports.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from src.consensus_edge import MODEL_VERSION, opportunity, params as params_mod, score as score_mod
from src.consensus_edge import sharp_flow as sf
from src.consensus_edge.fair_value import coverage as fv_coverage, fair_value_index
from src.consensus_edge.mispricing import score_index

STATUS_OK = "ok"
STATUS_NO_CONTRACT = "no_contract"


def _explain(row: dict[str, Any]) -> list[str]:
    """Plain-language reasons, each backed by a field on the row.

    Deliberately a list of independent sentences rather than one
    paragraph: the UI shows the first two and the card shows all of
    them, and a paragraph would have to be re-split to do that.
    """
    parts: list[str] = []
    mis = row.get("mispricing") or {}
    if mis.get("score") is not None and mis.get("pctGap") is not None:
        direction = "above" if mis["pctGap"] > 0 else "below"
        parts.append(
            f"Our anchor-free fair value is {abs(mis['pctGap']):.0%} {direction} the market "
            f"({mis['fairValue']:.0f} vs {mis['marketValue']:.0f})."
        )
        if mis.get("cohortLevel") == "family":
            parts.append(
                "Measured against a pooled position cohort rather than an exact "
                "value tier, because too few peers priced at this level."
            )

    flow = row.get("sharpFlow") or {}
    if flow.get("direction") is not None:
        verb = "acquiring" if flow["direction"] > 0 else "moving off"
        parts.append(
            f"Qualified managers have been net {verb} this player across "
            f"{flow.get('uniqueManagers', 0)} managers and "
            f"{flow.get('uniqueLeagues', 0)} leagues."
        )
    elif flow.get("reason"):
        parts.append("No qualified-manager activity supports or contradicts this.")

    opp = row.get("opportunity") or {}
    if opp.get("score") is None and opp.get("absentAxes"):
        parts.append("Role and usage evidence was not available, so this rests on price alone.")

    conflict = row.get("conflict") or {}
    if conflict.get("conflicted"):
        parts.append("Components disagree, so no directional call is made until that resolves.")
    return parts


def build_board(
    contract: dict[str, Any] | None,
    *,
    movements_by_asset: dict[str, Any] | None = None,
    rank_history_by_player: dict[str, list[dict[str, Any]]] | None = None,
    params: dict[str, Any] | None = None,
    hours_stale: float | None = None,
) -> dict[str, Any]:
    """Score every player on the contract.

    ``movements_by_asset`` of ``None`` means no ledger — Sharp Flow is
    then reported unavailable and omitted from the composite rather than
    contributing a neutral zero.
    """
    if not contract:
        return {
            "status": STATUS_NO_CONTRACT,
            "message": "No contract loaded; Consensus Edge has nothing to score.",
            "players": [],
        }

    p = params or params_mod.load()
    raw_payload = contract.get("_rawPayload") or contract
    index = fair_value_index(raw_payload)
    mispricing = score_index(index)
    flow = sf.sharp_flow_index(movements_by_asset, p)

    players: list[dict[str, Any]] = []
    for key, entry in index.items():
        mis = mispricing.get(key) or {}
        flow_entry = (flow.get("assets") or {}).get(key) or {}
        opp = opportunity.assess(rank_history=(rank_history_by_player or {}).get(key))

        components: dict[str, float | None] = {
            "mispricing": mis.get("score"),
            "sharpFlow": flow_entry.get("direction"),
            "opportunity": opp.get("score"),
        }
        comp = score_mod.composite(components, p)
        conflict = score_mod.detect_conflict(components, p)
        conf = score_mod.confidence(
            params=p,
            components_present=len(comp["componentsPresent"]),
            components_possible=len(components),
            cohort_level=mis.get("cohortLevel"),
            source_count=int(entry.get("sourceCount") or 0),
            hours_stale=hours_stale,
        )
        label = score_mod.classify(
            comp["score"],
            conf["score"],
            conflict,
            p,
            has_market_price=entry.get("marketValue") is not None,
        )

        row = {
            "playerKey": key,
            "displayName": entry.get("displayName"),
            "position": entry.get("position"),
            "assetClass": entry.get("assetClass"),
            "score": comp["score"],
            "label": label["label"],
            "labelReason": label.get("reason"),
            "confidence": conf["score"],
            "confidenceFactors": conf["factors"],
            "components": components,
            "componentsAbsent": comp["componentsAbsent"],
            "effectiveWeights": comp["effectiveWeights"],
            "mispricing": mis,
            "sharpFlow": flow_entry or {"reason": flow.get("status")},
            "opportunity": opp,
            "conflict": conflict,
            "fairValue": entry.get("fairValue"),
            "marketValue": entry.get("marketValue"),
            "anchorKey": entry.get("anchorKey"),
            "excludedSources": entry.get("excludedSources"),
            "unpricedReason": entry.get("unpricedReason"),
        }
        row["explanation"] = _explain(row)
        players.append(row)

    players.sort(key=lambda r: (r["score"] is None, -(r["score"] or 0.0)))

    return {
        "status": STATUS_OK,
        "modelVersion": MODEL_VERSION,
        "paramSetId": p.get("paramSetId"),
        "generatedAt": datetime.now(timezone.utc).isoformat(),
        "players": players,
        "coverage": fv_coverage(index),
        "sharpFlowStatus": flow.get("status"),
        "componentValidation": score_mod.COMPONENT_VALIDATION,
        "experimental": True,
        "caveats": [
            "Composite weights are declared priors, not fitted — only the "
            "mispricing component has an out-of-sample result.",
            "Validated against market movement, not fantasy production.",
        ],
    }


def top_movers(board: dict[str, Any], limit: int = 20) -> dict[str, list[dict[str, Any]]]:
    """Qualified top buys and sells.

    Merit-ranked with no positional quota: a weak player promoted to
    represent his position would be labelled a buy because of a display
    rule, which is exactly the thing the brief forbids. Positions with
    nothing qualifying are simply absent, and the caller renders that as
    "no qualifying buy" rather than reaching further down the list.
    """
    qualified = [
        r
        for r in board.get("players") or []
        if r.get("score") is not None
        and r.get("label")
        in (score_mod.STRONG_BUY, score_mod.BUY, score_mod.SELL, score_mod.STRONG_SELL)
    ]
    buys = [r for r in qualified if r["score"] > 0][:limit]
    sells = sorted((r for r in qualified if r["score"] < 0), key=lambda r: r["score"])[:limit]
    return {"buys": buys, "sells": sells}
