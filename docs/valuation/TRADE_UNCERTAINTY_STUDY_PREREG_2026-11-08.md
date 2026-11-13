# Trade Monte Carlo value-uncertainty study: preregistered analysis plan

**Date:** 2026-11-08. **Authority:** MD-107, owner directive 2026-11-08 Priority 12 (research only).
**Status:** committed before any evaluation outcome was computed. Nothing in this study changes `src/trade/monte_carlo.py`, any flag or any served value.

## 0. Disclosure of prior looks

* The 2026-08-05 study (`scripts/backtest_mc_band_width.py`, `docs/open-modeling-decisions.md` decision 4) measured the board's own movement on an April to July replay: p10-p90 half-width 3.57% (7d), 3.35% (14d), 8.31% (30d), with four bimodal outlier folds that were join-population artefacts. Those numbers are known to the author and are not redone. This study differs: it scores competing uncertainty MODELS out of sample, by date, with proper scoring rules, over a window that includes the 2026 season.
* The author ran one replay (2026-10-01) to learn the row schema and the per-date cost (about 5 s, 1,125 rows). No movement or coverage was computed.

## 1. Three questions, kept separate

| id | question | this study |
|---|---|---|
| Q1 | How uncertain is an asset's value over horizon h? | **Primary.** Sections 2 to 7 |
| Q2 | How uncertain is the sign of a trade's fairness verdict? | **Secondary, descriptive.** Section 8. Raw value sums, no Value Adjustment; a verdict-persistence measure, not a probability of anything |
| Q3 | Will a manager accept? | **Out of scope, not addressable.** Nothing here estimates it. A simulation win-fraction is never an acceptance probability |

## 2. Data and the truth being scored

* **Source of realized values: panel replay.** `src/consensus_edge/panel.py::panel_day` rebuilds each past date's raw payload and source CSVs from git, and `build_api_data_contract(payload, csv_root=...)` produces `rankDerivedValue`. Checked: `exports/archive` zips carry the raw scraper payload and CSVs only (no canonical board), and the as-served canonical history (`data/board_history.sqlite`, `data/rank_history.jsonl`, `data/temporal_ledger.sqlite`) is box-local and absent from this checkout, so an as-served canonical series cannot be used. The ledger's `source_value` lane (vendor numbers) is a different quantity and is not the target.
* **Consequence, stated up front:** the replay runs one fixed pipeline (worktree HEAD) over every date. Movement is input-driven only. Real as-served movement also included constant promotions, so replay movement UNDERSTATES true board movement, and a "flat band too wide" result is an upper bound on the excess. Genuine board methodology changes in the live window are therefore not testable here, and are neutralised by construction. This is a limitation of the study, not a property of the product. Also, replay runs without `data/scrape_state`, so freshness/health weighting is off (every source at base authority), constantly across dates.
* **Dates:** every date from `panel.available_dates()` through 2026-11-08 inclusive (2026-11-09 excluded as partial). One replay per calendar day.
* **Per row, per date, kept:** `playerId` (else `canonicalName::assetClass`) as key; `rankDerivedValue` (only if finite and > 0, else the asset is absent that day, never 0); `position`, `assetClass`, `age`, `rookie`, `marketDispersionCV` (null stays null), `sourceCount`.
* **Outcome:** `r = v(t+h) / v(t) - 1` for assets priced at both t and t+h. An asset priced at t but unpriced at t+h is counted in attrition and reported, never scored as a loss to zero. Because attrition could bias coverage, the report includes attrition rate by tier and position.
* **Horizons:** h in {7, 14, 28} days.

## 3. Candidate models

All models emit predictive quantiles of `r` for the 19 levels tau = 0.05, 0.10, ..., 0.95. Interval at level L is [q(0.5 - L/2), q(0.5 + L/2)].

| id | model | fitted from |
|---|---|---|
| M0 | Incumbent: flat +/-15% as `monte_carlo._triangular_draw` realizes it (p10 = -0.15, p50 = 0, p90 = +0.15, extended piecewise-linear tails). Its 50% interval is therefore +/-5.625% and its 80% interval +/-15% | nothing |
| M1 | Source dispersion per row: `sigma_i = k * marketDispersionCV_i`; quantiles = `sigma_i *` the empirical quantiles of `z = r / (marketDispersionCV)` over the training pairs. Rows with null or non-positive CV are **unavailable** for M1 (no imputation) | training pairs |
| M2 | Empirical conditional bands: quantiles of `r` from the training pairs in cell = (asset group, position, value tier, age bucket) with backoff | training pairs |
| M3 | Dispersion plus horizon: `sigma_i^2 = a * CV_i^2 + b * h`, `(a, b) >= 0` fitted by non-negative least squares of `r^2` on `(CV^2, h)` using all horizons in training; quantiles from the empirical quantiles of `r / sigma_i`. CV unavailable means M3 unavailable | training pairs |
| M4 | Pooled empirical (no conditioning), per horizon, as a reference for how much conditioning adds | training pairs |

* **Value tier** (by `v(t)`): [0,1000), [1000,2500), [2500,5000), [5000,7500), [7500,inf).
* **Age bucket:** rookie (`rookie` true), age <= 24, 25 to 28, >= 29, unknown. Picks use the single bucket "pick".
* **Asset group:** offense, idp, pick (as `monte_carlo.build_trade_player` defines it).
* **M2 backoff order** (first cell with training n >= floor wins): (group, position, tier, age) then (group, position, tier) then (group, tier) then (group) then pooled. The floor is **N_FLOOR = 300 training pairs from at least 8 distinct origin dates**. The share of evaluation pairs served by each backoff level is reported.
* Fixed hyperparameters, no tuning on evaluation data: the tiers, buckets, floor and quantile grid above.

## 4. Walk-forward protocol (no future board)

* Evaluation origins: E_START = 2026-06-15 through the last origin whose t+h is on or before 2026-11-08 and not excluded.
* Refit every 14 days at refit date R. The model used for an origin t in [R, R+14) is fitted ONLY on pairs (o, o+h) with o+h <= R (outcome known at R). Minimum training: 30 distinct origin dates, else that refit block is skipped and counted.
* The refit for horizon h uses pairs of that horizon. M3 uses all horizons with o+h <= R.
* Ties, ordering and quantile estimation use `numpy` linear interpolation (`method="linear"`), fixed in code and tested.

## 5. Breaks and exclusions (mechanical, input-based, set before looking at movement)

A date is flagged a BREAK date if any of:

1. the set of source CSV stems differs from the previous date's;
2. the count of priced rows differs from the previous date's by more than 10%;
3. the payload is carried forward by more than 3 days (payload date more than 3 days before the as-of date), since a stale board manufactures zero-movement pairs.

Any pair whose origin t or target t+h is a break date, or that spans a break date in (t, t+h], is **excluded from the primary analysis**. Exclusions are chosen on input-state changes only, never on the size of value moves, so wide-moving weeks are not removed. Every excluded date and its rule is listed in the evidence JSON and the report. A sensitivity run with no exclusions is also reported.

## 6. Metrics

All reported per model, per horizon, on the intersection of rows where **every compared model is available** (M1 and M3 need CV), plus a separate availability report (share of pairs with CV).

* **Coverage at 50% and 80%:** share of outcomes inside the central interval.
* **Mean width** of those intervals in return units (and the median).
* **Mean pinball loss over the 19 levels** (a CRPS approximation: `CRPS ~ 2 * mean_tau pinball`; the plain mean pinball is reported and used for comparison).
* **Calibration by value tier and by position (and asset group):** 50% and 80% coverage per stratum. A stratum is reported only with n >= 1,000 pairs from >= 10 distinct origin dates; smaller strata are listed as `below_floor`, not scored.
* **Season phase:** pre-season (origin before 2026-09-10) and in-season (origin on or after 2026-09-10), reported separately.
* **Inference:** the unit is the ORIGIN DATE. All assets on one date share common-mode movement, so rows are not independent. The 95% intervals come from a moving-block bootstrap over origin dates with block length L = h days (so overlapping horizons stay inside a block), 2,000 replicates, seeded. A sensitivity uses disjoint origins spaced h days apart. The effective sample is reported as `floor(eval_days / h)` disjoint blocks.
* **Floor for deciding a horizon:** a horizon is DECIDABLE only if the primary window has at least 8 disjoint blocks of h days. Otherwise results are shown and labelled inconclusive for that horizon.

## 7. Preregistered decision rule

A model PASSES at a decidable horizon only if ALL hold:

1. pooled 80% coverage point estimate in [0.75, 0.85] and 50% coverage in [0.45, 0.55];
2. the 95% bootstrap interval of 80% coverage lies inside [0.70, 0.90];
3. mean pinball loss is lower than M0's, with the 95% bootstrap interval of the paired difference (model minus M0) excluding zero;
4. mean pinball loss is not higher than M4's by more than its bootstrap interval (conditioning must not hurt versus pooled);
5. every reportable position and value-tier stratum has 80% coverage in [0.70, 0.90];
6. both season phases have pooled 80% coverage in [0.70, 0.90].

Verdict:

* **(a) a credible candidate** only if one model passes at every decidable horizon, and h = 7 and h = 14 are both decidable. It is then proposed to the owner as horizon-parameterised, offseason-and-early-season evidence, with numbers.
* **(b) none credible** if no model passes at any decidable horizon, or the best model fails criterion 1 or 2 at a decidable horizon with the interval confirming the miss. The product state is then an explicit uncertainty-unavailable contract, and the report proposes the exact additive field.
* **(c) inconclusive** if fewer than two horizons are decidable, or intervals are too wide to separate pass from fail. The report names what data would settle it.

A model that passes only on the replay is still labelled self-consistency evidence: it measures how much OUR board moves, not how wrong it is, and cannot capture common-mode error.

## 8. Secondary analysis Q2: verdict persistence (descriptive)

For each evaluation origin t and horizon h, sample 5,000 pseudo-trades (seeded) of shape 1v1, 2v1 and 2v2 from assets priced at both dates, side value = raw sum of `rankDerivedValue`, no Value Adjustment, no roster context. Record whether `sign(gap(t)) == sign(gap(t+h))` by bucket of `|gap| / max(sideA, sideB)` (bins 0-2%, 2-5%, 5-10%, 10-20%, 20%+). Reported with date-block bootstrap intervals. It answers "how stable is a raw-value fairness verdict against board movement", not "what is the chance a trade is good" and not acceptance. If a model passes Q1, the same pseudo-trades are used to show how often its band implies a verdict flip, but only if Q1 passes.

## 9. Deliverables and tests

* `scripts/research/trade_uncertainty_study.py` (metric functions pure and importable; replay behind a CLI).
* `tests/research/test_trade_uncertainty_metrics.py`: hand-computed pinball, coverage, width, interval-from-quantiles, incumbent quantile map, backoff selection, break detection, walk-forward leakage guard (a training pair never has o+h after the refit date), block bootstrap determinism.
* `docs/valuation/evidence/trade-uncertainty-2026-11-08/` (replay cache summary, results JSON).
* `docs/valuation/TRADE_UNCERTAINTY_STUDY_2026-11-08.md`.

Any deviation from this plan after outcomes are seen is labelled DEVIATION in the report with the reason.
