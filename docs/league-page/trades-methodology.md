# Trades Methodology (Public League Page)

## Scope
Define public-safe methodology for Trades tab, including:
- best trade ever
- worst trade ever
- biggest overpay
- biggest steal
- most active trader

with required evaluation layers:
- at-time value
- 6-month hindsight
- 1-year hindsight

## Current repo reality
Source-of-truth now:
- `sleeper.trades` in runtime payload from `Dynasty Scraper.py`
- trade fields currently available: `leagueId`, `week`, `timestamp`, `sides[]`, with side `got[]` and `gave[]`
- trade history is rolling-window (`tradeWindowDays`, default 365), not guaranteed all-time

Critical missing pieces for full historical grading:
- canonical historical asset-value snapshots by trade date
- full weekly ownership timeline (`roster_history`)
- full league-specific weekly scoring outcomes linked to ownership
- complete historical draft results for pick outcome attribution

## Canonical trade normalization (required first)
Each trade must be normalized into:
- `trades` (header):
  - `trade_id`
  - `league_id`
  - `season`
  - `week`
  - `traded_at_utc`
  - `source_league_id`
  - `window_scope` (`rolling_365d`, `all_time`, etc.)
- `trade_assets` (line items):
  - `trade_id`
  - `from_franchise_id`
  - `to_franchise_id`
  - `asset_type` (`player`, `pick`)
  - `player_id` (nullable until normalized)
  - `pick_season` / `pick_round` / `pick_slot` (for picks)
  - `asset_label_raw`

Without this normalization, overpay/steal and hindsight scoring are unreliable.

## Evaluation layer framework

### Layer A: At-time value
Purpose:
- evaluate package balance using values available at trade date.

Public-safe method:
- Use a separate public valuation baseline (not private trade-calculator internals).
- Recommended baseline source:
  - archived public market snapshots (public consensus sources) normalized by date.

At-time package score:
- `at_time_package_value(side) = sum(asset_at_time_value(asset, trade_date))`
- `at_time_delta(side) = value_received - value_sent`

### Layer B: 6-month hindsight
Purpose:
- evaluate medium-term realized impact after trade.

Method:
- For players:
  - `player_6m_value = sum(weekly_vorp_raw while rostered by acquiring franchise, trade_date -> trade_date+183d)`
- For picks:
  - if pick used within window, map to selected player’s realized value in same window;
  - otherwise fallback to remaining expected value curve snapshot.

- `hindsight_6m_delta(side) = realized_received_6m - realized_sent_6m`

### Layer C: 1-year hindsight
Purpose:
- evaluate longer-term realized outcome.

Method:
- same as 6-month but window = 365 days.
- `hindsight_1y_delta(side) = realized_received_1y - realized_sent_1y`

## Trade award methodologies

### Best trade ever
- Score:
  - `best_trade_score = w_at * at_time_delta + w_6m * hindsight_6m_delta + w_1y * hindsight_1y_delta`
- Recommended weights:
  - `w_at=0.25`, `w_6m=0.35`, `w_1y=0.40`
- Winner:
  - highest side-level `best_trade_score` across all normalized trades.

### Worst trade ever
- Same score framework.
- Winner:
  - lowest side-level `best_trade_score`.

### Biggest overpay
- Focus:
  - at-time imbalance only.
- Score:
  - `overpay_score = -(at_time_delta)` for the side acquiring assets.
- Winner:
  - highest positive `overpay_score`.
- Guard:
  - require minimum absolute at-time package value threshold to avoid noise trades.

### Biggest steal
- Focus:
  - favorable at-time acquisition, confirmed by hindsight.
- Score:
  - `steal_score = 0.5*at_time_delta + 0.2*hindsight_6m_delta + 0.3*hindsight_1y_delta`
- Winner:
  - highest `steal_score`.

### Most active trader
- Score:
  - `activity_score = trade_count + 0.2 * unique_trade_partners + 0.05 * asset_lines_moved`
- Alternate simple metric (Phase 1-safe):
  - rank by `trade_count`, tie-break by `unique_trade_partners`.

## Tie-breakers
For best/worst/overpay/steal:
1. Higher absolute primary score.
2. Higher total asset-value moved (at-time package total).
3. More unique trade partners (for same side/franchise season).
4. Co-winner if still tied.

For most active trader:
1. Higher `trade_count`.
2. Higher `unique_trade_partners`.
3. Higher `asset_lines_moved`.
4. Alphabetical franchise name.

## Required data by metric
| Metric | Required data | Supportability now |
| --- | --- | --- |
| Best trade ever | normalized trades/assets + at-time value snapshots + 6m/1y ownership-linked outcomes | not supportable now |
| Worst trade ever | same as above | not supportable now |
| Biggest overpay | normalized trades/assets + at-time value snapshots | not supportable now |
| Biggest steal | normalized trades/assets + at-time + 6m/1y outcomes | not supportable now |
| Most active trader | normalized trades + franchise identity map | supportable now (rolling window) |

## Historical calculator values policy (public)
- Private trade-calculator values should not be exposed publicly as asset-level numbers.
- Public tab should never output private proprietary package math, fairness engines, or recommendation logic.
- If historical values are needed for at-time layer:
  - use a separate public valuation archive or a redacted public model.
  - expose only high-level categorical outputs (for example: `clear win`, `slight win`, `even`) after historical windows close.

## Phase recommendations
- Phase 1:
  - timeline/feed
  - most active trader
  - trade partner frequency
  - rolling-window descriptive stats
- Phase 2:
  - normalize full trade archive and asset identities
  - add at-time layer once public historical value archive exists
- Phase 3:
  - launch best/worst/overpay/steal with all three layers and quality gates

## Public-safe guardrails
- Label time scope on every trade metric (`rolling 365d` vs `all-time`).
- Do not show private per-asset value numbers or optimization outputs.
- Keep outputs historical/descriptive, not tactical/opponent-exploitable.
