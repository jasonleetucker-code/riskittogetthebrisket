# Repo Architecture Findings (League Page Discovery + Scaffold)

## Scope
Repo-grounded architecture audit for the public League Page. This document tracks
what is live now, what is scaffolded, and what is still blocked.

## Skills used explicitly
- `blueprint-auditor`: blueprint/docs vs live runtime path verification.
- `reality-check-review`: status labeling and stale/unsupported claim detection.
- `scraper-ops`: ingestion/source path tracing.

## Evidence base (primary files inspected)
- `server.py`
- `Dynasty Scraper.py`
- `src/api/data_contract.py`
- `Static/landing.html`
- `Static/league/index.html`
- `Static/league/league.js`
- `Static/league/league.css`
- `Static/index.html`
- `Static/js/runtime/*.js`
- `frontend/app/*`
- `frontend/lib/*`
- `docs/BLUEPRINT_EXECUTION.md`
- `docs/REPO_INVENTORY.md`
- `README.md`
- `src/README.md`

## 1) Framework and runtime topology
- `complete`: backend framework is FastAPI (`server.py`).
- `complete`: live producer path is `Dynasty Scraper.py -> src/api/data_contract.py -> /api/data`.
- `complete`: runtime mode switch exists (`FRONTEND_RUNTIME=static|next|auto`).
- `complete`: default runtime is `static` when env var is unset/invalid.

## 2) Routing structure and auth
### Public routes (verified)
- `GET /`
- `GET /league`
- `GET /league/{league_path:path}`
- `GET /api/league/public`
- `GET /api/data`
- `GET /api/dynasty-data`
- `GET /api/status`
- `GET /api/architecture`
- `GET /api/health`
- `GET /api/uptime`
- `GET /api/scaffold/*` (status/raw/canonical/league/identity/validation/report)

### Auth/session endpoints (verified)
- `GET /api/auth/status`
- `POST /api/auth/login`
- `POST /api/auth/logout`
- `GET /logout`

### Auth-gated workspace routes (verified)
- `GET /app`
- `GET /rankings`
- `GET /trade`
- `GET /login`
- `GET /index.html`
- `GET /Static/index.html`

### Live landing -> League execution path (verified)
1. `GET /` serves `Static/landing.html`.
2. Landing "League" button navigates to `/league`.
3. `serve_league_entry` serves `Static/league/index.html` (public, no auth redirect).
4. `Static/league/league.js` handles section routing for `/league/*`.
5. `Static/league/league.js` fetches `/api/league/public`.

Status call:
- Route-level public vs private split: `complete`.
- Dedicated public-safe League API surface: `complete` for baseline summary scope.

## 3) Frontend architecture
### Static runtime (`Static/`) - live default
- `complete`: default runtime remains static.
- `complete`: dedicated public League shell now exists in `Static/league/*`.
- `complete`: all locked top-level League nav paths are routable in shell JS:
  - home, standings, franchises, awards, draft, trades, records, money,
    constitution, history, league-media.
- `partial`: most non-home tabs are scaffold modules pending deeper data wiring.

### Next runtime (`frontend/`) - optional and incomplete
- `partial`: Next app shell exists (`layout.jsx`, `page.jsx`, `rankings/page.jsx`,
  `trade/page.jsx`, `login/page.jsx`, API route).
- `partial`: current Next pages are lightweight migration surfaces (not full parity replacements for static runtime).
- `scaffolded only`: source route files for `frontend/app/league/*` are intentionally absent while backend remains League authority.
- `missing`: source route files for `frontend/app/calculator` remain absent.
- `safe-to-ignore local artifact`: `.next` can exist locally but is non-authoritative for runtime route ownership.

Status call:
- Public League implementation in static runtime: `complete` (scaffold level).
- Public League implementation in Next runtime: `scaffolded only / non-authoritative`.

## 4) Backend/API architecture
- `complete`: `/api/data` serves versioned contract payloads (`view=full|runtime|startup`).
- `complete`: in-memory payload pre-serialization + ETag/gzip for `/api/data`.
- `complete`: scraper scheduler/startup scrape live in `server.py`.
- `complete`: architecture truth endpoint exists (`/api/architecture`).
- `complete`: `/api/league/public` now provides a strict public-safe subset.
- `partial`: `/api/league/public` currently exposes summary-only context,
  not full tab-level historical datasets.

## 5) Storage and database approach
- `complete`: file-based storage for runtime payloads/exports
  (`data/dynasty_data_*.json`, CSVs, exports).
- `complete`: startup load from latest disk cache.
- `complete`: in-memory runtime state for payload/auth/scrape status.
- `partial`: SQL schema scaffold exists (`src/identity/migrations/0001_identity_schema.sql`)
  but no live DB-backed League Page domain storage.
- `missing`: authoritative DB-backed stores for constitution, money ledger,
  media posts, and deep history entities.

## 6) Public vs authenticated boundary findings
- `complete`: League routes are public and no longer login-gated.
- `complete`: Jason workspace routes remain auth-gated.
- `complete`: new `/api/league/public` intentionally excludes private
  valuation/calculator internals.
- `partial`: `/api/data` remains public and still contains private valuation and
  diagnostic internals; this is a residual boundary risk if non-League consumers
  treat `/api/data` as public-facing.

## 7) Where league-related logic already exists
- `complete`: Sleeper league context ingestion in `Dynasty Scraper.py`:
  teams, rosters, settings, roster slots, traded picks, rolling trade history.
- `complete`: public League shell logic in `Static/league/league.js`:
  route resolution, tab navigation, scaffold module status, public API consumption.
- `partial`: prior static runtime league-related features remain in
  `Static/js/runtime/40-runtime-features.js` but are tied to the private workspace app.
- `partial`: scaffold snapshot pipeline (`scripts/league_refresh.py`,
  `data/league/league_snapshot_*.json`) exists but is explicitly non-authoritative.

## 8) Sleeper and external API usage
### Sleeper endpoints used (verified in `Dynasty Scraper.py`)
- `https://api.sleeper.app/v1/players/nfl`
- `https://api.sleeper.app/v1/league/{league_id}`
- `https://api.sleeper.app/v1/league/{league_id}/rosters`
- `https://api.sleeper.app/v1/league/{league_id}/users`
- `https://api.sleeper.app/v1/league/{league_id}/drafts`
- `https://api.sleeper.app/v1/draft/{draft_id}`
- `https://api.sleeper.app/v1/league/{league_id}/traded_picks`
- `https://api.sleeper.app/v1/league/{league_id}/transactions/{week}`
- `https://api.sleeper.app/v1/stats/nfl/regular/{season}/{week}`

### Trade-history scope control
- `complete`: rolling window controlled by `SLEEPER_TRADE_HISTORY_DAYS` (default 365).

### Other external ingestion families (non-Sleeper)
- KTC, FantasyCalc, DynastyDaddy, FantasyPros, DraftSharks, Yahoo, DynastyNerds,
  IDPTradeCalc, optional Flock, plus local DLF CSV imports.

Status call:
- current league context ingestion: `partial` for full League history goals.
- deep historical reconstruction (standings/matchups/ownership): `missing`.

## 9) Where trade calculator logic currently lives
- `complete` (live runtime): static runtime modules
  - `Static/js/runtime/20-data-and-calculator.js`
  - `Static/js/runtime/30-more-surfaces.js`
  - `Static/js/runtime/40-runtime-features.js`
- `complete` (value pipeline): `Dynasty Scraper.py` + `src/api/data_contract.py`.
- `partial/missing` (Next trade runtime): `frontend/app/trade/page.jsx` exists but
  imports missing modules/components.

## 10) Summary status matrix
| Area | Status | Notes |
| --- | --- | --- |
| FastAPI backend host | `complete` | Live authority host. |
| Scraper -> API contract path | `complete` | `Dynasty Scraper.py -> data_contract -> /api/data`. |
| Static app runtime | `complete` | Default runtime mode. |
| Next runtime | `partial` | Optional mode, source/import gaps remain. |
| Landing -> League path | `complete` | Landing League choice now routes to public League shell. |
| Public League route scaffold | `complete` | `/league` + top-level nav routes are wired and usable. |
| Public-safe League API subset | `complete` | `/api/league/public` exists for summary context. |
| League historical data backbone | `missing` | No full standings/matchup/ownership history pipeline yet. |
| DB-backed League content stores | `missing` | No live constitution/money/media/history DB stores yet. |
| Data-level public/private hard boundary | `partial` | `/api/data` still exposes private internals if consumed directly. |
