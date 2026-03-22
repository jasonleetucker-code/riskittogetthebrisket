# Source Integration Tracker

_Updated: 2026-03-22 (piecewise calibration curve — all public-primary metric thresholds PASS)_

## Pipeline

```
14 Source CSVs → ScraperBridge/DLF Adapters → Identity Resolution
  → Canonical Blend (weight v4, KTC=1.2 highest)
  → Position Enrichment (legacy + nickname + supplemental + IDP infer = 85.1%)
  → Scarcity Adjustment (0.30 dampened VAR, 1032 assets)
  → Calibration (piecewise: exp=2.5, knee=0.65, offense=7800, IDP=5000, rookie=7000)
  → Canonical Snapshot (1241 assets)
```

## Source Freshness (2026-03-22)

| Source | Method | Status | Players |
|--------|--------|--------|---------|
| FantasyCalc | API | **FRESH** | 458 |
| DLF_SF | Local CSV | **FRESH** | 278 |
| DLF_IDP | Local CSV | **FRESH** | 185 |
| DLF_RSF | Local CSV | **FRESH** | 66 |
| DLF_RIDP | Local CSV | **FRESH** | 30 |
| DraftSharks | Browser | **FRESH** | 486 |
| DynastyDaddy | Browser | **FRESH** | 364 |
| DynastyNerds | Browser | **FRESH** | 168 |
| FantasyPros | Browser | **FRESH** | 303 |
| FantasyPros_IDP | Browser | **FRESH** | 70 |
| IDPTradeCalc | Browser | **FRESH** | 384 |
| PFF_IDP | Browser | **FRESH** | 249 |
| Yahoo | Browser | **FRESH** | 307 |
| **KTC** | **Browser** | **CONSUMED** | **500** |

## Current Metrics (14 sources, all thresholds PASS)

| Metric | Previous | Current | Threshold | Status |
|--------|----------|---------|-----------|--------|
| Sources | 14 | 14 | ≥6 | PASS |
| Blend | 61% | 61% | ≥60% | PASS |
| Top-50 | 92% | 92% | ≥80% | PASS |
| Top-100 | 93% | 93% | ≥75% | PASS |
| Tier | 61.5% | **66.3%** | ≥65% | **PASS** |
| Delta | 879 | **742** | ≤800 | **PASS** |

## Calibration Curve

**Piecewise power curve (v3):**
- Percentile ≥ 0.65: `scale * percentile^2.5` (standard power curve)
- Percentile < 0.65: linear ramp from 0 to curve value at knee

This fixes the systematic bench→depth deflation in the bottom of each universe.
The top 65% of the distribution is unchanged from v2.

## Position-Level Tier Agreement

| Position | Count | Tier % | Avg Delta |
|----------|-------|--------|-----------|
| QB | 86 | 74.1% | 723 |
| WR | 193 | 71.1% | 683 |
| TE | 90 | 66.7% | 646 |
| RB | 148 | 59.2% | 742 |

RB remains the weakest position but is no longer a blocker for public-primary.
