# Promotion Readiness Status

_Updated: 2026-03-22 (post real-exports + scarcity + calibration)_

## Mode Progression

```
off → shadow → internal_primary → public_primary
```

---

## Current State: OFF (default)

### Shadow Mode: READY (3/3 hard checks pass)

All checks pass. Can activate with `CANONICAL_DATA_MODE=shadow`.

### Internal Primary: NOT READY (5/10 pass)

| Check | Required | Actual | Status | Trend |
|-------|----------|--------|--------|-------|
| Source count >= 4 | 4 | **14** | PASS | 5→7→14 |
| Top-50 overlap >= 70% | 70% | 40% | FAIL | 62%→50%→40%* |
| Top-100 overlap >= 65% | 65% | 45% | FAIL | 63%→59%→45%* |
| Tier agreement >= 50% | 50% | **23.9%** | FAIL | 13.4%→11.8%→**23.9%** |
| Avg |delta| <= 1500 | 1500 | **2225** | FAIL | 2903→3152→**2225** |
| Sample size >= 500 | 500 | **838** | PASS | 670→838 |
| Multi-source blend >= 40% | 40% | **54%** | PASS | 35%→53%→54% |
| IDP sources >= 2 | 2 | **5** | PASS | 2→5 |
| Weights tuned | Yes | Yes | PASS | — |
| Tests pass | Yes | 323 pass | PASS | 268→297→323 |

*Top-50/100 overlap dropped because 14 sources brought in many more IDP/pick assets that rank high in their universe but aren't in legacy's top-50.

### What Improved

| Metric | Phase start | Now | Change |
|--------|------------|-----|--------|
| Sources | 7 (2 real + 2 seed) | **14 (all real)** | +7 real sources |
| Tier agreement | 13.6% | **23.9%** | +76% improvement |
| Avg delta | 2975 | **2225** | -25% improvement |
| Total assets | 747 | **1251** | +67% |
| Multi-source | 392 | **759** | +94% |

### What Still Blocks

1. **Top-50 overlap (40%, need 70%)**: IDP/pick assets calibrated high within their universe compete with offense assets for top-50 spots. The legacy system doesn't rank IDP players this high. Fix: either filter comparison to offense-only or adjust IDP calibration to match legacy IDP value ceilings.

2. **Tier agreement (23.9%, need 50%)**: Improved 76% but still below threshold. Root cause: 692 assets lack position data → no scarcity adjustment → inflated values. Improving position data coverage from source adapters would help.

3. **Avg delta (2225, need 1500)**: Improved 25% but still above threshold. Same root cause as tier agreement — distribution calibration helped but assets without position data dilute the improvement.

### Next Steps to Close Gap

1. **Filter comparison to offense-only** or add universe-aware comparison
2. **Improve position data in bridge adapter** — extract position from legacy data when available
3. **Apply scarcity to IDP assets** — currently 692 assets lack position data for scarcity

---

## 0f83 Status: RETIRED (no branch exists)

One weighting truth: `config/weights/default_weights.json`

---

_All numbers from actual pipeline runs with real scraper data._
