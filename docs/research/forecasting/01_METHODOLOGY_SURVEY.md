# 01. Methodology survey: projections, consensus and statistical methods

**Status:** research only, 2026-11-08. No model was trained. Nothing here authorizes a build.

**Evidence labels used in every table**

| label | meaning |
|---|---|
| `[D]` | Documented by the provider or a primary page, retrieved 2026-11-08 |
| `[R]` | Measured in this repository; the file is named |
| `[X]` | External analysis without peer review (blog, thesis, vendor article) |
| `[L]` | Academic literature. Marked `*` when the citation was not re-fetched this session |
| `[I]` | Inference by this author. Treat it as a hypothesis |

Proprietary formulas are not asserted anywhere below. "Not documented" means the search did not find it, not that it does not exist.

## 1. Providers and open-source projects

| source | what it publishes | documented method | not documented; do not assume | cost / access | fit to our stack | how to evaluate |
|---|---|---|---|---|---|---|
| FantasyPros consensus (ECR, consensus projections) | Rank aggregates; aggregated projections | ECR was described as not a plain average (2010 post) `[D]`. Draft accuracy scores a rank by the rolling 3-year points of that rank slot `[D]` | Current ECR weights; how consensus projections combine sources | API free for prototype, $8.99/mo personal, commercial custom `[D]` | Already consumed as ROS **ranks** (`src/ros/sources/fantasypros_ros_*.py`). Projections are GREENFIELD in `config/projections/source_capability_census.json` | Rescore raw stat lines under the league card; compare against other families on the same player-weeks |
| ESPN / Mike Clay | Preseason team and player projections; weekly TD odds on ESPN | Built by Clay by hand, not fully automated; guide has a team section before positions `[D]` | Equations, weights, in-season method | Public PDF on ESPN CDN; Disney terms apply (see `02_`) | LIVE through `src/bdvm/clay_projections.py`. Season horizon only | Season-level MAE by position, per-game, excluding DNP; the AL-3b SEASON horizon |
| PFF | Median weekly projections; grades; charting | 2019 article: team score projections drive volume through game script; team target and carry tendencies set player volume; grades and charting predict efficiency; IDP follows the offense method with more opponent dependence `[D]` | Current method, weights, share formula | Paid; terms bar commercial use and AI training (see `02_`) | Cannot be integrated under standard terms | Not evaluable without a license |
| Footballguys | Staff projections per specialty; a staff consensus `[D]` | Named human projectors `[D]` | How projections are built or combined | Paywalled `[D]` | Not integrated | Not evaluated. Ingestion needs a recorded access path |
| RotoWire | Weekly projections, including through Sleeper `[R]` | Reporting updates projections `[D]` | Model structure (articles paywalled) | Via Sleeper's undocumented endpoint today `[R]` | **The only live weekly family**: every row of a measured week carries `company = "rotowire"` (`src/ros/sleeper_weekly_projections.py`) | AL-3b weekly scorecard (`src/model_registry/projection_scorecard.py`) |
| 4for4 | Rankings derived from projections `[D]` | Rankings use statistical projections under league scoring `[D]` | Model structure | Paid | Not integrated | Not evaluated |
| Establish The Run | Projections, sims, props | Efficiency and play-calling models with analyst adjustments; prop menus narrow player projections `[D]`. A third-party account says 80th/20th percentile sim outcomes define ceiling/floor `[X]` | Formal method; audited accuracy | Paid | Not integrated | Treat as a market-informed family; check its ancestry before counting it as independent |
| Fantasy Football Analytics (`ffanalytics`) | Scraper plus average, robust and weighted crowd | Crowd of scraped sources `[D]`. 2012-16: all three combinations beat every single source each year; simple mean beat robust; weighted about equal to mean; five-year R² .625 `[X]` | Current source list; IDP accuracy | Open source, but upstream site terms still apply | A method template. Do not run its scrapers | Reproduce the combination ladder on our own PIT archive |
| numberFire | Projections (brand under FanDuel since 2015) `[D]` | Claims predictive algorithms; no detail `[D]` | Algorithm; current product status | Unknown | Not integrated | Not evaluable |
| PlayerProfiler | Metric glossary: Opportunity Share, Target Premium, Breakout Age, College Dominator, Expected Fantasy Points, Lifetime Value `[D]` | Definitions at glossary level `[D]` | Model weights behind Lifetime Value and Breakout Rating | Paid | Feature definitions only, and only re-derived from licensed data | Test each feature by ablation |
| FTN | Charting data; DVOA add-on `[D]` | Charting fields are public through nflverse 2022+ `[D]` | Any projection method | CSV listed at $599 and API at $5,000 on an undated vendor page `[D]` | Free route via nflverse is CC-BY-SA | Ablation; `date_pulled` lag must be enforced |
| SportsDataIO (BAKER and Legacy) | Weekly and season projections; IDP | Vendor coverage page names BAKER and a machine-learning Legacy model `[D]`. A search excerpt of a vendor page and a 2022 interview describe 10,000 play-level game simulations and published medians `[X]`; a direct fetch of that vendor page did not render the claim | Features, backtests, white paper | Quote-based; ML input use allowed under license `[D]` | Adapter exists, flag OFF (`src/ros/sportsdataio_weekly_projections.py`) | Family in the ensemble after credential and license check |
| nflverse / nflfastR | PBP-derived EP, WP, CP, xYAC, xPass | xgboost, leave-one-season-out validation, binned calibration error `[D]` | n/a | Free | Direct feature source (`src/nfl_data/`) | Already validated upstream; re-check for our use |
| ffopportunity | Expected fantasy points per play | xgboost on nflverse PBP, trained 2006-2020; code GPL-3, models and data CC-BY-SA `[D]` | League-specific scoring | Free | Baseline for opportunity features; it assumes generic scoring | Compare with a re-derivation that outputs expected stats, not points |
| ffsimulator | Season simulation | Bootstrap resampling on historical rankings and nflfastR data; optimal lineups `[D]` | Exact resampling unit | MIT | Conceptual baseline for sims. Our exact solver stays the owner | Compare team-week CRPS against our sim |
| Williams 2026 (Princeton thesis) | RB/WR/TE weekly | Per-position XGBoost, 32,900 player-weeks 2022-25, 2025 holdout; MAE 2.909 vs ESPN 3.074; blend 2.907; Vegas features dominate importance `[X]` | Scoring format; QB and IDP; peer review | Public abstract | Closest published analog to a bottom-up challenger | Replicate the ladder before trusting the lift |
| TeamRankings BetIQ | Fantasy projections | Team projections first, then player models, with team stats allocated so players add up `[D]` | Weights | Paid | Confirms the additive constraint pattern | n/a |

**Common shape.** Vendors that document anything describe the same sequence: team volume, then player share, then efficiency, with market information and analyst adjustment on top. That sequence is what `05_CANDIDATE_FORMULA_LIBRARY.md` tests. Nobody publishes an audited, league-specific accuracy record that decides the question for us.

## 2. Statistical method families

Sample sizes use a rough rate of about 8,000 RB/WR/TE player-weeks per season (Williams 2026 reports 32,900 over four seasons) `[X]`. The IDP rate is assumed similar `[I]`.

| method | predicts | inputs | key assumptions | sample needs | failure modes | cost | fit to our data | verdict | how to evaluate |
|---|---|---|---|---|---|---|---|---|---|
| OLS / Poisson / NegBin GLM | Rates and counts | Lagged usage, team context | Linear on link scale; stable rates | Hundreds per position | Underfits interactions; scale mismatch across positions | Very low | High. Baseline for every position | **Start here** | MAE, bias vs B1-B3, per position |
| Ridge / lasso / elastic net | Same, wide features | Many correlated features | Sparsity or small effects | Thousands | Unstable selection with correlated features | Low | Good once features exceed about 20 | Challenger. Reject features unstable across seasons | Locked-fold ablation; coefficient stability across seasons |
| Hierarchical / mixed models | Partially pooled rates by player, position, team | Same as GLM with group ids | Exchangeable players in a group | Hundreds of players | Over-pooling stars; wrong grouping (EDGE/LB drift) | Low to medium | **High.** The repo's IDP lift came from shrinkage `[R]` | **Start here** | MAE vs B3; top-N hit; posterior predictive checks |
| Empirical Bayes / credibility | Shrunk mean, Beta-Binomial and Gamma-Poisson rates | Player sample, group mean, group variance | Conjugacy; group prior is right | Tens of players per group | Prior misspecified; ignores role change | Very low | High. `n_prior_*` in `config/bdvm/params_v1.json` are unfitted priors `[R]` and are estimable | **Start here.** Efron-Morris 1975*, Brown 2008* `[L]` | MAE vs B2, B3; compare fitted kappa with priors |
| Full Bayes (HMC / NUTS) | Posterior of hierarchical rates and uncertainty | Same as EB, with explicit priors | Priors and sampler valid | Same as EB, plus compute | Divergences; false confidence from a mis-specified likelihood | Medium to high | Low now. The sampler proves mixing, not prediction | Reject as a default. Consider only if EB fails posterior checks | Log score vs EB on held-out weeks |
| GAM | Smooth age, usage and time effects | Age, pick, volume | Additive smooth effects | Thousands | Tail extrapolation; survivorship in age curves | Low to medium | High for aging, rookie and pick curves | Challenger for career work | Held-out cohorts; partial-effect plots; compare with delta curves |
| Time series / state space | Latent weekly level; change points | Weekly usage or points | Slowly moving latent state | 6+ weeks per player | Lag; false breaks; label delay | Low | Medium. EWMA is the bar. BOCPD only if it beats EWMA in flagged weeks | EWMA first, BOCPD second. Glickman-Stern 1998*, Adams-MacKay 2007* `[L]` | Next-week usage MAE vs EWMA, in flagged weeks and overall |
| Boosting (XGBoost, LightGBM) | Point, quantile | Wide features | Stationary conditional mean; no temporal leakage | 10k+ rows | Leakage; extrapolation at the extremes; fits noise when signal is weak | Medium | Medium. Good challenger once PIT features exist | Challenger. Must beat the hierarchical GLM | Must beat hierarchical GLM on PG3; permutation tests for leakage |
| Survival / hazard | Time to lost startable status, games missed | Age, usage, injury history | Censoring is non-informative | Many careers; only a few cohorts per decade | Informative censoring through retirement; competing risks | Low to medium | Medium. `src/bdvm/survival.py` runs on priors only `[R]` | Research. Discrete-time logit first | Brier and concordance on held-out draft cohorts |
| Quantile / distributional | Predictive distribution | Point model plus residuals | Residual model holds by position | Thousands | Crossing quantiles; thin tails; overconfidence | Low to medium | **High value.** Fallback CVs are shown too narrow `[R]` | **Start here.** Hurdle-lognormal or NegBin before NGBoost (Duan 2020*) | CRPS and exact-acceptance coverage vs D0 |
| Simulation | Team, week, season outcomes | Marginals, correlation, rules | Marginals are calibrated | n/a (depends on marginals) | Precise nonsense from miscalibrated inputs | Medium | Exact solver exists (`src/ros/lineup.py`) | Keep. Fix marginals before adding dependence | Team-week CRPS, energy score, playoff reliability when outcomes exist |
| Stacking / combination | Blend of families | Family forecasts, PIT labels | Enough history to estimate weights | Many weeks of forecasts | Estimated weights lose to equal weights (combination puzzle) `[L]` | Low | Only when two or more independent weekly families have archived history | **Equal weights first.** Yao 2018 stacking needs real history | Weight stability; lift over E0 on held-out weeks |
| Calibration (isotonic, recalibrated quantiles, conformal) | Corrected probabilities and intervals | Past forecasts, outcomes | Exchangeability, which fails week to week | Hundreds of events minimum | Coverage drift; wide useless intervals | Low | Needed everywhere. Report empirical coverage, never a guarantee (Barber 2023, Gibbs-Candès 2021) | **Start here** with rolling residual quantiles | Reliability tables, coverage and width by position and week |

**Rejected for now** (agrees with `docs/research/amath/SITEWIDE_PROJECTIONS_2026-11-01.md`): HMC-based model averaging over one weekly family, EVT for IDP splash, causal DML for matchups, vine copulas and normalizing flows on uncalibrated marginals. Rejection reasons are data and identification, not taste.

**Expectation for each method against a strong baseline** `[I]`. Most of these will not beat equal-family consensus at offense means. Their defensible value is in (a) distributions, (b) IDP, (c) categories vendors do not publish, and (d) availability. A method that cannot beat the baseline in `07_EVALUATION_DESIGN.md` is dropped.

## 3. What the evidence currently supports

| # | claim | evidence | strength | consequence |
|---|---|---|---|---|
| 1 | Averaging sources beats any single source | FFA 2012-16, offense, season level `[X]`; combination literature, Stock-Watson 2004* `[L]` | Moderate; informal, and old in NFL terms | Equal-family mean is the bar |
| 2 | Weighted averages rarely beat equal weights | FFA weighted about equal to mean `[X]`; Smith-Wallis 2009 attributes this to weight-estimation error `[L]` | Strong in general | Do not learn weights from a few weeks |
| 3 | A public-data model can match a major provider narrowly | Williams 2026: 5.4% MAE edge, RB/WR/TE only, one holdout year `[X]` | Weak | Worth testing; do not assume |
| 4 | Fundamentals from history alone lose to the market on near-term ordering | BDVM proxy tier: within-position Spearman −0.266 vs rebuilt market, Holm p 0.006 (`docs/valuation/idp_accuracy/G_ACCURACY.md`) `[R]` | Strong, for this proxy on six weeks | Independent-only is not the answer for ordering |
| 5 | Shrinkage gives the IDP lift; opportunity extras do not | M2 beats naive mean by 0.36-0.50 pts/player-week; opponent, injury-replacement terms ≈ 0 or harmful (`docs/projections/IDP_OPPORTUNITY_CHALLENGERS_RESULTS_2026-11-01.md`) `[R]` | Moderate; champion was weak | Shrinkage first, signals only if they earn it |
| 6 | Simple team-level forecasts beat the served sim | CRPS 69.0 vs 29.0-32.0, every holdout week (`docs/league-intelligence/TEAM_POINTS_CALIBRATION_RESULTS_2026-11-08.md`) `[R]` | Moderate; 48 team-weeks | Fix marginals and scale before complexity |
| 7 | Usage persists, efficiency largely does not | RB targets/game r 0.70, carries/game 0.65, YPC 0.16 (4for4 2012-22) `[X]`; YPC slope 0.28 (Football Perspective) `[X]` | Moderate; informal, consistent | Forecast volume hard, shrink efficiency hard |
| 8 | IDP is forecast less well than offense | Projections least accurate for IDP and DST (Petersen textbook) `[X]`; persistence wk1-6 to wk7-12: QB .38, RB .79, WR .69, TE .56, DL .41, LB .59, **DB .11** (`G_ACCURACY.md`) `[R]` | Moderate | Weekly DB forecasts need wide intervals |
| 9 | External weekly coverage is thin on IDP | Provider projects 56-62% of scoring defender-weeks; bias −1.1 to −1.6 (`SITEWIDE_PROJECTIONS`) `[R]` | Strong | An in-house IDP model has a coverage role even at equal accuracy |
| 10 | Market lines carry much of the weekly signal | Vegas features dominate importance (Williams 2026) `[X]`; ETR uses prop menus `[D]` | Moderate | Team totals are the first feature to test |

## 4. Answer to the owner's question, by target

These are hypotheses for `07_EVALUATION_DESIGN.md` to settle, not findings. "Consensus" today means one family for weekly and effectively one for offense preseason (`src/ros/projection_ensemble.py`, `weekly_league_projections.py`). A true multi-family test is not possible until a second independent family has archived history.

| target | expected best today | why | what would change it |
|---|---|---|---|
| Weekly offense, point | Equal-family consensus, plus market-implied team totals | Evidence items 1, 2, 10 | An in-house family that adds a nonzero stacking weight on held-out weeks |
| Weekly offense, distribution | **Independent** (our residual model on top of consensus) | No vendor exposes a calibrated league-scored distribution; ours can be measured from the archive | A vendor publishing audited quantiles |
| Weekly IDP | **Independent shrinkage model** where vendors are absent; consensus where present | Evidence items 5, 8, 9 | The frozen prospective study (`IDP_OPPORTUNITY_PROSPECTIVE_PREREGISTRATION_2026-11-01.md`) showing PROV wins |
| League-card categories (reception bands, first downs, ST, sack yards) | **Independent** | Vendors do not publish them; `src/nfl_data/reception_shape_projection.py` and `first_down_rate.py` already fill them | n/a |
| ROS | **Hybrid**: consensus or weekly-derived means, in-house availability and depth | ROS is mostly volume, availability and schedule | ROS archive with enough seasons to test |
| Team-level points | **Hybrid with heavy shrinkage** to trailing means | Evidence item 6 | The v2 calibration study |
| Dynasty market value | **External market**. Not a forecasting target | It is the exchange price (`rankDerivedValue`) | Never replaced by a production forecast |
| Dynasty football production | **Independent** survival and aging model as a separately named concept | Vendors publish no multi-year stat forecast | Evidence that market value alone predicts multi-year production better |
| Decisions (start/sit, waivers, streaming) | **Whichever forecast gives best calibrated exceedance probabilities**; often not the lowest-MAE one | IDP shrinkage compresses the top of the cut, CB top-N hit 0.08 vs 0.22 (`SITEWIDE_PROJECTIONS` finding 6) `[R]` | Decision backtests in `07_` |

**Bottom line** `[I]`. A hybrid is the best expected design, but a specific one: consensus for offense means, in-house for distributions, IDP, category gaps and availability, and the market kept as a separate, named input. An independent model alone is unlikely to win at offense means. External consensus alone leaves IDP, distributions and league-specific categories unaddressed.

## 5. Sources (retrieved 2026-11-08 unless marked `*`)

**Providers and open source**
- FantasyPros 2010 post on ECR: https://www.fantasypros.com/2010/10/how-accurate-are-expert-consensus-rankings
- FantasyPros draft accuracy method: https://www.fantasypros.com/about/faq/football-draft-accuracy-methodology/
- FantasyPros API plans: https://www.fantasypros.com/api-data/
- Mike Clay interview: https://www.fantasypros.com/2014/01/most-accurate-experts-mike-clay-interview
- Mike Clay guide: https://g.espncdn.com/s/ffldraftkit/26/NFLDK2026_CS_ClayProjections2026.pdf
- PFF projection logic (2019): https://www.pff.com/news/fantasy-the-logic-behind-pffs-fantasy-projections
- Footballguys projections: https://www.footballguys.com/projections
- 4for4 rankings explainer: https://www.4for4.com/which-rankings-should-i-use
- ETR props page: https://establishtherun.com/betting-player-props-with-etr/
- FFA 2017 update: https://www.r-bloggers.com/2017/03/who-has-the-best-fantasy-football-projections-2017-update/
- Petersen textbook (CC BY 4.0): https://isaactpetersen.github.io/Fantasy-Football-Analytics-Textbook/
- numberFire acquisition: https://www.legalsportsreport.com/3214/fanduel-acquires-numberfire/
- PlayerProfiler glossary: https://www.playerprofiler.com/terms-glossary/
- FTN data page (undated): https://ftnfantasy.com/data
- SportsDataIO NFL coverage: https://sportsdata.io/developers/coverages/nfl
- BAKER interview: https://sbcamericas.com/2022/07/12/dustin-sullivan-sportsdataio-unlocking-new-data-insights-with-the-new-baker-engine/
- BAKER deck: https://sportsdata.io/files/SportsDataIO%20BAKER%20Deck.pdf
- nflfastR models: https://opensourcefootball.com/posts/2020-09-28-nflfastr-ep-wp-and-cp-models/
- ffopportunity: https://ffopportunity.ffverse.com/
- ffsimulator: https://ffsimulator.ffverse.com/
- Williams 2026: https://theses-dissertations.princeton.edu/entities/publication/d6981488-f30c-47ce-8f06-b6c3e98f2578
- BetIQ method: https://betiq.teamrankings.com/fantasy-football/strategy/official-player-projections-created/
- 4for4 RB stability: https://www.4for4.com/2023/preseason/most-predictable-running-back-stats
- Football Perspective YPC: https://footballperspective.com/how-sticky-is-yards-per-carry-from-year-to-year

**Literature**
- Yao, Vehtari, Simpson, Gelman 2018, Bayesian Analysis 13(3): https://arxiv.org/abs/1704.02030
- Forecast combination puzzle overview: https://econweb.ucsd.edu/~gelliott/Combination.pdf
- Romano, Patterson, Candès 2019, NeurIPS: https://mlanthology.org/neurips/2019/romano2019neurips-conformalized
- Gibbs, Candès 2021: https://arxiv.org/abs/2106.00170
- Barber et al. 2023, Annals of Statistics: https://doi.org/10.1214/23-AOS2276
- Lopez, Matthews, Baumer 2018, AOAS: https://arxiv.org/abs/1701.05976
- Massey, Thaler 2013, Management Science: https://repository.upenn.edu/oid_papers/170
- Brill, Wyner 2026 rebuttal: https://arxiv.org/abs/2411.10400v2
- Kuzmits, Adams 2008 summary: https://ngdc.cncb.ac.cn/openlb/publication/OLB-PM-18841077
- Štrumbelj 2014, IJF 30(4), via `implied` vignette: https://search.r-project.org/CRAN/packages/implied/vignettes/introduction.html
- Gneiting, Raftery 2007, JASA 102(477) (citation confirmed through the stacking paper)
- `*` Not re-fetched, standard references: Efron-Morris 1975; Brown 2008 (AOAS 2(1)); Stock-Watson 2004; Smith-Wallis 2009; Glickman-Stern 1998 (JASA 93); Adams-MacKay 2007; Duan et al. 2020 (NGBoost); Chen-Guestrin 2016; Makridakis et al. 2022 (M5, IJF 38(4)); Holm 1979; Diebold-Mariano 1995; Hansen-Lunde-Nason 2011.
