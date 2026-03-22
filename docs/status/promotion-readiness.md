# Promotion Readiness Status

_Updated: 2026-03-22 (final pre-launch polish pass complete)_

## Current State: **PUBLIC_PRIMARY METRIC-READY — 10/12 PASS**

All automated metric checks pass. Only founder approval remains.

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

| Metric | v1 (exp=2.0, no KTC) | v2 (exp=2.5, +KTC) | v3 (piecewise) | Final |
|--------|----------------------|---------------------|----------------|-------|
| Sources | 13 | 14 | 14 | 14 |
| Blend | 57% FAIL | 61% PASS | 61% PASS | 61% PASS |
| Top-50 | 92% PASS | 92% PASS | 92% PASS | 92% PASS |
| Top-100 | 92% PASS | 93% PASS | 93% PASS | 93% PASS |
| Tier | 50.1% FAIL | 61.5% FAIL | **66.3% PASS** | **66.3% PASS** |
| Delta | 1006 FAIL | 879 FAIL | **742 PASS** | **742 PASS** |
| Pub-primary | 7/12 | 9/12 | **10/12** | **10/12** |

## Position-Level Tier Agreement

| Position | v1 | v2 | v3/Final |
|----------|-----|-----|----------|
| QB | 55.3% | 74.1% | **74.4%** |
| WR | 46.8% | 67.2% | **71.0%** |
| TE | 51.7% | 63.2% | **66.3%** |
| RB | 35.2% | 56.3% | **62.2%** |

## Final Pre-Launch Polish Pass (2026-03-22)

**Phase A — RB-specific polish:**
Tested scarcity weight (0.10-0.30) x calibration knee (0.65-0.70) grid.
No tested change improved the system. Reducing scarcity helps RBs but damages QB/WR/TE
by more. Current config is the best launch candidate.

**Phase B — KTC freshness reliability:**
- Scraper manifest now tracks `siteRawFresh` vs `siteRawPreserved` per-source
- `source_pull.py` now warns explicitly when KTC contributes 0 records
- `canonical_build.py` now logs per-source record/asset counts
- KTC freshness is now visible at every pipeline stage

**Phase C — Final checkpoint:**
All metrics stable. 408 tests pass. KTC confirmed at 500 records.

## KTC Freshness Visibility

After every pipeline run, look for these signals:

```
[source_pull] KTC: 500 records ingested ✓           # healthy
[source_pull] ⚠ KTC: 0 records ingested — ...       # problem

[canonical_build] sources: ... KTC=500r/500a ...     # healthy
```

The scraper manifest (`exports/latest/manifest.json`) now includes:
- `siteRawFresh`: list of CSVs produced this run
- `siteRawPreserved`: list of CSVs carried forward from a previous run

## Activation Steps

1. **Founder approval** — grant approval
2. Run `python -m pytest tests/ --ignore=tests/e2e -q` on production
3. Set `CANONICAL_DATA_MODE=public_primary` on production
4. Verify via `curl /api/data | jq '.metadata.data_mode'`

---

_408 tests pass. Thresholds from config/promotion/promotion_thresholds.json._
