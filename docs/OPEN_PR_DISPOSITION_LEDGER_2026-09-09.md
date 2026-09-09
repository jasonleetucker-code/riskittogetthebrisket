# Open PR Disposition Ledger — 2026-09-09

**Census base:** `18452f714608265ae446e61b28cd042fa8a87b79`  
**Open PRs at census:** 30  
**Purpose:** preserve useful work while draining stale/ambiguous PRs. This ledger is disposition evidence, not product authority. Current `main`, active owner directives, and normal CI/review gates still decide what may merge.

## Disposition rules

- **MERGE WHEN GREEN** — current bounded work; merge only after its required exact-head/current-candidate gate.
- **RE-DERIVE / REPLACE** — concept remains useful, but the old branch is too stale or overlaps newer architecture. Port the smallest current-head change, then close the old PR as superseded.
- **DEFER / PRESERVE REFERENCE** — useful future work not authorized/needed in the current launch window. Preserve branch/diff and durable backlog reference; close the stale PR.
- **CLOSE ABSORBED / OBSOLETE** — value already landed, superseded, or the dependency constraint already permits the requested version. Do not merge.
- **INTENTIONAL MAJOR UPGRADE** — meaningful dependency jump requiring fresh migration validation, not blind Dependabot merge.

## Current queue

| PR | Disposition | Rationale / replacement |
|---|---|---|
| #1311 | MERGE WHEN GREEN | Fresh current-main frontend dependency refresh; Next 16.3.4 + grouped minor/patch updates. Supersedes #1264/#1300 if green. |
| #1310 | MERGE WHEN GREEN | Fresh current-main Week 1 production-proof triggers; supersedes green-but-old-base #1307. |
| #1309 | MERGE WHEN GREEN | Cross-model benign-main-movement policy; owner-directed process fix. |
| #1307 | CLOSE SUPERSEDED after #1310 | Same two workflow changes; #1310 is the current-main re-derivation. |
| #1300 | CLOSE SUPERSEDED after #1311 | Next 16.3.3 is older than #1311's 16.3.4 target. |
| #1299 | INTENTIONAL MAJOR UPGRADE | Vitest 4 -> 5. Recreate on current main and validate migration deliberately, or defer; do not blind-merge stale branch. |
| #1298 | RE-DERIVE / REPLACE | Lock-only nanoid patch. Fold into a fresh lock refresh after #1311 or recreate current-head. |
| #1297 | RECONCILE + MERGE | Priority DLF/KTC semantic repair. Resolve current-main conflicts, full hard gate, exact-head independent review, then merge. |
| #1290 | RECONCILE AFTER #1297 | Hill Autopilot overlaps valuation/evidence semantics; repair formatting/tests on post-#1297 main, safety review, then merge if green. |
| #1264 | CLOSE SUPERSEDED after #1311 | Fresh #1311 ports the same grouped refresh onto current main. |
| #1217 | RE-DERIVE / REPLACE | Preserve shadow-only FAAB activation semantics; port minimal flag/logging change to current main and prove live response unchanged. |
| #1203 | MERGE WHEN GREEN | Dependabot has refreshed it onto current main; audit remaining Actions-version diff and merge if CI stays green. |
| #1202 | RE-DERIVE / REPLACE | Tiny root Playwright patch, but ancient branch. Recreate current-head and run E2E. |
| #982 | DEFER / PRESERVE REFERENCE | C4 FAAB Market Heat remains post-launch/backlog work; stale branch should not be merged wholesale. |
| #980 | DEFER / PRESERVE REFERENCE | C6 Analyst claim/evidence ledger remains future architecture reference. |
| #975 | SPECIAL DEFER / PRESERVE | Automatic pre-auction snapshot is perishable; preserve implementation reference and re-derive for the next applicable auction if current event evidence cannot be recovered. |
| #970 | DEFER / PRESERVE REFERENCE | C6 central Buy/Sell reconciler remains future roadmap work. |
| #969 | DEFER / PRESERVE REFERENCE | C5 WAR/VORP deterministic core remains future roadmap work. |
| #921 | DEFER / PRESERVE REFERENCE | Per-source rank history is explicitly post-launch evidence capture; preserve and re-derive later. |
| #775 | CLOSE OBSOLETE | `uvicorn~=0.52.0` already permits 0.52.1. |
| #774 | CLOSE OBSOLETE | `openpyxl~=3.1.0` already permits 3.1.5. |
| #773 | CLOSE OBSOLETE | `pywebpush~=2.0` already permits 2.x, including requested 2.4. |
| #772 | INTENTIONAL MAJOR/MINOR UPGRADE | `pytest~=9.0.0` does not permit 9.1.x; meaningful upgrade, but ancient branch. Recreate intentionally or defer. |
| #771 | INTENTIONAL UPGRADE | Python Playwright 1.58 -> 1.62 is meaningful; recreate current-head with browser/runtime verification. |
| #763 | CLOSE PRE-SQUASH / RE-DERIVE IF NEEDED | Stacked pre-#722 palette optimization; do not merge old stack. |
| #762 | CLOSE PRE-SQUASH / PRESERVE DIAGNOSTIC | Old E2E unstamped-snapshot investigation; reproduce current-head before any port. |
| #761 | CLOSE PRE-SQUASH / RE-DERIVE IF NEEDED | Historical first-load measurement branch; remeasure on current site if needed. |
| #760 | CLOSE ABSORBED | FPS harness/windowing machinery now exists on main; old historical claims are superseded. |
| #759 | CLOSE ABSORBED | Non-data-route player-fetch gating is already present on main. |
| #758 | CLOSE ABSORBED | Core SSR duplication invariant/tests were ported to main; old measurement branch is archival. |

## Closure discipline

Before closing a stale PR, add a factual comment naming one of: `absorbed`, `superseded`, `deferred/reference preserved`, `obsolete`, or `re-derive on current main`. Do not delete useful source branches during this cleanup.

A stale PR is not kept open merely to remember that work existed. The durable record is this ledger plus the canonical roadmap/backlog and the retained Git history/branch where useful.

## End-state target

The target is **zero ambiguous PRs**, not artificially zero PRs. Anything left open must be actively validating, actively being repaired, or intentionally awaiting a named current dependency with a clear owner and next action.
