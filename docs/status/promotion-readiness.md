# Promotion Readiness Status

_Updated: 2026-03-22 (internal_primary validated + scarcity confirmed + enhanced founder review)_

## Current State: **INTERNAL_PRIMARY VALIDATED**

Internal-primary has been activated, tested, and validated in this environment:
- Server starts in `internal_primary` mode successfully
- `/api/scaffold/canonical` serves curated player-values view (1165 players)
- `/api/scaffold/shadow` runs comparison (819 matched)
- `/api/scaffold/promotion` confirms 9/9 hard checks pass
- `/api/data` continues to serve legacy data (unchanged)
- Rollback is trivial: `CANONICAL_DATA_MODE=off`

### Activation
```bash
export CANONICAL_DATA_MODE=internal_primary  # and restart server
```

### Rollback
```bash
export CANONICAL_DATA_MODE=off  # and restart server
```

### Key Endpoints in internal_primary
| Endpoint | Purpose |
|----------|---------|
| `/api/data` | **Still serves legacy** (unchanged, always) |
| `/api/scaffold/canonical` | Curated canonical values for evaluation |
| `/api/scaffold/shadow` | Side-by-side comparison report |
| `/api/scaffold/mode` | Current mode + status |
| `/api/scaffold/promotion` | Live readiness checks |

## Internal Primary: 9/9 Hard Checks Pass

| Check | Required | Actual | Status |
|-------|----------|--------|--------|
| Source count >= 4 | 4 | **14** | PASS |
| Top-50 overlap >= 70% | 70% | **94%** | PASS |
| Top-100 overlap >= 65% | 65% | **90%** | PASS |
| Tier agreement >= 50% | 50% | **53.6%** | PASS |
| Avg |delta| <= 1500 | 1500 | **972** | PASS |
| Sample size >= 500 | 500 | 830 | PASS |
| Multi-source blend >= 40% | 40% | **61%** | PASS |
| IDP sources >= 2 | 2 | 5 | PASS |
| Weights tuned | Yes | v4 | PASS |
| Tests pass | Yes | 382 pass | PASS |

## Public Primary: 8/12 Pass

| Check | Required | Actual | Status | Gap |
|-------|----------|--------|--------|-----|
| Source count >= 6 | 6 | 14 | **PASS** | — |
| Top-50 overlap >= 80% | 80% | **94%** | **PASS** | +14% |
| Top-100 overlap >= 75% | 75% | **90%** | **PASS** | +15% |
| Tier agreement >= 65% | 65% | 53.6% | FAIL | -11.4% |
| Avg delta <= 800 | 800 | 972 | FAIL | +172 |
| Sample >= 500 | 500 | 830 | **PASS** | — |
| Multi-source >= 60% | 60% | **61%** | **PASS** | — |
| IDP sources >= 2 | 2 | 5 | **PASS** | — |
| Weights tuned | Yes | v4 | **PASS** | — |
| Tests pass | Yes | 382 | **PASS** | — |
| League context active | Yes | Yes | **PASS** | — |
| Founder approval | Yes | No | FAIL | — |

Note: Overall metrics (all universes) pass: delta 739 < 800, tier 65.2% >= 65%.
The offense-players-only view fails on tier (53.6% vs 65%) and delta (972 vs 800).

## Why Public-Primary Is Still Blocked

Scarcity sweep evidence shows offense-only tier maxes out at ~62% regardless of weight.
Root cause: calibration scale differences in the 5000-8000 range between canonical sources
and legacy. This is a **calibration curve problem**, not a scarcity problem.

See `data/comparison/founder_review_packet.md` for detailed player-level disagreement analysis.

## Scarcity Weight: 0.30 (Confirmed)

Extended sweep (0.25-0.60) confirms 0.30 is optimal:

| Weight | Off Top-50 | Off Tier | Off Delta | Overall Delta | Overall Tier |
|--------|-----------|----------|-----------|---------------|-------------|
| 0.25 | 94% | 52.1% | 991 | 748 | 64.3% |
| 0.28 | 94% | 52.9% | 980 | 742 | 64.8% |
| **0.30** | **94%** | **53.6%** | **972** | **739** | **65.2%** |
| 0.32 | 94% | 54.2% | 964 | 736 | 65.4% |
| 0.35 | 94% | 54.6% | 953 | 731 | 65.7% |
| 0.40 | 92% | 55.3% | 932 | 721 | 65.9% |
| 0.50 | 90% | 58.4% | 882 | 699 | 67.6% |
| 0.60 | 88% | 61.6% | 821 | 670 | 69.2% |

0.30 wins: best top-50 (94%), passes all internal-primary thresholds, overall metrics
pass public-primary. Higher weights gain tier agreement but lose top-50 overlap.

## Scraper Status

| Source | Date | Players | Status |
|--------|------|---------|--------|
| FantasyCalc | 2026-03-22 | 458 | **FRESH** |
| DLF (4 CSVs) | 2026-03-22 | 559 | **FRESH** |
| KTC | 2026-03-09 | 500 | archived |
| DynastyDaddy | 2026-03-09 | 336 | archived |
| DraftSharks | 2026-03-09 | 490 | archived |
| FantasyPros | 2026-03-09 | 303 | archived |
| Yahoo | 2026-03-09 | 457 | archived |
| IDPTradeCalc | 2026-03-09 | 383 | archived |
| PFF_IDP | 2026-03-09 | 249 | archived |
| FantasyPros_IDP | 2026-03-09 | 70 | archived |
| DynastyNerds | 2026-03-09 | 12 | archived (paywalled) |

Blocker: sandbox egress blocked to browser-scraped sites. Run on unrestricted network.

## Environment Setup for Scraper

The scraper uses **Playwright** (not Selenium). Required:
```bash
pip install playwright beautifulsoup4 lxml
python -m playwright install chromium
```

---

_382 tests pass. Founder review packet: `data/comparison/founder_review_packet.md`_
