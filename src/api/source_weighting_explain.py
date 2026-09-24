"""Explain the board: per-source weighting table and per-player value breakdown.

Pure functions over a built contract (``build_api_data_contract`` output) —
no second computation.  Every number here is read from stamps the canonical
pipeline already wrote (``sourceWeighting``, ``sourceRankMeta``,
``ktcMarket``); this module only arranges them so "why is this player valued
where he is" can be answered without reverse-engineering the blend.

Consumed by ``GET /api/sources/weighting``, ``GET /api/players/{id}/value-explain``
and ``scripts/source_weighting_report.py``.  Owner directive 2026-09-23.
"""

from __future__ import annotations

from typing import Any, Mapping

from src.sources.ktc_market import (
    KTC_CROWD_KEY,
    KTC_MARKET_KEY,
    KTC_TRADES_KEY,
    ktc_market_for_row,
    model_vs_market,
)


def source_table(
    contract: Mapping[str, Any], fetch_stamps: Mapping[str, Any] | None = None
) -> dict[str, Any]:
    """One row per (source, subset): clocks, cadence, factors, weights, state."""
    summary = contract.get("sourceWeighting") or {}
    stamps = fetch_stamps or {}
    rows: list[dict[str, Any]] = []
    for key, entry in (summary.get("sources") or {}).items():
        subsets = entry.get("subsets") or {}
        fetch = stamps.get(key) or {}
        base = {
            "source": key,
            "role": entry.get("role"),
            "measured": entry.get("measured", True),
            "lastFetchedAt": fetch.get("lastFetched") or fetch.get("mtime"),
            "health": entry.get("health"),
            "healthFactor": entry.get("healthFactor"),
            "healthErrors": entry.get("healthErrors") or [],
            "coverage": entry.get("coverage"),
            "coverageFactor": entry.get("coverageFactor"),
            "baseWeight": entry.get("baseWeight"),
            "votingRows": entry.get("votingRows"),
            "excludedRows": entry.get("excludedRows"),
            "meanAppliedWeight": entry.get("meanAppliedWeight"),
            "meanVoteShare": entry.get("meanVoteShare"),
        }
        if not subsets:
            rows.append({**base, "subset": None, "state": "UNMEASURED"})
            continue
        for name, sub in subsets.items():
            factor = None
            if sub.get("freshness") is not None and base["healthFactor"] is not None:
                factor = round(
                    float(sub["freshness"])
                    * float(base["healthFactor"])
                    * float(base["coverageFactor"] or 1.0),
                    4,
                )
            effective = (
                None
                if factor is None or base["baseWeight"] is None
                else round(factor * float(base["baseWeight"]), 4)
            )
            rows.append(
                {
                    **base,
                    "subset": name,
                    "publicationStyle": sub.get("publicationStyle"),
                    "freshnessClock": sub.get("freshnessClock"),
                    "sourceDataAsOf": sub.get("sourceDataAsOf"),
                    "lastAnyMeaningfulChangeAt": sub.get("lastAnyMeaningfulChangeAt"),
                    "lastBroadDatasetChangeAt": sub.get("lastBroadDatasetChangeAt"),
                    "expectedCadenceHours": sub.get("expectedCadenceHours"),
                    "cadenceSource": sub.get("cadenceSource"),
                    "observedCadenceHours": sub.get("observedCadenceHours"),
                    "ageHours": sub.get("ageHours"),
                    "ageOverExpected": sub.get("ageOverExpected"),
                    "freshness": sub.get("freshness"),
                    "dynamicFactor": factor,
                    "effectiveWeight": effective if base["role"] == "model_input" else None,
                    "state": sub.get("state"),
                }
            )
    return {
        "asOf": summary.get("asOf"),
        "applied": summary.get("applied"),
        "curve": summary.get("curve"),
        "formula": summary.get("formula"),
        "configVersion": summary.get("configVersion"),
        "rowStates": summary.get("rowStates") or {},
        "ktcMarket": contract.get("ktcMarket"),
        "sources": rows,
    }


def find_row(contract: Mapping[str, Any], player: str) -> dict[str, Any] | None:
    """Resolve a player by playerId, then by exact display / canonical name."""
    needle = str(player or "").strip()
    if not needle:
        return None
    rows = contract.get("playersArray") or []
    for row in rows:
        if str(row.get("playerId") or "") == needle:
            return row
    low = needle.casefold()
    for row in rows:
        for field in ("displayName", "canonicalName"):
            if str(row.get(field) or "").casefold() == low:
                return row
    return None


def player_explain(contract: Mapping[str, Any], row: Mapping[str, Any]) -> dict[str, Any]:
    """Why is this player valued where he is — every model source, then the
    KTC Market benchmark, then model vs market."""
    summary = (contract.get("sourceWeighting") or {}).get("sources") or {}
    meta = row.get("sourceRankMeta") or {}
    sites = row.get("canonicalSiteValues") or {}
    # ``canonicalSiteValues`` holds a SYNTHETIC descending encoding for
    # rank-signal sources (a bookkeeping artefact); the vendor's own number
    # is ``sourceNativeValues`` and its own rank ``sourceOriginalRanks``.
    native = row.get("sourceNativeValues") or {}
    original_ranks = row.get("sourceOriginalRanks") or {}
    is_pick = row.get("assetClass") == "pick"
    subset = "picks" if is_pick else "players"
    excluded = set(row.get("freshnessExcludedSources") or [])
    dropped = set(row.get("droppedSources") or [])

    voters = {
        k: float(m["appliedWeight"])
        for k, m in meta.items()
        if isinstance(m, dict)
        and m.get("contributedToBlend") is not False
        and k not in dropped
        and isinstance(m.get("appliedWeight"), (int, float))
        and m["appliedWeight"] > 0
    }
    total_weight = sum(voters.values())

    sources: list[dict[str, Any]] = []
    for key, m in meta.items():
        if not isinstance(m, dict):
            continue
        src = summary.get(key) or {}
        sub = (
            (src.get("subsets") or {}).get(subset)
            or (src.get("subsets") or {}).get("players")
            or {}
        )
        applied = voters.get(key)
        share = (applied / total_weight) if applied and total_weight > 0 else None
        value_direct = m.get("valueContributionPath") == "value_direct"
        raw_value = sites.get(key) if value_direct else native.get(key)
        contribution = m.get("valueContribution")
        sources.append(
            {
                "source": key,
                "rawValue": raw_value,
                "rawRank": original_ranks.get(key, m.get("rawRank")),
                "signal": "value" if value_direct else "rank",
                "normalizedValue": contribution,
                "effectiveRank": (row.get("sourceRanks") or {}).get(key),
                "dataAsOf": sub.get("sourceDataAsOf"),
                "freshnessClock": sub.get("freshnessClock"),
                "ageHours": m.get("freshnessAgeHours", sub.get("ageHours")),
                "expectedCadenceHours": sub.get("expectedCadenceHours"),
                "publicationStyle": sub.get("publicationStyle"),
                "freshness": m.get("freshness", sub.get("freshness")),
                "health": src.get("health"),
                "healthFactor": src.get("healthFactor"),
                "coverageFactor": src.get("coverageFactor"),
                "baseWeight": m.get("baseWeight", src.get("baseWeight")),
                # Family cap: the family and the factor its members were
                # scaled by so the family's total stays one provider's
                # authority (1.0 = uncapped); ``preFamilyWeight`` is the
                # weight before that scaling.
                "family": src.get("correlationGroup") or key,
                "preFamilyWeight": m.get("preFamilyWeight", m.get("appliedWeight")),
                "familyAdjustment": m.get("familyAdjustment"),
                # The weight the pipeline applied to this observation; an
                # observation that did not vote (outlier / superseded /
                # quarantined) shows its would-be weight and no vote share.
                "effectiveWeight": m.get("appliedWeight"),
                "voteShare": None if share is None else round(share, 4),
                "contribution": None
                if share is None or not isinstance(contribution, (int, float))
                else round(share * float(contribution), 1),
                "status": (
                    "excluded_stale_or_unhealthy"
                    if key in excluded
                    else "hampel_outlier"
                    if key in dropped
                    else "superseded_by_family"
                    if m.get("contributedToBlend") is False
                    else "voting"
                ),
                "supersededBy": m.get("supersededBy"),
            }
        )
    # Voters by share, then every non-voter (no share is not a zero share).
    sources.sort(key=lambda s: (s["voteShare"] is None, -s["voteShare"] if s["voteShare"] else 0))

    model_value = row.get("rankDerivedValue")
    market = ktc_market_for_row(row)
    return {
        "player": row.get("displayName"),
        "playerId": row.get("playerId"),
        "position": row.get("position"),
        "assetClass": row.get("assetClass"),
        "modelValue": model_value,
        "modelRank": row.get("canonicalConsensusRank"),
        "confidence": row.get("confidenceBucket"),
        "sourceWeightState": row.get("sourceWeightState"),
        "retainedAuthority": row.get("retainedAuthority"),
        "dominantSource": row.get("dominantSource"),
        "dominantSourceShare": row.get("dominantSourceShare"),
        "validSourceCount": len(voters),
        "observedSourceCount": len(meta),
        "modelSources": sources,
        # Off-cap rows (past OVERALL_RANK_LIMIT) are valued but carry no
        # per-source stamps, so there is nothing to itemise — say so.
        "sourceBreakdownAvailable": bool(meta),
        "ktcMarketBenchmark": {
            "definition": "KTC's published Crowd+Trades value (benchmark only — never a model input)",
            "sourceKey": KTC_MARKET_KEY,
            "ktcCrowdComponent": sites.get(KTC_CROWD_KEY),
            "ktcTradesComponent": sites.get(KTC_TRADES_KEY),
            "ktcMarketValue": market.get("value"),
            "ktcMarketNormalizedValue": market.get("normalizedValue"),
            "ktcMarketRank": market.get("rank"),
            "available": market.get("available"),
            "unavailableReason": market.get("reason"),
            "marketDataState": (
                _market_data_state(summary, subset) if market.get("available") else None
            ),
        },
        "modelVsKtcMarket": model_vs_market(model_value, market),
    }


def _market_data_state(summary: Mapping[str, Any], subset: str = "players") -> dict[str, Any]:
    """KTC Market's freshness, qualified by its two components — a fresh
    market built from a stale Trades board is not reported as simply fresh.
    ``None`` for a row with no KTC Market (never a fabricated 1.0)."""

    def fresh(key: str) -> Any:
        subs = (summary.get(key) or {}).get("subsets") or {}
        return (subs.get(subset) or {}).get("freshness")

    market, crowd, trades = fresh(KTC_MARKET_KEY), fresh(KTC_CROWD_KEY), fresh(KTC_TRADES_KEY)
    known = [v for v in (market, crowd, trades) if isinstance(v, (int, float))]
    return {
        "marketFreshness": market,
        "crowdFreshness": crowd,
        "tradesFreshness": trades,
        "confidence": None if not known else round(min(known), 4),
        "componentStale": bool(known) and min(known) < 0.95,
    }
