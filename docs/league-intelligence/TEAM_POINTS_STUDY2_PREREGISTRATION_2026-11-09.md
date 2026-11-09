# Best-ball team-points model, study two: preregistration

**Status:** PREREGISTRATION. This file is committed **alone**, before any harness change for this study, before any
forecast for any arm in §4 has been computed on any holdout week, and before the first kickoff of the first holdout
week. Results will go in `docs/league-intelligence/TEAM_POINTS_STUDY2_RESULTS.md`. Nothing above the freeze line changes
after this commit. A later correction goes in a dated addendum below it, and the affected result is then reported both
ways.

**Authority and lane:** owner directive 2026-11-08, Priority 1 (intake MD-97, RPA-LGI-008), option (b) of
`docs/owner/DECISION_BRIEFS_2026-11-08.md` brief 1. Design and evaluation only. Activation of anything is
owner-reserved.

**What this study does not do.** It promotes nothing, and champion and challenger stay separate. It does not change:
- `src/ros/playoff_sim.py` served behaviour;
- any feature flag (`playoff_ros_counted_once` stays OFF);
- `data/league_intel/` or `config/league_intel/`;
- any served value, route or frontend.

Every output carries `promotes: false`.

**Predecessor.** Study one (#2161):
`TEAM_POINTS_CALIBRATION_PREREGISTRATION_2026-11-08.md` and `TEAM_POINTS_CALIBRATION_RESULTS_2026-11-08.md`. That
completed study is not altered. Its gates, verdicts, constants and code stay as written. Its disclosed gate-design
flaw is repaired only here (§8).

**Label: SCREEN.** Five weeks is below the eight-week prospective minimum proposed in
`docs/research/forecasting/07_EVALUATION_DESIGN.md` (§2, PG9), and 80% power is reachable only for very large effects
(§10). A pass here can never be described as a confirmation.

## 0. The question, and what was known before this freeze

**Question.** On weeks whose first kickoff falls after this commit, does repairing the served best-ball team-points
model's level, its spread, or both, beat the served forecast on a proper score, without being materially worse than a
simple trailing-mean baseline?

Study one measured, on holdout weeks 5–8 (48 team-weeks):
- served arm: CRPS 69.0 against 29.0–32.0, MAE 81.8 against 42.0–45.4, between-team spread ratio 1.83, slope 0.49;
- team ordering is sound (concordance 0.814);
- two separable faults: the ROS multiplier on the presim drives spread; the through-origin `rosValue / 2.7` conversion
  drives level;
- a third, measured but not fixed by either: the presim's sd is about half the realized within-team sd (zSd 2.14 after a
  player-level affine conversion).

**Known before this freeze (disclosed).**
1. Everything published in study one's results and evidence, covering weeks 1–8. Weeks 1–8 are therefore not holdout
   here under any circumstances.
2. Close neighbours of two arms were already scored on weeks ≤ 8 by study one's diagnosis: `P_once` (CO without the bye
   calendar) and `P_C0` (the AFCO mean, without dispersion repair or bye calendar).
3. Design choices those numbers motivated, stated openly:
   - AF and AFCO carry a dispersion repair (§4), because a conversion alone leaves zSd at 2.14;
   - a calibration-slope band (§8), because the slope is the diagnosed spread fault;
   - the non-inferiority margin (§8), to repair the study-one flaw;
   - a bye calendar (§3), because study one showed the error concentrated in bye-heavy weeks and omitted the part of the
     served calendar that can be reconstructed.
4. Files read while writing this: `config/leagues/playoff_rules.json`,
   `config/league_intel/sleeper_league_snapshot_2026-07-26.json` (settings only), and the field names of one
   `data/ros/aggregate/history/` snapshot dated 2026-11-04.
5. A power simulation on synthetic data only, parameterized from study one's published numbers (§10).
6. **Not read or computed before this freeze:** any Sleeper matchup, roster or stats body for week 9 or later; any
   forecast or metric for any arm of §4 as defined here, on any week.

## 1. Population

- **League:** `dynasty_main`. 12 teams, best ball, weekly median game ON, 7 playoff teams, regular season weeks 1–14
  (`config/leagues/playoff_rules.json`, `playoff_week_start = 15`). The scoring card's fingerprint must equal
  `sf1:9e51824690d091f9`, or the run refuses.
- **Unit:** the team-week. All 12 teams in every included week. Nothing is dropped.
- **Season:** 2026.
- **Not in the population:** `dynasty_new` (start/sit; the presim path does not apply), any other league, any other
  season. No claim is made about them.
- **Realized score `y`:** Sleeper's matchup `points` for that team-week, after the week is settled (§2).

## 2. Weeks and timing

| block | weeks | role |
|---|---|---|
| fit-only | 1–9 | training inputs for §5 only; never scored here |
| **holdout (gated)** | **10, 11, 12, 13, 14** (60 team-weeks, 30 head-to-head games, 60 median games) | §6–§9 |
| extension (optional) | 15–17 | not part of this study; a dated addendum may report CRPS, MAE and bias; it can change no verdict |

**Freeze rule.** Every holdout week's first kickoff must be strictly after this file's commit timestamp. The harness
enforces this against the nflverse schedule and refuses otherwise. Week 9 opened on Thursday 2026-11-05 ET, before this
commit, so week 9 is fit-only even though its last game finishes afterward. Week 10 is expected to open on Thursday
2026-11-12 ET.

**Study-one weeks.** Weeks 5–8 are never holdout here. Study one's deferred confirmation block (week 9 and later) must
not be run on weeks 10–14 until this study's primary analysis is final, so it cannot become a back door to the holdout.

**Settled.** A week is settled when seven full days have passed since its last scheduled kickoff, per the nflverse
schedule. The harness refuses to score an unsettled week, and refuses a Sleeper matchups or stats body cached before
that week settled, so a pre-correction body cannot enter. Dates here are counted from week 8's Thursday 2026-10-29
opener and were not read from the schedule, because this file precedes all data access. Expected: week 14's last game is
Monday 2026-12-14, so the primary analysis cannot run before about **2026-12-22**. The rule governs, not this date.

**One analysis.** The primary analysis runs once, after all five weeks are settled. No holdout week may be scored,
summarized or "checked" before then. Anyone may see live scores; nobody computes forecast accuracy on these weeks
early.

## 3. Point-in-time input rules

For a target week `k`, and for every earlier week `j` used in fitting:

- **rosValue snapshot:** the latest `data/ros/aggregate/history/*.json` file STRICTLY before that week's first kickoff.
- **Roster:** that week's Sleeper matchup `players` list, through the production join (`hydrate_roster_players` +
  `compute_team_strength`). Disclosed limitation, identical for every arm: the list can include moves made between the
  first kickoff and a player's own game.
- **Injury state: none.** Today's health fields are stripped from the directory exactly as in study one's correction.
  No as-of injury source exists, so injury state is UNKNOWN and read as not flagged. Today's flags never enter.
- **Byes (new here):** every presim uses the served availability owner, `src/ros/availability.py`, with no return
  evidence, no overrides and health-stripped metadata, which leaves only its bye rule. A bye is published in advance.
  This restores the part of the served calendar that can be reconstructed point-in-time. It uses the served form: at
  origin `k` the presim cycles weeks `k` through the championship week. A player's NFL team comes from the directory.
- **Player directory:** the `players/nfl` body in the study-two cache if captured before week 10's first kickoff
  (recorded as `directoryPointInTime: true`); otherwise the body at run time, labelled `false` (study one's inherited
  caveat).
- **Slots:** `load_league_starter_slots("dynasty_main")`.
- **Leakage rule (enforced in code, pinned by test):** a week-`k` forecast reads only realized scores and player-weeks of
  weeks `< k`, plus week `k`'s as-of snapshot and roster. Any read of a realized week `>= k` raises.

**The reconstructed incumbent is not the exact served number.** It has the served equation, presim seed, points model and
bye calendar. It lacks the served calendar's injury and return-date parts, which were never archived.

## 4. Arms

Every arm outputs a Normal `(μ, σ)` per team-week. Two presims per week, both on the §3 inputs, both seeded with the
production seed `20260428`:

- `P^F`: `_bestball_presim` under the served `PointsModel()` fallback (`rosValue / 2.7`, fixed CVs).
- `P^C`: the same presim with the mean replaced by the fitted player-level affine conversion `C0`
  (`src/ros_calibration/conversion.py`, `a + b·rosValue`), the same one study one's diagnosis used, with the fallback CVs.

| id | name | μ and raw σ | σ used | role |
|---|---|---|---|---|
| **I** | incumbent | `_team_distributions_from_inputs(bestball_dists=P^F, ros_counted_once=False)` | raw | champion |
| **CO** | counted-once | same call with `ros_counted_once=True` (the held flag, unchanged) | raw | eligible challenger |
| **AFCO** | affine plus counted-once | `bestball_dists=P^C, ros_counted_once=True` | `d_k × raw` | eligible challenger, **tested first** |
| **AF** | fitted affine conversion | `bestball_dists=P^C, ros_counted_once=False` | `d_k × raw` | factorial arm, **never eligible** for a recommendation |
| **B1** | team mean, team sd | study one's B1 | | simple baseline |
| **B2** | team mean, pooled sd | study one's B2 | | simple baseline |

**Reported only, never gated, never recommended:** B0 (league climatology), A and S (study one's forms, on this study's
`P^F`), and `I_noCal` (the incumbent without the bye calendar, for continuity with study one).

AF is in the design to complete the 2×2 (conversion × ROS handling) and to answer whether the conversion alone suffices.
It cannot be recommended because `ODR-PLAYOFF-ROS-DOUBLE` already rejects the double count as policy. Its gates are
computed and published as information.

**Dispersion repair `d_k` (AF and AFCO only).** One number per arm per target week:

`d_k = √( mean over j ∈ [3, k−1], all teams, of ((y_{t,j} − μ_{t,j}) / σ^raw_{t,j})² )`

where `(μ_{t,j}, σ^raw_{t,j})` is that arm's own walk-forward forecast for week `j`, so each fitted from weeks `< j` only.
It needs at least 48 such rows; otherwise that arm has no forecast and the run refuses.

CO and I take no dispersion repair: each arm is tested exactly as it would ship.

**Parameters per forecast:** AF and AFCO estimate `a`, `b`, `d_k`.

## 5. Fitting (strictly before each forecast)

- **C0** for target week `k` is fit on every appeared, positively priced player-week of weeks `< k`, using each week's own
  §3 as-of snapshot, by `fit_model("C0", rows)`. It is refit at every origin. No decay, no tuning, no regularization.
- **B1, B2, B0, A, S** read realized weeks `< k` only, with study one's rules.
- **Week 9 and weeks 1–8** may be used as fit data. Study-one weeks are fit data only.
- Nothing is fit on, tuned on or selected from any holdout week. Seeds are in §4, §6 and §7.

## 6. Metrics

All are computed on unrounded values and pooled over the five holdout weeks, in every comparison over identical rows.

**Team-week level.**
- **Primary: CRPS**, closed-form Normal, mean over 60 team-weeks.
- Secondary: bias (`y − μ`), MAE, calibration slope (OLS of `y` on `μ`), z-RMS, zSd, zMean, central-80% coverage,
  within-week concordance over the 66 team pairs (realized ties excluded, predicted ties 0.5), between-team spread ratio.

**Binary game level** (the outcomes that drive playoff odds): 30 head-to-head games plus 60 median games.
- **Primary at this level: log loss** (clipped to `[1e-6, 1 − 1e-6]`).
- Secondary: Brier, each also by game type, under the production independence assumption. Median games use
  `game_day_sim.median_threshold`, 20,000 Monte Carlo draws, seed `20261109 + k`.

**Binary playoff level (descriptive only, never gated).** For each origin `k` in the holdout, the probability each team
qualifies:
- simulate weeks `k..14`, each arm's week-`k` `(μ, σ)` held constant as the simulator does, on the actual schedule, with
  realized results of weeks `< k`, median games and half-win ties counted;
- 20,000 draws, seed `20261109 + k`;
- qualification is the recorded rule: the seven best overall records, ties by points for.

Outcome: whether the team actually qualified. **Primary at this level: Brier at origin 10.** Secondary: log loss, each
later origin, and the count of probabilities at or beyond 1% / 99%. These are twelve outcomes from one standings table.
Title odds: `INSUFFICIENT_BY_CONSTRUCTION` (one champion, one season).

**Also reported (descriptive):** per-week metrics, study one's projected-PF and expected-wins errors, and the gate table
for every arm including AF and B-arms as references.

## 7. Inference, clustering and multiple comparisons

**Primary test (one per eligible arm).** `D_w` = mean over the 12 teams of `CRPS_I − CRPS_X` in week `w`. One-sided **exact
sign-flip test over the five weeks**: `p = #{s ∈ {±1}⁵ : Σ s_w D_w ≥ Σ D_w} / 32`.
- The week is the sampling unit because the claim concerns this league's 12 teams, a fixed population, and each week's
  12 scores share one NFL slate. Any within-week dependence among teams is absorbed.
- The smallest attainable p is 1/32 = 0.03125. So a challenger clears α = 0.05 only if it beats the incumbent on CRPS in
  **all five** weeks. That is the exact consequence of five weeks, and is intended.

**Clustering by team and week.** The sign-flip alone is not enough: in the §10 simulation, persistent team effects make
"every week positive" occur 9.5% of the time under a zero true mean. So SG1 also requires a **two-way pigeonhole bootstrap**
(resample the 12 teams and the 5 weeks independently, statistic = weighted mean over the product cells, B = 2,000, seed
20261109, 95% interval by `symmetric_interval`). Together their simulated false-positive rate is 2.9%.

Also reported, never gated:
- study one's paired team-cluster bootstrap, known to under-cover with 12 clusters and blind to week-wide shocks;
- the weekly-mean t statistic on 4 degrees of freedom.

**Multiple comparisons.** Two eligible challengers, fixed-sequence gatekeeping at one-sided α = 0.05: test **AFCO**; only
if its primary test rejects, test **CO** at the same α; otherwise CO is `NOT_TESTED` and fails SG1. This controls the
family-wise error rate.
- Holm (proposed in `07_EVALUATION_DESIGN` §5) cannot work here: with two arms it needs p ≤ 0.025 first, which is below the
  smallest attainable 0.03125.
- SG2–SG6 are necessary conditions on top of the primary test, so they can only lower the chance of a false
  recommendation.
- AF and every reported-only arm are outside the family.
- Per-week, per-team and per-game-type figures are descriptive. No claim rests on them.

## 8. Gates

These repair study one's disclosed flaw **in this study only**. There, each challenger had to strictly beat "the other
simple baseline", and B1 and B2 share one mean, so its MAE gate was unpassable for both.

Three changes:
1. Baselines are references here, never candidates, so no arm is ever compared with itself.
2. The reference is the **best baseline per metric**: `min(metric(B1), metric(B2))`. Identical baselines cannot block
   anyone.
3. A challenger must be **non-inferior** within a labelled margin, not strictly better. Strict inequality against a strong
   baseline is a coin flip at this sample size and is not what activation needs.

Margin: 5% of the best baseline's value (a PRIOR; 5% of log loss ≈ 0.02 nats, inside D11's 0.03). Every comparison uses
unrounded values: a |bias| of 20.18 fails a limit of 20. For challenger `X`:

| gate | passes when |
|---|---|
| **SG1 distribution (primary)** | (a) §7 sign-flip p ≤ 0.05, in sequence; **and** (b) two-way 95% lower bound on ΔCRPS = CRPS(I) − CRPS(X) is > 0; **and** (c) ΔCRPS ≥ 0.10 × CRPS(I) |
| **SG2 win probability** | LL(X) < LL(I); **and** Brier(X) ≤ Brier(I); **and** LL(X) ≤ 1.05 × best baseline LL |
| **SG3 level** | \|bias(X)\| ≤ 20; **and** MAE(X) < MAE(I); **and** MAE(X) ≤ 1.05 × best baseline MAE |
| **SG4 spread** | z-RMS(X) ∈ [0.80, 1.25]; **and** central-80% coverage ∈ [0.68, 0.92]; **and** calibration slope ∈ [0.70, 1.40] |
| **SG5 ordering** | concordance(X) ≥ concordance(I) − 0.02 |
| **SG6 non-inferior distribution** | CRPS(X) ≤ 1.05 × best baseline CRPS |

The set is jointly satisfiable: an arm equal to the best baseline on every metric, in band on every calibration
measure and better than the incumbent, passes. The harness carries that witness as a test.

## 9. Decision rule

Applied in this order. "Eligible" means AFCO or CO.

| # | condition | outcome |
|---|---|---|
| 0 | any void condition in §12 | `VOID` |
| 1 | fewer than five holdout weeks settled and scored | `INCONCLUSIVE` (`insufficient_weeks`) |
| 2 | AFCO passes SG1–SG6 | `PROMOTE_RECOMMENDATION(AFCO)` |
| 3 | otherwise, CO passes SG1–SG6 | `PROMOTE_RECOMMENDATION(CO)` |
| 4 | otherwise, at least one eligible arm passes SG1 | `INCONCLUSIVE` (`beats_incumbent_fails_gate`, naming each failed gate) |
| 5 | otherwise | `RETAIN` (no eligible arm demonstrated superiority over the incumbent) |

In every outcome except `PROMOTE_RECOMMENDATION` the incumbent stays and no owner request is made. An AF pass is reported
as information and never changes the outcome. A challenger is never retuned on these weeks after results are known: the
next step after `INCONCLUSIVE` or `RETAIN` is a new preregistration on new weeks.

## 10. Minimum sample and power

**Minimum-sample rule: all five holdout weeks, 60 team-weeks.** Five is the smallest week count at which the exact test can
reach p ≤ 0.05. With four weeks the floor is 1/16 and the study is `INCONCLUSIVE` by construction. There is no early stop
and no extension to reach significance.

**Power.** Synthetic simulation, no league data, 4,000 runs, parameterized from study one's published numbers: between-week
SD of the weekly gap 11.1; team effect SD 30 and team-week residual SD 30, calibrated to the published team-cluster
intervals. Pass rate of SG1 (a), (b) and (c):

| true ΔCRPS | SG1 pass rate |
|---|---|
| 0 | 2.9% |
| 7 (10% of 69) | 9% |
| 10 | 15% |
| 20 | 41% |
| 30 | 75% |
| 40 (study one's size) | 94% |

80% power needs a gap of about 33 points, roughly 48% of the incumbent's CRPS. Against the incumbent, that is the effect
this study can see. Anything smaller is likely to read as `RETAIN`, which then means "not demonstrated", not "no effect".

Against the baselines there is no meaningful power. The non-inferiority checks are point estimates. Assuming a weekly SD
of 4–5 CRPS points between two reasonable arms (an assumption; study one reports no such figure), the five-week mean has
a standard error near 2 against a 1.5-point margin, so an arm truly equal to the best baseline fails SG6 about one time in
four. In the same simulation a well-calibrated arm passes the z-RMS and coverage bands together about 95% of the time
(the slope band was not simulated).

## 11. What twelve teams and five weeks cannot prove

Stated in advance so a result is not over-read.
- **Effective sample.** Sixty team-weeks are not sixty independent observations. All twelve teams in a week share one NFL
  slate, one set of injuries and bye weeks; the realized unit of evidence is five weeks.
- **One league.** Twelve managers, one scoring card, one roster format. Nothing transfers to any other league.
- **One stretch of one season.** Weeks 10–14 are late-season weeks with the deadline passing in week 13 and playoff-chasing
  rosters. They say nothing about early-season forecasts, which is when the odds matter most and when these fits have the
  least data.
- **Team-week scores are not playoff odds.** The simulator also assumes weekly independence and independent teams. This
  study cannot test either at the season level.
- **Twelve playoff outcomes and one champion.** No statement about calibrated playoff or title probabilities follows from
  this study, in either direction.
- **Superiority, not sufficiency.** Beating a badly miscalibrated incumbent is a low bar. Non-inferiority to a trailing
  mean is measured with almost no power.

## 12. What voids the study

Any of these makes the outcome `VOID`, and no recommendation may be made:
1. Text above the freeze line differs from this commit.
2. This file's commit touched any other file, is not an ancestor of the evaluated code, or was pushed at or after week
   10's first kickoff.
3. Any Sleeper result for a holdout week was fetched or inspected before this file was pushed.
4. Any arm, gate, margin, week set, seed, fitting window or sequence is changed after this commit, except through a
   dated addendum that publishes the original result next to the changed one. An addendum can make a verdict
   stricter, never looser.
5. League facts change in the study window: the scoring fingerprint, best ball, median game, team count, or
   `playoff_week_start`.
6. The served equation, presim or points model changes before the run, as detected by the harness's behaviour
   fingerprint. The comparison would no longer be against what is served.
7. Any holdout week is scored before all five are settled, or study one's confirmation block is run on these weeks first.
8. Any fit or tuning touches a holdout week, or an arm reads injury flags from run time.

A holdout week that cannot be scored for a data reason is not a void: the outcome is `INCONCLUSIVE` under §9 row 1.

## 13. What passing means

A pass **only entitles the coordinator to ask the owner.** It is not approval, and it activates nothing. The ask must state
that this is a five-week SCREEN in one league, and must carry the §11 limits. Any live change still requires, in order:
1. an explicit owner decision recorded in `docs/owner/OWNER_DECISION_REGISTER.md`;
2. a new default-OFF flag through the `playoff_sim` owner, or the existing held flag for CO;
3. monitoring and a rollback plan.

This is the sequence fit → backtest → validate → compare → human approval → promote → monitor → rollback. Nothing
self-promotes.

## 14. Reproduction

Harness (added after this commit, before the run): `src/ros_calibration/team_points.py` and
`scripts/team_points_calibration_eval.py`, subcommand `study2`. Network off by default.

```
python scripts/team_points_calibration_eval.py study2 --network   # once, after week 14 settles
python scripts/team_points_calibration_eval.py study2             # cache only
```

Outputs under `docs/league-intelligence/evidence/team_points_study2/`, carrying `promotes: false`, code SHA, script and
library sha256, this file's commit, the card fingerprint, per-week snapshot sha256, cache receipts and seeds. No manager
name, team name or league id appears.

---

*Freeze line. Anything below is a dated addendum written after this commit.*
