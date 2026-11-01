# AMATH sitewide audit — master synthesis (2026-11-01)

**Status: RESEARCH AND PLANNING ONLY.** This report changes no value, weight, flag, scoring card, band, package
model, bid, waiver, recommendation, preregistration or deployment. `docs/EXECUTION_PLAN.md` remains the only
implementation authorization. **Priority is not authorization**: every AMATH-S item below is "RESEARCH ONLY — not
authorized for implementation" until the execution plan says otherwise, and every promotion still runs the
champion → challenger → owner-approval path.

**Scope.** The Chase Upside fantasy football app only. Market Edge Lab is out of scope (owner correction recorded in
AMATH-01). DFS is OWNER_PAUSED and is studied only for reusable lessons.

**Directive.** Owner "MASTER CLAUDE RESEARCH DIRECTIVE" (2026-11-01): codebase-grounded mathematical due diligence
across every meaningful system; screen ten statistical principles and seven pure-maths disciplines; always compare
current champion → strong simple baseline → advanced challenger; be willing to say KEEP, REMOVE or REJECT; produce
deliverables 1–15, a Top 20 and five proof-of-concept specifications.

**Inputs synthesized (read these for detail; this report links rather than copies):**

| Lane | Report | Rows | Systems inventoried |
|---|---|---|---|
| Valuation, confidence, adaptive learning, data/identity | [SITEWIDE_VALUATION](SITEWIDE_VALUATION_2026-11-01.md) | 17 | 27 |
| Trade calculator/advisor, finder/market, manager intelligence | [SITEWIDE_TRADES](SITEWIDE_TRADES_2026-11-01.md) | 16 | 29 |
| Weekly/ROS projections, IDP, Game Day | [SITEWIDE_PROJECTIONS](SITEWIDE_PROJECTIONS_2026-11-01.md) | 18 | 21 |
| Waivers/FAAB/streaming, roster construction, draft, league intelligence | [SITEWIDE_ROSTER](SITEWIDE_ROSTER_2026-11-01.md) | 22 | 35 |
| Competitive research, pure maths, uncertainty UX, DFS lessons, innovation | [SITEWIDE_FRONTIER](SITEWIDE_FRONTIER_2026-11-01.md) | 13 | 17 |
| Baseline (owner draft #2053) | [ten statistical principles](../ADVANCED_STATISTICAL_METHODS_CHASE_UPSIDE_2026-11-01.md) (AMATH ranks 1–10, S1–S10) and [pure-maths screen](../ADVANCED_MATHEMATICS_FEASIBILITY_2026-11-01.md) (AMATH-1…5) | — | — |

**Merged matrix:** [`evidence/sitewide_opportunities_merged.json`](evidence/sitewide_opportunities_merged.json) — 86
lane rows deduplicated into **63** canonical items AMATH-S01…S63. Same schema as the lane files plus `merged_from`
(lane ids) and `final_rank`. Every merged field keeps the lane id that supplied it. Scores are expert
research-priority judgments on the shared 100-point rubric, **not observed model performance**.

**Evidence labels** (every lane, kept here): **DEMONSTRATED-IN-REPO** (file or command cited in the lane report),
**PUBLISHED-EXTERNAL** (cited), **HYPOTHESIS** (plausible, untested), **SPECULATION**. No number in this report is
new: each is quoted from a lane report or a committed repository record, with its caveat.

**Frozen and failed — untouched by this synthesis.**

- The IDP prospective preregistration (`docs/projections/IDP_OPPORTUNITY_PROSPECTIVE_PREREGISTRATION_2026-11-01.md`)
  and the ROS H1 preregistration (`docs/league-intelligence/ROS_HORIZON_ORDERING_PREREGISTRATION_2026-11-01.md`)
  are **FROZEN**. No item amends, re-scores or tunes them.
- **G3** (ROS scale calibration, 2026-10-28) **stays FAILED**: all three challengers fail cross-group pair ordering
  (`docs/league-intelligence/ROS_SCALE_CALIBRATION_RESULTS_2026-10-28.md`).
- **G4 / D11**: the D11 corrected playoff equation improved weekly log loss 1.133 → 0.661 but **FAILED gate G4**
  (score PIT mean 0.95 vs 0.83), so the incumbent stays published (`docs/OWNER_REQUESTED_TODO.md` D11 update).
- Sim calibration **V3 failed** SC-G1, SC-G4, V3-G6 and V3-G9
  (`docs/league-intelligence/SIM_CALIBRATION_V3_RESULTS_2026-10-27.md`).
- The sparse-evidence challenger failed **G2c** (3.335 vs 2.0); the learned source-quality challengers C1–C3 failed
  their materiality gate.

---

## 1. Executive discovery summary — the ten most important findings

1. **Real accepted trades mostly do not land in our "fair" band (surprising).** Of 29 committed own-league
   multi-piece trades, the live `fairness_bands.classify` under `geom_q078_v1` rates 6 fair, 4 slight, 8 unfair and
   11 lopsided; median gap 14.5% of the larger package. Caveats: n = 29, values from boards **reconstructed by
   today's pipeline** over archived raw payloads, not the board served at the time. The bands are a normative
   statement about our board, not a description of what clears. Band changes stay owner-gated (OD-F4). [TRADES §0.2,
   §8.1; DEMONSTRATED-IN-REPO]
2. **The trade Monte Carlo "win rate" carries almost no information.** 0 of 1,093 rows carry a real `valueBand`;
   the UI synthesizes a flat ±15% band, so the output is a monotone transform of the gap shown as a probability.
   Found independently by two lanes. → AMATH-S12. [TRADES B9, FRONTIER #5; DEMONSTRATED-IN-REPO]
3. **The playoff/title simulator has no season-level team-strength uncertainty, and its calibration gates are
   mis-sized.** Weekly scores are drawn around a fixed per-team mean, so season variance omits the n²τ² term. A
   perfectly calibrated model passes SC-G4 0.2% and SC-G1 16% of the time at week-7 sizes, so the gates could not
   have passed a good model either. The D11 record already names a "per-draw team shock" as the follow-up its failed
   G4 points to. → AMATH-S01, S03. [ROSTER §0.1–0.2; DEMONSTRATED-IN-REPO structure; magnitude HYPOTHESIS]
4. **Every Game Day probability runs on fallback dispersion constants, independent draws, and an in-progress
   variance that shrinks too fast.** Production uses `FALLBACK_CV_BY_POSITION` (QB 0.32 … TE 0.65) because the
   calibrated artifact was never built (RPA-F-021). Remaining SD scales with the remaining fraction f instead of √f
   (0.50× at f = 0.25). Same-NFL-team pair dependence measured at τ² ≈ 0.0169 vs ≈ 0.0088 roster-wide (2,646 pairs)
   is ignored. The true weekly-projection CV is **unmeasured**; V3's 0.73–1.20 is an upper reference only. →
   AMATH-S04, S03. [PROJECTIONS §0.1–0.3, FRONTIER F1]
5. **Streaming's binding constraint is the forecast, not the optimizer (reverses #2053's sequencing).** Relaxing
   every point-in-time guard moves the strict optimizer from +0.40 to +3.71 points per decision-week; hindsight
   points give +52.7. The decision layer owns roughly 6% of the hindsight headroom. So Wasserstein DRO / CVaR
   streaming (#2053 AMATH-2 / S4) moves to **BLOCKED** behind forecast calibration. → AMATH-S51, S06, S26.
   [ROSTER §0.3; `docs/waivers/IDP_STREAMING_GAP_DECOMPOSITION_2026-11-01.md`; 6 decision weeks, small n]
6. **The single-source ×0.30 value haircut has no evidence and penalizes missing corroboration as if it were bad
   news.** Owner decision B already rejects the design; the only challenger failed a gate that measured distance
   from the haircut itself (G2c). → AMATH-S02, owner decision OD-AM-1. [VALUATION §(a) row 9]
7. **The market consensus drifts toward KTC, not the reverse, and KTC shows no mean reversion.** VALUATION D2:
   non-KTC consensus moves toward KTC (median Spearman 0.145, positive in 9/9 windows, n ≈ 290); KTC toward the
   consensus 0.006. TRADES §8.2: no mean reversion in KTC (weak 21-day momentum, 4 origins). Consequences: the
   Finder/Angle "arbitrage" premise is untested and could point the wrong way (→ S10), the consensus-vs-KTC
   "inefficiency map" is rejected (→ S60), and leave-KTC-out consensus cannot serve as the independent Hill
   validation target (→ S50). Caveats: offense only, preseason 2026, about 3 effective windows, exploratory.
8. **Disagreement weakly predicts value revision, but depth and season phase dominate, and the confidence gate has
   never been outcome-calibrated.** D1: median ρ 0.15 / 0.16 / 0.07 by rank band, turning ≤ 0 in-season; revision
   scale jumps from 0.035–0.08 to 0.19–0.23 once the season starts. Any uncertainty product must stratify by phase. →
   AMATH-S01 (confidence reliability), S07, S28. [VALUATION D1; exploratory, about 3 effective windows]
9. **The two scorecards that would say whether anything is calibrated are built, merged and never scheduled.**
   AL-3b (`projection_scorecard.py`) and AL-4a (`game_day_calibration.py`) are `SHADOW_NOT_RUNNING` (RPA-LGI-004).
   Scheduling them is the cheapest high-value step in the audit. → AMATH-S01.
10. **The FAAB market model is fitted on look-ahead joins and treats a winning bid as a typical bid.** The model's
    $0-share is 0.6% against an observed 45.8% in the 2100–2600 band (`docs/faab-model.md` §9.3). Sleeper exposes
    only winning bids, so the right likelihood is the order-statistic likelihood of the maximum. → AMATH-S05.

Also notable: `infer_archetype` reads a missing feature as 0.0 and silently picks the default archetype, a live
MISSING IS NEVER ZERO violation (→ AMATH-S38, P0 fix). Acceptance probability is **not identifiable** from
accepted-only trades, and `partner.py`'s refusal to publish one is correct (KEEP).

---

## 2. Current mathematical architecture map — what is empirically validated

"Validated" means outcome or oracle evidence in the repo, not "tests pass". Detail per system is in each lane's
inventory table (129 systems in total).

| Layer | Canonical owner | Status | Empirically validated? |
|---|---|---|---|
| League scoring | `src/league_intel/scorer.py::score_stat_line` | live | **YES** — 1,415/1,415 (2025) and 4,275/4,275 within 0.02 (2026 weeks 1–7) |
| Exact lineup | `src/ros/lineup.py::solve_optimal_assignment` | live | **YES** — 10/10 vs Sleeper-awarded lineups; brute-force oracle tests |
| Streaming solver, Perfect Draft knapsack | `src/waivers/streaming_solver.py`, `frontend/lib/perfect-draft.js` | live | **Exactness YES** (6/6 optimal in base backtest); decision value **NO** (Perfect Draft backtest BLOCKED, no pre-auction snapshot) |
| Identity | `src/identity/resolution.py`, `picks.py` | V1 served | **YES for parity** (dual-read 2,016/2,016 and 24,024/24,024 at cut-over); V2 diverges on 23/2,015 |
| Dynasty value blend | `src/api/data_contract.py::_compute_unified_rankings` | live | **Reproducible** (value replay); no outcome validation exists, by nature of a market value |
| Hill masters | `src/canonical/player_valuation.py` | live | Fit on board holdouts only (RMSE 83.8 vs best 83.4); **no independent validation target** (gate 7 BLOCKED) |
| Single-source haircut ×0.30, α = 0.10, Hampel K 2.75, freshness C4 | `data_contract`, `src/sources/freshness.py` | live | **NO** — PRIOR or stability-selected |
| Equal family weights | `_RANKING_SOURCES` | live | **YES (negative result)** — learned weights failed: ΔMALE ≤ 0.00127 vs materiality 0.00215 over 522,206 cells |
| Pick year-step | `derivedYearModel` | live | 1→2-out holdout MAPE ~1.4% (816 cells); 2→3-out extrapolation **PRIOR** |
| Confidence gate | `src/api/confidence.py` | live | **NO outcome calibration** (invariant tests only) |
| Package model | `src/valuation_math/package_model.py` (`geom_q078_v1`) | live | **Research-backed** on 18,690 PIT market trades; q itself only partially identified |
| Fairness bands v2 | `src/valuation_math/fairness_bands.py` | live | **NO** — PRIOR, KTC-era cut points; OD-F4 validation PENDING |
| Trade decision v2, posture, partner logits, Best Offers, Sharp Score, archetypes | `trade_decision.py`, `window.py`, `partner.py`, `best_offers.py`, `sharp/score.py`, `manager_career.py` | live | **NO** — declared PRIOR |
| Trade Monte Carlo | `src/trade/monte_carlo.py` | live (flag) | **NO** — synthetic band |
| FAAB engine | `src/trade/faab_engine.py` | live | Partial — anchors reproduce two human judgments; market fitted on look-ahead joins; above-all-in parameters asserted |
| Drop protection | `src/waivers/drop_assessment.py` | live-private | **NO** — ten PRIORs |
| Weekly projections | `src/ros/weekly_league_projections.py` | live | Not scored (AL-3b unscheduled); provider covers 56–62% of scoring defender-weeks |
| ROS rank aggregate | `src/ros/aggregate.py` | live | **NO** for multipliers; G3 FAILED downstream |
| Sim points model / Game Day / playoff | `sim_calibration.py`, `game_day_sim.py`, `playoff_sim.py` | live-fallback | **Measured miscalibrated** (V1–V3); odds labelled uncalibrated (MD-11) |
| IDP opportunity challengers | `src/ros/idp_opportunity/` | research, frozen | Retrospective MAE gain 0.36–0.50 vs weak C0, mostly from shrinkage; prospective study decides |
| BDVM | `src/bdvm/` | live (flag on) | Parity with reference fixture; params "priors, not validated truth" |
| Pick market c | `src/trade/pick_market.py` | live | Designed Brier fit; no outcomes yet |
| Rookie-auction curve, draft order | `src/draft/rookie_auction/`, `draft_order.py` | owner-protected | Owner methodology; parity-pinned |

**Reading.** The exact, combinatorial and identity layers are validated. Almost every probabilistic and threshold
layer above them is a declared prior or measured miscalibrated. The repo is honest about this (labels, refusals,
MD-11 wording), but it has no running calibration record to retire the labels.

---

## 3. The ten statistical principles applied sitewide

Each row: the credible applications that survived the lanes, the limitation, and the simple competitor that must be
beaten first. Lane-by-lane screens: VALUATION §(b), TRADES §2, PROJECTIONS §(b), ROSTER §(b), FRONTIER §3.

| # | Principle | Credible sitewide applications (AMATH-S) | Limitation | Simple competitor first |
|---|---|---|---|---|
| 1 | Bayesian / epistemic uncertainty | Season-level team-mean draw (S03); value band from family bootstrap → posterior (S07); BDVM n₀ (S19); FAAB posterior (S05); posterior HOLD (S41) | Every useful posterior is conjugate or low-dimensional. **HMC/NUTS is unnecessary anywhere**; BMA over one effective weekly family is meaningless | Conjugate normal–normal, Beta–Binomial, Gamma–Poisson in ~20 lines of scipy |
| 2 | Hierarchical partial pooling | Manager/Sharp rates (S17); dispersion (S04); BDVM hazards/aging (S39); rookie hit rates (S20); α re-selection (S21); IDP rates (#2053 S1, retained) | Small groups; priors must be declared; monotonicity imposed | Method-of-moments empirical Bayes; isotonic regression |
| 3 | Causal inference | **None identified.** Descriptive realized-value-added and paired contrasts only | No exogenous variation, confounding by team strength, interference, tiny n | Descriptive tables labelled non-causal → **REJECT** (S62) |
| 4 | Nonstationarity / latent state | Season-phase strata in every interval (S01, S07); Role Change Radar (S25, BOCPD/HMM); board drift nowcast (S34); local-level team drift (S03) | Few observations per player or team-season; label lag | EWMA, last-3 mean, phase dummies; Particle MCMC rejected |
| 5 | High-dimensional sparsity | Drop-regret features (S09, ≤ 10 features); ablation for explanations (S22) | Nothing here is high-dimensional (~15 sources, 2 Hill parameters) | L2 / monotone logistic; ablation tables. Horseshoe **REJECT** |
| 6 | Multivariate / tail dependence | One game factor + same-team factor (S03); Gaussian copula only if needed; fragility CVaR (S11) | Measured dependence is small; marginals uncalibrated first | Single shared shock. Vines/flows **REJECT** (S63) |
| 7 | Extreme value theory | **None.** | Too few independent exceedances; dynasty top saturated by construction | Empirical quantiles, hurdle counts, order statistics → **REJECT** (S61) |
| 8 | Conformal / calibration | **Calibration ledger (S01)**; measured marginals (S04); value revision band (S07); clearing percentile (S08); band validation (S14) | Exchangeability fails (drift, clustering, refreshed inputs): report empirical coverage per stratum, **never claim the finite-sample guarantee** | Rolling empirical quantiles and reliability diagrams; ACI as a one-line challenger |
| 9 | Nonignorable missingness / selection | Single-source haircut (S02); provider non-coverage (S16); ROS rank censoring (S30); winner-only FAAB bids (S05); accepted-only trades (S08, S48, S44); archetype missing→0 (S38) | Mechanism not identified from observed data; sensitivity bounds, not point claims | Explicit missingness states, two-stage models, δ-shift sensitivity |
| 10 | Decision theory / DRO | SD-scaled no-action threshold (S06); drop regret (S09); No-Action / regret layer (S23); exceedance ranking (S26); title-equity exchange rate (S35) | Inputs not yet calibrated; a Wasserstein radius cannot be validated with ~4 effective time origins | Expected utility vs NO ACTION with a conservative threshold; scenario MC. DRO **BLOCKED** (S51) |

---

## 4. The seven pure-maths disciplines — verdict

The FRONTIER lane challenged #2053's screen against the actual code (FRONTIER §6).

| Discipline | #2053 verdict | Final verdict | Reason |
|---|---|---|---|
| Arithmetic algebraic geometry | REJECT | **REJECT** | No object in the codebase is a variety over a number field |
| Higher category theory | REJECT (borrow compositional design) | **REJECT** | Typed artifacts, `leagueKey` / scoring-fingerprint scoping and one-owner modules already give compositionality |
| Algebraic topology (TDA) | RESEARCH / LOW | **REJECT for now** (changed) | The real champion is the hand-threshold `infer_archetype` tree #2053 skipped; a GMM/BIC baseline must pass stability and lift first, and NFL samples are too sparse for persistent homology |
| Analytic number theory | REJECT | **REJECT** | No application |
| PDEs | REJECT | **REJECT** | Weekly discrete observations; no boundary conditions or data |
| Set theory / logic | PROTOTYPE TESTS via CP-SAT/Z3 | **Property-based tests YES, SMT NO** (changed) | The oracle (`brute_force_best`) exists; Hypothesis plus exhaustive enumeration cover the invariants (AMATH-S15). Correctness gain, not predictive accuracy |
| Differential geometry | RESEARCH / LOW | **REJECT** (changed) | Presupposes a validated archetype space that does not exist |

---

## 5. Top 10 replacement opportunities (R / REMOVE)

| # | AMATH-S | Replace | With | Code reference | Justification |
|---|---|---|---|---|---|
| 1 | S02 | ×0.30 single-source haircut | Value kept, uncertainty carried (LOW + interval), censor bound where an absent board reaches the depth | `data_contract._SINGLE_SOURCE_VALUE_RETENTION`; challenger `src/api/sparse_evidence.py` | No evidence; owner decision B rejects the design; missing ≠ penalty |
| 2 | S04 | Fallback CVs, SD ∝ f, truncated Gaussian | PIT-measured pooled dispersion, √f remainder, hurdle shape | `sim_calibration.py::PointsModel.draw_from_mean`; `game_day_week.py::_remaining_for` | RPA-F-021; V3 evidence that fallback is too narrow |
| 3 | S06 | `materialityPoints 1.0` fixed no-action threshold | Act iff E[ΔL] − z·SD(ΔL) > c_txn | `config/waivers/streaming.json`; `src/waivers/streaming.py` | A 3-swap 4-week plan has far more forecast SD than a 1-swap 1-week plan |
| 4 | S09 | Ten drop-protection PRIORs | Empirical value-transition kernel ("≈1 in N gain 50% within 30 days") | `config/waivers/streaming_protection.json`; `drop_assessment.py` | Composite proxy: P(≥1.5× in 30 d) 0.76% at 1000–1500 (926 pairs) vs 8.3% below 1000 |
| 5 | S10 | Finder/Angle "arbitrage" assumed edge | Convergence test, or relabel as "disagreement" | `src/trade/finder.py`, `angle.py` | Two diagnostics show no reversion toward the board/consensus |
| 6 | S12 | Trade MC win rate on synthetic ±15% | Hide/relabel now; real band later | `src/trade/monte_carlo.py`; `MonteCarloButton.jsx:65-68` | 0/1,093 real bands |
| 7 | S17 | Raw tendency shares at n ≥ 3, archetype cliffs, raw Sharp win% | Empirical-Bayes pooling with intervals | `src/intel/manager_trade_intel.py`, `manager_career.py`, `src/sharp/score.py` | SE ≈ 0.29 at n = 3 |
| 8 | S21 | Stability-selected α = 0.10, C4, Hampel floor | One predictive leave-family-out target | `data_contract._ALPHA_SHRINKAGE`; `freshness_v1.json` | α was selected with λ = 0.10; λ is now 0 |
| 9 | S47 | ROS format multipliers 1.15…0.85, freshness steps | Leave-one-source-out; equal weights unless gain | `src/ros/parse.py::format_match_multiplier` | No empirical support; input side of the NC-A scale problem |
| 10 | S33 | Rank-index team-strength composite (0.72/0.18/0.05/0.05) | Presim expected best-ball points; power rankings scored forward | `src/ros/team_strength.py` | Unit is not points; never scored against outcomes (E-category in the matrix; replacement in effect) |

---

## 6. Top 10 enhancements (E)

| # | AMATH-S | Enhance | Mechanism | Score / horizon |
|---|---|---|---|---|
| 1 | S03 | Playoff, Game Day and BBLI draws | Season-level team-mean draw; game + team shared factors | 85 / P1 |
| 2 | S05 | FAAB market fit | Point-in-time join via `src/history`; winner-censored order-statistic likelihood; hierarchical engagement | 84 / P1 |
| 3 | S13 | Perfect Draft backtest data | Mandatory `--record-snapshot` before the 2027 rookie auction | 80 / P0 |
| 4 | S14 | Fairness bands v2 | Executable OD-F4 protocol: band hit-rates on PIT market trades by shape × level, league-disjoint, time-forward | 80 / P1 |
| 5 | S15 | Invariant tests | Hypothesis property suite (lineup, capacity, ledger conservation, pick fold) | 78 / P1 |
| 6 | S18 | Uncertainty display | One grammar: fact / estimate / recommendation / unavailable, with calibration status | 77 / P1 |
| 7 | S19 | BDVM `n_prior` 6 / 8 | Bühlmann / empirical-Bayes n₀ per position | 77 / P1 |
| 8 | S20 | BDVM rookie pick outcomes (placeholder table) | Monotone hierarchical Beta–Binomial by slot | 77 / P2 |
| 9 | S24 | Pick-slot forecasts and pick-market c | Fix the sim upstream, score by RPS, then fit c | 76 / P2 |
| 10 | S28 | Confidence agreement axis | Leave-that-family-out reference (removes self-inclusion) | 74 / P1 |

---

## 7. New product concepts (19, of which 5 genuinely original)

All concepts are proposals; none is authorized. "Original" means **not found in this repo or in the public evidence
the FRONTIER lane could inspect**; competitor methods are mostly paywalled, so every novelty claim is **uncertain**.
Each entry: user problem → mechanism → data → UX → measurable advantage → why current features do not solve it →
novelty.

**Genuinely original (5)**

1. **Market Clearing Percentile (S08).** "Would a deal like this actually happen?" → conditional quantiles of
   accepted-trade residuals by shape × level × pick share, EB-pooled, rolling, league-disjoint → box market-trade
   ledger (18,690 PIT trades) → private line under the meter, "81% of comparable completed trades were closer to even"
   → prospective interval coverage → bands are normative, not descriptive → novelty uncertain (KTC lists trades; no
   conditional percentile found).
2. **Board Drift Forecast (S34).** "Is this value about to move because slow sources haven't caught up?" → expected
   drift Σ w_f·β(age_f, band)·gap_f, β walk-forward → CSV git history, temporal ledger → drift arrow beside the
   value, never added to it, never a vote → lower MAE of the next board change than zero-drift in non-overlapping
   folds → nothing forecasts the board's own movement → SPECULATION on external novelty.
3. **Drop-Regret Curve (S09).** "If I drop him, how likely am I to regret it?" → value-transition kernel
   P(v_{t+H} ≥ k·v_t | band, age, usage, draft capital) → canonical-board ledger (composite proxy today) → "≈1 in N
   like him gained 50% within 30 days" beside every safe-to-drop verdict → regret-calibrated protection vs ten PRIORs
   → current classes are opaque thresholds → original in repo; external novelty uncertain.
4. **Projection Blind-Spot Map (S16).** "38–44% of scoring defender-weeks were never projected — who am I missing?"
   → P(projected | features) × production | played, with δ-shift sensitivity band → Sleeper stats, snaps, provider
   rows (archive from week 8) → "not projected by provider — model estimate" chips → recall of free-agent defenders
   beating the 9th-best rostered starter → D1 correctly refuses to invent a number; nothing models the selection →
   not found in repo; external uncertain.
5. **Trade Robustness Stamp (S29).** "Would this verdict survive if one source were wrong?" → re-run the unchanged
   verdict over family-bootstrap and leave-one-family-out boards → contract per-source contributions → "holds under
   9 of 10 resampled boards / flips if DLF is excluded" → share of fragile verdicts, comprehension test → no
   verdict-level robustness exists → overlap Low (uncertain).

**Other concepts (14)**

6. **Public/private Calibration Ledger (S01)** — "how right have we been": reliability, coverage, n and
   SMALL_SAMPLE per probability; no competitor found publishing realized coverage (Medium overlap: FantasyPros
   tracks rank accuracy).
7. **Value Weather Band (S07)** — p10–p90 bracket on each dynasty value; family bootstrap now, calibrated revision
   band later; replaces the synthetic ±15% band.
8. **Matchup Weather (S03 component b)** — "your outcome is tied to the BUF–KC game"; correlated simulation is
   established in DFS, apparently absent in season-long matchup odds (uncertain).
9. **Roster Fragility Index + Hidden Weakness (S11)** — lower-tail lineup risk and points-at-risk per slot from one
   exact-lineup engine; FFBB-5 already names fragility.
10. **Role Change Radar (S25)** — BOCPD role-change probability with false-alarm rate; snap trends are common
    (Medium overlap), the calibrated probability with abstention is not.
11. **Exceedance Board (S26)** — rank streaming adds by P(X > the team's marginal starter), not by mean; fixes the
    shrinkage-compresses-top-N problem (CB top-N hit 0.08 vs 0.22).
12. **Regret / No-Action cards (S23)** — NO ACTION always scored; "if wrong, typical cost"; ESPN/IBM boom-bust is
    Medium overlap.
13. **Exact Evidence Explainer + Disagreement Map (S22)** — V − V₋f per family; one "who is mispriced" page (UX-P06).
14. **Title-Equity Exchange Rate (S35)** — marginal title equity per 1,000 market points, for buy/sell timing.
15. **Calibrated championship impact of a waiver claim (S37)** — paired Δ title odds with CI, after S01/S03.
16. **Future Roster Paths (S43)** — 1–3-season window and "cliff year" distributions (P3, behind S39/S20).
17. **Private Offer Ledger (S44)** — opt-in logging of the user's own offers and outcomes; the only route to
    acceptance data (owner decision OD-AM-5).
18. **Availability Odds (S52)** — P(plays) on top of the four-state owner; BLOCKED on point-in-time injury data.
19. **Live Usage Nowcast (S53)** — in-game Gamma–Poisson rate update; BLOCKED on provider access.

Full per-concept fields (data available/missing, consumers, risk, evaluation) are in the merged JSON.

---

## 8. The complete opportunity matrix

All 63 items, ranked. Horizon is assigned to every item. Full fields — current system, owner, method, evidence,
baseline, proposal, principle, mechanism, data, consumers, risk, evaluation, acceptance, rejection, effort, roadmap
links, novelty and score components — are in
[`evidence/sitewide_opportunities_merged.json`](evidence/sitewide_opportunities_merged.json).

| Rank / ID | Cat | Horizon | Total | Title | Merged from (lane ids) |
|---|---|---|---|---|---|
| AMATH-S01 | N | P0 | 88 | Forecast Calibration Ledger: schedule AL-3b/AL-4a, size-controlled gates, calibration-state on every published probability/interval, and outcome reliability of confidence buckets | AM-PROJECTIONS-04, AM-PROJECTIONS-05, AM-FRONTIER-02, AM-ROSTER-02, AM-VALUATION-03 |
| AMATH-S02 | R | P0 | 85 | Replace the single-source x0.30 value haircut with value-kept + uncertainty-carried, tested against outcomes | AM-VALUATION-01 |
| AMATH-S03 | E | P1 | 85 | Shared latent factors in simulation draws: season-level team-strength uncertainty (playoff/title) and game/team correlation (Game Day, BBLI, playoff) | AM-ROSTER-01, AM-FRONTIER-01, AM-PROJECTIONS-03 |
| AMATH-S04 | R | P0 | 84 | Measured weekly predictive marginals: replace fallback CVs, SD-proportional-to-remaining in-progress scaling and the truncated Gaussian with PIT-measured, position-pooled (empirical-Bayes) dispersion, sqrt(f) remainder scaling and a hurdle/skewed shape | AM-PROJECTIONS-01, AM-PROJECTIONS-02, AM-PROJECTIONS-14, AM-FRONTIER-09 |
| AMATH-S05 | E | P1 | 84 | Point-in-time FAAB market refit with winner-censored (order-statistic) likelihood | AM-ROSTER-03 |
| AMATH-S06 | R | P1 | 84 | Uncertainty-derived no-action threshold for streaming | AM-ROSTER-04 |
| AMATH-S07 | N | P1 | 83 | Dynasty value uncertainty band: family-bootstrap band now (named alternate concept) and a stratified, outcome-calibrated revision-risk interval later | AM-VALUATION-02, AM-FRONTIER-07 |
| AMATH-S08 | N | P1 | 82 | Market Clearing Percentile plus board-noise decomposition of accepted-trade residuals | AM-TRADES-01, AM-TRADES-08 |
| AMATH-S09 | R | P1 | 81 | Drop-Regret Curve: empirical value-transition kernel replacing protection PRIORs | AM-ROSTER-07 |
| AMATH-S10 | R | P1 | 81 | Validate or relabel the Finder/Angle 'arbitrage' edge (convergence test) | AM-TRADES-09 |
| AMATH-S11 | N | P2 | 81 | Roster Fragility Index and Hidden Weakness (expected points at risk per slot) from one exact-lineup scenario engine | AM-ROSTER-06, AM-ROSTER-14 |
| AMATH-S12 | REMOVE | P0 | 80 | Hide or relabel the live trade Monte Carlo 'win rate' built on a synthetic flat +/-15% band; replace only once real per-asset bands exist | AM-FRONTIER-04, AM-TRADES-03 |
| AMATH-S13 | E | P0 | 80 | Record pre-auction board + roster snapshot before the 2027 rookie auction | AM-ROSTER-18 |
| AMATH-S14 | E | P1 | 80 | Executable OD-F4 validation protocol for fairness_bands_v2 | AM-TRADES-02 |
| AMATH-S15 | E | P1 | 78 | Hypothesis property-based invariant suite (test-only) | AM-FRONTIER-03 |
| AMATH-S16 | N | P1 | 78 | Projection Blind-Spot Map (provider non-coverage as a selection process) | AM-PROJECTIONS-10 |
| AMATH-S17 | R | P1 | 77 | Empirical-Bayes partial pooling for small-sample manager tendencies, archetypes and Sharp Score win% | AM-TRADES-10, AM-TRADES-11 |
| AMATH-S18 | E | P1 | 77 | Uncertainty Grammar: fact / estimate / recommendation / unavailable | AM-FRONTIER-06 |
| AMATH-S19 | E | P1 | 77 | Empirical-Bayes credibility for BDVM n_prior | AM-PROJECTIONS-08 |
| AMATH-S20 | E | P2 | 77 | Hierarchical monotone rookie hit-rate priors (BDVM pick outcomes) | AM-ROSTER-11 |
| AMATH-S21 | R | P1 | 76 | One predictive selection target for board constants chosen on stability (alpha = 0.10 shrinkage, freshness curve C4, Hampel floor), including re-selection of alpha | AM-VALUATION-05, AM-VALUATION-04 |
| AMATH-S22 | N | P1 | 76 | Exact leave-one-family-out evidence explainer and one Disagreement Map ('who is mispriced') | AM-VALUATION-17, AM-FRONTIER-10 |
| AMATH-S23 | N | P2 | 76 | Regret and No-Action layer (private shadow): No-Action Advantage, regret/CVaR versus hold, and regret cards with NO ACTION always shown | AM-TRADES-05, AM-TRADES-04, AM-FRONTIER-12 |
| AMATH-S24 | E | P2 | 76 | Pick-slot forecasts: fix simulator overconfidence upstream, score by RPS, then fit pick-market c with log score, reliability and cross-season pooling | AM-ROSTER-09, AM-TRADES-16 |
| AMATH-S25 | N | P1 | 75 | Role Change Radar (offense; shared surface with IDP S2) | AM-PROJECTIONS-09 |
| AMATH-S26 | N | P1 | 75 | Exceedance Board: rank streaming adds by P(X > marginal starter) | AM-PROJECTIONS-11 |
| AMATH-S27 | E | P0 | 74 | Fail-closed FAAB config loading and removal of inert keys | AM-ROSTER-17 |
| AMATH-S28 | E | P1 | 74 | Remove self-inclusion bias from the agreement axis (compare each family to the leave-that-family-out value) | AM-VALUATION-13 |
| AMATH-S29 | N | P2 | 74 | Trade Robustness Stamp (verdict under resampled / leave-one-family-out boards) | AM-FRONTIER-08 |
| AMATH-S30 | E | P1 | 73 | ROS aggregate: rank censoring instead of missing-at-random skip | AM-PROJECTIONS-06 |
| AMATH-S31 | E | P1 | 73 | Natural-experiment test of the PRIOR pick year-step (derivedYearModel) when vendors first publish the next far class | AM-VALUATION-08 |
| AMATH-S32 | E | P2 | 73 | Stochastic replacement levels (lineup-entry probability) | AM-ROSTER-08 |
| AMATH-S33 | E | P2 | 72 | Points-unit team strength and forward-scored power rankings | AM-ROSTER-16 |
| AMATH-S34 | N | P2 | 72 | Board drift forecast from stale votes (original): predict how the canonical value will move as lagging sources update | AM-VALUATION-11 |
| AMATH-S35 | N | P2 | 71 | Trade-window timing: Title-Equity Exchange Rate | AM-TRADES-06 |
| AMATH-S36 | E | P2 | 71 | Add a 'no outlier filter + count-aware weighted trimmed median' arm as the strong simple baseline for outlier-integrity V2 | AM-VALUATION-06 |
| AMATH-S37 | N | P2 | 70 | Calibrated championship impact of waiver/FAAB/streaming decisions | AM-ROSTER-15 |
| AMATH-S38 | E | P0 | 69 | Evidence check for hand-threshold archetypes; fix missing-feature-to-0 | AM-FRONTIER-05 |
| AMATH-S39 | E | P2 | 68 | BDVM hazards and aging curves: position-pooled discrete-time survival with dropout/selection correction | AM-ROSTER-12, AM-VALUATION-12 |
| AMATH-S40 | E | P2 | 67 | Version, refresh and attribute the KTC TE++ uplift curve as a KTC-lineage component on non-TEP TE votes | AM-VALUATION-10 |
| AMATH-S41 | E | P2 | 66 | Competitive Posture validation: shadow behavioural check first, posterior-based HOLD later | AM-TRADES-15, AM-ROSTER-10 |
| AMATH-S42 | E | P2 | 66 | Probabilistic record-linkage (Fellegi-Sunter) challenger as an abstention and reviewer-queue ranker, not a served matcher | AM-VALUATION-09 |
| AMATH-S43 | N | P3 | 66 | Future Roster Paths (multi-season window simulation) | AM-ROSTER-13 |
| AMATH-S44 | N | P2 | 65 | Private Offer Ledger (decision-data capture for acceptance and regret) | AM-TRADES-13 |
| AMATH-S45 | E | P2 | 65 | Re-express legacy Suggestions/Finder gates in band/percent units | AM-TRADES-14 |
| AMATH-S46 | E | P3 | 64 | Budget shadow price (approximate DP) for FAAB option value | AM-ROSTER-19 |
| AMATH-S47 | R | P2 | 62 | Evaluate / simplify hardcoded ROS format and freshness multipliers | AM-PROJECTIONS-07 |
| AMATH-S48 | E | P3 | 61 | Partial identification of package q (and level c) by moment inequalities | AM-TRADES-07 |
| AMATH-S49 | E | P2 | 53 | Lineage-aware family disagreement as uncertainty | AM-PROJECTIONS-13 |
| AMATH-S50 | N | BLOCKED | 67 | Preregister a genuinely independent validation target for Hill gate 7 (format-qualified non-KTC completed trades) | AM-VALUATION-07 |
| AMATH-S51 | REJECT | BLOCKED | 58 | Defer Wasserstein DRO / CVaR streaming until forecasts have PIT skill (value-of-information gate) | AM-ROSTER-05 |
| AMATH-S52 | N | BLOCKED | 55 | Availability odds: probability layer over the four-state owner | AM-FRONTIER-13 |
| AMATH-S53 | N | BLOCKED | 53 | Live usage nowcast (in-game Bayesian rate update) | AM-PROJECTIONS-12 |
| AMATH-S54 | KEEP | KEEP | 73 | Keep exact solvers: canonical lineup, streaming solver, Perfect Draft knapsack | AM-ROSTER-21 |
| AMATH-S55 | KEEP | KEEP | 71 | Game Day player-state machine (no double-counting of completed scoring) | AM-PROJECTIONS-16 |
| AMATH-S56 | KEEP | P3 | 70 | Keep the 2-parameter percentile Hill (log-logistic) curve family; fix only its validation target and a stale docstring | AM-VALUATION-16 |
| AMATH-S57 | KEEP | KEEP | 70 | Host-native scorer and realized-points delegation | AM-PROJECTIONS-15 |
| AMATH-S58 | KEEP | KEEP | 67 | Keep owner-protected rookie-auction curve, Batch D promotion and draft-order rule | AM-ROSTER-22 |
| AMATH-S59 | REJECT | REJECT | 54 | A new learned source-reliability weighting system (already built and failed its gate) | AM-VALUATION-15 |
| AMATH-S60 | REJECT | REJECT | 44 | Consensus-vs-KTC 'market inefficiency' buy/sell map | AM-VALUATION-14 |
| AMATH-S61 | REJECT | REJECT | 37 | REJECT: extreme value theory for IDP splash games, FAAB tails and title-odds tails | AM-ROSTER-20, AM-PROJECTIONS-17 |
| AMATH-S62 | REJECT | REJECT | 31 | REJECT: causal DML/TMLE/SCM claims (manager skill, advisor effect, opponent/matchup effects, streaming benefit) | AM-TRADES-12, AM-PROJECTIONS-18 |
| AMATH-S63 | REJECT | REJECT | 20 | Rejected: TDA archetypes, SMT for legality, vine copulas/flows, EVT, DML on advice uptake, differential geometry | AM-FRONTIER-11 |

---

## 9. Combined Top 20 with every score component

Ranks 1–20 of the actionable items (BLOCKED, KEEP and REJECT excluded). Ties are broken by horizon (P0 first).
Rubric: advantage 25, justification 20, data 15, feasibility 15, strategic 10, interpretability 10, efficiency 5.

| # | ID | Cat | Horizon | Adv 25 | Just 20 | Data 15 | Feas 15 | Strat 10 | Interp 10 | Eff 5 | **Total** | One line |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| 1 | AMATH-S01 | N | P0 | 18 | 19 | 12 | 14 | 10 | 10 | 5 | **88** | Forecast Calibration Ledger: schedule AL-3b/AL-4a, size-controlled gates, calibration-state on every published probability/interval, and outcome reliability of confidence buckets |
| 2 | AMATH-S02 | R | P0 | 22 | 18 | 10 | 12 | 9 | 9 | 5 | **85** | Replace the single-source x0.30 value haircut with value-kept + uncertainty-carried, tested against outcomes |
| 3 | AMATH-S03 | E | P1 | 21 | 17 | 12 | 13 | 9 | 8 | 5 | **85** | Shared latent factors in simulation draws: season-level team-strength uncertainty (playoff/title) and game/team correlation (Game Day, BBLI, playoff) |
| 4 | AMATH-S04 | R | P0 | 20 | 19 | 11 | 14 | 8 | 8 | 4 | **84** | Measured weekly predictive marginals: replace fallback CVs, SD-proportional-to-remaining in-progress scaling and the truncated Gaussian with PIT-measured, position-pooled (empirical-Bayes) dispersion, sqrt(f) remainder scaling and a hurdle/skewed shape |
| 5 | AMATH-S05 | E | P1 | 22 | 18 | 10 | 13 | 8 | 8 | 5 | **84** | Point-in-time FAAB market refit with winner-censored (order-statistic) likelihood |
| 6 | AMATH-S06 | R | P1 | 17 | 17 | 13 | 15 | 8 | 9 | 5 | **84** | Uncertainty-derived no-action threshold for streaming |
| 7 | AMATH-S07 | N | P1 | 22 | 15 | 12 | 12 | 9 | 9 | 4 | **83** | Dynasty value uncertainty band: family-bootstrap band now (named alternate concept) and a stratified, outcome-calibrated revision-risk interval later |
| 8 | AMATH-S08 | N | P1 | 20 | 17 | 11 | 12 | 9 | 9 | 4 | **82** | Market Clearing Percentile plus board-noise decomposition of accepted-trade residuals |
| 9 | AMATH-S09 | R | P1 | 18 | 16 | 12 | 13 | 8 | 9 | 5 | **81** | Drop-Regret Curve: empirical value-transition kernel replacing protection PRIORs |
| 10 | AMATH-S10 | R | P1 | 19 | 18 | 12 | 12 | 9 | 7 | 4 | **81** | Validate or relabel the Finder/Angle 'arbitrage' edge (convergence test) |
| 11 | AMATH-S11 | N | P2 | 20 | 15 | 12 | 12 | 9 | 9 | 4 | **81** | Roster Fragility Index and Hidden Weakness (expected points at risk per slot) from one exact-lineup scenario engine |
| 12 | AMATH-S12 | REMOVE | P0 | 12 | 19 | 15 | 14 | 6 | 9 | 5 | **80** | Hide or relabel the live trade Monte Carlo 'win rate' built on a synthetic flat +/-15% band; replace only once real per-asset bands exist |
| 13 | AMATH-S13 | E | P0 | 14 | 18 | 14 | 15 | 8 | 6 | 5 | **80** | Record pre-auction board + roster snapshot before the 2027 rookie auction |
| 14 | AMATH-S14 | E | P1 | 16 | 18 | 11 | 13 | 9 | 8 | 5 | **80** | Executable OD-F4 validation protocol for fairness_bands_v2 |
| 15 | AMATH-S15 | E | P1 | 14 | 17 | 15 | 14 | 7 | 8 | 3 | **78** | Hypothesis property-based invariant suite (test-only) |
| 16 | AMATH-S16 | N | P1 | 20 | 15 | 11 | 11 | 9 | 8 | 4 | **78** | Projection Blind-Spot Map (provider non-coverage as a selection process) |
| 17 | AMATH-S17 | R | P1 | 15 | 17 | 12 | 13 | 7 | 8 | 5 | **77** | Empirical-Bayes partial pooling for small-sample manager tendencies, archetypes and Sharp Score win% |
| 18 | AMATH-S18 | E | P1 | 17 | 17 | 13 | 12 | 8 | 9 | 1 | **77** | Uncertainty Grammar: fact / estimate / recommendation / unavailable |
| 19 | AMATH-S19 | E | P1 | 15 | 17 | 13 | 13 | 6 | 8 | 5 | **77** | Empirical-Bayes credibility for BDVM n_prior |
| 20 | AMATH-S20 | E | P2 | 17 | 17 | 11 | 12 | 8 | 8 | 4 | **77** | Hierarchical monotone rookie hit-rate priors (BDVM pick outcomes) |

**Rescoring on merge (only where combined evidence justified it):**

- **S01** 87 → 88: strategic 9 → 10, because five lanes independently found their probabilistic items unadjudicable
  without it.
- **S10** 80 → 81: justification 17 → 18, because VALUATION D2 and TRADES §8.2 are two separate diagnostics that
  agree.
- **S12**: score kept, horizon P1 → P0, because a live number presented as a probability is a correctness defect.
- **S38**: score kept, horizon → P0 for the missing → 0 fix only.
- **S39**: score kept, horizon P3 → P2, to align the two lanes.

All other merged items keep their primary lane row's score.

---

## 10. Five proof-of-concept specifications

Four of five are outside projections/IDP. Each is a separately preregistered **new** study. None touches the frozen
IDP or ROS H1 protocols. Full detail is in the cited lane section.

### POC-A — Single-family value treatment judged on outcomes (AMATH-S02; VALUATION POC-V1)

- **Formulas.** Arms H: ŷ = 0.30·o; N: ŷ = o; C: ŷ = min(o, U), where U is the smallest published-cutoff
  contribution among healthy, eligible, dynasty-verified absent families whose board reaches the player's depth.
  Loss L = median_i |log ŷ − log y|, where y is the canonical value on the first later board with ≥ 2 voting
  families.
- **Data.** Sparse-evidence shadow ledger (box-local) plus weekly `value_replay` rebuilds up to 2026-10-20T20:00Z.
  Later archives are sealed for V2.1.
- **Point-in-time cutoff.** Board at t only. The outcome board must be strictly later and built by the same code
  revision.
- **Validation.** Parameter-free arms, so no training window. Horizons h = 28 and 56 days, preregistered. Rows with
  no outcome are a separate censored stratum.
- **Leakage safeguards.** Preregistration before any score; refuse outcome boards from a different code revision;
  sealed boards unread; no post-hoc gate edits (the G2c lesson).
- **Effective n.** Perhaps 100–300 row-origins (HYPOTHESIS until the ledger is counted). The unit is distinct
  players; cluster by player.
- **Uncertainty.** Paired loss differences, player-clustered bootstrap with 4,000 resamples, 90% CIs.
- **Multiplicity.** Three pairwise comparisons, Holm.
- **Compute.** Minutes.
- **Acceptance.** C or N beats H at both horizons, and G2a/G2b/G3/G4 pass. If N is non-inferior to C, prefer N.
- **Rejection.** H not beaten; C's bound coverage < 0.6; any top-200 entry; fewer than 60 distinct players with an
  outcome (underpowered, keep accumulating).
- **Rollback / monitoring.** Shadow until a human promotes. Flag `sparse_evidence_estimator`. Weekly bound coverage
  and top-400 entrants.
- **Replace or supplement:** **REPLACES** the ×0.30 constant, gated on owner decision OD-AM-1.

### POC-B — Season-level team-strength uncertainty with size-controlled gates (AMATH-S03a + S01; ROSTER POC-1)

- **Formulas.** Y_{t,w} = θ_t + ε. Champion: θ_t fixed at the composed mean. Challenger: θ_t ~ N(μ̂_t, τ_t²),
  drawn once per simulated season.
  - μ̂_t = (n ȳ/σ² + m/κ²) / (n/σ² + 1/κ²)
  - τ_t² = 1 / (n/σ² + 1/κ²)
  - κ² by method of moments
  - optional local level θ_{t,w} = θ_{t,w−1} + η
- **Data.** `dynasty_main` 2024–2026 matchups via the `previous_league_id` chain. The presim arm runs only on 2026
  archived forecasts. No point-in-time rosValue exists before 2026-07-14; this is stated, not imputed.
- **Point-in-time cutoff.** Before week w kickoff, using scores ≤ w − 1.
- **Validation.** κ², q and residual variance are fit on training weeks only. Evaluate on both the D11-incumbent and
  D11-corrected arms.
- **Leakage safeguards.** Origin-stamped inputs; a script asserts no week ≥ origin enters; refit per fold.
- **Effective n.** About 250 game outcomes per origin set, block-bootstrapped by season-week. Seed RPS rests on 36
  team-seasons and is descriptive if its CI spans 0.
- **Uncertainty.** Season-week block bootstrap, 2,000 reps.
- **Multiplicity.** Holm over P1 (matchup log score) and P2 (seed RPS). Gates are admitted only if a calibrated
  synthetic model passes ≥ 90% at the real n.
- **Compute.** Minutes on a laptop.
- **Acceptance.** P1 gain 95% CI > 0, P2 not worse, reliability slope toward 1, and the gain holds under the
  D11-corrected arm.
- **Rejection.** P1 CI ≤ 0; τ CV across folds > 50%; the gain vanishes under D11-corrected.
- **Rollback / monitoring.** Research module only. Any adoption needs a default-OFF flag, an owner decision, and
  live Brier by origin week from the forecast archive.
- **Replace or supplement:** **REPLACES** the fixed-mean season draw, behind a flag. The MD-11 wording stays until
  S01 shows calibration.

### POC-C — Measured weekly predictive marginals for Game Day (AMATH-S04; PROJECTIONS PoC-1)

- **Formulas.**
  - Champion F: y ~ max(0, N(μ, max(0.5, cv_F·μ))).
  - Challenger M: log(y + 1) = log(μ + 1) + ε, ε ~ N(b_pos, σ²_pos), expanding window, optional shrinkage
    σ²_i = (n s² + kσ²_pos)/(n + k).
  - Challenger H: hurdle.
  - Remainder SD ∝ f^γ with γ = 0.5 fixed.
- **Data.** Kickoff-locked pregame archive (week 8+); realized points via AL-3b's proven-final rule. DNP is scored as
  a separate availability target.
- **Point-in-time cutoff.** Training weeks 8…w−1. Evaluation weeks 10–14, preregistered before 2026-11-12.
- **Leakage safeguards.** Kickoff lock; per-week frozen parameters with commit-timestamped receipts; settled stat
  corrections.
- **Effective n.** About 3,000–4,500 player-weeks (HYPOTHESIS; confirm from the archive), player-clustered. Team-level
  Brier on about 55 matchups is **underpowered** and reported only.
- **Uncertainty.** Player-cluster bootstrap B = 2,000.
- **Multiplicity.** Bonferroni over three challengers (98.33% CIs).
- **Compute.** Seconds per week, plus minutes for re-simulation.
- **Acceptance.** ΔCRPS lower bound > 0, no position significantly worse, pooled 80% PIT coverage in [0.75, 0.85],
  every position in [0.70, 0.90].
- **Rejection.** ΔCRPS upper bound < 0; coverage reached only at ≥ 1.5× width; mean ratio outside [0.85, 1.15].
- **Rollback / monitoring.** Shadow; the loader keeps refusing non-promoted artifacts; AL-4a weekly.
- **Replace or supplement:** **REPLACES** the fallback CV table as the served dispersion, after model-registry
  promotion. The joint-factor POC (FRONTIER POC-1) follows only after this passes.

### POC-D — Market Clearing Percentile and board-noise decomposition (AMATH-S08; TRADES PoC-1)

- **Formulas.** r = (U_A − U_B)/max(U_A, U_B) under `geom_q078_v1`.
  - Q_τ(r | shape, level bin, pick bin) for τ ∈ {.025 … .975}, EB pooled toward the shape margin.
  - Split-conformal with time-weighted calibration.
  - log|r| = β₀ + β_shape + γ·log σ_board + δ·ℓ + ε.
- **Data.** Box ledger: board strictly before the trade, ≤ 7-day lag, superflex, all assets priced. Training runs
  from 2026-07-14 to a preregistered freeze F.
- **Validation.** League-disjoint split, plus ≥ 2,000 prospective unequal-count trades after F.
- **Leakage safeguards.**
  - The `residual_eligible` lookahead refusal.
  - No KTC-Trades-in-sample rows in any test that grades KTC.
  - Lineage-aware splits.
  - Hyperparameters frozen on discovery.
- **Effective n.** About 9,300 trades per half, but the clusters are leagues (11,565) and manager-lineage
  components (about 2–4 giant). Report coverage league-capped (≤ 3 trades per league). γ is descriptive if only 2–4
  components exist.
- **Uncertainty.** League-cluster bootstrap; pinball / interval score.
- **Multiplicity.** Primary endpoint: pooled 80% coverage plus the worst shape (Holm across shapes). γ is a single
  coefficient.
- **Compute.** Minutes on the box.
- **Acceptance.** Prospective 80% coverage in [0.75, 0.85] pooled, every shape in [0.70, 0.90], and an interval score
  better than unconditional quantiles. γ > 0 in both source families.
- **Rejection.** Coverage out of band or no interval-score gain (keep descriptive aggregates only); γ CI including 0.
- **Rollback / monitoring.** JSON aggregates only. A private product would carry a monthly coverage monitor with
  auto-hide outside [0.70, 0.90]. It never touches bands, q or values.
- **Replace or supplement:** **SUPPLEMENTS** the fairness bands. It is a separately named market-behaviour concept
  and is private; a public version is owner-gated.

### POC-E — Does board − market disagreement predict market convergence? (AMATH-S10; TRADES PoC-2)

- **Formulas.** Δ_{i,t,h} = log M_{t+h} − log M_t = α_t + β·g + θ·x + u.
  - g = log B − log M; the primary form is g′ = B₋KTC − M, so KTC is not regressed on itself.
  - α_t are time fixed effects.
- **Data.** 110 archive days (2026-07-14 → 2026-11-01), h ∈ {14, 28}. IDP is restricted to dates where IDPTC
  content changed, or dropped.
- **Point-in-time cutoff.** B is the point-in-time board, rebuilt from archived payloads with the pinned pipeline
  commit or read from `src/history` `canonical_board`. The last origin satisfies t + h ≤ freeze.
- **Validation.** Non-overlapping origins only (about 7 at h = 14, 3 at h = 28), plus prospective origins every 14
  days.
- **Leakage safeguards.** Point-in-time board only; the KTC-excluded gap; the IDPTC staleness rule.
- **Effective n.** About 350 players per origin, but inference is time-clustered. Use two-way clustered errors with a
  wild-cluster bootstrap.
- **Multiplicity.** Primary: offense, h = 14, g′. The rest are secondary, with Holm.
- **Compute.** About 1–2 h CPU to rebuild boards; no network.
- **Acceptance.** β > 0 with its CI excluding 0, the same sign at h = 28, and the top-decile g portfolio beating the
  bottom decile on prospective origins.
- **Rejection.** β CI includes 0, or β is negative. Then recommend relabelling "arbitrage" as "disagreement"
  (owner decision OD-AM-4).
- **Rollback / monitoring.** Research only; finder scoring is unchanged.
- **Replace or supplement:** **Decides** whether the Finder/Angle "edge" framing is **REPLACED** by "disagreement"
  copy. It never changes ranking without a separate decision.

---

## 11. Unified statistical architecture — reuse the canonical owners

No new valuation, scoring, lineup or identity owner is proposed. Statistical work plugs into existing owners through
seven shared foundations.

```
Point-in-time inputs (temporal ledger src/history, forecast_archive, game_day archive, pregame archive, box ledgers)
  -> identity (src/identity/resolution.py, picks.py)  +  source lineage (config/sources/source_lineage.json, source_census)
  -> exact scoring (src/league_intel/scorer.py)  +  roster eligibility (src/ros/lineup.py::resolve_starter_slots)
  -> F1 typed predictive-distribution artifact (marginals S04, shared factors S03, missingness states S16/S30)
  -> exact lineup per draw (src/ros/lineup.py::solve_optimal_assignment) + replacement (league_intel/replacement.py,
     draft/displacement.py)
  -> F2 calibration ledger (model_registry/projection_scorecard.py, game_day_calibration.py) -> calibrationState
  -> F7 decision layer: expected utility vs NO ACTION (streaming, FAAB, drops, trades) -- recommendation != execution
  -> display through the Uncertainty Grammar (S18): fact / estimate (with calibration status) / recommendation / unavailable
Dynasty market value (data_contract._compute_unified_rankings) stays a SEPARATE lane; F4 adds bands and explainers beside
it, never inside rankDerivedValue.  Model governance (src/model_registry/*) promotes nothing on its own.
```

| Foundation | Reuses | Serves |
|---|---|---|
| **F1** Typed predictive-distribution artifact (domain, freezeTimestamp, cardFingerprint, lineage, calibrated flag; #2053 §3 schema) | `scorer.py`, `forecast_archive.py`, `sim_calibration.py` | S03, S04, S11, S26, S37 |
| **F2** Calibration ledger + size-controlled gates + calibrationState | `projection_scorecard.py`, `game_day_calibration.py`, `scripts/sim_calibration_gate_operating_characteristics.py` | every probability item; promotion evidence |
| **F3** Dual-clock point-in-time as-of (observed_at and recorded_at ≤ T; DFS lesson L2) | `src/history/asof.py` | S05, S08, S09, S10, all POCs |
| **F4** Family bootstrap / exact leave-one-family-out recomputation | `data_contract` blend, `/api/rankings/overrides` path | S07, S22, S28, S29, S02 |
| **F5** Empirical-Bayes pooling helper (conjugate scipy; no new dependency) | numpy/scipy only (`requirements.txt`) | S17, S19, S20, S39, S04 |
| **F6** Shared-shock draw module (game, team, season factors) | `game_day_sim.py`, `playoff_sim.py`, `best_ball_utility.py` (paired CRN) | S03, S11, S23 |
| **F7** Decision layer with explicit NO ACTION and SD-scaled thresholds | `streaming_solver.py`, `faab_engine.py`, `trade_decision.py` (shadow only for trades) | S06, S09, S23, S26, S35 |

Library posture (FRONTIER §2.3): keep serving on numpy/scipy; statsmodels is the first add *if* a model graduates.
Stan, PyMC and NumPyro are research-box only. MAPIE, pyvinecopulib, cvxpy, POT and DoubleML are rejected as serving
dependencies. `hypothesis` is a test-only candidate in `requirements-dev.txt`, subject to execution authority.

---

## 12. Competitive research (with sources)

From FRONTIER §2. Every competitor-novelty statement is **uncertain**, because most methods are paywalled or
undisclosed.

- **Ranges are common; audited coverage is not.** 4for4 publishes volatility-based floor/ceiling
  (https://www.4for4.com/2015/w1/floor-ceiling-projections-draftkings10-ppr), Fantasy Labs a top-15% ceiling
  (https://fantasylabs.com/?p=131153), Yahoo Plus min/max (https://help.yahoo.com/kb/SLN37118.html), and Draft Sharks
  an injury "confidence interval" (https://www.draftsharks.com/injury-predictor/about). No product was found
  publishing realized coverage of its ranges, which is the gap the S01 ledger fills.
- **Correlated simulation is standard in DFS, not in season-long odds.** Sources: Haugh & Singal
  (https://papers.ssrn.com/abstract=3393127), Hunter, Vielma & Zaman (https://arxiv.org/pdf/1604.01455), teammate
  correlation (https://arxiv.org/pdf/2112.07002), Stokastic
  (https://www.stokastic.com/articles/dfs-strategy/dfs-projections-vs-simulations). Applying it to best-ball league
  matchup and median odds (S03) appears uncommon.
- **Dynasty value products publish point values.** KTC (crowd votes), FantasyCalc (league trades) and Dynasty Daddy
  algorithms could not be verified: the FAQ pages returned 404 or title-only content. No posterior bands on dynasty
  values were found (S07: uncertain-novel).
- **Accuracy tracking exists for ranks, not probabilities.** See FantasyPros' accuracy methodology
  (https://www.fantasypros.com/about/faq/football-draft-accuracy-methodology/).
- **Boom/bust and AI insights do not disclose calibration.** See ESPN/IBM
  (https://betanews.com/2025/09/24/espn-fantasy-football-adds-ai-powered-weekly-insights-from-ibm-watsonx/).
- **Methods literature used.**
  - Gneiting & Raftery 2007 on proper scoring
    (https://sites.stat.washington.edu/people/raftery/Research/PDF/Gneiting2007jrssb.pdf).
  - Gibbs & Candès 2021 on Adaptive Conformal Inference
    (https://proceedings.neurips.cc/paper/2021/hash/0d441de75945e5acbc865406fc9a2559-Abstract.html).
  - Barber et al. on time-series conformal (#2053 references).
  - Adams & MacKay 2007 on BOCPD.
  - Efron & Morris 1975 on empirical Bayes.
  - Pakes et al. 2015 and Chernozhukov, Hong & Tamer 2007 on moment inequalities.
  - Cameron, Gelbach & Miller 2008 on the wild-cluster bootstrap.
  - Uncertainty UX: Hullman et al. 2015 on HOPs (https://pmc.ncbi.nlm.nih.gov/articles/PMC4646698); Kale, Kay &
    Hullman 2020 (https://idl.uw.edu/papers/effect-size-judgments); Kay et al. 2016 on quantile dotplots (DOI to
    verify).
- **Combined novelty statement.** No public product was found combining exact per-league scoring and best-ball
  lineups, family-independence accounting, bottleneck evidence confidence, missing-is-never-zero states and labelled
  uncalibrated odds. Absence of public documentation is not absence of the feature.

---

## 13. Roadmap reconciliation

### 13.1 Reconciliation with #2053 (no duplication)

| #2053 item | Disposition in this synthesis |
|---|---|
| AMATH-1 / S1 hierarchical IDP event rates | **RETAINED as #2053's item** (IDP owner; the frozen prospective study decides). Extended, not duplicated, by S16 (provider non-coverage) and S19 (BDVM n₀) |
| AMATH-2 / S4 multiweek risk-aware streaming, Wasserstein DRO | **SUPERSEDED in sequencing → BLOCKED** (S51). Its cheap sub-components go first: S06 (SD-scaled no-action threshold) and S26 (exceedance ranking). Reason: the decision layer owns about 6% of hindsight headroom |
| AMATH-3 / S3 source-independent distributional ensemble and calibration | **Method retained; realized as** S01 (ledger and gates) plus S04 (measured marginals); S07 is the dynasty analogue, kept separate from weekly/ROS |
| AMATH-4 ROS position-scale / points distributions | **Retained; G3 stays FAILED.** Input side extended by S30 (rank censoring) and S47 (multiplier ablation). The frozen ROS H1 study decides |
| AMATH-5 formal logic / CP-SAT / Z3 | **SUPERSEDED in method** by S15 (Hypothesis plus exhaustive enumeration; SMT rejected) |
| S2 latent IDP role | **RETAINED** (IDP owner). S25 is the offense extension and shared surface |
| S5 missingness audit | **Extended** by S02, S16, S30, S38 and S05 |
| S6 joint dependence | **Realized as** S03 (plus pure-maths row 6) |
| S7 BMA / HMC | **REJECTED for now** (one effective weekly family); the cheap version is S49 |
| S8 causal | **REJECT reaffirmed** (S62) |
| S9 sparsity | **Deferred** (P3) for projections; **REJECT** for valuation |
| S10 EVT | **REJECT** (S61) |
| Pure-maths rows 7 / 8 / 9 / 10 | Row 7 → S39; row 8 → S08 and S23; row 9 → S05 and S46; row 10 TDA → REJECT (S63) |

### 13.2 Existing roadmap IDs touched (pointers only)

- **MD-4 / MD-11 / D11 / NC-A** (ROS hold, uncalibrated-odds wording, double count, scale): S01, S03, S04, S30, S47
- **MD-7 / MD-8 / IST / FC-05 / inventory 3.9** (streaming): S06, S09, S16, S26, S51
- **OD-F4 / OD-F1…F5 / inventory 2.1** (fairness bands, trade calculator): S08, S12, S14
- **inventory 2.3 / C3-XMKT-01** (Finder): S10, S45
- **C6-MGR-01 / Sharp**: S17, S44
- **C7-POST-01 / inventory 2.12** (posture): S41
- **C1-U7 / C7-PICKGEN-01 / backlog §3** (picks): S24, S31
- **inventory 3.1 / faab-model** (FAAB): S05, S27, S46
- **inventory 3.5–3.6** (Perfect Draft): S13
- **FC-04 / IDPV** (cross-position): S30, S47, #2053 AMATH-4
- **FC-06 / FFBB-5** (contender path): S11, S35, S43
- **FC-07 / AL-1 / Hill gate 7** (sources and validation): S21, S36, S50, S60
- **B11 / backlog §5 Consensus Edge**: S01, S28, S22
- **Game Day (backlog §11, inventory §13.2)**: S01, S03, S04, S53
- **FFBB-2 / inventory 1.2** (weakness): S11
- **BDVM (inventory §8)**: S19, S20, S39

Routing to `docs/OWNER_REQUESTED_TODO.md` (AMATH-01 → "AMATH sitewide audit" block), `docs/MASTER_PRODUCT_PLAN.md`
§14, and dated cross-reference notes in `docs/OWNER_PRODUCT_BACKLOG_SPEC.md` and
`docs/OWNER_FEATURE_INVENTORY.md`. `docs/EXECUTION_PLAN.md` is unchanged.

---

## 14. Recommended development sequence

Priority is not authorization; each phase still needs execution-plan authority and owner gates.

**Phase 0 — correctness and data foundations (no new model).**

1. Schedule AL-3b / AL-4a and build the calibration ledger with size-controlled gates (S01).
2. Hide or relabel the trade MC win rate (S12; owner decision).
3. Fix `infer_archetype` missing → 0 (S38).
4. Fail-closed FAAB config (S27).
5. Record the pre-auction snapshot before the 2027 rookie auction (S13; time-critical, irreversible if missed).
6. Preregister POC-A for the single-source haircut (S02; owner decision on the central value).
7. Start POC-C's measured marginals as soon as weeks 10–14 are archived (S04).

**Phase 1 — short-term predictive work.**

- S03 (season team-strength uncertainty, then game factors).
- S05 (FAAB point-in-time refit).
- S07 (family-bootstrap band).
- S10 (Finder convergence test).
- S08 / S14 (clearing percentile, OD-F4 protocol).
- S15 (Hypothesis).
- S16, S19, S21, S22, S25, S28, S30, S31.

**Phase 2 — medium-term decision work (only after Phase-1 inputs pass the ledger).**

- S06 / S26 (streaming threshold and exceedance).
- S09 (drop regret).
- S11 (fragility).
- S23 (regret / No-Action shadow).
- S24 (pick slots).
- S33, S35, S37, S41.

**Phase 3 — long-term speculative research.**

- S43 (future roster paths), S46 (FAAB shadow price), S48 (moment-inequality q).
- BLOCKED items S50–S53, re-opened only when their stated data or headroom condition is met. For S51 that is
  decision-side headroom > 5 points per decision-week with a calibrated forecast.

---

## 15. Answers to the fifteen strategic questions

1. **Strongest replacement candidate.** The single-source ×0.30 haircut (S02). It has no evidence, the owner design
   decision already rejects it, a parameter-free outcome test is ready, and it touches deep rows, waivers and trades.
   Runner-up: the Game Day fallback dispersion (S04).
2. **System to leave alone.** The exact layers: the host-native scorer and the exact lineup solver (S57, S54). Both
   are validated against independent ground truth and nothing statistical improves them. Also leave alone:
   `geom_q078_v1` (frozen R1 KEEP), the count-aware blend with family cap and equal family weights, and the
   owner-protected rookie-auction curve (S58).
3. **Principle that improves the most features.** Calibration (principle 8). It gates every probability, interval,
   band, odds and decision input on the site (S01, S04, S07, S08, S14) and is the precondition for principles 6
   and 10.
4. **Principle most likely to improve decisions.** Decision theory in its simple form (principle 10). Expected
   utility vs NO ACTION, with thresholds scaled by forecast uncertainty (S06, S09, S23, S26) — **not** Wasserstein
   DRO, and only after calibration. Runner-up: missingness (principle 9), because the streaming blind spot (S16) is a
   ranking problem the optimizer cannot see.
5. **Greatest-value new feature.** The Forecast Calibration Ledger with calibration-state badges (S01).
6. **Strongest differentiation.** Publishing how right our probabilities have been (realized coverage and
   reliability), combined with exact-lineup, correlation-aware matchup odds. No competitor was found publishing
   realized coverage (novelty uncertain).
7. **Models that lean on arbitrary assumptions.**
   - Fairness bands 3.5/9/18% with a 250 floor (KTC-era).
   - The ×0.30 haircut; α = 0.10; freshness C4; Hampel K 2.75 / floor.
   - Fallback CVs; the ±15% trade band; ROS format and freshness multipliers.
   - Posture anchors and temperature; partner logits; Best Offers and Sharp Score weights.
   - Archetype thresholds; manager-archetype cut-offs.
   - FAAB toe 2.2 and the above-all-in parameters; the ten drop-protection PRIORs.
   - BDVM params, pick outcomes and n_prior 6/8.
   - Team-strength weights 0.72/0.18/0.05/0.05.
   - `FAIRNESS_TOLERANCE 769`; the Finder constants.
8. **Uncalibrated simulations and probabilities.**
   - Game Day Win Matchup % and Beat Median %.
   - Playoff, title and seed odds (labelled, MD-11).
   - Pick-projector slot distributions; pick-market c (provisional).
   - The trade MC win rate.
   - BBLI deltas (inherit the sim points model).
   - Perfect Draft P(plan wins); FAAB P(win | b).
   - Confidence buckets are ordinal evidence quality, not probabilities, and must not be shown as accuracy.
   - The partner acceptance estimate is correctly capped and not presented as calibrated.
9. **Sophisticated techniques unlikely to beat simple ones.** HMC/NUTS, Gaussian processes, Particle MCMC, vine
   copulas and normalizing flows, the regularized horseshoe, Wasserstein DRO, EVT, TDA/Mapper, BMA over one family,
   SMT, DML/TMLE, and learned source-reliability weights (already built and failed).
10. **Where data is insufficient or biased.**
    - Accepted-only trades (rejections unobserved); winner-only FAAB bids.
    - 6 streaming decision weeks; 3 league seasons (36 team-seasons).
    - No pre-kickoff projection archive before week 8, and none in the IDP retrospective.
    - Temporal floor 2026-07-14.
    - No point-in-time injury designations.
    - IDP-containing market trades are rare (138 of 18,690); 2–4 giant manager-lineage clusters.
    - Sharp snowball selection.
    - KTC Trade DB partly in-sample for KTC.
    - Box-local ledgers (FAAB history, sparse-evidence shadow, temporal ledger) were not countable from the repo.
11. **Shared foundations.** F1–F7 in §11: the typed predictive artifact, calibration ledger, dual-clock as-of, family
    bootstrap / LOFO engine, EB pooling helper, shared-shock draws and a NO-ACTION decision layer — all on existing
    owners.
12. **Five priority experiments.** POC-A (haircut), POC-B (season team-strength + gates), POC-C (weekly marginals),
    POC-D (clearing percentile), POC-E (Finder convergence).
13. **What to defer or reject.** See "Top 5 to reject or defer" below, plus S59 / S60 and all BLOCKED items.
14. **What would justify promoting a challenger over the incumbent.** All of the following:
    - a preregistration committed before outcomes are read;
    - point-in-time inputs with pinned code and input hashes;
    - comparison against the champion **and** the strongest simple baseline;
    - size-controlled gates (a calibrated synthetic model passes ≥ 90%);
    - effective-n-honest clustered uncertainty with multiplicity control;
    - non-inferiority in every major stratum, with no gain bought by widening intervals;
    - prospective replication (or explicit pilot-only labelling);
    - frozen protocols untouched;
    - an owner promotion decision, a default-OFF flag with rollback, and post-promotion ledger monitoring.

    Evaluation never self-promotes.
15. **The single best innovation.** Make every displayed number state how right it has been: the calibration ledger
    plus calibration-state on every estimate (S01 with S18). It is the cheapest item, it unblocks the rest, and it is
    rare publicly.

---

## Top 5 ideas to reject or defer

1. **Wasserstein DRO / CVaR streaming** — BLOCKED (S51) until a forecast with point-in-time skill exists.
2. **Causal DML / TMLE / SCM anywhere** — not identified (S62).
3. **Extreme value theory** — too few independent exceedances (S61).
4. **Heavy machinery before simple baselines fail** — vine copulas, normalizing flows, HMC/NUTS, BMA over one family,
   GP, Particle MCMC, TDA and SMT (S63).
5. **Learned source-reliability weighting, correlation-based vote caps, and the consensus-vs-KTC "market
   inefficiency" map** — S59 already failed its gate; caps are forbidden by the 2026-10-19 consensus directive; S60
   has no out-of-sample edge.

## Top 5 systems to preserve

1. **Host-native scorer and exact lineup / streaming / knapsack solvers** (S57, S54) — validated, no greedy fallback.
2. **Count-aware weighted mean-median, family cap and equal family weights** — owner-approved; learned weights
   failed.
3. **Missing-is-never-zero state machines** — Game Day player states (S55), the four-state availability owner, D1
   explicit projection states and the B3 evidence gates.
4. **Hill Autopilot fail-closed gate 7 with an empty independent-validation registry** — better blocked than filled
   with a dependent target (S56, S50).
5. **Honest refusals** — `partner.py` refuses to emit an acceptance probability, `geom_q078_v1` stays KEEP, MD-11
   wording and the owner-protected rookie-auction curve and draft-order rule (S58).

---

## Owner decisions surfaced

| ID | Decision needed | Items |
|---|---|---|
| OD-AM-1 | Does a single uncontradicted dynasty family keep its observation as the central value (instead of ×0.30), subject to POC-A? | S02 (AM-VALUATION-01) |
| OD-AM-2 | Trade MC win rate: hide, relabel as a gap transform, or keep until a real band exists? | S12 |
| OD-AM-3 | Fairness-band validation stays owner-gated. Approve executing the OD-F4 protocol (S14) as evidence only; any band change is a new owner version | S14, S08 |
| OD-AM-4 | If POC-E rejects convergence, relabel Finder/Angle "arbitrage" as "disagreement" (copy only)? | S10 |
| OD-AM-5 | Allow opt-in private logging of the user's own trade offers and outcomes (privacy and scope)? | S44 |
| OD-AM-6 | Extend calibration-status wording (decision 9 / MD-11) from simulator odds to every estimate surface via the Uncertainty Grammar? | S18, S01 |
| OD-AM-7 | Schedule the pre-auction board and roster snapshot before the 2027 rookie auction (irreversible evidence-timing window) | S13 |
| OD-AM-8 | Acknowledge that #2053 AMATH-2 / S4 (DRO streaming) is resequenced to BLOCKED behind forecast calibration | S51 |

---

## UNRESOLVED

- Box-local data were not available to any lane, so several sample sizes are unknown:
  - FAAB claims after 2026-07-14 (POC feasibility for S05);
  - sparse-evidence shadow ledger rows (POC-A n);
  - temporal ledger (canonical-board rerun of the S09 proxy);
  - pregame archive weeks and per-player Game Day snapshots (POC-C, γ test);
  - whether `data/league_intel/sim_points_model.json` exists on production.
- Diagnostics D1, D2, the KTC momentum test and the drop-stickiness proxy are exploratory, about 2–6 effective time
  origins, offense or composite-only, and not preregistered.
- The 29-trade band result uses reconstructed boards, not the boards served at trade time.
- The magnitude of the season-level team-strength effect (S03a) and of the agreement self-inclusion bias (S28) was
  not measured.
- Competitor methodologies (KTC, FantasyCalc, Dynasty Daddy, ETR, Rotoviz) could not be verified. Some UX citation
  DOIs are from memory.
- The UX navigation audit (PR #2051, UX-P06) is unmerged.
- No production-box state was inspected. Sealed post-T0 boards were deliberately not read.
