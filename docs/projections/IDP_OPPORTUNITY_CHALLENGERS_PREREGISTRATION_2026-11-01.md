# Weekly IDP opportunity challengers — PREREGISTRATION (2026-11-01)

**Status:** preregistered BEFORE any evaluation was run.  Committed alone, ahead of the
harness and the results document.  Any later deviation is listed in the results document
under "Deviations from preregistration", never edited in here.

**Authority:** research / SHADOW ONLY (issue #2039 §B, §D, §F; owner record
`docs/owner/CHASE_UPSIDE_MASTER_DIRECTIVE_DECISIONS_2026-11-01.md` decisions 4, 5, 7, 10).
Nothing here changes a dynasty value, a rank, a source vote, a FAAB bid, a streaming
recommendation, a feature flag or a live route.  The package
`src/ros/idp_opportunity/` is isolated: no production module may import it, and it imports
nothing from `src/waivers/streaming*.py`, `server.py`, `src/api/data_contract.py` or the
frontend (pinned by a test).  Champion ≠ challenger: a passing result here authorizes
nothing; it is evidence for a later owner decision.

**Evidence lane:** WEEKLY (seasonal intelligence lane).  Every artifact labels its evidence
type as one of `weekly_opportunity` (this study), `rest_of_season` or `dynasty`.  Only the
first is produced here.  No dynasty or ROS quantity is read, written or derived.

**Question.**  For individual defensive players in `dynasty_main`, does an
opportunity-based weekly projection (snaps / role, injury replacement, opponent
opportunity by true-position group, regressed splash plays) predict league-card points
better than a point-in-time rolling league-scored average?  Three family challengers:

1. **CB** — alignment (wide/slot/box), snap share, opponent personnel / WR targets / pass volume;
2. **LB / S** — tackle opportunity, defensive snap share, injury / replacement role, opponent
   tackle opportunity by positional group;
3. **EDGE / DT** — pass-rush / run snaps, pressure, snap opportunity, sacks / splash regressed.

## 0. Data inventory and point-in-time policy

Only public, freely licensed or already-wired inputs.  The IDP Show and every paid source are
out of scope here (a separate track handles IDP Show permission).  No scraping of gated pages.

| signal | source | 2026 available? | point-in-time use for week W | license / notes |
|---|---|---|---|---|
| league-scored weekly stat line (target and history) | Sleeper `/v1/stats/nfl/regular/{season}/{week}` via `src.league_comparison.sleeper_stats.fetch_week_stats_response` | yes | weeks < W only as features; week W only as the scored outcome | public API; stat corrections can land up to ~1 week later (fetched today, so prior-week features carry corrections that may postdate a kickoff — declared limitation) |
| defensive snaps (`def_snp`), team defensive snaps (`tm_def_snp`) | same Sleeper payload | yes | weeks < W | same |
| team / opponent per game, offense pass attempts, sacks suffered, WR targets | nflverse `stats_player/stats_player_week_{season}.csv` | yes | weeks < W (team of last appearance before W) | nflverse CC-BY 4.0; nightly in season |
| schedule, kickoff, finals | nflverse `schedules/games.csv` | yes | week W opponent + kickoff are pre-game facts | CC-BY 4.0 |
| true position (CB / S / LB / EDGE / DT) | nflverse `players/players.csv` (`pff_position`, else `position`) + Sleeper player dump | yes (current snapshot) | static attribute; today's snapshot is a declared approximation | CC-BY 4.0; Sleeper public |
| injury report status for week W (`report_status` Out / Doubtful) | nflverse `injuries/injuries_{season}.csv` | yes | the week-W report is a pre-game document by NFL rule (final report ≥ 1 day before kickoff), BUT the file carries no publication timestamp and is not immutably archived → **PIT unverified**, labelled; used only in M3 / M5 | CC-BY 4.0 |
| QB hits per defender (pressure PROXY) | Sleeper `idp_qb_hit` | yes | weeks < W | proxy, labelled; not pressure |
| per-defender pressures / pass-rush win rate | none public | **NO** | — | PFF / NGS paid → UNAVAILABLE, not imputed |
| per-defender pass-rush vs run snaps | nflverse `pbp_participation` | **NO for 2026** (404 at preregistration; 2025 published) | — | UNAVAILABLE for 2026 |
| per-defender alignment (wide / slot / box / deep) | none public | **NO** | — | PFF paid → UNAVAILABLE |
| offensive personnel (11-personnel share) | nflverse `pbp_participation` | **NO for 2026** | — | UNAVAILABLE for 2026 |
| team-level charting (box count, pass rushers, blitzers) | nflverse `ftn_charting_{season}.csv` | yes, with lag (measured and reported by the harness from `date_pulled`) | not used in this preregistration | CC-BY-SA 4.0 (FTN) |
| green-dot / three-down designation | none public | **NO** | — | UNAVAILABLE |
| OL injuries / quality, double teams | none public at per-snap level | **NO** | — | UNAVAILABLE |
| pre-kickoff archived provider projections (Sleeper / RotoWire) | `data/projections/weekly_archive/` (`src.ros.weekly_projection_archive`) or Game Day pregame archive | checked at run time | only captures with `fetchedAt` and every provider `updated_at` before the week's first kickoff | production-box stores; if absent locally → provider champion NOT RUN (reported as 0 snapshots) |

So the CB challenger runs WITHOUT alignment and personnel (UNAVAILABLE signals are omitted,
never imputed); the EDGE / DT challenger runs WITHOUT pass-rush snaps and true pressure (QB hits
are a labelled proxy).

## 1. Target, population, groups

| item | decision |
|---|---|
| target | league-card points for player p, week W: the full Sleeper stat line scored by `src.league_intel.scorer.score_stat_line` under the **`dynasty_main` 2026 scoring card** (Sleeper league `1312006700437352448`; card fingerprint recorded by `scoring_fingerprint`). Includes TFL (`idp_tkl_loss` 4.24) and passes defended (`idp_pass_def` 5.3) |
| population | players whose Sleeper `fantasy_positions` includes DL, LB or DB, with a week-W stat row carrying `def_snp > 0` AND ≥ 1 prior played week (`def_snp > 0`) in the same season. The SAME set scores every model (conditional-on-playing accuracy; inactives are excluded identically for all models and counted) |
| family | Sleeper `position` DL / LB / DB |
| sub-group (true position) | `pff_position` ED→EDGE, DI→DT, LB→LB, CB→CB, S→S; else nflverse `position` DE→EDGE, DT/NT→DT, CB→CB, S/SS/FS/SAF→S, ILB/MLB/LB→LB, OLB→EDGE if Sleeper DL else LB; otherwise **UNKNOWN** (kept in family metrics, excluded from sub-group metrics, counted) |
| missing | a player with no prior played week has no champion → not in the population (counted). A missing feature is a named missing state, never 0: a model whose feature is missing for a row FALLS BACK to the next-simpler model for that row and the row is counted per reason |

## 2. Models (all fit on weeks < W only)

Stat line first, then rescoring: every model emits a projected stat line over the card's
scored keys, then `score_stat_line` turns it into points.

* **C0 — champion: rolling league-scored average.**  Per scored key, the expanding mean over the
  player's prior played weeks this season.  (Linear scoring ⇒ identical to the expanding mean of
  league-scored points.)
* **Provider champion (Sleeper / RotoWire)** — only on genuine pre-kickoff archived snapshots
  (section 0).  If none exist, NOT RUN.
* **M1 — matchup only.**  C0 × opponent factor: for key class c and sub-group g, the week-W
  opponent's allowed rate (Σ stat c by group g against that offense ÷ Σ group-g defensive snaps
  against it, weeks < W) over the league rate, shrunk with pseudo-count κ_opp snaps, raised to α.
* **M2 — snaps / role.**  Per key: per-snap rate shrunk toward the sub-group league per-snap rate
  with pseudo-count κ (separately κ_vol for tackles `idp_tkl_solo` / `idp_tkl_ast`, κ_splash for every
  other scored IDP key — this is the sack / splash regression) × expected snaps (mean snap share
  of the last 3 played weeks × the team's mean defensive snaps over weeks < W).  Non-IDP keys
  keep their C0 value.
* **M3 — M2 + injury / replacement.**  Expected snaps += β_g × vacated snaps, where vacated snaps
  are the week-W report Out / Doubtful teammates' recent mean snaps in the same sub-group,
  divided among the group's other recently active players.  β_g fit on weeks < W.
* **M4 — M2 + family-specific opponent opportunity.**  CB: opponent dropbacks per game × WR targets
  per game ratio (pass volume); LB / S: opponent tackle opportunity allowed to that sub-group
  per defensive snap; EDGE / DT: opponent dropbacks per game and sacks + QB hits allowed per
  dropback.  Each factor shrunk (κ_opp) and raised to α.
* **M5 — full hybrid = M2 + M3 + M4** (the designated challenger for every family).
* Source judgement (licensed analyst ranks) — NOT RUN: no licensed input.

**Fitting.**  κ_vol, κ_splash ∈ {0, 25, 50, 100, 200, 400, 800, 1600}; κ_opp ∈ {50, 200, 800};
α ∈ {0, 0.25, 0.5, 0.75, 1}; β_g by least squares through the origin.  Chosen by minimizing
MAE of pseudo-out-of-sample predictions for weeks 2 … W−1, each built only from weeks before
it.  When that fit set is empty, declared PRIORS: κ_vol 100, κ_splash 400, κ_opp 200, α 0.5,
β 0.  No other weight exists.

**Uncertainty.**  80% interval = point + the 10th / 90th percentile of the same model's
pseudo-out-of-sample residuals for the same family over weeks < W.  No interval (counted)
when fewer than 30 residuals exist.

## 3. Weeks

* **2026 primary:** expanding window over regular-season weeks whose games are ALL final when
  the run starts (nflverse `result` present for every REG game of the week), starting at week 3
  (week 1 has no history; week 2 is the first fit week).  At preregistration that is weeks 3–7;
  week 8 is in progress and excluded.
* **2025 retrospective (separately labelled):** weeks 3–17, same pipeline, 2026 card applied to
  2025 stat lines.  It is a forecasting-accuracy holdout, NOT 2025 awarded results, and is never
  pooled with 2026.

## 4. Metrics

Per family DL / LB / DB and per sub-group CB / S / LB / EDGE / DT, per season: MAE, RMSE, bias
(projection − realized), 80% interval coverage, Spearman rank correlation (computed per week,
then averaged), top-N starter hit rate (|top-N by projection ∩ top-N by realized| ÷ N per week;
N = starter demand of the live slots `DL DL IDP_FLEX LB LB LB DB DB DB` × 12 teams: DL 24,
LB 36, DB 36; sub-groups N = 12), with sample sizes (player-weeks, players, weeks).

Not measured here (deferred, named): roster-dependent lineup uplift, transaction-level realized
improvement, FAAB, churn, dynasty-loss budget (Worker 4's streaming harness owns these), and the
subgroup splits after byes / QB changes / late inactives / rookies (sample too small in 2026).

## 5. Primary endpoints and acceptance

Primary: per challenger family — CB (sub-group CB), LB / S (sub-groups LB ∪ S), EDGE / DT
(sub-groups EDGE ∪ DT) — ΔMAE = MAE(M5) − MAE(C0) over all 2026 evaluation player-weeks.
95% CI by player-clustered bootstrap (2,000 resamples, seed 20261101); the confirmatory bar is
the Bonferroni 98.33% CI over the three families.

A family challenger shows **detectable lift** only if ALL hold:
1. the upper bound of the 98.33% CI of ΔMAE is < 0;
2. |bias(M5)| ≤ |bias(C0)| + 0.5 points;
3. mean weekly Spearman(M5) ≥ Spearman(C0) (point estimate).

Otherwise: **no detectable lift** (reported with its numbers — null and negative results are
results).  Secondary (descriptive, no claim): every M1–M4 increment, RMSE, coverage, top-N, and
the 2025 retrospective.  Even a pass is shadow evidence; promotion would require owner approval
and a frozen prospective confirmation on weeks ≥ 9.

## 6. Reproducibility

Raw downloads are cached with SHA-256 recorded in the evidence JSON; the run is deterministic
(sorted iteration, seeded bootstrap).  Evidence: `docs/projections/evidence/idp_opportunity/`.
