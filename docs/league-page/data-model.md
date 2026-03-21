# Canonical League Page Data Model

## Scope
Canonical data model for public League Page modules:
- history
- franchise profiles
- records
- awards
- trades
- draft history
- money
- constitution
- league media

This model is based on current repo reality:
- authoritative runtime path: `Dynasty Scraper.py -> src/api/data_contract.py -> /api/data`
- current storage pattern: file artifacts (`data/*.json`, `data/*.csv`)
- historical gap constraints documented in:
  - `docs/league-page/data-availability-matrix.md`
  - `docs/league-page/historical-gap-audit.md`

## Modeling rules
- Public League model is isolated from private trade-calculator internals.
- Use stable internal IDs for franchise and manager identity across seasons.
- Every row includes provenance: `source_of_truth`, `derived`, `backfilled`, or `manual`.
- Keep ingestion-truth rows immutable where possible; publish derived snapshots separately.
- Phase 1 must support file-artifact persistence first; relational DB can be added later.

## ID and provenance conventions
| Field | Type | Notes |
| --- | --- | --- |
| `league_id` | string | Sleeper league id; used across all domain tables. |
| `season` | int | NFL season year for partitioning and joins. |
| `week` | int nullable | Week number for weekly entities. |
| `franchise_id` | string | Stable internal id; not tied to one-season roster id. |
| `manager_id` | string | Stable internal manager/person identity id. |
| `data_provenance` | enum | `source_of_truth`, `derived`, `backfilled`, `manual`. |
| `source_ref` | string nullable | Raw source pointer (endpoint, file, run id, or manual ledger id). |
| `created_at_utc` | datetime | Insert timestamp. |
| `updated_at_utc` | datetime | Last modification timestamp. |

## Canonical entities

### Identity and lifecycle entities
| Entity | Purpose | Required fields | Optional fields | Relationships | Data class | Phase |
| --- | --- | --- | --- | --- | --- | --- |
| `franchises` | Canonical franchise identity across all seasons. | `league_id`, `franchise_id`, `is_active`, `created_at_utc`, `updated_at_utc`, `data_provenance` | `current_display_name`, `current_sleeper_roster_id`, `current_manager_id` | 1:M to `franchise_name_history`, `franchise_logo_history`, `roster_history`, `trades`, `draft_picks`, `payouts`, `awards` | source_of_truth + manual override | required P1 |
| `managers` | Canonical manager identity and profile metadata. | `league_id`, `manager_id`, `display_name`, `is_active`, `created_at_utc`, `updated_at_utc`, `data_provenance` | `sleeper_user_id`, `joined_season`, `left_season`, `bio` | 1:M to `franchises` (time-bound), `media_posts` (author), `rules_versions` (editor), `payouts` (approved_by) | source_of_truth + manual | required P1 |
| `seasons` | Canonical season registry and high-level season state. | `league_id`, `season`, `status`, `data_provenance`, `created_at_utc`, `updated_at_utc` | `season_label`, `champion_franchise_id`, `runner_up_franchise_id`, `regular_season_weeks`, `playoff_weeks` | 1:M to `matchups`, `weekly_team_scores`, `weekly_player_scores`, `awards`, `media_posts` | backfilled/manual initially | required P1 (minimal row set) |
| `franchise_name_history` | Track franchise display-name changes over time. | `league_id`, `franchise_id`, `effective_start_season`, `display_name`, `data_provenance`, `created_at_utc` | `effective_end_season`, `change_reason`, `source_ref` | M:1 to `franchises` | source_of_truth partial + manual correction | required P1 |
| `franchise_logo_history` | Track logo/avatar changes for franchise identity timeline. | `league_id`, `franchise_id`, `effective_start_season`, `logo_url_or_asset_key`, `data_provenance`, `created_at_utc` | `effective_end_season`, `thumbnail_url`, `source_ref` | M:1 to `franchises` | manual (until reliable API history exists) | deferred P2 (optional P1 manual) |

### Competition and scoring entities
| Entity | Purpose | Required fields | Optional fields | Relationships | Data class | Phase |
| --- | --- | --- | --- | --- | --- | --- |
| `matchups` | One row per team per matchup slot/week. | `league_id`, `season`, `week`, `matchup_id`, `franchise_id`, `opponent_franchise_id`, `result`, `data_provenance`, `created_at_utc` | `is_playoff`, `seed_at_time`, `source_ref` | M:1 to `seasons`, M:1 to `franchises` | backfilled | deferred P2 |
| `weekly_team_scores` | Canonical weekly points and result-facing team metrics. | `league_id`, `season`, `week`, `franchise_id`, `points`, `data_provenance`, `created_at_utc` | `bench_points`, `optimal_points`, `opp_points`, `margin`, `source_ref` | M:1 to `seasons`, M:1 to `franchises`, joins `matchups` | backfilled | deferred P2 |
| `weekly_player_scores` | Canonical player week scores under league scoring. | `league_id`, `season`, `week`, `player_id`, `fantasy_points`, `data_provenance`, `created_at_utc` | `position`, `team`, `stat_blob`, `source_ref` | M:1 to `seasons`; joins `roster_history` for ownership attribution | partial now/backfilled later | deferred P2 |
| `roster_history` | Week-level franchise ownership timeline for each player asset. | `league_id`, `season`, `week`, `franchise_id`, `player_id`, `ownership_status`, `data_provenance`, `created_at_utc` | `acquired_via_transaction_id`, `released_via_transaction_id`, `source_ref` | M:1 to `franchises`, M:1 to `seasons`, joins `weekly_player_scores`, `transactions`, `awards` | source_of_truth current snapshot + backfilled timeline | required structure P1, full data deferred P2/P3 |

### Trade, draft, and transaction entities
| Entity | Purpose | Required fields | Optional fields | Relationships | Data class | Phase |
| --- | --- | --- | --- | --- | --- | --- |
| `trades` | Canonical trade event header. | `league_id`, `trade_id`, `season`, `week`, `traded_at_utc`, `status`, `data_provenance`, `created_at_utc` | `source_league_id`, `window_scope` | 1:M to `trade_assets`; M:M with `franchises` via assets | source_of_truth partial (rolling) + backfilled | required P1 |
| `trade_assets` | One row per asset moved in a trade side. | `league_id`, `trade_id`, `asset_row_id`, `from_franchise_id`, `to_franchise_id`, `asset_type`, `asset_label`, `data_provenance`, `created_at_utc` | `player_id`, `pick_season`, `pick_round`, `pick_slot`, `source_ref` | M:1 to `trades`; M:1 to `franchises` | source_of_truth partial + backfilled | required P1 |
| `draft_picks` | Pick ownership and metadata (future + historical chain). | `league_id`, `pick_id`, `pick_season`, `pick_round`, `original_franchise_id`, `current_owner_franchise_id`, `data_provenance`, `created_at_utc` | `pick_slot`, `tier_label`, `source_ref` | M:1 to `franchises`; 1:1 or 1:0 to `draft_results` | source_of_truth partial now + backfilled | required P1 (future board), full history deferred |
| `draft_results` | Actual drafted player results by pick. | `league_id`, `pick_id`, `draft_season`, `selected_player_id`, `drafting_franchise_id`, `data_provenance`, `created_at_utc` | `selected_player_name`, `selected_position`, `source_ref` | M:1 to `draft_picks`; M:1 to `franchises` | backfilled | deferred P2 |
| `transactions` | Canonical non-trade league transactions (waiver/add/drop/IR/etc.). | `league_id`, `transaction_id`, `season`, `week`, `transaction_type`, `status`, `created_at_utc`, `data_provenance` | `faab_bid`, `franchise_id`, `player_id`, `source_ref` | M:1 to `seasons`; M:1 to `franchises`; ties to `roster_history` | backfilled | deferred P2 |

### Governance, finance, awards, and media entities
| Entity | Purpose | Required fields | Optional fields | Relationships | Data class | Phase |
| --- | --- | --- | --- | --- | --- | --- |
| `league_messages` | League communication metadata for culture stats. | `league_id`, `message_id`, `message_ts_utc`, `data_provenance`, `created_at_utc` | `manager_id`, `season`, `week`, `channel`, `message_type`, `source_ref` | M:1 to `managers`, M:1 to `seasons` | backfilled/new integration | deferred P3 |
| `payouts` | Money ledger rows for dues, payouts, penalties, refunds. | `league_id`, `season`, `franchise_id`, `dues_paid`, `payout_amount`, `data_provenance`, `created_at_utc` | `penalties`, `refunds`, `notes`, `approved_by_manager_id`, `source_ref` | M:1 to `franchises`, M:1 to `seasons` | manual-first | required P1 |
| `rules_versions` | Versioned constitution/rules text and status. | `league_id`, `rules_version_id`, `effective_start_season`, `title`, `body_markdown`, `status`, `data_provenance`, `created_at_utc` | `effective_end_season`, `change_summary`, `approved_by_manager_id` | 1:M self-link via prior version; ties to `media_posts` for announcements | manual | required P1 |
| `awards` | Official team/player awards outputs with formula metadata. | `league_id`, `season`, `award_id`, `award_key`, `winner_type`, `winner_ref_id`, `is_official`, `data_provenance`, `created_at_utc` | `formula_version`, `calculation_ref`, `notes` | M:1 to `seasons`; winner links to `franchises` or player id; depends on `weekly_player_scores` + `roster_history` for player awards | derived/backfilled/manual gating | deferred P2/P3 |
| `media_posts` | Public League Media content and publishing workflow. | `league_id`, `post_id`, `post_type`, `title`, `body_markdown`, `status`, `author_manager_id`, `created_at_utc`, `data_provenance` | `season`, `week`, `matchup_id`, `published_at_utc`, `approved_by_manager_id`, `source_ref` | M:1 to `managers`, optional links to `seasons`/`matchups` | manual-first, optional derived assist later | required P1 (manual workflow) |

## Phase 1 minimum physical model
These entities are required to ship truthful Phase 1 League Page value without fake history:
- `franchises`
- `managers`
- `seasons` (minimal registry rows)
- `franchise_name_history`
- `trades`
- `trade_assets`
- `draft_picks` (future ownership snapshot)
- `payouts` (manual commissioner ledger)
- `rules_versions` (manual constitution/rules)
- `media_posts` (manual League Media archive)
- `roster_history` structure with current snapshot support only

## Deferred entities (after Phase 1)
- `matchups`
- `weekly_team_scores`
- `weekly_player_scores`
- full `roster_history` backfill
- `draft_results`
- non-trade `transactions`
- `league_messages`
- automated/official `awards`
- historical `franchise_logo_history` unless manually seeded

## Historical roster ownership by week (critical note)
`roster_history` by week is the single most important historical integrity table for player-attribution claims.

Why it matters:
- Franchise player leaders:
  - Without week-level ownership, career points/TDs cannot be truthfully attributed to the correct franchise.
- Player awards:
  - VORP-style outputs require joining weekly player performance to the franchise that actually rostered the player that week.
- Matchup previews/recaps:
  - Accurate “who started/scored for whom” storytelling depends on week-specific ownership context.
- Trade hindsight:
  - Post-trade outcomes (value won/lost after move date) require clear pre/post ownership boundaries by week.

Practical model decision:
- Keep `roster_history` in the canonical schema now.
- Populate only current snapshot in Phase 1.
- Mark historical rows as `missing` until backfilled; do not infer ownership from present-day rosters.

## Practical storage plan for current repo
Current repo is file-artifact first, so implement this model physically as versioned artifacts before introducing DB migration work:
- `data/league/public/*.json` for published API-ready slices.
- `data/league/backfill/*.jsonl|csv` for imported historical pulls.
- `data/league/manual/money/*.json`
- `data/league/manual/constitution/*.md|json`
- `data/league/manual/media/*.md|json`
- `data/league/manual/identity/*.json` for franchise name/logo history.

When a relational store is added later, preserve these canonical entity keys and provenance fields unchanged.

## Public boundary reminder
- Do not include private trade-calculator internals, ranking blends, or optimization diagnostics in League Page entities.
- League Page entities are narrative/history/governance domains only.
