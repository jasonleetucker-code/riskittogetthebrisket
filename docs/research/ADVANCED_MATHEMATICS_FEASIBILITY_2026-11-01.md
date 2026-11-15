# Secondary pure-mathematics applicability screening — Chase Upside fantasy (2026-11-01)

**Status:** SECONDARY SCREENING ONLY; the owner clarified that the primary Chase Upside research is the [ten advanced statistical approaches](ADVANCED_STATISTICAL_METHODS_CHASE_UPSIDE_2026-11-01.md). **Market Edge is out of scope**. RESEARCH / PLANNING ONLY. No implementation authority, no champion promotion, no live-value, source-weight, flag, route, FAAB, DFS or production changes. This is a subordinate research specification indexed by docs/OWNER_REQUESTED_TODO.md and docs/MASTER_PRODUCT_PLAN.md; docs/EXECUTION_PLAN.md remains the sole implementation authorization. Numerical rankings below are **expert feasibility judgments, not observed model performance**.

**Repo inspected:** jasonleetucker-code/riskittogetthebrisket, main as observed 2026-11-01 (consult live main before any future work). No other application is in scope.

## I. Architecture and verified mathematical starting point

- Production-facing stack documented in README.md, CLAUDE.md and docs/ARCHITECTURE.md: Python 3.12 FastAPI, Next.js 15/React 19, Sleeper league settings, source registries, normalized identity and scores, multi-league scoped scoring. A code repository read is NOT a production-box health check.
- Canonical market board: src/api/data_contract.py; source provenance/independence and freshness; Hill percentile curves in src/canonical/player_valuation.py. Canonical dynasty market value must stay separate from league-adjusted points, forecast distributions, roster utility and trade decision outputs.
- Weekly/rest-of-season sources: src/ros/projection_ensemble.py, src/ros/sleeper_weekly_projections.py; src/league_intel/scorer.py is the sole scorer. BDVM includes src/bdvm/{survival,uncertainty,engine}.py. Its hazards and dispersions are modeled/assumption-based, not empirically validated merely because code exists.
- IDP opportunity research: src/ros/idp_opportunity/{features,model,evaluate,leakage,prospective}.py and preregistration/results dated 2026-11-01. Retrospective M5 versus unshrunk C0: CB -0.497, LB/S -0.440, EDGE/DT -0.362 points MAE per player-week in 2026 weeks 3-7. Crucially most of the lift comes from M2 snap-weighted partial pooling; injury term hurts; top-N often does not improve; strong shrunk S0 and archived provider PROV comparison still pending prospectively. **Do not represent this as evidence for topology or advanced opponent modeling.**
- Existing shadow prospectively frozen program: docs/projections/IDP_OPPORTUNITY_PROSPECTIVE_PREREGISTRATION_2026-11-01.md. Preserve parameters, freezes, outcome protocol and protected evaluation; do not inject new candidates into the frozen study post hoc.
- Streaming: src/waivers/{streaming,streaming_solver,streaming_backtest}.py; exact roster/lineup feasibility delegated to src/ros/lineup.py; dynasty protection separate from projected weekly points. The Oct 29 observational manager-B versus hold estimate: +19.9 realized 2026 best-ball points/week, 95% CI [+10.1,+30.2], only six weeks. Extra defensive depth and injury replacements confound causal attribution; existing optimizer does not recover the manager's benefit.
- ROS cross-family: docs/league-intelligence/ROS_SCALE_CALIBRATION_RESULTS_2026-10-28.md. Offense vs IDP scale misalignment verified; no challenger passed every preregistered gate, and no ROS/market-value promotion is approved. Simulation calibration V3 also failed its gates; do not repackage a failed challenger as production-ready.
- Trade: src/trade/monte_carlo.py draws consensus-value bands, explicitly not real-world trade-win probabilities. Its module documents synthetic front-end bands and absence of measured bands in a 2026-07-30 snapshot; reverify on live data before claiming improvement. No independent probabilistic evidence arises merely by repeatedly sampling consensus.
- DFS: src/dfs/optimizer.py already uses SciPy HiGHS MILP for projected-point-maximum legal lineups; src/dfs/distributions.py has joint sampling and src/dfs/portfolio_opt.py has simulation-based portfolio selection. **All further DFS implementation is OWNER_PAUSED (docs/dfs/DECISIONS.md, 2026-10-18).** This audit recommends research only.
- Critical actual league card in Oct 28 report: 12 teams, 21 starters (QB; SUPER_FLEX; RB x2; WR x3; FLEX x2 accepting RB/WR/TE; TE x2; K; DL x3; LB x3; DB x3); NO IDP flex or TE reception premium. Exact Sleeper/scorer card fingerprint sf1:9e51824690d091f9 at study date; recheck freshness before a later experiment.
- Readiness limitation: authenticated production weekly archive, true pre-kickoff provider captures, full defensively aligned tracking, historic source versions and some injury point-in-time fields were not available to this repository-only audit. No new empirical backtest was run.

## II. Seven original disciplines: verdict

| Discipline | Legitimate application | Evidence/data versus conventional alternative | Verdict |
|---|---|---|---|
| Arithmetic algebraic geometry | Polynomial identity and constraint consistency | No concrete advantage over canonical scoring, ordinary algebraic constraints, MILP or regression | REJECT |
| Higher category theory | Typed transformations between scoring profiles, source and model outputs | Ordinary schemas, types, versioned interfaces and property tests solve this more cheaply; no use case requires higher categories | REJECT (borrow compositional design only) |
| Algebraic topology | Persistent-homology descriptors for defender archetypes/role transitions | Plausible, but no 2026 defender alignment/pressure tracking and no incremental predictive evidence; PCA, GMM, HDBSCAN first | RESEARCH / LOW PRIORITY |
| Analytic number theory | No defensible application to roster search | Integer programming/combinatorics are different mathematical subjects; neither needs analytic prime-number theory here | REJECT |
| Partial differential equations | Hypothetical continuous market-value evolution | Discrete weekly observations, identifiable hazards and state-space processes make a PDE unjustified; unspecified PDE boundaries | REJECT |
| Set theory / mathematical logic | Invariants for exact league/lineup/roster constraints; SAT/SMT proof fixtures | Existing solver already enforces constraints; targeted formal counterexample generation could add safety, NOT predictive accuracy | PROTOTYPE TESTS |
| Differential geometry | Nonlinear archetype distances, parameter/manifold geometry | High-dimensional data poorly grounded; Euclidean standardized features, PCA/UMAP and simple embeddings are stronger first alternatives | RESEARCH / LOW PRIORITY |

Do not relabel practical constraint programming "advanced set theory"; do not claim Mapper or UMAP is automatically persistent homology; do not call feature interactions arithmetic geometry.

## III. Stronger neighboring fields

Highest applicability: empirical Bayes / hierarchical count models; multivariate calibration; decision theory with proper scoring rules; robust and stochastic optimization; mixed-integer programming; survival analysis / discrete hazards; sequential state-space models; hierarchical bootstraps; source dependence and correlated ensembles; structured validation/formal logic. Plausible conditional methods: copulas and multivariate dependence, optimal transport for distribution shifts, change-point models and game theory for manager behavior. Explainability and point-in-time evidence outrank extra sophistication.

Outside evidence (specific methods are documented; none proves lift on this site):
- Sabin, hierarchical Bayesian plus-minus model for American football, JQAS: https://www.degruyterbrill.com/document/doi/10.1515/jqas-2020-0033/html
- Nguyen, 2026 JRSS-A Bayesian multilevel NFL snap-timing model: https://doi.org/10.1093/jrsssa/qnaf185
- Becker and Sun, fantasy football draft/lineup mixed-integer optimization, JQAS 2016: https://doi.org/10.1515/jqas-2013-0009
- Beal et al, NFL DFS mixed-integer optimization, 2020: https://doi.org/10.2478/ijcss-2020-0008
- Mlčoch, 2024 generative DFS joint outcomes and portfolio optimization: https://doi.org/10.1111/itor.13344
- Muniz and Flamand, player archetypes/analytics review including topological approaches, 2022: https://doi.org/10.3233/JSA-220584
- Xu and Fong, football scouting TDA, 2025 *preprint* (association football, not proof for NFL IDP): https://doi.org/10.21203/rs.3.rs-7756175/v1
- Wiseman, persistent homology of NBA lineup usage (different sport/outcome), 2025: https://doi.org/10.1177/22150218251324877

## IV–V. Opportunity matrix and TOP TEN (100-point rubric)

Scoring order: competitive advantage /25 + evidence /20 + data /15 + feasibility /15 + strategy /10 + interpretability /10 + efficiency /5. **Scores judge feasibility and importance, NOT measured effect or scientific confidence intervals.** Cost estimates are rough incremental research scales, not production estimates. Hypothesis thresholds are candidate gates that must be preregistered prospectively if selected; they do not amend existing studies.

| Rank | Technique, use and canonical owner | Score components = total | Current implementation, simpler comparator and mechanism | Data, cost, interpretability, evaluation hypothesis and verdict |
|---|---|---|---|---|
| 1 | Hierarchical count / opportunity IDP forecasts; src/ros/idp_opportunity | 24+19+13+13+10+9+4=92 | M2 empirical shrinkage is already effective; candidate learns partial pooling for stat-specific event rates and player/role exposure, versus current S0/SNAP/PROV | Historical scored stats/snaps available, PIT provider gaps; low–medium CPU for empirical Bayes, high for full MCMC; HIGH explanation. New independent forward test: improve strong S0/SNAP/PROV MAE by >=0.25 points/player-week, no worse top-N/coverage; PROTOTYPE, not promote |
| 2 | Robust multiweek streaming / stochastic integer search; src/waivers/streaming_solver | 24+17+12+13+10+9+4=89 | Already lineup-optimal deterministic add/drop; optimize uncertainty, capacity, FAAB, dynasty-loss and NO ACTION over scenarios versus current solver and simple rules | Week-by-week forecasts, roster and transactions; medium CPU; HIGH explanation. Forward replay: >=1 extra weekly realized lineup point vs strongest legal existing solver, no dynasty-loss-policy breach; PROTOTYPE |
| 3 | PIT source-independent calibrated projection ensemble; src/ros/projection_ensemble | 23+18+11+13+10+9+4=88 | Sources already combined; estimate errors/dependence, calibrated intervals and weights versus single provider/equal weights | Only verified pre-kickoff historical snapshots; collector entitlement and coverage gating; medium CPU; HIGH explanation. Require proper-score lift and no worse top-N under weekly clustered evaluation; PROTOTYPE after capture |
| 4 | League-scored ROS position/risk calibration; src/ros_calibration and src/league_intel | 23+16+12+12+9+8+4=84 | Existing calibration correctly detects offense/IDP mismatch but failed gates; compare replacement-aware positional scale against held ROS calibration | Week/season PIT outcomes and held cross-position gates; medium CPU; HIGH explanation; require predeclared improvement in cross-position ordering **and** lineup/sim noninferiority, respecting previous failed G3; RESEARCH / no promotion |
| 5 | Formal counterexample and constraint correctness tests; src/ros/lineup, src/waivers, src/trade | 18+18+14+13+7+9+3=82 | Existing exact lineups and MILP; find unsatisfiable edge cases/illegal suggestions via OR-Tools CP-SAT or Z3 on small synthetic leagues; alternative exhaustive enumeration | Current rules/fixtures sufficient; low–medium CPU; HIGH explanation; zero invalid recommendations/verified counterexamples versus independent oracle; PROTOTYPE test-only |
| 6 | Joint game/season probabilistic calibration; src/ros/playoff_sim and league_intel/sim_calibration | 22+16+11+12+9+7+4=81 | V3 already failed; compare position-level calibrated joint draws with fallback and strong simple distributions | More PIT and team-week samples necessary; medium CPU; MEDIUM explanation; future Brier/log-loss, CRPS and interval coverage with strict prereg gates; RESEARCH |
| 7 | Dynasty relevance and availability hazard calibration; src/bdvm/survival | 20+16+11+11+9+8+3=78 | Hazard priors already exist; estimate age/role/position conditional discrete-time hazards instead of assumed fixed multipliers | Multi-season roster/snap/availability labels and censoring; medium CPU; HIGH explanation; improve held-out log score/Brier and avoid unfair positional bias; RESEARCH |
| 8 | Causal/decision model for trade utility and market liquidity; src/trade/decision_engine, market_trades | 20+13+9+11+10+8+3=74 | Separate observed trade prices from counterfactual roster utility; compare expected points/win probability against consensus bands, not fake trade-win probabilities | Trade timestamps, roster state, offers and transaction selection bias; medium–high CPU; MEDIUM explanation; assess decision regret and calibration in prospective shadow; RESEARCH |
| 9 | Correlated decision-risk / portfolio optimization for waiver assets; src/trade/faab_engine, src/roster_intel | 19+13+10+11+8+8+3=72 | Scenario-robust ownership and FAAB risk versus deterministic marginal utility; avoid overlapping utility with #2 | Historical constraints and audited state necessary; medium CPU; HIGH explanation; forward shadow utility and drawdown; RESEARCH after #2 |
| 10 | Topological defender archetypes (persistent homology); isolated research in src/ros/idp_opportunity | 15+10+7+8+7+5+2=54 | No existing TDA; compare weighted standardized features with PCA/GMM/HDBSCAN; persistent features may characterize role shifts | Missing detailed alignments and low per-player sample; high research burden; LOW–MEDIUM explanation. Accept ONLY if stable archetype and incremental forward predictive/decision lift; speculative RESEARCH |

**Rejected strongest original-field alternative:** full topological data analysis is the most intellectually interesting but currently **lower priority** than empirical Bayes. No demonstrated NFL IDP benefit, critical alignment inputs missing and clear strong simpler comparators exist. Arithmetic geometry, analytic number theory, PDEs and higher categories have even poorer fit.

**DFS exception:** robust/copula DFS lineup portfolio work is mathematically plausible; the platform already has MILP, multivariate sampling and payout simulation. All further implementation is OWNER_PAUSED, so it is not a recommended active execution lane. Preserve DFS-specific roster constraints and zero-overlap research within that paused scope without implying approval.

## VI. Three controlled proof-of-concept experiments (new studies only, never amendments to frozen IDP protocol)

**E1 — Hierarchical IDP counts.** Hypothesis: player, true-position, role and team partially pooled event rates improve on strong S0/SNAP and genuinely captured PROV for starts/sits, not only naive C0. Exact card, pre-kickoff sources, and distinct weekly/ROS/dynasty evidence types. Construct fits only on weeks strictly before the predicted games, group by athlete + NFL week, nested model choice within past data, hold recent contiguous future weeks and set hypothesis/alpha before observing labels. Report coverage, MAE, CRPS, Spearman, per-position top-N, calibration, rate-of-missing and affected lineup points. **Stop** if improvement is not reproducible, top-N drops, false availability assumptions rise or PIT lineage fails. 2–5 engineer-days for small empirical-Bayes POC after verified input capture; full Bayesian extension separately costed.

**E2 — Robust streaming decisions.** Hypothesis: chance/risk-aware, scenario-based add/drop with exact eligibility, player protection and FAAB yields >1 additional true forward lineup point per week over current algorithm on the same reconstructible roster snapshots, without violating zero-default dynasty loss; require no-action baseline and uncertainty-aware negative control. Use weekly PIT forecasts plus archived rosters/transactions, include transaction costs and one-step and multiweek horizons; evaluate manager-independent fold, active/inactive, defensive-depth confounds and no look-ahead. **Stop** if deterministic solver matches gains, PIT insufficient or churn creates unapproved dynasty asset loss. 3–7 engineer-days after E1/forecast archive; no operational waiver writes.

**E3 — Topological archetypes (only after E1/E2).** Hypothesis: persistent-homology features improve held-out IDP role-change detection or top-N lineup decisions beyond standardized PCA + GMM/HDBSCAN and simple true-position/snap groups. Build anonymized player-week trajectories from ONLY pre-week features; use stable nearest-neighbor and bootstrap-stability tests across years. Compare ablation/no-topology model; measure silhouette/stability for descriptive use and incremental forward performance for predictive use. **Stop** if no delta vs ordinary clusters or input data missing; current classification is RESEARCH ONLY. 3–10 days if data exists, otherwise not feasible.

Power/sample-size and compute budgets for all studies must be estimated from observed PIT counts and variance BEFORE pre-registration. Existing six-week findings are not sufficient to assume transportability. Archived 2026 final statistics must not impersonate contemporaneous input snapshots.

## VII. Mathematical deep dive: hierarchical IDP count forecasting

For player i, week t, stat category k, let E_it be projected defensive snaps; y_itk the observed scored event count (solo tackles, assisted tackles, sacks, TFL, QB hits, passes defended, etc.; distinguish overlapping source keys). For event-count categories propose

y_itk | E_it, lambda_itk, phi_k ~ NegBin(mean=E_it * lambda_itk, dispersion=phi_k)

log(lambda_itk) = alpha_(position(i),k) + u_(i,k) + beta_k^T x_(i,t) + v_(team(i),k)

with partially pooled player effect u_(i,k) ~ Normal(0, tau_(position,k)^2). E_it comes from a separately PIT-trained availability/snap-share process; do not use actual target-week snaps as a forecast input. Use zero-inflation or separate Bernoulli hurdle only where genuine empirical residuals justify it. Injury and start probability require their own likelihood/labels. A candidate negative-binomial model must be compared against a regularized empirical-Bayes Poisson/Gamma, current SNAP and a strong source baseline; MCMC is OPTIONAL, not assumed superior. League-scored simulated total is g_card(y_it1,...,y_itK), calling canonical scorer with no duplicate points (e.g. TFL and sack treatment exactly as card/source semantics). Joint event dependence matters for distribution tails; estimate only with sufficient samples.

Plain English: first forecast how many snaps a defender is likely to play, then estimate tackles and rarer events per snap. Borrow sensible information from similar defenders when one player has limited history; give experienced players more of their own weight. Produce point ranges under the league's exact rules. Most of this already appears in simplified form in SNAP: prove that learning extra structure improves it before adding complexity.

For E2, let x_p be binary selected free agents, d_p binary dropped roster players, z_pwk simulated available starters, omega scenarios, L(R,omega) the exact best-ball score of legal roster R. Candidate decision:

maximize E_omega[sum_w gamma^(w-1){L(R(x,d),omega)-L(R0,omega)}] - lambda * CVaR_alpha(loss_omega) - mu * dynasty_loss(x,d) - transaction_cost(x,d)

subject to legal roster/lineup assignment, only available free agents, exact FAAB, at-most-one ownership, protection list, transaction-window and dynasty-loss budget. Existing solver and canonical lineup/calculation owners remain responsible; no parallel hidden scoring system. Compare simple scenario sampling and deterministic penalties first.

For E3 use standardized PIT defender-feature vectors, Vietoris–Rips persistence summaries across density scales, and only persistence features calculated on training observations. Establish stability to missingness/season drift and compare ordinary clusters; do NOT assert topological "holes" mean real position roles.

## VIII. Competitive differentiation and limitations

Hierarchical models are established in NFL research and are not novel by themselves (Sabin; Nguyen above). MILP in fantasy football is established (Becker/Sun, Beal); the differentiator would be exact two-TE, custom IDP, multi-year dynasty protection, source lineage and demonstrably better prospectively evaluated actions. Sports TDA exists in other leagues and association football but does NOT establish superiority for NFL defenders. The strongest credible product distinction is a PIT-audited, source-independent, league-scored weekly IDP decision engine that respects dynasty asset protection and can honestly recommend NO ACTION.

## IX. Roadmap routing and authority

- OWNER INTAKE: docs/OWNER_REQUESTED_TODO.md, add one new concise entry **AMATH-01** pointing to this full report. Do not duplicate pre-existing MD-4, MD-7/8, MD-17–25, prospectively frozen #2039, C5, IDP source/research, V3, BDVM, DFS pause or existing R-model ideas.
- CANONICAL FRONT DOOR: docs/MASTER_PRODUCT_PLAN.md, one pointer to this audit from the current plan, while respecting existing roadmap hierarchy.
- RESEARCH OWNER: src/ros/idp_opportunity for IDP forecasts; src/waivers/streaming_solver for weekly optimizer; src/ros/projection_ensemble for PIT ensemble; src/ros_calibration for ROS scale; src/ros/lineup and rule validation for formal invariants. Existing domain teams own all proposals; no new global mathematical engine.
- STATUS: feasibility review + PROPOSED POCs, not authorized implementation. Existing proof requirements govern promotion. No change to docs/EXECUTION_PLAN.md, feature flags, production weights, release gates, or frozen protocols.
- Roadmap acceptance: each future selected POC must have dataset/source permissions, independent PIT receipts, preregistered baseline and metrics, CI/coverage and independent review, evidence-to-decision trace, and a separate owner-approved promotion.

## X. Executive verdict

1. Advanced mathematics **is justified**, chiefly partially pooled event models, calibrated uncertainty, stochastic decisions and constraint proofs; not complexity for prestige.
2. Of the seven original fields, **mathematical logic/constraint systems** is the most immediately useful for correctness. **Algebraic topology** offers the most distinctive speculative research direction, not the best return.
3. Overall greatest near-term expected value: **hierarchical empirical Bayes for IDP opportunities combined with source-calibrated weekly forecasts**.
4. IDP projections: prioritize event-specific shrinkage and true-position opportunity, then PIT source benchmark; no speculative injury allocation without evidence.
5. Dynasty and trades: measured career relevance hazards, roster/scoring utility and source-market independence, not fictitious "probability that trade wins."
6. Waivers: exact multiweek risk-aware add/drop under dynasty protection, compared against the existing deterministic solver and doing nothing.
7. Mathematically impressive but unnecessary now: higher category theory, analytic number theory, PDEs and arithmetic algebraic geometry; topology unproven.
8. First unblock prospective, genuinely pre-kickoff IDP capture/evaluation; do not contaminate the frozen Week 9+ prospective study.
9. Avoid promotion after a weak naive baseline, duplicate ownership, postgame-as-forecast, correlated-source double counting, unauthorized paid data, paused DFS and unsupported causal claims.
10. Production needs predeclared decisive forward lift against strong incumbent, calibration/ranking/decision noninferiority, exact-card tests, source and privacy permission, robust deployment/rollback and explicit owner authorization. No such authorization is granted here.


## XI. Top-five implementation-ready *research* specification (not deployment authorization)

The following are **design hypotheses** for subsequent separately preregistered POCs. The “expected improvements” are *test gates*, not empirically measured forecasts; cost ranges are rough planning estimates excluding data licensing, infrastructure migration and reviewer time. For each: preserve existing owners, canonical scorer and value distinction; no new live routes until permissions and approval.

### AMATH-1 — Hierarchical IDP opportunity counts (92/100)

- **Specific method:** negative-binomial or overdispersed Poisson/Gamma partial-pooling counts with a separately forecast exposure/snap process; only add mixture/hurdle events if residual checks justify them.
- **User problem:** rank DL/LB/DB and predict volatile solo/assist/sack/TFL/PD lines under custom scoring without wild estimates after a small sample.
- **Evidence/baseline:** M2 snap-weighted shrinkage already drives most 2026 retrospective lift; competitor is strongest of frozen S0/SNAP/PROV, not weak C0. Formalize current model first as a probabilistic regression; added complexity only if reproducibly useful.
- **Equation:** Y_{itk} | E_{it},lambda_{itk},phi_k ~ NegBin(mu=E_{it}lambda_{itk}, dispersion=phi_k); log lambda_{itk} = alpha_{p(i),k} + b_{i,k} + beta_k^T X_{it} + c_{team(i),k}, where b_{i,k} ~ N(0,tau_{p(i),k}^2). Project E_{it} = planned team defensive snaps * availability_prob_{it} * conditional_snap_share_{it}; DO NOT substitute actual week-W snaps. Score simulated stat lines through canonical league scorer.
- **Input/capability:** Sleeper historical keyed IDP lines, team defensive snaps, injury status with **as-of** dates, true position, player/team identifiers, game times and card; verify legal data rights; per-defender pressure/alignment absent so exclude those covariates rather than fabricate.
- **Libraries/architecture:** optional research Python statsmodels/scipy with empirical Bayes and scipy special/optimize; PyMC/Bambi only if incremental accuracy justifies compile/MCMC overhead; own module under existing src/ros/idp_opportunity/, research runner mirrors existing leakage guards, output typed as weekly_opportunity SHADOW. No new point/scorer owner.
- **Evaluation:** walk-forward fit per week, nested hyperparameter selection on past games, 2025/2026 regime strata, player/team/week clustered uncertainty, proper log/CRPS score, MAE, bias, 80% interval coverage, top-36/position rankings and realized marginal lineup points. Pre-register minimum -0.25 fantasy points per player-week vs **strongest** baseline as an illustrative hurdle, not inherited protocol; require no degrading top-N.
- **Failure:** no clean PIT covariates, provider-source non-comparability, variance model degeneracy, simple SNAP equivalent, rank top-tail regression, overfit, inadequate out-of-season replication.
- **POC effort:** 2–5 research engineering days with verified input receipts, plus review and prospective outcome collection. Low/medium CPU for empirical Bayes; high/avoidable for full HMC.
- **Roadmap:** owner existing C5/IDP; further independent experiment only after frozen current prospective experiment completes/its scope is protected. No promotion.

### AMATH-2 — Multiweek risk-aware IDP streaming optimizer (89/100)

- **Specific method:** scenario-sampled stochastic mixed integer/matroid-like roster constraints with CVaR or robust lower-confidence objective, optimized using the **existing** roster/lineup owners and add/drop solver.
- **User problem:** manager's +19.9/week observed gains have not been matched by deterministic dynasty-safe optimizer; must decide add/drop or NO ACTION without losing valuable young defenders.
- **Baselines:** no action, legal best current deterministic streaming solver, greedy last-week, current projections with conservative protected releases; causal confounds require separate depth and replacement controls.
- **Equation:** a=(adds,drops), R_a= legal resulting roster; omega indexes jointly sampled future results. J(a)=Σ_w δ^(w−1) E_omega[L_w(R_a,omega)−L_w(R_0,omega)] − λ CVaR_q(negative utility across omega) − μ D_loss(a) − C_FAAB(a). Constraints: roster cardinality/cap, player exclusivity, candidate availability, waiver deadlines, owners' immutable-protection list, budget, positional slots incl QB superflex/TE2/IDP3/3/3, permitted dynasty-loss budget (zero default), and explicit no-transaction a=∅.
- **Inputs:** genuine pre-kickoff projected stat distributions by player and week, roster/scheduled games, user-specific protected players, positional rules/scoring, availability, FAAB history and remaining cap, marginal dynasty values separated from lineup points, ownership/transaction PIT.
- **Architecture/libs:** keep src/waivers/streaming_solver.py as only solver; import canonical lineup owner. Research-only scenario evaluation in isolated module; numpy/scipy (already dependency), existing MILP HiGHS for small exact models; OR-Tools CP-SAT could be challenger only if solver complexity merits new dependency. Use seed, scenario count, solve time and infeasibility receipts.
- **Evaluation:** forward decision replay with **same available transaction snapshot and predictions** across alternatives, not realized hindsight; compare realized lineup-point lift, false churn, no-action rate, protection violations, FAAB spent, portfolio deterioration, dynasty hold/release cost, runtime and convergence. Exploratory minimum +1.0 true lineup point/decision-week versus current solver, zero hard-rule violations and no increase in material avoidable drops.
- **Failure:** gain disappears when matched for defensive depth/injury replacements; solver not better than a simple safe policy; transaction history reconstruction non-PIT; infeasibility/performance; penalization overwhelms scores; insufficient sample.
- **POC effort:** 3–7 research engineering days after validated weekly distributions, plus season-long prospective testing. Medium bounded CPU; output explanations via primary contributor and why NO ACTION won.
- **Roadmap:** MD-7/8, existing streaming owner; not a second Perfect Waivers or global trade valuation.

### AMATH-3 — Source-independent distributional ensemble and calibration (88/100)

- **Method:** family-aware weighted probabilistic pooling, isotonic/logistic calibration where sufficient sample, regularized dependence-aware convex weights; quantile aggregation or mixture distributions explicitly, separate WEEKLY/ROS/DYNASTY horizons.
- **Problem:** multiple provider inputs may be stale/correlated (one vendor relays another), so simple consensus may double count and intervals may be too narrow.
- **Baselines:** latest permitted source alone; simple median/equal-family mean; existing src/ros/projection_ensemble.py; compare across distinct horizons, never pool IDP Show dynasty votes as weekly projections.
- **Equation:** F_hat(y|X)=Σ_f w_f F_f(y|X), w_f≥0, Σ_f w_f=1; optimize w over PIT historical folds using proper loss Σ_t CRPS(F_hat_t,y_t)+ηΣ_f(w_f−1/F)^2, grouping sources by proven dependence lineage; estimate calibrated 80% interval separately by family/time. Missing source ≠ zero; absent jointly point-in-time source means explicitly unavailable row.
- **Inputs:** signed/timestamped actual pre-kickoff provider stat distributions or statistical fields, source capability/terms, source ancestry graph, scorer card and game results, roster/league cutoffs; provider historical snapshots absent from local audit.
- **Architecture/libs:** existing source/lineage owners, src/ros/projection_ensemble.py, src/ros/projection_observations.py, scoring and leakage guards. Python numpy/scipy, optional scikit-learn for isotonic/regression only in new research dependency; do not silently install packages on production.
- **Evaluation:** 2025/2026 grouped walk-forward out-of-sample, point MAE, CRPS, log score, nominal interval coverage, top-IDP start selection, downstream waiver utility, source-family ablations and source outages; hypothesis better proper score with no >0.5-point player-week loss to strongest provider on major positional strata. Define a preregistered family and effective sample threshold first.
- **Failure:** true independent sources unavailable or entitlements disallow re-use; correlated vendors overwhelm effective sample; uncalibrated source forecasts; no improvement over median/single provider; drift.
- **POC effort:** 3–6 days once historic capture exists, plus long-running forward window. Low/medium CPU; high explainability via evidence family/version/weight table.
- **Roadmap:** existing C5 source and projection contracts; no new source vote or canonical value change.

### AMATH-4 — ROS position-scale / points distributions (84/100)

- **Method:** regularized hierarchical position calibration for predicted fantasy points per week and uncertainty conditioned on source horizon, distinct from canonical dynasty market price; calibration slope/offset and probabilistic residuals constrained against overfitting.
- **Problem:** top IDP ROS ranks carry incompatible scale relative to offense; study reports 2026 empirical disagreement, but failed preregistered cross-position and lineup gates.
- **Baselines:** current ROS fallback, no-conversion C0 and existing CR/CF preregistered studies; treat **G3 failed** and V3 not-for-promotion as real negative evidence.
- **Equation:** E[Y_{it}|r_{it},position p] = a_p + b_p r_{it}, with (a_p,b_p) partially pooled across positions; r_{it} is pre-week ROS signal, calibrated to league-card points; use suitable nonlinear monotone mapping only after heldout residual/ordering tests. Forecast S_it=Σ_j points_{ijt} with exact lineup solver, not raw sum of 0–100 ROS ranks.
- **Inputs:** PIT ROS board snapshots, actual player-week stat lines, scoring profile, exact 21-slot league roster, availability and season horizon; point-in-time 2025 league topology unresolved by prior report, so prioritize 2026 and fail closed on nonverified historical rules.
- **Architecture/libs:** reuse src/ros_calibration, src/league_intel/sim_calibration, src/ros/lineup; statsmodels/scipy optional, avoid new "global cross-position valuation" owner. Output shadow rosPointsPerWeek field only under existing owner-gated permission.
- **Evaluation:** preserve existing preregistered fail as immutable, any new test must use new held-out future games and independent preregistration; cross-position pair concordance, PIT calibration, lineup noninferiority, team ordering, family mean residuals and playoff simulation Brier/CRPS. **All** relevant noninferiority gates must pass; no owner promotion from a good mean alone.
- **Failure:** new candidate passes MAE but fails ordering, misattributes IDP slots or affects dynasty market values; insufficient prospective label count.
- **POC effort:** 3–8 days depending on missing PIT snapshots and heldout repeat; low/medium CPU, high explanation.
- **Roadmap:** MD-4 and existing ROS study; do not promote or re-run protected holdouts until approved.

### AMATH-5 — Formal logic, invariant tests and constraint counterexamples (82/100)

- **Method:** SAT/SMT or CP-SAT for small synthetic counterexamples, independent constraint proof fixtures; a *test-only checker*, not a new lineup optimizer.
- **Problem:** invalid recommended trades/waivers/lineups and scoring inconsistency under 21 unusual starters, positional flex, source-missing and roster/FAAB requirements.
- **Baselines:** existing independent pure-Python validator, existing exact DFS HiGHS ILP and small exhaustive-enumeration tests, canonical lineup and roster solver; add formal method only when it finds a missing class of counterexample.
- **Equation:** binary z_{i,s}∈{0,1} indicates player i occupies eligible starter slot s; Σ_i z_{i,s}≤1; Σ_s z_{i,s}≤1; z_{i,s}=0 if player not eligible; x_i owned-after, z_{i,s}≤x_i; Σ_i x_i≤roster cap; Σ_i FAAB_i ≤ B; score = Σ_{i,s} points_i z_{i,s}. For superflex enforce allowed QB/RB/WR/TE; for FLEX RB/WR/TE; for DL/LB/DB 3 each; no IDP FLEX or imaginary TE bonus. Separate manual versus best-ball semantics.
- **Inputs:** literal canonical scoring profile and roster eligibility cards, contract schemas and synthetic player pool; no NFL vendor data, no paid sources needed.
- **Architecture/libs:** tests only under tests/ with property-based Hypothesis (if approved), z3-solver or OR-Tools CP-SAT as OPTIONAL dev-only deps; compare brute-force enumeration on 2–10 player toy rosters and existing solver. Never replace scipy.optimize.milp/owner paths from a mere test.
- **Evaluation:** discover at least one new lawful counterexample vs prior validator or establish that all synthetic cases match; test contradictory ownership, missing scores vs zero, ineligible flex, multiple positions, remaining budget, unique assignment, transfer atomicity, no transaction, scoring cross-family leakage and infeasibility diagnostics. **Accept** test harness only when CI stable and it demonstrably strengthens coverage; no performance-lift claim.
- **Failure:** no additional bugs/invariants uncovered for added dependency complexity, solver too slow/flaky, conflict with current owners or mistaken interpretation of SAT feasibility as user benefit.
- **POC effort:** 1–4 days research/tests only, low/medium CPU; transparent counterexample report. Existing DFS pause respected.
- **Roadmap:** canonical rule owner and CI engineering; isolated tests under ordinary review, zero production behavior changes.

### Complete per-candidate matrix column coverage

For AMATH-1 through AMATH-5, the preceding five specifications explicitly record discipline/method, application, current implementation, mechanism, necessary inputs, simpler baseline, proposed minimum improvement (not achieved), external and internal evidence, complexity, computation, explainability, library/stack fit, evaluation, and verdict. For #6–#10, the top-ten table records feasibility and baseline while their **prototype-level designs remain unapproved research**; collecting full architecture details before source-data readiness would give false specificity.

**As-of and data-evidence caveat:** GitHub document/code inspection is **not** a production VPS audit; this review did not inspect authenticated caches or locally run packages/scripts, verify live source permission, execute forecasting experiments, or independently reproduce reported archived results. All quoted October/November performance is from the repository's existing study docs, not a new test by this audit. No citation/PR approval substitutes for new label-safe validation.
