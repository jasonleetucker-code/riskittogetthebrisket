# Promotion Readiness Status

_Updated: 2026-03-22 (post enrichment + player-only + weight retune)_

## Current State: OFF (default) — **INTERNAL_PRIMARY READY**

### Shadow Mode: READY (3/3 hard checks pass)

### Internal Primary: READY (9/9 hard checks pass, 1 manual verification)

| Check | Required | Actual | Status |
|-------|----------|--------|--------|
| Source count >= 4 | 4 | **14** | PASS |
| Top-50 overlap >= 70% | 70% | **72%** | **PASS** |
| Top-100 overlap >= 65% | 65% | **81%** | **PASS** |
| Tier agreement >= 50% | 50% | **56.8%** | **PASS** |
| Avg |delta| <= 1500 | 1500 | **988** | **PASS** |
| Sample size >= 500 | 500 | 838 | PASS |
| Multi-source blend >= 40% | 40% | 54% | PASS |
| IDP sources >= 2 | 2 | 5 | PASS |
| Weights tuned | Yes | Yes (v4) | PASS |
| Tests pass | Yes | 351 pass | PASS (manual) |

**All hard metric thresholds now pass. The canonical system can be promoted to internal_primary when the founder is ready.**

### Public Primary: NOT READY (6/12 pass)

| Check | Required | Actual | Status |
|-------|----------|--------|--------|
| Top-50 overlap >= 80% | 80% | 72% | FAIL (-8%) |
| Tier agreement >= 65% | 65% | 56.8% | FAIL (-8.2%) |
| Avg delta <= 800 | 800 | 988 | FAIL (+188) |
| Multi-source blend >= 60% | 60% | 54% | FAIL (-6%) |
| Founder approval | Yes | No | FAIL |

### What Changed This Phase

| Metric | Before | After | Improvement |
|--------|--------|-------|-------------|
| Position coverage | 64.7% | **77.1%** | +19% |
| Scarcity-adjusted | 797 | **952** | +19% |
| Offense top-50 (players) | 54% | **72%** | **+33%** |
| Offense top-100 (players) | — | **81%** | New metric |
| Offense tier agreement | 40.0% | **56.8%** | **+42%** |
| Offense avg delta | 1436 | **988** | **-31%** |
| Internal-primary passes | 7/10 | **9/10** | +2 (all hard checks pass) |

---

_All comparison metrics now use offense_players_only view (excludes picks). 351 tests pass._
