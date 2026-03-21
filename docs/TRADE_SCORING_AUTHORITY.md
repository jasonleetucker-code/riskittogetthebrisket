# Trade Scoring Authority (Static Runtime + Backend)

Last verified: 2026-03-20 (live runtime)

## Authority Path
1. `Dynasty Scraper.py` builds canonical player values.
2. `src/api/data_contract.py` publishes backend `valueBundle` layers.
3. `server.py` exposes `/api/data` and `/api/trade/score`.
4. `Static/js/runtime/20-data-and-calculator.js` computes row display values, then requests backend package scoring from `/api/trade/score`.
5. Historical Sleeper trade analysis (`analyzeSleeperTradeHistory`) and roster trade grades now route package scoring through `/api/trade/score` (no browser-only package formula in those surfaces).

## New Endpoint
- Route: `POST /api/trade/score`
- Request:
  - `valueBasis`: `raw | scoring | scarcity | bestBall | full`
  - `alpha`: trade exponent
  - `bestBallMode`: boolean
  - `sides`: `{ A: [...], B: [...], C: [...] }`
  - Each side item supports:
    - `label`
    - `fallbackValue`
    - `pos`, `isPick`, `isIdp`, `isRookie`, `assetClass`
    - `confidence`, `bestBallLift`
    - `manualOverride`
- Response:
  - Per-side package totals (`weightedTotal`, `packageMultiplier`, `packageDeltaPct`, etc.)
  - Resolution diagnostics (`backendResolved`, `fallbackUsed`, `quarantinedExcluded`, `unresolvedExcluded`)
  - Resolved and unresolved entry lists for operator/debug visibility

## Trust Rules Enforced
- Known assets resolve from backend `valueBundle` (not browser fallback values).
- Quarantined non-pick assets are excluded from package scoring.
- Manual override rows use explicit fallback values and are labeled as manual fallback.
- Unresolved non-manual rows use fallback only when provided; otherwise excluded.

## Residual Browser-Only Logic
- Manual row site-entry composition remains browser-side.
- Local package formula remains as an explicit calculator fallback only when `/api/trade/score` is unavailable.
- If backend responds but omits a populated side `weightedTotal`, calculator now withholds package totals (integrity hold) instead of falling back locally.
- Historical trade analysis and trade grades require backend scoring authority; they now surface unavailable/partial authority state instead of silently scoring with browser formula.
- Fallback diagnostics are explicit:
  - Calculator: `window.__tradeCalculatorPackageDiagnostics.fallback`
  - Historical analysis: `window.__tradeHistoryScoringDiagnostics`

## Runtime Authority Diagnostics
- Calculator now publishes authority state to `window.__tradeCalculatorAuthorityState`.
- Calculator now publishes compact user-truth summary state to `window.__tradeCalculatorTruthState`.
- Contract/version mismatch between runtime payload and trade-score response is surfaced as a hard error:
  - `window.__tradeCalculatorPackageDiagnostics.contract.mismatch === true`
  - UI warning banners: `#tradeAuthorityWarning` and `#mobileTradeAuthorityWarning`
- Compact trust summary surfaces in UI:
  - desktop: `#tradeTruthSummary`
  - mobile: `#mobileTradeTruthSummary`
  - includes authoritative/partial headline plus fallback/manual/quarantine/unresolved/low-confidence counts when present.
- Fallback policy can be controlled with:
  - `window.__tradeFallbackPolicy = "allow" | "disallow"`
  - `localStorage["dynasty_trade_fallback_policy"] = "allow" | "disallow"`
- When fallback is disallowed and backend scoring is unavailable, package totals are withheld and surfaced as non-authoritative:
  - `authority: "backend_trade_scoring_required_fallback_disallowed"`
  - `fallback.blockedCount > 0`
- When backend is healthy but payload integrity is broken (missing side totals), package totals are withheld and surfaced as non-authoritative:
  - `authority: "backend_trade_scoring_invalid_payload"`
  - `fallback.backendPayloadIssueCount > 0`
  - `fallback.bySide.<side>.payloadIssue === true`
- Best-ball context assumptions are explicit in diagnostics:
  - `window.__tradeCalculatorPackageDiagnostics.bestBallContext`
- Row-level truth flags are surfaced in the trade value cell when applicable:
  - `manual override`
  - `quarantined`
  - `low confidence`

## Live Runtime Proof Snapshot (2026-03-20)
- `POST /api/trade/score` returns:
  - `authority: "backend_trade_scoring_v1"`
  - `contractVersion: "2026-03-20.v6"`
  - per-side `resolution` counters (`backendResolved`, `fallbackUsed`, `quarantinedExcluded`, `unresolvedExcluded`)
- Known-assets-only call showed `fallbackUsed: 0` on both populated sides.
- Mixed call (known + unknown asset) showed explicit surfaced fallback:
  - unknown row resolution: `fallback_unresolved`
  - summary `fallbackUsed: 1`
