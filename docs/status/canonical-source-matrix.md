# Canonical Pipeline -- Source Integration Matrix

_Updated: 2026-04-08 (scope reduction to 2 sources)_

## Active Sources

Only two sources are active after scope reduction:

| Source | Adapter | Universe | Signal | File |
|--------|---------|----------|--------|------|
| **KTC** | ScraperBridgeAdapter | offense_vet | value | exports/latest/site_raw/ktc.csv |
| **IDPTRADECALC** | ScraperBridgeAdapter | idp_vet | value | exports/latest/site_raw/idpTradeCalc.csv |

## Adapter Architecture

```
Dynasty Scraper.py (scrapes KTC + IDPTradeCalc)
         |
    exports/latest/site_raw/ktc.csv
    exports/latest/site_raw/idpTradeCalc.csv
         |
  ScraperBridgeAdapter (src/adapters/scraper_bridge_adapter.py)
    signal_type="value" -> stores value_raw (higher=better)
         |
  source_pull.py -> canonical_build.py -> data/canonical/
```

## Removed Sources

The following sources were removed in the 2026-04-08 scope reduction:
- DLF (all 4 universes: SF, IDP, RSF, RIDP)
- FantasyCalc
- DynastyDaddy
- Yahoo
- FantasyPros (offense + IDP)
- DraftSharks (offense + IDP)
- DynastyNerds
- Flock
- PFF IDP
- KTC Stub (legacy adapter)

## Removed Adapters

- DlfCsvAdapter (was used for DLF CSV imports)
- KtcStubAdapter (legacy scaffold)
- ManualCsvAdapter (placeholder, never implemented)
