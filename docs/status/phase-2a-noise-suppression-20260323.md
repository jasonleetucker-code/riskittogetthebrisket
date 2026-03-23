# Phase 2A: Noise Suppression — Before/After Report

**Date:** 2026-03-23
**Scope:** `src/trade/suggestions.py` — quality filter pipeline only
**Method:** 10 roster shapes, live canonical snapshot (2026-03-22T210702Z)
**Status:** Implemented, tested, deterministic

---

## Founder-Readable Summary

The suggestion feed was dominated by repetition and noise. 52.5% of all
suggestions featured the same outgoing player appearing 3 times, and the
engine showed trades it knew were unfair (attaching "balancers" as an
afterthought). This phase fixes those problems with four narrowly-scoped
filter additions.

### What changed
- **Outgoing player cap lowered from 3 to 2.** No player dominates the feed.
- **Same-tier swaps suppressed.** WR-for-WR within 500 value is lateral
  movement, not a trade idea. These are now filtered out.
- **Fair-but-weak trades suppressed.** Both sides below 2000 display value?
  Not worth negotiating. Filtered.
- **Near-miss 1-for-1s suppressed.** If the engine attaches balancers and
  the gap exceeds 400, the trade is really a package deal — showing it as
  a 1-for-1 is misleading. Filtered.

### Impact
- **Before:** 40 suggestions across 6 active rosters
- **After:** 34 suggestions across 6 active rosters
- **Removed:** 7 low-quality suggestions (5 repetitive, 2 unrealistic 1-for-1s)
- **Added:** 1 new suggestion (previously blocked player now has room)
- **Net reduction:** 15% fewer suggestions, 100% quality-relevant removals
- **Zero good suggestions lost.** Every removal is defensible.

### What was NOT changed
- No ranking formula changes
- No scoring/calibration changes
- No UI changes
- No API contract changes (additive constants exported, no fields removed)
- No roster analysis changes
- Core architecture untouched

---

## Before/After: All 40 Suggestions Compared

### REMOVED (7 suggestions)

| # | Roster | Category | Trade | Gap | Removal Reason |
|---|--------|----------|-------|-----|----------------|
| 5 | contender_balanced | buy_low | Fred Warner (LB, 6089) → Kevin Winston (DB, 6502) | -413 | **F5: near-miss 1-for-1** — gap 413 with balancers attached; should be a package deal |
| 12 | rb_heavy | buy_low | De'Von Achane (RB, 9641) → Drake Maye (QB, 9721) | -80 | **F1: repetitive** — De'Von Achane's 3rd appearance (cap now 2) |
| 13 | rb_heavy | buy_low | Jonathan Taylor (RB, 9408) → JSN (WR, 9485) | -77 | **F1: repetitive** — Jonathan Taylor's 3rd appearance (cap now 2) |
| 20 | wr_heavy | buy_low | CeeDee Lamb (WR, 8988) → Jayden Daniels (QB, 9603) | -615 | **F5: near-miss 1-for-1** — gap 615 with balancers attached; needs a sweetener |
| 23 | te_premium | sell_high | Trey McBride (TE, 9761) → Ja'Marr Chase (WR, 9563) | +198 | **F1: repetitive** — Trey McBride's 3rd appearance (cap now 2) |
| 28 | te_premium | sell_high | Tucker Kraft (TE, 8148) → Dak Prescott (QB, 8042) | +106 | **F1: repetitive** — Tucker Kraft's 3rd appearance (cap now 2) |
| 31 | idp_stacked | sell_high | Myles Garrett (DL, 6812) → Kyler Murray (QB, 6770) | +42 | **F1: repetitive** — Myles Garrett's 3rd appearance (cap now 2) |

### NEW (1 suggestion — previously blocked)

| Roster | Category | Trade | Gap | Why it appeared |
|--------|----------|-------|-----|-----------------|
| idp_stacked | sell_high | Abdul Carter (DL, 6694) → Kevin Winston (DB, 6502) | +192 | Myles Garrett no longer consumes 3 slots; Abdul Carter gets room in the feed |

### KEPT (33 suggestions — all unchanged)

| # | Roster | Category | Trade | Gap | Fair | Conf |
|---|--------|----------|-------|-----|------|------|
| 1 | contender_balanced | sell_high | Fred Warner (LB) → Kyle Hamilton (DB) | -37 | even | med |
| 2 | contender_balanced | sell_high | Nick Bolton (LB) → Nick Emmanwori (DB) | -181 | even | med |
| 3 | contender_balanced | sell_high | CJ Allen (LB) → Nick Emmanwori (DB) | -37 | even | low |
| 4 | contender_balanced | buy_low | Fred Warner (LB) → Caleb Downs (DB) | -321 | lean | low |
| 6 | rb_heavy | sell_high | De'Von Achane (RB) → Jayden Daniels (QB) | +38 | even | high |
| 7 | rb_heavy | sell_high | De'Von Achane (RB) → Ja'Marr Chase (WR) | +78 | even | high |
| 8 | rb_heavy | sell_high | Jonathan Taylor (RB) → Joe Burrow (QB) | -38 | even | high |
| 9 | rb_heavy | sell_high | Jonathan Taylor (RB) → Puka Nacua (WR) | +38 | even | high |
| 10 | rb_heavy | sell_high | James Cook (RB) → Patrick Mahomes (QB) | -39 | even | high |
| 11 | rb_heavy | sell_high | James Cook (RB) → Amon-Ra St. Brown (WR) | +37 | even | high |
| 14 | wr_heavy | sell_high | CeeDee Lamb (WR) → Jaxson Dart (QB) | +38 | even | high |
| 15 | wr_heavy | sell_high | Drake London (WR) → Trevor Lawrence (QB) | -37 | even | high |
| 16 | wr_heavy | sell_high | Drake London (WR) → Breece Hall (RB) | +74 | even | high |
| 17 | wr_heavy | sell_high | Nico Collins (WR) → Fernando Mendoza (QB) | -36 | even | high |
| 18 | wr_heavy | sell_high | Nico Collins (WR) → Saquon Barkley (RB) | +36 | even | high |
| 19 | wr_heavy | sell_high | CeeDee Lamb (WR) → Jeremiyah Love (RB) | +15 | even | low |
| 21 | te_premium | sell_high | Trey McBride (TE) → Ashton Jeanty (RB) | -78 | even | high |
| 22 | te_premium | sell_high | Trey McBride (TE) → Drake Maye (QB) | +40 | even | high |
| 24 | te_premium | sell_high | Tyler Warren (TE) → TreVeyon Henderson (RB) | -37 | even | high |
| 25 | te_premium | sell_high | Tyler Warren (TE) → Drake London (WR) | -149 | even | high |
| 26 | te_premium | sell_high | Tucker Kraft (TE) → Chase Brown (RB) | -35 | even | high |
| 27 | te_premium | sell_high | Tucker Kraft (TE) → Garrett Wilson (WR) | +72 | even | high |
| 29 | idp_stacked | sell_high | Myles Garrett (DL) → Emmanuel McNeil-Warren (DB) | -159 | even | low |
| 30 | idp_stacked | sell_high | Myles Garrett (DL) → Jaylen Waddle (WR) | +10 | even | med |
| 32 | idp_stacked | sell_high | Carson Schwesinger (LB) → Tyler Shough (QB) | +69 | even | med |
| 33 | idp_stacked | sell_high | Jack Campbell (LB) → Tyler Shough (QB) | +182 | even | med |
| 34 | idp_stacked | sell_high | Maxx Crosby (DL) → Kyler Murray (QB) | -36 | even | med |
| 35 | idp_stacked | sell_high | Maxx Crosby (DL) → Jaylen Waddle (WR) | -68 | even | med |
| 36 | idp_stacked | sell_high | Abdul Carter (DL) → Jameson Williams (WR) | +51 | even | med |
| 37 | shallow_everywhere | sell_high | Zack Baun (LB) → Budda Baker (DB) | +68 | even | med |
| 38 | shallow_everywhere | sell_high | Quay Walker (LB) → Danielle Hunter (DL) | -34 | even | med |
| 39 | shallow_everywhere | sell_high | Quay Walker (LB) → Trevon Moehrig (DB) | -69 | even | low |
| 40 | shallow_everywhere | sell_high | Zack Baun (LB) → Danielle Hunter (DL) | -69 | even | med |

---

## Technical Appendix

### Exact Filter Stages Added

The quality filter pipeline in `_apply_quality_filters()` now has 7 stages
(was 4). New stages 4-6 are inserted before the cross-category give-player
cap (now stage 7). All stages are order-preserving (remove only, never reorder).

| Stage | Filter | Trigger | Effect |
|-------|--------|---------|--------|
| 1 | Consolidation stretch | `fairness == "stretch"` | Remove | (existing) |
| 2 | Receive-target cap | Same receive target > 2x per category | Remove later ones | (existing) |
| 3 | Low-confidence cap | `confidence == "low"` > 2x per category | Remove later ones | (existing) |
| **4** | **Fair-but-weak** | All players in trade `< MIN_ACTIONABLE_VALUE (2000)` | **Remove** | NEW |
| **5** | **Same-tier swap** | 1-for-1, same position, value diff < 500 | **Remove** | NEW |
| **6** | **Near-miss 1-for-1** | 1-for-1, `abs(gap) > MAX_GAP_FOR_1FOR1 (400)`, has balancers | **Remove** | NEW |
| 7 | Give-player cap | Player appears > `MAX_GIVE_PLAYER_APPEARANCES (2)` cross-category | Remove later ones | (existing, cap lowered 3→2) |

### New Constants Added

```python
MIN_ACTIONABLE_VALUE = 2000    # Both sides must exceed this
MAX_GAP_FOR_1FOR1 = 400        # Max gap before 1-for-1 becomes misleading
MAX_GIVE_PLAYER_APPEARANCES = 2  # Was 3; lowered after audit
```

### Determinism

All new filters are pure functions of the suggestion data. No randomness,
no external state, no time-dependence. The full pipeline test
(`TestNewFiltersDeterministic::test_full_pipeline_deterministic`) confirms
identical outputs across runs.

### Exact Files Changed

| File | Lines Changed | What |
|------|--------------|------|
| `src/trade/suggestions.py:59` | Config | `MAX_GIVE_PLAYER_APPEARANCES` 3→2 |
| `src/trade/suggestions.py:70-77` | Config | Added `MIN_ACTIONABLE_VALUE`, `MAX_GAP_FOR_1FOR1` |
| `src/trade/suggestions.py:791-828` | Logic | 3 new filter stages in `_apply_quality_filters()` |
| `tests/test_trade_suggestions.py:13-35` | Imports | Added new constants |
| `tests/test_trade_suggestions.py:720-765` | Tests | Updated existing tests for cap=2 |
| `tests/test_trade_suggestions.py:835-1010` | Tests | 5 new test classes, 15 new test methods |

### Exact Tests Added

| Test Class | Tests | What It Validates |
|------------|-------|-------------------|
| `TestFairButWeakFilter` | 3 | Both-sides-low suppressed; one-side-high kept; boundary kept |
| `TestSameTierSwapFilter` | 4 | Same-pos close-value removed; large gap kept; cross-pos kept; multi-player kept |
| `TestNearMiss1For1Filter` | 4 | Big gap + balancers removed; small gap kept; no balancers kept; multi-player kept |
| `TestTightenedGivePlayerCap` | 3 | Cap is 2; 3rd blocked; different players unaffected |
| `TestNewFiltersDeterministic` | 1 | Full pipeline produces identical results |

**Total tests: 66 (was 51, added 15)**

### API Contract

No breaking changes. Two new constants are exported (`MIN_ACTIONABLE_VALUE`,
`MAX_GAP_FOR_1FOR1`) but no response fields were added or removed. The
`_apply_quality_filters` function signature is unchanged. All existing
serialized output fields remain identical.

### Rollback Instructions

To revert to pre-Phase-2A behavior:

```python
# In src/trade/suggestions.py:
MAX_GIVE_PLAYER_APPEARANCES = 3   # was 2, revert to 3

# Delete these two constants:
# MIN_ACTIONABLE_VALUE = 2000
# MAX_GAP_FOR_1FOR1 = 400

# In _apply_quality_filters(), remove stages 4, 5, and 6
# (the three new filter blocks between "Cap low-confidence" and
# "Cross-category give-player cap")
```

Or simply: `git revert <commit-hash>`

The new test classes (`TestFairButWeakFilter`, `TestSameTierSwapFilter`,
`TestNearMiss1For1Filter`, `TestTightenedGivePlayerCap`,
`TestNewFiltersDeterministic`) should also be removed or updated if reverting.
