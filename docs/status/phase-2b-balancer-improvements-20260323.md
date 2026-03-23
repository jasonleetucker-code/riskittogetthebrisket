# Phase 2B: Balancer Improvements — Before/After Report

**Date:** 2026-03-23
**Scope:** `_find_balancers()` in `src/trade/suggestions.py`
**Method:** Direct function testing + full pipeline on live canonical data
**Status:** Implemented, tested, deterministic

---

## Founder-Readable Summary

When a trade is close but not quite fair, the engine suggests "balancers" —
small add-on players to close the gap. Before this change, balancers were
pulled from the entire asset pool with no awareness of who should add them
or whether they were realistic. The engine would suggest practice-squad
nobodies, positionless placeholders like "All Other RBs", and always
returned 3 options regardless of quality.

### What changed
- **Direction-aware.** When you're underpaying, balancers come from YOUR
  roster (your expendable depth). When you're overpaying, balancers come
  from the global pool (what the opponent could add back).
- **Roster-aware.** Your surplus-position depth pieces sort first — these
  are players you can actually afford to include.
- **Quality floor raised.** Minimum value raised from 100 to 500
  (MIN_RELEVANT_VALUE). No more suggesting waiver-wire ghosts.
- **Positionless entries filtered.** "All Other RBs" and similar
  placeholder entries are excluded.
- **Capped at 2.** Fewer, stronger suggestions instead of 3 weak ones.
- **New `balancerSide` field.** Frontend can now display "You add" vs
  "They add" context for balancers.

### Impact
The improvement is most visible on larger-gap trades. For small gaps
(< 256), nothing changes (no balancers needed). For medium gaps, the
system now honestly returns nothing when neither side has a realistic
add-on, instead of suggesting random 300-value nobodies. For large gaps
where the user has real depth, it suggests actual roster pieces the user
owns.

### What was NOT changed
- No ranking formula changes
- No scoring/calibration changes
- No UI changes (frontend can optionally use `balancerSide` field)
- No suggestion generation changes
- Filter pipeline untouched
- Core architecture untouched

---

## Before/After: 20 Concrete Balancer Examples

All examples use a "varied roster" with QB/RB/WR/LB surplus depth:
- **RB surplus depth:** Bucky Irving (8507), Kyren Williams (8006), Josh Jacobs (7729)
- **WR surplus depth:** George Pickens (8254), Ladd McConkey (7831)
- **LB surplus depth:** Fred Warner (6089), Nick Bolton (5799)

### User Underpaying (gap < 0 → "you_add")

| # | Gap | OLD Balancers | NEW Balancers | Why Better |
|---|-----|---------------|---------------|------------|
| 1 | -300 | Ashtyn Davis (DB, 299), Jalen Walthall (???, 303), Donaven McCulley (???, 295) | *none* | Honest: user has no ~300-value depth to add. Old suggested nobodies the user doesn't own. |
| 2 | -500 | Eric Rivers (WR, 499), All Other RBs (???, 496), Alex Wright (DL, 505) | *none* | "All Other RBs" is a placeholder. User has no ~500 depth pieces to offer. |
| 3 | -1000 | Drew Sanders (LB, 1000), Jacob Cowing (WR, 1001), Kaelon Black (RB, 997) | *none* | User doesn't own any of these. Suggesting them is misleading. |
| 4 | -2000 | Deommodore Lenoir (DB, 2000), Dawson Knox (TE, 2002), Justin Joly (TE, 1995) | *none* | Same — user can't add players they don't have. |
| 5 | -5000 | Diontae Johnson (WR, 5037), Tyler Bass (K, 4973), Dalvin Cook (RB, 5083) | Nick Bolton (LB, 5799), Fred Warner (LB, 6089) | Both from user's LB SURPLUS. User actually owns and can trade these. |
| 6 | -7000 | Dak Prescott (QB, 8042), C.J. Stroud (QB, 7694), Cam Ward (QB, 7557) | Josh Jacobs (RB, 7729), Ladd McConkey (WR, 7831) | From user's RB/WR SURPLUS. Old suggested QBs the user doesn't own. |
| 7 | -7500 | Ladd McConkey (WR, 7831), George Pickens (WR, 8254), Chris Olave (WR, 7866) | Josh Jacobs (RB, 7729), Ladd McConkey (WR, 7831) | Both SURPLUS pieces user owns. Old mixed in non-roster players. |
| 8 | -8000 | Quinshon Judkins (RB, 8543), Bucky Irving (RB, 8507), Kenneth Walker (RB, 8580) | Kyren Williams (RB, 8006), Ladd McConkey (WR, 7831) | User's own RB/WR surplus depth. Old found close values but from global pool. |

### User Overpaying (gap > 0 → "they_add")

| # | Gap | OLD Balancers | NEW Balancers | Why Better |
|---|-----|---------------|---------------|------------|
| 9 | +300 | Ashtyn Davis (DB, 299), Jalen Walthall (???, 303), Donaven McCulley (???, 295) | *none* | Positionless/low-value players filtered. No realistic add from opponent at 300. |
| 10 | +500 | Eric Rivers (WR, 499), All Other RBs (???, 496), Alex Wright (DL, 505) | AJ Dillon (RB, 522), Zamir White (RB, 546) | Real players with positions. "All Other RBs" eliminated. 2 instead of 3. |
| 11 | +1000 | Drew Sanders (LB, 1000), Jacob Cowing (WR, 1001), Kaelon Black (RB, 997) | Drew Sanders (LB, 1000), Jacob Cowing (WR, 1001) | Same quality but capped at 2. Kaelon Black was marginal third option. |
| 12 | +2000 | Deommodore Lenoir (DB, 2000), Dawson Knox (TE, 2002), Justin Joly (TE, 1995) | Ty Johnson (RB, 1993), Keyshaun Elliott (LB, 1987) | Positionless entries avoided. Real positioned players only. |
| 13 | +3000 | (3 candidates near 3000) | (2 candidates near 3000) | Capped at 2, positioned players only. |
| 14 | +5000 | (3 candidates near 5000) | Romeo Doubs (WR, 5023), Devin Lloyd (LB, 5078) | Clean results, capped at 2. |

### Edge Cases

| # | Gap | OLD | NEW | Why Better |
|---|-----|-----|-----|------------|
| 15 | -100 | *none* (below 256 threshold) | *none* | Unchanged — small gaps don't need balancers. |
| 16 | +100 | *none* | *none* | Unchanged. |
| 17 | -256 | Colbie Young (???, 259), Chris Hilton (???, 263), ... | *none* | User has no ~256-value depth. Honest empty result. |
| 18 | +256 | Colbie Young (???, 259), Chris Hilton (???, 263), ... | *none* | No positioned players near 256 above MIN_RELEVANT_VALUE. |
| 19 | -50000 | *none* (0.4 tolerance too narrow) | *none* | Both correctly return empty for unrealistic gaps. |
| 20 | +500 (excluded) | All 3 from pool | 2 from pool, excludes named players | Exclude set works correctly. |

---

## Technical Appendix

### Architecture Change

**Before:** `_find_balancers(gap, pool, roster_set, exclude)` → always
searched global pool, min value 100, returned up to 3.

**After:** `_find_balancers(gap, pool, roster_set, exclude, roster=None)`
→ direction-aware search with two helper functions:

```
gap < 0 + roster → _roster_balancer_candidates()  → user's depth pieces
gap < 0 + no roster → _pool_balancer_candidates() → fallback to pool
gap > 0 → _pool_balancer_candidates()             → opponent's pool
```

Returns `(list[PlayerAsset], side: str)` where side is `"you_add"` or
`"they_add"`.

### New Functions

| Function | Purpose |
|----------|---------|
| `_roster_balancer_candidates()` | Searches user's roster for expendable depth (surplus first, then any non-starter) |
| `_pool_balancer_candidates()` | Searches global pool with position and value filters |

### New Constants

```python
MAX_BALANCERS = 2  # Was hardcoded 3, now configurable constant
```

### New Serialization Field

```json
{
  "suggestedBalancers": [...],
  "balancerSide": "you_add"  // or "they_add" — NEW additive field
}
```

The `balancerSide` field is only present when `suggestedBalancers` is
non-empty. This is a purely additive API change — no existing fields
removed or modified.

### Exact Files Changed

| File | Lines Changed | What |
|------|--------------|------|
| `src/trade/suggestions.py:749-830` | Logic | Replaced `_find_balancers`, added `_roster_balancer_candidates`, `_pool_balancer_candidates`, `MAX_BALANCERS` |
| `src/trade/suggestions.py:997` | Call site | Pass `roster` to `_find_balancers`, capture `(bals, side)` tuple |
| `src/trade/suggestions.py:998` | Call site | Store `balancer_side` in `__dict__` |
| `src/trade/suggestions.py:1085-1087` | Serializer | Emit `balancerSide` when balancers present |
| `tests/test_trade_suggestions.py:13-38` | Imports | Added new function/constant imports |
| `tests/test_trade_suggestions.py:1085-1230` | Tests | 7 new test classes, 16 new test methods |

### Exact Tests Added

| Test Class | Tests | What It Validates |
|------------|-------|-------------------|
| `TestFindBalancersDirection` | 4 | gap < 0 → user roster; gap > 0 → pool; small gap → empty; no roster → fallback |
| `TestBalancerQuality` | 5 | Max 2; no positionless; no below-min; surplus preferred; exclude respected |
| `TestPoolBalancerCandidates` | 2 | Filters positionless; filters below MIN_RELEVANT_VALUE |
| `TestRosterBalancerCandidates` | 2 | Only depth (not starters); skips positionless |
| `TestBalancerSideSerialization` | 1 | `balancerSide` appears in serialized output |
| `TestBalancerDeterminism` | 2 | Direct call deterministic; full pipeline deterministic |

**Total tests: 82 (was 66, added 16)**

### Rollback Instructions

To revert to pre-Phase-2B behavior:

```python
# In src/trade/suggestions.py:
# 1. Replace _find_balancers, _roster_balancer_candidates,
#    _pool_balancer_candidates, and MAX_BALANCERS with the old version:
def _find_balancers(gap, asset_pool, roster_names_set, exclude_names):
    if abs(gap) < 256:
        return []
    target_value = abs(gap)
    candidates = [
        a for a in asset_pool
        if a.name.lower() not in roster_names_set
        and a.name.lower() not in exclude_names
        and a.display_value >= 100
        and abs(a.display_value - target_value) < target_value * 0.4
    ]
    candidates.sort(key=lambda c: abs(c.display_value - target_value))
    return candidates[:3]

# 2. Revert call site (line ~997):
#    s.__dict__["balancers"] = _find_balancers(s.gap, pool, roster_set, exclude)
# 3. Remove balancerSide from serializer
```

Or simply: `git revert <commit-hash>`
