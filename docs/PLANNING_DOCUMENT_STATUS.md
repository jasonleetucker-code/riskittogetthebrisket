# Planning Document Status / Authority Map

**Status:** GOVERNANCE INDEX
**Canonical front door:** `PRODUCT_PLAN.md` → `docs/MASTER_PRODUCT_PLAN.md`
**Last reconciled:** 2026-08-18 (V1 completion contract registered; owner V1 sprint authorization)

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
| `docs/C_SERIES_EXECUTION_MAP.md` | **The bounded-unit decomposition of the manifest.** Answers "what are the executable units, in what order, owned by whom, proven how". Decomposition only — it authorizes nothing; `EXECUTION_PLAN.md` alone does |
| `docs/EXECUTION_PLAN.md` | **The ONLY record of current sequencing and explicit next authorized scope** |
| `docs/VERSION_1_COMPLETION_CONTRACT.md` | **The V1 completion denominator and status ledger.** Answers "what must be true for V1 to be complete, and how much of it is proven". Classifies scope; authorizes nothing — `EXECUTION_PLAN.md` §0 alone does |
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
- `docs/OWNER_FEATURE_ADDENDUM_2026-08-29_BEST_BALL_ROSTER_UTILITY.md` — **owner-approved scope, issue #1173,
  owner decision 2026-08-29.** A roster-conditional dynasty best-ball utility layer for Analyze Trade
  (`F(R) = E[optimal legal weekly lineup score | R, exact league rules]`; Best-Ball Lineup Impact, Lineup Entry
  Probability, Usable Production/Redundancy, Depth Insurance Value, Roster Spot Shadow Value,
  Consolidation/Diversification classification) that must reuse canonical exact lineup/assignment machinery and
  must never overwrite standalone canonical player value. Per the addendum's own §8, reconciliation into
  `docs/OWNER_REQUESTED_TODO.md`, `docs/OWNER_FEATURE_INVENTORY.md`, the scope manifest and
  `docs/EXECUTION_PLAN.md` is deliberately deferred until the normal planning/authorization workflow schedules
  implementation — not yet done.
- `docs/trade/TRADE_GENERATION_PREFERENCES_AND_REFINEMENT_SPEC.md` — Best Trade to Send Each Team, persistent personal protection, LOCK/EXCLUDE, the shared constraint owner *(from PR #835)*
- `docs/TRADE_CALCULATOR_MARKET_EVIDENCE_EXPANSION_SPEC.md` — TC-01…TC-30, the mature-calculator end-state gate *(from PR #816)*
- `docs/trade/HISTORICAL_TRADE_REPLAY_AS_OF_ANALYSIS_SPEC.md` — three lenses, no-hindsight rule, fidelity taxonomy *(from PR #816)*
- `docs/TRADE_HISTORY_AGING_SPEC.md` — Current Grade / At-the-Time Grade / How It Aged *(from PR #809)*
- `docs/MARKET_TRADE_LEDGER_ACTIONABILITY_SPEC.md` — CE-01; **carries the only third-party data-use permission record in the repository, at §19.2** *(from PR #809)*
- `docs/trade/ANALYZE_TRADE_TODO.md`, `docs/trade/MC_AUDIT_TODO.md`, `docs/trade/SECOND_OPINIONS_TODO.md`, `docs/trade/TRADE_DECISION_SYNTHESIS_PLAN.md` — partially resolved working records

### Later 2026-08-14 trade addenda — binding, and superseding

These landed on the planning PRs while the post-B reconciliation was being written. They are the newest owner
intent in the repository and win over anything older they contradict.

- `docs/OWNER_FEATURE_ADDENDUM_2026-08-14_TRADE_FINDER_POSTURE_AWARE_PICKS.md` +
  `docs/trade/TRADE_FINDER_POSTURE_AWARE_PICKS_ADDENDUM_2026-08-14.md` — **#841. Withdraws the generated-trade
  `no draft picks` rule.** Picks are valid when both teams' strategic positions make them mutually beneficial,
  never as filler. → manifest `C7-PICKGEN-01`
- `docs/OWNER_FEATURE_ADDENDUM_2026-08-14_TRADE_CONTEXT_AND_TOPOLOGY.md` +
  `docs/trade/TRADE_CONTEXT_AND_TOPOLOGY_SUPERSESSION_2026-08-14.md` — **#841/#842. Withdraws the
  exact-equal-player-count rule** in favour of `abs(players_A − players_B) <= 1` with picks excluded from the
  count, and establishes the shared **Use Team Context** toggle, ON by default. → `C3-TOPO-01`, `C3-CTX-01`
- `docs/trade/ANALYZE_TRADE_COMPETITIVE_POSTURE_ADDENDUM_2026-08-14.md` — **#840.** PUSH / RETOOL / REBUILD /
  HOLD posture from canonical evidence. → `C7-POST-01`
- `docs/trade/ROSTER_CAPACITY_FORCED_DROP_TRADE_ANALYSIS_ADDENDUM_2026-08-14.md` — **#843.** Evaluate against the
  final legal post-trade roster, never the intermediate over-limit state. → `C3-CAP-01`
- **#839 Canonical Meaningful Roster Core** (universal `ceil(1.5 × real starter demand)` rule, Superflex counted
  as real QB demand) is recorded in `docs/OWNER_REQUESTED_TODO.md` and → `C2-CORE-01`

### Valuation, sources, seasonal
- `docs/MATH_MODEL_CALIBRATION_POLICY_2026-08-15.md` — **binding owner methodology refinement.** Preserve the canonical consensus board as champion; classify consequential tunables as MEASURED / MECHANICAL / PRIOR; calibrate future-pick discounts and pick distributions in C1, roster/replacement/core/Young-Core math in C2, trade fairness/consolidation/Monte-Carlo math in C3, TE-demand mapping under existing #785, and require a C10 prior census. It refines existing manifest rows and authorizes no implementation.
- `docs/PROJECTION_ENSEMBLE_PLAN_2026-08-15.md` — **binding owner projection-source/methodology refinement, issue #854.** Build a multi-source weekly/ROS/full-season projection evidence layer for offense and IDP; initial desired families are CBS, NFL Fantasy, FantasyPros, DraftSharks, Mike Clay/ESPN and IDP Show where applicable; rescore raw projected football stats through exact league scoring; preserve source lineage/independence; archive forecasts before outcomes; backtest simple family-level ensembles before learned weighting; keep the entire lane separate from canonical dynasty value. It maps primarily to `C5-ROS-01` and authorizes no implementation.
- `docs/MULTI_FORMAT_SOURCE_NORMALIZATION_SPEC.md` *(#809)*
- `docs/REDRAFT_ROS_INTELLIGENCE_SPEC.md` *(#809)*
- `docs/PLAYER_IMPACT_WAR_MVP_SPEC.md` — **its §7 supersedes the player-MVP eligibility gate** *(#816)*
- `docs/PLAYOFF_PREDICTOR_SPEC.md` *(#809)*
- `docs/CANONICAL_WEEKLY_POWER_RANKINGS_SPEC.md` *(#809)*
- `docs/GAME_DAY_PROBABILITY_SPEC.md` *(#809)*
- `docs/faab-model.md`, `docs/FAAB_MARKET_SIGNAL_NORMALIZATION_2026-08-14.md` — **binding, issue #830, decisions 56–65**
- `docs/perfect-draft.md`

### Roster intelligence
- `docs/OWNER_FEATURE_ADDENDUM_2026-08-18_FLEX_STARTER_ASSIGNMENT.md` — **binding, issue #899, owner decision
  2026-08-18.** FLEX is an ASSIGNMENT RULE deciding which players enter the meaningful-roster value pool, not a
  separate sortable Team Strength position. Supersedes the older "multiplied dedicated cores first, FLEX from the
  leftovers" wording: actual starter assignment (dedicated → FLEX → SF → IDP FLEX) comes first, reserve/depth
  demand second, and every player counts at most once. Reconciled into the Master Product Plan, the Owner
  Requested TODO and its spec index, the Feature Inventory, the Scope Manifest, the Zero-Loss Traceability record,
  the directive reconciliation and the Execution Plan, as the addendum itself requires
- `docs/OWNER_FEATURE_ADDENDUM_2026-08-14_AGE_VALUE_PORTFOLIO.md` — **binding, issue #838, owner decision
  2026-08-14.** Roster Age-Value Portfolio and the Young Core Index. Reconciled into the Master Product Plan,
  the Feature Inventory, the Product Backlog Spec and the Scope Manifest (`C2-AGE-01`…`C2-AGE-03`,
  `C7-AGE-01`) by the post-B reconciliation, as the addendum itself requires

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

### `docs/C_SERIES_DIRECTIVE_RECONCILIATION_2026-08-17.md`
The 2026-08-17 owner-directive → manifest-row proof, and the **owner methodology authority**
record: where two owner records could be read as disagreeing, which one governs and on what
evidence. Authoritative for the meaningful-roster-core, FLEX, KTC-VA and future-pick-decay
dispositions, and for the restated `X-02` / `X-07` rejections. It authorizes nothing.

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

## 6. THE THREE PLANNING PULL REQUESTS — ALL CLOSED

**All three are CLOSED, not merged.** Verified against GitHub 2026-08-17: #809 closed
2026-08-15T02:53:35Z, #816 closed 02:53:57Z, #835 closed 02:54:17Z — none merged, all three
`mergeable_state: dirty`. This section previously read *"All three remain open and untouched…
evidence until the owner approves the post-B reconciliation"*; that approval landed (PR #845,
merge `6d9640c7`) and the PRs were closed two minutes apart the same night.

**Nothing was lost, and that is the point.** Their content had already been **promoted to `main`**
before closure, which is exactly what traceability criterion 6 demands — *"it cannot disappear if
an old PR is later closed"*. Had the reconciliation merely cited these branches, closing them
would have destroyed the newest owner intent in the repository.

| PR | content | state |
|---|---|---|
| #809 | 15 detailed specifications | **CLOSED unmerged 2026-08-15.** Content on `main` |
| #816 | 9 owner-intent documents + 3 governance rewrites | **CLOSED unmerged 2026-08-15.** 9 documents promoted; the governance rewrites deliberately not imported — importing them would have regressed the authorization record, deleted the CLAUDE.md runbook and flipped the CE namespace. T-NEW-18/T-NEW-19 were promoted to `OWNER_REQUESTED_TODO_SPEC_INDEX.md` before closure |
| #835 | Best Trade / protection / LOCK-EXCLUDE | **CLOSED unmerged 2026-08-15.** Spec promoted and cross-referenced |

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