# Repository Inventory — 2026-03-09

> **HISTORICAL SNAPSHOT (2026-03-09).** Not maintained; kept for provenance. Corrections of claims
> that read as current were added 2026-10-07 (CLEANUP-1) and are marked inline.
>
> **Current architecture (2026-10-07) — read these instead:** `CLAUDE.md` (legacy filename, universal
> technical runbook — "Frontend Runtime", "Live Value Pipeline"), `docs/ARCHITECTURE.md`, `README.md`.
> In one paragraph: Next.js serves every page; `server.py` is a FastAPI backend that registers **no page
> routes** since #555 (2026-07-31) and does not proxy Next; nginx routes `location /` to Next and
> `location /api/` to FastAPI (`deploy/nginx/chaseupside-proxy.conf`); `frontend/middleware.js` +
> `frontend/lib/public-routes.js` are the only page auth gate. The `Static/` frontend was removed
> 2026-04-09 (`4061800bf`). `Dynasty Scraper.py` is the production scraper. CI/CD is GitHub Actions
> (`.github/workflows/`); the live contract is `contractVersion = 2026-03-10.v2`
> (`src/api/data_contract.py`).

## High-level layout
```
.
├── codex_loop_config.example.json
├── codex_loop.py                     # legacy Codex helper
├── debug_loop.py                    # (removed since)
├── defs_scraper.txt                 # notes on current scraper actions (removed since)
├── dlf_*.csv                        # manually downloaded DLF data files (removed since)
├── Dynasty Scraper.py               # legacy scraping script — CORRECTED 2026-10-07: the PRODUCTION scraper
├── frontend/                        # Next.js + React client
├── funcs_index.txt                  # (removed since)
├── inspect_dlf_csvs.py              # CSV inspector utility (removed since)
├── players.txt / rookie_must_have.txt
├── scripts/                         # PowerShell + Python helpers
├── server.py                        # FastAPI/Flask-style backend (serves API + proxies Next) — CORRECTED: API only since #555
├── start_*.bat + run_scraper.bat    # Windows helpers
├── Static/                          # legacy static dashboard assets — REMOVED 2026-04-09 (`4061800bf`)
└── README.md
```

## Legacy components
| Component | Description | Status | Notes |
| --- | --- | --- | --- |
| `Dynasty Scraper.py` | Older scraping logic, uses Selenium/requests to pull rankings. | Legacy — **CORRECTED 2026-10-07: the production scraper** (imported by `server.py`; `scheduled-refresh.yml` every 2h) | Will mine for adapter hints but ultimate goal is modular adapters under `src/adapters`. |
| `server.py` | Python backend that proxies Next, serves API, hits CSV data. **CORRECTED 2026-10-07:** API only; no page routes or Next proxy since #555. | Legacy (active production) — now the canonical production backend | Remains the sole production backend until canonical engine + league context engine are wired in and validated. No replacement timeline set. |
| `frontend/` | Next.js app with calculator UI. | Keep / evolve | Will hook into new API endpoints once canonical engine exists. |
| `Static/` | Old static HTML dashboards. | Sunset later — **REMOVED 2026-04-09** (`4061800bf`) | Useful as fallback if Next/server offline. **CORRECTED: there is no fallback frontend.** |
| `scripts/` | Jenkins helper, sync script, trigger script. | Keep, update | Will update once new CI stages defined. (CI is now GitHub Actions.) |
| `dlf_*.csv` | Manual exports of DLF rankings (superflex, IDP, rookies). | Seed data | Move into `data/raw/dlf/` under new pipeline for reproducibility. |

## New structure to introduce
```
src/
  adapters/          # source importers (DLF CSV, KTC scraper, etc.)
  identity/          # master player/pick mapping utilities
  canonical/         # percentile/curve/blending logic
  league/            # placeholder (scarcity + replacement removed)
  api/               # new FastAPI service exposing calculator + rankings
  data_models/       # Pydantic models / schemas
  utils/

config/
  sources/
  leagues/
  weights/

data/
  raw/
  processed/
  snapshots/
```

## Immediate actions derived from inventory
1. Preserve `frontend`, `server.py`, and existing scripts so current workflow keeps working while new engine spins up.
2. Relocate CSV inputs into a structured `data/raw/` tree with metadata.
3. Stand up `/src` scaffolding with placeholder modules + README for adapters/canonical/league layers.
4. Document how current backend reads/writes data so we know where to intercept with canonical outputs.

## Runtime Authority (HISTORICAL — superseded)

**CURRENT (2026-10-07):** Next.js serves every page; nginx `location /` → Next, `location /api/` →
FastAPI; `server.py` has no page routes since #555 (2026-07-31). The `FRONTEND_RUNTIME`
static/next/auto switch described below was removed. *Historical text follows.*

- Authoritative production frontend runtime is now controlled by `FRONTEND_RUNTIME` in `server.py`.
- Current default is `static` unless explicitly overridden.
- Runtime modes:
  - `static`: serves `Static/index.html` intentionally.
  - `next`: proxies Next only; no silent fallback to static.
  - `auto`: tries Next and explicitly falls back to static with status visibility.

## Backend Data Contract (HISTORICAL — superseded)

**CURRENT (2026-10-07):** `contractVersion = 2026-03-10.v2`; validated by
`scripts/validate_api_contract.py` (structural / full lanes) in GitHub Actions, not Jenkins; there
is no Static app to keep compatible. *Historical text follows.*

- `/api/data` now serves a versioned contract with `contractVersion = 2026-03-09.v1`.
- Legacy compatibility remains in place (`players` object map, `maxValues`, etc.) for Static app continuity.
- Normalized contract additions include:
  - `playersArray` (stable player list shape)
  - `dataSource` metadata
  - `contractHealth` summary
- Contract validation is enforced via runtime diagnostics (`/api/status`) and CI (`scripts/validate_api_contract.py` in Jenkins).

~~This doc will be kept up to date as we migrate functionality into the new architecture.~~ It was not;
see the current-architecture pointer block at the top.
