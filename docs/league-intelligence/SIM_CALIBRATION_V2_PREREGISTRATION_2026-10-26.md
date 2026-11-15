# Best-ball sim points model, v2 challenger (per-family scale + within-player CV): preregistration

**Status:** PREREGISTRATION. Frozen at commit time. It is committed **alone**, before the v2 study script exists and
before any v2 number has been computed, on the fit window or the holdout. Results and the verdict go in
`docs/league-intelligence/SIM_CALIBRATION_V2_RESULTS_2026-10-26.md`. Nothing above the freeze line changes after the
results are known. A later correction is a dated addendum below the freeze line.

**Authority:** the same as v1 (`docs/league-intelligence/SIM_CALIBRATION_PREREGISTRATION_2026-10-26.md`):

- `docs/EXECUTION_PLAN.md` §0, "League intelligence ... owner, 2026-10-19 (later)";
- `docs/owner/IDP_VALUATION_ACCURACY_DIRECTIVE_2026-10-25.md`.

Research and shadow only. Champion ≠ challenger: the fallback constants that production serves today are the
champion. This study promotes nothing. Every output carries `promotes: false`. It never writes `data/league_intel/`.

**Base:** branch `claude/sim-calibration-prereg-study` (PR #1963), approved and **not merged** when this was written.
v1 is the evidence in that PR, at commit `86b3fcf71`.

## 0. Why v2, and what v1 already made public

v1 (results: `docs/league-intelligence/SIM_CALIBRATION_RESULTS_2026-10-26.md`) found two things:

- **The fallback is badly miscalibrated.** Holdout realized/predicted runs from 1.13 (LB) to 1.86 (QB), and 4.0 for
  K. Its CVs are too narrow (QB 0.32 against a within-player 0.66). Simulated team-week totals sit about 109 points
  below the realized totals.
- **The `build_calibration` candidate (v1, "C") also fails, for two named methodological reasons:**
  1. One global `rosValuePerPoint` (1.4764). In the holdout it over-predicts LB by 62%.
  2. A CV pooled over every player-week at a position (0.69 to 0.96). That includes between-player spread, which the
     sim does not need: it already gives each player his own mean. The within-player CV (v1 D2: 0.57 to 0.77) is the
     statistic the sim needs. The pooled CV inflates simulated best-ball totals by about 116 points.

v1 also flagged a defect in its own coverage metric. When the lower bound of a "central" interval censors at 0, the
interval also holds the point mass at 0, so its true content is not its nominal level. v1 said a future
preregistration should gate on PIT-interval coverage.

**v2 tests exactly those two fixes, and gates on PIT coverage.** Nothing else changes.

### Information known before this preregistration (disclosed, not hidden)

- **v1's holdout results are public**, and this unit read all of them: the results doc and v1's `evaluation.json`,
  which includes every per-family holdout number for C and F.
- **v1's fit-window diagnostics.**
  - D2, the within-player CVs: QB .6618, RB .6654, WR .7169, TE .7662, K .4537, DL .7661, LB .5714, DB .5893. Under
    the method in §3 these **are** the challenger's CVs, so that half of the challenger is known in advance.
  - D6, fit-window realized/predicted under v1's pooled `k`: QB .94, RB .73, WR .86, TE .98, K 2.35, DL .88, LB 1.00,
    DB .99. This hints at the per-family scales. No per-family scale has been computed.
- **The gates' operating characteristics**, computed from the known holdout family sizes only, no outcomes (§6.1).
- **Format checks.** The cached league body's card fingerprint (`sf1:9e51824690d091f9`) and its `roster_positions`
  (QB, 2 RB, 3 WR, 2 TE, 2 FLEX, SUPER_FLEX, K, 3 DL, 3 LB, 3 DB). Also the sha256 of the cached bodies and of the v1
  candidate file.
- **No v2 number of any kind has been computed:** no per-family scale, no fit-window v2 prediction, no holdout
  prediction.

### How v2 avoids tuning to v1's public holdout

1. **The method comes from v1's diagnosis only.** Each component is a statistic or routine that existed before v1's
   holdout was examined:
   - the scale is the owner's `sim_calibration.calibrate_scale`, run on v1's scale-call inputs **partitioned by
     family**;
   - the CV is v1's preregistered D2 statistic, computed exactly as v1 defined it.
2. **No free parameters.** Every constant is inherited, and none was chosen by looking at v1's holdout:
   - `MIN_SAMPLES_PER_POSITION` 30 and `CV_CLAMP` [0.15, 1.20] from the owner module;
   - D2's at-least-4-weeks rule and `pstdev`;
   - v1's preseason snapshot rule;
   - v1's seeds, B, draw count and gates.
3. **Exactly one challenger is evaluated on the holdout.** The alternatives in §3.4 were considered and **not**
   adopted. Where they appear at all, they appear on the fit window only (§8), never on the holdout.
4. **The holdout is the same as v1's, and the population is identical.** Rows, U draws and team-week seeds are
   shared, so F and v1 must reproduce v1's published numbers exactly (§8, V2-D6). That proves the data path did not
   move.
5. **The order is provable.** This file is committed and pushed alone. The script, the tests and the run come after
   it. The evidence records this commit's SHA, and the script checks that this commit is an ancestor of the code it
   runs.

## 1. Data, population and scoring

**Identical to v1 §1**, by reuse: the v2 script imports v1's loaders, scorer path, census and join, and keeps no
second copy. In detail:

- the same cache (`data/idp_accuracy/cache/`, `sha256(url)[:24]`), and the same 49 bodies v1's evidence hashed.
  This worktree's copy of v1's cache was checked against those 49 sha256s before writing this, and all 49 match.
  That is an input-integrity check only; no number was computed from the bodies;
- the card fingerprint must equal `sf1:9e51824690d091f9`, or the run aborts;
- host-native scoring through `compute_weekly_points(..., source="sleeper")`;
- the same appearance rule and the same exclusion census. **Missing is never zero.**
- the same point-in-time rosValue rule and production join (`hydrate_roster_players` + `compute_team_strength`):
  - preseason snapshot `2026-09-09T21-17-37.092580+00-00.json` for the fit;
  - for each holdout week, the latest snapshot strictly before its first kickoff.

## 2. Split

| | weeks |
|---|---|
| fit (variance) | 2025 weeks 1–17 + 2026 weeks 1–4, identical to v1 |
| fit (scale) | 2026 weeks 1–4 with the preseason rosValue, identical to v1 |
| **holdout (gated)** | **2026 weeks 5–6**, identical to v1 |
| confirmation | 2026 week 7, only when final (below) |

**Week 7.** When this was written (2026-10-26, about 17:40Z), week 7 was **not final**: DAL at PHI kicks off
2026-10-26 20:15 ET (2026-10-27T00:15Z). The v2 run is expected to happen before that kickoff.

- The rule is v1's: a week joins only when every one of its games has a `result` in a schedule body.
- Week 7 is **never pooled into the gated weeks**. If it is final at run time, it is evaluated as the confirmation
  block on the frozen challenger.
- Otherwise it is deferred to a dated addendum, run on the frozen challenger by sha256 with no refit, exactly as v1
  §2 deferred it.
- The results state which applied, and why.

**Split integrity.** The v2 fit functions receive only fit weeks. The script refuses any evaluated week that reaches
them, and a test pins that.

## 3. The challenger (V2)

A **research candidate inside the study script.** It does not modify `src/league_intel/sim_calibration.py`, and the
production loader cannot load it (§9).

### 3.1 Per-family scale

The family of a player is v1's `lineup_family(directory meta)`: QB, RB, WR, TE, K, DL, LB or DB.

**Inputs.** Exactly v1's scale-call inputs: 2026 weeks 1–4 appeared player-weeks with a positive preseason
rosValue. For each player, the pair is (preseason rosValue, mean host-native points over his appeared fit weeks),
as `build_calibration` forms it.

**Fit.** For each family `f`, `k_f = sim_calibration.calibrate_scale(pairs of family f)`. That is the owner's
through-origin least squares of rosValue on mean points, unchanged. Its own filter drops pairs with a non-positive
value.

**Floor.** A family uses its own `k_f` only when both of these hold:

- its scale-fit input holds at least `MIN_SAMPLES_PER_POSITION` (30) player-weeks. That is the owner's floor, in the
  owner's unit;
- `calibrate_scale` fitted from at least 2 usable pairs. Below 2 pairs it returns the 2.7 fallback with `n < 2`.

Otherwise the family takes the **pooled** scale: `calibrate_scale` over all pairs. That is v1's scale call, which
must reproduce `1.4764`.

**Disclosed:** K has 74 fit-window player-weeks (v1 D6), so this floor's unit decides that K gets its own scale. K is
ungated at player level (n = 36), but it fills one team-week slot.

### 3.2 Within-player CV per family

`cv_f` is v1's `within_player_cv` (D2), over all appeared fit player-weeks (2025 weeks 1–17 and 2026 weeks 1–4):

- per (player, season), with at least 4 appeared weeks and a positive mean, the CV is `pstdev(points) / mean(points)`;
- per family, `cv_f` is the mean of those CVs weighted by weeks.

**Floor:** a family whose contributing player-weeks are fewer than 30 keeps `FALLBACK_CV_BY_POSITION[f]`, or
`FALLBACK_DEFAULT_CV` for K. The value is clamped to `CV_CLAMP`.

### 3.3 Prediction (the sim's draw, per family)

The sim calls `model.draw(rosValue, raw_position, rng)` with the RAW directory position (CB, DE, FB, ...). V2 maps a
raw position to a family as follows:

1. `lineup_position(raw)` when that is a sim family (CB → DB; DE, DT, NT → DL; S, SS, FS → DB; PK → K);
2. otherwise the modal `lineup_family` among the fit player-weeks with that raw position. Ties go to the first family
   in the order QB, RB, WR, TE, K, DL, LB, DB. This is expected to send FB to RB;
3. otherwise the pooled scale and the pooled within-player CV, computed over all families by the same rules.

Then, with no other change to production's draw:

- `μ = max(0, r / k_f)`;
- `σ = max(0.5, μ · cv_f)`;
- `X = max(0, N(μ, σ²))`.

This is `PointsModel.draw_from_mean`, reused. V2 is a research subclass of `PointsModel`, so production's
`playoff_sim._bestball_weekly_score` runs it unmodified. Its position-free `mean_points(r)` raises, so no path can
silently use a single scale.

### 3.4 Considered and deliberately NOT adopted in v2

Each item below would be its own candidate with its own preregistration. Each also carries a named a priori risk
for v2.

- **Regression direction.** `calibrate_scale` regresses rosValue on points, then inverts the fit to predict points.
  When the fit is noisy that over-predicts, and v1's fit-window D6 under the pooled `k` is below 1 in six of eight
  families. A forward fit (points on rosValue) or a ratio estimator would change the method beyond the two diagnosed
  fixes. **Risk:** V2 over-predicts means, and that inflates team totals. Reported on the fit window only (V2-D3).
- **Snapshot drift.** v1's results say the LB miss coincides with LB rosValues rising from the preseason snapshot to
  the holdout snapshots, while v1's pooled `k` fitted LB at 1.00 in the fit window. A per-family `k` fitted on the
  preseason snapshot **cannot** correct a drift that happens after it. Fitting on each fit week's as-of snapshot is
  not adopted. **Risk:** V2 still over-predicts LB in the holdout and fails SC-G3 there. Measured on inputs only
  (V2-D5).
- **Mean-prediction error is not in σ.** The within-player CV is week-to-week spread around a player's own mean. The
  holdout predictive also carries the error in `r / k_f` (v1's scale R² is 0.33). **Risk:** V2 under-covers at player
  level. The fit-window residual CV is reported (V2-D7).
- **Small-sample `pstdev`.** It divides by n, so a 4-week season understates σ by about 13%. v1's D2 definition is
  kept as written.
- **No inflation factors, shrinkage, per-week refits or K special-casing.**

## 4. Comparators

| name | model | source |
|---|---|---|
| **F** | `PointsModel()`, the fallback constants (the champion, served today) | the owner module |
| **V1** | v1's frozen candidate, loaded through `load_points_model(path=…)` | `docs/league-intelligence/evidence/sim_calibration/candidate_sim_points_model.json`, which **must** hash to `cee877c2901a9f01d24222bc872e5a96c4acce795a5d239db6a696814c92fbb3`, or the run refuses |
| **V2** | §3 | fitted by the v2 script |

V1 is not refitted. Player-level and team-week predictions for every model use v1 §4 unchanged:

- the same evaluated rows (priced, appeared players);
- the same row order;
- one uniform `U` per row from seed 20261026, shared by every model;
- one team-week seed per (week, roster), shared by every model (common random numbers);
- 2,000 draws per team-week;
- the oracle-availability pool;
- production's `_bestball_weekly_score` and `solve_optimal_assignment`.

## 5. Metrics

**Identical to v1 §5**, computed with v1's functions: censored log score, censored CRPS, PIT, KS D with the
Kolmogorov p-value, the 10-bin histogram, a 95% player-cluster bootstrap (B = 2,000, seed 20261026), and team-week
sample CRPS, PIT, type-7 coverage and bias.

**PIT coverage (new for the gate, defined here before looking).** A player-week's randomized PIT is v1's:

- `Φ((y* − μ)/σ)` for `y* > 0`;
- `U · Φ(−μ/σ)` for `y* = 0`.

Then:

- **PIT coverage 80** is the share of the group's player-weeks with `0.10 ≤ PIT ≤ 0.90`;
- **PIT coverage 95** is the share with `0.025 ≤ PIT ≤ 0.975`.

Under a calibrated model each equals its nominal level exactly, whatever the censoring. This is the same quantity v1
reported, non-gating, as `postHoc.pitCoverage80/95`.

**Paired differences:**

- **gated:** `ΔLS = LS_V2 − LS_F` and `ΔCRPS = CRPS_F − CRPS_V2`, so a positive value favours V2;
- **reported, non-gating:** the same against V1 (`LS_V2 − LS_V1`, `CRPS_V1 − CRPS_V2`), and V1 against F. V1 against
  F must reproduce v1's published C−F intervals.

## 6. Gates: "V2 beats the fallback"

**v1's SC-G1..G5, reused exactly, with V2 in C's place.** The one change is the one v1 asked for: **SC-G1 is applied
to PIT coverage** instead of the censored central-interval coverage. The bands are unchanged. "Gated family" means
at least 50 holdout player-weeks, as in v1. The population is unchanged, so the gated set is expected to be QB, RB,
WR, TE, DL, LB and DB, with K reported only.

| gate | passes when (holdout 2026 weeks 5–6) |
|---|---|
| **SC-G1 coverage (PIT)** | In every gated family, V2's PIT coverage 80 is in [0.75, 0.85] **and** its PIT coverage 95 is in [0.90, 1.00]. |
| **SC-G2 log score** | Pooled mean ΔLS (V2 − F) > 0 with the 95% CI lower bound > 0, **and** no gated family has a ΔLS CI upper bound < 0. |
| **SC-G3 CRPS** | Pooled mean ΔCRPS (F − V2) > 0 with the 95% CI lower bound > 0, **and** no gated family has a ΔCRPS CI upper bound < 0. |
| **SC-G4 PIT** | In every gated family, V2's KS D ≤ 0.08, **and** the pooled D for V2 is below the pooled D for F. |
| **SC-G5 team-week** | Across the 24 team-weeks, V2's 80% coverage is in [0.65, 0.95], its 95% coverage is ≥ 0.85, **and** its mean team-week CRPS is ≤ F's. |

SC-G5 keeps v1's type-7 draw-quantile coverage. Team totals lie far from 0 (v1's realized range is 205.7 to 461.2),
so censoring cannot reach them.

**Verdict.** `CHALLENGER_BEATS_FALLBACK` if and only if all five gates pass. Otherwise the verdict is
`CHALLENGER_DOES_NOT_BEAT_FALLBACK`, and every failing gate is named. The literal v1 SC-G1, on central-interval
coverage, is reported beside it, non-gating, for comparability.

### 6.1 Operating characteristics of these gates (computed before looking, no outcomes)

Under a **perfectly calibrated** model, PIT is iid Uniform(0, 1). At the known gated family sizes (QB 64, RB 122,
WR 181, TE 90, DL 133, LB 161, DB 170), 20,000 Monte Carlo replications (seed 20261026) give:

| gate half | P(pass \| calibrated) | weakest family |
|---|---|---|
| SC-G1, every gated family | **0.27** | QB 0.70 |
| SC-G4, D ≤ 0.08 in every gated family | **0.019** | QB 0.22, TE 0.42 |
| SC-G1 and SC-G4 together | **0.007** | |
| SC-G5 coverage halves (n = 24) | 0.91 | |

These are **lower bounds on difficulty**. Each player appears in up to two holdout weeks, and within-player
dependence widens the sampling distributions further.

So under these gates even a perfect challenger earns an owner request well under 1% of the time. **This is disclosed
before looking, not after.** It does not change the gates, which this study reuses exactly. A FAIL is still a FAIL.

To help read the result, v2 declares a **size-aware descriptive reading** (V2-D2). It never gates, and it is never a
basis for a request.

## 7. What a result justifies (promotion is owner-only)

**Any gate fails.** No owner request. Production keeps serving what it serves today. V2 stays a research artifact in
`docs/`. The results report, by family, what V2 gets wrong, against both F and V1.

**All five pass.** That would justify an **owner request, not a promotion**, and only once all of these hold:

- the week-7 confirmation, when final, keeps the pooled ΔLS and ΔCRPS point estimates against F above 0;
- the request names the exact challenger file by sha256;
- the request asks for a **methodology change** to the points-model owner, `src/league_intel/sim_calibration.py`.
  `PointsModel` and `load_points_model` cannot represent a per-family scale, so V2 cannot be served by writing a
  file, and nothing here proposes one.

Writing anything to `data/league_intel/` stays owner-reserved, and this study never does.

## 8. Descriptive analyses (declared now, never gated)

- **V2-D1. Per family, for V2, V1 and F:**
  - mean bias and realized/predicted;
  - PIT coverage 80 and 95, and censored-interval coverage;
  - KS D;
  - observed zero share against predicted zero mass.
- **V2-D2. Size-aware reading, per gated family, for V2:**
  - the KS p-value;
  - whether D exceeds the asymptotic 95% critical value at that n;
  - whether each PIT coverage lies inside the central 95% binomial range for that n.
- **V2-D3. Scale estimators, fit window only.** Per family:
  - the owner's inverse fit `k_f` (V2's), the forward through-origin fit, and the ratio estimator `Σr / Σȳ`;
  - for each, the fit-window realized/predicted.

  None of the alternatives is evaluated on the holdout.
- **V2-D4. Team-week without the availability filter** (v1 D4), for all three models.
- **V2-D5. Snapshot drift, inputs only.** Per family, for the evaluated holdout players: the mean as-of rosValue in
  each holdout snapshot against the same players' mean preseason rosValue, from the same production join. No
  outcome is used.
- **V2-D6. Reproduction check.** The v2 run's F and V1 numbers must equal v1's `evaluation.json` exactly, field by
  field, at its rounding:
  - player level, pooled and per family, including the V1 − F bootstrap intervals;
  - team-week metrics for C and F;
  - the census;
  - the pooled scale `1.4764`.

  A mismatch is reported, not repaired, and the results must explain it before the verdict is read.
- **V2-D7. Fit-window residual CV.** Per family, over the 2026 weeks 1–4 priced player-weeks:
  `sqrt(mean((y − r/k_f)²)) / mean(r/k_f)`, beside `cv_f`.

## 9. Outputs

Under `docs/league-intelligence/evidence/sim_calibration_v2/`:

- `challenger_v2_points_model.json`, the V2 parameters. Its `schemaVersion` is a string,
  `"research-sim-points-v2"`, so `load_points_model` treats it as a schema mismatch and serves the fallback if the
  file is ever copied into place. A test pins that.
- `evaluation_v2.json`, holding the gates, metrics, census, descriptive analyses and the reproduction check.

Both carry:

- `promotes: false`;
- the code SHA and the script's sha256;
- this preregistration's commit SHA, and whether it is an ancestor of the code SHA;
- the card fingerprint;
- the sha256 of every cached body, every rosValue snapshot and the V1 candidate file;
- the seeds.

All writes go through v1's `assert_safe_output`. It refuses `data/league_intel/` and the served file name anywhere.
The evidence holds no manager, team name or roster-identified number: team-week results appear as aggregates and
anonymous PIT values only.

---

*Freeze line. Anything below is a dated addendum written after results were known.*
