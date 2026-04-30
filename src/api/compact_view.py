"""Compact `/api/data?view=compact` response builder (upgrade item #17).

Prunes fields that mobile / fast-first-paint views don't need
so the payload drops from ~4MB to ~500KB uncompressed.  Opt-in
via query param; defaults unchanged.

Fields we prune (listed in ``_PRUNED_CONTRACT_FIELDS``):
    poolAudit, methodology, siteStats (verbose per-scrape stats)

Fields we prune per-player (listed in ``_PRUNED_PLAYER_FIELDS``):
    droppedSources, effectiveSourceRanks, sourceOriginalRanks,
    anomalyFlags, confidenceLabel, pickDetails

Fields slimmed per-player (listed in ``_SLIM_SOURCE_RANK_META_FIELDS``):
    sourceRankMeta entries are kept but reduced to the subset of
    fields the mobile UI actually consumes.  Mobile drops the per-
    source ``percentile`` / ``valueContributionPath`` / ``isAnchor``
    / ``ladderDepth`` / TEP audit stamps, but keeps the
    ``valueContribution`` (drives the trade per-source winner row,
    PlayerPopup, source-contribution graphs, rankings audit cell),
    ``effectiveWeight``, and ``method`` fields.

Fields KEPT (mobile UI needs them):
    name / canonicalName / displayName / position / team / age /
    rookie / assetClass / values / sourceCount / confidence /
    marketLabel / canonicalConsensusRank / rankDerivedValue /
    canonicalTierId / rankChange / sleeper (for team-switcher) /
    canonicalSiteValues (KTC TE+ row in the trade per-source winner
    reads the raw native value from this map) / sourceRankMeta
    (slimmed — see above).

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

# Per-source meta fields kept on the compact view.  Drives the trade
# per-source winner card (``valueContribution``), the rankings audit
# popover (``valueContribution`` + ``effectiveWeight`` + ``method``),
# and the PlayerPopup source-contribution graphs (``valueContribution``).
# Audit-only stamps (percentile, isAnchor, TEP correction flags, etc.)
# are dropped on mobile to keep the payload small.
_SLIM_SOURCE_RANK_META_FIELDS = frozenset({
    "valueContribution",
    "effectiveWeight",
    "method",
})


def _slim_source_rank_meta(meta: Any) -> Any:
    """Return a per-source meta dict reduced to the mobile-consumed
    subset.  Non-dict inputs pass through untouched."""
    if not isinstance(meta, dict):
        return meta
    slim: dict[str, dict[str, Any]] = {}
    for src_key, src_meta in meta.items():
        if isinstance(src_meta, dict):
            slim[src_key] = {
                k: v for k, v in src_meta.items()
                if k in _SLIM_SOURCE_RANK_META_FIELDS
            }
        else:
            # Defensive: preserve unexpected shapes verbatim so tests
            # that mutate fixtures (and downstream consumers that
            # tolerate odd shapes) don't break silently.
            slim[src_key] = src_meta
    return slim


def compact_player(player: dict[str, Any]) -> dict[str, Any]:
    """Return a shallow-copied player row with pruned fields and a
    slimmed ``sourceRankMeta`` map."""
    if not isinstance(player, dict):
        return player
    out: dict[str, Any] = {}
    for k, v in player.items():
        if k in _PRUNED_PLAYER_FIELDS:
            continue
        if k == "sourceRankMeta":
            out[k] = _slim_source_rank_meta(v)
            continue
        out[k] = v
    return out


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
