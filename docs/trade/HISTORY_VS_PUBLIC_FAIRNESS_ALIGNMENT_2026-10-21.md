# History grade vs the fairness bands -- alignment study (OD-F6 input)

**Status: PENDING OWNER DECISION. Nothing here is approved, activated, or served.**
Read-only tooling, tests and documentation. No change to `src/public_league/trade_grading.py`,
`frontend/lib/league-analysis.js`, `fairness_bands_v2`, `geom_q078_v1`, the public advisor
thresholds, any launch gate or any flag. Every proposed change below is a **default-OFF flag
design only**.

Agent-OS-Receipt: cb64f74cf4d2763aa16d55ba0d6350f585a2a42f

Related: [`docs/owner/FAIRNESS_V2_DECISIONS_2026-10-20.md`](../owner/FAIRNESS_V2_DECISIONS_2026-10-20.md)
(OD-F6 open), [`docs/TRADE_HISTORY_AGING_SPEC.md`](../TRADE_HISTORY_AGING_SPEC.md),
`CLAUDE.md` "Trade History -- three distinct questions". The public-advisor audit that first named
OD-F6 (finding A1) and the low-value-asset correction record (C1.1 rows for these two files) live on
their own branches; this document does not depend on them.

## 0. Headline

* The history grade's "Fair trade" (below 3.0 % of the larger **effective** side, no floor) and the
  advisor's FAIR (band `fair`: below 3.5 % of the larger **package utility**, or a gap under the
  250-point floor) are two different predicates behind one word.
* Measured on the league's real trades at one pinned current board (76 gradable trades, 153
  trade sides): they disagree on **6 sides (3.9 %)** -- 3 of 76 trades -- and **every** disagreement
  is the history grade saying "not fair" where the band says FAIR, all of it from the absolute floor.
  There is **no** real side the history grade calls "Fair trade" that the advisor calls NOT FAIR.
* On a labelled synthetic population built to put gaps on every band edge (3,000 sides) they differ
  on **222 sides (7.4 %)**: 220 history-stricter, 2 owner-stricter. By cause: relative cut 62
  sides, floor 184, package-utility denominator -28 (deep packages, owner stricter).
* The disagreement concentrates in **small packages** (all 6 real flips and 216 of 222 synthetic flips
  are under the 250 floor) and in **1-for-1 / 2-for-2** shapes. For deep packages
  the owner is the stricter one.
* The two grades also read different **percentages** for the same trade: the owner's relative gap is
  a median 1.12x the history percent (p90 1.30x on the real population).
* The word "fair" also differs *within* the history surfaces: the number 3 is a literal in five places
  (Section 1.3), so even a pure relabel has to touch them together.

## 1. Surface audit (current `main`, `7dd8cb048`)

Concept key: **MF** market fairness now (is this package gap inside the fairness band, on today's
values); **TR** team recommendation (what this team should do; band is one input); **HO** historical
outcome (how a completed trade looks on a stated value basis). "Reads v2" = the classification comes
from `src/valuation_math/fairness_bands.py` (`fairness_bands_v2`, 3.5 / 9 / 18 %, floor 250, base =
larger package utility).

### 1.1 Table

| # | Surface | file:line | Concept | Quantity, denominator, threshold | Reads v2 | User-visible words |
|---|---|---|---|---|---|---|
| 1 | Public advisor, overall result | `src/trade/public_advisor.py:87-91` (`OVERALL_LABELS`); `src/trade/team_verdicts.py:229-238` (`fairness_overall`, Kleene AND); UI `frontend/app/league/sections/_advisor-result.jsx` | MF | per-team market gap `recvAdj - sendAdj`; FAIR iff every team's band level is `fair` (`counts_as_fair_trade`, OD-F1) | **yes** | `FAIR TRADE` / `NOT FAIR` / `UNABLE TO DETERMINE` |
| 2 | Public advisor, per team | `src/trade/public_advisor.py:94-98` (`TEAM_LABELS`); `src/trade/team_verdicts.py:172-226` (`team_fairness`, `counts_as_fair_trade` at :213) | MF | that team's own gap; base = larger package utility (`largerPackageUtility`, :210); 3.5 % or under 250 | **yes** | `FAIR FOR THIS TEAM` / `NOT FAIR FOR THIS TEAM` / `UNABLE TO DETERMINE` |
| 3 | War Room market band (equity / market lens) | `src/trade/analyze_trade.py:160-198` (`equity_verdict`, band at :176, `legacy_magnitude` :177, `win` :188); `_market_lens` :200 | MF | gap `recvAdj - sendAdj`; base `larger_package_utility`; level `fair`/`slight`/`unfair`/`lopsided` | **yes** | band label `FAIR` / `SLIGHT EDGE` / `UNFAIR` / `LOPSIDED`; legacy keys `even`/`lean`/`stretch`; boolean `win` |
| 4 | War Room team Accept/Decline-style category | `src/trade/team_verdicts.py:84-129` (`team_category`), text :41-49; headline text `src/trade/trade_decision.py:54-58`; component A `trade_decision.py:482-520` (band at :505) | TR | five-level category from `decide`: component A (band on the gap net of any added forced-release cost), roster utility, strategy, execution gate | indirectly (component A only) | `Strongly favorable` ... `Strongly unfavorable`, `Approximately even`; `YES - MAKE THE TRADE`, `NO - DO NOT MAKE THE TRADE`, `NO - TOO CLOSE`, `NOT ENOUGH EVIDENCE` |
| 5 | Trade meter / gap, sticky tray, fairness explanation | `frontend/components/trade/TradeMeter.jsx:139-213`; `frontend/lib/trade-logic.js:2374-2383` (`meterVerdict`), :1229-1250 (`tradeGapAdjusted`, `VERDICT_WORDS`); `frontend/components/trade/TradeFairnessExplanation.jsx:124,154` | MF | gap = A adjusted minus B adjusted; `relativeGapPct` over larger package utility; JS mirror of the owner | **yes** (JS mirror `frontend/lib/fairness-bands.js`) | `FAIR` / `SLIGHT EDGE` / `UNFAIR` / `LOPSIDED` + `percentText`; legacy words `Near even` / `Lean` / `Strong lean` / `Major gap` |
| 6 | Trade Finder levels | `src/trade/finder.py:359-364` (`_edge_label`), score :825-833 | TR (arbitrage opportunity) | board gain / give-side model total: >= 25 % `Strong Edge`, >= 10 % `Moderate Edge`, else `Slight Edge`; KTC appeal must be strictly positive | **no** (its own cut points, raw board delta) | `Strong Edge` / `Moderate Edge` / `Slight Edge` |
| 7 | Best Offers | `src/trade/best_offers.py:97-131` (`best_offers_qualification`); UI `frontend/app/arbitrage/BestOffersView.jsx:410-413` | TR (built on MF) | qualifies if `equity.win` (gap beyond the fair band) **or** a positive gain >= the owner's `absoluteMinimum` that the band still rates FAIR | **yes** (band, floor) | "Adjustment past the fairness band, or by at least 250 points even when the band rates the package fair" |
| 8 | Suggestions "even" badge, ranking bonus, equalizer | `src/trade/suggestions.py:963-968` (`_fairness_label`), :1022 (`_FAIRNESS_RANK_BONUS`), :1595-1601 (`is_even`) | TR (badge from MF) | `classify_packages` over give/receive; `even` iff band `fair` | **yes** | `even` / `lean` / `stretch` |
| 9 | Second Opinions "even" (per source) | `frontend/lib/second-opinions.js:371-386` (`OPINION_EVEN_TOLERANCE_PCT = 1`); tally `frontend/components/trade/TradeOpinionTally.jsx` | MF-like, per source | leader margin within 1 % of the leader's total, totals adjusted (or a 1-point gap); owner decision 4 (2026-10-18), initial value | **no** (own 1 % rule, **adjusted** side) | `Even` in "Side A n - Side B n - Even n" |
| 10 | Historical trade grade (Python): public `/league` timeline, private at-the-time grade, manager activity | `src/public_league/trade_grading.py:54-58` (cuts), :61-89 (`grade_from_pct`), :187-217 (`grade_trade_side`); callers `src/public_league/activity.py:170` (at-the-time), :205 (current), `src/api/trade_history_asof.py:91`, `src/intel/manager_activity.py:962-975`; UI `frontend/app/league/sections/activity.jsx:196-225` | **HO** | `pctGap = netAdjusted / max(larger effective side, 1) * 100`, per side from its own got/gave; "Fair trade" iff `abs(pct) < 3.0`; further tiers 8 / 15 / 25 / 40; **no floor** | **no** | `Fair trade`, `Slight win`, `Good win`, `Clear win`, `Big win`, `Slight overpay`, `Overpay`, `Bad deal`, `Robbery`, `Fleeced`; letters A+ ... F; unavailable: `Insufficient historical evidence` |
| 11 | Historical trade grade (JS mirror): private `/trades` Current Grade | `frontend/lib/league-analysis.js:93-104` (`gradeTradeHistorySide`, `pct < 3`), :449-471 (`gradeTradeSide`); card `frontend/app/trades/page.jsx:428-465` | **HO** | identical math (parity fixture `tests/fixtures/trade_grade_parity_cases.json`) | **no** | same words; card badge: neutral `Fair trade` when headline `pctGap < 3`, else `<team> won by N%` / `overpaid by N%` |
| 12 | Winners / losers W/L counts | `frontend/lib/league-analysis.js:644-657` (`s.pctGap >= 3` -> won, `<= -3` -> lost); panel `frontend/app/trades/page.jsx:72-100` | **HO** | a side "wins"/"loses" iff `|pctGap| >= 3`; fair sides count for nobody | **no** | `Won` / `Lost` columns |
| 13 | Winners & Losers net value | `frontend/lib/league-analysis.js:641-650` (`netAdjustedTotal`, sum of every trade's adjusted net, fair ones included); default metric `frontend/app/trades/page.jsx:81-100` | **HO** | sum of per-trade adjusted nets (no threshold) | no (no threshold) | `Net value` |
| 14 | How It Aged | `frontend/lib/trade-history-grades.js:31-34` (`AGING_STABLE_BAND_PRIOR = 200`), :145-160 (`sideAging`); copy `frontend/app/trades/page.jsx:516` | **HO** | change in this side's **adjusted** net, today minus at-the-time, same package model; within +/-200 points reads Stable; a labelled PRIOR, evidence-gated by the aging spec | **no** | `Aged well` / `Aged poorly` / `Stable` / `Aging unavailable` |

Not in the table by design: the unavailable states of rows 10-11 and 14 (`Insufficient historical
evidence`, `Aging unavailable`) are explicit and never coerced to a grade; row 1-2's `UNABLE` is the
advisor's equivalent.

### 1.2 What "effective" means in the history grade (traced, not assumed)

`trade_grading.grade_trade_side` (`trade_grading.py:200-208`):

```
got_effective  = got_linear  + max(0,  va_net)
gave_effective = gave_linear + max(0, -va_net)
scale          = max(got_effective, gave_effective, 1.0)
pctGap         = (got_linear - gave_linear + va_net) / scale * 100
```

`va_net` is the active package model's value adjustment (`package_model.adjust_pair`, geom q 0.78),
credited to the side that discarded less depth. So an **effective side total is exactly the
package-adjusted side total**, and `scale` is *the larger adjusted side* -- **the retired
fairness_bands_v1 denominator.** The numerator is the same adjusted gap the band owner classifies
(`recvAdj - sendAdj`; the script asserts agreement on every side, 0 failures).

The owner's v2 base is the larger **package utility** `U = sum q^i v_i` (values best first). Under
`geom_q078_v1` `adjusted_A - adjusted_B = U_A - U_B`, and `U <= linear <= adjusted`, so for any
multi-piece package the owner's percentage is >= the history percentage; for a 1-for-1 they are
identical. Measured (real population): package utility / history scale has median 0.90, p10 0.77.
The history scale also carries a one-point floor (`max(..., 1.0)`), the owner none (it refuses a zero
base beside a non-trivial gap instead).

So three rule differences exist, and only these three: the relative **cut** (3.0 vs 3.5), the
absolute **floor** (none vs 250), and the **denominator** (adjusted vs utility). The measurement
below attributes flips to each.

### 1.3 Where the same word means different things

| word | meanings in the product today | intentional or accidental |
|---|---|---|
| **fair** | (a) advisor `FAIR TRADE` / `FAIR FOR THIS TEAM`: band `fair`, 3.5 % of utility or under 250 (rows 1-3, 5, 8); (b) history `Fair trade`: below 3.0 % of the larger adjusted side, no floor (rows 10-11); (c) the `/trades` card's neutral `Fair trade` badge, also `pctGap < 3` (row 11); (d) Best Offers counts a FAIR-band gain >= 250 as a qualifying *gain* (row 7); (e) the Finder's comment/score logic about the opponent seeing a "fair/favorable" KTC deal (`finder.py:823-824`) | (a)-(d) **accidental collision** between MF and HO: one word, two predicates, no shared owner. (e) different quantity, different surface. (d) intentional (owner decision 2026-10-18, Option B) and consistent with the owner. |
| **win** | (a) `equity.win` / War Room: positive gap beyond the band (`analyze_trade.py:188`); (b) history `Slight win` ... `Big win`: positive `pctGap >= 3.0`, tiers up to 25 %+ (rows 10-11); (c) W/L `Won`: `pctGap >= 3` (row 12); (d) Best Offers "meaningful gain" counts a sub-band gain >= 250 (row 7) | (a) vs (b)/(c) **accidental**: a 3.2 % gap on a 100,000-point trade is a history "win" and a market-FAIR (no win) trade at once. (d) intentional. |
| **even** | `even` (suggestions, band `fair`); `Approximately even` (team category for the decision's `NO - TOO CLOSE`, `trade_decision.py:553-580`); `Near even` (meter legacy word, band `fair`); `Even` (Second Opinions, 1 % of the leader's adjusted total) | the first three are the band; Second Opinions is a different question (per-source leader) with its own, **older** 1 % rule on the **adjusted** side -- accidental denominator mismatch with v2 (the owner moved the band base, not this) but a different concept. Out of OD-F6 scope. |
| **lopsided** | band label `LOPSIDED` (>= 18 % of utility, MF); War Room component-A magnitude `large` (>= `unfair`); history has no "lopsided" -- `Clear win`/`Big win` (>= 15 / 25 %), `Bad deal`/`Robbery`/`Fleeced` | intentional vocabulary split, but the **cut points do not line up** (18 % vs 15 / 25 / 40 %), so the same trade can be `LOPSIDED` in the meter and `Good win` in the history |
| **the number 3** | `trade_grading._GRADE_PCT_FAIR`; `league-analysis.js` lines 94 (`pct < 3`), 652 and 655 (`>= 3`, `<= -3`); `trades/page.jsx:429` (`a.pctGap >= 3`) | **accidental duplication**: five literals for one threshold (only the Python one is a named constant, the JS ones are pinned only by the parity fixture and the W/L rule is not in the fixture) |
| **percentage printed** | meter `percentText` = gap / larger *utility*; `/trades` card `won by N%` = gap / larger *adjusted* | **accidental**: two percentages for one trade on two tabs |

Intentional differences (different question): the history grade is per **side** on a stated value
basis (at-the-time or current) and graded by outcome *margin* tiers; the advisor is a **neutral
market** answer for the *current* package and has no margin tiers by owner amendment; the War Room
category is a **team** recommendation. Those should stay separate. Accidental: same word, different
predicate (above), five copies of the literal, two denominators, two percentages.

## 2. Measurement

Script: `scripts/history_grade_vs_fairness_bands.py` (new; imports and *calls* both owners, hard-codes
no cut point, floor or fair level; read-only; aggregate-only output guarded by
`assert_aggregate_only`). Tests: `tests/scripts/test_history_grade_vs_fairness_bands.py`.
Machine-readable result: `docs/trade/history-vs-public-fairness-alignment/results.json`
(reproduces byte for byte; sha256 `d5a63f609242133677a6a575378d3d92a83c5e19b0294049ea75386bec3a9874`).

Exact command (the pins below make it reproducible after the board moves):

```bash
nice -n 10 python scripts/history_grade_vs_fairness_bands.py \
    --archive exports/archive/dynasty_export_20261021_080314.zip \
    --csv-rev 7dd8cb048 --trades-rev 7dd8cb048 --synthetic 1500 \
    --out docs/trade/history-vs-public-fairness-alignment/results.json
```

| pin | value |
|---|---|
| board archive | `exports/archive/dynasty_export_20261021_080314.zip`, member `dynasty_data_2026-10-21.json`, sha256 `2853be37767ee652423003aec3f31ad0feb3448e1c30b95070c510c55d68b807` |
| CSV / config tree | git `7dd8cb04819b68eee49d5f31571c2e7d1482541f`, content sha256 `24e7f8ffd4db82c9417f7708459eac948d7034b1ecba17d2bea9343de970ffa1` |
| built board | sha256 `6d524a330b5800f68029ebbb324016d6c600933ab59b4c07a0fed085bdd865de` |
| trade list | `data/sleeper_last_good.json` at `7dd8cb048`, blob `4eb7de895d6939ac88de668ddde8043c4e43fb2d` |
| owners | `fairness_bands_v2` (`PRIOR_OWNER_APPROVED_2026-10-20`), `geom_q078_v1`; history cuts read from `trade_grading` (3 / 8 / 15 / 25 / 40) |
| pin helper | `scripts/research_pinned_board.py` -- byte-identical to the copy on the fairness-v2-correction branch (one copy, the identical add merges cleanly) |

### 2.1 Populations -- and what each is not

1. **`own_league_trades_current_board` (real).** The own-league trades in the tracked
   `rosterData.trades` (105 trades in the rolling window, 2025-10 to 2026-10), each asset priced at
   the **single pinned CURRENT board** with the same pick/player resolver the other fairness
   measurements use. **76 trades are gradable; 29 are excluded** because an asset is unpriced
   (counted, never priced as 0): 94 of 930 assets, **84 of them draft picks**, 10 players (most
   likely picks of classes the board has since retired, which today's board cannot price; the cause
   was not verified per asset).
   * Is it the set the public `/league` grade grades? **Not exactly.** The public grade resolves
     **at-the-time** values from the temporal ledger (box-local, not in the repository) for the
     league's whole snapshot history; this is the rolling window priced **today**. The two share the
     trades, not the value basis, and the gradable subsets differ (the public grade can grade a
     retired-class pick at its then value; this cannot). Survivorship: trades whose assets are still
     on the board are over-represented.
   * The real league's trades are **not** available in a public-safe tracked at-the-time form, so
     the distribution of what the public timeline *displays* is not reproduced here. Nothing was
     fabricated.
2. **`synthetic_balanced` (illustrative).** 1,500 deterministic (seed 20261021) trades from the top
   450 board values; shapes 1v1, 2v1, 2v2, 3v2, 3v3; the last received piece is chosen so the
   relative package gap lands near a target in [0, 20 %], so every band edge is exercised. Not the
   league's trades; says nothing about how often such trades occur. Use it for *shape of the effect*
   (which differences appear where), not for a rate.

Apples-to-apples: within a population, both classifiers see **identical inputs** (same assets, same
values, same package model, same gap `recvAdj - sendAdj`), so the comparison of the *rules* is exact.
Not apples-to-apples: (i) current-board values vs the public timeline's at-the-time values -- a rule
comparison, not a reproduction of displayed grades; (ii) the history card's trade-level "Fair trade"
badge (headline side's `pctGap < 3`) is modelled as "every side fair"; (iii) the synthetic population
vs any real frequency.

### 2.2 Results -- real population (153 sides, 76 trades)

| measure | value |
|---|---|
| history "Fair trade" sides / owner FAIR sides | 22 / 28 |
| FAIR-vs-not classification differs | **6 sides (3.9 %)**; 3 of 76 trades (3.9 %) |
| direction | 6 history-not-fair -> owner FAIR; **0** history-fair -> owner not-fair |
| cause (sequential) | relative cut 3.0 -> 3.5: 0; floor added: **6**; utility denominator: 0 |
| grade bucket would change if only the fair boundary were the owner's | 6 sides, all to "Fair trade" (from the lowest not-fair tier) |
| by shape (sides: flips) | 1v1 32: 4; 2v1 28: 0; 2v2 24: 2; larger two-team 66: 0; multi-team 3: 0 |
| by picks | pick involved 75: 4; no pick 78: 2 |
| by `\|gap\|` vs the 250 floor | under 1x: 28 sides, **all 6 flips**; every side at 1x or more: 0 flips (125 sides) |
| 250 floor | 28 sides (18.3 %) sit under it; 22 of them are already history-fair; the floor alone makes 6 (3.9 %) owner-FAIR |
| W/L rule (`\|pct\| >= 3` vs band non-fair) | wins 66 -> 63, losses 65 -> 62; 6 sides change status (3 win -> none, 3 loss -> none) |
| owner relative % / history % | median 1.12, p10 1.00, p90 1.30 |
| package utility / history scale | median 0.90, p10 0.77 |
| fair boundary monotone in the history margin? | **No**: largest history margin the owner still calls FAIR is 7.7 %; 30 owner-NOT-fair sides have a smaller margin than that (the floor, by design) |
| if the history margin were the owner's relative gap (history cut points kept) | 37 sides (24.2 %) would move to a more severe tier; none less severe |

History tier (rows) by owner level (columns), real: tier0 (<3 %): fair 22 | tier1 (3-8 %): fair 6,
slight 24, unfair 6 | tier2 (8-15 %): unfair 23, lopsided 2 | tier3 (15-25 %): unfair 4, lopsided 20 |
tier4 (25-40 %): lopsided 24 | tier5 (40 %+): lopsided 22.

Read it honestly: the real trades are mostly large (hindsight, and trades with retired picks dropped),
so 125 of 153 sides sit far outside every band and cannot disagree. The real result is "the only
disagreement is the floor on small trades".

### 2.3 Results -- synthetic population (3,000 sides, 1,500 trades)

| measure | value |
|---|---|
| history "Fair trade" / owner FAIR sides | 394 / 612 |
| FAIR-vs-not differs | **222 sides (7.4 %)**; 111 of 1,500 trades |
| direction | 220 history-not-fair -> owner FAIR; 2 history-fair -> owner not-fair |
| cause (sequential, net of direction) | relative cut +62 to fair; floor +184 to fair; utility denominator **28 to not-fair** |
| owner FAIR only because of the floor | 196 sides (6.5 %); 556 sides (18.5 %) under the floor |
| by shape (sides: history-fair / owner-fair / history-not-fair-owner-fair) | 1v1 584: 86 / 252 / 166; 2v1 610: 86 / 122 / 36; 2v2 586: 68 / 86 / 18; larger two-team 1,220: 154 / 152 / 0 (2 owner-stricter) |
| by `\|gap\|` vs floor | under 1x: 556 sides, 216 flips; 1x-2x: 500, 6 flips (4 + 2); 2x or more: 0 flips |
| W/L | 222 sides change status (110 win -> none, 110 loss -> none, 1 none -> win, 1 none -> loss) |
| owner relative % / history % | median 1.11, p90 1.20 |
| rebased margin tiers | 392 sides (13.1 %) would move to a more severe tier |

The synthetic population confirms the shape: **small packages and 1-for-1 / 2-for-2** drive the
history-stricter flips (cut and floor), **deep packages** drive the rarer owner-stricter flips
(denominator).

## 3. Three concepts, three vocabularies

| concept | question | owner | basis | recipient | must never say |
|---|---|---|---|---|---|
| **MARKET FAIRNESS** | Is this package gap inside the fairness band, now? | `fairness_bands` | current values, both teams neutral | anyone (public) | recommend, accept, decline, good/bad for you |
| **TEAM RECOMMENDATION** | Should this team make the trade? | `trade_decision` + `team_verdicts` | current values + roster, strategy, gates | the owner of the team (private) | "fair" as the verdict (fairness is an input, not the answer) |
| **HISTORICAL OUTCOME** | How did the completed trade measure, on a stated value basis? | `trade_grading` (+ aging) | at-the-time or current values, **named** | league members | "FAIR TRADE" / "NOT FAIR" (the advisor's phrase), or any claim about whether it was fair *when proposed* unless it uses the advisor's predicate |

Copy that would keep them apart (all **PROPOSED**, none applied):

* History tier 0: rename `Fair trade` to a margin word that is not the advisor's phrase, e.g.
  `Even outcome` (card badge: `Even outcome` instead of `Fair trade`). Tiers 1+ unchanged.
* Every history grade carries its basis in the label or tooltip: `At the time` / `Today` (the public
  timeline already says which; the `/trades` card does not for the badge).
* The advisor keeps `FAIR TRADE` / `NOT FAIR` / `UNABLE TO DETERMINE` and the "within our fairness
  threshold" sentence; it never shows a margin tier.
* The War Room keeps its category and states fairness as one input ("market gap: FAIR").
* One percentage per trade where both appear (Section 1.3, last row): label the history percent "of
  the larger adjusted side" or move it to the owner's base under option C.
* Winners & Losers: describe the rule in words ("3 % or more of the larger side"), and take the
  literal from one named constant (all JS copies).

## 4. OD-F6 options

All flags below are **designs**, default **OFF**, none created. Reading convention in this
repository: `RISKIT_FEATURE_<NAME>=0` plus a restart is the rollback for a backend flag. Because the
history grade has a client-side twin (`league-analysis.js`), a flag that changes the math must be
**served** (a backend-stamped `historyGradePolicy` field on the data contract / the as-of response,
e.g. `legacy_3pct` | `band_owner_v2`), read by both languages from that one source, so Python and
JavaScript cannot disagree and rollback needs no frontend deploy.

### Option A -- leave the math, relabel the tier word

* Change: copy only. History tier-0 label `Fair trade` -> `Even outcome` (and the `/trades` badge);
  basis shown in the label/tooltip; the five `3` literals in the JS become one named constant (no value
  change). `tests/fixtures/trade_grade_parity_cases.json` keeps its numbers; the label field changes in
  both parity suites.
* Measured impact: **0 sides, 0 trades change grade; 0 W/L changes.** Only the displayed word.
* Does not resolve the "win" collision (§1.3): a 3.0-8 % history "Slight win" remains next to a market-FAIR trade. Adding that wording to the copy list is part of the option if the owner wants it resolved.
* Contract note: as designed, the flag serves `historyGradePolicy.wording`, which is an API contract and fixture change, so it is not a "zero-change copy edit". A flagless copy-only change is the alternative; the owner picks one.
* Risk: low. Does not make the two thresholds agree -- it stops *calling both* "fair". The percentage
  and denominator differences remain (labelled).
* Flag design: `history_grade_outcome_wording` (default OFF). OFF = today's labels. Rollback
  `RISKIT_FEATURE_HISTORY_GRADE_OUTCOME_WORDING=0` + restart; served as `historyGradePolicy.wording`.
  (A copy-only change could also ship without a flag; the flag keeps it reversible without a deploy.)
* Needs the owner: the replacement word.

### Option B -- the history grade's fair boundary comes from `fairness_bands_v2`, behind a flag

* Change: `trade_grading.grade_trade_side` (and its JS twin) decide "Fair trade" by
  `fairness_bands.counts_as_fair_trade(classify_packages(...).level)`; every tier above fair stays on
  the history cut points (the script's `hybridLabel` is exactly this).
* Measured impact: real **6 / 153 sides (3.9 %)**, 3 / 76 trades, all to `Fair trade`; synthetic
  **222 / 3,000 (7.4 %)**, 220 to `Fair trade`, 2 away from it. W/L: 6 real sides (222 synthetic)
  change status -- the W/L rule must move with it or `Won`/`Lost` and the badge disagree.
* Risks: (1) the grade stops being monotone in the history margin (the floor makes a 7.7 % margin
  `Fair trade` while a 4.2 % margin is `Slight win`; the TC-A invariant "a bigger win never earns a
  lower letter" needs an explicit carve-out or a test change); (2) it retroactively re-grades
  history (every user sees old grades move); (3) both parity suites and the shared fixture change;
  (4) it reads the *advisor's* predicate for a *historical* question, so the word "fair" then means
  "fair by today's bands, on this value basis", which must be said.
* Flag design: `history_grade_fairness_bands` (default OFF), `historyGradePolicy.fairBoundary =
  "band_owner_v2"`, rollback `RISKIT_FEATURE_HISTORY_GRADE_FAIRNESS_BANDS=0` + restart.

### Option C -- one shared owner function, two separate named outputs

* Change: add one function in the band-owner module that returns, for a (got, gave) pair, both
  `marketFairness` (the band level and relative % -- the advisor's quantity) and `outcomeMargin` (the
  history tier, on the **owner's base** so both read one percentage). The history card shows the
  outcome tier and, where the owner's predicate disagrees, a separate market-fairness chip; the
  advisor reads only `marketFairness`. `Won`/`Lost` and the badge are defined on `outcomeMargin`.
* Measured impact: option B's fair-boundary effect, **plus** re-basing every tier: with the history
  cut points kept and the owner's base, **37 / 153 real sides (24.2 %)** and 392 / 3,000 synthetic
  (13.1 %) move to a more severe tier (none less severe). Tier cut points would then need an owner
  recalibration (they are PRIORs today).
* Risks: widest change (two grades, UI, fixture, aging inputs); makes "same word, same predicate"
  *and* "one percentage" true; the most to validate. Depends on OD-F4 post-launch evidence for the
  band numbers it would inherit.
* Flag design: `history_grade_dual_output` (default OFF), `historyGradePolicy.outputs =
  "market_and_outcome"`, rollback `RISKIT_FEATURE_HISTORY_GRADE_DUAL_OUTPUT=0` + restart. Nothing
  about it may reach a public payload beyond what the public `/league` grade already shows (band
  and label, no values).

### Comparison

| | A relabel | B fair boundary = owner | C shared owner, two outputs |
|---|---|---|---|
| sides whose grade changes (real / synthetic) | 0 / 0 | 6 (3.9 %) / 222 (7.4 %) | B plus tier moves: 37 (24.2 %) / 392 (13.1 %) more severe |
| "fair" means one thing | no (stops sharing the word) | yes | yes, and one percentage |
| monotone letters | unchanged | broken at the floor (needs a carve-out) | redefined by the owner |
| files touched | copy, JS constant | trade_grading, league-analysis, fixture, 2 suites, W/L, page | B plus owner module, API, UI, aging |
| reversible without deploy | yes (served policy) | yes | yes |

## 5. Recommendation (PENDING owner)

**A now, with C kept as a designed, evidence-gated follow-up; B alone is not recommended.**

1. The measured disagreement (a lower bound: unpriced pick trades near the floor are excluded and the at-the-time population is unmeasured) is small and one-directional on real trades (floor only, history is the
   *stricter* one; never history-fair while the advisor says NOT FAIR), so there is no urgency to
   change the math and a retroactive re-grade (B) buys little.
2. The user-visible harm is the **shared word** and the **two percentages**, which A fixes at no
   numeric risk.
3. B on its own leaves a non-monotone grade and a second fair predicate under a new name; if the
   owner wants one predicate, do it as C, once, after OD-F4 evidence says the band numbers survive,
   because C inherits those numbers.
4. Keep the three concepts separate (Section 3) regardless of which option is chosen.

## 6. OD-F6 -- ready-to-use owner decision text (PENDING; not decided)

> **OD-F6 -- League Hub trade-history "Fair trade" grade.**
> The history grade's "Fair trade" (below 3.0 % of the larger adjusted side, no floor) and the advisor's
> FAIR (band `fair` of `fairness_bands_v2`) are different predicates. Measured at one pinned board they
> disagree on at least 3.9 % of real trade sides (6 of 153; all from the 250-point floor, the history grade
> being the stricter) and 7.4 % of a synthetic grid. The real figure is the current-board gradable subset only
> (76 of 105 trades; trades with unpriced assets, mostly picks, are excluded; the at-the-time population the
> public timeline shows is unmeasured).
> **Choose one:**
> 1. **A -- relabel only (recommended now).** Rename the history tier-0 word to "Even outcome" (and the
>    `/trades` badge), state the value basis in the label, define the 3 % literal once. No grade,
>    W/L, aging or band changes.
> 2. **B -- history "fair" boundary from `fairness_bands_v2` behind a default-OFF flag.** 3.9 % of real
>    sides re-grade (all to "Fair trade"); the W/L rule moves with it; letters stop being monotone at
>    the floor (carve-out needed).
> 3. **C -- shared owner function, separate market-fairness and outcome outputs behind a default-OFF
>    flag**, activation only after OD-F4 evidence and an owner recalibration of the margin tiers.
> 4. **Leave as is** and record the difference as accepted.
> Whichever is chosen, no flag is activated by this decision; each activation is a separate owner
> approval after the checklist in Section 7.
> Answer: ______ (A / B / C / leave); replacement word for "Fair trade" (if A): ______.

Status: **PENDING.** No option is approved.

## 7. Before any activation

* Owner decision on the option and the copy (Section 6); nothing here records it.
* Evidence: re-run this script on the **at-the-time** population once an identity-proven, public-safe
  export of the real trade ledger exists (or run it box-local against the ledger), and compare to the
  displayed public grades; OD-F4's post-launch validation of the band numbers (B and C inherit them).
* Tests: update `tests/fixtures/trade_grade_parity_cases.json` and both parity suites for the chosen
  option; add the W/L rule to the shared fixture (it is not pinned today); a registry test that any
  public label reading "fair" is produced by `fairness_bands` (the audit's recommended item 6) once
  the option makes that true; a served-policy test that Python and JavaScript read the same
  `historyGradePolicy`; a monotonicity test with the explicit floor carve-out for B.
* UI copy: the Section 3 vocabulary, the basis label, one percentage per trade, an unchanged
  `Insufficient historical evidence` / `Aging unavailable` state.
* Guards that must stay green: no model/threshold edit outside the owners; `fairness_bands_v2`
  and `geom_q078_v1` untouched; `TRADE_HISTORY_AGING_SPEC` rules (same methodology on both
  timestamps; missing is not today's value) unchanged; How It Aged's +/-200 stays a labelled PRIOR.

## 8. Engineering-reliability applicability check

Against `docs/engineering/ENGINEERING_RELIABILITY_PRIORITIES_2026-09-06.md`, only mechanisms that
could matter to a read-only measurement:

| mechanism | disposition |
|---|---|
| source replay / captured fixtures | `APPLY_NOW`: board pinned by archive + CSV rev + trade-file blob; result reproduces byte for byte |
| typed contracts / OpenAPI | `NOT_RELEVANT` (no API or payload change); a served `historyGradePolicy` is `DEFERRED_BY_AUTHORITY` to the chosen option |
| property-based / mutation tests | `DEFERRED_BY_AUTHORITY`: the monotonicity and fair-boundary properties belong with option B/C |
| deployment identity / persistence | `NOT_RELEVANT` (nothing persisted or deployed) |
| tracing / SLOs | `NOT_RELEVANT` |
| CI / supply chain / agent harness | `ALREADY_COVERED`: the new test file runs in the existing script suite; the helper is byte-identical to its other copy |

## 9. Completion record

* STATUS: PARTIAL (tooling, tests, docs complete; the OD-F6 decision itself is the owner's).
* ACCEPTANCE: surface audit with file:line; read-only measurement of the history grade against the
  band owner on the same trades with attribution; three-way concept separation; options with
  measured impact and default-OFF flag designs; owner decision text; applicability check.
* EVIDENCE: `tests/scripts/test_history_grade_vs_fairness_bands.py`; `results.json` above; format
  contract green.
* UNRESOLVED: OD-F6 (owner); the **at-the-time** population is not reproduced (temporal ledger is
  box-local), so the displayed public grades' disagreement rate is unmeasured; 29 of 105 real trades
  are not gradable on the current board (mostly draft picks the board does not price today); the synthetic rate is
  illustrative.
* BLOCKERS: none for the owner decision; at-the-time measurement needs the box-local ledger.
* NEXT_ACTION: owner answers Section 6; if A, a copy-only PR; if B/C, a claimed implementation lane
  with the Section 7 checklist.
