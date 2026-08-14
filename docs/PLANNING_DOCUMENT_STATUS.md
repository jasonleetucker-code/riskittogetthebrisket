# Chase Upside — Planning Document Status / Authority Map

**Status:** CANONICAL GOVERNANCE INDEX  
**Last synchronized:** 2026-08-14  
**Canonical product-direction front door:** `docs/MASTER_PRODUCT_PLAN.md`  
**Only current sequencing / authorization record:** `docs/EXECUTION_PLAN.md`

This file exists so a future assistant cannot reasonably mistake an old session capture, audit roadmap, dated inventory, competitor TODO, implementation handoff, or PR description for the current product plan.

The repository intentionally preserves history. **Synchronization does not mean rewriting old evidence until it looks current.** It means every record has an explicit role and precedence so historical truth cannot become a competing roadmap.

---

# 1. CORE CANONICAL GOVERNANCE

| Document | Role / authority | May authorize implementation? |
|---|---|---|
| `PRODUCT_PLAN.md` | Root planning entrypoint; tells every session what to read first | No |
| `docs/MASTER_PRODUCT_PLAN.md` | Canonical long-range product direction, product families, durable invariants, conflict resolution, document precedence | No — direction is not authorization |
| `docs/EXECUTION_PLAN.md` | **Only current sequencing / authorization record**; says what work is authorized now and what is merely queued/future | **Yes** |
| `docs/PLANNING_DOCUMENT_STATUS.md` | This authority/classification map | No |
| `docs/PRODUCT_DIRECTION_SYNC_MANIFEST.md` | Synchronization receipt across active + historical feature/direction records | No |
| `CLAUDE.md` | Technical operating constitution/runbook; implementation invariants, repo workflow, validation discipline | **No** — explicitly subordinate to Product/Execution hierarchy for direction |

If a status sentence in any other record disagrees with `EXECUTION_PLAN.md`, reconcile the status rather than starting work from the stale sentence.

---

# 2. ACTIVE OWNER SCOPE / SPECIFICATION RECORDS

These preserve approved scope and intended behavior. They do **not** independently decide when implementation starts.

| Document | Active role |
|---|---|
| `docs/OWNER_MASTER_FEATURE_BACKLOG_2026-08-13.md` | Exhaustive discussion-derived owner feature coverage ledger; prevents ideas from disappearing during C replan |
| `docs/OWNER_FEATURE_SPEC_RECONCILIATION_2026-08-13.md` | Binding newer owner-intent / specification-depth registry across current, partial, and future product |
| `docs/OWNER_FEATURE_SPEC_APPENDIX_2026-08-13.md` | Binding companion for smaller/secondary/CE feature intent |
| `docs/OWNER_PRODUCT_BACKLOG_SPEC.md` | Older detailed owner methodology/UX specification; remains active where not superseded by newer explicit owner decisions/specs |
| `docs/OWNER_REQUESTED_TODO.md` | **Active compact durable owner-request ledger**. It is not a historical-only file. |
| `docs/OWNER_REQUESTED_TODO_SPEC_INDEX.md` | Maps compact owner requests to the implementation-grade detailed spec source |
| `docs/C_SERIES_REPLAN_AND_COMPLETION_CONTRACT.md` | Binding **post-B** C planning/execution/deployment/completion standard; does not authorize starting C early |
| `docs/PLAYER_IMPACT_WAR_MVP_SPEC.md` | Binding Player Impact / VORP / WAR / xWAR / WAB / MVP methodology requirements |
| `docs/TRADE_CALCULATOR_MARKET_EVIDENCE_EXPANSION_SPEC.md` | Binding mature Trade Calculator / real-trade / comparable-market / equalizer / sharing expansion requirements |
| Premium Sports Intelligence design records | Approved visual-direction source; migration remains dependency/authorization gated |
| Other feature-specific specs explicitly referenced by the Master Plan / owner reconciliation | Active for their feature, subject to newer owner decisions and `EXECUTION_PLAN.md` timing |

### Specification precedence

When detailed feature records disagree:

1. newest explicit owner instruction;
2. `MASTER_PRODUCT_PLAN.md` global conflict resolutions;
3. newest binding feature-specific owner spec / reconciliation / later addendum;
4. `OWNER_PRODUCT_BACKLOG_SPEC.md` where not superseded;
5. older detailed records as evidence/provenance.

A one-line TODO or inventory row is never enough implementation specification for material work.

---

# 3. ACTIVE EVIDENCE / STATUS RECORDS — NOT ROADMAP AUTHORITY

These may be extremely important, but they answer “what did we observe?” rather than “what should we build next?”

## `docs/OWNER_FEATURE_INVENTORY.md`

A **dated 2026-08-11 repo/status census** created as a scope-control checkpoint. It remains valuable for breadth, classification, repo archaeology, and detecting drift, but individual status/phase cells may become stale as the repository moves.

It is **not** the live execution queue. The eventual C0 scope census must reconcile it against the Owner Master Feature Backlog, newer specs, and then-current code rather than copying its old phase column.

## `docs/master-site-audit/`

Authoritative for measured findings/evidence at the pinned code/input state each artifact names. Not authoritative for current phase completion or long-range product scope.

Examples:

- `B_SERIES_EXECUTION_LEDGER.md` — detailed B-series evidence/receipts. It may lag the newest merge/status and explicitly authorizes nothing.
- `REPAIR_ROADMAP.md` — historical root-cause plan produced from the audit.
- `NEXT_STEPS.md` — historical session-resumption snapshot.
- evidence registries / reproduction artifacts / proof cases — pinned measurement records.

Use them to prove/understand a defect. Use `EXECUTION_PLAN.md` to decide what is authorized now.

## `docs/ARCHITECTURE_HANDOFF.md`

Technical handoff / canonical-owner / invariant evidence. Its architecture content may be useful and current; **its phase/status prose can age quickly**. It does not authorize work and cannot override `MASTER_PRODUCT_PLAN.md` or `EXECUTION_PLAN.md`.

## `docs/WORK_CLAIMS.md`

Concurrent-edit coordination only. A path being claimed does not make its feature authorized or prioritized.

## ADRs / implementation docs

Canonical for their explicitly scoped technical decision when still current. They do not create product scope or phase authorization by themselves.

---

# 4. RESEARCH / COMPETITOR RECORDS — INPUT, NOT ROADMAP

`docs/competitive/` and other competitor/site research preserve observations, ideas, and rationale. Approved concepts are reconciled into active owner scope/spec records.

A competitor page, screenshot, feature checklist, or research memo does not independently authorize copying or implementing anything.

Examples include Play For Keeps, Fantasy Navigator, Dynasty Daddy, OTC, KTC-inspired workflow research, and CE-derived research. Use the active owner spec to determine what Chase Upside is actually intended to build.

---

# 5. HISTORICAL / SUPERSEDED AS INDEPENDENT ROADMAP

Keep these for provenance; do not use them as independent implementation queues when they disagree with the active hierarchy:

- `UNIMPLEMENTED_BACKLOG.md`;
- `docs/OWNER_FEATURE_ADDENDUM_2026-08-11.md` where absorbed/superseded;
- `docs/SCOPE_COORDINATION_2026-08-11.md`;
- `docs/master-site-audit/NEXT_STEPS.md`;
- `docs/master-site-audit/REPAIR_ROADMAP.md`;
- `docs/competitive/DYNASTY_DADDY_INTEGRATION_TODO.md`;
- `docs/competitive/COMPETITIVE_EXPANSION_DYNASTY_DADDY_ADDENDUM.md` where reconciled;
- `docs/BLUEPRINT_EXECUTION.md` where it conflicts with newer owner scope;
- old public-league phase plans superseded by Public League Experience v3 intent;
- date-stamped session handoffs / branch-disposition notes / checkpoint files;
- old PR bodies/comments as statements of *what that PR claimed then*;
- superseded modeling proposals and rejected experiments.

**Do not “fix” historical evidence by rewriting it to modern conclusions.** Classification + explicit precedence is the synchronization mechanism.

If a historical capture contains a durable owner requirement that cannot be found in the Owner Master Feature Backlog / active detailed specs, that is documentation drift. Reconcile it before implementation.

---

# 6. GLOBAL CONFLICT RESOLUTIONS THAT ALL PLANNING RECORDS MUST HONOR

1. **Product name:** current product is **Chase Upside**; historical/repo/league/infra identifiers remain where identity requires them.
2. **Current canonical player value:** one canonical methodology. PR #822 rejected the existing league-aware lens as canonical; experimental adjusted output must not overwrite canonical value/rank/tier or recreate a device-local/user-selectable methodology split.
3. **Supported picks through 2029:** by C completion, every valid league-supported pick through the 2029 rookie class must have a finite, non-missing canonical Chase Upside value. Older indefinite-unpriced language is superseded.
4. **Missing is never zero:** applies across value, scoring, assignments, history, projections, analyst signals, market evidence, and degraded states.
5. **Player MVP:** no hard playoff-field or >.500 eligibility requirement. Team success may be context/tie-break evidence; MOTY may use validated team-success eligibility.
6. **Trade concepts:** canonical raw asset value, exact KTC Value Adjustment, and before→apply→rerank→after roster impact are distinct concepts.
7. **Seasonal concepts:** Team Strength ≠ Power Rankings ≠ Playoff Predictor ≠ Standings.
8. **No automatic B→C transition:** after B11, stop and perform the owner-approved C Scope Manifest + dependency-DAG replan before any C1 implementation.
9. **No silent C deferrals:** the C completion audit requires every approved feature to be implemented/deployed/production-verified or explicitly dispositioned by the owner due to a concrete external blocker.

---

# 7. OPERATING RULE FOR NEW OR CHANGED PRODUCT DIRECTION

Do not accumulate another permanent parallel roadmap because a new idea arrived.

When the owner materially changes or adds a feature:

1. record it in the Owner Master Feature Backlog / durable owner request layer so breadth cannot be lost;
2. update the existing detailed feature spec when possible; create a feature-specific spec only when depth genuinely requires it;
3. update `MASTER_PRODUCT_PLAN.md` only if product direction, global invariants, family structure, or precedence changes;
4. update `EXECUTION_PLAN.md` only if current authorization/sequence changes;
5. update this file + `PRODUCT_DIRECTION_SYNC_MANIFEST.md` when a planning record is created/reclassified or a precedence conflict is resolved;
6. preserve old evidence as history rather than editing away the fact that the decision changed.

Temporary capture notes are allowed during active work only if they name the canonical record into which their durable content must be reconciled.

---

# 8. FAST CHECK FOR ANY FUTURE CLAUDE / CHATGPT SESSION

Before implementing a material feature, be able to answer **yes** to all of these:

- Did I start at `PRODUCT_PLAN.md`?
- Did I read the current `MASTER_PRODUCT_PLAN.md`?
- Did I check `EXECUTION_PLAN.md` and confirm this exact work is authorized?
- Did I identify the active detailed owner spec rather than relying on a one-line backlog row?
- Did I inspect current code/runtime evidence so I know the actual implementation state?
- Did I check for an existing canonical owner / duplicate engine before adding another one?
- Did I preserve missing/degraded/provenance/freshness/confidence semantics?
- Did I separate historical evidence from current product direction?
- If the work is C-series work, has the B→C hard gate actually passed and has the owner approved the post-B C plan?

If not, stop the implementation and reconcile the planning state first.
