# BDVM directional-signal saturation — diagnosis and preregistered challenger screen (2026-11-08)

Authority: owner master directive 2026-11-08 §18 Priority 13. Scope: DIAGNOSE and
EVALUATE only. No served signal, threshold, parameter (`config/bdvm/params_v1.json`
is owner-protected), label enum or value changes in this record. Evaluation code is
`src/bdvm/signal_diagnostics.py` (never imported by the serving path) driven by
`scripts/evaluate_bdvm_signal.py`.

## 0. Preregistration (committed BEFORE any outcome was computed)

**Question.** Does the served ladder (`market.buy_hold_sell`, absolute alpha =
(fundamental balanced trade value - market value) x liquidity against +-400 / +-900)
discriminate, and would a scale-aligned or relative comparison predict later market
movement better?

**Incumbent C0.** Served ladder, absolute alpha. Score for rank-IC = alpha.

**Challengers (fixed now, not tuned):**

| id | construction | thresholds |
|---|---|---|
| C1 | within-pool percentile(fundamental) - percentile(market), one pool, one 0-1 scale | weak 0.15, strong 0.30 percentile points (round priors, chosen before data) |
| C2 | fundamental quantile-matched onto the market's empirical distribution, then the INCUMBENT's alpha thresholds unchanged | incumbent's +-400 / +-900 |
| C3 | C1 within position group | weak 0.15, strong 0.30 |
| N0 | NULL baseline: score = -(market level). Any method that cannot beat "cheap things rise" has not found a fundamental signal | n/a |

C1/C3 label balance is a property of percentile construction, NOT evidence. Balanced
charts are never a pass criterion.

**Outcome (point-in-time, no leakage).** Origins are archived contract exports
(`exports/archive`, 2026-07-14 .. 2026-11-08). At each origin the fundamental is the
engine run on that origin's contract with the SAME frozen reconstructed baseline
(built only from completed seasons <= 2025 realised scoring plus draft-slot priors; no
2026 actuals are passed, so no outcome after the origin enters the fundamental) and the
market is that origin's value-signal anchor. Outcome = relative change of the SAME
asset's market value from origin to origin + H days, minus the cross-sectional median
change at that origin (removes board-wide drift). Pairs whose market source key differs
between the two dates are dropped (a source change is not a repricing).

**Primary horizon H = 14 days, origins spaced 14 days apart** (non-overlapping, so
origins are as independent as the calendar allows). Secondary (descriptive only):
H = 28 days, weekly origins (overlapping).

**Pass criteria** (all must hold, challenger vs incumbent, primary horizon):

- P1 mean per-origin Spearman IC >= 0.05, and exceeds BOTH the incumbent's and N0's mean IC by >= 0.02.
- P2 pooled SELL-class hit rate P(excess < 0 | sell) exceeds the unconditional down-rate by >= 5 percentage points; same for BUY with up.
- P3 IC > 0 in >= 70% of origins.

**Sufficiency rule.** The archive spans about 17 weeks of ONE NFL season: at most 8
non-overlapping 14-day windows, one regime, one in-season market. This can only be a
SCREEN. A pass authorises a longer preregistered study; it never authorises changing a
threshold or a served label (champion != challenger; model evaluation != promotion).
If fewer than 6 usable origins exist the verdict is INSUFFICIENT and no challenger is
ranked.

**Known limitation declared up front.** The fundamentals here come from the
reconstructed realised-points baseline (every record `is_proxy`), run locally without the
play-by-play supplement (nflverse PBP returned HTTP 504) and without the production real
sources (Mike Clay). Reception-band scoring (about two thirds of reception points on the
league card) is therefore unscored for WR/RB/TE locally, which depresses those fundamentals
relative to production. Absolute magnitudes below are a local reproduction, not the
production board.

## 1. Reproduction

Pinned input: committed `exports/latest/dynasty_data_2026-11-08.json` -> `build_api_data_contract`
-> `run_valuation(dynasty_main)` with a baseline rebuilt from nflverse (2,011 proxy records plus
197 rookie draft-slot priors). Production `/api/bdvm/values` needs auth and no BDVM snapshot is
committed (`data/` is gitignored), so this is a **local reproduction**, not the production board.

| | value |
|---|---|
| priced players with a market anchor | 794 |
| STRONG_SELL / HOLD / BUY / SELL / STRONG_BUY | 638 / 94 / 22 / 20 / 20 (80.4% STRONG_SELL) |
| earlier production audit | ~570 of 676 (84%), same shape |
| projection source | 100% `reconstructedBaseline` or `rookieDraftSlotPrior`; **100% `is_proxy`**, sourceCount 1 |
| liquidity | median 0.97, all measured; the liquidity factor is not a cause |

Across 17 weekly origins (Jul 14 - Nov 3) the census is stable (e.g. 639 STRONG_SELL at Nov 3):
the saturation is structural, not a one-day artefact.

## 2. Ranked causes (local reproduction, newest origin 2026-11-03, n = 795)

1. **Scale / curve-shape mismatch between the two sides of `gap` (dominant).** Both are nominally
   0-10000 and the fundamental is anchored so its single top asset prints 9800, but the
   distributions are not the same shape. Quantiles fundamental vs market: p10 46 vs 790, p25 182
   vs 1227, p50 544 vs 1911, p75 1256 vs 2967, p90 2504 vs 4643, p99 5644 vs 7905, a
   matched-quantile ratio of 0.06, 0.15, 0.28, 0.42, 0.54, 0.71. Sum of fundamental is 42% of
   sum of market. Median gap is about -1,200; **62.5% of players have gap < -900** (the STRONG_SELL
   bar) and only 11.4% sit inside the +-400 hold band. Removing ONLY this level/shape difference
   (challenger C2: quantile-match the fundamental onto the market's distribution, incumbent
   thresholds unchanged) moves STRONG_SELL from 639 to 144 (18%) and relabels 630 of 795, so
   roughly 495 of the 639 STRONG_SELLs are produced by the scale difference alone.
2. **Single-point anchor.** `calibrate()` pins each strategy's MAX asset to 9800 and raises the rest
   to gamma = 1.2. The top asset is Drake Maye (QB, 24.5 fpg, 9800) with the next at 7695, so one
   projection sets the unit for the board; the 1.2 power then compresses the mid-pool (p50 ratio
   0.28). Methodology observation, not a defect: it is what the owner-protected params say.
3. **Position-level level shifts.** Sum-of-fundamental / sum-of-market by group: LB 0.21, WR 0.29,
   RB 0.37, TE 0.50, QB 0.63, DL 0.67, DB 0.68 (STRONG_SELL 150 of 160 LBs). IDP retail prices
   carry far more value per fantasy point than the league's replacement-adjusted fundamental
   gives LBs. Partly genuine model/market disagreement, partly cause 1.
4. **Genuine disagreement exists but is moderate.** Spearman(fundamental, market) = 0.53 overall
   (WR 0.77, RB 0.76, LB 0.59, DB 0.42). Order agrees far more than level, which is what a scale
   problem rather than an information problem looks like.
5. **Thresholds are absolute alpha units.** +-400 / +-900 against a median gap near -1,200 are the
   wrong instrument whatever their origin; no repo evidence shows they were derived from this
   distribution. No evidence they were copied from another one either.
6. **Proxy / stale inputs: cannot be separated locally.** 100% of rows are proxy (share among
   STRONG_SELL 1.0 vs others 1.0, no contrast). The local build also lacked the play-by-play
   supplement (nflverse PBP HTTP 504), leaving reception bands unscored for WR/RB/TE. That is NOT
   the main driver: QB and LB/DB (no reception bands) show sum ratios 0.63 / 0.21 / 0.68, spanning
   the same range as WR/RB/TE (0.29 / 0.37 / 0.50). In-season actuals were not applied. Real
   sources (Mike Clay) could change rows but not a board-wide level.
7. **Formula defect: none found.** gap = fundamental balanced - market, alpha = gap x liquidity
   (median 0.97), thresholds applied in magnitude order; the served ladder is reproduced exactly
   (pinned by test). Source selection: offense uses `ktcCrowdTradesSfTep` (all but 4 rows), IDP
   `idpTradeCalc`; consistent. No bias found.

## 3. Challenger screen (preregistered section 0)

Evidence: `evidence/signal_screen_2026-11-08.json` (8 non-overlapping 14-day origins, about 780
pairs each; 13 weekly 28-day origins as a descriptive secondary). Hit rates are strict
(excess < 0 / > 0): many assets do not reprice in 14 days, so base rates are low (down 15.2%,
up 12.2%).

| method | mean IC (14d) | origins IC>0 | SELL hit (base 15.2%) | BUY hit (base 12.2%) | P1 | P2 | P3 | verdict |
|---|---|---|---|---|---|---|---|---|
| C0 incumbent | -0.018 | 3/8 | 14.2% (n 5114) | 15.4% (n 266) | - | - | - | reference |
| N0 level-only null | -0.016 | 4/8 | - | - | - | - | - | null |
| C1 percentile gap | -0.020 | 3/8 | 11.3% | 18.1% | FAIL | FAIL | FAIL | **FAIL** |
| C2 scale-aligned, incumbent thresholds | -0.020 | 3/8 | 10.5% | 17.2% | FAIL | FAIL | FAIL | **FAIL** |
| C3 position-relative percentile gap | +0.033 | 6/8 | 18.0% | 13.7% | FAIL | FAIL | PASS | **FAIL** |

Reading:

- The incumbent's SELL hit rate (14.2%) is **below** the unconditional down-rate (15.2%): its
  5,114 sell-class observations carry no directional information at 14 days. It does not
  discriminate; it also does not demonstrably mislead (IC -0.018, indistinguishable from the
  null's -0.016).
- No challenger passes. C3 is the only one with a positive IC and a majority of positive origins
  (6/8; 12/13 at 28 days) but its mean IC (0.033) is below the 0.05 bar and its BUY hit rate is
  barely above base. It earns, at most, a longer preregistered look, not adoption.
- **Sufficiency.** One season, 8 independent windows, per-origin IC swinging from -0.18 to +0.10
  with the in-season market regime. The verdict is SCREENED, not validated: the outcome evidence
  cannot support re-tuning thresholds and none was tuned. Label counts that look better under
  C1/C2 (18% STRONG_SELL) are by construction and prove nothing.

## 4. Bugs

No plain defect found. Checked and cleared: signal ladder ordering (pinned), liquidity handling
(measured, never 0), unmeasured dispersion (0 unmeasured rows here), source selection. Known and
documented elsewhere: the `strong_buy_min_liquidity` gate is decorative for measured rows. No
strict-xfail test was written because there is no defect to name.

## 5. Decision brief (owner)

**Finding.** The saturation is mostly a **scale problem** in the gap, not 570 independent sell
opinions: fundamental and market share a nominal 0-10000 range but not a curve (fundamental median
is 28% of market, total 42%). Order agreement is decent (rho 0.53). Whether any version of the
signal PREDICTS price movement is **unproven**: neither the incumbent nor the scale-aligned
challengers show 14-day directional skill in this season's data.

**Options.**
1. Leave the served signal as is; keep the shipped label rewording ("Sell · large gap", #2150),
   which describes a level gap rather than advice. No risk.
2. Authorise a longer preregistered evaluation (full season plus offseason, real Clay and
   play-by-play inputs, C3 as lead challenger) before any threshold or alignment change.
3. Separately decide whether the single-max anchor and gamma = 1.2 (owner-protected params) are
   meant to put the fundamental at ~40% of market value; that, not thresholds, moves the label
   distribution.

**Recommendation.** Option 1 now, option 2 once real projection sources are present; do not tune
thresholds to balance the chart. Nothing in this PR changes any served behaviour.

## 6. Reproduce

`python scripts/evaluate_bdvm_signal.py --out result.json --baseline-cache base.pkl --panel-cache panel.pkl`
(network needed for the nflverse baseline; archives are committed). Tests:
`python -m pytest tests/bdvm/test_signal_diagnostics.py`.
