# Source Integration Tracker

_Updated: 2026-03-22 (Phase E — enrichment + player-only + weight retune)_

---

## Active Sources (in canonical pipeline)

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
| DraftSharks | 490 | **0.5** | Real (archived scraper export) |
| DynastyNerds | 12 | 0.6 | Real (partial, paywalled) |
| IDPTradeCalc | 383 | 1.0 | Real (archived scraper export) |
| PFF IDP | 249 | 0.7 | Real (archived scraper export) |
| FantasyPros IDP | 70 | 0.6 | Real (archived scraper export) |

**14 active sources. All real data. Weight version 4.**

## Pipeline Processing Stages

```
Source CSVs → Adapter → Identity Resolution → Canonical Blend (weighted)
  → Position Enrichment (legacy + nickname + IDP inference)
  → Scarcity Adjustment (dampened VAR, 35% weight)
  → Universe-Aware Calibration (offense=8500, idp=5000, picks=7500, K≤600)
  → Canonical Snapshot
```

## Position Coverage

| Source | Count | Method |
|--------|------:|--------|
| DLF adapters | 559 | Rank-suffix parsing |
| Legacy enrichment | 251 | Cross-reference _lamBucket |
| Nickname matching | 3 | Cam→Cameron, etc. |
| IDP universe inference | 152 | IDP universe + IDP-only sources → LB |
| Picks (skipped) | 108 | Correctly excluded |
| Unmatched | 178 | Single-source assets not in legacy |
| **Total coverage** | **965/1251 (77.1%)** | |

## Key Metrics (offense players only)

| Metric | Value | Threshold |
|--------|-------|-----------|
| Top-50 overlap | **72%** | 70% ✓ |
| Top-100 overlap | **81%** | 65% ✓ |
| Tier agreement | **56.8%** | 50% ✓ |
| Avg delta | **988** | 1500 ✓ |
| Internal-primary | **9/10 pass** | All hard checks pass |

---

_All sources use real scraper export data. No test seeds._
