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

## Server Linking (Backend <-> Frontend)

This repo is now wired so both sides can work together:

1. **Next API route prefers backend data first**
   - `frontend/app/api/dynasty-data/route.js`
   - Tries backend `http://127.0.0.1:8000/api/data` first
   - Falls back to local `dynasty_data_YYYY-MM-DD.json` / `dynasty_data.js`

2. **Python server can proxy Next pages**
   - `server.py`
   - If Next is running, backend serves:
     - `/`
     - `/rankings`
     - `/trade`
     - `/_next/*` assets
   - If Next is not running, backend falls back to legacy static `index.html`

### Optional env vars
- `ENABLE_NEXT_FRONTEND_PROXY=true|false` (default `true`)
- `FRONTEND_URL=http://127.0.0.1:3000`
- `BACKEND_API_URL=http://127.0.0.1:8000/api/data` (for Next route)

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
python .\scripts\canonical_build.py --repo .
python .\scripts\league_refresh.py --repo .
python .\scripts\reporting.py --repo .
```

Outputs:
- `data/raw_sources/raw_source_snapshot_*.json`
- `data/canonical/canonical_snapshot_*.json`
- `data/league/league_snapshot_*.json`
- `data/reports/ops_report_*.md`

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
