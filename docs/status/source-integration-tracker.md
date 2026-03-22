# Source Integration Tracker

_Updated: 2026-03-22 (corrected checkpoint: collision fix + config-driven thresholds)_

## Pipeline

```
14 Source CSVs → ScraperBridge/DLF Adapters → Identity Resolution
  → Canonical Blend (weight v4)
  → Position Enrichment (legacy + nickname + supplemental + IDP infer = 81.4%)
  → Scarcity Adjustment (0.30 dampened VAR, 996 assets)
  → Calibration (offense=8500, IDP=5000, picks=legacy curve)
  → Canonical Snapshot (1239 assets)
```

## Corrected Metrics (2026-03-22)

| Metric | Value | Int-Primary | Pub-Primary |
|--------|-------|-------------|-------------|
| Sources | 14 | PASS (>=4) | PASS (>=6) |
| Assets | 1239 | — | — |
| Position coverage | 81.4% | — | — |
| Scarcity-adjusted | 996 | — | — |
| Multi-source blend | **61%** | PASS (>=40) | PASS (>=60) |
| Off players top-50 | **82%** | PASS (>=70) | **PASS (>=80)** |
| Off players top-100 | **84%** | PASS (>=65) | PASS (>=75) |
| Off players tier | **53.5%** | PASS (>=50) | FAIL (>=65) |
| Off players delta | **999** | PASS (<=1500) | FAIL (<=800) |
| Overall delta | **764** | — | PASS (<=800) |
| Overall tier | **64.8%** | — | — |
| IDP tier | **74.0%** | — | — |
| **Internal-primary** | **9/9 PASS** | **VALIDATED** | — |
| **Public-primary** | **8/12** | — | 3 remaining |

## What Changed from Collision Fix

| Metric | Before | After | Change |
|--------|--------|-------|--------|
| Off top-50 | 78% | **82%** | **+4% — blocker cleared** |
| Off delta | 1006 | **999** | -7 |
| Off tier | 53.4% | **53.5%** | +0.1% |

## Remaining Public-Primary Blockers

| Blocker | Gap | Root Cause | Fix |
|---------|-----|-----------|-----|
| Offense tier | 53.5% vs 65% | 162 players: canonical 1 tier higher | Full scraper run |
| Offense delta | 999 vs ≤800 | Same 162 players | Full scraper run |
| Founder approval | Not given | Manual | After metrics clear |
