# Source Integration Tracker

_Updated: 2026-04-08 (scope reduction to 2 sources: KTC + IDP Trade Calculator)_

## Pipeline

```
2 Source CSVs -> ScraperBridge Adapter -> Identity Resolution
  -> Canonical Blend (KTC=1.2, IDPTRADECALC=1.0)
  -> Position Enrichment
  -> Calibration
  -> Canonical Snapshot
```

## Active Sources

| Source | Universe | Method | Signal | Players | Notes |
|--------|----------|--------|--------|---------|-------|
| KTC (KeepTradeCut) | offense_vet | Browser | value | ~500 | Primary offense source |
| IDPTradeCalc | idp_vet | Browser | value | ~384 | Primary IDP source |

All other sources have been removed as part of scope reduction.

## Source Reliability

| Source | Reliability | Risk | Notes |
|--------|-------------|------|-------|
| KTC | High | Medium | Sometimes fails in sandbox, preserved from previous run |
| IDPTradeCalc | High | Medium | Primary IDP source |
