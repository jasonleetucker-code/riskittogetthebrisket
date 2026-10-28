# ROS scale calibration (offense vs IDP): results

**Status:** `RESEARCH_EVIDENCE_NOT_FOR_PROMOTION`. Nothing is served or wired; every output carries
`promotes: false`; no live value, rank, `rosValue`, weight, curve, flag or card changed.

| item | value |
|---|---|
| preregistration | `ROS_SCALE_CALIBRATION_PREREGISTRATION_2026-10-28.md`, commit `d4ade9803` (touches only that file), committed 2026-10-28T13:41:21Z, before the script existed |
| code | `src/ros_calibration/` + `scripts/ros_scale_calibration_study.py`, commit `f7509c913`; evidence run on that SHA, clean tree, preregistration is an ancestor |
| inputs | Sleeper public API (league, `players/nfl`, matchups weeks 1–8, stats weeks 1–7), nflverse schedule fetched 2026-10-28; cached in gitignored `data/ros_calibration/cache/`. Pre-kickoff snapshot sha256 per week in `evaluation.json → receipts` |
| card | `sf1:9e51824690d091f9` (pinned, matched) |
| scorer receipt | v1 host-native points equal Sleeper's `players_points` within 0.02 on **4,275 / 4,275** rostered player-weeks (weeks 1–7) |
| evidence | `evidence/ros_scale_calibration/evaluation.json` (sha256 `a1627f57…`), `downstream.json` (`0b7780b3…`), `fits_week8_frozen.json` (`7d6e5287…`) |

## Headline

1. **The offense/IDP scale mismatch is real and confirmed, but it is mostly a SPREAD problem, not a level one.** On
   one shared scale (champion C0) the IDP-to-offense realized/predicted ratio is **D = 0.870 [0.797, 0.952]** (CI
   excludes 1): IDP is over-valued ≈13% relative to offense on average. The bigger distortion is in the tails:
   holdout calibration slope of realized on predicted points is **1.39 for offense and 0.52 for IDP**, and the fitted
   points per `rosValue` unit is **0.35 (offense) vs 0.14 (IDP)** (group fit, weeks 1–7). Each `rosValue` point is
   worth about 40% as many weekly points for IDP as for offense.
2. **Concrete:** LB1 Jack Campbell carries `rosValue` 91.8, above QB1 Josh Allen (86.4) and RB1 Jahmyr Gibbs (86.3).
   Converted per family (CR, weeks 1–7 fit) that is **19.4 vs 32.6 vs 32.1 expected points/week**. In the latest
   snapshot **53% of `rosRankOverall` top-100 are IDP**; by expected points 17–24%, by points above replacement
   33–36%.
3. **Per-position verdict: a group (offense/IDP) conversion is not enough; QB needs its own.** Under the group model QB
   is still under-predicted (realized/predicted 1.34); per-family models bring every gated family to 0.95–1.08
   (DB 1.08 the widest).
4. **No challenger passes all preregistered gates**, so there is **no recommendation for a live change** under the
   preregistered rule. All three challengers pass scale coherence (G1), accuracy (G2), stability (G4) and team
   ordering (G6); all three fail cross-group pair ordering (G3: +0.010 concordance, CI lower bound just below 0),
   and CF also misses lineup non-inferiority (G5) by 0.0006.

## 1. League facts, verified (owner description vs live)

From the live contract (`sleeper.rosterPositions`, `sleeper.scoringSettings`), `config/leagues/registry.json` and the
Sleeper league body (all three agree):

| item | owner description | verified | discrepancy |
|---|---|---|---|
| QB | 2 QB | `QB` ×1 + `SUPER_FLEX` ×1 | **Not 2 dedicated QB slots.** One QB plus a superflex (QB/RB/WR/TE). In practice the solver starts a QB there almost always, but a second QB is not required |
| RB / WR | 2 RB, 3 WR | `RB` ×2, `WR` ×3 | none |
| "2 WR flex" | 2 WR flex | `FLEX` ×2, eligible **RB/WR/TE** | **Not WR-only.** Sleeper `FLEX` accepts RB, WR and TE |
| TE | 2 TE, two-TE scarcity | `TE` ×2 | none on slots. **Scoring has no TE premium**: `bonus_rec_te 0.0` (ADR-009), so the scarcity is roster-driven only |
| K | — | `K` ×1 | **Owner omitted the kicker slot** |
| IDP | 3 DL, 3 LB, 3 DB | `DL` ×3, `LB` ×3, `DB` ×3, no IDP flex | none |
| superflex | yes | yes | none |
| other | — | 21 starters, 37 bench (58), best ball, 12 teams, playoffs from week 15, 7 playoff teams | — |

IDP scoring (live card): `idp_tkl_solo 1.33`, `idp_tkl_ast 0.8`, `idp_sack 2.92`, `idp_tkl_loss 4.24`,
`idp_qb_hit 2.12`, `idp_pass_def 5.3`, `idp_int 5.3`, `idp_ff 4.24`, `idp_fum_rec 3.19`, `idp_def_td 6.36`. Offense:
`pass_td 6`, `pass_yd 0.04`, `pass_cmp 0.37`, `pass_inc −0.67`, `rec 0.1` plus reception-length bands (0.25–2.0),
`bonus_fd_{rb,wr,te} 1.0`, `bonus_fd_qb 0.4`, `rec_yd`/`rush_yd 0.1`. All study points come from this card through
the host-native scorer.

## 2. Consumers of `rosValue` and whether they mix offense and IDP

| consumer | how it uses `rosValue` | mixes offense + IDP on the 0–100 scale? |
|---|---|---|
| `src/ros/team_strength.py::compute_team_strength` | sums starters (+ decayed bench) into `teamRosStrength` | **Yes** — 9 of 21 starter slots are IDP |
| `src/ros/power_v2.py` | team-strength percentiles into power rankings | **Yes** (via team strength) |
| `src/ros/direction.py`, `RosTradeFitPanel` | buyer/seller from team-strength rank; trade ROS-fit panel | **Yes** (via team strength) |
| `src/ros/tags.py` | `rosRankOverall ≤ 100` = "starter caliber"; `≤ 50` "top IDP" | **Yes** — overall rank interleaves both boards |
| `src/ros/playoff_sim.py` + `league_intel/sim_calibration.py` | presim draws `rosValue / 2.7` per player for every family, sums the best-ball lineup; ROS z-score + depth ratio from team strength | **Yes** — one global factor (V3 studies the points model itself) |
| `src/ros/lineup.py` (solver) | maximizes Σ value over slots | **No cross-group effect** here (no slot accepts both; no IDP flex). Within-offense scale matters for FLEX / SUPER_FLEX |
| `src/roster_intel/{marginal,best_ball_utility,droppability}` | lineup-delta weights; drop ladders across positions | **Yes** where candidates are compared across positions (droppability reads `rosValue` only through the optional scarcity input) |
| `src/league_intel/replacement.py` | per-position levels; `eliteSeparation` in `rosValue` units | within-position levels no; cross-position separation comparisons yes (experimental overlay only) |
| `src/api/gameplan.py` targets | `(rosValue − price) / price`, candidates capped per position | **Yes** when targets are ranked across positions |
| `src/trade/roster_capacity.py`, `src/draft/*` | `rosValue` drives lineup feasibility only; cost is `rankDerivedValue` | no |
| `src/public_league/player_impact.py` | writes realized points into a `rosValue` field | different quantity, no |

Measured distortion on the composite: across 84 team-weeks (weeks 1–7) IDP starters carry **48.5%** of the live
`startingLineupScore` but **44.5%** of awarded best-ball points.

**Points per `rosValue` unit, weeks 1–7, as-of pairing (n = player-weeks):** QB 0.656 (225), TE 0.676 (349),
DB 0.594 (636), WR 0.590 (717), RB 0.533 (476), DL 0.506 (490), LB 0.465 (579), K 1.503 (131). Kickers aside, the
same `rosValue` buys 41% more points at QB than at LB.

A second, input-side source of drift (already found by V3): the `draftSharksRosSf` IDP rank basis switched on
2026-09-16 (overall-list → within-position), lifting top-12 LB `rosValue` from 36.8 to ~65. `rank_to_score` also
depends on each board's `total_ranked`, so board size changes move a family's level. The rank-curve challenger CR is
invariant to both by construction (pinned by a test).

## 3. Champion vs challengers (primary holdout: weeks 5–7 pooled, rolling origin)

1,433 player-weeks (629 players), all scored by every model; 158,251 valid cross-group pairs; 36 team-weeks.

| model | params | MAE | RMSE | R_OFF | R_IDP | **D = R_IDP/R_OFF** | slope OFF | slope IDP | ΔMAE vs C0 [95% CI] |
|---|---|---|---|---|---|---|---|---|---|
| **C0** champion (one scale) | 2 | 6.445 | 8.232 | 1.077 | 0.937 | **0.870 [0.797, 0.952]** | 1.39 | 0.52 | — |
| CG group | 6 | 6.271 | 8.026 | 1.044 | 0.987 | 0.946 [0.869, 1.030] | 0.99 | 0.89 | +0.174 [+0.082, +0.271] |
| CF family | 16 | 6.209 | 7.984 | 1.031 | 0.990 | 0.961 [0.884, 1.045] | 0.97 | 0.79 | +0.236 [+0.102, +0.370] |
| **CR** family rank curve | 16 | **6.179** | **7.974** | 1.043 | 1.009 | **0.967 [0.891, 1.050]** | 0.94 | 0.87 | **+0.266 [+0.126, +0.404]** |
| F (served fallback, `r/2.7`) | 0 | 6.780 | 9.307 | 1.659 | 1.364 | 0.822 [0.729, 0.931] | 0.94 | 0.35 | −0.336 [−0.549, −0.120] |

**Per family, realized / predicted (n holdout player-weeks):**

| family | n | mean pts | C0 | CG | CF | CR | F |
|---|---|---|---|---|---|---|---|
| QB | 94 | 18.28 | **1.46** | 1.34 | 1.00 | 1.01 | 1.88 |
| RB | 178 | 12.00 | 1.07 | 1.02 | 1.12 | 1.12 | 1.55 |
| WR | 275 | 10.37 | 1.01 | 0.99 | 1.01 | 1.02 | 1.61 |
| TE | 135 | 7.93 | 0.88 | 0.91 | 0.98 | 1.01 | 1.73 |
| K | 53 | 8.78 | 1.17 | 0.93 | 0.93 | 0.94 | 3.85 |
| DL | 202 | 8.99 | **0.87** | 0.89 | 0.98 | 1.00 | 1.37 |
| LB | 235 | 11.25 | **0.89** | 0.99 | 0.93 | 0.95 | 1.14 |
| DB | 261 | 10.72 | 1.04 | 1.07 | 1.07 | 1.08 | 1.68 |

No gated family is significantly worse than C0 under any challenger (ΔMAE CI upper > 0 everywhere). Significant
family gains: LB (all three), TE (all three), DL (CF, CR), WR (CR).

**Other metrics**

| metric | C0 | CG | CF | CR |
|---|---|---|---|---|
| M3 week-to-week Spearman of μ (mean of 4→5, 5→6, 6→7; n ≈ 622) | 0.979 | 0.972 | 0.981 | 0.979 |
| M4 cross-group pair concordance (single week) | 0.6448 | 0.6548 | 0.6548 | 0.6553 |
| M4 ΔConc vs C0 [95% CI] | — | +0.0100 [−0.0007, +0.0203] | +0.0100 [−0.0056, +0.0258] | +0.0105 [−0.0060, +0.0279] |
| M4 ROS-horizon concordance (reported; 86,529 pairs) | 0.673 | 0.683 | 0.695 | **0.698** |
| M5 lineup agreement with Sleeper's awarded starters | 0.535 [0.505, 0.567] | 0.535 | 0.525 | 0.527 |
| M6a all-play team-week concordance (36 team-weeks) | 0.803 | 0.788 | 0.813 | 0.813 |
| M6b mean weekly Spearman, predicted vs realized team total | 0.767 | 0.746 | 0.781 | 0.781 |
| composite (team-strength formula on μ) weekly Spearman | 0.769 | 0.769 | 0.774 | 0.776 |

The **live** team-strength composite (production `compute_team_strength` on `rosValue`) scores all-play 0.793 and
weekly Spearman 0.748 on the same 36 team-weeks.

## 4. Gates (preregistration §5)

| gate | CG | CF | CR |
|---|---|---|---|
| G1 scale coherence (|D−1| ≤ 0.10, R in [0.85, 1.15]) | PASS (0.946) | PASS (0.961) | PASS (0.967) |
| G2 accuracy (ΔMAE CI > 0, no family worse) | PASS | PASS | PASS |
| G3 cross-group ordering (ΔConc CI lower > 0) | **FAIL** (−0.0007) | **FAIL** (−0.0056) | **FAIL** (−0.0060) |
| G4 stability (≥ C0 − 0.02) | PASS | PASS | PASS |
| G5 lineups (≥ C0 − 0.01) | PASS | **FAIL** (−0.0106) | PASS (−0.0080) |
| G6 team ordering (≥ C0 − 0.02) | PASS | PASS | PASS |
| **verdict** | DOES_NOT_PASS | DOES_NOT_PASS | DOES_NOT_PASS |

Champion diagnosis: **distortion confirmed** (C0's D CI [0.797, 0.952] excludes 1).
**Recommendation under the preregistered rule: none.**

Reading G3 honestly: single-week cross pairs are dominated by week-to-week noise (residual SD 7–12 points per player
against family mean differences of 1–8), so a correct scale fix moves single-week pair concordance by only ~1 point
and the player-cluster CI straddles zero. On the ROS horizon (realized mean over remaining weeks, ≥ 2 appearances —
reported, not gated) the gain is 2.5 points for CR. The gate was preregistered on the single-week version, and it
failed.

**Development weeks 3–4 (never gated):** same ordering. MAE C0 6.489, CG 6.327, CF 6.231, CR 6.207; D: C0 0.860,
CR 0.949; cross-group concordance C0 0.647, CR 0.661; lineup agreement C0 0.525, CR 0.515; all-play C0 0.826,
CR 0.803.

## 5. Downstream shadow (latest snapshot `2026-10-28T09-05-28`, current rosters, fits on weeks 1–7)

**Team strength / expected lineup points (anonymous team index; rank 1 = strongest):**

| team | live composite rank | C0 exp. lineup pts | CR exp. lineup pts | CR exp-points rank | CR composite rank |
|---|---|---|---|---|---|
| 1 | 1 | 342.9 | 332.6 | 2 | 2 |
| 9 | 2 | 347.8 | 339.4 | 1 | 1 |
| 4 | 3 | 321.2 | 318.2 | 4 | 4 |
| 6 | 4 | 308.9 | 311.0 | 5 | 5 |
| 8 | 5 | 312.3 | 325.4 | 3 | 3 |
| 5 | 6 | 293.4 | 294.2 | 6 | 6 |
| 10 | 7 | 283.3 | 278.6 | 7 | 7 |
| 2 | 8 | 275.2 | 259.7 | 8 | 8 |
| 12 | 9 | 262.5 | 249.3 | 9 | 9 |
| 3 | 10 | 248.1 | 232.5 | 11 | 10 |
| 11 | 11 | 237.8 | 233.9 | 10 | 11 |
| 7 | 12 | 225.9 | 213.0 | 12 | 12 |

The top two swap, team 8 rises 5 → 3 (it is offense-heavy relative to its IDP), teams 4 and 6 drop one place.
Buyer/seller direction reads team-strength rank, so these moves are what a trade ROS-fit read would inherit.

**Optimal lineups:** vs C0, the CR lineup changes on average 1.0 starter per team (max 2), CF 0.83, CG 0 (a group
map preserves within-group order). Changes are FLEX / SUPER_FLEX choices.

**Replacement (starter tier, points/week, CR):** QB 18.3, RB 12.5, WR 11.3, TE 8.6, K 9.4, DL 10.7, LB 11.1, DB 10.9.

**IDP share of an overall top-100:** `rosRankOverall` (the `tags.py` "starter caliber" cut) **53%**; by μ C0 53%,
CG 24%, CF 21%, CR 17%; by PAR C0 50%, CG 33%, CF 33%, CR 36%.

**Representative players (`rosValue` → μ points/week → PAR):**

| player | family rank | rosValue | μ C0 | μ CR | PAR C0 | PAR CR |
|---|---|---|---|---|---|---|
| Jack Campbell (LB) | 1 | 91.8 | 28.5 | 19.4 | 16.2 | 8.3 |
| Aidan Hutchinson (DL) | 1 | 87.2 | 27.4 | 17.9 | 14.9 | 7.3 |
| Josh Allen (QB) | 1 | 86.4 | 27.2 | 32.6 | 13.9 | 14.3 |
| Jahmyr Gibbs (RB) | 1 | 86.3 | 27.2 | 32.1 | 15.0 | 19.7 |
| Jaxon Smith-Njigba (WR) | 1 | 65.2 | 22.0 | 29.2 | 11.0 | 17.9 |
| Kyle Hamilton (DB) | 1 | 43.8 | 16.8 | 15.8 | 5.2 | 4.9 |
| Brock Bowers (TE) | 1 | 35.6 | 14.8 | 18.2 | 5.1 | 9.6 |
| Devin Lloyd (LB) | 12 | 52.1 | 18.8 | 13.9 | 6.5 | 2.8 |
| Tetairoa McMillan (WR, 2nd year) | 12 | 38.3 | 15.4 | 17.0 | 4.4 | 5.7 |
| Fernando Mendoza (QB, rookie) | 36 | 11.7 | 8.9 | 14.7 | −4.4 | −3.6 |
| Demetrius Knight (LB, deep) | 36 | 24.7 | 12.1 | 11.5 | −0.2 | 0.4 |
| Colby Parkinson (TE, deep) | 36 | 10.5 | 8.6 | 6.3 | −1.0 | −2.3 |

CR's QB intercept is high at deep ranks (a QB36 is mostly a non-starter whose appeared weeks are spot starts);
rookies get no special treatment in any model.

**Playoff sim:** Brier / log loss is `INSUFFICIENT_BY_CONSTRUCTION` (no completed season with as-of ROS snapshots).
V3 (C2) already measured that relative family scales move title odds by up to 10 points; this study's CR fits are
an input such a run could use, not a result.

## 6. Proof the dynasty board is untouched

- `git diff --name-only origin/main...HEAD` lists only new files: this doc, the preregistration, the evidence, the
  `src/ros_calibration/` package, its tests and the study script. No file under `src/api/`, `src/canonical/`,
  `src/ros/`, `src/league_intel/` or `src/sources/` changed; `src/league_intel/te_premium.py` (TE++ basis) untouched.
- `scripts/golden_board.py` on `origin/main` (`12b0f3209`) and on this branch: **byte-identical captures** (sha256
  `40697845…` both; 1,087 rows, 740 ranked); `scripts/board_diff.py --expect-no-value-change`: **0 values moved,
  0 ranks changed, ASSERTION OK**.
- `tests/ros_calibration/test_isolation.py`: no module under `src/`, `scripts/` (except the study script),
  `deploy/` or `server.py` imports `src.ros_calibration`; the frontend never references it; the package imports
  only `src.ros.lineup.lineup_position` and the replacement owner; it contains no file writes.

## 7. Owner recommendation

**What to approve now: nothing live.** The preregistered rule gives no recommendation, and the scale fix moves
user-visible ranks (team strength, overall tags), which is owner-reserved.

**What the evidence supports, for an owner decision:**

1. **Accept the diagnosis.** `rosValue` is not a cross-position currency: on one scale IDP is over-valued ~13% on
   average and its spread is about 2.5× too wide relative to offense; QB is under-valued ~46% (superflex). Every
   consumer in §2 marked "Yes" inherits it.
2. **If a fix is wanted, the candidate is CR** (per-family rank → expected points curve): best MAE (+0.27 points per
   player-week vs C0, CI excludes 0), scale coherence D 0.97, every family within 0.95–1.08 except DB 1.08 and RB 1.12,
   invariant to the rank-basis steps that moved IDP levels this season. It failed G3 (single-week pair ordering,
   underpowered) and passed everything else.
3. **Where it would go:** a new, separately named field (e.g. `rosPointsPerWeek`) computed beside `rosValue` by the
   ROS aggregation owner, consumed first by team strength and the overall tag cut, behind a new default-OFF flag.
   `rosValue` itself would not change. Do not add positional multipliers on top: PAR already uses the canonical
   replacement owner.
4. **Evidence still missing before any activation:** the week-8 confirmation with the frozen weeks 1–7 fits
   (`fits_week8_frozen.json`, sha256 `7d6e5287…`); ideally two or more further weeks so G3 can be evaluated on the
   ROS horizon with a preregistered gate; a decision on whether G3 should be gated at single-week or ROS horizon.
5. **Rollback** would be the flag off (consumers read `rosValue` as today); nothing in this PR needs rollback.

## Deviations and disclosures

1. `evaluation.json → code.scriptSha256` is computed by the reused v1 `code_identity()` and hashes the v1 script;
   this study's own script hash is the top-level `scriptSha256`.
2. The downstream run (§5) used the same code SHA; its rosters are Sleeper's week-8 matchups body (current rosters).
3. `no_stat_line` grows from ~50 to ~130 rostered player-weeks per week after week 4 (IR / inactive players without a
   Sleeper stat row). They are outside the population in every model; counts are in `receipts`.
4. No method, threshold or split was changed after outcomes were read. No re-run was made.

## UNRESOLVED

- **No clean holdout week.** Weeks 5–7 were seen by the SIM_CALIBRATION v1–v3 studies (other models). Week 8 is not
  final; its confirmation is deferred against the frozen fits.
- **G3 is underpowered at single-week horizon**; whether to gate on the ROS horizon is an owner methodology call.
- **Opponent / matchup uncertainty, injuries after the snapshot and weekly variance** are not modelled here (V3 owns
  spread); the per-family residual SD is reported only.
- **Playoff-sim Brier** cannot be measured until a season completes with as-of snapshots.
- **Kickers** have 53 holdout player-weeks, just above the 50 floor; K results are noisy (ΔMAE CIs span ±0.5).
- The **`draftSharksRosIdp`** board (from 2026-10-27) is present only in the week-8 snapshot; none of the evaluated
  weeks include it, so its effect on the IDP scale is not yet measured.

## Reproduce

```
python scripts/ros_scale_calibration_study.py evaluate     # ~1 min with a warm cache
python scripts/ros_scale_calibration_study.py downstream
python -m pytest -p no:cacheprovider tests/ros_calibration
```
