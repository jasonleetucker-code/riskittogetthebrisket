# Promotion Readiness Status

_Updated: 2026-03-22_

## Mode Progression

```
off → shadow → internal_primary → public_primary
```

Each mode has concrete, measurable requirements defined in `config/promotion/promotion_thresholds.json` and checked by `scripts/check_promotion_readiness.py`.

---

## Current State: OFF (default)

The canonical pipeline runs and produces snapshots, but `CANONICAL_DATA_MODE=off` means server.py ignores them entirely. Legacy scraper values are the sole authority.

### Shadow Mode: EFFECTIVELY READY

| Check | Required | Actual | Status |
|-------|----------|--------|--------|
| Canonical snapshot exists | Yes | Yes | PASS |
| Asset count >= 500 | 500 | 747 | PASS |
| Source count >= 2 | 2 | 5 | PASS |
| Tests pass | Yes | 268 pass | PASS |

**Shadow mode can be safely activated** by setting `CANONICAL_DATA_MODE=shadow`. It attaches comparison data to the API response but does not change any live values.

### Internal Primary: NOT READY (6 failures)

| Check | Required | Actual | Status | Blocker |
|-------|----------|--------|--------|---------|
| Source count >= 4 | 4 | 5 | PASS | |
| Top-50 overlap >= 70% | 70% | 62% | FAIL | Need more sources for convergence |
| Top-100 overlap >= 65% | 65% | 63% | FAIL | Same |
| Tier agreement >= 50% | 50% | 13.4% | FAIL | Scale mapping difference (percentile vs Z-score) |
| Avg |delta| <= 1500 | 1500 | 2903 | FAIL | Fundamental with only 2 sources |
| Sample size >= 500 | 500 | 670 | PASS | |
| Multi-source blend >= 40% | 40% | 35% | FAIL | Need KTC/DynastyDaddy CSVs |
| IDP sources >= 2 | 2 | 2 | PASS | |
| Weights tuned | Yes | No | FAIL | All 1.0 — founder decision needed |
| Tests pass | Yes | 268 pass | PASS | |

### Public Primary: NOT READY (9 failures)

Stricter thresholds than internal_primary, plus:
- League context engine must be active (src/league/ is empty)
- Founder must explicitly approve

---

## What Must Happen to Reach Internal Primary

1. **Get more scraper CSVs flowing** (KTC + DynastyDaddy at minimum) — this is config-only, no code needed
2. **Tune source weights** — founder must decide relative weights
3. **Improve tier agreement** — likely needs normalization curve adjustment or more sources
4. **Multi-source blend above 40%** — follows from getting more offense_vet sources

## What Must Happen to Reach Public Primary

Everything above, plus:
- 6+ sources active
- League context engine (`src/league/`) with real implementation
- Top-50 overlap >= 80%
- Avg |delta| <= 800
- 14+ days in internal_primary
- Founder approval

---

## Running the Checks

```bash
# Check all modes
python scripts/check_promotion_readiness.py

# Check specific mode
python scripts/check_promotion_readiness.py --target internal_primary

# Machine-readable output
python scripts/check_promotion_readiness.py --json
```

The promotion readiness check is also available at runtime via `GET /api/scaffold/promotion`.

---

## 0f83 Weighting Branch: RETIRED

The previously referenced "0f83" weighting branch does not exist in this repository. Exhaustive search of all branches, commits, stashes, and code found zero references. There is exactly one weighting implementation: `src/canonical/transform.py:blend_source_values()` reading from `config/weights/default_weights.json`. No competing weighting logic exists. This decision is final.

---

_This document reflects measured reality, not aspirations. All numbers come from actual pipeline runs and comparison batches._
