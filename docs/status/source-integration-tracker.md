# Source Integration Tracker

_Updated: 2026-03-22 (Phase D — internal_primary ready + pick calibration)_

---

## Active Sources (14 real sources, all active)

| Source | Records | Weight | Data Origin |
|--------|--------:|-------:|-------------|
| DLF Superflex | 278 | 1.0 | Real (manual CSV) |
| DLF IDP | 185 | 1.0 | Real (manual CSV) |
| DLF Rookie SF | 66 | 1.0 | Real (manual CSV) |
| DLF Rookie IDP | 30 | 1.0 | Real (manual CSV) |
| FantasyCalc | 451 | 1.0 | Real (scraper export) |
| KTC | 500 | 1.2 | Real (archived scraper export) |
| DynastyDaddy | 336 | 0.8 | Real (archived scraper export) |
| Yahoo | 457 | 0.7 | Real (archived scraper export) |
| FantasyPros | 303 | 0.7 | Real (archived scraper export) |
| DraftSharks | 490 | 0.5 | Real (archived scraper export) |
| DynastyNerds | 12 | 0.6 | Real (partial, paywalled) |
| IDPTradeCalc | 383 | 1.0 | Real (archived scraper export) |
| PFF IDP | 249 | 0.7 | Real (archived scraper export) |
| FantasyPros IDP | 70 | 0.6 | Real (archived scraper export) |

## Pipeline

```
Source CSVs → Adapter → Identity → Canonical Blend (14 sources, weight v4)
  → Position Enrichment (legacy + nickname + IDP infer = 77.1%)
  → Scarcity Adjustment (dampened 35% VAR, 952 assets)
  → Player Calibration (offense=8500, IDP=5000, K≤600)
  → Pick Calibration (legacy direct match → round curve → fallback)
  → Canonical Snapshot
```

## Key Metrics

| Metric | Value |
|--------|-------|
| Sources | 14 (all real) |
| Assets | 1251 |
| Position coverage | 77.1% (965/1251) |
| Scarcity-adjusted | 952 |
| Multi-source blend | 61% |
| **Offense players top-50** | **72%** (threshold: 70%) |
| **Offense players top-100** | **81%** (threshold: 65%) |
| **Offense players tier agreement** | **56.8%** (threshold: 50%) |
| **Offense players avg delta** | **988** (threshold: 1500) |
| Offense combined tier agreement | 63.2% |
| IDP tier agreement | 76.2% |
| Overall avg delta | 749 |
| Overall tier agreement | 67.4% |
| **Internal-primary** | **9/10 pass (all hard checks)** |
| Public-primary | 6/12 pass |
