# Repository Inventory — 2026-03-09

## High-level layout
```
.
├── codex_loop_config.example.json
├── codex_loop.py                     # legacy Codex helper
├── debug_loop.py
├── defs_scraper.txt                 # notes on current scraper actions
├── dlf_*.csv                        # manually downloaded DLF data files
├── Dynasty Scraper.py               # legacy scraping script
├── frontend/                        # Next.js + React client
├── funcs_index.txt
├── inspect_dlf_csvs.py              # CSV inspector utility
├── players.txt / rookie_must_have.txt
├── scripts/                         # PowerShell + Python helpers
├── server.py                        # FastAPI/Flask-style backend (serves API + proxies Next)
├── start_*.bat + run_scraper.bat    # Windows helpers
├── Static/                          # legacy static dashboard assets
└── README.md
```

## Legacy components
| Component | Description | Status | Notes |
| --- | --- | --- | --- |
| `Dynasty Scraper.py` | Older scraping logic, uses Selenium/requests to pull rankings. | Legacy | Will mine for adapter hints but ultimate goal is modular adapters under `src/adapters`. |
| `server.py` | Python backend that proxies Next, serves API, hits CSV data. | Legacy (to be replaced) | Keep running until new API ready; treat as fallback. |
| `frontend/` | Next.js app with calculator UI. | Keep / evolve | Will hook into new API endpoints once canonical engine exists. |
| `Static/` | Old static HTML dashboards. | Sunset later | Useful as fallback if Next/server offline. |
| `scripts/` | Jenkins helper, sync script, trigger script. | Keep, update | Will update once new CI stages defined. |
| `dlf_*.csv` | Manual exports of DLF rankings (superflex, IDP, rookies). | Seed data | Move into `data/raw/dlf/` under new pipeline for reproducibility. |

## New structure to introduce
```
src/
  adapters/          # source importers (DLF CSV, KTC scraper, etc.)
  identity/          # master player/pick mapping utilities
  canonical/         # percentile/curve/blending logic
  league/            # scoring + scarcity + replacement engine
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

## Runtime Authority (Current, Live)
- Authoritative production frontend runtime is now controlled by `FRONTEND_RUNTIME` in `server.py`.
- Current default is `static` unless explicitly overridden.
- Runtime modes:
  - `static`: serves `Static/index.html` intentionally.
  - `next`: proxies Next only; no silent fallback to static.
  - `auto`: tries Next and explicitly falls back to static with status visibility.

## Backend Data Contract (Current, Live)
- `/api/data` now serves a versioned contract with `contractVersion = 2026-03-09.v1`.
- Legacy compatibility remains in place (`players` object map, `maxValues`, etc.) for Static app continuity.
- Normalized contract additions include:
  - `playersArray` (stable player list shape)
  - `dataSource` metadata
  - `contractHealth` summary
- Contract validation is enforced via runtime diagnostics (`/api/status`) and CI (`scripts/validate_api_contract.py` in Jenkins).

This doc will be kept up to date as we migrate functionality into the new architecture.
