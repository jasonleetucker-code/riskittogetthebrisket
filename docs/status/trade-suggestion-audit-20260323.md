# Trade Suggestion Quality Audit

**Date:** 2026-03-23
**Scope:** `src/trade/suggestions.py` — suggestion engine v2
**Method:** 10 diverse roster shapes against live canonical snapshot (2026-03-22T210702Z)
**Status:** Audit only — no fixes applied

---

## Founder-Readable Summary

The trade suggestion engine works but has significant blind spots. Out of 10
realistic roster shapes tested, **4 received zero suggestions**. The remaining 6
rosters generated 40 total suggestions — 35 of which (87.5%) were sell-high.
**Zero consolidation and zero positional-upgrade suggestions were generated
across any roster.** The buy-low category produced only 5 suggestions.

The engine excels at one thing: finding same-value swaps between surplus and
need positions. But it structurally cannot help with the most common dynasty
scenarios: rebuilding teams with no depth, contenders with aging rosters,
teams with draft picks as tradeable assets, or QB-surplus teams where the
value gap to IDP/DB is too large.

### What works
- Sell-high suggestions are fair and well-matched (mostly "even" fairness)
- Market-disagreement signals (dispersion CV) flag real uncertainty
- Deterministic output — same inputs always produce same results
- The quality filter pipeline correctly caps repetition (3-per-player)

### What's broken
1. **40% of roster archetypes get zero help** — the engine silently returns nothing
2. **Consolidation is structurally dead** — when depth pieces are worth 8000+, no single player exceeds their combined value (capped at 9999)
3. **Positional upgrades never fire** — they require depth at the same position as the weakest starter, which is rare; upgrade floor is too high for WR-heavy rosters where the "weakest starter" is already Justin Jefferson
4. **Draft picks are invisible** — picks have empty position (`""`), so they never count toward surplus and can't be offered in trades
5. **Cross-position value gaps kill QB/IDP trade paths** — QBs worth 9600 can't match to DL/DB worth 6800 (gap = 2800 vs tolerance = 769)
6. **Sell-high dominance makes the feature feel one-dimensional** — users see the same pattern 35/40 times

---

## Failure Taxonomy

### F0: ZERO_SUGGESTIONS — Roster gets no suggestions at all

**Root cause:** Engine requires `surplus_positions` (>= 2 depth pieces above starter need at a position) to generate any sell-high or buy-low suggestions. Consolidation requires surplus. Upgrades require depth at the same position as starters.

**Affected roster shapes:**
- **Rebuilder (young/thin):** 11 elite players, zero depth at any position → no surplus → 0 suggestions
- **QB surplus:** 4 elite QBs (surplus detected), but needs are DL/DB where best players are worth 6800-7000 vs QBs at 9600+ → value gap of 2500+ far exceeds 769 tolerance → 0 suggestions
- **Aging contender:** Full starting lineup with 1 TE depth piece (needs 2 for surplus) → 0 suggestions
- **Pick-rich rebuilder:** 5 draft picks worth 6600-9000 have position="" → invisible to surplus detection → 0 suggestions

**Prevalence:** 4/10 rosters (40%)

### F1: REPETITIVE_OUTGOING — Same outgoing player appears 3+ times within one roster

Despite MAX_GIVE_PLAYER_APPEARANCES=3, the cap still allows a player to dominate the feed. When a roster has narrow surplus (e.g., only LB depth), the same 2-3 names appear in nearly every suggestion.

**Prevalence:** 21/40 suggestions (52.5%)

| Roster | Repeat offenders |
|--------|-----------------|
| contender_balanced | Fred Warner x3 |
| rb_heavy | De'Von Achane x3, Jonathan Taylor x3 |
| wr_heavy | CeeDee Lamb x3 |
| te_premium | Trey McBride x3, Tucker Kraft x3 |
| idp_stacked | Myles Garrett x3 |
| shallow_everywhere | Zack Baun x2, Quay Walker x2 |

### F2: FAIR_BUT_WEAK — Mathematically fair trade between low-value depth pieces

Both sides of the trade are below 3000 display value. The suggestion is technically correct but not worth the effort of negotiating.

**Prevalence:** 0/40 in this run (threshold didn't trigger because current surplus players are all mid-tier IDP/LB worth 5000-6000+). However, the engine has no floor check — it would happily suggest swapping two 501-value players if the math works.

### F3: SAME_TIER_SWAP — 1-for-1 between same-position players within 500 value

Not observed in this run because sell_high explicitly targets different positions (surplus → need). But nothing prevents this in buy_low or positional_upgrade if the engine matched same-position players at similar values.

### F4: ONE_SIDED_NO_PARTNER — No opponent wants what I'm trading

Without league rosters provided, `opponentFit` is always null. 100% of suggestions in this audit (without league data) lack a real trade partner signal. The engine generates ideas in a vacuum.

**Prevalence:** 40/40 when no league_rosters provided; structural limitation

### F5: NEEDS_PACKAGING — 1-for-1 where engine suggests balancers (admitting it's unfair)

The engine generates a 1-for-1 that it knows isn't fair, then tacks on "suggestedBalancers" as an afterthought. These should be generated as 2-for-1 or 2-for-2 package deals instead.

**Prevalence:** 3/40 (7.5%)

| # | Roster | Give | Receive | Gap |
|---|--------|------|---------|-----|
| 1 | contender_balanced | Fred Warner (LB, 6089) | Caleb Downs (DB, 6410) | -321 |
| 2 | contender_balanced | Fred Warner (LB, 6089) | Kevin Winston (DB, 6502) | -413 |
| 3 | wr_heavy | CeeDee Lamb (WR, 8988) | Jayden Daniels (QB, 9603) | -615 |

### F6: STRETCH_FAIRNESS — Trade gap exceeds "lean" threshold

Not observed in the final output (consolidation stretches are filtered). But the pipeline is the reason consolidation returns zero — all consolidation candidates would be stretches when depth pieces combined > 17000.

### F7: LOW_CONFIDENCE — Source count < 3

Suggestions where the engine has weak source agreement.

**Prevalence:** 6/40 (15%)

### F8: DEAD_CONSOLIDATION — Consolidation structurally impossible

**Root cause:** When tradeable depth pieces at surplus positions are worth 8000-9000+ each, their combined value is 17000-19000. The engine requires a consolidation target worth MORE than the highest individual piece AND within [combined * 0.70, combined + 769]. With max display value at 9999, no single player can satisfy `display_value > 9641` AND `display_value >= 13334`. The math is impossible.

**Prevalence:** 0/10 rosters produced any consolidation suggestion

### F9: DEAD_POSITIONAL_UPGRADE — Upgrade path structurally unreachable

**Root cause:** The upgrade generator requires:
1. At least 2 players at the position (starters + depth)
2. Depth piece at the SAME position as the upgrade
3. An external target > weakest_starter + 500
4. A sweetener within 769 of the gap

For WR-heavy roster: weakest WR starter is Justin Jefferson at 9026, so upgrade_floor = 9526. Best external WR (JSN at 9485) is below the floor. Dead end.

For cross-position sweeteners: the gap_needed between a target and the weakest starter is usually 500-2000, but surplus-position depth is at a different value tier.

**Prevalence:** 0/10 rosters produced any positional upgrade suggestion

### F10: INVISIBLE_PICKS — Draft picks cannot participate in trade suggestions

**Root cause:** Draft picks in the canonical snapshot have `position: ""`. The engine indexes everything by position. Picks:
- Are never counted toward any position's surplus
- Can never be offered as the "give" side of a sell-high
- Can never be a sweetener in positional upgrades
- Can never participate in consolidation pairs

A pick-rich team with Early 1st (9027), Mid 1st (7850), Early 2nd (7740) has massive tradeable value that the engine completely ignores.

**Prevalence:** Affects any roster with draft picks (very common in dynasty)

---

## All 40 Live Suggestions (Numbered Reference)

| # | Roster | Category | Give | Receive | Gap | Fair | Conf | Edge | Score |
|---|--------|----------|------|---------|-----|------|------|------|-------|
| 1 | contender_balanced | sell_high | Fred Warner (LB, 6089) | Kyle Hamilton (DB, 6126) | -37 | even | med | mkt_disc | 13.6 |
| 2 | contender_balanced | sell_high | Nick Bolton (LB, 5799) | Nick Emmanwori (DB, 5980) | -181 | even | med | mkt_disc | 13.3 |
| 3 | contender_balanced | sell_high | CJ Allen (LB, 5943) | Nick Emmanwori (DB, 5980) | -37 | even | low | mkt_disc | 12.4 |
| 4 | contender_balanced | buy_low | Fred Warner (LB, 6089) | Caleb Downs (DB, 6410) | -321 | lean | low | - | 9.1 |
| 5 | contender_balanced | buy_low | Fred Warner (LB, 6089) | Kevin Winston (DB, 6502) | -413 | lean | low | - | 9.1 |
| 6 | rb_heavy | sell_high | De'Von Achane (RB, 9641) | Jayden Daniels (QB, 9603) | +38 | even | high | - | 15.6 |
| 7 | rb_heavy | sell_high | De'Von Achane (RB, 9641) | Ja'Marr Chase (WR, 9563) | +78 | even | high | - | 15.6 |
| 8 | rb_heavy | sell_high | Jonathan Taylor (RB, 9408) | Joe Burrow (QB, 9446) | -38 | even | high | - | 15.4 |
| 9 | rb_heavy | sell_high | Jonathan Taylor (RB, 9408) | Puka Nacua (WR, 9370) | +38 | even | high | - | 15.4 |
| 10 | rb_heavy | sell_high | James Cook (RB, 9177) | Patrick Mahomes (QB, 9216) | -39 | even | high | - | 15.2 |
| 11 | rb_heavy | sell_high | James Cook (RB, 9177) | Amon-Ra St. Brown (WR, 9140) | +37 | even | high | - | 15.1 |
| 12 | rb_heavy | buy_low | De'Von Achane (RB, 9641) | Drake Maye (QB, 9721) | -80 | even | high | - | 15.6 |
| 13 | rb_heavy | buy_low | Jonathan Taylor (RB, 9408) | JSN (WR, 9485) | -77 | even | high | - | 15.4 |
| 14 | wr_heavy | sell_high | CeeDee Lamb (WR, 8988) | Jaxson Dart (QB, 8950) | +38 | even | high | - | 14.9 |
| 15 | wr_heavy | sell_high | Drake London (WR, 8839) | Trevor Lawrence (QB, 8876) | -37 | even | high | - | 14.8 |
| 16 | wr_heavy | sell_high | Drake London (WR, 8839) | Breece Hall (RB, 8765) | +74 | even | high | - | 14.8 |
| 17 | wr_heavy | sell_high | Nico Collins (WR, 8326) | Fernando Mendoza (QB, 8362) | -36 | even | high | - | 14.3 |
| 18 | wr_heavy | sell_high | Nico Collins (WR, 8326) | Saquon Barkley (RB, 8290) | +36 | even | high | - | 14.3 |
| 19 | wr_heavy | sell_high | CeeDee Lamb (WR, 8988) | Jeremiyah Love (RB, 8973) | +15 | even | low | - | 13.0 |
| 20 | wr_heavy | buy_low | CeeDee Lamb (WR, 8988) | Jayden Daniels (QB, 9603) | -615 | lean | high | - | 13.0 |
| 21 | te_premium | sell_high | Trey McBride (TE, 9761) | Ashton Jeanty (RB, 9839) | -78 | even | high | - | 15.8 |
| 22 | te_premium | sell_high | Trey McBride (TE, 9761) | Drake Maye (QB, 9721) | +40 | even | high | - | 15.7 |
| 23 | te_premium | sell_high | Trey McBride (TE, 9761) | Ja'Marr Chase (WR, 9563) | +198 | even | high | - | 15.6 |
| 24 | te_premium | sell_high | Tyler Warren (TE, 8690) | TreVeyon Henderson (RB, 8727) | -37 | even | high | - | 14.7 |
| 25 | te_premium | sell_high | Tyler Warren (TE, 8690) | Drake London (WR, 8839) | -149 | even | high | - | 14.7 |
| 26 | te_premium | sell_high | Tucker Kraft (TE, 8148) | Chase Brown (RB, 8183) | -35 | even | high | - | 14.2 |
| 27 | te_premium | sell_high | Tucker Kraft (TE, 8148) | Garrett Wilson (WR, 8076) | +72 | even | high | - | 14.1 |
| 28 | te_premium | sell_high | Tucker Kraft (TE, 8148) | Dak Prescott (QB, 8042) | +106 | even | high | - | 14.0 |
| 29 | idp_stacked | sell_high | Myles Garrett (DL, 6812) | Emmanuel McNeil-Warren (DB, 6971) | -159 | even | low | - | 11.8 |
| 30 | idp_stacked | sell_high | Myles Garrett (DL, 6812) | Jaylen Waddle (WR, 6802) | +10 | even | med | - | 11.8 |
| 31 | idp_stacked | sell_high | Myles Garrett (DL, 6812) | Kyler Murray (QB, 6770) | +42 | even | med | - | 11.8 |
| 32 | idp_stacked | sell_high | Carson Schwesinger (LB, 6312) | Tyler Shough (QB, 6243) | +69 | even | med | hi_disp | 11.7 |
| 33 | idp_stacked | sell_high | Jack Campbell (LB, 6425) | Tyler Shough (QB, 6243) | +182 | even | med | hi_disp | 11.7 |
| 34 | idp_stacked | sell_high | Maxx Crosby (DL, 6734) | Kyler Murray (QB, 6770) | -36 | even | med | - | 11.7 |
| 35 | idp_stacked | sell_high | Maxx Crosby (DL, 6734) | Jaylen Waddle (WR, 6802) | -68 | even | med | - | 11.7 |
| 36 | idp_stacked | sell_high | Abdul Carter (DL, 6694) | Jameson Williams (WR, 6643) | +51 | even | med | - | 11.6 |
| 37 | shallow_everywhere | sell_high | Zack Baun (LB, 5448) | Budda Baker (DB, 5380) | +68 | even | med | mkt_prem | 12.4 |
| 38 | shallow_everywhere | sell_high | Quay Walker (LB, 5483) | Danielle Hunter (DL, 5517) | -34 | even | med | - | 10.5 |
| 39 | shallow_everywhere | sell_high | Quay Walker (LB, 5483) | Trevon Moehrig (DB, 5552) | -69 | even | low | - | 10.5 |
| 40 | shallow_everywhere | sell_high | Zack Baun (LB, 5448) | Danielle Hunter (DL, 5517) | -69 | even | med | - | 10.4 |

---

## Technical Appendix

### Audit Method

Ran `generate_suggestions()` against the latest canonical snapshot using 10
hand-crafted rosters representing distinct dynasty archetypes:

| Roster | Archetype | Players | Result |
|--------|-----------|---------|--------|
| contender_balanced | Strong everywhere, moderate depth | 25 | 5 suggestions |
| rebuilder_young | Young core, thin roster | 11 | **0 suggestions** |
| rb_heavy | Stacked RB, thin elsewhere | 19 | 8 suggestions |
| wr_heavy | Deep WR, thin RB/TE | 18 | 7 suggestions |
| qb_surplus | 4 elite QBs, average elsewhere | 17 | **0 suggestions** |
| te_premium | Loaded TE in TEP, thin spots | 14 | 8 suggestions |
| idp_stacked | Elite IDP, weak offense | 22 | 8 suggestions |
| aging_contender | Veterans everywhere, window closing | 16 | **0 suggestions** |
| shallow_everywhere | Exactly starter counts, zero depth | 17 | 4 suggestions |
| pick_rich | Draft capital heavy, thin active | 12 | **0 suggestions** |

### Exact Failure Category Definitions

| Code | Label | Definition | Trigger |
|------|-------|-----------|---------|
| F0 | ZERO_SUGGESTIONS | Roster gets no suggestions at all | No surplus positions detected |
| F1 | REPETITIVE_OUTGOING | Same give-player appears 3+ times in one roster's output | Counter per roster >= 3 |
| F2 | FAIR_BUT_WEAK | Both sides below 3000 display value | All assets in trade < 3000 |
| F3 | SAME_TIER_SWAP | Same-position 1-for-1 within 500 value | Same pos, gap < 500 |
| F4 | ONE_SIDED_NO_PARTNER | No opponent roster fit identified | opponentFit is null |
| F5 | NEEDS_PACKAGING | 1-for-1 with balancers attached (engine admits unfairness) | balancers present, gap > 256 |
| F6 | STRETCH_FAIRNESS | Gap exceeds 769 display value | fairness == "stretch" |
| F7 | LOW_CONFIDENCE | Source count < 3 | confidence == "low" |
| F8 | DEAD_CONSOLIDATION | Consolidation math impossible at current value scale | Combined > 17000, max target 9999 |
| F9 | DEAD_POSITIONAL_UPGRADE | Upgrade floor unreachable | weakest_starter + 500 > best external |
| F10 | INVISIBLE_PICKS | Draft picks have no position, excluded from all logic | position == "" |

### Prevalence Matrix

| Code | Count | % of 40 | Structural? |
|------|-------|---------|-------------|
| F0 | 4 rosters | 40% of rosters | Yes — surplus detection |
| F1 | 21 | 52.5% | Partially — cap=3 not aggressive enough |
| F4 | 40 | 100% (w/o league data) | Design gap |
| F7 | 6 | 15.0% | Expected for thin sources |
| F5 | 3 | 7.5% | Design gap |
| F8 | 10 rosters | 100% of rosters | Yes — value scale math |
| F9 | 10 rosters | 100% of rosters | Yes — threshold math |
| F10 | any with picks | common | Yes — position field empty |

### Structural Root Causes (in priority order)

1. **Surplus detection is too strict.** Requiring 2+ depth pieces above starter need excludes most real rosters. A team with 2 QBs (need=2) and 2 extra QBs could be surplus, but a team with exactly need+1 at every position has zero surplus anywhere.

2. **Fairness tolerance (769) is too narrow for cross-tier trades.** QBs and WRs trade in the 7000-9999 range; IDP players trade in the 5000-7000 range. A 769 tolerance can never bridge the QB→DB gap of 2500+. The engine needs either wider tolerance with package support or explicit cross-tier logic.

3. **Consolidation assumes combined value < 9999.** With depth pieces at 8000+, two pieces sum to 16000-19000, but no single asset exists in that range. The consolidation concept only works for mid-tier depth (2000-5000 range pieces combining into one 4000-8000 player).

4. **Draft picks are positionless.** The canonical snapshot stores picks with `position: ""`. The engine indexes everything by position. Without special handling, picks are invisible.

5. **Positional upgrade math is too constrained.** The upgrade floor (weakest_starter + 500) combined with the sweetener tolerance (769) creates a narrow band that rarely aligns with available assets.

### Files Likely to Change in Next Phase

| File | Change Type | Why |
|------|-------------|-----|
| `src/trade/suggestions.py` | Major refactor | All F0/F1/F5/F8/F9/F10 fixes live here |
| `src/trade/suggestions.py:31-38` | Config | DEFAULT_STARTER_NEEDS thresholds affect surplus detection |
| `src/trade/suggestions.py:42` | Config | MIN_RELEVANT_VALUE (500) may be too low for some positions |
| `src/trade/suggestions.py:45` | Config | FAIRNESS_TOLERANCE (769) too narrow for cross-tier |
| `src/trade/suggestions.py:52` | Config | CONSOLIDATION_MIN_UPGRADE_RATIO needs rethink |
| `src/trade/suggestions.py:59` | Config | MAX_GIVE_PLAYER_APPEARANCES (3) may need to be 2 |
| `src/trade/suggestions.py:258-273` | Logic | Surplus detection (depth >= 2 is too strict) |
| `src/trade/suggestions.py:488-535` | Logic | _generate_sell_high needs cross-tier + pick support |
| `src/trade/suggestions.py:538-591` | Logic | _generate_buy_low needs package deal generation |
| `src/trade/suggestions.py:594-659` | Logic | _generate_consolidation needs value-scale fix |
| `src/trade/suggestions.py:662-736` | Logic | _generate_positional_upgrades needs cross-position sweetener fix |
| `tests/test_trade_suggestions.py` | Test updates | New test cases for each fix |
| `frontend/app/trade/page.jsx` | Minor | May need UI for package deals, pick-based suggestions |
