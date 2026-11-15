# Sleeper → League Tycoon parity matrix and feature impact

These are Deliverables 2 and 6. There are two availability columns, and they must not be merged:

- **LT concept**: does League Tycoon's product have this, per its published docs?
  - `DOC`: documented.
  - `UNK`: unknown.
  - `N/A`: no such concept.
  - `DIFF`: League Tycoon has a different semantic.
- **Machine access**: can we actually retrieve it? This is **UNKNOWN for every row** until the owner capture
  (`OWNER_EVIDENCE_CAPTURE.md`). Batch 1 fills this column.

**Migration risk** is how likely a consumer breaks if the projection gets it wrong: H / M / L.

## §A. Field-level matrix (league-scoped Sleeper data only)

### A1. League configuration (`/v1/league/{id}`)

| Sleeper field | Repo consumers | Transform today | Freshness | LT counterpart | LT concept | Risk |
|---|---|---|---|---|---|---|
| `league_id`, `previous_league_id` | registry, seven chain walkers | season chain | per build | League Tycoon league id + season; imported seasons live *inside* one League Tycoon league | DIFF (one League Tycoon league holds many seasons, vs one Sleeper league per season) | H |
| `name` | `/api/leagues`, contract `leagueName` | display | 5 min | league name | DOC | L |
| `season`, `status`, `season_type` | scoring evidence state, public snapshot, pick lifecycle | season verification | 6 h | league year (rollover date, default Apr 1) | DIFF (offseason boundary differs) | H |
| `total_rosters`, `settings.num_teams` | `data_contract._resolve_league_context` (rookie anchor, DLF size), BDVM, FAAB | league size | 1 h | team count | DOC | M |
| `scoring_settings` (148 keys in `dynasty_main`, 17 `idp_*`) | `sf1` fingerprint, realized points, BDVM, league comparison, TE demand (`bonus_rec_te`) | canonical scoring vocabulary | 6 h budget | scoring rules (custom, "no equivalent" rules listed at import) | DOC (general); **UNK for IDP keys** | **H** |
| `roster_positions` | lineup owner (truth-ladder rung 1), `starter-slots.js`, roster capacity, market-trade format | slot vocabulary | per build | starting lineup slots | DOC (superflex); **UNK (DL/LB/DB, IDP flex)** | **H** |
| `settings.best_ball` | lineup, Game Day, awards, player impact, intel filter | lineup mode | per build | — | **UNK** | **H** |
| `settings.league_average_match` | public metrics, playoff sim (median game) | extra W/L | per build | not documented | UNK | M |
| `settings.playoff_week_start`, `playoff_teams`, `playoff_seed_type` | playoff structure, sim | bracket | per build | playoff start (default wk 15), teams (6), reseeding, divisions, 2-week rounds | DOC / DIFF | M |
| `settings.trade_deadline` | gameplan, posture season timing | deadline week | per build | trade deadline (default wk 9), review period, veto votes | DOC | L |
| `settings.waiver_budget`, `waiver_type` | FAAB engine, bid history | budget | per build | FAAB; FAAB-only mode; FA → 1-yr contract | DOC / DIFF | M |
| `settings.draft_rounds` | pick fold, draft capital | horizon depth | per build | rookie rounds (default 3), picks tradable 2 yrs ahead | DOC / DIFF | M |
| `settings.taxi_slots`, `taxi_years`, `reserve_slots` | roster capacity, Sharp format | capacity | per build | practice squad (per-player permanent eligibility), IR (3 modes) | DIFF | M |
| `settings.type` (2 = dynasty) | intel/Sharp dynasty gate, chain coverage | dynasty proof | per build | standard dynasty / contract dynasty / Graveyard / Gambit | DIFF (must map explicitly; unknown ≠ dynasty) | M |
| `metadata.latest_league_winner_roster_id` | public metrics champions | champion | per season | trophies (gold/silver/bronze) | DOC | L |

### A2. Teams and managers (`/rosters`, `/users`)

| Sleeper field | Consumers | LT counterpart | LT concept | Risk |
|---|---|---|---|---|
| `roster_id` | pick ids, draft capital, trade simulator, Game Day `teamId`, acquisition | team id → **franchise number** (README §5.3) | DIFF | **H** |
| `owner_id` / `user_id`, `co_owners` | manager registry, user_kv, sessions, auction, Manager Scout | League Tycoon account per team (one account per league per person, Terms §3); commissioner reassignment | DIFF | **H** |
| `display_name`, `username`, `metadata.team_name`, `avatar` | labels via `owner_names.json`, name-joins, avatars | display name, team name, team logo | DOC | M (name joins) |
| `players` | every roster consumer | roster | DOC | H |
| `starters` | Game Day, awards, public metrics | starting lineup (locks at kickoff) | DOC | M |
| `taxi`, `reserve` | Sharp only (contract path omits them) | practice squad, IR | DIFF | M (an improvement opportunity: exact membership) |
| `settings.wins/losses/ties/fpts(_decimal)/fpts_against` | public standings, draft capital, Sharp records | standings (record, PF, PA) | DOC | M |
| `settings.waiver_budget_used` | `faabRemaining` | FAAB remaining (and cap space) | DOC | M |

### A3. Transactions and trades (`/transactions/{week}`)

| Sleeper field | Consumers | LT counterpart | LT concept | Risk |
|---|---|---|---|---|
| `type` trade / waiver / free_agent / commissioner | activity, acquisition, FAAB history, trades block | trades, trade auctions, FAAB claims, FA pickups, commissioner actions, RFA, tags, cuts, comp-pick awards | DIFF (more types) | H |
| `status`, `transaction_id`, `created`, `status_updated` | idempotency, ordering | unknown ids/timestamps | UNK | H |
| `roster_ids`, `adds`, `drops` | every ledger | trade legs, add/drop | DOC | H |
| `draft_picks[].{season,round,roster_id,owner_id,previous_owner_id}` | pick lineage | pick trades (+ comp picks) | DOC / DIFF | H |
| `settings.waiver_bid` | FAAB history, awards, records | FAAB bid (becomes salary on contract leagues) | DOC / DIFF | M |
| `leg` | week bucket | week | UNK | M |
| *(new)* cap dollars in trades | — | cap-space trading | DOC | — |
| *(new)* trade-auction offers | — | public competing offers | DOC | — |
| **Pre-migration history** | trade history, How It Aged, acquisition | **not imported by League Tycoon** | N/A, so Sleeper stays the record | **H** |

### A4. Picks and drafts (`/traded_picks`, `/drafts`, `/draft/{id}`, `/draft/{id}/picks`)

| Sleeper field | Consumers | LT counterpart | LT concept | Risk |
|---|---|---|---|---|
| traded picks `roster_id` (origin) / `owner_id` (holder) | `src/identity/picks.py` fold; pick ownership state | future picks "transfer with the correct owner" at import; ongoing pick trades | DOC | **H** |
| *(new)* compensatory picks | — | commissioner-assigned, tradable | DOC (needs a new origin class) | H |
| `draft_id`, `status`, `type`, `start_time`, `settings.rounds` | draft lifecycle, class retirement | rookie draft (linear/snake/offline), FA draft (auction/slow/contract bidding), supplemental drafts | DIFF | M |
| `slot_to_roster_id`, `draft_order` | slot maps | lottery / inverse / MPF / manual order | DIFF | M |
| `pick_no`, `round`, `player_id`, `picked_by`, `picked_at` | draft history, live sync | draft selections | DOC | M |
| `metadata.amount` (`"$23"`) | auction history, Perfect Draft backtest | auction winning bid = first-year salary | DIFF (semantics: salary, not a one-off price) | H |

### A5. Matchups and brackets (`/matchups/{week}`, brackets)

| Sleeper field | Consumers | LT counterpart | LT concept | Risk |
|---|---|---|---|---|
| `matchup_id`, `roster_id`, `points` | public league, playoff sim, power, Game Day | weekly matchups, final scores | DOC | H |
| `players_points`, `starters`, `players` | awards, player impact, recaps, Game Day | lineups + player stat lines (also rebuilt for ≤ 20 imported seasons) | DOC | M |
| pre-posted future pairings (0 points) | playoff sim remaining schedule | schedule (regenerated at import) | UNK (visibility of future weeks) | **H** for the sim |
| bracket `{r,m,t1,t2,w,l,p}` | champions, recaps | championship + bankrupt/consolation brackets, optional 2-week rounds, reseeding | DIFF | M |
| weeks 1–18 | public snapshot loops | season ends week 17 | DIFF | M |

### A6. Contract-dynasty fields (no Sleeper counterpart; League Tycoon only)

All DOC as concepts, UNK for access, and gated by README OD-2 / OD-5.

| Group | Fields |
|---|---|
| Contract | salary by season (locked at signing), years (1–5), contract type (rookie / FA / extension / tag / tender), signing source, extension status, tag status, rookie option status, practice-squad eligibility |
| Allocations | multi-year allocations used / remaining per length |
| Cap | cap, used, available, holdback, rollover in, dead money current / next, compliance |
| RFA | tender level, salary, compensation picks, right to match, auction outcome |
| Pricing | tag prices per position (avg top-N), extension price (stable or performance-based) |
| Auctions | nominations, winning bids, contract-bidding length discounts; losing bids UNK |

## §B. Feature impact report (Deliverable 6)

| Feature | Route(s) / owner | Depends on | Class | Required work |
|---|---|---|---|---|
| Rankings / values / consensus | `/api/data` → `_compute_unified_rankings` | global sources; **plus** `_resolve_league_context` (default league `total_rosters`, `bonus_rec_te`) | Unchanged* | *Route `_resolve_league_context` through the provider seam; prove values byte-identical |
| Trade calculator | `/trade`, `/api/trade/{simulate,analyze}` | Hub A teams, `pickDetails.assetId`, name joins | Fed by Hub A | Franchise-number continuity keeps pick `assetId`s; replace name joins with ids (open follow-up already) |
| Trade engines | suggestions / finder / best-offers / golden / package / angle | Hub A, `myTeam` = name, registry capacity | Fed by Hub A | `myTeam` by manager key; capacity from real League Tycoon roster rules |
| Trade history / How It Aged | `/trades`, public `activity`, `trade_grading` | `sleeper.trades` (365-day window), transactions | Adaptation | Merge Sleeper (≤ cutover) + League Tycoon trades by provider; point-in-time values unchanged |
| Terminal | `/api/terminal` | Hub A + trades for roster reconstruction | Fed by Hub A | Cross-provider trade window |
| Rosters | `/rosters`, `/api/roster/intelligence` | Hub A, `rosterPositions` | Fed by Hub A | Slot vocabulary mapping |
| Public `/league` | `src/public_league/*` | Hub B raw Sleeper shapes per season | Adaptation | Hub B projection per League Tycoon season; permalinks for League Tycoon seasons; median / bracket semantics |
| Power rankings | `src/ros/power_v2.py` | Hub B matchups, `last_scored_leg` | Fed by Hub B | Week-17 season |
| Manager Scout | `/api/manager-scout` | acquisition / market / waiver ledgers keyed by Sleeper user id | Adaptation | Manager crosswalk; ledgers gain `provider` |
| Gameplan / posture / window | `/api/gameplan`, `src/roster_intel/window.py` | team strength, sims, `trade_deadline`, calendar week | Fed by A/B | One league-year clock |
| Playoff sim / championship / deadline dashboard | `src/ros/playoff_sim.py` | **pre-posted future matchups**, median game, bracket rules | Adaptation (H) | Needs League Tycoon's remaining schedule; if not observable, mark the sim's schedule input UNKNOWN (never synthesize) |
| Pick projector / forecast / draft order | `src/ros/pick_projection.py`, `draft_order.py` | `pickDetails`, `config/leagues/draft_order_rules.json` | Adaptation | League Tycoon draft-order mode (lottery: forecast must model ball odds, or refuse) |
| Draft capital / Perfect Draft / Rookie Auction Room | `/api/draft-capital`, `/draft`, `src/auction/*` | Sleeper drafts, workbook, `metadata.amount` | Adaptation (H) | League Tycoon rookie drafts are not auctions; owner decision OD-7 |
| Live draft sync | `/api/sleeper/draft/picks` (2.5 s UI poll) | Sleeper draft picks | Adaptation | ≤ 1 / 30–60 s or manual entry |
| Waivers / FAAB engine / bid history | `/api/waiver/*`, `src/trade/faab_*` | waiver budget, bids, transaction types | Adaptation | FA cost = 1-yr salary on contract leagues; tiebreak rules; cap gating |
| Lineup optimizer | `src/ros/lineup.py` | `roster_positions`, `fantasy_positions` | Adaptation | League Tycoon slot names → canonical slots, one mapping table owned by `lineup.py` |
| Roster capacity | `src/trade/roster_capacity.py` | registry sizes; taxi membership unknown | Adaptation (improves) | Practice squad / IR exact membership; dead-money cost of a forced cut on contract leagues |
| Game Day / matchup intel | `/api/matchup/intel`, `src/ros/game_day_*` | per-minute Sleeper matchups + stats | Adaptation (H) | Local live scoring from existing stats × League Tycoon lineups (README §5.4) |
| Weekly narratives | `scripts/generate_weekly_narratives.py` | Hub B, `matchup_id` | Fed by Hub B | Provider-scoped matchup ids |
| BDVM roster / trades | `/api/bdvm/*` | Hub A, scoring card, `leagueSettings` | Fed by Hub A | Scoring mapping |
| Signal alerts | `/api/signal-alerts/run` | Hub A, user_kv `ownerId` | Fed by Hub A | Manager crosswalk |
| Scoring fingerprint / league comparison | `league_registry`, `sleeper_scoring.py` | Sleeper scoring card, `scoring_<sleeperId>.json` | Adaptation | Fingerprint over the *canonical* card after League Tycoon → canonical key mapping; a card that does not fully map fails closed |
| League-adjusted overlay | `/api/valuation/league-adjusted` | committed Sleeper league snapshots | Adaptation | Provider-neutral snapshot |
| Sharp market / roster % / curated sharps | `src/sharp/*` | other Sleeper leagues (X) | **Unchanged** | none |
| Intel crawler (members' other leagues) | `src/intel/crawler.py` | members' Sleeper user ids (X) | **Loses seed** | Seed from the manager crosswalk (Sleeper ids of the same people) or retire; owner decision |
| Username portfolio (2026-10-16 directive) | Manager Intelligence lane | Sleeper global | **Unchanged** | none. A League Tycoon portfolio is not possible beyond the one authorized league |
| Auth / user_kv / sessions | `server.py`, `src/api/user_kv.py` | `ownerId`, `sleeper_user_id` | Fed by crosswalk | Keep canonical manager key |
| Temporal history | `src/history/` | player key = Sleeper id | **Unchanged** | none (League Tycoon players crosswalk to Sleeper ids) |
| Contract intelligence (new) | — | League Tycoon contract tables | New, gated by R60 | README §7 |

## §C. Reconciliation alerts (Batch 8/9)

Each alert is a source-health finding: it fires, it reports, and it changes no value.

| Alert | Trigger |
|---|---|
| `lt_roster_mismatch` | the League Tycoon roster set ≠ the roster implied by our transaction ledger replay |
| `lt_unmatched_player` | a League Tycoon player has no canonical id (lists IDP separately) |
| `lt_pick_owner_conflict` | two franchises claim one pick asset, or a pick changed owner with no trade row |
| `lt_score_mismatch` | the local recompute of a final week differs from League Tycoon's final by > 0.01 |
| `lt_cap_identity` | Σ salaries + dead money ≠ League Tycoon cap used |
| `lt_dead_money_horizon` | dead money appears beyond two seasons (violates the documented rule) |
| `lt_schema_drift` | a read field is missing or has changed type, so the capture is quarantined |
| `lt_access_challenged` | 401/403/429, so the collector stops and the owner is notified |
| `lt_league_id_mismatch` | a response for a non-allow-listed league; it is discarded |
