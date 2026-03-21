# Frontend/Backend Parity Release Gate

## Objective
Treat rankings/trade parity as release-critical proof, not advisory diagnostics.

## Live Authority Path
1. Backend builds authoritative values in `/api/data` (`valueBundle.fullValue`, canonical source values).
2. Static runtime renders rankings/trade surfaces from that payload.
3. Frontend parity snapshots are written to:
   - `window.__frontendBackendParity.rankings`
   - `window.__frontendBackendParity.tradeCalculator`
4. Release gate fails if parity mismatches are detected on required surfaces.

## Required Assertions (Release-Critical)
The release parity gate now blocks publish if any required assertion fails:

- Rankings displayed-value parity vs backend authority bundle
- Rankings source-column parity vs canonical source values
- Player popup/card final value parity
- Trade row parity vs backend authority bundle
- Key position-bucket coverage (OFF + IDP buckets) for tracked sources
- No client-side mutation for known-player rows in rankings/trade

## Enforcement Point
Release gating is wired into `.github/workflows/deploy.yml` (validate job):

- installs Playwright + Chromium
- seeds deterministic runtime payload fixture:
  - `tests/fixtures/runtime_last_good_fixture.json` -> `data/runtime_last_good.json`
- runs `npm run regression:test:parity`
- executes required projects:
  - `desktop-1366`
  - `mobile-390`

A failing parity assertion blocks deploy before remote execution starts.

## Local Operator Commands
One-time setup:

```powershell
npm install
npm run regression:install
```

Run release parity gate locally:

```powershell
npm run regression:parity
```

Fast parity-only run (skip preflight):

```powershell
npm run regression:test:parity
```

## Failure Artifacts
On CI failure, deploy validation uploads:

- `tmp/playwright/playwright-report`
- `tmp/playwright/test-results`
- legacy fallback paths (`playwright-report`, `test-results`, `tests/e2e/*`) when present

Use those artifacts to identify which parity contract drifted.

## Live Runtime Parity Proof (2026-03-20)
Authenticated parity was run directly against production:

```powershell
$env:E2E_BASE_URL='https://riskittogetthebrisket.org'
$env:E2E_JASON_USERNAME='jasonleetucker'
$env:E2E_JASON_PASSWORD='<redacted>'
npx playwright test -c tests/e2e/playwright.config.js tests/e2e/specs/parity-gate.spec.js --project=desktop-1366 --project=mobile-390 --workers=1
```

Result: `4 passed` (desktop + mobile, rankings + trade authority surfaces).
