"""Compact `/api/data?view=compact` response builder (upgrade item #17).

Prunes fields that mobile / fast-first-paint views don't need.
Opt-in via query param; defaults unchanged.

Measured on the pinned 2026-07-30 contract (1,093 rows), serialised
the way FastAPI's ``JSONResponse`` does:

    full view        11.80 MB raw   1,057 KB gzipped
    compact view      7.19 MB raw     698 KB gzipped   (-34% / -34%)

The docstring used to claim "~4MB to ~500KB uncompressed".  Neither
number survives contact with today's contract, which has roughly
tripled in size since; the ratio is about right, the magnitudes are
not.  Quoting a stale absolute is how a payload budget silently stops
being a budget, so the figures above carry the date they were taken.

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
    both weights (``appliedWeight`` + ``effectiveWeight`` — see the
    comment on the constant), and ``method``.

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

_PRUNED_CONTRACT_FIELDS = frozenset(
    {
        "poolAudit",
        "methodology",
        "siteStats",
        "sites",  # leave sleeper.sites in place
    }
)

_PRUNED_PLAYER_FIELDS = frozenset(
    {
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
    }
)

# Per-source meta fields kept on the compact view.  Drives the trade
# per-source winner card (``valueContribution``), the rankings audit
# popover (``valueContribution`` + both weights + ``method``), and the
# PlayerPopup source-contribution graphs (``valueContribution``).
# Audit-only stamps (percentile, isAnchor, TEP correction flags, etc.)
# are dropped on mobile to keep the payload small.
#
# BOTH WEIGHTS, DELIBERATELY.  ``data_contract.py`` stamps them side by
# side and they mean different things: ``appliedWeight`` is what the
# count-aware blend multiplies the source's vote by, and
# ``effectiveWeight`` is the depth-scaled coverage DIAGNOSTIC that
# ``docs/open-modeling-decisions.md`` decision #1 is the measured call
# NOT to apply.  This set used to carry the diagnostic alone, so the
# compact view rendered the inert number on all 6,461 sourceRankMeta
# entries of the pinned contract, and on the 147 where the two differ
# it was a different number from the one that did the work — with the
# honest "Weight (applied)" row unable to render because the field
# never arrived.  Cost of carrying both, measured on that contract:
# +258,440 B raw but only **+5,105 B gzipped** on a 697 KB compact
# payload (+0.73%), and production runs GZipMiddleware.  Shipping only
# the wrong number to save 0.73% is not a trade worth making.
_SLIM_SOURCE_RANK_META_FIELDS = frozenset(
    {
        "valueContribution",
        "appliedWeight",
        "effectiveWeight",
        "method",
    }
)


def _slim_source_rank_meta(meta: Any) -> Any:
    """Return a per-source meta dict reduced to the mobile-consumed
    subset.  Non-dict inputs pass through untouched."""
    if not isinstance(meta, dict):
        return meta
    slim: dict[str, dict[str, Any]] = {}
    for src_key, src_meta in meta.items():
        if isinstance(src_meta, dict):
            slim[src_key] = {
                k: v for k, v in src_meta.items() if k in _SLIM_SOURCE_RANK_META_FIELDS
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
    full_payload: dict[str, Any],
    compact_payload: dict[str, Any],
) -> dict[str, int]:
    """Diagnostic: JSON byte sizes of full vs. compact."""
    import json

    full_bytes = len(json.dumps(full_payload).encode("utf-8"))
    compact_bytes = len(json.dumps(compact_payload).encode("utf-8"))
    return {
        "fullBytes": full_bytes,
        "compactBytes": compact_bytes,
        "savedBytes": max(0, full_bytes - compact_bytes),
        "savedPct": round((full_bytes - compact_bytes) / full_bytes * 100, 1)
        if full_bytes
        else 0.0,
    }
