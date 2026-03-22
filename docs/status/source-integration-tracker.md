# Source Integration Tracker

_Updated: 2026-03-22 (Phase B completion)_
_Previous version: 2026-03-22 (pre-Phase B)_

This document tracks the factual status of every value source in the canonical pipeline.

---

## Active Sources (in canonical pipeline)

| Source | Adapter | Config | Blending | Records | Universe | Signal |
|--------|---------|--------|:--------:|--------:|----------|--------|
| DLF Superflex | `DlfCsvAdapter` | Enabled | **Yes** | 278 | offense_vet | rank_avg |
| DLF IDP | `DlfCsvAdapter` | Enabled | Yes (single) | 185 | idp_vet | rank_avg |
| DLF Rookie SF | `DlfCsvAdapter` | Enabled | Yes (single) | 66 | offense_rookie | rank_avg |
| DLF Rookie IDP | `DlfCsvAdapter` | Enabled | Yes (single) | 30 | idp_rookie | rank_avg |
| FantasyCalc | `ScraperBridgeAdapter` | Enabled | **Yes** | 452 | offense_vet | value |

**Multi-source blending**: 264 assets in offense_vet are blended across DLF_SF + FANTASYCALC.

## Configured Sources (auto-activate when scraper CSV appears)

All of these have config entries in `dlf_sources.template.json` and weight entries in `default_weights.json`. They will activate automatically when the legacy scraper exports their CSV to `exports/latest/site_raw/`.

| Source | Config Key | Signal Type | Export File | Universe | Status |
|--------|-----------|-------------|-------------|----------|--------|
| KTC | `KTC` | value | `ktc.csv` | offense_vet | **Awaiting CSV** |
| DynastyDaddy | `DYNASTYDADDY` | value | `dynastyDaddy.csv` | offense_vet | Awaiting CSV |
| Yahoo | `YAHOO` | value | `yahoo.csv` | offense_vet | Awaiting CSV |
| FantasyPros | `FANTASYPROS` | value | `fantasyPros.csv` | offense_vet | Awaiting CSV |
| DraftSharks | `DRAFTSHARKS` | rank | `draftSharks.csv` | offense_vet | Awaiting CSV |
| DynastyNerds | `DYNASTYNERDS` | rank | `dynastyNerds.csv` | offense_vet | Awaiting CSV |
| Flock | `FLOCK` | value | `flock.csv` | offense_vet | Awaiting CSV |
| IDPTradeCalc | `IDPTRADECALC` | value | `idpTradeCalc.csv` | idp_vet | Awaiting CSV |
| PFF IDP | `PFF_IDP` | rank | `pffIdp.csv` | idp_vet | Awaiting CSV |
| DraftSharks IDP | `DRAFTSHARKS_IDP` | value | `draftSharksIdp.csv` | idp_vet | Awaiting CSV |
| FantasyPros IDP | `FANTASYPROS_IDP` | rank | `fantasyProsIdp.csv` | idp_vet | Awaiting CSV |

**No code changes needed** to activate these sources. The adapter, config, and weight entries are all in place. The only blocker is that the legacy scraper's last run did not export these CSVs.

## Disabled / Superseded Sources

| Source | Adapter | Status | Notes |
|--------|---------|--------|-------|
| KTC_STUB | `KtcStubAdapter` | Disabled in config | Superseded by ScraperBridgeAdapter for KTC data |
| Manual CSV | `ManualCsvAdapter` | Placeholder | Returns empty results; not implemented |

## Legacy Source (Production)

| Source | Status | Notes |
|--------|--------|-------|
| `Dynasty Scraper.py` | **LIVE** — sole production data source | Scrapes 11+ sites. Output consumed by `server.py` as `dynasty_data_*.json`. Exports per-site CSVs to `exports/latest/site_raw/` for bridge adapter consumption. |

---

## Key Metrics

- **Adapters available**: 4 (`DlfCsvAdapter`, `KtcStubAdapter`, `ManualCsvAdapter`, `ScraperBridgeAdapter`)
- **Sources active in pipeline**: 5 (4 DLF + 1 FantasyCalc)
- **Sources configured and ready**: 11 (will auto-activate when CSVs appear)
- **Total sources when all CSVs present**: 16 (5 active + 11 configured)
- **Sources with multi-source blending**: 1 universe (offense_vet: DLF_SF + FANTASYCALC)
- **Sources in production** (live on website): 0 — canonical pipeline output not yet consumed by `server.py` in primary mode
- **Shadow comparison**: Wired — `CANONICAL_DATA_MODE=shadow` attaches canonical values to `/api/data` payload

## Weighting

There is **one weighting truth** in the repo: `config/weights/default_weights.json`.

All 16 sources have weight entries, all set to 1.0 (equal weight). This is a placeholder — founder decision needed for relative weights before promotion to internal-primary or public-primary modes.

The weighting is applied in `src/canonical/transform.py:blend_source_values()`.

No competing weighting branches or implementations exist. (The previously referenced "0f83" branch does not exist in this repo — confirmed by exhaustive search of all branches, commits, and code.)

## Test Coverage

| Component | Tests | Status |
|-----------|-------|--------|
| DlfCsvAdapter | 25+ | Complete |
| ScraperBridgeAdapter | 21 | Complete |
| Source config completeness | 8 | Complete — verifies all scraper exports have config entries |
| Graceful missing CSV handling | 3 | Complete — directory/empty/missing paths produce warnings not errors |
| Canonical transform | 40+ | Complete |
| Identity matcher | 28+ | Complete |
| Snapshot integration | 14 | Complete |

---

_End of source integration tracker._
