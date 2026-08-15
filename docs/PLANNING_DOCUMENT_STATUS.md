# Planning Document Status / Authority Map

**Status:** GOVERNANCE INDEX
**Canonical front door:** `PRODUCT_PLAN.md` → `docs/MASTER_PRODUCT_PLAN.md`
**Last reconciled:** 2026-08-14 (post-B master reconciliation)

This file exists so an assistant cannot reasonably mistake an old session capture, an audit roadmap, or a
competitor TODO for the current product plan. **Every planning document in the repository must appear somewhere
below.** A document that appears nowhere is drift, and `scripts/check_planning_integrity.py` fails CI on it.

---

## 1. ACTIVE CANONICAL RECORDS

| Document | Authority |
|---|---|
| `docs/MASTER_PRODUCT_PLAN.md` | Overall product direction, document precedence, unified feature families, public/private philosophy, removed scope |
| `docs/C_SERIES_REPLAN_AND_COMPLETION_CONTRACT.md` | Zero-loss planning, execution discipline, the definition of done, and the completion standard for the C-Series |
| `docs/OWNER_FEATURE_INVENTORY.md` | Exhaustive feature/status/classification/dependency ledger |
| `docs/OWNER_PRODUCT_BACKLOG_SPEC.md` | Detailed owner product intent/methodology/UX for specified features |
| `docs/C_SERIES_SCOPE_MANIFEST.md` | **The exhaustive implementation/disposition census.** Answers "is this in scope, who owns it, what phase, what proves it done" |
| `docs/EXECUTION_PLAN.md` | **The ONLY record of current sequencing and explicit next authorized scope** |
| `docs/CE_REGISTRY.md` | **The only place a CE identifier is defined** |
| `docs/OWNER_REQUESTED_TODO.md` | **THE LIVE OWNER INTAKE LEDGER** — see §2 |
| `docs/ARCHITECTURE_HANDOFF.md` | Architecture / canonical-owner state; may contain stale phase metadata and must not override `EXECUTION_PLAN.md` |
| `docs/WORK_CLAIMS.md` | Current concurrent-edit ownership only |

The Master Plan controls the hierarchy when these records appear to disagree, per its §2 precedence rules.

**One nuance worth repeating:** live code or executable evidence can prove a *status* claim in any of these
documents stale — but implementation behaviour never overrides a newer *owner decision*.

---

## 2. OWNER INTAKE — one mechanism, stated once

**`docs/OWNER_REQUESTED_TODO.md` is the live intake ledger.** New owner instructions land there first. This is a
deliberate 2026-08-14 reclassification: the file was previously listed as historical/superseded while carrying
**65 binding owner decisions**, including the two newest binding decision sets in the repository. The governance
system was telling readers not to trust the file where the newest owner intent lived.

**The reconciliation workflow, in order:**

1. **Intake** — the instruction is written into `docs/OWNER_REQUESTED_TODO.md`. It is durable from that moment.
   If it needs more than a table row, it also gets a dated standalone spec, which **must** be registered in §3
   below in the same change.
2. **Canonical record** — it is reflected in the Feature Inventory (does it exist / what is its status) and, if
   it carries detailed behaviour, in the Product Backlog Spec or its own spec document.
3. **Manifest row** — it gets a row in `docs/C_SERIES_SCOPE_MANIFEST.md` with a canonical owner, a phase and
   completion evidence. **This is the step that makes it un-losable.**
4. **Authorization** — only `docs/EXECUTION_PLAN.md` may say it can be built, and only after an owner decision.

Steps 1–3 are documentation and may happen at any time. Step 4 is the gate.

**Enforced:** `scripts/check_planning_integrity.py` fails CI when a numbered owner decision in the intake ledger
has no destination in the Scope Manifest or the traceability document.

---

## 3. CANONICAL SUPPORTING SPECIFICATIONS

Detailed owner-approved behaviour. Binding within their subject; they do not authorize implementation.

### Trade
- `docs/trade/TRADE_GENERATION_PREFERENCES_AND_REFINEMENT_SPEC.md` — Best Trade to Send Each Team, persistent personal protection, LOCK/EXCLUDE, the shared constraint owner *(from PR #835)*
- `docs/TRADE_CALCULATOR_MARKET_EVIDENCE_EXPANSION_SPEC.md` — TC-01…TC-30, the mature-calculator end-state gate *(from PR #816)*
- `docs/trade/HISTORICAL_TRADE_REPLAY_AS_OF_ANALYSIS_SPEC.md` — three lenses, no-hindsight rule, fidelity taxonomy *(from PR #816)*
- `docs/TRADE_HISTORY_AGING_SPEC.md` — Current Grade / At-the-Time Grade / How It Aged *(from PR #809)*
- `docs/MARKET_TRADE_LEDGER_ACTIONABILITY_SPEC.md` — CE-01; **carries the only third-party data-use permission record in the repository, at §19.2** *(from PR #809)*
- `docs/trade/ANALYZE_TRADE_TODO.md`, `docs/trade/MC_AUDIT_TODO.md`, `docs/trade/SECOND_OPINIONS_TODO.md`, `docs/trade/TRADE_DECISION_SYNTHESIS_PLAN.md` — partially resolved working records

### Valuation, sources, seasonal
- `docs/MULTI_FORMAT_SOURCE_NORMALIZATION_SPEC.md` *(#809)*
- `docs/REDRAFT_ROS_INTELLIGENCE_SPEC.md` *(#809)*
- `docs/PLAYER_IMPACT_WAR_MVP_SPEC.md` — **its §7 supersedes the player-MVP eligibility gate** *(#816)*
- `docs/PLAYOFF_PREDICTOR_SPEC.md` *(#809)*
- `docs/CANONICAL_WEEKLY_POWER_RANKINGS_SPEC.md` *(#809)*
- `docs/GAME_DAY_PROBABILITY_SPEC.md` *(#809)*
- `docs/faab-model.md`, `docs/FAAB_MARKET_SIGNAL_NORMALIZATION_2026-08-14.md` — **binding, issue #830, decisions 56–65**
- `docs/perfect-draft.md`

### Public, storytelling, intelligence
- `docs/BRISKET_HONORS_ELIGIBILITY_SPEC.md` — **player-MVP gate superseded; Manager of the Year NOT superseded** *(#809)*
- `docs/UPSIDE_REPORT_WEEKLY_SHOWCASE_SPEC.md` *(#809)*
- `docs/UPSIDE_REPORT_PRESEASON_KICKOFF_EDITION_SPEC.md` — the Tuesday-before-Week-1 requirement and the immutable preseason baseline *(#809)*
- `docs/WEEKLY_REPORT_STUDIO_MANUAL_AI_ARCHITECTURE_2026-08-14.md` — **binding, issue #829, decisions 47–55**
- `docs/AI_FRONT_OFFICE_INTELLIGENCE_SPEC.md` — Ask Brisket, Roster Path Optimizer, Edge Alerts, Trade Liquidity & Market Depth, Negotiation Coach, League Truth *(#809)*
- `docs/SHARP_INSIDER_EXPERIENCE_PERFORMANCE_SPEC.md` *(#809)*
- `docs/sharp-roster-percentage/METHODOLOGY.md`

### Design, performance, policy
- `docs/PREMIUM_SPORTS_INTELLIGENCE_DESIGN_NORTH_STAR.md` — Direction A, the permanent visual direction *(#809)*
- `docs/GLOBAL_PERFORMANCE_STANDARD.md` — 1 s warm / 3 s cold / 2 s p95 / **5 s failure ceiling** *(#809)*
- `docs/COMPETITOR_REUSE_POLICY.md` — **design-pattern reuse only; grants no data rights** *(#809)*
- `docs/DESIGN-SYSTEM.md` — **STALE against live tokens**; see manifest `C0-PSI-01`

### Owner-intent reconciliation set *(all from PR #816)*
- `docs/OWNER_MASTER_FEATURE_BACKLOG_2026-08-13.md` — the 104-item discussion ledger. **A coverage/provenance ledger, explicitly NOT a second execution queue**
- `docs/OWNER_FEATURE_SPEC_RECONCILIATION_2026-08-13.md`
- `docs/OWNER_FEATURE_SPEC_APPENDIX_2026-08-13.md`
- `docs/OWNER_REQUESTED_TODO_SPEC_INDEX.md`
- `docs/PRODUCT_DIRECTION_SYNC_MANIFEST.md` — **its sync claims and checklist are false as written**; retained for its §7 global owner decisions

Every document above carries a `RECONCILIATION AMENDMENT` header recording what, if anything, was corrected when
it was promoted to `main`.

---

## 4. AUTHORITATIVE EVIDENCE / RESEARCH — NOT PRODUCT ROADMAPS

### `docs/POST_B_RECONCILIATION_2026-08-14.md`
The adjudication record for the two independent post-B audits, and the source of the owner-decision list.
Authoritative for *why* the plan is shaped this way; it authorizes nothing.

### `docs/C_SERIES_ZERO_LOSS_TRACEABILITY.md`
The source-entry → manifest-row proof. Authoritative for *where a requirement went*.

### `docs/master-site-audit/`
Authoritative for measured findings at the pinned code/input state each artifact names. **Not** authoritative for
current phase completion or long-term scope. `B_SERIES_COMPLETION_AUDIT.md` and `B_SERIES_EXECUTION_LEDGER.md`
are the authoritative record of B closure.

### `docs/competitive/`
Research record. Approved concepts are reconciled into `docs/CE_REGISTRY.md` and the owner hierarchy. Competitor
docs do not independently authorize implementation. Note `docs/competitive/COMPETITIVE_EXPANSION_ARCHITECTURE.md`
is referenced by `docs/ARCHITECTURE_HANDOFF.md` and **does not exist** — a dangling pointer, not a missing file.

### `docs/valuation/LEAGUE_AWARE_METHODOLOGY_REJECTION.md`
The record of a methodology evaluated for promotion and **rejected** on seven measured defects.

---

## 5. HISTORICAL CAPTURE / SUPERSEDED AS INDEPENDENT ROADMAP

Useful provenance. **Must not be treated as independent future-scope authorities.** Their durable requirements
are reconciled into the canonical hierarchy and mapped in `docs/C_SERIES_ZERO_LOSS_TRACEABILITY.md`.

- `UNIMPLEMENTED_BACKLOG.md` — **15 of its 56 items appear in no other source**; all are mapped (traceability §K)
- `docs/ROADMAP-competitor-parity.md` — *newly named here; it was a findable roadmap the index did not list*
- `docs/status/*.md` (20 files, March 2026) — including `priority-roadmap.md` and `remaining-work-inventory.md`, *also newly named*
- `docs/OWNER_FEATURE_ADDENDUM_2026-08-11.md` — verified fully absorbed
- `docs/SCOPE_COORDINATION_2026-08-11.md`
- `docs/master-site-audit/NEXT_STEPS.md`, `docs/master-site-audit/REPAIR_ROADMAP.md`
- `docs/competitive/DYNASTY_DADDY_INTEGRATION_TODO.md`, `docs/competitive/COMPETITIVE_EXPANSION_DYNASTY_DADDY_ADDENDUM.md`
- date-stamped owner-action / branch-disposition / session-handoff documents, specifically:
  `docs/OWNER_ACTION_AUDIT_2026-07-29.md`, `docs/BRANCH_DISPOSITION_2026-07-29.md`,
  `docs/BRANCH_DISPOSITION_2026-08-11.md`, `docs/CLAUDE_SESSION_AUDIT_HANDOFF.md`,
  `docs/CHASE_UPSIDE_RUN_LOG.md`, `HANDOFF.md`
- `docs/BLUEPRINT_EXECUTION.md` where it conflicts with newer owner scope
- old public-league phase documents superseded by Public League Experience v3

If an old capture contains a requirement that cannot be found in the canonical hierarchy **or in
`docs/C_SERIES_SCOPE_MANIFEST.md`**, that is documentation drift. Reconcile it before implementing it.

---

## 6. OPEN PLANNING PULL REQUESTS

**All three remain open and untouched.** They are evidence until the owner approves the post-B reconciliation.
Recommended disposition afterwards is in `docs/POST_B_RECONCILIATION_2026-08-14.md` §5.

| PR | content | status |
|---|---|---|
| #809 | 15 detailed specifications | **Content promoted to `main`.** Do not merge; do not close until the owner confirms |
| #816 | 9 owner-intent documents + 3 governance rewrites | **9 documents promoted; the governance rewrites deliberately not imported.** Do not merge — it would regress the authorization record, delete the CLAUDE.md runbook and flip the CE namespace |
| #835 | Best Trade / protection / LOCK-EXCLUDE | **Spec promoted and cross-referenced.** Still merges clean if the owner prefers its lineage on record |

---

## 7. OPERATING RULE FOR NEW DOCUMENTS

Do not create another permanent `MASTER_*`, `TODO_*`, `OWNER_*_ADDENDUM` or competitor-specific implementation
roadmap merely to record a new idea. Instead:

1. extend the existing feature's detailed spec where possible;
2. update `docs/OWNER_FEATURE_INVENTORY.md` when status, dependencies or classification change;
3. update `docs/C_SERIES_SCOPE_MANIFEST.md` when scope changes — **this is the step that prevents loss**;
4. update `docs/MASTER_PRODUCT_PLAN.md` only for material product-direction, family or governance changes;
5. update `docs/EXECUTION_PLAN.md` only for sequencing/authorization changes;
6. **register any new dated spec in §3 of this file in the same change**;
7. temporary capture notes are allowed during active work but must say they are temporary and name the canonical
   record into which they must be reconciled.

This prevents the repository from accumulating multiple plausible answers to "what are we supposed to build?"
