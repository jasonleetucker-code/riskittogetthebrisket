# Source Integration Tracker

_Updated: 2026-03-22_
_Previous version: 2026-03-14_

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

## Ready Sources (adapter exists, awaiting scraper CSV export)

These sources can be activated with a config entry only — no adapter code needed.

| Source | Adapter | Signal Type | Export File Expected | Status |
|--------|---------|-------------|---------------------|--------|
| KTC | `ScraperBridgeAdapter` | value | `exports/latest/site_raw/ktc.csv` | **CSV not present** — scraper last run did not export it |
| DynastyDaddy | `ScraperBridgeAdapter` | value | `exports/latest/site_raw/dynastyDaddy.csv` | CSV not present |
| Yahoo | `ScraperBridgeAdapter` | value | `exports/latest/site_raw/yahoo.csv` | CSV not present |
| FantasyPros | `ScraperBridgeAdapter` | value | `exports/latest/site_raw/fantasyPros.csv` | CSV not present |
| DraftSharks | `ScraperBridgeAdapter` | rank | `exports/latest/site_raw/draftSharks.csv` | CSV not present |
| IDPTradeCalc | `ScraperBridgeAdapter` | value | `exports/latest/site_raw/idpTradeCalc.csv` | CSV not present |
| DynastyNerds | `ScraperBridgeAdapter` | rank | `exports/latest/site_raw/dynastyNerds.csv` | CSV not present |
| Flock | `ScraperBridgeAdapter` | rank | `exports/latest/site_raw/flock.csv` | CSV not present |
| PFF IDP | `ScraperBridgeAdapter` | rank | `exports/latest/site_raw/pffIdp.csv` | CSV not present |
| DraftSharks IDP | `ScraperBridgeAdapter` | value | `exports/latest/site_raw/draftSharksIdp.csv` | CSV not present |
| FantasyPros IDP | `ScraperBridgeAdapter` | rank | `exports/latest/site_raw/fantasyProsIdp.csv` | CSV not present |

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
- **Sources with multi-source blending**: 1 universe (offense_vet: DLF_SF + FANTASYCALC)
- **Sources ready but awaiting CSV**: 11 (all legacy scraper sites not currently exporting)
- **Sources in production** (live on website): 0 — canonical pipeline output not yet consumed by `server.py` in primary mode
- **Shadow comparison**: Wired — `CANONICAL_DATA_MODE=shadow` attaches canonical values to `/api/data` payload

## What "Active in Pipeline" Means

A source is "active in the canonical pipeline" when:
1. Its adapter runs in `scripts/source_pull.py`
2. Records appear in `data/raw_sources/raw_source_snapshot_*.json`
3. Values appear in `data/canonical/canonical_snapshot_*.json`

FantasyCalc and all 4 DLF sources meet these criteria.

## What "In Production" Means

A source is "in production" only when:
1. Active in the canonical pipeline (above)
2. Canonical pipeline output consumed by `server.py` in primary mode
3. Values from that source appear in the frontend

Currently **zero** canonical sources meet all three criteria. The shadow comparison path is wired but only serves comparison data, not authoritative values.

## Next Steps

1. **Get more scraper CSVs** — The primary blocker is that the latest scraper run only exported DLF + FantasyCalc CSVs. When KTC/DynastyDaddy/etc. exports appear, adding them is config-only.
2. **Set source weights** — Founder decision needed (currently all 1.0).
3. **Phase D: Wire canonical → server.py primary mode** — Required before any canonical source reaches production.
