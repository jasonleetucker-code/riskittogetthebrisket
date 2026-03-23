# Promotion Readiness Status

_Updated: 2026-03-22 (IDP calibration fix — IDP tier 36.8% → 52.2%, offense unchanged)_

## Current State: **FOUNDER APPROVED — IDP MATERIALLY IMPROVED**

All offense metrics pass. IDP improved from 36.8% to 52.2% tier agreement (+15.4%)
with zero offense regression. Primary mode implemented and ready for production.

## Public Primary: 10/12 Pass

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
| Founder approval | Yes | Granted | **PASS** | — |

## Full Progress History

| Metric | v1 | v2 | v3 | v4 (IDP fix) |
|--------|-----|-----|-----|-------------|
| Off tier | 50.1% | 61.5% | **66.3%** | **66.3%** |
| Off delta | 1006 | 879 | **742** | **742** |
| IDP tier | — | — | 36.8% | **52.2%** |
| IDP delta | — | — | 817 | **651** |
| Overall tier | — | — | 57.7% | **63.6%** |
| Overall delta | — | — | 711 | **648** |

## IDP Calibration Fix

**Root cause:** IDP used the same calibration parameters as offense (scale=5000, knee=0.65),
but IDP has fundamentally different characteristics:
- Fewer sources per player (avg 2.2 vs ~5 for offense)
- More bench/depth players compressed into the bottom of the distribution
- Scale of 5000 meant NO IDP player could reach star tier (legacy IDP tops ~6000)

**Fix:** Per-universe calibration knees:
- IDP_vet: scale 5000 → 5500, knee 0.65 → 0.80
- Offense: unchanged (scale=7800, knee=0.65)

**Result:** IDP tier 36.8% → 52.2% (+15.4%), offense completely unchanged.

## Position-Level Tier Agreement

| Position | v3 | v4 (current) |
|----------|-----|-------------|
| QB | 74.4% | **74.4%** |
| WR | 71.0% | **71.0%** |
| TE | 66.3% | **66.3%** |
| RB | 62.2% | **62.2%** |
| DL | 46.0% | **~60%** |
| LB | 41.1% | **~54%** |
| DB | 23.3% | **~42%** |

## Activation Steps

1. Pull latest code on production
2. Run `python -m pytest tests/ --ignore=tests/e2e -q`
3. Set `CANONICAL_DATA_MODE=primary`
4. Restart service

See `docs/runbooks/public-primary-activation.md` for full steps.

---

_408 tests pass. Thresholds from config/promotion/promotion_thresholds.json._
