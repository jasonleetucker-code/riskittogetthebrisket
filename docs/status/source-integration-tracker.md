# Source Integration Tracker

_Updated: 2026-03-22 (Phase B scraper re-run, honest metrics with anchor variance noted)_

## Pipeline

```
14 Source CSVs → ScraperBridge/DLF Adapters → Identity Resolution
  → Canonical Blend (weight v4)
  → Position Enrichment (legacy + nickname + supplemental + IDP infer = 81.4%)
  → Scarcity Adjustment (0.30 dampened VAR, 996 assets)
  → Calibration (offense=8500, IDP=5000, picks=legacy curve)
  → Canonical Snapshot (1239 assets)
```

## Key Metrics (2026-03-22, current run)

| Metric | Value | Int-Primary | Pub-Primary |
|--------|-------|-------------|-------------|
| Sources | 14 | PASS (>=4) | PASS (>=6) |
| Assets | 1239 | — | — |
| Position coverage | 81.4% | — | — |
| Scarcity-adjusted | 996 | — | — |
| Multi-source blend | **61%** | PASS (>=40) | PASS (>=60) |
| Off players top-50 | **78%** | PASS (>=70) | FAIL (>=80, by 2%) |
| Off players top-100 | **84%** | PASS (>=65) | PASS (>=75) |
| Off players tier | **53.4%** | PASS (>=50) | FAIL (>=65) |
| Off players delta | **1006** | PASS (<=1500) | FAIL (<=800) |
| Overall delta | **758** | — | PASS (<=800) |
| Overall tier | **65.2%** | — | PASS (>=65) |
| IDP tier | **75.2%** | — | — |
| **Internal-primary** | **9/9 PASS** | **VALIDATED** | — |
| **Public-primary** | **7/12** | — | 4 remaining |

### Metric Stability Note

Offense top-50 varies 78-94% across scraper runs due to DLF rookie anchor variance
in the legacy reference. This is not canonical instability — canonical player values
are identical between runs.

## Source Freshness

| Source | Date | Players | Status |
|--------|------|---------|--------|
| FantasyCalc | 2026-03-22 | 458 | **FRESH** |
| DLF (4 CSVs) | 2026-03-22 | 559 | **FRESH** |
| KTC | 2026-03-09 | 500 | archived (browser timeout) |
| DynastyDaddy | 2026-03-09 | 336 | archived (browser timeout) |
| DraftSharks | 2026-03-09 | 490 | archived (browser timeout) |
| FantasyPros | 2026-03-09 | 303 | archived (browser timeout) |
| Yahoo | 2026-03-09 | 457 | archived (browser timeout) |
| IDPTradeCalc | 2026-03-09 | 383 | archived (browser timeout) |
| PFF_IDP | 2026-03-09 | 249 | archived (browser timeout) |
| FantasyPros_IDP | 2026-03-09 | 70 | archived (browser timeout) |
| DynastyNerds | 2026-03-09 | 12 | archived (paywalled) |

## Mode Status

| Mode | State | Notes |
|------|-------|-------|
| off | Available | Default |
| shadow | Available | Logs comparison, serves legacy |
| **internal_primary** | **VALIDATED** | Canonical via scaffold, legacy on /api/data |
| primary | Not ready | Blocked by offense metrics + founder approval |
