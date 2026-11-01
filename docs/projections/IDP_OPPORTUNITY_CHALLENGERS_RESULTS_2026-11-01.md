# Weekly IDP opportunity challengers — RESULTS (2026-11-01)

**Status:** SHADOW research evidence for issue #2039 §B / §D.  Nothing is promoted, wired or
flagged.  No dynasty value, rank, source vote, FAAB bid or streaming recommendation changed.
Evidence type: `weekly_opportunity` only.

* Preregistration (committed first, `e8f140e36`):
  `docs/projections/IDP_OPPORTUNITY_CHALLENGERS_PREREGISTRATION_2026-11-01.md`
* Harness: `src/ros/idp_opportunity/` + `scripts/idp_opportunity_backtest.py`
* Evidence: `docs/projections/evidence/idp_opportunity/backtest_2026-11-01.json` (input SHA-256s,
  per-week fitted parameters, fallback counts, every metric below)
* Provenance: evidence produced at code `1f3f2864e63e780dd33b9bc04daafdd43d6345ad` on a clean
  tree (`codeSha` / `codeDirty: false` in the JSON), with SHA-256 for every input. That covers the
  scoring card (`card.settingsSha256`), the nflverse players and games files, the Sleeper player
  dump, each season's nflverse files (`availability`), and every Sleeper weekly stat and team file
  (`sleeperStats.hashes`, `sleeperTeamStats.hashes`). That SHA includes the decision-path coercion
  fix (missing snaps, dropbacks, WR targets and league rates stay `None` instead of `or 0.0`). Re-running
  at `978c6521b` (provenance stamp only) and again at `1f3f2864e` (coercion fix) reproduced every
  metric, fitted parameter and diagnostic of the original run identically. No reported number changed;
  no real input in this run was missing, so the explicit missing paths never fired.
* Card: `dynasty_main` 2026, fingerprint `sf1:9e51824690d091f9` (TFL 4.24, PD 5.3, solo 1.33,
  assist 0.8, sack 2.92, QB hit 2.12, …), scored only by `src.league_intel.scorer.score_stat_line`.

## Headline

1. **All three family challengers pass the preregistered 2026 acceptance bar** against the
   rolling league-scored average (C0): ΔMAE CB −0.50, LB/S −0.44, EDGE/DT −0.36 points per
   player-week, every Bonferroni 98.33% CI below zero, bias not worse, rank correlation not lower.
   The 2025 retrospective (separately labelled, never pooled) points the same way at roughly half
   the size (−0.23 / −0.23 / −0.14).
2. **The lift is NOT the opportunity-specific signals.**  Almost all of it comes from M2
   (snap-weighted per-snap rates shrunk toward the true-position group rate — i.e. regressing
   splash plays and small samples).  The post-hoc increments over M2 are ≈ 0: opponent opportunity
   (M4) adds −0.02 to −0.03 (CIs touch or barely exclude 0), the injury-replacement term (M3) is
   slightly HARMFUL (+0.02 to +0.05; significantly harmful in 2025 for EDGE/DT and CB), and
   matchup-only (M1) is indistinguishable from C0.  The designated full hybrid M5 is therefore
   no better than M2.
3. **C0 is a weak champion** (an unshrunk expanding mean).  A large share of M2's gain is the
   generic benefit of shrinkage; a shrunk-mean champion was not preregistered and was not run.
   Treat "beats C0" as "beats the naive rolling average", not as proof that opportunity modelling
   beats a competent baseline.
4. **Zero genuine pre-kickoff archived provider snapshots** were available locally (the
   `data/projections/weekly_archive/` store and the Game Day pregame archive live on the
   production box only), so no Sleeper/RotoWire champion was run.

## Data availability (step 0)

| signal | available for 2026? | point-in-time lag / status | used |
|---|---|---|---|
| Sleeper weekly stat lines (target, history, `def_snp`, `tm_def_snp`, QB hits) | yes, weeks 1–7 final (week 8 in progress) | same-day; stat corrections up to ~1 week (fetched today) | yes |
| Sleeper team / opponent per player-week (`api.sleeper.app/stats/nfl/…`) | yes | same-day | yes (team of last played week; opponent from schedule) |
| nflverse `stats_player_week` (offense dropbacks, WR targets) | yes | nightly | yes |
| nflverse schedule (`games.csv`) | yes | pre-season | yes (opponent, finality, kickoff) |
| nflverse players (`pff_position`) + season roster crosswalk (`sleeper_id`↔`gsis_id`, `depth_chart_position`) | yes | current snapshot | yes (true position) |
| nflverse injury report (`report_status`) | yes | pre-game by NFL rule; file NOT timestamped → **PIT unverified** | M3 / M5 only |
| nflverse `pbp_participation` (per-defender snaps by play, offensive personnel) | **no** (404 for 2026; 2025 published) | — | UNAVAILABLE |
| per-defender alignment (wide / slot / box / deep) | **no public source** | — | UNAVAILABLE (CB challenger runs without it) |
| per-defender pressures / pass-rush snaps / win rate | **no public source** | — | UNAVAILABLE (QB hits used as a labelled proxy) |
| offensive 11-personnel share | **no** for 2026 | — | UNAVAILABLE |
| green-dot / three-down role; OL quality; double teams | **no public source** | — | UNAVAILABLE |
| FTN charting (team-level box count, pass rushers, blitzers) | yes, with lag | measured from `date_pulled`: week 1 47.5 d, weeks 2–5 14–30 d, weeks 6–7 ≈ 2 d after the week's last game | not used |
| pre-kickoff archived Sleeper/RotoWire projections | **0 captures** found locally | — | provider champion NOT RUN |
| The IDP Show / any paid source | out of scope (separate permission track) | — | not used |

## Primary endpoint (2026, weeks 3–7, preregistered)

ΔMAE = MAE(M5) − MAE(C0), player-clustered bootstrap, 2,000 resamples, seed 20261101.
Every ΔMAE and MAE in this document is POOLED over player-weeks, so each player counts in
proportion to the number of evaluation weeks he played. Every-week starters weigh more than
part-timers. The bootstrap resamples players (clusters), so the CIs account for that
within-player correlation, but the point estimates are not per-player averages.

| challenger | player-weeks | players | ΔMAE | 95% CI | 98.33% CI | bias not worse | Spearman not lower | verdict |
|---|---|---|---|---|---|---|---|---|
| CB | 488 | 134 | −0.497 | [−0.768, −0.226] | [−0.838, −0.181] | yes | yes | detectable lift |
| LB / S | 878 | 250 | −0.440 | [−0.682, −0.214] | [−0.729, −0.165] | yes | yes | detectable lift |
| EDGE / DT | 1,196 | 297 | −0.362 | [−0.518, −0.202] | [−0.554, −0.172] | yes | yes | detectable lift |

### Every model, by challenger family (2026)

MAE / RMSE / bias in league-card points; coverage = share inside the 80% interval; Spearman and
top-N hit are weekly means (N = 12 per sub-group in the family).

| family | model | MAE | RMSE | bias | cov80 | Spearman | top-N hit | ΔMAE vs C0 [95% CI] |
|---|---|---|---|---|---|---|---|---|
| CB | C0 | 6.32 | 8.44 | −0.25 | 0.82 | 0.24 | 0.22 | — |
| CB | M1 matchup | 6.31 | 8.43 | −0.29 | 0.83 | 0.25 | 0.22 | −0.015 [−0.051, 0.019] |
| CB | M2 snaps/role | 5.83 | 7.96 | −0.42 | 0.77 | 0.26 | 0.08 | −0.490 [−0.765, −0.218] |
| CB | M3 +injury | 5.85 | 7.90 | −0.05 | 0.77 | 0.29 | 0.17 | −0.470 [−0.750, −0.192] |
| CB | M4 +pass volume | 5.81 | 7.93 | −0.44 | 0.77 | 0.27 | 0.17 | −0.514 [−0.773, −0.261] |
| CB | M5 hybrid | 5.82 | 7.86 | −0.08 | 0.78 | 0.29 | 0.22 | −0.497 [−0.768, −0.226] |
| LB/S | C0 | 5.62 | 7.99 | −0.66 | 0.85 | 0.50 | 0.25 | — |
| LB/S | M1 | 5.59 | 7.96 | −0.71 | 0.85 | 0.51 | 0.26 | −0.033 [−0.075, 0.007] |
| LB/S | M2 | 5.16 | 7.26 | −0.58 | 0.81 | 0.54 | 0.24 | −0.457 [−0.679, −0.257] |
| LB/S | M3 | 5.21 | 7.23 | −0.22 | 0.80 | 0.55 | 0.24 | −0.407 [−0.637, −0.190] |
| LB/S | M4 +tackle opp. | 5.13 | 7.23 | −0.59 | 0.80 | 0.55 | 0.25 | −0.485 [−0.705, −0.281] |
| LB/S | M5 | 5.18 | 7.21 | −0.24 | 0.80 | 0.56 | 0.27 | −0.440 [−0.682, −0.214] |
| EDGE/DT | C0 | 5.12 | 7.21 | −0.01 | 0.82 | 0.35 | 0.28 | — |
| EDGE/DT | M1 | 5.13 | 7.23 | −0.05 | 0.82 | 0.35 | 0.28 | 0.001 [−0.021, 0.022] |
| EDGE/DT | M2 | 4.75 | 6.47 | −0.02 | 0.80 | 0.42 | 0.35 | −0.376 [−0.530, −0.223] |
| EDGE/DT | M3 | 4.78 | 6.48 | 0.08 | 0.79 | 0.42 | 0.33 | −0.344 [−0.497, −0.188] |
| EDGE/DT | M4 +dropbacks×pressure | 4.73 | 6.46 | −0.04 | 0.79 | 0.42 | 0.33 | −0.394 [−0.549, −0.239] |
| EDGE/DT | M5 | 4.76 | 6.47 | 0.07 | 0.79 | 0.42 | 0.33 | −0.362 [−0.518, −0.202] |

Post-hoc increments over M2 (descriptive, NOT preregistered; ΔMAE [95% CI]):

| family | M3 − M2 (injury) | M4 − M2 (opponent) | M5 − M2 |
|---|---|---|---|
| CB 2026 | +0.021 [−0.090, 0.123] | −0.023 [−0.081, 0.035] | −0.007 [−0.131, 0.113] |
| LB/S 2026 | +0.051 [−0.024, 0.132] | −0.028 [−0.058, 0.001] | +0.018 [−0.061, 0.102] |
| EDGE/DT 2026 | +0.033 [0.009, 0.056] | −0.018 [−0.035, −0.002] | +0.014 [−0.013, 0.038] |
| CB 2025 | +0.028 [0.006, 0.049] | +0.002 [−0.018, 0.022] | +0.028 [0.003, 0.054] |
| LB/S 2025 | +0.034 [0.000, 0.071] | +0.003 [−0.007, 0.013] | +0.037 [0.002, 0.074] |
| EDGE/DT 2025 | +0.020 [0.010, 0.030] | −0.026 [−0.035, −0.018] | −0.006 [−0.020, 0.008] |

### By Sleeper family (2026)

| family | model | n | players | MAE | RMSE | bias | cov80 | Spearman | top-N hit (N) |
|---|---|---|---|---|---|---|---|---|---|
| DL | C0 | 1,124 | 285 | 4.79 | 6.73 | −0.23 | 0.83 | 0.35 | 0.30 (24) |
| DL | M2 | 1,124 | 285 | 4.47 | 6.16 | −0.14 | 0.81 | 0.43 | 0.38 |
| DL | M5 | 1,124 | 285 | 4.48 | 6.17 | −0.06 | 0.80 | 0.43 | 0.35 |
| LB | C0 | 615 | 165 | 5.98 | 8.52 | −0.08 | 0.82 | 0.48 | 0.46 (36) |
| LB | M2 | 615 | 165 | 5.47 | 7.50 | −0.21 | 0.78 | 0.54 | 0.48 |
| LB | M5 | 615 | 165 | 5.52 | 7.48 | 0.10 | 0.76 | 0.56 | 0.49 |
| DB | C0 | 988 | 279 | 5.91 | 8.06 | −0.48 | 0.84 | 0.32 | 0.28 (36) |
| DB | M2 | 988 | 279 | 5.43 | 7.52 | −0.56 | 0.80 | 0.36 | 0.26 |
| DB | M5 | 988 | 279 | 5.41 | 7.43 | −0.26 | 0.80 | 0.38 | 0.29 |

Sub-group tables (CB / S / LB / EDGE / DT, every model) and every 2025 table are in the evidence
JSON.  2025 retrospective, 2026 card applied to 2025 stat lines (weeks 3–17; not awarded results):
DL C0 4.72 → M5 4.60, LB 5.41 → 5.18, DB 5.30 → 5.07 MAE.

## What failed, or is weak

* **Opportunity-specific signals did not earn their place.**  The CB alignment / personnel
  signals were UNAVAILABLE; the pass-volume proxy that replaced them adds nothing measurable.
  The LB/S opponent tackle-opportunity factor and the EDGE/DT dropback × pressure factor add a few
  hundredths of a point.  The injury-replacement term hurts (the PIT-unverified injury report and
  the equal-split allocation of vacated snaps are both crude).  Matchup-only (M1) ≈ nothing.
* **Intervals are slightly narrow:** 80% intervals cover 0.76–0.81 for the M2–M5 family, and
  EDGE 0.70 (2026); C0 over-covers (0.82–0.85) because its residuals are wider.
* **Top-N hit rate does not improve consistently** (CB M2 0.08 vs C0 0.22 in 2026; the
  shrinkage compresses the top of a 12-player cut).  Lower average error is not the same as
  better start/sit ranking at the top.
* **EDGE over-projection persists** (bias +0.65 C0, +0.75 M5 on EDGE; within the +0.5 tolerance
  only because the bar compares with C0's own bias).

## Small-sample and validity limits

* 2026 is five evaluation weeks (3–7); 134 CB, 250 LB/S, 297 EDGE/DT players.  Fitted parameters
  move week to week (e.g. CB β 1.87 → 0.56; κ_vol 800 → 1600 → 400).
* Conditional-on-playing accuracy: rows require `def_snp > 0` in the target week (identical
  for every model).  Inactive / late-scratch risk is not measured here.
* Prior-week stat lines and Sleeper team rows were fetched today, so stat corrections that landed
  after a later kickoff are inside the features (small, declared).  Sleeper and nflverse position
  snapshots are current, not as-of.
* No pre-kickoff provider archive ⇒ no comparison with the one existing weekly provider family.
* Not measured (deferred, named): roster-dependent lineup uplift, transaction-level realized
  improvement, FAAB, churn, dynasty-loss budget (Worker 4's streaming harness owns these),
  sub-group errors after byes / QB changes / late inactives / rookies.

## Deviations from preregistration

1. **Identity join repaired before the reported run.**  A first development run joined Sleeper
   ids to nflverse only through Sleeper's own `gsis_id`, which is missing for most active
   defenders (428 of 543 who played week 7): 75% of rows were sub-group UNKNOWN and team-unknown.
   Fixed by (a) the nflverse season roster's published `sleeper_id`↔`gsis_id` crosswalk and its
   `depth_chart_position` (then Sleeper `position`) as further sub-group fallbacks, and (b) team /
   opponent per player-week from Sleeper's team-bearing stats endpoint instead of nflverse player
   rows; team codes normalized by `src.playerctx.normalize.normalize_team_code` (LA → LAR).  The
   preregistered sub-group rules, models, grids, weeks, metrics and acceptance bar were NOT changed.
   Disclosure on timing: the preregistration was committed (`e8f140e36`) BEFORE any code ran. The
   broken-join development run happened AFTER that commit, as did the repaired-join run that
   preceded the reported one. Both runs' 2026 numbers were seen before the final run. Nothing
   tunable (grids, weeks, metrics, acceptance bar, model definitions) changed between them; only
   the identity / team joins were repaired.
2. **CB pass-volume factor** = geometric mean of the dropback and WR-target ratios (the
   preregistration wrote "×"; the two are correlated, so a plain product would count pass volume
   twice).  Per-game and per-dropback shrinkage uses κ_opp converted from snaps by the league's own
   snaps-per-game and dropbacks-per-game (PIT).
3. **M5 fit order:** κ_vol / κ_splash from the M2 fit, β from the M3 fit, then κ_opp / α refit on
   M5.  LB/S M4 applies the tackle-opportunity factor to tackle keys only; EDGE/DT to sack, sack
   yards and QB-hit keys only.
4. **Post-hoc** M3/M4/M5-vs-M2 bootstraps were added after the primary results were seen; they are
   descriptive and claim nothing.

## Reconciliation with the IDP Show library audit (PR #2042)

Inputs from `docs/sources/IDP_SHOW_LIBRARY_AUDIT_2026-11-01.md` (branch
`claude/idp-show-library-audit`), handled as follows.  No IDP Show data was read here.

* **Tackle efficiency ("TKL EFF Allowed").**  Already rebuilt point-in-time: the LB/S M4 factor is
  tackles (solo + assist) allowed to one true-position sub-group ÷ the offense's offensive snaps
  faced (the defending team's `tm_def_snp` in those games), weeks < W only, shrunk toward the league
  rate.  It is the same quantity, computed from our own data.  Measured value as a factor on top of
  snaps / role: −0.028 [−0.058, 0.001] (2026), +0.003 [−0.007, 0.013] (2025) — no detectable gain.
* **True-position mapping vs PFF.**  Our sub-group uses nflverse `pff_position` first (PFF-derived,
  like theirs), then the nflverse roster `depth_chart_position` / `position` and Sleeper `position`.
  Over the Sleeper IDP universe the PFF label decided 2,173 players; on 380 the other owners
  disagree, mostly PFF ED vs roster OLB/LB (218, the off-ball vs edge question), DI vs DE (95) and
  S vs CB (41).  Counts per pair are in `identityCensus.disagreeByPair` of the evidence JSON.
  Players Sleeper lists as LB but PFF calls ED are scored in the EDGE sub-group here.
* **Pressure proxy.**  QB hits per pass-rush snap is NOT rebuildable for 2026: per-defender
  pass-rush snaps need `pbp_participation`, which returned 404 for 2026 at run time (2025 exists).
  The proxy used is QB hits per defensive snap.
* **Offensive personnel.**  Same 2026 participation gap → UNAVAILABLE for 2026 (contrary to the
  audit's "rebuildable" note, which holds for 2025 only).  **Betting lines** (`spread_line`,
  `total_line` in nflverse `games.csv`) are available but were not preregistered and were not used.
* **CB alignment, grades, pressures** — UNAVAILABLE (PFF charting), as declared.
* **IDP Show 2025 weekly projections** — not used (paid, permission unverified).  **Big 3
  thresholds** — never reused; every number here is rescored under our card.
* **Role-change detection** (the audit's highest-value hypothesis for the +19.9 vs +0.4 gap).
  Offered as a clean, point-in-time feature for Worker 4:
  `src.ros.idp_opportunity.features.role_change(view, sleeper_id)` → `RoleChange(state, last_week,
  last_share, baseline_share, delta, baseline_weeks)`, reading only weeks < W through the
  `AsOfView` guard and never the week-W injury report; `state` is `ok` / `single_week` /
  `no_history` (missing is never 0).  The isolation test allows exactly one research importer of
  it (`src/waivers/streaming_backtest.py`).  **It was NOT evaluated** in this preregistered study.
  Note what this study does say: M2 already uses a 3-week mean snap share and wins, while the
  injury-report replacement term (M3) hurts — so a role-change signal should be tested as a
  separately preregistered variant (e.g. last-week share vs 3-week mean), not assumed.

## Recommended next action

Do not promote anything.  If this line is pursued: preregister a **shrunk-mean champion** (C0 with
the same group-rate shrinkage, no snaps) and an M2-only challenger, freeze both, and confirm
prospectively on weeks ≥ 9 with pre-kickoff captures (the production-box archive) and the
Sleeper/RotoWire provider as a second champion.  Drop or redesign the injury-replacement term
before retesting.  Revisit CB alignment / pass-rush / personnel only if a licensed per-defender
source or a 2026 participation release appears.
