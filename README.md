# Risk It To Get The Brisket — Dynasty Trade Calculator

Private repo for the dynasty trade calculator stack powering
[riskittogetthebrisket.org](https://riskittogetthebrisket.org).

**Architecture at a glance:**
- **Backend:** Python 3.12 FastAPI + Uvicorn (port 8000).
- **Frontend:** Next.js 15 + React 19 App Router (port 3000).
- **Multi-league:** configurable via `config/leagues/registry.json`;
  scoring profile drives rankings, league key drives context
  (teams / trades / draft capital).
- **Auth model:** session-gated `/api/*` endpoints with a
  Sleeper-login allowlist; public routes hit `/api/public/league/*`.
- **Feature flags** (`src/api/feature_flags.py`): every new
  capability from the 2026-04 upgrade ships flag-gated (default OFF).

**Orientation docs:**
- [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) — system map
- [`docs/ONBOARDING.md`](docs/ONBOARDING.md) — how to add a league / source / flag
- [`docs/upgrade_phases_1_10.md`](docs/upgrade_phases_1_10.md) — April 2026 upgrade deep-dive
- [`CLAUDE.md`](CLAUDE.md) — architectural rules + non-negotiables

## Production Bootstrap

For first-time server setup and deploy hardening, use:
- `deploy/PRODUCTION_BOOTSTRAP.md`
- `deploy/bootstrap-production.sh`

## Environment Setup (Linux / macOS / WSL)

**Single source of truth for Python deps.** Local dev, CI, and production
all install from the same two manifests:

- `requirements.txt` — runtime deps (what the server + scrapers need).
- `requirements-dev.txt` — chains in `requirements.txt` via `-r` and adds
  test-only deps (`pytest`, `httpx` for `fastapi.testclient`).

One-command bootstrap on a clean checkout:

```bash
make setup        # creates .venv, installs runtime + dev deps, runs preflight
make test         # runs pytest exactly like CI does
```

`make setup` wraps `scripts/setup.sh`, which:

1. Creates a `.venv/` virtualenv (so nothing leaks from the system Python).
2. Installs `requirements-dev.txt` into it.
3. Runs `pip check` — fails fast on conflicting pins.
4. Runs `scripts/check_env.py` — validates every expected module imports.
5. Installs the Playwright Chromium browser (set `SKIP_PLAYWRIGHT=1` to skip).

If `make test` passes on your machine, it will pass in CI — every
workflow runs the same install + preflight path (`pip install -r
requirements-dev.txt && pip check && python scripts/check_env.py`).

## Quick Start (Windows / PowerShell)

### 1) Install frontend deps once
```powershell
cd .\frontend
npm install
cd ..
```

### 2) Run backend server (scraper + API)
```powershell
python .\server.py
```
Backend API:
- `GET /api/data`
- `GET /api/status`
- `POST /api/scrape`

### 3) Run Next frontend (separate terminal)
```powershell
cd .\frontend
npm run dev
```
Frontend:
- [http://localhost:3000](http://localhost:3000)

## Regression Harness (Desktop + Mobile)

Automated parity/smoke suite targets the live runtime (`server.py` + `Static/index.html`) across:
- desktop `1366x768`
- mobile `390x844`
- mobile large `430x932`

One-time setup:
```powershell
npm install
npm run regression:install
```

Run full gate (Python compile + API contract + Playwright regression):
```powershell
npm run regression
```

Run browser suite only:
```powershell
npm run regression:test
```

## Server Linking (Backend <-> Frontend)

This repo is now wired so both sides can work together:

1. **Next API route prefers backend data first**
   - `frontend/app/api/dynasty-data/route.js`
   - Tries backend `http://127.0.0.1:8000/api/data` first
   - Falls back to local `dynasty_data_YYYY-MM-DD.json` / `dynasty_data.js`

2. **Python server runtime proxies to Next.js**
   - `server.py`
   - `FRONTEND_RUNTIME` is hardcoded to `next` — all page routes proxy to the Next.js frontend
   - No legacy Static fallback exists

### Optional env vars
- `FRONTEND_URL=http://127.0.0.1:3000`
- `ENABLE_NEXT_FRONTEND_PROXY=true|false` (legacy/deprecated)
- `BACKEND_API_URL=http://127.0.0.1:8000/api/data` (for Next route)
- `SLEEPER_LEAGUE_ID=1312006700437352448` (canonical main league ID for backend scraper)
- `BASELINE_LEAGUE_ID=1328545898812170240` (canonical baseline league for comparison)

### `/api/data` contract
- `/api/data` is now versioned (`contractVersion=2026-03-09.v1`)
- Preserves legacy compatibility fields (`players` map, `maxValues`, etc.)
- Adds normalized stable fields (`playersArray`, `dataSource`, `contractHealth`)
- Runtime + CI validation:
  - runtime surfaced in `GET /api/status`
  - CI check via `scripts/validate_api_contract.py`

## One-click helpers
- `start_dynasty.bat` → starts Python server
- `start_frontend.bat` → starts Next dev server
- `start_stack.bat` → starts backend + frontend together (separate terminal windows)
- `sync.bat` → git add + commit + push on current branch (no-op safe if nothing changed)
- `run_scraper.bat` → runs scraper + debug loop

Example:
```powershell
.\sync.bat "Update rankings + trade UX"
```

## Canonical Scaffold (Phase 0/1)

New modular scaffold lives under `src/` with config templates under `config/`.

Run the scaffold pipeline:

```powershell
python .\scripts\source_pull.py --repo .
python .\scripts\validate_ingest.py --repo .
python .\scripts\identity_resolve.py --repo .
python .\scripts\canonical_build.py --repo .
python .\scripts\league_refresh.py --repo .
python .\scripts\reporting.py --repo .
```

Outputs:
- `data/raw_sources/raw_source_snapshot_*.json`
- `data/validation/ingest_validation_*.json`
- `data/identity/identity_resolution_*.json`
- `data/canonical/canonical_snapshot_*.json`
- `data/validation/canonical_validation_*.json`
- `data/league/league_snapshot_*.json`
- `data/reports/ops_report_*.md`

Scaffold API endpoints (served by `server.py`):
- `GET /api/scaffold/status`
- `GET /api/scaffold/raw`
- `GET /api/scaffold/canonical`
- `GET /api/scaffold/league`
- `GET /api/scaffold/identity`
- `GET /api/scaffold/validation`
- `GET /api/scaffold/report`

## Jenkins Lockstep

This repo now includes a root `Jenkinsfile` so Jenkins can build exactly what is on `main`.

### Optional: trigger Jenkins automatically after `sync.bat`
Set these env vars once in PowerShell:

```powershell
[Environment]::SetEnvironmentVariable("JENKINS_TRIGGER_URL","https://<jenkins-host>/job/<job-name>/buildWithParameters","User")
[Environment]::SetEnvironmentVariable("JENKINS_USER","<jenkins-username>","User")
[Environment]::SetEnvironmentVariable("JENKINS_API_TOKEN","<jenkins-api-token>","User")
```

Then `.\sync.bat "message"` will:
1. commit
2. push
3. trigger Jenkins via `scripts/trigger_jenkins.py`

If your Jenkins does not require auth, only `JENKINS_TRIGGER_URL` is needed.

Quick verify command:
```powershell
.\scripts\verify_lockstep.ps1
```

Full setup + operating checklist:
- `LOCKSTEP_SETUP.md`

## GitHub
Remote:
- `origin = https://github.com/jasonleetucker-code/riskittogetthebrisket.git`

Initial push done on branch `main`.
