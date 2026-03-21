# Trade Calculator Release Proof (2026-03-20)

## Scope
- Target runtime: `https://riskittogetthebrisket.org`
- Focus: trade-calculator authority, promotion gate truth, authenticated parity (desktop + mobile)

## Verified Live Facts
- `GET /api/health` -> `HTTP 200`
  - `status: ok`
  - `contract_version: 2026-03-20.v6`
  - `contract_ok: true`
  - `promotion_gate_status: pass`
- `GET /api/validation/promotion-gate` -> `HTTP 200`
  - `status: pass`
  - `report.status: pass`
  - `gates.formulaSanity.ok: true`
  - `gates.formulaSanity.intentionalQuarantineMissingFullValueRows: 60`
- `GET /api/data?view=app` -> `HTTP 200`
  - `contractVersion: 2026-03-20.v6`
  - `payloadView: runtime`
  - `players: 1191`

## Trade Authority Proof
- `POST /api/trade/score` (known assets only):
  - `ok: true`
  - `authority: backend_trade_scoring_v1`
  - `contractVersion: 2026-03-20.v6`
  - side `resolution.fallbackUsed: 0`
- `POST /api/trade/score` (known + unknown asset):
  - unknown row is explicitly surfaced as `resolution: fallback_unresolved`
  - summary `fallbackUsed: 1`

## Authenticated Parity Proof
- Command:
  - `npx playwright test -c tests/e2e/playwright.config.js tests/e2e/specs/parity-gate.spec.js --project=desktop-1366 --project=mobile-390 --workers=1`
  - with `E2E_BASE_URL=https://riskittogetthebrisket.org` and authenticated Jason credentials
- Result: `4 passed`
  - desktop rankings parity
  - desktop trade parity
  - mobile rankings parity
  - mobile trade parity

## Regenerated Validation Artifacts
- `data/validation/api_contract_validation_latest.json`
- `data/validation/runtime_probe_live_latest.json`

## Residual Operator Note
- `runtime_probe_live_latest.json` reports one warning: compact status omits parseable `last_scrape` while full status includes `last_scrape`.
- This is an observability schema inconsistency, not a release blocker for trade authority.
