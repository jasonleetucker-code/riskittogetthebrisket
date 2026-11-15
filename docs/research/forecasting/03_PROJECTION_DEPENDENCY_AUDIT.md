# 03. Current projection dependency audit

**Status:** read-only trace of `origin/main` at `f90604cba`, 2026-11-08. Paths are repo-relative. Flag values are the default-state entries in `src/api/feature_flags.py` (that file also has a separate lifecycle table, where LIVE means released, not on). What the production box overrides through `.env` was not inspectable.

Three concepts are kept apart throughout: **market value** (what the asset trades for), **football production** (stat lines and points), and **team-specific utility** (what the asset does for one roster).

## 1. External projections (football production, forward-looking)

| source | horizon | ingest owner | stored at | default state | consumers |
|---|---|---|---|---|---|
| RotoWire via Sleeper | Weekly | `src/ros/sleeper_weekly_projections.py` (kickoff lock `lock_baseline_at_kickoff`) | `data/projections/weekly_archive/` (gitignored, box-local); Game Day pregame archive through `src/ros/game_day_live.py::build_pregame_projection_archive` | `sleeper_weekly_projections` ON | `src/ros/game_day_estimates.py` (and through it `src/api/matchup_intel.py` and Game Day), `src/ros/weekly_league_projections.py` (and through it `src/waivers/streaming.py`), `src/model_registry/projection_scorecard.py` |
| FPTrack | Weekly | `src/ros/fptrack_weekly_projections.py` | Same archive | `fptrack_weekly_projections` OFF | `weekly_league_projections.py` as filler only: declares RotoWire ancestry, so it never votes alongside it |
| Fantasy Nerds | Weekly, IDP | `src/ros/fantasynerds_weekly_projections.py`, `src/ros/keyed_weekly_projections.py` | n/a | OFF; `UNREACHABLE` | None |
| SportsDataIO | Weekly, IDP | `src/ros/sportsdataio_weekly_projections.py`, `keyed_weekly_projections.py` | n/a | OFF | None |
| Mike Clay / ESPN | Preseason | `scripts/fetch_clay_projections.py`, `src/bdvm/clay_projections.py`, run weekly by `scripts/refresh_bdvm_projections.py` (`dynasty-bdvm-refresh` timer) | `data/bdvm/projections/` | LIVE | BDVM (`src/bdvm/projections.py`, `service.py`); `src/ros/projection_observations.py` → `src/ros/projection_ensemble.py`; `projection_scorecard.py` SEASON horizon; `src/ros/game_day_estimates.py` preseason fallback |
| The IDP Show | Preseason IDP | `scripts/fetch_idpshow_projections.py`, `src/bdvm/idpshow_projections.py`, gate `src/bdvm/idpshow_switch.py` | Shadow only by default: `data/bdvm/shadow/idpshow_projections/` | **Merge OFF** (`BDVM_IDPSHOW_MERGE_INTO_SNAPSHOT`, owner-reserved) | None by default. See finding F2 |
| DFS providers | DFS | `src/dfs/providers.py`, `src/dfs/auto/nfl.py` | n/a | **Paused product** | DFS only |
| In-house | n/a | Reserved: census key `brisketInternalModel`, status `NOT_STARTED` | n/a | n/a | n/a |

## 2. External rankings (ordinal or value evidence)

| lane | sources | owner | stored at | consumers |
|---|---|---|---|---|
| Dynasty market | 27 registry keys, `_RANKING_SOURCES` in `src/api/data_contract.py` lines 2063-3178: KTC Crowd and Trades, IDPTC, DLF family, IDP Show combined, Dynasty Nerds, FantasyCalc, Signals, OTC, Fantasy Navigator, PFK, Dynasty Daddy, FantasyPros family, Flock, Yahoo/Boone, Draft Sharks | `Dynasty Scraper.py`, `scripts/fetch_*.py` | `CSVs/site_raw/`, `exports/archive/` (history from 2026-07-14) | `_compute_unified_rankings` → `rankDerivedValue` |
| Market benchmark | KTC Market (`ktcCrowdTradesSfTep`), not a vote | `src/sources/ktc_market.py` | Contract rows | `marketGap*`, `src/trade/finder.py`, `src/bdvm/market.py` |
| ROS ranks | Six entries in `src/ros/sources/__init__.py::ROS_SOURCES` (below) | `src/ros/scrape.py`, `src/ros/parse.py`, `src/ros/aggregate.py` | `data/ros/aggregate/latest.json`, `history/` (1,366 files from 2026-04-28 when traced; box-local in some checkouts, so not re-verifiable from every tree) | `rosValue` consumers, section 5 |

**ROS registry detail** (measured from `src/ros/sources/__init__.py`):

| key | `is_ros` | `is_dynasty` | `is_projection_source` | base weight |
|---|---|---|---|---|
| `fantasyProsRosSf` | False | **True** | False | 0.85 |
| `draftSharksRosSf` | True | False | **True** | 1.25 |
| `draftSharksRosIdp` | True | False | False | 1.25 |
| `fantasyProsRosIdp` | False | **True** | False | 1.05 |
| `fantasyProsRosOverall` | True | False | False | 1.15 |
| `ffc2qbAdp` | False | False | False | 0.70 |

## 3. Realized statistics

| data | owner | upstream | consumers |
|---|---|---|---|
| Weekly stats, snaps, schedules, IDs, PBP | `src/nfl_data/nflverse_direct.py`, `ingest.py`, `cache.py` | nflverse release CSVs | `src/nfl_data/realized_points.py`, `src/bdvm/baseline.py`, `context.py`, `actuals.py`, `schedule.py`, `src/league_comparison/*`, `src/league_intel/scoring_fit.py`, `src/news/usage_signals.py`, `src/public_league/metrics.py`, `src/waivers/streaming_backtest.py` |
| Host stat lines | `src/league_comparison/sleeper_stats.py`, `src/nfl_data/sleeper_live_stats.py` | Sleeper | `projection_scorecard.py`, `src/ros_calibration/*`, `src/ros/idp_opportunity/sources.py`, Game Day |
| PBP-derived supplements | `src/nfl_data/pbp_weekly.py`, `reception_depth.py`, `first_down_rate.py`, `opportunity_stats.py` | nflverse PBP | `realized_points.py`, `reception_shape_projection.py`, `src/league_intel/reception_fit.py` |
| Durable actuals | `src/nfl_data/actuals_store.py` | Above | History |
| Exact scoring | `src/league_intel/scorer.py::score_stat_line` | League card | Everything |
| Usage windows | `src/nfl_data/usage_windows.py` | nflverse | `src/news/usage_signals.py`, BUY/SELL alerts |
| Injury state | `src/nfl_data/injury_feed.py`, `injury_identity.py`, `injury_history.py` (append-only as-known log) | ESPN | `src/ros/availability.py`, BDVM events |
| Depth, contracts | `src/nfl_data/depth_charts.py` (ESPN); `src/playerctx/fetch.py`, `asof.py` (nflverse, OTC, PFR-sourced snaps) | Mixed | Usage cross-checks; `src/bdvm/context.py` |
| Live game state | `src/nfl_data/live_game_state.py` (ESPN default); `balldontlie_live_game_state.py`, `sportsdataio_live_game_state.py` | Mixed | `src/ros/game_day_week.py` |

## 4. Market values consumed by decisions

| consumer | reads | concept |
|---|---|---|
| `src/trade/suggestions.py`, `finder.py`, `angle.py`, `src/api/trade_simulator.py` | `rankDerivedValue`; finder also reads retail markets per asset class | Market value |
| `src/waivers/advisor.py`, `src/waiver_compare/service.py`, `values.py` | Canonical plus KTC-derived | Market value |
| `src/consensus_edge/fair_value.py`, `score.py` | Market anchors plus Sharp flow | Market value |
| `src/bdvm/market.py` | Value-signal sources only, after fundamentals | Market value, compared to production |
| `src/league_intel/cross_market.py`, `values.py` | KTC, IDPTC | Market value |
| `src/draft/vendor_comparison.py`, `rookie_pool.py` | Rookie prices | Market value |
| `src/trade/market_trade_eval.py`, `src/sharp/market.py`, `scripts/fetch_crowd_faab.py` | Observed trades and bids | Market behavior |

## 5. Derived forecasts we own

| forecast | owner | inputs | consumers | state and known validation |
|---|---|---|---|---|
| Weekly league-scored points | `src/ros/weekly_league_projections.py` | Section 1 | `src/waivers/streaming.py` and its solver. The module docstring also names the Waiver Advisor; `src/waivers/advisor.py` has no direct import of it | LIVE. One family `[R]` |
| Game Day baselines and probabilities | `src/ros/game_day_estimates.py`, `game_day_week.py`, `game_day_sim.py` | RotoWire weekly, Clay fallback, `PointsModel.draw_from_mean` | `src/api/matchup_intel.py`, Game Day | LIVE on fallback CVs; calibration needs more weeks (`docs/engineering/MATH_AUDIT_2026-11-08.md`) |
| ROS full-season ensemble | `src/ros/projection_ensemble.py` | Clay, IDP Show | Best-ball utility, Universal Player Profile | LIVE. See F2 |
| `rosValue` | `src/ros/aggregate.py` | ROS ranks | `src/ros/team_strength.py`, `power_v2.py`, `direction.py`, `playoff_sim.py`, `pick_forecast_snapshot.py`, `src/roster_intel/*`, `src/draft/context.py`, `displacement.py`, `src/league_intel/replacement.py`, `sim.py`, `src/bestball/competitive.py`, `src/trade/roster_capacity.py`, `src/api/gameplan.py` | LIVE. A log-rank index, not points |
| Points model | `src/league_intel/sim_calibration.py::PointsModel` (`rosValue / 2.7`, fallback CVs) | `rosValue` or weekly points | Playoff sim, Game Day, `src/roster_intel/best_ball_utility.py`, `src/bestball/marginal.py` | LIVE on fallback; miscalibrated at team level (`TEAM_POINTS_CALIBRATION_RESULTS_2026-11-08.md`) |
| Playoff and title odds | `src/ros/playoff_sim.py`, `championship.py` | Presim, ROS multiplier, availability | Power, Pick Forecast, public odds | LIVE; D11 double count (flag OFF); archive `src/ros/forecast_archive.py` |
| Pick forecast | `src/ros/pick_forecast_snapshot.py`, `pick_projection.py` | Team strength, playoff sim | Trade, draft | Capture exists; no outcome scoring |
| BDVM fundamental value | `src/bdvm/*` | Clay, proxy baseline, actuals, schedule, priors | `/api/bdvm/*`, Fund gap column, alerts | LIVE. Local reproduction 100% proxy; no 14-day skill (`SIGNAL_SATURATION_DIAGNOSIS_2026-11-08.md`) |
| Best-ball utility | `src/roster_intel/best_ball_utility.py`, `src/bestball/marginal.py` | Projected means, solver | Trade, roster surfaces | LIVE or research per surface |
| FAAB recommendation | `src/trade/faab_engine.py` | `rankDerivedValue`, history, crowd | Waivers | LIVE; backtest in-sample |
| Trade Monte Carlo | `src/trade/monte_carlo.py` | Market values with synthetic ±15% bands | `MonteCarloButton.jsx` | Reads as a frequency only |
| League-valuation candidates | `src/league_valuation/*` | BDVM output, rosters | Shadow | Research; no candidate advanced |
| IDP opportunity challengers | `src/ros/idp_opportunity/*` | Sleeper, nflverse | Shadow | **Prospective study frozen**; do not modify |
| Scorecards | `src/model_registry/projection_scorecard.py`, `game_day_calibration.py`; timer `dynasty-forecast-calibration-ledger` | Archives | `data/learning/scorecards/` | Scheduled Tue/Wed; expect `insufficient_sample` early |

## 6. Findings

| # | finding | evidence | consequence |
|---|---|---|---|
| F1 | **The weekly "consensus" is one model family.** FPTrack cannot vote beside RotoWire; Fantasy Nerds and SportsDataIO are off | `weekly_league_projections.py` docstring; flags; `projection_scorecard.py` `championEqualsSoleConstituent` | "External consensus" as a weekly baseline does not exist yet. The real comparison today is RotoWire vs in-house |
| F2 | **The preseason ensemble is effectively single-family on both sides.** Offense: Clay only. IDP: Clay only unless the owner enables the IDP Show merge. The census still marks `idpShowProjections` LIVE | `src/ros/projection_ensemble.py:69`, `src/bdvm/idpshow_switch.py`, census | The census row overstates what reaches snapshots by default. `single_family_passthrough` must stay the label |
| F3 | **Dynasty boards feed the ROS aggregate as proxies.** `fantasyProsRosSf` and `fantasyProsRosIdp` are `is_dynasty: True`, `is_ros: False`; `ffc2qbAdp` is not ROS either | Registry above | Horizon mismatch under `docs/REDRAFT_ROS_INTELLIGENCE_SPEC.md` §6. Does not breach the dynasty-pool boundary, which runs the other direction. Should be tested and labelled |
| F4 | **`draftSharksRosSf.is_projection_source` is True while the source reads rankings** | Registry; census note | Flag names a weight tier, not evidence class. Do not treat as a projection |
| F5 | **`rosValue` drives point forecasts through a through-origin 2.7 divisor and re-enters as a multiplier** | `TEAM_POINTS_CALIBRATION_RESULTS` §1, D11 | Causes both the level bias and the over-spread |
| F6 | **No market-implied input reaches any non-paused forecast.** `spread_line` and `total_line` are read only in `src/dfs/auto/nfl.py`; census `BETTING_MARKET` lane is GREENFIELD | Grep of `src/`, `config/projections/source_capability_census.json` | Likely the cheapest unused weekly signal |
| F7 | **Rights problems on live inputs**: PFR-sourced snaps, ESPN feeds, Clay PDF | `02_DATA_SOURCE_LICENSING_MATRIX.md` §C | Owner decision before any training use |
| F8 | **PIT history is short.** Weekly provider archive: 2026 week 8+. ROS history: 2026-04-28+. Market archive: 2026-07-14+. Injury log: recent only | `RPA-COL-020` via `SITEWIDE_PROJECTIONS`; `CLAUDE.md` "Temporal history" | Historical comparison with external sources is not possible before these dates. Realized-stat baselines are possible back to 1999 |
| F9 | **Scoring parity is host-exact but the nflverse path is not**: 91.6% match, 96.2% with #1938 | `SCORING_PARITY_TAXONOMY_2026-11-08.md` | Training labels from nflverse carry known defects, mostly IDP. Prefer Sleeper lines where they exist; state the residual where they do not |
| F10 | **No forecast surface consumes a calibrated distribution** | `PointsModel` fallback; AMATH findings 1-3 | Probability surfaces are uncalibrated until marginals are measured |

**Not verified:** box-level `.env` flag overrides; contents of `data/projections/weekly_archive/` and `data/learning/`; whether the box has a calibrated `sim_points_model.json`; exact in-season weight of each ROS source after freshness steps.
