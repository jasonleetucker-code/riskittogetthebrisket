# Low-value assets: what they should contribute to a trade (2026-10-20)

**Status: RESEARCH — exploratory evidence complete; confirmatory box run pending (§7).**

**Unchanged in production:** `geom_q078_v1` (q = 0.78), canonical values, source weights, fairness classification,
every recommendation, and the public calculator's methodology. **Directive:**
`docs/owner/LOW_VALUE_ASSET_RESEARCH_2026-10-20.md`. **Frozen protocol:**
`evidence/low_value_assets_2026-10-20/PREREGISTRATION.md`, frozen before any lane reported, plus Amendment 1
(anchor values only).

**Evidence files** (aggregate-only), all in `evidence/low_value_assets_2026-10-20/`:

| file | evidence line |
|---|---|
| `lineup_utility.json` | U — lineup utility |
| `value_dynamics.json` | D — value dynamics |
| `shadow_replay.json` | F — filler flips, and T — Team Context |

Each lane ran in its own isolated worktree. Phase 3's evidence and conclusions are untouched.

Agent-OS-Receipt: cb64f74cf4d2763aa16d55ba0d6350f585a2a42f

## Contents

1. The question, and the three approaches
2. How much low-value players actually contribute
3. Is the canonical scale wrong at the low end? (Approach A)
4. Would a trade-currency adjustment help? (Approach B)
5. Does Team Context already handle it?
6. Comparison of the three approaches
7. Confirmatory box run (pending)
8. Recommendation (preliminary)
9. Uncertainties and outstanding work

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
supported by local evidence. Rule R-A still needs the served-history check (§7, M3).

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

## 5. Does Team Context already handle it? (the double-count test)

Team Context was tested in War Room, i.e. `/api/trade/analyze` with Team Context **on**, under the production
GEOM_78:
- **setup:** every `dynasty_main` roster at the 58-player cap, receiving 1–3 expendable fillers on a near-even
  trade;
- **result:**
  - 133 of 135 sweetened steps flip under asset-only scoring;
  - with Team Context, **85 are neutralised**, **43 are over-corrected** (the verdict turns against the
    receiver), and **5 survive**.

**Read: R-B0 holds.** On team-aware surfaces the existing forced-drop charge already absorbs filler sweeteners, so
any extra trade-currency adjustment there would double-count.

**A separate finding: the charge looks too large.**
- The median release charge is **3,128**, against a median filler credit of 1,982 (1.65×).
- 57 of 270 forced drops are charged at an *assumed waiver value* (about 1,918) for players the board does not
  price at all.
- 26 drops are the filler just acquired.

That points to over-correction in `roster_capacity` release costs for unranked cuts. **It is reported, not
changed:** it belongs to the roster-capacity owner and needs its own decision.

The roster-utility half of Team Context (lineup) needs the box-local projection snapshot, so only the forced-drop
half is measured here.

## 6. Comparison of the three approaches

| | A: value curve | B: trade currency | C: informational |
|---|---|---|---|
| Is the evidence for its premise there? | **no.** Low end ≈ ROS usefulness; it ages *slower* than the vendors. The IDP anomaly is separate | **partly.** Replacement is free at the low end, especially IDP. But Team Context already prices it where a roster is known | yes. The market discount is real (Phase 3), and many low pieces are freely replaceable |
| Removes inappropriate filler flips | 20–28% | 14–22% | 0% (it discloses instead) |
| Protects genuine starters and usable depth | no (F2 31–40% changed) | no (F2 36–39% changed) | yes (numbers unchanged) |
| Mathematical properties | monotone, order, swap, continuous; **fails** 1-for-1-raw and homogeneity | monotone, order, swap, continuous, 1-for-1 raw; **fails** homogeneity | n/a (no number changes) |
| Double counting with Team Context | yes | yes on team-aware surfaces | none |
| Scope of change | every ranking and trade | every trade surface | UI copy only |

## 7. Confirmatory box run (pending)

`scripts/low_value_asset_box.py --box`, owner-run at pinned commit `348313b1c`, read-only guard, aggregates only.
- **M1:** market agreement per treatment, with a league-disjoint split.
- **M2:** whether the market credits usable depth above filler, by position.
- **M3:** **served** value dynamics from the temporal ledger, the decisive input for R-A.
- **M4:** retention of pieces traded as extras.

The prospective population (trades after 2026-10-20) follows in a later run of the same command.

## 8. Recommendation (preliminary, pending §7)

**No change to production numbers.** Keep GEOM_78, canonical values and fairness bands.

| rule | applies? | consequence |
|---|---|---|
| R-B (trade-currency adjustment) | not met | every treatment fails F1 and F2 in every class |
| R-B0 (Team Context sufficient) | holds | no adjustment on team-aware surfaces |
| R-A (value curve) | not supported locally | awaits the M3 served-history check |
| **R-C (informational)** | **the expected outcome** | disclose, don't adjust |

**Approach C, informational, is the expected outcome, and it should be built better than the shadow version.**
- The shadow rule "fire when B would change the verdict" is not specific enough. It fires on 59% of filler cases,
  but also on 19% of depth cases and 13% of starter cases.
- A factual, classification-based disclosure would serve users better. For example: *"N pieces on this side
  (X points) are below their position's replacement level in this league; managers rarely pay for them in real
  trades."*
- It changes no number and is league-aware.
- Its UI wording and placement need owner approval. They are not authorized here.

Two follow-ups for separate owner decisions:
1. **Review of roster-capacity release charges for unranked cuts.** Team Context over-corrects, by 1.65× the
   filler credit at the median.
2. **League-aware IDP value check.** The waiver DBs and LBs are valued above rostered starters.

## 9. Uncertainties and outstanding work

**Uncertainties:**
- The lineup sample is only six weeks long, and its free-agent comparison uses hindsight.
- The dynamics come from a sensitivity replay, not served history (M3 is pending).
- The flip study uses one board and context-free surfaces.
- Team Context's lineup half could not be measured locally.
- IDP evidence is limited (only 18 external leagues start IDP), and the IDP classification is confounded (§4).

**Pending:**
- The box run (M1–M4).
- The prospective re-run.
- An owner decision on the disclosure (C).
- The two follow-ups in §8.

UNRESOLVED: the box run; the prospective re-run; the owner decisions above.
