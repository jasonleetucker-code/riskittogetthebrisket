# IDP accuracy — Deliverable E: scoring sensitivity

**Lane:** E. **Authority:** `docs/owner/IDP_VALUATION_ACCURACY_DIRECTIVE_2026-10-25.md` section 10 (scoring
sensitivity) and section 13 (production safety), nothing wider. **Status:** `RESEARCH_EVIDENCE_NOT_FOR_PROMOTION`.
Production scoring is unchanged. No served value, rank, flag, weight, source, threshold or verdict is read or
written by this lane, and nothing in `src/` imports it.
Agent-OS-Receipt: cb64f74cf4d2763aa16d55ba0d6350f585a2a42f

* **Pre-registration:** commit `9a6a82851` fixed the grid, cards, pools, metrics, bootstrap design and contrast
  families before any result was computed (`config/idp_accuracy/scoring_sensitivity_cards.json`, hashed into the
  evidence). Deviations are listed under "Deviations from the pre-registration".
* **Evidence:** `docs/valuation/idp_accuracy/evidence/scoring_sensitivity.json` (aggregates and NFL player names
  only). **Code:** `scripts/idp_accuracy/scoring_sensitivity.py`. **Tests:**
  `tests/idp_accuracy/test_scoring_sensitivity.py`.
* Every results table on this page is generated from the evidence file by `render_blocks`, and a test fails if the
  page drifts from it. Prose numbers are copied from those tables. Intervals are 95 percent basic bootstrap
  intervals unless a Bonferroni interval is named.

## Answer in brief

The directive asks four questions. The experiment rescored 2026 weeks 1-6 under 57 IDP scoring cards (eleven
directive keys varied one at a time, eight joint cards, the league's own 2025 and 2024 cards, two constructed
cards) and measured what each does to DL, LB and DB and to the DT, EDGE, ILB, CB and S archetypes.

**1. TFL: does it help interior DL or elite edge? Not interior DL as a class. It lifts the few elite disruptors,
no more than it lifts elite edge rushers.** Taking TFL from x0 to x2 (all else actual), the elite 12 gain
about the same on both: DT +6.5 ppg [4.5, 8.4], EDGE +5.3 [3.1, 7.3] (selection-corrected; observed +7.4 and
+7.5), a difference of +1.2 [-1.5, 4.1] that cannot be told from zero (Q1.1). The average starter does not: the
25th-36th DT gains +2.3 [1.4, 3.1] and the 25th-36th EDGE +5.8 [4.8, 6.8], a difference of -3.5 [-4.8, -2.2] that
survives the Bonferroni correction (Q1.2). The cause is counts, not weights. An elite DT averages 0.87 TFL a game
and an elite EDGE 0.89, but an average-starter DT has 0.29 against 0.69 for an average EDGE, because an edge
rusher's sacks carry their own TFLs (a sack play pays sack, TFL and QB hit together, 9.28 points on the actual
card). So more TFL widens elite-versus-average separation inside the DT class by about 4.2 ppg and inside EDGE by
about -0.5. The number of DTs among the 36 best DL moves 13, 15, 15 across x0, actual, x2 (Q1.3 +3.1 [0.0, 7.0],
not significant). The standalone, non-sack TFL goes to linebackers (elite ILB 0.58 a game beyond their sacks), then
DTs (0.41), least to EDGE (0.23). Confidence: medium on the tier gains (they follow from counts), low on any
DT-versus-EDGE ordering of persistence.

**2. PD: does it create elite cornerbacks or a deeper pool? A deeper pool.** PD x0 to x2 lifts every CB tier by
7.6 to 9.7 ppg: elite +9.7 [5.5, 13.1], average starter +8.9 [7.6, 10.3], first bench +7.6 [6.4, 8.9]. The elite
tier's extra over the bench is +2.1 [-2.0, 5.5] (observed +5.0), which cannot be told from zero (Q2.1), and the
change in in-sample elite separation is +0.8 [-2.9, 4.3] (Q2.2). What would make elites valuable is that they
persist, and they do not: the held-out separation changes by -0.8 [-3.8, 1.8] (Q2.3) and the split-half
reliability by -0.03 [-0.10, 0.05] (Q2.4). At the actual card an elite CB's edge over an average starter is -0.5
[-2.1, 1.0] ppg in the held-out half, and -0.6 [-3.1, 1.3] and +2.2 [0.2, 6.3] ppg forward into the next season
(2024 to 2025, 2025 to 2026). There is no stable CB elite for PD to amplify. What PD does move is the DB share of
IDP starter points, 28.9 percent at x0, 33.3 at the actual card, 37.6 at x2, and the DB starter-to-bench gap, 2.5,
3.2, 4.5 ppg. The top-heavier beneficiary is the safety, not the corner (exploratory): elite S gain +7.0 [4.7, 9.2]
against +3.8 [2.8, 4.7] for the S first bench, about twice, where CB gain 9.7 against 7.6. Confidence: high that PD
raises the pool, medium that it does not detectably create persistent elite CBs (intervals are wide and include
modest positive effects).

**3. LB: does scarcity outweigh low explosiveness? Scarcity is real but not larger than DL's; explosiveness is low
and that is the point.** The free-agent gap relative to the starters is 0.36 for LB, 0.35 for DL and 0.23 for DB:
LB minus DL +0.01 [-0.29, 0.15], LB minus DB +0.13 [-0.20, 0.30], neither distinguishable from zero (Q3.1). On
the rank-based gap LB beats DB, +0.08 [0.04, 0.20], and survives Bonferroni (Q3.2b), and is not different from DL,
-0.06 [-0.15, 0.00]. LBs are the stable position: weekly CV 0.51 against 0.67 (DL) and 0.63 (DB), LB minus DL -0.16
[-0.33, -0.07] (Bonferroni-significant, Q3.3a), split-half reliability 0.85 against 0.63 and 0.76. But the elite LB
does not separate persistently (held-out -0.6 [-3.0, 1.6]; forward +2.9 [0.5, 5.9] and +2.6 [-0.2, 7.4]), and best
ball does not reward the LB floor: the 36 LB starters' best-ball marginal is 2.10 points a week against 3.00 in a
season-long ppg lineup (premium -0.91), a bigger give-up than DL (-0.24) or DB (-0.63). LB minus DL in best-ball
marginal is -0.57 [-3.01, 1.17], not significant (Q3.4). Tackle volume is the LB lever: solo and assist x0.5, x1,
x1.5 give LB 34.0, 36.2, 37.7 percent of IDP starter points. Confidence: medium that LB scarcity is about DL's and
above DB's; low on any best-ball premium or discount.

**4. Best ball: does it change volatile versus stable? After the fact yes, ex ante no detectable.** On the realized
weeks, each +0.1 of weekly CV adds 0.14 points a week of best-ball premium over a season-long lineup, holding ppg
and group fixed: slope 1.41 [0.62, 2.05], Bonferroni [0.29, 2.18] (Q4.1). But that is mechanical (a spiky week
that happened gets used). Measuring CV on one half of the weeks and the premium on the other, the slope is 0.11
[-0.22, 0.46] (Q4.2), whose interval lies below the in-sample interval: variance measured beforehand did not
predict the premium. The ranking is changed, mostly in the middle: Spearman between the deterministic and the
best-ball marginal is 0.81 [0.76, 0.86] over the rostered pool and 0.61 [0.47, 0.80] among deterministic starters
(Q4.3). A big-play card has a slope 0.17 [-0.38, 0.75] above a tackle-heavy card, not significant (Q4.4).
Confidence: high for the existence and sign of the in-sample effect, low for its ex ante use.

**What each scoring key does.** Moving one key from x0 to x2 shifts the share of IDP starter points most for PD (DB
+8.7 points), solo tackles (DL -7.2, LB +3.7, DB +3.6), QB hits (DL +6.6, DB -5.2), TFL (DL +4.4, DB -4.8) and sacks
(DL +3.7, DB -3.0); interceptions move DB +2.2 and assists LB +3.7; sack yards, forced fumbles, fumble recoveries
and defensive touchdowns each move no group by more than 1.0 point. QB hits are the largest single DL lever: they
pay 4.0 ppg to an elite DL against 2.8 for sacks. The league's 2025 card is nearly the 2026 card in effect (DL, LB,
DB shares 30.8, 36.6, 32.6 against 30.5, 36.2, 33.3), and the 2024 card, heavier on interceptions, widens every
separation (DL 8.2, LB 6.9, DB 5.8 against 7.2, 5.4, 4.1).

**Trade-offs, not a recommendation.** Nothing here optimises a card toward equal position totals, and no card
change is recommended. The measured trade-offs: a big-play weighting lowers the predictability of LB and DB
rankings (split-half 0.85 to 0.75 and 0.76 to 0.68 under the big-play card) while a tackle emphasis raises it
(0.87 and 0.79 under the tackle-heavy card) and compresses elite separation (DL 4.4, LB 3.7, DB 2.7 ppg); doubling
both enhancements raises every group's rank gap and in-sample separation (DL 6.8 and 9.5, LB 6.0 and 8.1, DB 5.0
and 6.1) without making the LB or DB held-out separation positive; and removing them shrinks DB's share (31.3
percent) while LB's grows (38.5).

**Cross-position, raw fantasy points, not dynasty value.** At the actual card an elite DL delivers 0.47 [0.32,
0.66] of an elite RB's best-ball marginal, 0.53 [0.40, 0.73] of a WR's and 0.84 [0.62, 1.24] of a TE's; an elite LB
0.32, 0.37, 0.58; an elite DB 0.19, 0.22, 0.35 (intervals for LB and DB reach zero). Over the free-agent level the
ppg ratios are DL 0.44, 0.57, 0.81, LB 0.43, 0.56, 0.80, DB 0.28, 0.36, 0.52 against RB, WR, TE. Elite persistence
is thinner for LB and DB than for any offense position: forward separation 2024 to 2025 is DL 4.8, LB 2.9, DB 2.2 ppg
against RB 8.1, WR 5.2, TE 4.5.
This is utility in points over a hindsight-selected free agent, not a price and not a dynasty value; no market,
horizon or 1-9999 conversion is attempted.

**Selection noise is the largest single caveat.** Ranking six-game samples selects on noise. The bootstrap
measures how much of each observed in-sample elite separation is selection: 80 percent for DB, 65 CB, 50 LB, 30 S,
24 DL, 17 DT, 15 EDGE, against 9 percent for RB. That is why every elite-versus-average claim here is
paired with a held-out (within-2026 halves) and a forward (season-over-season) version, and why the headline
levels in the first table are shown both as observed and selection-corrected.

## Method

**Exact rescoring.** Sleeper's scorer is a dot product of stat counts and card rates
(`src.league_intel.scorer.score_stat_line`). Each 2026 player-week is stored once as `fixed` (every key this study
does not vary, scored by the production scorer under the actual card with the varied keys zeroed) plus the counts
of the sixteen IDP keys it does vary; any card's points are `fixed + counts @ rates`. Stacking is therefore a
property of the stat line, reproduced by construction: a sack play carries `idp_sack`, `idp_tkl_loss` and
`idp_qb_hit` and pays all three. The combined `idp_tkl` key is priced 0 on the card, so solo plus assist are never
double-paid. The identity is pinned against the production scorer, against perturbed cards and against Sleeper's
own awarded points:

<!-- table:parity -->
| check | result |
| --- | ---: |
| actual card, linear vs production scorer | 7,037 player-weeks, max abs diff 1.4e-14 |
| 8 sampled perturbed cards, linear vs production scorer | 24,000 comparisons, max abs diff 1.4e-14 |
| actual card vs Sleeper awarded points (rostered) | 3,294 of 3,294 within 0.01, max abs diff 0.0044 |
| sack plays carrying a TFL or QB hit | 251 of 251 match the stacked total, 0 the un-stacked alternative |
<!-- /table:parity -->

**Pools.** Group is `lineup_position` of the Sleeper directory position (a DL/LB hybrid belongs to his listed
position). The pool is every player with at least 4 played games of 6 (3 and 5 are published as stability
variants). A played week is a game the player appeared in; a bye is excluded and a team game without the player is
a DNP, which best ball pays 0.0 and which is never a played week. Archetypes (EDGE, DT, ILB, OLB, CB, S) come from
nflverse fine positions by provenance, never by performance (Lane D's rule, vendored). OLB (26 players) is too
thin for a 25th-36th tier and is reported as undefined, never as a number.

**Tiers and gaps.** Players are ranked by points per played game under the configuration. Elite is ranks 1-12,
average starter 25-36, first bench 37-48, starters 1-36 (3 DL, 3 LB and 3 DB for each of 12 teams). The
rank-based gap is starters minus first bench. The free-agent gap is starters minus the median conditional ppg of
the top five production-qualified free agents (unrostered, healthy by the host's status, at least two appearances
and one in weeks 4-6): a hindsight-selected level that Lane B measured to be about half real out of sample, so
the gap is a lower bound.

**Predictability.** Split-half: all ten balanced 3|3 partitions of the six weeks, Spearman correlation of the two
halves' conditional ppg, Spearman-Brown corrected, averaged. Held-out separation: rank on one half, then take the
other half's mean of the elite minus the average-starter tier, over the ten partitions and both directions
(labelled within-2026, not forward; three-game halves understate a full-window ranking). Forward separation: rank
on the earlier season's rescored ppg (at least 8 games), measure the later one. Year over year: 2024 to 2025 (at
least 8 games each) and 2025 to 2026 weeks 1-6, both seasons rescored under the same configuration. These are
rescored shape references: neither season was paid under these cards.

**Best ball.** Realized weeks 1-6 on the league's 12 current rosters, aggregated only (no team, manager or
per-roster number is published). The exact lineup solver (Lane D's, pinned to `src.ros.lineup`) gives each rostered
player's marginal: the optimal lineup with him minus the lineup with the median-scoring roster among the rank 1-5
qualified free agents for each slot family he can fill. The deterministic counterpart puts every player at his
expected points per counted week every week. The premium is the difference, in points per week.

**Uncertainty.** Scheme W resamples each player's played weeks (deviations inflated by sqrt(n/(n-1)) so a six-game
sample is not under-dispersed) and re-ranks, 500 replicates, paired across configurations. Scheme P resamples
players, 500 replicates. Scheme B resamples the six weeks as blocks and re-runs the whole best-ball procedure, 200
replicates, for the 13 key configurations. Intervals are basic (reverse-percentile), which corrects the upward bias
re-ranking adds to selected tiers; contrasts are paired differences; families carry a Bonferroni interval.

## Deviations from the pre-registration

All additions below were made after the first (smoke) run and are labelled supplementary or exploratory; none
enters a Bonferroni family and none changes a pre-registered contrast.

1. **A bug was found and fixed before the final run.** `half_means` compared week positions 0-5 with week numbers
   1-6, so half-season splits were mis-assigned. It was caught by checking the first held-out numbers against an
   independent recomputation from the raw arrays; a regression test now pins week numbers. No result from the
   buggy version is used or published.
2. **Selection-corrected levels.** The pre-registered basic intervals correct selection bias, but then the observed
   value can sit outside its interval. The bias (replicate mean minus observed) is now stored and a selection-corrected
   estimate is shown beside the observed one.
3. **Held-out and forward measures** (held-out tier levels, forward 2024 to 2025 and 2025 to 2026 separation,
   archetype year-over-year pools) were added because the in-sample elite tiers proved heavily selected.
4. **Q4.3 variant** restricted to deterministic starters, because the pre-registered Spearman over the whole pool
   is dominated by tied zeros on the bench.
5. **Best-ball replacement sensitivity** (free agents ranked 6-10, roster-only counterfactual) and the TFL and PD
   mechanism tables were added to show how much a marginal's level depends on its replacement.
6. The first full run was lost to a Windows process-pool failure at 20 workers; it was re-run with 10 and then
   re-run once more after the code was committed so that `provenance.gitHead` names the commit that contains the
   code. The two full runs agree on all 104,920 shared numeric leaves to within rounding (worst difference
   5e-05). Later commits only add the page-rendering helpers; no analysis code changed after the final run.

## Inputs and provenance

League `dynasty_main` (Sleeper `1312006700437352448`), season 2026, scoring fingerprint `sf1:9e51824690d091f9`
(identical to Lane A's pin), weeks 1-6 of the regular season (week 7 excluded, in progress). 21 starting slots:
QB, 2 RB, 3 WR, 2 TE, 2 FLEX, SUPER_FLEX, K, 3 DL, 3 LB, 3 DB; 12 teams; best ball. Statistics: Sleeper's own weekly
stat lines for 2026 (the host-native path Lane A reconciled 3,710 of 3,710 within 0.01 of awarded points), and 2025
and 2024 weeks 1-18 for the season-over-season rows, all scored with the host-native scorer. Fine positions and byes
from nflverse (`rosters/roster_{2026,2025}.csv`, `schedules/games.csv`). Every body read is hashed in
`provenance.datasets`. The 2025 and 2024 reference cards are the league's own `scoring_settings` fetched from its
`previous_league_id` chain, checked equal to the pre-registered numbers at run time. Players with a 2026 stat line:
2,106; with at least two played games: 1,392; production-qualified free agents: 608; rostered entries: 696.
The one two-way player (a DB/WR whose eligibility spans both lineups) is out of the best-ball scope.

## The actual card

<!-- table:cards -->
| card | solo | assist | tfl | sack | sack_yd | qb_hit | pd | int | ff | fr | def_td |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| actual 2026 card | 1.33 | 0.80 | 4.24 | 2.92 | 0.11 | 2.12 | 5.30 | 5.30 | 4.24 | 3.19 | 6.36 |
| bigplay down | 1.33 | 0.80 | 4.24 | 1.46 | 0.11 | 1.06 | 5.30 | 2.65 | 2.12 | 1.59 | 3.18 |
| bigplay up | 1.33 | 0.80 | 4.24 | 4.38 | 0.11 | 3.18 | 5.30 | 7.95 | 6.36 | 4.79 | 9.54 |
| double enhancements | 1.33 | 0.80 | 8.48 | 2.92 | 0.11 | 2.12 | 10.60 | 5.30 | 4.24 | 3.19 | 6.36 |
| no enhancements | 1.33 | 0.80 | 0.00 | 2.92 | 0.11 | 2.12 | 0.00 | 5.30 | 4.24 | 3.19 | 6.36 |
| playmaking only | 0.00 | 0.00 | 4.24 | 2.92 | 0.11 | 2.12 | 5.30 | 5.30 | 4.24 | 3.19 | 6.36 |
| tackles down | 0.67 | 0.40 | 4.24 | 2.92 | 0.11 | 2.12 | 5.30 | 5.30 | 4.24 | 3.19 | 6.36 |
| tackles only | 1.33 | 0.80 | 0.00 | 0.00 | 0.00 | 0.00 | 0.00 | 0.00 | 0.00 | 0.00 | 0.00 |
| tackles up | 2.00 | 1.20 | 4.24 | 2.92 | 0.11 | 2.12 | 5.30 | 5.30 | 4.24 | 3.19 | 6.36 |
| big play | 0.50 | 0.25 | 2.00 | 6.00 | 0.10 | 3.00 | 4.00 | 9.00 | 7.00 | 5.00 | 9.00 |
| league 2024 actual | 1.50 | 0.75 | 5.00 | 4.00 | 0.10 | 2.00 | 6.00 | 12.00 | 5.00 | 4.00 | 6.00 |
| league 2025 actual | 1.38 | 0.83 | 4.40 | 3.03 | 0.11 | 2.20 | 4.40 | 6.60 | 4.40 | 3.30 | 6.60 |
| tackle heavy balanced | 1.50 | 0.75 | 1.50 | 3.00 | 0.00 | 1.00 | 2.00 | 4.00 | 3.00 | 2.00 | 6.00 |
<!-- /table:cards -->

The 2025 and 2024 rows are the league's real cards (10-team leagues with smaller IDP lineups; only their IDP scoring
block is used). `tackle heavy balanced` and `big play` are constructed by this study and are not any platform's
default. Offense, special teams and every non-IDP key keep their actual 2026 rates in every card. Where the points
come from at the actual card:

<!-- table:components_elite -->
| pool | ppg | tackles | TFL | sacks + yds | QB hit | PD | INT | FF | FR | TD | other |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| DL | 18.3 | 4.1 | 3.9 | 2.8 | 4.0 | 1.9 | 0.2 | 0.7 | 0.4 | 0.1 | 0.2 |
| LB | 19.8 | 8.6 | 3.7 | 1.4 | 1.5 | 2.4 | 1.1 | 0.5 | 0.2 | 0.3 | 0.1 |
| DB | 17.8 | 7.1 | 1.3 | 0.3 | 0.4 | 5.9 | 2.1 | 0.4 | 0.1 | 0.2 | 0.0 |
| DT | 13.7 | 3.6 | 3.7 | 1.9 | 2.3 | 1.5 | 0.0 | 0.5 | 0.2 | 0.1 | 0.1 |
| EDGE | 18.9 | 4.0 | 3.8 | 2.9 | 4.1 | 1.9 | 0.5 | 1.0 | 0.4 | 0.2 | 0.3 |
| ILB | 19.6 | 9.5 | 3.5 | 1.1 | 1.2 | 2.4 | 1.1 | 0.3 | 0.1 | 0.2 | 0.1 |
| CB | 16.0 | 6.1 | 1.4 | 0.2 | 0.2 | 6.3 | 1.2 | 0.4 | 0.1 | 0.1 | 0.0 |
| S | 16.7 | 7.2 | 1.7 | 0.4 | 0.4 | 4.1 | 2.1 | 0.3 | 0.1 | 0.1 | 0.2 |
<!-- /table:components_elite -->

Elite tier (ranks 1-12), points per game by component.

<!-- table:components_avg_starter -->
| pool | ppg | tackles | TFL | sacks + yds | QB hit | PD | INT | FF | FR | TD | other |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| DL | 11.1 | 2.9 | 2.7 | 1.5 | 2.2 | 1.1 | 0.0 | 0.3 | 0.1 | 0.1 | 0.1 |
| LB | 14.4 | 7.9 | 2.1 | 0.6 | 1.0 | 1.6 | 0.3 | 0.5 | 0.2 | 0.1 | 0.0 |
| DB | 13.8 | 6.2 | 1.4 | 0.3 | 0.4 | 3.7 | 0.9 | 0.2 | 0.3 | 0.0 | 0.3 |
| DT | 7.1 | 2.9 | 1.2 | 0.6 | 1.2 | 0.8 | 0.0 | 0.3 | 0.0 | 0.0 | 0.0 |
| EDGE | 10.5 | 2.6 | 2.9 | 1.8 | 2.0 | 0.6 | 0.1 | 0.4 | 0.0 | 0.0 | 0.1 |
| ILB | 13.0 | 8.3 | 1.8 | 0.2 | 0.5 | 1.3 | 0.1 | 0.2 | 0.4 | 0.1 | 0.0 |
| CB | 11.5 | 5.2 | 0.6 | 0.1 | 0.1 | 4.3 | 1.0 | 0.2 | 0.0 | 0.0 | 0.1 |
| S | 10.4 | 5.9 | 0.4 | 0.1 | 0.3 | 2.5 | 0.6 | 0.1 | 0.3 | 0.2 | 0.1 |
<!-- /table:components_avg_starter -->

Average-starter tier (ranks 25-36). Tackles carry 43 percent of an elite LB's ppg and 55 percent of an average
LB's; QB hits and TFL carry more of a DL's than sacks do.

## Baseline results at the actual card

<!-- table:baseline_separation -->
| pool | n | 36 starters ppg | elite 1-12 ppg | avg starter 25-36 ppg | in-sample separation | selection-corrected separation [CI] | held-out separation, 2026 halves [CI] | forward separation 2024 to 2025 [CI] | forward separation 2025 to 2026 [CI] |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| DL | 248 | 14.2 | 18.3 | 11.1 | 7.2 | 5.5 [2.8, 7.9] | 4.7 [1.3, 7.7] | 4.8 [0.2, 7.7] | 3.2 [-1.1, 8.4] |
| LB | 174 | 16.8 | 19.8 | 14.4 | 5.4 | 2.7 [-0.1, 5.1] | -0.6 [-3.0, 1.6] | 2.9 [0.5, 5.9] | 2.6 [-0.2, 7.4] |
| DB | 272 | 15.5 | 17.8 | 13.8 | 4.1 | 0.8 [-1.8, 3.0] | -0.2 [-2.1, 1.2] | 2.2 [0.2, 4.0] | 1.8 [-0.7, 5.4] |
| DT | 127 | 10.0 | 13.7 | 7.1 | 6.6 | 5.5 [3.5, 7.4] | 3.7 [0.7, 5.9] | 4.6 [2.4, 7.5] | 3.5 [-0.4, 7.1] |
| EDGE | 156 | 14.1 | 18.9 | 10.5 | 8.4 | 7.1 [4.5, 9.4] | 4.5 [1.6, 7.9] | 7.0 [3.4, 10.7] | 2.5 [-2.7, 6.8] |
| ILB | 114 | 16.0 | 19.6 | 13.0 | 6.6 | 4.8 [2.1, 7.3] | 1.2 [-1.2, 3.6] | 1.2 [-2.8, 3.6] | 1.6 [-3.8, 4.8] |
| CB | 143 | 13.6 | 16.0 | 11.5 | 4.5 | 1.6 [-1.1, 3.8] | -0.5 [-2.1, 1.0] | -0.6 [-3.1, 1.3] | 2.2 [0.2, 6.3] |
| S | 127 | 13.3 | 16.7 | 10.4 | 6.3 | 4.4 [1.8, 6.5] | 2.5 [0.1, 4.5] | 2.0 [-0.2, 3.7] | 3.3 [0.2, 7.4] |
| QB | 31 | n/a | 27.1 | n/a | n/a | n/a | n/a | n/a | n/a |
| RB | 97 | 16.5 | 24.3 | 10.8 | 13.5 | 12.3 [9.9, 14.4] | 11.9 [7.2, 16.8] | 8.1 [3.6, 11.9] | 8.7 [3.0, 15.0] |
| WR | 154 | 17.7 | 22.6 | 13.2 | 9.4 | 7.8 [5.2, 10.2] | 5.1 [1.6, 8.3] | 5.2 [0.8, 8.3] | 9.2 [4.5, 14.3] |
| TE | 107 | 10.3 | 14.7 | 6.8 | 7.9 | 6.1 [4.0, 8.1] | 4.2 [1.0, 7.3] | 4.5 [1.5, 8.1] | 6.3 [3.2, 10.0] |
<!-- /table:baseline_separation -->

Separations are in ppg. The observed in-sample separation is the elite tier minus the average-starter tier as it
happened; the selection-corrected value subtracts the bootstrap's measured inflation. Held-out and forward
separations are the unbiased predictive versions. DL, and within it DT and EDGE, show a positive elite separation in
every version (the 2025 to 2026 interval includes zero); LB, DB and CB do not in the three-game halves, and CB does
not from 2024 to 2025. RB separates and persists about 2.5 times as much as DL (held-out 11.9 against 4.7); WR and TE
are close to DL in the held-out halves (5.1 and 4.2) and ahead in the forward rows (WR 5.2 and 9.2, TE 4.5 and 6.3
against DL 4.8 and 3.2).

<!-- table:baseline_gaps -->
| pool | rank gap (ppg) | rank gap / starters | free-agent level (ppg) | FA gap / starters | split-half r (SB) [CI] | year-over-year r 2024-25 [CI] | weekly CV (36 starters) | weekly ICC | best-ball marginal, elite tier (pts/wk) [CI] |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| DL | 4.9 | 0.35 | 9.2 | 0.35 | 0.63 [0.55, 0.71] | 0.65 [0.57, 0.76] | 0.67 | 0.27 | 5.7 [3.1, 8.1] |
| LB | 4.8 | 0.28 | 10.8 | 0.36 | 0.85 [0.82, 0.89] | 0.79 [0.73, 0.86] | 0.51 | 0.41 | 4.0 [-1.8, 6.2] |
| DB | 3.2 | 0.21 | 12.0 | 0.23 | 0.76 [0.72, 0.82] | 0.73 [0.67, 0.79] | 0.63 | 0.28 | 2.4 [-1.3, 4.2] |
| DT | 4.0 | 0.40 | n/a | n/a | 0.56 [0.45, 0.71] | 0.60 [0.48, 0.75] | 0.70 | 0.22 | 1.8 [0.4, 4.3] |
| EDGE | 4.8 | 0.34 | n/a | n/a | 0.67 [0.60, 0.77] | 0.65 [0.54, 0.79] | 0.69 | 0.25 | 6.6 [2.0, 9.5] |
| ILB | 5.1 | 0.32 | n/a | n/a | 0.89 [0.87, 0.92] | 0.75 [0.68, 0.88] | 0.44 | 0.50 | 3.1 [-1.0, 5.0] |
| CB | 3.1 | 0.23 | n/a | n/a | 0.69 [0.62, 0.80] | 0.72 [0.65, 0.82] | 0.64 | 0.22 | 1.3 [-1.4, 2.7] |
| S | 4.2 | 0.32 | n/a | n/a | 0.82 [0.78, 0.88] | 0.76 [0.68, 0.86] | 0.54 | 0.36 | 2.3 [1.1, 6.7] |
| QB | n/a | n/a | n/a | n/a | 0.61 [0.45, 0.90] | 0.29 [-0.00, 0.64] | n/a | 0.19 | 10.9 [6.6, 12.5] |
| RB | 9.1 | 0.55 | 3.5 | 0.79 | 0.88 [0.85, 0.94] | 0.83 [0.75, 0.94] | 0.51 | 0.58 | 12.2 [9.3, 13.6] |
| WR | 6.7 | 0.38 | 6.5 | 0.63 | 0.82 [0.78, 0.88] | 0.77 [0.70, 0.86] | 0.54 | 0.42 | 10.7 [7.5, 11.2] |
| TE | 6.3 | 0.61 | 3.4 | 0.67 | 0.81 [0.77, 0.89] | 0.74 [0.64, 0.86] | 0.73 | 0.41 | 6.8 [4.4, 7.2] |
<!-- /table:baseline_gaps -->

The weekly CV is the median of the 36 starters' within-player SD over mean; ICC is the between-player share of
weekly variance. LB and ILB are the least volatile and the most reliable; DT and EDGE the most volatile.

Event-level stability explains why (Spearman correlation per game, by event; split-half and 2024 to 2025):

<!-- table:events -->
| group | measure | solo | assist | TFL | sack | QB hit | PD | INT | FF | FR |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| DL | split-half | 0.50 | 0.49 | 0.34 | 0.44 | 0.62 | 0.40 | 0.29 | 0.07 | 0.03 |
| DL | 2024 to 2025 | 0.54 | 0.42 | 0.56 | 0.53 | 0.71 | 0.35 | -0.08 | 0.13 | -0.05 |
| LB | split-half | 0.89 | 0.91 | 0.64 | 0.50 | 0.63 | 0.28 | -0.05 | 0.19 | 0.06 |
| LB | 2024 to 2025 | 0.79 | 0.79 | 0.66 | 0.70 | 0.75 | 0.55 | 0.29 | 0.35 | 0.17 |
| DB | split-half | 0.78 | 0.78 | 0.30 | 0.14 | 0.36 | 0.55 | 0.19 | 0.17 | -0.12 |
| DB | 2024 to 2025 | 0.70 | 0.68 | 0.48 | 0.27 | 0.39 | 0.68 | 0.33 | 0.05 | 0.05 |
<!-- /table:events -->

Tackles are stable (0.78 to 0.91 split-half for LB and DB), QB hits and PD are moderate (0.28 to 0.63), sacks and TFL
depend on role (DB sacks 0.14, LB TFL 0.64), and interceptions, forced fumbles and fumble recoveries are weak (split-half
correlations from -0.12 to 0.29).

## Responses to every card

Share of IDP starter points, in-sample separation, rank gap and held-out separation for DL, LB and DB under each
configuration (one-at-a-time x0.5 and x1.5 are in the evidence file; paired intervals for every difference from the
actual card are in `deltasVsActual`).

<!-- table:responses -->
| configuration | DL share % | LB share % | DB share % | DL separation | LB separation | DB separation | DL rank gap | LB rank gap | DB rank gap | DL held-out sep | LB held-out sep | DB held-out sep |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| actual 2026 card | 30.5 | 36.2 | 33.3 | 7.2 | 5.4 | 4.1 | 4.9 | 4.8 | 3.2 | 4.7 | -0.6 | -0.2 |
| solo x0 | 35.0 | 33.9 | 31.1 | 6.5 | 4.9 | 3.9 | 4.4 | 3.2 | 2.7 | 3.8 | -0.4 | -0.8 |
| solo x2 | 27.7 | 37.6 | 34.7 | 8.0 | 6.7 | 5.5 | 5.4 | 5.6 | 3.7 | 5.1 | 0.9 | 0.8 |
| assist x0 | 31.7 | 34.1 | 34.2 | 6.8 | 6.2 | 3.9 | 4.8 | 4.1 | 3.2 | 4.2 | -0.5 | -0.2 |
| assist x2 | 29.5 | 37.8 | 32.7 | 7.6 | 5.4 | 4.4 | 5.1 | 4.8 | 3.0 | 5.1 | -0.5 | -0.1 |
| tfl x0 | 28.0 | 35.8 | 36.2 | 6.2 | 4.3 | 4.3 | 3.8 | 3.8 | 2.8 | 4.9 | 0.4 | -0.2 |
| tfl x2 | 32.4 | 36.3 | 31.4 | 8.5 | 7.0 | 4.7 | 6.3 | 5.2 | 3.6 | 4.2 | -1.2 | -0.3 |
| sack x0 | 28.5 | 36.6 | 34.9 | 6.3 | 4.9 | 4.1 | 4.2 | 4.3 | 3.1 | 4.8 | -0.6 | -0.0 |
| sack x2 | 32.2 | 35.9 | 31.9 | 8.3 | 6.3 | 4.1 | 5.5 | 4.9 | 3.3 | 4.7 | -0.6 | -0.4 |
| sack_yd x0 | 30.0 | 36.3 | 33.6 | 6.9 | 5.2 | 4.1 | 4.8 | 4.7 | 3.1 | 4.7 | -0.3 | 0.0 |
| sack_yd x2 | 31.0 | 36.0 | 33.0 | 7.5 | 5.5 | 4.1 | 5.1 | 4.8 | 3.3 | 4.6 | -0.7 | -0.2 |
| qb_hit x0 | 26.9 | 37.0 | 36.1 | 5.7 | 5.1 | 4.0 | 4.0 | 4.3 | 3.1 | 3.6 | -0.6 | -0.4 |
| qb_hit x2 | 33.5 | 35.5 | 30.9 | 9.0 | 6.3 | 4.3 | 6.0 | 5.0 | 3.3 | 5.5 | -0.3 | -0.0 |
| pd x0 | 32.9 | 38.2 | 28.9 | 6.5 | 5.1 | 3.9 | 4.4 | 3.8 | 2.5 | 3.3 | -0.3 | 1.1 |
| pd x2 | 28.4 | 33.9 | 37.6 | 8.3 | 6.1 | 6.0 | 5.5 | 5.6 | 4.5 | 6.1 | -1.9 | -0.1 |
| int x0 | 31.4 | 36.3 | 32.3 | 7.1 | 4.9 | 3.8 | 5.0 | 4.5 | 2.9 | 4.7 | 0.1 | -0.1 |
| int x2 | 29.6 | 35.9 | 34.5 | 7.3 | 6.0 | 5.3 | 4.8 | 5.1 | 3.4 | 4.8 | -0.1 | 0.2 |
| ff x0 | 30.3 | 36.0 | 33.7 | 6.9 | 5.6 | 4.0 | 4.6 | 4.4 | 3.2 | 4.4 | 0.1 | -0.4 |
| ff x2 | 30.7 | 36.3 | 33.0 | 7.7 | 5.6 | 4.3 | 5.3 | 5.1 | 3.2 | 4.8 | -0.6 | -0.0 |
| fr x0 | 30.3 | 36.2 | 33.4 | 7.0 | 5.4 | 4.1 | 4.8 | 4.9 | 3.3 | 4.5 | -0.7 | -0.1 |
| fr x2 | 30.6 | 36.2 | 33.2 | 7.5 | 5.4 | 4.0 | 5.0 | 4.6 | 3.2 | 4.8 | -0.7 | -0.0 |
| def_td x0 | 30.5 | 36.1 | 33.4 | 7.2 | 5.2 | 3.8 | 4.9 | 4.7 | 3.1 | 4.7 | -0.3 | -0.1 |
| def_td x2 | 30.4 | 36.3 | 33.3 | 7.2 | 5.6 | 4.3 | 5.0 | 4.9 | 3.2 | 4.5 | -0.5 | -0.3 |
| no enhancements | 30.2 | 38.5 | 31.3 | 5.3 | 3.9 | 3.3 | 3.0 | 3.0 | 2.0 | 3.0 | 0.4 | 1.0 |
| double enhancements | 30.3 | 34.4 | 35.3 | 9.5 | 8.1 | 6.1 | 6.8 | 6.0 | 5.0 | 6.4 | -2.3 | -0.0 |
| tackles up | 28.6 | 37.7 | 33.7 | 7.8 | 6.0 | 4.9 | 5.3 | 5.2 | 3.3 | 5.3 | 0.2 | 0.2 |
| tackles down | 33.2 | 34.0 | 32.7 | 6.7 | 5.5 | 3.9 | 4.7 | 3.6 | 2.8 | 4.1 | -0.5 | -0.4 |
| bigplay up | 32.5 | 35.7 | 31.8 | 9.1 | 6.8 | 4.8 | 5.9 | 5.4 | 3.5 | 5.3 | -0.4 | 0.4 |
| bigplay down | 28.0 | 36.8 | 35.2 | 5.6 | 4.9 | 3.7 | 3.9 | 4.0 | 2.8 | 3.8 | 0.5 | -0.2 |
| tackles only | 19.0 | 44.3 | 36.7 | 1.3 | 2.4 | 1.5 | 0.8 | 2.1 | 1.1 | 0.8 | 1.0 | 0.6 |
| playmaking only | 36.7 | 31.7 | 31.6 | 6.1 | 5.0 | 3.8 | 4.3 | 3.0 | 2.4 | 3.9 | 0.3 | -0.7 |
| league 2025 actual | 30.8 | 36.6 | 32.6 | 7.4 | 5.5 | 4.1 | 4.9 | 4.8 | 3.2 | 4.5 | -0.2 | 0.2 |
| league 2024 actual | 29.7 | 35.7 | 34.6 | 8.2 | 6.9 | 5.8 | 5.4 | 5.6 | 3.8 | 5.4 | 0.1 | 0.2 |
| tackle heavy balanced | 27.3 | 39.0 | 33.7 | 4.4 | 3.7 | 2.7 | 2.9 | 3.0 | 2.0 | 2.6 | 0.4 | 0.7 |
| big play | 36.6 | 33.4 | 30.0 | 8.1 | 6.5 | 4.0 | 5.0 | 4.0 | 2.8 | 4.7 | 1.0 | -0.4 |
<!-- /table:responses -->

## Q1 — TFL

Where TFL points come from at the actual card:

<!-- table:tfl_profile -->
| pool | tier | TFL / game | sacks / game | TFL beyond sacks / game | TFL points / game | TFL share of ppg % |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| DT | elite 1-12 | 0.87 | 0.52 | 0.41 | 3.7 | 27 |
| DT | avg starter 25-36 | 0.29 | 0.17 | 0.15 | 1.2 | 17 |
| EDGE | elite 1-12 | 0.89 | 0.79 | 0.23 | 3.8 | 20 |
| EDGE | avg starter 25-36 | 0.69 | 0.48 | 0.24 | 2.9 | 28 |
| DL | elite 1-12 | 0.92 | 0.76 | 0.27 | 3.9 | 21 |
| DL | avg starter 25-36 | 0.65 | 0.42 | 0.28 | 2.7 | 25 |
| ILB | elite 1-12 | 0.83 | 0.29 | 0.58 | 3.5 | 18 |
| ILB | avg starter 25-36 | 0.42 | 0.05 | 0.37 | 1.8 | 14 |
| LB | elite 1-12 | 0.88 | 0.40 | 0.53 | 3.7 | 19 |
| LB | avg starter 25-36 | 0.50 | 0.16 | 0.38 | 2.1 | 15 |
<!-- /table:tfl_profile -->

Responses (ppg and counts) at TFL x0, actual, x2:

<!-- table:q1_table -->
| TFL rate | DT elite ppg | EDGE elite ppg | DT avg-starter ppg | EDGE avg-starter ppg | DT among best 36 DL | DT held-out elite ppg | EDGE held-out elite ppg | DT forward elite ppg 24-25 | EDGE forward elite ppg 24-25 |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| tfl x0 | 10.2 | 15.1 | 5.8 | 7.9 | 13 | 7.5 | 11.7 | 7.8 | 12.2 |
| actual 2026 card | 13.7 | 18.9 | 7.1 | 10.5 | 15 | 10.0 | 13.2 | 10.2 | 16.4 |
| tfl x2 | 17.7 | 22.7 | 8.5 | 13.5 | 15 | 12.1 | 14.6 | 12.8 | 20.6 |
<!-- /table:q1_table -->

Gains from x0 to x2 by tier. Selection-corrected for the in-sample tiers, with 95 percent intervals; the held-out
and forward columns are the elite tier's gain when ranking is done on one half, or on the earlier season:

<!-- table:supp_tfl -->
| pool | elite ppg gain | avg-starter ppg gain | first-bench ppg gain | held-out elite gain | forward elite gain 24-25 | forward elite gain 25-26 | best-ball elite gain (pts/wk) |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| DT | 6.54 [4.50, 8.44] | 2.32 [1.41, 3.08] | 1.93 [1.33, 2.59] | 4.58 [3.24, 6.01] | 5.02 [3.93, 6.67] | 3.92 [1.68, 5.83] | 1.31 [-1.09, 2.89] |
| EDGE | 5.31 [3.15, 7.30] | 5.81 [4.77, 6.78] | 4.38 [3.44, 5.26] | 2.92 [0.40, 4.50] | 8.39 [5.32, 10.85] | 5.15 [2.32, 7.95] | 1.89 [-2.52, 2.60] |
| DL | 5.58 [3.24, 7.74] | 5.73 [4.70, 6.71] | 3.68 [2.82, 4.57] | 3.85 [1.93, 5.73] | 7.94 [4.29, 10.81] | 4.51 [1.74, 7.75] | 1.83 [-2.18, 3.34] |
<!-- /table:supp_tfl -->

Reading. The elite DT and the elite EDGE respond alike; the average DT does not respond like the average EDGE,
because most DTs record few TFL and an edge rusher's TFL stack with sacks. The DT-versus-EDGE ordering of
persistence is not consistent: DT's held-out elite gain is larger (4.6 against 2.9), EDGE's forward gain 2024 to 2025
is larger (8.4 against 5.0), and the intervals overlap. Best-ball gains for both are +1.3 [-1.1, 2.9] and
+1.9 [-2.5, 2.6] points a week for the elite tier, not distinguishable from zero. TFL x2 also lowers DL
split-half reliability from 0.63 to 0.59 (point estimates).

## Q2 — PD

Where PD points come from at the actual card:

<!-- table:pd_profile -->
| pool | tier | PD / game | INT / game | PD points / game | PD share of ppg % | tackle points / game |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| CB | elite 1-12 | 1.18 | 0.15 | 6.3 | 39 | 6.1 |
| CB | avg starter 25-36 | 0.82 | 0.16 | 4.3 | 38 | 5.2 |
| CB | first bench 37-48 | 0.62 | 0.06 | 3.3 | 31 | 4.7 |
| S | elite 1-12 | 0.77 | 0.32 | 4.1 | 25 | 7.2 |
| S | avg starter 25-36 | 0.47 | 0.10 | 2.5 | 24 | 5.9 |
| S | first bench 37-48 | 0.27 | 0.09 | 1.4 | 16 | 5.9 |
| DB | elite 1-12 | 1.11 | 0.27 | 5.9 | 33 | 7.1 |
| DB | avg starter 25-36 | 0.71 | 0.14 | 3.7 | 27 | 6.2 |
| DB | first bench 37-48 | 0.78 | 0.11 | 4.1 | 34 | 5.9 |
<!-- /table:pd_profile -->

Responses at PD x0, actual, x2:

<!-- table:q2_table -->
| PD rate | CB elite ppg | CB avg-starter ppg | CB first-bench ppg | CB separation | CB held-out separation | CB split-half r | CB forward sep 24-25 | CB forward sep 25-26 | S elite ppg | S held-out separation |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| pd x0 | 10.5 | 7.4 | 6.6 | 3.1 | 0.2 | 0.69 | 0.8 | 1.2 | 13.3 | 2.0 |
| actual 2026 card | 16.0 | 11.5 | 10.5 | 4.5 | -0.5 | 0.69 | -0.6 | 2.2 | 16.7 | 2.5 |
| pd x2 | 23.0 | 16.1 | 14.1 | 6.8 | -0.6 | 0.66 | -0.3 | -1.2 | 21.1 | 4.0 |
<!-- /table:q2_table -->

Gains from x0 to x2 by tier (same conventions):

<!-- table:supp_pd -->
| pool | elite ppg gain | avg-starter ppg gain | first-bench ppg gain | held-out elite gain | forward elite gain 24-25 | forward elite gain 25-26 | best-ball elite gain (pts/wk) |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| CB | 9.69 [5.49, 13.11] | 8.87 [7.62, 10.30] | 7.60 [6.41, 8.86] | 6.80 [4.58, 9.26] | 5.92 [4.20, 8.38] | 6.98 [5.22, 10.86] | 2.54 [-0.41, 5.37] |
| S | 7.04 [4.70, 9.19] | 4.42 [3.31, 5.52] | 3.78 [2.81, 4.67] | 5.05 [3.05, 7.31] | 5.27 [4.19, 6.56] | 5.35 [1.20, 8.59] | -0.21 [-1.26, 4.85] |
| DB | 7.32 [3.47, 10.72] | 7.83 [6.44, 9.17] | 6.93 [5.66, 8.11] | 4.27 [2.04, 6.00] | 4.11 [1.95, 5.62] | 6.41 [3.51, 9.51] | 0.72 [-2.81, 2.24] |
<!-- /table:supp_pd -->

Reading. PD pays a CB 6.3 ppg at the elite tier and 3.3 at the first bench: 39 and 31 percent of ppg. The gain in
elite separation is not distinguishable from zero in any version (Q2.1 to Q2.4), the reliability of the CB ordering is
unchanged, and the elite CB's held-out edge is near zero at every PD rate, including PD x0 (0.2, -0.5, -0.6), with a forward edge
that changes sign. The pool
deepens: a first-bench CB at PD x2 scores 14.1 ppg against 6.6 at x0. The DB group, not the CB archetype, is where
the share moves (28.9 to 37.6 percent). The safeties' PD is more concentrated at the top (elite S 0.77 PD a game,
first bench 0.27), and their held-out separation rises with PD (2.0, 2.5, 4.0 ppg; point estimates, exploratory).

## Q3 — LB

<!-- table:q3_table -->
| pool | 36 starters ppg | rank gap / starters | FA gap / starters | weekly CV | best-ball marginal, 36 starters (pts/wk) | deterministic-lineup marginal (pts/wk) | held-out starter-minus-bench gap (ppg) |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| DL | 14.2 | 0.35 | 0.35 | 0.67 | 2.67 | 2.91 | 3.13 |
| LB | 16.8 | 0.28 | 0.36 | 0.51 | 2.10 | 3.00 | 1.55 |
| DB | 15.5 | 0.21 | 0.23 | 0.63 | 1.39 | 2.02 | 0.32 |
| ILB | 16.0 | 0.32 | n/a | 0.44 | 0.77 | 2.26 | 2.27 |
<!-- /table:q3_table -->

Starter-to-replacement is the same story as the contrast table: the relative gaps are close across LB, DL and DB
and the LB advantage is in the floor (CV, reliability) rather than in explosiveness or best-ball premium. How the LB
case depends on tackle scoring:

<!-- table:q3_lb_cards -->
| configuration | DL share of IDP starter points % | LB share of IDP starter points % | DB share of IDP starter points % | LB 36 starters ppg | LB FA gap / starters | DL rank gap (ppg) | LB rank gap (ppg) | DB rank gap (ppg) |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| tackles down | 33.2 | 34.0 | 32.7 | 12.8 | 0.32 | 4.7 | 3.6 | 2.8 |
| actual 2026 card | 30.5 | 36.2 | 33.3 | 16.8 | 0.36 | 4.9 | 4.8 | 3.2 |
| tackles up | 28.6 | 37.7 | 33.7 | 21.0 | 0.35 | 5.3 | 5.2 | 3.3 |
| tackles only | 19.0 | 44.3 | 36.7 | 9.1 | 0.43 | 0.8 | 2.1 | 1.1 |
| playmaking only | 36.7 | 31.7 | 31.6 | 9.4 | 0.25 | 4.3 | 3.0 | 2.4 |
<!-- /table:q3_lb_cards -->

`tackles only` and `playmaking only` are decomposition cards, not proposals: tackles alone give LB 44.3 percent of
IDP starter points, playmaking alone 31.7, and the rank gap collapses to 0.8 ppg for DL on tackles alone.

## Q4 — best ball

<!-- table:q4_table -->
| configuration | slope in-sample [CI] | slope ex ante [CI] | Spearman det vs best ball [CI] | Spearman, deterministic starters only [CI] | DL mean premium, 36 starters | LB mean premium | DB mean premium |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| actual 2026 card | 1.41 [0.62, 2.05] | 0.11 [-0.22, 0.46] | 0.81 [0.76, 0.86] | 0.61 [0.47, 0.80] | -0.24 | -0.91 | -0.63 |
| tfl x0 | 1.31 [0.57, 1.95] | 0.01 [-0.26, 0.28] | 0.74 [0.69, 0.81] | 0.67 [0.56, 0.81] | -0.27 | -0.46 | -0.26 |
| tfl x2 | 1.84 [0.94, 2.75] | 0.12 [-0.25, 0.51] | 0.76 [0.71, 0.82] | 0.63 [0.50, 0.79] | -0.48 | -1.87 | -1.13 |
| pd x0 | 1.64 [0.91, 2.22] | 0.34 [0.08, 0.62] | 0.76 [0.71, 0.82] | 0.58 [0.45, 0.76] | -0.05 | -0.53 | -0.19 |
| pd x2 | 1.72 [0.63, 2.63] | -0.06 [-0.45, 0.35] | 0.79 [0.74, 0.85] | 0.65 [0.54, 0.78] | 0.01 | -0.93 | 0.08 |
| no enhancements | 1.21 [0.72, 1.69] | 0.17 [-0.04, 0.40] | 0.82 [0.78, 0.87] | 0.66 [0.54, 0.84] | 0.56 | 0.18 | -0.08 |
| double enhancements | 2.09 [0.97, 3.00] | -0.05 [-0.47, 0.40] | 0.79 [0.75, 0.86] | 0.66 [0.54, 0.81] | -0.68 | -1.96 | -0.15 |
| tackles up | 1.53 [0.48, 2.39] | 0.13 [-0.26, 0.54] | 0.79 [0.74, 0.85] | 0.70 [0.60, 0.82] | -0.07 | -0.74 | -1.06 |
| tackles down | 1.14 [0.51, 1.67] | 0.02 [-0.23, 0.29] | 0.82 [0.78, 0.87] | 0.68 [0.57, 0.85] | -0.32 | -0.65 | 0.01 |
| bigplay up | 1.53 [0.64, 2.30] | 0.13 [-0.24, 0.54] | 0.80 [0.76, 0.85] | 0.69 [0.56, 0.83] | -0.17 | -0.82 | -0.74 |
| bigplay down | 1.05 [0.25, 1.68] | 0.00 [-0.28, 0.32] | 0.80 [0.76, 0.86] | 0.62 [0.49, 0.79] | -0.29 | -1.04 | -0.84 |
| tackle heavy balanced | 1.10 [0.47, 1.70] | 0.13 [-0.08, 0.38] | 0.73 [0.68, 0.80] | 0.69 [0.59, 0.82] | 0.38 | -0.34 | -0.39 |
| big play | 1.28 [0.64, 1.82] | 0.05 [-0.23, 0.36] | 0.80 [0.76, 0.86] | 0.81 [0.72, 0.95] | -0.80 | -0.27 | -0.27 |
<!-- /table:q4_table -->

The premium columns are mean best-ball minus deterministic marginal over each group's 36 starters: negative for
nearly every group and card, because a bench full of spikes already supplies the best-ball option value that a locked
starter would otherwise add. The positive exceptions are small and largest for DL under the no-enhancement card
(+0.56) and the tackle-heavy card (+0.38). The slope is positive and significant in-sample on every card; the
ex ante slope is indistinguishable from zero on 12 of 13 cards (the exception, PD x0 at 0.34 [0.08, 0.62], is one of
13 uncorrected tests). Lane D's finding that best ball's premium follows the slot economy rather than a
"big-play" label (PR #1941) is consistent with this: the premium here varies by position group, not with the card's
big-play weighting.

## Contrasts

Every pre-registered contrast, with its family's Bonferroni interval. "Bias-corrected" subtracts the mean
replicate minus the observed value.

<!-- table:contrasts -->
| id | contrast | scheme | estimate | bias-corrected | 95% CI | Bonferroni CI | excludes 0 |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| Q1.1 | DT minus EDGE: elite-tier ppg gain from TFL x2 vs x0 | W | -0.11 | 1.23 | [-1.47, 4.11] | [-1.89, 5.38] (m=3) | no |
| Q1.2 | DT minus EDGE: average-starter-tier ppg gain, TFL x2 vs x0 | W | -2.88 | -3.49 | [-4.77, -2.19] | [-5.02, -1.89] (m=3) | yes |
| Q1.3 | change in DT among the 36 best DL, TFL x2 vs x0 | W | 2.00 | 3.14 | [0.00, 7.00] | [-1.00, 7.00] (m=3) | no |
| Q2.1 | CB elite-tier gain minus CB first-bench gain, PD x2 vs x0 | W | 4.99 | 2.09 | [-1.98, 5.54] | [-4.37, 6.62] (m=5) | no |
| Q2.2 | change in CB elite separation (in-sample), PD x2 vs x0 | W | 3.71 | 0.82 | [-2.94, 4.32] | [-5.19, 4.96] (m=5) | no |
| Q2.3 | change in CB held-out elite separation, PD x2 vs x0 | P | -0.78 | -0.83 | [-3.81, 1.82] | [-4.84, 2.52] (m=5) | no |
| Q2.4 | change in CB split-half reliability, PD x2 vs x0 | P | -0.03 | -0.03 | [-0.10, 0.05] | [-0.13, 0.08] (m=5) | no |
| Q2.5 | CB minus S elite-tier gain, PD x2 vs x0 | W | 4.67 | 2.65 | [-1.73, 6.82] | [-3.80, 7.24] (m=5) | no |
| Q3.1a | relative FA-based gap, LB minus DL | W | 0.01 | -0.05 | [-0.29, 0.15] | [-0.35, 0.25] (m=8) | no |
| Q3.1b | relative FA-based gap, LB minus DB | W | 0.13 | 0.08 | [-0.20, 0.30] | [-0.32, 0.36] (m=8) | no |
| Q3.2a | relative rank-based gap, LB minus DL | W | -0.06 | -0.07 | [-0.15, 0.00] | [-0.18, 0.04] (m=8) | no |
| Q3.2b | relative rank-based gap, LB minus DB | W | 0.08 | 0.12 | [0.04, 0.20] | [0.02, 0.23] (m=8) | yes |
| Q3.3a | weekly CV of the 36 starters, LB minus DL | W | -0.16 | -0.20 | [-0.33, -0.07] | [-0.35, -0.01] (m=8) | yes |
| Q3.3b | weekly CV of the 36 starters, LB minus DB | W | -0.12 | -0.16 | [-0.29, -0.02] | [-0.33, 0.01] (m=8) | 95% only |
| Q3.4a | best-ball marginal of the 36 starters (pts/wk), LB minus DL | B | -0.57 | -1.00 | [-3.01, 1.17] | [-3.17, 2.14] (m=8) | no |
| Q3.4b | best-ball marginal of the 36 starters (pts/wk), LB minus DB | B | 0.71 | -0.02 | [-3.21, 2.67] | [-3.70, 3.18] (m=8) | no |
| Q4.1 | premium-on-CV slope (in-sample), actual card | P | 1.41 | 1.39 | [0.62, 2.05] | [0.29, 2.18] (m=4) | yes |
| Q4.2 | premium-on-CV slope (ex ante), actual card | P | 0.11 | 0.11 | [-0.22, 0.46] | [-0.29, 0.54] (m=4) | no |
| Q4.3 | Spearman of deterministic vs best-ball marginal | P | 0.81 | 0.81 | [0.76, 0.86] | [0.75, 0.87] (m=4) | yes |
| Q4.4 | premium-on-CV slope, big-play minus tackle-heavy card | P | 0.17 | 0.17 | [-0.38, 0.75] | [-0.57, 0.89] (m=4) | no |
<!-- /table:contrasts -->

## Cross-position

<!-- table:cross_position -->
| pool | card | best-ball marginal, elite 1-12 (pts/wk) [CI] | elite ppg over free-agent level [CI] |
| --- | ---: | ---: | ---: |
| QB | offense, actual card | 10.9 [6.6, 12.5] | n/a |
| RB | offense, actual card | 12.2 [9.3, 13.6] | 20.7 [17.8, 23.0] |
| WR | offense, actual card | 10.7 [7.5, 11.2] | 16.1 [11.8, 18.7] |
| TE | offense, actual card | 6.8 [4.4, 7.2] | 11.2 [8.9, 14.2] |
| DL | actual 2026 card | 5.7 [3.1, 8.1] | 9.1 [6.6, 12.7] |
| LB | actual 2026 card | 4.0 [-1.8, 6.2] | 9.0 [3.6, 11.6] |
| DB | actual 2026 card | 2.4 [-1.3, 4.2] | 5.8 [2.0, 9.4] |
| DL | tfl x0 | 4.4 [2.6, 6.1] | 7.4 [5.9, 10.4] |
| LB | tfl x0 | 3.5 [-2.2, 5.4] | 8.6 [4.8, 11.4] |
| DB | tfl x0 | 2.9 [0.8, 4.9] | 5.3 [1.8, 8.5] |
| DL | pd x0 | 4.9 [1.2, 6.6] | 7.4 [4.0, 10.2] |
| LB | pd x0 | 3.7 [-1.2, 6.7] | 8.2 [4.1, 11.7] |
| DB | pd x0 | 3.2 [1.7, 4.7] | 5.1 [2.4, 7.9] |
| DL | bigplay up | 7.5 [3.8, 10.7] | 10.5 [6.9, 14.1] |
| LB | bigplay up | 5.1 [-1.4, 9.9] | 10.2 [3.7, 13.4] |
| DB | bigplay up | 3.1 [-0.3, 5.2] | 6.5 [2.1, 10.7] |
| DL | tackle heavy balanced | 3.6 [1.8, 5.1] | 5.6 [4.0, 7.9] |
| LB | tackle heavy balanced | 2.9 [-0.8, 3.2] | 6.8 [3.4, 8.0] |
| DB | tackle heavy balanced | 1.6 [0.2, 4.2] | 3.7 [1.7, 5.9] |
| DL | big play | 7.1 [4.5, 10.1] | 8.8 [5.5, 11.9] |
| LB | big play | 4.5 [-1.3, 7.8] | 7.7 [2.2, 11.2] |
| DB | big play | 2.8 [-0.1, 4.1] | 4.6 [0.3, 7.4] |
<!-- /table:cross_position -->

Ratios of IDP elite to offense elite, same procedure for both:

<!-- table:cross_ratios -->
| card | IDP elite | bb ratio to QB | bb ratio to RB | bb ratio to WR | bb ratio to TE | ppg-over-FA ratio to RB | ppg-over-FA ratio to WR | ppg-over-FA ratio to TE |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| actual 2026 card | DL | 0.52 [0.29, 0.76] | 0.47 [0.32, 0.66] | 0.53 [0.40, 0.73] | 0.84 [0.62, 1.24] | 0.44 [0.30, 0.62] | 0.57 [0.38, 0.82] | 0.81 [0.44, 1.13] |
| actual 2026 card | LB | 0.36 [-0.06, 0.58] | 0.32 [-0.04, 0.51] | 0.37 [-0.04, 0.57] | 0.58 [-0.11, 0.95] | 0.43 [0.16, 0.57] | 0.56 [0.22, 0.76] | 0.80 [0.24, 1.06] |
| actual 2026 card | DB | 0.22 [-0.07, 0.39] | 0.19 [-0.12, 0.34] | 0.22 [-0.04, 0.39] | 0.35 [-0.15, 0.63] | 0.28 [0.09, 0.45] | 0.36 [0.12, 0.59] | 0.52 [0.09, 0.84] |
| tackle heavy balanced | DL | 0.33 [0.19, 0.49] | 0.29 [0.21, 0.40] | 0.33 [0.26, 0.46] | 0.53 [0.41, 0.79] | 0.27 [0.19, 0.38] | 0.35 [0.24, 0.51] | 0.50 [0.28, 0.71] |
| tackle heavy balanced | LB | 0.26 [-0.02, 0.32] | 0.24 [-0.00, 0.27] | 0.27 [0.01, 0.30] | 0.42 [-0.02, 0.51] | 0.33 [0.14, 0.40] | 0.42 [0.20, 0.53] | 0.60 [0.20, 0.74] |
| tackle heavy balanced | DB | 0.15 [0.03, 0.38] | 0.14 [0.01, 0.35] | 0.15 [0.05, 0.40] | 0.24 [0.03, 0.61] | 0.18 [0.08, 0.29] | 0.23 [0.11, 0.37] | 0.33 [0.11, 0.53] |
| big play | DL | 0.65 [0.39, 0.98] | 0.58 [0.47, 0.85] | 0.66 [0.55, 0.97] | 1.03 [0.86, 1.56] | 0.42 [0.26, 0.59] | 0.55 [0.33, 0.77] | 0.79 [0.33, 1.09] |
| big play | LB | 0.41 [-0.02, 0.70] | 0.37 [0.01, 0.65] | 0.42 [0.06, 0.73] | 0.66 [0.00, 1.15] | 0.37 [0.09, 0.55] | 0.48 [0.14, 0.73] | 0.69 [-0.00, 0.98] |
| big play | DB | 0.26 [-0.00, 0.38] | 0.23 [-0.01, 0.35] | 0.26 [0.07, 0.39] | 0.41 [0.09, 0.61] | 0.22 [0.01, 0.36] | 0.29 [0.05, 0.47] | 0.41 [-0.05, 0.66] |
<!-- /table:cross_ratios -->

Free-agent levels differ by construction: RB 3.5, WR 6.5, TE 3.4 ppg against DL 9.2, LB 10.8, DB 12.0, and no QB
free agent qualifies at all, so a points-over-replacement ratio to QB does not exist. The ratios are raw fantasy-point
utility.

## Stability

The contrast point estimates under pool rules of at least 3, 4 and 5 games:

<!-- table:stability_pools -->
| pool rule | Q1.1 | Q1.2 | Q1.3 | Q2.1 | Q2.2 | Q2.5 |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| at least 3 games | -0.11 | -2.88 | 2.00 | 5.04 | 3.80 | 4.67 |
| at least 4 games | -0.11 | -2.88 | 2.00 | 4.99 | 3.71 | 4.67 |
| at least 5 games | -0.63 | -3.11 | 1.00 | 4.53 | 3.29 | 3.69 |
<!-- /table:stability_pools -->

Q1.3 (a count of DTs among the 36 best DL) moves most (2, 2, 1); every other point estimate moves by at most 1.0 ppg. The best-ball level depends strongly on who
the replacement is: the 36 starters' marginal (points a week) by replacement rule:

<!-- table:stability_replacement -->
| replacement | DL 36 starters | LB 36 starters | DB 36 starters | RB 36 starters | WR 36 starters | TE 36 starters |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| free agents ranked 1-5 (primary) | 2.67 | 2.10 | 1.39 | 6.47 | 7.08 | 4.13 |
| free agents ranked 6-10 | 3.71 | 3.88 | 3.10 | 6.63 | 7.23 | 4.40 |
| roster only (no free agent) | 5.56 | 5.61 | 4.80 | 6.76 | 7.37 | 4.80 |
<!-- /table:stability_replacement -->

Against the primary rank 1-5 free-agent replacement, free agents ranked 6-10 raise the IDP starters' marginal by 39
percent (DL), 85 (LB) and 123 (DB), and a roster-only counterfactual by 108, 167 and 245 percent, while offense moves
by 2 to 16 percent. This is Lane D's finding
too, and it is why this page leads with contrasts and ranks rather than with best-ball levels.

## Limitations

* **Six weeks, one season in-sample.** Season-over-season rows use rescored 2024 and 2025 seasons; neither was
  played under these cards, so they are shape references, not what those seasons paid.
* **Selection.** Observed elite tiers are inflated by selection on noise (above). Held-out three-game halves are
  conservative; forward rows use a full season of training but only 6 games of outcome in 2026.
* **Eligibility and positions** are today's Sleeper directory; Sleeper publishes no dated history. Fine positions
  and archetypes come from nflverse rosters and are UNKNOWN where the source is silent.
* **Hindsight free agents.** The free-agent level and the best-ball replacement are selected on the same weeks they
  are scored on, so gaps and marginals are lower bounds (Lane B measured about half of a free agent's level
  surviving out of sample).
* **Best ball is on current rosters** applied to past weeks; aggregates only.
* **Raw fantasy points only.** No dynasty horizon, aging, market price or 1-9999 conversion is attempted, and nothing
  here is a recommendation to change the league's scoring.
* The pre-registered pools are the ones above; 26 OLB are too few for a tier. QB has two qualified free agents and
  therefore no free-agent level.

## Unresolved

* Whether a longer window (a full 17-game 2026 season) shows a CB or LB elite separation the six-week windows cannot.
* An independent forward test of the best-ball premium on a season not used here.
* The vendored Lane D block should become an import once PR #1941 merges; the comparison test then becomes an
  import-equivalence check. The test skips when Lane D's modules are absent; it was run once against them at
  PR #1941's head `0f7eb4a2a` and passed (solver totals, archetype rule and join key identical).

## Reproduce

```bash
python -m scripts.idp_accuracy.scoring_sensitivity run --workers 10   # writes the evidence file (about 8 minutes)
python -m scripts.idp_accuracy.scoring_sensitivity render-doc         # refreshes the generated tables on this page
python -m pytest tests/idp_accuracy/test_scoring_sensitivity.py -q
```

Public Sleeper GETs are cached once under the gitignored `data/idp_accuracy/cache/` (same key scheme as Lanes A
and D, throttled under 5 requests a second); `--offline` reuses them. A stat correction or a re-published nflverse
file can change a re-run; the hashes in `provenance.datasets` are the reference.
