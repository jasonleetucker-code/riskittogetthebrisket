# Source Integration Tracker

_Updated: 2026-03-22 (KTC format fix — playersArray adaptation, production validated reachable)_

## Pipeline

```
13 Source CSVs → ScraperBridge/DLF Adapters → Identity Resolution
  → Canonical Blend (weight v4)
  → Position Enrichment (legacy + nickname + supplemental + IDP infer = 87.8%)
  → Scarcity Adjustment (0.30 dampened VAR, 1028 assets)
  → Calibration (offense=8500, IDP=5000, picks=legacy curve)
  → Canonical Snapshot (1198 assets)
```

## Source Freshness (2026-03-22)

| Source | Method | Status | Players | Blocker |
|--------|--------|--------|---------|---------|
| FantasyCalc | API | **FRESH** | 458 | — |
| DLF_SF | Local CSV | **FRESH** | 278 | — |
| DLF_IDP | Local CSV | **FRESH** | 185 | — |
| DLF_RSF | Local CSV | **FRESH** | 66 | — |
| DLF_RIDP | Local CSV | **FRESH** | 30 | — |
| DraftSharks | Browser | **FRESH** | 486 | — |
| DynastyDaddy | Browser | **FRESH** | 364 | — |
| DynastyNerds | Browser | **FRESH** | 168 | — |
| FantasyPros | Browser | **FRESH** | 303 | — |
| FantasyPros_IDP | Browser | **FRESH** | 70 | — |
| IDPTradeCalc | Browser | **FRESH** | 384 | — |
| PFF_IDP | Browser | **FRESH** | 249 | — |
| Yahoo | Browser | **FRESH** | 307 | — |
| **KTC** | **Browser** | **SANDBOX BLOCKED / PROD READY** | **526 (prod)** | **proxy_tls (sandbox only)** |

### KTC Diagnosis

**Sandbox:** Blocked by egress proxy TLS incompatibility (HTTP 503, `TLSV1_ALERT_PROTOCOL_VERSION`).

**Production (178.156.148.92):** KTC is **reachable and extractable**. Confirmed via
direct test on 2026-03-22:
- HTTP 200, page loads 3.7 MB
- `var playersArray = [...]` contains **526 players** with `playerName` + `superflexValues`
- 443 DOM elements matching `[class*="player"]`

**Format change (2026-03):** KTC migrated from `__NEXT_DATA__` (Next.js SSR) to inline
`var playersArray = [...]`. Health check and scraper updated in commit `c1559d4` to
detect both formats. Legacy `__NEXT_DATA__` path preserved as fallback.

**Health check**: `python scripts/check_ktc_health.py --full`
**Full runbook**: `docs/runbooks/ktc-production-validation.md`

## Current Metrics (11 fresh sources, no KTC player data)

| Metric | Value | Int-Primary | Pub-Primary |
|--------|-------|-------------|-------------|
| Sources | 13 | PASS (>=4) | PASS (>=6) |
| Assets | 1198 | — | — |
| Position coverage | 87.8% | — | — |
| Matched players | 1051 | — | — |
| Multi-source blend | **57%** | PASS (>=40) | FAIL (>=60) |
| Off players top-50 | **92%** | PASS (>=70) | **PASS (>=80)** |
| Off players top-100 | **92%** | PASS (>=65) | **PASS (>=75)** |
| Off players tier | **50.1%** | PASS (>=50) | FAIL (>=65) |
| Off players delta | **1006** | PASS (<=1500) | FAIL (<=800) |
| **Internal-primary** | **9/9 PASS** | **VALIDATED** | — |
| **Public-primary** | **7/12** | — | 4 remaining |

## What Changed from Proxy Fix + KTC Phase

| Metric | 2-source (prev) | 11-source (now) | Change |
|--------|-----------------|-----------------|--------|
| Legacy sources | 2 | 11 | +9 |
| Legacy players | 916 | 1163 | +247 |
| Off top-50 | 82% | **92%** | **+10%** |
| Off top-100 | 84% | **92%** | **+8%** |
| Off tier | 53.5% | 50.1% | -3.4% |
| Off delta | 999 | 1006 | +7 |
| Multi-source blend | 61% | 57% | -4% |

## Remaining Public-Primary Blockers

| Blocker | Gap | Root Cause | Fix |
|---------|-----|-----------|-----|
| Offense tier | 50.1% vs 65% | KTC missing, more sources = higher variance | KTC on production |
| Offense delta | 1006 vs ≤800 | Same root cause | KTC on production |
| Multi-source blend | 57% vs 60% | KTC missing reduces blend % | KTC on production |
| Founder approval | Not given | Manual | After metrics clear |

## KTC Impact Estimate

KTC is the largest single missing source. On the March 9 production run, KTC
contributed 501 players. Adding KTC is expected to:
- Increase multi-source blend from 57% → ~65%+ (many players gain a 12th source)
- Improve tier agreement by anchoring values to the market standard
- Reduce delta by providing the primary reference baseline

**Next step**: Run `python scripts/check_ktc_health.py --full` on production, then
run a full scrape if healthy.
