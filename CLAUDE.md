# CLAUDE.md — Risk It To Get The Brisket

## Project Overview

Dynasty fantasy football valuation and trade calculator platform. Ingests external rankings sources (DLF, KTC, FantasyCalc, DynastyDaddy, etc.), normalizes them to a canonical scale, applies league-specific adjustments, and serves a web UI for trade analysis and rankings.

## Tech Stack

- **Backend**: Python 3, FastAPI, Uvicorn (port 8000)
- **Frontend**: Next.js 15 + React 19 (port 3000)
- **Scraping**: Playwright (browser automation), legacy Selenium/requests (`Dynasty Scraper.py`)
- **CI/CD**: GitHub Actions (`.github/workflows/`)
- **Testing**: pytest (unit/integration), Playwright E2E regression
- **Platform**: Windows (primary dev via `.bat` files), Linux/Unix (production + CI)

## Directory Structure

```
├── server.py                  # FastAPI backend entry point
├── Dynasty Scraper.py         # Legacy scraper (Selenium/requests)
├── .github/workflows/         # GitHub Actions CI/CD pipelines
│
├── frontend/                  # Next.js app (App Router)
│   ├── app/                   # Pages: rankings/, trade/, login/
│   │   └── api/dynasty-data/  # Backend data bridge route
│   ├── components/            # React components + hooks
│   └── lib/                   # Data utilities
│
├── src/                       # Modular canonical engine
│   ├── adapters/              # Source ingestion (DLF CSV, KTC stub, manual CSV)
│   ├── api/                   # API data contract (versioned)
│   ├── canonical/             # Core valuation pipeline + player_valuation.py
│   ├── identity/              # Player/pick master identity mapping
│   ├── scoring/               # Scoring adjustments, archetypes, backtesting
│   ├── league/                # League context: replacement baselines, scarcity
│   ├── trade/                 # Trade engines: suggestions + KTC arbitrage finder
│   ├── data_models/           # Dataclass contracts
│   └── utils/                 # Config loading, name/position normalization
│
├── config/
│   ├── sources/               # Source ingestion templates
│   ├── weights/               # Source blending weights
│   ├── leagues/               # League profile templates
│   └── promotion/             # Canonical mode promotion thresholds
│
├── scripts/                   # Pipeline helper scripts (canonical_build, etc.)
├── deploy/                    # Deployment configs (nginx, systemd, deploy scripts)
├── tests/                     # pytest unit/integration + Playwright E2E
├── data/                      # Generated pipeline outputs (not committed)
├── exports/                   # Release artifacts (latest/ + archive/)
└── docs/                      # Architecture blueprints, status docs
```

## Key Commands

### Starting the Stack

```powershell
.\start_dynasty.bat          # Start Python backend (port 8000)
.\start_frontend.bat         # Start Next.js dev server (port 3000)
.\start_stack.bat            # Start both in separate windows
```

### Testing & Validation

```bash
# Python tests (primary test suite)
python -m pytest tests/ -q

# E2E regression
npm install                          # Install root + frontend deps
npm run regression:install           # Install Playwright browsers (one-time)
npm run regression                   # Full pipeline: preflight + tests
```

### Build Pipeline

```bash
# Legacy engine (default)
python scripts/canonical_build.py --repo .

# Canonical engine (6-step rank-based valuation)
python scripts/canonical_build.py --repo . --engine canonical
```

### Git Workflow

```powershell
.\sync.bat "commit message"          # Git add, commit, push
```

## API Endpoints

| Endpoint | Method | Purpose |
|---|---|---|
| `/api/data` | GET | Main player data (versioned contract `2026-03-10.v2`) |
| `/api/status` | GET | Server status + runtime info |
| `/api/health` | GET | Uptime health check |
| `/api/scrape` | POST | Trigger manual scrape |
| `/api/scaffold/status` | GET | Pipeline status |
| `/api/scaffold/raw` | GET | Raw source snapshots |
| `/api/scaffold/canonical` | GET | Canonical values |
| `/api/scaffold/identity` | GET | Identity mappings |

## Architecture Concepts

### Frontend Runtime
Next.js is the sole production frontend. `FRONTEND_RUNTIME` is hardcoded to `next` in server.py — all page routes proxy to Next.js at port 3000. Returns 503 if Next is down; there is no Static fallback.

Production deployment requires both `dynasty.service` (backend) and `dynasty-frontend.service` (Next.js) running.

### Multi-Universe Value Pipeline
Separate canonical value chains for: offense vet, offense rookie, IDP vet, IDP rookie, picks. Each has independent source blending, percentile transforms, and calibration.

### Canonical Player Valuation
The new 6-step rank-based engine (`src/canonical/player_valuation.py`):
1. **Consensus rank** — weighted median/mean of per-source ranks
2. **Tier detection** — gap-based clustering into natural value tiers
3. **Base value curve** — exponential decay from consensus rank
4. **Tier cliff injection** — bonus points at tier boundaries
5. **Volatility adjustment** — compresses values for high-disagreement players
6. **Display scaling** — stable 1-9999 mapping via hyperparameter-derived anchor

Selected via `--engine canonical` in `scripts/canonical_build.py`. Default remains `--engine legacy`.

### Trade Engines
Two independent trade suggestion systems in `src/trade/`:
- **suggestions.py** — roster-aware trade suggestions (sell-high, buy-low, consolidation, upgrades)
- **finder.py** — KTC arbitrage finder (board value vs market value mismatches)

Both enforce a **KTC top-150 quality filter**: only players ranked inside the top 150 appear in any trade suggestion.

### Canonical Data Mode
Controlled by `CANONICAL_DATA_MODE` env var (`off` | `shadow` | `internal_primary` | `primary`). Allows gradual rollout of canonical values alongside legacy scraper values.

### Adapter Pattern
Pluggable source adapters (`src/adapters/base.py` defines the frozen contract). All adapters emit `RawAssetRecord` dataclasses with normalized fields. Current adapters: DLF CSV, KTC stub, manual CSV, scraper bridge.

### Position Normalization
Single source of truth: `POSITION_ALIASES` in `src/utils/name_clean.py`. All modules import from there.

### Deployment
Production runs on a Hetzner VPS with nginx reverse proxy, systemd service, and Let's Encrypt SSL. See `deploy/` directory.

## Non-Negotiable Rules

1. **Do not assume features work** — trace the live execution path end-to-end before claiming anything is implemented
2. **Prefer modifying existing architecture** over introducing parallel systems
3. **Preserve working behavior** unless a verified flaw requires change
4. **Verify downstream effects** for any value/ranking change across UI rendering, sorting, filtering, exports, and league-specific transforms
5. **Verify the full pipeline** for any scraper/source change: ingestion -> normalization -> merge -> fallback -> frontend consumption
6. **Call out anything** mocked, bypassed, stale, duplicated, half-wired, dead, or missing
7. **Smallest correct change set** — read relevant files first, identify the real live path, make minimal changes, run validation, report what changed and what remains uncertain

## Performance Rules

- Prioritize page-load speed and perceived responsiveness
- Reduce blocking work on initial load
- Eliminate duplicated calculations, repeated fetches, oversized payloads
- Prefer memoization, batching, precomputation, caching, lazy loading where justified
- Do not sacrifice correctness for speed

## Coding Conventions

### Python
- Type hints with `from __future__ import annotations`
- Dataclasses for models, Pydantic for API contracts
- `pathlib.Path` for file operations
- ISO 8601 UTC timestamps (`datetime.now(timezone.utc).isoformat()`)
- `argparse` for script CLI arguments
- Exit codes for script success/failure

### JavaScript / React
- Next.js App Router (no pages directory)
- React hooks for state management
- Named exports from modules

### General
- Configuration via JSON templates in `config/`
- Environment variables via `.env` (see `.env.example`)
- Markdown for all documentation
- Versioned API contracts (e.g., `2026-03-10.v2`)

## Environment Variables

Key variables (see `.env.example` for full list):

| Variable | Purpose | Default |
|---|---|---|
| `FRONTEND_RUNTIME` | `next` (hardcoded) | `next` |
| `FRONTEND_URL` | Next.js dev server URL | `http://127.0.0.1:3000` |
| `CANONICAL_DATA_MODE` | Canonical rollout mode | `off` |
| `SLEEPER_LEAGUE_ID` | Primary Sleeper league | -- |
| `BASELINE_LEAGUE_ID` | Baseline comparison league | -- |

## Safety

- Do not exfiltrate private data
- Do not run destructive commands without approval
- Prefer reversible operations
- Be explicit before any action affecting production, deployment, credentials, or public output
