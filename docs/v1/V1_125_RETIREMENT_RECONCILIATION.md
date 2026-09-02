# V1-125 duplicate-owner retirement reconciliation

Exact-head census base: `f83e1e3f104125e4ea12e3d7b3befcebb24fe534` (2026-09-02).

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
| `C2-U2` / `C2-REPL-01` | owner shown historically as `(to consolidate)`; retire 5 implementations | later V1-29 work explicitly closed the replacement-level single-owner discovery gap and corrected the canonical-unit record, but the execution-map line itself was never reconciled | `NEEDS_CURRENT_REACHABILITY_CHECK` | enumerate current replacement definitions/importers and compare to the V1-29 guard before deleting anything |
| `C2-U4` / `C2-STR-01` | retire 4 notions of Team Strength | map was corrected 2026-08-20 to canonical `src/roster_intel/strength.py`; historical count alone does not prove four live owners remain | `NEEDS_CURRENT_REACHABILITY_CHECK` | use current import/definition census plus the row-specific single-owner evidence; stop if a distinct ROS composite is semantically intentional |
| `C2-U5` / `C2-WEAK-01` | retire >=5 need definitions | historical declaration does not identify enough current targets to delete safely | `NEEDS_CURRENT_REACHABILITY_CHECK` | enumerate definitions and consumers; require later row-specific owner evidence before any retirement |

## Hard stops discovered so far

None of the entries above currently requires an owner methodology decision. The unresolved entries
are evidence/reachability work, not permission to delete.

## Promotion gate still outstanding

V1-125 remains ineligible for promotion until **every V1-applicable** `retires` declaration is
classified using current reachability evidence, every `LIVE_SECOND_OWNER_SETTLED_REPLACEMENT` is
retired without semantic drift, and an exact-head automated zero-live-second-owner check is green.
