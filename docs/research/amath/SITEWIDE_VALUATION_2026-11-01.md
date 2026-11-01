# AMATH sitewide audit — VALUATION lane (2026-11-01)

**Status:** RESEARCH / PLANNING ONLY. No implementation authority, no flag, constant, weight,
value, registry or production change. `docs/EXECUTION_PLAN.md` remains the sole implementation
authorization; priority below is **not** authorization. Scores are expert research-priority
judgments, not observed model performance.
**Scope:** directive Part 6 domains A (dynasty player valuation), Confidence, L (historical
research and adaptive learning) and M (data acquisition, quality and identity) for the Chase
Upside fantasy app only.
**Builds on:** `docs/research/ADVANCED_STATISTICAL_METHODS_CHASE_UPSIDE_2026-11-01.md` (S1-S10,
IDP/ROS-weighted) and `docs/research/ADVANCED_MATHEMATICS_FEASIBILITY_2026-11-01.md`
(AMATH-1..5). Neither covers the canonical dynasty board, the confidence gate, the Hill
registry or identity in depth, so this lane does not duplicate them. AMATH-3 (distributional
source ensemble) is the weekly/ROS analogue of AM-VALUATION-02 and stays separate: dynasty
market value is never pooled with weekly or ROS projections.
**Evidence:** `evidence/valuation_opportunities.json` (17 rows, exact schema in the shared brief).
**Worktree basis:** `C:\Users\jason\code\wt-amath` at `d1c649da2` (branch
`research/amath-sitewide-2026-11-01`), read-only.

**Evidence labels:** DEMONSTRATED-IN-REPO (file cited), PUBLISHED-EXTERNAL, PLAUSIBLE
HYPOTHESIS, SPECULATION. Two new read-only diagnostics, D1 and D2, were run for this lane
(§0). Every other number is quoted from a committed repository record.

**Market value vs modeled production value.** Throughout, the canonical board
(`rankDerivedValue`, a dynasty **market-consensus** value) and BDVM (a projection-driven
**fundamental** value) are kept separate. Nothing here proposes merging them or feeding one
into the other.

---

## 0. New read-only diagnostics (exploratory, not preregistered)

**Substrate.** I used `git show` of the committed source CSVs (`CSVs/site_raw/*.csv`) on
`origin/main`, taking the latest commit at or before each date. There are 8 offense sources,
roughly one per provider family:

- `ktcSfTep`, `fantasyCalc`, `dynastyDaddySf`, `dlfSf`
- `draftSharksSf`, `fantasyProsSf`, `flockFantasySf`, `dynastyNerdsSfTep`

OTC and PFK are excluded because they are measured or suspected KTC-dependent.

- **Players and ranks:** QB/RB/WR/TE only. The rank is the within-source offense rank, used as
  a log rank. Older CSVs that lack a position column take positions from today's CSVs.
- **Dates:** origins t0 = 2026-07-20 … 2026-09-14, weekly. The horizon is 28 days, so the last
  outcome date is 2026-10-13.
- **Held-out data:** all reads are **before the V2.1 sealed-board cutoff T0 =
  2026-10-20T20:00Z**. No sealed H board and no export archive after T0 was read. The frozen
  IDP prospective and ROS H1 preregistrations were not touched.
- **Scripts:** session scratchpad, `amath_val_d1.py` and `amath_val_d2.py`, run with
  `python -I` from the worktree. They are about 60 s each and stdlib only.
- **Independence:** windows overlap (7-day steps, 28-day horizon), so there are about **3
  effective independent windows**. There is no multiplicity correction, and both diagnostics
  are descriptive.

Each player's consensus `c` is the median log rank over the sources (at least 4) that list him
at both t0 and t1. Disagreement is `d = median|log r_s − c|`.

**D1 — does disagreement predict later consensus revision?** I computed Spearman(d at t0,
|c(t1) − c(t0)|) within each rank band.

| band (consensus rank at t0) | median ρ over 9 windows | min / max | windows with ρ > 0 |
|---|---|---|---|
| 1-50 | 0.151 | −0.151 / 0.289 | 8 / 9 |
| 51-150 | 0.157 | −0.116 / 0.370 | 8 / 9 |
| 151-300 | 0.072 | −0.116 / 0.151 | 7 / 9 |

The association is weak and positive in the preseason. It turns ≤ 0 in the window starting
2026-09-07.

The revision scale itself jumps once the season starts. For the top 50, the mean |Δ log rank|
in the low-disagreement tercile is 0.035–0.08 in Jul–Aug windows and 0.19–0.23 in windows
ending in October.

**Reading (DEMONSTRATED, exploratory).** Cross-source disagreement carries some information
about future movement, but depth and season phase dominate. An uncertainty or confidence
product driven mainly by disagreement would be miscalibrated.

**D2 — who moves toward whom?** For offense players KTC ranks in its top 300 who have at least
4 non-KTC sources, gap = (non-KTC median log rank) − (KTC log rank).

- **KTC toward the consensus:** Spearman(gap, KTC's 28-day log-rank change) has median
  **0.006**. The range is −0.068 to 0.06.
- **Consensus toward KTC:** Spearman(−gap, the non-KTC consensus change) has median **0.145**.
  The range is 0.129 to 0.301, and it is **positive in 9 / 9** windows (n ≈ 290 per window).

**Reading (DEMONSTRATED, exploratory, offense, preseason 2026).** Over 28 days, the
expert/other-market consensus drifts toward KTC, and KTC does not drift toward the consensus.
Three consequences:

- It agrees with the repository's existing **null** for the Consensus Edge mispricing component
  (`src/consensus_edge/score.py` `COMPONENT_VALIDATION`,
  `docs/measurements/consensus-edge-backtest-2026-08-04-h14.json`).
- It is lineage-relevant evidence: lagged convergence toward KTC means that "leave-KTC-out
  future consensus" is **not** a safe independent validation target for a KTC-trained Hill
  curve (AM-VALUATION-07).
- It suggests that part of the canonical board's next move is forecastable from the staleness
  of its slower voters (AM-VALUATION-11).

Several confounds are not separated here:

- slower publication cadence;
- regression to the mean in a noisier consensus;
- possible KTC influence on trade-data markets.

---

## (a) Domain inventory

Status vocabulary: live / flag-OFF / research / held / shadow.

"Constants + evidence" says whether a constant has repository support:

- **M** = MEASURED/VALIDATED
- **MR** = MECHANICALLY REQUIRED
- **P** = PRIOR/HEURISTIC
- **NONE** = no evidence found

The classes are those of `docs/MATH_MODEL_CALIBRATION_POLICY_2026-08-15.md` §2.

| # | System | Owner (file::function) | Status | Method | Constants + evidence | Missingness | Uncertainty | Validation / PIT | Consumers | Known defects / gates |
|---|---|---|---|---|---|---|---|---|---|---|
| 1 | Unified value pipeline | `src/api/data_contract.py::_compute_unified_rankings` | live | rank→percentile→Hill + value-direct votes; count-aware blend | Reference N 500 (MR coordinate); `OVERALL_RANK_LIMIT` 800 (display, MR) | unpriced rows stay unpriced; off-cap players valued only if they voted (#1101) | none (point value) | V1 value replay reproduces stamps (#1562) | every engine and surface | `blendIntegrityViolation` detector only abstains; correlated multi-source anomalies uncovered (named in CLAUDE.md) |
| 2 | Hill percentile masters | `src/canonical/player_valuation.py::percentile_to_value`; `config/model_registry/hill_scope_masters.json` | live | V(p)=9999/(1+(p/c)^s); OFFENSE c 0.110 s 1.110 | refit challengers; M on board holdouts only | n/a | none | D2 rerun 636/636 reproducible; **no independent holdout exists** (hill-d2 README post-hoc) | all rank-signal votes | docstring still says ranks past 500 clamp (tail is 904): stale doc |
| 3 | Tail policy | `src/canonical/tail_policy.py` | live | saturate past rank 904 | 904 = deepest observed source rank (M, data-derived) | n/a | n/a | measured on 2026-10-18 export | Hill | — |
| 4 | Count-aware weighted mean-median | `data_contract._mean_median_blend` | live | n=1 pass, 2 mean, 3-4 untrimmed, ≥5 trimmed; continuous weighted median | rungs MR; window median owner-approved 2026-09-26 (conditional on refresh) | absent source = absent | `sourceSpread` diagnostic | refresh evidence in SOURCE_FRESHNESS_WEIGHTING.md | all offense rows | — |
| 5 | Hampel outlier filter | `data_contract._hampel_filter_per_player` | live; V2/V2.1 **held** (#1884) | median/MAD rejection, value space | K 2.75 (P, comment-justified), min n 4 (P), floor K·MAD ≥ 1000 (P from drop-rate audits) | rejected vote = dropped, not zero | none | OIV2 comparison 2026-11-01: incumbent drops plausible votes; V2.1 fails safety gates | all non-pick rows with n≥4 | weight-blind (V2-3) |
| 6 | Freshness weighting v1 | `src/sources/freshness.py`, `dataset_state.py`, `config/sources/freshness_v1.json` | live | f = curve C4(age/E), E = p75 of learned broad-change intervals | C4 chosen as "most stable day to day" (P); quarantine 0.02 (P); state bands (P) | unknown clock → unmeasured posture | none | 14-day backtest (stability) | effective weights, confidence freshness axis | selection on stability (AM-05) |
| 7 | Freshness schedule v2 | same; `freshness_schedule_v2.json` | **held** (owner, flag OFF) | 7/14/21/30-day steps 1/.75/.5/.25/0 | owner-approved percentages (policy, not fit) | unknown update → 0 vote | none | OIV2 doc §1 computed effects | — | activation owner-reserved |
| 8 | Family cap | `data_contract.cap_family_weights` | live | family total ≤ one provider | cap 1.0 (policy) | n/a | n/a | consensus directive 2026-10-19 | blend, confidence | — |
| 9 | Single-source haircut | `data_contract._SINGLE_SOURCE_VALUE_RETENTION` | live | value × 0.30 | **NONE**; owner decision B rejects the design | lack of corroboration → value penalty | via value (wrong channel) | sparse-evidence challenger failed G2c (3.335 vs 2.0) | deep rows, waivers, trade | AM-01 |
| 10 | IDP/pick α-shrinkage | `data_contract._ALPHA_SHRINKAGE` | live | anchor + 10% subgroup voice | 0.10 picked on a stability grid with λ=0.10; λ now 0 (P, rationale stale) | — | none | `reports/alpha_lambda_joint_backtest_full.md` (Mar–Apr 2026) | IDP + pick values | AM-04 |
| 11 | MAD penalty λ | `_MAD_PENALTY_LAMBDA` | retired (0.0) | — | — | — | — | — | — | KEEP retired |
| 12 | TE basis conversion | `src/league_intel/te_premium.py::convert_te_value`, `config/weights/te_premium_curve.json` | live | base→TE++ ratio 1+a·v^-k, clamp [1.209, 2.053] | fit n=73, r² log 0.94 (M within KTC only); flat 1.10 for TEP-native (P) | non-positive → floor | none | measured once 2026-07-27 | all TE values | one provider's TEP algorithm applied to all non-TEP votes (AM-10) |
| 13 | Two-way boost | `_apply_two_way_player_boost` | live | max(offense, alt family) | one player (MR) | — | confidence re-stated after override | — | Travis Hunter | KEEP |
| 14 | Pick year-step (far future) | `_inject_far_future_pick_sources`; `pick_year_discount.json::derivedYearModel` | live | 1→2-out vendor step applied 2→3-out | 816 cell obs, holdout MAPE ~1.4% for 1→2-out (M); extrapolation **P** | unpublished year = missing until derived, provenance stamped | crossProviderDisagreement recorded, not propagated | time split; IDPTC frozen = ~1 obs per cell | picks everywhere | AM-08 |
| 15 | Pick round-step R5/R6, generic grade | `_complete_future_pick_values`; `derivedRoundModel`, `genericGradeModel` | live | rookie ladder R5/R4, R6/R5; uniform tier EV | P (labelled) | `pickValueProvenance`, never 0 | none | 6 sampled rebuilds | picks | C1-PICK-03 distributions planned |
| 16 | Pick tethering | Phase 5.2b | live | current-year slots inherit rookie pool | MR | — | — | — | picks | — |
| 17 | Blend-integrity detector | `_detect_blend_integrity_violations` | live | hull check, quarantine, contract error | ε 1e-9, quantization 1.5/0.5 (MR numerical) | — | — | tests | contract health | KEEP |
| 18 | Confidence gate (players) | `src/api/confidence.py::assess_confidence`; `config/confidence/gate_v1.json` | live | 5 axes, overall = weakest | families 5/3 (MR, blend rungs); shares 0.75/0.5 (**P**, labelled); agreement 15% (P, borrowed from /edge p70) | lost evidence seated in denominators | ordinal buckets only | **no outcome calibration found** | every row, Consensus Edge, /edge | self-inclusion in agreement (AM-13); AM-03 |
| 19 | Confidence (picks) | `assess_pick_confidence`, `_pick_confidence_from_values` | live | provider-count + CV | eff ≥ 1.5 & CV ≤ 0.15 → high; ≥ 1.0 & ≤ 0.30 → medium (P); slot synth weight 0.5 (P) | unknown provider fails closed | — | none | picks | only two pick providers exist |
| 20 | Sparse-evidence estimator | `src/api/sparse_evidence.py` | flag-OFF; shadow ledger | censor-bounded single-family estimate | gates preregistered | absence = censoring evidence | `sensitivity_uncalibrated` interval | failed G2c by construction | — | needs outcome re-prereg (AM-01) |
| 21 | KTC Market benchmark / market gap | `src/sources/ktc_market.py`; `marketGap*` | live (benchmark only; vote refused at import) | board vs KTC Crowd+Trades | — | — | — | Consensus Edge mispricing null; D2 | /edge, explainers | gap is partly self-referential (KTC Crowd and Trades vote) |
| 22 | BDVM fundamentals | `src/bdvm/{engine,survival,uncertainty,curves}.py`; `config/bdvm/params_v1.json` | live (`bdvm_engine` ON) | projection → survival-discounted surplus | **all P** ("NOT backtested truth") | unpriced with reason | σ from cv_base/drift (P) | `src/bdvm/backtest.py` harness, parity with reference | /bdvm, Fund gap, BDVM trade/roster | age/risk overlap magnitude unknown |
| 23 | Source-quality evaluator | `src/source_quality/*` | research / shadow | leakage-safe PIT panel, leave-family-out future agreement | materiality = champion MALE SE | — | date-block bootstrap CI | C1-C3 failed gate (Δ ≤ 0.00127 vs 0.00215) | AL-1 | KEEP as harness |
| 24 | Hill Autopilot + registry | `src/model_registry/{autopilot,holdout,promotion,independent_validation}.py` | live gates; promotion blocked | challenger/champion, gated auto-promotion | gate thresholds in `hill_autopilot_policy.json` | — | bootstrap robustness | `INDEPENDENT_VALIDATION_TARGETS = ()` → every run BLOCKED | Hill masters | AM-07 |
| 25 | Temporal ledger | `src/history/{store,asof,keys}.py` | live (box) | append-only as-of observations | `HISTORY_FLOOR` 2026-07-14 (MR) | before floor = `before_history_boundary` | fidelity labels | — | rank change, as-of grades | ledger is box-local; not in repo, so local research falls back to CSV git history |
| 26 | Identity resolution | `src/identity/resolution.py` | V1 served; CANONICAL_V2 shadow | deterministic ladders | — | unresolved = refused (V2) / best ladder (V1) | none | `identity_dual_read.json`: 23 / 2,015 V2 divergences | every source join | AM-09 |
| 27 | Source lineage / census / content staleness | `config/sources/source_lineage.json`, `src/sources/source_census.py`, `config/source_staleness.json` | live (observability) | declared lineage categories; content-change clocks | staleness budgets observability only | — | — | lineage sweeps (#1592), OTC remeasure | family assignment, holdouts | MD-21 IDPTC←IDP Show now vendor-stated |

---

## (b) Ten-principle screen (valuation domains)

For each principle: the champion today, a strong simple baseline, and the advanced challenger.

1. **Bayesian inference / epistemic uncertainty.**
   - *Credible use:* a latent-value measurement model on the log-value scale:
     `y_{i,f} = θ_i + b_f(band) + ε_{i,f}`, with `ε ~ N(0, σ_f²(band))`, a family random effect,
     and θ_i's posterior as the value interval. Conjugate normal or empirical Bayes is enough;
     HMC/NUTS is not needed for ≤ 15 votes per row.
   - *Limitation:* the count-aware trimmed median is an owner-approved robust estimator.
     Replacing the point value is not justified. Use the posterior only for **intervals**
     (AM-02).
   - *Simpler competitor:* weighted family bootstrap of the existing blend.
   - Verdict: **E (interval only)**.
2. **Hierarchical partial pooling.**
   - *Credible use:* fixed α=0.10 is a crude pooling weight whose selection basis has
     evaporated (AM-04). Empirical-Bayes shrinkage (James–Stein form) per position and rank band
     is the natural replacement. Also BDVM hazards and age curves pooled across positions
     (AM-12).
   - *Simpler competitor:* re-select a scalar α under a predictive target.
   - Verdict: **R/E**.
3. **Causal inference.**
   - Candidate questions: "did a news event cause the value move?" and "does a source's update
     cause others to move?"
   - Neither is identified: there is no exogenous variation, publication timing is endogenous
     to news, and lineage is partly unobserved. D2's lead/lag is **predictive, not causal**.
   - Verdict: **REJECT** causal claims; keep lead/lag descriptive.
4. **Nonstationarity / latent state.**
   - *Evidence:* D1 shows a regime change at season start. Freshness already treats age
     relative to cadence.
   - *Credible use:* (a) season-phase strata in every interval and calibration (AM-02/03);
     (b) a state-space nowcast of the board's drift as stale votes update, shown on screen only
     (AM-11); (c) change-point detection on a source's methodology (source drift), feeding the
     existing drift receipts.
   - *Simpler competitor:* phase dummies.
   - Verdict: **E/N**.
5. **High-dimensional sparsity.**
   - About 15 sources and two Hill parameters do not make a high-dimensional problem.
   - Horseshoe or elastic net would add parameters with no demonstrated misfit; the Hill
     re-tune already sits at the achievable floor.
   - Verdict: **REJECT** for valuation. The only plausible use is sparse feature selection
     inside BDVM, which is out of scope here.
6. **Multivariate / tail dependence.**
   - *Credible use:* estimated residual correlation between sources, giving an effective number
     of independent votes (Kish / eigenvalue).
   - **Owner constraint:** under the consensus directive of 2026-10-19, rank or value similarity
     alone never merges, caps, excludes or haircuts a vote.
   - So estimated correlation may only be a **diagnostic** or lineage-discovery lead feeding
     `source_lineage.json` review. It may never be a weight or a cap.
   - Concrete safe items: the self-inclusion bias in agreement (AM-13) and KTC-lineage
     attribution of the TE uplift (AM-10).
   - Vine copulas and flows: **REJECT**.
7. **Extreme value theory.** Dynasty value has no extremes to model: the top is saturated by
   construction (9999) and the tail by policy (904). **REJECT.**
8. **Conformal / calibration.**
   - *Credible use:* stratified rolling or adaptive conformal quantiles of future revision
     (AM-02), and a reliability study of confidence buckets (AM-03).
   - Exchangeability is violated by season phase and by refreshed inputs. So: strata,
     rolling-origin evaluation, coverage reported per stratum, and no finite-sample guarantee
     claimed.
   - Verdict: **N/E (highest-value principle in this lane)**.
9. **Nonignorable missingness / selection.**
   - The single-source haircut converts missing corroboration into a 70% value cut (AM-01).
   - A board's absence from a player is informative only when that board demonstrably reaches
     the player's depth: the censoring view of sparse-evidence C.
   - Identity refusal ≠ zero, which V2 already does right.
   - *Simpler competitor:* no haircut, LOW confidence, plus an interval.
   - Verdict: **R (P0)**.
10. **Decision theory / DRO.**
    - In this lane the decision is *which constants to ship*. Today several are chosen on a
      stability loss that is minimized by ignoring information (α, the freshness curve).
    - Replace this with a predictive loss defined on future, leave-family-out evidence (AM-05).
    - Wasserstein DRO over trade decisions belongs to the trade lane. It needs AM-02's
      intervals as its input first.
    - Verdict: **E** here; DRO **deferred** to the trade lane.

---

## (c) Replacement matrix

| ID | Replace | With | Why | Simpler alternative kept in comparison | Score / horizon |
|---|---|---|---|---|---|
| AM-VALUATION-01 | ×0.30 single-source value haircut | value kept, uncertainty carried (evidenceState, LOW, interval), with censor bound where an absent board reaches the depth | missing ≠ penalty; owner decision B rejected the design; the only challenger failed a gate that measured distance from the haircut | **no haircut at all** + LOW confidence | 85 / P0 |
| AM-VALUATION-04 | α = 0.10 fixed shrinkage | empirical-Bayes per-row α, or a scalar re-selected on a predictive target | the selected point (α=0.10, λ=0.10) no longer exists since λ=0; the stability metric prefers α=0 | equal treatment (offense-style blend) | 74 / P1 |

## (d) Enhancement rows

| ID | Enhance | Mechanism | Score / horizon |
|---|---|---|---|
| AM-VALUATION-03 | confidence gate → outcome calibration and axis ablation | reliability of HIGH/MED/LOW against later revision, controlling for depth; REMOVE axes that add nothing | 82 / P1 |
| AM-VALUATION-05 | stability-selected constants (α, C4, Hampel floor) → one predictive target | reuse `src/source_quality` leave-family-out future agreement; stability becomes a guard | 76 / P1 |
| AM-VALUATION-13 | agreement axis compares a family to a blend that contains it | leave-one-family-out reference | 74 / P1 |
| AM-VALUATION-08 | PRIOR pick 2→3-out extrapolation | freeze now; score when vendors first publish the next far class; compare against the global step | 73 / P1 |
| AM-VALUATION-06 | Hampel / V2.1 comparison lacks a "no filter" arm | add arm N (structural invalidity only, then the existing trimmed median) inside a new prereg before H is read | 71 / P2 |
| AM-VALUATION-10 | TE++ uplift curve measured once (n=73) and imported from one provider | versioned refits; tag converted votes with a KTC-lineage component | 67 / P2 |
| AM-VALUATION-09 | deterministic identity ladders | Fellegi–Sunter match log-odds as abstention calibration and reviewer-queue ranker (served path stays deterministic) | 66 / P2 |
| AM-VALUATION-12 | BDVM hazards and age curves (all priors) | pooled discrete-time hazard splines, rolling-origin by season | 65 / P2 |

## (e) New capability concepts

1. **AM-VALUATION-02 — Value revision-risk interval (83, P1).**
   - *User problem:* "Is 3,286 really different from 3,350, and how much could this move before
     the deadline?"
   - *Mechanism:* between-family bootstrap combined with stratified empirical/adaptive-conformal
     quantiles of |Δ log value| over a horizon h, by depth × asset class × season phase.
   - *Data:* CSV git history (point-in-time from 2026-04) and the temporal ledger on the box.
   - *UX:* a 50/80% band labelled "uncalibrated" until per-stratum coverage passes.
   - *Advantage:* trade and roster decisions stop over-reading noise.
   - *Why existing features don't solve it:* the confidence bucket is ordinal and uncalibrated,
     and `sourceSpread` is a diagnostic.
   - *Competitors:* expert rank ranges exist elsewhere; a calibrated forward band is uncertain
     novelty (SPECULATION).
2. **AM-VALUATION-11 — Board drift forecast from stale votes (72, P2). Genuinely original in
   this codebase.**
   - *User problem:* the canonical value can be mechanically about to move because slow sources
     have not caught up.
   - *Evidence:* D2 shows the non-KTC consensus converging on KTC.
   - *Mechanism:* expected drift Σ_f w_f · β(age_f, band) · gap_f, with β estimated
     walk-forward.
   - *UX:* a labelled drift arrow beside the value. It is **never added to the value, never a
     vote**, so signal independence is untouched.
   - *Measurable advantage:* lower MAE of the next board change than zero-drift, in
     non-overlapping folds.
   - *Novelty:* no known dynasty product forecasts its own consensus drift from source
     staleness (SPECULATION).
3. **AM-VALUATION-17 — Exact leave-one-family-out influence explainer (76, P1).**
   - The current explainer is a weighted-mean approximation, and the Valuation Advancement Map
     §D disproved that it equals the blend.
   - *Mechanism:* recompute the blend without each family (k ≤ ~15 per row) and publish
     V − V₋f, plus the "if every absent board listed him at its cutoff" bound.
   - It doubles as an anomaly alarm when one family moves a row by a large share.
   - *Advantage:* users can reconcile the number; the steward gets a cheap integrity signal.
4. **AM-VALUATION-07 — An independent validation target for the Hill Autopilot (67, BLOCKED
   on AL-2).**
   - A target built from format-qualified, deduplicated non-KTC completed trades (Sharp /
     own-league Sleeper), with the KTC Trade DB component excluded.
   - It unblocks gate 7 honestly instead of manufacturing a target.
   - D2 shows why the obvious shortcut fails: leave-KTC board consensus lags KTC, so it is not
     independent.

---

## (f) KEEP / REJECT

**KEEP** (with reasons):

- **Percentile Hill curve family**, 2 parameters, log-logistic (AM-VALUATION-16).
  - The rank-form re-tune sits at the achievable floor (RMSE 83.8 vs best-fit 83.4,
    `player_valuation.py` docstring).
  - The binding problem is the circular validation target, not the functional form.
  - Only defect: the stale "clamp at 500" docstring in `percentile_to_value`.
- **Count-aware weighted mean-median.** It is owner-approved, already robust, and continuous in
  the weights.
- **Family cap** (consensus directive 2026-10-19).
- **Equal-family base weights.** The learned challengers C1–C3 failed: Δ MALE ≤ 0.00127
  against a materiality of 0.00215, over 522,206 cells and 8 blocks
  (`source-quality-2026-10-01/REPORT_2026-09-30.md`).
- **λ·MAD retired** (stacked penalty).
- **Blend-integrity abstention**, the **tail policy (904)** and **`OVERALL_RANK_LIMIT`** (a
  display question, not valuation).
- **Freshness schedule v2 held.** The owner reserved it.
- **Outlier V2 held** until its gates pass (OIV2 comparison 2026-11-01).
- **Identity served path deterministic**, with V2 staying shadow.
- **Hill Autopilot fail-closed gate 7**, and **independent-validation registry empty** rather
  than filled with a dependent target.
- **BDVM kept separate** from the market board.

**REJECT:**

- **AM-VALUATION-14: KTC-vs-consensus "market inefficiency" buy/sell map.** The mispricing null
  plus D2 (KTC does not revert) mean there is no out-of-sample edge.
- **AM-VALUATION-15: another learned source-reliability system.** It duplicates the existing
  lane, and that lane failed its gate.
- **Causal (DML/TMLE) claims about source influence or news effects.** Not identified.
- **EVT and horseshoe/elastic-net for the board.** No tail data and no dimensionality.
- **Vine copulas / flows for source dependence**, and **any correlation-estimated vote cap.**
  The latter is forbidden by the consensus directive unless the owner changes it.
- **HMC/NUTS for the value posterior.** Conjugate / empirical-Bayes forms suffice at ≤ 15 votes.

---

## (g) Proof-of-concept experiments (best two)

### POC-V1 — Single-family treatment, judged on outcomes (AM-VALUATION-01)

**Hypothesis.** For non-pick rows that rest on exactly one family, keeping the observation
(arm N) or censor-bounding it (arm C) predicts the row's later multi-family canonical value
better than the incumbent ×0.30 (arm H).

**Variables.** Row i at origin t, with the single family's observed contribution `o_it`.

- H: `ŷ = 0.30 · o_it`
- N: `ŷ = o_it`
- C: `ŷ = min(o_it, U_it)`, where `U_it` = the smallest published-cutoff contribution among
  healthy, scope-eligible, dynasty-verified absent families whose board reaches the player's
  position depth (exactly `sparse_evidence.estimate`).

The outcome is `y_i,t+τ`: the canonical value on the first board in (t, t+h] where at least 2
families vote for i. Rows with no such board within h are a **separate censored stratum**,
reported but not scored against y.

**Loss.** `L = median_i |log ŷ_it − log y_i,t+τ|`. Secondary measures:

- mean absolute log error;
- bound coverage `P(y ≤ U)` for arm C;
- interval coverage of `[0.30·o, o]`.

**Data.** Two sources:

- the sparse-evidence shadow ledger (box-local, keyed by payload hash, code revision, inputs
  hash and estimator version; only records that predate their outcomes);
- weekly `value_replay` rebuilds from the committed CSV and archive history **up to
  2026-10-20T20:00Z**. Later archives are sealed for V2.1 until its Stage 4.

**Point-in-time cutoff.** Each prediction uses only the board at t. The outcome board must be
strictly later and built by the same code revision, so refreshed inputs are never compared
against old code.

**Training window.** None. All arms are parameter-free (C's bound is mechanical), so there is
no fitting and no tuning leakage.

**Horizons.** h = 28 and 56 days, preregistered.

**Leakage safeguards:**

- preregistration committed before any score;
- the evaluator refuses outcome boards with a different code revision;
- sealed H boards are not read;
- no gate is altered after the fact (the lesson of G2c).

**Sample size.** About 51 former-haircut rows per board (sparse-evidence README). With weekly
origins over ~14 weeks, perhaps 100–300 row-origins that later gain a second family. This is
a PLAUSIBLE HYPOTHESIS until the ledger is counted. Effective n is the number of distinct
players (strongly autocorrelated across origins). **Cluster by player.**

**Uncertainty.** Paired differences in loss (N−H, C−H, C−N); a player-clustered bootstrap with
4,000 resamples; 90% CIs.

**Multiplicity.** Three pairwise comparisons, Holm–Bonferroni.

**Compute.** Trivial; minutes.

**Acceptance.** Arm C or N beats H with a Holm-adjusted 90% CI excluding 0 at both horizons, and
the existing G2a/G2b (no top-200/400 entry), G3 (bounded influence) and G4 (scope) gates pass.
If N is non-inferior to C (CI on C−N includes 0), **prefer N** (fewer moving parts).

**Rejection** — any of:

- H not beaten;
- C's bound coverage < 0.6;
- any top-200 entry;
- fewer than 60 distinct players with an outcome (underpowered → keep accumulating, no
  decision).

**Rollback / monitoring.** Shadow only until a human promotes it. After promotion, monitor
weekly bound coverage, rows entering the top 400, and user-visible value deltas. The rollback
is the flag (`sparse_evidence_estimator`) or a constant revert.

### POC-V2 — Revision-risk bands and confidence reliability (AM-VALUATION-02 + 03 + 13)

**Hypothesis.** A stratified empirical quantile model of future log-value revision gives 80%
bands with near-nominal coverage per stratum. The current confidence gate adds discriminating
information beyond depth and season phase, and the leave-one-family-out agreement axis
discriminates at least as well as the self-inclusive one.

**Variables.** `r_it(h) = |log V_i,t+h − log V_it|` on canonical rebuilt boards.

The strata are:

- rank band (1-50, 51-150, 151-300, 301-800, off-cap);
- asset class (offense / IDP / pick);
- season phase (offseason / preseason / in-season).

The predictors are the confidence bucket, each axis level, family count, and D (median
abs-log deviation of family contributions).

**Model.** Band: `q̂_{0.8}(stratum, t)` = the 80% empirical quantile of r over origins
s ≤ t − h (rolling, adaptive-conformal update `α_t+1 = α_t + γ(α − err_t)` as a challenger).
The interval is `V_it · exp(±q̂)`.

Reliability: an ordinal or logistic model of `1{r > τ_stratum}` on bucket + depth. The
likelihood-ratio test is for bucket added to the depth-only model.

**Data.** Weekly `value_replay` rebuilds 2026-04-16 → 2026-10-20 (CSV git history). The
in-season part is only ~6 weeks before sealing, so in-season conclusions wait for prospective
weeks.

**Point-in-time cutoff.** The quantiles at t use only revisions fully observed by t (s + h ≤ t).
Non-overlapping evaluation folds: h = 28 days gives ~6 folds over 2026-04..10.

**Leakage safeguards:**

- no future board is used to fit;
- one code revision is pinned for all rebuilds (refreshed inputs only, as in the Hill D2
  substrate);
- sealed H boards are excluded;
- no change to frozen IDP or ROS preregistrations.

**Sample size.** About 1,000 rows × ~6 folds. The effective independent units are the folds
(~6) × players. Report fold spread, not just pooled metrics.

**Uncertainty.** Fold-block bootstrap; coverage with Wilson intervals per stratum.

**Multiplicity.** 15 strata × 2 band levels. Report all; acceptance needs every *major* stratum
(offense top-300 and IDP top-150 in each phase with data), with no cherry-picking.

**Compute.** Rebuilding ~28 weekly boards costs minutes each locally. Scoring is negligible.

**Acceptance:**

- 80% band coverage ∈ [0.75, 0.85] in every major stratum across folds;
- mean width ≤ the depth-only baseline;
- HIGH < MEDIUM < LOW in median revision in ≥ 80% of folds;
- the bucket adds significant information over depth (LR test, Holm-adjusted p < 0.05);
- LOFO agreement non-inferior.

**Rejection:**

- Coverage error > 0.10 in any major stratum.
- Bucket uninformative beyond depth: then simplify confidence to depth + family count, which
  is itself a valid, valuable outcome.
- Bands that only reach coverage at widths covering most of the scale.

**Rollback / monitoring.** Display-only, labelled "experimental, uncalibrated" until it passes
(MD-11 wording precedent). Monitor weekly coverage drift as a calibration-drift receipt
(Adaptive Learning §20).

---

## UNRESOLVED / limits

- D1 and D2 are exploratory, offense-only, preseason, on about 3 effective windows, with
  name-based joins. They may not generalize in-season or to IDP and picks.
- The magnitude of the agreement self-inclusion bias (AM-13) was not measured.
- The identity case "D.J. Moore / DL served 4983 vs V2 4961" needs Sleeper-directory
  verification.
- The temporal ledger and the sparse-evidence shadow ledger are box-local, so their sample
  sizes for POC-V1 are unknown here.
- Not evaluated: production-box state, served values, and the post-T0 boards (deliberately
  sealed).
- Owner decision needed for AM-01 (whether a single uncontradicted family keeps its observation
  as central value), as already raised in the sparse-evidence README.
