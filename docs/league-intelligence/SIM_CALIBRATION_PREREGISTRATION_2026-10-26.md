# Best-ball sim points model — calibrated vs fallback: preregistered study (RPA-LGI-008)

**Status:** PREREGISTRATION. Frozen at commit time. It was written and committed before any model was fitted and
before any held-out result was computed. Results and the verdict go in
`docs/league-intelligence/SIM_CALIBRATION_RESULTS_2026-10-26.md`. Nothing in this file changes after the results
are known. A later correction would be a dated addendum below the freeze line at the end.

**Authority:**

- `docs/EXECUTION_PLAN.md` §0, "League intelligence ... owner, 2026-10-19 (later)". Experimental models never
  change served values until they pass promotion gates written down before the holdout is examined.
- `docs/owner/IDP_VALUATION_ACCURACY_DIRECTIVE_2026-10-25.md`. Research and shadow only, preregistration before
  evaluation, and no look-ahead.

Champion ≠ challenger: the fallback constants are what production serves today, so they are the champion here.
This study promotes nothing. Every output carries `promotes: false`.

## 0. The question, and why it matters

`src/league_intel/sim_calibration.py::load_points_model()` reads `data/league_intel/sim_points_model.json`. When
the file is absent it returns `PointsModel()`, the fallback constants:

- `rosValuePerPoint` 2.7;
- per-position CV QB 0.32, RB 0.55, WR 0.60, TE 0.65, DL 0.55, LB 0.45, DB 0.50;
- every other position (including K) uses `FALLBACK_DEFAULT_CV` 0.55;
- the result is stamped `pointsModelSource: "fallback-constants"`.

The RPA-LGI-008 audit found that `data/league_intel/` does not exist on the production box. So every best-ball
draw runs on these constants: playoff odds (`src/ros/playoff_sim.py`), Game Day (`src/ros/game_day_sim.py`),
best-ball marginal utility (`src/bestball/marginal.py`) and the forecast archive. `build_calibration` and
`write_calibration` exist, but nothing calls them.

**Question.** Does the artifact that `build_calibration` produces from real stat lines, scored under the live
`dynasty_main` card, predict held-out weekly points better than the fallback constants, by the standard in §6?

### Information known before this preregistration

Disclosed, not hidden.

- Draft PR #1941 (Lane D) reported in-sample within-player CVs over 2026 weeks 1–6: DL 0.73, DB 0.65, QB 0.57.
  Those six weeks **include the holdout weeks 5–6 below**. They are a different statistic (own-weeks spread, not
  `build_calibration`'s pooled CV), but they are holdout-period information, and this study cannot unsee them.
- Draft PR #1931 (Lane A) verified the host-native scorer: 3,710 of 3,710 rows within 0.01 of Sleeper's
  `players_points` on 2026 weeks 1–6.
- D11 (`docs/research/PLAYOFF_ROS_DOUBLE_COUNT_D11.md`) failed its G4 (distribution / uncertainty) gate. Its
  evidence ran on the fallback constants, with `sampleSize` 0.
- This unit has inspected the data only for format: row counts, key names, whether `gp` is present (2026 week 5 has
  2,241 stat rows, of which 1,461 carry `gp`), the matchup row keys, the schedule dates, and the card fingerprint.
  It has not fitted a model, computed a player mean, or scored a holdout prediction.

## 1. Data

All sources are public. Sleeper bodies are cached once under the gitignored `data/idp_accuracy/cache/`, keyed
`sha256(url)[:24]`, the same scheme Lanes A and D used. The cache bodies those lanes fetched on 2026-10-26 are
reused byte for byte. Anything missing is fetched with the same throttled public GET (under 5 requests per second).
Every body's sha256 goes into the evidence file.

| input | source | use |
|---|---|---|
| live scoring card | `GET /v1/league/1312006700437352448` → `scoring_settings` | scoring every season |
| card identity | `scoring_fingerprint(card)` must equal **`sf1:9e51824690d091f9`** | **abort on mismatch**: every number would be void |
| stat lines | `GET /v1/stats/nfl/regular/{season}/{week}`, read through `sim_calibration.fetch_stat_lines` | points |
| 2026 rosters | `GET /v1/league/1312006700437352448/matchups/{week}` → `players` | population, team-week pools |
| 2026 realized team totals | the same rows → `points` (Sleeper's awarded best-ball total) | team-week outcome |
| 2025 rosters | `GET /v1/league/{previous_league_id}/matchups/{week}`, with `previous_league_id` read from the live league body (2025 `dynasty_main`, 10 teams) | 2025 population |
| positions | `GET /v1/players/nfl` (today's directory) → `position`, `fantasy_positions` | CV family, slot eligibility |
| point-in-time rosValue | `data/ros/aggregate/history/*.json`, tracked in git | scale fit, predicted means |
| schedule | nflverse `schedules/games.csv` | week cutoffs, finality |

**Scoring.** Every player-week is scored with the host-native scorer,
`compute_weekly_points({**row, "player_id": pid, "season": s, "week": w}, card, position=lineup_position(pos), source="sleeper")`.
That is the path Lane A verified at 3,710 of 3,710. 2025 stat lines are scored under the **live 2026 card**. That
makes them a rescored reference for how players' weeks vary under today's rules, not a statement of what 2025 paid.
The `config/league_intel` card is **not** used: it is 21 rate keys stale.

**Point-in-time rosValue (no look-ahead).** The cutoff for week `w` is the earliest kickoff of 2026 week `w`, from
the nflverse schedule (ET converted to UTC). The snapshot used is the latest `data/ros/aggregate/history/` file
whose timestamp is **strictly before** that cutoff. rosValue reaches a Sleeper id through the production join,
`team_strength.hydrate_roster_players` + `team_strength.compute_team_strength`, run on that week's matchup rosters
(`fullRoster[].rosValue`). The study keeps no private name matcher.

| use | cutoff | snapshot (from the file listing) |
|---|---|---|
| scale fit (2026 preseason) | week 1 kickoff 2026-09-10T00:20Z | `2026-09-09T21-17-37.092580+00-00.json` |
| holdout week 5 | 2026-10-09T00:15Z | latest before cutoff (expected `2026-10-08T20-15-39…`) |
| holdout week 6 | 2026-10-16T00:15Z | latest before cutoff |
| confirmation week 7 | 2026-10-23T00:15Z | latest before cutoff |

No point-in-time rosValue exists before 2026-04-28. So 2025 cannot feed the scale fit, and it is used only for
variance.

**Population.** A player-week enters the study only when all of these hold:

- (a) the player is on a `dynasty_main` matchup roster that week (the 2025 league for 2025);
- (b) his directory position is one the sim draws: QB, RB, WR, TE, K, DL, LB or DB;
- (c) his host row exists, is not a team entry, and shows an **appearance**.

An appearance is the Lane D definition: `gp > 0`, `off_snp > 0`, `def_snp > 0`, or non-zero host-native points.

**Missing is never zero.** Each of these is excluded and counted by reason, season and week, never scored 0:

- `no_stat_line`: the host has no row for the player that week;
- `no_appearance`: a row exists but shows no appearance;
- `team_entry`: the scorer refuses the row;
- `unknown_position`: the player is not in the directory, or has a position outside the sim's set;
- `unpriced`: rosValue ≤ 0, or no join at the as-of snapshot. This applies to the scale fit and the holdout
  predictions only.

A host-native score of 0 on an appearance is a real 0 and is kept. The points model describes a player who plays.
Whether he plays belongs to `src/ros/availability`, a separate owner that is out of scope here.

## 2. Split

**Fixed origin.**

- **Fit:** 2025 weeks 1–17 for which the 2025 league has matchup rosters (its fantasy season ends at week 17;
  week 18 has no rosters), plus 2026 weeks 1–4.
- **Primary holdout:** 2026 weeks 5–6.
- **Confirmation holdout:** 2026 week 7.

Week 7 is not final at preregistration: DAL at PHI kicks off on 2026-10-26 at 20:15 ET. A week joins the
evaluation only when every one of its games has a `result` in the schedule. Its stats are fetched no earlier than
that. Week 7 is therefore run later against the **frozen** candidate, by sha256 and with no refit, as a dated
addendum. It is not part of this verdict.

**Why a fixed origin and not rolling-origin.** The decision on the table is whether to ship one artifact.
A fixed origin evaluates exactly one frozen candidate, which is the thing a `write_calibration` would ship. A
rolling origin evaluates a refitting procedure, and each origin would produce a different candidate. With only two
final holdout weeks there is also little to roll. A refit that includes weeks 5–7 would be a new candidate, and it
would need its own evaluation.

**Split integrity.** The fit stage receives only fit weeks. The script asserts that no holdout or confirmation week
reaches either `build_calibration` call, and a test pins that.

## 3. The candidate (`build_calibration`, reused; no second calibration owner)

The candidate comes from two calls to `src.league_intel.sim_calibration.build_calibration`, composed as follows.

- **Variance call (V).** All fit player-weeks (2025 weeks 1–17 and 2026 weeks 1–4) are passed as
  `stat_lines_by_week` with season-qualified week keys (`2025*100 + w`, `2026*100 + w`), because one integer week
  key would collide across seasons. `ros_values = {}`. This yields `byPosition` (pooled CV, mean, n, `measured`),
  with the owner's own 30-sample floor and the [0.15, 1.20] clamp.
- **Scale call (S).** 2026 weeks 1–4 player-weeks with a positive preseason rosValue. `ros_values` maps
  pid → preseason rosValue. This yields `scale` (`rosValuePerPoint`, `r2`, `n`), the owner's through-origin fit.
- **Candidate.** The artifact from V, with its `scale` replaced by S's `scale`. Both call receipts are recorded.
  The candidate is written to `docs/league-intelligence/evidence/sim_calibration/candidate_sim_points_model.json`
  and loaded back through `load_points_model(path=…)`. The study evaluates exactly what the owner's loader would
  serve.

**Host-native points enter `build_calibration` unchanged.** Each player-week is passed as the one-key line
`{"hostNativePoints": P}`, with `config = {"hostNativePoints": 1.0}`. `score_stat_line` then returns exactly `P`,
and every other step of `build_calibration` (positions, floor, clamp, scale fit, schema) runs as written. The
alternative, passing raw host rows with the raw card, is checked for parity in D3 rather than assumed.

## 4. Predictions

### Player level

For model `M` ∈ {C = candidate, F = `PointsModel()` fallback}, holdout week `w`, and player `i` with as-of
rosValue `r` and position `p`, the prediction is exactly `PointsModel.draw_from_mean` with
`mean_points`:

- `μ = max(0, r / k_M)`;
- `σ = max(0.5, μ · cv_M(p))`;
- `X = max(0, N(μ, σ²))`.

The outcome is the host-native score `y`, and `y* = max(0, y)`. The model cannot produce negative points.

### Team-week (the sim itself)

For each of the 12 rosters in each holdout week:

- **Pool:** that week's matchup roster with its as-of `fullRoster` rows, restricted to players who appeared that
  week. This is "oracle availability". It is labelled as such: as-of injury states are not archived, and
  availability is a separate owner.
- **Draws:** 2,000 draws of production's `playoff_sim._bestball_weekly_score(pool, slots, rng, model)`. That is a
  `PointsModel.draw` per priced player, then the exact `solve_optimal_assignment`.
- **Slots:** `starter_slots_from_roster_positions(league.roster_positions)`.
- **Seed:** one per (week, roster), shared by both models (common random numbers).
- **Outcome:** Sleeper's awarded `points` for that roster and week.
- **Cross-check:** the exact solve over host-native points of the roster must reproduce `points` within 0.01. The
  count is reported. A mismatch is reported, not repaired.

## 5. Metrics

### Player level (per family and pooled)

- **Log score** (higher is better). The censored Gaussian (Tobit) likelihood of `y*`: `log Φ(−μ/σ)` when
  `y* = 0`, and `log(φ((y*−μ)/σ)/σ)` when `y* > 0`.
- **CRPS** (lower is better). The closed form for a normal left-censored at 0, at observed `y`:
  `σ[z(2Φ(z)−1) + 2φ(z) − 1/√π] − σ[lΦ(l)² + 2Φ(l)φ(l) − Φ(√2·l)/√π]`, with `z = (y−μ)/σ` and `l = −μ/σ`. For
  `y < 0` it is `−y` plus the value at 0, which is identical for both models.
- **Interval coverage.** Central 80% and 95% intervals,
  `[max(0, μ+σ·z_lo), max(0, μ+σ·z_hi)]`. An outcome is covered when `lo ≤ y* ≤ hi`.
- **PIT.** For `y* > 0`, `Φ((y*−μ)/σ)`. For `y* = 0`, `U·Φ(−μ/σ)`, where `U` is drawn from a uniform
  distribution with seed 20261026 and the same `U` is used for both models. Uniformity is measured by the KS
  distance D to Uniform(0,1), with the asymptotic Kolmogorov p-value and a 10-bin histogram.

**Families:** QB, RB, WR, TE, K, DL, LB, DB (`lineup_position`). A family is **gated** when it has at least 50
holdout player-weeks. Other families are reported only.

**Uncertainty.** The paired differences are `ΔLS = LS_C − LS_F` and `ΔCRPS = CRPS_F − CRPS_C`, so a positive value
favours the candidate. Intervals are 95% percentile bootstraps, B = 2,000, seed 20261026, resampling **players**
(clusters) with replacement: the pooled interval over all players, family intervals within the family.

### Team-week

- sample CRPS, `mean|X−y| − ½·mean|X−X′|`;
- PIT, `(#{X<y} + U·#{X=y})/n`;
- 80% and 95% coverage from type-7 empirical quantiles of the draws;
- mean bias, `mean(X) − y`.

## 6. Gates: "the candidate beats the fallback"

The gates apply to C on the primary holdout (2026 weeks 5–6). F's numbers are reported beside them.

| gate | passes when |
|---|---|
| **SC-G1 coverage** | In every gated family, C's 80% coverage is in [75%, 85%] and its 95% coverage is in [90%, 100%]. |
| **SC-G2 log score** | Pooled mean ΔLS > 0 with the 95% CI lower bound > 0, **and** no gated family has a ΔLS CI upper bound < 0. |
| **SC-G3 CRPS** | Pooled mean ΔCRPS > 0 with the 95% CI lower bound > 0, **and** no gated family has a ΔCRPS CI upper bound < 0. |
| **SC-G4 PIT** | In every gated family, C's KS D ≤ 0.08, **and** the pooled D for C is below the pooled D for F. |
| **SC-G5 team-week** | Across the 24 team-weeks, C's 80% coverage is in [65%, 95%], its 95% coverage is ≥ 85%, **and** its mean team-week CRPS is ≤ F's. |

These gates are not D11's G1–G5, and are named `SC-` so they cannot be confused with them.

**Verdict.** `CANDIDATE_BEATS_FALLBACK` if and only if all five gates pass. Otherwise the verdict is
`CANDIDATE_DOES_NOT_BEAT_FALLBACK`, and every failing gate is named. The gates are conjunctive, so passing needs
no multiplicity correction.

The SC-G1, SC-G4 and SC-G5 thresholds are declared priors, not derived constants:

- ±5 pp is about 1.8 standard errors of an 80% coverage at n = 200;
- D ≤ 0.08 bounds the CDF error that a ±5 pp interval error permits, with some slack;
- the team-week bands are approximately the exact binomial 95% range at n = 24.

## 7. What a result justifies (promotion is owner-only)

- **Any gate fails.** No promotion request. Production keeps serving what it serves today (the fallback). The
  candidate stays a research artifact in `docs/`. The results document reports, by position, what each model gets
  wrong.
- **All five pass.** That would justify an **owner request**. It is not a promotion. Two conditions apply first:
  - the week-7 confirmation, run on the frozen candidate, keeps the pooled ΔLS and ΔCRPS point estimates above 0;
  - the request names the **exact candidate file by sha256**.

  Writing it to `data/league_intel/sim_points_model.json` on the box is owner-reserved: that path auto-loads into
  served playoff odds, Game Day, marginal utility and the forecast archive. A refit on more weeks is a new
  candidate and needs its own evaluation.

**This study never writes `data/league_intel/`.** The script refuses any output path inside that directory, a
test pins the refusal, and the candidate is named `candidate_sim_points_model.json`.

## 8. Descriptive analyses (declared now, never gated)

- **D1. What the fallback gets wrong, by family.** For F and C:
  - mean predicted-mean bias, `mean(μ − y*)`;
  - realized mean against predicted mean;
  - interval coverage;
  - KS D;
  - the share of `y* = 0` against the predicted zero mass.
- **D2. Pooled CV against within-player CV, fit window only.** `build_calibration`'s pooled CV (between- plus
  within-player spread) against the within-player CV: each player's own appeared weeks, players with at least 4,
  n-weighted by family. This tests whether the pooled statistic answers the question the sim asks.
- **D3. Raw-path parity.** `score_stat_line(raw host row, raw card)` against the host-native points on every fit
  row, counting rows with |Δ| > 0.01. A future writer who passes raw lines straight into `build_calibration` would
  inherit any disagreement.
- **D4. Team-week sensitivity without the availability filter.** Every priced rostered player is drawn, whether or
  not he played.
- **D5. Exclusion census.** Every exclusion reason, by season and week.
- **D6. One cross-position scale.** The realized mean against `r/k` by family, in the fit window and in the
  holdout. This tests whether one `rosValuePerPoint` fits every position.

## 9. Outputs

Under `docs/league-intelligence/evidence/sim_calibration/`:

- `candidate_sim_points_model.json`;
- `evaluation.json`: gates, metrics, exclusion census, descriptive analyses.

Both carry:

- `promotes: false`;
- the code SHA (the commit containing the script) and the script's own sha256;
- the card fingerprint;
- the sha256 of every cached input body and every rosValue snapshot;
- the seeds.

The evidence contains no manager, team name or roster-identified number: team-week results appear only as
aggregates and anonymous PIT values. Player-level rows are aggregated by family.

---

*Freeze line. Anything below is a dated addendum written after results were known.*
