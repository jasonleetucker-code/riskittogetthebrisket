# V1-125 duplicate-owner retirement reconciliation

Exact-head census base: `78e6d4f7fea0c8a426faf4b7d6a972732421a07f` (2026-09-03).

This record exists only to reconcile historical `retires` declarations in
`docs/C_SERIES_EXECUTION_MAP.md` against later row-specific closure evidence before any deletion.
It is not deletion authority by itself and it does not promote V1-125. The governing invariants
remain ONE CONCEPT/ONE CANONICAL OWNER, missing != zero, stale != current, and no methodology
change by inference.

## Classification vocabulary

- `ALREADY_RETIRED_OR_INERT` — later row-specific evidence already proves the historical second
  owner was retired/adapted or is intentionally non-owning. No mechanical deletion is due from
  this census entry.
- `LIVE_SECOND_OWNER_SETTLED_REPLACEMENT` — a current live second owner remains and the canonical
  replacement is already settled by later evidence. This is the only class eligible for bounded
  mechanical retirement.
- `OWNER_DECISION_REQUIRED` — current ownership or methodology is genuinely ambiguous. Stop; do
  not choose an owner by inference.
- `NEEDS_CURRENT_REACHABILITY_CHECK` — historical prose is stale or broad enough that current code
  reachability still has to be proven before classification.

## Reconciled entries

| execution-map unit | historical declaration | later governing evidence | classification | action |
|---|---|---|---|---|
| `C1-U2` / `C1-ID-01` | retire 3 independent player matchers | execution-map row itself records CLOSED 2026-08-16, cutover at both production sites, legacy ladders deleted, no flag/fallback; V1-01 is `VERIFIED` | `ALREADY_RETIRED_OR_INERT` | none |
| `C2-U1` / `C2-LINE-01` | retire 3 production greedy fills plus duplicate eligibility/demand definitions | execution-map closure text records all three competing greedy fills retired; V1-27 is `VERIFIED` against the canonical exact solver | `ALREADY_RETIRED_OR_INERT` | none |
| `C3-U2` / `C3-VA-01`,`C3-VA-02` | consolidate Value Adjustment copies | execution-map row records COMPLETE: monkeypatch + second Python port retired; forced public/private wrapper delegates to shared stdlib core; `tests/valuation_math/test_single_owner.py` is the structural guard | `ALREADY_RETIRED_OR_INERT` | none |
| `C3-U1` / `C3-PKG-01` | historical map names `suggestions.py` as the live package-generator holdout | later V1-36 contract row is `VERIFIED`; current trade code documents construction mechanics as owned by `src/packages/construction.py` | `ALREADY_RETIRED_OR_INERT` | no deletion from stale map prose; zero-owner guard still must include this family |
| `C2-U2` / `C2-REPL-01` | owner shown historically as `(to consolidate)`; retire 5 implementations | `scripts/replacement_census.py` is the current V1-29 discovery/ownership guard. It declares the live replacement implementations by quantity, unit, population and disposition, derives production callers by AST, preserves materially distinct quantities rather than collapsing them, marks `src/scoring/replacement_level.py::vorp_table` as RETIRED, and fails if retired symbols reappear. The canonical owners are explicit for each actually shared quantity (`src/league_intel/replacement.py` for ROS-production levels; `src/scoring/replacement_level.py::replacement_per_game` for fantasy-points replacement), while adapters delegate and distinct populations/units remain intentionally separate. | `ALREADY_RETIRED_OR_INERT` | no deletion from the historical “5 implementations” count; keep the V1-29 census/retired-symbol guard as the zero-second-owner authority for this family |
| `C2-U4` / `C2-STR-01` | retire 4 notions of Team Strength | canonical owner is `src/roster_intel/strength.py`. `tests/roster_intel/test_strength_weakness_single_owner.py` scans all production Python definition sites by AST and asserts every public Team Strength owner symbol (`PositionStrength`, `TeamStrength`, `build_team_strength`, `rank_team_strengths`) is defined only at that canonical path; its positive-control probe demonstrates a second owner is detected. The test’s own historical note records the previously live frontend duplicates as retired. | `ALREADY_RETIRED_OR_INERT` | none; retain the definition-site discovery guard and do not collapse semantically distinct ROS/portfolio/marginal quantities into Team Strength |
| `C2-U5` / `C2-WEAK-01` | retire >=5 need definitions | canonical owner is `src/roster_intel/weakness.py`. The same AST discovery guard asserts every public Team Weakness owner symbol (`PositionRanks`, `SlotRung`, `PositionNeed`, `TeamWeakness`, `build_position_ranks`, `build_team_weakness`) is defined only at that canonical path; its positive-control probe demonstrates a second weakness owner is detected, and the guard pins the historical `PositionNeed` naming collision as renamed rather than redefined. | `ALREADY_RETIRED_OR_INERT` | none; retain the definition-site discovery guard and keep distinct roster quantities distinct |

## Hard stops discovered so far

None of the entries above currently requires an owner methodology decision. The reconciled C2
families are guarded as single-owner or explicitly distinct by unit/population; deleting those
distinct implementations merely to satisfy historical duplicate counts would violate the
canonical-owner methodology rather than enforce it.

## Promotion gate still outstanding

V1-125 remains ineligible for promotion until **every V1-applicable** `retires` declaration is
classified using current reachability evidence, every `LIVE_SECOND_OWNER_SETTLED_REPLACEMENT` is
retired without semantic drift, and an exact-head automated zero-live-second-owner check is green.
