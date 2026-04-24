"""Compact `/api/data?view=compact` response builder (upgrade item #17).

Prunes fields that mobile / fast-first-paint views don't need
so the payload drops from ~4MB to ~500KB uncompressed.  Opt-in
via query param; defaults unchanged.

Fields we prune (listed in ``_PRUNED_CONTRACT_FIELDS``):
    poolAudit, methodology, siteStats (verbose per-scrape stats)

Fields we prune per-player (listed in ``_PRUNED_PLAYER_FIELDS``):
    sourceRankMeta, canonicalSiteValues, droppedSources,
    effectiveSourceRanks, sourceOriginalRanks, anomalyFlags,
    confidenceLabel, pickDetails

Fields KEPT (mobile UI needs them):
    name / canonicalName / displayName / position / team / age /
    rookie / assetClass / values / sourceCount / confidence /
    marketLabel / canonicalConsensusRank / rankDerivedValue /
    canonicalTierId / rankChange / sleeper (for team-switcher)

Shape tests in ``tests/api/test_compact_view`` pin the
contract so adding a field to this list either updates tests
or is caught.
"""
from __future__ import annotations

from typing import Any

_PRUNED_CONTRACT_FIELDS = frozenset({
    "poolAudit",
    "methodology",
    "siteStats",
    "sites",  # leave sleeper.sites in place
})

_PRUNED_PLAYER_FIELDS = frozenset({
    "sourceRankMeta",
    "canonicalSiteValues",
    "droppedSources",
    "effectiveSourceRanks",
    "sourceOriginalRanks",
    "anomalyFlags",
    "confidenceLabel",
    "pickDetails",
    "marketCorridorClamp",
    "twoWayPlayerBoost",
    # Post-pipeline audit fields — kept in the full view, pruned here.
    "subgroupBlendValue",
    "subgroupDelta",
    "alphaShrinkage",
    "softFallbackCount",
    "hillValueSpread",
    "marketDispersionCV",
    "blendedSourceRank",
    "madPenaltyApplied",
    "anchorValue",
})


def compact_player(player: dict[str, Any]) -> dict[str, Any]:
    """Return a shallow-copied player row with pruned fields."""
    if not isinstance(player, dict):
        return player
    return {k: v for k, v in player.items() if k not in _PRUNED_PLAYER_FIELDS}


def compact_contract(payload: dict[str, Any]) -> dict[str, Any]:
    """Return a new contract payload with pruned fields at both
    levels.  Non-destructive — input is not mutated."""
    if not isinstance(payload, dict):
        return payload
    out: dict[str, Any] = {}
    for k, v in payload.items():
        if k in _PRUNED_CONTRACT_FIELDS:
            continue
        if k == "playersArray" and isinstance(v, list):
            out[k] = [compact_player(p) for p in v]
            continue
        if k == "players" and isinstance(v, dict):
            out[k] = {name: compact_player(p) for name, p in v.items()}
            continue
        out[k] = v
    # Stamp the view in meta so clients can verify they got what they asked for.
    meta = dict(out.get("meta") or {})
    meta["view"] = "compact"
    out["meta"] = meta
    return out


def byte_savings(
    full_payload: dict[str, Any], compact_payload: dict[str, Any],
) -> dict[str, int]:
    """Diagnostic: JSON byte sizes of full vs. compact."""
    import json
    full_bytes = len(json.dumps(full_payload).encode("utf-8"))
    compact_bytes = len(json.dumps(compact_payload).encode("utf-8"))
    return {
        "fullBytes": full_bytes,
        "compactBytes": compact_bytes,
        "savedBytes": max(0, full_bytes - compact_bytes),
        "savedPct": round((full_bytes - compact_bytes) / full_bytes * 100, 1) if full_bytes else 0.0,
    }
