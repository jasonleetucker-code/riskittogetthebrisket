# Best-ball sim points model, v3 challenger: preregistration

**Status:** PREREGISTRATION. Frozen at commit time. It is committed **alone**, before the v3 study script exists
and before any v3 number has been computed, on any fit week or any held-out week. Results go in
`docs/league-intelligence/SIM_CALIBRATION_V3_RESULTS_2026-10-27.md`. Nothing above the freeze line changes after
results are known; a later correction is a dated addendum below it.

**Authority:** the same lane as v1 and v2 (`docs/EXECUTION_PLAN.md` §0, "League intelligence ... owner,
2026-10-19 (later)"; `docs/owner/IDP_VALUATION_ACCURACY_DIRECTIVE_2026-10-25.md`), run under the owner's
BUILD_ONLY_MAX_THROUGHPUT mode of 2026-10-27 (build, test, draft PR only).

Research and shadow only. Champion ≠ challenger: `PointsModel()` (the fallback constants production serves) is the
champion. This study promotes nothing, every output carries `promotes: false`, and it never writes
`data/league_intel/` (v1's `assert_safe_output` is reused for every write). It does not modify
`src/league_intel/sim_calibration.py`, `src/ros/playoff_sim.py`, `src/ros/lineup.py` or any served path.

**Base:** `origin/main` at `a53680edc`, which contains v1 (#1963, squash `b4e11f6ce`) and v2 (#1972, squash
`d73738619`).

## 0. Why v3, and what is already public

v1 and v2 (results: `SIM_CALIBRATION_RESULTS_2026-10-26.md`, `SIM_CALIBRATION_V2_RESULTS_2026-10-26.md`) found:

- The served fallback F is badly miscalibrated: team-week totals about **−109** points against realized, 0 of 24
  team-weeks inside its 80% interval, offense means off by 1.5x–1.9x.
- v2's challenger (per-family inverse scale on the preseason snapshot, within-player CV) over-predicts team totals by
  about **+113**, fails SC-G1, SC-G3, SC-G4 and SC-G5, and is not promotable. v2 named three causes:
  1. the **inversion problem**: `calibrate_scale` regresses rosValue on noisy mean points and inverts that fit, which
     over-predicts in the fit window itself (0.81–0.95), most where R² is lowest (IDP);
  2. **IDP snapshot drift** (as-of / preseason rosValue LB ≈ 1.6, DL ≈ 1.28, DB ≈ 1.2–1.3), which a scale fitted on
     the preseason snapshot cannot follow;
  3. **σ omits mean-prediction error** (fit-window residual CV 0.61–0.89 against within-player CV 0.45–0.77).
- Whether the fallback's level bias changes relative standings or odds was **not measured**.

### Information known before this preregistration (disclosed)

- **All of v1's and v2's published numbers**, including every per-family holdout number for 2026 weeks 5–6. The v3
  method is designed from that diagnosis, so **weeks 5–6 cannot be an out-of-sample test of v3**. They are used only
  as a disclosed, non-gating development read (§2).
- **Input-integrity checks.** The 49 cached bodies in this worktree's `data/idp_accuracy/cache/` (copied from a
  sibling worktree's v1 cache) match v2's evidence receipts by sha256, 49 of 49.
- **Inputs-only rosValue drift (no outcome read).** For the players rostered in 2026 week 4, mean as-of rosValue by
  family in the latest snapshot before each week's first kickoff:

  | family | wk1 (09-09) | wk2 (09-17) | wk3 | wk4 | wk5 | wk6 | wk7 (10-22) |
  |---|---|---|---|---|---|---|---|
  | QB | 25.72 | 25.58 | 25.27 | 26.44 | 25.79 | 25.62 | 27.95 |
  | WR | 17.15 | 16.80 | 16.28 | 16.65 | 16.35 | 16.42 | 18.20 |
  | TE | 11.84 | 11.22 | 10.25 | 11.16 | 10.96 | 11.38 | 13.06 |
  | DL | 14.91 | 19.23 | 18.93 | 18.75 | 19.07 | 19.20 | 19.56 |
  | LB | 17.72 | 25.60 | 26.28 | 26.84 | 28.22 | 27.90 | 27.94 |
  | DB | 14.55 | 18.72 | 18.46 | 18.72 | 18.10 | 18.81 | 18.78 |

  The IDP drift is a **step**, not a trend. Its input-level cause: between snapshots `2026-09-16T18-32-01` and
  `2026-09-16T21-49-09`, the `draftSharksRosSf` contributor's IDP ranks changed basis from an overall-list rank
  (best LB rank 47) to a within-position rank (best LB rank 1, scoring 100). A second, smaller step lands in the
  week-7 snapshot for offense (+9% QB, +11% WR, +15% TE on a fixed player set) while `fantasyProsRosSf` coverage
  rises from 374 to 536 players. **rosValue's level per family is not stationary across snapshots.**
- **Week-7 finality.** A fresh nflverse `games.csv` fetched at 2026-10-27T09:08Z shows 2026 week 7 with 14 of 14
  games final and week 8 with 0 of 14. That body carries NFL game scores. No fantasy outcome, no Sleeper week-7
  stat line and no week-7 matchup body has been read.
- **No v3 number of any kind has been computed.**

## 1. Data, population, scoring

v1 §1 by reuse: the v3 script imports v1's and v2's loaders, scorer path (`compute_weekly_points(..., source=
"sleeper")`), appearance rule, exclusion census, production rosValue join (`hydrate_roster_players` +
`compute_team_strength`), card-fingerprint pin `sf1:9e51824690d091f9` (abort on mismatch) and output guard. There is
no second copy. Missing is never zero.

- Only **2026** player-weeks are used (every v3 component needs a point-in-time rosValue, and the snapshot history
  starts 2026-04-28). 2025 is not read.
- The **as-of rosValue** for any 2026 week `t` (fit or evaluated) is the latest snapshot in
  `data/ros/aggregate/history/` strictly before week `t`'s first kickoff (v1's `snapshot_before`), joined through the
  production join onto that week's rosters (the week-`t` Sleeper matchups body, as v1).
- **The pool of week `t`, family `f`** (`P_ft`) is every appeared player of family `f` on any of the 12 rosters in
  week `t` with a positive as-of rosValue. Family is v1's `lineup_family`.
- New bodies for week 7 (stats and matchups) and a new schedule body are fetched through v1's write-once
  `CachedFetcher`. The fresh schedule body is cached under a new path
  (`nflverse/schedules__games__v3_20261027.csv`); v1's 13-of-14 body is left untouched.

## 2. Split (as-of only, rolling origin)

Every evaluated week `h` is predicted by a model fitted **only on 2026 weeks `1..h-1`**, with each fit week paired
with **its own** as-of snapshot. The points of week `h-1` are final before week `h`'s first kickoff, so every input
is available at prediction time. The script refuses if any week `≥ h` reaches week `h`'s fit (a test pins it).

| block | weeks | role |
|---|---|---|
| **primary holdout (gated)** | **2026 week 7** (fit on weeks 1–6) | the only week no study has looked at |
| development (reported, **never gated**) | 2026 weeks 5 and 6 (fit on 1–4 and 1–5) | contaminated by design knowledge (§0) |
| confirmation (deferred) | 2026 week 8, when final | frozen V3 week-8 fit by sha256 in a dated addendum, no method change |

## 3. The challenger V3

A research candidate inside the study script: a research subclass of `PointsModel` that production's
`playoff_sim._bestball_weekly_score` runs unmodified. Its file uses `schemaVersion: "research-sim-points-v3"`, which
`load_points_model` refuses (served fallback), pinned by a test.

All constants inherited: `MIN_SAMPLES_PER_POSITION` 30, `CV_CLAMP` [0.15, 1.20], σ floor 0.5, v1 seeds.

### 3.1 Re-anchored rosValue (fixes snapshot drift)

For a player in week `t`: `r̃ = r / Ā_f(t)`, where `Ā_f(t)` is the mean as-of rosValue over the week's pool `P_ft`.
Inputs only, as-of, and invariant to a family-wide multiplicative step in a snapshot.

### 3.2 Forward mean model (fixes the inversion problem)

Per family, ordinary least squares of **points on `r̃`** (the conditional-mean direction, with intercept) over the
fit player-weeks: `μ = max(0, a_f + b_f · r̃)`.

- Below the floor (fewer than 30 fit player-weeks in the family), or when `b_f ≤ 0`: the family takes the
  level-only predictor `μ = ȳ_f · r̃` (`ȳ_f` = the family's mean fit points per pool player-week). A family with no fit
  player-weeks takes the pooled level-only predictor over all families.
- No other shrinkage, no recency weighting, no per-week parameter.

### 3.3 Predictive spread from out-of-sample prediction error

**Prequential residuals.** For each fit week `t ∈ {2..h-1}`, predict week `t` with §3.1–3.2 fitted on weeks
`1..t-1` only; `e = y − μ`. (Week 1 has no earlier 2026 week and contributes no residual.)

**Total CV `c_f`.** Per family, the value on a 0.005 grid in `CV_CLAMP` that maximizes the mean censored log score
(v1's `censored_log_score`) of the prequential player-weeks under `max(0, N(m, max(0.5, m·c)²))` with
`m = μ / g(c)` (§3.5). Family below 30 prequential player-weeks: the pooled `c` from the same search over all
families.

### 3.4 Correlated roster outcomes

Two shared multiplicative shocks per simulated week, a league-week shock `s_L ~ N(0, τ_L²)` shared by every roster
and a roster-week shock `s_R ~ N(0, τ_R²)` shared by one roster's players. Method of moments on the prequential
residuals, with `m` from §3.5:

- `τ_L² = Σ e_i e_k / Σ m_i m_k` over pairs of players on **different** rosters in the same week;
- `τ_W² = Σ e_i e_k / Σ m_i m_k` over pairs on the **same** roster in the same week; `τ_R² = max(0, τ_W² − τ_L²)`;
- `τ_L² = max(0, τ_L²)`.

The idiosyncratic CV is `c_idio,f = sqrt(max(0.15², c_f² − τ_L² − τ_R²))`. The per-player marginal is then exactly the
censored normal of §3.3 whenever `c_f² − τ² ≥ 0.15²` (the shocks are Gaussian and add), so player-level metrics use
`c_f`.

### 3.5 Censoring-corrected location

The draw is censored at 0, so its mean exceeds its location. V3 sets the location `m = μ / g(c_f)` with
`g(c) = Φ(1/c) + c·φ(1/c)`, the exact mean of `max(0, N(m, (c m)²))` divided by `m`, so the simulated mean equals `μ`
(up to the 0.5 σ floor).

### 3.6 Draw

`X = max(0, N(m(1 + s_L + s_R), σ_idio²))`, `σ_idio = sqrt(max(0, max(0.5, m c_f)² − m²(τ_L² + τ_R²)))`, falling
back to `max(0.5, m·c_idio,f)` when that is not positive. The team-week sim calls production's
`_bestball_weekly_score` once per draw with a per-draw model instance carrying that draw's `s_L + s_R`. `s_L` for
draw `d` of week `w` comes from one stream per week shared by every roster; `s_R` from a per-(week, roster) stream
separate from the player-draw stream, so V3 and its no-shock ablation share player uniforms.

### 3.7 Considered and not adopted

Recency weighting; per-week refits of `c` or `τ`; NFL-team stacking correlation (reported, §8); a position-specific
zero-inflation component; 2025 data; any K special-casing.

## 4. Comparators and ablations

| name | model | role |
|---|---|---|
| **F** | `PointsModel()` | champion, gated against |
| **V2** | v2's frozen challenger, sha256 `b7826d44c73a1a974b10c5562822648879e97cec737f1b6792d016ba577ceceb` (LF-normalized) | reported |
| **V3** | §3 | gated |
| V3-noAnchor | §3 without §3.1 (`r̃ = r`) | ablation, reported only |
| V3-noShock | §3 with `τ_L = τ_R = 0`, `c_idio = c_f` | ablation, reported only (player level identical to V3 by construction) |

Player-level rows, uniforms, team-week seeds (v1's `team_week_seed`), 2,000 draws, the oracle-availability pool and
production's `_bestball_weekly_score` + `solve_optimal_assignment` are v1/v2's, shared by every model.

## 5. Metrics

v2 §5 unchanged at player level (censored log score, censored CRPS, randomized PIT, PIT coverage 80/95, KS D, 95%
player-cluster bootstrap B = 2,000, seed 20261026) and at team-week level (sample CRPS, PIT, type-7 coverage, bias).
Added, all computed from the same draws:

- **Team-week bias CI**: 95% percentile bootstrap (B = 2,000, seed 20261026) of mean(simulated mean − realized),
  resampling team-weeks.
- **All-play win probability**: for every pair of rosters in a week, `P(A > B)` = share of draw indices with
  `X_A,d > X_B,d` (ties ½); outcome from awarded points. Brier and log loss (clipped 1e-6). Head-to-head matchups
  (Sleeper `matchup_id`) reported separately.
- **Ranking**: per-week Spearman ρ between simulated team means and realized totals.
- **Per-family mean ratio CI**: 95% player-cluster bootstrap of `Σy / Σμ`.

## 6. Gates on the primary holdout (week 7)

"Gated family" = at least 50 week-7 player-weeks (v1's `GATE_MIN_N`). From the weeks 5–6 sizes the expectation is
RB, WR, DL, LB and DB, with QB, TE and K reported only; the realized set is whatever meets the floor.

| gate | passes when |
|---|---|
| **SC-G1** | v2's rule exactly: every gated family's V3 PIT coverage 80 in [0.75, 0.85] and PIT coverage 95 in [0.90, 1.00] |
| **SC-G2** | v2's rule exactly: pooled ΔLS (V3 − F) > 0 with CI lower > 0, no gated family CI upper < 0 |
| **SC-G3** | v2's rule exactly: pooled ΔCRPS (F − V3) > 0 with CI lower > 0, no gated family CI upper < 0 |
| **SC-G4** | v2's rule exactly: every gated family's KS D ≤ 0.08, pooled D below F's |
| **SC-G5** | v2's rule exactly: team-week coverage 80 in [0.65, 0.95], coverage 95 ≥ 0.85, mean CRPS ≤ F's |
| **V3-G6 team-week bias** | the 95% bias CI lies inside **[−30, +30]** points (an equivalence test: a wide CI fails) |
| **V3-G7 team-week distribution** | team-week PIT KS D ≤ the 95% critical value at that n (v2's `ks_critical_95`) |
| **V3-G8 win probability** | all-play Brier(V3) ≤ Brier(F) **and** < 0.25 |
| **V3-G9 family means** | in every gated family, the 95% CI of `Σy/Σμ` lies inside **[0.80, 1.25]** |

No gate is loosened: SC-G1..G5 are v2's, verbatim; G6–G9 are additional. A gate that fails because its interval is
too wide is reported as `FAIL (underpowered)` when the point estimate is inside the band, and it is still a FAIL.

**Verdict.** `V3_BEATS_FALLBACK` iff all nine gates pass on week 7; otherwise `V3_DOES_NOT_BEAT_FALLBACK`, naming every
failing gate. Weeks 5–6 get the same table, labelled development, and cannot change the verdict.

**Operating characteristics, disclosed before looking.** At week-7 family sizes (about 45–90) a perfectly calibrated
model passes SC-G4's `D ≤ 0.08` well under v2's 2% (smaller n), and SC-G1 less often than v2's 27%. With n = 12 team
weeks, V3-G6 needs a team-week residual SD of roughly 50 points or less to pass even at zero bias. **A FAIL is
expected from sample size alone and is still a FAIL.** v2's size-aware reading (V2-D2) is repeated, never gated.

## 7. What a result justifies

- **Any gate fails:** no owner request. V3 stays a research artifact; the results say which components helped.
- **All pass:** an owner request (not a promotion) for a methodology change to the points-model owner, only after the
  week-8 confirmation keeps pooled ΔLS and ΔCRPS against F above 0 and the week-8 bias point estimate inside
  [−30, +30]. Writing `data/league_intel/` stays owner-reserved.

## 8. Descriptive analyses (declared now, never gated)

- **V3-D1** per family per model: bias, realized/predicted, PIT coverage, KS D, zero share vs predicted zero mass, and
  v2's size-aware reading for V3.
- **V3-D2** fitted parameters per evaluated week: `a_f, b_f`, fallback used, `c_f`, `τ_L`, `τ_R`, `c_idio,f`, and the
  prequential sample sizes.
- **V3-D3** anchors `Ā_f(t)` per week (inputs only) and V3-noAnchor vs V3 per family.
- **V3-D4** NFL-team correlation: the method-of-moments `τ` restricted to same-roster pairs on the same NFL team, from
  the prequential residuals of the week-7 fit.
- **V3-D5** weeks 5–6 development table, every gate and metric.

### C2 — downstream impact (declared now, never gated)

- **C2-a relative within-week outcomes.** For F, F\*, V2, V3 on weeks 5–7: Spearman ρ, all-play Brier, the mean and
  max |ΔP(A > B)| against F, and Kendall τ of the simulated team-mean order against F's. **F\*** is F with every mean
  multiplied by one constant `B = Σ realized / Σ F simulated mean` over the 36 evaluated team-weeks (an **oracle**
  rescale using outcomes, labelled as such, whose only purpose is to isolate the absolute level); F\* is run on week 7.
- **C2-b playoff qualification and championship.** Today's state through the D11 harness
  (`scripts/evaluate_playoff_ros_once.py::current_state`, i.e. production `simulate_playoff_odds` on the live public
  snapshot and `data/ros/aggregate/latest.json`), once per points model F, F\*, V2, V3-marginal (V3 fitted on weeks
  1–7, no shocks, since the production presim draws players independently). Per team playoff and title odds, max
  |Δ| against F, Kendall τ of team order. Both arms are reported; production serves the incumbent arm
  (`playoff_ros_counted_once` defaults OFF). If the public snapshot cannot be built, this piece is reported BLOCKED.
- **C2-c trade marginal-utility ordering.** On each week-7 roster, the 12 highest-rosValue priced players'
  drop-one Best-Ball Lineup Impact through production `best_ball_utility.evaluate_trade_utility` (400 draws, fixed
  seed), under (i) common means (V3's week-7 μ) with F's CVs vs V3's `c_f` — the production configuration, where the
  means come from the ROS ensemble and only the points model's variance is used — and (ii) each model's own means and
  spread. Within-roster Kendall τ against F, top-3 overlap.

## 9. Outputs

Under `docs/league-intelligence/evidence/sim_calibration_v3/`: `challenger_v3_week7.json` (and the weeks-5/6 fits),
`evaluation_v3.json`, `downstream_c2.json`. All carry `promotes: false`, code SHA, script sha256 (LF-normalized), this
preregistration's commit, the card fingerprint, input hashes and seeds. No manager, team name or roster-identified
number; team-level results appear as aggregates or anonymous indexes.

---

*Freeze line. Anything below is a dated addendum written after results were known.*
