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
