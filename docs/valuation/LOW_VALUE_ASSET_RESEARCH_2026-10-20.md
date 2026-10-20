# Low-value assets: what they should contribute to a trade (2026-10-20)

**Status: RESEARCH — COMPLETE.** The confirmatory box run is in, and the frozen decision rules have been applied
(§8). **Recommendation: R-C, informational disclosure only.** No canonical value change, and no trade-currency
adjustment.

**Owner decision 2026-10-20: R-C approved** (`docs/owner/LOW_VALUE_ASSET_OWNER_DECISIONS_2026-10-20.md`). The
follow-ups, investigations A and B, the disclosure design and a public-fairness consistency audit, run as separate
workstreams.

**Unchanged in production:**
- `geom_q078_v1` (q = 0.78);
- canonical values and source weights;
- the fairness classification and every recommendation;
- the public calculator's methodology.

Nothing in this program activates or promotes anything.

**Directives:**
- `docs/owner/LOW_VALUE_ASSET_RESEARCH_2026-10-20.md` (the program);
- `docs/owner/LOW_VALUE_ASSET_FINAL_FOLLOWUP_2026-10-20.md` (box run, final follow-up, investigations A and B).

**Frozen protocol:** `evidence/low_value_assets_2026-10-20/PREREGISTRATION.md`. It was frozen before any lane
reported. Amendment 1 changed anchor values only.

**Evidence files** (aggregate-only), all in `evidence/low_value_assets_2026-10-20/`:

| file | evidence line |
|---|---|
| `lineup_utility.json` | U — lineup utility (exploratory) |
| `value_dynamics.json` | D — value dynamics (exploratory, sensitivity replay) |
| `shadow_replay.json` | F — filler flips; T — Team Context (exploratory) |
| `production_box_run_2026-10-20.json` | M1–M4 — confirmatory, owner-run, read-only |
| `forced_drop_diagnostic.json` | investigation A — forced-drop charges |
| `idp_anomaly.json` | investigation B — IDP replacement values |

Each lane ran in its own isolated worktree. Phase 3's evidence and conclusions are untouched.

Agent-OS-Receipt: cb64f74cf4d2763aa16d55ba0d6350f585a2a42f

## 0. Owner summary

**What the evidence says, in one line each:**

- **A, canonical value curve — not supported.**
  - Served history shows low-value assets do *not* lose value faster than mid-range ones over 30 or 60 days.
    Offense at 60 days: 1,000–1,999 retain 1.01–1.03; 3,000–5,999 retain 0.97–0.99 (§7.4). That fails R-A's
    frozen condition, but about 80% of those ratios span a pipeline change, and a fixed-methodology replay shows
    small low-band decay. The evidence is "no excess decay that would justify a curve change", not proof that the
    curve is right.
  - The low end matches rest-of-season usefulness (§3).
- **B, trade-currency adjustment — not supported.**
  - No candidate removes the inappropriate filler flips without re-levelling genuine starter trades (§4).
  - The market does not credit usable depth above filler as the replacement anchor predicts (§7.3).
- **R-B0, Team Context — holds as frozen, for a defect-driven reason.** Today's analyze verdict absorbs filler
  at the roster cap, but mostly because the forced-drop charge is mis-specified (§5).
- **C, informational only — what the frozen rules select.** It changes no numbers.

**The five questions:**

| question | answer |
|---|---|
| 1. Is legitimate depth unfairly penalized? | **Not by the production model.** GEOM_78 credits every piece at its value times its rank discount. Every tested treatment would re-level 31–42% of starter-only trades (F2 fails). Each also removes 7–14% of appropriate depth flips; that stays within the frozen ≤ 25% tolerance (F3 passes), but it is still credit taken from legitimate depth. The one place depth can be over-charged today is the forced-drop release cost (§5). |
| 2. Is Team Context over-charging forced drops? | §5, investigation A: **Yes, on the War Room / analyze path.** The forced cut is picked alphabetically among sub-waiver players and charged at full value rather than surplus, and unpriced players are charged a whole waiver value. With the cheapest legal cut, 110 of 133 filler flips survive, so most of today's "absorption" is the over-charge. This is a roster-capacity defect for its owner; nothing was changed. |
| 3. The IDP replacement anomaly | §6, investigation B: **Not a data bug.** The DB anchor is set by an injured player. The anchor rule counts injured and non-producing free agents as available. And canonical IDP value predicts this league's big-play IDP scoring poorly: rank correlation 0.45, against 0.77 for offense. Managers at a full cap churn IDP by production. So it is a replacement-methodology and league-scoring valuation issue. |
| 4. Can filler turn an unfair trade into a fair one? | **Yes, on context-free surfaces**: the calculator, the 3–4-team meter, Trade Finder in asset-only mode, and Trade History. Example: Hurts vs Egbuka is +722, unfair; adding ~900-point fillers to Egbuka's side carries it through "fair", and four of them reach −1,300, unfair the other way. **Today, mostly no where a full roster is known**: Team Context absorbs 85 of 133 filler flips at the cap. But that is largely the over-charge in §5. With a correct cut, most of those flips survive, and they are genuine roster gains rather than errors. No smooth adjustment fixes it without harming legitimate trades (§4). |
| 5. Effect on the public Fair/Not Fair calculator | §10. Its 2-team path runs with Team Context on, so it inherits §5's release-charge behaviour. Its 3–4-team path is the context-free band, where filler flips are unmitigated. Recommend no methodology or threshold change. A later disclosure must not reveal proprietary numbers. |

**Your preliminary decision is supported by the frozen rules:**
- retain GEOM_78 (q = 0.78);
- retain canonical player values;
- add no blanket trade-currency discount;
- disclosure only (R-C), with any UI separately reviewed.

**Two follow-ups for separate owner decisions** (§11):
1. a roster-capacity release-charge review (investigation A);
2. an IDP league-scoring and replacement-value review (investigation B).

## Contents

0. Owner summary
1. The question, and the three approaches
2. How much low-value players actually contribute
3. Is the canonical scale wrong at the low end? (Approach A, exploratory)
4. Would a trade-currency adjustment help? (Approach B; the filler-flip study)
5. Does Team Context already handle it, and does it over-charge? (investigation A)
6. The IDP replacement-value anomaly (investigation B)
7. Confirmatory box run: validation and M1–M4
8. Decision rules, applied exactly as frozen
9. Comparison of the three approaches
10. The public Fair/Not Fair calculator
11. Recommendation and follow-ups
12. Uncertainties and protocol deviations

## 1. The question, and the three approaches

Phase 3 found that completed trades treat assets below about 2,000 as near-worthless trade currency. The owner
asked how much low-value assets *should* contribute, while preserving legitimate depth, and to compare three
approaches:

| approach | claim | where a fix would live | shadow treatment tested |
|---|---|---|---|
| **A, value curve** | low-end assets are over-valued as holdings | value pipeline (rankings, 1-for-1 trades, everything) | `A_curve_*`: every asset remapped through `g(v; c) = v²/(v + c)`, then GEOM_78 |
| **B, trade currency** | valued correctly as holdings, but extra package pieces buy less | trade engine only; 1-for-1 untouched | `B_currency_*`: one piece per side at full value, the others at `g(v; c)`, geometric by rank |
| **C, informational** | the discount is a convention, so disclose it without changing numbers | UI text | a disclosure when B would change the verdict |

Each treatment is tested with two anchors for `c`:
- **market:** 2,000, kept as a comparator only;
- **replacement:** the league's own waiver value at the asset's position.

Usable depth is distinguished from filler by the league's own position-specific replacement and starter lines,
not by one global threshold (PREREGISTRATION §3).

## 2. How much low-value players actually contribute (lineup utility, `dynasty_main`, 2026 weeks 1–6)

**How it was measured.**
- **Values:** taken from the board **served on 2026-08-25**, before the season.
- **Lineups:** re-solved exactly from Sleeper's weekly points.
- **Checks:** the scorer matched Sleeper on 4,172 / 4,172 player-weeks, and the lineup solver matched Sleeper's
  best-ball lineup on 72 / 72 team-weeks.

| pre-season value | player-weeks | start % | share of league starting points | marginal pts/wk over the best bench alternative | vs the 3rd-best free agent (hindsight) |
|---|---:|---:|---:|---:|---:|
| 1,000–1,499 | 529 | 26.7 | 7.4% | 1.49 | −1.19 |
| 1,500–1,999 | 1,005 | 29.4 | 17.3% | 2.10 | −0.66 |
| 2,000–2,999 | 892 | 37.7 | 20.6% | 2.93 | +0.77 |
| 3,000–4,499 | 588 | 47.1 | 20.6% | 4.71 | +2.88 |
| 4,500+ | 456 | 58.1 | 23.8% | 7.65 | +6.50 |

- **Below 2,000, low-value players still matter.** They supply about a third of the league's starting points
  (with unvalued players included).
- **But a free agent would fill the same spot about as well,** and that is where the market's "near-worthless"
  view holds.
- **The crossover is position-dependent, not a 2,000 line:**

  | position | where it stops beating the wire | why |
  |---|---|---|
  | offense RB / WR | still beats the wire at 1,500–1,999 (+0.32 / week) | — |
  | IDP | does not beat the wire below about 3,000 (1,500–1,999: −1.37 / week) | the wire is deep: best free agent DB 33 pts/wk with hindsight |
  | QB | low-value QBs keep real value | the wire is empty |

- **Usable depth versus filler** (487 rostered players under 2,000 or unvalued):

  | group | count | notes |
  |---|---:|---|
  | never started (filler) | 209 | e.g. Luke Musgrave, Kam Curl, Troy Franklin |
  | started, but a free agent would have done as well | 134 | mostly IDP |
  | **usable depth that beat free replacement** | **143** | Aaron Rodgers (QB, 1,941, +50 season pts over a free agent), Brian Robinson (RB, 1,980, +45), Tre Tucker (WR, 1,957, +39), Amani Hooker (DB, 1,531, +31), DeForest Buckner (DL, 1,916, +27), Tyler Higbee (TE, 1,812, +26) |

  **A flat haircut would penalize exactly the 143.**
- **Our own replacement levels sit around 1,500–2,100,** consistent with the market's ~2,000 level:
  - waiver best by position: RB 1,626 to DB 2,156;
  - cut-ladder median: 1,526;
  - FAAB V_repl: 1,687.

**Limits.** Six weeks is a small sample. The free-agent comparison uses hindsight. 2025 used a 10-team format and
no board on this scale exists for it, so it was not used.

## 3. Is the canonical scale wrong at the low end? (Approach A)

**Value aging.** Median log-ratio of value over 60 days, for veterans in offense, starting before the season.
This is a *sensitivity replay*: today's methodology applied to each day's archived inputs, with the voting panel
held constant. It is not served history.

| | below 3,000 | 3,000 and above |
|---|---:|---:|
| canonical | −1.7% (n 1,165) | −0.6% |
| KTC SF TEP | −4.9% | −2.2% |
| IDP Trade Calculator | −5.6% | −0.8% |

- All three lanes decay slightly more at the low end. The vendors decay 2–3× faster than our board, so our curve
  holds aging low-end veterans relatively **high**.
- The gap is modest: about 3 points of log value per 60 days.
- Mean reversion is weak (a slope of −0.04).
- Rookies and picks run flat on our board while KTC swings.

**Ranking against rest-of-season usefulness.**
- Players valued 1,000–1,500 sit at about 0.98× their ROS-rank equivalent.
- Veterans 25 and older sit at 0.93×.
- Players 24 and younger sit at 1.03–1.2×, which is the normal dynasty premium for youth.
- So **the low end is not ranked above its usefulness.**

**Replacement cost.** Waiver markets in 412 external dynasty leagues:
- 98.9% of priced adds were players valued below 3,000;
- at 1,000–1,500, 61% cost $0, with a median bid of 0.2% of budget;
- in the 2,000–3,000 band, drops outnumber adds 1.4 : 1.

**IDP observation (a separate finding).** In `dynasty_main` the **best unrostered DB (2,156) is valued above the
lowest rostered starting DB (1,335)**, and the same pattern holds for LB and DL. Either managers do not roster by
canonical value, or the shared IDP board does not reflect this league's IDP scoring and the depth of the IDP wire.
That is a valuation question for the scoring-aware/IDP owners, not a package question.

**Read.** As a *holding*, the low end is about right on usefulness and slightly sticky on aging. Approach A is not
supported by local evidence. The served-history check (§7.4, M3) fails R-A's frozen condition, but it is confounded by pipeline changes, so it does not *confirm* the reading.

## 4. Would a trade-currency adjustment help? (Approach B; the filler-flip study)

**The study.**
- 2,825 near-even base trades built from real board assets.
- 1–4 sweeteners added to the trailing side: expendable filler, usable depth or genuine starters.
- 32,180 cases in total.
- Verdicts come from the **shared** fairness classifier.

**GEOM_78 flips about as often on filler as on depth.** For example, in offense 3,017 cases flip on filler and
3,047 on depth. It is size-blind by design.

Preregistered criteria. **No treatment passes F1 or F2 in any asset class.**

| class (incumbent flip cases, filler / depth) | treatment | F1 filler flips removed (need ≥ 80%) | F2 starter-only levels changed (need ≤ 2%) | F3 depth flips removed (need ≤ 25%) |
|---|---|---:|---:|---:|
| offense (3,017 / 3,047) | B_currency_replacement | 21.5% ✗ | 37.1% ✗ | 12.2% ✓ |
| offense | A_curve_market | 27.8% ✗ | 33.8% ✗ | 14.4% ✓ |
| IDP (2,249 / 2,320) | B_currency_replacement | 18.6% ✗ | 35.9% ✗ | 9.0% ✓ |
| picks (1,098 / 1,244) | B_currency_replacement | 13.6% ✗ | n/a | 7.2% ✓ |
| mixed (2,909 / 2,962) | B_currency_market | 21.2% ✗ | 38.9% ✗ | 10.0% ✓ |

**Why no smooth treatment can pass.**
- **The bands are tight.** They sit at 3.5% / 250 points, so any real credit for a ~1,000 filler piece still
  crosses a band on a near-even trade. Under the replacement anchor, `g(1000; 1,800)` is still about 357.
- **A size-aware discount also hits genuine starters.** Discounting the second piece re-levels genuine 2-for-2
  starter trades, so F2 fails.
- **Only a hard zero for filler would pass F1.** That is the "arbitrary threshold" the owner ruled out, and it
  would destroy the 143 usable-depth players from §2.
- **The IDP rows are confounded.** IDP anchors sit above IDP starters (§3), so some IDP "filler" are real
  starters.

Real players (gap from the star's side; level from the shared classifier; today's board):

| trade | GEOM_78 | B_currency_replacement | A_curve_market |
|---|---|---|---|
| Hurts (5,919) vs Egbuka (5,197) | +722 unfair | +722 unfair | +671 unfair |
| … + four ~900 fillers (Hodgins, Gore, Herbert, Tipton) | **−1,300 unfair the other way** | −179 fair | +41 fair |
| Gibbs (9,864) vs Smith + Higgins + four ~1,000 fillers | −674 slight to the package | +497 fair | +1,360 slight |
| Gibbs vs Young + Kraft (two genuine starters) | +129 fair | +356 fair | +1,072 slight |
| Gibbs vs six ~2,950 starters / usable depth | −564 fair | **+871 slight** | **+1,977 unfair** |
| Wilson vs Ferguson + Kelce | +221 fair | **+749 unfair** | +961 unfair |
| Schwesinger vs Baun + Parsons (IDP starters) | +176 fair | +658 slight | +903 unfair |
| 2027 1.04 vs 1.12 + two 4th-round picks | −791 unfair | +22 fair | +241 fair |
| Boston (WR 4,204) vs Bailey (DL) + two ~1,125 DB fillers | −832 unfair | +43 fair | +81 fair |

- **B fixes the real filler cases:** Hurts plus four fillers, the pick sweeteners, and the DB fillers.
- **But it breaks legitimate depth:** Wilson against Ferguson + Kelce, the six-starter package, and the IDP
  starters.
- **A does the same, and worse.**

Decision changes across surfaces (context-free, today's board):

| surface | GEOM_78 → B_currency_replacement | GEOM_78 → A_curve_market |
|---|---|---|
| Calculator: fairness level changed (2,000 trades) | 622–657 trades (more than LP_150's 520 in Phase 3) | 827–852 |
| Trade Finder top-10 overlap, B / A on the market anchor (package scan / all shapes / best offers / builder) | .78 / .34 / .52 / .43 | .56 / .14 / .33 / .32 |
| Trade History grade bucket changed (150 fully priced own-league sides) | 57 | 84 |
| Public category (shadow only; no public route exists) | 43–45 of 180 | 84–92 of 180 |

- No treatment produced a star-for-pile recommendation.
- The user's board edge falls under every treatment. For best offers it drops from 2,288 to 1,463 under B.

**Read.** Approach B removes some inappropriate flips, but at the cost of many appropriate verdicts. It fails the
preregistered bar in every class. **R-B is not met.**

## 5. Does Team Context already handle it, and does it over-charge? (investigation A)

### 5.1 The exploratory test (T, unchanged)

**What was tested:** War Room, i.e. `/api/trade/analyze` with Team Context **on**, under the production GEOM_78.
- **Setup:** every `dynasty_main` roster at the 58-player cap receives 1–3 expendable fillers on a near-even trade.
- **Asset-only scoring:** 133 of 135 sweetened steps flip.
- **With Team Context:** **85 are neutralised**, **43 are over-corrected** (the verdict turns against the receiver),
  and **5 survive**.
- **Release charges:** the median charge is 3,128 against a median filler credit of 1,982. The median of the
  per-step ratios is 1.65×.
- **Unpriced players:** 57 of 270 forced drops are charged at an *assumed waiver value* for players the board does
  not price.

On production behaviour, R-B0's frozen test is met: the existing analyze verdict does discount filler sweeteners.

### 5.2 Investigation A: the charge is mis-specified, and the neutralisation is mostly an artifact of it

`forced_drop_diagnostic.json` and `scripts/low_value_asset_forced_drop_diagnostic.py` reproduce 133 / 85 / 43 / 5
exactly, with the same archive and seed. The rebuilt production cut set matches on 135 of 135 steps. The mechanism
below was checked against the code.

**How the cut is chosen and charged** (component A):

1. **The cut ladder sorts by `ECC = max(0, base − waiver) × multiplier`** (`src/draft/displacement.py:383`, sorted at
   `:455` by `(ECC, name)`).
   - Every player at or below his position's waiver level has ECC 0. That includes every unpriced player, whose
     base is *set* to the waiver value (`:376`).
   - **Among sub-waiver players, the forced drop is therefore chosen alphabetically.** In the examples that meant
     Aaron Donald, Adin Huntington, Alex Singleton, and so on.
2. **The charge is the player's full base value, not his surplus over replacement**
   (`src/trade/roster_capacity.py:1282`: `release_cost = base × scarcity`).
   - An unpriced player is charged the whole waiver value at his position: 1,802–2,156, for example 1,918 at DL.
   - So the selection rule (surplus) and the charge (full value) disagree.
3. **Incoming pieces are cut candidates** (`roster_capacity.py:1234-1237`), but only when their name sorts early.
   - 215 of 270 drops had a cheaper just-acquired piece that was not cut.
   - 253 of 270 had a cheaper legal swap.
   - In **0** cases were all cheaper candidates protected by lineup legality.
4. **The War Room and the Trade Finder use different rules for unpriced drops.**
   - The War Room subtracts the full release cost, unpriced drops included (`trade_decision.py:444-455`).
   - The Trade Finder's `forced_drop_cost` excludes unpriced drops as a labelled lower bound (`roster_capacity.py:687`).
5. **The scarcity multiplier was inert locally** (1.0 on all 270 drops), and is **not** a cause here. On the box
   it can add up to 15%.

**What removes the 43 over-corrections:**

| fix that is enough on its own | count |
|---|---:|
| cheapest legal cut (V1) | 36 |
| either V1 or charging unpriced drops consistently | 5 |
| both together | 2 |

Lineup protection and scarcity cause none of them. 31 of the 43 involve multiple drops, and 28 charge more than
the raw value of the fillers received.

**Shadow counterfactuals** (same 133 asset-only flips; no production change):

| variant | neutralised | over-corrected | survive | steps with charge > credit | median charge / credit |
|---|---:|---:|---:|---:|---:|
| production | 85 | 43 | 5 | 127 | 1.65 |
| V1: cheapest legal cut (incoming pieces eligible) | 21 | 2 | 110 | 10 | 0.55 |
| V2a: production cuts, unpriced charged 0 | 60 | 38 | 35 | 95 | 1.25 |
| V2b: production cuts, unpriced capped at the position's board floor | 64 | 38 | 31 | 97 | 1.29 |
| V3: V1 and V2 together | 5–6 | 0 | 127–128 | 2 | 0–0.25 |
| V4: package-consistent (cutting an acquired filler removes it from the package) | 1 | 0 | 132 | 0 | 0.25 |

### 5.3 Answer to question 2, and what it means for R-B0

**Yes: on this path Team Context over-charges forced drops.** The demonstrated defect is a mismatch:
- the cut is *selected* by surplus over waiver (ECC), which is 0 for every sub-waiver player, so the choice among
  them falls to name order;
- it is *charged* at the player's full base value.

V1 (cheapest legal cut) keeps the full-value charge and alone removes 41 of the 43 over-corrections. Charging
surplus instead was not tested.

Unpriced players are charged a whole waiver value. A rational receiver could always cut the cheaper incoming filler
instead.

**Most of the "neutralisation" in §5.1 is a by-product of the over-charge.** With the cheapest legal cut, 110–132 of
the 133 filler flips survive.
- The cheapest cuts are real deep-bench players: median 445, and 27 of 270 sit at a position's board floor.
- So a filler worth more than the receiver's worst player is a genuine gain, and the surviving flips are the correct
  *roster* answer.

**Caveat.** The board's floor values are a known artifact (CLAUDE.md, Perfect Draft: single-source players at 375 /
497). V1's cut values may therefore understate the true cost of some cuts.

**R-B0 under the frozen wording.** The rule asks whether the *existing* analyze verdict already discounts filler
sweeteners at the cap, and on production behaviour it does, so **R-B0 holds as frozen**. But the reason is
defect-driven. The durable reading is:
- **Team-aware surfaces should price filler through a correct roster-capacity charge** (value over the receiver's
  cheapest legal cut), not through a trade-currency discount. A currency discount layered on top would double-count
  once the charge is fixed.
- **After the fix, filler flips on team-aware surfaces become *appropriate* flips:** the receiver really does gain.
  The informational disclosure (R-C) remains the right tool where the market convention differs from that roster
  answer.

**Limits:**
- Component B (the lineup lens) cannot be evaluated locally, so only component A is measured.
- Scarcity was inert locally.
- 45 trades on a single board; exploratory.
- **This is a defect report for the roster-capacity owner.** Nothing was changed (§11, follow-up 1).

## 6. The IDP replacement-value anomaly (investigation B)

**The observation.** The best *unrostered* IDP is valued above the lowest IDP *starter*:

| position | best unrostered | lowest starter |
|---|---:|---:|
| DB | 2,156 | 1,335 |
| LB | 2,149 | 1,474 |
| DL | 1,918 | 1,539 |

`idp_anomaly.json` and `scripts/low_value_asset_idp_anomaly.py` reuse the shadow context, so they reproduce S1
exactly. Their scorer matched Sleeper's points on 3,300 of 3,300 player-weeks.

**Verdict on each hypothesis:**

| hypothesis | verdict | evidence |
|---|---|---|
| H1 data defect (rostered players showing as free) | **rejected** | All 24 unrostered IDP valued at or above the lowest starter are absent from live rosters (checked by Sleeper id), and all have an NFL team. The board's only name-join miss is a DL at 1,267, below the anomaly. **However, 10 of the 24 are injured or inactive now**, including Winfield (Out), who sets the 2,156 DB anchor. |
| H2 lineup definition | **settled** | The 12 "optimal lineups" are solved on `rankDerivedValue`, not projections. The lowest-valued starters are productive veterans: a DB at 10.3 ppg, an LB at 8.2, a DL at 7.9. Re-solved on actual points, only 34% (DB), 47% (DL) and 74% (LB) of the *production* starters are also in the value-based lineup, against 60–76% in offense. |
| H3 league-scoring mismatch | **supported** | Rank correlation between value and points per game under `dynasty_main`'s card: offense 0.77, IDP 0.45 (the served pre-season board gives 0.67 vs 0.40). DL ~0.32, DB ~0.35, LB ~0.6; ~0 among unrostered IDP. The card rewards big plays: pass defended and interception 5.3, tackle for loss 4.24, solo tackle 1.33. A tackle-share comparison was mixed, so the exact cause is unsettled. |
| H4 manager behaviour | **supported (churn, not stale rosters)** | Eleven rosters sit at the 58 cap and one at 59, with no taxi or IR players, so every add forces a drop. Managers drop injured and non-producing IDP. 176 IDP waiver/FA adds in weeks 1–7, against 149 for offense; 13 of the 24 were rostered 60 days ago. On IDP, value separates rostered from unrostered (0.79) no better than points do; on offense it does much better (0.93). |
| H5 board risers | **rejected** | With today's code over archived inputs, the 24 moved 0.986× over 60 days, while rostered 1,000–2,999 IDP fell to 0.94×. The served-history appreciation in M3 is therefore *plausibly* methodology (pipeline-version) change rather than input change. That is a comparison of 24 `dynasty_main` players against full-ledger bands, and served history was not available locally to confirm it. |

**Answer to question 3.** The anomaly is not a data bug. It has three parts, which overlap:

1. **Replacement methodology:** the waiver anchor is the single best unrostered player by value. That counts
   injured or inactive players and non-producing rookies as available replacements (`displacement.waiver_values_by_position`,
   also used by Perfect Draft).
   - Excluding injured players, DB falls from 2,156 to 1,917.
   - DL (1,918) and LB (2,149) are rookies scoring 1.7 and 2.8 ppg. A healthy-only, rank-k or LI-5 banded level would
     be sturdier.
2. **Valuation and league scoring:** the shared IDP board predicts this league's big-play IDP scoring much worse than
   offense value predicts offense scoring.
3. **Roster management:** managers at the cap churn IDP by production and health.

**Implications for this program:**
- (a) Using the waiver value as the IDP replacement anchor inflates the IDP "filler" count. 19 of 35 DB starters
  sit below even the healthy anchor.
- (b) The *conclusion* that low-value IDP is weak trade currency still holds on production evidence: the lineup lane
  found IDP under ~3,000 does not beat the wire on points. But it should rest on production, not on the value anchor.

IDP stays insufficient for any class-wide recommendation (138 graded trades).

**Handling:** the scoring-aware IDP / value-pipeline owner (not identity). The waiver-anchor rule belongs with the
displacement owner (§11, follow-up 2).

**Limits:**
- Six weeks of games, with at least 3 games per player for ppg; the free-agent comparison uses hindsight.
- Today's values already reflect this season, so the served pre-season board is reported alongside.
- The board is local (2026-10-20); rosters were fetched live.
- Older dates are a sensitivity replay, not served history.

## 7. Confirmatory box run: validation and M1–M4

**Run details:** `scripts/low_value_asset_box.py --box`, owner-run 2026-10-20 12:34 UTC.
- Code pinned at `348313b1c`, with all six files sha256-verified before running.
- Deployed SHA `f631607ff`; peak RSS 1,124.7 MB; exit 0.
- Report: `production_box_run_2026-10-20.json` (sha256 `f5daf9f8…6613a`).

### 7.1 Validation

| check | result |
|---|---|
| Aggregate-only | passes `assert_aggregate_only`; no league, user, roster, transaction or asset identifiers |
| Read-only guard | installed; **0** refused write or process attempts |
| Population | 18,690 graded trades, 11,565 leagues, 91 boards, trades 2026-07-15 → 10-20. The audit block is **identical, key for key,** to the Phase 3 production run (same ledger build, 2026-10-20 08:56 UTC) |
| League concentration | largest league 0.2% of trades; top five 0.6% |
| Split | league-disjoint `sha256("lva-2026-10-20" \| league)`: discovery 9,199 / confirmation 9,491. No trades fell outside a league; 0 prospective trades (the run predates any trade after the freeze) |
| Anchors and starter lines | equal to Amendment 1 (pinned by test) |

**Refused network calls.** The guard refused all **273** network calls from one site:
- `src/api/data_contract.py:9543`, inside `_resolve_league_context`, which reads `total_rosters` and
  `bonus_rec_te` from Sleeper and otherwise falls back to defaults;
- that is 3 calls for each of the 91 boards;
- Phase 3's run refused exactly the same 273 calls from the same site.

The Phase 3 offline-parity audit (`../package_model_phase3_2026-10-20/offline_parity_audit.json`) still applies to
this run, for three reasons:
1. **The audit itself.** It covered 138 boards (2026-07-14 → 10-18): 0 of 136,558 values change between the fallback
   and the live context. A control using a different league context (2025: 10 teams, TE bonus 0.35) changes 8,370
   values, so the audit can detect a difference.
2. **The code is unchanged.** Between Phase 3's deployed SHA (`fd798c3`) and this run's (`f631607`), nothing under
   `src/`, `scripts/` or `config/` changed. Only 5 frontend and E2E test files plus data refreshes did.
3. **The two boards after the audit window** (10-19, 10-20) also give the fallback's numbers. The live league was
   queried today and returns `total_rosters` 12 and `bonus_rec_te` 0.0, exactly the fallback.

**Fallback impact on this run: none.**

**Exclusions** (from the audit block), stated as the owner asked:

| excluded | count | why |
|---|---:|---|
| board basis not superflex, or unknown | 7,064 | — |
| pieces unpriced on the point-in-time board | 1,377 | — |
| empty | 1,661 | — |
| no board strictly before the trade | 544 | — |
| one-sided | 176 | — |
| **multi-team (3+ teams)** | **64** | **every multi-team trade is excluded; nothing here speaks to 3–4-team packages** |
| possible duplicates | 21 | — |
| FAAB | 16 | — |
| unresolved | 25 | — |

**Asset-class sizes:**

| class | graded trades | unequal-bin trades (discovery / confirmation) | status |
|---|---:|---:|---|
| mixed offense + picks | 14,823 | 4,619 / 4,743 | adequate |
| player-only offense | 3,648 | 671 / 734 | adequate |
| **IDP-involved** | **138** | **43 / 47** | **insufficient for any class-wide conclusion** |
| pick-only | 81 | 19 / 17 | insufficient |

### 7.2 M1 — agreement with completed trades

M1 is necessary for R-B and never sufficient on its own. The signed residual is the gap from the fewer-pieces
side's point of view; negative means the model under-credits that side relative to the trade that happened. J is
the worst unequal-bin |mean|.

| | J, discovery | J, confirmation | confirmation 1-for-N small | ordinary | deep |
|---|---:|---:|---|---|---|
| GEOM_78 (production) | 0.298 | 0.302 | −0.302 [−0.309, −0.296] | −0.135 | −0.125 |
| A_curve_market | 0.124 | 0.127 | −0.127 [−0.132, −0.123] | −0.052 | −0.043 |
| A_curve_replacement | 0.138 | 0.141 | −0.141 [−0.146, −0.136] | −0.059 | −0.051 |
| B_currency_market | 0.180 | 0.183 | −0.183 [−0.189, −0.178] | −0.083 | −0.074 |
| B_currency_replacement | 0.199 | 0.202 | −0.202 [−0.208, −0.196] | −0.093 | −0.085 |

Brackets are league-clustered 95% CIs.

**What this shows:**
- **The incumbent's residual reproduces Phase 3:** confirmation 1-for-N −0.302 here, against −0.298 there.
- **Every treatment moves toward the completed trades, and still under-credits the consolidating side** by 13–20%
  of the trade's size.
- The ordering is stable between discovery and confirmation, and within every adequately sampled class:
  - player-only offense: J 0.256 → 0.097–0.162;
  - mixed: 0.310 → 0.132–0.209.

**Reading** (the owner's point 1). Every candidate agrees with completed trades better than GEOM_78. The curve
remaps (A), which also change 1-for-1 trades, agree best. **Agreement is not the objective.** Phase 3 already
showed that a model closer to the market can be a worse adviser. The program's goal is how much these assets
*should* contribute, not how to imitate accepted trades. So M1 satisfies one R-B condition and decides nothing else.

### 7.3 M2 — implied credit for the extra piece

**Definition.** For 1-for-2 trades: `w = (a − b₁) / b₂`. This is the fraction of the second piece's value the trade
implies was credited, assuming the first piece counts in full and the completed trade was value-fair.

| extra piece | n | median w | IQR |
|---|---:|---:|---|
| starter class | 3,272 | 0.211 | [−0.023, 0.431] |
| filler class | 517 | 0.183 | [−0.133, 0.415] |
| usable-depth class | 842 | 0.093 | [−0.102, 0.317] |
| by value band: 1,000–2,499 | 2,605 | 0.093–0.185 | — |
| by value band: 2,500–3,999 | 1,618 | 0.222 | — |
| by value band: 4,000+ | 406 | 0.318 | — |

**Usable depth gets *less* implied credit than filler.** This is the opposite of what the replacement anchor
predicts. **It is not a causal effect.** It is largely a composition artifact of the frozen classification (the
owner's point 2):

- **"Usable" is almost entirely picks.** 832 of the 842 usable extras are picks, against 177 of the 517 fillers.
  In offense the §3 rule leaves almost nothing in the usable band, because the starter line sits *below* the
  replacement anchor at WR (1,510 vs 1,802) and TE (1,671 vs 2,061). An offensive player between those numbers
  is classed a starter. Usable offense exists only in two narrow windows: QB 1,923–1,987 and RB 1,626–1,652.
  Offense usable has n = 10, which is insufficient.
- **The comparison is therefore mostly picks vs players,** and pick extras are credited less than player extras at
  the same value:
  - 1,000–2,499 band: picks 0.105 (n 1,344), offense players 0.174 (n 1,256);
  - this matches Phase 3's finding that pick-heavy packages carry the largest residuals.
- **Within picks the order is still non-monotone:** filler 0.170, usable 0.093, starter 0.196.
  - On today's board, the usable pick band (1,687–2,386) is mainly 2027 rounds 3–6 slot picks. Their value is
    tethered to the rookie pool.
  - The filler pick band is mainly 2028–2029 rounds 4–6.
  - So within picks the comparison is also a pick-type comparison (year, round, tether), not a depth comparison.
  - Trade-time boards were not re-examined for this mapping (§12).
- **Ratio noise.** `w` divides by the extra piece's value, so it is noisiest for the smallest pieces. The IQRs are
  wide in every class.
- **Selection.** Only completed trades are observed, and only those that pass the audit filters.

**What M2 does support:** the market credits extra pieces at a small fraction of their value in **every** class.
Even starter-calibre extras get a median 0.21, rising with value to 0.32 at 4,000+. **The market's discount is a
general extra-piece convention, not a filler-specific one.** A filler-specific treatment therefore cannot reproduce
it, and the replacement anchor does not explain it.

**IDP M2 cells:** n = 1–10, so insufficient.

### 7.4 M3 — served-history value dynamics

Source: the temporal ledger's `canonical_board` lane (1,879 assets). Starts are weekly from 07-15 to 09-16, with
30- and 60-day horizons. Retention is the value at the horizon divided by the value at the start. Drop-offs are
counted as missing, never as 0.

| offense band | 30d median (n, missing, pipeline changed) | 60d median (n, missing, pipeline changed) |
|---|---|---|
| 1,000–1,499 | 1.011 (1,065, 13%, 42%) | **1.030** (531, 56%, 81%) |
| 1,500–1,999 | 1.004 (796, 16%, 44%) | **1.008** (434, 54%, 80%) |
| 2,000–2,999 | 0.997 (781, 19%, 42%) | 0.995 (419, 56%, 79%) |
| 3,000–4,499 | 0.997 (522, 19%, 43%) | **0.987** (281, 56%, 79%) |
| 4,500–5,999 | 0.986 (324, 18%, 44%) | **0.974** (178, 55%, 80%) |
| 6,000+ | 0.993 (342, 18%, 46%) | 0.984 (194, 53%, 80%) |
| below 1,000 | 1.02–1.04 at 30d (n 45–82) | **no observations** |

**IDP:**

| band | 30d | 60d | note |
|---|---:|---:|---|
| 1,000–1,499 | 1.04 | 1.08 | appreciates |
| 1,500–1,999 | 1.00 | 1.06 | appreciates |
| 500–999 | 1.39 | 1.39 | n 90 / 76; 84–100% of observations span a pipeline change |
| 4,500–5,999 | 0.93 | 0.91 | — |

**Picks** appreciate in nearly every band (4,500–5,999 at 30 days is 0.99); the low bands appreciate most (1.15–1.26 at 60d, n 30–47). That is consistent with time-to-draft,
and with derived-pick methodology changes. Pick missingness is high above 1,500 (27–36% at 30d; 1,000–1,499 only 1%).

**Reading:** the predicted excess 60-day depreciation of low-value assets is **absent**. In offense, low bands
retain *more* than the 3,000–5,999 band; in IDP they appreciate.

**Caveats** (the owner's point 3):

- **Missing horizons.**
  - Most 60-day missingness is structural: horizons after the ledger's last day (10-20) cannot be observed. Only 6
    of the 10 weekly starts (07-15 to 08-19) have one.
  - The remaining 30-day missingness is similar across offense bands of 1,000 and up (13–19%). So survivorship does
    not differ by band in the range R-A is about.
  - Below 1,000, 26–31% of 30-day observations are missing and none exist at 60 days. **The sub-1,000 range cannot
    be assessed.** No observation there spans a pipeline change, which suggests these rows enter the ledger only in later windows, plausibly off-cap player values (priced since 2026-08-25). This was not verified.
- **Pipeline-version changes.**
  - 42–46% of offense 30-day ratios, and about 80% of 60-day ratios, span a pipeline change. Served history mixes
    market movement with methodology changes. That is honest about what users saw, but it cannot separate the two.
  - Band-wide shifts partly cancel in the band comparison R-A uses. Band-specific methodology changes would not:
    for example the IDP source-independence and pick-completeness work. The IDP and pick rows are the most exposed.
- **Clustered confidence intervals were not produced.** This is a protocol deviation, recorded in §12.
  - R-A's frozen M3 condition requires low-band 60-day retention *below* the 3,000–6,000 band "by more than its
    clustered CI".
  - The observed point estimates are on the other side: 1.008–1.030 against 0.974–0.987. So **no interval width
    could satisfy the condition**, and the missing CI cannot change the R-A outcome.
  - The CI would be needed to claim low bands are *better*-retained, and this memo does not claim that.
  - Observations are also not independent: overlapping windows and the same asset at several starts. The effective
    sample is smaller than n.

### 7.5 M4 — do traded extras keep their value?

**Population:** 1-for-2 trades at least 30 days old with both pieces identified: 1,234 trades, 2,468 lookups.

| piece | n | median 30-day retention |
|---|---:|---:|
| consolidated piece | 1,090 | 0.999 |
| extra piece, all | 919 | 1.005 |
| extra, filler | 95 | 1.009 |
| extra, usable | 108 | 1.030 |
| extra, starter | 716 | 0.997 |

**Reading:** pieces traded as extras, filler included, kept their value over 30 days as well as the piece they were
traded for.

**Caveats** (the owner's point 4):
- **Missing lookups:** 459 of 2,468 (18.6%), and they are **unequal**. 315 extras are missing (25.5%) against 144
  consolidated pieces (11.7%).
  - An extra that fell off the board is not counted, so if drop-offs are value collapses, M4 is conditional on
    survival and *overstates* extras' retention.
  - The direction of that bias favours the extras, so M4 cannot be read as evidence that extras hold value
    *better*. It only fails to show they lose it faster.
- **Selection:** only trades dated on or before 09-20 can have a 30-day horizon. That window is the earlier,
  sharp-discovery-heavy part of the ledger, so it is not representative of October's KTC-heavy population.
- **Small classes:** filler n 95, usable n 108. These are indicative only.

## 8. Decision rules, applied exactly as frozen

**R-A: recommend investigating a canonical-curve change.** It needs all three conditions. **Not met.**

| condition | result | evidence |
|---|---|---|
| D: low-band decay in both our lane and the vendor lane | **met (small)**: every lane decays more at the low end over 60 days (canonical −1.7% vs −0.6%; KTC −4.9% vs −2.2%; IDPTC −5.6% vs −0.8%). The frozen rule sets no magnitude. The canonical replay panel excludes KTC on every board | §3 |
| M3: served low-band 60-day retention below the 3,000–6,000 band by more than its CI | **fails as frozen**: low bands retain *more* (1.008–1.030 vs 0.974–0.987). Confounded: about 80% of the 60-day ratios span a pipeline change, and the fixed-methodology replay shows small low-band decay (§3; `idp_anomaly.json` H5: rostered offense 1,000–2,999 at 0.966) | §7.4 |
| U: low-band usable depth contributes little lineup value relative to its value | **not met, contestable**: the low end matches ROS usefulness and 143 low-value players beat free replacement. But on average players under 2,000 trail the 3rd-best free agent (−1.19 / −0.66 pts/wk), and the 143 were identified with hindsight | §2, §3 |

**R-B: recommend a B treatment for owner approval on context-free surfaces.** It needs all five conditions. **Not
met:** two conditions fail (F, M2) and a third (T) cannot be demonstrated.

| condition | result |
|---|---|
| F1–F3 in offense and mixed packages | **fails**: F1 removes at most 23% of filler flips (need ≥ 80%); F2 changes 37–42% of starter-only trades (need ≤ 2%) |
| M1: no loss of market agreement on held-out leagues | passes (J 0.302 → 0.183–0.202) |
| M2: the market credits usable depth above filler as the anchor predicts | **fails**, and the comparison is confounded (§7.3) |
| T: Team Context does not already absorb the effect on those surfaces | **not demonstrated, so not met.** T measured team-aware surfaces only; context-free surfaces have no roster to measure (disclosed in §12) |
| every §2 property except homogeneity | passes (B is monotone, order- and swap-consistent, continuous, raw on 1-for-1) |

**R-B0: Team Context is sufficient on team-aware surfaces. Holds as frozen.** On production behaviour 85 of 133
filler flips are neutralised and 43 are over-corrected. Investigation A (§5.2) shows that outcome is mostly
produced by a mis-specified forced-drop charge. The durable conclusion is unchanged: no trade-currency adjustment
on team-aware surfaces. They should price filler through a *correct* roster-capacity charge (value over the
receiver's cheapest legal cut), and a currency discount layered on top would double-count it.

**R-C: informational only. Applies.** Neither R-A nor R-B is met, and IDP (138 trades) and pick-only packages (81)
are insufficient for any class-wide change.

**Explicit non-conclusions (as frozen):**
- Agreement with completed trades decided nothing.
- No threshold was chosen to maximise agreement.
- No class-wide recommendation is made for IDP or pick-only packages.
- Nothing activates.

## 9. Comparison of the three approaches

| | A: value curve | B: trade currency | C: informational |
|---|---|---|---|
| Is its premise supported? | **no.** Served history shows no low-band decay; the low end matches ROS usefulness | **no.** The market discounts extras of every class, not filler specifically; Team Context already prices filler where a roster is known | **yes.** The market discount is real (Phase 3, M2) and many low pieces are freely replaceable (§2) |
| Agreement with completed trades (M1, confirmation J) | 0.127–0.141 | 0.183–0.202 | 0.302 (unchanged numbers) |
| Removes inappropriate filler flips (F1) | 20–28% | 14–23% | 0% (it discloses instead) |
| Protects genuine starters (F2) | no (31–40% re-levelled) | no (36–42% re-levelled) | yes |
| Mathematical properties | monotone, order, swap, continuous; **fails** 1-for-1-raw and homogeneity | all except homogeneity | n/a |
| Double counting with Team Context | yes | yes on team-aware surfaces | none |
| Scope of change | every ranking and trade | every trade surface | copy only, separately reviewed |
| Decision changes, context-free (§4) | 827–852 of 2,000 calculator levels; Trade Finder top-10 overlap .14–.56 | 622–657 levels; overlap .34–.78 | none |

## 10. The public Fair/Not Fair calculator

The public Brisket Trade Advisor (open PR #1861; design record `docs/owner/BRISKET_TRADE_ADVISOR_DESIGN_2026-10-19.md`, on that
PR's branch `claude/advisor-public-backend`, not yet on this branch)
evaluates 2-team trades through the shared `analyze_service` with **Team Context on**. It maps 3–4-team trades through
the fairness band (`public_category_from_net_band`). Consequences:

1. **The 2-team path inherits the forced-drop release charge.** On a roster at the cap, filler sweeteners are mostly
   neutralised, which is good. Any over-charge found in §5, however, reaches public categories: a fair trade can read
   *UNFAVORABLE*. Investigation A finds exactly that over-charge (§5). Follow-up 1 should be resolved, or its effect on public categories measured, before the public 2-team advisor launches. Once it is fixed, more filler sweeteners will *legitimately* move 2-team verdicts, which makes the disclosure more useful there.
2. **The 3–4-team path is context-free.** It is built but switched off today (`multi_team_unsupported`). Once it is
   activated, no roster charge applies, so §4's filler flips will apply unmitigated. The
   multi-team market evidence was excluded from the box run (§7.1), so it gives no 3–4-team calibration.
3. **No methodology or threshold change is recommended or authorized.** The public implementation stays protected.
   Threshold research may continue independently.
4. **Disclosure (R-C) on a public surface must not reveal proprietary numbers.** That means:
   - no point values, gaps, anchors or replacement levels;
   - categorical wording only, for example *"Part of this side is low-value depth that managers rarely pay for in
     trades"*;
   - a trigger computed server-side from the §3 classification.

   Wording, placement and the trigger need separate owner review before any UI work.

## 11. Recommendation and follow-ups

**Recommendation (R-C):**
- Keep `geom_q078_v1` (q = 0.78), the canonical values and the fairness bands unchanged.
- Add **no** canonical low-end adjustment and **no** blanket trade-currency discount.
- Offer an **informational disclosure**, with these properties:
  - it is classification-based and league-aware;
  - it fires only when part of a side is below its position's replacement level;
  - it shows no numbers publicly.

  Its design and UI need separate review and authorization.
- Do not use the shadow rule "fire when B would change the verdict". It fires on 19% of depth cases and 13% of
  starter cases (`shadow_replay.json`, `S3_fillerFlipStudy.C_informationalDisclosure`).

**Follow-up investigations** (separate owner decisions; none is authorized to change production here):

| # | investigation | owner area | priority | evidence |
|---|---|---|---|---|
| 1 | Roster-capacity release-charge review | `src/trade/roster_capacity.py` / `src/draft/displacement.py` | **high**: reaches the public 2-team advisor | §5; `forced_drop_diagnostic.json` |
| 2 | IDP replacement and league-scoring review | scoring-aware IDP / value pipeline; the waiver-anchor rule belongs to the displacement owner | medium | §6; `idp_anomaly.json` |
| 3 | Prospective re-run of the same pinned box command once at least 2,000 unequal-count trades are dated after 2026-10-20 | this program | low | §7.1 |
| 4 | Pick-type composition of the market's extra-piece credit (§7.3), if pick package pricing is ever revisited | pick valuation | low | §7.3 |

## 12. Uncertainties and protocol deviations

**Protocol deviations** (each disclosed; none changes a rule outcome):
1. **M3 clustered CIs were not computed** by the frozen box script. The deviation cannot change the R-A outcome,
   because the point estimates lie on the opposite side of the condition (§7.4).
2. **The §3 classification leaves offense "usable depth" nearly empty** (starter line below anchor at WR and TE).
   - M2's usable-vs-filler comparison is therefore mostly picks vs players.
   - This is a property of the frozen rule and was not repaired after seeing results.
   - The F-study (§4) used the board's rostered classification and is not affected.
3. **M1 has clustered CIs for the population bins but not per asset class**; `byAssetClass` reports means only.
4. **The preregistered "rookie-pick-involved" class was reported as `pick_only` plus a `byRookiePick` split.**
5. **M3 was split by asset group (offense / IDP / pick), not by the §3 class.** `missingAtHorizon` lumps true
   drop-offs together with unobservable horizons; the script uses an exact-date lookup (`low_value_asset_box.py`
   `m3`). Drop-offs are therefore not reported separately as frozen.
6. **R-B's T condition was not demonstrable on context-free surfaces** (no roster), and it is read as *not met*
   (§8).
7. **The live-league query** that confirmed today's settings equal the fallback (§7.1) was run in this session;
   no artifact of it is stored in the repo.
8. **Waiver anchors differ between lanes on the same board** (lineup lane DL 1,839 / LB 1,895 / QB 1,648; S1
   1,918 / 2,149 / 1,923). That reflects the roster snapshot each lane used, and it shows how sensitive the anchor
   rule is (§6).

**Uncertainties:**
- **Lineup utility (U):** six weeks of data; the free-agent comparison uses hindsight.
- **Value dynamics (D):** a sensitivity replay. M3 is served history, but it mixes in methodology changes (§7.4).
- **The filler-flip study (F):** one board, and context-free surfaces only.
- **Team Context:** its lineup half (component B) could not be measured locally.
- **Thin samples:** IDP has 138 graded trades; pick-only packages have 81; filler and usable extras in M4 have about
  100 each.
- **Coverage gaps:**
  - multi-team trades were excluded;
  - there is no prospective population yet;
  - trade-time boards were not re-examined for the pick-type mapping in §7.3.

**Independent review** (a fresh reviewer, 2026-10-20). It checked about 120 numbers against the evidence, the
frozen protocol and the cited code. Verdict: **ACCEPT WITH FIXES**: the recommendation follows from the evidence.
All fixes were applied: R-B tally, F1/F2 ranges, R-A condition D, M3 wording, protocol deviations 3–8 and the IDP
details.

**UNRESOLVED:**
- owner decision on the R-C recommendation and on whether to commission the disclosure design;
- the two follow-up investigations (§11 #1–#2) are owner decisions;
- prospective re-run (§11 #3).
