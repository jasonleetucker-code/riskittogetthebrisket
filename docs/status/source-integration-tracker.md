# Source Integration Tracker

_Updated: 2026-03-22 (Phase D — identity resolution + supplemental positions)_

## Active Sources (14 real)

| Source | Records | Weight |
|--------|--------:|-------:|
| DLF Superflex | 278 | 1.0 |
| DLF IDP | 185 | 1.0 |
| DLF Rookie SF | 66 | 1.0 |
| DLF Rookie IDP | 30 | 1.0 |
| FantasyCalc | 451 | 1.0 |
| KTC | 500 | 1.2 |
| DynastyDaddy | 336 | 0.8 |
| Yahoo | 457 | 0.7 |
| FantasyPros | 303 | 0.7 |
| DraftSharks | 490 | 0.5 |
| DynastyNerds | 12 | 0.6 |
| IDPTradeCalc | 383 | 1.0 |
| PFF IDP | 249 | 0.7 |
| FantasyPros IDP | 70 | 0.6 |

## Pipeline

```
Source CSVs → Adapter → Identity Resolution (initial collapsing + suffix cleanup)
  → Canonical Blend (14 sources, weight v4)
  → Position Enrichment (legacy + nickname + supplemental + IDP infer = 82.0%)
  → Scarcity Adjustment (dampened 35% VAR, 1003 assets)
  → Player Calibration (offense=8500, IDP=5000, K≤600)
  → Pick Calibration (legacy curve)
  → Canonical Snapshot
```

## Key Metrics

| Metric | Value | Threshold | Status |
|--------|-------|-----------|--------|
| Sources | 14 | — | — |
| Assets | 1239 | — | — |
| Position coverage | 82.0% | — | — |
| Scarcity-adjusted | 1003 | — | — |
| Multi-source blend | **61%** | 60% | ✓ PASS |
| Offense players top-50 | **76%** | 70% | ✓ PASS |
| Offense players top-100 | **81%** | 65% | ✓ PASS |
| Offense players tier | **52.9%** | 50% | ✓ PASS |
| Offense players delta | **1033** | 1500 | ✓ PASS |
| IDP tier agreement | 75.6% | — | — |
| Overall avg delta | 774 | — | — |
| Overall tier agreement | 65.1% | — | — |
| **Internal-primary** | **9/10 pass** | All hard | ✓ |
| **Public-primary** | **7/12 pass** | — | — |
