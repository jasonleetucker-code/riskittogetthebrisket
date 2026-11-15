# IDP streaming: why +19.9 vs +0.4? Gap decomposition and projection census (2026-11-01)

**Status:** research / shadow diagnostics only. Nothing here changes a value, a ranking, a
FAAB recommendation, a flag, an ensemble weight or a route. The default dynasty-loss budget
stays 0 (owner decision 7, 2026-11-01). Every ablation below is a counterfactual measurement,
**never a recommendation**. Rows marked HINDSIGHT use week-*w* realized points; they bound
what a perfect forecast could explain and nothing more.

- **Benchmark:** [`IDP_STREAMING_BACKTEST_RESULTS_2026-10-29.md`](IDP_STREAMING_BACKTEST_RESULTS_2026-10-29.md)
  (manager B 2026 actual − hold **+19.9** pts / decision week; baseline 7 strict dynasty-safe
  optimizer **+0.4**).
- **Code:** `src/waivers/streaming_gap_attribution.py` (ablations + actual-move profile),
  `src/waivers/streaming_point_in_time.py` (point-in-time candidate universe, timestamp
  classification, projection error rows), `scripts/research_weekly_idp_projection_census.py`.
  Nothing live imports any of them (pinned by `tests/waivers/test_streaming_backtest.py`).
- **Evidence (anonymous):** [`evidence/idp_streaming/gap_attribution_2026-11-01.json`](evidence/idp_streaming/gap_attribution_2026-11-01.json),
  [`evidence/idp_streaming/projection_census_2026-11-01.json`](evidence/idp_streaming/projection_census_2026-11-01.json).
- **Issue:** #2039 §D (see §6 traceability).
- **Agent-OS-Receipt:** `47a8b19fff9d06da9b1a651aab5fb92f1e16d5f6`

## 1. Answer

**The gap is a forecasting gap, not a constraint gap.** On the same frozen input (2026 weeks
1–7, decision weeks 2–7, the same candidate universe and hold reference, manager B selected by
the reproducible "heaviest defender streamer" rule: 51 defender adds against a league mean of
16.7):

* Relaxing any single guard of the strict optimizer moves it from +0.40 to at most **+2.78**
  pts / week. These guards are dynasty protection, unpriced players, injured or inactive
  release, roster capacity, swap cap, materiality, the multi-week horizon, and the masked
  waiver pool. Relaxing every point-in-time guard at once gives **+3.71**. That closes about
  17% of the 19.5-point gap.
* Feeding the **unchanged** optimizer the week's realized points instead of the projection
  (HINDSIGHT bound) gives **+52.7** under every guard, including budget 0. Nothing is relaxed in
  that run. The guards are therefore not what holds it back: with the right ranking of free
  agents, it beats manager B by 33 points a week without releasing any dynasty value it is not
  allowed to.
* The constraint on the optimizer is the **projection**. The provider (Sleeper / RotoWire)
  projects only 56–62% of the defender-weeks that score, under-projects every IDP group (bias −1.1
  to −1.6), and compresses the range (DL calibration slope 0.72). So almost no free agent
  *projects* above the 9th-best projected defender on a 27-deep roster, even when he out-scores
  him.
* Point-in-time alternatives do not rescue it. Recent realized production as the forecast gives
  **−3.9**. Every preregistered simple rule loses or shows no detectable effect on the same input
  (−2.6 to −9.2).

**League level reads differently** (all 12 teams, 72 team-weeks, cluster bootstrap):

* Roster capacity +5 gains **+4.2 [+2.1, +6.8]** a team-week. Everything else that is
  point-in-time gains **+5.6 [+3.7, +7.8]**, which is above the league's own actual behavior
  (+4.6 [+0.7, +8.6]).
* Shallower rosters gain from free defender adds where manager B's 27-deep roster does not.
* This is an upper bound on capacity's value, not a policy. The relaxation charges nothing for
  the offensive player a real add-without-drop would release; baseline 1b of 2026-10-29 found
  manager B's such releases cost 0, but that is not shown for other teams.
* 43 of the 72 combined decisions were search-bounded.

Manager B's +19.9 therefore rests on information the available weekly projection does not
carry: role, injury and depth-chart news, snap shares and similar opportunity signals. It is
consistent with that reading, but with n = 6 weeks luck cannot be separated from skill (§5). This
is the gap the #2039 §B opportunity challengers target (Worker 5, `src/ros/idp_opportunity/`).
This document does not claim they close it.

## 2. Same input, every model (manager B, 2026, Δ vs hold per decision week)

| model / ablation | what changes vs baseline 7 | manager B Δ (95% CI) | verdict | B adds | B actual − this (paired) | league Δ / team-week (12 team-seasons) | search |
|---|---|---|---|---|---|---|---|
| 1 no move (hold) | reference | 0 | — | 0 | +19.9 [+10.1, +30.2] | 0 | — |
| **actual behavior** | manager B as played | **+19.9 [+10.1, +30.2]** | gains | 37 visible | — | +4.6 [+0.7, +8.6] | — |
| 2 previous-week points | simple rule | −8.8 [−21.8, +2.2] | no detectable effect | — | — | -1.6 [-5.8, +2.6] (no detectable effect) | — |
| 3 rolling production | simple rule | −2.6 [−16.9, +7.5] | no detectable effect | — | — | +3.1 [-1.6, +7.8] (no detectable effect) | — |
| 4 single projection | simple rule | −3.3 [−13.3, +7.0] | no detectable effect | — | — | -3.6 [-8.2, +0.8] (no detectable effect) | — |
| 6 lowest dynasty value | simple rule | −9.2 [−18.8, +0.4] | no detectable effect | — | — | -3.1 [-8.7, +2.9] (no detectable effect) | — |
| **7 base** (masked, S = 3, budget 0, materiality 1) | — | **+0.40 [0.0, +1.2]** | no detectable effect | 1 | +19.5 | +0.9 [-1.9, +4.2] (no detectable effect; 0.64 adds/tw; 0/72 bounded) | 6/6 optimal |
| conservative | S = 1, materiality 3 | +0.40 [0.0, +1.2] | no detectable effect | 1 | +19.5 | -0.6 [-1.9, +0.7] (no detectable effect; 0.24 adds/tw; 0/72 bounded) | 6/6 optimal |
| pool unmasked (availability / FAAB) | another team's week-*w* claims offered | +2.78 [−0.7, +8.7] | no detectable effect | 3 (contested: FAAB unknown) | +17.1 | +0.9 [-1.3, +3.4] (no detectable effect; 0.76 adds/tw; 3/72 bounded) | 6/6 optimal |
| dynasty protection off (what budget > 0 buys) | priced defenders above the line releasable free | +0.40 | no detectable effect | 1 | +19.5 | -0.9 [-3.0, +1.1] (no detectable effect; 0.72 adds/tw; 32/72 bounded) | 3 optimal, **3 bounded** |
| unpriced releasable (diagnostic) | unknown-value defenders releasable | +0.40 | no detectable effect | 1 | +19.5 | +1.4 [-0.8, +4.2] (no detectable effect; 0.74 adds/tw; 4/72 bounded) | 6/6 optimal |
| injury replacement | unprojected / ≤ 0 projected defenders releasable | +0.40 | no detectable effect | 1 | +19.5 | +0.6 [-2.2, +3.9] (no detectable effect; 0.67 adds/tw; 3/72 bounded) | 6/6 optimal |
| roster capacity +5 (surplus bench depth) | 5 adds a week without a release | +0.40 | no detectable effect | 1 (pure add) | +19.5 | +4.2 [+2.1, +6.8] (gains; 0.62 adds/tw; 0/72 bounded) | 6/6 optimal |
| search: 6 swaps | S = 6 | +0.40 | no detectable effect | 1 | +19.5 | +0.5 [-2.0, +3.0] (no detectable effect; 0.62 adds/tw; 41/72 bounded) | 4 optimal, **2 bounded** |
| materiality 0 (bench / replacement threshold) | any positive projected gain | +1.01 [0.0, +2.2] | no detectable effect | 2 | +18.9 | +1.5 [-1.5, +4.6] (no detectable effect; 0.85 adds/tw; 0/72 bounded) | 6/6 optimal |
| 3-week horizon | plans on w..w+2 projections | +1.01 [0.0, +2.2] | no detectable effect | 2 | +18.9 | +2.0 [-2.3, +7.4] (no detectable effect; 0.85 adds/tw; 28/72 bounded) | 1 optimal, **5 bounded** |
| rolling-production forecast (point-in-time) | forecast = recent realized average | −3.88 [−12.0, +4.0] | no detectable effect | 10 | +23.8 | +0.8 [-3.0, +4.7] (no detectable effect; 1.83 adds/tw; 0/72 bounded) | 6/6 optimal |
| **all point-in-time relaxations** | all of the above except the forecast | **+3.71 [+0.3, +9.1]** | gains | 4 (pure adds) | +16.2 | +5.6 [+3.7, +7.8] (gains; 0.97 adds/tw; 43/72 bounded) | 2 optimal, **4 bounded** |
| HINDSIGHT: realized-points forecast | forecast = week-*w* realized points; every guard ON | **+52.7 [+39.1, +66.3]** | (bound) | 11 | −32.8 | not run (cost) | 6/6 optimal |
| HINDSIGHT: all relaxations + realized forecast | — | +108.2 [+92.0, +125.7] | (bound) | 36 (30 pure) | −88.3 | not run (cost) | 6/6 optimal |

"Bounded" means the 100,000-solve work limit stopped the search. The plan found was applied and
counted, but it is never presented as optimal; the base cell keeps the solver default and
reproduces the 2026-10-29 cell exactly. One-at-a-time rows do not add up: the interaction
residual is all point-in-time (+3.31 over base) minus the sum of its single rows (pool +2.39,
materiality +0.62, the rest 0: +3.00), about +0.3. The HINDSIGHT rows are upper bounds that use information unavailable at the cutoff. They
are not policies, and no number in this table is a recommendation.

Dynasty-value flow (IDP Trade Calculator vendor value, NOT canonical) for manager B:

| run | released | acquired |
|---|---|---|
| base | 951 | nothing valued |
| realized-forecast bound | 13,213 (11 priced releases) | 1,235 (10 of 11 adds unvalued) |

A perfect forecast would still spend dynasty value at the replacement line. Every release in that
run was at or below the line it was charged against.

## 3. What manager B actually did, against the optimizer's inputs at the same cutoff

Point-in-time profile of his 37 matchup-visible in-season defender adds and 29 releases
(2026, weeks 2–7):

| adds | share | releases | share |
|---|---|---|---|
| in the masked pool | 34 / 37 (92%) | priced (value known before the cutoff) | 17 / 29 (59%) |
| in the masked pool **and** projected | 32 / 37 (86%) | **unpriced** | 12 / 29 (41%) |
| priced | 21 / 37 (57%) | droppable under rule 7 (priced, at or below the line) | 13 / 29 (45%) |
| made the optimal lineup that week | 10 / 37 (27%) | priced **above** the line (protected) | 4 / 29 (14%) |
| paid claims | 0 | not projected, or projected ≤ 0 (out / inactive) | 10 / 29 (34%) |
| realized points that week (mean) | 9.6 | realized points that week (mean) | 4.4 |

Reading, by #2039 §D factor:

* **Candidate eligibility / availability:** not the gap. 86% of his adds were in the optimizer's
  own candidate set (masked pool, projected), and unmasking the pool adds only +2.4.
* **Guards (dynasty protection, unpriced, injury):** 41% of his releases are players the rule
  will never release (unpriced) and 14% are protected. Yet relaxing those guards changes nothing
  under the projection. The guards would matter only once the forecast identified the better
  player (in the realized-forecast bound the guards were on and still allowed +52.7).
* **Real injuries:** a third of his releases were out or unprojected. The hold baseline keeps
  4.3 non-playing defenders a week vs his 3.3 (2026-10-29). Injury replacement is part of his
  edge, but the projected lineup already ignores unprojected players, so the optimizer gains
  nothing from releasing them unless a free agent also *projects* above a starter.
* **Surplus bench depth:** a 27-defender hold roster for about 9 IDP slots means a free agent
  must project above the 9th-best projected defender. Extra capacity (+5) adds nothing, for the
  same forecasting reason.
* **Search exhaustion:** base 6/6 optimal. The relaxed runs hit the work limit on up to 5 of 6
  decisions, and the realized-forecast bound shows bounded search is not what stops the gain.
* **Planning horizon:** +0.6 over base (equal to materiality 0); future-week projections share
  the same weakness.
* **FAAB:** no paid claims (0 of 37). The unmasked pool's contested adds would have needed
  winning claims of unknown cost (never $0).


## 4. Weekly IDP projection source census (C2)

**Point-in-time lineage first.** Every projection row available locally was fetched AFTER its
week's first kickoff:

| season | provider rows classified | pre-kickoff | post-kickoff | unstamped | immutable W1 archive captures (`data/projections/weekly_archive/`) |
|---|---|---|---|---|---|
| 2026 (weeks 1–7) | 4,315 (Sleeper / RotoWire) | **0** | 4,315 | 0 | **none locally** (archive lives on the production box) |
| 2025 (weeks 1–13) | 7,915 (Sleeper / RotoWire) | **0** | 7,915 | 0 | none (the archive did not exist in 2025) |
| 2026 FPTrack (weeks 1–7) | one fetch per week, today | **0** | 7 of 7 fetches | — | none |

So **every error below is a post-kickoff (hindsight-exposed) error, not a historical forecast
error**, and no figure here may be quoted as forecast accuracy. The genuine pre-kickoff count
per week has to be read on the box:
`python -c "from src.waivers.streaming_point_in_time import archive_snapshot_audit; ..."` with
the season's cutoffs (the function returns pre / post / unstamped captures per week and source).
The 2026-10-29 MAE figures (DL 4.47 / LB 4.84 / DB 4.65) split by that classification are
therefore: **pre-kickoff n = 0 (not measurable here); post-kickoff = the whole figure.**

### 4.1 Sleeper / RotoWire (the live family) by group, league-card points, played player-weeks

| season | group | n | MAE | RMSE | bias (proj − real) | coverage of played player-weeks | calibration slope (real on proj) | late inactives (proj > 0, no stat line) |
|---|---|---|---|---|---|---|---|---|
| 2026 | DL | 1,575 | 4.47 | 6.55 | −1.09 | 57.9% | 0.72 | 19 |
| 2026 | LB | 1,096 | 4.84 | 7.31 | −1.35 | 61.9% | 1.11 | 8 |
| 2026 | DB | 1,609 | 4.65 | 7.01 | −1.57 | 55.8% | 0.89 | 8 |
| 2025* | DL | 2,822 | 4.74 | 7.03 | −1.07 | 60.5% | 0.82 | 14 |
| 2025* | LB | 2,044 | 4.75 | 6.85 | −0.49 | 62.5% | 0.93 | 2 |
| 2025* | DB | 3,021 | 4.34 | 6.21 | −0.51 | 54.6% | 0.82 | 12 |

\*2025 is shown separately and never pooled with 2026: 2025 lineups were manager-set (the
backtest scores optimal-lineup POTENTIAL points there).

Calibration (2026 quintiles, mean projected → mean realized): DL 0.7→3.3, 1.8→4.0, 4.1→4.9,
6.3→5.9, 10.2→10.5 (low projections are far too low: the provider does not project paid keys
such as `idp_def_td`, blocked kicks and special-teams tackles, reported per player as
`uncovered_scoring_keys`); LB 1.3→3.1, 2.5→2.4, 5.9→7.3, 9.1→10.7, 12.3→14.4 (high projections too
low, slope 1.11); DB 0.9→2.3, 2.7→4.9, 5.9→7.9, 8.0→9.7, 10.3→10.8. Coverage: only 56–62% of the
defender-weeks that recorded a stat line had a projection at all.

### 4.2 Subgroups (#2039 §D; 2026, post-kickoff rows)

| group | after a bye (n, MAE, bias) | not after a bye | rookie (`years_exp` 0) | veteran | first appearance (new starter proxy) | returning | late inactive (host scores 0) |
|---|---|---|---|---|---|---|---|
| DL | 26, 4.69, −1.93 | 1,390, 4.43, −1.20 | 204, 3.31, −0.77 | 1,371, 4.65, −1.14 | 181, 4.54, −0.03 | 1,394, 4.46, −1.23 | 19, error 2.50 |
| LB | 14, 3.74, −0.48 | 970, 4.70, −1.28 | 147, 4.95, −2.17 | 949, 4.82, −1.22 | 120, **6.01**, −1.63 | 976, 4.70, −1.31 | 8, error 3.61 |
| DB | 24, 4.35, +0.05 | 1,405, 4.64, −1.71 | 214, 4.72, −2.03 | 1,395, 4.64, −1.50 | 195, 4.60, −0.67 | 1,414, 4.66, −1.70 | 8, error 3.68 |

Reading: LBs in their first appearance of the season are the worst-forecast cell (MAE 6.0); rookie
LBs and DBs are the most under-projected (bias about −2.1); after-bye samples are too small to
read (14–26). **Not computed:** opposing-QB changes (the cached inputs carry no per-game starting
QB table) and true late inactives by report time (only "projected, then no stat line" is
observable). Bye and rookie flags use today's player dump (team / `years_exp`), so a mid-season
trade makes "after a bye" approximate.

### 4.3 FPTrack (coverage filler, RotoWire constituent) — incremental accuracy, 2026 weeks 1–7

FPTrack's public catalog still serves weeks 1–7 (fetched today, one GET per week, flag forced on
in-process only; identity through the exact-rung resolver over the cached Sleeper directory).

| group | FPTrack alone (n, MAE, bias) | overlap with RotoWire: FPTrack / RotoWire / mean of both MAE | error correlation | fill-in where RotoWire is silent (n, MAE, bias) |
|---|---|---|---|---|
| DL | 1,459, 4.48, −2.78 | 4.56 / 4.74 / 4.57 (n 1,375) | 0.95 | 84, 3.16, −1.00 |
| LB | 1,077, 5.03, −2.35 | 5.16 / 4.97 / 5.02 (n 1,008) | 0.97 | 69, 3.03, +0.60 |
| DB | 1,598, 4.94, −1.09 | 5.00 / 4.87 / 4.84 (n 1,432) | 0.95 | 166, 4.42, −0.13 |

Reading: errors correlate 0.95–0.97 with RotoWire's (the shared-lineage finding of the
2026-10-29 census, now measured on outcomes), so averaging the two buys almost nothing (≤ 0.17
MAE) and must not be counted as a second vote. Its real increment is **coverage**: 69–166 played
player-weeks per group that RotoWire did not project, at MAE 3.0–4.4. FPTrack's TFL field is a
zero placeholder, which is part of its larger negative bias. These are post-kickoff fetches; the
ensemble weights are unchanged.

Other sources: unchanged from the 2026-10-29 census (paid, keyed without a key, points-only, or
blocked); no other weekly IDP stat-line source is reachable for an accuracy measurement here.

## 5. Limitations

* n = 6 decision weeks for manager B. The percentile bootstrap under-covers at this size and
  ignores serial correlation (see the 2026-10-29 §5). The league column is the more robust read.
* Projections are post-kickoff revisions (§4). That bias favors the projection-driven runs, and
  they still show nothing.
* The dynasty value is the IDP Trade Calculator vendor value. The canonical history lane is
  production-only.
* 2025 is not used here: its lineups were manager-set (potential points), and its dynasty
  values pre-date the 2026-07-14 history floor.
* The HINDSIGHT rows answer "how much is the forecast worth", not "what should be done".
* Opposing-QB changes and true late-inactive timing could not be measured from the cached
  inputs.

## 6. #2039 traceability

| #2039 section | requirement | where / finding | status |
|---|---|---|---|
| §A source inventory / legality / freshness | weekly projection sources: access, freshness, ancestry | §4 here (no new access path; FPTrack lineage measured on outcomes: error correlation 0.95–0.97 with RotoWire). IDP Show products: [`docs/sources/OUTLIER_V2_AND_IDPSHOW_COMPARISON_2026-11-01.md`](../sources/OUTLIER_V2_AND_IDPSHOW_COMPARISON_2026-11-01.md) §IDP Show and vendor clocks | partial. The per-product IDP Show inventory (tackles-allowed, snap shares, CB / DL series) is not done here and needs the coordinator / Worker 5. No paid gate touched |
| §B weekly opportunity features | CB / LB-S / EDGE-DT shadow challengers | not here (Worker 5, `src/ros/idp_opportunity/`). This doc supplies the target (§1: the forecast is the binding constraint) and the point-in-time helpers below | handed off |
| §C dynasty / ROS separation | keep the combined-board hold and the DLF hold; no double vote | source-comparison doc: HOLD the IDP-only switch and gate it on V2; DLF IDP held (D5). Here the dynasty value used is the named IDPTC vendor value, never presented as canonical | held, as required |
| §D accuracy / counterfactual | +19.9 vs +0.4 on the same input and candidate universe, with no-move and conservative scenarios | §1–§3 (13 ablations + 4 simple models + no-move + conservative, same frozen input) | DONE for manager B. League column §2 |
| §D timestamps | classify each snapshot pre / post kickoff; count W1-archive pre-kickoff snapshots per week; re-state MAE by class | §4: 0 pre-kickoff rows of 4,315 (2026) and 7,915 (2025); no W1 archive locally. `archive_snapshot_audit()` must run on the box. MAE re-stated: pre-kickoff n = 0, post-kickoff = the whole figure | DONE locally; box count UNRESOLVED |
| §D subgroups | after bye, QB changes, late inactives, rookies / new starters; no 2025/2026 pooling | §4.2 (after bye, rookie, first appearance, late inactive per group). QB change not computable from cached inputs. 2025 is separate everywhere | partial (QB change) |
| §D metrics | MAE, RMSE, bias, calibration, rank, top-9 hit, lineup uplift, transaction outcomes, FAAB, churn, dynasty loss | MAE / RMSE / bias / calibration slope + quintiles / coverage (§4); lineup uplift, adds, dynasty-value flow, FAAB state (§2–§3). Rank correlation and top-9 hit rate not computed | partial |
| §E UI | Waiver Advisor / weekly IDP page | not in scope (evidence first) | not started |
| §F gates | no production change, flags / votes / budget unchanged, no Sleeper writes, no duplicate owner | no flag, weight, vote or default changed. Budget default 0 pinned (`tests/waivers/test_streaming_owner_scenarios.py`). The new modules are research-only and import-guarded. They reuse the backtest's leakage boundary (one owner) | held |

### Point-in-time interface for the §B shadow challengers

`src/waivers/streaming_point_in_time.py` (research only; nothing live imports it):

* `candidate_universe(data, roster_id, week, idp_roster, masked=True)`: the defenders a team
  could add at week *w*'s cutoff. Same pool as the backtest.
* `decision_context_for(data, roster_id, week, idp_roster, ...)`: the full point-in-time
  `DecisionContext`, built through `streaming_backtest.build_decision_context`, the one leakage
  boundary.
* `classify_projection_timestamp(stamp, cutoff)`: `pre_kickoff` / `post_kickoff` / `unstamped`.
  Only `pre_kickoff` may be read as a forecast.
* `archive_snapshot_audit(season, weeks, cutoffs, base_dir=None)`: W1 archive captures per week
  and source, split pre / post kickoff.
* `projection_error_rows(data, players_dump)` + `error_summary(errors)`: per defender-week
  projected vs realized, with did-not-play kept separate from 0, and subgroup flags.

