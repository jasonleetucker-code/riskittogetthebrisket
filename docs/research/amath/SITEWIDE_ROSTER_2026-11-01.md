# AMATH sitewide audit — lane ROSTER (waivers/FAAB/streaming, roster construction, draft/rookie, team strength/league intelligence) — 2026-11-01

**Status:** RESEARCH / PLANNING ONLY. No implementation authority, no flag, no value, bid, config, route or
protected-protocol change. `docs/EXECUTION_PLAN.md` remains the sole implementation authorization; the frozen IDP
prospective preregistration and ROS H1 preregistration are untouched; DFS is owner-paused and not studied here.
Priority is not authorization. Machine-readable rows: `docs/research/amath/evidence/roster_opportunities.json`.

**Builds on (never duplicates)** `docs/research/ADVANCED_STATISTICAL_METHODS_CHASE_UPSIDE_2026-11-01.md` (S1–S3, S4
DRO, S6 joint dependence) and `docs/research/ADVANCED_MATHEMATICS_FEASIBILITY_2026-11-01.md` (AMATH-2 multiweek
risk-aware streaming 89/100; matrix row 6 joint season calibration 81; row 7 dynasty hazards 78; row 9 FAAB
portfolio risk 72). Where this lane touches those items it either adds a new codebase finding or changes their
sequencing, and says so explicitly.

**Evidence labels:** `DEMO` = DEMONSTRATED-IN-REPO (file cited); `EXT` = PUBLISHED-EXTERNAL; `HYP` = PLAUSIBLE
HYPOTHESIS; `SPEC` = SPECULATION. No backtest numbers below are invented; every number is either quoted from a cited
repo document or produced by the read-only diagnostic in Appendix A.

---

## 0. Executive findings (lane-specific, ranked by consequence)

1. **The playoff/title simulator omits epistemic team-strength uncertainty** (`DEMO`,
   `src/ros/playoff_sim.py::simulate_playoff_odds` lines ~1640–1650). Each simulated week draws
   `rng.gauss(dist.mean, dist.sd)` independently around a FIXED per-team mean; nothing is drawn once per simulated
   season. Season-total variance is therefore `n·σ_w²` when it should be `n·σ_w² + n²·τ²` (τ² = uncertainty in the
   team's true weekly mean). This makes playoff/title odds — and every consumer (`draftSlotDistribution` → Pick
   Projector → `pick_market` c-shrink; Competitive Posture; FAAB competitive status) — structurally overconfident.
   It is distinct from D11 (double-counted ROS evidence) and from the V3 points-model challenger (player-level
   marginals). Consistent with, not proof of: V3 results record "playoff odds already 0 or 1 for every team after
   week 7" and presim means ranging 117–507 vs realized 200–460 (`docs/league-intelligence/SIM_CALIBRATION_V3_RESULTS_2026-10-27.md` UNRESOLVED).
2. **The calibration GATES themselves are mis-sized** (`DEMO`, same V3 results doc): "a perfectly calibrated model
   passes SC-G4 0.2% of the time and SC-G1 16%" at week-7 family sizes. Any future calibration challenger in this
   lane is unadjudicable until the gate family is size-controlled. This is a P0 evaluation-correctness item, not a
   model item.
3. **Streaming's binding constraint is the forecast, not the optimizer** (`DEMO`,
   `docs/waivers/IDP_STREAMING_GAP_DECOMPOSITION_2026-11-01.md`): relaxing every point-in-time guard moves the
   strict optimizer from +0.40 to +3.71 pts/decision-week; feeding it realized points (hindsight) gives +52.7.
   **Consequence for the baseline:** relaxing every decision-layer guard closes ~17% of the gap to manager B and
   ~6% (+3.3 of +52.3) of the hindsight headroom, so AMATH-2 / S4 (CVaR / Wasserstein DRO streaming) is bounded by
   that small decision-side share; it should be resequenced BEHIND forecast calibration, not ahead. This lane
   downgrades DRO-for-streaming to BLOCKED until a forecast with demonstrated PIT skill exists.
4. **The FAAB market model is fitted on look-ahead-biased joins and is asserted (not fitted) above the all-in line**
   (`DEMO`, `docs/faab-model.md` §9.3: model $0-share 0.6% vs observed 45.8% in the 2100–2600 band). The temporal
   ledger (`HISTORY_FLOOR` 2026-07-14) now makes an unbiased point-in-time join possible for every claim after that
   date, and the correct likelihood for winner-only data (Sleeper never exposes losing bids) is the order-statistic
   likelihood of the observed maximum — not band-quantile matching.
5. **Drop protection is ten PRIOR thresholds with no regret model** (`DEMO`, `config/waivers/streaming_protection.json`).
   A read-only diagnostic on the committed export archive (Appendix A) shows the scraper composite is very sticky
   in-season: P(≥1.5× in 30 days) ≈ 0.8% for composite 1000–1500 (926 non-overlapping pairs, 371 distinct players),
   ≈ 0.2% above 1500, but 8.3% below 1000. That is the empirical shape a regret-calibrated protection rule would be
   built on (proxy only; see caveats).

---

## Score summary (100-point rubric; full rows in the JSON)

| Rank | ID | Cat | Horizon | Total | Title |
|---|---|---|---|---|---|
| 1 | AM-ROSTER-02 | E | P0 | 86 | Component-first calibration ladder with size-controlled gates |
| 2 | AM-ROSTER-01 | E | P1 | 85 | Season-level latent team-strength uncertainty in the playoff sim |
| 3 | AM-ROSTER-03 | E | P1 | 84 | Point-in-time FAAB market refit, winner-censored likelihood |
| 4 | AM-ROSTER-04 | R | P1 | 84 | Uncertainty-derived streaming no-action threshold |
| 5 | AM-ROSTER-06 | N | P2 | 81 | Roster Fragility Index |
| 6 | AM-ROSTER-07 | R | P1 | 81 | Drop-Regret Curve (original) |
| 7 | AM-ROSTER-18 | E | P0 | 80 | Record pre-auction snapshot before the 2027 rookie auction |
| 8 | AM-ROSTER-11 | E | P2 | 77 | Hierarchical monotone rookie hit-rate priors |
| 9 | AM-ROSTER-09 | E | P2 | 76 | Fix pick-slot miscalibration upstream before calibrating c |
| 10 | AM-ROSTER-14 | N | P2 | 75 | Hidden Roster Weakness Detector |
| — | AM-ROSTER-17 | E | P0 | 74 | Fail-closed FAAB config |
| — | AM-ROSTER-05 | REJECT | BLOCKED | 58 | Defer DRO/CVaR streaming (VOI gate) |
| — | AM-ROSTER-20 | REJECT | REJECT | 37 | EVT for FAAB/title tails |

Scores are expert feasibility judgments, not observed model performance.

## (a) Domain inventory

Status vocabulary: LIVE (served), LIVE-PRIVATE (authenticated/flagged-on), FLAG-OFF, SHADOW, RESEARCH, HELD,
OWNER-PROTECTED (owner-approved methodology). "Constants evidence" cites the doc that supports a constant, or NONE.

### F. Waivers / FAAB / streaming

| # | System | Owner file::function | Status | Method | Constants + evidence | Missingness | Uncertainty | Validation / PIT | Consumers | Defects / risks |
|---|---|---|---|---|---|---|---|---|---|---|
| F1 | FAAB objective ceiling | `src/trade/faab_engine.py::resolve_anchors`, `objective_ceiling`, `_smootherstep` | LIVE | Value anchors V_allin (rank = teams × starters) / V_repl (2× line blended 0.5 with 12th-best FA); ceiling = smootherstep(s^2.2) | `toeExponent 2.2` tuned to one 2026-08-04 wire top (`config/trade/faab.json` comment); anchors reproduce two human judgments (`tests/trade/test_faab_calibration.py`); `fallbackAllin 2400 / Repl 1400` NONE | Missing value → no recommendation; fallback anchors if board absent | None (point ceiling) | Anchors human-sanity-checked only; no outcome fit | advisor, `/api/waiver/faab-recommend`, waiver.py | Toe sensitive to V_repl (12.1% vs 5.0% for same player, faab-model §10.1) |
| F2 | FAAB rival market + bid optimizer | `faab_engine.py::_rival_engagement`, `rival_bid_cdf`, `_market_clearing_price`, `optimal_bid` | LIVE | Each rival zero-inflated lognormal, independent; recommended = argmax_b P(win\|b)(rawCeiling − b) (first-price, independent private values) | `engagementBase 0.05/Max 0.7/Exp 0.9`, `rivalSigma 1.1`, share curve 1.5%→45% exp 1.3: "fitted" to 384 claims joined to TODAY's values below all-in only (faab-model §9.3); above-all-in params NONE (asserted); `crowdBlendWeight 0.6`, `crowdWinningBidToRivalMedian 0.53`, `trendingSaturationCount 500` category C NONE | Unknown rival balance → excluded (invariant); in-code defaults diverge from config (faab-model §10.7) | Implicit via CDF; p25/p50/p75 clearing band | `scripts/faab_backtest.py` OLD vs NEW, five stated look-ahead caveats; low-value overbids 166/166 → 0/166 | advisor, waivers UI, Perfect Waivers | Look-ahead join; winner-only censoring not modelled in fit; option value is a scalar PRIOR (0.55→1.0); no budget coupling across simultaneous claims |
| F3 | Crowd comparability | `src/trade/faab_comparability.py` | LIVE | Fail-closed format gate; tiers reported, weight nothing | thresholds measured on live feed 2026-08-18 (`docs/faab-external-market-comparability.md`) | Unknown format → exclude; IDP refused | Tier counts only | Measured exclusion census | F2 market layer | `tep_level` dormant by construction (documented) — KEEP |
| F4 | Live opportunity layer | `src/trade/faab_opportunity.py` | SHADOW (`waiver_live_opportunity`) | opportunity = dynasty + retention × short-term surplus | `retentionFlat 1.0` category D; others category C (faab.json) NONE | events-based | none | shadow log accumulating | none live | Unvalidated by design |
| F5 | Waiver targets (legacy pool) | `src/trade/waiver.py::find_waiver_targets` | LIVE | Unrostered sorted by `rankDerivedValue` | `MIN_WAIVER_VALUE 500`, per-position 6 NONE | unpriced dropped | none | none | advisor (add pool) | Dynasty value is not weekly points; labelled (`advisor.LINEUP_OBJECTIVE`) |
| F6 | Waiver Advisor | `src/waivers/advisor.py` | LIVE-PRIVATE (IST-10) | Composer, decides nothing | `LIST_BID_COMPETITIVE_STATUS "bubble"` | delegates | delegates | composer tests | `/waivers` | KEEP as composer |
| F7 | Weekly IDP streaming composer | `src/waivers/streaming.py` | LIVE-PRIVATE (`idp_streaming`) | Capacity curve k=0..7, multiweek weighted objective, recommendedCapacity rule | `materialityPoints 1.0`, `horizonWeekWeights [1,.85,.72,.61]`, `defaultCapacity 3`, node budgets — all PRIOR (`config/waivers/streaming.json`); node budgets measured for latency | unprojected FA not offered; unpriced never auto-dropped | none (deterministic means) | `streaming_backtest.py` + gap attribution (6 decision weeks, 2026) | `/waivers` streaming tab | Fixed no-action threshold ignores forecast uncertainty; horizon weights not tied to hold survival |
| F8 | Streaming solver | `src/waivers/streaming_solver.py` | LIVE-PRIVATE | Exact branch-and-bound over add/drop sets with Lagrangian bound; lineup via `ros/lineup.py` | node limits; "bounded" labelled with proven gap | delegates | none | 6/6 optimal in base backtest | F7 | KEEP (exactness verified; gap is forecast-side) |
| F9 | Dynasty drop assessment | `src/waivers/drop_assessment.py` | LIVE-PRIVATE | Rule classes protected/conditional/churn from value gap + flags | 10 PRIORs (`churnGapMax 0.15`, `protectGapMin 0.40`, `youngAgeMax 24`, snap thresholds, `valueTrendUpMinRatio 0.15`…) NONE; rationale prose only | unknown inputs BLOCK churn (good) | none | none | F7/F8 | No regret / re-acquisition model; thresholds uncalibrated |
| F10 | Streaming backtest + PIT harness | `src/waivers/streaming_backtest.py`, `streaming_point_in_time.py`, `streaming_gap_attribution.py` | RESEARCH | Paired replay vs hold, cluster bootstrap | prereg `IDP_STREAMING_BACKTEST_PREREGISTRATION_2026-10-29.md` | timestamp classes pre/post/unstamped | bootstrap CIs | n = 6 weeks (2026), 18 pooled | research docs | n tiny; manager-B effect not causally identified |

### G. Roster construction

| # | System | Owner | Status | Method | Constants + evidence | Missingness | Uncertainty | Validation | Consumers | Defects |
|---|---|---|---|---|---|---|---|---|---|---|
| G1 | Exact lineup | `src/ros/lineup.py::solve_optimal_assignment`, `resolve_starter_slots` | LIVE | Exact max-weight transversal-matroid assignment; no greedy fallback | none | `None` ros_value = unassignable (not 0) | n/a | 10/10 vs Sleeper awarded lineups (`docs/lineup/C2_U1_CANONICAL_LINEUP.md`) | everything | **KEEP** |
| G2 | Roster Construction V1 | `src/roster_intel/construction.py` | LIVE-PRIVATE (MD-1/MD-28) | Realized-points attribution via exact solver; host-parity check | `_HOST_TIEBREAK 1e-7` | unobserved weeks excluded with reason | none (descriptive) | parity 84/84 (MD-28) | private tab | Descriptive only; no fragility or forward view (FFBB-2/5 open) |
| G3 | Best-ball utility (BBLI) | `src/roster_intel/best_ball_utility.py::evaluate_trade_utility` | LIVE (trade path) | draw → solve → average; paired seeds; MC SE | `DEFAULT_DRAWS 400`, `AFFECTED_LEP_PP 5.0` NONE | unprojected not seated; coverage partial | MC SE only; **no player correlation, no P(plays) for uncertain** (own docstring) | V3 C2: ordering τ≈0.89 under variance swap | trade simulator, analyze | Independence assumption across players |
| G4 | Marginal contribution | `src/roster_intel/marginal.py` | LIVE | S(R) − S(R∖p) via exact solver | none | inherits | none | unit tests | strength/weakness | KEEP |
| G5 | Team Strength (roster) | `src/roster_intel/strength.py` | LIVE | Meaningful-core marginal strength | none | inherits | none | owner rows 1.1 | terminal, trade | KEEP |
| G6 | Team Weakness / Need | `src/roster_intel/weakness.py` | LIVE | rank thresholds (top-12/24…; IDP slots × teams) | `_SEVERE 2.0`, `_MAJOR 1.0` PRIOR | inherits | none | none | suggestions need source | Point-estimate needs; ignores absence risk |
| G7 | Age portfolio / Young Core Index | `src/roster_intel/age_portfolio.py` | LIVE | value-weighted position-relative age percentile | bands; index status PRIOR (addendum validation not run) | no DOB excluded + coverage | none | not validated | rosters UI | Descriptive; fine as such |
| G8 | Meaningful core | `src/roster_intel/core.py` | LIVE | exact starters + reserve-slot pass | config reserve slots | unpriced excluded | none | owner addendum | G5–G7 | KEEP |
| G9 | Replacement levels (LI-5) | `src/league_intel/replacement.py::measure_endogenous_starters` | LIVE | endogenous flex allocation from exact solves over real rosters | none | inherits | **point estimates only (own KNOWN LIMITATION)** | measured vs even-split (~40% wrong at QB) | FAAB anchors? no (FAAB uses rank line); scarcity | Deterministic thresholds |
| G10 | Cut ladder / ECC | `src/draft/displacement.py::build_cut_ladder` | LIVE | ECC = max(0, base − waiver) × scarcity | scarcity mult `0.85 + 0.30·waiverScarcity` PRIOR | unranked cost 0 + stamped | none | ADR-010 measurements | Perfect Draft, roster_capacity | KEEP; scarcity multiplier NONE |

### H. Draft / rookie

| # | System | Owner | Status | Method | Constants + evidence | Missingness | Uncertainty | Validation | Consumers | Defects |
|---|---|---|---|---|---|---|---|---|---|---|
| H1 | Perfect Draft optimizer | `frontend/lib/perfect-draft.js`, `src/draft/context.py` | LIVE (`perfect_draft`) | Exact cardinality-constrained knapsack over surplus-over-replacement; indifference planMaxBid | none in objective | 0 marketDispersion = UNOBSERVED → p90 | bootstrap P(plan wins), seeded | **Backtest BLOCKED** (`scripts/backtest_perfect_draft.py` exit 2) | /draft | Roster value is unweighted market sum (docs/perfect-draft.md §9) |
| H2 | PD uncertainty inputs | `perfect-draft.js::valueSigmas`, `logPriceDispersion` | LIVE | per-player CV, price log-dispersion shrunk to prior | `PRICE_DISPERSION_PRIOR 0.35`, `defaultCv 0.08`, `singleSourceFloor 0.35`, near-tie 0.25 — NONE | handled | bootstrap | none | H1 | Priors never checked against a realized auction |
| H3 | Rookie-auction curve | `src/draft/rookie_auction/curve.py`, `apportion.py`, `published.py` | OWNER-PROTECTED (decision 2026-10-18) | Workbook formula transcription (decay k clamp 0.03–0.08, 0.6/0.4 blend, floors/caps) + whole-dollar apportionment | owner-approved, parity-pinned; empirical support NONE beyond 3 completed drafts as spine | last-known-good / refuse | none | workbook parity tests | draft capital, auction room, /trade stack note | **KEEP** (methodology owner-reserved) |
| H4 | Batch D promotion | `rookie_auction/promotion.py` | LIVE (policy, dry-run/live switch) | preregistered gates, checksummed policy | `config/draft_valuation/promotion_policy.json` prereg | ERROR_* states | gate-based | BATCH_D prereg | H3 | KEEP |
| H5 | Rookie-draft order | `src/public_league/draft_order.py` | LIVE (owner rule) | reverse record, lower PF tiebreak | owner rule | other leagues UNKNOWN | n/a | doc DRAFT_ORDER_RULE | sim, pick projector | **KEEP** |
| H6 | Pick-market forecast shrink | `src/trade/pick_market.py::owned_pick_forecasts`, `calibrated_confidence` | LIVE | P_used = c·P + (1−c)/3 over tiers; c by Brier grid once ≥24 outcomes/bucket | `PROVISIONAL_CONFIDENCE_CAP 0.5`, `CALIBRATION_MIN_OUTCOMES 24` PRIOR | provisional until calibrated | c shrink | none yet (needs ≥2 seasons per bucket) | generated trades | c compensates post hoc for upstream sim overconfidence (finding 1) |
| H7 | Pick projector | `src/ros/pick_projection.py` | LIVE | slot distribution from sim; mass-window confidence | `CONFIDENCE_HIGH_MASS 0.8 / MED 0.5`, horizon ceilings PRIOR | refusal codes | inherits sim | none | /league picks | inherits finding 1 |
| H8 | BDVM rookie pick outcomes | `config/bdvm/pick_outcomes_v1.json` via `src/bdvm/picks.py` | LIVE (BDVM on) | per-slot p_hit/v_hit/p_mid table | "explicitly the most placeholder-ish table" (file comment) NONE | v_miss ≈ 0 implicit | class_strength [0.85,1.15] | none | /bdvm, /draft BDVM pick panel | Placeholder priors |
| H9 | BDVM aging / hazards | `config/bdvm/params_v1.json` age_curves, base_hazard; `src/bdvm/survival.py` | LIVE (BDVM) | asymmetric Gaussian age curves; stepwise hazards | "priors, not validated truth" NONE | unpriced if no age | sigma widening | engine parity vs reference only | /bdvm | Cross-lane (baseline row 7) |

### I. Team strength / league intelligence

| # | System | Owner | Status | Method | Constants + evidence | Missingness | Uncertainty | Validation | Consumers | Defects |
|---|---|---|---|---|---|---|---|---|---|---|
| I1 | Playoff / title engine | `src/ros/playoff_sim.py::simulate_playoff_odds`, `_compose_team_distribution`, `_bestball_presim` | LIVE; odds labelled uncalibrated (MD-11) | Presim best-ball weeks → (mean, sd); weekly independent Gaussian team scores; exact bracket; adaptive convergence + Wilson CIs | `ROS_BLEND 0.20`, `BEST_BALL_VARIANCE_BUMP 1.10`, `DEPTH_VARIANCE_LIFT_MAX 0.15` NONE; D11 flag `playoff_ros_counted_once` | refusals; unverifiable median rule refused | **MC error only; no team-mean uncertainty** | D11 prereg comparison; V1–V3 calibration studies (fallback measured miscalibrated) | public/private odds, pick projector, posture, FAAB status, trade impact | Finding 1; D11 double count (incumbent); Gaussian collapse of skewed best-ball weeks |
| I2 | Sim points model | `src/league_intel/sim_calibration.py` | LIVE fallback constants | rosValue/2.7, per-position CV | `rosValuePerPoint 2.71 r² 0.63 n 402`; v1 measured fallback biased −94 to −109 team pts | `MIN_SAMPLES 30` | CV clamp 0.15–1.2 | V1/V2/V3 failed gates | I1, BBLI variance, Game Day | V3 best candidate but fails SC-G1/G4/V3-G6/G9 |
| I3 | Team ROS strength | `src/ros/team_strength.py::compute_team_strength` | LIVE | weighted composite | `WEIGHT_STARTING .72 / DEPTH .18 / COVERAGE .05 / HEALTH .05` NONE | fallbacks | none | none | power rankings, I1 ros_z, depth ratio | Unit is a rank-index composite, not points |
| I4 | Power rankings | `src/ros/power_v2.py` | LIVE | 0.30 ROS / 0.30 all-play / 0.15 recent / 0.15 VORP (unavailable) / 0.10 record; evidence τ = 2 games | owner directive 2026-09-22 (target split) | renormalize, never zero | none | none | /league | Weights owner-set; never scored against forward outcomes |
| I5 | Competitive posture | `src/roster_intel/window.py::competitive_posture` | LIVE | PUSH/HOLD/RETOOL/REBUILD; HOLD = flip share of 3×3 perturbation grid | `posture_v1_prior`: deadline sharpen 2.0, deltas 0.08/0.15/0.10/0.25, temperature 0.18 PRIOR | no evidence → HOLD | sensitivity grid, not probabilistic | sweep tests | trade analyze lens, team_impact, FAAB competitive status | Reads overconfident championship odds (finding 1) |
| I6 | Game Day sim | `src/ros/game_day_sim.py` | LIVE | weekly draws, median threshold | shares I2 | — | — | V3 C2 | Game Day | shares I2 issues |

**Count:** 35 systems inventoried (F 10, G 10, H 9, I 6). Not evaluated in depth: `src/roster_intel/partner.py`,
`targets.py`, `packages.py` (trade-partner generation — trade lane), `src/trade/perfect_waivers.py` internals
(dynasty-objective sibling of F8; read only by reference), `src/ros/trade_deadline.py`.

---

## (b) Ten-principle screen (lane domains)

| Principle | Credible application here | Limitation | Simpler competitor (try first) |
|---|---|---|---|
| 1 Bayesian / epistemic | Team-mean uncertainty in I1 (normal–normal posterior per team: prior = presim mean, likelihood = scored weeks); posterior-predictive FAAB market (winner-censored likelihood); rookie hit-rate posteriors | 3 seasons of league history; season-level outcomes ≈ 36 dependent team-seasons | Empirical-Bayes / conjugate closed form — **HMC/NUTS not needed** anywhere in this lane |
| 2 Hierarchical pooling | Team means shrunk toward league; FAAB engagement by value band pooled; rookie p_hit pooled across adjacent slots (isotonic + beta-binomial); aging curves pooled by position | Small groups; monotonicity must be imposed | Method-of-moments shrinkage; isotonic regression |
| 3 Causal | "Does streaming cause points?" — baseline already rejects causal language (confounded by depth/injury) | No identification; n = 6 weeks | Paired descriptive contrasts (already done) — **REJECT DML/TMLE** |
| 4 Nonstationarity / latent state | Team strength drifts with trades/injuries mid-season → local-level Kalman on team weekly mean; FAAB clearing level by phase | Few observations per team-season (≤17) | Exponential smoothing; existing τ=2-game evidence ramp |
| 5 Sparsity | Drop-regret features (age, snap trend, draft capital, value trend) — ≤10 features | Tiny positive class | Logistic with L2 / monotone constraints; trees only if n allows |
| 6 Dependence | Same-NFL-team shocks (V3-D4 τ²≈0.017 vs roster-wide 0.008); bye-week clustering in fragility | Measured correlations are small | **One shared-shock factor**; reject vines/flows here (data cannot support) |
| 7 EVT | FAAB max bids (52–65% observed), title-odds tails | A handful of independent tail observations | **REJECT** — empirical quantiles + order-statistic model |
| 8 Calibration / conformal | Component-level calibration (weekly matchup probabilities, team-week CRPS) where n is hundreds; size-controlled gates; conformal intervals on team-week scores | Weeks within a season are not exchangeable (roster changes); split by season-week blocks | Reliability diagrams + Brier/log score with block bootstrap |
| 9 Nonignorable missingness | Sleeper exposes only WINNING bids (selection on the max); unprojected defenders (provider covers 56–62% of scoring defender-weeks); players who leave the league in aging data | Missing mechanism partly unknowable | Order-statistic likelihood (handles winner-only exactly under the model); explicit "unprojected" state, never 0 |
| 10 Decision theory / DRO | Streaming no-action threshold from forecast SD; FAAB budget shadow price (λ_t) across weeks; Perfect Draft already exact | Value-of-information bound shows decision layer owns ~17% of headroom today | Mean-minus-z·SD rule; scenario MC; **Wasserstein DRO BLOCKED** until forecasts calibrated |

---

## (c) Replacement matrix (R)

| ID | Replace | With | Why | Gate |
|---|---|---|---|---|
| AM-ROSTER-04 | `materialityPoints 1.0` fixed no-action threshold (F7) | act iff E[ΔL] − z·SD(ΔL) > c_txn, SD(ΔL) from projection error rows (`streaming_point_in_time` error rows: bias −1.1…−1.6, DL slope 0.72) summed over swapped players and horizon | A fixed 1-pt threshold ignores that a 3-swap 4-week plan has far larger forecast SD than a 1-swap 1-week plan | Existing paired harness: false-churn rate ↓ with no loss of realized lift vs base 7 |
| AM-ROSTER-07 | Ten protection PRIORs (F9) | Regret-calibrated rule: protect iff P(value ≥ k·V_repl within H \| features) · (re-acquisition cost) > expected streaming gain | Converts protection into one interpretable decision with empirical support | Requires canonical-board history (src/history); proxy in Appendix A |

## (d) Enhancement rows (E)

| ID | Enhance | Mechanism | Principle |
|---|---|---|---|
| AM-ROSTER-01 | I1 playoff engine | Draw team-mean offset u_t ~ N(0, τ_t²) once per simulated season (normal–normal posterior); optional local-level drift | 1, 2, 4 |
| AM-ROSTER-02 | Calibration evaluation governance (I1/I2/H6) | Component-first ladder (weekly matchup Brier/log score, team-week CRPS) + size-controlled gates (pooled PIT tests with Holm; skill-score CIs) replacing per-family KS | 8 |
| AM-ROSTER-03 | F2 market fit | Point-in-time join via `src/history` + winner-censored order-statistic likelihood; hierarchical engagement by band | 1, 2, 9 |
| AM-ROSTER-08 | G9 replacement levels | Lineup-entry probability by draw-then-solve (BBLI machinery) instead of point-estimate solve | 1, 10 |
| AM-ROSTER-09 | H6/H7 pick forecasts | Fix sim (01) first, then fit c on residual miscalibration; score slot forecasts by Ranked Probability Score by origin week | 8 |
| AM-ROSTER-10 | I5 posture HOLD | HOLD when posterior label probability (under 01's uncertainty) < threshold, replacing perturbation-flip share | 1, 10 |
| AM-ROSTER-11 | H8 BDVM pick outcomes | Monotone hierarchical beta-binomial p_hit by slot using free nflverse draft/production data + 3 league classes | 1, 2 |
| AM-ROSTER-12 | H9 aging curves | Position-pooled aging with dropout/selection correction (extends baseline row 7; not a duplicate) | 2, 9 |
| AM-ROSTER-15 | Waiver/FAAB decisions | Report Δ title odds with paired CI via the existing `simulate_trade_impact` pairing — after 01/02 | 10 |
| AM-ROSTER-17 | F2 config loading | Fail-closed `FaabConfig` (divergent in-code defaults, inert keys; faab-model §10.7–8) | correctness |
| AM-ROSTER-18 | H1 backtest data | Mandatory `--record-snapshot` board + roster capture before the 2027 rookie auction | data |
| AM-ROSTER-19 | F2 option value | Budget shadow price λ_t (approximate DP) replacing scalar `optionValueEarly 0.55→1.0` PRIOR, coupling simultaneous claims | 10 |
| AM-ROSTER-16 | I3/I4 strength unit | Replace rank-index composite (0.72/0.18/0.05/0.05) with presim E[best-ball points] where available; score power rankings against forward all-play | 8 |

## (e) New capability concepts (N)

**N1 — Roster Fragility Index (AM-ROSTER-06).** *User problem:* "my team projects well — how badly can it break?"
*Mechanism:* weekly best-ball score distribution F_w(R) from BBLI's draw→solve loop with three additions it
currently omits: the deterministic bye calendar (already in `src/ros/availability.py`), per-player availability
probability for `uncertain` players, and one same-NFL-team shared shock (τ² ≈ 0.017 measured, V3-D4). Index =
(E[F] − CVaR₁₀%[F]) / E[F], per week and season, plus "fragile weeks" and the slot that collapses. *Data:* all
in-repo. *UX:* one number + a week strip + "which slot breaks". *Advantage:* existing surfaces show means; none show
lower-tail lineup risk. *Why not existing:* BBLI reports a mean delta with MC SE; Construction is retrospective.
*Overlap:* owner intake FFBB-5 names "fragility" (not novel to the repo); commercial tools show bye-week grids but
(uncertain-novelty flag) not exact-lineup CVaR under superflex+IDP rules.

**N2 — Hidden Roster Weakness Detector (AM-ROSTER-14).** Expected points at risk per slot:
EPaR_s = Σ_w Σ_p P(absent_{p,w}) · (score_p − backfill_{p,w}), where backfill is the next legal player the exact
solver would seat (or the waiver level). Surfaces slots that look fine on mean (G6 says "none") but rest on one
fragile player with a thin bench. Same engine as N1; a decomposition, not a second model.

**N3 — Drop-Regret Curve (AM-ROSTER-07, genuinely original in this repo).** An empirical value-transition kernel
K_H(v, x) = P(value_{t+H} ≥ k·v_t | band(v_t), age, usage, draft capital) estimated from the canonical-board
ledger, published beside every "safe to drop" verdict as "≈1 in N players like this gain 50% within 30 days".
Turns ten opaque PRIORs into one stated probability. Appendix A gives the first proxy evidence.

**N4 — Future Roster Paths (AM-ROSTER-13).** 1–3-season Monte Carlo of the roster's starting-lineup expected
points using aging/hazard posteriors (11/12) and pick-outcome posteriors, giving window length and "cliff year"
distributions. *Data missing:* calibrated hazards; HELD behind 11/12. *Overlap:* FFBB-5/6 succession concepts.

**N5 — Calibrated championship impact of a waiver claim (AM-ROSTER-15).** The trade path already has paired
Δ-odds with CI (`playoff_sim.simulate_trade_impact`, `_paired_delta_ci`); extending it to a streaming plan or FAAB
claim gives "this add moves your title odds +0.6 pts [−0.2, +1.4]" — only after 01/02 make the odds honest.

---

## (f) KEEP / REJECT

**KEEP**
- `src/ros/lineup.py` exact assignment (10/10 vs host; no greedy fallback). Nothing in this lane beats exact.
- `src/waivers/streaming_solver.py` exact search with proven-gap labelling (6/6 optimal in base; the gap is forecasts).
- Perfect Draft k-decomposed knapsack and indifference `planMaxBid` (exact; ADR-009/010/011).
- Rookie-auction curve + whole-dollar apportionment + Batch D promotion (owner-protected methodology; parity-pinned).
- Rookie-draft order rule (owner rule; `draft_order.py`).
- Roster Construction V1, marginal/strength/core owners (descriptive, single-owner, missing ≠ 0).
- FAAB crowd comparability gate (fail-closed, measured).
- FAAB separation of objective ceiling vs recommended bid (structurally prevents crowd hype moving worth).
- Power-ranking weight TARGETS (owner directive) — evaluate, do not re-tune silently (AM-ROSTER-16).

**REJECT (now)**
- Wasserstein DRO / CVaR streaming optimization (baseline AMATH-2 / S4) **until** a forecast with PIT skill exists:
  value-of-information bound shows the decision layer owns ≈ +3.3 of ≈ +52 hindsight points (gap decomposition).
  Status BLOCKED, not abandoned.
- EVT for FAAB/title tails — too few independent tail observations.
- DML/TMLE causal estimate of streaming benefit — no identification (agrees with baseline).
- Vine copulas / normalizing flows for league odds — measured cross-player dependence is small (τ_R ≈ 0.09); a
  single shared shock is the strongest simple competitor.
- HMC/NUTS anywhere in this lane — every posterior proposed is conjugate or one-dimensional.

---

## (g) Proof-of-concept experiments

### POC-1 — Latent team-strength uncertainty + component-first calibration (AM-ROSTER-01 + 02)

**Model.** Team t weekly score Y_{t,w} = θ_t + ε_{t,w}, ε ~ N(0, σ_t²). Champion: θ_t fixed at the composed mean m_t
(`_compose_team_distribution`, D11 incumbent or corrected arm, both evaluated). Challenger: θ_t ~ N(μ̂_t, τ_t²)
drawn ONCE per simulated season, where for the empirical basis
μ̂_t = (n_t ȳ_t/σ_t² + m_league/κ²) / (n_t/σ_t² + 1/κ²), τ_t² = 1/(n_t/σ_t² + 1/κ²), κ² by method of moments
across team-seasons; for the presim basis τ_t² = variance of (realized team-week mean − presim mean) estimated on
training weeks only. Optional arm: local level θ_{t,w} = θ_{t,w−1} + η, η ~ N(0, q) (Kalman), q fitted on training.

**Data.** `dynasty_main` 2024, 2025, 2026 matchups via the `previous_league_id` chain (public Sleeper data already
snapshotted by `src/public_league`). Presim arm only on 2026 origins with archived forecasts (`src/ros/forecast_archive.py`,
AL-P6); 2024/2025 use the empirical basis only — no point-in-time rosValue exists before 2026-07-14, stated not imputed.

**Point-in-time cutoff.** Forecast origin = before week w kickoff; uses scores ≤ w−1 and rosters/values as of the
origin. **Training window:** κ², q, presim residual variance fit on 2024–2025 + 2026 weeks < origin; never on the
evaluated week.

**Endpoints (primary, preregistered):** (P1) log score of weekly matchup win probabilities, all remaining-week
pairs per origin (≈ 6 games × ~14 weeks × 3 seasons ≈ 250 game outcomes per origin set; outcomes repeat across
origins, so effective n ≈ the 250 games, block-bootstrapped by season-week); (P2) Ranked Probability Score of
final-seed distributions by origin week (36 team-seasons — reported with honest width; descriptive if CI spans 0).
Secondary: reliability slope of playoff-qualification probabilities; PIT uniformity of simulated season wins.

**Size-controlled gates (AM-ROSTER-02).** Before running, compute each gate's pass rate for a perfectly calibrated
synthetic model at the actual sample sizes (reuse `scripts/sim_calibration_gate_operating_characteristics.py`); a
gate is admissible only if a calibrated model passes ≥ 90% of the time. Multiplicity: Holm over P1, P2.

**Uncertainty:** season-week block bootstrap (2,000 reps). **Compute:** ~20k sims × ~40 origins × 3 arms — minutes
on a laptop. **Leakage safeguards:** origin-stamped inputs; script asserts no score with week ≥ origin enters; κ² refit
per fold.

**Accept** if P1 log-score difference (challenger − champion) has 95% CI > 0 AND P2 is not worse (CI upper bound of
loss ≤ 0) AND reliability slope moves toward 1. **Reject** if P1 CI ≤ 0, if τ estimates are unstable across folds
(coefficient of variation > 50%), or if the gain disappears under the D11-corrected arm. **Rollback/monitoring:**
research module only; any production adoption needs a default-OFF flag, owner decision, and the existing forecast
archive to monitor live Brier by origin week.

### POC-2 — Point-in-time FAAB market refit with winner-censored likelihood (AM-ROSTER-03)

**Model.** For claim j on player with demand signal s_j (from the AS-OF board, `src/history` canonical_board lane,
nearest-prior fidelity only), each manager i (all N, including the eventual winner) bids 0 w.p. 1 − p_i(s_j), else
B_i ~ LogNormal(log m_i(s_j), σ). Observed: winning bid b_j only. Likelihood: P(b_j = 0) = Π_i [1 − p_i] (+ $0
engaged-bid mass) for b_j = 0; for b_j > 0 interval-censored to whole dollars,
L_j = Π_i F_i(b_j + ½) − Π_i F_i(b_j − ½), F_i the zero-inflated CDF. Parameters θ = (engagement base/max/exp, share
base/max/exp, σ), with hierarchical band-level offsets and weakly-informative priors centred on the shipped config.
This replaces matching band quantiles to winners (which treats a maximum as a typical bid; the engine already
corrects this for crowd data with `crowdWinningBidToRivalMedian`, but not in its own fit).

**Data.** `data/faab/bid_history_dynasty_main.json` (box-local) claims with timestamp ≥ 2026-07-14, joined to as-of
values. **Training/validation:** leave-one-waiver-week-out. **Baselines:** champion (shipped `faab.json`); strong
simple baseline = nonparametric per-band empirical distribution of winning bids. **Metrics:** held-out log score of
the observed winning bid; calibration of P($0) per band (±5 pp); expected-surplus regret of `optimal_bid` under each
fitted model. **Sample size:** unknown in this worktree (data box-local); BLOCKED unless ≥ 150 joined claims, of which
≥ 30 above V_allin. **Leakage:** values strictly as-of claim time; no today's-board joins. **Multiplicity:** one primary
(log score). **Accept** if challenger log-score gain CI > 0 vs champion AND not worse than the nonparametric baseline.
**Reject** otherwise, or if above-all-in parameters remain non-identified (posterior ≈ prior). **Rollback:** output is a
candidate config version only; promotion is an owner decision; `faab.json` untouched.

---

## Appendix A — read-only diagnostic: in-season value stickiness (proxy for drop regret)

**Data:** committed `exports/archive/dynasty_export_*.zip` (153 archives, 110 distinct dates 2026-07-14 → 2026-11-01),
column `Composite` of `dynasty_full.csv` (the **raw scraper composite**, NOT canonical `rankDerivedValue`); pick rows
excluded. **Command (run from repo root, `python -I`):** load each archive's `dynasty_full.csv`, keep one snapshot per
date, take non-overlapping 30-day windows starting 2026-07-14 (starts 07-14, 08-13, 09-12, 10-12), and for every
player present at both ends compute value ratio. **Result:**

| composite band at t | pairs | distinct players | P(ratio ≥ 1.5 at t+30d) | P(ratio ≤ 0.67) |
|---|---|---|---|---|
| < 1000 | 290 | 147 | 8.3% | 1.0% |
| 1000–1500 | 926 | 371 | 0.76% | 0.76% |
| 1500–2000 | 514 | 229 | 0.19% | 0.39% |
| 2000–3000 | 502 | 204 | 0.20% | 0.40% |
| ≥ 3000 | 514 | 193 | 0.19% | 0.19% |

Overlapping (all-start-date) windows give the same shape (1000–1500: 0.9% at 30 d, 2.2% at 60 d). **Caveats:** proxy
quantity; composite scale drifted (median 1587 → 1791 → 1667 across window starts); the < 1000 band includes
pool-entry and floor artifacts (the 375/497 floor noted in CLAUDE.md); market value lags role news, so this is a
LOWER bound on football-relevant breakouts; pairs within a band are not independent across windows. **Reading
(HYP):** above composite ~1500, a 30-day market breakout is rare enough that a value-gap-only protection rule loses
little; the regret mass sits in the sub-1000 tail where `young_rising_usage`-style flags matter. Label: DEMO for the
numbers, HYP for the interpretation.

## UNRESOLVED

- FAAB claim counts after 2026-07-14 are box-local; POC-2 feasibility unknown here.
- Whether `src/ros/forecast_archive.py` holds enough 2026 origins for the presim arm of POC-1 was not verified.
- Appendix A uses the scraper composite; a canonical-board rerun needs `data/temporal_ledger.sqlite` (box-local).
- The V3 UNRESOLVED note (presim means 117–507) was not investigated; finding 1 is a structural reading of the
  code, its magnitude is unmeasured (illustration only: with σ_w = 30, τ = 10, n = 7 remaining weeks, season-total
  SD rises by ×1.33 — arithmetic, not a measurement).
