# Promotion Readiness Status

_Updated: 2026-03-22 (KTC consumed by pipeline + calibration retuned)_

## Current State: **INTERNAL_PRIMARY VALIDATED — 9/9 PASS**

Activate: `export CANONICAL_DATA_MODE=internal_primary` and restart.
Rollback: `export CANONICAL_DATA_MODE=off` and restart.

## Internal Primary: 9/9 Hard Checks Pass

| Check | Required | Actual | Status |
|-------|----------|--------|--------|
| Source count >= 4 | 4 | **14** | PASS |
| Top-50 overlap >= 70% | 70% | **92%** | PASS |
| Top-100 overlap >= 65% | 65% | **93%** | PASS |
| Tier agreement >= 50% | 50% | **61.5%** | PASS |
| Avg |delta| <= 1500 | 1500 | **879** | PASS |
| Sample size >= 500 | 500 | 1055 | PASS |
| Multi-source blend >= 40% | 40% | **61%** | PASS |
| IDP sources >= 2 | 2 | 5 | PASS |
| Weights tuned | Yes | v4 | PASS |
| Tests pass | Yes | 408 pass | PASS |

## Public Primary: 9/12 Pass, 2 Hard Fails + Founder Approval

| Check | Required | Actual | Status | Gap |
|-------|----------|--------|--------|-----|
| Source count >= 6 | 6 | 14 | **PASS** | +8 |
| Top-50 overlap >= 80% | 80% | **92%** | **PASS** | +12% |
| Top-100 overlap >= 75% | 75% | **93%** | **PASS** | +18% |
| Tier agreement >= 65% | 65% | 61.5% | **FAIL** | **-3.5%** |
| Avg delta <= 800 | 800 | 879 | **FAIL** | **+79** |
| Sample >= 600 | 600 | 1055 | **PASS** | — |
| Multi-source >= 60% | 60% | **61%** | **PASS** | +1% |
| IDP sources >= 2 | 2 | 5 | **PASS** | — |
| Weights tuned | Yes | v4 | **PASS** | — |
| Tests pass | Yes | 408 | **PASS** | — |
| League context active | Yes | Yes | **PASS** | — |
| Founder approval | Yes | No | **FAIL** | — |

## Progress: Before → After

| Metric | Before KTC | After KTC + Calibration | Change |
|--------|-----------|------------------------|--------|
| Source count | 13 | **14** | +1 |
| Multi-source blend | 57% | **61%** | **+4% → PASS** |
| Top-50 overlap | 92% | **92%** | — |
| Top-100 overlap | 92% | **93%** | +1% |
| Tier agreement | 50.1% | **61.5%** | **+11.4%** |
| Avg delta | 1006 | **879** | **-127** |
| Public-primary fails | 4 | **2 + approval** | **-2 blockers cleared** |

## What Changed

**KTC consumed by pipeline:** `exports/latest/site_raw/ktc.csv` restored from
raw snapshot data (500 players). Pipeline now ingests KTC as source #14 with
weight 1.2 (highest). Scraper export logic fixed to preserve site_raw CSVs
from previous runs when a source fails (prevents KTC wipe in sandbox).

**Calibration retuned:** Exponent 2.0 → 2.5, offense_vet scale 8500 → 7800,
offense_rookie 8500 → 7000. Chosen via empirical sweep (`scripts/calibration_sweep.py`)
over 28 parameter combinations. The old curve compressed too many players into
the elite tier (≥7000), causing systematic 1-tier inflation for QBs 7-15 and TEs.

## What Still Blocks Public-Primary

Two metric fails remain, both small:

| Blocker | Gap | Root Cause | Likely Fix |
|---------|-----|-----------|------------|
| Tier 61.5% vs 65% | -3.5% | RBs at 56% drag average (QB 74%, WR 67%, TE 64%) | Position-specific weight or calibration |
| Delta 879 vs ≤800 | +79 | Correlated with tier mismatches | Closes with tier fix |
| Founder approval | Manual | — | After metrics clear |

## Validation Phase Summary

| Milestone | Status |
|-----------|--------|
| Canonical pipeline built (13+ sources) | Done |
| Collision bugs fixed (all 3 consumers) | Done |
| Config-driven thresholds | Done |
| Proxy-aware browser (11 sources fresh) | Done |
| KTC failure diagnosed (proxy TLS) | Done |
| KTC health check script | Done |
| KTC freshness reporting | Done |
| Shadow/comparison/block layers aligned | Done |
| Internal-primary validated | Done |
| Scarcity weight tuned (0.30) | Done |
| 408 tests passing | Done |
| **KTC consumed by pipeline** | **Done — 500 players, weight 1.2** |
| **Calibration retuned** | **Done — exp=2.5, scale=7800** |
| **Scraper site_raw preservation** | **Done — prevents KTC wipe** |
| Public-primary decision | 2 metrics + founder approval remain |

---

_408 tests pass. Thresholds from config/promotion/promotion_thresholds.json._
