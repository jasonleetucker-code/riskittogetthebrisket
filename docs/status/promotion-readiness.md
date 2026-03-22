# Promotion Readiness Status

_Updated: 2026-03-22 (post position-enrichment + universe-aware calibration)_

## Mode Progression

```
off → shadow → internal_primary → public_primary
```

---

## Current State: OFF (default)

### Shadow Mode: READY (3/3 hard checks pass)

### Internal Primary: NOT READY (7/10 pass)

| Check | Required | Actual | Status | Trend |
|-------|----------|--------|--------|-------|
| Source count >= 4 | 4 | **14** | PASS | 5→7→14 |
| Top-50 overlap >= 70% | 70% | 54% (offense) | FAIL | 64%→40%→**54%** |
| Top-100 overlap >= 65% | 65% | **66%** | **PASS** | 63%→42%→**66%** |
| Tier agreement >= 50% | 50% | 40.0% (offense) | FAIL | 13.6%→23.9%→**40.0%** |
| Avg |delta| <= 1500 | 1500 | **1436** (offense) | **PASS** | 2975→2225→**1436** |
| Sample size >= 500 | 500 | **838** | PASS | 670→838 |
| Multi-source blend >= 40% | 40% | **54%** | PASS | 35%→54% |
| IDP sources >= 2 | 2 | **5** | PASS | 2→5 |
| Weights tuned | Yes | Yes | PASS | — |
| Tests pass | Yes | 341 pass | PASS | 268→297→**341** |

### What Changed This Phase

| Metric | Before | After | Improvement |
|--------|--------|-------|-------------|
| Position coverage | 44.7% (559) | **64.7% (810)** | +45% |
| Scarcity-adjusted | 559 | **797** | +43% |
| Avg delta (offense) | 2225 | **1436** | **-35%** |
| Tier agreement (offense) | 13.6% | **40.0%** | **+194%** |
| Top-100 overlap | 42% | **66%** | **+57%** |
| Internal-primary passes | 5/10 | **7/10** | +2 new passes |

### New Passes This Phase

1. **avg_abs_delta_max**: 1436 ≤ 1500 (was 2225)
2. **top100_overlap_min_pct**: 66% ≥ 65% (was 42%)

### What Still Blocks Internal Primary

1. **Top-50 overlap (54%, need 70%)**: Position-less assets from single sources (DraftSharks, KTC newcomers) rank high because scarcity can't adjust them. Fixing position coverage for these 345 unmatched assets would help. Also, the canonical system ranks some players differently than legacy due to multi-source consensus vs legacy's single-source weighting.

2. **Tier agreement (40.0%, need 50%)**: Improved nearly 3x but still below threshold. Root cause: ~27% of offense assets still lack position data and get inflated calibrated values.

### Universe-Aware Comparison (new this phase)

| Universe | Players | Avg Delta | Top-N Overlap | Tier Agreement |
|----------|---------|-----------|---------------|----------------|
| **Offense Combined** | 565 | 1436 | 54% | 40.0% |
| IDP Combined | 273 | 1334 | 64% | 53.5% |
| IDP Vet | 252 | 1347 | 68% | 54.4% |

_IDP metrics are now healthy. Offense is the remaining bottleneck._

---

_All numbers from actual pipeline runs. Promotion readiness uses offense_combined view for overlap/tier/delta metrics._
