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
from src.consensus_edge import scoring_fit, sharp_flow as sf
from src.consensus_edge.fair_value import (
    MARKET_ANCHOR_BY_ASSET_CLASS,
    coverage as fv_coverage,
    fair_value_index,
)
from src.consensus_edge.mispricing import score_index

STATUS_OK = "ok"
STATUS_NO_CONTRACT = "no_contract"

# Labels that make a row eligible for a ranked list. Defined once, here,
# and stamped onto every row as ``qualified`` so no consumer re-derives
# it.
DIRECTIONAL_LABELS = frozenset(
    {score_mod.STRONG_BUY, score_mod.BUY, score_mod.SELL, score_mod.STRONG_SELL}
)


def resolve_hours_stale(contract: dict[str, Any] | None) -> float | None:
    """Age of the data the mispricing signal actually depends on.

    The contract already carries a full freshness block —
    ``dataFreshness.sourceTimestamps`` with per-source ``ageHours`` — and
    Consensus Edge ignored all of it, so ``score.confidence`` took its
    "unknown staleness" branch and pinned freshness at 0.5 for every
    player forever. Stale data was therefore not visibly degraded
    anywhere, which is the opposite of what this feature promises.

    **The MARKET ANCHORS are what matter**, not the mean source age. The
    mispricing score is a comparison against the anchor's published
    price; if that price is a day old the signal is a day old, however
    fresh eleven expert boards happen to be. So this takes the OLDEST
    anchor — the weakest link — and falls back to the board-wide maximum
    only when no anchor timestamp is available.

    Returns None when the contract carries no usable freshness data at
    all, which correctly routes back to the "unknown" branch rather than
    inventing a zero.
    """
    if not isinstance(contract, dict):
        return None
    freshness = contract.get("dataFreshness")
    if not isinstance(freshness, dict):
        return None
    timestamps = freshness.get("sourceTimestamps")
    if not isinstance(timestamps, dict) or not timestamps:
        return None

    def _age(entry: Any) -> float | None:
        if not isinstance(entry, dict):
            return None
        value = entry.get("ageHours")
        try:
            age = float(value)
        except (TypeError, ValueError):
            return None
        return age if age >= 0 else None

    anchor_ages = [
        age
        for key in set(MARKET_ANCHOR_BY_ASSET_CLASS.values())
        if (age := _age(timestamps.get(key))) is not None
    ]
    if anchor_ages:
        return max(anchor_ages)

    all_ages = [age for entry in timestamps.values() if (age := _age(entry)) is not None]
    return max(all_ages) if all_ages else None


def component_availability(players: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    """Which components actually produced a value, and on how many rows.

    A component that is dark because its data source is empty looks
    exactly like a component that is dark because nobody wired it up.
    Both were true here at different times, and neither was visible.
    This makes the distinction a reported fact.
    """
    names = ("mispricing", "sharpFlow", "opportunity")
    scored = [r for r in players if r.get("score") is not None]
    out: dict[str, dict[str, Any]] = {}
    for name in names:
        present = sum(
            1 for r in players if isinstance((r.get("components") or {}).get(name), (int, float))
        )
        out[name] = {
            "available": present > 0,
            "rowsWithValue": present,
            "rowsScored": len(scored),
        }
    return out


def confidence_ceiling(available_components: int, total_components: int = 3) -> float:
    """Highest confidence attainable given how many components are live.

    Confidence is a geometric mean over coverage, reliability and
    freshness. With only ``available_components`` of ``total_components``
    ever present, coverage is capped, and so is the whole score — which
    silently suppresses every Strong label. Publishing the ceiling means
    "why are there no Strong Buys" is answerable without reading source.

    Assumes the best case for the other two factors (both 1.0), so this
    is a genuine upper bound rather than an estimate.
    """
    if total_components <= 0:
        return 0.0
    coverage = max(0, available_components) / total_components
    return 100.0 * (coverage ** (1.0 / 3.0))


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
    # The contract IS the payload. ``build_api_data_contract`` copies the
    # raw top level through and only adds keys, so it is idempotent on
    # its own output and ``fair_value_index`` reads the same ``players``
    # dict either way — verified byte-identical over 973 rows. This used
    # to read a ``_rawPayload`` key that nothing in the repo ever wrote,
    # which documented an indirection that did not exist.
    fit_board = scoring_fit.measure(season=contract.get("currentDraftYear"))
    index = fair_value_index(contract, scoring_fit_board=fit_board)
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
            # Whether this row is eligible for a ranked list. Stamped by
            # the backend so no client re-derives it: the frontend used
            # to keep its own copy of this label set, matched by English
            # string against Python constants, which is the same drift
            # the client-side rank fallback caused.
            "qualified": label["label"] in DIRECTIONAL_LABELS,
        }
        row["explanation"] = _explain(row)
        players.append(row)

    players.sort(key=lambda r: (r["score"] is None, -(r["score"] or 0.0)))

    availability = component_availability(players)
    live_components = sum(1 for meta in availability.values() if meta["available"])
    ceiling = confidence_ceiling(live_components, len(availability))

    return {
        "status": STATUS_OK,
        "modelVersion": MODEL_VERSION,
        "paramSetId": p.get("paramSetId"),
        "generatedAt": datetime.now(timezone.utc).isoformat(),
        "players": players,
        "coverage": fv_coverage(index),
        "sharpFlowStatus": flow.get("status"),
        "componentValidation": score_mod.COMPONENT_VALIDATION,
        # League scoring fit is applied INSIDE fair value, never as a
        # separate component. Reported here so a reader can see which
        # axes were measured and at what level, without being able to
        # mistake it for a fourth additive term.
        "scoringFit": fit_board.to_meta(),
        "componentAvailability": availability,
        # Published because it silently governs which labels can appear
        # at all: with one live component the ceiling sits below the
        # Strong threshold, so Strong Buy and Strong Sell are
        # unreachable. That is a legitimate state, but it must never
        # again be mistaken for the model simply not finding any.
        "confidenceCeiling": ceiling,
        "strongLabelsReachable": ceiling
        >= float((p.get("classification") or {}).get("minConfidenceForStrong") or 70.0),
        # What this board was actually handed. An input that never
        # arrived is the defect class this whole feature suffered from,
        # so the inputs are part of the payload, not an implementation
        # detail.
        "inputs": {
            "hoursStale": hours_stale,
            "sharpMovementAssets": len(movements_by_asset or {})
            if movements_by_asset is not None
            else None,
            "rankHistoryPlayers": len(rank_history_by_player or {})
            if rank_history_by_player is not None
            else None,
        },
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
        r for r in board.get("players") or [] if r.get("score") is not None and r.get("qualified")
    ]
    buys = [r for r in qualified if r["score"] > 0][:limit]
    sells = sorted((r for r in qualified if r["score"] < 0), key=lambda r: r["score"])[:limit]
    return {"buys": buys, "sells": sells}
