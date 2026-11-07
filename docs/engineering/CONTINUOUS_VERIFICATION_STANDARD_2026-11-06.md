# Continuous Feature-Intent Verification and Regression Standard — owner, 2026-11-06

**Status:** permanent, model-neutral engineering/quality standard for all *authorized* Chase Upside / Risk It To Get The Brisket work.
**Authority:** owner requirement for how completed and future work is verified. This document does **not** create new product scope, authorize a methodology change, grant deployment or merge authority, or override `docs/EXECUTION_PLAN.md`, active owner decisions, branch/file claims, the L0–L3 Agent OS validation workflow, or the stricter L0–L6 sitewide remediation/release gates.
**Canonical process owner:** `docs/AGENT_OPERATING_SYSTEM.md`; this standard supplies the detailed protocol and evidence schema. **Product-intent owners:** `docs/MASTER_PRODUCT_PLAN.md`, `docs/OWNER_PRODUCT_BACKLOG_SPEC.md`, feature addenda, owner decisions. **Historical/operational evidence:** live code, CI, API, production, fixtures and evaluation results. Existing `docs/engineering/ENGINEERING_RELIABILITY_PRIORITIES_2026-09-06.md` and `docs/owner/SITEWIDE_REMEDIATION_DIRECTIVE_2026-11-06.md` remain additive, not superseded.

## 1. Owner's outcome

A feature's existence, a green test suite, a rendered page or a plausible number is **not** proof that it does what the owner intended. Every material newly built or substantially changed capability must have traceable, independently testable intended behavior and maintain that behavior across future releases. The initial sitewide investigation must apply the same method retrospectively to existing features, without assuming all recorded features are shipped or every historical document is still current.

Distinguish and record these different verdicts:

1. **Exists / reachable:** is the code on a live execution path with the correct feature flag, audience, route and authorization?
2. **Intent conformance:** does implementation match the *latest authorized* owner contract, including edge cases and negative cases?
3. **Deterministic correctness:** do formulas, invariants, state transitions and data contracts produce expected outputs with independent test oracles?
4. **System integration and user journey:** do source → normalization → canonical model → API → frontend, persistence, authentication, privacy and device flows hold together?
5. **Operational resilience:** do realistic concurrency, load, failures, timeouts, stale sources and recoveries behave acceptably?
6. **Decision quality / model skill:** does any predictive or recommendation mechanism beat relevant baselines on legitimate, point-in-time, out-of-sample data? This is **not** established by passing unit tests.

Do not collapse these into a single “working” checkbox. Use `VERIFIED`, `FAILED`, `PARTIAL`, `UNVERIFIED`, `BLOCKED`, `NOT_APPLICABLE`, or `DEFERRED_BY_AUTHORITY`, scoped by surface, data, environment, git SHA, and evidence. Production verification and model promotion require their own independent evidence.

## 2. Intent-to-code / code-to-intent two-way census

For the authorized first baseline audit and on every material future feature:

- Inventory routes, major components, endpoints, workers/jobs, feature flags, data sources, persistence, reports and outputs using **current live execution paths**, not names alone.
- For each feature, link its latest controlling owner decision, spec/acceptance case, canonical owner, code path, tests, runtime flag and deployment status. Resolve superseded or conflicting records explicitly; unknown remains unknown.
- Map each intended requirement to implementation and to an executable validation case (including the *absence* of forbidden behavior). In the reverse direction, map implemented behaviors that lack authorization or a consumer; classify rather than deleting on sight.
- Identify missing, dead, hidden, intentionally OFF, obsolete, duplicate, unused, shadow, read-only, unmerged, and historically superseded work distinctly. A flag-off or externally invoked entry point is not automatically dead code.
- Apply existing sitewide remediation CW identifiers and registries, owner feature inventory and completion dashboard. **One finding = one canonical issue/work item**; do not create a competing completion denominator or second remediation roadmap.
- Preserve evidence references (requirements path + clause/decision, current SHA, file/function or route, test + fixture, environment, last verified date, PR/issue, resulting verdict and remaining gap). Unknown verification is never “passed.”

Suggested per-feature row: `Feature ID | intended behavior/owner contract | live entry point + flag | canonical owner | required tests/oracle | actual observed behavior | environment/SHA | verdict | gap/root cause | issue/PR | owner/residual gate`.

## 3. Minimum verification portfolio

Use the smallest sufficient set for each risk-bearing behavior; a blanket demand for every test technique on every PR is counterproductive.

- **Static / unit / contract:** lint, formatter, type/shape, pure formula cases, boundary conditions, exact league scoring and lineup constraints, API request/response shape and backward compatibility.
- **Regression:** retain a deterministic reproducer for each fixed defect. Tests should fail on the old faulty code and pass on the corrected code whenever feasible; do not simply adjust expected results to match the implementation.
- **Property, metamorphic and differential:** invariants including missing ≠ zero, stale ≠ current, no confidence increase on evidence loss, valid legal lineup assignments, deterministic repeatability, ordering invariance, conservation/no double counting, monotonicity where justified, and cross-implementation equivalence where contracts require it. Compare to independent reference implementations, frozen known-answer examples or host-scoring truth as appropriate.
- **Integration and E2E:** full data lineage, auth/tenant boundary, frontend/backend contract, feature flags, user interactions, browser/device (including WebKit/mobile where relevant), error states, accessibility and real authenticated workflows without exposing private data.
- **External data drift/replay:** sanitized immutable fixtures, source provenance/as-of, parser replay, unavailable/stale/partial input; no real private tokens or unlicensed data in tests.
- **Security, privacy and reliability:** authorization, IDOR, injection, SSRF, secret leakage, rate limits, caching/tenant isolation, timeouts, fallbacks, concurrency, resource bounds, idempotency and restoration where relevant.
- **Load/stress/soak:** reproducible realistic scenarios, baseline metrics, production-like safe environment, explicit traffic ceiling, error/latency/CPU/memory budgets, graceful degradation and cleanup; **do not load-test live production without separately approved bounded safety controls**.
- **Predictive/model quality:** separate preregistered prospective or leakage-free historical backtests with frozen inputs, timestamp/cutoff discipline, missingness strata, uncertainty, baselines, sample sizes, utility/accuracy, challenger vs incumbent, rollback and promotion restrictions. Never conflate mathematical correctness with predictive skill.

Use established tests, fixtures, commands and CI infrastructure first; do not build a second test framework or a second model evaluator if the canonical one exists.

## 4. Permanent development loop (every material feature, bug fix and major refactor)

**Before coding**
1. Inspect current main, execution authorization, owner requirements, active claims, prior findings and the live pipeline.
2. Write a concise acceptance contract for the affected behavior: positive, negative, boundary, missing/stale and failure cases; numerical tolerance and provenance if applicable; real route/flag/user scope.
3. Link intended requirements to tests; choose independent expected results or oracle (hand-calculated example, external host source, trusted separately coded reference, frozen snapshot, historical ground truth). When independence cannot be proved, mark the oracle provisional.
4. Record baseline behavior and an existing-regression check; for a bug, create a reproducing test first where practical.

**While coding**
5. Run existing L0 continuously and relevant L1 after coherent changes; add focused tests and preserve neighboring behavior.
6. Fix root causes at the canonical owner, not page-local symptoms; avoid unnecessary duplicate models and test-only production logic.
7. If identifying unrelated defects or unowned code, log/dedupe them and stay within authorized/file-claimed scope; do not silently expand the change.

**Before integration and release**
8. Run required exact-tree L2 and release L3 (or the controlling campaign's stricter L0–L6 gates), independent review and relevant negative/security/E2E/performance checks. Never mute, skip, weaken or delete a failing gate to attain green.
9. Include a concise PR **feature verification receipt**: intent/spec version; affected feature IDs and canonical paths; baseline and corrected behavior; positive/negative/edge case coverage; commands + actual results; known gaps and fixtures; risk/rollback; flagged vs active; independent review; promotion/deployment status. Separate `TESTED_IN_PR`, `MERGED`, `DEPLOYED`, `VERIFIED_IN_PRODUCTION`.
10. Retain regression fixtures and tests in repo so later changes automatically run the appropriate suite; flag coverage gaps as unresolved and do not claim universal coverage.

**After deployment**
11. Confirm the served artifact/SHA, flag state, observability, key safe smoke flows, private/public boundaries and numerical/dataset invariants; report unresolved production-only checks explicitly.
12. Route newly discovered defects or improvement hypotheses back to the existing owner intake / canonical remediation work item. Prevent recurrence through tests and monitoring, not merely a one-time manual audit.

## 5. Cadence and CI ownership

- **Per code change:** L0 + affected L1; new bug/behavior tests run locally.
- **Every integration PR:** existing L2 on the exact candidate tree, independently reviewed; path-aware only when proven safe by the canonical CI change-scope owner.
- **Every production candidate:** L3 and any stricter release gate. No change to deploy authority or active launch conditions.
- **Scheduled, when explicitly authorized:** bounded nonproduction E2E canaries, dependency/security checks, replay/drift and performance runs, targeted mutation/property suites, production-safe telemetry review, and ongoing feature-to-intent coverage reconciliation. Start with low-cost/high-value schedules; add jobs only after checking CI cost, data rights, secrecy and reliability. Historical evidence must include a time window, not a false claim of current health.
- **After each incident/defect:** preserve a permanent, failing-before/fixed-after regression test if feasible.
- **At meaningful product checkpoints:** reconcile actual feature status, orphaned behaviors and unverified features with the canonical owner inventory and existing completion ledger; no inflated test-coverage metric that confuses line coverage with contract coverage.

## 6. Refactoring and dead-code safety

Use static references plus runtime traces, build entrypoints, indirect imports, dynamic dispatch, flags, jobs, deployment scripts and external consumers before declaring code dead. Inventory callsites and impact; classify `PROVEN_UNUSED` / `FLAGGED_OFF_RETAIN` / `SHADOW_RESEARCH` / `SUPERSEDED` / `UNKNOWN_CONSUMER`. Remove only proven-unused code within authorization, with tests, dependency review and a reversible small PR; never delete protected historical datasets, rollback paths, test fixtures or owner-parked work merely for tidiness. Simplification is a measured benefit, not a license for feature loss.

## 7. Initial audit deliverables and stop conditions

Work in the existing sitewide remediation program, respecting its higher-priority deploy blockers, perishable capture and security tasks. Produce:
- a source-backed complete-enough feature census with explicit unverified/unreachable rows;
- requirement → execution path → tests → result → finding/PR traceability;
- repeatable exact commands and measured baseline for test quality, flakiness, runtime, coverage and critical-flow completeness;
- a ranked deduplicated backlog of specific **reproduced** defects, missing test oracles, dead/duplicate candidates, and performance/predictive hypotheses, using the existing CW portfolio rather than an independent shadow backlog;
- incremental fixes and durable regression tests where in scope, plus a CI schedule/owner plan;
- clear `VERIFIED / PARTIAL / UNVERIFIED / BLOCKED` status after each accepted PR, independent review and production evidence.

Never promise every feature is proved merely because automation finishes; never mark a contract `VERIFIED` without a concrete positive and relevant negative observation. Stop or escalate only on a genuine owner-reserved methodology/launch decision, unavailable access, overlapping active file claim, or an unsafe load/promotion action. Continue independent authorized work.

## 8. PR verification receipt check (CW-53, owner directive 2026-11-07)

`.github/workflows/pr-verification-receipt.yml` runs `scripts/check_pr_verification_receipt.py` on every PR
(opened / edited / synchronize / reopened / ready_for_review) and enforces §4 step 9.

- **Material** = the diff touches `src/`, `server.py`, `Dynasty Scraper.py`, `frontend/` (excluding
  `frontend/__tests__/` and `*.test.*` / `*.spec.*`), `deploy/`, `config/`, `.github/workflows/`, or `scripts/`
  (excluding `scripts/research/`). A material PR must have a `## Feature verification receipt` section in which every
  field of `.github/pull_request_template.md` is filled — not empty, not template placeholder text. A field that does
  not apply may say `n/a — <reason>` (a reason of a few words is required). The State field must name one of
  `TESTED_IN_PR / MERGED / DEPLOYED / VERIFIED_IN_PRODUCTION`.
- **Not material** (pass without a receipt): docs/markdown-only, `data/`, `exports/`, `CSVs/`. Tests-only changes get an
  advisory notice, never a failure.
- **Exempt authors**: `dependabot[bot]` and `github-actions[bot]` (automated refresh commits); the report says so.
- **Fixing a red check**: edit the PR body to complete the listed fields; the check re-runs within seconds. No push needed.
- **Status**: this is *not yet* a branch-protection required check. Making it required is a repository-settings action
  reserved for the owner. Until then the Integration Authority treats a green receipt check as required for material PRs.
