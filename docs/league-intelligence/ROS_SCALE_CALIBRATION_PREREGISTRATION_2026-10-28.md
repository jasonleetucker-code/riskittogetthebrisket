# ROS scale calibration (offense vs IDP): preregistration

**Status:** PREREGISTRATION. Frozen at commit time. It is committed **alone**, before the study script exists and
before any outcome-based number of this study has been computed. Results go in
`docs/league-intelligence/ROS_SCALE_CALIBRATION_RESULTS_2026-10-28.md`. Nothing above the freeze line changes after
results are known; a later correction is a dated addendum below it.

**Lane:** Workstream A of the 2026-10-28 coordinated cycle (research/shadow only). Champion ≠ challenger. This study
promotes nothing, changes no live value, rank, `rosValue`, source weight, Hill curve, TE++ basis, package model,
fairness band, verdict, scoring card or flag, and wires nothing into a live path. New code is an isolated package
(`src/ros_calibration/`) imported only by the study script, pinned by an isolation test. Every output carries
`promotes: false`.

## 0. The question

`src/ros/aggregate.py` publishes `rosValue` = a weighted mean of `rank_to_score(rank, total_ranked)` =
`100 · (ln(n+1) − ln r) / ln(n+1)` over ROS boards. Offense boards rank offense and IDP boards rank IDP, so the
best player on each board lands near 100 whatever he scores under this league's card. Consumers that put offense and
IDP on one scale (team-strength composite sums starters across both; `rosRankOverall` mixes both; the sim points
model applies one `rosValue → points` factor to every family) inherit whatever cross-group mismatch exists.

The study measures that mismatch against realized host-native points and evaluates candidate conversions of
`rosValue` into **expected weekly fantasy points under the exact card** (the comparable currency), plus a
points-above-replacement (PAR) read for value comparisons.

### Information known before this preregistration (disclosed)

- **Prior studies on the same weeks.** `SIM_CALIBRATION_{,V2_,V3_}RESULTS_2026-10-2{6,7}.md` published, for 2026
  weeks 5–7, per-family realized/predicted mean ratios for *other* models (the served fallback `rosValue / 2.7` and
  per-family forward fits on re-anchored `rosValue`). V3 reports that the fallback over-scales QB ≈1.97× relative to
  LB ≈1.16× (week 7), i.e. the scale mismatch is real at family level. The candidates below (§3) are designed with that
  knowledge. **Weeks 5–7 are therefore not design-blind**; they are the primary holdout only because no clean final
  week exists. Week 8 (not final at freeze) is the deferred confirmation (§7).
- **Inputs-only facts read before freeze (no outcome):**
  - Pre-kickoff snapshot per 2026 week (latest `data/ros/aggregate/history/` file strictly before the week's first
    kickoff, nflverse schedule fetched 2026-10-28): wk1 `2026-09-09T21-17-37`, wk2 `09-17T21-51-47`, wk3
    `09-24T23-24-45`, wk4 `09-30T13-07-10`, wk5 `10-08T20-15-39`, wk6 `10-15T21-53-29`, wk7 `10-22T22-01-15`, wk8
    `10-28T09-05-28`. Weeks 1–7 have all games final; week 8 has none.
  - The IDP level step between the wk1 and wk2 snapshots (V3 §0: `draftSharksRosSf` IDP ranks switched from an
    overall-list to a within-position basis). Mean of the top-12 `rosValue` per family in the wk2…wk8 snapshots:
    LB 62–65, DL 53–56, QB 51–54, RB 53–55, WR 46–48, DB 35–39, TE 23–25, K ≈ 8; in the wk1 snapshot LB 36.8, DL 33.9.
  - `draftSharksRosIdp` (new IDP board) first appears 2026-10-27; it is in the wk8 snapshot only.
  - League facts (live contract `sleeper.rosterPositions` / `scoringSettings`, registry): starters
    `QB, RB×2, WR×3, TE×2, FLEX×2 (RB/WR/TE), SUPER_FLEX, K, DL×3, LB×3, DB×3` (21 slots), 37 bench, best ball,
    12 teams, no IDP flex; IDP scored on `idp_tkl_solo 1.33, idp_tkl_ast 0.8, idp_sack 2.92, idp_tkl_loss 4.24,
    idp_qb_hit 2.12, idp_pass_def 5.3, idp_int 5.3, idp_ff 4.24`; `bonus_rec_te 0.0`.
  - One outcome glimpse: while testing API access, the first ~600 bytes of the week-1 matchups body were printed
    (one team's week-1 total). No player-level outcome was read.
- **No number of this study (any model, any week) has been computed.**

## 1. Data, population, scoring

Reuse, no second copy: `scripts/sim_calibration_study.py` (v1) loaders — `CachedFetcher` (write-once cache, here under
gitignored `data/ros_calibration/cache/`), `schedule_by_week`, `snapshot_before`, `load_snapshot_players`,
`as_of_full_rosters` (production join: `hydrate_roster_players` + `compute_team_strength`), `classify_player_week`
(host-native points via `compute_weekly_points(..., source="sleeper")`, the scorer reconciled 1,415/1,415 in LI-2),
`rostered_by_week`, `lineup_family`, card fingerprint pin `sf1:9e51824690d091f9` (abort on mismatch).

- **Season:** 2026 only (snapshot history starts 2026-04-28). 2025 is not read.
- **Player-week population `P_t`:** every player on any of the 12 week-`t` rosters (Sleeper matchups body) whose
  status is `appeared` (v1 rule), whose lineup family is one of QB RB WR TE K DL LB DB, and whose **as-of `rosValue`
  is positive** (week-`t` pre-kickoff snapshot, production join). Unpriced players are excluded and counted, never
  scored as 0.
- **Groups:** OFF = {QB, RB, WR, TE}; IDP = {DL, LB, DB}; K is its own group.
- **Receipt:** per week, the share of rostered player-weeks whose v1 points equal Sleeper's matchups `players_points`
  within 0.02 is reported (not gated).

## 2. Split (rolling origin, as-of only)

Each evaluated week `h` is predicted by fits on weeks `1..h−1` only, each fit week paired with its own pre-kickoff
snapshot. The script refuses if any week ≥ `h` reaches the fit for `h`.

| block | weeks | role |
|---|---|---|
| **primary holdout (gated)** | **5, 6, 7 pooled** (fits on 1–4, 1–5, 1–6) | not design-blind (§0) |
| development (reported, never gated) | 3, 4 | |
| confirmation (deferred) | 8 when final | fits on 1–7 frozen by sha256 in the results; a dated addendum, no method change |

## 3. Models

All predict `μ` = expected host-native points for an appeared player-week, as of the pre-kickoff snapshot.
`μ = max(0, ·)` in every model. Fits are ordinary least squares over the fit player-weeks.

| id | model | parameters |
|---|---|---|
| **C0 (champion)** | `rosValue` on ONE shared scale: `μ = a + b·r`, pooled over all families | 2 |
| CG | group scale: `μ = a_g + b_g·r`, g ∈ {OFF, IDP, K} | 6 |
| CF | family scale: `μ = a_f + b_f·r`, f ∈ 8 families | 16 |
| CR | family rank curve: `μ = a_f + b_f·ln k_f`, `k_f` = the player's rank by `rosValue` **within his family over the whole as-of snapshot** (1 = best) | 16 |
| F (reference) | production fallback `μ = r / 2.7` (`sim_calibration.FALLBACK_ROS_VALUE_PER_POINT`) | 0, reported only |

C0 is the champion because it preserves the live ordering exactly (a positive linear map of `rosValue`) and is the
most favourable single-scale reading of it. CR is invariant to a family-wide level step in a snapshot (a rank basis
change moves `r`, not `k_f`).

**Fallback rules (fixed now):** a family with fewer than 30 fit player-weeks, or with a fitted slope of the wrong
sign (`b ≤ 0` for CG/CF, `b ≥ 0` for CR), takes its group's CG fit; a group with fewer than 30 takes C0. Fallbacks
are reported.

**PAR (reported, never gated).** `PAR = μ − R_f`, where `R_f` is the `starter` tier of production
`league_intel.replacement.compute_replacement_levels` run over the 12 as-of rosters with `μ` substituted for
`rosValue` (the exact solver's endogenous allocation; no slot table, no flex split, no scarcity multiplier).

**Not modelled (declared):** opponent/matchup inputs (no as-of opponent feed is joined), injuries announced after the
snapshot, recency weighting, 2025 data. Spread is out of scope here (V3 owns the points-model spread); per-family
prequential residual SD is reported descriptively.

## 4. Metrics (holdout pooled over weeks 5–7)

1. **M1 accuracy:** MAE and RMSE of `μ` vs realized points, pooled and per family. Paired ΔMAE = MAE(C0) − MAE(X)
   with a 95% player-cluster percentile bootstrap (B = 2,000, seed 20261028).
2. **M2 cross-group calibration:** group ratio `R_g = Σy / Σμ` for OFF and IDP; **scale distortion
   `D = R_IDP / R_OFF`** with the same bootstrap; calibration slope (OLS of y on μ) per group; decile table.
3. **M3 ranking stability (inputs only):** for each consecutive pair of evaluated weeks, Spearman ρ of `μ` over players
   priced in both snapshots and rostered in the later week; mean over pairs (weeks 4→5, 5→6, 6→7).
4. **M4 cross-group concordance:** within each holdout week, over all (OFF player, IDP player) pairs in `P_t`, the share
   of pairs (realized ties excluded) where the order of `μ` matches the order of realized points. ΔConc vs C0 with a
   player-cluster bootstrap. Reported alongside: the same over realized mean points across weeks `h..7` for players
   with ≥ 2 appearances (ROS horizon).
5. **M5 optimal-lineup agreement:** for each holdout team-week, the exact solver (`solve_optimal_assignment`) over the
   roster's priced players valued at `μ`; agreement = |predicted starters ∩ Sleeper's awarded `starters`| / |awarded
   starters|. Mean over team-weeks, team-week bootstrap.
6. **M6 team-week ordering:** predicted team-week total = Σ `μ` over that predicted lineup. (a) all-play concordance:
   share of the 66 pairs per week where the predicted order matches the realized matchup points order; (b) mean
   per-week Spearman ρ of predicted vs realized totals. Also for the **live team-strength composite**
   (`compute_team_strength` with `rosValue`, the true live champion) and the same composite with `μ` substituted.

## 5. Gates (thresholds are labelled PRIORs, chosen now)

Minimum samples: a family is **gated** in family-level checks only with ≥ 50 holdout player-weeks (v1 `GATE_MIN_N`);
M4 needs ≥ 1,000 cross pairs; M5/M6 need ≥ 36 team-weeks. Below a floor the check reads `INSUFFICIENT` and is not a
pass.

| gate | passes when (challenger X ∈ {CG, CF, CR}) |
|---|---|
| **G1 scale coherence** | `|D_X − 1| ≤ 0.10` **and** `R_OFF`, `R_IDP` each in [0.85, 1.15] (point estimates) |
| **G2 accuracy** | pooled ΔMAE > 0 with CI lower > 0, and no gated family with ΔMAE CI upper < 0 |
| **G3 cross-group ordering** | ΔConc (X − C0) CI lower > 0 |
| **G4 stability (non-inferiority)** | mean M3 ρ(X) ≥ ρ(C0) − 0.02 |
| **G5 lineups (non-inferiority)** | M5 agreement(X) ≥ agreement(C0) − 0.01 |
| **G6 team ordering (non-inferiority)** | M6a concordance(X) ≥ concordance(C0) − 0.02 |

Champion diagnosis (reported, not a gate): `D_C0` with CI. **A scale distortion is "confirmed"** when the C0 CI of
`D` excludes 1.

**Verdict per challenger:** `PASSES_ALL_GATES` iff G1–G6 pass; else `DOES_NOT_PASS`, naming each failing gate.
**Recommendation rule:** among challengers that pass all gates, recommend the lowest pooled holdout MAE; within 0.05
points MAE of each other, the fewer-parameter model (CG < CF = CR; CF vs CR tie → CR, level-step invariant). If none
passes, no recommendation for a live change; the results say which gates failed.

## 6. Downstream shadow (reported, never gated)

On the latest snapshot (`2026-10-28T09-05-28`, the only one carrying `draftSharksRosIdp`) and the current rosters
(Sleeper week-8 matchups body), using fits on weeks 1–7 for each model:

- team-strength composite rank (live `rosValue` vs `μ` substituted), and expected best-lineup weekly points per team
  (anonymous team index);
- optimal lineups: slots whose occupant changes;
- IDP share of `rosRankOverall` top-100 (the `tags.py` "starter caliber" cut) vs IDP share of the top-100 by `μ` and by
  PAR;
- representative players (elite offense, elite IDP, rookies, deep bench): `rosValue`, `μ`, PAR per model.

Playoff-sim Brier / log loss is **INSUFFICIENT by construction**: no completed season has as-of ROS snapshots, and
V3 already measured points-model → odds sensitivity. Trade ROS-fit is reported as the change in `tags.py` inputs it
reads (`rosRankOverall` cut) and team-strength ranks (`direction.py` buyer/seller reads team strength).

## 7. What a result justifies

- **No challenger passes:** no owner request for a live change; the mismatch diagnosis (G1 champion read) still stands
  on its own evidence.
- **A challenger passes:** an owner **recommendation** (not a promotion) to consider a points-equivalent ROS read for
  cross-position consumers, only after the week-8 confirmation keeps pooled ΔMAE > 0 and `|D − 1| ≤ 0.10`. Any live
  change would go through the ROS aggregation / team-strength owners, behind a default-OFF flag, owner-approved.

## 8. Outputs

`docs/league-intelligence/evidence/ros_scale_calibration/`: `evaluation.json` (gates, metrics, fits per week),
`downstream.json`, `fits_week8_frozen.json`. All carry `promotes: false`, code SHA, script sha256, this
preregistration's commit, the card fingerprint, snapshot hashes and seeds. No manager or team name and no league id;
teams appear as anonymous indexes. Raw API bodies stay in gitignored `data/ros_calibration/cache/`.

---

*Freeze line. Anything below is a dated addendum written after results were known.*
