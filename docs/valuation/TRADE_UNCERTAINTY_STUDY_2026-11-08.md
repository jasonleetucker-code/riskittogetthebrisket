# Trade Monte Carlo value uncertainty: can the band be empirically justified?

**Date:** 2026-11-08. **Task:** MD-107 (owner directive 2026-11-08, Priority 12). Research only: no served behavior, flag or value changed.
**Plan:** [`TRADE_UNCERTAINTY_STUDY_PREREG_2026-11-08.md`](TRADE_UNCERTAINTY_STUDY_PREREG_2026-11-08.md), committed alone before any outcome was computed.
**Evidence:** `docs/valuation/evidence/trade-uncertainty-2026-11-08/results.json` (all numbers below), `replay_panel_2026-04-16_2026-11-08.zip` (the 207 replayed daily boards the analysis runs from).
**Reproduce:** `python scripts/research/trade_uncertainty_study.py collect --cache-dir <dir> [--shard i/n]` (about 40 min of replay), then `... analyze --cache-dir <dir> --out results.json` (about 2 min), or unzip the evidence archive into `<dir>` and run `analyze` only. Metric functions: `tests/research/test_trade_uncertainty_metrics.py` (18 hand-computed tests).

## Verdict: (b) none credible

**No candidate uncertainty model passed the preregistered rule at either decidable horizon (7 and 14 days), so the correct product state today is an explicit uncertainty-unavailable contract.** The exact additive field is in section 7. Three separate reasons, all measured:

1. **The incumbent flat band is not a p10/p90. It is far wider than anything the replay moved.** Labelled 80% interval, observed coverage **99.2%** at 7 days (95% CI 98.9 to 99.5) and **97.6%** at 14 days (96.2 to 98.5), at a mean 80% width of 30.0% of value. Replayed boards moved by far less (pooled empirical 80% interval about 3 to 4.5% wide at its trained width; section 4). This is the earlier 2026-08-05 finding (3.57% half-width) confirmed on a longer window that includes the season. It is **not** evidence that 15% is "right to shrink": see caveat A.
2. **Every empirical alternative under-covers out of sample.** At 7 days the best, source dispersion per row (M1), reaches 80% coverage 0.759 (CI 0.716 to 0.790) and 50% coverage 0.439. The conditional bands (M2) reach 0.689 and the dispersion-plus-horizon model (M3) 0.700. At 14 days: 0.685, 0.602, 0.653. Nothing sits in the preregistered [0.75, 0.85] / [0.45, 0.55] acceptance region on both levels.
3. **The shortfall is nonstationarity, not noise.** Trained on earlier dates, each model gets too narrow as the season approaches. In-season (origin on or after 2026-09-10) 7-day 80% coverage is M1 0.710, M2 0.608, M3 0.620, pooled M4 0.492, against 0.82, 0.78, 0.79, 0.65 pre-season. The pooled model's own 10th to 90th percentile of 7-day returns, re-estimated every 14 days, widens from [-1.5%, +1.1%] (fit 2026-06-29) to [-2.3%, +2.0%] (fit 2026-11-02). A fixed band fitted on history cannot track that.

A near miss is named, not promoted: **M1 (source dispersion)** passes the coverage-interval, beats-incumbent, beats-pooled and season-phase criteria in the no-exclusions sensitivity run at both horizons (section 5), and fails only the per-stratum criterion: tight-end rows over-cover (80% coverage 0.94-0.95) and the lowest value tier (under 1,000) under-covers (0.65-0.67). It also exists for **offense only** (43.6% of matched pairs; IDP and picks have no dispersion). Promoting it would need a new preregistered study with stratum handling fixed before the data are seen, plus IDP/pick coverage. This study does not claim it.

## 1. Questions kept separate

| id | question | status |
|---|---|---|
| Q1 | How uncertain is one asset's value over horizon h? | Answered: no calibrated band exists on this evidence |
| Q2 | How stable is a fairness verdict (raw-value gap sign) against board movement? | Descriptive only, section 6 |
| Q3 | Will a manager accept? | **Not addressable here.** Nothing in this study estimates it, and `winProbA` is a simulation fraction over an assumed band, never an acceptance probability |

## 2. Data, dates used and dates excluded

* **Truth series: panel replay.** `exports/archive` zips carry the raw scraper payload and CSVs only, with no canonical board. The as-served canonical history (`data/board_history.sqlite`, `rank_history.jsonl`, `temporal_ledger.sqlite`) is box-local and absent from this checkout, so as-served `rankDerivedValue` could not be used. Each date was rebuilt with `panel_day` + `build_api_data_contract(csv_root=...)` at worktree head `cf06d8480`.
* **Dates used:** every day from **2026-04-16 to 2026-11-08** (207 days, 0 collection failures; 2026-11-09 excluded as partial). 208 are available from `panel.available_dates()`.
* **Breaks (26 dates excluded under the preregistered input-based rules; pairs touching one, as origin, target or interior day, are dropped):**
  * source set changed (13 dates): 2026-04-17, 04-19, 04-20, 04-21, 04-27, 04-28, 05-13, 05-15, 07-21, 07-25, 08-20, 09-09, 09-24
  * priced rows moved by more than 10% (15 dates): 2026-04-24, 04-25, 04-27, 06-02, 06-03, 06-04, 06-05, 06-29, 07-01, 07-24, 07-25, 08-18, 08-19, 09-12, 09-13
  * stale payload more than 3 days: none triggered. (04-27 and 07-25 carry two reasons, so 26 distinct dates.)
  * Full list with reasons: `results.json` `breakDates` (26 distinct dates).
* **Walk-forward:** refit every 14 days, each fit uses only pairs whose target date is on or before the refit date. The 2026-06-15 refit was skipped (20 clean training dates, floor 30). Evaluation actually covers:

| horizon | evaluation origins | span | disjoint blocks | decidable (>= 8) |
|---|---|---|---|---|
| 7d | 81 | 2026-07-02 to 2026-11-01 | 17 | yes |
| 14d | 50 | 2026-07-02 to 2026-10-25 | 8 | yes (exactly at the floor) |
| 28d | **0** | none | none | **no** |

  **28 days produced no primary result.** After exclusions no clean 28-day training pair existed until the 2026-11-02 refit, and by then no origin had a target on or before 2026-11-08. The no-exclusions sensitivity run does evaluate 28 days (119 origins, 4 blocks, below the floor of 8) and is labelled inconclusive.
* **Attrition** (priced at the origin, unpriced at the target, not scored as a loss): 7d 1,867 of 79,605 (2.3%); 14d 2,477 of 49,520 (5.0%).

## 3. Models and what the incumbent actually is

| id | model |
|---|---|
| M0 | Incumbent flat 15%, realized through `monte_carlo._triangular_draw`. Its 50% interval is **+/-9.375%** (not the +/-5.625% the plan's text said; the code uses the simulator's own map, which is what the plan defines as the model, and a hand test pins 9.375%), its 80% interval +/-15% |
| M1 | Per-row source dispersion (`marketDispersionCV`), quantiles of return / CV from training pairs; unavailable where CV is null (never imputed) |
| M2 | Empirical conditional bands (asset group, position, value tier, age/rookie bucket) with backoff, floor 300 pairs from 8 dates |
| M3 | `sigma^2 = a CV^2 + b h` fitted by non-negative least squares, empirical z-quantiles |
| M4 | Pooled empirical per horizon (reference) |

M3's fitted `a` is **0.0 at every one of the 10 refits at 7 and 14 days**: once a horizon term is in, per-row dispersion carries no additional variance information, so M3 reduces to a horizon-scaled pooled model. M2 was served from the finest cell for 84% (7d) and 62% (14d) of pairs, 100% from some real cell, never the pooled fallback.

## 4. Primary results (breaks excluded, intersection of rows where every model is available, i.e. offense with CV)

Pairs: 33,883 (7d, 81 origins), 21,120 (14d, 50 origins). 95% intervals are moving-block bootstrap over origin dates (block = h days, 2,000 replicates); rows are not the independent unit.

**7 days**

| model | cov 50% | cov 80% (95% CI) | mean 80% width | mean pinball | pinball minus M0 (CI) |
|---|---|---|---|---|---|
| M0 incumbent | 0.976 | 0.992 (0.989, 0.995) | 0.300 | 0.01950 | n/a |
| M1 dispersion | 0.439 | 0.759 (0.716, 0.790) | 0.070 | 0.01021 | -0.00929 (-0.01030, -0.00811) |
| M2 conditional | 0.366 | 0.689 (0.620, 0.741) | 0.054 | 0.01026 | -0.00923 (-0.01038, -0.00789) |
| M3 disp+horizon | 0.379 | 0.700 (0.631, 0.753) | 0.049 | 0.01014 | -0.00936 (-0.01038, -0.00810) |
| M4 pooled | 0.172 | 0.565 (0.502, 0.615) | 0.033 | 0.01056 | -0.00894 (-0.01005, -0.00757) |

**14 days**

| model | cov 50% | cov 80% (95% CI) | mean 80% width | mean pinball | pinball minus M0 (CI) |
|---|---|---|---|---|---|
| M0 incumbent | 0.930 | 0.976 (0.962, 0.985) | 0.300 | 0.02128 | n/a |
| M1 dispersion | 0.382 | 0.685 (0.600, 0.732) | 0.089 | 0.01511 | -0.00617 (-0.00831, -0.00371) |
| M2 conditional | 0.304 | 0.602 (0.474, 0.666) | 0.070 | 0.01542 | -0.00586 (-0.00820, -0.00292) |
| M3 disp+horizon | 0.326 | 0.653 (0.516, 0.744) | 0.070 | 0.01509 | -0.00619 (-0.00837, -0.00347) |
| M4 pooled | 0.159 | 0.492 (0.373, 0.571) | 0.045 | 0.01579 | -0.00548 (-0.00785, -0.00246) |

Reading it: every empirical model has far lower pinball loss than the incumbent (the flat band is wasteful, not just wide), and M1 is slightly better than pooled (pinball minus M4 = -0.00035, CI -0.00056 to -0.00020 at 7d; -0.00069 at 14d). But that is sharpness, not calibration: none reaches nominal coverage.

**Calibration by stratum (80% coverage, 7d, n >= 1,000 and >= 10 dates).** M1: QB 0.754, RB 0.707, WR 0.715, **TE 0.942**; tiers 0: 0.677, 1: 0.742, 2: 0.796, 3: 0.734, 4: 0.879. Incumbent: every position and tier 0.94 to 1.00. Full tables for every model and horizon are in `results.json` (`primary.byHorizon.*.strata`); strata below the floor are listed as `below_floor` (14d tiers 0 and 4).

**Preregistered criteria that failed** (`decisionRule`): M1 at 7d fails criterion 1 (50% coverage 0.439 below 0.45) and 5 (TE, tier 0); M2, M3, M4 fail 1, 2, 5, 6; at 14d all four fail 1, 2, 5, 6.

## 5. Sensitivity and robustness

* **No exclusions** (breaks kept; evaluation from 2026-06-15): M1 80% coverage 0.792 (0.761, 0.820) at 7d and 0.770 (0.724, 0.803) at 14d, with 50% coverage 0.482 and 0.463, so M1 passes criteria 1 to 4 and 6 there, failing only criterion 5 (TE 0.954/0.945, tier 0 0.673/0.651). The same mechanical rule still gives **(b)** (`sensitivityDecisionRule`, added after the primary outcomes were seen, informational). Source-set changes and input jumps are real uncertainty that a user faces, so the preregistered exclusion removes some genuine variation; it did not change the verdict but it did move M1 from passing to failing the coverage criteria.
* **Disjoint origins** spaced h days apart (10 at 7d, 4 at 14d): M0 80% coverage 0.992 / 0.985; M1 0.763 / 0.735. Same picture, wider uncertainty.
* **Phase split** shown in section 0 point 3.
* **28 days, no exclusions:** M0 0.945, M1 0.724, M2 0.666, M3 0.657, M4 0.786 at 80%; 4 blocks, inconclusive.

## 6. Q2: verdict persistence (descriptive; not a probability of anything)

Pseudo-trades of shapes 1v1, 2v1, 2v2 sampled from assets priced at both dates (5,000 candidates per shape and origin, at most 1,000 kept per gap bin), side value = raw sum of `rankDerivedValue`, no Value Adjustment, no roster context. Share of trades whose gap sign is unchanged after h days, by gap as a fraction of the larger side (1v1; 2v1 and 2v2 are within a few points):

| gap | 0-2% | 2-5% | 5-10% | 10-20% | 20%+ |
|---|---|---|---|---|---|
| sign persists at 7d | 0.69 | 0.89 | 0.96 | 0.99 | 1.00 |
| sign persists at 14d | 0.61 | 0.81 | 0.92 | 0.97 | 1.00 |

Raw-value verdicts inside roughly 5% are not stable even at a week; beyond 10% they almost always are. This is how often the sign of a gap on THIS board survives the board's own movement; it ignores the Value Adjustment, roster fit and posture, and says nothing about whether either side is "right". The 28-day rows are not interpretable (17 origins, bootstrap block longer than the sample; intervals degenerate), so they are omitted here and flagged in the JSON. Because Q1 produced no passing model, the planned "how often a band implies a flip" comparison was not run.

## 7. Product proposal for (b): an explicit uncertainty-unavailable contract

For the owner to decide; nothing here is implemented. Proposed additive field on `SimResult.to_dict()` in `src/trade/monte_carlo.py` (no existing field removed or reworded):

```json
"valueUncertainty": {
  "state": "unavailable",
  "reason": "no_empirically_calibrated_band",
  "bandBasis": "assumed_flat_15pct",
  "horizonDays": null,
  "calibratedIntervals": null,
  "replayCheckOfAssumedBand": {
    "nominalCoverage": 0.8,
    "observedCoverage7d": 0.992,
    "observedCoverage14d": 0.976,
    "basis": "board_self_consistency_replay_2026-04-16_to_2026-11-08"
  },
  "evidence": "docs/valuation/TRADE_UNCERTAINTY_STUDY_2026-11-08.md"
}
```

`bandBasis` follows the existing `bandSources` tally (`assumed_flat_15pct` when any asset is `synthetic_flat_15pct`, `stamped_value_band_uncalibrated` when stamped, since no stamped band has been shown calibrated either). Consequences to wire in a later, owner-authorized change: the UI would stop describing the 10th/90th percentiles as measured, `winProbA` stays labelled a simulation fraction, and `valueUncertainty.state` flips only through a preregistered, owner-approved promotion. This is a contract statement, not a recommendation to narrow the band: see caveat A.

## 8. Caveats that bound every number above

* **A. The replay understates real movement, and the direction is easy to get backwards.** The replay runs one pipeline (worktree head) over every date, so movement is input-driven only; as-served movement also included constant promotions (methodology changes in the live window are neutralized by construction and cannot be tested here). Understated movement makes the flat 15% look more excessive than it is. A "too wide" finding is an upper bound on the excess; it does not authorize shrinking. A "too narrow" model finding (every empirical model under-covers) is the emphatic direction, because true movement is larger still.
* **B. Self-consistency, not accuracy.** This measures how much OUR board moves, not how wrong it is. Common-mode error (every source wrong together) is invisible to it.
* **C. Replay differs from live in one stated way:** no `data/scrape_state`, so freshness/health weighting is off (every source at base authority), constantly across dates.
* **D. Seasonality and regime.** The window spans offseason, preseason and about 8 in-season weeks, and coverage fell in-season for every empirical model. Eight weeks of in-season history is the thinnest part of the evidence.
* **E. Dispersion models are offense only.** IDP and picks have null `marketDispersionCV`; M2 covers them but under-covers (all-rows M2 80% coverage 0.659 at 7d, 0.591 at 14d).
* **F. Overlapping horizons and common-mode moves.** Pooled coverage is dominated by date-level shocks; effective sample size is the block count (17 and 8), which is why CIs are wide and 14 days is only just decidable.

## 9. Deviations from the preregistration

* **DEVIATION (text error):** the plan said the incumbent's 50% interval is +/-5.625%; it is +/-9.375% under the simulator's own map. The code was correct; the plan's arithmetic was not. Found by the hand-computed test.
* **DEVIATION (post hoc, informational):** `sensitivityDecisionRule` applies the rule to the no-exclusions run after primary outcomes were seen. The verdict uses the primary only.
* **DEVIATION (Q2 sampling):** at most 1,000 pseudo-trades kept per gap bin per origin; binds only the 20%+ bin.
* **Outcome of the plan's own floors:** the 28-day horizon was not decidable (section 2), and the 2026-06-15 refit was skipped.
* **Debug run on partial data:** before the full cache existed the script was run once on 85 dates only to check that it executes; its output was not read.

## 10. Verdict mapping and what would settle it

Verdict **(b)**. The decisive evidence is point 2 above at both decidable horizons. To move to (a) the following would be needed, none available now:

1. **A full as-served in-season history** (box-local `board_history` / ledger `canonical_board` lane), so the band is tested against the board users actually saw, including methodology promotions. The replay cannot supply it.
2. **At least 8 disjoint 28-day blocks outside breaks** (about 224 clean days) before 28-day claims; today 4.
3. **IDP and pick dispersion**, or an explicit statement that bands are offense-only.
4. **A new preregistered study of M1-type models with stratum handling fixed in advance** (TE and the lowest value tier are the measured failures), refit on a rolling recent window to address the in-season drift, evaluated on a locked later window.

Tests: `python -m pytest tests/research -q` (18 passed).
