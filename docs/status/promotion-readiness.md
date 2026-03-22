# Promotion Readiness Status

_Updated: 2026-03-22 (piecewise calibration curve — all metric thresholds PASS)_

## Current State: **PUBLIC_PRIMARY METRIC-READY — 10/12 PASS**

All automated metric checks pass. Only founder approval and test verification remain.

## Internal Primary: 10/10 Pass

| Check | Required | Actual | Status |
|-------|----------|--------|--------|
| Source count >= 4 | 4 | **14** | PASS |
| Top-50 overlap >= 70% | 70% | **92%** | PASS |
| Top-100 overlap >= 65% | 65% | **93%** | PASS |
| Tier agreement >= 50% | 50% | **66.3%** | PASS |
| Avg |delta| <= 1500 | 1500 | **742** | PASS |
| Sample size >= 500 | 500 | 1055 | PASS |
| Multi-source blend >= 40% | 40% | **61%** | PASS |
| IDP sources >= 2 | 2 | 5 | PASS |
| Weights tuned | Yes | v4 | PASS |
| Tests pass | Yes | 408 pass | PASS |

## Public Primary: 10/12 Pass — Only Founder Approval Remains

| Check | Required | Actual | Status | Margin |
|-------|----------|--------|--------|--------|
| Source count >= 6 | 6 | 14 | **PASS** | +8 |
| Top-50 overlap >= 80% | 80% | **92%** | **PASS** | +12% |
| Top-100 overlap >= 75% | 75% | **93%** | **PASS** | +18% |
| Tier agreement >= 65% | 65% | **66.3%** | **PASS** | +1.3% |
| Avg delta <= 800 | 800 | **742** | **PASS** | -58 |
| Sample >= 600 | 600 | 1055 | **PASS** | +455 |
| Multi-source >= 60% | 60% | **61%** | **PASS** | +1% |
| IDP sources >= 2 | 2 | 5 | **PASS** | +3 |
| Weights tuned | Yes | v4 | **PASS** | — |
| Tests pass | Yes | 408 | **PASS** | — |
| League context active | Yes | Yes | **PASS** | — |
| Founder approval | Yes | No | **FAIL** | — |

## Full Progress History

| Metric | v1 (exp=2.0, no KTC) | v2 (exp=2.5, +KTC) | v3 (piecewise knee=0.65) |
|--------|----------------------|---------------------|--------------------------|
| Sources | 13 | 14 | 14 |
| Blend | 57% FAIL | 61% PASS | 61% PASS |
| Top-50 | 92% PASS | 92% PASS | 92% PASS |
| Top-100 | 92% PASS | 93% PASS | 93% PASS |
| Tier | 50.1% FAIL | 61.5% FAIL | **66.3% PASS** |
| Delta | 1006 FAIL | 879 FAIL | **742 PASS** |
| Pub-primary | 7/12 | 9/12 | **10/12** |

## Position-Level Tier Agreement

| Position | v1 | v2 | v3 (current) |
|----------|-----|-----|-------------|
| QB | 55.3% | 74.1% | **74.1%** |
| WR | 46.8% | 67.2% | **71.1%** |
| TE | 51.7% | 63.2% | **66.7%** |
| RB | 35.2% | 56.3% | **59.2%** |

## What Changed

**Piecewise calibration curve:** For the bottom 35% of each universe (percentile < 0.65),
the steep power curve (`7800 * p^2.5`) is replaced with a linear ramp from 0 to the curve's
value at the knee. This fixes the systematic bench→depth deflation that was hitting RBs hardest
(41 RBs were pushed from bench to depth tier).

The top 65% of the distribution uses the same power curve as before — elite/star rankings
are unchanged.

## Remaining Steps to Public-Primary

1. **Founder approval** — all metrics pass, this is the only remaining gate
2. Run `python -m pytest tests/ --ignore=tests/e2e -q` on production to verify tests
3. Set `CANONICAL_DATA_MODE=public_primary` on production

## Validation Phase Summary

| Milestone | Status |
|-----------|--------|
| Canonical pipeline built (14 sources) | Done |
| KTC consumed by pipeline (500 players) | Done |
| Calibration v3: piecewise knee=0.65 | Done |
| Scraper site_raw preservation | Done |
| All metric thresholds PASS | **Done** |
| 408 tests passing | Done |
| **Founder approval** | **Pending** |

---

_408 tests pass. Thresholds from config/promotion/promotion_thresholds.json._
