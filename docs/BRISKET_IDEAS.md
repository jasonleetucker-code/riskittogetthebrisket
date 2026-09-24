# Calculator Ideas — Owner Intake & Parallel Work Front Door

## Full completion portfolio / permanent UI batching — 2026-09-24 (#1421)

UI policy: ALWAYS_PARALLEL_UNTIL_UI_COMPLETE
UI batching: INCLUDE_OR_REFERENCE_ACTIVE_LANE

Calculator Ideas represents the entire remaining master site completion plan. Keep this
legacy filename; it is a front door, not a competing backlog. Before next reasonable
batch / next ten / parallel batches / fresh-session dispatch, reconcile current main,
open PRs/branches/claims, Master Plan, Feature Inventory, Product Backlog/specs, C-Series
manifest/map, completion contracts, owner intake, issues, code/production evidence and
the combined-phase replan. Remove completed/superseded/rejected work, group shared
foundations, respect dependencies and avoid active-file conflicts. Preserve #1419's
related full-portfolio reconciliation during integration, not one or the other.

Every substantial batch explicitly evaluates backend completion, UI completion, actual
UI staffing, stable routes, file/branch conflicts and integration order. Consult
`docs/ui/CALCULATOR_UI_IMPLEMENTATION_CONTRACT.md` and `docs/ui/UI_PARALLEL_LEDGER.md`. Required response shape:

- FOUNDATION / BACKEND: bounded authorized unit, canonical owner, dependencies.
- UI: safe unit/claim/branch, or `UI lane already active: <issue/PR/work claim>` with
  adequate coverage. Queued handoffs/old branches are not running workers. An unstable
  route contract blocks only its final wiring; select other useful UI work.
- INTEGRATION: contract connection, ordering, E2E and production proof. Backend complete
  / UI incomplete = product incomplete, without double-counting scope.

Use `docs/ui/UI_IMPACT_TEMPLATE.md` for material feature plans. Tiny maintenance need
not manufacture UI edits; substantial planning still names Lane 6 coverage.

**Status:** OWNER-FACING NAVIGATION / PROCESS LAYER  
**Owner directive:** 2026-09-24 · issue #1412  
**Product authority:** none by itself. `docs/EXECUTION_PLAN.md` remains the only implementation-authorization record.

This is the simple front door for ideas, defects, UX requests, methodology changes, future products, and “do this later” instructions for **Calculator**.

The owner should not need to remember the repository's planning-document hierarchy.

## 1. Conversational shorthand

When the owner says any of the following, treat them as equivalent:

- “add this to Calculator Ideas”
- “put this on the Calculator list”
- “save this idea”
- “remember this for the site”
- “we should build/fix/revisit this later”

The durable destination is still the existing canonical intake system:

```
owner statement
  -> docs/OWNER_REQUESTED_TODO.md        # live intake ledger
  -> existing/new GitHub issue or spec   # detail when needed
  -> canonical feature/spec/manifest mapping
  -> docs/EXECUTION_PLAN.md              # only place that authorizes implementation
```

**This file is not a second backlog.** It explains how to use the one we already have.

## 2. One idea, one durable record

Before creating anything new:

1. search `docs/OWNER_REQUESTED_TODO.md`;
2. search open/closed GitHub issues;
3. search the Feature Inventory / Product Backlog Spec / feature-specific specs;
4. search recent PRs and current code when the request may already be implemented;
5. update/supersede the existing record when one exists instead of creating a duplicate.

If a later owner instruction changes an earlier one, preserve the old record for history and mark the newer instruction as the active supersession.

Do not delete history merely to make the list look cleaner.

## 3. Lightweight same-session portfolio check

Every **material** new owner idea triggers a small planning pass in the same session. This is intake/reconciliation, not implementation authorization.

Record or determine:

- **Priority:** P0 / P1 / P2 or the product-family equivalent already in use.
- **Canonical owner:** the module/system that should own the concept.
- **Dependencies:** what must exist or be proven first.
- **Overlap / supersession:** which existing idea, issue, feature or defect it touches.
- **Shared foundation:** whether an already-needed primitive can satisfy several ideas at once.
- **Planning position:** NOW / NEXT / LATER / BLOCKED.
- **Parallel class:** SAFE_PARALLEL / SERIAL_CANONICAL_OWNER / INTEGRATION_ONLY / DEPENDENCY_BLOCKED.
- **Roadmap effect:** whether it changes the current combined phase or should wait.
- **Acceptance evidence:** what would prove the work is actually complete.

Always ask:

> Can this be implemented through an already-needed canonical owner or shared foundation so several requirements are unlocked once, without creating a second implementation?

The answer should prefer reuse/consolidation over feature-local copies.

## 4. Planning position vocabulary

These labels organize the portfolio. They **do not grant authority**.

| State | Meaning |
|---|---|
| **NOW** | On the current critical path or already-authorized campaign. Must still be supported by `EXECUTION_PLAN.md`. |
| **NEXT** | Dependency-ready or nearly ready; the next sensible work once current prerequisites/claims clear. |
| **LATER** | Wanted and preserved, but not on the current path. |
| **BLOCKED** | Waiting on a named dependency, owner decision, credential, evidence, or canonical-owner work. |
| **PAUSED** | Explicitly paused by the owner; do not resume without a later owner instruction. |
| **DONE** | Implemented and verified to the evidence standard named by the canonical record. |
| **REJECTED / NOT PLANNED** | Deliberately not doing it; keep the reason so it is not re-litigated from scratch. |

Legacy status words in older planning records remain historical evidence. Do not mass-rewrite old rows just for vocabulary consistency. Normalize an item when it is next touched/reconciled.

## 5. Authorization is a separate axis

A planning state is not permission to build.

Use `docs/EXECUTION_PLAN.md` for the authority question:

- **AUTHORIZED NOW**
- **NOT AUTHORIZED**
- **COMPLETE / VERIFIED**
- **OWNER ACTION REQUIRED**

An item may be `NEXT` while still `NOT AUTHORIZED`.

An issue, this document, the intake ledger, a branch, or a model's confidence can never silently promote work into authorized implementation.

## 6. Parallel-work classification

Parallel work is encouraged when it is genuinely independent and discouraged when it creates competing canonical owners.

### SAFE_PARALLEL

Use when all are true:

- independent canonical owners or clearly disjoint files;
- no unresolved dependency between the units;
- one writer per path/canonical concept;
- acceptance can be tested independently;
- integration order is known.

Examples: a frontend-only presentation unit and a source-research unit that consume a stable contract.

### SERIAL_CANONICAL_OWNER

Use when multiple ideas touch the same canonical owner, especially high-conflict owners such as:

- `src/api/data_contract.py`;
- `server.py`;
- canonical player/pick value;
- identity;
- trade simulation;
- scoring;
- shared persistence/schema.

Combine/resequence the requirements, then use one writer for that owner. Do not let several sessions create alternate implementations.

### INTEGRATION_ONLY

The implementation is complete or independent, but the next step requires the integration/traffic-control role to:

- reconcile current `main`;
- sequence dependent PRs;
- run final integration/release gates;
- merge/deploy.

Implementation agents freeze rather than chase every movement of `main`.

### DEPENDENCY_BLOCKED

A required upstream owner, permission, data source, owner decision, or evidence gate is missing. Name the blocker precisely and move to another dependency-ready unit instead of idling.

## 7. How multiple sessions should work

For meaningful parallel work, prefer:

```
coordinator / traffic control
    |
    +-- bounded lane A (one owner / one path set)
    +-- bounded lane B (different owner / path set)
    +-- bounded lane C (different owner / path set)
    |
    +-- read-only reviewer when warranted
    |
integration queue -> current-main reconciliation -> merge/deploy
```

There is no magic number of lanes. Use the smallest number that gains real calendar time. Two to four active implementation lanes is usually enough; more lanes are justified only when the ownership graph is genuinely independent.

Every lane gets:

- mission;
- canonical owner;
- exact paths;
- dependencies;
- writer/read-only role;
- acceptance tests;
- stop condition;
- work claim.

Before writing, check:

- `docs/WORK_CLAIMS.md`;
- open PR changed-file lists;
- remote branches;
- current execution authorization.

If a unit collides with a live claim, do not build around the owner. Mark only that unit blocked and continue with another dependency-ready unit.

## 8. Shared-foundation / combined-phase rule

Calculator has many historical issue numbers and owner decisions. Issue order is not automatically implementation order.

When several requests share:

- the same canonical owner;
- the same data model;
- the same API contract;
- the same UI primitive;
- the same source/provenance layer;
- the same test/deploy prerequisite;

plan the shared foundation once, then split implementation into small coherent PRs.

The canonical combined-phase sequencing overlay is:

`docs/BACKLOG_REPLAN_2026-09-10.md`

It is subordinate to the Master Product Plan and Execution Plan and does not authorize work.

## 9. Intake record shape for new material ideas

The compact owner ledger may stay compact, but the issue/spec should make these fields recoverable:

```
Owner request
Area / product family
Required outcome
Canonical owner
Priority
Planning position: NOW | NEXT | LATER | BLOCKED
Authorization: from EXECUTION_PLAN
Dependencies
Overlap / supersession
Shared foundation
Parallel class
Acceptance evidence
Status
Related issue/spec/PR
```

Do not force trivial one-line fixes to create a giant spec. Use proportional detail.

## 10. Cleanup rules

Orderliness means fewer conflicting truths, not fewer historical records.

- Do not create a second idea ledger.
- Do not duplicate an existing issue because its title differs.
- Do not copy an entire feature spec into the intake table.
- Use compact pointers from intake -> detailed record.
- Close/mark superseded records only when the successor is explicit.
- Preserve rejected ideas and their reasons.
- When a status is stale relative to merged code, fix the status rather than creating a new feature row.
- Prefer one canonical owner and many consumers.
- Keep implementation readiness separate from product desirability.

## 11. Where to look

| Question | Record |
|---|---|
| “Where do I put this idea?” | `docs/OWNER_REQUESTED_TODO.md` (use the shorthand **Calculator Ideas**) |
| “What exactly did the owner mean?” | GitHub issue + `docs/OWNER_PRODUCT_BACKLOG_SPEC.md` / feature-specific spec |
| “Does it already exist / what is its status?” | `docs/OWNER_FEATURE_INVENTORY.md` + current code/PR evidence |
| “Which canonical owner/foundation should handle it?” | `docs/MASTER_PRODUCT_PLAN.md`, architecture records, combined-phase replan |
| “Can several items be built together?” | this file + `docs/BACKLOG_REPLAN_2026-09-10.md` |
| “Is it authorized now?” | **`docs/EXECUTION_PLAN.md` only** |
| “Who is editing it?” | `docs/WORK_CLAIMS.md`, open PRs and branches |
| “How do branches/merges work?” | `ASSISTANT_COORDINATION.md` |
| “How does an agent operate?” | `AI_INSTRUCTIONS.md` + `docs/AGENT_OPERATING_SYSTEM.md` |

## 12. Owner experience

The owner may simply say:

> Add this to Calculator Ideas.

The agent is responsible for the repository bookkeeping. The owner should not have to choose between the intake ledger, issue tracker, feature inventory, manifest, backlog spec, or execution plan.

The agent should report what durable record was updated and whether the idea is NOW, NEXT, LATER, BLOCKED, PAUSED, or already covered — without turning capture into unauthorized implementation.

---

**Related:** issue #1412 · `docs/OWNER_REQUESTED_TODO.md` · `docs/PLANNING_DOCUMENT_STATUS.md` · `docs/MASTER_PRODUCT_PLAN.md` · `docs/EXECUTION_PLAN.md` · `docs/WORK_CLAIMS.md`.
