# Promotion Readiness Status

_Updated: 2026-03-22 (post internal_primary activation + pick calibration)_

## Current State: OFF — **INTERNAL_PRIMARY SAFELY ACTIVATABLE**

All 9 hard metric checks pass. The canonical system can be promoted to
`internal_primary` at the founder's discretion.

### Activation Steps

```bash
# 1. Verify readiness (should show 9/9 hard checks pass)
python scripts/check_promotion_readiness.py --target internal_primary

# 2. Activate (set env var and restart server)
export CANONICAL_DATA_MODE=internal_primary
# (or set in .env file)

# 3. Verify mode is active
curl http://localhost:8000/api/scaffold/mode

# 4. Access canonical data (internal only)
curl http://localhost:8000/api/scaffold/canonical
```

### Rollback Steps

```bash
# Set mode back to off and restart
export CANONICAL_DATA_MODE=off
```

### What internal_primary Means

- Public `/api/data` **still serves legacy data** (unchanged)
- Canonical snapshot loads and comparison runs automatically
- `/api/scaffold/canonical` serves canonical player values for internal testing
- `/api/scaffold/shadow` shows comparison report
- `/api/scaffold/mode` shows current mode status

---

## Internal Primary: 9/9 Hard Checks Pass

| Check | Required | Actual | Status |
|-------|----------|--------|--------|
| Source count >= 4 | 4 | **14** | PASS |
| Top-50 overlap >= 70% | 70% | **72%** | PASS |
| Top-100 overlap >= 65% | 65% | **81%** | PASS |
| Tier agreement >= 50% | 50% | **56.8%** | PASS |
| Avg |delta| <= 1500 | 1500 | **988** | PASS |
| Sample size >= 500 | 500 | 838 | PASS |
| Multi-source blend >= 40% | 40% | 54% | PASS |
| IDP sources >= 2 | 2 | 5 | PASS |
| Weights tuned | Yes | v4 | PASS |
| Tests pass | Yes | 372 pass | PASS (manual) |

## Public Primary: 6/12 Pass (NOT READY)

| Check | Required | Actual | Gap |
|-------|----------|--------|-----|
| Top-50 overlap >= 80% | 80% | 72% | -8% |
| Tier agreement >= 65% | 65% | 56.8% | -8.2% |
| Avg delta <= 800 | 800 | 988 | +188 |
| Multi-source blend >= 60% | 60% | 54% | -6% |
| Founder approval | Yes | No | — |

---

_372 tests pass. All comparison metrics use offense_players_only view._
