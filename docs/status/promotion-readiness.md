# Promotion Readiness Status

_Updated: 2026-03-22 (corrected checkpoint: collision fix + config-driven thresholds)_

## Current State: **INTERNAL_PRIMARY VALIDATED — 9/9 PASS**

Activate: `export CANONICAL_DATA_MODE=internal_primary` and restart.
Rollback: `export CANONICAL_DATA_MODE=off` and restart.

## Internal Primary: 9/9 Hard Checks Pass

| Check | Required | Actual | Status |
|-------|----------|--------|--------|
| Source count >= 4 | 4 | **14** | PASS |
| Top-50 overlap >= 70% | 70% | **82%** | PASS |
| Top-100 overlap >= 65% | 65% | **84%** | PASS |
| Tier agreement >= 50% | 50% | **53.5%** | PASS |
| Avg |delta| <= 1500 | 1500 | **999** | PASS |
| Sample size >= 500 | 500 | 830 | PASS |
| Multi-source blend >= 40% | 40% | **61%** | PASS |
| IDP sources >= 2 | 2 | 5 | PASS |
| Weights tuned | Yes | v4 | PASS |
| Tests pass | Yes | 399 pass | PASS |

## Public Primary: 8/12 Pass, 3 Hard Fails

| Check | Required | Actual | Status | Gap |
|-------|----------|--------|--------|-----|
| Source count >= 6 | 6 | 14 | **PASS** | — |
| Top-50 overlap >= 80% | 80% | **82%** | **PASS** | +2% |
| Top-100 overlap >= 75% | 75% | **84%** | **PASS** | +9% |
| Tier agreement >= 65% | 65% | 53.5% | **FAIL** | **-11.5%** |
| Avg delta <= 800 | 800 | 999 | **FAIL** | **+199** |
| Sample >= 600 | 600 | 830 | **PASS** | — |
| Multi-source >= 60% | 60% | **61%** | **PASS** | — |
| IDP sources >= 2 | 2 | 5 | **PASS** | — |
| Weights tuned | Yes | v4 | **PASS** | — |
| Tests pass | Yes | 399 | **PASS** | — |
| League context active | Yes | Yes | **PASS** | — |
| Founder approval | Yes | No | **FAIL** | — |

## What Changed from Collision Fix

The collision fix resolved a bug where 74 players appearing in both rookie and vet
universes had the wrong entry kept. After the fix:

| Metric | Before Fix | After Fix | Change |
|--------|-----------|-----------|--------|
| Offense top-50 | 78% | **82%** | **+4% — now passes 80% threshold** |
| Offense delta | 1006 | **999** | -7 |
| Offense tier | 53.4% | **53.5%** | +0.1% |

**Top-50 overlap was a blocker and is now cleared.**

## Remaining Gap Analysis

The two remaining metric fails are both driven by the same root cause:
**162 offense players where canonical is exactly 1 tier higher than legacy.**

| Tier shift | Players | Avg delta |
|------------|---------|-----------|
| star → elite | 39 | 1637 |
| starter → star | 55 | 1686 |
| bench → starter | 40 | 1102 |
| depth → bench | 28 | 1165 |
| **Canonical 1 tier higher total** | **162** | **~1450** |

Only 53 of these 162 would need to resolve to reach 65% tier agreement.
If they resolve, the projected avg delta drops to ~569 (well under 800).

**Root cause**: Legacy ran with 2 sources (FantasyCalc + DLF). The 9 missing
browser-scraped sources would raise legacy values for these mid-tier players.
A full 11-source legacy scraper run is the single action most likely to close
both remaining gaps simultaneously.

---

_399 tests pass. Thresholds from config/promotion/promotion_thresholds.json._
_Founder review packet: `data/comparison/founder_review_packet.md`_
