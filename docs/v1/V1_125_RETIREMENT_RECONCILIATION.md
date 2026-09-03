# V1-125 duplicate-owner retirement reconciliation

Exact-head census base: `e98dc9a5e0e892445674c9546752a818c6b4fc46` (2026-09-03).

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
| `C1-U3` / `C1-ID-02` | `retires/adapts` the measured 39 independent pick-identity definition sites | execution-map closure records the canonical `src/identity/picks.py` owner, consumer adaptation with byte parity, and deferred consumers explicitly separated rather than silently treated as duplicate owners; V1-02 is `VERIFIED` at L2 | `ALREADY_RETIRED_OR_INERT` | none; deferred consumer migration is not a second pick-identity owner |
| `C1-U4` / `C1-HIST-01…03` | retire fragmented as-of semantics across 5 measured decision paths while retaining raw stores as evidence feeds | execution-map closure records `src/history/` as the immutable as-of owner and explicitly says raw stores remain recording/evidence feeds; V1-03, V1-04 and V1-05 are `VERIFIED`, including production as-of proof and the never-future/missing-history semantics | `ALREADY_RETIRED_OR_INERT` | none; do not delete raw evidence stores merely because their former decision semantics were retired |
| `C2-U1` / `C2-LINE-01` | retire 3 production greedy fills plus duplicate eligibility/demand definitions | execution-map closure text records all three competing greedy fills retired; V1-27 is `VERIFIED` against the canonical exact solver | `ALREADY_RETIRED_OR_INERT` | none |
| `C3-U2` / `C3-VA-01`,`C3-VA-02` | consolidate Value Adjustment copies | execution-map row records COMPLETE: monkeypatch + second Python port retired; forced public/private wrapper delegates to shared stdlib core; `tests/valuation_math/test_single_owner.py` is the structural guard | `ALREADY_RETIRED_OR_INERT` | none |
| `C3-U1` / `C3-PKG-01` | historical map names `suggestions.py` as the live package-generator holdout | later V1-36 contract row is `VERIFIED`; current trade code documents construction mechanics as owned by `src/packages/construction.py` | `ALREADY_RETIRED_OR_INERT` | no deletion from stale map prose; zero-owner guard still must include this family |
| `C2-U2` / `C2-REPL-01` | owner shown historically as `(to consolidate)`; retire 5 implementations | `scripts/replacement_census.py` is the current V1-29 discovery/ownership guard. It declares the live replacement implementations by quantity, unit, population and disposition, derives production callers by AST, preserves materially distinct quantities rather than collapsing them, marks `src/scoring/replacement_level.py::vorp_table` as RETIRED, and fails if retired symbols reappear. The canonical owners are explicit for each actually shared quantity (`src/league_intel/replacement.py` for ROS-production levels; `src/scoring/replacement_level.py::replacement_per_game` for fantasy-points replacement), while adapters delegate and distinct populations/units remain intentionally separate. | `ALREADY_RETIRED_OR_INERT` | no deletion from the historical “5 implementations” count; keep the V1-29 census/retired-symbol guard as the zero-second-owner authority for this family |
| `C2-U4` / `C2-STR-01` | retire 4 notions of Team Strength | canonical owner is `src/roster_intel/strength.py`. `tests/roster_intel/test_strength_weakness_single_owner.py` scans all production Python definition sites by AST and asserts every public Team Strength owner symbol (`PositionStrength`, `TeamStrength`, `build_team_strength`, `rank_team_strengths`) is defined only at that canonical path; its positive-control probe demonstrates a second owner is detected. The test’s own historical note records the previously live frontend duplicates as retired. | `ALREADY_RETIRED_OR_INERT` | none; retain the definition-site discovery guard and do not collapse semantically distinct ROS/portfolio/marginal quantities into Team Strength |
| `C2-U5` / `C2-WEAK-01` | retire >=5 need definitions | canonical owner is `src/roster_intel/weakness.py`. The same AST discovery guard asserts every public Team Weakness owner symbol (`PositionRanks`, `SlotRung`, `PositionNeed`, `TeamWeakness`, `build_position_ranks`, `build_team_weakness`) is defined only at that canonical path; its positive-control probe demonstrates a second weakness owner is detected, and the guard pins the historical `PositionNeed` naming collision as renamed rather than redefined. | `ALREADY_RETIRED_OR_INERT` | none; retain the definition-site discovery guard and keep distinct roster quantities distinct |

## Explicit `retires` lines outside the V1 denominator

`C6-U1` also carries a historical `retires` declaration (the Central Buy/Sell reconciler retires
multiple emitters). The V1 contract explicitly classifies the full analyst/signal-intelligence
continuation ecosystem as POST-V1. It is therefore **not** silently folded into V1-125's V1
acceptance set and is not used to enlarge the 136-row denominator. Its eventual retirement work
remains governed by its own post-V1 unit.

## Hard stops discovered so far

None of the V1-applicable entries above currently requires an owner methodology decision. The
reconciled C1/C2/C3 families are guarded as single-owner, explicitly adapted, or intentionally
distinct by role/unit/population; deleting those distinct implementations or evidence stores
merely to satisfy historical duplicate counts would violate the canonical-owner methodology
rather than enforce it.

## Promotion gate still outstanding

The explicit V1-applicable `retires` declarations are now represented in this reconciliation
record, but V1-125 remains ineligible for promotion until an **exact-head automated
zero-live-second-owner check** proves those classifications against current code. Any future
`LIVE_SECOND_OWNER_SETTLED_REPLACEMENT` discovered by that check must be retired without semantic
drift; any `OWNER_DECISION_REQUIRED` result remains a hard stop rather than an inferred choice.
