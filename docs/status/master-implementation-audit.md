# Master Implementation Audit (Truth Report)

Date: 2026-03-19  
Scope: Repo-grounded status and gap audit for runtime, product surfaces, value pipeline, source integrations, auth boundaries, tests, deploy safety, and roadmap drift.

## 1) Executive Summary
- The live runtime authority is `server.py` + Static shell, not Next, with explicit route authority and deploy-readiness checks now present.
- The value pipeline is materially live and shared (`Dynasty Scraper.py` -> `src/api/data_contract.py` -> `/api/data`) with promotion gates and last-known-good fallback.
- Yahoo, DynastyNerds, and IDPTradeCalc are present in current payloads; IDPTradeCalc has offensive + IDP coverage in the latest local run.
- League public routing is resilient (no raw `/league` 500 when shell assets are missing), but there is still a deploy-risk mismatch: `Static/league/*` exists locally and is untracked in this workspace.
- Mobile/tablet smoke coverage now passes on desktop + phone + tablet for the public League flow.
- Blueprint and league docs are now materially aligned with runtime truth; remaining drift risk is concentrated around unresolved `/calculator` policy and deploy artifact provenance.

## 2) Blueprint Sources and Source-of-Truth Assessment

Primary source of truth (implementation-level):
- `server.py` route handlers + runtime metadata endpoints (`/api/runtime/route-authority`, `/api/architecture`).
- `Dynasty Scraper.py` + `src/api/data_contract.py` for valuation authority.

Primary source of truth (planning-level):
- `docs/BLUEPRINT_EXECUTION.md` (master intent + phases).

Supporting truth docs:
- `docs/RUNTIME_ROUTE_AUTHORITY.md`
- `docs/REPO_INVENTORY.md`
- `docs/FORMULA_AUTHORITY_MAP.md`
- `docs/PROMOTION_RELEASE_GATE.md`
- `docs/VALUE_PIPELINE_GOLDEN_REGRESSION.md`
- `docs/league-page/README.md` + `docs/league-page/*.md`

Active doc drift risks:
- `/calculator` is still discussed in roadmap/blueprint threads but not implemented as a live backend route.
- League shell deploy provenance can still be misread when local untracked `Static/league/*` artifacts exist.

## 3) Master Feature / Workstream Inventory

### Runtime + Routing
- Public landing and League routes: implemented.
- Private routes `/app`, `/rankings`, `/trade`: implemented/auth-gated.
- `/calculator` parity route: missing.
- Runtime authority diagnostics endpoint: implemented.
- League fallback hardening for missing static shell: implemented.

### League Surface
- Top-level route shells for all requested League tabs: implemented.
- Home/franchise directory/recent trades summary: implemented (summary-level).
- Deeper standings/records/awards/history/money/media content: scaffolded/blocked by data/manual inputs.

### Value Pipeline + Sources
- Authoritative value path wired and versioned contract emitted.
- IDPTradeCalc dual-universe handling (offense + IDP) in pipeline: implemented.
- Identity diagnostics and deterministic merge strategy metadata: implemented.
- Source coverage diagnostics and positional coverage: implemented.

### Testing + Gating
- API contract + identity + promotion-gate + league-route resilience unit tests: implemented.
- Golden value regression fixtures/tests: implemented.
- Cross-device route smoke: implemented and passing on desktop + phone + tablet.
- Deploy verification script checks route authority and League shell readiness: implemented.

### Frontend Runtime Split
- Static runtime authority: implemented/default.
- Next runtime shell (optional): partial.
- Next League route ownership: not implemented.

### Ops/Deployment/Automation
- GitHub deploy workflow + remote deploy/verify/rollback scripts: implemented.
- In-process scrape scheduler + uptime watchdog in server runtime: implemented.
- Event-driven scheduled smoke/regression in CI: not implemented.

### Strategic/Backlog Threads Mentioned in planning but not wired
- Mike Clay offseason projection ingestion/integration: not implemented.
- Full trade suggestions productization (shared service, realism sliders, counterflows): partial.
- Full historical league backbone and manual content tooling: partial/missing.

## 4) Blueprint vs Current State Comparison

| Blueprint target | Current state | Status |
|---|---|---|
| Unified authoritative value backbone across rankings/calculator | Live scraper+contract path shared; static UI parity checks exist | mostly complete |
| Public League hub with strong public/private boundary | Public routes + summary public API exist; deep tab data/manual stores missing; `/api/data` still broad/public | partial |
| Mobile parity for core workflows | Public League route smoke passes on desktop + phone + tablet; deeper mobile UX parity remains ongoing | partial |
| Runtime authority clarity and migration safety | Route-authority endpoint/docs/tests exist; Next League ownership still non-authoritative; `/calculator` alias gap remains | mostly complete |
| Source breadth including Yahoo, DynastyNerds, IDPTradeCalc offensive+IDP | Present in latest payload and smoke checks; relies on successful scrape runs | mostly complete |
| Deterministic identity resolution with diagnostics | Strategy + mismatch diagnostics implemented; non-zero unresolved/conflict counts remain | partial |
| Publish gate preventing bad payload promotion | Promotion gates + operator report + last-known-good in place | complete |
| Deployment-safe League shell readiness | Verify gate exists, but local workspace has untracked `Static/league/*` artifacts | partial/blocker |
| Next migration for League and route ownership cleanup | Next League pages absent (directories only), static remains authority | scaffolded only |
| Offseason projection integration (Mike Clay) | No code or schema artifacts found | planned but not started |

## 5) Verified Complete
- Runtime route authority map endpoint and headers are implemented and exercised by smoke/tests.
- `/league` fallback behavior avoids raw 500 and keeps route public.
- Auth gate for `/app`, `/rankings`, `/trade` is implemented in backend route handlers.
- Promotion gate path blocks bad payload promotion and persists last-known-good snapshots.
- Value contract validation and golden regression tests exist and pass in current local run.

## 6) Partial / Incomplete
- Public League content depth: most tabs remain scaffold/blocked.
- Public/private data boundary: improved via `/api/league/public` but `/api/data` remains broad/public.
- Mobile parity: route smoke is green, but deeper calculator/rankings interaction parity is still incomplete.
- Next migration: route ownership for League remains static backend-owned.
- Identity integrity: conflicts/unmatched are diagnosed but not zero.
- Formula authority consolidation: fallback frontend math still exists for non-authoritative/manual paths.

## 7) Planned but Not Started
- Mike Clay 2026 projection ingestion pipeline.
- Mike Clay seasonal weighting/gating integration into shared ranking/trade value layer.
- Full historical/curated datasets for League tabs (awards/records/history/money/media).
- True recommendations engine evolution beyond calculator-centric flows.

## 8) Blocked or Unclear
- `Static/league/*` tracked/deployed state is blocked in this workspace because folder is untracked.
- Production runtime confirmation is unclear from repo alone (local tests pass; remote deploy state not directly verified here).
- True mobile physical-device behavior remains unclear beyond Playwright emulation.

## 9) False Sense of Completion Items
- Any future `frontend/app/league/page.*` sources do not imply live League ownership until backend authority is intentionally cut over.
- `frontend/.next` presence does not imply route authority.
- League tab routes load, but many modules are scaffold/blocked and not feature-complete.
- Docs claim progression in some areas where implementation is still placeholder-level.
- `tests/api/test_promotion_gate.py` references a date-pinned local data file (`data/dynasty_data_2026-03-19.json`), which can create confidence locally but fragility in clean CI environments.

## 10) Blueprint Gap Analysis (Condensed)
- See `docs/status/blueprint-gap-analysis.md` for full gap table and closure actions.

## 11) Critical Remaining Work
1. Resolve deploy-risk mismatch for `Static/league/*` (track/build/generate policy) so `/league` full shell is not dependent on local untracked artifacts.
2. Keep cross-device smoke (`desktop-1366`, phone, tablet) as a required release gate to prevent regressions.
3. Decide and implement `/calculator` route policy (alias to `/trade` or explicit route) to remove blueprint/runtime mismatch.
4. Close public/private boundary ambiguity for public consumers (`/api/data` exposure strategy + explicit public contract policy).

## 12) High / Medium / Low Priority Remaining Work
- See `docs/status/remaining-work-inventory.md`.

## 13) Recommended Next Execution Order
- See `docs/status/priority-roadmap.md`.

## 14) Docs Created / Updated
- Created:
  - `docs/status/master-implementation-audit.md`
  - `docs/status/blueprint-gap-analysis.md`
  - `docs/status/remaining-work-inventory.md`
  - `docs/status/priority-roadmap.md`

## 15) Risks and Unknowns
- Untracked local artifacts may hide deploy/runtime breaks not visible in source control.
- Date-pinned/local-data-dependent tests may pass locally and fail in clean environments.
- Dual-runtime architecture (static default + optional Next) continues to create drift risk unless route ownership remains explicitly guarded.
- Scrape/source variability can still cause payload volatility; gates catch many failures but do not eliminate upstream instability.

## 16) Final Recommendation
- Treat this system as a production static-backend app with an optional Next migration shell, not as a completed Next-owned architecture.
- Prioritize route/deploy truth and public data-boundary policy first, then continue feature expansion (League depth, suggestions, offseason projections) on top of that stable base.
