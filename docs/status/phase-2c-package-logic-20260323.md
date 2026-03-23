# Phase 2C: Package Logic for Unrealistic 1-for-1s — Before/After Report

**Date:** 2026-03-23
**Scope:** Consolidation generation, quality filtering, give-player caps
**Status:** Implemented, tested, deterministic

---

## Founder-Readable Summary

Before this change, the engine produced **zero** multi-player package trades
across all 6 test rosters. Every suggestion was a 1-for-1 swap. This
happened because of three interlocking bugs:

1. **Consolidation picked the most expensive target** instead of the
   closest-value target, maximizing the gap and ensuring all results were
   "stretch" fairness.
2. **All stretch consolidations were blanket-suppressed** by the quality
   filter — a rule that made sense before fix #1 but became overly
   aggressive after.
3. **The give-player appearance cap was shared** between 1-for-1 and
   package categories. Since sell_high was processed first, surplus
   players hit their cap before consolidation got a chance.

### What changed

Three narrow, independent fixes:

1. **Closest-value targeting** — `_generate_consolidation()` now sorts
   targets by `abs(combined - target.display_value)` instead of
   `-target.display_value`. Produces the fairest possible package.

2. **Graduated stretch filter** — Instead of blanket-suppressing all
   stretch consolidations, the quality filter now allows stretches where
   the overpay is ≤ 30% of the give total (`CONSOLIDATION_MAX_OVERPAY_RATIO`).
   A 16-21% overpay on a 2-for-1 package is realistic in dynasty.

3. **Separate give-player budgets** — 1-for-1 categories (sell_high,
   buy_low) and package categories (consolidation, positional_upgrade)
   now have independent give-player caps. A player at cap in sell_high
   can still appear in a consolidation package.

4. **Bonus: wider sweetener tolerance** — Positional upgrade sweetener
   matching is now 2× wider for surplus-position depth pieces
   (`UPGRADE_SWEETENER_SURPLUS_MULTIPLIER`). Surplus depth is expendable,
   so slightly wider tolerance is acceptable. (No live upgrades triggered
   yet due to the value ceiling, but the path is now unblocked.)

### Impact

| Metric | Before | After |
|--------|--------|-------|
| Total 1-for-1 suggestions | 34 | 34 (no regression) |
| Total multi-player packages | 0 | 5 |
| Rosters with packages | 0/6 | 3/6 |

### What was NOT changed
- No ranking formula changes
- No sell_high / buy_low generation changes
- No value calibration changes
- No UI changes
- Core 1-for-1 suggestions completely preserved

---

## Before/After: 20 Concrete Examples

### NEW: Package suggestions that now appear (were 0 before)

| # | Roster | Type | Trade | Gap | Overpay% | Fairness |
|---|--------|------|-------|-----|----------|----------|
| 1 | contender_balanced | CONS | CJ Allen(LB,5943) + Nick Bolton(LB,5799) → Jeremiyah Love(RB,9878) | +1864 | 16% | stretch |
| 2 | contender_balanced | CONS | Fred Warner(LB,6089) + Nick Bolton(LB,5799) → Jeremiyah Love(RB,9878) | +2010 | 17% | stretch |
| 3 | idp_stacked | CONS | Jack Campbell(LB,6425) + David Bailey(LB,6275) → Bijan Robinson(RB,9999) | +2701 | 21% | stretch |
| 4 | idp_stacked | CONS | Jack Campbell(LB,6425) + Carson Schwesinger(LB,6312) → Bijan Robinson(RB,9999) | +2738 | 21% | stretch |
| 5 | shallow_everywhere | CONS | Quay Walker(LB,5483) + Zack Baun(LB,5448) → Bijan Robinson(RB,9999) | +932 | 9% | stretch |

**Why these are good trades:**
- All give from SURPLUS positions (LB depth the user can afford to lose)
- All receive at NEED positions (RB/positional upgrades)
- Overpay ranges from 9-21% — realistic for dynasty 2-for-1 deals
- Each uses expendable depth pieces, not starters

### PRESERVED: Existing 1-for-1 suggestions (no regression)

| # | Roster | Trade | Gap | Fairness | Status |
|---|--------|-------|-----|----------|--------|
| 6 | contender_balanced | Fred Warner(LB) → Kyle Hamilton(DB) | -37 | even | Unchanged |
| 7 | contender_balanced | Nick Bolton(LB) → Nick Emmanwori(DB) | -181 | even | Unchanged |
| 8 | contender_balanced | CJ Allen(LB) → Nick Emmanwori(DB) | -37 | even | Unchanged |
| 9 | rb_heavy | De'Von Achane(RB) → Jayden Daniels(QB) | +38 | even | Unchanged |
| 10 | rb_heavy | De'Von Achane(RB) → Ja'Marr Chase(WR) | +78 | even | Unchanged |
| 11 | rb_heavy | Jonathan Taylor(RB) → Joe Burrow(QB) | -38 | even | Unchanged |
| 12 | wr_heavy | CeeDee Lamb(WR) → Jaxson Dart(QB) | +38 | even | Unchanged |
| 13 | wr_heavy | Drake London(WR) → Breece Hall(RB) | +74 | even | Unchanged |
| 14 | te_premium | Trey McBride(TE) → Ashton Jeanty(RB) | -78 | even | Unchanged |
| 15 | te_premium | Tyler Warren(TE) → Drake London(WR) | -149 | even | Unchanged |

### CORRECTLY SUPPRESSED: No packages for all-elite surplus

| # | Roster | Surplus Depth Range | Why No Packages |
|---|--------|-------------------|-----------------|
| 16 | rb_heavy | RB 8580-9641 | Cheapest pair combined = 17345, min_target@0.70 = 12141 > max_pool (9999) |
| 17 | wr_heavy | WR 7831-8988 | Cheapest pair combined = 15456, min_target@0.70 = 10819 > max_pool (9999) |
| 18 | te_premium | TE 8148-9761 | Cheapest pair combined = 16000+, far exceeds max_pool |

### EDGE: Correctly blocked high-overpay stretches

| # | Example | Gap | Overpay% | Result |
|---|---------|-----|----------|--------|
| 19 | Myles Garrett(6812) + Maxx Crosby(6734) → Bijan Robinson(9999) | +3547 | 26% | Allowed (< 30%) |
| 20 | Hypothetical 10000 give → 5000 receive | +5000 | 50% | Blocked (> 30%) |

---

## Technical Appendix

### Exact Trigger Rules for Package Logic

A consolidation package appears when ALL of these hold:

1. **Two surplus depth pieces exist** with `display_value >= MIN_RELEVANT_VALUE` (500)
2. **A target exists** where:
   - `combined * 0.70 <= target.display_value <= combined + FAIRNESS_TOLERANCE`
   - `target.display_value > max(piece1, piece2)` (true upgrade)
   - Target is at a need position (preferred) or any position
3. **Overpay ratio ≤ 30%**: `gap / give_total <= CONSOLIDATION_MAX_OVERPAY_RATIO`
4. **Give-player cap not exceeded** within the package budget
5. **Receive-target cap not exceeded** (max 2 per target per category)

### New Constants

```python
CONSOLIDATION_MAX_OVERPAY_RATIO = 0.30  # Max overpay for stretch consolidations
UPGRADE_SWEETENER_SURPLUS_MULTIPLIER = 2.0  # Wider tolerance for surplus sweeteners
```

### Exact Files Changed

| File | Lines Changed | What |
|------|--------------|------|
| `src/trade/suggestions.py:54-59` | Constants | Added `CONSOLIDATION_MAX_OVERPAY_RATIO`, `UPGRADE_SWEETENER_SURPLUS_MULTIPLIER` |
| `src/trade/suggestions.py:646` | Consolidation | Sort targets by closest value, not highest value |
| `src/trade/suggestions.py:713-726` | Upgrades | Sort targets ascending, try 5 instead of 3, wider surplus sweetener tolerance |
| `src/trade/suggestions.py:855-859` | Filter | Graduated stretch filter (allow ≤30% overpay) |
| `src/trade/suggestions.py:949-971` | Filter | Separate give-player budgets for 1-for-1 vs packages |
| `tests/test_trade_suggestions.py:15-40` | Imports | Added new constant imports |
| `tests/test_trade_suggestions.py:672-689` | Test fix | Updated stretch test for graduated filter |
| `tests/test_trade_suggestions.py:753-771` | Test fix | Updated give-player-cap test for separate budgets |
| `tests/test_trade_suggestions.py:1320-1475` | New tests | 6 new test classes, 10 new test methods |

### Exact Tests Added

| Test Class | Tests | What It Validates |
|------------|-------|-------------------|
| `TestConsolidationClosestValueTarget` | 1 | All consolidation gaps ≤ 30% |
| `TestConsolidationStretchFilter` | 3 | Low overpay allowed, high blocked, even/lean unaffected |
| `TestSeparateGivePlayerBudgets` | 2 | Sell_high doesn't block consolidation; within-budget cap works |
| `TestConsolidationInLiveOutput` | 3 | Deep surplus gets packages; elite surplus gets none; sell_high preserved |
| `TestPackageDeterminism` | 1 | Full pipeline deterministic with packages |

**Total tests: 500 (was 490, added 10)**

### Rollback Instructions

To revert Phase 2C only:

```bash
git revert <phase-2c-commit-hash>
```

Or manually:
1. In `_generate_consolidation()`: change `targets.sort(key=lambda t: abs(combined - t.display_value))` back to `targets.sort(key=lambda t: -t.display_value)`
2. In quality filter: change graduated stretch back to `if s.fairness != "stretch"`
3. In give-player cap: merge the two budget groups back into one
4. Remove `CONSOLIDATION_MAX_OVERPAY_RATIO` and `UPGRADE_SWEETENER_SURPLUS_MULTIPLIER`
