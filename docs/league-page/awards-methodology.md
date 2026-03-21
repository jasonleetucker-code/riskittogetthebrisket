# Awards Methodology (League Page)

## Scope
Define rigorous, formula-first award methodology for the public League Page using:
- actual league scoring
- actual league lineup requirements
- canonical league model entities
- data quality gates from the historical gap audit

## Current league context (repo-grounded)
Source: `data/dynasty_data_2026-03-12.json` + `data/custom_scoring_config.json`.

- League size: `12` teams (`leagueSettings.num_teams=12`)
- Best-ball mode: `enabled` (`leagueSettings.best_ball=1`)
- Playoff start setting: `week 15` (`leagueSettings.playoff_week_start=15`)
- Starting lineup slots:
  - `QB x1`
  - `RB x2`
  - `WR x3`
  - `TE x1`
  - `FLEX x2` (RB/WR/TE)
  - `SUPER_FLEX x1` (QB/RB/WR/TE)
  - `K x1`
  - `DL x2`
  - `LB x2`
  - `DB x2`
  - `IDP_FLEX x2` (DL/LB/DB)
- Scoring profile is custom and non-standard:
  - pass TD = `6.0`
  - pass INT = `-4.0`
  - pass completion/incompletion scoring active
  - first-down bonuses active
  - IDP scoring active and material (`idp_sack=3.04`, `idp_int=5.54`, etc.)

Awards must use this scoring profile and must not use private valuation internals.

## Required data entities for official computed awards
- `seasons`
- `weekly_player_scores`
- `roster_history` (week-level ownership)
- `matchups` (to define regular season vs playoffs and playoff context)
- `awards` (output table + formula metadata)
- `draft_results` (required for Best Value Pick)

## Data reality check (today)
- Formula framework is design-ready.
- Official historical computed awards are blocked now because:
  - week-level `roster_history` is missing historically,
  - full historical `weekly_player_scores` in league context are incomplete,
  - matchup/season boundary history is incomplete.

---

## Player awards catalog

| Award | Primary score | Eligibility | Required data | Minimum quality gate | Phase |
| --- | --- | --- | --- | --- | --- |
| MVP | `regular_season_vorp` | QB/RB/WR/TE/DL/LB/DB, min 8 games | weekly scores + ownership + season boundaries | full regular-season week coverage and ownership attribution >= 99.5% | Phase 3 official |
| Playoff MVP | `playoff_vorp` | players with playoff-week games, min 1 playoff game | weekly scores + ownership + playoff week flags | complete playoff week capture and franchise ownership attribution >= 99.5% | Phase 3 official |
| Rookie of the Year | `regular_season_vorp` | rookie-eligible players (season-start rookie flag), min 6 games | weekly scores + ownership + rookie flag | rookie flag mapping >= 99%, season coverage >= 99.5% | Phase 3 official |
| Best Weekly Performance | `max_weekly_vorp_raw` | same position universe as MVP, single-week event | weekly scores + replacement table | week coverage for award season = 100% | Phase 2/3 |
| Most Consistent Player | `consistency_score` | min 10 games, positive mean VORP raw | weekly scores + replacement table | no missing eligible weeks for candidate games | Phase 3 |
| Biggest Breakout | `breakout_score` | non-rookies with prior baseline sample | multi-season weekly scores + ownership | prior-season coverage for lookback >= 95% | Phase 3 |
| Best Value Pick | `value_pick_score` | players with known rookie draft pick metadata | draft results + multi-season VORP + pick expectation curve | draft-results coverage >= 90% for season and expectation baseline coverage >= 3 classes | Phase 3 |
| Best IDP Season | `idp_regular_season_vorp` | DL/LB/DB only, min 8 games | weekly scores + ownership + IDP position mapping | IDP position mapping >= 99%, ownership attribution >= 99.5% | Phase 3 official |

---

## Replacement level framework

### Objective
Set position-specific weekly replacement points using actual league demand implied by lineup slots and league size.

### Official method (required for official award publication)
1. Build weekly franchise player pools from `roster_history` joined to `weekly_player_scores`.
2. For each franchise-week, run a best-ball lineup optimizer using the league’s real slot rules.
3. Count selected starters by position across all franchises:
   - `effective_starter_slots[position, week]`
4. For each `position, week`, rank scored players at that position by weekly fantasy points.
5. Set replacement points:
   - `replacement_points[position, week] = points at rank effective_starter_slots[position, week]`
6. Persist replacement table with formula version + source refs.

This method captures FLEX/SUPER_FLEX/IDP_FLEX pressure from real weekly usage instead of assumptions.

### Fallback method (provisional only, not official)
- If full weekly ownership is missing, do not publish official awards.
- Optional internal preview mode can use structural demand from slot counts, but outputs must be labeled `provisional` and non-official.

### Structural demand implied by current lineup (for sanity checks)
Fixed weekly base demand across 12 teams:
- QB 12, RB 24, WR 36, TE 12, K 12, DL 24, LB 24, DB 24
- Plus FLEX/SUPER_FLEX/IDP_FLEX allocations resolved by optimizer each week

---

## VORP calculation framework

### Weekly VORP
For player `i`, position `p`, week `w`:
- `weekly_vorp_raw(i,w) = weekly_points(i,w) - replacement_points(p,w)`
- `weekly_vorp(i,w) = max(0, weekly_vorp_raw(i,w))`

`weekly_vorp_raw` is used for single-week dominance/consistency math.  
`weekly_vorp` is used for cumulative contribution awards.

### Seasonal VORP
- `regular_season_vorp(i,s) = sum(weekly_vorp(i,w)) for regular-season weeks in season s`
- `playoff_vorp(i,s) = sum(weekly_vorp(i,w)) for playoff weeks in season s`

### Franchise attribution for player awards
Player is the award winner entity.  
Franchise attribution for display:
- `franchise_of_record = franchise with max cumulative weekly_vorp_raw for that player in award scope`

### Award-specific formulas
- MVP:
  - `score = regular_season_vorp`
- Playoff MVP:
  - `score = playoff_vorp`
- Rookie of the Year:
  - `score = regular_season_vorp` among rookies
- Best Weekly Performance:
  - `score = max(weekly_vorp_raw)`
- Most Consistent Player:
  - `consistency_score = median(weekly_vorp_raw) - stdev(weekly_vorp_raw)` over eligible weeks
- Biggest Breakout:
  - `breakout_score = regular_season_vorp(current_season) - max(regular_season_vorp(prior_2_seasons_best), 0)`
- Best Value Pick:
  - `value_pick_score = realized_vorp_window - expected_vorp_for_pick_slot`
  - default realized window: rookie season regular-season VORP; expand to 2-year window when history matures
- Best IDP Season:
  - `idp_regular_season_vorp` with eligible positions `DL/LB/DB`

---

## Tie-breakers and edge cases

### Global tie-breaker order
1. Higher primary award score.
2. Higher total raw fantasy points in award scope.
3. More above-replacement weeks (`weekly_vorp_raw > 0`).
4. Higher best single-week `weekly_vorp_raw`.
5. If still tied, declare co-winners.

### Award-specific tie-break adjustments
- Playoff MVP:
  - tie-break #2 uses championship-week `weekly_vorp_raw` before total playoff points.
- Best Weekly Performance:
  - tie-break after `weekly_vorp_raw` is raw weekly points.
- Best Value Pick:
  - tie-break after `value_pick_score` is later draft slot (later pick wins), then higher realized VORP.

### Edge case handling
- Traded player mid-season:
  - player remains one candidate; franchise attribution uses `franchise_of_record`.
- Bye weeks / non-games:
  - excluded from game-count denominators; not treated as zero.
- Position changes:
  - weekly position from scoring record governs weekly replacement bucket.
- Kicker handling:
  - K excluded from listed player awards unless a separate kicker award is added.
- Incomplete playoff data:
  - Playoff MVP not published as official.

---

## Data quality gates (official publication)
Official computed player awards require all of the following:

1. Scoring profile lock:
- season scoring map snapshot pinned with `scoring_version`.

2. Week coverage:
- all regular-season weeks and playoff weeks present for the award scope.

3. Ownership attribution:
- `roster_history` completeness for eligible player-week rows >= `99.5%`.

4. Entity mapping integrity:
- player ID and position mapping completeness >= `99%`.

5. Reproducibility:
- saved run metadata:
  - `run_id`
  - `formula_version`
  - `inputs_snapshot_refs`
  - `generated_at_utc`
  - `quality_gate_status`

6. Commissioner publication control:
- first official publish of each award season requires commissioner sign-off.

---

## Manager and culture awards methodology recommendations

### Methodology type by category
- Formula-based:
  - use for objective activity/performance awards when data coverage is complete.
- Commissioner-selected:
  - use for narrative/context awards in low-data periods.
- League-voted:
  - use for culture/personality awards.
- Mixed:
  - use for major awards where objective shortlist + human judgment is desired.

### Recommended manager/culture award set
| Award | Method type | Why | Phase |
| --- | --- | --- | --- |
| Commissioner’s Award | commissioner-selected | narrative leadership/culture recognition with minimal data dependency | Phase 1 |
| Story of the Year | league-voted | engagement-first, supported by media archive | Phase 1 |
| Trade of the Year | mixed | shortlist from `trades/trade_assets`, final commissioner or league vote | Phase 1 (window-labeled) |
| Most Active Trader | formula-based | objective from trade counts (must label rolling window if not full history) | Phase 1 (rolling) |
| GM of the Year | mixed | requires objective season outcomes + optional vote | Phase 3 |
| Most Improved Franchise | formula-based | requires multi-season standings/score history | Phase 3 |
| Rivalry of the Year | league-voted + data-assisted shortlist | needs matchup history for strong shortlist | Phase 2/3 |

---

## Phase 1 recommendation
- Publish:
  - full methodology and quality-gate policy
  - manual/commissioner/voted culture awards
  - optional rolling-window trade culture awards with explicit scope label
- Do not publish official computed player awards yet.
- Do not label provisional outputs as official history.

## Public-safe boundary reminder
- Awards pipeline must only consume public league-history domains.
- Never expose private trade-calculator internals, proprietary rank logic, or optimization tools.
