# Team-level points calibration for the best-ball playoff simulator: results

**Status:** `RESEARCH_EVIDENCE_NOT_FOR_PROMOTION`. Nothing is served or wired, and every output carries
`promotes: false`. No change was made to `src/ros/playoff_sim.py`, any flag, `data/league_intel/`,
`config/league_intel/` or the points model.

| item | value |
|---|---|
| authority | owner master directive 2026-11-08 §6 Priority 1; MATH_AUDIT_2026-11-08 finding F2; RPA-LGI-008 |
| preregistration | `TEAM_POINTS_CALIBRATION_PREREGISTRATION_2026-11-08.md`, commit `b7aa4ac21`. That commit touches only the preregistration and was pushed before the script or library existed in the branch. |
| code | `src/ros_calibration/team_points.py` + `scripts/team_points_calibration_eval.py`, commit `0395e6f21`. A redaction fix followed in `eab492979` (see Deviations). |
| evidence run | code SHA `eab492979`, clean tree, preregistration an ancestor (`code` block in each file) |
| inputs | Sleeper public API: league, rosters, `players/nfl`, matchups weeks 1–8, stats weeks 1–8 (stats used in the diagnosis only). Also the nflverse schedule. 21 GETs on 2026-11-08, cached in gitignored `data/team_points_calibration/cache/`; both evidence runs are `--offline`. Per-week snapshot sha256 values are in `receipts`. |
| card | `sf1:9e51824690d091f9` (pinned, matched) |
| evidence | `evidence/team_points_calibration/evaluation.json` (sha256 of the LF form `6e8cba96…`) and `diagnosis.json` (`b4605110…`) |

## Headline

1. **No challenger passes all preregistered gates, so the incumbent stays.** Under the preregistered rule there is no
   recommendation (§3).
2. **The served team distribution is nevertheless decisively worse than every simple baseline on every probability
   metric.** Holdout weeks 5–8, 48 team-weeks:

   | metric | incumbent | challengers / baselines | note |
   |---|---|---|---|
   | CRPS | 71.3 | 29.0–32.1 | |
   | binary log loss | 0.718 | 0.40–0.43 | the incumbent is worse than a coin flip (0.693) |
   | MAE | 84.6 | 42.0–45.5 | |
   | 80% coverage | 0.27 | | |
   | z-RMS | 4.5 | | errors run about 4.5 times the simulated sd |

   Every challenger beats the incumbent with team-cluster CIs that exclude zero:

   | challenger | ΔCRPS | Δ log loss |
   |---|---|---|
   | A | +39.2 [19.7, 60.2] | +0.29 [0.07, 0.56] |
   | B1 | +41.1 [21.6, 61.1] | +0.30 [0.07, 0.55] |
   | B2 | +42.2 [22.6, 62.7] | +0.30 [0.07, 0.55] |
   | S | +41.6 [21.9, 62.0] | +0.32 [0.11, 0.56] |

   What fails is the second half of each gate: beating the OTHER simple baseline, plus bias, spread and ordering
   limits.
3. **The incumbent's team ORDER is fine; its scale and spread are not.**
   - All-play concordance 0.811 is the best of all arms (tied with A).
   - Calibration slope 0.47 means predicted differences are about twice the real ones.
   - Between-team spread of predicted means is 1.85× realized on the holdout, and 2.24× on the live week-9 forecast
     (F2 measured ≈ 2.3×).
4. **Diagnosis, ranked:**
   1. The **ROS multiplier on the presim** (the D11 double count, flag OFF) causes the spread error.
   2. The **through-origin `rosValue / 2.7` conversion** causes the level error.
   3. **Ignoring availability** and the **too-narrow simulated sd** come next.
   4. Position-family scale (offense 0.35 vs IDP 0.14 points per unit) matters little at TEAM level.

   Numbers in §1.

## 1. Diagnosis: why the served fallback mis-scales teams

Every arm uses the same point-in-time inputs: the snapshot strictly before the week's first kickoff, that week's
roster, and the production join, presim and seed. Bias = realized − predicted.

**Holdout weeks 5–8 (48 team-weeks):**

| arm | what it is | bias | MAE | slope | z-RMS | spread ratio | mean σ |
|---|---|---|---|---|---|---|---|
| L_F | deterministic lineup Σ `rosValue/2.7` (no noise) | +95.4 | 95.4 | 1.03 | — | 0.89 | — |
| P_F | production presim, fallback model | +69.1 | 69.7 | 0.89 | 3.94 | 1.01 | 25.1 |
| **I** | **served: P_F × (1 + 0.2 z), σ × (1.10 + 0.15 r)** | **+56.2** | **84.6** | **0.47** | **4.51** | **1.85** | 28.3 |
| P_once | D11 corrected arm (no multiplier, σ × 1.10) | +69.1 | 69.7 | 0.89 | 3.58 | 1.01 | 27.6 |
| P_C0 | presim, mean = one affine scale fitted on earlier weeks (`a ≈ 6.0 + 0.25·r`) | −12.8 | 41.7 | 1.31 | 2.17 | 0.69 | 25.8 |
| P_CF | presim, per-family affine | −11.8 | 41.1 | 1.27 | 2.17 | 0.72 | 25.8 |
| P_CR | presim, per-family rank curve | −5.9 | 39.7 | 1.28 | 2.06 | 0.73 | 25.6 |
| P_CF_oracle | P_CF with only players who appeared (**oracle, not knowable**) | +24.5 | 36.8 | 1.23 | 1.87 | 0.79 | 26.0 |

Weeks 2–8 (84 team-weeks) give the same ordering: I has slope 0.41 and spread ratio 2.08; P_F has 0.76 and 1.15;
P_CF has 1.03 and 0.83.

**Contributors, ranked by effect** (`diagnosis.json → contributors`):

| # | contributor | measured effect |
|---|---|---|
| 1 | **ROS multiplier re-applied to the presim** (the double count; `playoff_ros_counted_once` OFF) | spread ratio 1.01 → **1.85**, slope 0.89 → **0.47**, MAE +14.9. The multiplier runs 0.655–1.39 across teams. The presim and team strength are sums of the same `rosValue` numbers, so this stretch is pure re-use of evidence. **Main source of the spread error and of the 0% / 100% odds.** |
| 2 | **Unit conversion: `rosValue / 2.7` through the origin** | replacing it with one affine scale fitted on earlier weeks moves bias **+69 → −13** and MAE **70 → 42**. Through-origin gives low-`rosValue` players about 0, while real deep starters score 6+ points: the fitted intercept is about 6.0, and the slope about 0.25 vs 0.37. Teams built on many mid-value players are hit hardest. **Main source of the level error.** Once the level is fixed, the presim's between-team spread is too narrow (ratio 0.69, slope 1.3). |
| 3 | **Availability not modelled** (byes, injuries; the historical reconstruction has no point-in-time calendar) | the oracle arm shows a full-roster presim overstates the mean by about **35–36 points** (P_F 34.9, P_CF 36.4). Part of this is knowable in advance: NFL byes start week 5 (15 games), and weeks 6–8 each have four teams on bye (14 games). Realized league means fall to 317 and 326 in weeks 6–7, from 357–364 in weeks 3–5 (week 8: 346). Every empirical arm's holdout bias is concentrated in weeks 6–7 (−25 to −47). This is consistent with a bye effect but not proven. |
| 4 | **Spread: independent per-player draws with the fallback CVs** | presim σ ≈ 25 against a realized within-team SD of **46.2**, so about 1.8× too narrow. After the level fix z-RMS is still 2.2. The depth lift adds only ×1.12–1.14. |
| 5 | **Best-ball max over noisy draws** (P_F − L_F) | +26.2 points mean (10–52), 9.8% of the presim mean. A real effect, which realized best ball also has. With CV-proportional noise it scales with the mean, so it widens team gaps proportionally. |
| 6 | **Position-family scale** (C0 → CF / CR) | small at team level: MAE −0.6 (CF) / −2.0 (CR), spread ratio +0.03. Fixed slots give every team a similar position mix, so most of the family error cancels in a team total. It matters for player-level and cross-position reads (ROS scale study), not for team totals. |
| 7 | **Unpriced roster players draw 0** (presim skips `rosValue ≤ 0`) | 0.4%–3.7% of realized starter points per week. Minor. |

**Receipts:**
- Host-native scorer vs Sleeper `players_points`: **4,833 / 4,833** player-weeks within 0.02.
- Canonical solver (`src/ros/lineup.py`) over `players_points` vs Sleeper's team `points`: **95 / 96** within 0.05.
  The one miss (T08, week 8, solver +5.42) starts a player whom today's directory lists as DL/LB-eligible, and Sleeper
  did not start him in week 8. That fits a later eligibility change and is an inherited caveat (directory is today's).
- The reconstructed incumbent for week 9 runs **117.0–522.7**, against F2's served 117.3–524.5. The difference is the
  served availability calendar, which the reconstruction omits.

## 2. Champion vs challengers (primary holdout: weeks 5–8, rolling origin)

48 team-weeks, 24 head-to-head games, 48 median games, 12 team clusters.

| arm | bias | MAE | slope | z-RMS | cov80 | CRPS | concordance | log loss (all / h2h / median) | Brier | spread ratio |
|---|---|---|---|---|---|---|---|---|---|---|
| **I** (served) | +56.2 | 84.6 | 0.47 | 4.51 | 0.27 | 71.3 | **0.811** | 0.718 / 0.741 / 0.707 | 0.171 | 1.85 |
| B0 (reference) | −16.8 | 61.1 | −0.31 | 1.12 | 0.71 | 44.2 | 0.500 | 0.694 / 0.693 / 0.694 | 0.250 | 0 |
| B1 team mean, team sd | −16.8 | **42.0** | 1.09 | 1.41 | 0.73 | 30.2 | 0.788 | 0.419 / 0.380 / 0.438 | 0.136 | 0.84 |
| B2 team mean, pooled sd | −16.8 | **42.0** | 1.09 | 0.98 | 0.83 | **29.0** | 0.788 | 0.423 / 0.385 / 0.442 | 0.138 | 0.84 |
| A affine rescale of presim | −25.1 | 45.5 | 1.27 | 1.08 | 0.71 | 32.1 | **0.811** | 0.430 / 0.419 / 0.435 | 0.139 | 0.71 |
| S presim + trailing mean | −20.0 | 43.6 | 1.03 | 1.02 | 0.75 | 29.6 | 0.799 | **0.401** / 0.379 / 0.412 | **0.130** | 0.88 |

**Fitted challengers (week-8 forecast):**
- A: `y = 162.7 + 0.714·P`, s 53.5.
- S: `y = 30.8 + 0.438·P + 0.560·M`, s 50.9.

A's slope runs 0.50 → 0.71 as weeks accumulate. Both fits say the presim's raw scale is wrong: A's slope is well below
1, and its intercept is large.

## 3. Gates (preregistration §5)

| gate | B1 | B2 | A | S |
|---|---|---|---|---|
| TG1 CRPS: beat I (CI) and the other baseline | FAIL (30.2 > B2 29.0) | **PASS** | FAIL (32.1 > 29.0) | FAIL (29.6 > B2 29.0) |
| TG2 log loss: beat I (CI) and baseline; Brier ≤ I | **PASS** | FAIL (0.423 > B1 0.419) | FAIL (0.430 > 0.419) | **PASS** |
| TG3 level: \|bias\| ≤ 20, beat I MAE (CI), beat baseline MAE | FAIL (MAE ties B2) | FAIL (MAE ties B1) | FAIL (bias −25.1; MAE 45.5) | FAIL (bias −20.006; MAE 43.6 > 42.0) |
| TG4 spread: z-RMS in [0.80, 1.25], cov80 in [0.68, 0.92] | FAIL (z-RMS 1.41) | **PASS** | **PASS** | **PASS** |
| TG5 ordering: concordance ≥ I − 0.02 (0.791) | FAIL (0.788) | FAIL (0.788) | **PASS** | **PASS** |
| **verdict** | DOES_NOT_PASS | DOES_NOT_PASS | DOES_NOT_PASS | DOES_NOT_PASS |

**Recommendation under the preregistered rule: none. The incumbent stays.**

Reading the failures honestly:
- **S comes closest.** It passes TG2, TG4 and TG5. It misses TG1 by 0.6 CRPS against B2, and TG3 on bias by 0.006
  points and on MAE by 1.6 against the trailing mean.
- **B1 and B2 share one mean by construction**, so neither can strictly beat the other on MAE. TG3 was therefore
  unpassable for both. That is a gate-design flaw, disclosed below and not repaired after the fact.
- The **negative bias of every empirical arm** (−17 to −25) is concentrated in bye-heavy weeks 6–7 (§1, item 3).

**Development weeks 3–4 (never gated).** I: MAE 109.2, CRPS 94.2, log loss 0.611. B2: CRPS 27.9. A: CRPS 26.0, bias
+1.4. S has no forecast there (its 24-row floor needs k ≥ 5), so it is left out and named, never filled in.

## 4. Descriptive outputs (never gated)

**Season horizon (origins 5–8, horizon through week 8, 48 team-origin pairs):**

| arm | projected-PF MAE | projected-PF bias | expected-wins MAE |
|---|---|---|---|
| I | **190.6** | +142.5 | 0.76 |
| B1 | 70.9 | −49.7 | **0.67** |
| B2 | 70.9 | −49.7 | 0.71 |
| A | 87.4 | −68.5 | 0.84 |
| S | 82.8 | −61.8 | 0.72 |

Over horizons of one to four games, the incumbent's good ordering keeps its expected-wins error close to the others.
Its projected-PF error is 2.2–2.7 times theirs.

**Live week-9 forward forecasts** (anonymous index; realized weeks 1–8 mean in brackets):

| team | I | A | S | B2 |
|---|---|---|---|---|
| T09 (436) | 523 / 35 | 443 / 53 | 449 / 49 | 436 / 49 |
| T01 (391) | 504 / 33 | 438 / 53 | 421 / 50 | 391 / 49 |
| T07 (241) | 117 / 18 | 276 / 52 | 237 / 50 | 241 / 49 |
| T11 (297) | 142 / 18 | 294 / 52 | 278 / 49 | 297 / 49 |

The full table is in `diagnosis.json → liveWeek9`. Under any challenger the bottom team is about 2–3 standard
deviations below the top team in a single week. Under the incumbent it is about 10, which is why the odds are
0% / 100%.

**Playoff / title calibration:** `INSUFFICIENT_BY_CONSTRUCTION`. No completed 2026 season exists (January 2027,
RPA-LGI-006).

## 5. Deviations and disclosures

1. **Weeks 1–8 were not design-blind.** The preregistration (§0) discloses the F2 table, D11, v1–v3, the ROS scale
   study, and an exploratory incumbent decomposition run before freeze. The diagnosis numbers above equal that
   exploratory run exactly. No candidate forecast was computed before freeze.
2. **Redaction fix after the first run.** The first evaluation and diagnosis runs (code `0395e6f21`) wrote cache
   receipts keyed by raw Sleeper URLs, which carried the league id. Preregistration §7 forbids that.
   - `eab492979` redacts the id in the receipts only. The evidence was re-run on that SHA.
   - Every non-provenance block (holdout, gates, development, weeks, diagnosis summaries, contributors, live table)
     is byte-identical between the runs.
   - No method, threshold, split or seed changed after outcomes were seen.
3. **Gate-design flaw (preregistered, not repaired).** B1 and B2 have identical means, so TG3's strict "beat the other
   baseline's MAE" cannot pass for either. A v2 should compare each challenger against the single best baseline per
   metric.
4. **TG3 bias read literally.** S's |bias| is 20.006 against a limit of 20. The preregistration set no rounding rule,
   so the gate fails.
5. **The reconstructed incumbent omits the served availability calendar** for every arm. No point-in-time injury
   states are archived (same as D11). It reproduces F2's served week-9 range to within 2 points.
6. **Rosters** are each week's Sleeper matchup list, which can include moves made after the first kickoff. The
   **directory** is today's (eligibility and positions).

## 6. What the evidence supports, for an owner decision

**Approve now: nothing live.** The preregistered rule gives no recommendation.

What the evidence does support:
1. **Accept the diagnosis.** The served best-ball team distribution is mis-scaled at team level for two separable
   reasons:
   - the ROS multiplier double-counts the presim's own evidence and stretches team gaps by about 1.8×;
   - the through-origin `rosValue / 2.7` conversion under-states every team (bias +69) and most of all teams of
     mid-value players.

   Its sd is also about half the realized within-team SD. Together these produce F2's 0% / 100% odds and inflated or
   deflated projected PF.
2. **Simple, transparent forecasts already beat it by a wide margin.** CRPS falls 71 → 29–32 and log loss
   0.72 → 0.40–0.43, all with CIs excluding zero. They do not beat each other by enough to pass the preregistered bar.
3. **A v2 study, preregistered before week 10 data, would test:**
   - S (or A) with bye-week availability from the published schedule, which is knowable in advance;
   - the D11 corrected arm as a second incumbent-family arm;
   - the TG3 flaw fixed (beat the best baseline per metric);
   - week 9+ as the clean confirmation block.

   Any eventual live change would go through the `playoff_sim` owner behind a new default-OFF flag, with owner
   approval.
4. **Interim user-facing caveat (owner product decision, C3 of SIM_CALIBRATION_V3).** "Seed, title and projected-PF
   numbers come from an uncalibrated weekly score model." Week-8 playoff qualification is robust to F2, per the audit's
   independent check.

## Reproduce

```
python scripts/team_points_calibration_eval.py evaluate --offline    # ~20 s with a warm cache
python scripts/team_points_calibration_eval.py diagnose --offline    # ~1 min
python -m pytest -p no:cacheprovider tests/ros_calibration
```

Without the cache, drop `--offline`. It makes 21 read-only public GETs, and the bodies are hash-pinned in `receipts`.

## UNRESOLVED

- **No clean holdout.** Weeks 1–8 were seen in aggregate (F2). Week 9 (final after Monday night, 2026-11-09) is the
  first clean week. A confirmation needs the script's `FINAL_WEEKS` extended, as a dated addendum with the method
  frozen.
- **Power.** 48 team-weeks in 12 clusters. Baseline comparisons are point estimates, and S's TG1 / TG3 misses are
  within noise.
- **Availability** is unmodelled in every arm (no archived injury states). Bye-week effects are visible in weeks 6–7
  but not tested.
- **Playoff / title calibration** cannot be measured until the season ends.
- **Plain served-path bugs found: none.** The double count (D11) and the unpriced-as-absent presim rule are known,
  documented methodology, not plain bugs.
