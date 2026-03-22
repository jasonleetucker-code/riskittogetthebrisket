# Source Integration Tracker

_Updated: 2026-03-22 (Phase D — position enrichment + universe-aware calibration)_

---

## Active Sources (in canonical pipeline)

| Source | Adapter | Records | Universe | Signal | Weight | Data Origin |
|--------|---------|--------:|----------|--------|-------:|-------------|
| DLF Superflex | `DlfCsvAdapter` | 278 | offense_vet | rank_avg | 1.0 | Real (manual CSV) |
| DLF IDP | `DlfCsvAdapter` | 185 | idp_vet | rank_avg | 1.0 | Real (manual CSV) |
| DLF Rookie SF | `DlfCsvAdapter` | 66 | offense_rookie | rank_avg | 1.0 | Real (manual CSV) |
| DLF Rookie IDP | `DlfCsvAdapter` | 30 | idp_rookie | rank_avg | 1.0 | Real (manual CSV) |
| FantasyCalc | `ScraperBridgeAdapter` | 451 | offense_vet | value | 1.0 | Real (scraper export) |
| KTC | `ScraperBridgeAdapter` | 500 | offense_vet | value | 1.2 | Real (archived scraper export 2026-03-09) |
| DynastyDaddy | `ScraperBridgeAdapter` | 336 | offense_vet | value | 0.8 | Real (archived scraper export 2026-03-09) |
| Yahoo | `ScraperBridgeAdapter` | 457 | offense_vet | value | 0.7 | Real (archived scraper export 2026-03-09) |
| FantasyPros | `ScraperBridgeAdapter` | 303 | offense_vet | value | 0.7 | Real (archived scraper export 2026-03-09) |
| DraftSharks | `ScraperBridgeAdapter` | 490 | offense_vet | rank | 0.7 | Real (archived scraper export 2026-03-09) |
| DynastyNerds | `ScraperBridgeAdapter` | 12 | offense_vet | rank | 0.6 | Real (partial, paywalled) |
| IDPTradeCalc | `ScraperBridgeAdapter` | 383 | idp_vet | value | 1.0 | Real (archived scraper export 2026-03-09) |
| PFF IDP | `ScraperBridgeAdapter` | 249 | idp_vet | rank | 0.7 | Real (archived scraper export 2026-03-09) |
| FantasyPros IDP | `ScraperBridgeAdapter` | 70 | idp_vet | rank | 0.6 | Real (archived scraper export 2026-03-09) |

**14 active sources. 3810 total records. 1251 canonical assets.**
**759 multi-source blended (61%). Up to 8-source blending for top offense players.**
**All sources are now REAL data — no test seeds in use.**

## Pipeline Processing Stages

```
Source CSVs → ScraperBridgeAdapter → Identity Resolution → Canonical Blend (weighted)
  → Position Enrichment (legacy _lamBucket)
  → Scarcity Adjustment (value above replacement)
  → Universe-Aware Calibration (offense=8500, idp=5000, picks=7500, kickers≤600)
  → Canonical Snapshot
```

## Position Coverage

| Source | Coverage | Method |
|--------|----------|--------|
| DLF adapters | 559 assets | Rank-suffix parsing ("WR1", "LB12") |
| Legacy enrichment | +251 assets | Cross-reference _lamBucket by name |
| Picks (skipped) | 96 assets | Correctly excluded from position |
| Unmatched | 345 assets | Single-source assets not in legacy |
| **Total coverage** | **810/1251 (64.7%)** | |

## Key Metrics

- **Sources active**: 14
- **Total records**: 3810
- **Canonical assets**: 1251
- **Multi-source blended**: 759 / 1251 (61%)
- **Position metadata coverage**: 810 / 1251 (64.7%)
- **Scarcity-adjusted assets**: 797
- **Calibration**: Universe-aware (offense=8500, IDP=5000, picks=7500)
- **Avg |delta| (offense)**: 1436
- **Top-50 overlap (offense)**: 54%
- **Tier agreement (offense)**: 40.0%
- **Internal-primary checks**: 7/10 pass

---

_All sources use real scraper export data. No test seeds in production pipeline._
