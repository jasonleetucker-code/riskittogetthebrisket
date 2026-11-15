# Playoff / title odds — removing the double-counted ROS evidence (Owner Decision 11)

**Status (2026-10-18): EVIDENCE GATE FAILED → INCUMBENT KEPT.** The corrected equation exists behind the flag
`playoff_ros_counted_once`, default **OFF** (shadow only). Published odds are unchanged.

| record | where |
|---|---|
| owner decision | 2026-10-18 closeout directive, Part 3, Decision 11 ("double-counted evidence is not acceptable; the evidence gate determines whether the proposed implementation has actually corrected it") |
| preregistration (committed before any result) | `docs/research/PLAYOFF_ROS_D11_PREREGISTRATION.md`, commit `70662dcf4c` |
| evaluation code | `scripts/evaluate_playoff_ros_once.py` |
| captured inputs / full results | `docs/research/evidence/D11/inputs.json`, `docs/research/evidence/D11/results.json` |
| structural proof (G1) | `tests/ros/test_playoff_ros_counted_once.py` |
| Power Rankings unchanged | `tests/ros/test_power_formula_unchanged_by_d11.py` |

## 1. Where ROS evidence entered twice

The engine is `src/ros/playoff_sim.py` (the one canonical playoff / title engine, C5-PLAY-01). Line numbers are on
`origin/main` `fd87c9068a`.

1. **The pre-sim is ROS evidence.** In a best-ball league each team's weekly `(mean, sd)` is replaced by the
   pre-sim (line 706, `emp_mean, emp_sd = bb_mean, bb_sd`). The pre-sim draws every rostered player from
   `model.draw(rosValue, position)` (line 411) and solves the exact best-ball lineup on each draw.
2. **The mean multiplier re-applies it.** Lines 711–712 then compute `ros_z = (teamRosStrength − mean) / sd` and
   `blended_mean = emp_mean × (1 + ROS_BLEND × ros_z)`, `ROS_BLEND = 0.20`. `teamRosStrength` is
   `0.72·startingLineupScore + 0.18·benchDepthScore + 0.05·coverage + 0.05·health`
   (`src/ros/team_strength.py` lines 40–43 and 192), and the lineup and bench scores are sums of the **same
   `rosValue` numbers** the pre-sim draws from (line 172).
3. **The spread re-applies it too.** Line 715 calls `_team_variance_multiplier` (line 264):
   `1.10 + 0.15 × benchDepthScore / startingLineupScore` — again a ratio of the same `rosValue` sums — although the
   pre-sim spread already comes from drawing the whole roster, bench included, through the lineup solve.

So on a pre-sim basis the roster's ROS evidence entered the mean twice and the spread twice. On an empirical or pool
basis (start/sit leagues, or a best-ball team whose pre-sim could not run) the basis is past scores, not ROS, so the
ROS term there is its one entry — not a double count.

## 2. The equations

For team *i* with ROS z-score `z_i`, depth ratio `r_i = bench_i / starters_i` (capped to [0, 1]), and basis
`(μ_i, σ_i)`:

**Incumbent** (`incumbent_presim_plus_ros_multiplier`), every basis:

```
mean_i = μ_i × (1 + 0.20 × z_i)
sd_i   = σ_i × (1.10 + 0.15 × r_i)          best ball
sd_i   = σ_i                                 start/sit
```

**Corrected** (`ros_counted_once`):

```
basis = presim:            mean_i = μ_i                   sd_i = σ_i × 1.10
basis = empirical / pool:  mean_i = μ_i × (1 + 0.20 × z_i)  sd_i = σ_i × (1.10 + 0.15 × r_i)  (best ball) or σ_i
```

Both forms are one function, `_compose_team_distribution`; the flag selects `ros_counted_once`. The constant 1.10
best-ball bump on a pre-sim basis is kept: it is not ROS evidence, so removing it is outside this decision (named in
§6). The incumbent form is pinned to the retired arithmetic over 1,200 random inputs, so flag-off is byte for byte
the published engine.

**Proof that ROS counts once (G1).** On a pre-sim basis the corrected mean and sd do not move when `z_i` or `r_i`
change, and two team-strength summaries that disagree completely produce identical corrected distributions when
the rosters (hence the pre-sim) are the same; the incumbent moves in both cases. On an empirical basis the ROS term
still moves the mean (its one entry). All in `tests/ros/test_playoff_ros_counted_once.py`.

## 3. Data used, and what was not available

* **Used:** 2026 regular-season weeks 1–5 (every final week at capture, 2026-10-18 22:04 UTC) of both active leagues.
  `dynasty_main`: 12 teams, best ball, median game on → 30 head-to-head games, 60 median games, 60 team-weeks.
  `dynasty_new`: 10 teams, start/sit, no median → 25 games, 50 team-weeks.
* **Point-in-time ROS:** the `data/ros/aggregate/history` snapshot nearest before each week's Thursday 22:00 UTC
  cutoff (`nearest-prior`): 2026-09-10, 09-17, 09-24, 09-30, 10-08. Rosters: that week's Sleeper matchup rows.
* **Not available:**
  - 2024 and 2025 — no point-in-time ROS aggregate before 2026-04-28; excluded rather than rebuilt from hindsight.
  - Season-end title calibration (AL-5b) — no archived season has finished (2026 ends January 2027).
  - Point-in-time injury states for past weeks — none archived; the historical pre-sim ran without the
    availability calendar (same for every arm).
  - The calibrated points model is box-local and untracked. This run used the documented fallback
    (`fallback-constants`, 2.7 rosValue per point) for every arm. Production may differ (§6).

## 4. Results (preregistered metrics)

Best-ball pool = `dynasty_main` only.

| metric | incumbent | corrected | mean-only (Cm) |
|---|---|---|---|
| log loss, head-to-head (30) | 1.004 | **0.449** | 0.442 |
| log loss, median games (60) | 1.198 | **0.767** | 0.759 |
| log loss, all binary (90) | 1.133 | **0.661** | 0.653 |
| Brier, all binary | 0.193 | **0.171** | 0.170 |
| favourite mean probability / realized win rate | 0.927 / 0.867 | 0.881 / 0.833 | 0.879 / 0.833 |
| PIT mean (ideal 0.5) | **0.831** | 0.945 | 0.944 |
| PIT variance (ideal 0.083) | 0.110 | 0.018 | 0.019 |
| central-80% coverage (ideal 0.80) | 0.150 | 0.167 | 0.167 |

A coin flip scores 0.693 log loss; the incumbent is worse than a coin flip on every binary outcome type.
Cluster bootstrap (5 league-weeks, 10,000 reps): Δ binary log loss (corrected − incumbent) = −0.472, 95% [−0.763,
−0.244]. Mean-only: −0.480, [−0.780, −0.247].

**Predicted distribution behaviour.** Team means on the week-5 inputs: incumbent 82.7–504.3, corrected 138.5–378.1,
realized week-5 scores 221.3–461.2 (median 353.6). The multiplier stretches the field by about ±40% around a pre-sim
that is itself too low and too narrow; that stretch is what produced 99% title odds. The corrected arm removes the
stretch but leaves the pre-sim's own level and spread error fully exposed.

| gate | result | detail |
|---|---|---|
| G1 structural | PASS | test file above |
| G2 non-inferiority | PASS | hi95 −0.244 ≤ +0.03 |
| G3 favourite calibration | PASS | gap 0.048 vs 0.060 |
| **G4 distribution / uncertainty** | **FAIL** | \|PIT − 0.5\| 0.445 vs 0.331 (worse by 0.115 > 0.05); coverage 0.167 vs 0.150 passes |
| G5 format sensitivity | PASS | `dynasty_new` identical for every team-week (max \|Δ\| 0); `dynasty_main` Δ −0.472 |
| G6 well-formed forecast | PASS for `dynasty_new`; **not evaluable** for `dynasty_main` | see §5 |

## 5. Current-state check

* `dynasty_new` (start/sit): both arms give identical odds (top title probability 0.792, entropy 0.607, sum 1.000;
  published incumbent 0.799). Expected: the correction only touches a pre-sim basis.
* `dynasty_main`: **both arms are refused** with `median_game_week_unsimulable` for weeks 6–14, exactly as the
  published `data/ros/sims/latest_championship.json` has been since 2026-10-17 12:31 UTC. Cause found during this
  check, not fixed here: the remaining schedule maps one roster to owner `735693375101108224` while the scored
  weeks key that team as `712035316776669184`, so one scheduled team has no distribution and the median game is
  refused. Separate defect; reported as a follow-up.

## 6. Disposition

Preregistration §7: any gate fails → keep the incumbent, the corrected equation stays shadow only. **G4 failed**, so:

* `playoff_ros_counted_once` defaults **OFF**; every published playoff, bye, seed, championship, finals and
  semifinal probability is unchanged, and the payload now names its equation (`rosEvidenceMethod`).
* The corrected equation is implemented, tested, and reachable only through the flag.
* The official Power Rankings formula is untouched (pinned: constants, no import path into the simulator, and a
  byte-identical section with the flag on and off).

What the failure means, stated plainly: the double count is real and proven, and removing it makes head-to-head and
median-game probabilities far better. But the pre-sim it exposes predicts team scores that sit below nearly every
realized score (mean PIT 0.95) with a spread far narrower than observed (PIT variance 0.018 against the ideal
0.083). The incumbent's multiplier
"helped" PIT only by spreading the means apart. G4 caught a real calibration problem in the shared pre-sim, not in
the correction itself, but the preregistered rule does not allow overriding a failed gate.

**What would unblock promotion** (engineering evidence, no owner decision needed):

1. Re-run on the production box, where the calibrated `data/league_intel/sim_points_model.json` may exist:
   `python scripts/evaluate_playoff_ros_once.py evaluate --inputs docs/research/evidence/D11/inputs.json --out /tmp/d11_box.json --current`.
   If every gate passes there, the preregistered rule sets the default ON.
2. Otherwise repair the pre-sim's level and spread (points-model scale, zero-valued unmapped players, the per-player
   draw variance), which is the AL-5c calibration work, then re-run the same preregistered comparison.
3. Separately, fix the `dynasty_main` owner-id mismatch that stops the title odds from publishing (§5).

## 7. Rollback

Nothing is switched on. If the flag is ever enabled: `RISKIT_FEATURE_PLAYOFF_ROS_COUNTED_ONCE=0` and restart (flag
reads are cached per process). Code rollback is reverting this PR; the incumbent arithmetic is unchanged and pinned.
