# AMATH sitewide audit, lane TRADES: trade calculator and advisor, trade finder and market, manager intelligence (2026-11-01)

**Status:** RESEARCH AND PLANNING ONLY. This record changes no production value, flag, fairness band, package model,
public/private boundary or deployment, and it authorizes nothing (`docs/EXECUTION_PLAN.md` remains the only
implementation authority). Priority is not authorization. It builds on the owner draft #2053
(`docs/research/ADVANCED_STATISTICAL_METHODS_CHASE_UPSIDE_2026-11-01.md`, `docs/research/ADVANCED_MATHEMATICS_FEASIBILITY_2026-11-01.md`)
and does not repeat it. Those documents rank trade decision theory as #8 (74/100) and DRO as principle 4 (92/P2).
This lane gives that ranking the codebase detail it lacked and adds the trade-specific identification analysis.

**Evidence labels:** **[DEMO]** demonstrated in this repo (file or command cited). **[EXT]** published externally (cited).
**[HYP]** plausible hypothesis. **[SPEC]** speculation.

**Machine-readable companion:** `docs/research/amath/evidence/trades_opportunities.json` (AM-TRADES-01 to AM-TRADES-16).

---

## 0. Executive summary

1. **The trade stack is mostly declared priors on top of a few strong pieces of evidence.** Fairness bands v2
   (3.5 / 9 / 18 %, a 250-point floor), the posture map, the decision rule table, the shadow v3 policy table, the
   partner-acceptance logits, the Best Offers weights, the Sharp Score weights, the manager-archetype thresholds and
   Finder/Suggestions gates are all labelled PRIOR in code or config [DEMO]. The strong evidence is the package-model
   research on 18,690 point-in-time market trades (`docs/valuation/PACKAGE_MODEL_PHASE3_RESEARCH_2026-10-20.md`)
   and the paired common-random-number best-ball utility simulation (`src/roster_intel/best_ball_utility.py`).
2. **Most surprising finding [DEMO]: real accepted trades almost never land in the "fair" band.** Of the 29 committed
   own-league multi-piece trades in `docs/valuation/evidence/package_model_hybrid_2026-10-19/research.json`, the live
   owner `fairness_bands.classify` under `geom_q078_v1` rates **6 fair, 4 slight, 8 unfair and 11 lopsided**. The
   median relative gap is 14.5 % of the larger package utility (command in §8.1; the values come from the archived
   reconstructed boards). On the 9,384-trade league-disjoint market confirmation set, equal-count trades, which no
   package model touches, show mean |residual| 0.166 under GEOM_78 (`production_phase3_run_2026-10-20.json`
   → `analysis.confirmationLeagueDisjoint.*.bins.GEOM_78.equal.meanAbs`). The bands are therefore a **normative
   statement relative to our board, not a description of what managers accept.** This changes no policy: changing the
   bands is BLOCKED-owner, and the existing OD-F4 post-launch validation (`config/trade/fairness_bands.json`
   `postLaunchValidation`, state PENDING) is the authorized route for this evidence.
3. **Can q be estimated from accepted trades? Only partially, and not by minimizing residual-to-even.** The repo has
   already shown the symptom [DEMO]. The loss keeps improving as q falls to 0.2 on own-league trades
   (`residualByQExtended`). Homogeneous formulas chase a value-level effect, and the joint fit `VG_q_c` finds
   q ≈ 0.85 with c ≈ 2,000 (Phase 3 §6). §3 names five identification failures behind this: revealed-preference
   inequalities rather than equalities, errors in variables, confounding between q and the value curve,
   context-correlated heterogeneity, and lineage clustering. A moment-inequality identified set (AM-TRADES-07) is
   the only honest estimand. The package model is not changed (BLOCKED-owner).
4. **Acceptance modelling is not identifiable from today's data [DEMO].** Only accepted trades are observed. The
   repo's own partner model says so and gates the manager term at 30 accept-and-reject decisions plus z ≥ 2
   (`src/roster_intel/partner.py::MANAGER_EVIDENCE_MIN_DECISIONS`). The fix is a data asset, not a model:
   opt-in private logging of the user's own sent offers and their outcomes (AM-TRADES-13).
5. **The causal effect of manager behaviour is not identifiable: REJECT** (§2, principle 3). Descriptive
   "realized value added versus hold" through the existing at-the-time machinery (How It Aged / `decision_replay`)
   is KEEP. Small-sample tendencies should move from hard minimum-sample cut-offs to empirical-Bayes partial pooling
   (AM-TRADES-10).
6. **Two concrete correctness and comprehensibility items.**
   - The live `/trade` Monte Carlo "win rate" runs on a synthetic flat ±15 % band, because nothing stamps
     `valueBand` (`frontend/components/ui/MonteCarloButton.jsx:65-68`; no `valueBand` producer in
     `src/api/data_contract.py`). It is therefore a deterministic monotone transform of the gap dressed as a
     probability [DEMO]. Recommendation: SIMPLIFY or REMOVE (AM-TRADES-03).
   - The Finder's "arbitrage" premise has never been validated. A quick read-only diagnostic over the tracked export
     archive found **no mean reversion** in the KTC market. It found weak momentum, with only four effective time
     origins [DEMO, exploratory] (§8.2; AM-TRADES-09).

---

## 1. Domain inventory

**Status keys:** LIVE = served by default; FLAG-ON / FLAG-OFF; SHADOW = library not on the served path;
WITHDRAWN; RESEARCH. "Evidence NONE" means no empirical fit or validation exists for the constant. The cited
documents are the evidence.

### B. Trade calculator / advisor

| # | System | Owner file::function | Status | Method | Constants and evidence | Missingness | Uncertainty | Validation | Consumers | Known defects / gates |
|---|---|---|---|---|---|---|---|---|---|---|
| B1 | Package Value Adjustment | `src/valuation_math/package_model.py` (`geom_utility`, `adjusted_pair_totals`); JS `trade-logic.js::packageAdjustPair` | LIVE `geom_q078_v1`; KTC `ktc_2026_04` shadow and rollback (`config/trade/package_model.json`) | Sorted geometric utility `U=Σ q^(i-1) v_i`, shown as a positive-only adjustment | q = 0.78 PRIOR, owner-approved 2026-10-17. Evidence: Phase 1–3 plus the v2 remeasure keep it (`docs/valuation/PACKAGE_MODEL_*`). Market best fit is `VG` q 0.85, c 2,000 (Phase 3 §6.1) | A NaN piece is priced as absent; fairness refuses non-finite input | None (point utility) | Properties pinned (monotone, symmetric, homogeneous). Residual studies on 18,690 trades. Parity fixture JS↔Py | Every trade surface (`docs/valuation/PACKAGE_MODEL_CONSUMER_INVENTORY.md`) | Market leaves the consolidating side short about 30 % (1-for-2/3) and about 13 % (ordinary/deep); explained as a value-level effect, not shape (Phase 3 §6.2) |
| B2 | Fairness bands v2 | `src/valuation_math/fairness_bands.py::classify` / `classify_packages`; JS `frontend/lib/fairness-bands.js` | LIVE | \|gap\| / max(U_A, U_B) against 3.5 / 9 / 18 %, with a 250 floor | All PRIOR, owner-approved 2026-10-20 (OD-F2/F3/F5). Cut points inherited from the KTC-era 350/900/1800 meter. Evidence NONE for calibration; OD-F4 validation PENDING | Refuses NaN, negative and inconsistent zero bases (`FairnessInputError`) | None: a point gap with a fixed threshold | Parity fixture only | Meter, balancers, Analyze market lens, Best Offers, package builder, suggestions badge, public advisor | §0.2: 6/29 completed own-league multi-piece trades read "fair" |
| B3 | Served trade decision | `src/trade/trade_decision.py::decide` (`DECISION_VERSION trade_decision_v2`) | LIVE (private) | Four-step rule table: strategy, execution gate, evidence gates, goal-keyed table over component A (band of adjusted gap net of forced releases) and B (BBLI) | `config/trade/analyze_trade.json`: materialityPpg 1.0, largeMultiple 3.0, depthNotableLossPpg 0.5, all PRIOR. Evidence NONE ("no outcome data yet") | Names each missing item → NOT ENOUGH EVIDENCE (strong) | Confidence is a weakest-axis label, never a probability. The B term respects 2× MC SE | Owner tests; `decision_replay.py` asset-only replay; team-context replay DEFERRED (no as-of rosters) | `/trade` Analyze, decision log | No outcome labels, so no regret has been measured |
| B4 | Decision engine v3 | `src/trade/decision_engine/{engine,policy,terms}.py` | SHADOW (isolation pinned) | Policy table strategy × A-class × P-class. P = C (lineup delta), or D1 (title-prob delta, materiality 0.02) / D2 (multi-season ppg) once promoted | `config/trade/decision_engine_v1.json`, all PRIOR | Imprecise C means "does not vote", never neutral | Precision gate on C | Challenger evaluation vs B3 (no labels) | None in production | D1/D2 await their lineage family's promotion |
| B5 | Best-ball roster utility (BBLI) | `src/roster_intel/best_ball_utility.py` | LIVE (Analyze lens B) | `F(R)=E[optimal legal weekly lineup]`, simulated per scenario with paired CRN draws; exact lineup solver | Per-position CV from `league_intel.sim_calibration.PointsModel` (Sim V3 failed gates; see #2053) | Unpriced players are not assignable | MC SE published | ROS calibration discrepancies, G3 FAILED (MD-4) | B3, B4 | Inherits ROS projection miscalibration |
| B6 | Multi-team engine | `src/trade/trade_ledger.py`, `analyze_service.analyze_trade_n`, `team_verdicts.py` | FLAG `trade_multi_team_analysis` default OFF (route); engine shared with advisor | Per-team perspective `packageAdjustedPairTotals(G_i,R_i)`; Kleene-AND overall; conservation check | `config/trade/multi_team.json` bounds | Unverifiable ownership becomes UNVERIFIABLE | None | N=2 parity on archived trades; `ConservationViolation` | Private route, public advisor | `findBalancers` returns nothing for N≥3 (no approved objective, SD-13) |
| B7 | Roster capacity / forced drops | `src/trade/roster_capacity.py` (`forced_drop_cost`) | LIVE (report); finder rerank with Team Context ON | Matching-based cut ladder; taxi bracketing; release cost | Ladder bound is exact (not a heuristic) | Unknown cap is unknown; unpriced drop is null | Taxi range → `forcedDropsAreUpperBound` | Tests pin agreement with `_check_legality` | All trade engines | Box replay of forced-drop selection is dormant (#1922) |
| B8 | Competitive Posture | `src/roster_intel/window.py::competitive_posture` | LIVE | Soft assignment to five state anchors (temperature 0.18); posture map plus deadline sharpening; HOLD = label-flip share on a 3×3 perturbation grid | Anchors, weights 2.0/1.0, temperature 0.18, sharpen 2.0, deltas 0.08/0.15/0.10/0.25: all PRIOR (`posture_v1_prior`). Evidence NONE | No evidence → HOLD | Perturbation grid (sensitivity, not probability) | Sweep test (labels change only via HOLD) | B3 strategy, finder future-tilt, team_impact | Never validated against what teams did |
| B9 | Monte Carlo trade | `src/trade/monte_carlo.py::simulate_trade`; UI `MonteCarloButton.jsx` | LIVE flag `monte_carlo_trade` | Triangular draws from (p10, p50, p90) per player; shared latent factors ρ_team 0.25 / ρ_posgroup 0.10 | ±15 % synthetic band, ρ values: Evidence NONE (`docs/open-modeling-decisions.md` #4) | Zero-value guard in UI | Synthetic | None | TradeMeter button | `valueBand` is stamped on no live row, so the output is f(gap) (§0.6) |
| B10 | Draft-capital stack effect | `trade-logic.js::computeStackAdjustments` | WITHDRAWN from decisions (#1527); informational note | — | — | — | — | `trade-stack-withdrawn.test.js` | Note only | #1529 prerequisites |
| B11 | Public Brisket Trade Advisor | `src/trade/public_advisor.py::reduce_fairness` | FLAG `brisket_trade_advisor` (launch OWNER-GATED, MD-6/MD-24) | Fairness-only reduction: FAIR / NOT_FAIR / UNABLE per team | `fairTradeLevels ["fair"]` (OD-F1) | UNABLE_TO_DETERMINE | None | Privacy tests (no values leak) | Public | By §0.2, most real accepted trades would read NOT_FAIR [DEMO on 29 own-league trades; HYP for the population] |
| B12 | Decision receipts / replay | `src/trade/trade_decision_log.py`, `decision_replay.py` | LIVE log; replay research tool | Append-only served-decision log; bitemporal as-of replay | `max_age_days`, `knowledge_cutoff` guards | Missing at T means missing | — | — | AL-P5 receipts | The log is not joined to what the user then did, so there are no outcome labels |
| B13 | Balancer / imbalance | `trade-logic.js::tradeImbalance`, `findBalancers`; Py `suggestions._find_balancers` | LIVE | Simulate the post-add adjusted gap (never subtract) | MAX_BALANCERS 2 | — | — | 4,000-trade seeded study: 0 misses after repair (CLAUDE.md) | Meter | — |

### C. Trade finder / market

| # | System | Owner | Status | Method | Constants and evidence | Missingness | Uncertainty | Validation | Consumers | Defects / gates |
|---|---|---|---|---|---|---|---|---|---|---|
| C1 | Trade Finder | `src/trade/finder.py` (+ `finder_value_adjustment.py`) | LIVE | Board (canonical) vs per-market retail value (KTC Market offense and picks; IDPTC IDP), with a top-150 market gate; VA-scored | MIN_ASSET_VALUE 700, MAX_BOARD_LOSS −175, ELITE 6600, ratios 0.55/0.65/0.35, CONFIDENCE_SOURCE_BASELINE 5, `_BOARD_EDGE_WEIGHT` 50, partial-arbitrage cap 8: re-derived scale ports with no fit. Evidence NONE that the gap predicts anything | Unpriced → `assetsUnpricedByBoard` | None | None of the edge itself | `/api/trade/finder`, Best Offers | Premise unvalidated; §8.2 diagnostic |
| C2 | Suggestions | `src/trade/suggestions.py` | LIVE | Rule-based sell-high/buy-low/consolidation with a board top-150 plus positional floor | `FAIRNESS_TOLERANCE 769` "undocumented legacy tuning", HIGH/LOW_DISPERSION_CV 0.12/0.04, rank bonuses 3/1/0, 2/1/0, 1.5/1/0.5: Evidence NONE | — | Source CV as a flag | — | `/api/trade/suggestions` | 769 is in KTC-era units |
| C3 | Angle finder | `src/trade/angle.py` | LIVE | Trades the counterparty's consulted market reads "even" while our board says we gain | — | `allow_unknown_value` | None | — | `/api/angle/*` | Same unvalidated premise as C1 |
| C4 | Package topology | `src/packages/construction.py::topology_is_allowed` | LIVE | \|players_A − players_B\| ≤ 1 | Owner rule (#841/#842) | — | — | Tests | All generators | KEEP (rule, not math) |
| C5 | Pick market | `src/trade/pick_market.py::unknown_slot_market_value`, `calibrated_confidence` | LIVE | `P_used = c·P + (1−c)/3` over KTC tiers; slot distribution from `playoff_sim` | PROVISIONAL_CONFIDENCE_CAP 0.5; c fitted by Brier per progress bucket once ≥ 24 outcomes | Forecast missing → equal thirds | Shrinkage weight | Brier fit designed; no outcomes yet | Generated-trade market side | Calibration awaits realized drafts. A well-designed KEEP |
| C6 | Market-trade ledger and evaluation | `src/trade/market_trade_{normalize,format,groups,ledger,eval,report,archive}.py` | RESEARCH / diagnostic (box-local `data/intel`) | PIT-priced canonical trades; residual = adjusted gap / mean side; strict prior-board lookahead guard | 7-day max board lag | All-or-nothing pricing | Bootstrap; league-clustered on box | Phase 3 audit pass (`docs/valuation/PACKAGE_MODEL_PHASE3_RESEARCH_2026-10-20.md` §1) | Package research, OD-F4 target | KTC trade DB is in-sample for KTC Trades (`isUsedInVft`) |
| C7 | chaseTradeMarket power bench | `src/trade/market_trade_sim.py`, `market_trade_sim_bench.py` | RESEARCH | Synthetic worlds; estimators: prior_only, naive_sum, Bradley–Terry, geom_huber (+ ridge to prior, recency, caps, manager effect) | Bench priors | — | Cluster-robust (lineage component) SEs | Power study (`docs/market_trades/CHASE_TRADE_MARKET_POWER_STUDY.md`) | None (production estimator `market_trade_price_model.py` does not exist) | Effective clusters about 2–4 under a giant manager component (`docs/market_trades/LINEAGE_COMPONENT_CENSUS_2026-10-21.md`) |
| C8 | Sharp Score / cohort | `src/sharp/score.py`, `cohort.py`, `config/sharp/scoring_v2.json` | LIVE | Hard gates, then a weighted percentile score; beta-binomial championship shrinkage; top-25 % percentile bar | minWinPct 0.52, subweights (winPct 0.28 …): PRIOR, "not validated against an outcome dataset" | rosterQuality None, renormalized | Championship shrinkage only | None | Sharp tracker, roster %, crawls | Raw win% (luck-heavy); snowball-discovery selection |
| C9 | Sharp market signals | `src/intel/signals.py`, `src/sharp/market.py` | LIVE | Window-safe net/volume/velocity ratios (no overlapping-window sums) | — | Volume never optional | None | None vs forward value | Sharp tracker, Insider | No forward-predictiveness test |
| C10 | Partner acceptance estimate | `src/roster_intel/partner.py::assess_partner` | LIVE in gameplan, leads, packages | Bounded logit sum around BASE_ACCEPTANCE_PRIOR 0.18; manager term gated (30 decisions, z ≥ 2) | All PRIOR; the module states acceptance rate is unidentifiable | Abstentions cost confidence (floor 0.55) | Confidence cap 0.40 reachable | None possible | Gameplan, packages, leads | Correctly modest. KEEP |
| C11 | Best Offers | `src/trade/best_offers.py`, `config/trade/best_offers_prior.json` | LIVE | Hard rules, then a weighted prior ordering | `best_offers_prior_v3` PRIOR_UNVALIDATED | Unknown → worst known in the head | — | Run receipts | `/trade` best offers | Weights await a validation target |

### K. Manager intelligence

| # | System | Owner | Status | Method | Constants and evidence | Missingness | Uncertainty | Validation | Consumers | Defects |
|---|---|---|---|---|---|---|---|---|---|---|
| K1 | Activity / trades / feed | `src/intel/manager_activity.py` | LIVE flag `manager_intelligence` | Composes canonical owners; package-graded trades | Windows 7/30/90/season; call budget 900 | Unpriced = None; partial leagues named | None | Tests | `/api/manager-intel/activity` | — |
| K2 | Draft capital and tendencies | `src/intel/manager_trade_intel.py` | LIVE | Counts and shares; age buckets | TENDENCY_MIN_SAMPLE 3 PRIOR | `insufficient_sample` state | **None**: raw shares at n = 3 | — | Profile, compare | A 3-trade share is shown as a measured share |
| K3 | Career and archetypes | `src/intel/manager_career.py` | LIVE | Threshold rules on rates/shares | ARCHETYPE_MIN_* (5 trades, 8 acquisitions, 8 own picks, 25 aged players, 4 seasons); thresholds 0.30/0.50/1.5/0.5/3.0/8.0/26.5/24.5/0.60: "PRIOR (declared, not fitted or validated)" | Insufficient / unavailable states | None (hard cut-offs) | — | Career, compare | Cliff behaviour at thresholds |
| K4 | Manager Scout and offer evidence | `src/intel/manager_scout.py` | LIVE (`/api/manager-scout`, private) | Descriptive tendency profiles; `OFFER_EVIDENCE_BASIS` = descriptive counts, explicitly not an acceptance probability | Thresholds via shares | Five explicit states | None | Tendency tests (C6-MGR-01 DEPLOYED_NOT_PRODUCTION_VERIFIED) | Private | Honest labelling; no pooling |
| K5 | Compare / leaderboard | `src/intel/manager_compare.py`, `manager_leaderboard.py` | LIVE | Percentile over a named population; competition ranking | — | Missing is unranked with a reason | None | — | Private UI | Percentiles of raw small-n rates |

**Not evaluated in depth:** the internals of `src/trade/screenshot_import/`, `ktc_import.py` and `golden_upgrades.py`
(ingestion and UX, with no material math), and FAAB (`faab_*`), which belongs to the waivers lane. Held PRs #1873
and #1852 were used as context only.

---

## 2. Ten-principle screen (trade, market and manager domains)

| # | Principle | Credible application here | Limitation / identification | Simpler competitor | Verdict |
|---|---|---|---|---|---|
| 1 | Bayesian / epistemic uncertainty | Posterior of the package gap from per-asset value uncertainty (source dispersion, freshness, confidence axes) → P(gap > 0) and expected loss of acting. BMA across package models (GEOM/KTC/VG) as model uncertainty in a private shadow | No calibrated per-asset value uncertainty exists (`valueBand` unstamped). Source spread mixes correlated families. HMC/NUTS is unnecessary because the posterior is low-dimensional | Bootstrap over source votes per asset (already-computed contributions) | E: only after AM-TRADES-08 shows what drives residual dispersion |
| 2 | Hierarchical partial pooling | Manager tendencies (beta-binomial / Dirichlet-multinomial toward league or population); Sharp win% shrinkage; clearing-residual distribution by shape × level with pooling across cells | Population prior choice; lookup selection bias (who gets searched) | Empirical-Bayes method of moments (no GP needed) | E (AM-TRADES-10, 11, 01) |
| 3 | Causal inference (SCM/DML/TMLE) | "Did manager X's trading cause their wins?" "Does following the advisor cause better outcomes?" | **Not identified.** No exogenous variation in who trades; rosters, posture and trades co-determined (confounding by team strength and window); interference (a trade changes two teams in one league); n is single digits per manager; outcomes dominated by injury/luck. DML needs unconfoundedness plus overlap and has neither | Descriptive realized-value-added vs hold at PIT values (How It Aged) | **REJECT causal language** (AM-TRADES-12). KEEP descriptive |
| 4 | Nonstationarity / latent state | Market value drift; momentum vs mean reversion in KTC (§8.2); regime around deadline and draft; drifting clearing-residual distribution | 110 archive days ≈ 4 non-overlapping 21-day origins; season-start shocks are common to all players | Rolling-window recalibration plus change-point flags | E inside AM-TRADES-01/09; a switching state-space model is premature |
| 5 | High-dimensional sparsity | Which features predict clearing residual (shape, level, picks, age, position, source family, freshness) | Already answered for the main effect by `VG_q_c` (2 params). Lasso adds little | Low-dimensional parametric decomposition (exists) | KEEP the existing decomposition; REJECT a horseshoe search |
| 6 | Multivariate / tail dependence | Correlated asset outcomes for regret/CVaR (same NFL team, same age cohort, QB-WR stacks) | The current MC uses two ad-hoc ρ. No measured covariance of dynasty value returns (110 days) | Empirical factor covariance from archive log-returns by position × age tier; Gaussian copula at most | E inside AM-TRADES-04; vine copulas / flows REJECT (data far too thin) |
| 7 | Extreme value theory | Career-ending injury / value collapse tails | Few independent tail events per season; BDVM survival hazard already owns career relevance | Discrete hazard (BDVM) plus scenario stress | REJECT EVT here |
| 8 | Conformal / calibration | Clearing percentile: where a proposed trade sits within the conditional distribution of trades that actually cleared (shape × level × time); OD-F4 band validation | Exchangeability fails (drift, league clustering, giant lineage components). Use weighted/rolling split-conformal with league-disjoint calibration and report empirical coverage, not guarantees | Empirical conditional quantiles by cell | **N/E, top item** (AM-TRADES-01, 02) |
| 9 | Nonignorable missingness / selection | Accepted-only trades (rejected proposals unobserved); trades priced only when every asset has a PIT price (1,377 excluded); superflex filter (7,064 excluded); snowball Sharp discovery | Selection on acceptance is the defining problem for q and acceptance models (§3) | Sensitivity analysis: bounds under selection (moment inequalities); report excluded-population shape mix | E (AM-TRADES-07, 13) |
| 10 | Decision theory / DRO | Replace "classify a point gap" with "choose the action with the best expected utility versus NO ACTION, with CVaR on title equity, robust to package-model ambiguity" | Needs value-trajectory and title-equity distributions that are only partly calibrated (ROS G3 failed; Sim V3 failed gates). The bands and the B3 rule table are owner-approved policy, so a utility layer can only be a **private shadow** | Scenario MC across {GEOM, KTC, VG} plus a conservative tie rule (already in v3: TIE = NO) | N (AM-TRADES-04/05/06) as shadow research. Replacing B2/B3 is **BLOCKED-owner** |

**Answer to "does decision theory give better accept/decline answers than the bands?"** In principle yes. The
bands answer "how far apart are two point estimates on our board". An accept/decline decision should answer whether
E[U(trade) − U(hold)] exceeds the cost of acting, and how bad the downside is. Three concrete reasons the current
approach is not decision-optimal:
- (a) The "too close" threshold should scale with the **posterior SD of the gap**, not a fixed 3.5 %. A 3.5 % gap
  between two well-covered stars is more certain than a 3.5 % gap built on single-source depth pieces.
- (b) Market value is a **liquidation value**. A team's utility is title equity over its window plus terminal resale
  value, so the same trade has opposite utility for PUSH and REBUILD teams. B3 handles this with a rule table instead
  of a utility.
- (c) Regret and CVaR distinguish "both outcomes fine" from "small expected gain, large tail loss". Neither the bands
  nor B3 sees that.

The honest status [HYP]: no outcome labels exist to show any decision-theoretic layer gives better *realized*
outcomes. The decision log is not joined to executed trades, and title outcomes take seasons. So the deliverable is
a shadow layer evaluated on proper scoring of its probabilistic components (title-prob calibration, value-return
coverage) and on "decision agreement and disagreement explained". It is not a promotion. CVaR or Wasserstein DRO
should start as scenario CVaR over the three package models plus value-return scenarios. A Wasserstein radius
cannot be validated with about 4 effective time origins of value history [DEMO §8.2]. This agrees with #2053
(DRO = optional challenger; complexity must be earned).

---

## 3. Can q be estimated from accepted trades? The identification problem

**Data that exists [DEMO]:**
- 18,690 PIT-graded market trades from 11,565 leagues (KTC trade database 13,124; Sharp Sleeper 4,879), box-local.
- 233 completed own-league trades from 2024 to 2026, 80 of them in the current format
  (`docs/market_trades/OWN_LEAGUE_HISTORY_CENSUS_2026-10-27.md`).
- 38 own-league trades priced on reconstructed archive boards (`research.json`).

**Current estimand.** The mean signed residual `(adj_A − adj_B)/mean adjusted side` is assumed to be 0 for accepted
trades. Minimizing J over a model family "selects" q.

**Why that does not identify q:**

1. **Revealed preference gives inequalities, not an equality.** Acceptance implies, for each team i,
   `u_i(R_i) − u_i(G_i) ≥ κ_i` (κ = hassle / transaction cost ≥ 0). With a common scale, `u_i = V + ε_i`, this gives
   a **band** for the common-scale gap: −(ε_B + κ_B) ≤ U(R_A) − U(G_A) ≤ ε_A − κ_A. The gap's expectation is 0 only if
   surplus is split symmetrically **conditional on shape**. The consolidating side in a 1-for-N is disproportionately
   a contender buying a star (posture-correlated ε). So the residual's sign by shape is confounded with who
   consolidates [HYP; the mechanism is consistent with Phase 3's persistent "consolidating side short" in every bin].
2. **Errors in variables.** Each v_i is a noisy board estimate. Package sums and orderings (sorting by noisy v) induce
   regression-to-the-mean artefacts. Phase 3 partially corrected this with a noise-balanced level [DEMO]. Sorting
   bias in `Σ q^(i−1) v_(i)` remains.
3. **q is confounded with the value curve.** `U = Σ q^(i−1) f(v_i)` cannot separate q from the convexity of f at the
   low end. The repo measured exactly this: c ≈ 2,000 absorbs what homogeneous q tried to fit, and "completed trades
   cannot distinguish (a) value scales run rich at the low end from (b) a fixed per-piece discount" (Phase 3 §6.2)
   [DEMO].
4. **Degenerate optimum.** Own-league loss falls monotonically as q → 0.2 with "no turning point"
   (`residualByQExtended`) [DEMO]. A target whose optimum is the corner "only the best piece counts" has no interior
   identification. It mixes points 1 to 3.
5. **Clustering and lineage.** Trades are not independent. Manager-lineage components give about 2–4 effective
   clusters under the Sharp snowball (`LINEAGE_COMPONENT_CENSUS_2026-10-21.md`) [DEMO]. KTC trade-DB rows are
   partly in-sample for KTC's own values (`market_trade_eval.py` header) [DEMO]. Naive CIs (Phase 3 §2 table) are far
   too narrow for inference about q itself. Clustered intervals were a box-run item.

**What is identifiable:**
- (i) The **conditional distribution of clearing residuals** given observable shape and level, which is descriptive
  and needs no structural claim (→ AM-TRADES-01).
- (ii) An **identified set** for (q, c) under the inequality model with explicit κ and a bounded heterogeneity
  assumption, estimated by moment inequalities (Pakes, Porter, Ho & Ishii 2015, *Econometrica* 83(1); Chernozhukov,
  Hong & Tamer 2007, *Econometrica* 75(5)) [EXT].
- (iii) A **conditional-logit "decoy" test**: does the actual counter-package fit better than size-matched decoys
  under each model? This is already a bench metric in `market_trade_sim_bench.py` [DEMO]. It is a ranking test
  between models, not a point estimate.

Recommendation: report q as a set, and keep `geom_q078_v1`. Any formula change is BLOCKED-owner and already
decided KEEP under frozen R1 (Phase 3 §9.3).

**Selection bias inventory for acceptance modelling:**
- Rejected, countered and expired offers are unobserved on Sleeper's public API.
- Trades with unpriced assets (IDP, deep picks) are excluded, which skews against IDP-heavy deals. Phase 3 §5A: only
  138 of 18,690 contain an IDP asset.
- The superflex filter excludes 7,064.
- KTC trade-DB rows are user-submitted (self-selection).
- Sharp rows come from snowball discovery (a skill- and activity-selected population).
- Own-league n is tiny.

Conclusion [DEMO via `partner.py` docstring and the census]: **acceptance probability is not identifiable**, and
the existing refusal to publish one is correct (KEEP). Only new decision data can change that (AM-TRADES-13).

---

## 4. Manager intelligence: small samples and causality

- **Small-sample honesty.** K2–K5 show raw shares once n ≥ 3, or apply archetype cut-offs at fixed n. Standard
  error at n = 3 for a share near 0.5 is about 0.29. A "67 % consolidator" at 2/3 is noise.
- **Proposed estimator: empirical-Bayes partial pooling.**
  - Shares (pick share, consolidation share): beta-binomial. θ_m ~ Beta(α, β), with (α, β) fitted by marginal
    likelihood or method of moments on a declared population (the league, or all managers seen by Manager
    Intelligence in scope).
  - Position mix: Dirichlet-multinomial.
  - Rates (trades per league-season): gamma-Poisson / negative binomial.
  - Publish the posterior mean with an 80 % interval and keep the `insufficient_sample` state when the posterior is
    indistinguishable from the prior. That is a principled replacement for TENDENCY_MIN_SAMPLE.
  - Archetypes become "P(rate > threshold) ≥ 0.8" instead of a cliff.
  - Reference: Efron & Morris 1975, *JASA* 70; Efron 2010, *Large-Scale Inference* [EXT].
- **Selection.** The population of looked-up managers is not random (users search notable or active managers). A
  league-level prior from the full league roster is less biased than a lookup-population prior. Report which prior
  was used.
- **Causal evaluation of manager behaviour: not identifiable** (§2, principle 3). The defensible substitute is a
  **decision-level descriptive ledger**: for each trade, the PIT adjusted gap at T (At-the-Time Grade) and the change
  since (How It Aged), aggregated per manager with pooling. It is labelled as realized market drift versus a hold
  counterfactual on the same board, never "skill caused".
  - Already-owned machinery: `src/api/trade_history_asof.py`, `decision_replay.py`, the temporal ledger.
  - Window: History floor 2026-07-14 limits it to about 3.5 months [DEMO].

---

## 5. Replacement matrix (R) and removal/simplification

| ID | Current champion | Strong simple baseline | Advanced challenger | Verdict |
|---|---|---|---|---|
| AM-TRADES-03 | MC win-rate on synthetic ±15 % bands (B9) | Show the gap and band only (already shown) | Posterior P(gap>0) from bootstrap over source votes once real per-asset uncertainty exists | **REMOVE/SIMPLIFY** now (owner UI decision); R later after AM-TRADES-08 |
| AM-TRADES-09 | Finder "arbitrage" edge = board − market, assumed to be our edge | Relabel as "disagreement" with no implied edge | Validated convergence model: E[Δ log market_{t→t+h} \| gap_t, covariates], cluster-robust, PIT | R or relabel, pending PoC-2 |
| AM-TRADES-10 | Raw tendency shares at n ≥ 3; archetype cut-offs | Show counts and Wilson intervals | EB beta-binomial / Dirichlet-multinomial pooling | R (private surfaces only) |

## 6. Enhancement rows (E)

| ID | Target | Enhancement | Principle |
|---|---|---|---|
| AM-TRADES-02 | Fairness bands v2 (B2) | An executable OD-F4 validation protocol: band hit-rates on PIT market trades by shape × level, league-disjoint, time-forward. Any band change stays a new owner-approved version | 8 |
| AM-TRADES-07 | Package q evidence (B1) | Moment-inequality identified set for (q, c); decoy-choice test across models | 9, 3 (identification) |
| AM-TRADES-08 | Residual dispersion | Errors-in-variables decomposition: regress \|residual\| on per-trade source dispersion, single-source share, freshness, confidence buckets. Shows what share of "unfairness" is board noise | 1, 9 |
| AM-TRADES-11 | Sharp Score (C8) | EB-shrunk all-play win% plus league-strength adjustment; snowball-selection sensitivity | 2, 9 |
| AM-TRADES-14 | Suggestions/Finder legacy constants (C1, C2) | Re-express FAIRNESS_TOLERANCE 769 and finder gates in band/percent units with before/after volume measurement (the code's own requirement) | heuristic hygiene |
| AM-TRADES-15 | Competitive Posture (B8) | Shadow behavioural check: does posture predict the next 4 weeks' net buy/sell direction (ordinal agreement, Brier on directional share)? Changing the map is BLOCKED-owner | 4, 8 |
| AM-TRADES-16 | Pick market c (C5) | When the 24-outcome bucket fills, add log-score / reliability diagrams and cross-season pooling of c (beta prior). The design is otherwise KEEP | 2, 8 |

## 7. New capability concepts (N)

**AM-TRADES-01 Market Clearing Percentile (genuinely original, uncertain-novelty flag below).**
- **User problem.** "FAIR / UNFAIR" on our board tells a manager nothing about whether such a deal *happens*. §0.2
  shows most real accepted deals sit outside "fair".
- **Mechanism.** From PIT-priced completed market trades, estimate the conditional distribution of the clearing
  residual r given shape (1-for-N, ordinary, deep, equal), noise-balanced level and pick share. A proposed trade's
  residual is placed as a percentile: "81 % of comparable completed trades were closer to even than this one."
  - Estimate with split-conformal / empirical quantiles per pooled cell (partial pooling across adjacent cells).
  - Use a rolling time window and league-disjoint calibration.
- **Data.** Box ledger (18,690 graded), refreshed by the existing crawlers.
- **UX (private only).** A secondary line under the meter, labelled as market behaviour and never as fairness.
- **Measurable advantage.** Empirical coverage of the predicted 50/80/95 % clearing intervals on later trades.
- **Why existing features don't solve it.** The bands are normative. KTC's trade database lists trades but
  [HYP/uncertain] does not, to our knowledge, publish a conditional clearing percentile for an arbitrary package.
- **Public/private.** Private. Exposing it publicly would be a boundary change → BLOCKED-owner.

**AM-TRADES-04 Dynasty Regret Simulator.**
- **Problem.** "Will I regret this in 1 to 3 seasons?"
- **Mechanism.** Joint scenarios over:
  - per-asset value trajectories (empirical log-return bootstrap by position × age tier from the export archive,
    with the BDVM survival hazard for the career tail);
  - season title equity (`playoff_sim` with BBLI rosters).
- **Utility.** `U = Σ_t δ^t P(title_t) · w + λ · terminal market value`.
- **Outputs.** E[U_trade − U_hold], P(regret > x) and CVaR_10 of the difference. Robust across {GEOM, KTC, VG}
  package views as an ambiguity set.
- **Data.** Exists partly. Value history covers only 110 days, so multi-season returns are extrapolated and must be
  labelled PRIOR.
- **Why new.** B3/B4 classify components. Nothing computes regret versus hold across futures.
- **Competitor overlap.** Commercial "trade analyzers" show win-now/future splits [HYP]. A paired-CRN regret/CVaR
  versus no-action is uncertain-novelty.

**AM-TRADES-05 No-Action Advantage score.**
- **Problem.** Most offers should be declined. The UI should show how strongly holding beats the best available
  alternative.
- **Mechanism.** NAA = P(U_hold ≥ U_trade) and E[(U_trade − U_hold)⁺] from the existing paired BBLI draws plus a
  gap posterior.
- **Use.** Shown with Best Offers and Finder results so "no trade" is always an explicit, scored option.
- **Data.** Existing (BBLI, board, confidence axes).
- **Why new.** Decision engine v3 has a conservative TIE = NO but no continuous advantage measure.

**AM-TRADES-06 Trade-window timing: Title-Equity Exchange Rate.**
- **Problem.** "Is this the week or season to buy or sell?"
- **Mechanism.** For each team and season, ∂P(title_s)/∂(market value moved into starters), estimated by small
  paired perturbations in `playoff_sim`, combined with the asset's expected value drift (age curve). Sell when
  marginal title equity per 1,000 market points is low and drift is negative; buy the reverse.
- **Boundary.** A separately named concept that consumes posture and never re-derives it.
- **Data.** `playoff_sim` (uncalibrated title odds, MD-11 labelling), BBLI, the archive.

**AM-TRADES-13 Private Offer Ledger (decision-data capture).**
- **Problem.** Acceptance is unidentifiable without rejects.
- **Mechanism.** Opt-in, per-user private logging of offers *the user* sent or received (from the trade page or
  screenshot import) with outcome (accepted / rejected / countered / expired), joined to the PIT board and to
  `trade_decision_log` receipts.
- **Effect.** Accumulates the decision data `partner.py`'s gate already waits for, and gives the served decision
  outcome labels for regret evaluation.
- **Privacy.** The user's own league actions only; no other manager profiling beyond existing private scope.

---

## 8. Read-only diagnostics run in this lane (exact commands and data)

### 8.1 Band classification of completed own-league trades [DEMO]

Data: `docs/valuation/evidence/package_model_hybrid_2026-10-19/research.json` → `trades.multiPieceTrades` (29
trades, values from boards reconstructed by today's pipeline over the raw payload archived before each trade). The
classification uses the live owner, unchanged.

```
python -I -c "import json,re,sys; sys.path.insert(0,'.'); from src.valuation_math import fairness_bands as fb; \
from collections import Counter; mp=json.load(open('docs/valuation/evidence/package_model_hybrid_2026-10-19/research.json',encoding='utf-8'))['trades']['multiPieceTrades']; \
v=lambda s:[float(re.search(r'\((\d+(?:\.\d+)?)\)\s*$',x).group(1)) for x in s]; c=Counter(); \
[c.update([fb.classify(*(lambda u:(u[0]-u[1],max(u)))(fb.package_utilities(v(t['A']),v(t['B']),model_id='geom_q078_v1')))['level']]) for t in mp]; print(c)"
```

Result: fair 6, slight 4, unfair 8, lopsided 11 (n = 29). Median |gap| / max U = 0.145. The 9 own-league 1-for-1
trades have median |residual| 0.117 and mean 0.206 (`trades.oneForOneNoiseFloor`). Market equal-count held-out
mean |residual| is 0.166 (`production_phase3_run_2026-10-20.json`).

**Caveats:**
- The residual denominator there is the mean adjusted side, not max U.
- Own-league n is tiny.
- Board reconstruction is today's pipeline, not the served board at T.

### 8.2 Does the KTC market mean-revert? [DEMO, exploratory, low effective n]

Data: tracked `exports/archive/*.zip` (153 archives, 110 distinct days, 2026-07-14 to 2026-11-01),
`site_raw/ktcSfTep.csv` and `site_raw/idpTradeCalc.csv`. Players only, values ≥ 1,500.
Scripts (scratchpad, not committed): `trades_lane/conv.py`, `trades_lane/mom.py`.

| test | origins | n obs / players | slope | player-cluster bootstrap 95 % |
|---|---|---|---|---|
| future 30-day Δlog KTC on log(IDPTC/KTC), origins every 14 days | 6 | 1,876 / 337 | −0.197 | [−0.286, −0.119] |
| future 21-day Δlog KTC on past 21-day Δlog KTC (non-overlapping) | 4 | 1,306 / 352 | +0.085 | [+0.009, +0.161] |
| same, 30-day | 2 | 649 / 335 | +0.093 | [−0.048, +0.210] |

**Reading:**
- IDPTC content changed on only 5 of 109 day transitions (also measured), so log(IDPTC/KTC) mostly encodes KTC's own
  past drift against a stale anchor. The negative slope therefore reflects KTC **continuing** its drift, not converging.
- Pure momentum is weakly positive at 21 days.
- With 2 to 6 time origins, common seasonal shocks are not controlled, and the bootstrap ignores time clustering.
  Treat this as "no evidence of mean reversion", not "momentum proven".
- Implication: the Finder's implied bet ("market will move to our board") is untested, and a naive gap-to-stale-anchor
  reading would bet the wrong way. PoC-2 is the proper test.

---

## 9. KEEP / REJECT list

**KEEP:**
- `geom_q078_v1` with q = 0.78. Frozen R1 decision; the identified set will not justify a point change.
- Partner acceptance model's refusal to emit a calibrated acceptance probability, and its decision-data gate.
- Roster capacity / forced-drop owner (exact matching, taxi bracketing, unknown ≠ unlimited).
- Package topology rule.
- Pick-market Brier-fitted c with a minimum-outcome gate.
- `signals.py` no-overlapping-windows rule.
- Sharp championship beta-binomial shrinkage.
- Multi-team per-team perspective and conservation check.
- Missing-evidence gates in B3 (strong: "missing is never zero" done right).
- Decision log and PIT replay guards.
- The draft-capital stack withdrawal (stays out of decisions until #1529).
- Manager Scout's "not an acceptance probability" labelling.
- `VG_q_c` as a diagnostic decomposition (not a live term).

**REJECT:**
- Causal (DML/TMLE/SCM) claims about manager skill or advisor effect: not identifiable (AM-TRADES-12).
- A logistic acceptance model fitted on accepted-only trades: unidentifiable; it would manufacture confidence.
- A Wasserstein-DRO radius for trade decisions: unvalidatable with about 4 effective time origins.
- Vine copulas / normalizing flows for asset dependence: data far too thin.
- EVT for value-collapse tails: too few independent tail events; BDVM hazard owns it.
- Horseshoe / lasso feature search on clearing residuals: the 2-parameter decomposition already explains the main
  effect.
- Re-fitting q by minimizing residual-to-even: degenerate optimum (§3.4).

**BLOCKED-owner:**
- Any change to fairness cut points, floor, basis or `fairTradeLevels`.
- Replacing the B3 rule table with a utility.
- Publishing a clearing percentile or regret score publicly.
- Changing the posture map.
- Any package-formula change or level term.

---

## 10. Proof-of-concept experiments

### PoC-1: Market Clearing Percentile and board-noise decomposition (AM-TRADES-01 + 08; feeds OD-F4 / AM-TRADES-02)

**Hypotheses.**
- H1: conditional clearing intervals estimated on earlier trades achieve near-nominal coverage on later,
  league-disjoint trades.
- H2: |residual| increases with board uncertainty of the traded assets, so part of the "unfairness" of accepted trades
  is measurement error.

**Variables.**
- For trade j: `r_j = (U_A − U_B)/max(U_A,U_B)` under the active model (the same basis as the bands).
- Shape s_j ∈ {1v1, 1vN≤3, ordinary, deep, equal-count}.
- Level ℓ_j = mean of both sides' best asset (noise-balanced, Phase 3).
- Pick share π_j.
- Board-uncertainty covariates σ_j:
  - value-weighted mean of per-asset source CV (`sourceSpread`, diagnostic field);
  - single-source share;
  - share of low-confidence assets;
  - freshness-excluded share.

**Model.**
- (a) Empirical conditional quantiles `Q_τ(r | s, ℓ-bin, π-bin)`, τ ∈ {.025,.1,.25,.5,.75,.9,.975}, with
  empirical-Bayes pooling of sparse cells toward their shape margin.
- (b) Split-conformal residual intervals with time-weighted calibration (recency half-life H chosen on discovery only).
- (c) Decomposition: `log|r_j| = β0 + β_s + γ·log σ_j + δ·ℓ_j + ε_j`, with γ the noise elasticity. Fitted on
  discovery leagues only.

**Data, cutoff, windows.**
- Box ledger as in Phase 3: board strictly before the trade, ≤ 7-day lag, superflex, all assets priced.
- Training: trades 2026-07-14 to a freeze date F declared in a preregistration committed **before** the run.
- Validation: (i) league-disjoint split as Phase 3; (ii) **prospective** trades after F (at least 2,000 unequal-count,
  about 2 weeks at October volume per Phase 3 §9.4).

**Leakage safeguards.**
- PIT board only (`residual_eligible` lookahead refusal).
- No KTC-Trades-in-sample rows in any test that grades KTC.
- Lineage-component-aware splits.
- Hyperparameters (cell edges, H, pooling strength) frozen on discovery.

**Effective n.**
- About 9,300 per half by trade, but clusters are leagues (11,565) and manager-lineage components (about 2–4 giant).
- Report coverage both trade-weighted and league-capped (≤ 3 trades/league, as Phase 3).
- For γ, use component-clustered SEs. If only 2–4 components, report as descriptive.

**Uncertainty.**
- Coverage CIs by league-cluster bootstrap.
- Pinball loss / interval score versus the baseline (unconditional quantiles of r).

**Multiplicity.**
- Seven quantiles × 5 shapes. Primary endpoint is 80 % interval coverage pooled, plus the worst shape (Holm across
  shapes).
- γ is a single preregistered coefficient.

**Compute.** Minutes on the box (pure aggregation); peak memory below the Phase 3 1,157 MB.

**Acceptance.**
- H1: prospective 80 % coverage within [0.75, 0.85] pooled, every shape within [0.70, 0.90], and the interval score
  beats unconditional quantiles with a league-cluster CI excluding 0.
- H2: γ > 0 with its clustered CI excluding 0 in both source families (KTC DB, Sharp).

**Rejection.**
- Coverage outside the bands on prospective data, or an interval score no better than unconditional, means AM-TRADES-01
  is rejected (keep descriptive aggregates only).
- γ CI including 0 means board noise does not explain dispersion, and uncertainty-scaled "too close" is not
  supported.

**Rollback / monitoring.**
- Research output only (JSON aggregates, no identifiers, Phase 3 privacy checks).
- If later productized privately: monthly coverage monitor with an auto-hide when rolling coverage leaves
  [0.70, 0.90].
- Never touches bands, q or values.

### PoC-2: Does board − market disagreement predict market convergence? (AM-TRADES-09)

**Question.** Is the Finder/Angle "edge" an edge?

**Equation.**
`Δ_{i,t,h} = log M_{i,t+h} − log M_{i,t} = α_t + β·g_{i,t} + θ·x_{i,t} + u_{i,t}`, where:
- `g_{i,t} = log B_{i,t} − log M_{i,t}`, with B the canonical `rankDerivedValue` at t;
- M is the KTC Market (offense) / IDPTC (IDP) value at t;
- x holds past h-day market momentum, age, position and confidence bucket;
- α_t is time fixed effects (absorbing common shocks).

**Interpretation.**
- β > 0: the market converges toward the board, so the edge is real.
- β ≈ 0: disagreement is not predictive.
- β < 0: the board lags the market.

**Leakage.**
- B must be the PIT board. Rebuild it from each archived raw payload with the pinned pipeline commit, as
  `research.json` did, or read `src/history` `canonical_board` lane rows (no future selection).
- KTC is itself a voter in B, so g is mechanically shrunk toward 0. Also run g′ = B_{−KTC} − M (board recomputed
  without the KTC vote) as the primary, to avoid regressing KTC on itself.
- IDPTC staleness: restrict IDP to dates where IDPTC content changed, or drop IDP and say so.

**Data and windows.**
- 110 archive days (2026-07-14 to 2026-11-01), h ∈ {14, 28}.
- Non-overlapping origins only for inference (about 7 at h = 14, about 3 at h = 28).
- Cutoff: the latest origin with t + h ≤ freeze.
- Prospective confirmation: origins after the freeze as the archive grows (one per 14 days).

**Effective n.** Players about 350 per origin, but the inference unit for β must respect time: use **time-clustered**
(origin) and player-clustered two-way SEs. With about 7 origins, report wild-cluster bootstrap (Cameron, Gelbach &
Miller 2008, *REStat* 90(3)) [EXT].

**Multiplicity.** Two horizons × {offense, IDP}. Primary: offense h = 14, g′ form. The others are secondary with Holm.

**Compute.** Pipeline rebuild of about 110 boards. The research container did this for 38 trades; budget about 1–2 h
CPU locally, no network.

**Acceptance.**
- Primary β > 0 with the wild-cluster CI excluding 0.
- Same sign at h = 28.
- Out-of-sample: the top-decile g portfolio's mean Δ beats the bottom decile on prospective origins.

**Rejection.** β CI including 0 or negative. Then recommend relabelling Finder/Angle "arbitrage" as "disagreement"
(a UI/copy change routed to the owner). No ranking change without a separate decision.

**Rollback.** Research only. Nothing in finder scoring changes from this PoC.

---

## 11. Roadmap mapping and authority

- **Related IDs:** C3-REPLAY-01, C3-AGE-01 (aging, ±200 prior), C7-DESK-01 (decision synthesis), C7-POST-01
  (posture), C6-MGR-01 (Manager Scout), C7-BEST-TRADE, C3-CAP-01, C7-PICKGEN-01, IC-3 (trade learning states
  READY / PROMISING_BUT_CONFOUNDED / INSUFFICIENT / NOT_IDENTIFIABLE), OD-F4 (band validation), MD-6 / NC-D (advisor
  labelling), MD-11 (uncalibrated odds wording), FFBB-4 (no-transaction option), MD-32 (math research continues),
  #1529 (stack effect), AMATH #8 and principle 4 (#2053).
- **Authority:** MD-32 authorizes research. OD-F4 is the existing authorized validation target. Everything that
  changes a served answer is owner-gated.
