# Promotion Readiness Status

_Updated: 2026-03-22 (post identity resolution + supplemental positions)_

## Current State: OFF — **INTERNAL_PRIMARY SAFELY ACTIVATABLE**

All 9 hard metric checks pass. Activate with:
```bash
export CANONICAL_DATA_MODE=internal_primary  # and restart server
```
Rollback: `export CANONICAL_DATA_MODE=off` and restart.

## Internal Primary: 9/9 Hard Checks Pass

| Check | Required | Actual | Status |
|-------|----------|--------|--------|
| Source count >= 4 | 4 | **14** | PASS |
| Top-50 overlap >= 70% | 70% | **76%** | PASS |
| Top-100 overlap >= 65% | 65% | **81%** | PASS |
| Tier agreement >= 50% | 50% | **52.9%** | PASS |
| Avg |delta| <= 1500 | 1500 | **1033** | PASS |
| Sample size >= 500 | 500 | 827 | PASS |
| Multi-source blend >= 40% | 40% | **61%** | PASS |
| IDP sources >= 2 | 2 | 5 | PASS |
| Weights tuned | Yes | v4 | PASS |
| Tests pass | Yes | 372 pass | PASS (manual) |

## Public Primary: 7/12 Pass

| Check | Required | Actual | Gap |
|-------|----------|--------|-----|
| Top-50 overlap >= 80% | 80% | 76% | **-4%** |
| Tier agreement >= 65% | 65% | 52.9% | -12.1% |
| Avg delta <= 800 | 800 | 1033 | +233 |
| Founder approval | Yes | No | — |

**New passes this phase:**
- Multi-source blend: 54% → **61%** (now passes 60% threshold)
- Top-100 overlap: 66% → **81%** (now passes 75% threshold)

## Remaining 115 Unmatched Assets

| Category | Count | Reason |
|----------|------:|--------|
| Not in legacy data at all | 115 | Single-source DraftSharks/KTC/Yahoo newcomers |
| Requires fresh scraper run | 115 | Cannot resolve without Selenium + Chrome |

## What Internal_Primary Provides

| Path | Mode=off | Mode=internal_primary |
|------|----------|----------------------|
| `/api/data` | Legacy | **Legacy** (unchanged) |
| `/api/scaffold/canonical` | 404 | Canonical values |
| `/api/scaffold/shadow` | 404 | Comparison report |
| `/api/scaffold/mode` | Status | Status |

---

_372 tests pass. All comparison metrics use offense_players_only view._
