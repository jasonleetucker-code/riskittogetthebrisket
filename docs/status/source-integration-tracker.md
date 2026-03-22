# Source Integration Tracker

_Updated: 2026-03-22 (KTC consumed by pipeline, calibration retuned to exp=2.5/scale=7800)_

## Pipeline

```
14 Source CSVs → ScraperBridge/DLF Adapters → Identity Resolution
  → Canonical Blend (weight v4, KTC=1.2 highest)
  → Position Enrichment (legacy + nickname + supplemental + IDP infer = 85.1%)
  → Scarcity Adjustment (0.30 dampened VAR, 1032 assets)
  → Calibration (offense=7800, IDP=5000, rookie=7000, picks=legacy curve, exp=2.5)
  → Canonical Snapshot (1241 assets)
```

## Source Freshness (2026-03-22)

| Source | Method | Status | Players | Blocker |
|--------|--------|--------|---------|---------|
| FantasyCalc | API | **FRESH** | 458 | — |
| DLF_SF | Local CSV | **FRESH** | 278 | — |
| DLF_IDP | Local CSV | **FRESH** | 185 | — |
| DLF_RSF | Local CSV | **FRESH** | 66 | — |
| DLF_RIDP | Local CSV | **FRESH** | 30 | — |
| DraftSharks | Browser | **FRESH** | 486 | — |
| DynastyDaddy | Browser | **FRESH** | 364 | — |
| DynastyNerds | Browser | **FRESH** | 168 | — |
| FantasyPros | Browser | **FRESH** | 303 | — |
| FantasyPros_IDP | Browser | **FRESH** | 70 | — |
| IDPTradeCalc | Browser | **FRESH** | 384 | — |
| PFF_IDP | Browser | **FRESH** | 249 | — |
| Yahoo | Browser | **FRESH** | 307 | — |
| **KTC** | **Browser** | **CONSUMED** | **500** | **—** |

### KTC Status

**Pipeline consumption confirmed.** KTC is now source #14 in the canonical pipeline:
- 500 players ingested via `exports/latest/site_raw/ktc.csv`
- Weight 1.2 (highest of all sources)
- Scraper export logic fixed to preserve site_raw CSVs across runs

**Previous blocker:** The scraper's export phase wiped `exports/latest/site_raw/` on each run.
When KTC scraping failed in sandbox (TLS proxy), the existing `ktc.csv` was destroyed.
Fixed by backing up and restoring site_raw CSVs for sources that didn't produce new data.

## Current Metrics (14 sources, KTC consumed)

| Metric | Before KTC | After KTC+Cal | Pub-Primary |
|--------|-----------|---------------|-------------|
| Sources | 13 | **14** | PASS (>=6) |
| Assets | 1198 | **1241** | — |
| Multi-source blend | 57% | **61%** | **PASS (>=60)** |
| Off players top-50 | 92% | **92%** | PASS (>=80) |
| Off players top-100 | 92% | **93%** | PASS (>=75) |
| Off players tier | 50.1% | **61.5%** | FAIL (>=65) |
| Off players delta | 1006 | **879** | FAIL (<=800) |
| **Public-primary** | **7/12** | **9/12** | **2 remaining + approval** |

## Remaining Public-Primary Blockers

| Blocker | Gap | Root Cause | Fix |
|---------|-----|-----------|-----|
| Offense tier | 61.5% vs 65% | RBs at 56% tier agreement | Position-specific calibration or weight tuning |
| Offense delta | 879 vs ≤800 | Correlated with tier gap | Closes with tier fix |
| Founder approval | Not given | Manual | After metrics clear |

## Calibration Sweep Results

Tested 28 combinations of exponent (2.0-3.5) × scale (7600-9500).
Best: exp=2.5, scale=7800 → tier=61.5%, delta=879, top-50=92%.
Full sweep data in `scripts/calibration_sweep.py`.

| Position | Tier % (old) | Tier % (new) | Change |
|----------|-------------|-------------|--------|
| QB | 55.3% | 74.1% | **+18.8%** |
| WR | 46.8% | 67.2% | **+20.4%** |
| TE | 51.7% | 63.2% | **+11.5%** |
| RB | 35.2% | 56.3% | **+21.1%** |

RB remains the weakest position. All other positions are at or above 63%.
