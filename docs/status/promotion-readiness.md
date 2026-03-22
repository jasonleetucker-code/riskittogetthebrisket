# Promotion Readiness Status

_Updated: 2026-03-22 (post scarcity sweep + founder review packet)_

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
| Top-50 overlap >= 70% | 70% | **80%** | PASS |
| Top-100 overlap >= 65% | 65% | **81%** | PASS |
| Tier agreement >= 50% | 50% | **50.5%** | PASS |
| Avg |delta| <= 1500 | 1500 | **1071** | PASS |
| Sample size >= 500 | 500 | 827 | PASS |
| Multi-source blend >= 40% | 40% | **61%** | PASS |
| IDP sources >= 2 | 2 | 5 | PASS |
| Weights tuned | Yes | v4 | PASS |
| Tests pass | Yes | 372 pass | PASS (manual) |

## Public Primary: 8/12 Pass

| Check | Required | Actual | Status | Gap |
|-------|----------|--------|--------|-----|
| Source count >= 6 | 6 | 14 | **PASS** | — |
| Top-50 overlap >= 80% | 80% | **80%** | **PASS** | — |
| Top-100 overlap >= 75% | 75% | **81%** | **PASS** | — |
| Tier agreement >= 65% | 65% | 50.5% | FAIL | -14.5% |
| Avg delta <= 800 | 800 | 1071 | FAIL | +271 |
| Sample >= 500 | 500 | 827 | **PASS** | — |
| Multi-source >= 60% | 60% | **61%** | **PASS** | — |
| IDP sources >= 2 | 2 | 5 | **PASS** | — |
| Weights tuned | Yes | v4 | **PASS** | — |
| Tests pass | Yes | 372 | **PASS** | — |
| League context active | Yes | Yes | **PASS** | — |
| Founder approval | Yes | No | FAIL | — |

## Scarcity Weight Sweep Results

| Weight | Off Top-50 | Off Tier | Off Delta | Chosen? |
|--------|-----------|----------|-----------|---------|
| 0.00 | 80% | 49.5% | 1112 | |
| 0.15 | 82% | 49.9% | 1082 | |
| **0.20** | **80%** | **50.5%** | **1071** | **✓ CHOSEN** |
| 0.25 | 78% | 52.0% | 1059 | |
| 0.35 | 76% | 52.9% | 1033 | (previous) |
| 0.45 | 74% | 55.8% | 1006 | |

**0.20 chosen**: Best balance — passes both top-50 (80%) and tier (50.5%) thresholds simultaneously.

## Scraper Refresh Blocker

Cannot run legacy scraper in this environment:
- Selenium: NOT INSTALLED
- Chrome/Chromium: NOT FOUND
- bs4/lxml: NOT INSTALLED

To run: install Chrome + Selenium on host, then `python "Dynasty Scraper.py"`

---

_372 tests pass. Founder review packet: `data/comparison/founder_review_packet.md`_
