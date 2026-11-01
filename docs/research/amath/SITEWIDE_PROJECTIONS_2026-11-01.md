# AMATH sitewide audit — lane PROJECTIONS (weekly + ROS projections, IDP, Game Day) — 2026-11-01

**Status:** RESEARCH / PLANNING ONLY. No production change, flag, value, route, scoring card, prereg or champion was
touched. Priority is **not** authorization; `docs/EXECUTION_PLAN.md` remains the sole implementation authority.
The IDP prospective preregistration (`docs/projections/IDP_OPPORTUNITY_PROSPECTIVE_PREREGISTRATION_2026-11-01.md` +
`docs/projections/evidence/idp_opportunity/prospective/frozen_params_2026.json`) and the ROS H1 preregistration
(`docs/league-intelligence/ROS_HORIZON_ORDERING_PREREGISTRATION_2026-11-01.md`) are **FROZEN**. Nothing here
amends, re-scores or tunes them. G3 (2026-10-28) **stays FAILED**.

**Builds on, does not duplicate:** `docs/research/ADVANCED_STATISTICAL_METHODS_CHASE_UPSIDE_2026-11-01.md`
(#2053: AMATH-1..10, S1 hierarchical IDP rates, S2 IDP latent role, S3 calibrated intervals) and
`docs/research/ADVANCED_MATHEMATICS_FEASIBILITY_2026-11-01.md`. Where an item below overlaps S1/S2/S3 it is scoped
as the **offense / Game Day / ROS** extension or as an implementation prerequisite, and the overlap is named.

**Evidence labels:** DEMONSTRATED-IN-REPO (file cited), PUBLISHED-EXTERNAL (cited), PLAUSIBLE HYPOTHESIS,
SPECULATION. Opportunity JSON: `docs/research/amath/evidence/projections_opportunities.json`.

---

## 0. The six findings that matter most

1. **Every displayed Game Day probability uses fallback dispersion that the repo's own evidence says is too
   narrow.** `src/ros/game_day_sim.py::_draw_player` → `src/league_intel/sim_calibration.py::PointsModel.draw_from_mean`
   draws `max(0, N(μ, max(0.5, μ·cv)))` with `FALLBACK_CV_BY_POSITION` (QB 0.32, RB 0.55, WR 0.60, TE 0.65, DL 0.55,
   LB 0.45, DB 0.50, K → default 0.55). RPA-F-021 (`docs/audits/RESEARCH_PROMOTION_READINESS_AUDIT_2026-10-25.md`)
   confirms production runs `fallback-constants` because the calibrated artifact was never built. The V3 study
   measured prediction-error CVs of 0.73–1.20 for rosValue-based means
   (`docs/league-intelligence/evidence/sim_calibration_v3/evaluation_v3.json → fits.week{5..8}.V3.cv`). **Caveat:**
   Game Day's means come from weekly provider projections, whose error CV is *probably smaller* than ROS-based
   error — so the V3 number is an upper reference, not the right Game Day value. The right value is **unmeasured**
   (DEMONSTRATED gap; magnitude PLAUSIBLE HYPOTHESIS). The pregame projection archive that would measure it began
   in week 8 (RPA-COL-020).
2. **In-progress uncertainty probably shrinks too fast late in games.** `src/ros/game_day_week.py::_remaining_for`
   sets remaining mean = pregame baseline × remaining_fraction, and the sim then applies the *same* CV to that
   reduced mean, so SD ∝ f. For a sum of roughly independent in-game increments (compound-Poisson scoring), Var ∝ f,
   SD ∝ √f. At f = 0.25 the current SD is **0.50×** the increments-model SD; at f = 0.10, 0.32×
   (arithmetic, `scratchpad/proj/diag.py`). A toy 5-v-5 remaining-player matchup with a 5-point lead at f = 0.25
   gives win 0.966 (current) vs 0.856 (√f) — **illustration only, SPECULATION on real magnitude**. The live
   scorecard (AL-4a) already buckets live predictions by progress, so this is directly testable.
3. **No correlation exists in Game Day draws.** Players are drawn independently. V3-D4 measured
   τ² ≈ 0.0169 for same-roster, same-NFL-team pairs versus ≈ 0.0088 roster-wide (2,646 pairs,
   `evaluation_v3.json → V3-D4_nflTeamCorrelation`, with an inherited-position caveat). Stacks and opposing
   players in the same game are the correlation that exists and the model ignores it (DEMONSTRATED-IN-REPO).
4. **Both scorecards that would tell the owner whether any projection or probability is calibrated are merged
   but unscheduled** (AL-4a `src/model_registry/game_day_calibration.py`, AL-3b
   `src/model_registry/projection_scorecard.py`; RPA-LGI-004 `SHADOW_NOT_RUNNING`). The highest-value item in this
   lane is not a new model; it is running these weekly and gating display wording on their output.
5. **The ROS rosValue aggregate treats "not on this source's list" as missing-at-random.**
   `src/ros/aggregate.py::aggregate` skips any player a source did not rank and averages the sources that did. A
   player absent from a 300-deep list is informatively censored ("worse than 300"), so fringe players covered by
   one generous source are biased upward (PLAUSIBLE HYPOTHESIS; mechanism DEMONSTRATED in code). Together with the
   hardcoded format multipliers (1.15/1.10/1.05/0.95/0.85, `src/ros/parse.py::format_match_multiplier`), freshness
   steps (1.00/0.90/0.75/0.50/0.25) and `rank_to_score`'s dependence on each board's `total_ranked`, none with
   empirical support, this is the input side of the NC-A scale problem the calibration studies found on the output
   side.
6. **MAE-optimal shrinkage is the wrong target for the streaming decision.** The IDP challenger study shows M2
   shrinkage wins MAE but *compresses the top of the cut* (CB top-N hit 0.08 vs C0 0.22,
   `docs/projections/IDP_OPPORTUNITY_CHALLENGERS_RESULTS_2026-11-01.md` lines ~143–146), and the gap decomposition
   shows the optimizer is bound by projection *ranking* of free agents (hindsight +52.7 vs +0.4,
   `docs/waivers/IDP_STREAMING_GAP_DECOMPOSITION_2026-11-01.md` §1). Streaming needs calibrated *exceedance
   probabilities* P(X > roster cut), not a better mean.

---

## (a) Domain inventory

Status vocabulary: LIVE / LIVE-FALLBACK (live but on uncalibrated constants) / FLAG-OFF / RESEARCH / MERGED-UNSCHEDULED
/ FROZEN.

| # | System | Owner `file::function` | Status | Method | Hardcoded constants → empirical support | Missingness | Uncertainty | Validation / PIT | Consumers | Known defects / failed gates |
|---|---|---|---|---|---|---|---|---|---|---|
| D1 | Weekly league-scored projections | `src/ros/weekly_league_projections.py::load_weekly_projections` (`_build`, `_ensemble`) | LIVE | Source precedence (Sleeper/RotoWire → FPTrack filler) + census ancestry exclusion; ≥2 independent families → `equal_family_mean`, else `single_family_passthrough`; scored by `scorer.score_stat_line`; first-down bonus imputed (`first_down_rate.imputed_sleeper_first_down_bonus`) | `FETCH_TTL_SECONDS 900` (ops); `INJURED_OUT_STATUSES` (rule) → NONE needed | Explicit states `projected/bye/injured_out/unprojected`; bye only when the schedule proves it — **exemplary** | None (point only) | AL-3b scorecard exists but is unscheduled; 2026 provider audit in gap decomposition | IDP streaming solver, Waiver Advisor | Provider projects only 56–62% of scoring defender-weeks; IDP bias −1.1 to −1.6; DL slope 0.72 (gap decomposition §1). In practice one family (FPTrack declares RotoWire as constituent) |
| D2 | RotoWire-via-Sleeper adapter | `src/ros/sleeper_weekly_projections.py` (`lock_baseline_at_kickoff`, `build_weekly_observations`) | LIVE | Fetch + kickoff lock + rescoring | none | Placeholder rows refused | none | Temporal lock is the PIT guard | D1, J1, AL-3b | Weeks 1–2 2026 pregame projections permanently lost (RPA-COL-020) |
| D3 | ROS full-season projection ensemble | `src/ros/projection_ensemble.py::combine_ensemble`, `build_ros_full_season_ensemble` | LIVE (feeds BBLI means per V3 C2.3) | `equal_family_mean` / `median` / `trimmed_mean` over Clay + IDP Show; no weights by design | No weights (good). Default source tuple of 2 | Absent family = not a vote | `proj_high/low` carried, not used | AL-3b SEASON horizon (unscheduled) | BBLI (`roster_intel/best_ball_utility`), Universal Player Profile | Offense is effectively single-family (IDP Show is IDP-only), so "ensemble" is passthrough for offense |
| D4 | Clay / IDP Show snapshots | `scripts/fetch_clay_projections.py`, `scripts/fetch_idpshow_projections.py`, `scripts/refresh_bdvm_projections.py`, `data/bdvm/projections/` | LIVE (weekly timer) | PDF/sheet parse → immutable snapshots; supersede-merge | `vocabulary_dominated_weight_mult` (labelled PRIOR, `config/bdvm/params_v1.json`); tackle solo share 0.62 → NONE found | Unprojected → BDVM `unpriced` | none | Snapshot `asOf` lets AL-3b score only later weeks | BDVM, D3 | Preseason horizon only; no in-season update from the provider |
| D5 | ROS rank aggregate (`rosValue` 0–100) | `src/ros/aggregate.py::aggregate`; `src/ros/parse.py::rank_to_score`, `format_match_multiplier`, `freshness_multiplier` | LIVE | Log rank curve `100·(ln(N+1)−ln r)/ln(N+1)`; weighted mean of available sources | Format 1.15/1.10/1.05/0.95/0.85; freshness 1/.9/.75/.5/.25; `VOLATILITY_THRESHOLD 18`; quintile tiers → **NONE** | Source absence skipped (MAR assumption; informative censoring ignored); `rank_to_score` returns 0 for invalid but 0-scores are skipped (OK) | `sourceStddev`, `confidence` composite (heuristic) | NC-A study (below) | team strength, power, direction, tags, playoff presim, gameplan targets, droppability (see ROS results §2 table) | IDP/offense scale mismatch (D = 0.870 [0.797, 0.952], IDP slope 0.52); DraftSharks basis step 2026-09-16; `total_ranked` dependence; DraftSharks `projection_value` parsed but deliberately not consumed |
| D6 | ROS scale calibration research (NC-A) | `src/ros_calibration/{conversion,metrics,par}.py`, `scripts/ros_scale_calibration_study.py` | RESEARCH; H1 prereg FROZEN | C0 one scale; CG group; CF family; CR family rank curve | Frozen fits `fits_week8_frozen.json` blob `cbed086e…` | `in_population` rule | Player-cluster bootstrap B=2000 | Rolling-origin holdout wk 5–7; prospective P1/H1 from wk 8 | none (research) | **G3 FAILED** (all challengers); CR best MAE (ΔMAE +0.266 [+0.126, +0.404]); CF missed G5 by 0.0006 |
| D7 | Sim points model | `src/league_intel/sim_calibration.py::PointsModel` (`draw_from_mean`, `mean_points`, `load_points_model`) | LIVE-FALLBACK | Truncated Gaussian, mean = rosValue/2.7 or supplied points mean, SD = max(0.5, μ·cv_pos) | `FALLBACK_ROS_VALUE_PER_POINT 2.7`, CVs 0.32–0.65, default 0.55 → **contradicted** by v1/V3 (served F realized/predicted 1.44; pooled PIT 80/95 coverage 0.44/0.62) | n/a | Per-position CV only; no correlation | v1/v2/V3 studies; **V3 failed SC-G1, SC-G4, V3-G6, V3-G9** | Game Day sim, playoff sim, forecast archive, trade impact | RPA-F-021; V3 KS gate has 0.2% pass rate even for a perfect model at week-7 n (disclosed OC) |
| D8 | Realized points | `src/nfl_data/realized_points.py::compute_weekly_points`, `host_stat_line`, `sleeper_stat_line_from_row` | LIVE | Translates provider columns to host stat line, then **delegates** to the scorer | Column maps (factual) | `gp`, unpublished category ≠ zero (AL-3b rules) | none | n/a | BDVM actuals/baseline, AL-3b, league comparison | none found; KEEP |
| D9 | Host-native scorer | `src/league_intel/scorer.py::score_stat_line` | LIVE | Pure dot product over stat ∩ card | none | Absent key = not scored | none | 1,415/1,415 (2025, `SCORING_VALIDATION.md`); 4,275/4,275 within 0.02 (2026 wk 1–7, ROS results) | everything | none; **KEEP** |
| D10 | BDVM in-season blend | `src/bdvm/ros.py::blend_ros_mu`, `ros_projection_weight` | LIVE (`bdvm_engine` ON) | Credibility blend w = n₀/(n₀+weeks) | `n_prior_offense 6`, `n_prior_idp 8` (`config/bdvm/params_v1.json`, "priors, not validated truth") → **NONE** | Unplayed weeks ROS drop via `current_week` | σ shrinks by √w_prior | `tests/bdvm/test_inseason.py` (mechanics only) | `/api/bdvm/*`, Fund-gap column, BDVM alerts | n₀ is estimable (Bühlmann: n₀ = E[within-player variance] / Var[true means]); never estimated |
| D11 | BDVM ROS value | `src/bdvm/ros.py::ros_value` | LIVE | Σ P(active)·E[max(0,X−R)]·playoff weight, Normal X | `playoff_weight` param | `p_active` | Normal σ | Engine parity tests vs reference fixture | BDVM surfaces | Normal assumption; σ priors |
| D12 | Projection scorecard (AL-3b) | `src/model_registry/projection_scorecard.py`, `scripts/projection_scorecard.py` | MERGED-UNSCHEDULED | Pregame vs realized, exact card, per-stat; cohorts by provider/vintage | `MIN_N`, `STAT_CORRECTION_SETTLE` | Exemplary (did_not_play, outcome_missing, unpublished category) | Point error only | Temporal guard pinned by tests | Model Lab (when run) | No scorable week until the archive (week 8+) exists (RPA-LGI-004) |
| E1 | IDP opportunity challengers | `src/ros/idp_opportunity/{model,features,evaluate,leakage,prospective,sources}.py` | RESEARCH; prospective params FROZEN | C0 expanding mean; M1–M5 shrinkage κ (vol/splash/opp), snaps, injury β, opponent | κ grid per week (`backtest_2026-11-01.json → diagnostics.weeks.*.params`) — fitted, PIT | Leakage guard module; FTN lag tracked | 80% intervals cover 0.76–0.81 (slightly narrow) | 2025 + 2026 wk 3–7 retrospective; prospective wk 9+ | none (shadow) | Lift is shrinkage, not opportunity signals; top-N hit compressed; **no genuine pre-kickoff provider archive** in retrospective (`preKickoffArchive.captures 0`); identity census: 218 EDGE→LB, 652 subgroup unknown |
| E2 | IDP streaming projection input | `src/waivers/streaming_solver.py` reading D1; diagnostics `src/waivers/streaming_gap_attribution.py`, `streaming_point_in_time.py` | LIVE solver / RESEARCH diagnostics | Exact optimizer on point projections | Guards are policy | Unprojected candidates excluded (correct, but 38–44% of scorers invisible) | none | Backtest + gap decomposition | Waiver Advisor (MD-7/8) | Forecast-quality gap (finding 6) |
| J1 | Game Day estimates | `src/ros/game_day_estimates.py::resolve_game_day_estimates`, `_combine_families`, `_preseason_by_id` | LIVE | Weekly RotoWire-via-Sleeper (`BASIS_WEEKLY`), ensemble if ≥2 families, else preseason full-season per-game fallback | none | `WEEKLY_*` status vocabulary; unpriced reported | none | AL-3b (unscheduled) | J2, J3, matchup_intel | Preseason fallback mixes horizons without a variance penalty |
| J2 | Game Day live remaining | `src/ros/game_day_week.py::_remaining_for`, `_wall_time_fallback_remaining`; live state `src/nfl_data/live_game_state.py` (+ BALLDONTLIE shadow / SportsDataIO) | LIVE (`game_day_live_game_state` LIVE) | remaining = pregame baseline × observed remaining_fraction; degraded wall-time linear decay | `_ASSUMED_GAME_DURATION_SECONDS 3.25 h`, `LIVE_STATE_MAX_AGE_SECONDS 180` (3× poll rule) → rule-derived, no measurement | Unknown progress → `None` with reason, never 0 — **exemplary** | None (mean only) | none | J3 | No in-game information beyond clock: a player with 0 snaps at halftime keeps half his projection until marked inactive |
| J3 | Game Day league-week sim | `src/ros/game_day_sim.py::simulate_league_week`, `_draw_player`, `_team_assignment`, `_threshold` | LIVE-FALLBACK | 10,000 joint league draws (seed 20260910); best-ball exact lineup per draw; median threshold from each draw's own league scores | `DEFAULT_DRAWS 10000`, `DEFAULT_SEED`; median semantics verified for even leagues (`MEDIAN_SEMANTICS_VERIFICATION.md`) | States completed/in_progress/not_started/inactive/unknown; unknown excluded and reported | D7 dispersion; independence | AL-4a (unscheduled) | Game Day UI, matchup_intel, leverage, median race | Findings 1–3; truncation at 0 inflates the mean by 0.0–1.7% at fallback CVs, 3–14% at V3-measured CVs (`diag.py`); no "uncalibrated" label found in `matchup_intel.py`/`game_day_live.py` by grep |
| J4 | Game Day calibration scorecard (AL-4a) | `src/model_registry/game_day_calibration.py::evaluate`, `reliability` | MERGED-UNSCHEDULED | Brier, reliability by bucket; cohorts by model version × state (pregame / live progress buckets / decided) | `MIN_EVENTS`, `LIVE_PROGRESS_EDGES` | Missing probability never imputed; ties apart | No interval claimed | Strict temporal guard | Model Lab, private learning store | Not run (RPA-F-029) |
| J5 | Playoff / title sim (adjacent) | `src/ros/playoff_sim.py`, `src/public_league/playoff_odds.py` | LIVE-FALLBACK | rosValue/2.7 presim + D7 | as D7 | posted-weeks certainty rules | D7 | v1/v2/V3, D11 harness | Power, Pick Forecast, public odds | V3: level bias does not move odds; per-family relative error and spread do (title odds Δ up to 0.10) |

Count: **21 systems** (D1–D12, E1–E2, J1–J5, plus the J2 live-state providers folded into J2).

---

## (b) Ten-principle screen (Projections / IDP / Game Day)

Order in every row: **current champion → strong simple baseline → advanced challenger**.

| # | Principle | Credible application here | Limitation | Simpler competitor that must be beaten | Verdict |
|---|---|---|---|---|---|
| 1 | Bayesian / epistemic uncertainty (BMA, HMC vs conjugate/EB) | Posterior over BDVM `n_prior` and per-position weekly CV; BMA only if ≥3 independent weekly families exist | D1 has one effective weekly family; D3 has one offense family. BMA over one model is meaningless. HMC proves sampling, not prediction | Conjugate Normal–Normal credibility with EB-estimated n₀ | **E** (EB n₀, AM-PROJECTIONS-08). **REJECT** HMC/BMA for weekly now |
| 2 | Hierarchical partial pooling | Shrink per-player weekly residual variance toward position; offense extension of S1 (target share, carries) as Gamma–Poisson / NB rates | S1 already owns IDP; offense providers already embed usage. A partially pooled *variance* model is the under-served half | Position-level CV from the pregame archive | **E** (pooled dispersion feeds AM-01) |
| 3 | Causal (SCM, DML/TMLE) | "Does an opponent's pass rate cause DB tackles?" | Not identified: game script, coordinator and injury confounders are unobserved PIT; M4 opponent increment ≈ 0 already | Descriptive conditional means | **REJECT** for this lane |
| 4 | Nonstationarity / latent state | Role Change Radar (offense + IDP): BOCPD or 2-state HMM on snap/route/target share | S2 owns IDP; label lag (snap counts land post-game); false-break cost | EWMA, last-3 mean, and the existing ROLE feature | **N** (AM-PROJECTIONS-09); Particle MCMC **REJECT** |
| 5 | High-dimensional sparsity | Feature selection for offense role/usage nowcasts | Few PIT features available; n per position-week small | Elastic net with locked-fold ablation | **DEFER** (P3) |
| 6 | Multivariate / tail dependence | Game-level shocks in Game Day (QB–pass-catcher, same-game opponents, shared tackle pool) | Marginals are not yet calibrated; copulas on top of miscalibrated marginals add confident error | One Gaussian team-game factor (variance-components) fitted from residual pairs, per V3-D4 | **E** (AM-PROJECTIONS-03); vines/flows **REJECT** now |
| 7 | Extreme value theory | IDP splash (INT/FF/TD) ceilings | ~4–6 weeks × hundreds of defenders but splash events are rare per player; threshold exceedances too few for stable GPD shape; hurdle counts already capture it | Hurdle/zero-inflated count model with empirical quantiles | **REJECT** (AM-PROJECTIONS-17) |
| 8 | Conformal / calibration | Intervals on weekly points; recalibrating Game Day win/median probabilities | Exchangeability fails (weekly drift, within-player dependence, schedule). Probability recalibration (isotonic/Platt) needs ≥ hundreds of matchup events; we have ~6–12 per league-week | Rolling empirical residual quantiles by position; Brier/reliability from AL-4a | **E/N** (AM-04, AM-05); use weighted / time-series conformal (Barber et al.) only as challenger, reporting empirical coverage, never a guarantee |
| 9 | Nonignorable missingness | (i) players with no projection who score (38–44% of scoring defender-weeks); (ii) ROS rank censoring beyond list depth; (iii) post-kickoff timestamps (already guarded) | Not identified from observed data alone; needs sensitivity bounds | Explicit two-stage P(projected) × production with indicators; pattern-mixture sensitivity | **N/E** (AM-10, AM-06). This is the biggest under-modelled principle in the lane |
| 10 | Decision theory / DRO | Rank streaming adds by P(X > cut) and expected lineup gain under the exact solver; CVaR for risk-averse matchups | Needs calibrated distributions first; Wasserstein radius unvalidated | Scenario Monte Carlo through the existing exact solver | **N** (AM-11); Wasserstein **DEFER** (#2053 S4 owns) |

---

## (c) Replacement matrix (R)

| ID | Replace | With | Why | Gate |
|---|---|---|---|---|
| AM-PROJECTIONS-01 | Fallback CVs (0.32–0.65) in `PointsModel` for **Game Day** draws | Position CVs (optionally shrunk per player) measured from pregame-archive weekly-projection residuals, refit weekly from PIT data only | RPA-F-021 + V3 evidence that fallback dispersion is too narrow; weekly residual CV is the right quantity and is unmeasured | Player-level PIT coverage / CRPS on held-out weeks, then AL-4a Brier non-inferiority |
| AM-PROJECTIONS-02 | SD ∝ remaining mean for in-progress players | SD ∝ √(remaining fraction) (compound-increment model), or a fitted exponent γ in SD ∝ f^γ | Late-game overconfidence (finding 2) | AL-4a live-bucket reliability; γ fitted on earlier weeks only |
| AM-PROJECTIONS-14 | Truncated Gaussian weekly distribution | Hurdle (P(≈0)) × lognormal/gamma for positives; allow offense negatives | Truncation biases means upward at realistic CVs (+3–14% at V3 CVs); real weekly distributions are right-skewed with mass near 0 (K, TE, IDP) | Log score / CRPS vs truncated Gaussian on the same marginals |
| AM-PROJECTIONS-07 | Hardcoded ROS format/freshness multipliers | Leave-one-source-out evaluation; simplify to equal weights if no measured gain | No empirical support; multipliers can amplify basis steps | ROS-horizon realized points ordering on prospective weeks (separate prereg; must not touch H1) |

## (d) Enhancement rows (E)

| ID | Enhance | Mechanism | Overlap |
|---|---|---|---|
| AM-PROJECTIONS-03 | Game Day joint draws | One shared N(0, τ²_game) multiplicative factor per NFL game side plus a smaller same-team factor; τ² from residual pair covariance (V3-D4 method) | #2053 S6 (generic); this is the concrete Game Day minimal version |
| AM-PROJECTIONS-05 | AL-3b scorecard | Schedule weekly; add PIT histogram, 50/80/90% interval coverage, CRPS by position × provider × state (projected vs unprojected) | #2053 S3 (method); this is the plumbing |
| AM-PROJECTIONS-06 | ROS aggregate missingness | Treat absence from a list of depth N as rank > N: impute via the curve's tail expectation conditional on > N, with a sensitivity band; shadow field only | NC-A input side |
| AM-PROJECTIONS-08 | BDVM `n_prior` | Bühlmann/EB: n₀ = E[s²_within] / Var̂(true per-game means), per position, multi-season nflverse, scored by the host card | none |
| AM-PROJECTIONS-13 | Family disagreement → uncertainty | When ≥2 independent weekly families exist, inflate player SD by between-family dispersion (lineage-aware) | #2053 AMATH-7 (BMA) — this is the cheap version |

---

## (e) New capability concepts (N)

1. **Calibration receipts on every probability (AM-PROJECTIONS-04).** *User problem:* "Win Matchup 82%" reads as
   fact. *Mechanism:* schedule AL-4a weekly; each displayed probability carries a state badge
   `unverified | failing | tracking (n events, Brier, reliability slope)` from one descriptor owner (the
   `calibrationState` design in SIM_CALIBRATION_V3_RESULTS C3). *Data:* `generations.jsonl` already collected.
   *Advantage:* trust; prevents overclaiming while dispersion is fallback. *Why existing features do not solve it:*
   the scorecard exists but no surface reads it. *Competitors:* FiveThirtyEight-style reliability pages exist
   publicly; fantasy apps rarely show them (novelty uncertain).
2. **Weekly automated learning report (AM-PROJECTIONS-05).** One private report per finalized week: projection
   error and calibration by position/provider, Game Day reliability, CR P1 status (reading the frozen evaluation
   outputs only, never refitting), IDP prospective status, biggest misses with reasons (unprojected, injury, role).
   Reuses AL-3b/AL-4a/learning receipts. Novelty: low externally, high internally.
3. **Role Change Radar (AM-PROJECTIONS-09).** *User problem:* role changes (RB1 injury promotion, WR2 route share
   jump, LB going three-down) are visible in usage before projections catch up. *Mechanism:* per player, Bayesian
   online change-point detection (Adams & MacKay 2007, PUBLISHED-EXTERNAL) on snap share / route participation /
   target share (offense, `src/nfl_data/usage_windows.py`, `opportunity_stats.py`) and snap share (IDP, S2 owns the
   model; the radar is the shared surface). Output: "role change probability" + direction + weeks of evidence, shown
   only once calibrated. *Baseline to beat:* |last-week share − 3-week mean| > threshold; EWMA. *Measurable
   advantage:* next-week snap-share MAE and points MAE in the flagged subset; precision@k of flags. Competitors:
   many sites show snap trends (novelty: the calibrated probability + abstention, moderate).
4. **Projection Blind-Spot Map (AM-PROJECTIONS-10) — genuinely original in this repo.** *User problem:* 38–44% of
   defender-weeks that score were never projected, so the streaming optimizer cannot see them. *Mechanism:* model
   the provider's coverage as a selection process: P(projected | features) and production | (played, features),
   fit with explicit missingness indicators; surface players with high P(score ≥ roster cut) among the unprojected,
   labelled "not projected by provider — model estimate", with a pattern-mixture sensitivity band (δ-shift on the
   unprojected group). *Data:* Sleeper weekly stats, snap counts, provider rows (all PIT in the archive from week 8).
   *Why not existing:* D1 correctly refuses to invent a number; E1 forecasts players with history but is not framed
   around provider non-coverage. *Advantage target:* recall of free-agent defenders who beat the 9th-best rostered
   starter. Novelty: uncertain externally; not found in repo.
5. **Exceedance Board for streaming (AM-PROJECTIONS-11).** Rank free agents by calibrated P(X > the team's own
   marginal starter's distribution) and expected lineup gain via scenario draws through the exact solver — not by
   mean. Fixes the shrinkage-compresses-top-N problem without abandoning shrinkage for the mean. Depends on #2053 S3
   calibration.
6. **Live usage nowcast (AM-PROJECTIONS-12).** In-game Bayesian update of a player's remaining rate from observed
   snaps/targets/tackles so far (Gamma–Poisson on events per play with the pregame projection as prior, play count
   from live state). *BLOCKED* on whether live providers expose per-player in-game usage under current access
   (`docs/game-day/SOURCE_ACCESS_EVIDENCE_2026-09-25.md`, BALLDONTLIE evaluation).
7. **Calibrated matchup win probability** is not a new capability; it is AM-01 + AM-02 + AM-03 + AM-04 together,
   scored by AL-4a.

---

## (f) KEEP / REMOVE / REJECT

**KEEP**
- `src/league_intel/scorer.py::score_stat_line` — exact, validated 1,415/1,415 and 4,275/4,275. No math to add.
- `src/nfl_data/realized_points.py` delegation to the scorer — single owner preserved.
- Game Day state machine (`game_day_sim._draw_player`, `game_day_week._remaining_for`): completed = banked, no draw;
  in-progress = banked + remainder only; unknown progress = `None`, never 0. **This is the correct guard against
  double-counting completed scoring; any challenger must keep it byte-for-byte.**
- Per-draw league-median threshold in `simulate_league_week` (joint, host-verified for even leagues).
- D1 explicit states (`bye` only when proven, `injured_out` only for current week + host status).
- `projection_ensemble` closed method set (no learned weights without leakage-safe history).
- IDP M2-style shrinkage as the point champion candidate (evidence-backed) — frozen study decides.
- AL-3b / AL-4a temporal guards and missing-never-zero rules.

**REMOVE / SIMPLIFY (candidates, evidence-gated)**
- ROS format multipliers and stepwise freshness (AM-07): simplify to equal weights unless a holdout shows gain.
- Fallback CV table as a *served* Game Day dispersion once a measured replacement passes (AM-01).

**REJECT (now)**
- EVT/GPD for IDP splash games (AM-17): too few independent exceedances per player; hurdle counts suffice.
- Causal DML/TMLE for matchup or opponent effects (AM-18): no identification; M4 increment ≈ 0 already.
- HMC/NUTS BMA over weekly sources: one effective family.
- Particle MCMC / switching nonlinear state-space for roles: start with BOCPD/HMM (agrees with #2053 S2).
- Vine copulas / normalizing flows in Game Day: marginals uncalibrated; n of game clusters small.
- Exact conformal coverage claims on weekly NFL data (exchangeability fails); report empirical coverage only.

---

## (g) Proof-of-concept experiments

### PoC-1 — Weekly projection predictive distribution and Game Day dispersion challenger (AM-01, AM-02, AM-14)

**Question.** Does a measured, position-pooled residual dispersion (plus √f remainder scaling) give calibrated
player-week intervals and better-calibrated Game Day probabilities than the fallback constants?

**Model.** For player i, week w, pregame league-scored projection μ_iw (D1/J1, kickoff-locked), realized y_iw
(scorer, only if `gp>0`; DNP handled in a separate availability target):

- Champion F: y ~ max(0, N(μ, max(0.5, cv_pos^F · μ))), cv^F = fallback table.
- Challenger M (log-scale residual): log(y + c) = log(μ + c) + ε, ε ~ N(b_pos, σ²_pos), with σ²_pos estimated from
  all prior weeks (expanding window) and optional player shrinkage
  σ²_i = (n_i s²_i + k σ²_pos)/(n_i + k), k chosen on training weeks only; c = 1 (fixed in advance).
- Challenger H (hurdle): P(y ≤ 0.5) logistic in log μ and position; positive part as M.
- In-progress remainder: R ~ same family with mean μ·f and SD scale f^γ; γ ∈ {1 (current), 0.5 (increments)},
  γ fixed at 0.5 for the primary test (no tuning on evaluation weeks).

**Data / PIT cutoff.** Pregame projection archive (week 8 onward, RPA-COL-020) selected by
`lock_baseline_at_kickoff`; realized via AL-3b's proven-final rule (host state + settle). Training window: weeks
8…w−1 (expanding); evaluation weeks: 10–14 (preregistered before week-10 kickoff, 2026-11-12). 2025 Sleeper
projections may serve as a development set **only** if a genuine pre-kickoff archive exists (current evidence says it
does not: `preKickoffArchive.captures 0`).

**Leakage safeguards.** Kickoff lock; no refit using week w outcomes before scoring week w; parameters frozen per
week with a commit-timestamped receipt (same pattern as `freeze_receipts/`); DNP excluded from the conditional target
and scored separately; stat corrections settled.

**Sample size.** ≈ 21 starters × 22 teams across both leagues is not the population; use all projected players with
position in the card: ≈ 600–900 player-weeks/week in-population (PLAUSIBLE; confirm from the archive). Five evaluation
weeks → ~3,000–4,500 player-weeks; effective n is lower (player clustering) — use player-cluster bootstrap.
Game-level outcomes: ~11 matchups/week across two leagues + 22 median events → ~55 matchups over weeks 10–14:
**underpowered for Brier differences**; team-level is reported, not gated.

**Metrics.** Primary: CRPS (player-week), PIT coverage at 50/80/90 by position. Secondary: log score; interval width
(sharpness); team-week coverage and CRPS (recomputed by re-simulating archived lineups with each dispersion);
AL-4a Brier by cohort (report only).

**Uncertainty / multiplicity.** Player-cluster percentile bootstrap B = 2,000; 3 challengers (M, H, M+γ) →
Bonferroni 98.33% CIs for the primary ΔCRPS.

**Acceptance.** ΔCRPS(F − M) 98.33% CI lower > 0 pooled AND no position with significantly worse CRPS AND pooled
80% PIT coverage within [0.75, 0.85] AND no position outside [0.70, 0.90] AND team-week 80% coverage not worse than F.
γ = 0.5 accepted only if AL-4a live-bucket reliability (late buckets) is not worse and its own player-level remainder
coverage on in-progress snapshots (if archived) improves.

**Rejection.** ΔCRPS CI upper < 0, or coverage improves only with intervals ≥ 1.5× F width and no CRPS gain, or any
position's realized/predicted mean drifts outside [0.85, 1.15] under M.

**Compute.** Seconds per week (closed-form), plus re-simulation of archived league-weeks at 10,000 draws (minutes).

**Rollback / monitoring.** Shadow only; production loader keeps refusing non-promoted artifacts. AL-4a weekly. Any
promotion is an owner decision via the model registry.

### PoC-2 — Role Change Radar, offense (AM-09; extends #2053 S2 to offense, does not touch the frozen IDP study)

**Question.** Does a Bayesian online change-point detector on usage share forecast next-week usage and points better
than simple smoothing, specifically in the weeks it fires?

**Model.** For player i, weekly share s_iw ∈ [0,1] (snap share for RB/TE; route participation or target share for
WR/TE; carries share for RB) from nflverse/FTN PIT feeds (`src/nfl_data/usage_windows.py`). Logit transform
z_iw = logit(clip(s, 0.01, 0.99)). BOCPD with Normal–Inverse-Gamma conjugate segment model, constant hazard
H = 1/8 (fixed in advance; sensitivity H ∈ {1/4, 1/16} reported). Forecast ẑ_{i,w+1} = posterior predictive mean
under the run-length posterior; projected points adjustment = provider μ × (ŝ/s̄_provider-implied) **only in the
research arm**.

**Baselines.** (B0) last-3 mean; (B1) EWMA α = 0.5; (B2) last week. Strong simple baseline is B1.

**Data / PIT cutoff.** Share for week w is available only after week w's games + feed lag (FTN lag recorded in
`backtest_2026-11-01.json → ftnLagDays`); a forecast for week w+1 may use week ≤ w only if the feed timestamp precedes
week w+1's first kickoff. Development: 2023–2025 seasons (nflverse); confirmation: 2026 weeks 10–14 prospective,
preregistered before 2026-11-12.

**Targets.** (T1) next-week share MAE; (T2) next-week league-scored points MAE where a provider projection exists;
(T3) flag precision: P(|s_{w+1} − s̄_{w−3..w−1}| > 0.15 | flag).

**Sample.** Development: ~3 seasons × ~17 weeks × ~400 offensive players ≈ 20,000 player-weeks; flagged subset
maybe 5–10% (SPECULATION). Confirmation: ~5 weeks × 400 ≈ 2,000.

**Validation.** Walk-forward by week; player-cluster bootstrap; per-position report; 3 positions × 2 primary targets
→ Holm correction.

**Acceptance.** Development: BOCPD T1 MAE better than B1 in the flagged subset (CI lower > 0) and not worse overall
(non-inferiority margin 0.005 share); T3 precision ≥ 0.5 at the operating point. Confirmation: same, plus T2 not worse
than provider alone.

**Rejection.** No gain over EWMA in the flagged subset, or gains that disappear when the feed-lag rule is enforced, or
flag precision < 0.35.

**Compute.** Trivial (conjugate updates). **Rollback:** research script + shadow JSON only; no UI until calibrated.

---

## Evidence commands run (read-only, isolated)

- `python -I docs/research/amath/scripts/projections_gameday_dispersion_diag.py <repo-root>`: reads `evaluation_v3.json`; computes truncated-normal mean inflation
  E[max(0,N(1,cv))] − 1, SD ratio f/√f, and a toy two-team live win probability. Script path:
  `docs/research/amath/scripts/projections_gameday_dispersion_diag.py`.
  The toy numbers are illustrations, not evidence about the live system.
- Greps of constants in `src/league_intel/sim_calibration.py`, `src/ros/parse.py`, `src/ros/aggregate.py`,
  `src/ros/game_day_week.py`, `config/bdvm/params_v1.json`.

## Domains not fully evaluated

- `src/ros/forecast_archive.py`, `src/ros/championship.py`, `src/ros/power_v2.py` internals: not read in this pass
  (listed as consumers only).
- Frontend Game Day wording: only a grep of `matchup_intel.py` / `game_day_live.py` for "calibrat"; the React
  surface was not inspected, so "no uncalibrated label" is unconfirmed on the UI.
- Private AL-4a outputs (`data/learning/`) and the pregame archive contents are box-local and were not available.

## UNRESOLVED

- True weekly-projection residual CV per position (needs the week-8+ archive).
- Whether Game Day generations archive per-player banked/remaining snapshots (needed for the γ test at player level).
- Whether live providers expose per-player in-game usage under current access (AM-12).
- Whether CR's prospective P1 confirms (frozen study; reported by its own runner, not here).
