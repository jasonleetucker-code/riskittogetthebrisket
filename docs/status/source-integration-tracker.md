# Source Integration Tracker

_Generated: 2026-03-14_

This document tracks the status of every value source that the platform intends to support.

---

## Active Sources

| Source | Adapter | Config | Pipeline Status | Production Status | Notes |
|--------|---------|--------|----------------|-------------------|-------|
| DLF Superflex | `src/adapters/dlf_csv_adapter.py` | Enabled in `dlf_sources.template.json` | Runs in Jenkins via `source_pull.py` | **Seed CSV only** — adapter output not consumed by `server.py` | Fully functional adapter with fallback parsing. Uses `dlf_superflex.csv` seed. |
| DLF IDP | Same adapter | Enabled | Runs in Jenkins | **Seed CSV only** | Uses `dlf_idp.csv` seed. |
| DLF Rookie Superflex | Same adapter | Enabled | Runs in Jenkins | **Seed CSV only** | Uses `dlf_rookie_superflex.csv` seed. |
| DLF Rookie IDP | Same adapter | Enabled | Runs in Jenkins | **Seed CSV only** | Uses `dlf_rookie_idp.csv` seed. |

## Stubbed / Disabled Sources

| Source | Adapter | Config | Status | Blocker |
|--------|---------|--------|--------|---------|
| KTC (KeepTradeCut) | `src/adapters/ktc_stub_adapter.py` | **Disabled** (`"enabled": false`) | Stub reads seed CSVs only; no live scraping | Needs live scraping implementation or reliable seed pipeline |
| Manual CSV | `src/adapters/manual_csv_adapter.py` | Not configured | Placeholder — returns empty results | Needs implementation |

## Planned Sources (No Implementation)

| Source | Priority | Blueprint Reference | Notes |
|--------|----------|-------------------|-------|
| Dynasty Nerds | Medium | Blueprint §1 mentions multi-source | Would strengthen offense + rookie coverage |
| Yahoo Fantasy | Medium | Implied by multi-source strategy | No adapter, no config |
| IDPTradeCalc | Medium | Implied by IDP emphasis | Would strengthen IDP value coverage |

## Legacy Source (Production)

| Source | Status | Notes |
|--------|--------|-------|
| `Dynasty Scraper.py` multi-source scrape | **LIVE** — sole production data source | Scrapes multiple sites via Selenium/requests. Output consumed by `server.py` as `dynasty_data_*.json`. This is what actually powers the site today. |

---

## Key Metrics

- **Sources with working adapters**: 1 (DLF CSV — covers 4 universes)
- **Sources active in pipeline**: 4 DLF universes (seed CSV only, output not in production)
- **Sources in production**: 1 (legacy scraper only)
- **Sources needed for meaningful blending**: minimum 2 (DLF + KTC)

## What "Production" Means

A source is "in production" only when:
1. Its adapter runs in the canonical pipeline
2. The canonical pipeline output is consumed by `server.py`
3. Values from that source appear in the frontend

Currently **zero** new-engine sources meet all three criteria. All live data comes from the legacy scraper.

## Next Steps

1. **Enable KTC** — either implement live scraping or establish reliable seed CSV workflow
2. **Set source weights** — founder decision needed (currently all 1.0)
3. **Wire canonical output to `server.py`** — without this, no new-engine source reaches production
