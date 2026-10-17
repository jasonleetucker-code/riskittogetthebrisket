# Sleeper dependency inventory (Phase 2)

Read-only audit of repo `main` at `ae489e18`, 2026-10-17. Paths are relative to the repo root; line numbers come
from that tree and will drift.

**Scope legend:**

- **L**: league-scoped. Registry `sleeperLeagueId` or one of its `previous_league_id` ancestors. **In
  migration scope.**
- **X**: other people's leagues (Sharp / intel crawls). Stays on Sleeper.
- **G**: global. Stays on Sleeper.

## 1. Endpoint inventory

All calls are anonymous REST against `api.sleeper.app`. There is no GraphQL. The frontend never calls the Sleeper
API directly: it loads images from `sleepercdn.com`, and `/api/sleeper/draft/picks` is a Next bridge to the backend.

| # | Endpoint | Scope | Main callers (file:line) | Fields read | Destination / cadence |
|---|---|---|---|---|---|
| 1 | `GET /v1/state/nfl` | G | `src/public_league/sleeper_client.py:251`; `server.py:9075`; `src/ros/scrape.py:424`; `src/ros/game_day_live.py:2396`; `src/ros/pick_forecast_snapshot.py:280`; `src/intel/crawler.py:504`; `src/sharp/transactions.py:167` | `season`, `week`, `season_type` | per request / 2 h / every minute (Game Day) |
| 2 | `GET /v1/league/{id}` | L, X | Scraper `Dynasty Scraper.py:848`, `:1325`; overlay `src/api/sleeper_overlay.py:240,263,471,1303,1389,1816`; `src/api/data_contract.py:9309` (**valuation side**: `total_rosters`, `bonus_rec_te`); `src/league_comparison/sleeper_scoring.py:137`; `src/api/draft_class_evidence.py:114`; `src/trade/faab_history.py:115`; `src/trade/own_league_format_capture.py:278`; `server.py:5703,12258`; Sharp `records.py:306`, `roster_collect.py:549`, `league_format_capture.py:1028` | `name`, `season`, `season_type`, `status`, `total_rosters`, `previous_league_id`, `scoring_settings`, `roster_positions`, `settings.{type,num_teams,waiver_budget,draft_rounds,best_ball,playoff_week_start,playoff_teams,playoff_seed_type,last_scored_leg,league_average_match,trade_deadline,taxi_slots,taxi_years,reserve_slots,bench_lock,max_keepers,waiver_type}`, `metadata.latest_league_winner_roster_id` | contract `sleeper.{leagueName,scoringSettings,rosterPositions,leagueSettings}`; `data/leagues/scoring_<id>.json`; `data/leagues/draft_classes_<id>.json`; own-league format sqlite |
| 3 | `GET /v1/league/{id}/rosters` | L, X | Scraper `:814`, `:1353`; overlay `:461,630,705,1138`; `sleeper_client.fetch_rosters:275`; `server.py:12269`; `src/api/draft_capital_fallback.py:256`; `faab_history.py:206`; intel/sharp crawlers | `roster_id`, `owner_id`, `co_owners`, `players`, `starters`, `reserve`, `taxi`, `settings.{fpts,fpts_decimal,fpts_against(_decimal),wins,losses,ties,waiver_budget_used}` | `sleeper.teams[]`; public snapshot; draft capital. The contract path does **not** read `taxi`/`reserve`/`starters` |
| 4 | `GET /v1/league/{id}/users` | L, X | Scraper `:829`, `:1356`; overlay `:462,631`; `sleeper_client.fetch_users:270`; `server.py:5755,12274`; `draft_capital_fallback.py:257`; `src/sharp/discovery.py:337` | `user_id`, `display_name`, `username`, `avatar`, `metadata.team_name` (labels via `config/leagues/owner_names.json`) | team names, manager registry |
| 5 | `GET /v1/league/{id}/matchups/{week}` | L | `sleeper_client.fetch_matchups:280` → public snapshot weeks 1–18; `src/api/matchup_intel.py:178`; `src/ros/game_day_live.py:2400`; `scripts/capture_game_day_predictions.py:264` | `roster_id`, `matchup_id`, `points`, `starters`, `players`, `players_points` | public snapshot; Game Day (**every minute**) |
| 6 | `GET /v1/league/{id}/transactions/{week}` | L, X | Scraper `:1443` (chain depth 4, 365-day window); overlay `:981`, `:1163`; `sleeper_client.fetch_transactions:285`; `faab_history.py:161`; intel/sharp crawlers | `type`, `status`, `transaction_id`, `created`, `status_updated`, `roster_ids`, `adds`, `drops`, `draft_picks[].{season,round,roster_id,owner_id,previous_owner_id}`, `settings.waiver_bid`, `leg` | `sleeper.{trades,waivers}`; `data/retention/league_events.sqlite`; `data/faab/bid_history_<key>.json` |
| 7 | `GET /v1/league/{id}/traded_picks` | L, X | Scraper `:984`; overlay `_build_pick_ownership:387`; `draft_capital_fallback.py:264`; `server.py:12577` (**still coerces a failure to `[]`**, known follow-up); public snapshot; intel | `season`, `round`, `roster_id` (origin), `owner_id` (holder), `previous_owner_id` | `teams[].picks/pickDetails/pickOwnershipState` |
| 8 | `GET /v1/league/{id}/drafts` | L | Scraper `:931`; overlay `:695`, `:1849`; `server.py:12312`; `draft_capital_fallback.py:187`; `draft_class_evidence.py:108,121`; public snapshot | `draft_id`, `season`, `status`, `type`, `start_time`, `settings.rounds`, `slot_to_roster_id`, `draft_order` | slot maps, live-draft id |
| 9 | `GET /v1/draft/{id}` | L | Scraper `:944`; overlay `:725`, `:1897`; `server.py:12401` | `slot_to_roster_id`, `draft_order`, `status` | slot maps |
| 10 | `GET /v1/draft/{id}/picks` | L | Overlay `fetch_live_draft_picks:1998` (2 s cache; UI polls 2.5 s); `draft_class_evidence.py:133`; public snapshot (`src/public_league/draft.py`) | `player_id`, `pick_no`, `round`, `roster_id`, `picked_by`, `picked_at`, `metadata.{amount,first_name,last_name}` | live draft board; draft history |
| 11 | `GET /v1/league/{id}/winners_bracket`, `/losers_bracket` | L, X | `sleeper_client.py:310,315` → public snapshot; `src/sharp/records.py:322` | `r`, `m`, `t1`, `t2`, `w`, `l`, `p` | brackets, champions |
| 12 | `GET /v1/user/{user_id}/leagues/nfl/{season}` | X | `src/intel/crawler.py:542`; `src/sharp/discovery.py:372` | `league_id`, `name`, `season`, `status`, `total_rosters`, `settings` | intel / Sharp ledgers |
| 13 | `GET /v1/user/{username}` | G | `src/sharp/curated.py:1054,1195` | `user_id`, `username`, `display_name` | curated sharps (06:20 UTC) |
| 14 | `GET /v1/players/nfl` | G | Scraper `:802`; `sleeper_client.py:327`; overlay `:857`; `src/playerctx/fetch.py:78`; Game Day `:806`; news; sharp | names, `position`, `fantasy_positions`, `team`, `years_exp`, `birth_date`, `gsis_id`, `espn_id`, `yahoo_id`, `fantasy_data_id`, `injury_status`, `depth_chart_order` | identity directory, eligibility, headshots |
| 15 | `GET /v1/players/nfl/trending/{add,drop}` | G | `src/adapters/sleeper_trending.py:37`; `scripts/refresh_sleeper_trending_history.py`; `src/news/providers/sleeper.py:157` | `player_id`, `count` | FAAB demand evidence |
| 16 | `GET /v1/stats/nfl/regular/{season}/{week}` | G | `src/league_comparison/sleeper_stats.py:210`; `src/nfl_data/sleeper_live_stats.py:239` (Game Day live) | per-player stat keys | live/realized scoring |
| 17 | `GET /projections/nfl/{season}/{week}` (undocumented) | G | `src/ros/sleeper_weekly_projections.py:95`; matchup intel; DFS auto | `stats`, positions incl. DL/LB/DB | Game Day, DFS |

**Migration scope = rows 2–11, restricted to scope L.** Rows 1 and 12–17 stay on Sleeper regardless.

## 2. League id configuration and season chains

- **Registry and resolver.** League ids live in `config/leagues/registry.json`, parsed by
  `src/api/league_registry.py:137`. Entry fields: `key`, `displayName`, `sleeperLeagueId`, `scoringProfile`,
  `idpEnabled`, `bestBall`, `active`, `aliases`, `rosterSettings`, `defaultTeamMap`. There is **no `platform`
  field.**
- **Env fallback.** `SLEEPER_LEAGUE_ID` is re-read on every call (`:199-226`).
- **Scraper fallback.** The scraper falls back to the hard-coded `DEFAULT_SLEEPER_LEAGUE_ID`
  (`Dynasty Scraper.py:363-381`) and scrapes the **default league only**.
- **Chain walkers.** There are seven `previous_league_id` walkers, each with its own depth:

  | Walker | Depth |
  |---|---|
  | public `walk_league_chain_status` | ≤ 25, with coverage states |
  | scraper | 4 |
  | overlay | 2 |
  | `draft_class_evidence` | 1 |
  | `faab_history` | 10 |
  | sharp records | 6 |
  | own-league format capture | own budget |

  A provider-aware chain must replace these through **one** resolver, not seven.
- **Registry inconsistency noted.** `dynasty_new` registry `taxiSize: 3` vs CLAUDE.md "5 taxi slots".
  Sleeper says `taxi_slots: 3` (VERIFIED 2026-10-17), so the CLAUDE.md prose is stale.

## 3. Consumers, by hub

### Hub A: contract `sleeper` block

- **Producers.** Built by `Dynasty Scraper.py:793-1297` (+ trades `:1300-1545`). The live overlay
  (`src/api/sleeper_overlay.py`) is spliced over it at `server.py:4744-4800`.
- **Shape:**
  - `sleeper.{leagueId, leagueName, teams[], positions, fantasyPositions, playerIds, idToPlayer, scoringSettings,
    rosterPositions, leagueSettings, draftClassEvidence, trades[], waivers[], tradeWindow*}`
  - `teams[] = {name, sleeperTeamName, roster_id, ownerId, players (NAMES), playerIds, picks (labels),
    pickDetails, pickOwnershipState/Reason, faabBudget/Used/Remaining, optimalLineup}`
- **Consumers:**
  - `/trade`; trade simulate/analyze;
  - suggestions/finder/best-offers/golden-upgrades/package-builder/angle;
  - terminal;
  - `/rosters` + `/api/roster/intelligence`;
  - BDVM roster/trade-eval;
  - signal alerts;
  - waivers/FAAB (`faabRemaining`);
  - draft capital + Perfect Draft roster context;
  - lineup stamp (`optimalLineup`);
  - gameplan (`leagueSettings.trade_deadline`, `pickDetails`);
  - pick projector;
  - Manager Scout (team names);
  - private `/trades` (`sleeper.trades`);
  - every page's ownership badges / TeamSwitcher.

### Hub B: `PublicLeagueSnapshot`

- **What it holds.** Raw verbatim Sleeper payloads per season (`src/public_league/snapshot.py:58-72`): league,
  users, rosters, `matchups_by_week`, `transactions_by_week`, drafts, draft picks, traded picks, both brackets,
  plus `nfl_players`.
- **Single-league.** One global cache plus `data/public_league/{snapshot,contract,identity,nfl_players}.json`.
- **Consumers:**
  - every `/league` section (history, rivalries, awards, records, franchise, activity, draft, weekly,
    superlatives, archives, luck, streaks, previews/recaps, conduct, playoff odds, ROS sections, FAAB
    analytics, team assignment);
  - ROS team strength;
  - playoff sim;
  - power rankings v2;
  - pick forecast snapshots;
  - weekly narratives (articles keyed by `matchup_id`).

### Hub C: Sleeper-derived ledgers

| Store | Sleeper-keyed columns |
|---|---|
| `data/retention/league_events.sqlite` `league_transactions` | `sleeper_league_id`, `transaction_id`, raw payload |
| `data/retention/acquisition.sqlite` (`acquisition_events`, `holdings`, `pick_lineage`) | `*_rid`, `*_user_id`, `sleeper_league_id`, `asset_id` |
| `data/retention/evidence.sqlite` `scoring_card_observations` | `sleeper_league_id` |
| `data/faab/bid_history_<key>.json` | `rosterId`, `ownerId`, `leagueId`, `transactionId` |
| `data/leagues/own_league_format_captures.sqlite` | `league_id`, `previous_league_id` |
| `data/market_trades/underlying_trades.sqlite` | `host`, `host_league_id`, `host_tx_id` (already host-aware) |
| `data/intel/ledger.sqlite3`, Sharp roster/format stores | Sleeper user/league/roster ids (X scope; unaffected) |
| `data/session_store.sqlite` `sessions` | `sleeper_user_id` |
| `data/auction/auction.sqlite` | `sleeper_user_id`, `intended_sleeper_user_id` |
| `data/temporal_ledger.sqlite`, `data/board_history.sqlite` | player key = Sleeper id |
| `data/ros/{team_strength,sims,power_snapshots}`, `data/forecast_archive`, `data/pick_forecast_snapshots`, `data/game_day/*` | `ownerId`, `roster_id`, Sleeper player ids, raw Sleeper shapes |
| tracked `exports/latest/*.json`, `exports/archive/*.zip` | the full `sleeper` block |

### Direct per-request Sleeper calls outside the hubs

- `data_contract._resolve_league_context` (`:9309`). This puts a league-scoped Sleeper read inside the
  scoring-profile board build.
- `/api/leagues` name and team: `server.py:5703`, `:5755`.
- Default-league draft-capital workbook path: `server.py:12160-12720`.
- Matchup intel: `src/api/matchup_intel.py:166-196`.
- The articles generate route.

## 4. Hidden-coupling catalog

1. **Player id = Sleeper id.**
   - Contract `playerId` (`src/api/data_contract.py:13683`).
   - `player:<sleeperId>` (`src/history/keys.py:5`).
   - Sharp `canonical_asset_id` (`src/platforms/assets.py:3-5`).
   - Draft workspace, Game Day archive, signals, headshot URLs on `sleepercdn.com`.
2. **Manager id = Sleeper `owner_id`.**
   - ManagerRegistry (`src/public_league/identity.py`; retired owners hard-coded at `:41-46`).
   - Trade sides, posture, playoff rows, user_kv `selectedTeamsByLeague`, sessions, auction, intel.
3. **`roster_id` integers.**
   - Inside canonical pick ids (`src/identity/picks.py:178-197`).
   - `pickDetails.{original_roster_id, owner_roster_id}`, draft-capital `originRosterId` / `currentOwnerRosterId`,
     `teamStackKey`, Game Day `teamId`, acquisition `*_rid`.
4. **Season chaining via `previous_league_id`** (seven walkers, §2).
5. **Transaction semantics.**
   - `type ∈ {trade, waiver, free_agent, commissioner}`, `status == "complete"`.
   - `leg` as the week bucket, `settings.waiver_bid`, `draft_picks[].previous_owner_id`.
   - Millisecond timestamps.
   - `waiver_budget_used` resets each season.
   - Fallback budget 100 = "Sleeper's default".
6. **Brackets.** `{r, m, t1, t2, w, l, p, t1_from, t2_from}` and `metadata.latest_league_winner_roster_id`.
7. **Standings math.**
   - `fpts + fpts_decimal/100`.
   - `rank` is published as `sleeperRank`.
   - "Scored" means `points > 0`.
   - Future pairings are pre-posted with 0 points; the playoff sim depends on this.
   - `"0"` is the empty-slot sentinel.
8. **Format flags.** `best_ball`, `league_average_match` (median game), `type` 2 = dynasty, `taxi_slots`,
   `draft_rounds`, `trade_deadline`, `playoff_week_start`, `playoff_seed_type`. The registry duplicates several
   of these by hand (`bestBall`, `idpEnabled`, `rosterSize`, `taxiSize`, `starters`), and they can drift.
9. **Vocabulary.**
   - Scoring keys (`rec`, `pass_td`, `bonus_rec_te`, `idp_*`) are the canonical scoring language
     (`src/league_comparison/sleeper_scoring.py:76-128`, `sf1`).
   - Slot names (`SUPER_FLEX`, `WRRB_FLEX`, `REC_FLEX`, `IDP_FLEX`, `BN`, `TAXI`, `IR`) belong to the lineup
     owner (`src/ros/lineup.py:340-381`; `slotSource: "sleeper_roster_positions"`).
10. **Draft semantics.** `slot_to_roster_id`, `draft_order` (user_id → slot), `metadata.amount` as a `"$23"`
    string, `picked_by`, `pick_no`.
11. **Names as join keys.**
    - `myTeam` = display name on finder/best-offers/golden-upgrades/package-builder (`server.py` 9487/9767/9937/10043).
    - `/trade` and `/rosters` match players by name (`frontend/app/trade/page.jsx:339-354`).
    - Workbook first-name bridge (`server.py:12160-12720`).
    - `config/team_assignment.json` keys are display names.
12. **Field names.** `sleeper` block, `sleeperDataReady`, `sleeperLoadedLeagueKey`, `sleeperSource`,
    `sleeperTeamName`, `sleeperRank`, `fetched_from_sleeper`.
13. **Public permalinks.** These embed Sleeper ids (listed in `frontend/app/sitemap.js:94-116`):
    - `/league/franchise/<ownerId>`
    - `/league/rivalry/<a>-vs-<b>`
    - `/league/weekly/<season>/<week>/<matchup_id>`
    - `/league/player/<sleeperId>`
14. **Clock split.**
    - Game Day, pick forecast and intel use Sleeper `/state/nfl`.
    - The FAAB engine, competitive posture and BDVM actuals use the calendar.

    League Tycoon's league year (rollover-based) is a third clock and must be owned in one place.

## 5. Dead or test-only Sleeper code observed (informational)

- `src/scoring/sleeper_ingest.fetch_league`: imported, never called.
- `src/league_intel/config.fetch_live_league`: tests only.
- `src/league_intel/sim_calibration.fetch_stat_lines`: tests only.
- `sleeper_client.fetch_draft_detail`: no caller.
- `src/platforms/sleeper.py`: no importers. Candidate home for the Sleeper league adapter (README §5.1).
- Stale comments: `src/sharp/records.py:69` ("users"), `src/intel/crawler.py:55-58` (`PICK_HOLDINGS_YEARS = 3`).

## 6. Test fixtures that embed Sleeper shapes

| Area | Files |
|---|---|
| Public league | `tests/fixtures/public_league/*` (incl. `dynasty_new_2024_matchups.json`, `median_record_parity_2026w4.json`) |
| Game Day | `tests/fixtures/game_day/replay/*` (13 scenarios + shared league files), `game_day/sleeper/*`, `sleeper_projections/*` |
| League intel | `tests/league_intel/fixtures/matchups_2025/w1..w17.json`, `golden_bestball_lineups.json`, `golden_team_weeks.json`, `golden_player_weeks.json`, `scoring_settings_2025.json` |
| Identity | `tests/fixtures/pick_identity_live_subset.json`, `identity_directory_subset.json` |
| Contract / archives | `tests/fixtures/golden/input_export.json.gz`, `tests/archive_fixtures.py` (tracked export archives) |
| Python builders | `tests/public_league/fixtures.py:23-491` |
| Broader usage | About 111 Python test files build `roster_id` / `owner_id` / `matchup_id` dicts. About 40 frontend tests and 5 E2E specs reference Sleeper shapes |

These are the regression baseline for Batch 2's "byte-identical" gate. League Tycoon fixtures must come only from
the owner's sanitized capture or be clearly synthetic.
