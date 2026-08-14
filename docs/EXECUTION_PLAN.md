# Risk It To Get The Brisket — Current Execution Plan

**Status:** CANONICAL SEQUENCING / AUTHORIZATION RECORD  
**Last reconciled:** 2026-08-13  
**Companions:** `docs/MASTER_PRODUCT_PLAN.md`, `docs/OWNER_FEATURE_SPEC_RECONCILIATION_2026-08-13.md`, `docs/OWNER_MASTER_FEATURE_BACKLOG_2026-08-13.md`, `docs/C_SERIES_REPLAN_AND_COMPLETION_CONTRACT.md`, `docs/TRADE_CALCULATOR_MARKET_EVIDENCE_EXPANSION_SPEC.md`

This file answers **what work should happen next**. It does not define long-term product intent; that lives in the Master Product Plan, Feature Inventory, Product Backlog Spec, owner feature-spec reconciliation, and feature-specific binding addenda.

> A feature being approved in the long-term plan does **not** authorize beginning it here.

---

# 1. CURRENT FOUNDATION PROGRAM

## Completed / accepted

### B4 — W30-F023 percentile-tail saturation

- VERIFIED FIXED / ACCEPTED.
- Canonical tail saturation boundary: **904**.
- PR #805 merged.
- No Hill promotion/refit authorized or performed.
- Do not reopen B4 absent new evidence.
- Future nonblocking safeguard: advisory detection if effective observed source rank exceeds the canonical boundary, rather than silently accumulating 905+ saturation.

### B5 — W06 canonical player identity

- PR #806 merged.
- W06-F001 fixed — ghost-row creation path.
- W06-F004 fixed — ID override precedence/merge semantics.
- W06-F007 fixed — directory index hoisted for batch resolution.
- W06-F009 fixed — SleeperId alias-token handling.
- W06-F002 refuted by executable evidence; retired near-name rule must not be re-enabled merely to satisfy the old finding.
- Residual explicitly noted by B5: ghost-row repair takes effect on the next scrape; do not falsely claim a historical/current board changed until that path actually runs.

---

# 2. NEXT AUTHORIZED FOUNDATION SCOPE

## B6 — League configuration / league-context correctness

**Scope chosen by owner:**

- **W18-F001** — scoring-profile identity is hand-authored rather than validated/derived from actual league scoring settings.
- **W18-F002** — cross-league Sleeper overlay can combine requested-league teams with another league's scoringSettings/rosterPositions/leagueSettings and incorrectly stamp `sleeperDataReady:true`.

Treat these as one league-configuration root-cause family.

Required posture:

1. reproduce both defects on current code/current host data;
2. establish RED coverage for the actual erroneous contracts;
3. identify the canonical owner of league scoring/config identity;
4. repair the root cause, not specific league-name exceptions;
5. scoring-profile equivalence must reflect actual scoring configuration, not merely matching strings;
6. no requested-league Sleeper block may contain another league's config fields and claim ready;
7. validate every configured league against its own host settings;
8. measure downstream behavior on `/api/data`, rankings/overrides, roster/team consumers, trade/waiver/draft contexts as relevant;
9. run normal broad gates and exact-head CI;
10. STOP for owner review.

**Explicit B6 non-scope:** W18-F003 realized-points scoring correctness. Do not mix the scoring-engine repair into B6.

---

# 3. QUEUED NEXT — NOT AUTOMATIC AUTHORIZATION

## B7 — Realized-points correctness

W18-F003 belongs here as an independent scoring-engine root cause. It has an NFL Week 1 urgency and should follow B6 without unnecessary delay, but B6 completion does not itself authorize starting B7.

Known W18-F003 evidence to revalidate on current HEAD includes:

- reception-distance scoring rules not represented correctly;
- renamed nflverse mappings for interception/sack/fumble-lost data;
- missing kicker scoring;
- requirement that every nonzero league scoring key be mapped or explicitly declared uncoverable rather than silently scored as zero.

Also reconcile the owner-requested individual special-teams requirement (`kr_yd`, `pr_yd`, supported `st_*`) when the realized-scoring work reaches the appropriate scope. Player special-teams scoring and DST `def_*` scoring must remain distinct.

## Subsequent foundation direction

The broader dependency direction remains:

- **B8** security/public-boundary correctness;
- **B9** canonical individual 1–9999 value-scale semantics/normalization;
- **B10** source independence / anti-circularity / leave-one-out;
- **B11** confidence semantics.

Exact B-phase boundaries must be confirmed against current findings and owner authorization at each checkpoint rather than inferred from this shorthand.

## HARD GATE AFTER B11 — REPLAN C BEFORE IMPLEMENTATION

**Binding owner decision:** there is **no automatic B11 → C1 transition**.

When B11 is completed/accepted:

1. **STOP. Do not begin C1.**
2. Put Claude Code in **Plan Mode only**.
3. Re-read the actual repository/product/production state at that time, including all current, partial, planned, newly discussed, and owner-requested features added during B.
4. Read and apply `docs/C_SERIES_REPLAN_AND_COMPLETION_CONTRACT.md` in full.
5. Build an exhaustive **C-Series Scope Manifest** before ordering phases. The manifest must reconcile every approved feature from the Master Product Plan, Feature Inventory, Product Backlog Spec, owner reconciliation + appendix, owner to-do/index, the **100-item Owner Master Feature Backlog**, feature-specific specs, Premium design records, the Trade Calculator/Market Evidence expansion, CE backlog, and every later owner addendum.
6. Completely **rewrite the C-series execution plan** rather than inheriting the old shorthand C ordering.
7. Build the dependency graph first: canonical owners, prerequisites, shared root causes, consolidation/retirement opportunities, parallelizable lanes, migrations/backfills, data/licensing constraints, performance budgets, rollout/rollback, and safe PR boundaries.
8. Prefer shared foundations that unlock many consumers over page-by-page implementation. Do not build duplicate value, pick, history, lineup, package, probability, analyst, or recommendation engines for convenience.
9. Explicitly honor the hard owner requirement that **every valid supported draft pick through 2029 has a finite non-missing canonical value** and cross-surface parity before C can complete.
10. Explicitly include `docs/TRADE_CALCULATOR_MARKET_EVIDENCE_EXPANSION_SPEC.md` in C scope, including real-trade database/comparables, amount-to-even/equalizers, analytics, sharing, and mobile parity.
11. For every material C feature/phase, specify in detail: user outcome, canonical owner, inputs/outputs, method, identity/provenance, uncertainty/confidence, freshness/historical semantics, degraded behavior, UI/UX, mobile/desktop behavior, accessibility, performance, dependencies, non-scope, migrations/backfills, tests/backtests, exact-head CI, deployment, production verification, observability, rollback, and exact done criteria.
12. Optimize the execution plan for **critical-path efficiency**: parallelize only genuinely independent/non-overlapping work, use CI/deploy wait time for read-only reconnaissance, and avoid unstable UI work that would be rebuilt after a shared contract changes.
13. Produce one proposed canonical **C-Series Execution Plan** with an explicit dependency DAG, PR/deploy boundaries, parallel lanes, and final completion audit.
14. Jason + ChatGPT review that proposal and may reorder, combine, split, expand, or reject methodology.
15. Only explicit owner approval authorizes C1 implementation.

The current shorthand C direction—Team Strength, Team Weakness, Acquisition History, historical value snapshots, package methodology, stable pick identity, etc.—is a dependency hint only until this hard-gate replanning pass occurs.

### C execution / deployment standard after approval

Once the owner approves the post-B C plan, C should proceed continuously without routine permission pauses **provided** each phase stays within the approved boundaries and no genuine owner decision is encountered.

Use one coordinated program, **not one giant PR**:

- RED/evidence → canonical implementation → focused tests → broad regression/backtest as applicable;
- exact-head CI on the final candidate SHA;
- merge only the validated head;
- deploy through the normal production path;
- production smoke/E2E/data-contract verification proportional to risk;
- mobile/desktop proof for relevant user-facing features;
- record completion evidence and rollback path;
- then allow dependent phases to treat the capability as complete.

A page rendering or a unit test passing is not completion. A feature must be real-data connected, reachable, correct, performant, deployed, and production-verified.

### C completion hard gate

Before declaring C complete, run the dedicated completion audit in `docs/C_SERIES_REPLAN_AND_COMPLETION_CONTRACT.md`.

There may be **no silent deferrals**. Every approved feature must be either:

- implemented, deployed, production-verified, and ready for confident use; or
- explicitly changed/removed/deferred by a new owner decision because a concrete external blocker makes implementation impossible or unsound.

Without explicit owner disposition, “planned later”, “mostly done”, “backend only”, “desktop only” where parity is required, “flagged off”, “mocked”, “unpriced”, “tests pass but production not verified”, and similar states are **not C-complete**.

Only after the final audit passes may Claude state:

**`C-SERIES COMPLETE — EVERY APPROVED FEATURE DEPLOYED, PRODUCTION-VERIFIED, AND READY FOR CONFIDENT USE`**

---

# 4. PRODUCT WORK THAT MUST NOT PREEMPT FOUNDATIONS

The following are approved future scope but are **not authorized merely by being listed**:

- Public League Experience v3 implementation;
- Brisket Honors / Awards & Honors v2 implementation;
- Market Trade Ledger / Real Trade Market Value;
- Pick Forecast / Canonical Owned Future Pick Projection & Valuation;
- complete canonical draft-pick values through 2029;
- mature Trade Calculator / real-trade database / comparable-trade / market-evidence expansion;
- Manager Scout;
- Command Center / Trade Desk / Portfolio;
- Analyst Intelligence podcast + YouTube expansion;
- Universal Player Profile expansion;
- Game Day Command Center;
- Share Renderer;
- PAR/Stats/ADP/Draft Room/Lineup Intelligence;
- Premium Sports Intelligence migration except when its explicit migration gate is satisfied and separately authorized;
- competitive CE-01–CE-21 expansion;
- large X analyst feed;
- adaptive source weighting.

They may be read during foundation work to avoid architectural contradictions, but not opportunistically implemented.

---

# 5. SAFE HOTFIXES / OWNER DEFECTS

Owner-requested live defects such as the Admin `fmtPassExpiry` crash, temporary-password end-to-end repair, Trade Calculator UX/correctness defects, public-League missing-data-as-zero defects, and narrow deployment/reliability follow-ups remain real work. Schedule them at a safe product-hotfix checkpoint or when one directly blocks the active phase; do not mix unrelated UI/product changes into a tightly scoped model/root-cause pass.

---

# 6. EXECUTION UPDATE RULE

At every owner-approved checkpoint:

1. update completed/accepted phase state here;
2. record the exact next authorized scope only after owner decision;
3. leave later approved product scope in `MASTER_PRODUCT_PLAN.md` and detailed owner specs rather than copying every implementation detail here;
4. never let a stale phase statement in `ARCHITECTURE_HANDOFF.md`, an old audit roadmap, or a session capture override this file;
5. if current code/evidence disproves this execution state, reconcile the document before beginning another phase;
6. when owner intent is more detailed than a shorthand backlog row, use `OWNER_FEATURE_SPEC_RECONCILIATION_2026-08-13.md`, `OWNER_MASTER_FEATURE_BACKLOG_2026-08-13.md`, `C_SERIES_REPLAN_AND_COMPLETION_CONTRACT.md`, feature-specific specs, and later owner addenda as the detailed intent layer.

This file should stay short enough that a new implementation session can understand the current sequence in minutes.
