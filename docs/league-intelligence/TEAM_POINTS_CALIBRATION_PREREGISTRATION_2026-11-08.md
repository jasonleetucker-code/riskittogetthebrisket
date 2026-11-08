# Team-level points calibration for the best-ball playoff simulator: preregistration

**Status:** PREREGISTRATION. This file is committed **alone**, before the evaluation script and library exist in the
branch, and before any candidate forecast in §3 has been computed. Results will go in
`docs/league-intelligence/TEAM_POINTS_CALIBRATION_RESULTS_2026-11-08.md`. Nothing above the freeze line changes once
results are known. A later correction goes in a dated addendum below it.

**Authority and lane:** owner master directive 2026-11-08, §6 Priority 1 (finish the mathematical correctness audit).
This study is the team-level follow-up to finding **F2** in `docs/engineering/MATH_AUDIT_2026-11-08.md`, under
**RPA-LGI-008** (`docs/audits/RESEARCH_PROMOTION_READINESS_AUDIT_2026-10-25.md`). Workstream A, research only.

**What this study does not do.** It promotes nothing, and champion and challenger stay separate. It does not change:
- `src/ros/playoff_sim.py` served behaviour;
- any feature flag (`playoff_ros_counted_once` stays OFF);
- `data/league_intel/` or `config/league_intel/`;
- the served points model.

New code is a pure library module, `src/ros_calibration/team_points.py`, plus one script,
`scripts/team_points_calibration_eval.py`. The isolation test in `tests/ros_calibration/test_isolation.py` will allow
that script and nothing else. Every output carries `promotes: false`.

## 0. The question

In a best-ball league the simulator replaces each team's weekly score distribution with a **presim**
(`_bestball_presim`). The presim draws every rostered player from `PointsModel.draw(rosValue, position)`, solves the
exact lineup (`src/ros/lineup.py::solve_optimal_assignment`) on each draw, and takes the mean and sd. The served
equation (flag OFF, `ROS_EVIDENCE_INCUMBENT`) then multiplies:
- the mean by `(1 + 0.20 · z_ROS)`;
- the sd by `1.10 + 0.15 · bench/starter`.

The served points model is `fallback-constants`: mean = `rosValue / 2.7`, with fixed position CVs. No calibrated
artifact is built.

F2 measured the result on the live league after week 8:
- simulated weekly means run 117 to 524, against realized team means of 241 to 436;
- the between-team spread is about 2.3 times the realized one;
- playoff odds sit at 0% / 100%, and expected wins are 0.0 for one team.

**Question.** Is there a team-level weekly score forecast that beats the served one **and** a simple baseline out of
sample, on point-in-time inputs?

### Information known before this preregistration (disclosed)

Weeks 1–8 are **not design-blind**. Week 9 and later are the clean confirmation (§2).

1. **Published records.**
   - The F2 table gives realized weekly mean and sd per team for weeks 1–8, and the served simulated mean and sd
     after week 8.
   - D11 (`docs/research/PLAYOFF_ROS_DOUBLE_COUNT_D11.md`, weeks 1–5): the ROS multiplier stretches team means by
     about ±40% around a presim that is too low and too narrow. Removing the multiplier lowers log loss sharply but
     fails D11's PIT gate.
   - SIM_CALIBRATION v1–v3 (weeks 5–7): the fallback's player-level scale and CVs are miscalibrated.
   - ROS scale study (weeks 5–7): about 0.35 points per `rosValue` unit for offense vs 0.14 for IDP.
2. **Exploratory diagnosis run before this freeze.** A scratch script outside the branch computed the following on
   weeks 2–9, using the inputs defined in §1. It will be re-run from committed code as the `diagnose` subcommand
   (§6).
   - **Receipts.**
     - Host-native scorer vs Sleeper `players_points`: 4,833 / 4,833 player-weeks within 0.02.
     - Canonical solver over `players_points` vs Sleeper's team `points`: 95 / 96 team-weeks within 0.05. The one miss
       (week 8) is a DL/LB-eligible player whom Sleeper did not start. This is consistent with today's directory
       granting an eligibility the player lacked in week 8.
   - **Team-level numbers on weeks 5–8**, 48 team-weeks. Bias = realized − predicted. Spread ratio = SD across teams
     of predicted means / the same for realized means.

     | arm | bias | MAE | spread ratio |
     |---|---|---|---|
     | incumbent | +56 | 85 | 1.85 |
     | presim alone (no ROS multiplier) | +69 | 70 | 1.01 |
     | presim, player-level conversion C0 fitted on earlier weeks | −13 | 42 | 0.69 |
     | presim, conversion CF | −12 | 41 | 0.72 |
     | presim, conversion CR | −6 | 40 | 0.73 |

     - Calibration slope of realized on predicted: 0.47 for the incumbent, 0.89 for the presim alone, about 1.3 for
       the converted presims.
     - The presim with ORACLE availability (only players who appeared) has bias +104. That arm uses outcome
       information, so it is never a candidate.
   - **Live week-9 forward table:** it reproduces F2's served range (incumbent 117.0 to 522.7).
   - **Unpriced players:** players with no positive `rosValue` contributed 0.4%–3.7% of realized starter points per
     week.
3. **Not computed before freeze:** any forecast or metric of B0, B1, B2, A or S (§3). Also not computed: any
   win-probability, CRPS, coverage, concordance, projected-PF or expected-wins number for any arm.

The diagnosis in item 2 motivated candidate A (a team-level level-and-slope repair of the presim). That influence is
disclosed here, as the ROS scale study disclosed its use of V3.

## 1. Data, population, scoring

- **League:** `dynasty_main`. 12 teams, best ball, weekly median game ON (`league_average_match = 1`). The scoring
  card's fingerprint must equal `sf1:9e51824690d091f9`, or the run refuses.
- **Weeks:** 2026 regular season. A week is used only when the nflverse schedule marks every game final and every
  team has a numeric matchup `points`. Otherwise the run refuses.
- **Realized team-week score `y`:** Sleeper's matchup `points` (the host's awarded best-ball total).
  - Receipts are reported, never gated: scorer vs `players_points`, and canonical solver vs `points` (as in §0).
- **As-of inputs for week `k`:**
  - **rosValue snapshot:** the latest `data/ros/aggregate/history/` file STRICTLY before the week's first kickoff.
    Reused from `scripts/sim_calibration_study.py::snapshot_before`; schedule from nflverse.
  - **Roster:** week `k`'s Sleeper matchups `players`. Disclosed limitation: the list can include moves made between
    the first kickoff and a player's own game.
  - **Join:** the production join, `hydrate_roster_players` + `compute_team_strength`.
  - **Slots:** `load_league_starter_slots("dynasty_main")`.
  - **Player directory:** today's Sleeper `players/nfl` (inherited caveat).
- **Availability:** NOT applied to any arm. No point-in-time injury state is archived (same as D11). So the
  reconstructed incumbent omits the served availability calendar.
- **Leakage rule (enforced in code, pinned by a test):** the week-`k` forecast of every arm reads only:
  - realized scores of weeks `< k`;
  - week `k`'s as-of snapshot and roster;
  - week `j`'s as-of presim for each `j ≤ k`.

  The forecast function raises if any realized week `≥ k` reaches it.
- **Network:** read-only public Sleeper and nflverse GETs, cached write-once in gitignored
  `data/team_points_calibration/cache/`. Cache-body sha256 values go in the evidence.

## 2. Split (rolling origin)

| block | target weeks `k` | role |
|---|---|---|
| **primary holdout (gated)** | **5, 6, 7, 8** (48 team-weeks, 24 head-to-head games, 48 median games) | not design-blind (§0) |
| development (reported, never gated) | 3, 4 | |
| confirmation (deferred) | 9 and later, once final | dated addendum, method frozen, no refit rule changes |

## 3. Candidates

Every arm outputs a Normal `(μ, σ)` per team-week. This is the production `_TeamDist` form. Production truncates
draws at 0, which is immaterial here because μ is many σ above 0.

| id | role | μ | σ |
|---|---|---|---|
| **I** | champion (served) | the production path: `_bestball_presim(…, random.Random(20260428), PointsModel())`, then `_team_distributions_from_inputs(…, best_ball=True, ros_counted_once=False)` | same call |
| B0 | reference only, never a challenger | mean of all team-weeks `< k` | their sample SD × √(1 + 1/n) |
| **B1** | simple baseline | team mean of its weeks `< k` | team sample SD (n−1) × √(1 + 1/n_t); needs n_t ≥ 2 |
| **B2** | simple baseline | as B1 | pooled within-team SD `s_p = √(Σ_t Σ_j (y − ȳ_t)² / Σ_t (n_t − 1))` × √(1 + 1/n_t) |
| **A** | challenger | OLS `y = α + β·P` over all team-weeks `j < k`, where `P_{t,j}` = the presim mean (fallback model, NO ROS multiplier, week-`j` as-of inputs); μ = `α + β·P_{t,k}` | OLS prediction SD: `s·√(1 + 1/n + (P − P̄)²/Sxx)`, with s the residual SE on n − 2 dof; needs n ≥ 12 |
| **S** | challenger (the one more sophisticated model) | OLS `y = α + β·P + γ·M` over training rows `j ∈ [3, k−1]`, where `M_{t,j}` = the team's mean of weeks `< j` | OLS prediction SD with full-design leverage `s·√(1 + x₀ᵀ(XᵀX)⁻¹x₀)`, n − 3 dof; needs ≥ 24 rows |

**Why S.** The presim carries forward-looking roster information that a trailing mean lags (trades, the snapshot's
injury and depth reads). The trailing mean carries realized team strength that `rosValue` misses: the diagnosis shows
a team-level calibration slope different from 1. A two-regressor least-squares combination is the smallest model
that weighs both. Its weights are learned only from earlier weeks. No regularization and no tuning.

## 4. Metrics

All metrics are pooled over the primary holdout.

1. **M1 level.** bias = mean(y − μ); MAE = mean|y − μ|; calibration slope (OLS of y on μ).
2. **M2 spread.**
   - sd ratio = z-RMS = `√mean(((y − μ)/σ)²)`. Ideal 1; above 1 means the simulated sd is too narrow.
   - Central-80% coverage of Normal(μ, σ).
3. **M3 team-order concordance.** Within each week, the share of the 66 team pairs whose μ order matches the realized
   order. Realized ties are excluded; a predicted tie counts 0.5. Pooled over weeks.
4. **M4 win probability.**
   - Head-to-head: `P(A > B) = Φ((μ_A − μ_B)/√(σ_A² + σ_B²))`. This uses the production independence assumption.
   - Median game: P(team beats the week's league median under production `game_day_sim.median_threshold`). Monte
     Carlo of independent Normals, 20,000 draws, seed `20261108 + k`.
   - Outcomes: realized win 1, tie 0.5, loss 0. The realized median uses the same `median_threshold`.
   - Scores: Brier and log loss (p clipped to [1e-6, 1 − 1e-6]) over all binary outcomes (24 head-to-head + 48
     median). Also reported per type.
5. **M5 CRPS.** Closed-form Normal CRPS per team-week; mean.
6. **M6 projected-PF error (descriptive).** For each origin `k` in the holdout and team `t`:
   - projected PF over weeks `k..8` = `(9 − k)·μ_{t,k}`, the week-`k` forecast held constant as the simulator does;
   - error = realized Σ y − projected.
   - Reported: MAE and bias over the 48 (team, origin) pairs. The horizons overlap.
7. **M7 expected-wins error (descriptive).** For the same origins and horizons:
   - expected wins = Σ over the team's actual scheduled games of P(head-to-head win) + P(median win), from the
     week-`k` distributions, with the median probability computed per horizon week as in M4;
   - error = realized wins − expected wins (median wins per `median_threshold`).
   - Reported: MAE and bias.
8. **M8 between-team spread ratio (descriptive).** SD across teams of each team's mean μ over the holdout, divided by
   the same SD of realized means.
9. **M9 playoff/title (descriptive only).** No completed 2026 season exists, so calibration is
   `INSUFFICIENT_BY_CONSTRUCTION` until January 2027 (RPA-LGI-006).

**Bootstrap.** Paired team-cluster bootstrap: B = 2,000, seed 20261108, 95% percentile intervals. Each resample
draws 12 teams with replacement. A drawn team brings:
- its 4 team-weeks;
- its 4 median outcomes;
- each of its head-to-head games, at weight 0.5.

So the full-sample weighted mean equals the plain mean. The same resample applies to both arms of every paired
difference.

## 5. Gates

The thresholds are labelled PRIORs, fixed now. Challenger `X ∈ {B1, B2, A, S}`. A challenger must beat the incumbent
**and** every OTHER simple baseline: `R(X) = {B1, B2} \ {X}`.

| gate | passes when |
|---|---|
| **TG1 distribution (CRPS)** | ΔCRPS = CRPS(I) − CRPS(X) has CI lower bound > 0, **and** CRPS(X) < min over R(X) of CRPS (point estimate) |
| **TG2 win probability** | Δ binary log loss = LL(I) − LL(X) has CI lower bound > 0, **and** LL(X) < min over R(X) of LL (point), **and** Brier(X) ≤ Brier(I) |
| **TG3 level** | \|bias(X)\| ≤ 20 points, **and** ΔMAE = MAE(I) − MAE(X) has CI lower bound > 0, **and** MAE(X) < min over R(X) of MAE (point) |
| **TG4 spread** | z-RMS(X) ∈ [0.80, 1.25] **and** central-80% coverage ∈ [0.68, 0.92] (about ±2 binomial SE at n = 48) |
| **TG5 ordering (non-inferiority)** | concordance(X) ≥ concordance(I) − 0.02 |

**Verdict per challenger.** `PASSES_ALL_GATES` if and only if TG1–TG5 all pass. Otherwise `DOES_NOT_PASS`, naming
each failed gate.

**Recommendation rule.** Among passing challengers, pick the lowest holdout CRPS. When two are within 1.0 CRPS points,
pick the one with fewer fitted parameters per forecast: A (3) < S (4) < B2 (13) < B1 (24). If none passes, the
incumbent stays, and the results record which gates failed.

**Power, stated in advance.**
- 48 team-weeks in 12 clusters. For a perfectly calibrated forecast, z-RMS has sampling SD of about 0.10 and 80%
  coverage about 0.058.
- Baseline comparisons use point estimates on purpose. A CI requirement against a strong baseline would be
  unpassable at this n. The comparison against the incumbent is CI-based.

**What a result justifies.**
- **No challenger passes:** no owner request; the incumbent stays. The diagnosis (§6) stands on its own evidence.
- **A challenger passes:** an owner **recommendation**, not a promotion. Any live change requires, in order:
  1. a week-9+ confirmation with the frozen method;
  2. owner approval;
  3. a new default-OFF flag through the `playoff_sim` owner.

  This is the sequence fit → backtest → validate → compare → human approval → promote → monitor.

## 6. Diagnosis (reported, never gated)

The committed `diagnose` subcommand re-computes the §0 item 2 decomposition. Per team-week, it reports:
- **L_F:** the deterministic lineup sum of `rosValue/2.7`.
- **P_F:** the presim, plus the best-ball noise lift P_F − L_F.
- **I:** the incumbent, and its ROS multiplier `(1 + 0.2z)`.
- **P_once:** the `ros_counted_once` arm.
- **P_C0, P_CF, P_CR:** presims under the `src/ros_calibration` conversions, fitted on appeared player-weeks of weeks
  `< k`.
- **Oracle availability arms (labelled oracle):** P_F and P_CF with only the players who appeared.
- **Spread parts:** the depth-lift range, and the realized within-team SD vs each arm's σ.

It also reports the unpriced-player share of realized starter points, and the live week-9 forward table under
anonymous team indexes. Contributors are ranked by their measured effect on bias, MAE, calibration slope and spread
ratio.

## 7. Outputs

Under `docs/league-intelligence/evidence/team_points_calibration/`: `evaluation.json` and `diagnosis.json`. Every
file carries:
- `promotes: false`;
- the code SHA and script sha256;
- this preregistration's commit;
- the card fingerprint;
- snapshot sha256 per week;
- cache receipts and seeds.

No manager name, team name or league id appears. Teams appear as anonymous indexes. Raw API bodies stay in the
gitignored cache.

---

*Freeze line. Anything below is a dated addendum written after results were known.*
