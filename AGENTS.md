# Repo Instructions (Dynasty Trade Calculator)

## Scope
This repository powers dynasty fantasy football valuation, rankings, trade calculation, source ingestion, scraper-backed data publishing, runtime health automation, and the public/private web surfaces around that data.

## Non-Negotiables
- Do not assume a feature works because a helper, component, or file exists.
- Trace the live execution path end to end before claiming anything is implemented.
- Prefer modifying existing architecture over introducing parallel systems.
- Preserve working behavior unless a verified flaw requires change.
- Verify downstream effects for any value/ranking change in UI rendering, sorting, filtering, exports, and league-specific transforms.
- Verify ingestion, normalization, merge logic, fallback behavior, and frontend consumption for any scraper/source change.
- Call out anything mocked, bypassed, stale, duplicated, half-wired, dead, or missing.

## Safety
- Do not exfiltrate private data.
- Do not run destructive commands without approval.
- Prefer reversible operations where possible.
- Be explicit before any action affecting production, deployment, credentials, Jenkins triggers, or public output.
- Do not run `sync.bat`, deploy scripts, or remote-only commands unless the user explicitly asks for commit/push/deploy behavior.

## Live Entry Points To Trace First
- Backend runtime, route ownership, health, and auth boundaries: `server.py`
- Scraper/value generation and published payload production: `Dynasty Scraper.py`
- API contract assembly and validation target: `src/api/data_contract.py`
- Frontend backend-first data access and fallback behavior: `frontend/app/api/dynasty-data/route.js`, `frontend/lib/dynasty-data.js`
- Regression harness and live browser checks: `tests/e2e/playwright.config.js`, `tests/e2e/specs/`
- Automation and release gates: `.github/workflows/deploy.yml`, `.github/workflows/runtime-health.yml`, `.github/workflows/runtime-smoke.yml`, `.github/workflows/weekly-deep-audit.yml`

## Required Workflow
1. Read the relevant files first.
2. Identify the real live path, not just helpers.
3. Make the smallest correct change set.
4. Run the smallest validation set that proves the touched path still works.
5. Report exactly what changed, what was verified, and what remains uncertain.

Validation selection rule:
- Docs-only changes should be verified against the source files they document; code tests are optional unless the doc changes operational behavior or commands.

## Task-Specific Workflows

### Value, Ranking, Trade, Or Contract Changes
1. Trace from `Dynasty Scraper.py` into `server.py`, `src/api/data_contract.py`, and any touched `src/scoring/` modules.
2. Verify the API contract and semantic integrity before claiming success.
3. Run the critical value/trade tests plus any focused matrix or regression coverage for the impacted path.
4. If the change affects UI rendering, run the relevant Playwright parity or smoke suite.

Preferred validation commands:
```powershell
python .\scripts\validate_api_contract.py --repo .
python .\scripts\semantic_ratchet_gate.py --repo .
python .\scripts\run_critical_api_tests.py --repo .
python -m unittest tests.api.test_trade_scoring_matrix -v
npm run regression:test:parity
```

### Route Authority, League Shell, Auth, Or Status Changes
1. Start at `server.py` and the affected static shell under `Static/`.
2. Verify route ownership, redirect behavior, health/status responses, and compact polling payloads.
3. Use the runtime probe for route smoke when public/private boundaries or health semantics change.
4. Run the focused API tests and the relevant Playwright smoke coverage.

Preferred validation commands:
```powershell
python -m unittest tests.api.test_league_route_resilience tests.api.test_server_lifespan tests.api.test_status_compact -v
python .\scripts\runtime_probe.py --base-url http://127.0.0.1:8000 --mode smoke --strict-health --strict-operator --strict-routes --max-scrape-age-hours 10 --output-json tmp/runtime_probe_local.json
npm run regression:test:smoke:release
```

### Scraper, Ingestion, Identity, Or Raw Fallback Changes
1. Trace from `Dynasty Scraper.py` or the touched `scripts/` ingestion path through normalization, validation, and frontend consumption.
2. Check fallback behavior explicitly; do not assume missing or malformed raw artifacts degrade safely.
3. Validate contract health, raw fallback health, and any identity/canonical side effects.

Preferred validation commands:
```powershell
python .\scripts\validate_api_contract.py --repo .
python -m unittest tests.api.test_frontend_raw_fallback_health tests.api.test_identity_resolution tests.api.test_value_authority_guardrails -v
python .\scripts\quarantine_invalid_raw_fallback.py --json
```

### Offseason Mike Clay Integration Changes
1. Read the importer and integration path in `scripts/import_mike_clay.py` and `src/offseason/mike_clay/`.
2. Verify the seasonal gating config in `config/mike_clay_integration.json`.
3. Run both ingest and value-integration tests before treating offseason blending as correct.

Preferred validation commands:
```powershell
python .\scripts\import_mike_clay.py --pdf .\data\imports\mike_clay\NFLDK2026_CS_ClayProjections2026.pdf
python -m unittest tests.api.test_mike_clay_ingest tests.api.test_mike_clay_value_integration -v
```

### Automation, Monitoring, CI, Or Deploy Changes
1. Read the affected workflow file under `.github/workflows/` plus any called script under `scripts/`.
2. Mirror the real gate locally instead of inventing a simplified substitute.
3. If you change monitoring, verify the matching `runtime_probe.py` mode and output contract.
4. If you change release gates, run the same ratchet/tests/smoke commands the workflow uses.

Current automation workflows:
- `deploy.yml`: push-to-`main` or manual deploy; validates league shell tracking, Python syntax, API contract, semantic ratchet, critical tests, Playwright smoke, Playwright parity, then remote deploy.
- `runtime-health.yml`: hourly runtime freshness/health probe via `scripts/runtime_probe.py --mode health`.
- `runtime-smoke.yml`: every 12 hours route/auth smoke via `scripts/runtime_probe.py --mode smoke --strict-routes`.
- `weekly-deep-audit.yml`: weekly semantic ratchet, critical tests, and regression-focused API unit coverage.

Preferred validation commands:
```powershell
python .\scripts\semantic_ratchet_gate.py --repo .
python .\scripts\run_critical_api_tests.py --repo . --verbose
python -m unittest tests.api.test_automation_policy tests.api.test_identity_resolution tests.api.test_league_route_resilience tests.api.test_promotion_gate tests.api.test_status_compact tests.api.test_value_pipeline_golden -v
python .\scripts\runtime_probe.py --base-url https://riskittogetthebrisket.org --mode health --strict-health --strict-operator --max-scrape-age-hours 10 --output-json tmp/runtime_probe_health.json
python .\scripts\runtime_probe.py --base-url https://riskittogetthebrisket.org --mode smoke --strict-health --strict-operator --strict-routes --max-scrape-age-hours 10 --output-json tmp/runtime_probe_smoke.json
npm run regression:test:smoke:release
npm run regression:test:parity
```

## Command Reference

### Backend, Frontend, And Helpers
```powershell
python .\server.py
.\start_dynasty.bat
.\start_frontend.bat
.\start_stack.bat
.\run_scraper.bat
```

### Frontend Workspace
```powershell
cd .\frontend
npm run dev
npm run build
npm run lint
npm run typecheck
npm run test:dynasty-source
```

### Regression Harness
Set `$env:E2E_JASON_PASSWORD` to the password your local server expects before auth-gated Playwright runs.

```powershell
npm install
npm run regression:install
npm run regression:preflight
npm run regression
npm run regression:test
npm run regression:test:smoke:release
npm run regression:test:parity
```

### Scaffold And Reporting Pipeline
```powershell
python .\scripts\source_pull.py --repo .
python .\scripts\validate_ingest.py --repo .
python .\scripts\identity_resolve.py --repo .
python .\scripts\canonical_build.py --repo .
python .\scripts\league_refresh.py --repo .
python .\scripts\reporting.py --repo .
```

### Lockstep And Jenkins
```powershell
.\scripts\verify_lockstep.ps1
.\sync.bat "Your commit message"
```

## Performance Rules
- Prioritize page-load speed and perceived responsiveness.
- Reduce blocking work on initial load.
- Eliminate duplicated calculations, repeated fetches, and oversized payloads.
- Prefer memoization, batching, precomputation, caching, and lazy loading where justified.
- Do not sacrifice correctness for speed.

## Output Rules
- Be direct.
- Name exact files touched.
- Name exact code paths affected.
- Distinguish verified facts from inferences.
- When auditing, label items as complete, partial, mocked, bypassed, stale, dead, or missing.
