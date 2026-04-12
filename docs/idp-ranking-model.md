# IDP Ranking Normalization Model

This document is the standalone methodology reference for how Risk It To Get
The Brisket ranks IDP (defensive) players inside the shared 1–9999 value
economy. It covers the two source topologies the pipeline must handle:

1. **Full overall IDP sources** — a single board that ranks DL, LB, and DB
   players against each other (e.g. IDP Trade Calculator's top 150).
2. **Position-only IDP sources** — segmented boards that rank players
   within a single family (e.g. a top-20 DL board, a top-20 LB board, a
   top-20 DB board).

Both topologies have to coexist inside the same unified ranking without
inflating shallow positional lists and without introducing a parallel
IDP-only value economy.

## Authoritative code paths

| Concern                     | Backend (authority)                                   | Frontend (fallback mirror)               |
|----------------------------|-------------------------------------------------------|-------------------------------------------|
| Unified ranking pipeline   | `src/api/data_contract.py::_compute_unified_rankings` | `frontend/lib/dynasty-data.js::computeUnifiedRanks` |
| IDP backbone + translation | `src/canonical/idp_backbone.py`                       | `buildIdpBackbone` / `translatePositionRank` in `dynasty-data.js` |
| Shared Hill curve          | `src/canonical/player_valuation.py::rank_to_value`    | `rankToValue` in `dynasty-data.js`        |
| Source registry            | `_RANKING_SOURCES` in `data_contract.py`              | `RANKING_SOURCES` in `dynasty-data.js`    |

Backend is always the source of truth. The frontend helpers exist so the
UI degrades gracefully when the backend contract is stale or unreachable;
every change to the ranking math must land in both files and in both test
suites simultaneously.

## Source scope metadata (PART 1)

Every ranking source declares its topology in the registry:

```python
{
    "key":            "idpTradeCalc",
    "display_name":   "IDP Trade Calculator",
    "scope":          SOURCE_SCOPE_OVERALL_IDP,      # full-board IDP
    "extra_scopes":   [SOURCE_SCOPE_OVERALL_OFFENSE],# also prices offense
    "position_group": None,                          # N/A for overall boards
    "depth":          None,                          # treated as full
    "weight":         1.0,
    "is_backbone":    True,                          # becomes the anchor ladder
}
```

| Field            | Purpose                                                                 |
|------------------|-------------------------------------------------------------------------|
| `scope`          | One of `overall_offense`, `overall_idp`, `position_idp`.                |
| `extra_scopes`   | Optional additional scope passes (for dual-economy sources like IDPTC). |
| `position_group` | Required when `scope == position_idp`; must be `DL`, `LB`, or `DB`.     |
| `depth`          | Number of players the source publishes. `None` means full coverage.     |
| `weight`         | Declared reliability weight, scaled by coverage during blending.        |
| `is_backbone`    | Marks the single source whose overall-IDP ordering anchors the ladder.  |

A `position_idp` source with `position_group=None` is a declaration error:
the scope predicate rejects every row and the source silently contributes
nothing. Tests pin this behaviour so regressions surface loudly.

## The IDP backbone (PART 2)

At build time the pipeline walks every row, picks the rows that carry a
positive value in the designated backbone source, and sorts them
descending (tie-break: lowercased canonical name). It then records three
per-position ladders of overall-IDP ranks:

```
DL ladder:  [1, 3, 6, 9, ...]   # overall ranks of the DL players
LB ladder:  [2, 5, 8, ...]      # overall ranks of the LB players
DB ladder:  [4, 7, 10, ...]     # overall ranks of the DB players
```

Each ladder captures exactly how the backbone source spaced that position
within its full board. No spacing is hard-coded — it always comes from the
live snapshot. If the backbone source is missing or empty, all ladders are
empty and any `position_idp` source will fall back to pass-through
ranking (with an `idpBackboneFallback=true` transparency flag).

## Translating a positional rank into a synthetic overall rank (PART 3)

Given a within-position rank and the relevant ladder,
`translate_position_rank` returns both the synthetic overall rank and the
method used to produce it:

| Raw rank input                  | Output method    | Behaviour                                                                 |
|---------------------------------|------------------|---------------------------------------------------------------------------|
| 1 ≤ rank ≤ len(ladder), integer | `exact`          | Returns the ladder entry at that index directly.                          |
| 1 ≤ rank ≤ len(ladder), fraction| `interpolated`   | Linearly interpolates between the surrounding ladder entries.             |
| rank > len(ladder)              | `extrapolated`   | Projects past the tail using the average step of the last five ladder gaps. A guardrail keeps the synthetic rank strictly greater than the last anchor, even for degenerate flat ladders. |
| Empty ladder                    | `fallback`       | Returns the raw positional rank unchanged and flags the row for backbone fallback. |
| rank ≤ 0                        | `exact`          | Clamps to the first anchor.                                               |
| Single-anchor ladder, rank > 1  | `extrapolated`   | Uses a defensive step equal to the single anchor's rank.                  |

DL ranks only flow through the DL ladder; LB and DB are symmetric. No
positional ladder is shared across families.

## Shared 1–9999 economy (PART 4)

Once a source has produced an **effective rank** (direct for overall
sources, translated for positional sources), the pipeline feeds that rank
through the canonical Hill curve:

```
value = max(1, min(9999, round(1 + 9998 / (1 + ((rank - 1) / 45) ^ 1.10))))
```

This is the same curve offense uses. There is no IDP-only value scale and
no parallel display economy; a DL3 that maps to synthetic overall IDP
rank 7 gets exactly the Hill-curve value for rank 7 — no different from
the DL that lands at overall rank 7 on a full-board source.

## Coverage-aware blending (PART 5)

Each source contributes a Hill-curve value per row. The row's unified
value is a weighted average of those contributions. The weight of a
source for a given blend is:

```
effective_weight = max(0, declared_weight) * min(1, depth / MIN_FULL_COVERAGE_DEPTH)
```

with `MIN_FULL_COVERAGE_DEPTH = 60`. Consequences:

- Full-board sources (`depth=None`) keep their declared weight unchanged.
- A top-20 positional list contributes `20 / 60 ≈ 0.333` of its declared
  weight, so it can never overpower a deeper full-board source.
- A zero- or negative-depth declaration yields zero weight and is a
  silent no-op rather than a crash.

Cross-universe ranking for dual-scope sources (like IDPTC, which prices
both offense and IDP on the same 0–9999 scale) happens inside Phase 1:
the pipeline ranks offense and IDP rows in a single combined pool, so a
top DL that sits below 40 offense starters in raw IDPTC value gets
combined rank 41, not rank 1. Ties in raw source values resolve
deterministically by lowercased canonical name — the Phase 1 sort,
Phase 4 final sort, and backbone builder all share this tiebreaker so
the output is byte-stable regardless of input iteration order.

## Transparency fields (PART 6)

Every ranked row carries:

| Field                    | Meaning                                                                                   |
|--------------------------|-------------------------------------------------------------------------------------------|
| `sourceRanks`            | Map of `source_key -> effective rank` fed into the Hill curve for this row.               |
| `sourceRankMeta`         | Same keys as `sourceRanks`, richer payload (see below).                                   |
| `canonicalConsensusRank` | Final unified board position for the row.                                                 |
| `rankDerivedValue`       | Hill-curve value at `canonicalConsensusRank`.                                             |
| `idpBackboneFallback`    | `True` iff any `position_idp` source had to fall back because the backbone was missing.   |

Each `sourceRankMeta[source_key]` entry contains:

- `scope` — which scope this row was ranked under for this source
- `positionGroup` — `DL`/`LB`/`DB` for positional sources, `null` otherwise
- `rawRank` — the rank assigned before translation
- `effectiveRank` — the rank after translation (what the Hill curve saw)
- `method` — `direct` / `exact` / `interpolated` / `extrapolated` / `fallback`
- `ladderDepth` — length of the ladder consulted (positional sources only)
- `backboneDepth` — depth of the backbone snapshot that built the ladder
- `depth` — declared coverage depth of the source
- `weight`, `effectiveWeight` — declared and coverage-scaled weights
- `valueContribution` — Hill-curve value this source contributed before blending

## Backward compatibility (PART 7)

These legacy fields remain populated and keep their historical semantics:

- `ktcRank` — overall-offense rank from the KTC source, if present
- `idpRank` — overall-IDP rank from the backbone source, if present
- `rankDerivedValue` — Hill-curve value at `canonicalConsensusRank`
- `canonicalConsensusRank` — final unified board position

Adding a new segmented IDP source is a purely declarative change — add
an entry to `_RANKING_SOURCES` (and the frontend `RANKING_SOURCES`
mirror) with the appropriate scope and position group, and the existing
pipeline handles ingestion, translation, blending, and UI rendering
without any call-site edits.

## Testing (PART 10)

The authoritative integration tests live in:

- `tests/api/test_scope_aware_rankings.py` — backend
- `frontend/__tests__/scope-aware-rankings.test.js` — frontend parity
- `tests/canonical/test_idp_backbone.py` — pure-Python unit tests for
  the backbone/translator/coverage helpers

Coverage includes: full-board ranking correctness, positional
translation (exact / interpolated / extrapolated / fallback), mixed
blending with shallow lists, offense non-regression, transparency field
presence, dual-scope IDPTC ranking, cross-universe combined-pass
ranking, and edge cases (missing position group, unsupported IDP alias,
duplicate player across families, shallow backbone extrapolation, tied
source values deterministically resolved by name).

## Related documents

- `src/canonical/player_valuation.py` — the shared Hill curve and six-step
  canonical valuation engine.
- `CLAUDE.md` — top-level project conventions and non-negotiable rules.
