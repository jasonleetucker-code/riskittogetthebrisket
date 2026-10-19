"""Explain the board: per-source weighting table and per-player value breakdown.

Pure functions over a built contract (``build_api_data_contract`` output) —
no second computation.  Every number here is read from stamps the canonical
pipeline already wrote (``sourceWeighting``, ``sourceRankMeta``,
``ktcMarket``); this module only arranges them so "why is this player valued
where he is" can be answered without reverse-engineering the blend.

Consumed by ``GET /api/sources/weighting``, ``GET /api/players/{id}/value-explain``
and ``scripts/source_weighting_report.py``.  Owner directive 2026-09-23.

``value-explain/v2`` (#1555 Batch 2 Lane 6, 2026-10-01) adds, per source, the
three clocks kept apart -- last FETCH, the source's own publication/as-of date,
and the last CONFIRMED content change -- with explicit unknowns; the freshness
treatment actually applied; why a non-voting observation was excluded; and,
per row, the ESTIMATOR that produced the published value, an honest statement
of whether vote-share attribution is exact, and a leave-one-out that is
labelled non-additive.  All additive: every v1 field keeps its meaning.
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

EXPLAIN_VERSION = "value-explain/v2"


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
            # Unstated is UNKNOWN, not measured (the canonical producer
            # always stamps it; an entry without it proves nothing).
            "measured": entry.get("measured"),
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
            # Every factor must be published to state the product.  A
            # missing coverage factor is unknown, never full coverage --
            # and a published 0.0 is a real zero (``or 1.0`` turned a
            # zero-coverage source back into a full-weight one here).
            factors = (sub.get("freshness"), base["healthFactor"], base["coverageFactor"])
            factor = None
            if all(isinstance(f, (int, float)) and not isinstance(f, bool) for f in factors):
                factor = round(float(factors[0]) * float(factors[1]) * float(factors[2]), 4)
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


def _clocks(fetch: Mapping[str, Any], sub: Mapping[str, Any]) -> dict[str, Any]:
    """Three different clocks, never merged: when WE fetched, what date the
    SOURCE says its data is as of, and when its content last CONFIRMABLY
    changed.  A missing clock is ``None`` and named in ``unknown``."""
    clocks = {
        "lastFetchedAt": fetch.get("lastFetched") or fetch.get("mtime"),
        "publishedAsOf": sub.get("sourceDataAsOf"),
        "lastConfirmedChangeAt": sub.get("lastAnyMeaningfulChangeAt"),
        "lastBroadChangeAt": sub.get("lastBroadDatasetChangeAt"),
        "judgedOn": sub.get("freshnessClock"),
    }
    clocks["unknown"] = sorted(k for k, v in clocks.items() if v is None)
    return clocks


def _freshness_treatment(freshness: Any, excluded: bool, state: Any) -> dict[str, Any]:
    if excluded:
        treatment = "excluded"
    elif not isinstance(freshness, (int, float)):
        treatment = "unknown"
    elif freshness >= 0.999:
        treatment = "full_weight"
    elif freshness > 0:
        treatment = "down_weighted"
    else:
        treatment = "excluded"
    return {"factor": freshness, "state": state, "treatment": treatment}


def _exclusion_reason(key: str, m: Mapping[str, Any], row: Mapping[str, Any]) -> str | None:
    if key in set(row.get("freshnessExcludedSources") or []) or m.get("excludedReason"):
        return str(m.get("excludedReason") or "freshness_or_health_zero_weight")
    if key in set(row.get("droppedSources") or []):
        detail = (row.get("jointFilterReasons") or {}).get(key)
        return f"outlier:{detail}" if detail else "outlier:hampel"
    if m.get("contributedToBlend") is False:
        return "superseded_by_family"
    return None


def _rung(n: int) -> str:
    if n <= 0:
        return "no_voters"
    if n == 1:
        return "passthrough"
    if n == 2:
        return "weighted_mean"
    if n <= 4:
        return "weighted_mean_median_untrimmed"
    return "weighted_mean_median_trimmed"


def _estimator(row: Mapping[str, Any], n_voters: int) -> dict[str, Any]:
    """Which estimator produced the published value -- read from stamps."""
    provenance = row.get("pickValueProvenance") or {}
    if row.get("assetClass") == "pick":
        path = str(provenance.get("class") or "pick_unknown_provenance")
    elif row.get("assetClass") == "idp":
        # The pipeline's hierarchical rule (``use_hierarchical_blend``): IDP
        # and picks only.  ``anchorValue`` is stamped on offense rows too, as a
        # diagnostic, so it cannot decide the path.
        path = "anchor_plus_alpha_shrinkage"
    elif not (row.get("sourceRankMeta") or {}):
        path = "off_cap_value_only" if row.get("offCapPlayerValue") else "no_breakdown"
    else:
        path = "flat_count_aware_blend"
    overrides = []
    if row.get("twoWayPlayerBoost"):
        overrides.append("two_way_player_boost")
    if path == "rookie_pool_tether":
        overrides.append("rookie_pool_tether")
    out = {
        "path": path,
        "rung": _rung(n_voters),
        "voters": n_voters,
        "singleSourceRetentionApplied": bool(row.get("singleSourceValuePenaltyApplied")),
        "limitedEvidence": row.get("limitedEvidence"),
        "postBlendOverrides": overrides,
        "anchorValue": row.get("anchorValue"),
        "alphaShrinkage": row.get("alphaShrinkage"),
    }
    # Flag ``sparse_evidence_estimator`` (default OFF) stamps this block; with
    # the flag off the key is absent, so the explain output is unchanged.
    if "sparseEvidence" in row:
        out["sparseEvidence"] = row.get("sparseEvidence")
    return out


def _attribution(estimator: Mapping[str, Any]) -> dict[str, Any]:
    exact = (
        estimator["path"] == "flat_count_aware_blend"
        and estimator["rung"] in ("passthrough", "weighted_mean")
        and not estimator["singleSourceRetentionApplied"]
        and not estimator.get("sparseEvidence")
        and not estimator["postBlendOverrides"]
    )
    return {
        "kind": "weighted_vote_share",
        "exact": exact,
        "note": (
            "Each source's contribution is its vote share times its normalized "
            "value. That reproduces the published value only when the estimator "
            "is a plain weighted mean (or one source) with no haircut or override; "
            "median-type rungs, anchor shrinkage and overrides are not weighted "
            "means, so the contributions need not add up to the model value."
        ),
    }


def _leave_one_out(row: Mapping[str, Any]) -> dict[str, Any]:
    """Published value with each voter removed, re-running ONLY the pipeline's
    own aggregator over the stamped survivors (offense rows whose stamps
    reproduce the published blend).  The outlier filter and freshness are not
    re-run, and the deltas are not additive."""
    from src.api import data_contract as dc  # noqa: PLC0415 — loaded by the server
    from src.api.value_replay import blend_check  # noqa: PLC0415

    base = {"nonAdditive": True, "basis": "aggregator_rerun_over_stamped_survivors"}
    check = blend_check(row)
    if check.get("status") != "reproduced":
        return {**base, "available": False, "reason": check.get("status") or "unavailable"}
    meta = row.get("sourceRankMeta") or {}
    voters = {
        k: (float(m["valueContribution"]), float(m["appliedWeight"]))
        for k, m in meta.items()
        if not m.get("hampelDropped")
        and not m.get("excludedReason")
        and m.get("contributedToBlend") is not False
        and isinstance(m.get("appliedWeight"), (int, float))
        and m["appliedWeight"] > 0
        and isinstance(m.get("valueContribution"), (int, float))
    }
    if len(voters) < 2:
        return {**base, "available": False, "reason": "fewer_than_two_voters"}
    published = check["recomputed"]
    out = []
    for key in sorted(voters):
        rest = [voters[k] for k in voters if k != key]
        value, _ = dc.weighted_count_aware_mean_median_blend(
            [v for v, _w in rest], [w for _v, w in rest]
        )
        families = {dc.correlation_group_for(k) for k in voters if k != key}
        if len(families) <= 1 and not row.get("limitedEvidence"):
            value *= dc._SINGLE_SOURCE_VALUE_RETENTION
        out.append(
            {"source": key, "valueWithout": round(value, 1), "delta": round(value - published, 1)}
        )
    return {**base, "available": True, "publishedBlend": published, "withoutEach": out}


def player_explain(
    contract: Mapping[str, Any],
    row: Mapping[str, Any],
    fetch_stamps: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Why is this player valued where he is — every model source, then the
    KTC Market benchmark, then model vs market."""
    stamps = fetch_stamps or {}
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
                "contributionIsApproximate": True,
                "clocks": _clocks(stamps.get(key) or {}, sub),
                "freshnessTreatment": _freshness_treatment(
                    m.get("freshness", sub.get("freshness")), key in excluded, sub.get("state")
                ),
                "exclusionReason": None if key in voters else _exclusion_reason(key, m, row),
            }
        )
    # Voters by share, then every non-voter (no share is not a zero share).
    sources.sort(key=lambda s: (s["voteShare"] is None, -s["voteShare"] if s["voteShare"] else 0))

    model_value = row.get("rankDerivedValue")
    market = ktc_market_for_row(row)
    estimator = _estimator(row, len(voters))
    return {
        "explainVersion": EXPLAIN_VERSION,
        "estimator": estimator,
        "attribution": _attribution(estimator),
        "leaveOneOut": _leave_one_out(row),
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
