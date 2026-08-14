# Chase Upside — Current Execution Plan

**Status:** CANONICAL SEQUENCING / AUTHORIZATION RECORD  
**Last reconciled:** 2026-08-14  
**This file alone answers:** **What implementation work is authorized next?**  
**Companions:** `docs/MASTER_PRODUCT_PLAN.md`, `docs/PLANNING_DOCUMENT_STATUS.md`, `docs/C_SERIES_REPLAN_AND_COMPLETION_CONTRACT.md`

> Long-range approval is not current authorization. A feature may be fully specified and still be forbidden to begin until this file places it in the active sequence.

---

# 1. FOUNDATION PROGRAM — COMPLETED / ACCEPTED THROUGH B8

## B4 — percentile-tail saturation

- **COMPLETE / ACCEPTED.**
- PR #805 merged.
- Canonical tail saturation boundary: 904.
- No Hill promotion/refit was authorized merely by B4.

## B5 — canonical player identity

- **COMPLETE / ACCEPTED.**
- PR #806 merged.
- Identity repairs remain the canonical player-identity foundation; do not create per-feature alias/matching engines.

## B6 — league configuration / scoring identity

- **MERGED / VERIFIED.**
- PR #810 merged.
- B7.0 operational/evidence closure merged in PR #819.
- Cross-league scoring compatibility is a factual property of actual scoring settings, not a shared hand-authored `scoringProfile` label.
- Missing/unverified compatibility fails closed.
- Cross-league Sleeper data may not mix one league's teams with another league's scoring/roster/settings and claim ready.
- Detailed evidence remains in `docs/master-site-audit/B_SERIES_EXECUTION_LEDGER.md` and the W18 evidence records.

## B7 — realized-points scoring correctness

- **MERGED.**
- PR #820 merged.
- Realized scoring is required to speak the live data vocabulary, distinguish scored/unscorable/gap states honestly, and keep player special teams distinct from DST scoring.
- Subsequent feature work must consume the canonical realized-scoring path rather than recreate scoring locally.

## B8 — privacy / public-distribution boundary

- **MERGED.**
- PR #821 merged.
- Public-vs-private is a semantic boundary enforced across HTTP and repository/distribution surfaces, not merely a field-name denylist.
- Per-manager proprietary decomposition, strategy, roster intelligence, FAAB intelligence, and similar private decision evidence cannot leak merely because a builder can produce it.
- Public facts/products that were deliberately retained public must not be accidentally over-gated.

## Out-of-band canonical-value correctness — PR #822

- **MERGED / BINDING INPUT TO B9.**
- The previous league-aware valuation lens was evaluated and **rejected as canonical** under the current evidence bar.
- Production returns to **one canonical player-value methodology** across devices/surfaces.
- Experimental adjusted values may remain research/diagnostic outputs but must not overwrite canonical value/rank/tier.
- The user-selectable/device-local “Market vs My League” canonical methodology split is not part of the current product.
- This is not a permanent rejection of league-aware valuation as a goal; any replacement must earn promotion through evidence and explicit approval.

---

# 2. ACTIVE AUTHORIZED FAST-LANE SEQUENCE

The owner-authorized B-Series Fast Lane continues in dependency order. Complete each merge unit on a validated exact head; do not opportunistically begin unrelated product features between units.

## NEXT — B9a: canonical individual 1–9999 value semantics

**Status:** AUTHORIZED NEXT FOUNDATION UNIT.

Primary purpose: make the canonical value contract internally honest and cross-surface invariant before normalizing individual sources around it.

At minimum reconcile/prove:

- one canonical player-value methodology, incorporating the #822 decision;
- declared 1–9999 semantics versus Hill asymptote/ceiling behavior;
- canonical value/rank/tier aliases and transport parity;
- compact/array/legacy representations must not disagree;
- missing/unpriced/sentinel states must not masquerade as finite canonical values;
- no device-local or persisted setting may silently change canonical methodology;
- downstream consumers must not serve an alternate quantity under canonical field names;
- exact producer/consumer ownership of canonical value is explicit and testable.

**Do not absorb B9b source-normalization policy into B9a merely because both touch values.** B9a establishes what the canonical unit/contract means; B9b establishes how source observations map into it.

## THEN — B9b: source scale normalization / market baseline ownership

**Status:** AUTHORIZED AFTER B9a PASSES.

Reconcile/prove at least:

- source-native value vs rank observations;
- per-source scale semantics and conversion ownership;
- `siteWeights` / source-weight canonical ownership;
- TE-basis handling and double-count prevention;
- dynasty-format/source-domain validation;
- source range/normalization behavior;
- historical/provenance stamps required to reconstruct the normalized observation;
- missing source evidence remains missing rather than a zero vote.

B9b must consume the canonical unit semantics B9a establishes rather than defining a second scale implicitly.

## THEN — B10: source independence / anti-circularity / leave-one-out

**Status:** AUTHORIZED AFTER B9b PASSES.

The exact implementation may retain the approved tranche structure from the B-Series ledger, but the end state must establish:

- no source/thesis/correlation family gets counted multiple times merely through mirrors, derivatives, cross-platform copies, or same-provider variants;
- anchor/market evidence cannot secretly vote and then independently judge the result as though it were external;
- correlation/provenance families are explicit;
- leave-one-out / sensitivity measurements exist where required;
- source-family-aware aggregation is validated against pinned before/after history rather than plausibility alone.

## THEN — B11: confidence semantics

**Status:** AUTHORIZED AFTER B10 PASSES.

Confidence must be a truthful statement about evidence quality/coverage/disagreement/uncertainty — not a decorative score and not a duplicate direction signal.

At minimum separate:

- direction / value conclusion;
- coverage / sample size;
- source independence;
- freshness;
- disagreement/dispersion;
- model/measurement uncertainty;
- unsupported/unavailable state.

Confidence must not become high merely because correlated sources repeat the same underlying opinion.

---

# 3. EXACT-HEAD / MERGE / DEPLOY RULE FOR THE REMAINDER OF B

For every B9a→B11 merge unit:

1. re-read current `main` and the exact approved scope;
2. reproduce/measure the live defect or contract gap before changing production behavior;
3. establish RED or equivalent falsifiable evidence before GREEN where applicable;
4. repair the canonical owner rather than consumers individually;
5. run focused tests + required broad regression/backtest/contract gates;
6. validate the **exact final head SHA**;
7. merge only that validated head;
8. deploy through the normal production path where the unit changes production;
9. perform risk-proportional production verification;
10. record the evidence in the appropriate ledger/spec;
11. continue to the next authorized Fast Lane unit only if no genuine owner decision or blocker was uncovered.

A green test on an earlier SHA is not evidence for a later head.

---

# 4. HARD GATE AFTER B11 — NO AUTOMATIC C1

**Binding owner decision:** there is **no automatic B11 → C1 transition**.

After B11 is completed/accepted:

1. **STOP. Do not begin an inherited/old C1.**
2. Put Claude Code in **Plan Mode only**.
3. Read `docs/C_SERIES_REPLAN_AND_COMPLETION_CONTRACT.md` in full.
4. Re-read actual current `main`, production state, canonical contracts, all owner scope/spec records, all later addenda, and relevant evidence.
5. Build and commit the exhaustive **C-Series Scope Manifest** — one row for every owner-approved feature/capability, including existing-but-partial/duplicated/unreachable systems.
6. Reconcile at minimum the Master Product Plan, Owner Master Feature Backlog, owner reconciliation + appendix, Product Backlog Spec, Owner Requested TODO + index, Player Impact spec, Trade Calculator Market Evidence expansion, Premium Sports Intelligence records, CE-01–CE-21, and every later owner addition made before the gate.
7. Build the dependency DAG first: canonical owners, prerequisites, shared foundations, duplicate-engine consolidation/retirement, migrations/backfills, data/licensing blockers, performance budgets, public/private boundaries, safe parallel lanes, PR boundaries, rollout/rollback, production proof.
8. Optimize total delivery time by building shared foundations once and parallelizing only genuinely independent/non-overlapping work.
9. Explicitly carry the hard owner requirement that **every valid supported pick through 2029 has a finite non-missing canonical value by C completion**.
10. Produce a proposed canonical **C-Series Execution Plan**.
11. Jason + ChatGPT review it and may reorder, combine, split, expand, or reject methodology.
12. **Only explicit owner approval authorizes C implementation.**

The old shorthand C ordering is dependency evidence only, not an implementation queue.

---

# 5. C EXECUTION STANDARD AFTER OWNER APPROVAL

Once the post-B C plan is approved, C should proceed continuously within its approved boundaries without routine permission pauses unless a genuine owner decision is discovered.

Use one coordinated program, **not one giant PR**:

- evidence/RED → canonical implementation → focused validation → broad gates/backtest where applicable;
- exact-head CI;
- merge validated head only;
- deploy through normal production path;
- production smoke/E2E/data-contract verification proportional to risk;
- mobile + desktop proof for relevant product surfaces;
- performance/degraded-state/accessibility/observability proof;
- record completion evidence + rollback;
- then allow dependent phases to treat the capability as complete.

A page rendering or unit test passing is not product completion.

---

# 6. PRODUCT WORK THAT MUST NOT PREEMPT B FOUNDATIONS

The following are approved long-range scope but are **not authorized merely by appearing here** before the B→C gate:

- canonical owned future-pick projection/value and complete pick values through 2029;
- mature Trade Calculator / Trade Desk / real-trade database / comparable-trade expansion;
- Team Strength / Team Weakness / roster-impact canonicalization beyond B needs;
- Market Trade Ledger;
- Manager Scout;
- Perfect Waivers / mature FAAB product;
- Analyst Intelligence podcast + YouTube expansion;
- central Buy/Sell / mature Consensus Edge;
- Universal Player Profile expansion;
- Playoff / Power / Game Day expansions;
- Player Impact / WAR / xWAR / WAB;
- Awards & Honors;
- The Upside Report;
- Public League Experience v3 expansion;
- Command Center / Portfolio;
- Share Renderer;
- PAR/Stats/ADP/Utilization/Draft Room/Lineup Intelligence;
- Premium Sports Intelligence migration except when its explicit migration gate is reached and separately authorized;
- CE-01–CE-21 reconciled expansion;
- large X analyst feed;
- adaptive source weighting / learned production weighting.

They may be read during foundation work to avoid architectural contradictions. Do not opportunistically implement them inside B9a–B11.

---

# 7. SAFE HOTFIXES / OWNER DEFECTS

Real production defects and narrow reliability/security emergencies may be handled at a safe checkpoint when they are urgent or directly block the active phase. Keep them narrowly scoped and do not use a hotfix as a vehicle for unrelated feature work.

Examples include authenticated/admin correctness, Trade Calculator correctness, public-League missing-data-as-zero defects, deployment/reliability regressions, and security/privacy faults.

---

# 8. C COMPLETION HARD GATE

Before C can be declared complete, run the dedicated completion audit in `docs/C_SERIES_REPLAN_AND_COMPLETION_CONTRACT.md`.

There may be **no silent deferrals**. Every approved C-scope feature must be either:

- implemented at the correct canonical layer, real-data connected, reachable, deployed, performant, production-verified, mobile-complete where required, observable, and ready for confident use; or
- explicitly changed/removed/deferred by a new owner decision because a concrete external blocker makes implementation impossible or unsound.

Without explicit owner disposition, “planned later”, “mostly done”, “backend only”, “desktop only” where parity is required, “flagged off”, “mocked”, “unpriced valid pick”, or “tests pass but production was not verified” is **not complete**.

Only after the final audit passes may Claude state:

> **`C-SERIES COMPLETE — EVERY APPROVED FEATURE DEPLOYED, PRODUCTION-VERIFIED, AND READY FOR CONFIDENT USE`**

---

# 9. EXECUTION UPDATE RULE

At every completed/accepted checkpoint:

1. update this file to remove any stale “next” phase;
2. record the exact next authorized scope;
3. keep detailed long-range feature intent in the Master Product Plan / active detailed specs instead of duplicating it here;
4. never let `CLAUDE.md`, `ARCHITECTURE_HANDOFF.md`, B-Series ledger prose, an old roadmap, PR description, or session capture override this file for current authorization;
5. if current code/evidence disproves this execution state, reconcile this file before beginning another unit.

This document must stay short enough that a fresh implementation session can identify the current authorization in minutes.
