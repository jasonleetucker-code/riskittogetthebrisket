"""Compact ``/api/data?view=compact`` response builder — the mobile /
slow-network view.

WHAT IT IS FOR, AND WHAT IT MAY NOT DO
──────────────────────────────────────
This view exists to send FEWER BYTES to a phone.  It may not send a
phone a DIFFERENT BOARD.  Those two goals collided here for months and
the byte goal lost twice over — the view was simultaneously **larger**
than the desktop view and **lossy** in a way that changed rendered
numbers.  Both are fixed; the two rules below are what keep them fixed.

**Rule 1 — the legacy ``players`` dict is not carried.**  It and
``playersArray`` are parallel encodings of the same rows, and
``buildRows`` (``frontend/lib/dynasty-data.js``) prefers the array
whenever it is present, so the dict was pure duplicate weight that
nothing on this path read.  ``?view=array`` had already dropped it
(``server.py``); compact had not, which is the whole reason the
"optimized" mobile view was the LARGER of the two:

    measured 2026-08-18, 1,109-row contract, gzip level 6
        full      13.09 MB raw   1,092.8 KB gz
        array      7.25 MB raw     631.8 KB gz
        compact    8.28 MB raw     735.0 KB gz   ← +16.3% vs array

**Rule 2 — a field the frontend materializer READS may not be pruned.**
This is the rule that was broken, and it was invisible because nothing
tested it.  ``_materializePlayerArrayRow`` reads 14 of the 17 fields
this module used to prune, so the compact board rendered differently
from the array board for the same player on the same day:

    anomalyFlags        → /edge's "Flagged" stat tile read 0
    blendedSourceRank   → a SORT KEY; the Consensus sort collapsed
    confidenceLabel     → a different confidence string
    anchorValue, subgroupBlendValue, subgroupDelta, alphaShrinkage
                        → PlayerPopup's value-derivation chain collapsed
    sourceOriginalRanks → flipped "not listed by this source" against
                          "listed, no normalized contribution"
    droppedSources      → Hampel-drop markers vanished from the charts
    effectiveSourceRanks, madPenaltyApplied, marketCorridorClamp,
    softFallbackCount   → materialized to empty/false

    and ``methodology`` at the contract level → /rankings' methodology
    section was absent on mobile only.

``isMobileProfile()`` also fires on ``navigator.deviceMemory <= 4``, so
this was never confined to phones — a desktop browser reporting 4 GB
took the pruned payload at 1920px.

Pinned by ``tests/api/test_compact_view_consumer_parity.py``, which
parses the materializer's own field reads out of the frontend and fails
if any of them appears in a prune list.  Adding a field here without
checking the frontend is meant to turn CI red, not to ship a second
board.

WHAT IS STILL PRUNED
────────────────────
Only fields no frontend consumer reads at all — verified by that same
test, not by assertion:

    contract level : poolAudit, siteStats, sites
    per player     : pickDetails, hillValueSpread, marketDispersionCV
    sourceRankMeta : reduced to the consumed subset (see the constant)

``methodology`` was moved OUT of the contract-level prune list: it is
rendered at ``app/rankings/page.jsx`` and its absence was a mobile-only
missing section.

Shape tests in ``tests/api/test_compact_view`` pin the contract, so
adding a field to a prune list either updates a test or is caught.
"""

from __future__ import annotations

from typing import Any

# Contract-level fields no frontend consumer reads.
#
# ``methodology`` is deliberately ABSENT from this set: it is rendered by
# ``app/rankings/page.jsx`` (``<MethodologySection methodology={rawData?.methodology} />``)
# and ``app/rankings/board-sections.jsx``, so pruning it removed a whole
# section on mobile and nowhere else.
_PRUNED_CONTRACT_FIELDS = frozenset(
    {
        "poolAudit",
        "siteStats",
        "sites",  # leave sleeper.sites in place
    }
)

# Per-player fields no frontend consumer reads.
#
# THIS LIST IS SMALL ON PURPOSE, and it used to hold fourteen more.  Every
# one of those fourteen is read by ``_materializePlayerArrayRow``, so
# pruning them did not save a mobile user bytes it did not need — it
# handed them a board that disagreed with the desktop board.  See the
# module docstring for the measured per-field consequences.
#
# The three survivors are the ones the frontend genuinely never touches:
#   pickDetails        — the frontend's own ``pickDetails`` is built by
#                        ``lib/league-analysis.js`` from ``sleeper.teams``;
#                        the per-player stamp has no reader.
#   hillValueSpread    — no reader anywhere in ``frontend/``.
#   marketDispersionCV — read only in ``lib/draft-logic.js``, off the
#                        ``/api/draft-capital`` rookie rows, never off a
#                        contract player row.
#
# Before adding a fourth, run
# ``tests/api/test_compact_view_consumer_parity.py`` — it reads the
# materializer and will tell you.
_PRUNED_PLAYER_FIELDS = frozenset(
    {
        "pickDetails",
        "hillValueSpread",
        "marketDispersionCV",
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
            # Rule 1 (see module docstring): the legacy dict is a parallel
            # encoding of ``playersArray`` and ``buildRows`` prefers the
            # array whenever it is present.  Carrying both is what made the
            # "compact" view larger than the desktop ``array`` view.
            #
            # Dropped only when the array is actually there.  A payload
            # carrying the dict ALONE is a legitimate shape (the runtime
            # view strips the array), and silently emptying it would turn a
            # size optimization into a data loss.
            if isinstance(payload.get("playersArray"), list):
                continue
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
