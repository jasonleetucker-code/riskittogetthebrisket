# Remaining Work Inventory (Repo-Grounded)

Date: 2026-03-19

Status labels:
- `critical blocker`
- `high`
- `medium`
- `low`
- `technical debt`
- `verification gap`

## Critical blockers

| Item | Why it matters | Definition of done | Evidence |
|---|---|---|---|
| Resolve `Static/league/*` untracked deploy risk | `/league` full shell can appear healthy locally while deploy artifact ownership is undefined | `Static/league/index.html`, `league.css`, `league.js` are either tracked in git or generated deterministically in deploy/build and verified in CI | `git status --short` shows `?? Static/league/`; `deploy/verify-deploy.sh:13` |
| Decide `/calculator` runtime policy | Blueprint and runtime route map diverge, causing migration confusion | `/calculator` either exists as intentional alias (implemented + tested) or removed from planning/docs/tests as non-goal | runtime routes in `server.py:669` do not include `/calculator`; blueprint mentions it (`docs/BLUEPRINT_EXECUTION.md:165`) |

## High-priority unfinished features

| Item | Why it matters | Definition of done | Evidence |
|---|---|---|---|
| Finalize public/private payload policy for `/api/data` | Current public endpoint still exposes broad internals; boundary messaging is ambiguous | Chosen policy implemented (auth-gate, allowlist split, or explicit accepted exposure) and documented in operator docs | `/api/data` public at `server.py:2213`; boundary doc warning `docs/league-page/public-private-boundary.md:9` |
| Reduce identity conflict/unmatched rates | Deterministic merge exists but quality risk remains with non-zero conflict buckets | Top unresolved buckets triaged; mismatch trend report added; thresholds tightened with confidence | identity totals in `data/dynasty_data_2026-03-19.json:970` |
| De-pin promotion gate test fixture dependency | Date-pinned payload in tests can cause CI fragility | Promotion tests use stable fixture inputs under `tests/fixtures`, not date-specific runtime files | `tests/api/test_promotion_gate.py:25` |
| Keep docs/tests/runtime lockstep discipline | Drift can return as implementation changes unless ownership docs and smoke assertions stay coupled | Every route-authority change updates `README.md`, `docs/RUNTIME_ROUTE_AUTHORITY.md`, and smoke assertions in the same change set | route ownership docs in `README.md:132`, `docs/RUNTIME_ROUTE_AUTHORITY.md:54`, smoke checks in `tests/e2e/specs/smoke-api.spec.js:188` |
| League tab data depth (standings/records/history/awards/money/media) | Route shells exist but much of the public League product remains scaffold-level | At least one additional tab beyond Home/Franchises/Trades backed by real validated data, with blocked markers removed only where data exists | module status in `server.py:1739`; tab specs in `Static/league/league.js:39` |

## Medium-priority follow-up work

| Item | Why it matters | Definition of done | Evidence |
|---|---|---|---|
| Promote source/identity diagnostics into contract-level `valueResolverDiagnostics` | Diagnostics currently live in raw settings and are harder for downstream consumers | Key diagnostics (identity totals, IDPTradeCalc coverage) available in contract diagnostics and validated by tests | `Dynasty Scraper.py:12080`, `src/api/data_contract.py:1170` |
| Harden auth defaults for production | Hardcoded fallback password is acceptable for dev but risky in prod posture | Production mode requires env-provided credentials and secure cookie defaults; startup warnings upgraded | `server.py:98-101` |
| Clarify Next migration authority boundaries | Next shell exists but is non-authoritative for League; risk of accidental assumption | Migration doc includes explicit cutover checklist and route-by-route authority state | `frontend/README.md:24`; empty `frontend/app/league` routes |
| Improve mobile/tablet UX beyond smoke baseline | Smoke verifies route and basic layout, not full interaction quality | Mobile parity checklist includes calculator workflows, filters, dense tables, and performance targets | current smoke focus in `tests/e2e/specs/smoke-api.spec.js` |

## Low-priority polish / future enhancements

| Item | Why it matters | Definition of done | Evidence |
|---|---|---|---|
| Expand League media/manual workflows | Improves public league storytelling but not core runtime safety | Commissioner-editable media and constitution content workflow in place | planned in `docs/league-page/feature-blueprint.md` |
| Next runtime visual/system modernization | Useful once authority cutover path is stable | Unified design system applied after runtime authority ambiguity is resolved | `frontend/app/*` current shell status |
| Trade suggestions productization (v1.5/v2) | Differentiator feature but depends on stable shared value + route authority | Shared service-based suggestions engine replaces static-only branches | static suggestions in `Static/js/runtime/30-more-surfaces.js` |

## Technical debt / cleanup

| Item | Why it matters | Definition of done | Evidence |
|---|---|---|---|
| Dual-runtime complexity (static default + optional Next) | Increases drift risk and duplicate logic pressure | Explicitly scoped ownership matrix enforced by tests and docs; dead migration artifacts removed or quarantined | runtime split in `server.py`, `frontend/README.md`, `src/README.md` |
| Frontend fallback formula duplication | Needed for manual assets but can drift from backend authority | Fallback path isolated, version-tagged, and instrumented for drift alerts | `Static/js/runtime/00-core-shell.js`, `docs/FORMULA_AUTHORITY_MAP.md` |
| Local `.next` and scaffold artifacts narrative noise | Misleads maintainers about what is live | Non-authoritative artifacts either ignored by policy or clearly marked in docs/tests | warnings in `server.py:649-657` |

## Verification/testing gaps

| Item | Why it matters | Definition of done | Evidence |
|---|---|---|---|
| Cross-device smoke should stay green on desktop + phone + tablet | Needed for release confidence on public League flow | `smoke-api.spec.js` passes for `desktop-1366`, at least one phone, and one tablet in CI and release checks | latest local runs are green; keep this enforced to prevent drift |
| Production runtime probe evidence not stored per release | Repo-only checks cannot prove remote deploy truth | Release report stores route-authority + health snapshots from deployed environment | current audit is repo/local-runtime grounded |
| Historical before/after identity metric trend | User asked for before/after mismatch counts; historical baseline currently sparse | Persist daily mismatch snapshot (sourceRows/matched/unmatched/conflicts) for trend charts | only 2026-03-19 payload has full identity diagnostics in current local data series |

## Explicit before/after mismatch counts (available evidence)

- After instrumentation (current run payload):  
  `sourceRows=4682`, `matchedRows=4661`, `unmatchedRows=21`, `duplicateCanonicalMatches=2`, `conflictingPositions=0`, `conflictingSourceIdentities=159`  
  Source: `data/dynasty_data_2026-03-19.json` (`settings.sourceColumnDiagnostics.identityResolution.totals`).

- Before instrumentation (older snapshots in this workspace):  
  `sourceRows/unmatched/duplicate/conflict` are not present in `data/dynasty_data_2026-03-04.json` through `data/dynasty_data_2026-03-14.json`; explicit comparable counts are unavailable from those artifacts.

Required closure:
- add persisted daily identity metrics export so before/after is always measurable without ad hoc log archaeology.
