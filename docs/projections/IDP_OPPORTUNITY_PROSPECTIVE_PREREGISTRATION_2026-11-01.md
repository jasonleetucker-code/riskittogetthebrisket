# Weekly IDP models — PROSPECTIVE PREREGISTRATION (2026-11-01)

**Status:** preregistered BEFORE the frozen fit was run and before any Week 9 game.  This file is
committed alone, ahead of the freeze code and artifact.  Deviations go in the future results
document, never in here.

**Authority:** owner directive 2026-11-01, Priority 3: compare models on genuine pre-kickoff
forecasts.  Shadow / research only (issue #2039; owner decisions 4, 5, 7, 10).  It changes no value,
rank, source vote, flag, route, FAAB bid or streaming recommendation.  Champion ≠ challenger: a pass
here authorizes nothing.  Evidence type: `weekly_opportunity`.

**Predecessor:** the retrospective study
(`docs/projections/IDP_OPPORTUNITY_CHALLENGERS_RESULTS_2026-11-01.md`, PR #2043).  Its results were
SEEN before this was written.  That is why this study is prospective: every number that will be
judged is a forecast frozen before its games are played.

**Question:** on genuine pre-kickoff weekly forecasts for `dynasty_main` defenders, scored under
the exact league card:
1. which model has lower POINT ERROR;
2. which one makes better DECISIONS?

These are kept as two separate questions with separate endpoints.  Lower point error is never
reported as better decisions.

## 1. Models

| # | id | model | fitted? |
|---|---|---|---|
| 1 | `PROV` | **Sleeper/RotoWire production champion.**  For each player, the latest `sleeperWeeklyProjections` capture in `data/projections/weekly_archive/2026/w<W>/` (`src.ros.weekly_projection_archive`) whose `fetchedAt` is strictly before **that player's own game kickoff**.  Raw stat lines are rescored under the card.  A player with no such row is EXCLUDED from PROV comparisons and counted; he is never scored 0.  A capture at or after the kickoff is invalid (the Week 8 capture is post-kickoff, which is why Week 8 is not evaluated). | no |
| 2 | `S0` | **Properly shrunk baseline.**  Per scored key, the player's weekly mean shrunk toward his true-position group's per-game mean, with pseudo-count κ_games. | κ_games |
| 3 | `SNAP` | **Snap-weighted opportunity** (retrospective M2): per-snap rates shrunk toward the group (κ_vol for tackles, κ_splash for every other IDP key), × expected snaps (3-week share × team snaps). | κ_vol, κ_splash |
| 4 | `OPP` | **Opponent matchup:** SNAP × the family-specific opponent factor (retrospective M4).  CB: dropback and WR-target volume.  LB/S: tackle opportunity allowed to the sub-group per offensive snap.  EDGE/DT: dropbacks × sacks + QB hits allowed per dropback. | κ_opp, α |
| 5 | `ROLE` | **Role change:** SNAP with expected share = (1−γ)·3-week share + γ·last-week share, the last-week share taken from `src.ros.idp_opportunity.features.role_change`.  The retrospective injury-report replacement term is **dropped** because it hurt (M3 − M2 > 0 in every family, significant in 2025). | γ |
| 6 | `HYB` | **Full hybrid:** ROLE snaps × OPP factors.  No injury term. | κ_opp, α (on the ROLE base) |

All in-package models project a stat line first.  Points come only from
`src.league_intel.scorer.score_stat_line` under the `dynasty_main` 2026 card (fingerprint
`sf1:9e51824690d091f9`; the run refuses a different card).  A model whose input is missing for a
player falls back to `S0` for that row, and the row is counted per reason.  Points are never zero
by default.

## 2. Fitting and freezing

* Grids (as declared in the retrospective preregistration):
  * κ_vol, κ_splash ∈ {0, 25, 50, 100, 200, 400, 800, 1600};
  * κ_opp ∈ {50, 200, 800}; α ∈ {0, 0.25, 0.5, 0.75, 1};
  * κ_games ∈ {0, 0.5, 1, 2, 4, 8}; γ ∈ {0, 0.25, 0.5, 0.75, 1}.
* Selection minimizes MAE on pseudo-out-of-sample rows.
* **One fit, on 2026 weeks 2 … 8 that are final at freeze time.**  At freeze time Week 8 is in
  progress, so the fit uses weeks 2–7, and the artifact says so.
* Fit order: SNAP and OPP by the retrospective procedure (M2, then M4); then κ_games for S0; then
  γ for ROLE; then κ_opp and α for HYB on the ROLE base.
* **No refit on any evaluated week.**  Weeks 9+ only apply the frozen parameters.  Features for
  week W still read every final week < W through the `AsOfView` guard (data, not parameters).
* Frozen artifact: `docs/projections/evidence/idp_opportunity/prospective/frozen_params_2026.json`.
  It records:
  * parameters, fit weeks, fit diagnostics and grids;
  * code SHA and a clean-tree flag;
  * card fingerprint and hash;
  * every input SHA-256;
  * the resolved lineup demand.
* Written by `scripts/idp_opportunity_prospective.py freeze`.

## 3. Freeze receipts (per week)

* Before each evaluated week's first kickoff, a receipt
  `docs/projections/evidence/idp_opportunity/prospective/freeze_receipts/weekNN.json` is committed
  and pushed.  It names the frozen artifact's git blob and freeze commit, the code blobs, the card
  fingerprint, `refit: false`, and the provider-champion selection rule.  The pattern is
  `docs/league-intelligence/evidence/ros_scale_calibration/freeze_receipts/week09.json`.
* **Evidence of time is the GitHub push time** (and the PR timeline), which must precede the week's
  first kickoff.  Committer date is not proof.
* A week with no pre-kickoff receipt is NOT evaluated.  It is reported as missed.
* Where possible, the in-package predictions are also committed before kickoff
  (`predict --week W` → `predictions/weekNN.json`).  If they are not, they are regenerated
  deterministically from the frozen parameters with features from weeks < W.  That carries a
  declared limitation: stat corrections to weeks < W that land after W's kickoff would be inside
  the features.  The evaluation reports, per week, which path was used.

## 4. Evaluation weeks and population

* **Evaluation weeks:** 2026 weeks 9 onward that have a pre-kickoff receipt and are final.  Week 9's
  first kickoff is Thu 2026-11-05 ~00:15Z.
* **Interim:** each week's results may be reported as DESCRIPTIVE only.
* **Confirmatory read:** after weeks 9–14 are final (6 weeks).  No early stopping on a favourable
  interim.
* **Point-error population:** IDP-family players with a week-W stat line carrying `def_snp > 0` and
  ≥ 1 played week before W.  Each comparison is PAIRED on the rows both models cover.  PROV
  comparisons use only rows with a pre-kickoff PROV row; coverage is reported.
* **Groups:** Sleeper family DL / LB / DB, plus sub-groups CB / S / LB / EDGE / DT where
  identifiable (UNKNOWN is counted and excluded from sub-groups).

## 5. Endpoints

### 5.1 Point error (question 1)

* Per model × family: MAE, RMSE and bias (projection − realized).
* Calibration: 80% interval coverage, using frozen residual quantiles from the fit weeks.  A model
  without an interval is reported as such.
* Ranking: weekly Spearman by position family.
* **Primary point-error endpoints (confirmatory):** ΔMAE = MAE(model) − MAE(reference), paired by
  player-week and pooled.  Pooling weights each player by his number of weeks; this is stated.
  * vs `PROV`: models 2–6, in each of DL / LB / DB (15 tests);
  * vs `S0`: models 3–6, in each of DL / LB / DB (12 tests).
  * Total: 27 tests.

### 5.2 Decisions (question 2)

1. **Top-starter identification:** weekly top-N hit rate, |top-N by projection ∩ top-N by
   realized| ÷ N.  N is the CORRECT starter demand from the canonical resolver,
   `src.ros.lineup.resolve_league_slot_demand` with the live Sleeper `roster_positions` × team
   count: **DL 36, LB 36, DB 36** (DL×3, LB×3, DB×3, no IDP_FLEX; stamped in the artifact).
2. **Roster-dependent lineup improvement:** for each `dynasty_main` roster-week, the IDP starters
   are chosen from the rostered defenders by the canonical solver `src.ros.lineup` on each model's
   projections, then scored on REALIZED points.  This is compared with the realized-optimal lineup
   (the ceiling).  Because the league is best ball, the host awards the realized-optimal lineup
   anyway.  This metric therefore measures the model's ordering of a manager's own defenders, and
   is labelled as such, not as a decision the manager makes.
3. **Realized streaming decision:** per team-week, inside Worker 4's point-in-time universe:
   * candidates: `src.waivers.streaming_point_in_time.candidate_universe` and
     `decision_context_for`, at the week's first kickoff;
   * timestamps: `classify_projection_timestamp` — only `pre_kickoff` provider rows are forecasts;
   * error cells: `error_summary`.

   Each model's single best add per IDP family is its highest-projected available defender.  It
   replaces the team's lowest-projected same-family rostered defender that is droppable under owner
   decision 7 (dynasty-loss budget **zero**, the canonical release-cost owner, missing value never
   zero).  The outcome is the realized best-ball IDP lineup points with the swap minus without
   (the canonical solver on realized points).  "No move" is a valid decision and scores 0 uplift.
   Opportunity cost is reported beside it.

   *Dependency:* `src/waivers/streaming_point_in_time.py` is in PR #2045, not on `main` at
   preregistration.  The evaluation runner consumes it read-only once merged, and never forks it.

**Primary decision endpoints (confirmatory):** paired weekly Δ top-36 hit rate vs `PROV` and vs
`S0` per family (same 27 comparisons), and the paired per-team-week streaming uplift vs `PROV` and
vs `S0` (pooled over families; 9 comparisons).

## 6. Inference and acceptance

* 95% CIs by player-clustered bootstrap (top-N and streaming: week-clustered and team-week
  clustered respectively), 2,000 resamples, seed 20261101.
* Two-sided bootstrap p-values.
* **Multiplicity:** Holm–Bonferroni within each endpoint family, at α = 0.05: point error (27);
  top-N (27); streaming (9).
* A model shows **lower point error** than a reference in a family only if Holm-adjusted p < 0.05
  AND the 95% CI upper bound of ΔMAE < 0 AND |bias| is no worse than the reference's + 0.5 points.
* A model makes **better decisions** only on a decision endpoint passing the same Holm rule with
  CI lower bound > 0 (hit rate or uplift).
* Point-error wins never count toward decisions, or vice versa.
* **Null and negative results are reported.**  With 6 weeks of play the expected power is
  limited.  A non-pass is "no detectable difference", never "equal".
* Even an all-pass result is shadow evidence.  Promotion needs owner approval.

## 7. Excluded, named

* **The injury-report replacement term:** dropped.
* **Per-defender CB alignment, pressures, pass-rush snaps and 2026 offensive personnel:**
  UNAVAILABLE.
* **The IDP Show and any paid source:** not used.
* **fptrack:** its flag is off, so it is not a model here.
* **Betting lines:** available but not part of any model.
* **Week 8 as an evaluation week:** its provider capture is post-kickoff.
