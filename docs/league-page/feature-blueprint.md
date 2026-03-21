# League Page Feature Blueprint

## Scope
Tab-by-tab product spec for the public League Page, grounded in:
- current repo runtime (`Dynasty Scraper.py`, `server.py`, `/api/data`)
- data audit (`data-availability-matrix.md`, `historical-gap-audit.md`)
- canonical model (`data-model.md`)

## Locked top-level tabs
1. Home
2. Standings
3. Franchises
4. Awards
5. Draft
6. Trades
7. Records
8. Money
9. Constitution
10. History
11. League Media

---

## 1) Home
### Purpose
Public landing page for league identity, freshness, and current-state highlights.

### Submodules
- League identity header
- Current season status/freshness
- Quick links to key modules
- Recent activity strip

### Exact data requirements
- `seasons`: `season`, `status`
- `franchises`: active franchise count
- `trades`: recent count + recent timestamps
- runtime freshness metadata from public contract generation time
- optional manual hero copy from a league profile config

### Automated vs manual fields
- Automated: season status, counts, freshness, recent trades summary.
- Manual: league tagline/intro text, optional featured callout.

### Formulas/metrics
- `days_since_last_refresh = now_utc - public_payload_updated_at_utc`
- `recent_trades_30d = count(trades where traded_at_utc >= now-30d)`
- `active_franchises = count(franchises where is_active=true)`

### Dependencies
- Public-safe contract endpoint (`/api/public/league/*`)
- `trades` normalization

### Phase recommendation
- Phase 1 (strong)

---

## 2) Standings
### Purpose
Season standings and eventual historical standings archive.

### Submodules
- Current season standings table
- Season selector (historical)
- Standings trend summary (later)

### Exact data requirements
- `seasons`: season registry
- `matchups` and/or `weekly_team_scores` to compute wins/losses/ties/PF/PA
- optional manually seeded standings rows for legacy seasons

### Automated vs manual fields
- Automated: standings rows when matchup/team-week ingestion exists.
- Manual: temporary seeded standings/champion rows where ingestion is absent.

### Formulas/metrics
- `games = wins + losses + ties`
- `win_pct = (wins + 0.5*ties) / games`
- `pf = sum(weekly_team_scores.points by franchise/season)`
- `pa = sum(opponent weekly points by franchise/season)`

### Dependencies
- Historical matchup/team-week ingestion (currently missing)

### Phase recommendation
- Phase 2 core
- Phase 1 optional: provisional/manual current table only

---

## 3) Franchises
### Purpose
Franchise profile pages for identity, roster snapshot, picks, and transaction narrative.

### Submodules
- Franchise directory
- Franchise header (name/logo, manager, tenure)
- Current roster snapshot
- Future draft capital
- Recent trade activity
- Franchise notes/trophy case (manual)

### Exact data requirements
- `franchises`, `managers`
- `franchise_name_history`
- `franchise_logo_history` (manual initially)
- `roster_history` current snapshot rows
- `draft_picks` (future ownership view)
- `trades`, `trade_assets`
- optional `payouts` summary for profile context

### Automated vs manual fields
- Automated: current roster counts, current picks, recent trades.
- Manual: logo history cleanup, trophy narrative, franchise bio.

### Formulas/metrics
- `current_roster_size = count(current roster_history rows)`
- `future_pick_count = count(draft_picks where pick_season >= current_season)`
- `trade_activity_12mo = count(trades linked to franchise in last 365d)`
- `incoming_assets_12mo` / `outgoing_assets_12mo` from `trade_assets`

### Dependencies
- Stable `franchise_id` mapping from Sleeper roster IDs across seasons
- public-safe trade and pick transforms

### Phase recommendation
- Phase 1 (strong)

---

## 4) Awards
### Purpose
League awards book with methodology transparency and official outputs when data gates pass.

### Submodules
- Awards index by season
- Award detail pages
- Methodology and data-quality gate panel

### Exact data requirements
- `awards` (official output table)
- `weekly_player_scores`
- `roster_history` (week-level ownership)
- `weekly_team_scores` for team awards
- methodology metadata (formula version + evidence ref)

### Automated vs manual fields
- Automated later: formula awards once data completeness thresholds are met.
- Manual now: historical winners and methodology text.

### Formulas/metrics
- Player VORP framework (high-level):
  - `weekly_vorp = player_points - replacement_points(position, week, season)`
  - `season_vorp = sum(weekly_vorp where franchise owned player that week)`
- Team awards examples:
  - best regular-season record, most points for, upset/team-of-week.

### Dependencies
- Full `weekly_player_scores` + full week-level `roster_history` backfill
- award governance/versioning rules

### Phase recommendation
- Phase 3 for official automated player awards
- Phase 1: methodology + manual winners only

---

## 5) Draft
### Purpose
Draft capital and draft history center.

### Submodules
- Future pick ownership board
- Historical draft results (by season)
- Draft class outcome summaries (later)

### Exact data requirements
- `draft_picks` (current/future ownership, original owner, current owner)
- `draft_results` (selected player by pick)
- `trades`/`trade_assets` for pick movement lineage

### Automated vs manual fields
- Automated now: future picks board from existing `pickDetails` ingestion.
- Backfilled/manual later: historical draft results and historical ownership trails.

### Formulas/metrics
- `pick_capital_by_season = count(draft_picks grouped by owner, season, round)`
- `net_pick_change = picks_owned - original_picks` by franchise and season

### Dependencies
- Historical draft endpoint backfill for `draft_results`

### Phase recommendation
- Phase 1: future picks board
- Phase 2: historical draft results and lineage

---

## 6) Trades
### Purpose
League transaction narrative for completed trades with transparent scope labels.

### Submodules
- Trade timeline/feed
- Trade detail modal/page
- Franchise trade activity leaderboard
- Trade partner network (later)

### Exact data requirements
- `trades`
- `trade_assets`
- `franchises`
- trade window metadata (`tradeWindowDays`, `tradeWindowStart`) for scope labeling

### Automated vs manual fields
- Automated: trade feed, activity counts, partner counts.
- Manual optional: editorial tags (`blockbuster`, `rivalry`, `deadline`).

### Formulas/metrics
- `trades_by_franchise = count(trades with franchise participation)`
- `unique_trade_partners = distinct counterpart franchises`
- `player_assets_moved` and `pick_assets_moved` counts

### Dependencies
- Public-safe transform from runtime trades
- Historical backfill if all-time archive is required

### Phase recommendation
- Phase 1 (strong) for rolling recent archive
- Phase 2 for all-time archive

---

## 7) Records
### Purpose
Official league record book (team, player, season, single-week, streaks).

### Submodules
- Team records
- Player records
- Streak records
- Record change log

### Exact data requirements
- `weekly_team_scores`
- `weekly_player_scores`
- `roster_history` for franchise attribution
- `matchups` and `seasons`
- optional manual record seeds

### Automated vs manual fields
- Automated later: computed records from weekly datasets.
- Manual now: small curated headline records only.

### Formulas/metrics
- single-week max/min points
- season totals (`sum weekly points`)
- streaks from ordered matchup outcomes
- franchise player-record attribution via `roster_history` join

### Dependencies
- Historical weekly ingestion + ownership timeline (currently missing)

### Phase recommendation
- Phase 3 for trustworthy automation
- Phase 1 optional: manual headline subset

---

## 8) Money
### Purpose
Transparent league finance board for winnings, dues, and profitability.

### Submodules
- All-time winnings leaderboard
- Dues ledger
- Net P/L leaderboard
- ROI leaderboard
- `$ won / playoff appearance`
- `$ won / championship`

### Exact data requirements
- `payouts` manual ledger rows:
  - `dues_paid`, `payout_amount`, `penalties`, `refunds`
- `seasons` outcomes or manual season outcomes:
  - playoff appearances, championships by franchise

### Automated vs manual fields
- Manual: base money rows and season-outcome corrections where missing.
- Automated: derived metrics and leaderboards from manual ledger.

### Formulas/metrics
- `net_pl = payout_amount - dues_paid - penalties + refunds`
- `roi = net_pl / dues_paid` (null when `dues_paid <= 0`)
- `dollars_per_playoff = total_winnings / playoff_appearances` (null when zero)
- `dollars_per_title = total_winnings / championships` (null when zero)

### Dependencies
- Commissioner-ledger workflow and validation
- outcome counts by franchise (manual/backfilled)

### Phase recommendation
- Phase 1 (strong manual-first)

---

## 9) Constitution
### Purpose
League governance archive with searchable rules and amendment history.

### Submodules
- Current constitution
- Article/section search
- Version history
- Amendment/change log

### Exact data requirements
- `rules_versions`
- rule metadata:
  - effective season range, status, change summary
- manager/editor metadata from `managers`

### Automated vs manual fields
- Manual: full rule text, amendment entries, vote summaries.
- Automated: search indexing, version diff metadata.

### Formulas/metrics
- `active_ruleset = rules_versions where status='active' and effective window includes current season`
- amendment count by season/version

### Dependencies
- Commissioner editing/publishing workflow and schema validation

### Phase recommendation
- Phase 1 (strong manual-first)

---

## 10) History
### Purpose
League museum/timeline across eras, champions, moments, and structural changes.

### Submodules
- Season-by-season timeline
- Era highlights
- Championship lineage
- Notable events

### Exact data requirements
- `seasons`
- `standings`/matchup-derived outcomes
- `draft_results`, `trades`, `awards`, `records`
- optional manual narrative entries tied to seasons/weeks

### Automated vs manual fields
- Automated later: season outcomes timeline once backfill is complete.
- Manual now: narrative stubs and curated milestone entries.

### Formulas/metrics
- champion lineage chain by season
- franchise-era counts (titles, playoff runs) from season outcomes

### Dependencies
- multi-domain historical backfill across standings, matchups, and awards

### Phase recommendation
- Phase 2/3
- Phase 1: explicit placeholder with coverage notice

---

## 11) League Media
### Purpose
Sports-media hub for weekly storytelling and archive.

### Submodules
- Thursday Weekly Preview
- Tuesday Weekly Review
- Matchup of the Week
- Weekly Story Archive
- Optional later modules:
  - Power Rankings
  - Rivalry of the Week
  - Player Spotlight
  - Commissioner Notes

### Exact data requirements
- Phase 1 manual core:
  - `media_posts` with `post_type`, `season`, `week`, `status`, `author`, `approved_by`
- Later automation inputs:
  - `matchups`, `weekly_team_scores`, `trades`, `awards`, `records`
  - optional external NFL news feed references (approved links only)

### Automated vs manual fields
- Phase 1: manual authoring + commissioner approval required.
- Phase 3: optional assisted draft generation with mandatory commissioner review.

### Formulas/metrics
- content metadata only in Phase 1 (no optimization outputs)
- later optional summary metrics:
  - weekly scoring leaders,
  - biggest matchup margin,
  - trade volume per week

### Dependencies
- Publishing workflow and moderation guardrails
- historical scoring/matchup ingestion for auto-recap quality

### Phase recommendation
- Phase 1 manual archive
- Phase 3 assisted generation

---

## Strong Phase 1 module set
- Home
- Franchises
- Draft (future picks only)
- Trades (rolling recent window)
- Money (manual-first)
- Constitution (manual-first)
- League Media (manual publishing + archive)

## Modules dependent on unavailable history or major new ingestion
- Standings (historical)
- Awards (official formula outputs)
- Records (computed record book)
- History (full museum timeline)
- Draft historical results
- Trade hindsight analytics requiring ownership timeline

## Public-safe constraints (hard rules)
- Do not expose private ranking/value/optimization internals from `/api/data`.
- Do not publish inferred historical outcomes as factual.
- Label every module with data coverage status: `complete`, `partial`, `manual-only`, or `deferred`.
