# 06. Feature inventory

**Status:** research only, 2026-11-08. A feature is listed because it is plausible, not because it works. Labels: `[R]` measured in this repo; `[X]` external informal; `[I]` inference; `none` means no evidence was found.

**Reading the columns.** *Persistence* is evidence the feature repeats. *Leakage risk* names how it can see the future. *Known at* is the earliest honest time to use it. Every feature must be registered in `config/model_registry/feature_dictionary.json` with `knownAt` and missing semantics before any model reads it. "Rights" uses `02_`: G green, A amber, A+ open license stated with an upstream question open, R red for training.

## 1. Opportunity

| feature | positions | source | persistence | leakage risk | known at | rights | note |
|---|---|---|---|---|---|---|---|
| Carry share | RB, QB | nflverse PBP | RB carries/game r 0.65 `[X]`; RB ppg wk1-6 to wk7-12 .79 `[R]` | Low | After game, nightly | A+ | Strongest candidate alongside targets |
| Target share, targets per game | RB, WR, TE | PBP | RB targets/game r 0.70 `[X]` | Low | After game | A+ | Direct target-share stability not found in the search |
| Air-yards share, aDOT | WR, TE | PBP | none measured here | Low | After game | A+ | Test as a target-quality proxy |
| Routes, route participation | WR, TE | nflverse participation | none | **High in-season: 2023+ posts after playoffs** | Offseason only | A (SA) | Training only; need a live proxy |
| Snap share (offense) | All | nflverse snaps | none measured here | Low | Every 6 h post-game | **R** via PFR | Rights block; see `02_` finding 1 |
| Snap share (defense) | IDP | Sleeper `def_snp`, `tm_def_snp` | Strong in IDP study (M2 lift `[R]`) | Low | Same day | A | Used by `src/ros/idp_opportunity/` |
| Tackle-pool share | LB, S | PBP tacklers | LB persistence .59 `[R]` | Low; scorer quirks | After game | A+ | Assist/solo split has known parity issues |
| Pass-rush snaps, pressures | EDGE, DT | None public in-season `[R]` | n/a | n/a | Unavailable | n/a | QB hits are the labelled proxy `[R]` |
| Targets faced | CB, S | PFR advanced | none | Low | Weekly | **R** | Rights block; no clean live source |
| Red-zone and goal-line share | RB, WR, TE | PBP, `src/nfl_data/opportunity_stats.py` | none | Low | After game | A+ | TD regression candidate |
| Role state (starter, rotation, injury fill) | All | Derived | Injury-replacement term **harmful** on IDP `[R]` | Medium | After game | A | Test against EWMA and last-week share |
| Depth chart slot | All | ESPN or nflverse | none | **High**: timing | Varies | R (ESPN), A (nflverse) | Depth updates can follow news |

## 2. Efficiency

| feature | positions | persistence | leakage | note |
|---|---|---|---|---|
| Yards per carry | RB | r about 0.16, slope 0.28 `[X]` | Low | **Mostly noise.** Shrink hard or drop |
| Rushing yards over expected | RB | Contested; Lopez cited as finding some stability `[X]` | NGS after game | Needs ablation vs `shrink(YPC)` |
| Yards per route, TPRR | WR, TE | none here | Routes unavailable in-season | Candidate after a proxy exists |
| Catch rate over expected | WR, TE | none here | Low | Likely low signal `[I]` |
| Reception-band shape | RB, WR, TE | **Year-over-year r 0.72-0.77**, beats position mean by 44-53% of SSE `[R]` (`reception_shape_projection.py`) | Low | Rare example of a stable efficiency trait; league-specific value |
| First downs per yard | RB, WR, TE, QB | Nearly deterministic from yards `[R]` (`first_down_rate.py`) | Low | Measurement, not forecasting |
| CPOE, EPA per play | QB | none here | Low | Likely useful for QB, test against ypa |
| Turnover rate | QB | none here | Low | Shrink hard |
| TD rate per opportunity | RB, WR, TE | none measured here | Low | Regress toward xTD |
| Sack rate | QB | none here | Low | Partly team |
| Pressure-to-sack conversion | EDGE | none | Low | Noisy; rights-blocked data |
| Solo share of tackles | LB, S | Scorer-sensitive `[R]` (`SCORING_PARITY_TAXONOMY`) | Low | Stadium effect mentioned by PFF, unverified |
| Interception rate | DB | none here | Low | Treat as near-random at player level `[I]` |
| Kicker FG make skill | K | Holdouts noisy `[R]` | Low | Shrink very hard |

**Honest note on efficiency.** Across the evidence found, volume repeats and most per-play rates do not, with reception-band shape as a useful exception. Any model giving efficiency terms large weight should be assumed overfit until shown otherwise.

## 3. Team and coaching

| feature | persistence | leakage | note |
|---|---|---|---|
| Spread, game total, implied points | n/a; market-based | **High if the line postdates the cutoff** | Vegas features dominate one published model `[X]`. nflverse line timing unverified |
| Neutral pass rate, PROE | none measured here | Low | Team-level; pre-season coach changes break it |
| Pace, plays per game | none measured here | Low | Partly game script |
| Coaching or play-caller change | none | Low (date-known) | Binary change flag; sample thin; team-level shrink |
| Offensive line quality | none public | n/a | Paid data only |
| Starting QB identity | High face validity `[I]` | **High**: late news | Needs as-known starter record |
| Vacated targets, carries | none measured here | Low in offseason | Rookie landing spot input |

## 4. Opponent and environment

| feature | persistence | leakage | note |
|---|---|---|---|
| Opponent pass funnel, fantasy points allowed | **Near zero added on IDP** `[R]`: M4 adds −0.02 to −0.03 | Low | Likely noise after team totals, per `[I]`. External studies did not settle this |
| Opponent tackle opportunity | Same as above | Low | Same |
| Wind | Consistent direction, informal `[X]`: thresholds 15-20 mph | Forecast timing | Test as a threshold only |
| Temperature, precipitation | Mixed `[X]` | Low | Probably not worth a term |
| Roof, surface | Known | None | Low cost, low expected value |
| Home/away, travel, rest | Team level | None | Mostly already in the spread |
| Stadium stat-crew effect | Hypothesis (PFF mentions it) | Low | Check on tackle splits only |
| Prime time, division | none | None | Reject |

**Honest note on matchups.** The repo's measured opponent effect on IDP is close to zero once snaps and shrinkage are present. Team totals probably capture the offensive side. Opponent features should earn their way back through ablation.

## 5. Career context

| feature | persistence | leakage | note |
|---|---|---|---|
| Age, age by position | Curves, survivorship-biased `[X]` | None | Use a spline with survivorship correction |
| Draft capital | Mixed vendor evidence `[X]` | None post-draft | PFR-sourced in nflverse; `players.csv` carries `draft_pick` too (`src/bdvm/context.py`); confirm upstream |
| Years in league, rookie flag | Structural | None | Rookies need a separate model |
| Prior production, shrunk | Strong for RB/WR `[R]` | Low | The hard baseline |
| Games missed history | none found | Low | Include only with a measured hazard gain |
| Injury designation, practice status | Dated studies `[X]` | **High**: revised, untimestamped historic file `[R]` | Use `injury_history.py` forward |
| Contract, guarantees | none here | Date-known | Survival feature; OTC via nflverse |
| College production, breakout age | Vendor evidence, small sample `[X]` | None | CFBD; rights-clean |
| Combine, athleticism | Little beyond RB sprints `[L]` | None | PFR-sourced; rights-blocked until resolved |
| Career workload | Used in BDVM `[R]` | None | Test as a hazard term only |

## 6. Market-derived, separately named

These measure what others believe. They are admissible for near-term forecasting, not as evidence of independence, and never enter canonical value.

| feature | leakage | rule |
|---|---|---|
| Rookie price, ADP | Low if dated | Dated capture through `src/history/asof.py`; used as a baseline |
| Game and prop lines | High without cutoff | Capture only |
| Canonical value at a date | Date-pinned | Baseline for the production forecast, kept separate. The board orders near-term output well: Spearman with realized lineup contribution QB .69, RB .66, WR .69, TE .64, DL .30, LB .55, DB .33 `[R]` (`G_ACCURACY.md`) |

## 7. Publication lags (minimum to enforce)

| data | lag | source |
|---|---|---|
| Sleeper weekly stats | Hours; corrections up to about a week | `IDP_OPPORTUNITY_CHALLENGERS_RESULTS` |
| nflverse PBP and stats | Nightly; cleanest Thursday | nflverse schedule |
| nflverse snaps | 6-hourly after PFR post | nflverse schedule |
| FTN charting | From about 2 days to 47.5 days, measured `[R]` | `IDP_OPPORTUNITY_CHALLENGERS_RESULTS` |
| Participation 2023+ | After the postseason | nflverse schedule |
| Injury designations | Pre-game by rule; historic file not timestamped | `[R]` |
| Weekly projections | Must predate that player's kickoff | `lock_baseline_at_kickoff` |

## 8. Sources

External items are listed with URLs in `01_METHODOLOGY_SURVEY.md` §5 and `02_DATA_SOURCE_LICENSING_MATRIX.md` §D. Additional weather reading, informal (retrieved 2026-11-08): https://www.sharpfootballanalysis.com/sportsbook/weather-impact-on-nfl-betting/amp/ ; https://wsb.wharton.upenn.edu/wp-content/uploads/2022/09/2022_Football_Parks_Weather.pdf ; https://scholarship.claremont.edu/cmc_theses/830 . Injury designations: https://www.teamrankings.com/blog/nfl/nfl-injury-analysis-how-often-do-hurt-players-actually-play-1-of-4 ; https://africa.espn.com/blog/nflnation/post/_/id/215133/how-to-decode-the-nfls-new-injury-report-designations .
