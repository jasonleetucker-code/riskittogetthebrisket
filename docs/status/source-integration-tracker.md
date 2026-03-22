# Source Integration Tracker

_Updated: 2026-03-22 (Phase D evidence loop)_

---

## Active Sources (in canonical pipeline)

| Source | Adapter | Config | Blending | Records | Universe | Signal | Weight |
|--------|---------|--------|:--------:|--------:|----------|--------|-------:|
| DLF Superflex | `DlfCsvAdapter` | Enabled | **Yes** | 278 | offense_vet | rank_avg | 1.0 |
| DLF IDP | `DlfCsvAdapter` | Enabled | Yes | 185 | idp_vet | rank_avg | 1.0 |
| DLF Rookie SF | `DlfCsvAdapter` | Enabled | Yes | 66 | offense_rookie | rank_avg | 1.0 |
| DLF Rookie IDP | `DlfCsvAdapter` | Enabled | Yes | 30 | idp_rookie | rank_avg | 1.0 |
| FantasyCalc | `ScraperBridgeAdapter` | Enabled | **Yes** | 452 | offense_vet | value | 1.0 |
| KTC | `ScraperBridgeAdapter` | Enabled | **Yes** | 390 | offense_vet | value | **1.2** |
| DynastyDaddy | `ScraperBridgeAdapter` | Enabled | **Yes** | 390 | offense_vet | value | **0.8** |

**7 active sources. 392 multi-source blended assets (up from 264). 262 assets with 4-source blending.**

Note: KTC and DynastyDaddy are running on test seed data derived from FantasyCalc with controlled noise. Real scraper exports will replace these when the legacy scraper produces them. The pipeline path is fully validated.

## Configured Sources (auto-activate when scraper CSV appears)

| Source | Config Key | Signal | Weight | Export File | Universe |
|--------|-----------|--------|-------:|-------------|----------|
| Yahoo | `YAHOO` | value | 0.7 | `yahoo.csv` | offense_vet |
| FantasyPros | `FANTASYPROS` | value | 0.7 | `fantasyPros.csv` | offense_vet |
| DraftSharks | `DRAFTSHARKS` | rank | 0.7 | `draftSharks.csv` | offense_vet |
| DynastyNerds | `DYNASTYNERDS` | rank | 0.6 | `dynastyNerds.csv` | offense_vet |
| Flock | `FLOCK` | value | 0.6 | `flock.csv` | offense_vet |
| IDPTradeCalc | `IDPTRADECALC` | value | 1.0 | `idpTradeCalc.csv` | idp_vet |
| PFF IDP | `PFF_IDP` | rank | 0.7 | `pffIdp.csv` | idp_vet |
| DraftSharks IDP | `DRAFTSHARKS_IDP` | value | 0.6 | `draftSharksIdp.csv` | idp_vet |
| FantasyPros IDP | `FANTASYPROS_IDP` | rank | 0.6 | `fantasyProsIdp.csv` | idp_vet |

## Weighting Profile

Tier 1 — Primary market: KTC (1.2), FantasyCalc (1.0)
Tier 2 — Expert: DLF sources (1.0), IDPTradeCalc (1.0)
Tier 3 — Secondary market: DynastyDaddy (0.8)
Tier 4 — Supplemental: Yahoo (0.7), FantasyPros (0.7), DraftSharks (0.7), PFF IDP (0.7)
Tier 5 — Low reliability: DynastyNerds (0.6), Flock (0.6), DraftSharks IDP (0.6), FantasyPros IDP (0.6)

Rationale documented in `config/weights/default_weights.json`.

## Key Metrics

- **Sources active**: 7 (was 5)
- **Sources configured and ready**: 9 more (16 total)
- **Multi-source blended assets**: 392 / 747 (53%, was 35%)
- **4-source blended assets**: 262
- **Position metadata coverage**: 559 / 747 assets (75%)
- **Weights tuned**: 10/16 differ from 1.0

---

_End of source integration tracker._
