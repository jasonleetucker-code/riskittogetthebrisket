# Playoff / title odds — ROS counted once: preregistered comparison (Owner Decision 11)

**Status:** PREREGISTRATION — frozen at commit time, written and committed before any comparison result was
computed. Results and the disposition live in `docs/research/PLAYOFF_ROS_DOUBLE_COUNT_D11.md`. Nothing in this file
changes after the results are known; a later correction would be a dated addendum below the freeze line.

**Authority:** Owner Decision 11 (2026-10-18 closeout directive, Part 3): "double-counted evidence is not
acceptable; the evidence gate determines whether the proposed implementation has actually corrected it." Use the
AL-5c shadow evaluation "or an equivalent preregistered independent comparison". AL-5c does not exist on `main`
(`docs/completion/families/family_C.json`, row `AL-5c`: "None exist"), so this is the equivalent preregistered
comparison. Champion ≠ challenger: evaluation does not promote. Promotion here means the default of the flag
`playoff_ros_counted_once`, and it follows only the disposition rule in §7.

**Information known before preregistration (disclosed, not hidden).** The 2026-09-26 intake entry
(`docs/OWNER_REQUESTED_TODO.md`, D2) records one observation: one team's championship odds were 99.45% with the
multiplier and 84.6% without it, and the incumbent's weekly log loss on weeks 1–2 was 0.928 against 0.693 for a
coin flip. No other result on the data below has been computed by this unit.

## 1. Arms

| arm | name | equation on a best-ball pre-sim basis | role |
|---|---|---|---|
| I | incumbent (`incumbent_presim_plus_ros_multiplier`) | `mean = presim_mean × (1 + 0.20 × ros_z)`; `sd = presim_sd × (1.10 + 0.15 × depth_ratio)` | champion |
| C | corrected (`ros_counted_once`) | `mean = presim_mean`; `sd = presim_sd × 1.10` | **primary challenger — the gates apply to C** |
| Cm | mean-only | `mean = presim_mean`; `sd = presim_sd × (1.10 + 0.15 × depth_ratio)` | secondary, reported only, never gated |

On an `empirical` or `pool` basis (start/sit leagues, or a best-ball team whose pre-sim could not run) all three
arms are identical: `mean = basis_mean × (1 + 0.20 × ros_z)`, `sd = basis_sd × m` with `m = 1` for start/sit and
`1.10 + 0.15 × depth_ratio` for best ball. The code is `src/ros/playoff_sim.py::_compose_team_distribution`; C is
`ros_counted_once=True`.

## 2. Data actually available, and what is not

* **Available:** the 2026 regular season of both active registry leagues (`dynasty_main`: 12 teams, best ball,
  weekly median game on; `dynasty_new`: 10 teams, start/sit, median off), every week that is FINAL at capture time
  (weeks before the Sleeper NFL-state week whose matchups all carry points). Expected at capture: weeks 1–5.
* **Point-in-time ROS inputs:** `data/ros/aggregate/history/*.json` (tracked in git from 2026-04-28). For week `w`
  the snapshot used is the latest one at or before the cutoff `Thursday of week w, 22:00 UTC` (week 1 Thursday =
  the first Thursday on or after Sleeper's `season_start_date`). Fidelity label: `nearest-prior`.
* **Rosters:** the player list Sleeper records on that week's matchup row (exact for the week; it includes moves
  made after the cutoff during the week — disclosed, identical for every arm).
* **Not available:**
  - 2024 and 2025: no point-in-time ROS aggregate exists before 2026-04-28, so the pre-sim cannot be rebuilt for
    those seasons without hindsight values. They are excluded, not approximated.
  - Season-end calibration (AL-5b): no season with a point-in-time forecast archive has finished; 2026's playoffs
    end in January 2027. Season-level title-odds calibration cannot be measured and is not a gate.
  - Point-in-time injury/availability states for past weeks: none archived, so the historical pre-sim runs without
    the availability calendar (identical for every arm). The current-state check in §5 uses the production calendar.
  - The calibrated points model (`data/league_intel/sim_points_model.json`) is box-local and untracked; the
    evaluation uses whatever `load_points_model()` returns where it runs and records its `source`. Identical for
    every arm.

## 3. Predictions and outcomes

Per league-week, every arm builds per-team `(mean, sd)` through `_team_distributions_from_inputs` (the production
function) from: realized scores of weeks `< w` (empirical basis / pool), team-strength rows computed by
`team_strength.compute_team_strength` on that week's rosters and the point-in-time aggregate, and — for best-ball
leagues — `_bestball_presim` with the production seed `20260428` and the registry's starter slots.

Scores are drawn jointly exactly as the simulator draws them, `max(0, N(mean, sd))`, 20,000 draws per league-week
with seed `20261018 + week` and common random numbers across arms.

| outcome | definition | prediction |
|---|---|---|
| H2H | each matchup pair; y = 1 if team A outscores B, 0.5 on a tie | P(A > B) + ½ P(A = B) |
| median | leagues with `league_average_match = 1` only; each team-week, y = 1 above the week's threshold, 0.5 on it, threshold = `game_day_sim.median_threshold` of the realized scores | same rule applied per draw |
| score | each team-week's realized points | PIT u = share of draws ≤ realized points |

Probabilities are clipped to [1e-6, 1 − 1e-6]. Log loss `LL = −[y ln p + (1 − y) ln(1 − p)]`; Brier `(p − y)²`.

## 4. Metrics

Per arm and per league, and pooled over best-ball leagues: mean LL and Brier over H2H, over median, and over both
("binary"); favourite calibration over H2H (mean favourite probability vs realized favourite win rate, favourite
chosen by that arm); PIT mean, PIT variance (ideal 1/12) and central-80% coverage (share of u in [0.1, 0.9]).

## 5. Current-state forecast (predicted distribution behaviour)

For each league, the live public snapshot and today's team strength (`data/ros/aggregate/latest.json`, current
rosters, production availability calendar) feed `simulate_playoff_odds` with `n_simulations = 20,000` and
`random.Random(7)` under I and under C. Reported: every team's playoff and championship odds under both, the
largest title probability, the Shannon entropy of the title distribution, and, as a reconstruction cross-check,
the published `data/ros/sims/*_championship.json` value for I.

## 6. Gates (all apply to C against I)

| gate | rule | population |
|---|---|---|
| G1 structural | a test proves that on a pre-sim basis C's mean and sd do not change when `ros_z` or `depth_ratio` change, and that they still do on an empirical basis | code |
| G2 non-inferiority (primary) | Δ = mean binary LL(C) − mean binary LL(I); the upper bound of the 95% cluster-bootstrap interval (resampling league-weeks, 10,000 reps, seed 20261018) is ≤ +0.03 nats | best-ball leagues |
| G3 favourite calibration | \|p̄_fav − ȳ_fav\|(C) ≤ \|p̄_fav − ȳ_fav\|(I) + 0.05 | H2H, best-ball leagues |
| G4 distribution / uncertainty | \|mean PIT(C) − 0.5\| ≤ \|mean PIT(I) − 0.5\| + 0.05 AND \|cov80(C) − 0.80\| ≤ \|cov80(I) − 0.80\| + 0.05 | team-weeks, best-ball leagues |
| G5 format sensitivity | (a) every start/sit league: C and I identical for every team-week (max \|Δmean\| = max \|Δsd\| = 0); (b) every best-ball league on its own: Δ point estimate ≤ +0.03 | per league |
| G6 well-formed forecast | for every league with a playable bracket, C's championship odds sum to 1 within 0.005 and every playoff probability is in [0, 1] | §5 |

There is no separate sample-size gate: the cluster-bootstrap interval in G2 carries the sample size, and a small
sample widens it. The season-level calibration AL-5 ultimately asks for is unavailable (§2) and is not replaced by
a weaker substitute.

## 7. Disposition rule

* **Every gate G1–G6 passes:** implement C behind `playoff_ros_counted_once`, default **ON**, and document the
  movement of every published probability (§5).
* **Any gate fails, or cannot be evaluated:** keep the incumbent served (flag default **OFF**); C stays a shadow
  equation reachable only through the flag; the failure is reported with its numbers.

In both cases the official Power Rankings formula (`src/ros/power_v2.py`) is not touched, and a test pins it.

## 8. Reproduction

```
python scripts/evaluate_playoff_ros_once.py capture --out docs/research/evidence/D11/inputs.json
python scripts/evaluate_playoff_ros_once.py evaluate --inputs docs/research/evidence/D11/inputs.json \
    --out docs/research/evidence/D11/results.json --current
```

`capture` reads Sleeper's public API; `evaluate` reads only the captured file and tracked repository data, except
`--current`, which builds the live public snapshot for §5.

---
*Freeze line. Nothing above changes after results are computed.*
