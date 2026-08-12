# Planning Document Status / Authority Map

**Status:** GOVERNANCE INDEX  
**Canonical front door:** `docs/MASTER_PRODUCT_PLAN.md`

This file exists so an assistant cannot reasonably mistake an old session capture, audit roadmap, or competitor TODO for the current product plan.

---

## ACTIVE CANONICAL RECORDS

| Document | Authority |
|---|---|
| `docs/MASTER_PRODUCT_PLAN.md` | Overall product direction, document precedence, unified feature families, public/private philosophy, removed scope |
| `docs/OWNER_FEATURE_INVENTORY.md` | Exhaustive feature/status/classification/dependency ledger |
| `docs/OWNER_PRODUCT_BACKLOG_SPEC.md` | Detailed owner product intent/methodology/UX for specified features |
| `docs/EXECUTION_PLAN.md` | Current sequencing and explicit next authorized scope |
| `docs/ARCHITECTURE_HANDOFF.md` | Architecture/canonical-owner state; may contain stale phase metadata and must not override `EXECUTION_PLAN.md` |
| `docs/WORK_CLAIMS.md` | Current concurrent-edit ownership only |

The Master Plan controls the hierarchy when these records appear to disagree.

---

## AUTHORITATIVE EVIDENCE / RESEARCH, NOT PRODUCT ROADMAPS

### `docs/master-site-audit/`

Authoritative for measured findings/evidence at the pinned code/input state each artifact names. Not authoritative for current phase completion or long-term product scope.

Examples:

- `docs/master-site-audit/REPAIR_ROADMAP.md` — historical root-cause plan produced from the audit;
- `docs/master-site-audit/NEXT_STEPS.md` — historical session resumption snapshot;
- evidence registry / verification artifacts — measurement records.

Use these to understand/prove defects. Use `EXECUTION_PLAN.md` to determine what to do now.

### `docs/competitive/`

Research record for OTC Fantasy, Play For Keeps, Dynasty Daddy, and related competitive audits/addenda. Approved concepts have been reconciled into the unified CE roadmap in `MASTER_PRODUCT_PLAN.md` and the owner inventory/spec hierarchy.

Competitor docs do not independently authorize implementation.

---

## HISTORICAL CAPTURE / SUPERSEDED AS INDEPENDENT ROADMAP

The following remain useful provenance but must not be treated as independent future-scope authorities after the 2026-08-12 reconciliation:

- `UNIMPLEMENTED_BACKLOG.md`
- `docs/OWNER_REQUESTED_TODO.md`
- `docs/OWNER_FEATURE_ADDENDUM_2026-08-11.md`
- `docs/SCOPE_COORDINATION_2026-08-11.md`
- `docs/master-site-audit/NEXT_STEPS.md`
- `docs/master-site-audit/REPAIR_ROADMAP.md`
- `docs/competitive/DYNASTY_DADDY_INTEGRATION_TODO.md`
- `docs/competitive/COMPETITIVE_EXPANSION_DYNASTY_DADDY_ADDENDUM.md`
- date-stamped owner-action / branch-disposition / session-handoff documents
- `docs/BLUEPRINT_EXECUTION.md` where it conflicts with newer owner scope
- competitor-specific checkpoint files
- old public-league phase documents where newer Public League Experience v3 requirements supersede them

Their durable requirements were reconciled into the canonical hierarchy. Historical measurements and rationales may still be cited.

If an old capture contains a requirement that cannot be found in the Master Plan / Inventory / Product Backlog Spec, that is **documentation drift**. Reconcile it into the canonical hierarchy before implementing it.

---

## OPERATING RULE FOR NEW DOCUMENTS

Do not create another permanent `MASTER_*`, `TODO_*`, `OWNER_*_ADDENDUM`, or competitor-specific implementation roadmap merely to record a new idea.

Instead:

1. extend the existing feature's detailed spec when possible;
2. update `OWNER_FEATURE_INVENTORY.md` when status/dependencies/classification change;
3. update `MASTER_PRODUCT_PLAN.md` only for material product-direction/family/governance changes;
4. update `EXECUTION_PLAN.md` only for sequencing/authorization changes;
5. temporary capture notes are allowed during active work but must explicitly say they are temporary and identify the canonical record into which they must be reconciled.

This prevents the repository from accumulating multiple plausible answers to “what are we supposed to build?”