# Source Integration Tracker

_Updated: 2026-03-22 (internal_primary validated + scarcity confirmed at 0.30)_

## Pipeline

```
14 Source CSVs → ScraperBridge/DLF Adapters → Identity Resolution
  → Canonical Blend (weight v4)
  → Position Enrichment (legacy + nickname + supplemental + IDP infer = 81.4%)
  → Scarcity Adjustment (0.30 dampened VAR, 996 assets)
  → Calibration (offense=8500, IDP=5000, picks=legacy curve)
  → Canonical Snapshot (1239 assets)
```

## Key Metrics (2026-03-22)

| Metric | Value | Int-Primary | Pub-Primary |
|--------|-------|-------------|-------------|
| Sources | 14 | PASS (≥4) | PASS (≥6) |
| Assets | 1239 | — | — |
| Position coverage | 81.4% | — | — |
| Scarcity-adjusted | 996 | — | — |
| Multi-source blend | **61%** | PASS (≥40) | PASS (≥60) |
| Off players top-50 | **94%** | PASS (≥70) | PASS (≥80) |
| Off players top-100 | **90%** | PASS (≥65) | PASS (≥75) |
| Off players tier | **53.6%** | PASS (≥50) | FAIL (≥65) |
| Off players delta | **972** | PASS (≤1500) | FAIL (≤800) |
| Overall delta | **739** | — | PASS (≤800) |
| Overall tier | **65.2%** | — | PASS (≥65) |
| IDP tier | **74.8%** | — | — |
| **Internal-primary** | **9/9 PASS** | **VALIDATED** | — |
| **Public-primary** | **8/12** | — | 3 remaining |

## Source Freshness

| Source | Date | Players | Type | Status |
|--------|------|---------|------|--------|
| FantasyCalc | 2026-03-22 | 458 | API | **FRESH** |
| DLF_SF | 2026-03-22 | 278 | CSV | **FRESH** |
| DLF_IDP | 2026-03-22 | 185 | CSV | **FRESH** |
| DLF_RSF | 2026-03-22 | 66 | CSV | **FRESH** |
| DLF_RIDP | 2026-03-22 | 30 | CSV | **FRESH** |
| KTC | 2026-03-09 | 500 | browser | archived |
| DynastyDaddy | 2026-03-09 | 336 | browser | archived |
| DraftSharks | 2026-03-09 | 490 | browser | archived |
| FantasyPros | 2026-03-09 | 303 | browser | archived |
| Yahoo | 2026-03-09 | 457 | browser | archived |
| IDPTradeCalc | 2026-03-09 | 383 | browser | archived |
| PFF_IDP | 2026-03-09 | 249 | browser | archived |
| FantasyPros_IDP | 2026-03-09 | 70 | browser | archived |
| DynastyNerds | 2026-03-09 | 12 | browser | archived (paywalled) |

## Mode Status

| Mode | State | Notes |
|------|-------|-------|
| off | Available | Default — canonical pipeline ignored |
| shadow | Available | Loads canonical, logs comparison, serves legacy |
| **internal_primary** | **VALIDATED** | Serves canonical via scaffold endpoints, legacy unchanged |
| primary | Not ready | Blocked by offense tier (53.6% < 65%) and founder approval |
