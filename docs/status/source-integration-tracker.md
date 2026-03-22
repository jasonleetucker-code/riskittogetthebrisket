# Source Integration Tracker

_Updated: 2026-03-22 (fresh scraper + scarcity 0.30 + fresh legacy)_

## Pipeline

```
Source CSVs → Adapter → Identity Resolution (initial collapsing + suffix cleanup)
  → Canonical Blend (14 sources, weight v4)
  → Position Enrichment (legacy + nickname + supplemental + IDP infer = 81.4%)
  → Scarcity Adjustment (dampened 30% VAR, 996 assets)
  → Player Calibration (offense=8500, IDP=5000, K≤600)
  → Pick Calibration (legacy curve)
  → Canonical Snapshot
```

## Key Metrics

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
| **Internal-primary** | **9/9 PASS** | — | — |
| **Public-primary** | **8/12** | — | — |

## Source Freshness

| Source | Date | Status |
|--------|------|--------|
| FantasyCalc | 2026-03-22 | **FRESH** |
| DLF (4 CSVs) | 2026-03-22 | **FRESH** |
| KTC | 2026-03-09 | archived |
| DynastyDaddy | 2026-03-09 | archived |
| DraftSharks | 2026-03-09 | archived |
| FantasyPros | 2026-03-09 | archived |
| Yahoo | 2026-03-09 | archived |
| DynastyNerds | 2026-03-09 | archived |
| IDPTradeCalc | 2026-03-09 | archived |
| PFF_IDP | 2026-03-09 | archived |
| FantasyPros_IDP | 2026-03-09 | archived |
| DraftSharks_IDP | 2026-03-09 | archived |
