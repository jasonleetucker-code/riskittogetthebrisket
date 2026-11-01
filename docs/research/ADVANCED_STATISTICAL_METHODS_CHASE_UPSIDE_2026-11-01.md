# Chase Upside fantasy — ten advanced statistical principles and modeling approaches (2026-11-01)

**PRIMARY RESEARCH RECORD / AMATH-01 (re-scoped at owner correction).** This research is **exclusively for the fantasy football app** in jasonleetucker-code/riskittogetthebrisket. **Market Edge Lab, the prediction-market app, is OUT OF SCOPE**. Companion seven-pure-math screen at docs/research/ADVANCED_MATHEMATICS_FEASIBILITY_2026-11-01.md is secondary background, not the implementation priority. This is a *research and planning audit*, not implementation authorization, promotion, or a production verification. Never alter live scores, weights, dynasty prices, ranking, bids, waivers, trade recommendations, protected research experiments, feature flags or deployments on this directive alone.

**Repository basis checked:** README.md, docs/ARCHITECTURE.md, docs/MASTER_PRODUCT_PLAN.md, docs/EXECUTION_PLAN.md, docs/MATH_MODEL_CALIBRATION_POLICY_2026-08-15.md, docs/research/ADAPTIVE_LEARNING_2026-09-26.md, docs/projections/IDP_OPPORTUNITY_{CHALLENGERS_RESULTS,PROSPECTIVE_PREREGISTRATION}_2026-11-01.md, docs/waivers/IDP_STREAMING_BACKTEST_RESULTS_2026-10-29.md, docs/league-intelligence/{ROS_SCALE_CALIBRATION_RESULTS_2026-10-28,SIM_CALIBRATION_V3_RESULTS_2026-10-27}.md; actual code under src/ros/idp_opportunity, src/ros/projection_ensemble.py, src/ros/playoff_sim.py, src/waivers/streaming_solver.py, src/bdvm/survival.py, src/dfs/{optimizer,distributions,correlation}.py, src/trade/monte_carlo.py. GitHub connector inspection only, not shell-level runtime or production box inspection. Reconcile against latest main and active claims/PRs before future work.

## 1. Non-negotiable architecture and known evidence

1. The **source/market dynasty value** (canonical \`rankDerivedValue\`) is NOT player-week fantasy points, ROS value, win equity, or a calibrated trade-success probability. Do not retroactively rewrite the canonical market board. No competing valuation/scoring/lineup owner.
2. \`src.league_intel.scorer.score_stat_line\` alone scores forecasts for the actual league card. The 2026 \`dynasty_main\` lineup was independently checked as QB + SUPER_FLEX; RB×2, WR×3, FLEX×2 (RB/WR/TE), TE×2, K×1, DL×3, LB×3, DB×3; NO IDP-FLEX and NO TE premium. Obtain fresh actual league rules before each new study.
3. The November 1 IDP retrospective improves 2026 weeks 3–7 MAE versus **weak, unshrunk C0** by approximately 0.36–0.50 fantasy points/player-week across defensive groups. The increment mostly comes from **M2 snap-weighted partial pooling**, not injury/matchup sophistication. In some groups top-N hit rate was worse; no local true pre-kickoff provider archived snapshots for the retrospective. Therefore do NOT claim any advanced algorithm has demonstrated improvement or that PROV has been beaten.
4. \`docs/projections/IDP_OPPORTUNITY_PROSPECTIVE_PREREGISTRATION_2026-11-01.md\` freezes Week 9+ models S0/SNAP/OPP/ROLE/HYB and archived PROV comparison under protected rules. **Never insert these new methods into frozen evaluation or tune them from observed evaluation labels.** Create a separately preregistered sequential study only after safeguards.
5. Streaming backtest observed manager B +19.9 realized best-ball points/decision week in 2026 vs hold (6 weeks; CI [+10.1,+30.2]); extra IDP depth and injury-replacement effects confound causal attribution. Current optimization does NOT recover this manager effect automatically. No claim that streaming is causally superior.
6. ROS offense/IDP calibration discrepancies were found, but candidate ROS calibrators failed gates; V3 simulation challenger failed gates. Neither is authorized for promotion. \`src/trade/monte_carlo.py\` consensus-based draw win rate is NOT an empirical probability that a trade improves a real roster.
7. DFS implementation is explicitly OWNER_PAUSED in \`docs/dfs/DECISIONS.md\`; don't silently revive because a covariance/portfolio technique is interesting.
8. Source rights, freshness, independence and exact point-in-time histories are gates, not paperwork. Missing ≠ zero. Defensive true alignment, pass-rush win-rate and several role inputs remain unavailable in the 2026 retrospective. Availability/non-playing selection must be part of the target population if a fantasy recommendation needs pregame performance, not only conditional-on-played accuracy.

## 2. Ranked opportunity matrix: ten advanced statistical principles

**Ranking scores are subjective 0–100 research priorities, NOT predictive accuracy or likelihood of success.** We use (potential advantage 25 + plausibility/evidence 20 + data 15 + implementation feasibility 15 + strategy 10 + interpretability 10 + cost 5). Method name matches the user's ten item pairs, but **graduate-level model choice is never mandatory for a useful implementation**.

| Rank / owner principle and paired advanced method | Score / phase | Exact fantasy application and existing owner | Starting strong, cheap alternative; research-specific rejection condition |
|---|---|---|---|
| **1 Hierarchical inference / Bayesian nonparametric hierarchy + Gaussian processes** | **96 / P1** | \`src/ros/idp_opportunity\`: learn event-specific partially pooled defender rates; group by CB/S/LB/EDGE/DT, team and role; optionally position/age nonlinear career curves in \`src/bdvm/\` later. | **Start empirical-Bayes Gamma–Poisson/negative binomial and standard regularized age splines.** Current SNAP already demonstrates basic shrinkage. Escalate to GP only for verified nonlinear residual lift and enough multi-season samples. Reject if worse than S0/SNAP/PROV top-N/score. |
| **2 Nonstationarity / switching nonlinear state-space + Particle MCMC** | **94 / P1** | \`src/ros/idp_opportunity/features.py\`: per-player true snap/role state (full-time, rotational, injury replacement), transitions, snap-share and availability probabilities; future RB/WR usage only after verified adapters. | Start explicit recent-share + change-point/HMM with exact pre-week data; test prior ROLE vs HMM, no need for Particle MCMC initially. Reject if role improvements only appear using postgame injury reports or worse false-break rates. |
| **3 Distribution-free inference / adaptive or time-series conformal prediction** | **93 / P1** | \`src/ros/forecast_archive.py\`, \`src/league_intel/sim_calibration.py\`, projection evaluation: forecast intervals for weekly IDP, ROS and team points; compare actual interval coverage to promised coverage and recalibrate displays. | Compare rolling residual quantiles and empirical interval calibration against conformal variants. **Ordinary conformal finite-sample guarantee needs exchangeability**; within-player weekly drift violates it, so report empirical player/position/time coverages, interval width and sharpness separately. Reject if coverage only improves by uselessly huge intervals. |
| **4 Statistical decision theory / Wasserstein DRO** | **92 / P2** | \`src/waivers/streaming_solver.py\`, \`src/ros/lineup.py\`, private trade utility: minimize regrettable drops and FAAB costs while maximizing prospective lineup/season/championship outcomes, preserve NO ACTION and zero default dynasty-loss allowance. | Start Monte Carlo scenarios + bounded CVaR or robust minmax against existing exact solver; use full Wasserstein ambiguity balls only with a validated radius and enough independent PIT forecasts. Reject if added complexity yields no forward decision-value gain or violates protected assets. |
| **5 Selection/missingness / Bayesian selection + pattern-mixture** | **90 / P0/P1 foundation** | \`src/ros/idp_opportunity/leakage.py\`, source adapters and evaluation: separate missing provider projections, missing snap counts, DNP, late scratch and injured/partial role; model P(plays) and P(snaps | plays). | Start complete missingness ledger, missingness indicators, two-stage availability/conditional production and sensitivity bounds. Nonignorable missingness is generally **not identified from observed data alone**. Reject causal/precision claims without external assumptions; do not impute absent events as zeros. |
| **6 Multivariate dependence / dynamic vine copulas and conditional normalizing flows** | **87 / P2** | \`src/ros/playoff_sim.py\`, \`src/ros/game_day_sim.py\`, team/player scenario draws: QB-WR receiving correlation, opposing volume/game pace, defensive tackle opportunity, multi-defender competitions and game-environment shocks. DFS noted but remains paused. | Begin calibrated game-level latent-factor conditional sampling and regularized Gaussian/t copula for enough PIT cases. Conditional flows/vines only if heldout joint log-score, tail coverage and matchup decisions improve. Reject when positional marginals/football logic break or data too sparse. |
| **7 Bayesian inference / BMA with HMC/NUTS** | **85 / P2** | \`src/ros/projection_ensemble.py\`, \`src/bdvm/\`: model uncertainty about rookie roles, aging and provider reliability; variable independent-source pools and odds/intervals only if statistically calibrated. | Start simple hierarchical posterior updates and family-aware regularized stacking against verified independent PIT sources. **HMC/NUTS is a way to sample, not a proof of better prediction**; model averaging requires real alternate models/priors. Reject if runtime, mixing or posterior predictive checks fail or no lift vs simplest ensemble. |
| **8 Causal inference / structural causal models + DML/TMLE** | **81 / P3** | Research-only: did role promotions/blitz shifts/streaming *cause* later scoring changes, versus injuries, opponent and depth effects? Existing six-week single-manager result is not identified as a causal effect. | Start explicit causal DAG, treatment/outcome/time definition and pre-treatment variables, falsification and matched descriptive contrasts. DML/TMLE requires defensible identification/unconfoundedness or an alternative design and sufficient overlap. Reject causal language absent identifying data. |
| **9 High-dimensional inference / horseshoe structured sparsity** | **80 / P2/P3** | \`src/ros/idp_opportunity\` and QB/RB/WR source model research: hundreds of candidate context variables, remove spurious matchup/role interactions and identify stable signals. | First use elastic net, group lasso, stability selection and locked-fold feature ablation; horseshoe only if enough features/observations. Reject features that are unavailable PIT, post-outcome derived or unstable across seasons. |
| **10 Extreme value / hierarchical Bayesian EVT** | **65 / P3** | Extreme IDP splash/ceiling games, championship tail scenarios, unusually large weekly totals; NEVER invent certainty about rare 1-in-100 events from limited seasons. | First compare empirical/hurdle count distributions and calibrated simulation quantiles; GPD threshold diagnostics and hierarchical tails only with sufficient independent exceedances. Reject unstable shape estimates or erroneous zero-floor/negative scores. |

**Cross-cutting requirement:** good **source provenance, PIT training/evaluation, independent strong baselines and calibration** have higher value than exotic sampling machinery. The high scores for principles do not mean HMC/NUTS, GP, particle MCMC, vine copula, horseshoe or Wasserstein DRO should automatically be installed. The **first implementations should usually be simpler, scientifically strong representatives of those principles**.

## 3. Proposed end-to-end architecture (reuses existing modules)

\`\`\`
Licensed point-in-time league/source snapshots
  -> canonical identity + exact league scoring card + source ancestry
  -> availability/missingness layer (observed / unknown / DNP / scratched; no default zero)
  -> player-role state / prospective snaps (HMM/change point or simple ROLE)
  -> conditional count/rate models (partially pooled IDP, later offense)
  -> forecast distribution + joint scenario calibration (not canonical dynasty-market board)
  -> independent PIT scoring / calibration / coverage and decision replay
  -> EXISTING canonical exact lineup + roster/waiver/trade decision engines
  -> advisory output: value vs roster utility, uncertainty, reasons, NO TRANSACTION
\`\`\`

Each model publishes a typed artifact: \`domain=weekly_player_statline|weekly_points|ROS_points|dynasty_market_value|roster_utility|decision\`, \`trainingWindow\`, \`freezeTimestamp\`, \`cardFingerprint\`, \`provenance\`, \`sourceLineage\`, \`population\`, \`calibrated\`, \`promotionStatus\`, plus distribution and missingness flags. No weekly score may be treated as dynasty price or mere output simulation as a validated real win probability. Do not expose new model-derived numeric "chance" claims as calibrated until longitudinal evaluation passes.

## 4. Top-three research POCs with formulas, inputs and gates

### S1 — Hierarchical IDP event rates + missingness-aware exposure

**Hypothesis:** forecasted exposure and event-specific partial pooling beat independently frozen strong S0/SNAP/PROV without sacrificing top-N defensive starter selection.

For defender i, week t, stat k:
- \`A_it ~ Bernoulli(pi_it)\` for playing/availability; \`E_it | A_it=1\` is projected snaps, from an as-of share/role forecast.
- \`Y_itk | E_it,lambda_itk,phi_k ~ NegBin(mean=E_it*lambda_itk, dispersion=phi_k)\`, zero if truly inactive under exact target rules, **unknown** when source data missing.
- \`log(lambda_itk)=alpha_(position,k)+u_(i,k)+beta_k'X_(i,t)\` with \`u_(i,k)~N(0,tau_position,k^2)\`. Retain dependencies between overlapping event categories and canonical scorer semantics, not independently summing same event.

**Target:** an illustrative >=0.25 league-point/player-week improvement in future MAE vs the **strongest** S0/SNAP/PROV, proper-score improvement and no top-N/calibration degradation. This is a research gate to preregister later, NOT a achieved performance or an amendment to 2026 Week 9 study. Explore 2025 season separately; do not backfill postgame variables as forecasts. Evaluation includes all considered pregame players, including availability errors, in a separate unconditional target; earlier conditional-on-played tests remain clearly labeled. Inputs must be independently source-permitted and point-in-time. Software: existing Python/scipy/statsmodels; MCMC optional research environment only. Rough engineering 3–6 days after PIT capture verified, plus outcome horizon.

**Reject** if gain disappears against SNAP or genuine PROV, low-availability strata are unsupported, source attribution contaminated, role unavailable, extreme predictions explode or null-corrected clustered intervals do not support lift.

### S2 — Latent changing role: rotational -> three-down / injury replacement

**Hypothesis:** a transparent switching-role filter with as-of usage detects real role promotions and avoids chasing one-week false changes.

Let latent role \`Z_it in {rotation, full-time, temporary replacement}\` with transitions
\`Pr(Z_it=s | Z_i,t-1=r, X_i,t-1)=T_rs(X_i,t-1)\`.
Let observed pregame history snap shares \`O_i,t'<t\` arise under state-specific emissions \`p(O|Z)\`; forecast next-week role probability from past evidence only, and compute conditional expected snaps/variance.
Start 2-state regularized HMM and simple change-point threshold; add temporary state only if identifiable. Compare existing ROLE, 3-week average, last-week share and source forecasts on game-week grouped walk-forward tests. Explicitly evaluate stable/temporary promotions, late injury and label delay. Metric: role-probability Brier/log-loss, snap-share MAE, prospective point MAE, top-N hit and streaming ROI under zero dynasty-loss budget. Any Particle MCMC attempt is purely a heavier challenger after HMM fails demonstrably.
**Reject** if unseen injury reports are required or HMM overreacts, or performance is indistinguishable from a simple smoothing filter. Rough 3–5 days once PIT injury/source snapshots exist.

### S3 — Calibrated uncertainty and decision distributions

**Hypothesis:** empirical rolling residual calibration or adaptive conformal method makes 50%/80%/90% prediction intervals meaningfully reliable and appropriately sharp, improves action selection, and avoids unjustified simulated "win percentages."

Given frozen point forecast \`m_it\`, compute historical out-of-sample nonconformity \`r_it=|y_it−m_it|\` for **earlier games only**, preferably within adequate true-position/family strata; \`q_(1−alpha,t)\` is the historical quantile under a predeclared adaptive/window policy; interval \`[m_it−q, m_it+q]\` is a starting comparator, with nonnegative lower bound only where underlying points cannot be negative under that scoring category. Compare with distribution-based central intervals and asymmetric quantile methods (defensive outcomes often right-skewed).
**Do not claim exchangeability-based exact marginal guarantees for dependent, drifting NFL data.** Report empirical coverage by defensive subgroup, week, source, player tenure, and interval width; compare marginal CRPS/weighted interval score; evaluate calibrated decision regret and "too-wide-to-be-useful" rate. No retroactive calibration of frozen Week 9 predictions. Example acceptance: future 80% intervals have empirical coverage plausibly consistent with 80%, stable over multiple weeks/families, with narrower or no-worse width versus correct comparator; prespecify tolerance and power. Low-to-medium implementation cost, ~2–4 days plus genuine forward outcomes.

## 5. Remaining seven methods: evaluation contracts

- **Wasserstein DRO (decision theory):** candidate \`max_a inf_{Q: W(Q,P_hat)<=rho} E_Q[U(a,Y)]\`, subject to exact add/drop and FAAB constraints; tune radius rho on training-only decision regret; compare existing solver, mean-only, worst-case and CVaR, and NO TRANSACTION. Do not collapse dynasty price into weekly points. Use shadow replay before any live suggestion; robust advice is not evidence of a better outcome unless forward trials show gain.
- **Missingness/selection:** partition \`not_observed\`, \`not_permitted\`, \`identity_unknown\`, \`did_not_play\`, \`snap_unknown\`, \`late_scratch\`, \`valid_zero\`, \`postgame_revision\`; chart subgroup coverage and outcome-selection bias. For nonignorable missingness, publish plausible sensitivity intervals, not point certainty. Evaluate both forecast given played and unconditional pregame decision outcome.
- **Joint dependence:** compare conditional latent game factors, shrinkage covariance and Gaussian/t copula before vine copulas/flows; validate pairwise sign/strength, correlated scoring tails, proper multivariate energy/variogram scores and downstream championship probabilities; no independent-score sampling for shared game-state shocks. Keep separate from DFS pause.
- **Bayesian model averaging/HMC:** alternative model likelihoods and prior probabilities must be explicit; check posterior predictive diagnostics, source independence and chronology. Compare weighted family median/linear pool/stacking. Use Stan/PyMC in offline research only if simpler updates leave demonstrable value.
- **Causal DML/TMLE:** write causal identification DAG, intervention, pre-treatment covariates, ignorability/parallel trends/IV assumptions, overlap, negative controls, sensitivity to latent coordinator/injury changes. Never infer cause from manager B's observational retrospective. A failed identification design is a valuable *rejection*.
- **Horseshoe sparsity:** feature registry, pre-kickoff covariate availability/rights, proper nested rolling time splits, correlated feature grouping, negative controls, selected-feature stability and ablation; compare elastic-net and standard domain knowledge. Report predictive and decision lift, not just sparse coefficients.
- **Extreme value tails:** model player events with legitimate physical/statistical constraints; estimate exceedance count per subgroup, block dependence and threshold stability. If limited independent tail data or poor proper tail scoring, refuse to publish 99.9th percentiles as data-backed.

## 6. Sequencing and initial data work

**P0 — evidence architecture, no new model:** verify point-in-time pre-kickoff weekly provider archive on production if authorized, true-position and scoring card, observational population (all pregame candidates vs players who eventually played), missingness/rights, source lineage and stable replay history. Mirror only permitted data, and preserve label provenance. Restore no missing data using final stats. Continue frozen 2026 Week 9+ IDP study as is.

**P1 — low-cost, high-return modeling trials:** run S1 empirical Bayes partial pooling *without* GP/HMC; S2 two-state model vs ROLE; S3 rolling calibration vs adaptive conformal after sufficient labels. Each separately preregistered when eligible; only one published champion and one distinct shadow challenger; compare strongest of S0/SNAP/PROV and observed outcomes. Capture prospective decisions, not just model MAE. Keep nonplaying/missing separate.

**P2 — decision and joint distributions:** use marginal model distribution samples and correlated game scenarios through existing best-ball lineup/simulation and streaming solver; assess robust/cvar alternatives to current optimal legal solver. Bayesian weights and structured sparsity only if identified evidence gaps. Stop all proposals if simpler baseline dominates.

**P3 — high-research-cost:** causal policy studies, nonparametric GP, full HMC/NUTS, particle MCMC, advanced dynamic copulas/flows and EVT only when sample/rights/power/compute preconditions are demonstrated. These are not build commitments.

**No DFS implementation** until owner explicitly lifts its separate pause; no automated moves, Sleeper writes, real-money or paid source acquisition.

## 7. User experience: potential screens only if model is validated

- Player Profile: \`expected snaps\`, \`probability of role being full-time\`, forecast median/quantile range, exact league-scored points, \`what changed since last freeze\`, and source/coverage flags. Do not show role probability unless calibrated.
- Weekly IDP Streaming: expected points over holding, lower-tail scenario, safe drops, dynasty-loss budget (default zero), reasons, \`NO TRANSACTION\`; mark whether a gain is statistically demonstrated.
- Dynasty Trade Advisor: distinct \`market fairness\` versus \`roster utility\` and \`outcome uncertainty\`; no "62% likely to win trade" based solely on synthetic consensus bands.
- League Simulation/Power: probability estimates only with method/date/coverage qualification; protect owner-approved "experimental, uncalibrated" wording until promotion.
- Model Lab: champion/challenger evidence by position, source vintage, availability censoring, player-week error and forward decision regret, visible to site owner only if already permissioned. All new UI requires separate authorization and release gates.

## 8. Traceability, data sources, model code, and standards

| Proposal | Existing owner/related decision | Status and blocker |
|---|---|---|
| S1 hierarchical IDP rates | \`src/ros/idp_opportunity\`; #2039, MD-8 | research idea; strong SNAP and PROV prospective study protected; missing PIT source history |
| S2 dynamic role states | \`src/ros/idp_opportunity/features.py\`; existing ROLE | research idea; injury replacement proxy failed prior backtest; pre-week injury entitlement |
| S3 forecast calibration | \`src/ros/forecast_archive.py\`, \`src/league_intel/sim_calibration.py\`; existing adaptive learning | research idea; earlier sim V3 failed; true forecast vintages needed |
| S4 DRO / decisions | \`src/waivers/streaming_solver.py\`, exact lineup \`src/ros/lineup.py\`; MD-7/8 | research idea; existing solver already legal, empirical gain unproven |
| S5 missingness | \`src/ros/idp_opportunity/leakage.py\`; existing source owners | prerequisite audit; avoid "missing=0" and conditional-on-played censoring |
| S6 joint dependence | \`src/ros/playoff_sim.py\`, \`src/ros/game_day_sim.py\`; DFS paused | research idea; requires calibrated marginals and enough game clusters |
| S7 BMA | \`src/ros/projection_ensemble.py\`, \`src/bdvm/\`; C5 | research idea; independent PIT source families absent in local retrospective |
| S8 causality | streaming research / source analytics | speculative; unobserved confounding, short comparison horizon |
| S9 sparsity | IDP feature/projection owners | speculative; feature availability and nested evaluation first |
| S10 extreme tails | distribution/simulation owners; DFS paused | speculative; effective independent rare-event counts unknown |

**Primary external methodological references (not claims of site-level lift):**
- Stan HMC/NUTS reference: https://mc-stan.org/docs/reference-manual/mcmc.html
- Conformal calibration and exchangeability limits: https://journals.sagepub.com/doi/10.1177/25152459251380452
- Time-series split conformal theory (2026): https://proceedings.mlr.press/v313/barber26a.html
- Particle MCMC state-space methods: https://doi.org/10.1111/j.1467-9868.2009.00736.x
- DoubleML identification-first workflow: https://docs.doubleml.org/stable/workflow/workflow.html
- Normalizing flows research review: https://www.jmlr.org/papers/v22/19-1028.html
- Wasserstein DRO survey: https://doi.org/10.1287/educ.2019.0198
- 2026 Princeton published thesis abstract, position XGBoost/quantile benchmark (another scoring context, not comparable to Brisket scoring): https://theses-dissertations.princeton.edu/entities/publication/d6981488-f30c-47ce-8f06-b6c3e98f2578

**Review gates:** agent operating-system receipt; latest main and claims, source/rights inventory, pre-registered test with no protected leakage, independent review, exact-card semantics and typed domain, test suite/governance checks, separately authorized champion promotion, deployment rollback, outcome monitoring. No promise of improvement, no numerical claim without observed evidence, and no schema changes without approved owner.

## 9. Executive decision

Best *principle* now: **hierarchical inference/partial pooling**, especially for defensive event rates, with a **two-stage availability/missingness model** first. Most valuable *new complementary mechanism*: **dynamic latent role change**, which should be tested against ordinary smoothing and existing ROLE, not presumed useful. Fastest cross-cutting trust improvement once actual forecast vintages exist: **rolling calibration and honest prediction intervals**. Most consequential eventual decision application: **distributionally robust waiver and trade optimization**, but only after the inputs are empirically reliable. The fanciest named solvers/samplers (HMC/NUTS, GP, Particle MCMC, vine copulas, normalizing flows, regularized horseshoe, Wasserstein balls, hierarchical EVT) are **optional challengers**; complexity must be earned, not inherited from a list.

**Scope remains exclusively the Chase Upside fantasy site.**
