# Source Integration Tracker

_Updated: 2026-03-22 (IDP calibration fix + source reliability audit)_

## Pipeline

```
14 Source CSVs → ScraperBridge/DLF Adapters → Identity Resolution
  → Canonical Blend (weight v4, KTC=1.2 highest)
  → Position Enrichment (legacy + nickname + supplemental + IDP infer = 85.1%)
  → Scarcity Adjustment (0.30 dampened VAR, 1032 assets)
  → Calibration (piecewise: exp=2.5, offense knee=0.65, IDP knee=0.80,
                  offense=7800, IDP=5500, rookie off=7000, rookie IDP=5000)
  → Canonical Snapshot (1241 assets)
```

## Source Freshness — Definitive Status (2026-03-22)

Scrape timestamp: `2026-03-22T15:10:15` | KTC updated separately at `16:50:29`

| Source | Universe | Method | Status | Players | Evidence |
|--------|----------|--------|--------|---------|----------|
| FantasyCalc | offense_vet | API | **FRESH** | 458 | Produced by scrape, API confirmed |
| KTC | offense_vet | Browser | **FRESH** | 500 | Updated separately at 16:50 |
| DynastyDaddy | offense_vet | Browser | **FRESH** | 364 | Produced by scrape |
| Yahoo | offense_vet | Browser | **FRESH** | 307 | Produced by scrape |
| FantasyPros | offense_vet | Browser | **FRESH** | 303 | Produced by scrape, values 1-101 |
| DraftSharks | offense_vet | Browser | **FRESH** | 486 | Produced by scrape |
| DynastyNerds | offense_vet | Browser | **FRESH** | 168 | Session (17 cookies), paywalled |
| DLF_SF | offense_vet | CSV | **FRESH** | 278 | Manual CSV, 2026-03-21 |
| DLF_RSF | offense_rookie | CSV | **FRESH** | 66 | Manual CSV, 2026-03-21 |
| IDPTradeCalc | idp_vet | Browser | **FRESH** | 384 | Produced by scrape |
| PFF_IDP | idp_vet | Browser | **FRESH** | 249 | Produced by scrape |
| FantasyPros_IDP | idp_vet | Browser | **FRESH** | 70 | Produced by scrape |
| DLF_IDP | idp_vet | CSV | **FRESH** | 185 | Manual CSV, 2026-03-21 |
| DLF_RIDP | idp_rookie | CSV | **FRESH** | 30 | Manual CSV, 2026-03-21 |
| DraftSharks_IDP | idp_vet | Browser | **ENABLED** | 0 | Was disabled, now enabled. Needs production scrape |
| Flock | offense_vet | Browser | **FAILED** | 0 | flock_session.json missing, no credentials |

**Summary:** 14 FRESH, 1 ENABLED (pending production scrape), 1 FAILED (no credentials)

## Source Reliability by Category

### Offense Sources (9 active, 1 failed)
| Source | Reliability | Risk | Notes |
|--------|-------------|------|-------|
| FantasyCalc | High | Low | API, no auth needed |
| KTC | High | Medium | Sometimes fails in sandbox, preserved from previous run |
| DynastyDaddy | High | Low | Stable API intercept |
| Yahoo | Medium | Medium | Article URL discovery, month-dependent |
| FantasyPros | Medium | Medium | Article URL discovery + Datawrapper iframes |
| DraftSharks | High | Low | Session-based, stable |
| DynastyNerds | Medium | High | Paywalled, session expires, 168 player ceiling |
| DLF_SF | High | Low | Manual CSV, always available |
| Flock | Failed | High | Session expired, no auto-login credentials |

### IDP Sources (5 active + 1 pending)
| Source | Reliability | Risk | Players | Notes |
|--------|-------------|------|---------|-------|
| IDPTradeCalc | High | Medium | 384 | Primary IDP source |
| PFF_IDP | Medium | High | 249 | Google search discovery, often fails |
| DLF_IDP | High | Low | 185 | Manual CSV |
| FantasyPros_IDP | Medium | Medium | 70 | Low count but stable |
| DLF_RIDP | High | Low | 30 | Rookie IDP only |
| DraftSharks_IDP | Pending | Medium | 0 | Just enabled, needs production scrape |

## Current Metrics

| Metric | v3 | v4 (IDP fix) | Threshold | Status |
|--------|-----|-------------|-----------|--------|
| Sources | 14 | 14 | ≥6 | PASS |
| Off tier | 66.3% | **66.3%** | ≥65% | PASS |
| Off delta | 742 | **742** | ≤800 | PASS |
| Off top-50 | 92% | **92%** | ≥80% | PASS |
| Off top-100 | 93% | **93%** | ≥75% | PASS |
| IDP tier | 36.8% | **52.2%** | — | +15.4% |
| IDP delta | 817 | **651** | — | -166 |
| Overall tier | 57.7% | **63.6%** | — | +5.9% |
| Overall delta | 711 | **648** | — | -63 |

## Calibration Curve (v4)

**Piecewise power curve with per-universe knees:**
- Offense: `scale=7800 * percentile^2.5`, knee=0.65 (linear below)
- IDP: `scale=5500 * percentile^2.5`, knee=0.80 (linear below)

IDP uses a higher knee (0.80 vs 0.65) because:
- Fewer sources per player (avg 2.2 vs ~5 offense)
- More bench/depth players compressed at bottom of distribution
- Previous knee=0.65 crushed 215 bench-tier IDP players into depth

## Position-Level Tier Agreement

| Position | v3 | v4 (current) |
|----------|-----|-------------|
| QB | 74.4% | **74.4%** |
| WR | 71.0% | **71.0%** |
| TE | 66.3% | **66.3%** |
| RB | 62.2% | **62.2%** |
| DL | 46.0% | **~60%** |
| LB | 41.1% | **~54%** |
| DB | 23.3% | **~42%** |

## IDP Source Density

155 IDP players have only 1 source (23% tier). 81 have 2 sources (21%).
Players with 3-4 sources achieve 55-61% tier — comparable to offense.
Enabling DraftSharks_IDP will add a 6th IDP source in the next production scrape.
