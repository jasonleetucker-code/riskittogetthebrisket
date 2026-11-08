# Team-level points calibration for the best-ball playoff simulator: results

**Status:** `RESEARCH_EVIDENCE_NOT_FOR_PROMOTION`. Nothing is served or wired, and every output carries
`promotes: false`. No change was made to `src/ros/playoff_sim.py`, any flag, `data/league_intel/`,
`config/league_intel/` or the points model.

| item | value |
|---|---|
| authority | owner master directive 2026-11-08 §6 Priority 1; MATH_AUDIT_2026-11-08 finding F2; RPA-LGI-008 |
| preregistration | `TEAM_POINTS_CALIBRATION_PREREGISTRATION_2026-11-08.md`, commit `b7aa4ac21`. That commit touches only the preregistration and was pushed before the script or library existed in the branch. A dated **post-freeze addendum** below its freeze line records the review correction (§5). |
| code | `src/ros_calibration/team_points.py` + `scripts/team_points_calibration_eval.py`. First run on `0395e6f21`; redaction fix `eab492979`; review fixes `2724b7f3d`. |
| evidence run | code SHA `2724b7f3d`, clean tree, preregistration an ancestor (`code` block in each file) |
| inputs | Sleeper public API: league, rosters, `players/nfl`, matchups weeks 1–8, stats weeks 1–8 (stats used in the diagnosis only). Also the nflverse schedule. 21 GETs on 2026-11-08, cached in gitignored `data/team_points_calibration/cache/`; every evidence run is `--offline`. Per-week snapshot sha256 values are in `receipts`. |
| card | `sf1:9e51824690d091f9` (pinned, matched) |
| evidence | `evidence/team_points_calibration/evaluation.json` and `diagnosis.json` |

## Headline

1. **No challenger passes all preregistered gates, so the incumbent stays.** Under the preregistered rule there is no
   recommendation (§3). The verdict is the same before and after the review correction to the incumbent's inputs
   (§5).
2. **The served team distribution is overconfident, and much worse than every simple baseline on CRPS and MAE.**
   Holdout weeks 5–8, 48 team-weeks.
   - **CRPS and MAE (decisively worse):** CRPS 69.0 vs 29.0–32.0; MAE 81.8 vs 42.0–45.4. CRPS is 1.8–3.2 times B2's in
     *every* holdout week (§2).
   - **Log loss and Brier (overconfident):**
     - It puts ≤ 1% or ≥ 99% on 43 of 72 binary outcomes and gets 4 of those wrong. Those few near-certain misses
       dominate its log loss: the top three outcomes carry 35% of the total.
     - Binary log loss is 0.675 against 0.40–0.43 for the challengers.
     - Brier is 0.169, which is **better than chance** (0.25) but worse than every challenger (0.130–0.139).
   - Every challenger beats the incumbent on CRPS, log loss and MAE with team-cluster CIs that exclude zero, though
     those CIs are too narrow (§2).
   - What fails is the second half of each gate (beating the OTHER simple baseline), plus bias, spread and ordering
     limits.
3. **The incumbent's team ORDER is fine; its scale and spread are not.**
   - All-play concordance 0.814 is the best of all arms.
   - Calibration slope is 0.49.
   - Between-team spread of predicted means is 1.83× realized on the holdout.
   - The live week-9 forecast is about 2.2× (F2 measured ≈ 2.3×).
4. **Diagnosis (computed per metric; §1):**
   - The **ROS multiplier on the presim** (the D11 double count, flag OFF) ranks first on the **spread** metrics
     (spread ratio, slope).
   - The **through-origin `rosValue / 2.7` conversion** ranks first on the **level** metrics (|bias|, MAE). The ROS
     multiplier is second on MAE.

## 1. Diagnosis: why the served fallback mis-scales teams

Every arm uses the same point-in-time inputs:
- the snapshot strictly before the week's first kickoff;
- that week's roster;
- the production join with no injury flags (§5);
- the production presim and its seed.

Bias = realized − predicted. z-RMS² = zMean² + zSd², so zSd is the spread part alone, with the bias removed.

**Holdout weeks 5–8 (48 team-weeks):**

| arm | what it is | bias | MAE | slope | zSd | spread ratio | mean σ |
|---|---|---|---|---|---|---|---|
| L_F | deterministic lineup Σ `rosValue/2.7` (no noise) | +95.4 | 95.4 | 1.03 | — | 0.89 | — |
| P_F | production presim, fallback model | +69.0 | 69.5 | 0.90 | 2.56 | 1.01 | 24.8 |
| **I** | **served: P_F × (1 + 0.2 z), σ × (1.10 + 0.15 r)** | **+55.9** | **81.8** | **0.49** | **3.61** | **1.83** | 28.0 |
| I_todayInjury | I with today's injury flags (first run; look-ahead) | +56.0 | 84.6 | 0.47 | 3.62 | 1.85 | |
| P_once | D11 corrected arm (no multiplier, σ × 1.10) | +69.0 | 69.5 | 0.90 | 2.33 | 1.01 | |
| P_C0 | presim, one affine scale fitted on earlier weeks (`a ≈ 6.0 + 0.25·r`) | −13.0 | 41.7 | 1.31 | 2.14 | 0.69 | |
| P_CF | presim, per-family affine | −12.0 | 41.3 | 1.27 | 2.13 | 0.72 | |
| P_CR | presim, per-family rank curve | −6.0 | 39.9 | 1.29 | 2.07 | 0.73 | |
| P_CF_oracle | P_CF with only players who appeared (**oracle, not knowable**) | +24.5 | 36.8 | 1.22 | 1.68 | 0.79 | |

Weeks 2–8 (84 team-weeks) give the same picture: I has slope 0.43 and spread ratio 2.05; P_F has 0.77 and 1.15; P_CF
has 1.02 and 0.83.

**Contributor effects, computed** (`diagnosis.json → contributors.ranked`, `src/ros_calibration/team_points.py::rank_contributors`).

Each contributor is an arm pair (with it / without it). Its effect on each error metric is error(with) − error(without).
A positive effect means the contributor ADDS that error. **Each effect is measured alone against its own comparison
arm. There is no interaction or ordering check, so the effects do not add up and their signs depend on the other
errors present.** Rankings are per metric.

| contributor (with → without) | Δ\|bias\| | ΔMAE | Δ\|spread ratio − 1\| | Δ\|slope − 1\| |
|---|---|---|---|---|
| ROS multiplier on the presim (I → P_F) | −13.0 | **+12.3 (2nd)** | **+0.82 (1st)** | **+0.41 (1st)** |
| through-origin `rosValue/2.7` (P_F → P_C0) | **+55.9 (1st)** | **+27.8 (1st)** | −0.30 | −0.20 |
| one scale for every position (P_C0 → P_CF) | +1.0 | +0.5 | +0.03 | +0.04 |
| one scale for every position (P_C0 → P_CR) | +7.0 | +1.9 | +0.05 | +0.02 |
| availability not modelled, CF means (P_CF → oracle) | −12.5 | +4.4 | +0.07 | +0.05 |
| availability not modelled, fallback means (P_F → oracle) | −35.1 | −34.6 | +0.00 | +0.05 |
| best-ball max over noisy draws (P_F → L_F) | −26.4 | −25.9 | −0.10 | +0.08 |

Reading the table:
- **Spread error.** The ROS multiplier stretches team gaps: spread ratio 1.01 → 1.83, slope 0.90 → 0.49. The
  multiplier runs 0.60–1.35 across teams. The presim and team strength are sums of the same `rosValue` numbers, so
  this stretch is pure re-use of evidence. This is the main source of the 0% / 100% odds.
- **Level error.** The through-origin conversion gives low-`rosValue` players about 0. The fitted intercept is about
  6.0 and the slope about 0.25 vs 0.37. Fixing it removes most of the bias (+69 → −13). It also shows that the
  presim's spread is then too NARROW (ratio 0.69): the two errors partly offset in P_F.
- **Availability.** Not modelling it shifts the predicted level by about 35 points in either mean model:
  - P_F 267.6 → 232.5;
  - P_CF 348.6 → 312.1.

  Whether that shift adds or removes error depends on the other errors present, which is the measured-alone caveat
  at work. Part of it is knowable in advance: NFL byes start week 5 (15 games), and weeks 6–8 each have four teams on
  bye (14 games). Realized league means fall to 317 and 326 in weeks 6–7, from 357–364 in weeks 3–5 (week 8: 346).
  This is consistent with a bye effect, not proven.
- **Best-ball noise lift.** +26.4 points mean (10–52), 9.9% of the presim mean. A real effect, which realized best
  ball also has.
- **Spread.** Presim σ is about 25 against a realized pooled within-team SD of 46.2. After the CF conversion, zSd is
  still 2.13. The depth lift adds only ×1.12–1.14.
- **Unpriced players drawn as 0:** 0.4%–3.7% of realized starter points per week.

**Receipts:**
- Host-native scorer vs Sleeper `players_points`: **4,833 / 4,833** player-weeks within 0.02.
- Canonical solver (`src/ros/lineup.py`) over `players_points` vs Sleeper's team `points`: **95 / 96** within 0.05.
  The one miss (T08, week 8, solver +5.42) starts a player whom today's directory lists as DL/LB-eligible and whom
  Sleeper did not start. That fits a later eligibility change and is an inherited directory caveat.
- **Week-9 forward reconstruction.** For a forward forecast, today's injuries are legitimately known.
  - With today's flags: 117.0–522.7, against F2's served 117.3–524.5.
  - Without injury flags: 110.9–515.3.

## 2. Champion vs challengers (primary holdout: weeks 5–8, rolling origin)

48 team-weeks, 24 head-to-head games, 48 median games, 12 team clusters.

| arm | bias | MAE | slope | z-RMS (zSd) | cov80 | CRPS | concordance | log loss (all / h2h / median) | Brier | spread ratio |
|---|---|---|---|---|---|---|---|---|---|---|
| **I** (served, point-in-time) | +55.9 | 81.8 | 0.49 | 4.54 (3.61) | 0.27 | 69.0 | **0.814** | 0.675 / 0.622 / 0.701 | 0.169 | 1.83 |
| I_todayInjury (first run, reported only) | +56.0 | 84.6 | 0.47 | 4.54 (3.62) | 0.25 | 71.5 | 0.811 | 0.718 / 0.705 / 0.725 | 0.168 | 1.85 |
| B0 (reference) | −16.8 | 61.1 | −0.31 | 1.12 (1.10) | 0.71 | 44.2 | 0.500 | 0.694 / 0.693 / 0.694 | 0.250 | 0 |
| B1 team mean, team sd | −16.8 | **42.0** | 1.09 | 1.41 (1.34) | 0.73 | 30.2 | 0.788 | 0.419 / 0.380 / 0.438 | 0.136 | 0.84 |
| B2 team mean, pooled sd | −16.8 | **42.0** | 1.09 | 0.98 (0.93) | 0.83 | **29.0** | 0.788 | 0.423 / 0.385 / 0.442 | 0.138 | 0.84 |
| A affine rescale of presim | −25.3 | 45.4 | 1.27 | 1.08 (0.96) | 0.69 | 32.0 | 0.811 | 0.429 / 0.417 / 0.435 | 0.139 | 0.71 |
| S presim + trailing mean | −20.2 | 43.4 | 1.04 | 1.01 (0.93) | 0.73 | 29.6 | 0.799 | **0.401** / 0.378 / 0.412 | **0.130** | 0.88 |

**Paired team-cluster bootstrap, I − X** (B = 2,000; 95% percentile):

| X | ΔCRPS | ΔMAE | Δ log loss |
|---|---|---|---|
| A | +37.0 [17.8, 57.1] | +36.4 [16.3, 57.7] | +0.25 [0.05, 0.48] |
| B1 | +38.8 [19.9, 59.0] | +39.8 [19.4, 61.5] | +0.26 [0.06, 0.48] |
| B2 | +40.0 [20.8, 60.4] | +39.8 [19.4, 61.5] | +0.25 [0.05, 0.47] |
| S | +39.4 [19.7, 60.0] | +38.4 [18.0, 59.8] | +0.27 [0.09, 0.49] |

**These intervals are too narrow.**
- A 12-cluster percentile bootstrap under-covers.
- Week-wide shocks are NOT resampled: every resample keeps all four holdout weeks, including the bye-heavy weeks 6–7.

The CRPS conclusion does not rest on them. It holds week by week:

| week | I CRPS | B2 CRPS | ratio |
|---|---|---|---|
| 5 | 85.2 | 32.8 | 2.6× |
| 6 | 60.0 | 33.2 | 1.8× |
| 7 | 65.4 | 29.5 | 2.2× |
| 8 | 65.4 | 20.7 | 3.2× |

Week-level detail: `evaluation.json → holdout.perWeek`. The log-loss gap is less robust. In weeks 7–8, I's log loss
(0.36 / 0.33) is close to the challengers' (0.29–0.37), because its 0/1-like probabilities happened to be right.

**Fitted challengers (week-8 forecast):**
- A: `y = 161.9 + 0.718·P`, s 53.4.
- S: `y = 31.8 + 0.444·P + 0.553·M`, s 50.9.

A's slope runs 0.51 → 0.72 as weeks accumulate. Both fits say the presim's raw scale is wrong: A's slope is well below
1, and its intercept is large.

## 3. Gates (preregistration §5)

| gate | B1 | B2 | A | S |
|---|---|---|---|---|
| TG1 CRPS: beat I (CI) and the other baseline | FAIL (30.2 > B2 29.0) | **PASS** | FAIL (32.0 > 29.0) | FAIL (29.6 > B2 29.0) |
| TG2 log loss: beat I (CI) and baseline; Brier ≤ I | **PASS** | FAIL (0.423 > B1 0.419) | FAIL (0.429 > 0.419) | **PASS** |
| TG3 level: \|bias\| ≤ 20, beat I MAE (CI), beat baseline MAE | FAIL (MAE ties B2) | FAIL (MAE ties B1) | FAIL (bias −25.3; MAE 45.4) | FAIL (bias −20.2; MAE 43.4 > 42.0) |
| TG4 spread: z-RMS in [0.80, 1.25], cov80 in [0.68, 0.92] | FAIL (z-RMS 1.41) | **PASS** | **PASS** | **PASS** |
| TG5 ordering: concordance ≥ I − 0.02 (0.794) | FAIL (0.788) | FAIL (0.788) | **PASS** | **PASS** |
| **verdict** | DOES_NOT_PASS | DOES_NOT_PASS | DOES_NOT_PASS | DOES_NOT_PASS |

The verdicts are identical under the first run's incumbent (`I_todayInjury`).

**Recommendation under the preregistered rule: none. The incumbent stays.**

Reading the failures:
- **S comes closest.** It passes TG2, TG4 and TG5. It misses TG1 by 0.6 CRPS against B2, and TG3 on bias by 0.18
  points and on MAE by 1.5 against the trailing mean.
- **B1 and B2 share one mean by construction**, so neither can strictly beat the other on MAE. TG3 was therefore
  unpassable for both. That is a gate-design flaw, disclosed in §5 and not repaired after the fact.
- The **negative bias of every empirical arm** (−17 to −25) is concentrated in bye-heavy weeks 6–7 (§1).

**Development weeks 3–4 (never gated).** I: MAE 107.2, CRPS 92.2, log loss 0.579. B2: CRPS 27.9. A: CRPS 26.0, bias
+1.3. S has no forecast there (its 24-row floor needs k ≥ 5), so it is left out and named, never filled in.

## 4. Descriptive outputs (never gated)

**Season horizon (origins 5–8, horizon through week 8, 48 team-origin pairs):**

| arm | projected-PF MAE | projected-PF bias | expected-wins MAE |
|---|---|---|---|
| I | **182.0** | +141.3 | 0.72 |
| I_todayInjury | 190.5 | +141.6 | 0.77 |
| B1 | 70.9 | −49.7 | **0.67** |
| B2 | 70.9 | −49.7 | 0.71 |
| A | 87.6 | −69.4 | 0.84 |
| S | 83.2 | −62.5 | 0.72 |

Over horizons of one to four games, the incumbent's good ordering keeps its expected-wins error close to the others.
Its projected-PF error is 2.1–2.6 times theirs.

**Live week-9 forward forecasts** (anonymous index; point-in-time join; realized weeks 1–8 mean in brackets):

| team | I | A | S | B2 |
|---|---|---|---|---|
| T09 (436) | 515 / 35 | 444 / 53 | 449 / 49 | 436 / 49 |
| T01 (391) | 504 / 34 | 438 / 53 | 421 / 50 | 391 / 49 |
| T07 (241) | 111 / 18 | 276 / 52 | 237 / 50 | 241 / 49 |
| T11 (297) | 141 / 18 | 294 / 52 | 278 / 49 | 297 / 49 |

The full table is in `diagnosis.json → liveWeek9`. Under any challenger the bottom team is about 2–3 standard
deviations below the top team in a single week. Under the incumbent it is about 10, which is why the odds are
0% / 100%.

**Playoff / title calibration:** `INSUFFICIENT_BY_CONSTRUCTION`. No completed 2026 season exists (January 2027,
RPA-LGI-006).

## 5. Deviations and disclosures

1. **Weeks 1–8 were not design-blind.**
   - The preregistration (§0) discloses the F2 table, D11, v1–v3, the ROS scale study, and an exploratory
     decomposition run before freeze.
   - That pre-freeze diagnosis already scored the **incumbent** and an **A-like arm** (the presim under a fitted
     affine player-level scale, P_C0) on these same holdout weeks.
   - The holdout numbers for I are therefore a **re-measurement, not a confirmation**, and A's design was informed by
     them.
   - No candidate forecast (B0, B1, B2, A, S) was computed before freeze.
2. **Post-freeze correction to the incumbent's inputs (independent review of #2161).**
   - **The look-ahead.** `hydrate_roster_players` (`src/ros/team_strength.py`) sets `injured` from TODAY's Sleeper
     directory. That flag moved team strength, and so the incumbent's ROS multiplier and depth lift, in every
     evaluated week.
   - **The fix.** The point-in-time join now strips today's health fields. Injury is UNKNOWN for a past week and is
     read as not flagged; no archived as-of injury source exists.
   - **Both incumbents are reported.** The gated `I` is point-in-time. `I_todayInjury` reproduces the first run's
     multiplier and depth inputs.
   - **Effect.** The corrected incumbent is better: CRPS 71.5 → 69.0, MAE 84.6 → 81.8, binary log loss
     0.718 → 0.675 (h2h 0.705 → 0.622).
   - **What did not change.** Gate verdicts, the challengers' inputs, the split, the metrics, the thresholds and the
     seeds. The correction can only make the "beat the incumbent" gates harder.
   - **A side effect: Monte Carlo noise in the presim.** The presim draws ONE random stream across teams in
     team-strength order. The corrected strengths reorder teams, so every presim mean is re-drawn. The means move by
     up to 9.8 points (≤ 3.1%), which is the production presim's own Monte Carlo noise. A's and S's holdout metrics
     move by ≤ 0.3 points on bias, MAE and CRPS as a result (A's 80% coverage moves by one team-week). `I` vs `I_todayInjury` share the SAME presim, so their difference is the injury flags
     alone.
3. **Reporting changes from the same review (post-freeze, never gated):**
   - per-week metrics;
   - zSd / zMean (z-RMS no longer reads as a spread error when it is largely bias);
   - the contributor ranking computed from the metrics (§1) instead of typed by hand;
   - a percentile interval written explicitly symmetric (`symmetric_interval`). Identical values at B = 2,000.
4. **Redaction fix after the first run.**
   - The first run (`0395e6f21`) wrote cache receipts keyed by raw Sleeper URLs, which carried the league id.
     Preregistration §7 forbids that.
   - `eab492979` redacted them. The rerun was byte-identical in every non-provenance block.
5. **Gate-design flaw (preregistered, not repaired).** B1 and B2 have identical means, so TG3's strict "beat the
   other baseline's MAE" cannot pass for either. A v2 should compare against the single best baseline per metric.
6. **TG3 bias read literally.** S's |bias| is 20.18 against a limit of 20; no rounding rule was preregistered.
7. **The reconstructed incumbent omits the served availability calendar** for every arm. No point-in-time injury or
   availability states are archived (same as D11).
8. **Rosters and directory.**
   - Rosters are each week's Sleeper matchup list, which can include moves made after the first kickoff.
   - The directory is today's (eligibility and positions; health fields stripped).

## 6. What the evidence supports, for an owner decision

**Approve now: nothing live.** The preregistered rule gives no recommendation.

What the evidence does support:
1. **Accept the diagnosis.** The served best-ball team distribution is mis-scaled at team level for two separable
   reasons:
   - the ROS multiplier double-counts the presim's own evidence, which stretches team gaps by about 1.8× and halves
     the calibration slope;
   - the through-origin `rosValue / 2.7` conversion under-states every team (bias +69) and teams of mid-value players
     most.

   Its sd is about half the realized within-team SD. Together these produce F2's 0% / 100% odds and the inflated or
   deflated projected PF.
2. **Simple, transparent forecasts do much better on CRPS and MAE in every holdout week.** On log loss they are
   better overall, because they are not overconfident. They do not beat each other by enough to pass the
   preregistered bar.
3. **A v2 study, preregistered before week 10 data, would test:**
   - S (or A) with bye-week availability from the published schedule, which is knowable in advance;
   - the D11 corrected arm as a second incumbent-family arm;
   - the TG3 flaw fixed;
   - a week-cluster or block bootstrap;
   - week 9+ as the clean confirmation block;
   - optionally an as-of injury source (e.g. weekly injury reports) for a fair incumbent.

   Any eventual live change would go through the `playoff_sim` owner behind a new default-OFF flag, with owner
   approval.
4. **Interim user-facing caveat (owner product decision, C3 of SIM_CALIBRATION_V3).** "Seed, title and projected-PF
   numbers come from an uncalibrated weekly score model." Week-8 playoff qualification is robust to F2, per the audit's
   independent check.

## Reproduce

```
python scripts/team_points_calibration_eval.py evaluate --offline    # ~30 s with a warm cache
python scripts/team_points_calibration_eval.py diagnose --offline    # ~1 min
python -m pytest -p no:cacheprovider tests/ros_calibration
```

Without the cache, drop `--offline`. It makes 21 read-only public GETs, and the bodies are hash-pinned in `receipts`.

## UNRESOLVED

- **No clean holdout.** Weeks 1–8 were seen in aggregate (F2), and I was scored on them before freeze. Week 9 (final
  after Monday night, 2026-11-09) is the first clean week. A confirmation needs the script's `FINAL_WEEKS` extended,
  as a dated addendum with the method frozen.
- **Power.** 48 team-weeks in 12 clusters, and the bootstrap CIs are too narrow (§2). Baseline comparisons are point
  estimates, and S's TG1 / TG3 misses are within noise.
- **Availability and injuries** are unmodelled in every arm (no archived as-of states). Bye-week effects are visible
  in weeks 6–7 but not tested.
- **Contributor effects are each measured alone.** No interaction or ordering decomposition was done.
- **Playoff / title calibration** cannot be measured until the season ends.
- **Plain served-path bugs found: none.** The double count (D11) and the unpriced-as-absent presim rule are known,
  documented methodology. The injury look-ahead was in this study's reconstruction, not in the served path: a live
  forecast legitimately uses today's injuries.
