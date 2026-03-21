# Franchise Page Spec (Public League Page)

## Scope
Define exact structure and methodology for each public franchise page.

Franchise pages should function as:
- franchise profile
- trophy case
- rivalry hub
- all-time stats page
- transaction summary
- historical receipt page

This spec is constrained by current repo data reality:
- currently available: current rosters, future picks, rolling recent trades
- currently missing: full matchup history, full weekly team scores, week-level historical roster ownership timeline

## Feasibility labels
- `complete`: supportable from current authoritative data path.
- `partial`: some data exists, but historical/coverage limits prevent full truth.
- `manual-only`: requires commissioner-managed records.
- `missing`: major ingestion/backfill required.

## Canonical page structure
Route target:
- `/league/franchises/{franchise_id}`

Sections:
1. Core Profile
2. Trophy Case
3. All-Time Team Stats
4. Rank Among All Franchises
5. Head-to-Head Matrix
6. Franchise Superlatives
7. Player Leaders by Position
8. Transaction Profile
9. Money Summary
10. Trade Summary
11. Historical Receipts Timeline

---

## Module-by-module spec

### 1) Core Profile
- Purpose:
  - canonical franchise identity and current state snapshot.
- Fields:
  - `franchise_id`
  - `display_name_current`
  - `manager_display_name_current`
  - `current_logo` (if available/manual)
  - `active_since_season`
  - `current_roster_size`
  - `current_future_pick_count`
- Formulas / derived metrics:
  - `current_roster_size = count(current roster entries for franchise)`
  - `current_future_pick_count = count(draft_picks where owner=franchise and pick_season >= current_season)`
- Required historical data:
  - none for baseline snapshot.
- Automated vs manual:
  - automated: current roster size, pick count, current identity mapping.
  - manual: logo history cleanup, franchise bio text.
- Feasibility now:
  - `complete` (with stable franchise registry).

### 2) Trophy Case
- Purpose:
  - show championships, runner-up finishes, playoff appearances, major awards.
- Fields:
  - `championship_count`
  - `runner_up_count`
  - `playoff_appearance_count`
  - `major_awards_count`
  - list of trophy seasons
- Formulas / derived metrics:
  - counts aggregated from season outcomes and awards.
- Required historical data:
  - season outcomes by franchise (`seasons` + standings/playoff outcomes).
  - awards output table for major awards.
- Automated vs manual:
  - automated later after historical backfill.
  - manual interim seed strongly recommended.
- Feasibility now:
  - `manual-only` (automated truth not yet available).

### 3) All-Time Team Stats
- Purpose:
  - canonical performance totals for the franchise record page.
- Fields:
  - all-time W-L-T
  - points for (PF), points against (PA)
  - average points per game
  - playoff record
  - best season record
- Formulas / derived metrics:
  - `wins/losses/ties` from matchup results
  - `pf = sum(weekly_team_scores.points)`
  - `pa = sum(opponent weekly points)`
  - `avg_ppg = pf / total_games`
  - `playoff_wins/losses` from playoff flagged matchups
- Required historical data:
  - `matchups` and `weekly_team_scores` across all seasons.
- Automated vs manual:
  - automated when historical matchup backfill is complete.
  - manual fallback optional for headline-only stats.
- Feasibility now:
  - `missing` for automated full all-time stats.

### 4) Rank Among All Franchises
- Purpose:
  - rank franchise relative to league peers.
- Fields:
  - overall rank
  - rank by win pct
  - rank by PF
  - rank by championships
  - rank by playoff appearances
- Formulas / derived metrics:
  - dense-rank each metric league-wide.
  - optional composite franchise index (later):
    - weighted z-score of championships, playoff rate, win pct, PF per game.
- Required historical data:
  - same as all-time team stats + season outcomes.
- Automated vs manual:
  - automated after standings/matchups backfill.
  - manual rankings discouraged except temporary narrative labels.
- Feasibility now:
  - `missing` (except manual labels).

### 5) Head-to-Head Matrix
- Purpose:
  - rivalry and opponent record matrix.
- Fields:
  - opponent franchise id/name
  - W-L-T vs opponent
  - PF/PA vs opponent
  - playoff meetings (count and record)
  - last meeting result/date
- Formulas / derived metrics:
  - aggregate `matchups` grouped by `opponent_franchise_id`.
- Required historical data:
  - full matchup history with opponent mapping.
- Automated vs manual:
  - automated after matchup backfill.
  - manual-only rivalry notes can be added earlier.
- Feasibility now:
  - `missing` for matrix, `manual-only` for narrative rivalry notes.

### 6) Franchise Superlatives
- Purpose:
  - "best/worst/most" moments for franchise identity.
- Fields:
  - highest single-week score
  - lowest single-week score
  - biggest win margin
  - biggest upset (later definition)
  - longest win streak
  - longest losing streak
- Formulas / derived metrics:
  - extrema from `weekly_team_scores` + `matchups`.
  - streaks from ordered matchup outcomes by week.
- Required historical data:
  - full weekly team scores + matchup outcomes.
- Automated vs manual:
  - automated once weekly history exists.
  - manual headline superlatives possible in Phase 1.
- Feasibility now:
  - `missing` automated; `manual-only` curated headlines.

### 7) Player Leaders by Position
- Purpose:
  - all-time franchise player leaders at QB/RB/WR/TE/DL/LB/DB.
- Fields:
  - player id/name
  - position bucket
  - franchise-attributed fantasy points
  - games for franchise
  - points per game for franchise
  - seasons active with franchise
- Formulas / derived metrics:
  - strict attribution formula:
    - join `weekly_player_scores` to `roster_history` on (`season`,`week`,`player_id`)
    - keep rows where `roster_history.franchise_id = target franchise`
    - `franchise_points = sum(weekly_player_scores.fantasy_points)`
    - group by player + position bucket
  - `franchise_ppg = franchise_points / franchise_games`
- Required historical data:
  - full `weekly_player_scores` by season/week.
  - full week-level `roster_history` (non-negotiable).
- Automated vs manual:
  - automated only after ownership history backfill.
  - manual substitutes are high risk and should be labeled unofficial.
- Feasibility now:
  - `missing` for truthful all-time leaders.

### 8) Transaction Profile
- Purpose:
  - summarize franchise behavior (waivers/add-drop/trades/FAAB).
- Fields:
  - total transactions
  - waiver adds
  - drops
  - FAAB spent
  - trade count
  - transactions by season
- Formulas / derived metrics:
  - counts and totals from `transactions` plus `trades`.
- Required historical data:
  - non-trade transaction ingestion and FAAB history.
- Automated vs manual:
  - automated trade subset now.
  - full transaction profile requires expanded ingestion.
- Feasibility now:
  - `partial` (trade-only), `missing` for full transaction profile.

### 9) Money Summary
- Purpose:
  - franchise financial profile and profitability.
- Fields:
  - dues paid total
  - winnings total
  - net P/L
  - ROI
  - dollars per playoff appearance
  - dollars per championship
- Formulas / derived metrics:
  - `net_pl = winnings - dues - penalties + refunds`
  - `roi = net_pl / dues_paid`
  - `$/playoff = winnings / playoff_appearances`
  - `$/title = winnings / championships`
- Required historical data:
  - `payouts` ledger + season outcomes (playoff/championship flags).
- Automated vs manual:
  - ledger rows are manual-first.
  - metric math is automated.
- Feasibility now:
  - `manual-only` input, automated output is feasible after manual data entry.

### 10) Trade Summary
- Purpose:
  - summarize franchise trade history and asset movement.
- Fields:
  - total trades
  - trades by season
  - incoming players count
  - outgoing players count
  - incoming picks count
  - outgoing picks count
  - top trade partners
  - recent trades feed
- Formulas / derived metrics:
  - aggregate from `trades` + `trade_assets` grouped by franchise and direction.
- Required historical data:
  - trade events and trade assets; all-time requires backfill beyond rolling window.
- Automated vs manual:
  - automated for currently available trade window.
  - manual historical annotations optional.
- Feasibility now:
  - `partial` (rolling-window accurate, not all-time complete).

### 11) Historical Receipts Timeline
- Purpose:
  - chronological “receipt” narrative: key trades, titles, collapses, milestones.
- Fields:
  - event date/season/week
  - event type (`title`, `trade`, `record`, `note`)
  - event title/body
  - source/provenance
- Formulas / derived metrics:
  - timeline ordering by season/week/date.
  - optional impact tags derived from known metrics.
- Required historical data:
  - season outcomes, matchups, records, trade events.
- Automated vs manual:
  - Phase 1 should be manual editorial timeline.
  - automation grows as historical backfill matures.
- Feasibility now:
  - `manual-only` with limited automated trade entries.

---

## Roster-history requirement (critical accuracy rule)
Player leaders and many historical franchise claims are only trustworthy if week-level ownership exists.

Why:
- a player can score for multiple franchises in the same season after trades/waivers.
- attributing full-season points to one franchise without weekly ownership is factually wrong.

Required join for truthful attribution:
- `weekly_player_scores(season, week, player_id)`  
  JOIN  
  `roster_history(season, week, player_id, franchise_id)`

Without this join:
- player leaderboards become inferred and potentially incorrect.
- “best franchise player season” and “trade hindsight” become unreliable.

Policy:
- do not publish official all-time franchise player leaders until historical `roster_history` coverage meets quality threshold.
- if provisional leaders are shown, label clearly as `unofficial / incomplete-history`.

---

## Required data dependencies by module

| Module | Core entities needed | Current status |
| --- | --- | --- |
| Core Profile | `franchises`, `managers`, current `roster_history`, `draft_picks` | `complete/partial` |
| Trophy Case | `seasons` outcomes, `awards` | `manual-only` now |
| All-Time Team Stats | `matchups`, `weekly_team_scores` | `missing` |
| Rank Among Franchises | all-time stats + outcomes | `missing` |
| Head-to-Head Matrix | `matchups` | `missing` |
| Superlatives | `matchups`, `weekly_team_scores` | `missing` |
| Player Leaders by Position | `weekly_player_scores` + historical `roster_history` | `missing` |
| Transaction Profile | `transactions`, `trades` | `partial` |
| Money Summary | `payouts` + season outcomes | `manual-only` |
| Trade Summary | `trades`, `trade_assets` | `partial` (rolling window) |
| Historical Receipts | mixed historical entities + manual narrative | `manual-only` / `partial` |

---

## Phase recommendation

### Phase 1 (strong, truthful)
- Core Profile
- Trade Summary (rolling-window labeled)
- Money Summary (manual-ledger based)
- Manual Historical Receipts (editorial)
- Limited Trophy Case (manual seeded outcomes only)

### Phase 2
- Head-to-Head Matrix
- All-Time Team Stats
- Rank Among Franchises
- Draft/trade historical depth improvements

### Phase 3
- Player Leaders by Position (official)
- Full Superlatives automation
- Full transaction profile with waivers/FAAB history

## Public-safe guardrails
- Do not expose private trade-calculator internals on franchise pages.
- Explicitly label each module as `complete`, `partial`, `manual-only`, or `missing`.
- Label rolling-window modules clearly (especially trade counts).
