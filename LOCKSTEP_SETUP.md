# GitHub + Jenkins + Server Lockstep Checklist

This document is the single source of truth for keeping Codex, Jenkins, and the server in sync.

## Current repo truth

- Repo: `git@github.com:jasonleetucker-code/riskittogetthebrisket.git`
- Branch: `main`
- Jenkins pipeline file: `Jenkinsfile` (repo root)
- Optional post-push Jenkins trigger: `scripts/trigger_jenkins.py` via `sync.bat`

## 1) GitHub access (required)

You need one of these:

1. Add Codex/Kodex account as a collaborator on:
   - `jasonleetucker-code/riskittogetthebrisket`
2. Or add a deploy key/token for server automation (least privilege recommended)

Recommended minimum permissions:
- Read/Write code on this repo only

Validation commands (from workspace):

```powershell
ssh -T git@github.com
git ls-remote origin HEAD
git push --dry-run origin main
```

Expected:
- SSH auth success message
- HEAD hash returned
- dry-run push does not fail auth

## 2) Hetzner server access (ideal)

Current production target:
- Host/IP: `178.156.148.92`
- SSH user: `dynasty`
- App path: `/home/dynasty/trade-calculator`
- Venv path: `/home/dynasty/.venvs/trade-calculator`
- Deploy state path: `/home/dynasty/.deploy-state`

Preferred setup:

1. Ensure SSH key access for `dynasty`
2. Grant only required sudo commands for deploy automation (`systemctl`, `journalctl`, `install`), not blanket root
3. Clone repo with SSH remote (fresh host bootstrap only):

```bash
cd /home/dynasty
git clone git@github.com:jasonleetucker-code/riskittogetthebrisket.git trade-calculator
cd trade-calculator
git remote -v
git fetch origin
git checkout main
```

## 3) Briefing / environment notes for Codex and Jenkins

Python backend:
- entrypoint: `server.py`
- runs on: `http://localhost:8000`
- scrape interval: `SCRAPE_INTERVAL_HOURS = 2`

Frontend:
- directory: `frontend/`
- dev server: `http://localhost:3000`
- command: `npm run dev`

Key scripts:
- `run_scraper.bat` -> scraper + debug loop
- `sync.bat` -> git add/commit/push and optional Jenkins trigger
- `start_stack.bat` -> starts backend + frontend

Data locations:
- generated exports: `data/`
- main payload: `data/dynasty_data_YYYY-MM-DD.json` and `data/dynasty_data.js`

Optional Jenkins trigger env vars (local machine):

```powershell
[Environment]::SetEnvironmentVariable("JENKINS_TRIGGER_URL","https://<jenkins-host>/job/<job-name>/buildWithParameters","User")
[Environment]::SetEnvironmentVariable("JENKINS_USER","<jenkins-user>","User")
[Environment]::SetEnvironmentVariable("JENKINS_API_TOKEN","<jenkins-api-token>","User")
```

## 4) Lockstep operating flow

1. Make change
2. Validate locally
3. Run:

```powershell
.\sync.bat "Your commit message"
```

4. Confirm Jenkins job triggered and passed
5. Pull latest on server and restart services

## 5) Done criteria

You are in lockstep when all are true:

- GitHub collaborator/deploy token is active
- local push to `origin/main` succeeds
- Jenkins job runs from repo `Jenkinsfile`
- server clone can `git pull` from same `origin`
- `sync.bat` optionally triggers Jenkins automatically
