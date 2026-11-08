# 07. Evaluation design

**Status:** design only, 2026-11-08. Nothing here has been run. Numeric thresholds are proposals to be frozen in a preregistration per study, committed before outcomes are seen, as the repo's own studies do (`docs/research/PLAYOFF_ROS_D11_PREREGISTRATION.md`, `docs/projections/IDP_OPPORTUNITY_PROSPECTIVE_PREREGISTRATION_2026-11-01.md`).

**Two separate questions, separate endpoints.** (1) Which forecast predicts best? (2) Which forecast produces better decisions? Lower error is never reported as better decisions.

## 1. Point-in-time datasets

| id | dataset | window | supports | limit |
|---|---|---|---|---|
| DS-A | nflverse PBP and weekly stats, frozen by file hash | 1999+ (2016+ practical) | In-house models vs simple baselines | No vendor forecasts. Stat revisions; pin hashes. Label defects (see DS-B) |
| DS-B | Sleeper host stat lines | Multi-season | Exact labels under the card | Offense plus IDP parity is exact on host-native path (`SCORING_PARITY_TAXONOMY_2026-11-08.md`) |
| DS-C | Archived RotoWire-via-Sleeper projections | **2026 week 8+** | Existing production projection baseline | One family; short |
| DS-D | Clay preseason snapshots | 2026 | Preseason baseline | One season |
| DS-E | ROS aggregate history | From 2026-04-28 | `rosValue` baseline | One season |
| DS-F | Canonical market archive | From 2026-07-14 (`HISTORY_FLOOR`) | Market baseline, short horizon | One season |
| DS-G | nflverse `spread_line`, `total_line` | Long | H-VOL tests | Timing unverified; must verify before PIT claim |
| DS-H | The Odds API history | Games 2020-06-06+, props 2023-05-03+ | True PIT market baseline | Paid; owner authorization |
| DS-I | DynastyProcess FantasyPros ECR archive | Depth unverified | External consensus **ranks** back in time | Rank-only; rights AMBER |
| DS-J | CFBD | Multi-decade | Rookie models | API key is owner-held |
| DS-K | Forecast and decision archives (`data/forecast_archive/`, Game Day generations, power and pick snapshots) | 2026 partial | Decision replay | Box-local |

**Honest limit.** Multi-season tests are possible against simple baselines only. A multi-season test against external consensus requires DS-H or DS-I. A true multi-family weekly test cannot exist before a second family has been archived for at least a full season.

## 2. Folds and holdouts

| stage | seasons | use | rule |
|---|---|---|---|
| Development | 2016-2022 | Feature and structure choice | Rolling origin by week |
| Validation | 2023-2024 | Compare frozen candidates | Rolling origin; one look per freeze |
| Locked test | 2025 | Used once per candidate family | Any re-use is declared and that test is no longer confirmatory |
| Prospective | First window after a commit-timestamped freeze | Confirmation | Minimum eight consecutive regular-season weeks; realistically 2027 |

**Protected:** the IDP prospective study is frozen. No model from this program may be fit, compared or tuned on its Week 9+ evaluation labels under that preregistration's name. Any new IDP arm is a separate study on separate weeks.

## 3. Baselines

Every challenger faces the full ladder, reported together. "Beats the baseline" means beats the strongest applicable rung. The repo learned this directly: the IDP study's lift was over an unshrunk mean, so it proved less than it appeared to.

| id | baseline | maps to the owner's list |
|---|---|---|
| B0 | Position mean | Reference |
| B1 | Prior-season per-game | Prior average |
| B2 | Trailing four-game mean | Recent average |
| **B3** | Shrunk trailing mean, `kappa` fitted on earlier seasons only | Strong simple baseline |
| B4 | Existing production: RotoWire weekly, Clay preseason, `rosValue / 2.7` for ROS, D0 dispersion | Existing production projections |
| B5 | Single external family or rank-derived consensus (DS-I) | External consensus |
| **B6** | Equal-family mean of all independent families | Equal-weight consensus; exists only when two or more families are live |

Team-level baselines are the trailing team mean with team and pooled spread, already defined in `TEAM_POINTS_CALIBRATION_RESULTS_2026-11-08.md`.

## 4. Metrics

| metric | definition | use | notes |
|---|---|---|---|
| MAE | `mean(abs(y - mu))` | Primary point metric | Weekly, by position |
| RMSE | `sqrt(mean (y - mu)^2)` | Secondary | Tail sensitivity |
| Bias | `mean(y - mu)` | Gate | Repo sign: realized minus predicted |
| Rank correlation | Within-position Spearman | Ordering | Never pooled across positions |
| Top-N hit | Share of the true top N named in the forecast top N | Ordering | Required: shrinkage can lower MAE while compressing the top `[R]` |
| Brier | `mean (p - z)^2` | Binary | Availability, hit, exceedance |
| Log loss | `-mean[z ln p + (1-z) ln(1-p)]` | Binary | Clip at 1e-6 |
| CRPS | `E abs(Y - y) - 0.5 * E abs(Y - Y')` | Distribution primary | Gneiting-Raftery 2007 |
| Interval coverage | Share within central 50, 80, 90% | Distribution | Use exact binomial acceptance regions (`src/model_registry/size_controlled_gates.py`) |
| Calibration slope | Regress realized on predicted | Scale | Target 1 |
| Energy / variogram score | Multivariate | Team and joint | Only for simulation |
| Decision utility | Section 8 | Primary for decisions | In league points or regret units |

**Population rules**

| rule | detail |
|---|---|
| Same players, same weeks | Every comparison uses the intersection set. Coverage is reported as its own metric |
| Two targets | Conditional on active, and unconditional including inactive |
| Missing is never zero | DNP and unprojected are counted, not scored 0 (`projection_scorecard.py` rules) |
| Scored by the pinned card | `sf1:9e51824690d091f9` for `dynasty_main`; PPR separately only for comparison with published results |
| Stat-level | Per-key error reported where both sides publish it |
| Strata | Position by starter tier; rookies; returning from injury; new team |

## 5. Inference and multiple-comparison control

| item | rule |
|---|---|
| Unit of resampling | Player clusters plus week blocks. A 12-cluster percentile bootstrap under-covers (`TEAM_POINTS_CALIBRATION_RESULTS` §2) |
| Time dependence | Weekly mean loss differentials with HAC standard errors (Diebold-Mariano) as a cross-check |
| Family-wise | Holm within each preregistered family; at most three challengers per family per cycle |
| Final selection | Model confidence set when more than two remain |
| Power | A power simulation on development seasons is mandatory before freezing a minimum effect. If 80% power is unreachable, the study is labelled a screen. The repo's Lane G found a needed effect above its minimum meaningful effect |
| Reporting | Every comparison run is reported, including failures. Rejected challengers stay on record (`docs/research/ADAPTIVE_LEARNING_2026-09-26.md` §30) |

## 6. Leakage controls

| risk | control |
|---|---|
| Feature from after kickoff | `knownAt < kickoff` enforced by assertion, not convention |
| Vendor update after the game | `lock_baseline_at_kickoff` |
| Revised stats in features | Pin file hashes; use the feed as it stood where the data allows |
| Injury status hindsight | Today's directory fields stripped (`TEAM_POINTS_CALIBRATION_RESULTS` §5 correction) |
| Team membership hindsight | Week-specific rosters only |
| Season-to-date totals including the target week | Lag every rolling feature by one game |
| Hyperparameter leakage | Tuned inside training folds only |
| Scaling on the full panel | Fit transforms within fold |
| Pooling across scoring cards | Rescore history under the pinned card, and state that card changes are ignored |
| Label contamination | Host-native labels where available; nflverse path otherwise, with the known defect list |
| Selection on survivors | Include players who vanish; treat as absent, not dropped |
| Feature rights | Inputs with unresolved rights excluded |
| Researcher degrees of freedom | Disclose earlier looks, as in `TEAM_POINTS_CALIBRATION_RESULTS` §5 |

## 7. Preregistered promotion criteria (proposed)

All must pass for any move from shadow. Passing grants only the right to ask the owner.

| gate | criterion | proposed threshold |
|---|---|---|
| PG1 Rights | Every training and serving input has a recorded permitted-use status | No RED or unresolved input |
| PG2 Reproducibility | Evaluation receipt with code SHA, source hashes, feature manifest, card fingerprint | `src/model_registry/reproducible_evaluation.py` accepts |
| PG3 Point accuracy | ΔMAE vs the best of B3 and (when it exists) B6; Holm-adjusted cluster-block interval excludes zero | At least 0.10 offense, 0.25 IDP league points per player-week |
| PG4 No position loss | No position significantly worse | Point estimate not worse than −0.10 |
| PG5 Bias | Absolute bias by position and starter tier | At most 0.25 points per game |
| PG6 Ordering | Within-position Spearman and top-N hit | Not lower than baseline by more than 0.01 and 0.02 |
| PG7 Distribution | CRPS better than D0; 80% coverage inside its exact acceptance region | Pooled coverage [0.75, 0.85]; no position outside [0.70, 0.90] |
| PG8 Decisions | Section 8 utility | Interval lower bound above 0 on the surface being changed; not negative on the others measured |
| PG9 Prospective | Same directions on a frozen forward window | At least eight regular-season weeks |
| PG10 Human | Owner approval through the model registry | Explicit record |

**Stop rule for the program.** If, after two full seasons of archived families, no in-house arm receives weight above equal-family consensus on means and none improves a decision metric, stop building point models. Keep the dispersion and availability work only if those passed on their own.

## 8. Downstream decision backtests

Each uses frozen forecasts and the existing exact solver. Hindsight runs are labelled and used only to bound what perfect information could add.

| decision | policies compared | unit | outcome | baseline | main confounder | minimum evidence |
|---|---|---|---|---|---|---|
| **Start/sit** (`dynasty_new`, start/sit league; `dynasty_main` is best ball and has no start/sit decision) | Rank by each forecast | Team-week | Points versus optimal hindsight lineup | RotoWire | Injury news after lock | Full season, both forecasts archived |
| **Waivers** | Rank free agents by mean vs exceedance | Add decision | Realized starter points added, net of drop cost | Hold / do nothing | Add choices are endogenous | Season-level; descriptive until power shown |
| **Trades** | Accept or decline at market fairness with vs without production context | Trade | 1-year roster points and later market value delta | Market only | Survivorship of accepted trades | Multi-year; report descriptively first |
| **Drafts** | Board by market vs hybrid | Pick | PAR at years 1-3 | Market price | Few drafts | Slow; multi-year |
| **Rookies** | Capital-only vs model | Rookie | PPG3, hit rate | Slot prior | Small classes | Pool several classes |
| **IDP streaming** | Mean vs exceedance vs shrunk | Team-week | Realized best-ball gain vs hold (`src/waivers/streaming_backtest.py`) | Hold; +0.4 optimizer vs +19.9 manager benchmark (`docs/waivers/IDP_STREAMING_GAP_DECOMPOSITION_2026-11-01.md`) | Manager effect; depth | Six weeks is not enough for causal claims |
| **Best ball** | Means D0 vs calibrated | Team-week | CRPS on realized best-ball score; lineup concordance | Trailing team mean | Bye weeks | Full season |
| **Dynasty** | Market vs market plus production/survival | Player-year | Startable status next year; value change | Market | Regime change | Multi-season |

**Decision utility definition.** Mean of `(realized outcome of action taken under forecast A) − (realized outcome under forecast B)`, in the units above, with paired bootstrap at the team-week or decision level. A probability displayed to a user requires its own reliability table before wording claims a chance.

## 9. Runnable now, without new data or spending

| study | data | note |
|---|---|---|
| Baseline ladder B0-B3 by position | DS-A, DS-B | Establishes the bar |
| Empirical `kappa` and `n0` | DS-A | Replaces unfitted priors in analysis only |
| H-VOL1 trailing vs lines | DS-A, DS-G after a timing check | Likely the largest cheap gain |
| Reception-band and first-down fill | DS-A | H4 hybrid |
| ROS source leave-one-out, dynasty-proxy removal | DS-E | Limited to one season |
| Scorecards | DS-C | Already scheduled |
