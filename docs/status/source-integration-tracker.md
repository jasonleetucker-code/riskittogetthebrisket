# Source Integration Tracker

_Updated: 2026-03-22 (Phase D — real exports + scarcity + calibration)_

---

## Active Sources (in canonical pipeline)

| Source | Adapter | Records | Universe | Signal | Weight | Data Origin |
|--------|---------|--------:|----------|--------|-------:|-------------|
| DLF Superflex | `DlfCsvAdapter` | 278 | offense_vet | rank_avg | 1.0 | Real (manual CSV) |
| DLF IDP | `DlfCsvAdapter` | 185 | idp_vet | rank_avg | 1.0 | Real (manual CSV) |
| DLF Rookie SF | `DlfCsvAdapter` | 66 | offense_rookie | rank_avg | 1.0 | Real (manual CSV) |
| DLF Rookie IDP | `DlfCsvAdapter` | 30 | idp_rookie | rank_avg | 1.0 | Real (manual CSV) |
| FantasyCalc | `ScraperBridgeAdapter` | 451 | offense_vet | value | 1.0 | **Real** (scraper export) |
| KTC | `ScraperBridgeAdapter` | 500 | offense_vet | value | **1.2** | **Real** (archived scraper export 2026-03-09) |
| DynastyDaddy | `ScraperBridgeAdapter` | 336 | offense_vet | value | **0.8** | **Real** (archived scraper export 2026-03-09) |
| Yahoo | `ScraperBridgeAdapter` | 457 | offense_vet | value | 0.7 | **Real** (archived scraper export 2026-03-09) |
| FantasyPros | `ScraperBridgeAdapter` | 303 | offense_vet | value | 0.7 | **Real** (archived scraper export 2026-03-09) |
| DraftSharks | `ScraperBridgeAdapter` | 490 | offense_vet | rank | 0.7 | **Real** (archived scraper export 2026-03-09) |
| DynastyNerds | `ScraperBridgeAdapter` | 12 | offense_vet | rank | 0.6 | Real (partial, paywalled) |
| IDPTradeCalc | `ScraperBridgeAdapter` | 383 | idp_vet | value | 1.0 | **Real** (archived scraper export 2026-03-09) |
| PFF IDP | `ScraperBridgeAdapter` | 249 | idp_vet | rank | 0.7 | **Real** (archived scraper export 2026-03-09) |
| FantasyPros IDP | `ScraperBridgeAdapter` | 70 | idp_vet | rank | 0.6 | **Real** (archived scraper export 2026-03-09) |

**14 active sources. 3810 total records. 1251 canonical assets.**
**759 multi-source blended (61%). Up to 8-source blending for top offense players.**
**All sources are now REAL data — no test seeds in use.**

## Pipeline Processing Stages

```
Source CSVs → ScraperBridgeAdapter → Identity Resolution → Canonical Blend (weighted)
  → Scarcity Adjustment (value above replacement) → Distribution Calibration (8500 * p^2.0)
  → Canonical Snapshot
```

## Key Metrics

- **Sources active**: 14 (was 7)
- **Total records**: 3810 (was 1791)
- **Canonical assets**: 1251 (was 747)
- **Multi-source blended**: 759 / 1251 (61%)
- **Position metadata coverage**: 559 / 1251 (45%)
- **Scarcity-adjusted assets**: 559
- **Calibration**: All 1251 assets calibrated (8500 * p^2.0)

---

_All sources use real scraper export data extracted from archived exports._
