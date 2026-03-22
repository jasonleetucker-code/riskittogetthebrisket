# Promotion Readiness Status

_Updated: 2026-03-22 (Phase B scraper re-run + honest anchor variance documented)_

## Current State: **INTERNAL_PRIMARY VALIDATED — 9/9 PASS**

Internal-primary is validated and ready for production activation.

### Activation
```bash
export CANONICAL_DATA_MODE=internal_primary  # and restart server
```

### Rollback
```bash
export CANONICAL_DATA_MODE=off  # and restart server
```

## Internal Primary: 9/9 Hard Checks Pass

| Check | Required | Actual | Status |
|-------|----------|--------|--------|
| Source count >= 4 | 4 | **14** | PASS |
| Top-50 overlap >= 70% | 70% | **78%** | PASS |
| Top-100 overlap >= 65% | 65% | **84%** | PASS |
| Tier agreement >= 50% | 50% | **53.4%** | PASS |
| Avg |delta| <= 1500 | 1500 | **1006** | PASS |
| Sample size >= 500 | 500 | 830 | PASS |
| Multi-source blend >= 40% | 40% | **61%** | PASS |
| IDP sources >= 2 | 2 | 5 | PASS |
| Weights tuned | Yes | v4 | PASS |
| Tests pass | Yes | 388 pass | PASS |

## Public Primary: 7/12 Pass

| Check | Required | Actual | Status | Gap |
|-------|----------|--------|--------|-----|
| Source count >= 6 | 6 | 14 | **PASS** | — |
| Top-50 overlap >= 80% | 80% | 78% | FAIL | -2% |
| Top-100 overlap >= 75% | 75% | **84%** | **PASS** | — |
| Tier agreement >= 65% | 65% | 53.4% | FAIL | -11.6% |
| Avg delta <= 800 | 800 | 1006 | FAIL | +206 |
| Sample >= 500 | 500 | 830 | **PASS** | — |
| Multi-source >= 60% | 60% | **61%** | **PASS** | — |
| IDP sources >= 2 | 2 | 5 | **PASS** | — |
| Weights tuned | Yes | v4 | **PASS** | — |
| Tests pass | Yes | 388 | **PASS** | — |
| League context active | Yes | Yes | **PASS** | — |
| Founder approval | Yes | No | FAIL | — |

## Why Metrics Vary Between Scraper Runs

The offense top-50 metric **varies between 78-94%** across scraper runs without any
canonical code change. Root cause: the scraper's DLF rookie anchor source differs
run-to-run (fallback values vs `dynasty_data.js`), producing different DLF value
scales for ~93 players near ranking boundaries.

**This is legacy reference instability, not canonical instability.** The canonical
pipeline produces identical player values across runs (0 player differences).

## Scraper Blocker

All 11 browser-based scraper sources timeout in this sandbox environment. Sites return
HTTP 200 to curl but Playwright page loads cannot complete within 25 seconds.

| Source | Status | Blocker |
|--------|--------|---------|
| FantasyCalc | FRESH (API) | — |
| DLF (4 CSVs) | FRESH (local) | — |
| KTC, DynastyDaddy, DraftSharks, FantasyPros, Yahoo, DynastyNerds, IDPTradeCalc, PFF_IDP, FantasyPros_IDP | TIMEOUT | Playwright page rendering fails at 25s in sandbox |

**To get a full legacy reference**: run on production server with unrestricted browser access.

## Canonical Direction: Confirmed

Founder review of 20 most important disagreement players:
- Canonical more right: 14
- Lean canonical: 4
- Toss-up: 1
- Legacy more right: 0

**Do not tune canonical calibration to match this incomplete legacy reference.**

---

_388 tests pass. Scarcity weight: 0.30. Founder review: `data/comparison/founder_review_packet.md`_
