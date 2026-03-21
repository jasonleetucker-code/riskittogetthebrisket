# Priority Roadmap (Dependency-Ordered)

Date: 2026-03-19  
Purpose: execution order that minimizes runtime risk first, then unlocks blueprint expansion.

## Phase 0 - Immediate Stabilization (release safety first)

### 0.1 Fix League shell artifact authority
- Why: current workspace has untracked `Static/league/*`, which can mask deploy failures.
- Work:
  1. Decide artifact policy: tracked source files vs build-generated files.
  2. Enforce policy in CI/deploy verification.
  3. Update runtime/docs so authority is explicit and durable.
- Done looks like:
  1. `Static/league/index.html`, `league.css`, `league.js` provenance is deterministic.
  2. New clone + CI run still serves full League shell without local-only files.

### 0.2 Keep cross-device smoke as a hard release gate
- Why: route authority/public-access drift can silently return if desktop-only checks are used.
- Work:
  1. Require `desktop-1366`, one phone, and one tablet project in release smoke.
  2. Fail release checks when cross-device League route smoke fails.
- Done looks like:
  1. `smoke-api.spec.js` is green on desktop + phone + tablet in CI/release checks.
  2. Public League route regressions are caught before deploy.

### 0.3 Resolve `/calculator` route mismatch
- Why: blueprint/runtime mismatch creates migration ambiguity.
- Work:
  1. Choose one: add backend alias route or remove target from blueprint/doc claims.
  2. Add test assertion for chosen behavior.
- Done looks like:
  1. Runtime map, docs, and smoke assertions all agree on `/calculator`.

## Phase 1 - Runtime Truth + Boundary Hardening

### 1.1 Finalize `/api/data` public/private exposure policy
- Why: `/api/league/public` exists, but `/api/data` remains broad and public.
- Work:
  1. Decide policy (public broad, restricted, or split endpoint strategy).
  2. Implement enforcement and update operator docs.
  3. Add regression tests for expected access and data shape.
- Done looks like:
  1. Boundary behavior is intentional, tested, and documented for non-technical operators.

### 1.2 Remove stale/conflicting architecture docs
- Why: stale docs cause false completion and bad release calls.
- Work:
  1. Correct conflicting statements in league and blueprint docs.
  2. Link all route-ownership claims to `docs/RUNTIME_ROUTE_AUTHORITY.md`.
- Done looks like:
  1. No doc claims Next owns `/league` unless runtime actually does.

### 1.3 Harden auth config defaults for production
- Why: default password fallback in code is a security posture weakness.
- Work:
  1. Require explicit env secrets in production mode.
  2. Add startup warnings/fail-fast where needed.
- Done looks like:
  1. Production deploy cannot run with default credential fallback.

## Phase 2 - Value/Identity Quality Hardening

### 2.1 Improve identity conflict quality trend
- Why: merge is deterministic, but conflict/unmatched counts remain non-zero.
- Work:
  1. Export daily mismatch metrics with retained history.
  2. Prioritize top unresolved/conflict reasons and reduce count over time.
  3. Tighten promotion thresholds as quality improves.
- Done looks like:
  1. Before/after mismatch trend is queryable and reported per run.
  2. Conflict/unmatched rates show sustained reduction.

### 2.2 Move key source diagnostics into contract diagnostics
- Why: important diagnostics live in raw settings; downstream surfaces cannot consume them cleanly.
- Work:
  1. Surface identity/source-column highlights in `valueResolverDiagnostics`.
  2. Add contract tests for these fields.
- Done looks like:
  1. Consumers can read source/identity diagnostics directly from contract payload.

### 2.3 De-pin promotion gate tests from date-specific payload
- Why: date-pinned payload references can break clean CI over time.
- Work:
  1. Move base gate fixture to stable `tests/fixtures`.
  2. Keep dynamic payload checks separate.
- Done looks like:
  1. Promotion tests pass in clean environments without relying on mutable date files.

## Phase 3 - League Product Completion (data-backed depth)

### 3.1 Standings/records/history data backbone
- Why: current League tabs are mostly scaffold/blocked.
- Work:
  1. Build historical ingestion for seasons/matchups/team-week scores.
  2. Add quality gates before enabling official outputs.
- Done looks like:
  1. Standings + records + history modules render real validated data.

### 3.2 Money/constitution/media manual workflows
- Why: blueprint calls for public transparency modules; current state is mostly placeholders.
- Work:
  1. Add commissioner-editable stores.
  2. Add publish workflow and validation checks.
- Done looks like:
  1. Non-engineers can update these modules safely without code edits.

## Phase 4 - Migration + Differentiation

### 4.1 Decide Next cutover strategy route-by-route
- Why: dual-runtime can remain if explicit, but accidental split authority is dangerous.
- Work:
  1. Define readiness criteria per route.
  2. Cut over only when parity tests pass.
- Done looks like:
  1. No route has ambiguous ownership.

### 4.2 Trade suggestions engine maturation
- Why: flagship differentiation depends on stable shared value authority first.
- Work:
  1. Consolidate suggestion logic into shared service path.
  2. Add realism/strategy/exclusion controls with explainability.
- Done looks like:
  1. Suggestions are consistent with calculator value authority and test-covered.

### 4.3 Offseason projection integration (Mike Clay)
- Why: planned strategic edge feature, currently not started.
- Work:
  1. Build ingestion/parser + canonical mapping.
  2. Add offseason weighting + seasonal gate.
  3. Add diagnostics and override controls.
- Done looks like:
  1. Offseason projection signal is configurable, auditable, and safely decays post-Week-1.

## Top 10 concrete next actions

1. Resolve `Static/league/*` artifact policy and enforce it in CI.
2. Re-run smoke on `desktop-1366`, one phone, one tablet and store results as release evidence.
3. Keep cross-device smoke mandatory in deploy/release workflow checks.
4. Decide `/calculator` runtime behavior and align route map/docs/tests.
5. Decide `/api/data` public exposure policy and enforce it.
6. Add persistent identity mismatch trend export (daily snapshot).
7. Promote identity/source diagnostics into contract-level diagnostics.
8. De-pin promotion gate test fixture from date-specific payload files.
9. Start League historical data backbone implementation with quality gates.
10. Add release-time runtime probe artifact capture from deployed environment.
