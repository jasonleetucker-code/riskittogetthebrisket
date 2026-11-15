# IDP accuracy, Lane G: near-term retrospective backtest of the cross-position valuation candidates (2026-10-26)

**Status: SHADOW RESEARCH, COMPLETED.** Label `retrospective_point_in_time`. `promotes: false`. Nothing here changes a served value, rank, flag, source weight, anchor,
Hill curve, package model, fairness band or recommendation, and no verdict here writes an `EvaluationReceipt`, emits `challenger_better_pending_policy` or touches
`model_registry.family_gates`. It is **not** the long forward dynasty horizon the fair-value preregistration requires; that requirement stays unmet.

**Authority:** `docs/owner/IDP_VALUATION_ACCURACY_DIRECTIVE_2026-10-25.md` sections 9 and 11 under its section 13 rules.
**Preregistration:** `docs/valuation/idp_accuracy/G_PREREGISTRATION.md`, frozen at commit `4c53736fb`, blob `a60ae89c8` (verified unchanged by the evaluator at both stages).
**Blind stage (Stage 1):** commit `127149899c7a1658d092234a9001d92e75003dfd`, pushed before any outcome was joined; code pin `863691324`; `stage1CodeSha256` `27e19a04172f...` re-verified at Stage 2.
**Stage 2 head:** `a31b17b2f`. **Evidence:** `evidence/g_stage1_manifest.json`, `g_stage1_scores.json`, `g_backtest_2026w1_6.json`, `g_backtest_supplement_champion_level.json`, `f_structural_level_invariance.json`.
**Companion:** `F_CANDIDATES.md` (the candidate set, candidate D, and the F finding).

Agent-OS-Receipt: cb64f74cf4d2763aa16d55ba0d6350f585a2a42f

## 0. Verdict

Verdicts are the preregistered ones (section 8.2). **No candidate advances to a confirmatory preregistration.** The comparator is the *rebuilt* market board (`champion_methodology_at_head`): today's market method on point-in-time inputs, not the board users saw (deviation D2).

| candidate | within-position axis (primary, Delta1) | offense-vs-IDP axis (co-confirmatory, Delta2) | result |
|---|---|---|---|
| A | `champion_better`: -0.266 (-0.326, -0.202); Holm p 0.006 | `champion_better`: -0.041 (-0.069, -0.015); Holm p 0.010 | NOT ADVANCE |
| C | `no_detectable_difference`: -0.049 (-0.100, +0.003); Holm p 0.216 | `no_detectable_difference`: +0.029 (-0.005, +0.064); Holm p 0.216 | NOT ADVANCE |
| D | `no_detectable_difference`: -0.024 (-0.084, +0.037); Holm p 0.464 | `advance_blocked_regression`: +0.050 (+0.018, +0.083); Holm p 0.010 | NOT ADVANCE |
| B | `not_evaluable: degenerate_market_exact` | `not_evaluable: degenerate_market_exact` | not evaluable (every row excluded; returns the market value exactly) |

Cells are `point (95% bootstrap CI)` and the Holm-adjusted two-sided p over the family F1 (six hypotheses). Minimum meaningful effects, fixed beforehand: Delta1 +0.05, Delta2 +0.02.

**The one result that cleared its test and still did not advance.** Candidate D ordered offense-versus-IDP pairs better than the rebuilt market board by +0.050 (+0.018, +0.083), Holm-adjusted p 0.010, above the +0.02 threshold. The preregistered guards blocked the advance (`advance_blocked_regression`):
(i) the within-position guard `Delta1 >= -0.02` failed, Delta1 = -0.024; (ii) the per-position point floor `Delta rho >= -0.10` failed at DB, -0.116; and, separately and not what decided the verdict, (iii) the sign of Delta2 does not survive the best-ball volatility ablation D(sigma = 0), whose Delta2 is -0.005. Reading (iii) plainly: D's cross-position edge *is* the volatility term. Without residual variance it disappears.

**Level direction (section 9.3), near-term only.** Among offense-versus-defender pairs the rebuilt market board ordered wrongly (36,428 of 104,238 pairs with a different realized outcome), it had **overrated the defender in only 15% (95% CI 11% to 19%)**; in the other 85% it put an offensive player above a defender who contributed more to his lineups. Candidates C and D overshoot the other way (58% and 52% of their wrong pairs overrate the defender); A is closer to balance than the champion but still undervalues defenders (39%). That is evidence about **near-term league utility on six weeks**, not about dynasty trade value (section 5).

## 1. What was run

| item | value |
|---|---|
| window | W0: origin = latest archive strictly before the first 2026 kickoff (2026-09-10T00:20:00+00:00), `dynasty_export_20260909_211525.zip`, generated 2026-09-09T21:15:25.520881+00:00; outcome weeks 1-6 of the 2026 regular season |
| champion | **champion-rebuilt**: the ledger read (`batch_known_before`, `knowledge_cutoff` = kickoff - 1 s) found 0 of 834 priced rows (no `data/temporal_ledger.sqlite` here), so the archive's own raw payload was rebuilt by `build_api_data_contract` at HEAD; source freshness weighting was unavailable (every source votes at full base authority) |
| A | A-proxy: BDVM reconstructed baseline from nflverse 2023-2025 with the play-by-play supplement and rookie draft-slot priors, as of the cutoff date; 805 players priced |
| B | `league_fair_value_v1_shadow`, configuration unchanged: 1,067 of 1,067 rows excluded, 0 moved. Removed from every family in Stage 1 |
| C | `mu - R_p`, with `R_p` Lane B's D1 median marginal starter threshold from the 12 cutoff rosters |
| D | expected league-average marginal best-ball contribution (`cross_position.py`), 200 simulated weeks, seed 20261027, no market input |
| cohort | 651 veterans: QB 54, RB 94, WR 133, TE 58, DL 118, LB 90, DB 104. Offense 339, IDP 312. All seven positions have n >= 20, so F1 is fully tested (6 hypotheses; F2 21; F3 6) |
| outcome | LAMBC: realized league-average marginal best-ball contribution on the **cutoff** rosters, host-scored, weeks 1-6, in league points per week (mean 3.2877, sd 3.8101, 79 players exactly 0) |
| inference | paired position-stratified player bootstrap, B = 2000, `Generator(PCG64(20261026))`, one set of resamples for every candidate and metric; Holm at familywise 0.05 within F1, F2, F3 |

**Preconditions (section 6.3), both met before any metric:** the host-native scorer equals Sleeper's awarded points within its 2-decimal rounding for 3,299 of 3,299 player-weeks (max difference 0.00444); the exact solver with the host's zero-fill rule reproduces Sleeper's awarded best-ball totals for 72 of 72 team-weeks (max difference 0.01222). Stage 2 also re-derived the Stage 1 score vectors from scratch and they hashed identically to the committed ones (champion, A, R0, C, D, D standard errors).

**How much could any candidate achieve, and how much could six weeks detect (blind-stage, informational).** 2025 production persistence (Spearman of ppg between weeks 1-6 and weeks 7-12) is QB 0.38, RB 0.79, WR 0.69, TE 0.56, DL 0.41, LB 0.59, DB 0.11. The null standard deviation of the pooled Delta1 at these cohort sizes is 0.0259, so a true Delta1 of about 0.0725 is needed for 80% power, **above** the +0.05 minimum meaningful effect: a null at Delta1 is partly a statement about power.

## 2. Primary and co-confirmatory results

Delta1 is the equal-weight mean over the seven positions of (candidate within-position Spearman with LAMBC) minus (champion's). Delta2 is (candidate offense-vs-IDP pair concordance) minus (champion's). Reference R0 (`mu` alone) sits outside every family and has intervals only.

| | Delta1 within-position Spearman | Delta2 offense-vs-IDP concordance |
|---|---|---|
| A | -0.266 (-0.326, -0.202); Holm p 0.006 | -0.041 (-0.069, -0.015); Holm p 0.010 |
| C | -0.049 (-0.100, +0.003); Holm p 0.216 | +0.029 (-0.005, +0.064); Holm p 0.216 |
| D | -0.024 (-0.084, +0.037); Holm p 0.464 | +0.050 (+0.018, +0.083); Holm p 0.010 |
| R0 | -0.049 (-0.100, +0.003) | -0.005 (-0.040, +0.030) |

Absolute levels, for scale (not tested): within-position Spearman of the champion with LAMBC: QB 0.69, RB 0.66, WR 0.69, TE 0.64, DL 0.30, LB 0.55, DB 0.33; offense-vs-IDP concordance 0.650. Candidates: A concordance 0.609; C concordance 0.679; D concordance 0.700.

### 2.1 The permitted sentences (section 13.1)

* *On 2026 regular-season weeks 1-6, for veteran players with prior-season production (no rookies), at a point-in-time cutoff before week 1, candidate A ordered realized marginal best-ball lineup contribution within positions worse than the rebuilt served market board, by Delta1 = -0.266 (95% CI -0.326, -0.202, Holm-adjusted p 0.006).*
* *On 2026 regular-season weeks 1-6, for veteran players with prior-season production (no rookies), at a point-in-time cutoff before week 1, candidate A ordered realized marginal best-ball lineup contribution across offense versus IDP worse than the rebuilt served market board, by Delta2 = -0.041 (95% CI -0.069, -0.015, Holm-adjusted p 0.010).*
* *On 2026 regular-season weeks 1-6, for veteran players with prior-season production (no rookies), at a point-in-time cutoff before week 1, candidate C ordered realized marginal best-ball lineup contribution within positions indistinguishably from the rebuilt served market board, by Delta1 = -0.049 (95% CI -0.100, +0.003, Holm-adjusted p 0.216).*
* *On 2026 regular-season weeks 1-6, for veteran players with prior-season production (no rookies), at a point-in-time cutoff before week 1, candidate C ordered realized marginal best-ball lineup contribution across offense versus IDP indistinguishably from the rebuilt served market board, by Delta2 = +0.029 (95% CI -0.005, +0.064, Holm-adjusted p 0.216).*
* *On 2026 regular-season weeks 1-6, for veteran players with prior-season production (no rookies), at a point-in-time cutoff before week 1, candidate D ordered realized marginal best-ball lineup contribution within positions indistinguishably from the rebuilt served market board, by Delta1 = -0.024 (95% CI -0.084, +0.037, Holm-adjusted p 0.464).*
* *On 2026 regular-season weeks 1-6, for veteran players with prior-season production (no rookies), at a point-in-time cutoff before week 1, candidate D ordered realized marginal best-ball lineup contribution across offense versus IDP better than the rebuilt served market board, by Delta2 = +0.050 (95% CI +0.018, +0.083, Holm-adjusted p 0.010).*

## 3. Per position (F2) and the regression guards

Delta rho per position, `point (95% CI)`; the Holm-adjusted p is over all 21 position hypotheses. Per-position statements are allowed only where F2 rejects after Holm (marked `*`); elsewhere they are descriptive. With B = 2000 and m = 21 the first Holm threshold is 0.05/21 = 0.0024, so an F2 rejection allows at most one resample to cross zero: the practical regression guard is the -0.10 point floor, not F2 significance (stated in advance).

| position | n | A | C | D |
|---|---|---|---|---|
| QB | 54 | -0.426 (-0.652, -0.216) *; p 0.02 | -0.076 (-0.243, +0.070); p 1.00 | -0.074 (-0.217, +0.066); p 1.00 |
| RB | 94 | -0.146 (-0.259, -0.042); p 0.06 | -0.077 (-0.204, +0.041); p 1.00 | +0.003 (-0.096, +0.101); p 1.00 |
| WR | 133 | -0.160 (-0.244, -0.082) *; p 0.02 | -0.110 (-0.207, -0.015); p 0.31 | -0.055 (-0.170, +0.059); p 1.00 |
| TE | 58 | -0.266 (-0.438, -0.100) *; p 0.04 | +0.100 (-0.059, +0.257); p 1.00 | +0.035 (-0.167, +0.222); p 1.00 |
| DL | 118 | -0.304 (-0.482, -0.127) *; p 0.02 | +0.014 (-0.117, +0.144); p 1.00 | +0.046 (-0.092, +0.199); p 1.00 |
| LB | 90 | -0.264 (-0.429, -0.103) *; p 0.04 | -0.044 (-0.174, +0.085); p 1.00 | -0.004 (-0.181, +0.167); p 1.00 |
| DB | 104 | -0.298 (-0.485, -0.113); p 0.06 | -0.152 (-0.328, +0.017); p 1.00 | -0.116 (-0.321, +0.076); p 1.00 |

Guards per candidate and axis (section 8.2 rules 2-4; rule 5 is in section 6):

| candidate | axis | F1 rejects with delta > 0 and >= threshold | F2-significant negative positions | positions below -0.10 (point) | other-axis guard | verdict |
|---|---|---|---|---|---|---|
| A | within | no (delta -0.266, threshold +0.05) | QB, WR, TE, DL, LB | QB, RB, WR, TE, DL, LB, DB | FAILS (other axis -0.041, floor -0.01) | `champion_better` |
| A | cross | no (delta -0.041, threshold +0.02) | QB, WR, TE, DL, LB | QB, RB, WR, TE, DL, LB, DB | FAILS (other axis -0.266, floor -0.02) | `champion_better` |
| C | within | no (delta -0.049, threshold +0.05) | none | WR, DB | ok (other axis +0.029, floor -0.01) | `no_detectable_difference` |
| C | cross | no (delta +0.029, threshold +0.02) | none | WR, DB | FAILS (other axis -0.049, floor -0.02) | `no_detectable_difference` |
| D | within | no (delta -0.024, threshold +0.05) | none | DB | ok (other axis +0.050, floor -0.01) | `no_detectable_difference` |
| D | cross | yes (delta +0.050, threshold +0.02) | none | DB | FAILS (other axis -0.024, floor -0.02) | `advance_blocked_regression` |

## 4. Elite identification (F3, secondary, never gates)

Precision of the ex-ante top 12 within each position (averaged over the seven) and of the pooled top 36, as a difference from the champion; minimum meaningful effect +1/12.

| | Delta3 positional precision@12 | Delta3 pooled precision@36 |
|---|---|---|
| A | -0.131 (-0.226, -0.036); Holm p 0.060 | -0.139 (-0.278, +0.000); Holm p 0.445 |
| C | +0.071 (-0.071, +0.131); Holm p 1.000 | +0.056 (-0.111, +0.222); Holm p 1.000 |
| D | +0.000 (-0.119, +0.095); Holm p 1.000 | +0.000 (-0.167, +0.194); Holm p 1.000 |

No elite delta rejects. The pooled precision@36 levels are A 0.278, C 0.472, D 0.417 against the champion's 0.417.

## 5. The level diagnostic (section 9.3)

Among offense-versus-defender pairs a candidate orders wrongly, the share in which it put the defender above the offensive player. 0.5 is no level bias; above 0.5 it overvalues defenders relative to near-term lineup contribution; below, it undervalues them. Intervals are from the same resamples as every other metric (the champion's, from the supplement, deviation D7).

| | share overrating the defender | 95% CI | wrongly ordered pairs |
|---|---|---|---|
| champion | 0.150 | 0.112, 0.194 | 36,428 of 104,238 |
| A | 0.394 | 0.330, 0.459 | 40,713 of 104,238 |
| C | 0.584 | 0.513, 0.650 | 33,409 of 104,238 |
| D | 0.523 | 0.450, 0.592 | 31,236 of 104,238 |

Defenders in each candidate's own top 36 / top 100 of the cohort (blind-stage): champion 1 / 12, A 4 / 25, C 7 / 31, D 9 / 32, R0 0 / 17, against defenders being 47.9% of the cohort.

## 6. Stability (section 10)

Core variants S1-S6 must preserve the **sign** of Delta1 (within axis) or Delta2 (cross axis) for an advance. A variant that cannot be built is `not_evaluable` and does not block. Point estimates only (the cluster bootstrap S8 gives intervals).

| variant | applies to | Delta1 A / C / D | Delta2 A / C / D |
|---|---|---|---|
| main (W0, all 651) | all | -0.266 / -0.049 / -0.024 | -0.041 / +0.029 / +0.050 |
| S1 Wa weeks1to3 | A, C, D | -0.272 / -0.033 / -0.011 | -0.063 / +0.010 / +0.032 |
| S1 Wb weeks4to6 **(exploratory, D1)** | A, C, D | -0.135 / -0.048 / +0.031 | -0.006 / +0.040 / +0.071 |
| S2 age plus1 | A | -0.244 / - / - | -0.033 / - / - |
| S2 age minus1 | A | -0.287 / - / - | -0.049 / - / - |
| S3 D2 | C | - / -0.049 / - | - / -0.041 / - |
| S3 D4 | C | - / -0.049 / - | - / +0.029 / - |
| S4 sigma0 | D | - / - / +0.002 | - / - / -0.005 |
| S4 ownteam | D | - / - / -0.095 | - / - / +0.019 |
| S6 pairwise support | A, C, D | -0.276 / -0.067 / -0.019 | -0.044 / +0.025 / +0.051 |
| S7 placeholder | descriptive | - / -0.049 / -0.033 | - / +0.028 / +0.045 |
| S9 n weighted | descriptive | -0.252 / -0.059 / -0.025 | -0.041 / +0.029 / +0.050 |
| S9 cross rostered only | descriptive | -0.242 / -0.022 / -0.012 | -0.043 / +0.034 / +0.049 |
| S10 pseudo0 | descriptive | - / - / -0.031 | - / - / +0.048 |
| S10 pseudo16 | descriptive | - / - / -0.011 | - / - / +0.049 |
| S3 D5 | - | not_evaluable: degenerate_one_pseudo_week_allocation | |
| S5 projection mix | - | not_evaluable: no_real_projection_snapshot_with_a_creation_stamp_before_the_cutoff | |
| S8 cluster bootstrap by NFL team (32 clusters) | all | (-0.325, -0.199) / (-0.091, -0.006) / (-0.077, +0.031) | (-0.064, -0.014) / (-0.002, +0.059) / (+0.019, +0.078) |

Notes. S3 D4 is identical to C: the qualified free-agent pool is empty at every position at the cutoff, so D4 falls back to D1 (labelled). S4's ablation is the informative one: **D(sigma = 0)** removes the best-ball volatility term and with it D's cross-position gain (Delta2 -0.005), and the roster-context ablation (own team only) loses within-position order (Delta1 -0.095). The age variants (S2) move A's Delta1 only between -0.287 and -0.244: A's deficit is not an age-assumption artifact.

Sign changes found (these are what `stabilitySignChanged` lists in the evidence): A within: none; A cross: none; C within: none; C cross: S3_D2; D within: S1_Wb_weeks4to6, S4_sigma0; D cross: S4_sigma0. **No verdict depends on Wb**: the A and C verdicts are decided at F1, and D's two axes are decided before the stability rule (no detectable difference; blocked by guards (i) and (ii)).

## 7. Failure cases (section 11)

Delta rho (candidate minus champion Spearman, equal-weight mean over positions with at least 8 members in the slice) and the change in offense-vs-IDP concordance, where the slice has n >= 15 and at least 5 players on each side.

| slice | n | Delta rho A / C / D | Delta concordance A / C / D |
|---|---|---|---|
| position:QB | 54 | -0.426 / -0.076 / -0.074 | n/a / n/a / n/a |
| position:RB | 94 | -0.146 / -0.077 / +0.003 | n/a / n/a / n/a |
| position:WR | 133 | -0.160 / -0.110 / -0.055 | n/a / n/a / n/a |
| position:TE | 58 | -0.266 / +0.100 / +0.035 | n/a / n/a / n/a |
| position:DL | 118 | -0.304 / +0.014 / +0.046 | n/a / n/a / n/a |
| position:LB | 90 | -0.264 / -0.044 / -0.004 | n/a / n/a / n/a |
| position:DB | 104 | -0.298 / -0.152 / -0.116 | n/a / n/a / n/a |
| championBand:1-50 | 46 | -0.264 / +0.134 / -0.019 | n/a / n/a / n/a |
| championBand:51-150 | 79 | -0.242 / +0.107 / +0.089 | -0.039 / -0.038 / -0.051 |
| championBand:151-300 | 116 | -0.180 / +0.027 / +0.024 | +0.025 / +0.138 / +0.166 |
| championBand:301-800 | 347 | -0.346 / +0.027 / +0.173 | -0.012 / +0.134 / +0.158 |
| championBand:offCapValueOnly | 63 | -0.162 / +0.026 / +0.190 | n/a / n/a / n/a |
| age:<=24 | 184 | -0.251 / -0.179 / -0.059 | -0.011 / +0.024 / +0.055 |
| age:25-28 | 335 | -0.144 / -0.124 / -0.103 | -0.016 / +0.006 / +0.031 |
| age:>=29 | 132 | -0.041 / -0.012 / -0.020 | -0.006 / -0.022 / -0.007 |
| rostered | 505 | -0.242 / -0.022 / -0.012 | -0.043 / +0.034 / +0.049 |
| unrostered | 146 | -0.203 / -0.072 / +0.094 | +0.073 / +0.124 / +0.178 |
| dlLbHybrid | 37 | -0.008 / +0.086 / +0.176 | n/a / n/a / n/a |
| gamesPlayed<=3 | 137 | -0.108 / -0.115 / +0.010 | -0.006 / +0.013 / +0.046 |

Unavailable, named rather than invented: interior DL versus edge, and CB versus S (Sleeper positions do not distinguish them and no point-in-time depth-chart source is pinned).

The 20 players whose within-position percentile rank error grew most against the champion, per candidate (public names; patterns, not grades):

* **D:** Malik Nabers (WR, +0.79); Geno Stone (DB, +0.68); Mike Jackson (DB, +0.64); Devin White (LB, +0.62); Jonathon Cooper (DL, +0.61); MarShawn Lloyd (RB, +0.56); Isaiah Likely (TE, +0.55); Jalen Carter (DL, +0.55); Kevin Byard (DB, +0.49); Fred Warner (LB, +0.48); Jaycee Horn (DB, +0.48); Nolan Smith (DL, +0.43); Matthew Golden (WR, +0.41); Travis Hunter (WR, +0.41); Marquise Brown (WR, +0.41); Malaki Starks (DB, +0.38); Rashan Gary (DL, +0.37); Edgerrin Cooper (LB, +0.37); Tyrel Dodson (LB, +0.37); Quinnen Williams (DL, +0.36)
* **C:** Mike Jackson (DB, +0.64); Jonathon Cooper (DL, +0.64); Matthew Golden (WR, +0.54); James Conner (RB, +0.53); Brandon Aiyuk (WR, +0.50); Isaiah Likely (TE, +0.45); Devin White (LB, +0.44); Geno Stone (DB, +0.44); Bhayshul Tuten (RB, +0.44); Blake Corum (RB, +0.44); Bryce Young (QB, +0.43); Kevin Byard (DB, +0.42); Malaki Starks (DB, +0.41); Tyrel Dodson (LB, +0.40); Talanoa Hufanga (DB, +0.39); Ollie Gordon (RB, +0.38); DeShon Elliott (DB, +0.38); Mason Graham (DL, +0.36); Dorance Armstrong (DL, +0.35); Dee Winters (LB, +0.34)
* **A:** Byron Young (DL, +0.75); Terrion Arnold (DB, +0.74); Oluwafemi Oladejo (DL, +0.73); Jeremy Chinn (DB, +0.68); Omarr Norman-Lott (DL, +0.67); Shemar Stewart (DL, +0.64); Malachi Moore (DB, +0.64); Nick Martin (LB, +0.62); Shemar James (LB, +0.58); Talanoa Hufanga (DB, +0.58); Mykel Williams (DL, +0.54); Riley Leonard (QB, +0.54); Quinn Ewers (QB, +0.54); Budda Baker (DB, +0.53); Nolan Smith (DL, +0.53); Jaydon Blue (RB, +0.52); Xavier Restrepo (WR, +0.52); Jack Kiser (LB, +0.51); Minkah Fitzpatrick (DB, +0.48); Chimere Dike (WR, +0.47)

## 8. Descriptive analyses (no test family, no gate)

### 8.1 Roster counterfactuals (section 9.1), W0, 12 teams, no inferential claim

Every legal swap at the cutoff: drop a cohort player a team holds, add a cohort player nobody holds. 73,730 swaps across 12 teams (66,808 with a nonzero realized gain). Realized gain = sum over weeks 1-6 of the lineup-total change.

| | pairwise sign accuracy | top-swap mean realized (pts over 6 wks) | top-3 mean realized | teams whose top swap beat the champion's |
|---|---|---|---|---|
| champion | 0.718 | -4.95 | -7.65 | - |
| A | 0.647 | -12.55 | -10.31 | 5 of 12 |
| C | 0.648 | -12.44 | -7.67 | 5 of 12 |
| D | 0.739 | -3.32 | -2.00 | 5 of 12 |

Selection inflates every prediction (Lane B's winner's curse): the chosen swaps' predicted gain exceeded the realized per-week gain by +4.04 points per week for C and +5.53 for D. That gap is reported and never used to score. The champion's and A's predictions are on value scales with no validated points mapping.

### 8.2 Trade examples (section 9.2), W0, public-player level only

Universe: trades between two different teams, assets in the cohort, that the champion's own rule calls fair (`geom_q078_v1` adjusted gap inside the `fairness_bands_v2` fair band). Sample: the first 150 per category in `sha256("idp-g-v1" + trade id)` order. The realized winner is the team with the larger lineup-total gain over weeks 1-6 after any forced cut. A call is correct when it names that winner; Wilson 95% intervals.

| category | universe | champion | A | C | D |
|---|---|---|---|---|---|
| offense-for-IDP 1-for-1 | 57,034 | 0.507 (0.43, 0.59) | 0.561 (0.48, 0.64) | 0.689 (0.61, 0.76) | 0.750 (0.68, 0.81) |
| 2-for-1 | 4,874,961 | 0.513 (0.43, 0.59) | 0.413 (0.34, 0.49) | 0.543 (0.47, 0.62) | 0.547 (0.47, 0.62) |
| 2-for-1 forcing a cut (roster at 58) | 3,450,317 | 0.493 (0.41, 0.57) | 0.387 (0.31, 0.47) | 0.563 (0.48, 0.64) | 0.640 (0.56, 0.71) |

Read with care. The universe is the trades the *champion* calls fair, so its calls are near coin flips by construction. C and D predict whole-roster expected lineup change, which is the very quantity the outcome measures, so they are favoured by the target; a dynasty trade is a multi-year bet and six weeks of lineup points cannot grade it. These examples expose failure modes, nothing more. In the 2-for-1 category the starter-upgrade side (the team receiving the single player) won 81 of 150 (champion), 78 of 150 (A), 90 of 150 (C), 69 of 150 (D) under each candidate's own forced-cut choices, while D named the upgrade side the winner in only 39 of 150 trades (it prefers depth).

### 8.3 Elite separation (section 9.4), cardinal, points-scale candidates only

Mean of the top 12 over the mean of ranks 13-36 at the position, for the prediction and for the outcome (LAMBC, points per week).

| position | D prediction | outcome | C prediction | outcome |
|---|---|---|---|---|
| QB | 1.94 | 2.76 | n/a | 2.76 |
| RB | 1.69 | 2.79 | 14.30 | 2.79 |
| WR | 1.46 | 1.90 | 3.11 | 1.90 |
| TE | 1.62 | 2.27 | n/a | 2.27 |
| DL | 1.53 | 1.93 | 20.05 | 1.93 |
| LB | 1.36 | 1.88 | 6.46 | 1.88 |
| DB | 1.21 | 1.82 | 13.43 | 1.82 |

D's predicted elite separation is flatter than the realized one at every position (1.2-1.9 against 1.8-2.8): it understates how far the best players sit above the next tier (consistent with an average over twelve rosters and independent draws; not tested). C's ratios are on a *points-over-replacement* scale whose mean of ranks 13-36 is near or below zero, so its ratios are offset artifacts and carry no meaning; champion, A and B are `unavailable: no_validated_points_mapping`.

### 8.4 Secondary outcome and R0 (section 9.5), intervals only

Realized points per game over the window, 599 cohort players with at least one game, same metrics, B = 500 resamples (the evidence file carries p-values from the shared helper for this block; they are outside every family and are not used).

| | Delta1 | Delta2 |
|---|---|---|
| A | -0.218 (-0.285, -0.159) | +0.012 (-0.016, +0.040) |
| C | -0.017 (-0.073, +0.033) | +0.085 (+0.052, +0.124) |
| D | -0.057 (-0.116, -0.004) | +0.073 (+0.041, +0.106) |
| R0 | -0.017 (-0.073, +0.033) | +0.098 (+0.065, +0.136) |

On realized points per game the projection prior alone (R0) beats the rebuilt market board offense-versus-IDP (Delta2 about +0.10) while matching it within positions: a projection built from production history has a built-in advantage on a six-week production target, exactly as the fair-value preregistration says of its own secondary ROS metric.

## 9. The F finding in one paragraph

`league_fair_value_v1_shadow` quantile-matches offense and IDP **separately**, so it permutes (or log-interpolates between members of) each scope's own value list: each scope's multiset of values is exactly preserved at full strength and its geometric mean at any uniform strength, whatever utility order it is shown. It therefore structurally cannot correct an overall IDP-vs-offense level error. This was shown with a constructed example and measured on two real boards in `F_CANDIDATES.md` section 3 and `evidence/f_structural_level_invariance.json`. Here B was in any case `degenerate_market_exact`: with the proxy-only A it moved no row.

## 10. Deviations (dated 2026-10-26)

The preregistration was **not edited** (blob `a60ae89c8`, commit `4c53736fb`; the evaluator verified it at both stages). Where it could not be executed as written, or left a
choice open, the choice was made in the BLIND stage and recorded in the Stage 1 manifest before any outcome was joined. Anything affected by a deviation that touches outcomes
is labelled exploratory.

### D1. Wb (the week-4 origin) could not be built blind and was built after W0 was unblinded. Exploratory.
Section 2.3 admits 2026 REG weeks 1-3 as history for the Wb origin. Section 12.1 forbids loading any 2026 week 1-6 outcome in the blind stage. Those weeks ARE W0 outcome
weeks, so the two sections cannot both be followed. Stage 1 therefore computed W0/Wa only and declared Wb deferred (manifest `windows.Wb.candidateVectors`, written before any
outcome). Wb's vectors were built in Stage 2 from weeks 1-3 only and hashed before its weeks 4-6 outcomes were joined, but W0 (which contains weeks 4-6) was already open. Wb is
therefore **exploratory** and reported separately (section 6, a marked row). Wb's A uses BDVM's section 8.4 posterior from the three observed weeks, passed as an explicit
truncated `actuals` input, which `run_valuation` accepts. **No verdict depends on Wb** (section 6).

### D2. The ledger was unavailable; the champion is `champion-rebuilt` (the preregistered fallback, not a free choice).
`src.history.asof.batch_known_before(... knowledge_cutoff = K_w - 1 s)` was called for every priced row of the cutoff board against the production ledger path.
`data/temporal_ledger.sqlite` does not exist in this repository (a box-local store), so all 834 reads were `unavailable` (`no_prior_observation`) and coverage was 0% against
the 95% bar. Section 4.1 therefore applies: the champion is the cutoff archive's own raw payload rebuilt by `build_api_data_contract` at HEAD, labelled
`champion_methodology_at_head`; every claim reads "today's market method on point-in-time inputs". Three further limits of the rebuild are declared: the box's dataset-state
directory is not archived, so source freshness/health/coverage weighting is *unavailable* and every source votes at full base authority; the archive carries 10 source CSVs (the
KTC family, IDP Trade Calculator, Draft Sharks) and the contract builder logged missing files for 18 further registered sources (DLF, FantasyPros, FantasyCalc and others) that
the archive does not carry, so their votes, if the live board had any that day, are absent from the rebuild; and the builder's league context (roster count, TE
bonus) was read from the archive's own `sleeper` block instead of a live Sleeper call. No served board exists for the cutoff, so the served-versus-rebuilt drift (section 4.1)
is not computable.

### D3. Candidate A is the A-proxy tier, built by the script's library call, not its CLI.
No box snapshot with an immutable creation stamp at or before the cutoff exists in this repository, so the preregistered substitute applies: a clean reconstructed baseline
from nflverse seasons 2023-2025 (with the play-by-play supplement built for those seasons) and rookie draft-slot priors. `scripts/bdvm_build_baseline.py` hard-codes
`as_of = today` and writes to the default snapshot directory, so its two library calls (`fetch_and_build_baseline`, then `run_valuation`) were made directly with `as_of` =
the cutoff date, no prior snapshot to carry forward, no event loaded and no in-season actuals; the call chain is otherwise identical. Stability S5 (A-real against A-proxy;
offense-real plus IDP-proxy; IDP Show dropped) is **not evaluable**, and A's within-position deficit is a statement about the proxy tier (history-only, shrunk) and not about BDVM
with real projection sources.

### D4. Specification gaps resolved in the blind stage (recorded in the manifest; not outcome-informed).
1. **D1 in section 4.4.** "The league-wide starter threshold" was implemented as Lane B's `PositionThreshold.median_marginal` (what the weakest started player at the position
   produces, the median over teams), with `mu` as the lineup objective.
2. **Rookies.** A drafted rookie has a BDVM draft-slot prior but no prior-season production. Section 3.5 treats a rostered player with no `P` as UNKNOWN and section 13.1 limits
   the claim to veterans with prior-season production, so a player whose only projection is `rookieDraftSlotPrior` is UNKNOWN in the C and D environments and is not in the cohort
   (123 players). A's replacement pool still contains the rookie priors, as the shipped baseline builder produces them.
3. **D's randomness.** Each simulated week owns an independent child stream, `PCG64(SeedSequence([20261027, week]))`, instead of one sequential stream, so the result is a function
   of the seed alone and not of how weeks are chunked across 16 worker processes (a test pins one process equal to many).
4. **Availability.** `G_i` is the number of games the player's cutoff NFL team played in the history window (2025 weeks 1-18); nflverse roster files give no week-level
   roster membership. `abar_p` is the mean `g/G` over the provisional cohort (champion value, Sleeper id, in-scope position, `yearsExp >= 1`). A player with no team has no schedule
   and is not simulated (44 `no_availability`). Residual pools use the provisional cohort and `|E_j| >= 6`.
5. **Cached eligibility in the lineup port.** The solver call is the owner's `solve_optimal_assignment` with its own `precompute_slot_eligibility` map; only the per-shape caching
   is local, and a test pins the assignment byte for byte against the un-cached call.
6. **Section 9.1 / 9.2 / 11 operationalisation.** Trade id = `ta|tb|sorted ids given by ta|sorted ids given by tb` with anonymised labels `ta < tb`; a forced cut may remove only a
   player the choosing candidate can score (an UNKNOWN player is never a free cut); a 2-for-1 that pushes a roster past 58 forces a cut in both category (b) and (c); position-mixed
   slices report the equal-weight mean of within-position deltas over positions with at least 8 members.
7. **S3.** D4 is empty at every position at the cutoff and falls back to D1 (so S3 D4 equals C); D5 is not evaluable (a one-pseudo-week allocation degenerates to a single claim, Lane B).

### D5. File names.
The results record is `G_ACCURACY.md` (not `G_RESULTS.md`), as directed for this lane. The evidence file keeps the preregistered name `evidence/g_backtest_2026w1_6.json`.

### D6. Stage 2 was rehearsed on public 2025 weeks 1-6 as stand-in outcomes; one real invocation crashed before any join.
Before the real run the whole of Stage 2, including Wb, was rehearsed with the **public 2025** weeks 1-6 standing in for the outcomes (no 2026 outcome touched; the rehearsal
output was discarded and not used). It exercised every path and fixed three evaluator defects (variant arrays; the swap worker initialiser; the Wb stand-in season). The stage 1
portion of the script is unchanged and pinned by `stage1CodeSha256`, which Stage 2 recomputes and refuses to run without. The first real invocation then passed the section 6.3
preconditions and **crashed on an unbound local variable (`weeks`, assigned only on the rehearsal branch) before any outcome was joined to any candidate**; it computed no metric.
It was fixed (commit `a31b17b2f`) and re-run. The result of record is the second run; no threshold, cohort, window, variant or candidate definition changed between runs.

### D7. A supplement computes the comparator's own level-diagnostic interval.
Section 9.3 asks for each candidate's level diagnostic with a bootstrap interval from the same resamples. The Stage 2 run carried the intervals for A, C and D but only the
champion's point value. `scripts/idp_accuracy/backtest.py supplement` recomputes LAMBC deterministically, **verifies that it reproduces the committed champion and candidate
numbers**, and bootstraps the identical selections (`evidence/g_backtest_supplement_champion_level.json`). It tests nothing new and changes no verdict.

### D8. Reporting notes that are not deviations of procedure.
The secondary-outcome block in the evidence file carries p-values from the shared helper; per section 7.5 it is outside every family and they are not used. C's elite-separation
ratios (section 8.3) are on a points-over-replacement scale and are offset artifacts. `src/bestball` was read and not used: `tests/bestball/test_import_graph.py` forbids importing
it from `scripts/`, and section 4.5 defines D without a waiver-replacement scenario.


## 11. What may and may not be concluded (section 13)

**May:** the permitted sentences in section 2.1; the near-term level direction in section 0 and 5, as evidence about near-term league utility; per-position statements only where marked `*` in section 3 (candidate A at QB, WR, TE, DL, LB); that a candidate be carried to a confirmatory preregistration (none qualifies).

**May not:**
* **Nothing about dynasty value** (aging, development, durability, role security, rookies, future discounting). The target is six weeks. A projection-built candidate is favoured by construction on a near-term production target; the market prices years. "Beats the market on six weeks" is not "is a better dynasty value", and "loses on six weeks" is not "is a worse one".
* **Not out-of-sample or validated.** Label `retrospective_point_in_time`; the outcomes were public and earlier lanes had examined them before several candidates were defined (Lane B's definitions were developed on these weeks).
* **Correlated wins are not confirmations.** A, C and D all descend from the same projection prior; agreement among them is one body of evidence.
* **No scale or production change.** No served value, anchor, IDP ceiling, source weight, Hill curve, package model, fairness band or trade recommendation changes on this result. Nothing about calibration to 1-9999.
* **Nothing about rookies, kickers or picks** (not in the cohort); **no archetype claim** (interior DL, CB); **no individual-player claim** (a six-week outcome is dominated by noise and injury; the failure lists illustrate patterns).
* **Not "the market is right" either.** The nulls (C, D within positions) may be low power over six weeks: the detectable Delta1 at 80% power is about 0.0725, above the +0.05 effect that matters.
* **The injury asymmetry favours the champion.** Injury status at the cutoff is not used (it cannot be reconstructed point-in-time), so the market knew preseason injuries that the projection-built candidates did not. Any result favouring the champion may partly reflect that.
* **The champion is the rebuilt method at HEAD with freshness weighting unavailable**, not the served board.
* **Nothing here sets or informs any TO-FREEZE field of the fair-value preregistration.** That commit must disclose that this experiment ran and what it found for B (nothing: degenerate). Whether 2026 can still serve as a clean holdout season for `league_fair_value_v1` is an **owner question**, raised here and not decided.

## 12. Unresolved

* **UNRESOLVED (owner):** whether 2026 remains a clean holdout for `league_fair_value_v1` now that this ran (the preregistration raises it; it is not decided here). Its owner preconditions (`projectionUtilityInDynastyRuling`, `canonicalIdentityArchitecture`) remain unrecorded.
* **UNRESOLVED (evidence):** an A-real tier (a box BDVM snapshot with an immutable creation stamp before the cutoff, or a vendor projection source) would let S5 run and would make B evaluable; none exists in this repository. A served-board ledger for the cutoff would replace champion-rebuilt with the board users saw.
* **UNRESOLVED (design):** D's cross-position gain is carried by its volatility term and D loses at DB (the position with the lowest 2025 production persistence, Spearman 0.11 between half-seasons). A confirmatory test on outcomes not yet observed needs a new preregistration whose window starts after its commit; the long forward multi-season validation stays required on top of that.

## 13. Regenerate

```
python scripts/idp_accuracy/backtest.py stage1            # blind; writes the manifest, score vectors, F evidence
python scripts/idp_accuracy/backtest.py stage2            # unblind once; refuses unless the stage 1 commit is pushed and the stage 1 code unchanged
python scripts/idp_accuracy/backtest.py supplement        # champion section 9.3 interval from the same resamples (D7)
python scripts/idp_accuracy/backtest.py stage2 --rehearsal   # public 2025 weeks 1-6 stand in for the outcomes
python -m pytest tests/league_valuation tests/idp_accuracy -q
bash scripts/format_python_changes.sh
```

Inputs are Lane A's cached public Sleeper bodies (`data/idp_accuracy/cache`, gitignored), the tracked `exports/archive/` zips, and nflverse public CSVs. Committed artifacts carry aggregates and public NFL player names only; no manager, team, owner or roster identifier and no raw Sleeper league id.
