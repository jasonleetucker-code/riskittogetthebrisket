# CLAUDE.md — Risk It To Get The Brisket

## Project Overview

Dynasty fantasy football valuation and trade calculator platform. Ingests external rankings sources (DLF, KTC), normalizes them to a canonical scale, applies league-specific adjustments, and serves a web UI for trade analysis and rankings.

## Tech Stack

- **Backend**: Python 3, FastAPI, Uvicorn (port 8000)
- **Frontend**: Next.js 15 + React 19 (port 3000), with static HTML fallback (`Static/`)
- **Scraping**: Playwright (browser automation), legacy Selenium/requests (`Dynasty Scraper.py`)
- **CI/CD**: Jenkins (see `Jenkinsfile`)
- **Testing**: Playwright E2E regression, Python unit tests
- **Platform**: Windows (primary dev via `.bat` files), Linux/Unix (Jenkins CI)

## Directory Structure

```
├── server.py                  # FastAPI backend entry point
├── Dynasty Scraper.py         # Legacy scraper (~500KB, Selenium/requests)
├── codex_loop.py              # Codex agent audit helper
├── debug_loop.py              # Continuous smoke/debug testing loop
├── Jenkinsfile                # CI/CD pipeline (cross-platform)
│
├── frontend/                  # Next.js app (App Router)
│   ├── app/                   # Pages: rankings/, trade/, login/
│   │   └── api/dynasty-data/  # Backend data bridge route
│   ├── components/            # React components + hooks
│   └── lib/                   # Data utilities
│
├── src/                       # Modular canonical engine (Phase 0/1)
│   ├── adapters/              # Source ingestion (DLF CSV, KTC stub, manual CSV)
│   ├── api/                   # API data contract (versioned)
│   ├── canonical/             # Core valuation pipeline
│   ├── identity/              # Player/pick master identity mapping
│   ├── scoring/               # Scoring adjustments, archetypes, backtesting
│   ├── league/                # League context + scarcity (placeholder)
│   ├── data_models/           # Pydantic dataclass contracts
│   └── utils/                 # Config loading, name normalization
│
├── config/
│   ├── sources/               # Source ingestion templates
│   ├── weights/               # Source blending weights
│   └── leagues/               # League profile templates
│
├── scripts/                   # Jenkins pipeline helper scripts
├── tests/
│   ├── e2e/                   # Playwright regression (desktop + mobile)
│   └── scoring/               # Scoring module unit tests
│
├── data/                      # Generated pipeline outputs (not committed)
├── exports/                   # Release artifacts (latest/ + archive/)
├── Static/                    # Legacy static HTML fallback dashboard
├── docs/                      # Architecture blueprints, audit docs
└── .agents/skills/            # Codex agent skill definitions
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
npm install                          # Install root + frontend deps
npm run regression:install           # Install Playwright browsers (one-time)
npm run regression:preflight         # Python compile check + API contract validation
npm run regression:test              # Run Playwright E2E tests
npm run regression                   # Full pipeline: preflight + tests
```

### Git Workflow

```powershell
.\sync.bat "commit message"          # Git add, commit, push + optional Jenkins trigger
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

### Dual Runtime Frontend
Controlled by `FRONTEND_RUNTIME` env var:
- **static** (default): Serves `Static/index.html` directly from FastAPI
- **next**: Proxies to Next.js dev server at port 3000
- **auto**: Tries Next, falls back to static

### Multi-Universe Value Pipeline
Separate canonical value chains for: offense vet, offense rookie, IDP vet, IDP rookie, picks. Each has independent source blending, percentile transforms, and calibration.

### Adapter Pattern
Pluggable source adapters (`src/adapters/base.py` defines the frozen contract). All adapters emit `RawAssetRecord` dataclasses with normalized fields. Current adapters: DLF CSV, KTC stub, manual CSV.

### Jenkins Pipeline Stages
Checkout → Ingest → Validate → Identity Resolve → Canonical Build → League Refresh → Report → Backend Smoke → API Contract → Frontend Build → Regression Harness

## Non-Negotiable Rules

These rules from `AGENTS.md` must always be followed:

1. **Do not assume features work** — trace the live execution path end-to-end before claiming anything is implemented
2. **Prefer modifying existing architecture** over introducing parallel systems
3. **Preserve working behavior** unless a verified flaw requires change
4. **Verify downstream effects** for any value/ranking change across UI rendering, sorting, filtering, exports, and league-specific transforms
5. **Verify the full pipeline** for any scraper/source change: ingestion → normalization → merge → fallback → frontend consumption
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
| `FRONTEND_RUNTIME` | `static\|next\|auto` | `static` |
| `FRONTEND_URL` | Next.js dev server URL | `http://127.0.0.1:3000` |
| `CANONICAL_DATA_DIR` | Data directory override | `<repo>/data` |
| `SLEEPER_LEAGUE_ID` | Primary Sleeper league | — |
| `BASELINE_LEAGUE_ID` | Baseline comparison league | — |

## Safety

- Do not exfiltrate private data
- Do not run destructive commands without approval
- Prefer reversible operations
- Be explicit before any action affecting production, deployment, credentials, or public output
