# Risk It To Get The Brisket — Dynasty Trade Calculator

Private repo for your dynasty trade calculator stack:
- Python scraper + API server
- Legacy static dashboard
- New React + Next.js frontend (`frontend/`)

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
- tablet `820x1180`

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

Release gate smoke only:
```powershell
npm run regression:test:smoke:release
```

Current CI release gate expects:
- `desktop-1366`
- `mobile-390`
- `tablet-820`


## Automation (Production)

Runtime automation is now split into lightweight frequent checks and heavier staggered checks:

1. Server-side recurring scrape scheduler (`server.py`)
   - Default full refresh cadence: every `4` hours (`SCRAPE_INTERVAL_HOURS`)
   - Adds jitter (`SCRAPE_INTERVAL_JITTER_MINUTES=10`) to avoid synchronized hammering
   - Adds failure backoff (`SCRAPE_FAILURE_BACKOFF_MINUTES=60`, capped by `SCRAPE_MAX_BACKOFF_HOURS=12`)
   - Startup scrape runs once on boot by default (`SCRAPE_STARTUP_ENABLED=true`)

2. Server-side watchdog + health
   - External uptime watchdog loop (default every `300s`)
   - `/api/health` now degrades if scrape age exceeds `MAX_HEALTHY_SCRAPE_AGE_HOURS` (default `10`)
   - Promotion gate + last-known-good payload fallback remain active

3. GitHub Actions automation
   - `deploy.yml`: deploys on real code changes (`push` to `main`) + manual dispatch
     - includes semantic ratchet gate (`scripts/semantic_ratchet_gate.py`)
     - includes critical value/trade API tests (`scripts/run_critical_api_tests.py`)
   - `runtime-health.yml`: lightweight runtime health/freshness check hourly
   - `runtime-smoke.yml`: route/auth/runtime smoke check every 12 hours
   - `weekly-deep-audit.yml`: weekly deeper regression/unit audit + semantic/value-trade ratchet pass

4. Machine-readable probe reports
   - `scripts/runtime_probe.py` powers deploy-time and scheduled runtime checks
   - Probe artifacts are uploaded on each workflow run

Status endpoints to monitor:
- `GET /api/health`
- `GET /api/status`
- `GET /api/validation/operator-report`
- `GET /api/validation/promotion-gate`
- `GET /api/runtime/route-authority`

## Server Linking (Backend <-> Frontend)

This repo is now wired so both sides can work together:

1. **Next API route prefers backend data first**
   - `frontend/app/api/dynasty-data/route.js`
   - Tries backend `http://127.0.0.1:8000/api/data` first
   - Falls back to local `dynasty_data_YYYY-MM-DD.json` / `dynasty_data.js`

2. **Python server runtime is explicit (`FRONTEND_RUNTIME`)**
   - `server.py`
   - `FRONTEND_RUNTIME=static` (default): serves legacy static app intentionally
   - `FRONTEND_RUNTIME=next`: proxies Next intentionally (no silent static fallback)
   - `FRONTEND_RUNTIME=auto`: tries Next first, then explicit static fallback

3. **Status polling has a compact mode for UI performance**
   - `GET /api/status?compact=1`
   - Returns only high-frequency fields used by the dashboard polling loop
   - Full diagnostics remain on `GET /api/status` and validation endpoints

## Runtime Route Authority (Live)

Critical route authority is now explicit in both docs and runtime responses.

- Canonical doc: `docs/RUNTIME_ROUTE_AUTHORITY.md`
- Frontend artifact register: `docs/frontend/non-authoritative-artifacts.md`
- Machine-readable map: `GET /api/runtime/route-authority`
- Response headers on critical routes:
  - `X-Route-Authority`
  - `X-Route-Id`
  - `X-Frontend-Runtime-Configured`
  - `X-Frontend-Runtime-Active`

Important:
- `frontend/.next` artifacts are not route authority by themselves.
- `/league` and `/league/*` are owned by FastAPI public shell authority and never proxy to Next.
- Primary authority is `public-static-league-shell`.
- If League static artifacts are missing, runtime uses explicit fallback authority
  `public-league-inline-fallback-shell` (no raw 500).
- Deploy verify now checks League shell readiness via `/api/runtime/route-authority`
  (`STRICT_LEAGUE_SHELL_READINESS=true` by default in `deploy/verify-deploy.sh`).
- Deploy/CI also enforce source-control truth for full League UX artifacts:
  - `Static/league/index.html`
  - `Static/league/league.css`
  - `Static/league/league.js`
  Untracked shell files are treated as deploy-blocking in strict mode.

### Operator Route Ownership (Simple)
| Route | Public/private | Served by |
| --- | --- | --- |
| `/` | Public | `server.py` -> `serve_landing` (static landing shell) |
| `/league` and `/league/*` | Public | `server.py` -> `serve_league_entry` (static League shell or inline fallback) |
| `/app` | Auth-gated | `server.py` -> `serve_dashboard` -> `_serve_app_shell` |
| `/rankings` | Auth-gated | `server.py` -> `serve_rankings` -> `_serve_app_shell` |
| `/trade` | Auth-gated | `server.py` -> `serve_trade` -> `_serve_app_shell` |
| `/calculator` | Auth-gated alias | `server.py` -> `serve_calculator` -> redirects to `/trade` |

### What `FRONTEND_RUNTIME` Affects (and Does Not)
- It affects private app-shell resolution for `/app`, `/rankings`, `/trade`:
  - `static`: private static shell
  - `next`: Next proxy only (503 if Next unavailable)
  - `auto`: try Next, then explicit static fallback
- `/calculator` is a compatibility alias only; it authenticates like other private routes and then redirects to `/trade`.
- It does **not** change ownership of:
  - `/` (always backend static landing authority)
  - `/league` and `/league/*` (always backend public League authority)

### Optional env vars
- `FRONTEND_RUNTIME=static|next|auto` (default `static`)
- `FRONTEND_URL=http://127.0.0.1:3000`
- `ENABLE_NEXT_FRONTEND_PROXY=true|false` (legacy/deprecated)
- `BACKEND_API_URL=http://127.0.0.1:8000/api/data` (for Next route)
- `SLEEPER_LEAGUE_ID=1312006700437352448` (canonical main league ID for backend scraper)
- `BASELINE_LEAGUE_ID=1328545898812170240` (canonical baseline league for scoring/LAM comparison)
- `JASON_LOGIN_USERNAME=jasonleetucker` (private route username)
- `JASON_LOGIN_PASSWORD=<required>` (private route password; `/api/auth/login` returns `503` when missing)

### `/api/data` contract
- `/api/data` is versioned (resolver constant: `src/api/data_contract.py::CONTRACT_VERSION`)
- Preserves legacy Static compatibility fields (`players` map, `maxValues`, etc.)
- Adds normalized stable fields (`playersArray`, `dataSource`, `contractHealth`)
- Runtime + CI validation:
  - runtime surfaced in `GET /api/status`
  - CI check via `scripts/validate_api_contract.py`

## Runtime Authority Truth (Current)

- `Authoritative live path`:
  - `Dynasty Scraper.py` produces live player payload.
  - `server.py` calls `src.api.data_contract.build_api_data_contract(...)`.
  - `/api/data` is the runtime source of truth for live values.
- `Also live from src/`:
  - `src/scoring/*` is used by `Dynasty Scraper.py` when available.
- `Not authoritative for live runtime yet`:
  - `src/adapters`, `src/identity`, `src/canonical`, `src/league` pipelines.
  - `scripts/source_pull.py`, `scripts/identity_resolve.py`, `scripts/canonical_build.py`, `scripts/league_refresh.py`.
  - `/api/scaffold/*` endpoints are diagnostics/scaffold snapshots only.

You can inspect this directly at:
- `GET /api/status` → `architecture`
- `GET /api/architecture`

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
This scaffold pipeline is useful for diagnostics and migration work, but it is
not the live runtime authority for `/api/data` yet.

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

## Mike Clay Offseason Import

Dedicated offseason guide ingestion now lives in:
- `src/offseason/mike_clay/parser.py`
- `src/offseason/mike_clay/matcher.py`
- `src/offseason/mike_clay/pipeline.py`
- CLI: `scripts/import_mike_clay.py`

Run:

```powershell
python .\scripts\import_mike_clay.py --pdf .\data\imports\mike_clay\NFLDK2026_CS_ClayProjections2026.pdf
```

Outputs:
- run artifacts under `data/imports/mike_clay/<guide_year>/mike_clay_<guide_year>_<timestamp>/`
- latest status pointers:
  - `data/imports/mike_clay/mike_clay_import_latest.json`
  - `data/validation/mike_clay_import_status_latest.json`

Full workflow and artifact contract:
- `docs/offseason/MIKE_CLAY_IMPORT_PIPELINE.md`
- Live offseason value-layer integration details:
  - `docs/offseason/MIKE_CLAY_VALUE_INTEGRATION.md`

### Mike Clay Runtime Controls
- Config: `config/mike_clay_integration.json`
- Seasonal gate source of truth: `seasonWindowsByYear.<guide_year>`
  - Example:
    ```json
    {
      "seasonWindowsByYear": {
        "2026": {
          "offseasonStartDate": "2026-01-15",
          "week1StartDate": "2026-09-10",
          "week1EndDate": "2026-09-14"
        }
      }
    }
    ```
  - Missing or malformed year windows fail safe to inactive (no implicit date defaults).
- Optional env overrides:
  - `MIKE_CLAY_ENABLED`
  - `MIKE_CLAY_INTEGRATION_CONFIG`
  - `MIKE_CLAY_IMPORT_LATEST_PATH`
  - `MIKE_CLAY_FORCE_PHASE`
  - `MIKE_CLAY_FORCE_WEIGHT`

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
