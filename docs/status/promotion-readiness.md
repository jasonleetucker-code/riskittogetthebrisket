# Promotion Readiness Status

_Updated: 2026-03-22 (final validation checkpoint — all collision bugs fixed, 408 tests)_

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
| Tests pass | Yes | 408 pass | PASS |

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
| Tests pass | Yes | 408 | **PASS** | — |
| League context active | Yes | Yes | **PASS** | — |
| Founder approval | Yes | No | **FAIL** | — |

## What Blocks Public-Primary

Two metric fails and one manual gate. All three trace to the same root cause.

**The remaining metric gap (tier 53.5% vs 65%, delta 999 vs 800) is caused by the
legacy reference being a 2-source composite (FantasyCalc + DLF only).** The 9 browser-
based scraper sources cannot render in this sandbox environment — Playwright page loads
timeout at 25 seconds despite HTTP connectivity being fine.

**This is the single remaining operational blocker.** The production server
(`178.156.148.92`) has unrestricted browser rendering capability. Running the scraper
there is expected to close both metric gaps and leave only founder approval.

See `docs/runbooks/production-activation-runbook.md` for exact steps.

## Validation Phase Summary

| Milestone | Status |
|-----------|--------|
| Canonical pipeline built (14 sources) | Done |
| Collision bugs fixed (all 3 consumers) | Done |
| Config-driven thresholds | Done |
| Shadow/comparison/block layers aligned | Done |
| Internal-primary validated | Done |
| Scarcity weight tuned (0.30) | Done |
| 408 tests passing | Done |
| Founder review (14/20 canonical right) | Done |
| **Production scraper run** | **BLOCKED — needs Hetzner host** |
| Public-primary decision | Pending production run |

---

_408 tests pass. Thresholds from config/promotion/promotion_thresholds.json._
