# Promotion Readiness Status

_Updated: 2026-03-22 (KTC format fix applied — playersArray, production reachable, awaiting full scrape)_

## Current State: **INTERNAL_PRIMARY VALIDATED — 9/9 PASS**

Activate: `export CANONICAL_DATA_MODE=internal_primary` and restart.
Rollback: `export CANONICAL_DATA_MODE=off` and restart.

## Internal Primary: 9/9 Hard Checks Pass

| Check | Required | Actual | Status |
|-------|----------|--------|--------|
| Source count >= 4 | 4 | **13** | PASS |
| Top-50 overlap >= 70% | 70% | **92%** | PASS |
| Top-100 overlap >= 65% | 65% | **92%** | PASS |
| Tier agreement >= 50% | 50% | **50.1%** | PASS |
| Avg |delta| <= 1500 | 1500 | **1006** | PASS |
| Sample size >= 500 | 500 | 1051 | PASS |
| Multi-source blend >= 40% | 40% | **57%** | PASS |
| IDP sources >= 2 | 2 | 5 | PASS |
| Weights tuned | Yes | v4 | PASS |
| Tests pass | Yes | 408 pass | PASS |

## Public Primary: 7/12 Pass, 4 Hard Fails

| Check | Required | Actual | Status | Gap |
|-------|----------|--------|--------|-----|
| Source count >= 6 | 6 | 13 | **PASS** | — |
| Top-50 overlap >= 80% | 80% | **92%** | **PASS** | +12% |
| Top-100 overlap >= 75% | 75% | **92%** | **PASS** | +17% |
| Tier agreement >= 65% | 65% | 50.1% | **FAIL** | **-14.9%** |
| Avg delta <= 800 | 800 | 1006 | **FAIL** | **+206** |
| Sample >= 600 | 600 | 1051 | **PASS** | — |
| Multi-source >= 60% | 60% | 57% | **FAIL** | **-3%** |
| IDP sources >= 2 | 2 | 5 | **PASS** | — |
| Weights tuned | Yes | v4 | **PASS** | — |
| Tests pass | Yes | 408 | **PASS** | — |
| League context active | Yes | Yes | **PASS** | — |
| Founder approval | Yes | No | **FAIL** | — |

## What Blocks Public-Primary

Three metric fails and one manual gate. All trace to KTC being missing.

**KTC is blocked in this sandbox** by an egress proxy TLS incompatibility. However,
**KTC is confirmed reachable on production** (178.156.148.92) — tested 2026-03-22 with
526 players extracted via the new `playersArray` format.

KTC format changed from `__NEXT_DATA__` to `var playersArray`. Health check and scraper
code updated in commit `c1559d4`. Full production scrape needed to prove KTC end-to-end.

Without KTC, the multi-source blend drops below 60% and tier agreement suffers because
KTC is the primary market reference. Adding ~500 KTC player values is expected to close
all three metric gaps.

## KTC Freshness Check

After any scrape run, look for this line in the output:
```
[KTC Status] FRESH — N players scraped     # success
[KTC Status] BLOCKED — reason (0 players)  # failure with diagnosis
```

Health check for production: `python scripts/check_ktc_health.py --full`

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
| **KTC fresh on production** | **READY — reachable, code fixed, awaiting full scrape** |
| Public-primary decision | Pending KTC + founder approval |

---

_408 tests pass. Thresholds from config/promotion/promotion_thresholds.json._
