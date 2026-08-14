# Chase Upside — Product Direction Synchronization Manifest

**Status:** CANONICAL SYNCHRONIZATION RECEIPT / DRIFT-PREVENTION INDEX  
**Created:** 2026-08-14  
**Purpose:** prove how the repository's feature, roadmap, master-plan, execution, Claude/runbook, architecture, evidence, competitor, TODO, and historical planning records relate so they cannot silently become competing sources of direction.

This manifest is **not another roadmap**. It records the synchronization contract among the roadmaps/specs/evidence that already exist.

---

# 1. WHAT “IN SYNC” MEANS

A repository with years of plans, audits, PRs, experiments, and handoffs should not rewrite history merely to make every old sentence sound current.

A planning layer is synchronized when:

1. there is one canonical long-range product-direction front door;
2. there is one current sequencing / authorization record;
3. every active feature/spec record has an explicit role and precedence;
4. dated inventories/evidence are clearly classified as dated rather than silently promoted to live truth;
5. old roadmaps/PR prose/session captures cannot authorize work;
6. global owner decisions are reconciled into active canonical records;
7. current code/runtime evidence can correct status without overriding owner intent;
8. new owner features cannot disappear because they were absent from an older plan;
9. historical evidence remains available rather than being falsified by retrospective edits;
10. a future Claude session can determine “what do we want?”, “what is true now?”, “what is authorized next?”, and “which spec owns this feature?” without conversational memory.

---

# 2. SYNCHRONIZED CORE

| Record | Classification | Synchronized role |
|---|---|---|
| `PRODUCT_PLAN.md` | **CANONICAL ENTRYPOINT** | First file for product/feature/roadmap work; points to Master Plan, Execution Plan, status map, sync manifest |
| `docs/MASTER_PRODUCT_PLAN.md` | **CANONICAL LONG-RANGE DIRECTION** | Product north star, global invariants, feature families, conflict resolutions, precedence |
| `docs/EXECUTION_PLAN.md` | **ONLY CURRENT AUTHORIZATION / SEQUENCE** | B9a → B9b → B10 → B11; then hard B→C replan gate |
| `docs/PLANNING_DOCUMENT_STATUS.md` | **CANONICAL AUTHORITY MAP** | Classifies active specs, evidence, historical records, CLAUDE/architecture roles |
| `docs/PRODUCT_DIRECTION_SYNC_MANIFEST.md` | **SYNC RECEIPT** | This file; ensures the classification itself stays explicit |
| `CLAUDE.md` | **TECHNICAL OPERATING CONSTITUTION** | Repo workflow, technical invariants, validation/deployment discipline; may not authorize product work |

The first four answer different questions by design. None should duplicate the entire contents of the others.

---

# 3. ACTIVE OWNER FEATURE / DIRECTION COVERAGE

| Record | Classification | What must survive from it |
|---|---|---|
| `docs/OWNER_MASTER_FEATURE_BACKLOG_2026-08-13.md` | **ACTIVE EXHAUSTIVE COVERAGE LEDGER** | Every owner-discussed feature/capability captured for the eventual zero-loss C scope census |
| `docs/OWNER_FEATURE_SPEC_RECONCILIATION_2026-08-13.md` | **ACTIVE BINDING NEWER OWNER SPEC** | Specification-depth contract + reconciled current/partial/future feature intent |
| `docs/OWNER_FEATURE_SPEC_APPENDIX_2026-08-13.md` | **ACTIVE BINDING COMPANION** | Smaller/secondary/CE features and policies that must not be left as names only |
| `docs/OWNER_PRODUCT_BACKLOG_SPEC.md` | **ACTIVE SUPPLEMENTAL DETAILED SPEC** | Older detailed methodology/UX decisions where newer owner records have not superseded them |
| `docs/OWNER_REQUESTED_TODO.md` | **ACTIVE COMPACT OWNER REQUEST LEDGER** | Durable owner requests; not implementation-grade by itself |
| `docs/OWNER_REQUESTED_TODO_SPEC_INDEX.md` | **ACTIVE SPEC MAP** | Maps compact owner requests to detailed binding specifications |
| `docs/PLAYER_IMPACT_WAR_MVP_SPEC.md` | **ACTIVE BINDING FEATURE SPEC** | Realized Lineup VORP, WAR, xWAR, WAB, Game Changer, Awards/MVP constraints |
| `docs/TRADE_CALCULATOR_MARKET_EVIDENCE_EXPANSION_SPEC.md` | **ACTIVE BINDING FEATURE SPEC** | Mature Trade Calculator, amount-to-even/equalizers, real-trade database, comparables, market analytics, share/mobile acceptance |
| `docs/C_SERIES_REPLAN_AND_COMPLETION_CONTRACT.md` | **ACTIVE FUTURE EXECUTION CONTRACT** | How C must be replanned/ordered/parallelized/deployed/proved complete after B; cannot start C early |
| Premium Sports Intelligence design/spec records | **ACTIVE VISUAL DIRECTION, MIGRATION-GATED** | Approved visual north star; do not turn it into a premature reskin or a duplicate business-logic layer |
| Feature-specific specs named by the active hierarchy | **ACTIVE FOR THEIR FEATURE** | Detailed behavior, subject to newer explicit owner decisions and current execution authorization |

### Rule

The eventual C0 Scope Manifest is a **union-and-reconcile** of these records plus then-current code/runtime truth. It may not take one older inventory as the whole scope.

---

# 4. DATED / EVIDENCE RECORDS THAT REMAIN IMPORTANT

These stay in the repository and may contain valuable or even load-bearing facts. Their *age/status* is the thing being synchronized.

| Record/family | Classification | Synchronization rule |
|---|---|---|
| `docs/OWNER_FEATURE_INVENTORY.md` | **DATED 2026-08-11 FEATURE/STATUS CENSUS** | Use for breadth/status archaeology; do not treat its old phase/status cells as current authorization |
| `docs/master-site-audit/B_SERIES_EXECUTION_LEDGER.md` | **B-SERIES EVIDENCE LEDGER** | Detailed receipts and measurements; may lag latest merge status; explicitly authorizes nothing |
| `docs/master-site-audit/**` evidence/findings/proof cases | **PINNED EVIDENCE** | Facts apply to the code/input state named by the artifact; newer code may change current status |
| `docs/ARCHITECTURE_HANDOFF.md` | **TECHNICAL HANDOFF / EVIDENCE** | Architecture details may be useful; phase/status prose is subordinate to Execution Plan |
| ADRs | **SCOPED TECHNICAL DECISIONS** | Canonical for their scoped decision while current; do not create product scope/priority by themselves |
| `docs/WORK_CLAIMS.md` | **CONCURRENCY COORDINATION** | Tells who owns paths now, not what feature is approved |

---

# 5. HISTORICAL / RESEARCH RECORDS — PRESERVE, DO NOT OBEY AS A QUEUE

The following categories are intentionally retained but cannot independently redefine scope or sequencing:

- `UNIMPLEMENTED_BACKLOG.md`;
- `docs/master-site-audit/NEXT_STEPS.md`;
- `docs/master-site-audit/REPAIR_ROADMAP.md`;
- old `BLUEPRINT_EXECUTION` / phase plans when superseded;
- older owner addenda already reconciled into active specs;
- competitor-specific TODOs/addenda/checkpoints;
- `docs/competitive/**` research;
- old Public League phase documents superseded by Public League Experience v3 intent;
- session handoffs / branch disposition notes;
- PR descriptions/comments/review prose;
- superseded model proposals, refit experiments, and rejected methodologies;
- screenshots/captures used to derive later owner requirements.

These records answer “what did we think/measure/plan then?” They do not answer “what may I implement now?”

---

# 6. CURRENT PROGRAM STATUS SYNCHRONIZED ACROSS DIRECTION DOCS

The current active dependency program is:

- B4 complete/accepted (#805);
- B5 complete/accepted (#806);
- B6 merged/verified (#810; operational verification #819);
- B7 realized scoring merged (#820);
- B8 privacy/public-distribution boundary merged (#821);
- #822 merged as an out-of-band canonical-value correctness decision, withdrawing the unvalidated league-aware lens from canonical serving;
- **next authorized: B9a** canonical 1–9999 value semantics;
- then **B9b** source scale/normalization ownership;
- then **B10** source independence/anti-circularity;
- then **B11** confidence semantics;
- then **STOP / Plan Mode / exhaustive C Scope Manifest + dependency DAG / owner review**;
- only then may a new approved C plan authorize C implementation.

Any active record that says B6 is still next, B7 has not started, B8 is merely queued, or PR #810 is not on main is stale status evidence, not the current plan.

---

# 7. GLOBAL OWNER DECISIONS RECONCILED IN THE ACTIVE HIERARCHY

These are the highest-risk places where older records could otherwise send implementation in the wrong direction.

## 7.1 Product identity

**Chase Upside** is the current product name. Do not blanket-rewrite operational/historical league/repository identifiers whose old name is part of their identity.

## 7.2 One canonical player-value methodology today

PR #822 rejected the existing league-aware valuation implementation as canonical. Canonical values may not differ by device or a persisted user-local methodology toggle. Experimental adjusted values do not overwrite canonical value/rank/tier.

A future league-aware methodology is allowed only after evidence + explicit promotion; this decision does not forbid the product goal.

## 7.3 Every valid supported pick through 2029 has value by C completion

Older language permitting valid 2028/2029 picks to remain indefinitely unpriced is superseded. Unknown slot means a documented uncertain/generic valuation — not disappearance and not zero.

## 7.4 Missing is never zero

Applies to values, history, scoring, roster/team assignment, projections, market evidence, Analyst Intelligence, Sharp evidence, public data readiness, and every degraded state.

## 7.5 Player MVP eligibility

No hard playoff-field or >.500 player-MVP gate. Team success may be context/tie-break evidence. MOTY may use separately validated team-success eligibility.

## 7.6 Trade concepts remain separate

- canonical raw asset equity;
- exact KTC Value Adjustment as a market/consolidation lens;
- canonical before→apply→rerank→after roster marginal impact.

Do not collapse them into one unexplained scalar.

## 7.7 Seasonal concepts remain separate

Team Strength ≠ Weekly Power Rankings ≠ Playoff Predictor ≠ Standings.

## 7.8 C has a hard zero-loss completion rule

No automatic B11→C1. No silent “later” bucket at C completion. Every approved feature is either implemented/deployed/production-verified to its acceptance standard or explicitly dispositioned by the owner because of a concrete external blocker.

---

# 8. SYNC RULE FOR CLAUDE.md / TECHNICAL HANDOFFS

`CLAUDE.md` and architecture/handoff docs are allowed to describe technical implementation, but **must never be used as a second product roadmap**.

Rules:

1. `CLAUDE.md` points to the active planning hierarchy at startup.
2. If `CLAUDE.md` contains a status sentence that conflicts with `EXECUTION_PLAN.md`, Execution Plan wins and the stale technical prose should be corrected when touched.
3. Architecture handoffs may retain historical phase context if classified as historical/evidence; they cannot authorize a phase.
4. Fast-changing implementation details should live near their canonical code/ADR/feature doc rather than being duplicated across many master planning files.
5. A future Claude session must use current code/runtime evidence to verify whether a technical statement is still true before relying on it for a material change.

---

# 9. MAINTENANCE / DRIFT CHECK

Whenever a material owner feature/direction decision changes:

1. update the durable owner backlog/scope ledger;
2. update the detailed spec that owns the behavior;
3. update Master Product Plan only when a global/family/precedence rule changes;
4. update Execution Plan only when current authorization/sequence changes;
5. update Planning Document Status + this manifest if a record is created/reclassified;
6. update CLAUDE.md only for technical operating consequences, not to create priority;
7. preserve superseded evidence instead of rewriting history;
8. run the product-plan governance/drift checks in CI where available;
9. before C begins, regenerate the C Scope Manifest from the full union rather than trusting this static receipt.

---

# 10. SYNCHRONIZATION ACCEPTANCE CHECKLIST

This planning layer is synchronized only if all are true:

- [x] current product name and legacy-name boundary are explicit;
- [x] one Master Product Plan exists;
- [x] one current Execution Plan exists and is the only authorization record;
- [x] active owner backlog/spec records are named;
- [x] Owner Requested TODO is classified active, not historical;
- [x] dated Feature Inventory is classified as a census/evidence record rather than a live queue;
- [x] B4–B8 + #822 current state is reflected in active direction docs;
- [x] B9a→B9b→B10→B11 sequence is explicit;
- [x] hard post-B C replan is explicit;
- [x] C zero-loss completion contract is explicit;
- [x] 2029-pick value requirement is explicit;
- [x] player-MVP eligibility conflict is resolved;
- [x] one-canonical-value / unvalidated-league-lens decision is explicit;
- [x] CLAUDE/architecture/evidence/competitor/historical records are classified so they cannot override product direction;
- [x] old evidence remains preserved rather than cosmetically rewritten.

A future synchronization pass should update this receipt when the document set or authority model materially changes.
