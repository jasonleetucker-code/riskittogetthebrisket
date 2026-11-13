# Package model q and fairness bands: out-of-sample validation plan (preregistered 2026-11-13)

**Status: PREREGISTRATION, research only.** Owner directive 2026-11-08, Priority 16 (Top 20 audit item 16,
"Validate package model q and fairness bands (OD-F4)"). Nothing here changes `geom_q078_v1` (q = 0.78),
`fairness_bands_v2` (3.5 / 9 / 18 %, floor 250), `config/trade/`, any flag or any served code.

This file is committed alone, before the evaluation script exists and before any trade in this study is priced.
The script and the result document must follow it. A deviation is recorded in the result document as a
deviation, never silently.

Agent-OS-Receipt: aa55ed12383caa257a25d28baa6612bc9577347d

## 0. What was already known before this plan

Disclosed so the plan cannot be tuned to it after the fact. All of it is committed aggregate evidence; none of it
is re-used as data here.

- Phase 3 production run (`docs/valuation/evidence/package_model_phase3_2026-10-20/production_phase3_run_2026-10-20.json`,
  18,690 graded trades, 11,565 leagues, trades through 2026-10-19): mean signed residual of q = 0.78 is
  −0.30 / −0.13 / −0.13 in the 1-for-2/3, ordinary and deep bins; q = 1 (raw sums) is −0.46 / −0.30 / −0.44.
- Same run, homogeneous geometric family: the calibration loss J falls monotonically as q falls, reaching its
  smallest value at the grid edge q = 0.50 (J 0.138). With a fixed per-piece level c ≈ 2,000 added, the best
  q is 0.85 (J 0.008), and the shape-only answer is attributed to a value-level effect (Phase 3 rule R1).
- Phase 3's holdout was **league-disjoint** (discovery / confirmation by a hash of the league), not
  date-blocked. No date-blocked out-of-sample fit of q exists, no asset-class (offense / IDP / pick) split of the
  residual exists, and `fairness_bands_v2` has never been evaluated on accepted market trades (OD-F4 is
  `PENDING` in `config/trade/fairness_bands.json`).

## 1. Questions

1. **Data.** What accepted-trade data exists locally and what exists only on the production box?
2. **q.** On format-comparable accepted trades, fit q on training folds blocked by date and compare, out of
   sample, q = 0.78, the fitted q and q = 1. Report residuals by package shape, asset class and value tier with
   bootstrap intervals clustered by league and date.
3. **Bands.** State the assumption any band check on accepted trades makes, then measure what can be measured
   under it.
4. **Concepts.** Keep market clearing, fair value and team utility distinct.

## 2. Three concepts this study keeps apart

| concept | what it is | where it lives | what this study does with it |
|---|---|---|---|
| **market clearing** | the exchange two managers actually accepted | the completed-trade ledger | the observation |
| **fair value** | the site's opinion of exchange value: canonical `rankDerivedValue`, combined by the package model, judged by the bands | `package_model`, `fairness_bands` | the model under test |
| **team utility** | what a trade is worth to one roster (lineup, roster spots, forced drops, posture) | the team-context lens of the trade engine | **not measured**; a cause of residuals, never a target |

The residual measures the gap between the model's fair value and market clearing. It is not a measure of
error in fair value unless the assumption in §7.1 holds.

## 3. Data

| label | what | where | role |
|---|---|---|---|
| **D-BOX** | the canonical market-trade ledger `data/market_trades/underlying_trades.sqlite` (KTC trade database lane, Sharp Sleeper lane, own-league lane), dated groups since 2026-07-01 | production box only (gitignored, box-local) | **decisive** |
| **D-EXPORT** | a byte copy of that SQLite file, opened read-only | wherever the owner places it (never in the repository) | same as D-BOX |
| **D-OWN** | `dynasty_main` completed trades in the tracked `data/sleeper_last_good.json` | tracked in the repository | pipeline demonstration; one league; **not decisive** |
| **D-SYN** | synthetic accepted trades generated from a known q | generated in process | tests and power analysis only; **never evidence about the market** |

Boards: the tracked `exports/archive/dynasty_export_*.zip` raw payloads, rebuilt with
`src.api.data_contract.build_api_data_contract` at the code of the run (Phase 3's documented caveat: "the board
at the time" is today's methodology applied to that day's source inputs).

## 4. Pricing and eligibility (fixed)

- Each trade is priced on the latest archived board whose date is **strictly before** the trade date and at
  most **7 days** before it. No board in that window: excluded and counted.
- Eligibility is the ledger owner's `market_trade_eval.residual_eligible`: proven-unique dedupe state,
  `dynastyState == "dynasty"`, verified superflex, two teams, no unresolved asset, no FAAB, no startup pick, no
  look-ahead. Unknown fails closed.
- Values are `market_trade_eval.BoardIndex.values(asset)["canonical"]`: `rankDerivedValue` for players and the
  one pick-value resolver for picks. Pricing is all-or-nothing per trade: an asset without a value excludes the
  trade. **Missing is never zero.**
- D-OWN only: player labels map to Sleeper ids through the snapshot's own `playerIds`; pick labels parse through
  `src.identity.picks.parse_pick_label`. The snapshot bakes "Mid" into every future pick whose slot is not known,
  so a tier label is priced at the **generic** grade (year, round), the grade `market_resolution` assigns to an
  unknown slot. A label that literally states a slot keeps the slot. D-OWN is one league in its own current
  format, so the format check is satisfied by construction; trades in an earlier season league are excluded by
  the board window.

**Format-comparability sensitivity (D-BOX).** The primary population is the `residual_eligible` population
(Phase 3's, so results are comparable). A sensitivity repeats the primary table on groups whose ledger
`targetPriceAuthority == 1` (NATIVE_COMPARABLE or VALIDATED_TRANSFORMABLE against `dynasty_main`), reported
only if it has at least 500 unequal-count trades.

## 5. Quantities

Values within a side are sorted best first. For a value vector `v` and weight `q`,
`U_q(v) = Σ_i q^(i-1) v_i` (the owner's `package_model.geom_utility`). `q = 1` is the plain sum.

- **Orientation.** A = the side receiving **fewer** pieces (the consolidating side), B the other. Piece count
  carries no value noise, so this orientation has no winner's curse. For equal-count trades the sign is
  arbitrary: their signed mean is not reported; their absolute residual is.
- **Residual** (the Phase 2/3 quantity, kept for comparability):
  `r_q = g / ((rawA + rawB + |(rawA − rawB) − g|) / 2)` with `g = U_q(A) − U_q(B)`. This is the gap divided by
  the mean of the two positive-only adjusted totals. Negative = the market gave the consolidating side more
  credit than the model does.
- **Band metric:** the owner's classification `fairness_bands.classify(g, fairness_base([U_q(A), U_q(B)]))`,
  i.e. `|g| / max(U)` against 3.5 / 9 / 18 % with the 250 floor. For `q ≠ 0.78` the same owner functions are
  called with that q's utilities; no band arithmetic is re-implemented.
- **Parity check.** At q = 0.78 the script's vectorized utilities must equal `package_model.geom_utility` on
  every row (|difference| < 1e-6), and its gap must equal `package_model.adjusted_pair_totals`' adjusted gap
  within the served rounding (|difference| ≤ 1). The result is stamped; a failure aborts the run.

**Strata (all fixed here):**

- **Shape** (the stud side, the side holding the single most valuable asset, first): `1v1`, `1v2` (the stud
  alone for two), `2v1` (the stud plus one for one), `2v2`, `3+` (either side has 3 or more pieces). For
  continuity the Phase 3 bins (`1vN_small`, `ordinary`, `deep`, `equal`) are reported too.
- **Asset class** (mutually exclusive): `offense_players_only` (no pick, no IDP player), `includes_idp` (any
  DL / LB / DB, any picks), `includes_picks_no_idp`.
- **Value tier** (Phase 3's noise-balanced level, the mean of both sides' best asset): `<2000`, `2000-3999`,
  `4000-5999`, `6000-7999`, `8000+`.

## 6. Fitting q out of sample (Q2)

- **Folds by date, never by row.** Trades are sorted by date and the distinct dates are cut into **K = 5**
  contiguous blocks of about equal trade count. A date is never split across blocks.
- **Forward chaining (primary).** Fold k = 2..5 fits on blocks 1..k−1 and is scored on block k. The pooled test
  set is blocks 2..5.
- **Models scored on every test row:** `M078` (q = 0.78, incumbent), `M100` (q = 1, no package adjustment),
  `MFIT` (the fold's fitted q).
- **Fit target.** `MFIT`'s q minimises the training mean of `r_q²` over **unequal-count** trades, on the grid
  q = 0.30, 0.31, …, 1.00. Equal-count trades are excluded from the fit target (a 1-for-1 does not depend on q);
  a secondary fit includes all multi-piece trades.
- **Secondary fit (moment).** The grid q whose training mean signed `r_q` over unequal-count trades is closest to
  0. Reported, not used for the primary decision.
- **Level diagnostic (not a package-formula candidate).** `VG_q,c = Σ q^(i-1) max(0, v_i − c)` with
  **c = 2,000 fixed** from Phase 3 (not refit). Its fitted q is reported to show how much of a low shape-only q
  is the level effect. `VG` is not homogeneous, so it can never be a package formula.
- **Full-sample q̂** (all blocks) with a bootstrap interval, plus each fold's q̂ for stability.

**Primary out-of-sample metric.** Pooled test-set mean `r²` over unequal-count trades (OOS MSE) for each model,
and the paired differences `MSE(M078) − MSE(MFIT)` and `MSE(M078) − MSE(M100)`.

**Secondary metrics.** Out-of-sample mean signed residual (unequal rows) and mean absolute residual (all rows) by
shape, asset class and value tier, for each model; the Phase 3 calibration loss J (worst unequal Phase 3 bin).

**Sensitivity.** The forward-chaining evaluation repeated on test rows from leagues that never appear in that
fold's training blocks (league-disjoint and date-forward at once).

## 7. Fairness bands (Q3)

### 7.1 The assumption, stated before any number

A band check on accepted trades assumes **A1: an accepted trade is, on average, a fair exchange at canonical
value**, so a band that labels it unfair is raising a false alarm. A1 can fail in two ways the data cannot tell
apart:

- **A2 (genuine lopsidedness):** accepted trades include real mistakes, information gaps, rebuild/contend
  context (team utility), and bargaining. Then the share of accepted trades a band calls not-fair is partly
  correct, and it is an **upper bound** on the band's false-alarm rate.
- **A3 (market convention):** the market systematically prices one shape differently from the site's fair
  value (for example a star premium). Then a shape-dependent gap is the market's convention, and calling it
  "unfair" may be the site being right. Completed trades cannot decide between A1 and A3 for a systematic
  effect; only outcomes (what the traded assets later produced) could.

So this study **evaluates what is evaluable without deciding A1 vs A3**: the shape-dependence of the labels and
their stability under q. It fits no cut point and proposes no replacement band value.

### 7.2 Measured

For q ∈ {0.78, full-sample q̂, 1.0}, on all eligible trades:

1. Share of accepted trades in each band level (fair / slight / unfair / lopsided) by shape, asset class and
   value tier.
2. **Direction:** among trades labelled not fair, the share where the label goes against the consolidating side
   (A receives less utility).
3. **Shape-neutrality:** the difference in not-fair share (and lopsided share) between each shape and `1v1`,
   with a clustered bootstrap interval. A 1-for-1 does not depend on q, so `1v1` is the reference noise level
   of accepted trades at the site's fair value; a band calibrated to that noise would label every shape alike
   under A1.
4. **Stability:** the share of trades whose band level changes when q moves from 0.78 to q̂ and to 1.0, by shape.

## 8. Intervals

- **Two-way cluster bootstrap by league and date** (pigeonhole bootstrap, Owen 2007): each replicate draws the
  leagues with replacement and, independently, the trade dates with replacement; a trade's weight is the
  product of its league's and its date's draw counts. It is mildly conservative for means under crossed
  league and date effects. A trade with no league id is its own league cluster.
- 1,000 replicates for means and differences; 300 replicates for the full-sample q̂ (each replicate refits q on
  the weighted sample). Percentile 95 % intervals. Fixed seed 20261113.
- A league-only cluster interval is reported beside the primary interval for the headline differences.

## 9. Decision rules (frozen)

- **R0, sufficiency.** D-BOX is decisive only with at least **2,000 unequal-count eligible trades**, at least
  **200 distinct leagues**, and every test fold holding at least **200 unequal-count trades**. Below that the
  result is **"insufficient data"** and no statement about q is made. D-OWN cannot meet R0.
- **R1, q.** If the 95 % interval of `MSE(M078) − MSE(MFIT)` lies above 0, the fitted q predicts accepted
  trades better out of sample; if it contains 0, there is no out-of-sample evidence against 0.78. The same rule
  compares 0.78 with q = 1.
- **R2, level.** If the shape-only q̂ is below 0.70 while the level-diagnostic q̂ (c = 2,000) lies in
  [0.70, 0.90], the low shape-only q is attributed to the value-level effect (as Phase 3 R1) and a change of q
  is **not** supported by this evidence alone, whatever R1 says.
- **R3, bands.** "Bands are shape-biased at q = 0.78" is recorded when the not-fair share of `1v2` or `3+`
  exceeds `1v1`'s by more than 10 percentage points with the interval excluding 0. This is a finding for the
  owner, never an automatic change.
- No rule changes q, a band, a config or a flag. Every option goes to the owner.

## 10. Outputs

- `scripts/research/package_model_validation.py`: modes `--box` (read-only guard, aggregates to stdout),
  `--ledger PATH` (an exported copy of the ledger), `--rows PATH` (priced rows), `--own-league`, `--power`
  (synthetic). Output is aggregate-only and checked for identifiers before it is printed or written.
- `tests/scripts/test_package_model_validation.py`: deterministic tests, including hand-computed utilities.
- `docs/valuation/evidence/package_model_validation_2026-11-13/results.json` and
  `docs/valuation/PACKAGE_MODEL_VALIDATION_2026-11-13.md`.
