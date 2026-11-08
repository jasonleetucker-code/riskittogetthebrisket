# 09. Feature integration map

**Status:** proposal, 2026-11-08. No surface changes here. **DFS and League Tycoon stay paused and are out of scope.** `docs/EXECUTION_PLAN.md` currently bars frontend changes under the backend directive, so any UI step below is future work requiring authorization.

**Concept column:** MV market value, FP football production, TU team utility. Surfaces that combine them show each by name.

**Cost:** S under one week, M one to three weeks, L more than three weeks, for one worker after prerequisites. **Feasibility** reflects today's data, not eventual potential.

| # | surface | current owner | current forecast input | concept | what a validated forecast would change | prerequisites | cost | feasibility | public/private |
|---|---|---|---|---|---|---|---|---|---|
| 1 | Dynasty rankings | `src/api/data_contract.py::_compute_unified_rankings`; `frontend/app/rankings` | None. Market only | MV | **Nothing in the value or rank.** At most a separately named production column, in the pattern of `Fund gap` | Production forecast passes gates | S | High for a column | Private column |
| 2 | Trade evaluation | `src/trade/analyze_service.py`, `src/trade/team_verdicts.py` | MV; posture from `src/roster_intel/window.py` | MV, TU | Named near-term production beside market fairness; never changes the fairness band | Team-level calibration | M | Medium | Private |
| 3 | Trade recommendations | `src/trade/suggestions.py`, `finder.py`, `angle.py` | MV; needs from Team Weakness | MV, TU | Need detection uses calibrated starter projections | Item 2 | M | Medium | Private |
| 4 | Waiver Advisor | `src/waivers/advisor.py`; `frontend/app/waiver-advisor` | MV, FAAB engine | TU | Rank by exceedance vs the team's marginal starter; distinct from MV | Dispersion study | M | Medium | Private |
| 5 | IDP Streaming | `src/waivers/streaming.py`, `streaming_solver.py` | `weekly_league_projections` (one family) | FP, TU | Coverage of unprojected defenders; exceedance ranking | Frozen study outcome; shrinkage plus exceedance | M | **High value**, bounded by frozen study | Private |
| 6 | Roster construction | `src/roster_intel/construction.py`, `core.py`; `frontend/app/roster-construction` | `rosValue`, MV | TU | Calibrated starter-slot production and depth | Marginals | M | Medium | Private |
| 7 | Draft intelligence | `src/draft/*`, `src/draft/context.py`; `frontend/app/draft` | MV, rookie ladder, `rosValue` | MV, TU | Replacement measured from projections, not rank | Rookie and replacement work | M | Low to medium | Private |
| 8 | Rookies | `src/draft/rookie_pool.py`, `src/bdvm/baseline.py`; `frontend/app/idptc-rookies` | Draft-slot priors | FP, MV | Calibrated hit probability by capital and college evidence, named beside market price | CFBD key; rights | L | Medium | Private |
| 9 | Breakout | **No dedicated owner** (`src/bdvm/engine.py`, `src/analyst/stance.py` mention the concept) | n/a | FP | New signal from role-change and age curves | Product authorization; role model | L | Low | Private |
| 10 | Decline | `src/bdvm/survival.py` (priors); `src/consensus_edge/*` | Priors | FP | Fitted hazard and age curve | Career study | L | Low to medium | Private |
| 11 | Start/sit | `src/ros/lineup.py`, `src/api/matchup_intel.py` | Weekly projections | FP, TU | Better rank and uncertainty. **Only relevant to managed leagues (`dynasty_new`); `dynasty_main` is best ball** | Point and dispersion gates | M | Medium | Private |
| 12 | Best-ball optimization | `src/bestball/*`, `src/roster_intel/best_ball_utility.py` | `PointsModel`, projection means | TU | Calibrated marginals change marginal utility and depth value | Points-model study outcome | M | Medium | Private |
| 13 | Superflex | `src/ros/lineup.py`, `src/league_intel/replacement.py` | Measured starter demand | TU | QB availability and backup value in best ball | Availability model | S to M | Medium | Private |
| 14 | TE and IDP scarcity | `src/league_intel/te_premium.py`, `replacement.py`, `src/league_valuation/*` | Market, replacement estimates | MV, TU | Replacement estimated from projected usable depth. TE demand must read the card: `dynasty_main` pays no TE premium | Replacement study | M | Medium | Private |
| 15 | Player comparisons | `frontend/app/players/compare`, `src/waiver_compare/*` | MV | MV, FP | Side-by-side production range, labelled | Calibrated intervals | S | Medium | Private |
| 16 | Team outlook | `src/roster_intel/window.py`, `team_equity.py`, `src/api/gameplan.py` | `rosValue`, posture | TU | Separate named current-season strength and long-horizon asset strength | Team calibration | M | Medium | Private; public wording separately governed |
| 17 | Playoff planning | `src/ros/playoff_sim.py`, `championship.py`, `src/public_league/playoff_odds.py` | `rosValue / 2.7`, ROS multiplier | TU | Calibrated team distributions | **Team-points v2 study**, not this program | M | Medium | Mixed; owner public-odds rules apply |
| 18 | Game Day | `src/ros/game_day_week.py`, `game_day_sim.py`, `game_day_live.py` | Weekly projections, fallback CVs | FP, TU | Measured dispersion; shared game factor; calibrated wording | Scorecards | M | **High** | Private |
| 19 | Market disagreement | `src/consensus_edge/*`, `/bdvm` Fund gap, `src/trade/finder.py` | MV, BDVM | MV vs FP | Better FP side; correct the scale problem first. Directional claims need evidence | BDVM diagnosis follow-ups | M | Low: no skill shown yet | Private |
| 20 | Role trends | `src/nfl_data/usage_windows.py`, `src/news/usage_signals.py`, `src/nfl_data/depth_charts.py` | Observed usage | FP | Calibrated role-change signal | BOCPD vs EWMA study | S to M | Medium | Private |

## Sequencing

| wave | surfaces | why |
|---|---|---|
| 1. Measurement first | 18, 5, 4 | Scorecards and dispersion studies can improve trust without changing any served value |
| 2. Calibrated team layer | 12, 17, 11, 13, 6, 16 | Depend on marginals and team calibration |
| 3. Trade context | 2, 3, 14, 15 | Depend on team layer; keep MV primary |
| 4. Long horizon | 8, 10, 9, 7, 19 | Need multi-season evidence |
| Never by forecast | 1 (value and rank) | Prohibited |

Paused products: DFS and League Tycoon. No backlog item may reactivate them.
