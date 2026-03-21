# Draft Methodology (Public League Page)

## Scope
Define methodology for Draft tab including:
- current year pick values (public-safe format)
- draft order
- traded pick tracker
- historical rookie draft archive
- draft hit-rate analytics
- best draft picks
- worst draft picks

## Current repo reality
Available now:
- future pick ownership snapshots via `sleeper.teams[].pickDetails`
- pick labels include `season`, `round`, and sometimes slot/tier context

Missing now:
- full historical rookie draft results across seasons
- complete historical pick ownership lineage
- multi-season player outcome attribution tied to draft slots
- full weekly ownership history needed for some long-horizon outcome analyses

## Canonical draft normalization (required first)
Normalize into:
- `draft_picks`:
  - `pick_id` (`{season}-{round}-{original_franchise_id}` canonical key)
  - `pick_season`, `pick_round`, `pick_slot` (nullable)
  - `original_franchise_id`
  - `current_owner_franchise_id`
  - `label`
  - `source_ref`
- `draft_results`:
  - `pick_id`
  - `selected_player_id`
  - `selected_player_name`
  - `drafting_franchise_id`
  - `draft_season`

## Methodology by requested feature

### 1) Current year pick values (public-safe format)
Goal:
- show useful pick strength context without leaking tactical edge.

Method:
- Use public-safe tiering and ordinal indices, not proprietary value numbers.
- Tier framework example:
  - Tier 1: picks 1.01-1.03
  - Tier 2: picks 1.04-1.06
  - Tier 3: picks 1.07-1.12
  - Tier 4+: round-based descending tiers
- Display:
  - tier badge
  - slot/round
  - relative pick index (1..N) for the year

Guardrail:
- Do not publish private trade-calculator pick values or package-value conversion factors.

Feasibility now:
- `partial` (depends on slot availability in current season pick details; otherwise use round+tier labels only).

### 2) Draft order
Method:
- Preferred:
  - use Sleeper draft order / slot mapping when available in draft endpoint pulls.
- Fallback:
  - derive from `pickDetails.slot` for current-year picks.
- If slot missing:
  - mark as `TBD` and keep ordering by round then known slot.

Feasibility now:
- `partial` for current year, not full historical.

### 3) Traded pick tracker
Method:
- For each pick row, show:
  - original owner
  - current owner
  - movement flag (`own`, `acquired`, `sent`)
- If trade linkage is normalized:
  - add movement count and last movement timestamp.

Feasibility now:
- `complete` for current/future snapshot ownership.
- `partial` for full historical movement chain.

### 4) Historical rookie draft archive
Method:
- Build season-by-season archive from historical draft pulls:
  - round, slot, selecting franchise, player selected.
- Retain immutable provenance per season snapshot.

Feasibility now:
- `missing` (requires backfill ingestion).

### 5) Draft hit-rate analytics
Objective:
- evaluate drafting outcomes by round/slot over time.

Method:
- Define hit classes based on realized contribution window:
  - `hit`: reaches threshold `season_vorp` or `rolling_points` in first N seasons
  - `starter-hit`: reaches higher threshold
  - `miss`: below baseline threshold
- Recommended default window:
  - years 1-3 after draft
- Round hit rate:
  - `hit_rate(round) = hits_in_round / picks_in_round`
- Franchise draft efficiency:
  - `draft_efficiency = sum(realized_value - expected_value_for_slot)`

Required data:
- complete `draft_results`
- multi-season player outcomes (`weekly_player_scores`, award/value outputs)
- stable player identity mapping

Feasibility now:
- `missing`.

### 6) Best draft picks
Method:
- For each pick:
  - `pick_surplus = realized_value_window - expected_value_by_slot`
- Rank descending by `pick_surplus`.

Required data:
- `draft_results` + expected slot baseline + player realized outcomes.

Feasibility now:
- `missing`.

### 7) Worst draft picks
Method:
- For each pick:
  - `pick_shortfall = expected_value_by_slot - realized_value_window`
- Rank descending by `pick_shortfall`.

Required data:
- same as best picks.

Feasibility now:
- `missing`.

## Expected-value baseline for pick analytics
For hit-rate/best/worst calculations:
- build `expected_value_by_slot` from historical league draft classes (preferred) or public external historical baseline until internal sample matures.
- baseline must be versioned:
  - `draft_baseline_version`
  - `fit_window_years`
  - `sample_size`

## Required data by feature
| Feature | Required data | Supportability now |
| --- | --- | --- |
| Current year pick values (safe tiers) | `draft_picks` current-year slot/tier fields | partial |
| Draft order | current season slot/order map | partial |
| Traded pick tracker | `draft_picks` owner fields + optional trade links | complete for snapshot / partial for lineage |
| Historical rookie archive | `draft_results` all seasons | missing |
| Hit-rate analytics | `draft_results` + multi-season outcomes + baseline | missing |
| Best/Worst picks | same as hit-rate plus surplus formula | missing |

## Public-safe guardrails
- Never expose private trade-calculator pick value numbers, package multipliers, or optimization logic.
- Prefer categorical/tier presentation for current-year pick value.
- Keep analytics retrospective and historical; avoid “what to do now” strategic framing.
- Label coverage clearly:
  - `current snapshot`, `rolling`, `historical complete`, or `historical partial`.

## Phase recommendations
- Phase 1:
  - future/current pick board
  - draft order where available
  - traded pick tracker (snapshot)
- Phase 2:
  - historical rookie draft archive
  - historical traded pick lineage
- Phase 3:
  - hit-rate analytics
  - best/worst draft picks
  - franchise draft efficiency leaderboards
