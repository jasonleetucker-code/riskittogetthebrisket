# AMATH sitewide audit, lane FRONTIER: competitive research, pure maths, uncertainty UX, DFS lessons and product innovation (2026-11-01)

**Status.** This is research and planning only. It carries no implementation authority. `docs/EXECUTION_PLAN.md` remains the only implementation authorization, and a priority score here does not authorize anything. This lane changed no code, flag, value, source weight or frozen protocol. Nothing was scraped and no paid data was used. DFS stays **OWNER_PAUSED** (`docs/dfs/DECISIONS.md`, PR #1810); this document reads it only for reusable lessons. The IDP prospective preregistration and the ROS H1 preregistration are frozen, and nothing below changes them.

**Builds on, does not repeat.** PR #2053's two records are the baseline:

- `docs/research/ADVANCED_STATISTICAL_METHODS_CHASE_UPSIDE_2026-11-01.md`: the ten principles, IDP-heavy, with POCs S1–S3.
- `docs/research/ADVANCED_MATHEMATICS_FEASIBILITY_2026-11-01.md`: the seven pure-maths disciplines, plus POCs E1–E3.

Those records cover the per-domain IDP, waiver and ROS lanes in depth. This lane covers four cross-cutting questions:

1. Where each technique is already established outside this repo, and where competitors already ship it.
2. Whether #2053's pure-maths verdicts survive a challenge against the actual code.
3. How mathematical outputs should be shown to a user.
4. What new products would combine several principles.

**Evidence classes used throughout:**

- **DEMONSTRATED-IN-REPO**: a file is cited.
- **PUBLISHED-EXTERNAL**: a URL is cited.
- **PLAUSIBLE HYPOTHESIS**: reasoned but untested.
- **SPECULATION**: a guess, labelled as one.

No backtest numbers, percentage improvements or significance levels are invented anywhere in this document. The one numeric diagnostic is labelled with its exact command.

---

## 1. Domain inventory: cross-cutting systems that present or police mathematical output

Systems were inventoried by reading code and docstrings. They were not health-checked on the production box.

| # | System | Owner file::function | Status | Method | Constants and evidence | Missingness | Uncertainty | Validation | Consumers | Defects / risks |
|---|---|---|---|---|---|---|---|---|---|---|
| 1 | Row confidence gate | `src/api/confidence.py::assess_confidence` | live | Five axes (independence, coverage, freshness, applicability, agreement); overall = the weakest axis | 5 / 3 families come from the blend's own trim rungs (derived). The 75% shares and 15% agreement band in `config/confidence/gate_v1.json` are declared, evidence NONE beyond B11 distribution checks (`docs/master-site-audit/evidence/B11/`) | Eligible-family denominator, so a family that drops out is permanent missing evidence | Ordinal bucket only; no probability | Tests pin the invariants that deleting evidence never promotes a row and duplicate families raise | rankings, trade, edge, arbitrage, compare, Consensus Edge | A bucket is not calibrated against any outcome. It is evidence QUALITY, not forecast accuracy, and the UI must not imply it is accuracy |
| 2 | Uncalibrated-odds disclosure | `frontend/lib/odds-disclosure.js::ODDS_EXPERIMENTAL_DISCLOSURE`, `frontend/components/league/OddsExperimentalNote.jsx` | live | One owner-approved string (decision 9, MD-11) | Wording is owner-fixed | n/a | Binary: calibrated or not | `odds-experimental-disclosure.test.jsx` | ros-championship, ros-power, ros-trade-deadline sections | Correct and honest. It is the only "estimate" label in the app, and it covers only simulator odds (see UX §7) |
| 3 | Game Day weekly simulation | `src/ros/game_day_sim.py::simulate_league_week` + `src/league_intel/sim_calibration.py::PointsModel.draw_from_mean` | live | One league-wide Monte Carlo. Win Matchup % and Beat Median % come from the same draws, through the exact lineup solver | Per player: **independent truncated Gaussian**, `sd = max(0.5, mean*CV_pos)`. `FALLBACK_CV_BY_POSITION` (QB .32, RB .55, WR .60, TE .65, LB .45, DB .50 …) is used unless the box-local `data/league_intel/sim_points_model.json` exists. V3 challenger failed (`docs/league-intelligence/SIM_CALIBRATION_V3_RESULTS_2026-10-27.md`, `V3_DOES_NOT_BEAT_FALLBACK`) | `availability.py` four-state; unpriced players are excluded | MC only; **no teammate or opponent correlation**; symmetric marginal | Spec `docs/GAME_DAY_PROBABILITY_SPEC.md`; V3 gates failed; 12 team-weeks per holdout week | /game-day, league hub | Independence and a symmetric marginal are unvalidated assumptions (see finding F1). Truncation bias is small: diagnostic below |
| 4 | Playoff / title engine | `src/ros/playoff_sim.py::canonical_forecast` | live, labelled experimental | Season MC through the exact lineup solver; adaptive convergence with Wilson intervals; paired arms for trade hypotheticals | Same PointsModel; D2 ROS uplift multiplier (see that module's docstring) | availability layer | MC standard error is reported. Model uncertainty is NOT | `tests/ros/test_one_playoff_engine.py`; league-outcome calibration never run | public league routes, pick projector, trade arms | The MC interval is easy to misread as model confidence (UX §7, anti-pattern A3) |
| 5 | Trade Monte Carlo | `src/trade/monte_carlo.py` | live, labelled | Draws side totals from per-asset `valueBand` (p10/p50/p90) | **0 of 1093 rows carry a real band**. The UI synthesises a flat ±15% band (module docstring; `docs/open-modeling-decisions.md` #4) | n/a | `consensus_based_win_rate`, honestly labelled | Docstring disclosure and `bandSources` | /trade | A number with almost no information. Candidate for REMOVE/SIMPLIFY (R-row FR-04) |
| 6 | Archetype labels | `src/scoring/archetype_model.py::infer_archetype` | live (scoring adjustments) | Hand-coded threshold tree per position | `qb_rush_contribution>=0.22`, `goal_line_proxy>=0.45`, `field_stretcher_proxy>=13.5`, `splash_dependency>=1.2`, `tackle_dependency>=6.5` … **evidence NONE found** | Missing feature becomes `0.0` via `f.get(...,0.0)`, so a **missing feature silently selects the default archetype** | none | none found | `feature_engineering`, scoring adjustments | This is the real champion that #2053's TDA discussion skipped (§6.2). Missing → 0 conflicts with the MISSING IS NEVER ZERO invariant |
| 7 | Positional tiering | `src/scoring/tiering.py` | live | Sequential gap = \|tier mean − candidate\| / pool SD over a per-position threshold | Thresholds are declared priors (not checked further here) | n/a | none | unit tests | rankings tiers | Deterministic and interpretable. Gap thresholds are a candidate for an ordinary 1-D change-point / Jenks comparison (enhancement only) |
| 8 | Exact lineup solver | `src/ros/lineup.py::solve_optimal_assignment` | live | Exact assignment; AST test forbids a greedy fallback | n/a | `ros_value=None` is unassignable, distinct from 0.0 | n/a | **Seeded random rosters vs an independent brute force** (`tests/lineup/test_canonical_lineup.py::brute_force_best`); 10/10 vs Sleeper-awarded lineups (CLAUDE.md) | every sim, streaming, roster construction, trade impact | Already near-formal: an oracle-based randomized test. Fixed seeds and no shrinking (§6.3) |
| 9 | Roster capacity / forced drops | `src/trade/roster_capacity.py` | live | Counting + cut ladder; taxi bracketed as a range | 58 cap read from league | Unknown cap → `None`, never unlimited | Range (taxi min/max), `certainty` | Test pins agreement with `_check_legality` | finder, suggestions, simulate, angle | Hand-written invariants; good target for property tests |
| 10 | N-team trade ledger | `src/trade/trade_ledger.py`, `src/trade/analyze_service.py::analyze_trade_n` | flag OFF (`trade_multi_team_analysis`) | Routed ledger; fixed-order validation; conservation check | `config/trade/multi_team.json` | Unverifiable ownership is a separate state | n/a | Parity fixtures; `ConservationViolation` | /api/trade/analyze-multi | Conservation is an algebraic invariant, an ideal property-test target |
| 11 | Availability states | `src/ros/availability.py` | live | Four states: available / unavailable / uncertain / unknown | Rule-based | UNKNOWN IS NEVER AVAILABLE | categorical; **no probability** | tests | sims, lineup | `uncertain` carries no P(plays). That is the gap S1 (#2053) depends on |
| 12 | DFS joint outcomes | `src/dfs/distributions.py`, `src/dfs/correlation.py` | **OWNER_PAUSED** | Gaussian copula over each player's own marginal; correlation-matrix repair | `correlation.priors@1.0.0`: directions from game logic, magnitudes shrunk, **declared uncalibrated** | No spread → no distribution | Quantile marginals; copula | Backtest harness exists, not claimed | DFS only | Lesson L1: better dependence machinery than the live Game Day sim |
| 13 | DFS duplication | `src/dfs/duplication.py` | OWNER_PAUSED | Naive product baseline plus a **zero-truncated** log-linear challenger that nests the baseline | Fit on holdout | Unseen lineups are modelled as truncation, not zeros | — | holdout + `pit.promote` | DFS | Lesson L3: selection-aware likelihood |
| 14 | DFS contest sim and portfolio | `src/dfs/contestsim.py`, `src/dfs/portfolio_opt.py` | OWNER_PAUSED | One joint draw scores field and ours; greedy portfolio; entry count stops at the **lower 90% bound of marginal EV ≤ 0** | MC SE reported; no Kelly | Unknown tie rule is simulated and stamped `assumedTieRule` | MC SE on every output | chronological PIT backtest (`backtest.py`) | DFS | Lessons L4 and L5 |
| 15 | DFS evidence-claim policy | `src/dfs/evidence.py::validate_claim` | OWNER_PAUSED | Code-enforced claim taxonomy: conditional, preference, interval, popularity, retrospective, promotion, duplicate report | — | — | — | tests | DFS | Lesson L6: the facts / estimates / recommendations taxonomy, already written as code |
| 16 | DFS PIT store and metrics | `src/dfs/pit.py::as_of`, `src/dfs/metrics.py` | OWNER_PAUSED | `as_of` keyed on both `observed_at` and `recorded_at`; seeded bootstrap; SMALL_SAMPLE flag | — | stated, never filled | bootstrap CI | tests | DFS | Lesson L2: a dual clock |
| 17 | Frontend confidence surfaces | `frontend/components/ds/Badge.jsx`, `frontend/components/graphs/ConfidenceValueScatter.jsx`, rankings/trade/edge sections | live | Renders the backend `confidenceBucket` / `confidenceLabel` | Calculator UI contract §8–§10 | Contract §9: MISSING IS NEVER ZERO | Ordinal badge | contract tests | users | No common grammar for "estimate vs fact vs recommendation" across surfaces (UX §7) |

**Inventory count: 17 systems.**

**Diagnostic D-1: truncation bias of the live weekly marginal.** For `X ~ N(μ, (cv·μ)²)`, `E[max(0, X)] / μ − 1 = Φ(1/cv) + cv·φ(1/cv) − 1`. The values were computed with `scipy.stats.norm` in an inline Python run (exact command in this lane's transcript):

| Position | CV | P(truncated) | Mean bias |
|---|---|---|---|
| QB | 0.32 | 0.001 | +0.0001 |
| RB | 0.55 | 0.035 | +0.0075 |
| WR | 0.60 | 0.048 | +0.0119 |
| TE | 0.65 | 0.062 | +0.0174 |
| LB | 0.45 | 0.013 | +0.0021 |
| DB | 0.50 | 0.023 | +0.0042 |

The mean bias is at most about 1.7%, so it is **not** the issue. The issue is shape and dependence, which is finding F1.

**Finding F1 (DEMONSTRATED-IN-REPO; consequence is a PLAUSIBLE HYPOTHESIS).** The live Game Day and playoff simulations draw each player independently from a symmetric Gaussian. The owner-paused DFS module already implements three things the live engine lacks:

- a Gaussian copula with conservative, signed game-logic correlation priors;
- quantile marginals;
- correlation-matrix repair.

Same-team stacks on one fantasy roster add positive covariance to a team total. Opposing players on one roster add negative covariance. Under independence, team-total variance is wrong in a roster-dependent direction, so Win Matchup % may be over- or under-confident for exactly the stacked rosters. This is untested. POC-1 (§12) is the test, and it reuses DFS architecture without resuming DFS.

---

## 2. Competitive research and citations

### 2.1 Where the ten techniques are established

| Principle | Established in NFL / sports analytics | Fantasy products (public evidence only) | Novelty for Chase Upside |
|---|---|---|---|
| 1 Bayesian / epistemic | Hierarchical Bayes for NFL draft prediction, Robinson, CMSAC 2020 (https://www.stat.cmu.edu/cmsac/conference/2020/assets/pdf/Robinson.pdf). Fantasy-soccer player model, Egidi & Gabry (https://www.research.unipd.it/retrieve/e14fb26a-5e0a-3de1-e053-1705fe0ac030/Egidi_Gabry_Short.pdf). Bayesian NFL plus-minus, Sabin (JQAS; cited in #2053). Stan NUTS (https://mc-stan.org/docs/reference-manual/mcmc.html) | No major fantasy site found that publishes posterior intervals on dynasty values. KTC and FantasyCalc publish point values (methods not public: §2.2) | **Uncertain-novel.** Posterior bands on *dynasty value* are rare publicly. The search was not exhaustive, so treat the novelty as uncertain |
| 2 Hierarchical pooling | Standard in sports rating (empirical-Bayes regression to the mean). The `balaban` package does hierarchical player metrics for soccer (https://www.pypi.org/project/balaban/0.0.15/) | Implicit "regression to the mean" in many projection systems; not disclosed | Not novel as a method; the repo's M2 snap-weighted pooling already demonstrates it |
| 3 Causal | DoubleML identification-first workflow (https://docs.doubleml.org/stable/workflow/workflow.html). Sports causal work is mostly policy evaluation, e.g. the 2011-CBA injury study with a mixed Poisson interrupted time series (https://arxiv.org/pdf/1805.01271) | None found for fantasy recommendations | Novel but **mostly not identifiable** here (§5) |
| 4 Latent state | HMM for defensive assignments from tracking data (arXiv 2602.10784, found via search; not read in full). Role assignment by hidden permutations in soccer (https://arxiv.org/pdf/2502.03342) | Practitioner "Starter / Rotation / Depth" role tiers (Razzball depth charts, https://football.razzball.com/depthcharts) without published state models | **Uncertain-novel**: no published NFL snap-share HMM was found. Search was limited |
| 5 Sparsity | Generic; the nflfastR EP/WP models are XGBoost, with regularization by trees (`fastrmodels` docs, https://nflverse.r-universe.dev/fastrmodels/fastrmodels.pdf) | Undisclosed | Not novel |
| 6 Dependence / copulas | DFS: Haugh & Singal simulate positional marginals and then choose a copula (https://papers.ssrn.com/abstract=3393127). Hunter, Vielma & Zaman integer programming with stacking (https://arxiv.org/pdf/1604.01455). Gaussian teammate-correlation estimates (https://arxiv.org/pdf/2112.07002). Stokastic on "simulations vs medians" (https://www.stokastic.com/articles/dfs-strategy/dfs-projections-vs-simulations) | DFS optimizers (SaberSim, Stokastic, RotoGrinders LineupHQ, https://rotogrinders.com/articles/how-to-use-the-lineuphq-optimizer-to-win-at-daily-fantasy-football-3670965) use correlated simulation | **Established in DFS, apparently absent in season-long matchup odds.** Applying it to best-ball league matchup and median odds is **uncertain-novel** |
| 7 EVT | Little NFL fantasy use found | None | Data-starved (agree with #2053) |
| 8 Conformal / calibration | Adaptive Conformal Inference (Gibbs & Candès, NeurIPS 2021, https://proceedings.neurips.cc/paper/2021/hash/0d441de75945e5acbc865406fc9a2559-Abstract.html; arbitrary online shift, JMLR 2024, https://par.nsf.gov//servlets/purl/10538780). Conformal review (https://arxiv.org/pdf/2005.07972). Proper scoring: Gneiting & Raftery 2007 (https://sites.stat.washington.edu/people/raftery/Research/PDF/Gneiting2007jrssb.pdf); calibration–sharpness, Gneiting, Balabdaoui & Raftery 2007 (cited there). **No NFL-specific conformal paper found** | 4for4 floor/ceiling from positional volatility, 2015 (https://www.4for4.com/2015/w1/floor-ceiling-projections-draftkings10-ppr). Fantasy Labs ceiling = top 15% of outcomes (https://fantasylabs.com/?p=131153). Yahoo Plus min/max projections (https://help.yahoo.com/kb/SLN37118.html). Draft Sharks games-missed with an 80% "confidence interval" (https://www.draftsharks.com/injury-predictor/about) | **Ranges are common; published coverage audits of those ranges are not.** No competitor found publishing realised coverage. A public calibration ledger is the clearest differentiator (concept C3) |
| 9 Missingness | Pattern-mixture and sensitivity analysis are standard biostatistics; sports injury work treats season end as censoring (NESSIS 2017 Kaplan–Meier poster, https://www.nessis.org/nessis17/Binney.pdf) | Draft Sharks / PlayerProfiler injury risk as P(miss ≥ 2 games) (https://www.playerprofiler.com/article/nfl-injured-players-injury-finder/) | The repo's explicit four-state availability is already ahead of most public products in *honesty*, behind in *probability* |
| 10 Decision theory / DRO | Wasserstein DRO survey (https://doi.org/10.1287/educ.2019.0198). Haugh & Singal frame DFS as maximising expected reward against stochastic benchmarks | ESPN/IBM "boom/bust probabilities" and trade grades (https://betanews.com/2025/09/24/espn-fantasy-football-adds-ai-powered-weekly-insights-from-ibm-watsonx/); method not public | Explicit regret- and CVaR-framed waiver/trade advice is **uncertain-novel** publicly |

### 2.2 Fantasy products: what is and is not publicly known

| Product | What is publicly documented | What we could NOT verify | Overlap with this repo |
|---|---|---|---|
| KeepTradeCut | Crowd keep/trade/cut votes produce dynasty values; SF/1QB/TE+ variants (secondary sources). Its FAQ URL returned 404 when fetched 2026-11-01 | The vote → value algorithm, smoothing, aging | Already ingested as voters (KTC Crowd, KTC Trades) and a benchmark (KTC Market), per CLAUDE.md |
| FantasyCalc | Values derived from real league trades (multiple secondary sources). The fetched FAQ page returned only a title | Algorithm, recency weighting, trade count (claims of 1.2M+ are unverified) | Ingested as a voter (`fantasyCalc` family) |
| Dynasty Daddy | One secondary source says its values come from consensus rankings with SF/TE-premium support | Everything else | Ingested voter |
| FantasyPros | Expert Consensus Rankings; accuracy methodology since 2015, weighted by ECR rank (https://www.fantasypros.com/about/faq/football-draft-accuracy-methodology/, https://support.fantasypros.com/hc/en-us/articles/44470556043547). ECR tables historically show best/worst/avg/std-dev columns (from product knowledge; **current presence unverified**) | ECR aggregation weights | Fitzmaurice source ingested |
| PFF | Projections authored by named analysts (https://www.pff.com/news/fantasy-the-logic-behind-pffs-fantasy-projections) | Any fantasy-point distribution simulation | none |
| 4for4 / ETR / RotoWire / Rotoviz / DLF | 4for4 volatility-based floor/ceiling (2015). Rotoviz Screener exists, details paywalled. DLF IDP held as a source (MD-5). ETR methodology not found | Most methodology is paywalled | DLF, RotoWire (via Sleeper) ingested |
| ESPN / Yahoo | IBM Player Insights boom/bust probabilities and trade grades; Yahoo min/max projections | Calibration of either | none |
| Sleeper | Platform data source; third-party Sleeper-connected value tools exist (Dynasty Assistant, https://www.footballguys.com/article/dynasty-assistant-sleeper) | Native value feature | Data source only |
| DFS optimizers | Correlated simulations, stacking, ownership, duplication (practitioner literature above) | Internals | Paused DFS module mirrors them |

**Novelty statement (careful).** Five things together appear rare publicly. We found no public product that combines:

- exact per-league scoring and best-ball lineup solving;
- source-family independence accounting;
- evidence-quality confidence with a bottleneck rule;
- MISSING-IS-NEVER-ZERO states;
- explicitly labelled uncalibrated odds.

This is **uncertain**. Most competitors' methods are paywalled or undisclosed, and absence of public documentation is not absence of the feature.

### 2.3 Library landscape against this repo's constraints

Constraints (DEMONSTRATED-IN-REPO):

- `requirements.txt` holds only `numpy~=2.0` and `scipy~=1.13` for numerics. **There is no pandas, statsmodels or scikit-learn.**
- `nfl_data_py` is deliberately excluded.
- The VPS is CPU-only.
- HiGHS solves must run on one pinned thread (ADR-DFS-012; memory note on a segfault).
- CI has L2 time budgets.
- Deploys are hash-locked (`requirements.lock.txt`).

| Library | Fit | Verdict |
|---|---|---|
| cmdstanpy | Needs a C++ toolchain and a CmdStan compile (https://mc-stan.org/cmdstanpy/installation.html). Offline research only | **Research box only**; never a serving dependency |
| PyMC | Heavy (pytensor compile); CPU OK | Research only |
| NumPyro | JAX dependency; CPU chains run sequentially by default (https://github.com/pyro-ppl/numpyro) | Research only |
| statsmodels (state-space, GLM NB) | Pure-Python plus scipy; no compile | **Best first add** *if* a model graduates. Until then, conjugate Gamma–Poisson / Beta–Binomial updates are ~20 lines of scipy |
| scikit-learn (GMM, isotonic) | Moderate wheel size | Research first. Isotonic calibration and GMM are the strong-simple baselines for §6 |
| DoubleML | Pulls scikit-learn | REJECT for now: identification is not available (§5) |
| MAPIE / crepes | MAPIE has EnbPI and ACI (https://mapie.readthedocs.io/en/stable/generated/mapie.regression.TimeSeriesRegressor.html) | **Not needed.** ACI is one line of online update (`α_{t+1} = α_t + γ(α − err_t)`); implement it in numpy against the existing forecast archive |
| pyvinecopulib | C++ core, pip/conda wheels (https://pypi.org/project/pyvinecopulib) | REJECT until Gaussian/t copulas fail a calibrated test |
| POT (optimal transport) | Only useful for DRO radius or distribution-shift diagnostics | REJECT now |
| cvxpy | Solver stack; conflicts in spirit with the single-thread HiGHS rule | REJECT for serving; `scipy.optimize.milp` / `linprog` covers the CVaR LP |
| hypothesis (test-only) | Pure Python; already named in `docs/engineering/ENGINEERING_RELIABILITY_PRIORITIES_2026-09-06.md` Priority 4 but **not installed** (no `import hypothesis` in `tests/`) | **APPLY** (test-only, `requirements-dev.txt`), subject to execution authority |
| z3-solver / OR-Tools CP-SAT | Large wheels | REJECT for invariants that finite enumeration covers (§6.3) |

---

## 3. Ten-principle screen: cross-cutting surfaces

The per-domain IDP and ROS screens are #2053's and are not repeated. Each row compares **champion → strong simple baseline → advanced challenger**.

| Principle | Credible cross-cutting application | Champion | Strong simple baseline | Advanced challenger | Limitation / verdict |
|---|---|---|---|---|---|
| 1 Bayesian | Posterior band on each board row's blended value, from the per-family votes already stamped | Point value + ordinal confidence | **Bootstrap over families** (resample voting families, re-run the count-aware blend) | Hierarchical model of family bias and noise (NUTS offline) | Families are few (≤ ~11), so a bootstrap band is coarse but honest. It must stay a NAMED alternate concept, never `rankDerivedValue` (CLAUDE.md invariant). E |
| 2 Hierarchical pooling | Shrink per-position CVs in PointsModel toward a league-wide CV | Fallback constants / box-fitted CVs | Empirical-Bayes CV shrinkage by sample size | GP over (position, projection level) | Variance heteroskedastic in the mean is likely (PLAUSIBLE). E |
| 3 Causal | "Did following the site's advice help?" | none | Descriptive before/after, labelled non-causal | DML/TMLE | **Not identifiable**: advice uptake is self-selected, n is tiny, there are no instruments. REJECT causal claims; KEEP descriptive |
| 4 Latent state | Contender/rebuilder posture over time | `window.py::competitive_posture` with HOLD perturbation | Keep | HMM over posture | Posture already explains itself with a perturbation grid; an HMM adds opacity. KEEP |
| 5 Sparsity | Which inputs drive a recommendation (explanations) | Factor rows | Ablation tables | Horseshoe | Explanations need ablation, not sparsity priors. REJECT horseshoe here |
| 6 Dependence | Game Day / playoff joint draws (F1) | Independent Gaussian | **Game-level shared factor** (one latent N(0,1) per NFL game and team, loading by position) | Gaussian copula with DFS-style priors, then t-copula | Tail dependence is understated by a Gaussian copula (ADR-DFS-015 says so itself). **E, top priority in this lane** |
| 7 EVT | "Championship-week blow-up" tails | none | Empirical quantiles | GPD | Too few independent exceedances. REJECT |
| 8 Calibration | One calibration ledger for every published probability and interval | Disclosure string only | **Reliability diagram + Brier/CRPS from the forecast archive** | ACI online recalibration | Exchangeability is violated (weekly drift), so report empirical coverage and never claim the conformal guarantee. N |
| 9 Missingness | Coverage-aware displays ("8 of 11 families voted") | Confidence axes | Show the eligible-family denominator in the UI | Pattern-mixture sensitivity bands | Already strong in the backend. UX gap only. E (UX) |
| 10 Decision / DRO | Present recommendations as regret ("cost if wrong") rather than a single best move | Deterministic best action | **Scenario regret table** from the existing MC | CVaR / Wasserstein DRO | Regret display needs calibrated scenarios first (depends on 6 and 8). P2 |

---

## 4. Replacement and enhancement rows (summary; full rows in JSON)

The class of each row is shown in its "Class" column.

| ID | Class | Current → proposed | Horizon |
|---|---|---|---|
| AM-FRONTIER-01 | E | Game Day / playoff independent Gaussian → shared game-factor and copula joint draws, reusing the DFS correlation-prior architecture as a *live-owner* module | P1 |
| AM-FRONTIER-02 | N | No probability calibration record → one Forecast Calibration Ledger (reliability, Brier, CRPS, coverage) per published probability or interval | P0/P1 |
| AM-FRONTIER-03 | E | Seeded random brute-force tests → Hypothesis property suite (shrinking counterexamples) for lineup, roster capacity, ledger conservation and pick ownership | P1 |
| AM-FRONTIER-04 | R / REMOVE-SIMPLIFY | Trade MC on a synthetic ±15% band → hide the win-rate until real bands exist, or replace it with a family-bootstrap band | P1 |
| AM-FRONTIER-05 | E | Hand-threshold archetypes → evidence check (GMM/BIC + stability), plus fixing missing-feature → 0 | P2 |
| AM-FRONTIER-06 | E (UX) | Ad-hoc confidence displays → one Uncertainty Grammar (fact / estimate / recommendation / unavailable) across surfaces | P1 |
| AM-FRONTIER-07 | N | Point values only → family-bootstrap value band as a named alternate concept | P2 |
| AM-FRONTIER-08 | N | — → Trade Robustness Stamp: does the verdict survive resampled / leave-one-family-out boards? (concept C8) | P2 |
| AM-FRONTIER-09 | E | Fallback CVs → empirical-Bayes shrunk CVs, heteroskedastic in the mean | P2 |
| AM-FRONTIER-10 | N | — → "Disagreement Map" (concept C2) | P2 |
| AM-FRONTIER-11 | REJECT | TDA archetypes, SMT for eligibility, vine copulas, EVT tails, DML on advice uptake | REJECT |
| AM-FRONTIER-12 | N | — → Regret-framed decision cards (concept C5) | P2 |
| AM-FRONTIER-13 | N | — → Availability-probability layer on top of the four-state owner (concept C7) | BLOCKED on PIT injury data |

---

## 5. Causal inference: explicit identification check

Candidate question: "Does acting on the Waiver Advisor or Trade Advisor improve a manager's outcomes?"

- **Treatment**: a manager follows an advisory output.
- **Outcome**: realised best-ball points or wins.
- **Confounders**: manager skill, roster state, attentiveness. All of these drive both uptake and outcome.
- **Identification** would require no unmeasured confounding (implausible), a randomised or encouragement design (no randomisation authority, and the user base is tiny), or a credible instrument (none).
- **Overlap**: 12 teams in one league.

**Verdict: NOT IDENTIFIABLE → REJECT causal language.** A preregistered descriptive "advice log vs realised outcome" table with explicit non-causal labelling is allowed. This agrees with #2053 S8 and extends it from streaming to every advisor.

---

## 6. Seven pure-maths disciplines: verify or challenge #2053

| Discipline | #2053 verdict | This lane | Reason |
|---|---|---|---|
| Arithmetic algebraic geometry | REJECT | **AGREE, REJECT** | No object in the codebase is a variety over a number field |
| Higher category theory | REJECT (borrow compositional design) | **AGREE, REJECT** | The repo already gets compositionality from typed artifacts, `leagueKey` / scoring-fingerprint scoping and one-owner modules. Category language adds vocabulary, not checks |
| Algebraic topology (TDA) | RESEARCH / LOW | **CHALLENGE → REJECT for now** | See §6.2 |
| Analytic number theory | REJECT | **AGREE, REJECT** | — |
| PDEs | REJECT | **AGREE, REJECT** | Weekly discrete observations; a Fokker–Planck framing of market value has no boundary conditions or data |
| Set theory / logic | PROTOTYPE TESTS via CP-SAT or Z3 | **CHALLENGE → property-based testing YES, SMT NO** | See §6.3 |
| Differential geometry | RESEARCH / LOW | **CHALLENGE → REJECT** | Information-geometric distances on archetype space presuppose a validated archetype space, which does not exist (§6.2) |

### 6.2 TDA vs ordinary clustering for player archetypes

**What #2053 missed.** #2053 compared persistent homology against PCA/GMM/HDBSCAN as if the starting point were "no archetypes". The live champion is `src/scoring/archetype_model.py::infer_archetype`, a hand-coded threshold tree with **no evidence found** for its cut-points (0.22, 0.45, 13.5, 1.2, 6.5 …). It also reads missing features as `0.0`, which silently assigns the default archetype.

The correct sequence is **champion (thresholds) → strong simple baseline (Gaussian mixture with BIC selection plus bootstrap stability) → advanced (TDA/Mapper)**.

**Why TDA loses here:**

- Mapper output depends on lens, cover and clusterer choices. The canonical NBA "13 positions" result used seven statistics, and a 2022 *Journal of Sports Analytics* review calls it more geometric than network-based (https://journals.sagepub.com/doi/10.3233/JSA-220584). That review then gets eight archetypes from ordinary methods on tracking data.
- Persistent homology needs dense point clouds. Per-player NFL samples are 17 games a season, and IDP alignment data is unavailable (MD-20).
- Archetypes earn their keep only through downstream predictive or decision lift. That test is identical for GMM and TDA, and GMM is cheaper and explainable.

**Verdict: REJECT TDA** until a GMM archetype model passes a stability and lift test and leaves a residual structure that clustering cannot capture. **E** for the threshold champion: add an evidence check and fix missing → 0. That fix is a correctness item (P0-adjacent) that does not need any research.

### 6.3 Formal methods for roster eligibility, trade legality and lineup optimality

| Property | Domain size | Right tool | Why not SMT |
|---|---|---|---|
| Slot eligibility table consistency (every slot type × position; FLEX ⊇ RB/WR/TE; SUPER_FLEX ⊇ QB+FLEX; IDP slot families) | ~15 slots × ~12 positions | **Exhaustive enumeration in a plain pytest** | Finite and tiny. Enumeration is a proof |
| Lineup optimality on unusual formats (2 TE, SF, 9 IDP, IDP_FLEX present/absent, taxi, best ball) | Combinatorial, but brute force is feasible ≤ ~14 players | **Hypothesis** generating league cards × rosters, oracle = existing `brute_force_best`; shrinking returns minimal counterexamples | The oracle already exists; SMT would only re-encode it |
| Roster capacity monotonicity (adding an incoming player never frees a spot; picks occupy none; unknown cap → None) | Unbounded inputs | **Hypothesis** (stateful) | Properties are relational and easy to state as tests |
| Ledger conservation (Σ raw given = Σ raw received; each asset routed once) | Unbounded | **Hypothesis** | Algebraic invariant |
| Pick ownership fold (trades as diffs; `observed` vs `unavailable`) | Sequences of trades | **Hypothesis stateful machine** | — |
| "No legal lineup exists" detection for pathological cards | Small | SAT *could* certify UNSAT, but a matching argument (Hall's condition) already does | Matching gives the same certificate with no new dependency |

**Verdict.** **APPLY** Hypothesis (test-only, already Priority 4 in the engineering priorities doc, not yet installed). **REJECT** Z3 and CP-SAT for these properties. This is a **targeted correctness gain, not predictive accuracy**, which agrees with #2053's caveat.

---

## 7. Uncertainty UX patterns

### 7.1 Literature (PUBLISHED-EXTERNAL)

- **Hypothetical outcome plots (HOPs).** These animate draws, and beat error bars and violins for ordering-reliability judgments. Hullman, Resnick & Adar, PLoS ONE 2015 (https://pmc.ncbi.nlm.nih.gov/articles/PMC4646698). Untrained observers infer trends better with HOPs at low evidence. Kale et al., InfoVis 2018 (https://idl.uw.edu/papers/hops-trends).
- **Quantile dotplots.** People derive probabilities from them more accurately than from densities. Kay et al., CHI 2016, "When (ish) is my bus?" (DOI 10.1145/2858036.2858558). They improve transit decisions, Fernandes et al., CHI 2018 (DOI 10.1145/3173574.3173718). Citations are from memory; the DOIs should be verified.
- **Estimation ≠ decision.** The display with the least estimation bias (quantile dotplot) is not the one with the least decision bias, and adding means slightly biases both. Kale, Kay & Hullman, VIS 2020 best paper (https://idl.uw.edu/papers/effect-size-judgments).
- **Overview.** Padilla, Kay & Hullman 2020 chapter (https://moodle2.units.it/pluginfile.php/466375/mod_resource/content/0/Uncertainty_Visualization_Padilla_Kay_Hullman_2020.pdf). "Noisy work" review 2024 (https://arxiv.org/pdf/2411.10482).
- **Trust.** Communicating epistemic uncertainty does not necessarily harm trust. van der Bles et al., Royal Society Open Science 2019 (doi:10.1098/rsos.181870, https://wrap.warwick.ac.uk/116193/).
- **Frequency framing at scale.** FiveThirtyEight's 2020 "ball swarm" showed 100 representative outcomes (https://fivethirtyeight.com/features/how-we-designed-the-look-of-our-2020-forecast). It was critiqued for over-correcting with caveats (https://statmodeling.stat.columbia.edu/2020/11/06/is-there-a-middle-ground-in-communicating-uncertainty-in-election-forecasts/). Hullman lab: no single display captures every aspect (https://www.hullmanlab.northwestern.edu/paper/2020/09/01/election-forecasts.html).
- **Evaluate probabilities with proper scores.** Gneiting & Raftery 2007 (link in §2.1).

### 7.2 Repo constraints (DEMONSTRATED-IN-REPO)

`docs/ui/CALCULATOR_UI_IMPLEMENTATION_CONTRACT.md` fixes the following:

- PSI tokens only; no page-local colours (§4).
- Movement uses blue/up and orange/down, never colour alone, and falling value is not an error (§4).
- MISSING IS NEVER ZERO, with loading, unavailable, missing, stale, degraded, partial and zero kept distinct (§9).
- Progressive disclosure, not permanent diagnostic clutter (§10).
- The UI must not create a parallel owner for confidence or freshness (§10).
- Trade puts "who gains / balanced / confidence" first, with sources and charts behind disclosure (§11).

The UX navigation audit on `claude/ux-nav-audit` covers IA and naming, not maths output. One relevant item is UX-P06: "who is mispriced" is spread over five surfaces, which concept C2 addresses.

### 7.3 Patterns proposed for this site

**P-U1, the Uncertainty Grammar: four kinds of claim, each with a fixed visual form.** This mirrors the paused DFS claim taxonomy (`src/dfs/evidence.py`) and turns it into a sitewide display rule.

| Kind | Example | Visual form | Required metadata |
|---|---|---|---|
| **Fact** | "Scored 18.4 in week 7", roster, standings | Plain number, primary ink | source + as-of |
| **Estimate** | projection, value, odds, band | Number + range glyph (p10–p90 bracket or dotplot), secondary-ink "est." eyebrow | method, as-of, calibration status (calibrated / uncalibrated / not testable) |
| **Recommendation** | "Start X", "Add Y, drop Z", trade verdict | Action label + "why" disclosure + "if wrong" line | the estimates it consumed, decision rule, NO-ACTION option |
| **Unavailable / unknown** | missing source, unverifiable ownership | Explicit state chip, never 0 or blank | reason code |

The grammar is display-only. It reads backend stamps and never computes confidence (contract §10).

**P-U2, calibration status is a first-class field.** Today only simulator odds carry the experimental disclosure. Every estimate surface should state one of three statuses:

- calibrated, with a ledger link;
- uncalibrated, using the owner's wording;
- not testable, e.g. dynasty values with no ground truth at horizon.

This generalises decision 9 without changing its wording.

**P-U3, separate MC noise from model uncertainty.** The playoff engine reports Wilson intervals on simulation error. Those intervals must never be shown as "±x% confidence" in the forecast, because that is anti-pattern A3. Show MC error only in the Model Lab and owner view.

**P-U4, frequency framing for probabilities.** "In 100 simulated weeks, you win 62", with an optional 10×10 icon array or a 20-dot quantile dotplot for team totals. Kay 2016 and Fernandes 2018 support dotplots. Kale 2020 warns that the best display for estimation is not always best for decisions, so pair the dotplot with the recommendation line.

**P-U5, show disagreement as a spread, not an average.** Per-family dots on a value axis (strip plot) with the blend marked. Coverage is shown as "8 of 11 eligible families". The confidence bottleneck axis is named in words ("held back by: freshness"). The backend already stamps `confidenceReasons`.

**P-U6, data quality inline, details behind disclosure.** A one-word quality chip (fresh / stale / partial / unavailable) next to the number. The full axes go in a drawer. This respects contract §10 against permanent clutter.

**P-U7, regret line on every recommendation.** "If wrong, typical cost: ~2.1 pts (bad week ~6)". Show it only when the scenarios are calibrated (gated by P-U2); otherwise show "risk not yet measured".

**Anti-patterns:**

- **A1**: probabilities with decimal false precision ("62.37%").
- **A2**: a confidence badge implying accuracy. The B11 bucket is evidence quality.
- **A3**: MC error presented as forecast uncertainty.
- **A4**: a ±15% synthetic band presented as information (system #5).
- **A5**: colour-only uncertainty, which violates contract §4.
- **A6**: hiding NO-ACTION.

**Accessibility.** Icon arrays and dotplots need a text equivalent ("62 of 100") and must never rely on hue. HOP animations need a pause control and `prefers-reduced-motion` handling.

---

## 8. N, DFS: reusable mathematical lessons (no resumption proposed)

| # | Lesson | Where in DFS | Live system that could adopt it (subject to authority) |
|---|---|---|---|
| L1 | Marginal-preserving Gaussian copula plus declared, signed, shrunk correlation priors plus nearest-correlation repair, with the uncalibrated flag stamped | `distributions.py`, `correlation.py` | Game Day / playoff sim (AM-FRONTIER-01) |
| L2 | A dual-clock as-of: an observation is usable at T only if `observed_at ≤ T` **and** `recorded_at ≤ T` | `pit.py::as_of` | Forecast archive and calibration ledger; compare with `src/history/asof.py` |
| L3 | Selection-aware likelihood: zero-truncated Poisson because unseen lineups are not zeros; the challenger nests the baseline | `duplication.py` | Market-trade comps (only observed trades exist); FAAB crowd bids |
| L4 | Monte Carlo standard error on every simulated output | `contestsim.py` | Already present in playoff_sim (Wilson). Extend to Game Day |
| L5 | Stop adding when the **lower 90% bound** of marginal value ≤ 0: conservative sequential stopping under model uncertainty | `portfolio_opt.py` | Streaming capacity (IST-6), number of waiver claims |
| L6 | Claim taxonomy enforced in code: preference never moves a number; conditional evidence is inactive until resolved | `evidence.py` | News → BDVM events (already speculation-lane); Uncertainty Grammar P-U1 |
| L7 | Independence disclosed on every range output ("stacked lineup range is wider than shown") | `outcomes.py` | Any range the live site shows before F1 is fixed |
| L8 | Seeded bootstrap plus a SMALL_SAMPLE flag in the one metrics owner | `metrics.py` | Calibration ledger (AM-FRONTIER-02) |

---

## 9. Product innovation challenge (Part 15)

Each concept combines at least two principles. All are proposals, not authorized features.

**Overlap labels:**

- **Low**: no public equivalent found.
- **Med**: partial equivalents exist.
- **High**: common in the market.

All overlap judgments are uncertain, because competitor internals are paywalled.

### C1 Matchup Weather (joint-dependence Game Day)

| Field | Content |
|---|---|
| Principles | 6 + 8 + 10 |
| UX | Under Win Matchup %: "Your outcome is tied to the BUF–KC game: 3 of your starters move together." Shows a 20-dot quantile dotplot of your total vs the opponent's, and a "hedge" note. |
| Example | Win 58 of 100. Your bad weeks cluster when BUF scores under 20. Opponent's spread is narrow (no stacks). |
| Maths | Team total `T = Σ_j s_j`, with `s_j = F_j^{-1}(Φ(Z_j))` and `Z = L·G + ε`, where G is a latent game/team factor (POC-1) |
| Data | Weekly projections (archived), NFL schedule, realised scores; game-day archive |
| Measured by | Brier / log-loss of matchup outcomes and PIT of team totals vs the independent champion (POC-1) |
| Competitors | DFS sims do this for contests (Med); season-long matchup odds with correlation: Low (uncertain) |
| Minimal POC | Offline replay on archived weeks, through `simulate_league_week` with a swapped draw function |

### C2 Disagreement Map ("who is mispriced", one surface)

| Field | Content |
|---|---|
| Principles | 1 + 9 + 3 (signal independence) |
| UX | One page answering UX-P06. Each player is a strip of per-family votes. Disagreement is measured in *independent families* with coverage shown. Filter: "my roster / targets". |
| Example | "Player X: 9 of 11 families say 4,100–4,600; DLF IDP says 2,900 (held: stale 19 days)." |
| Maths | Family-bootstrap band `[q05, q95]` of the count-aware blend; disagreement index = blend-free MAD across families |
| Data | Already on the contract (per-source contributions, families, freshness) |
| Measured by | User task time (UX study); whether later market moves fall inside the band (calibration ledger) |
| Competitors | FantasyPros best/worst/std-dev (Med); family-aware independence: Low |
| Minimal POC | Read-only notebook over one archived contract |

### C3 Public Calibration Ledger ("how right have we been")

| Field | Content |
|---|---|
| Principles | 8 + 9 |
| UX | Per published probability or interval: a reliability diagram, coverage of 80% intervals, sample size, SMALL_SAMPLE flag. Linked from every "est." chip. |
| Example | "Win Matchup %, 2026 weeks 1–8: 48 games; Brier 0.21; forecasts at 70–80% won 9 of 14 (small sample)." |
| Maths | Brier, log score, CRPS (Gneiting & Raftery), PIT histograms, empirical coverage; optional ACI |
| Data | `src/ros/forecast_archive.py`, `game_day_archive.py`, realised results |
| Measured by | Existence of an auditable record; trust survey (optional) |
| Competitors | FantasyPros accuracy tracks *rank* accuracy of experts (Med); probability calibration ledgers: Low |
| Minimal POC | Script over archived Game Day forecasts producing the reliability table |

### C4 Value Weather Band (dynasty value with an honest range)

| Field | Content |
|---|---|
| Principles | 1 + 2 + 9 |
| UX | Each rankings row gets a thin p10–p90 bracket. Hover: "range from resampling 9 independent families; not a forecast of future value". |
| Example | "4,350 (est. 4,050–4,600)" |
| Maths | Bootstrap over families, re-running the count-aware weighted blend; output named `familyBootstrapBand`, never canonical |
| Data | Present |
| Measured by | Band width vs confidence bucket agreement; stability day to day |
| Competitors | Low (uncertain) |
| Minimal POC | Offline computation over one contract; compare band width with `confidenceBucket` |
| Note | Replaces the synthetic ±15% band that the trade MC consumes |

### C5 Regret Cards (decisions framed as "cost if wrong")

| Field | Content |
|---|---|
| Principles | 10 + 6 + 8 |
| UX | Start/sit, add/drop and trade cards show expected gain and the 1-in-5 bad case. NO ACTION is always a card. |
| Example | "Start A over B: +1.8 pts expected; in the worst 20% of weeks you lose 3.1. NO ACTION: 0." |
| Maths | Scenario regret `R(a) = E[max_b U(b,Y) − U(a,Y)]`; CVaR_0.2 of the gain |
| Data | Calibrated joint draws (needs C1 + C3) |
| Measured by | Shadow replay decision regret vs deterministic champion |
| Competitors | ESPN/IBM boom-bust (Med); explicit regret + NO ACTION: Low |
| Minimal POC | Replay archived lineup decisions through MC |

### C6 Role Radar (latent role changes with false-alarm control)

| Field | Content |
|---|---|
| Principles | 4 + 2 + 9 |
| UX | Alert: "Player moved rotational → full-time (P=0.71, 2 weeks of evidence)". Each alert has a false-alarm rate shown from the history. |
| Example | As above |
| Maths | Two-state HMM on snap share vs a change-point baseline (#2053 S2) |
| Data | Snap counts (PIT), IDP features |
| Measured by | Precision/recall of role changes, Brier of P(full-time) |
| Competitors | Practitioner depth charts (Med) |
| Minimal POC | #2053 S2 (not duplicated here) |
| Note | Included for the UX layer only |

### C7 Availability Odds (from four states to a probability)

| Field | Content |
|---|---|
| Principles | 9 + 2 + 8 |
| UX | Replaces the `uncertain` chip with "plays: ~70% (questionable; historical Q designation)" and a calibration link |
| Example | As above |
| Maths | Beta–Binomial pooled P(plays \| designation, position, day-of-report), updated per season |
| Data | **Missing**: point-in-time injury designations and outcomes (nflreadr `load_injuries` is outside requirements; the Python port is reported broken for 2025, https://github.com/nflverse/nflreadpy/issues/6) |
| Measured by | Brier |
| Competitors | Draft Sharks / PlayerProfiler injury risk (Med-High) |
| Minimal POC | BLOCKED on data |

### C8 Trade Robustness Stamp

| Field | Content |
|---|---|
| Principles | 10 + 1 + 3 |
| UX | Next to a trade verdict: "Verdict holds under 9 of 10 resampled boards", or "Verdict flips if DLF is excluded". |
| Example | As above |
| Maths | Re-run the canonical verdict over family-bootstrap boards and leave-one-family-out boards (no new valuation owner; uses `analyze_trade_n` unchanged) |
| Data | Present |
| Measured by | Fraction of verdicts that are fragile; user comprehension test |
| Competitors | Low |
| Minimal POC | Offline loop over archived trades |

### C9 Explain-the-Gap Counterfactual

| Field | Content |
|---|---|
| Principles | 5 (ablation) + 9 |
| UX | "Why is our value 600 above KTC Market? Remove the IDPTC vote: gap 120. Remove freshness weighting: gap 580." |
| Example | As above |
| Maths | Leave-one-family-out and one-mechanism-off recomputations through the existing override path (`/api/rankings/overrides`), Shapley-style attribution optional |
| Data | Present |
| Measured by | Comprehension study |
| Competitors | Low |
| Minimal POC | Script calling the override builder |

### Ranking: top 5

| Rank | Concept | Why |
|---|---|---|
| 1 | C3 Calibration Ledger | Unblocks every other probability claim; data exists; differentiator |
| 2 | C1 Matchup Weather | F1 is a demonstrated modelling gap on a live surface; DFS architecture reusable |
| 3 | C8 Trade Robustness Stamp | Zero new valuation owner; strong interpretability; data present |
| 4 | C4 Value Weather Band | Replaces the synthetic ±15% band; data present |
| 5 | C2 Disagreement Map | Consolidates UX-P06; data present |

C5 ranks 6th because it depends on C1 and C3. C7 is BLOCKED on data.

---

## 10. KEEP / REMOVE / REJECT

**KEEP:**

- B11 bottleneck confidence. Do not replace it with a probability.
- The uncalibrated-odds disclosure string and its single owner.
- The four-state availability owner.
- The exact lineup solver and its brute-force oracle.
- `competitive_posture` with its HOLD perturbation grid. An HMM is not better.
- `tiering.py`'s effect-size gaps. Deterministic and readable; enhancement is optional.
- The playoff engine's MC error reporting, owner/lab-facing only.
- Ordinal display of `confidenceBucket`.

**REMOVE / SIMPLIFY:**

- The trade MC win-rate on a synthetic band, which is shown as a number with almost no information. Hide it or replace it via C4.
- Missing → 0.0 in `infer_archetype`.

**REJECT:**

- TDA archetypes; differential geometry.
- SMT / CP-SAT for eligibility or legality (enumeration and Hypothesis suffice).
- Arithmetic geometry, number theory, PDEs, higher categories.
- Vine copulas and normalizing flows before Gaussian/t copulas fail.
- EVT tails.
- DML/TMLE on advice uptake (not identifiable).
- MAPIE / pyvinecopulib / cvxpy / POT as serving dependencies.
- Horseshoe for explanations.
- Resuming DFS.

---

## 11. Scores (100-point rubric)

Scores are judgments, not measured effects. The full breakdown is in the JSON.

| ID | Title | Total | Horizon |
|---|---|---|---|
| AM-FRONTIER-02 | Forecast Calibration Ledger | 85 | P0/P1 |
| AM-FRONTIER-01 | Joint-dependence Game Day / playoff draws | 80 | P1 |
| AM-FRONTIER-03 | Hypothesis invariant suite | 78 | P1 |
| AM-FRONTIER-06 | Uncertainty Grammar | 77 | P1 |
| AM-FRONTIER-04 | Retire synthetic trade band | 76 | P1 |
| AM-FRONTIER-08 | Trade Robustness Stamp | 74 | P2 |
| AM-FRONTIER-07 | Family-bootstrap value band | 72 | P2 |
| AM-FRONTIER-05 | Archetype evidence + missing→0 fix | 69 | P2 |
| AM-FRONTIER-10 | Disagreement Map | 66 | P2 |
| AM-FRONTIER-09 | Shrunk heteroskedastic CVs | 64 | P2 |
| AM-FRONTIER-12 | Regret cards | 62 | P2 |
| AM-FRONTIER-13 | Availability odds | 55 | BLOCKED |
| AM-FRONTIER-11 | Rejected frontier techniques | 20 | REJECT |

---

## 12. Proof-of-concept experiments

### POC-1: Does joint dependence improve Game Day matchup calibration?

**Hypothesis (PLAUSIBLE).** Replacing independent per-player Gaussian draws with a shared game/team factor model improves the calibration of `Win Matchup %` and `Beat League Median %` and the PIT uniformity of team totals. Candidates are a Gaussian copula over quantile marginals, and the champion's own marginals with copula dependence only.

**Arms** (one change at a time):

- **A0** champion: independent truncated Gaussian, `sd = max(0.5, μ·CV_pos)`.
- **A1**: same marginals with the factor model `Z_j = Σ_g λ_{pos(j)} G_{game(j)} + λ'_{pos(j),team} H_{team(j)} + sqrt(1 − Σλ²) ε_j` and `s_j = F_j^{-1}(Φ(Z_j))`.
- **A2**: A1 with right-skewed marginals (lognormal or gamma, matching the mean and CV).

Loadings `λ` are **fit only on seasons strictly before the evaluation season**. Season-level realised score pairs give the residual correlations by (same team, position pair) and (opponents, position pair), shrunk toward zero with an empirical-Bayes weight `n/(n + k)`. `k` is preregistered, not tuned on the evaluation data. DFS's `correlation.priors@1.0.0` signs are the prior directions. The DFS code is not imported; the architecture is re-implemented in a live owner after authorization.

**Variables.** Per player-week: archived pregame mean `μ_j` (provider weekly baseline locked at kickoff, `game_day_estimates.py`), position, NFL team and game id, availability state, realised league-scored points. Per team-week: the optimal best-ball lineup total (via `solve_optimal_assignment`), matchup outcome, and median outcome.

**Point-in-time cutoff.** Inputs are the pregame baselines locked at each player's kickoff, the dual clock of lesson L2. The roster is as of lineup lock. No post-kickoff provider update is used.

**Training / evaluation.** Fit loadings on the season(s) before the evaluation season, or on weeks `< t` in an expanding window within a season. Evaluate on every archived week with locked baselines. If only one season has locked baselines, use expanding-window within-season fitting and state it.

**Sample size / effective n.** `dynasty_main` gives 6 matchups and 12 median outcomes per week, about 102 matchups and 204 median outcomes per 17-week season. Team-week totals are about 204 per season, clustered by week. Brier-score differences of the size plausible here will be **underpowered on one league-season** (PLAUSIBLE; compute power from observed variance before preregistration).

Mitigations:

- Use the PIT of team totals, which uses the whole distribution and so carries more information per observation.
- Add other leagues only where rights and scoring identity are proven (the `dynasty_new` fingerprint differs, so it is a separate stratum).
- Treat one season as **pilot evidence, not promotion evidence**.

**Uncertainty method.** Week-clustered block bootstrap (the whole week is resampled) for differences in Brier, log score, CRPS of team totals, and the Kolmogorov–Smirnov / Anderson–Darling distance of PIT from uniform.

**Multiplicity.** One primary endpoint: CRPS of team-week totals, A1 vs A0. Secondary endpoints (Brier of matchup, Brier of median, PIT KS, A2 vs A1) are reported with Holm correction.

**Compute.** About 20k draws × 12 teams × lineup solve per week. The existing engine already runs this. A1 adds one Cholesky per game slate. Single-thread CPU, minutes per season.

**Leakage safeguards:**

- Loadings fit only on earlier data.
- Realised scores are opened only after forecasts are frozen and their digest recorded, as in the DFS backtest step 1.
- Exclude any player-week whose baseline was first seen after kickoff.
- The week-7 V3 holdout is not reused as development data.

**Acceptance (all required):**

1. Primary CRPS improves, with the 95% clustered-bootstrap CI excluding 0 in A1's favour.
2. No secondary endpoint is worse beyond a preregistered noninferiority margin.
3. PIT is no worse in either tail.
4. The result replicates on a second evaluation season, or is labelled pilot-only.

**Rejection:**

- The CI includes 0.
- Or calibration improves only by uniformly widening the distributions (sharpness loss with no CRPS gain).
- Or the fitted correlations' signs contradict football logic in more than 2 of the preregistered pairs.
- Or there are insufficient locked baselines.

**Rollback / monitoring.** The experiment is research-only with no flag. Any later live adoption would sit behind a default-OFF flag, keep the owner-approved disclosure until the C3 ledger shows calibration, and run weekly ledger monitoring.

### POC-2: Hypothesis invariant suite (test-only)

**Hypothesis.** Property-based generation over league cards and rosters finds zero counterexamples to the stated invariants, or finds minimal counterexamples that hand-written tests missed. Either result is valuable.

**Properties:**

- (a) `solve_optimal_assignment` total equals `brute_force_best` for random cards. The cards cover SF on/off, TE×1–2, IDP slots 0–9 with and without IDP_FLEX, FLEX×0–3 and K on/off, with rosters of 8–14 players including `None`-valued players.
- (b) Unpriced players are never starters.
- (c) Roster capacity: `size_after = size_before − matched_outgoing + incoming`. Picks never count; an unknown cap gives `overLimitAfter is None`.
- (d) Ledger conservation: per-team raw given and received sum to equal totals; every asset is routed once.
- (e) Slot eligibility: an exhaustive enumeration proving FLEX ⊆ SUPER_FLEX and other lattice relations, with `lineup_position` and frontend parity unchanged.

**Data.** Synthetic only.

**Compute.** Hypothesis `max_examples` tuned to under 30 s per property for L1. A nightly-only profile can use larger budgets.

**Acceptance.** All properties pass at the L1 budget, and any found counterexample is converted into a pinned regression test.

**Rejection.** Flaky properties (nondeterminism) or a runtime that breaks the L1 budget. In that case, fall back to the current seeded tests.

**Rollback.** Delete the dev dependency. Production is untouched.

**Multiplicity / leakage.** Not applicable (deterministic tests).

---

## 13. UNRESOLVED

- KTC, FantasyCalc, Dynasty Daddy, ETR and Rotoviz methodologies could not be verified. Pages are paywalled, returned 404, or show title-only content.
- Some citations are from memory and should be verified before external use: the Kay et al. 2016 and Fernandes et al. 2018 DOIs, and the presence of FantasyPros ECR std-dev columns.
- Whether `data/league_intel/sim_points_model.json` exists on the production box (fitted CVs vs fallback constants) is unknown from the repo.
- The number of archived weeks with kickoff-locked weekly baselines, which POC-1's power depends on, was not counted. That needs box or archive access.
- The UX navigation audit is on an unmerged branch (`claude/ux-nav-audit`, PR #2051), so its UX-P06 status may change.
- Other AMATH lanes may also cover Game Day dependence or calibration. The coordinator should deduplicate AM-FRONTIER-01 and -02 against them.
