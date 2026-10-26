# IDP accuracy, Lane H: recommendations, owner decisions and a shadow trade comparison (2026-10-26)

**Status: RESEARCH, NOT FOR PROMOTION.** This page ranks the evidence the other lanes produced; it changes no served
value, rank, flag, weight, scoring rule, package model, fairness band, route or public output, and it authorizes
nothing. The only code it adds is a read-only research script and its tests (`scripts/idp_accuracy/trade_shadow_comparison.py`,
`tests/idp_accuracy/test_trade_shadow_comparison.py`); nothing under `src/` imports it.

**Authority:** `docs/owner/IDP_VALUATION_ACCURACY_DIRECTIVE_2026-10-25.md` section 3 (the ten questions), section 12
(shadow trade comparison), section 13 (safety rules) and section 14 (Deliverable H). Index of every lane: `README.md`.

Agent-OS-Receipt: cb64f74cf4d2763aa16d55ba0d6350f585a2a42f

**Evidence labels used below.** `VERIFIED-by-lane`: a lane measured it, with the stated n and interval, on pinned inputs, and
this page found no conflict with another lane. `CONTESTED`: lanes point in different directions, or one lane's result is
bracketed by another's caveat. `INCONCLUSIVE`: a lane measured it, but the interval that would settle it includes zero (or is wider
than the gap it would explain), so the evidence neither supports nor contradicts the stated direction. `UNAVAILABLE`: no lane could
test it, and the page says why. A label is not a verdict on the
question's truth; it says how much weight the evidence can bear. Every result is in-sample or retrospective on 2026
regular-season weeks 1-6 unless stated; **none of it is the long forward dynasty-horizon validation the fair-value
preregistration requires, and none of it speaks about dynasty value directly.**

## Bottom line

**No change to any served IDP value is warranted by this evidence.** The lanes do not show that the canonical board prices
defenders wrongly at the dynasty horizon in either direction, and no candidate demonstrated an improvement on its
preregistered test: candidate A (BDVM fundamentals, proxy tier) was significantly worse than the market on both axes; B (the
league-fair-value shadow) could not be evaluated and is structurally unable to correct an IDP-versus-offense level (it only
reorders inside each scope); C was indistinguishable from the market; and D's one cleared cross-position test (+0.050,
95% CI +0.018 to +0.083, Holm p 0.010) was blocked by its own regression guards and disappears when its best-ball volatility term is
removed. What the work did establish is narrower and mostly about evidence quality: the host-native scorer is exact
(3,710 of 3,710 player-weeks) but the nflverse path that feeds BDVM had four defects, three repaired in #1938 (which changes
BDVM in-season values and so needs owner approval); the shared-market anchor that sets the IDP level is not independently
justified for this league (NOT_JUSTIFIED, level unresolved), every one of the 397 priced IDP rows is low confidence and
three IDP voters are stale or withheld; replacement is fragile (four of seven served anchors are set by an injured or inactive
player, and the best free agents realize about half their history out of sample); best ball does raise the value of spread for
IDP slot classes (11.9% against 7.0% of ppg) but it follows slot economy and is not predictable per player ahead of time; and
the cut ladder's name tie-break is a measured defect on all 12 rosters (a tied first cut everywhere, and on 9 of 12 the name-chosen cut
costs replayed best-ball points while every tied set holds a legal cut that costs none). The two items that clear a mechanical bar are
deterministic correctness repairs (the scorer fixes and, for the tie-break, a name-independent key), not valuation
changes. The tie-break's measured lineup cost is a separate matter: a name-independent key is deterministic but still arbitrary and
does not remove that cost, only a lineup-aware choice would, and that is not built, so the cost stays an owner decision. Five owner
decisions are listed in section 3.

## 1. The ten questions (directive section 3)

| # | question | answer | label |
|---|---|---|---|
| 1 | Defenders over- or undervalued against offense? | Level unresolved. Near-term lineup evidence leans toward undervaluation by the market; the candidates that fix the level overshoot; nothing speaks to the dynasty horizon. **No value change warranted.** | CONTESTED |
| 2 | Are elite defenders separated enough from mediocre ones? | The board compresses the top of the IDP population (an estimator property on a thin panel). Points separation is persistent for DL and not detectable for LB or DB at six games. **No change warranted; a 17-game re-run is the test.** | CONTESTED |
| 3 | Are DL, LB and DB valued appropriately against one another? | The board's order LB, DL, DB points the same way as the replacement point estimates (DB wire flattest, LB steepest), but the intervals that would separate the positions include zero. **No change warranted either way.** | INCONCLUSIVE |
| 4 | Are interior DL and cornerbacks treated appropriately under our scoring? | The scoring does not achieve its stated aims as classes (TFL does not favour DT as a class; PD deepens the CB pool rather than creating elite CBs). Whether the market prices DT or CB appropriately could not be tested. | VERIFIED-by-lane (scoring effect); UNAVAILABLE (pricing) |
| 5 | Does consensus undervalue certain defensive archetypes? | No lane could test archetype pricing. Utility differences exist but follow slot economy. | UNAVAILABLE |
| 6 | Does best ball raise the value of volatile, big-play defenders? | Yes for slot classes, modestly; no usable per-player signal ahead of time; not a flat uplift. | VERIFIED-by-lane (class level); CONTESTED (use) |
| 7 | Are replacement levels correct? | Not shown wrong, but fragile and unvalidated; no alternative is validated as a served anchor. | VERIFIED-by-lane (diagnostics); UNAVAILABLE (the correct level) |
| 8 | Is the league-fair-value challenger more accurate than the market? | No evidence it is; it cannot fix a level by construction; its accuracy within a scope is not measurable without a real projection tier. | VERIFIED-by-lane (structure); UNAVAILABLE (accuracy) |
| 9 | How should a proven difference influence private team-specific trade decisions? | No difference is proven, so no influence is warranted. If one is, it belongs in the private roster-aware lane through whole-roster team impact, never the public calculator. | UNAVAILABLE |
| 10 | Can an improvement be shown without circular market assumptions? | The test can be run that way (D uses no market input; the outcome is realized lineup contribution), and it showed no improvement. | VERIFIED-by-lane |

### Q1. Defenders over- or undervalued relative to offense?

* **The level is a market fact, not a utility fact.** At equal depth the canonical board prices the k-th defender at about half
  the k-th offense player: 0.63 at k=1, 0.48 at k=10, 0.50 at k=25, 0.48 at k=50, 0.55 at k=108 (the last league-wide IDP starter);
  the top-108 defenders have a median value of 2,545 against 4,734 for the top-132 offense players (0.54). Priced rows: 397 IDP, 491
  offense. (Lane C section 1.)
* **Defenders start in best ball as often as offense players at every price band, and score about what RB and WR starters score.**
  The mean points of the player filling each slot (2026 weeks 1-6, realized): DL 17.75, LB 17.62, DB 18.28 against RB 18.39,
  WR 19.12. This is start share and starter points, not marginal value, and Lane C labels it "suggestive, not conclusive".
  (Lane C section 2.)
* **Near-term pairwise test.** Among 104,238 offense-versus-defender pairs with different realized lineup contribution, the
  market board (rebuilt method on the 2026-09-09 point-in-time inputs) ordered 36,428 wrongly; it had overrated the defender in only
  **15% (95% CI 11% to 19%)** of those, and put an offensive player above a defender who contributed more in the other 85%.
  Candidates C and D overshoot the other way (58%, CI 51% to 65%, and 52%, CI 45% to 59%, of their wrong pairs overrate the
  defender); A is closer to balance (39%) but still undervalues defenders. Label `retrospective_point_in_time`, six weeks,
  n = 651 veterans, rookies excluded. (Lane G section 5.)
* **What cuts against reading that as "undervalued".** The injury asymmetry favours the market (injury status at the cutoff cannot be
  reconstructed point-in-time, so the market knew what the candidates did not); the champion is a rebuild with freshness weighting
  unavailable; the target is six weeks of production, which a projection-built candidate is favoured on by construction; and the
  candidates share one projection prior, so their agreement is one body of evidence. (Lane G sections 10 and 11.)
* **What the replacement evidence adds.** The wire is close to the starter line at DB (median production starter minus best viable
  free agent: DB 1.0 ppg, DL 2.6, LB 4.4, WR 7.6, TE 7.0, RB 11.4), so points above replacement are smaller for defenders than
  their points per game suggest, and the observed free-agent levels are themselves inflated by selection. (Lane B section 3.)

**Answer:** CONTESTED. The near-term evidence leans toward the market undervaluing defenders relative to realized lineup
contribution, by an amount bracketed between "the market is mostly right" and "the candidates overshoot"; Lane C's verdict on the
anchor is that the level is **unresolved, not wrong**. Nothing here is a dynasty statement. No value change.

### Q2. Are elite defenders separated enough from mediocre ones?

* **On the board.** The top defender is the 34th player overall (Carson Schwesinger, 6,287), against 24th on IDP Trade Calculator's
  own board and 18th on Draft Sharks'. At k=10 the canonical defender is worth 0.80 of IDPTC's k-th defender, while offense at k=10
  is worth 1.13. The mechanism is identity disagreement: IDPTC's number one is rank 167 on Draft Sharks and Draft Sharks' number
  one is rank 54 on IDPTC, so blending two or three disagreeing votes pulls each player toward the middle. Offense has 12 to 14
  agreeing voters per row. Spearman between IDPTC's order and the canonical order is 0.91 (n 377), and for Draft Sharks 0.86
  (n 295). This is an estimator property on a thin panel, not a defect in a source. (Lane C section 3.)
* **In points.** Elite (ranks 1-12) minus average starter (25-36), points per game, at the actual card: DL in-sample 7.2,
  selection-corrected 5.5 (95% CI 2.8 to 7.9), held out within 2026 4.7 (1.3 to 7.7), forward 2024 to 2025 4.8 (0.2 to 7.7), forward
  2025 to 2026 3.2 (-1.1 to 8.4). LB: 5.4, 2.7 (-0.1 to 5.1), -0.6 (-3.0 to 1.6), 2.9 (0.5 to 5.9), 2.6 (-0.2 to 7.4). DB: 4.1, 0.8
  (-1.8 to 3.0), -0.2 (-2.1 to 1.2), 2.2 (0.2 to 4.0), 1.8 (-0.7 to 5.4). RB persists about 2.5 times as much as DL (held out 11.9
  against 4.7). Selection noise inflates the in-sample elite tier by 80% for DB, 65% for CB, 50% for LB and 24% for DL. (Lane E
  baseline table.)
* **Elite identification.** Ranking the ex-ante top 12 in each position, no candidate differs from the market (Delta3 not significant
  for A, C or D; Holm p 0.060 for A is the smallest). (Lane G section 4.)

**Answer:** CONTESTED. The board's top-of-IDP compression is real and mechanical; whether it is an error depends on elite
separation that persists for DL but cannot be detected for LB or DB at six games. Owner decision 5 (a 17-game re-run) is the way to
settle it. No value change.

### Q3. Are DL, LB and DB valued appropriately relative to one another?

* **Board order.** First appearance of each family: LB rank 34 (6,287), DL 63 (5,071), DB 106 (3,989, Nick Emmanwori). Top 100
  overall holds 9 LB, 3 DL and 0 DB. (Lane C section 1.)
* **Replacement.** Median production starter minus best viable free agent: DB 1.0 ppg, DL 2.6, LB 4.4. The third-best viable free
  agent produces 0.82 of the median starter at DB, 0.74 at DL, 0.64 at LB. The pool-based gaps are the stable ones; the single-player
  intervals are wider than the gaps at DL, LB and DB (for example DB 1.0, CI -12.5 to 12.6). (Lane B sections 0 and 3.)
* **Scarcity gap against the starters.** Free-agent gap over starter level: LB 0.36, DL 0.35, DB 0.23; LB minus DL +0.01 (-0.29 to
  0.15), LB minus DB +0.13 (-0.20 to 0.30), neither distinguishable from zero. On the rank-based gap LB beats DB by +0.08 (0.04 to
  0.20), which survives Bonferroni, and is not different from DL (-0.06, -0.15 to 0.00). (Lane E Q3.)

**Answer:** INCONCLUSIVE (relabelled from "VERIFIED-by-lane, low power"; every number above is unchanged). The point estimates run in
the direction of the board's order of LB, then DL, then DB (DB wire flattest, LB steepest), but the intervals that would have to
separate the positions include zero: on the free-agent gap, LB minus DL is +0.01 (-0.29 to 0.15) and LB minus DB is +0.13 (-0.20 to
0.30), and Lane B's single-player intervals are wider than the gaps they would explain (for example DB 1.0, CI -12.5 to 12.6). The one
interval that excludes zero, LB over DB on the rank-based gap (+0.08, 0.04 to 0.20), says nothing about where DL sits (LB minus DL
-0.06, -0.15 to 0.00). So the evidence neither supports nor contradicts the board's order; it was never shown to be wrong, and it was
not shown to be right. No change is warranted either way.

### Q4. Interior DL and cornerbacks under our scoring

* **TFL and interior DL.** Taking TFL from x0 to x2, the elite 12 gain about the same on both: DT +6.5 ppg (CI 4.5 to 8.4), EDGE +5.3
  (3.1 to 7.3), a difference of +1.2 (-1.5 to 4.1) that cannot be told from zero. The average starter does not: 25th-36th DT +2.3
  (1.4 to 3.1) against 25th-36th EDGE +5.8 (4.8 to 6.8), a difference of **-3.5 (-4.8 to -2.2) that survives Bonferroni**. The cause
  is counts: an average-starter DT averages 0.29 TFL a game against 0.69 for an average EDGE, because an edge rusher's sacks carry
  their own TFL on the same play (9.28 points on the actual card). The standalone, non-sack TFL goes to linebackers first (elite ILB
  0.58 a game beyond their sacks), then DT (0.41), then EDGE (0.23). (Lane E Q1.)
* **PD and cornerbacks.** PD x0 to x2 lifts every CB tier by 7.6 to 9.7 ppg (elite +9.7, average starter +8.9, first bench +7.6). The
  elite tier's extra over the bench is +2.1 (-2.0 to 5.5), indistinguishable from zero, and elite CBs do not persist: held-out
  separation -0.5 (-2.1 to 1.0), forward -0.6 (-3.1 to 1.3) and +2.2 (0.2 to 6.3). PD raises the DB share of IDP starter points from
  28.9% (x0) to 33.3% (actual) to 37.6% (x2). The top-heavy beneficiary is the safety, exploratory. (Lane E Q2.)
* **Pricing.** Lane G could not test interior DL versus edge or CB versus S: Sleeper positions do not distinguish them and no
  point-in-time depth-chart source is pinned. Lane D's labels come from two public sources that disagree on 15% of players (132 of
  883), and the DE/DT line is the weakest, so the EDGE-versus-DT contrast is the one most exposed to label provenance.

**Answer:** the scoring effect is VERIFIED-by-lane (TFL does not favour DT as a class; PD makes more cornerbacks viable and
deepens the pool); whether the market prices DT or CB appropriately is UNAVAILABLE. Production scoring stays unchanged by directive;
no card change is recommended.

### Q5. Does consensus undervalue certain defensive archetypes?

UNAVAILABLE. Lane G names it: "interior DL versus edge, and CB versus S" cannot be evaluated against a market. Lane D finds
differences in best-ball utility between archetypes (DL 13.9% and DB 12.8% of ppg against LB 7.9%; CB minus ILB +7.0 pp, CI 3.1 to 10.3;
DL minus LB +6.1 pp, CI 3.1 to 8.9, both Bonferroni-significant) but those are utility, not a comparison with price, and EDGE minus DT
(+1.5 pp, CI -2.8 to 5.6) and CB minus S (+3.4 pp, CI -0.7 to 7.0) are not distinguishable. No archetype-level mispricing is shown.

### Q6. Does best ball raise the value of volatile, big-play defenders?

* **Existence and sign.** The volatility premium J (lineup points the player's spread adds to the best-ball lineup, never negative)
  is 1.23 lineup ppg for IDP (CI 1.11 to 1.34), 11.9% of ppg (10.7% to 13.0%), against 0.75 (0.66 to 0.82), 7.0% (6.2% to 7.9%)
  for offense: IDP earns **4.8 percentage points more** (CI 3.4 to 6.4; Bonferroni 2.9 to 6.8), n = 264 IDP and 244 offense players.
  The sign holds under all six weekly-distribution models; independent Poisson events shrink it to +0.4 pp, and the data reject that
  model (observed weekly score variance is about 1.9 times the Poisson variance). (Lane D headline.)
* **It follows the slot economy, not the label.** The league starts the best 3 of about 10 at each IDP position every week, so spread
  pays when the mean sits near the cut line. The "explosive half" of an archetype does not reliably earn more (no split survives the
  correction for nine comparisons).
* **Not predictable per player.** Half-season reliability of the coefficient of variation is 0.37 for EDGE and 0.39 for DT against
  0.63 to 0.73 for ILB, CB and S; year over year 0.28 to 0.53. Lane E measures the same thing from the other side: in-sample, each +0.1
  of weekly CV adds 0.14 points a week of best-ball premium (slope 1.41, CI 0.62 to 2.05); measuring CV on one half and the premium on
  the other, the slope is 0.11 (-0.22 to 0.46). (Lane D reliability; Lane E Q4.)
* **It carries candidate D's cross-position gain.** Without its volatility term D's offense-versus-IDP edge is -0.005 (Lane G
  section 6, variant S4).

**Answer:** VERIFIED-by-lane for existence and sign at the slot-class level (size is model-dependent, 0.4 to 7.1 pp across
distribution models); CONTESTED as a basis for valuing an individual player; **no flat uplift** (the directive forbids one and Lane D
finds none).

### Q7. Are replacement levels correct?

* **Fragility of the served anchors.** Served anchors today: QB 1,379, RB 1,652, WR 1,754, TE 2,082, DL 1,874, LB 2,160, DB 1,917;
  **four of seven are set by an injured or inactive player** (DL, RB, WR, TE). Lane B's published DB headline (an anchor set by an Out
  player at 2,156) does not reproduce on the pinned inputs: no unrostered DB is valued above 1,917 now. B's own code reproduces
  exactly (63 of 63 anchors, 7 of 7 LI-5 value levels), so the difference is the wire, not the method. (Lane B sections 8 and 9.)
* **Selection inflates every free-agent level.** Ranked on weeks before *w* and scored on week *w*, the top five viable free agents
  scored **51% of their history ppg for IDP (95% CI 36% to 65%, 42 player-weeks, 23 players)**: DB 40% (22% to 60%), DL 48% (29% to
  71%), LB 69% (39% to 102%, 14 player-weeks), offense 37% (20% to 52%). The raw best-viable DB level of 13.7 ppg is one player
  (6 games, interval 1.7 to 25.7). (Lane B section 4.)
* **The board prices a minority of the productive wire.** 135 of 157 viable DBs, 135 of 167 DLs and 64 of 81 LBs are unpriced; value
  unit D3 and D4 levels therefore rest on three priced players or are undefined and are not usable as served anchors. (Lane B section 0.)
* **Consumer impact.** Forced-drop counts do not change under any anchor (0.83 per team at net +1); the anchor changes the cost and
  which tied cut is chosen. FAAB is barely affected. Perfect Draft's count of rookies with positive surplus changes with the anchor.
  (Lane B section 8.)
* **The forced-drop tie-break is a separate, measured defect** (X2 below): all 12 rosters have a tied first cut, and the name-chosen cut
  costs replayed lineup points on 9 of 12.

**Answer:** VERIFIED-by-lane for the diagnostics; the **correct level** is UNAVAILABLE. No definition is validated as a served
anchor. Sequencing against Investigation A and the LI-5 consolidation stays an owner matter.

### Q8. Is the league-fair-value challenger more accurate than the market?

* **Not evaluable.** With a proxy-only candidate A, `league_fair_value_v1_shadow` excluded all 1,067 rows and returned the market
  value exactly (`degenerate_market_exact`). (Lane G section 0.)
* **Structurally unable to fix an overall level.** It quantile-matches offense and IDP separately, so it permutes (or log-interpolates
  between) values inside one scope: each scope's multiset of values is preserved at full strength and its geometric mean at any
  uniform strength. Shown with a constructed example and on two real boards under three utility orders: the offense-over-IDP top-12
  ratio stays 1.938 on the cutoff board, and hypothetical level errors built in (IDP priced 25% too high or 20% too low) came out of
  the bare quantile match unchanged (ratio 1.550 and 2.422). (Lane F section 3.)
* **What an A-real tier would need.** A box BDVM snapshot with an immutable creation stamp before the cutoff, which does not exist in
  this repository.

**Answer:** VERIFIED-by-lane that it cannot correct a level; accuracy within a scope is UNAVAILABLE. It stays shadow-only.

### Q9. How should a proven difference influence private team-specific trade decisions?

Nothing is proven, so nothing is warranted. The architecture question is separate and is answered by section 4: Market Price, League
Utility and Team Transaction Impact are different quantities with different evidence, they diverge on market-fair trades, and
only the third is roster-aware. The public neutral calculator keeps the authorized market-fairness methodology; any use of the
other two belongs in the private roster-aware lane, through the whole-roster owners that already exist
(`roster_capacity.evaluate_final_roster_utility`, which the private simulator already attaches as `rosterUtility`).
UNAVAILABLE as a recommendation.

### Q10. An improvement without circular market assumptions?

The test was run that way and showed none. Candidate D has no market input by construction (never mapped onto 1-9999, never fitted to a
price, never anchored to IDPTC or Draft Sharks); the outcome is realized marginal best-ball contribution on the cutoff rosters,
host-scored; the preregistration was frozen before any outcome was read and the blind stage was committed and pushed first.

| candidate | within-position (Delta1, equal-weight Spearman) | offense-versus-IDP (Delta2, pair concordance) | verdict |
|---|---|---|---|
| A (BDVM fundamentals, proxy tier) | -0.266 (-0.326, -0.202), Holm p 0.006 | -0.041 (-0.069, -0.015), Holm p 0.010 | champion better |
| B (fair-value shadow) | not evaluable | not evaluable | degenerate: returns the market value |
| C (`mu` minus starter threshold) | -0.049 (-0.100, +0.003), Holm p 0.216 | +0.029 (-0.005, +0.064), Holm p 0.216 | no detectable difference |
| D (marginal best-ball contribution) | -0.024 (-0.084, +0.037), Holm p 0.464 | **+0.050 (+0.018, +0.083), Holm p 0.010** | blocked by regression guards |

Cohort 651 veterans (QB 54, RB 94, WR 133, TE 58, DL 118, LB 90, DB 104), 2026 weeks 1-6, bootstrap B = 2000, minimum meaningful
effects +0.05 and +0.02 fixed beforehand. D's cross-axis result cleared its test and was blocked because the within-position guard
(Delta1 at least -0.02) failed at -0.024, the per-position point floor (at least -0.10) failed at DB (-0.116), and the sign does not
survive the volatility ablation. The detectable Delta1 at 80% power is about 0.0725, above the +0.05 that matters, so the nulls at
C and D within positions are partly a statement about power. (Lane G sections 0, 2, 3, 6 and 11.)

**Answer:** VERIFIED-by-lane. Not an out-of-sample or forward result: label `retrospective_point_in_time`, the outcomes were public and
earlier lanes had looked at them before several candidates were defined, and A, C and D descend from one projection prior.

## 2. Candidate changes: ADVANCE, KEEP EXPERIMENTAL, REJECT

**Rule used.** ADVANCE means "enough evidence for an owner decision". It requires that the change met its own preregistered or
mechanical acceptance criterion: a Lane G verdict of `advance`, or, for a deterministic correctness repair, a reconciliation or a
strict pinned invariant. ADVANCE covers only what that criterion covers: where a repair is advisable for its determinism but does not
deliver a measured benefit, the table says so and that benefit stays an owner decision (X2). No predictive valuation candidate meets that
bar. KEEP EXPERIMENTAL means useful and unproven; REJECT means the
evidence argues against the change as proposed. **Nothing below is a promotion.**

| id | candidate change | class | basis in one line |
|---|---|---|---|
| X1 | Repair the nflverse IDP scorer defects 01, 02 and 03 (#1938) | **ADVANCE** (owner approval: changes BDVM values) | reconciliation 91.5% to 96.2% of joined rostered player-weeks, 0 newly wrong in the wide sample |
| X2 | Stop breaking the cut ladder's equal-cost ties by display name | **ADVANCE as a correctness repair only** (option a, a name-independent key: deterministic, not a fix for the lineup cost); **the measured lineup cost is an OWNER DECISION** that needs option (c), a lineup-aware choice, which is not built | all 12 rosters have a tied first cut (median 28 tied); the name-chosen cut costs replayed lineup points on 9 of 12 while every tied set holds a legal cut that costs none |
| X3 | Candidate A (BDVM fundamentals) as a market substitute or blend input | **REJECT** | significantly worse than the market on both axes |
| X4 | `league_fair_value_v1_shadow` as the fix for an IDP-versus-offense level | **REJECT** | structurally cannot move a scope's level |
| X5 | A universal IDP multiplier, level shift or re-anchor of the shared market | **REJECT** | no independent level evidence; barred by directive section 13 |
| X6 | Change the scoring card to rebalance positions | **REJECT** | no lane recommends it; trade-offs only |
| X7 | Candidate C (replacement-adjusted lineup utility) | **KEEP EXPERIMENTAL** | indistinguishable within and across positions; overshoots on defenders |
| X8 | Candidate D (marginal best-ball contribution) | **KEEP EXPERIMENTAL** | cleared the cross test, blocked by guards, carried by its volatility term |
| X9 | Replacement definitions D1 to D6 as served anchors | **KEEP EXPERIMENTAL** | fragile, selection-inflated, most IDP wire unpriced |
| X10 | Best-ball volatility as a per-player value input or flat IDP uplift | **REJECT** | not predictable ahead of time; follows slot economy |
| X11 | Check or refit the best-ball model's fallback spread constants | **KEEP EXPERIMENTAL** | fallback CVs sit below measured spread for DL, DB, QB; production state unknown |
| X12 | Replace the stale IDP Show combined voter with its maintained IDP-only board | **KEEP EXPERIMENTAL** (owner decision) | operational staleness evidence; no accuracy backtest |
| X13 | Present Market Price, League Utility and Team Transaction Impact side by side in the private roster-aware lane | **KEEP EXPERIMENTAL** | six-example shadow comparison; owners already exist |
| X14 | Re-run the elite-separation and scoring tests on a full 17-game 2026 season | **KEEP EXPERIMENTAL** (owner decision) | six games cannot separate LB or CB elites |

Shared fields for every row: **evidence dates** are the 2026 regular-season weeks 1-6 (Sleeper `last_scored_leg` 6; week 7 in progress
and excluded), the served board of 2026-10-25 12:03Z (`exports/archive/dynasty_export_20261025_120337.zip`, sha256 `50fb251a...c8dc8f6`, rebuilt
board hash `4e6ba1f5...7d8712`) and, for the retrospective tests, the point-in-time board of 2026-09-09 21:15Z. Scoring fingerprint
`sf1:9e51824690d091f9`. Every affected-player list below is public NFL names only.

### X1. Repair the nflverse IDP scorer defects 01, 02 and 03 (ADVANCE)

| field | value |
|---|---|
| effect | nflverse-path reconciliation against Sleeper's awarded points: 2,832 of 3,095 joined rostered player-weeks within 0.01 (91.5%) becomes 2,976 (96.2%); wide sample (6,387 player-weeks, host-native scorer as truth) 5,416 becomes 5,865 within 0.01 (84.8% to 91.8%), **0 newly wrong**. By position after: DL 402 of 422, LB 462 of 510, DB 492 of 533 |
| n | 3,095 rostered and 6,387 wide player-weeks; 92 player-weeks were scorer defects before (80 + 7 + 2 + 3) |
| uncertainty | an exact reconciliation, not an estimate; residuals enumerated: 111 stat-provider disagreements (was 171), 8 scorer-attributed (5 deliberate non-IDP assists, 3 defect 04), 53 identity misses |
| affected | **BDVM in-season posterior only.** 373 of 1,642 players with samples change; LB 115, S 86, CB 45, EDGE 12, DT 4 (mostly down about 0.2 to 0.25 ppg: special-teams tackles were double-paid) and WR 42, TE 21, RB 13, QB 7 (up 0.13 to 0.21: defensive events now paid) and K 9 (down 0.24); 117 of the changed players are ranked on the served board. Value-level movement is UNAVAILABLE here (the projection snapshot is box-local) |
| trade calculations | `/api/data`, `rankDerivedValue`, Market Price and the public calculator do not read this path and do not change. BDVM Fund gap, signal alerts and `/api/bdvm/trade-eval` do |
| risks | moves BDVM numbers on a live feature (flag `bdvm_engine` is ON); the special-teams tackle de-duplication is the part most worth review (it moves IDP-listed players, and withholding it restores the 01/02/03-only behaviour); tackle assists stay IDP-only because special-teams assists cannot be separated; defect 04 is a position-vocabulary choice, not a scorer defect |
| files | `src/nfl_data/realized_points.py`, `src/bdvm/clay_projections.py`, `tests/nfl_data/*`, `tests/bdvm/test_scoring.py`, `tests/idp_accuracy/test_scoring_events.py` (PR #1938, stacked on #1931) |
| rollback | revert #1938; the in-season blend recomputes from rows and the actuals cache turns over within one UTC day |
| owner approval | **required** (scoring-path changes move BDVM values) |

### X2. Stop breaking the cut ladder's equal-cost ties by display name (ADVANCE as a correctness repair only; the lineup cost is an owner decision)

| field | value |
|---|---|
| classification | **Two separate claims.** (1) *Determinism, ADVANCE:* the choice among equal-cost players should not depend on display name; option (a), a name-independent key (player id), repairs that, is advisable as a correctness repair, and is the invariant pinned as `LANE-E-DEFECT-I9-TIEBREAK`. (2) *Lineup cost, OWNER DECISION:* option (a) does **not** fix the measured cost below (9 of 12 rosters, up to 12.19 lineup points a week), because a player id is as arbitrary as a name with respect to lineup points. Only option (c), a choice that also reads best-ball lineup points, would, and it is not built; whether to build it is the owner's call. Option (b) (`forced_drop_cheapest_legal`) selects on market value, which is not lineup points either |
| effect | with the cheapest-legal flag OFF, `build_cut_ladder` sorts by `(effective cut cost, asset.name.lower())`, and cost is 0 for everyone at or below waiver level. On the pinned board **all 12 rosters (all at the 58-man limit) have a tied first cut**, tied set size median 28 (min 12, max 43) of 58; the chosen player is the alphabetically first lineup-legal tied player on all 12 (on the twelfth the guard skipped a kicker the lineup needs). The chosen player's release cost exceeds the cheapest tied player's on 11 of 12 rosters, **mean 1,126 value units, max 1,649**. **In replayed best-ball points the chosen cut costs lineup points on 9 of 12 rosters, mean 2.48 and max 12.19 points a week, while the tied set holds a slot-legal cut that costs nothing on 12 of 12** (the ladder guards the count of fillable slots, not points; the 12.19 is a DB averaging 19.5 ppg whose market value, 1,809, sits below the DB waiver level 1,917). Unpriced players are 14.7% of the tied set on average |
| n | 12 rosters, one hypothetical incoming player each, nobody leaving; weeks 1-6 replay for the lineup cost |
| uncertainty | an exact census of a deterministic rule; the release cost is the owner's own charge (base value times scarcity multiplier 1.0, with the waiver level as the ceiling for an unpriced player); the lineup cost is a six-week hindsight replay with no interval |
| affected | which tied player a real roster releases on a forced drop; in the shadow examples the first cut was Aaron Donald (unpriced DL, release cost the DL waiver level 1,874, lineup cost 0.00 in both examples where he appears), Alim McNeill (DL, 1,310, 3.07 points a week) and Akayleb Evans (unpriced DB, 1.37 points a week) |
| trade calculations | forced-drop cost in the Finder's Team Context factor and the War Room net; not Market Price and not the public calculator. `capacity.rungOrderWasTied` is True only when two or more FORCED drops tie each other, so a single forced drop never reports a tie even when dozens of candidates tied |
| risks | **a name-independent key (player id) is deterministic but still arbitrary**: it changes which tied player is cut without making the choice sensitive to market value or lineup points, and the census says that sensitivity is where the cost is. It also changes Perfect Draft's ladder (it shares `build_cut_ladder` and passes no `order_key`). The cheapest-legal flag path (default OFF) already ties on player id and selects on release cost (market value), which is not lineup points either; sequence, do not stack |
| files | `src/draft/displacement.py::build_cut_ladder`; pinned as strict xfail `LANE-E-DEFECT-I9-TIEBREAK` in `tests/trade/test_multi_team_properties.py` (PR #1937); census in `scripts/idp_accuracy/trade_shadow_comparison.py` |
| rollback | revert the key change; no persisted state |
| owner approval | **required** for both parts (documented in #1937 as an owner decision): approving option (a) as a determinism repair, and deciding whether option (c), the only route to the measured lineup saving, is built |

### X3. Candidate A as a market substitute or blend input (REJECT)

| field | value |
|---|---|
| effect | Delta1 -0.266 (-0.326, -0.202), Delta2 -0.041 (-0.069, -0.015), both Holm-significant against A; worst at QB (-0.426), DL (-0.304), DB (-0.298), LB (-0.264) |
| n | 651 veterans, 2026 weeks 1-6, cutoff 2026-09-09 |
| uncertainty | bootstrap B = 2000; age assumption does not explain it (+/-1 year moves Delta1 only between -0.287 and -0.244); **it is a statement about the proxy tier** (history-only, shrunk, no box snapshot), not about BDVM with real projection sources |
| affected | all seven positions; deficit largest in the champion's 301-800 band (-0.346) and smallest among players 29 and older (-0.041) |
| trade calculations | none (A is not wired into any trade path) |
| risks | rejecting A as a market substitute does not retire BDVM, which stays a separately named fundamental-value concept |
| files | `src/bdvm/*` unchanged |
| rollback | n/a |
| owner approval | not needed to reject; adopting A would need the full evidence package |

### X4. `league_fair_value_v1_shadow` as the level fix (REJECT)

| field | value |
|---|---|
| effect | 0 of 1,067 rows moved with a proxy-only A; for any utility order the scope's value multiset (full strength) or log-sum (any uniform strength) is unchanged, so the IDP-to-offense level cannot move |
| n | cutoff board (411 offense and 304 IDP rows) and Lane A's pinned board; three utility orders and two configurations |
| uncertainty | exact for the construction; the numeric illustration depends on the board and orders chosen |
| affected | IDP and offense scopes (reorders inside each) |
| trade calculations | none (shadow only) |
| risks | reading its within-scope reordering as a level correction; its gates and owner preconditions (`projectionUtilityInDynastyRuling`, `canonicalIdentityArchitecture`) remain unrecorded |
| files | `src/league_valuation/challenger.py`, `config/league_valuation/fair_value_v1.json` unchanged |
| rollback | n/a |
| owner approval | not needed to reject; question 3 in section 3 concerns the holdout |

### X5. A universal IDP multiplier, level shift or re-anchor (REJECT)

| field | value |
|---|---|
| effect | none proposed by any lane. Lane C's perturbations are measurements, not corrections: IDPTC's IDP values x0.80 / x1.25 move the median defender -9.1% / +10.8% (log-elasticity 0.43 / 0.46); Draft Sharks' x0.80 / x1.25 move it -2.8% / +5.3%; removing either bridge leaves the median level within +/-0.2% |
| n | 108 defenders and 132 offense players compared by name |
| uncertainty | single-factor local elasticities, not estimates of how wrong either market is |
| affected | n/a |
| trade calculations | n/a |
| risks | directive section 13 bars arbitrary 0.8x or 1.2x multipliers; candidates that do set a level (C, D) overshoot the near-term evidence in the other direction |
| files | `config/bridges/bridges_v1.json`, `src/bridges/*` unchanged |
| rollback | n/a |
| owner approval | not applicable |

### X6. Change the scoring card to rebalance positions (REJECT)

| field | value |
|---|---|
| effect | none proposed. Lane E: "Nothing here optimises a card toward equal position totals, and no card change is recommended." Measured trade-offs: a big-play weighting lowers LB and DB rank predictability (split-half 0.85 to 0.75 and 0.76 to 0.68), a tackle emphasis raises it and compresses elite separation (DL 4.4, LB 3.7, DB 2.7 ppg), doubling both enhancements raises every group's gap without making LB or DB held-out separation positive |
| n | 57 rescored cards over 2026 weeks 1-6; pools of 248 DL, 174 LB, 272 DB with at least 4 played games |
| uncertainty | 95% basic bootstrap intervals, Bonferroni within contrast families; elite tiers are selection-inflated (DB 80%, LB 50%, DL 24%) |
| affected | DL, LB, DB and the DT, EDGE, ILB, CB, S archetypes |
| trade calculations | none; production scoring is unchanged by directive |
| risks | optimizing a card to equalize totals trades predictability for separation; the 2025 card is nearly the 2026 card in effect, the heavier-interception 2024 card widens every separation |
| files | none (`config/idp_accuracy/scoring_sensitivity_cards.json` holds the reference cards, #1943) |
| rollback | n/a |
| owner approval | any card change is a league decision outside this program |

### X7. Candidate C: replacement-adjusted lineup utility (KEEP EXPERIMENTAL)

| field | value |
|---|---|
| effect | within positions -0.049 (-0.100, +0.003), Holm p 0.216; offense-versus-IDP +0.029 (-0.005, +0.064), Holm p 0.216; both "no detectable difference". Its within-position order is the projection prior's, so its distinctive content is the cross-position level, where it overrates the defender in 58% (51% to 65%) of its wrong offense-versus-defender pairs |
| n | 651 veterans (QB 54, RB 94, WR 133, TE 58, DL 118, LB 90, DB 104), cutoff 2026-09-09, outcome weeks 1-6 |
| uncertainty | paired position-stratified bootstrap B = 2000, Holm across 6 hypotheses; 80% power needs a Delta1 of about 0.0725, above the +0.05 that matters |
| affected | worst at DB (-0.152) and WR (-0.110); better than the market at TE (+0.100) and DL (+0.014), neither significant |
| trade calculations | none (shadow); it supplies the shadow League Utility column C |
| risks | shares the projection prior with A and D, so agreement is one body of evidence; the qualified free-agent pool is empty at the cutoff, so D4 falls back to D1; the injury asymmetry favours the market |
| files | `scripts/idp_accuracy/backtest.py`, `src/league_valuation/replacement_shadow.py` (#1940, #1942) |
| rollback | n/a (not imported by production) |
| owner approval | required for any serving; next test is a new preregistration on outcomes not yet observed |

### X8. Candidate D: marginal best-ball contribution (KEEP EXPERIMENTAL)

| field | value |
|---|---|
| effect | offense-versus-IDP +0.050 (+0.018, +0.083), Holm p 0.010, above the +0.02 minimum, **blocked** by (i) the within-position guard (Delta1 -0.024 against a -0.02 floor), (ii) the per-position floor (DB -0.116 against -0.10) and (iii) the sign not surviving D(sigma = 0), which gives -0.005. Within positions -0.024 (-0.084, +0.037), Holm p 0.464 |
| n | 651 veterans; first 150 trades per category for the trade examples |
| uncertainty | bootstrap B = 2000; S8 cluster bootstrap by NFL team: Delta2 (+0.019, +0.078); trade-example Wilson 95% intervals. Predicted elite separation is flatter than realized (1.2 to 1.9 against 1.8 to 2.8) |
| affected | gains in the 151-800 market bands and among unrostered veterans; loses at DB, the position with the lowest 2025 half-season persistence (Spearman 0.11); the largest percentile-rank errors are listed in Lane G section 7 (for example Malik Nabers, Geno Stone, Mike Jackson, Devin White, Jonathon Cooper) |
| trade calculations | none (shadow). In Lane G's examples (universe: trades the market calls fair) it named the winning side in 0.750 (0.68, 0.81) of offense-for-IDP 1-for-1 swaps against the market's 0.507 (0.43, 0.59), and 0.640 (0.56, 0.71) of 2-for-1 trades forcing a cut against 0.493 (0.41, 0.57); the target is the quantity D predicts and six weeks cannot grade a dynasty trade, so these expose failure modes only |
| risks | its cross-position edge is its volatility term; six-week CV reliability is low for pass rushers (0.37 EDGE, 0.39 DT); independent draws across players and weeks; roster cap ignored when adding |
| files | `src/league_valuation/cross_position.py` (#1942) |
| rollback | n/a (not imported by production) |
| owner approval | required for any serving; next test is a new preregistration whose window starts after its commit, plus the long forward validation the fair-value preregistration requires |

### X9. Replacement definitions D1 to D6 as served anchors (KEEP EXPERIMENTAL)

| field | value |
|---|---|
| effect | no definition is validated. Whole-roster before/after versus the naive sum of per-player deltas differs on 7 to 12 of 12 teams per recipe (for example a 1-for-2 LB expansion +1.1 points a week, interval 0.5 to 1.8); the planner allocation realized **24%** of the points it predicted when decided on weeks before the scored week |
| n | 12 rosters of 58; 5 recipes by 3 shapes; free-agent selection test 42 IDP player-weeks over 23 players |
| uncertainty | conditional intervals exclude selection; the same player sets the D2 level again in only 20% (DL), 25% (DB) and 27% (LB) of resamples |
| affected | DB (flattest wire), LB (steepest), DL; four of seven served anchors are set by an injured or inactive player (DL, RB, WR, TE) |
| trade calculations | if served: forced-drop cost, the Finder's Team Context factor (`-(cost/give) x 50`), Perfect Draft rookie surplus and FAAB `V_repl`; forced-drop counts unchanged (0.83 per team at net +1) |
| risks | value-unit D3 and D4 rest on three priced players or are undefined; 135 of 157 viable DBs, 135 of 167 DLs and 64 of 81 LBs are unpriced; health is one snapshot |
| files | `src/league_valuation/replacement_shadow.py`, `config/league_valuation/replacement_shadow_v1.json`, `scripts/idp_accuracy/replacement_report.py` (#1940) |
| rollback | n/a (not imported by production) |
| owner approval | required, sequenced against Investigation A and the LI-5 consolidation |

### X10. Best-ball volatility as a per-player input or flat uplift (REJECT)

| field | value |
|---|---|
| effect | Lane D: the premium depends on slot economy and on distance to the cut line; "there is no flat IDP, DL or big-play uplift in this evidence". Per player it is mostly noise ahead of time: slope 0.11 (-0.22 to 0.46) when CV is measured on one half and the premium on the other (Lane E), CV split-half reliability 0.37 EDGE and 0.39 DT |
| n | 529 evaluated players (264 IDP, 244 offense, 21 K); 2025 reliability pools of 25 to 139 per archetype |
| uncertainty | nested bootstrap, 40 outer by 20 inner; Bonferroni within contrast families |
| affected | all IDP slot classes; the premium is highest where mean sits near the cut line |
| trade calculations | none proposed |
| risks | a flat multiplier is barred by directive section 13 |
| files | none; the right vehicle is X8 (weekly distributions through the exact solver, Lane D's engine is the parity-tested reference) |
| rollback | n/a |
| owner approval | not needed to reject |

### X11. Check the best-ball model's fallback spread constants (KEEP EXPERIMENTAL)

| field | value |
|---|---|
| effect | Lane D: this checkout has no fitted artifact, so `PointsModel` uses documented fallback CVs that sit below the measured spread for DL (0.55 against 0.73), DB (0.50 against 0.65) and QB (0.32 against 0.57); if production runs on the fallback, its best-ball utility understates IDP and QB volatility value |
| n | 58 DL, 93 DB, 33 QB (plus 65 LB, 63 RB, 98 WR, 50 TE, 21 K), 2026 weeks 1-6, with a 2025 pooled cross-check |
| uncertainty | observed-to-assumed ratios 1.34 (DL), 1.29 (DB), 1.78 (QB); whether the box has a fitted artifact is UNAVAILABLE here |
| affected | DL, DB, QB; RB and WR sit close to their assumed values |
| trade calculations | the private best-ball utility (`rosterUtility`) if it runs on the fallback |
| risks | a finding about the fallback, not about production |
| files | `src/league_intel/sim_calibration.py::PointsModel` and its fitted artifact on the box |
| rollback | n/a (a check, not a change) |
| owner approval | an owner-gated operational check, not a research result |

### X12. IDP Show IDP-only board in place of the stale combined board (KEEP EXPERIMENTAL, owner decision)

| field | value |
|---|---|
| effect | the combined board (Datawrapper U8I37 v4, last modified 2026-08-19) is withheld at 66 days stale (freshness 0) on all 301 IDP rows it covers; the maintained IDP-only board was republished 2026-10-08 (#1939). Lane C names source restoration "the cheapest accuracy lever". No accuracy backtest of the swap exists |
| n | 301 IDP rows covered by the stale board; 397 priced IDP rows, all low confidence |
| uncertainty | operational evidence only; IDPTC (14 days since a content change, freshness 46%) and FantasyPros (51 days, 24%) are also past their budgets, DLF IDP is `testing`, Signals IDP is `data_issue` |
| affected | IDP rows with an IDP Show vote; the shared-market anchor sets about 90% of each IDP value, so restoring a vote can move identities, not just levels (removing Draft Sharks raises the top-200 IDP count from 43 to 54) |
| trade calculations | indirectly, through `rankDerivedValue` for IDP assets |
| risks | changes source voting, which is owner-reserved; independence of the IDP Show board from IDPTC (suspected lineage, `idptc-idpshow-dependence`) is unverified |
| files | source registry and voting configuration (not touched) |
| rollback | revert the voter registration |
| owner approval | **required** |

### X13. Three-quantity display in the private roster-aware lane (KEEP EXPERIMENTAL)

| field | value |
|---|---|
| effect | section 4: market-fair trades move lineups by -13.28 to +12.11 points a week; League Utility sums favour the side that receives more players; a package is not the sum of its single moves (up to +1.55 points a week in the examples) |
| n | 6 seeded examples, one per category; 64 market-fair candidates drawn per category |
| uncertainty | a sample, not a population estimate; the replay is hindsight over six weeks with no interval |
| affected | any private roster-aware trade surface; the public neutral calculator must not change |
| trade calculations | would add League Utility and Team Transaction Impact beside Market Price, never blended with it; the private simulator already attaches `rosterUtility` through the same owners |
| risks | League Utility is shadow, uncalibrated and unavailable for about a quarter of priced rostered players; three dates, three evidence bases |
| files | `scripts/idp_accuracy/trade_shadow_comparison.py` (research only); a product surface would reuse `roster_capacity` and `best_ball_utility` |
| rollback | revert this PR |
| owner approval | required before any user-visible surface, and it needs its own authorization in `docs/EXECUTION_PLAN.md` |

### X14. A 17-game re-run (KEEP EXPERIMENTAL, owner decision)

| field | value |
|---|---|
| effect | Lane E lists it as unresolved: whether a full season shows a CB or LB elite separation that six-week windows cannot (held-out LB -0.6, CI -3.0 to 1.6; CB -0.5, CI -2.1 to 1.0). It would also give the best-ball premium a forward test on a season not used here |
| n | 2026 weeks 1-17 or 18, after the regular season |
| uncertainty | the elite tiers are selection-inflated at six games (DB 80%, CB 65%, LB 50%) |
| affected | LB, DB and CB elite tiers; scoring-card trade-offs; the best-ball premium |
| trade calculations | none until a result moves a recommendation |
| risks | the preregistration must be committed before the data is opened, or it is not a forward test |
| files | the committed scripts of Lanes D, E and G (no new code) |
| rollback | n/a |
| owner approval | required to schedule, and to say whether the result may move a recommendation |

## 3. Owner decisions

Each is a decision only the owner can make; none is made here, and none is needed to keep every served value as it is.

1. **BDVM scorer fixes (#1938).** *Do you approve repairing the nflverse IDP scorer defects 01, 02 and 03 in
   `src/nfl_data/realized_points.py`, which changes BDVM's in-season posterior for 373 of 1,642 players with 2026 samples (mostly LB, S and CB
   down about 0.2 to 0.25 points a game as special-teams tackles stop being double-paid, and WR, TE, RB and QB up about 0.13 to 0.21 as defensive
   events are paid) without changing `/api/data` or any `rankDerivedValue`?* Options: approve all three; approve with the special-teams tackle
   de-duplication withheld (restores the 01/02/03-only behaviour); hold. The residual special-teams assist overcount (411 of 1,823 IDP-listed
   player-weeks with special-teams snaps) needs a schema change and is a follow-up either way.
2. **IDP Show board swap.** *Should The IDP Show's maintained IDP-only board (republished 2026-10-08) replace its stale combined board (v4, last
   modified 2026-08-19, withheld at 66 days) as the IDP Show voter, knowing this changes source voting, that no lane backtested the swap, and that
   IDP Trade Calculator and FantasyPros are also past their staleness budgets?* Options: swap; keep withheld; restore by another route.
3. **Is 2026 still a clean holdout for fair-value?** *Now that Lane G has examined 2026 weeks 1-6 (and Lane B's definitions were developed on those
   weeks), does 2026 remain a clean holdout season for `league_fair_value_v1`'s preregistered forward validation?* Lane G disclosed what ran and
   that B was degenerate; it set no frozen field. Options: yes (Lane G was exploratory); no (declare 2026 spent and name a later season); yes for
   weeks 7 and later only. The preregistration's other owner preconditions remain unrecorded.
4. **Cut-ladder name tie-break (from #1937).** *Should `build_cut_ladder`'s equal-cost tie-break stop using `asset.name.lower()`, and if so
   should it become (a) a name-independent key (player id, as the flag-gated cheapest-legal path already ties), (b) `forced_drop_cheapest_legal`
   enabled instead (selects the least market value), or (c) a choice that also looks at best-ball lineup points (not built)?* Every option changes
   which tied player a real roster releases, and (a) and (b) change Perfect Draft's ladder or the trade path respectively. Evidence: all 12 rosters tie
   (median 28 candidates); the name-chosen cut costs replayed lineup points on 9 of 12 (mean 2.48, max 12.19 a week) while each tied set holds a legal
   cut that costs none; the chosen cut is a mean 1,126 value units dearer than the cheapest tied cut. **Two parts, not one:** option (a) is advisable
   as a correctness repair (the choice stops depending on a display name), but it is deterministic and still arbitrary, so it does **not** remove the
   measured lineup cost; only option (c) would, and it is not built. Approving (a) therefore settles determinism and leaves the lineup cost open;
   whether to build (c) is the part that is the owner's decision.
5. **17-game re-run.** *Do you authorize re-running the elite-separation, scoring-sensitivity and best-ball-premium tests on a full 17-game 2026
   season after week 18, preregistered before the data is opened, to settle whether LB or CB elites separate persistently, and should its result be
   allowed to move any recommendation on this page?*

## 4. Shadow trade comparison (directive section 12)

`scripts/idp_accuracy/trade_shadow_comparison.py` prints three **separately named** quantities for each team in each example trade, and never
sums, scales or ranks them against each other:

| quantity | what it answers | source | status |
|---|---|---|---|
| **Market Price** | what independent market evidence says the assets are worth, run through the live package model | pinned board's `rankDerivedValue`; `package_model.adjusted_pair_totals` (ACTIVE `geom_q078_v1`) and `fairness_bands_v2`, called the way the live engines call them, from each team's own perspective | canonical, read-only |
| **League Utility** | what owning the player is expected to contribute under this league's scoring, lineup and best-ball rules | Lane F/G candidates C (projected ppg over the weakest started player) and D (expected league-average marginal best-ball points per week), cutoff 2026-09-09, veterans only | **SHADOW**, uncalibrated, per asset |
| **Team Transaction Impact** | what the trade does to this roster | the whole-roster optimal best-ball lineup before and after, replayed over weeks 1-6 with the exact solver; forced drops from `roster_capacity`; a package versus the sum of its single moves | read-only replay, hindsight |

**Inputs, all pinned.** The 2026-10-25 board is rebuilt from the archive under the repository tree of Lane A's pin (`bdbc83a1f`; the contract
builder reads the CSV, config and dataset-state directories from its own tree, and `main` has moved since), and the rebuilt board hash
`4e6ba1f5...7d8712` equals Lane A's `servedBoardSha256`, as do the archive hash and the scoring fingerprint. Rosters are the public Sleeper
`/rosters` as captured in the archive (2026-10-25 12:01Z), cross-checked against a live fetch (696 of 696 players in both). Weekly points are Sleeper's
own stat lines scored by the host-native scorer, which reproduces Sleeper's awarded points on 3,406 of 3,406 compared rostered player-weeks (max
difference 0.0044); the exact solver fed the host's own points reproduces the host's team totals on the 7 of 72 team-weeks whose players all sit
on today's rosters (Lane A's 72 of 72 covers the rest). All twelve rosters are at the 58-man limit.

**Selection.** One example per category: seeded draws from the category's structural universe, kept when the live fairness band calls them
`fair`, and the smallest `sha256` of the trade key is taken (64 fair candidates per category). The rule reads no replay result, so the examples are a
sample and not a showcase; the output is identical across runs and hash seeds. Shapes are limited to what the live generators would propose
(`construction.topology_is_allowed`).

### 4.1 The six examples

Teams are labelled A and B within each example only; no manager, team or roster identifier is published. The block below is generated by
`python scripts/idp_accuracy/trade_shadow_comparison.py --offline --write-doc` and a test pins it to the evidence file.

<!-- table:shadow -->
**T1 - offense for IDP (both scored by the shadow candidates) (1-for-1)**

Side A gives Elijah Arroyo (TE, 2,199); side B gives Azeez Al-Shaair (LB, 2,050).

| quantity | side A | side B |
|---|---|---|
| Market Price: receive minus send, adjusted (value units, canonical) | -149 | +149 |
| Market Price: fairness band | FAIR | FAIR |
| League Utility (SHADOW): net D, receive minus give, pts/wk | +2.70 | -2.70 |
| Team Transaction Impact: lineup pts/wk before to final (replay wk 1-6) | 389.66 to 392.51 (+2.85) | 409.08 to 407.72 (-1.36) |
| Team Transaction Impact: weeks improved / worsened | 4 / 0 | 0 / 5 |
| Team Transaction Impact: whole package minus sum of single moves | +0.00 | +0.00 |
| Forced drops (capacity owner) | none | none |

Readout: Market Price reads FAIR; League Utility D (naive sum) favours side A; Team Transaction Impact: A gains and B loses.

**T2 - offense for an IDP the shadow candidates cannot score (a rookie) (1-for-1)**

Side A gives Matthew Stafford (QB, 3,628); side B gives Caleb Downs (DB, 3,526).

| quantity | side A | side B |
|---|---|---|
| Market Price: receive minus send, adjusted (value units, canonical) | -102 | +102 |
| Market Price: fairness band | FAIR | FAIR |
| League Utility (SHADOW): net D, receive minus give, pts/wk | n/a | n/a |
| Team Transaction Impact: lineup pts/wk before to final (replay wk 1-6) | 401.42 to 392.32 (-9.11) | 350.48 to 362.04 (+11.56) |
| Team Transaction Impact: weeks improved / worsened | 1 / 4 | 5 / 1 |
| Team Transaction Impact: whole package minus sum of single moves | +0.00 | +0.00 |
| Forced drops (capacity owner) | none | none |

League Utility is UNAVAILABLE for: Caleb Downs (no prior-season production; never scored as 0).

Readout: Market Price reads FAIR; League Utility D is unavailable; Team Transaction Impact: B gains and A loses.

**T3 - two offense players for one IDP (consolidation across the position divide) (2-for-1)**

Side A gives Brian Thomas (WR, 3,387), Ray Davis (RB, 1,646); side B gives Cedric Gray (LB, 4,444).

| quantity | side A | side B |
|---|---|---|
| Market Price: receive minus send, adjusted (value units, canonical) | -227 | +227 |
| Market Price: fairness band | FAIR | FAIR |
| League Utility (SHADOW): net D, receive minus give, pts/wk | -2.05 | +2.05 |
| Team Transaction Impact: lineup pts/wk before to final (replay wk 1-6) | 266.88 to 267.92 (+1.04) | 446.60 to 446.81 (+0.21) |
| Team Transaction Impact: weeks improved / worsened | 4 / 1 | 1 / 0 |
| Team Transaction Impact: whole package minus sum of single moves | +0.00 | +0.00 |
| Forced drops (capacity owner) | none | Aaron Donald (DL, unpriced, rung 1) |

League Utility net is a naive per-asset sum; with unequal player counts it favours the side that receives more players.

Readout: Market Price reads FAIR; League Utility D (naive sum) favours side B; Team Transaction Impact: both rosters gain lineup points.

**T4 - starter upgrade: two same-position players for one better one (2-for-1)**

Side A gives DJ Moore (WR, 3,598), Romeo Doubs (WR, 2,548); side B gives Parker Washington (WR, 5,802).

| quantity | side A | side B |
|---|---|---|
| Market Price: receive minus send, adjusted (value units, canonical) | +217 | -217 |
| Market Price: fairness band | FAIR | FAIR |
| League Utility (SHADOW): net D, receive minus give, pts/wk | -5.30 | +5.30 |
| Team Transaction Impact: lineup pts/wk before to final (replay wk 1-6) | 377.35 to 379.91 (+2.55) | 403.89 to 399.38 (-4.51) |
| Team Transaction Impact: weeks improved / worsened | 2 / 3 | 3 / 2 |
| Team Transaction Impact: whole package minus sum of single moves | +0.37 | +1.55 |
| Forced drops (capacity owner) | none | Alim McNeill (DL, 1,310, rung 1) |

League Utility net is a naive per-asset sum; with unequal player counts it favours the side that receives more players.

Readout: Market Price reads FAIR; League Utility D (naive sum) favours side B; Team Transaction Impact: A gains and B loses.

**T5 - depth package: one star for two mid-value players (1-for-2)**

Side A gives Derrick Henry (RB, 4,641); side B gives Mark Andrews (TE, 3,047), Mac Jones (QB, 2,001).

| quantity | side A | side B |
|---|---|---|
| Market Price: receive minus send, adjusted (value units, canonical) | -33 | +33 |
| Market Price: fairness band | FAIR | FAIR |
| League Utility (SHADOW): net D, receive minus give, pts/wk | -1.21 | +1.21 |
| Team Transaction Impact: lineup pts/wk before to final (replay wk 1-6) | 401.42 to 388.14 (-13.28) | 293.14 to 305.25 (+12.11) |
| Team Transaction Impact: weeks improved / worsened | 0 / 5 | 6 / 0 |
| Team Transaction Impact: whole package minus sum of single moves | +0.13 | +0.30 |
| Forced drops (capacity owner) | Akayleb Evans (DB, unpriced, rung 1) | none |

League Utility net is a naive per-asset sum; with unequal player counts it favours the side that receives more players.

Readout: Market Price reads FAIR; League Utility D (naive sum) favours side B; Team Transaction Impact: B gains and A loses.

**T6 - cut-requiring: two for three, side A starts at the roster limit (2-for-3)**

Side A gives Travis Kelce (TE, 3,473), Nick Emmanwori (DB, 3,989); side B gives Joe Milton (QB, 1,598), Quentin Lake (DB, 1,739), A.J. Brown (WR, 4,564).

| quantity | side A | side B |
|---|---|---|
| Market Price: receive minus send, adjusted (value units, canonical) | +195 | -195 |
| Market Price: fairness band | FAIR | FAIR |
| League Utility (SHADOW): net D, receive minus give, pts/wk | +1.57 | -1.57 |
| Team Transaction Impact: lineup pts/wk before to final (replay wk 1-6) | 446.60 to 443.55 (-3.05) | 350.48 to 354.94 (+4.46) |
| Team Transaction Impact: weeks improved / worsened | 1 / 4 | 3 / 1 |
| Team Transaction Impact: whole package minus sum of single moves | +0.52 | +0.00 |
| Forced drops (capacity owner) | Aaron Donald (DL, unpriced, rung 1) | none |

League Utility net is a naive per-asset sum; with unequal player counts it favours the side that receives more players.

Readout: Market Price reads FAIR; League Utility D (naive sum) favours side A; Team Transaction Impact: B gains and A loses.
<!-- /table:shadow -->

### 4.2 What the six examples show

* **Market-fair does not mean lineup-neutral.** All six trades are inside the FAIR band, yet the replayed lineup moves from -13.28 to +12.11 points
  a week for the same trade's two sides (T5), and in T2 the side giving a QB loses 9.11 while the side receiving the unscorable rookie DB gains 11.56.
  The reason is roster composition (a team without a QB2 loses the most), which no asset-level number can see.
* **League Utility is an asset-level input and must not be read as a package score.** It sums per asset, so with unequal player counts it favours
  whoever receives more bodies: in T4 (two WRs for one better WR) and T6 (two for three) its naive sum favours the side that the roster-aware replay says
  loses lineup points (T4 side B -4.51; T6 side A -3.05). Across the 64 market-fair candidates drawn per category, the share in which D favours side A
  was 0.75 for offense-for-IDP 1-for-1 (equal counts, so no body-count bias), 0.19 and 0.17 where side A receives fewer players (2-for-1) and 0.88 and
  0.75 where it receives more (1-for-2, 2-for-3). That pattern is the bias, not evidence. The equal-count 0.75 is directionally consistent with Lane G's
  level diagnostic (D overrates defenders in 52% of its wrong pairs) and is a seeded sample, not a population estimate.
* **A package is not a sum.** Whole-package minus the sum of single moves is +0.37 and +1.55 points a week in T4, +0.52 in T6, +0.13 and +0.30 in
  T5, and zero to two decimals where the incoming and outgoing players do not compete for a slot (T1, T2, T3 and T6 side B).
* **League Utility is unavailable more often than it looks.** Of priced rostered players the candidates score 82.0% of QB, 79.3% of RB, 76.2% of WR,
  78.7% of TE, 77.4% of DL, 84.4% of LB and 75.8% of DB; of the top 25 by value at each position, 24 QB, 23 RB, 23 WR, 22 TE, 21 DL, 21 LB and 20 DB.
  The rest are rookies and players without a prior season, and T2 shows the display refusing to score one (Caleb Downs) rather than inventing a zero.
* **The forced drop is not always free in lineup terms, and which player is named is the alphabetical tie-break.** Four forced drops appear: an
  unpriced DL (Aaron Donald, in T3 and T6) whose release leaves the replayed lineup unchanged, a priced DL below waiver level (Alim McNeill, 1,310, T4)
  whose release takes a further 3.07 points a week off that side (-1.44 before the cut, -4.51 after) and an unpriced DB (Akayleb Evans, T5) who takes
  1.37 (-11.91 before, -13.28 after). X2 measures the same thing across all 12 rosters.
* **This is the architecture the directive asks for, not a recommendation.** Where the three disagree, the disagreement is the output. The public neutral
  calculator keeps the market-fairness methodology; a private roster-aware surface would show all three through the existing owners.

## 5. Limits and what this page does not establish

* **Everything is six weeks of one season**, in-sample or retrospective. Nothing is a forward test and nothing speaks about dynasty value
  (aging, development, durability, role security, rookies, discounting).
* **The shadow comparison is six sampled examples**, one per category, on three different dates: Market Price is the 2026-10-25 board, League Utility is
  the 2026-09-09 projection prior (veterans only), and the replay is weeks 1-6 on today's rosters (a player acquired mid-season is credited for weeks he
  spent elsewhere, and a missing stat line scores 0.0 as the host does). Lane B measured in-sample lineup gains at about four times what walking forward
  realizes, so the replay deltas are upper-biased and carry no interval.
* **League Utility sums are naive**, are withheld when any asset is unscored, and are biased toward the side that receives more players.
* **Forced drops use the live capacity owner with league scarcity unread** (the live multiplier is inert at 1.0) and whatever the checkout defaults the
  cheapest-legal flag to (OFF).
* **Not re-run here.** Lane A, B, C, D, E and G results are read from their committed documents and evidence, verified against the pinned inputs they
  name; this page re-ran only the shadow comparison, the board rebuild and the tie census.
* **Dependencies.** The League Utility scores are read from Lane G's committed blind-stage vectors, from this checkout once #1942 merges and from
  `git show origin/claude/idp-g-backtest:...` until then; the script reports its source and file hash.

## 6. Reproduce

```bash
python scripts/idp_accuracy/trade_shadow_comparison.py            # network once (public Sleeper GETs, cached), writes the evidence
python scripts/idp_accuracy/trade_shadow_comparison.py --offline  # reuse data/idp_accuracy/cache
python scripts/idp_accuracy/trade_shadow_comparison.py --offline --write-doc   # refresh the generated block above
python -m pytest tests/idp_accuracy/test_trade_shadow_comparison.py -q
bash scripts/format_python_changes.sh
```

Evidence: `docs/valuation/idp_accuracy/evidence/h_trade_shadow_comparison.json` (aggregates and public NFL player names only; a test refuses any manager,
team, owner, roster or league identifier). Rollback for this lane: revert the PR; nothing else was changed.
