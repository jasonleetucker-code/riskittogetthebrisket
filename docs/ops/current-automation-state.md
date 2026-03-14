# Current Automation State

_Generated: 2026-03-14_

---

## 1. Executive Summary

The production stack has **strong automation for deploy and runtime** but relies on a **monolithic in-process scraper** for all data freshness. There is no external cron, no systemd timer for scraping, and no separation between the web server and the data pipeline. If the server process dies, all scraping stops. If the scraper wedges, the web server continues serving stale data — which is the correct behavior, but monitoring of that staleness is limited to internal endpoints that no one is currently polling externally.

**What is automated**: Deploy (GitHub Actions → SSH → systemd restart → health verification → auto-rollback), scraper scheduling (2-hour in-process loop), data promotion (immediate after scrape), health endpoints, stall detection, uptime watchdog, ETag caching.

**What is manual**: Jenkins triggering (optional, via `sync.bat`), KTC data refresh, any source beyond the legacy scraper, monitoring/alerting review, rollback verification.

---

## 2. Current Automation State — Full Inventory

### 2.1 Deploy Pipeline

| Component | Mechanism | Trigger | Status |
|-----------|-----------|---------|--------|
| **GitHub Actions** (`.github/workflows/deploy.yml`) | SSH to Hetzner, run `deploy/deploy.sh` | Push to `main` or manual `workflow_dispatch` | **Automated** |
| `deploy/deploy.sh` | `git fetch` → `git checkout --force` → venv rebuild → systemd restart → verify → record state | Called by GitHub Actions | **Automated** |
| `deploy/verify-deploy.sh` | Probe `/api/status` (20 retries, 2s apart) + `/api/health` + optional public URL | Called by deploy.sh | **Automated** |
| `deploy/rollback.sh` | Checkout pre_deploy_rev → pip install → systemd restart → verify | Called by deploy.sh on failure (if AUTO_ROLLBACK=true) | **Automated** |
| `deploy/install-systemd-service.sh` | Template substitution → install unit → daemon-reload → enable | Called by deploy.sh if service missing | **Automated** (first-time only) |
| Systemd service (`dynasty.service`) | `Type=simple`, `Restart=always`, `RestartSec=5` | Systemd | **Automated** — auto-restarts on crash |

**Deploy flow**: Push to main → GitHub Actions validate job (syntax, imports, contract check, deploy script check) → deploy job (SSH preflight → remote deploy.sh → health verification → optional public smoke test).

**Rollback**: On deploy failure, `deploy.sh` traps ERR and calls `rollback.sh` with the pre-deploy rev. Rollback does the same checkout/pip/restart/verify sequence.

### 2.2 Jenkins CI Pipeline

| Stage | Script | Status | Notes |
|-------|--------|--------|-------|
| Checkout | git | **Automated** | |
| Git Info | git rev-parse | **Automated** | |
| Ingest | `scripts/source_pull.py` | **Automated** | Runs DLF adapters against seed CSVs |
| Validate | `scripts/validate_ingest.py` | **Automated** | Field presence, duplicate, sanity checks |
| Identity Resolve | `scripts/identity_resolve.py` | **Automated** | Confidence-based matching |
| Canonical Build | `scripts/canonical_build.py` | **Automated** | Transform + blend + validation |
| League Refresh | `scripts/league_refresh.py` | **Scaffold** | Produces stub output |
| Publish Report | `scripts/reporting.py` | **Automated** | Markdown ops report |
| Backend Smoke | py_compile | **Automated** | Syntax check only |
| API Contract Check | `scripts/validate_api_contract.py` | **Automated** | Validates contract structure |
| Frontend Build | npm ci + npm run build | **Automated** | |
| Regression Harness | Playwright E2E | **Automated** | Desktop + 2 mobile viewports |

**Jenkins trigger**: `scripts/trigger_jenkins.py` called by `sync.bat`. Requires `JENKINS_TRIGGER_URL`, `JENKINS_USER`, `JENKINS_API_TOKEN` env vars. **Manual** — user runs `sync.bat` from local machine.

**Critical gap**: Jenkins runs the scaffold pipeline but its output is **never consumed by production**. The pipeline validates data quality but doesn't promote canonical output to the live runtime.

### 2.3 Scraper Scheduling (In-Process)

| Parameter | Value | Source |
|-----------|-------|--------|
| Interval | 2 hours | `SCRAPE_INTERVAL_HOURS` (server.py:49) |
| Startup behavior | Load disk cache immediately, start scrape after 3s delay | server.py:1162-1178 |
| Scheduling mechanism | `asyncio.sleep()` in infinite loop | server.py:1148-1156 |
| Concurrency guard | `asyncio.Lock()` prevents overlapping scrapes | server.py:946 |
| Timeout | 7200s (2 hours) via `asyncio.wait_for()` | server.py:987-990 |
| Stall detection | 900s (15 min) no heartbeat = stalled | server.py:52, 358-364 |
| Manual trigger | POST `/api/scrape` | server.py:1521-1546 |

**Data promotion**: Immediate. When scraper completes, result is stored in memory, pre-serialized into 3 payload views (full/runtime/startup), pre-compressed with gzip, and ETag-hashed. Also written to `dynasty_data_*.json` on disk.

**Failure handling**: On scrape failure, `latest_data` is NOT updated — server continues serving last successful scrape data. Email alert sent if `SMTP_*` env vars are configured.

### 2.4 Health Endpoints

| Endpoint | Purpose | Returns |
|----------|---------|---------|
| `GET /api/health` | Service health | 200 if OK, 503 if error/stalled. Includes: has_data, scrape_running, scrape_stalled, contract_ok. |
| `GET /api/status` | Comprehensive status | Always 200. Scraper state, frontend_runtime, contract health, payload metrics (bytes/gzip), source health, uptime state. |
| `GET /api/uptime` | Uptime watchdog state | Enabled flag, target URL, last check, consecutive failures. |
| `GET /api/scaffold/status` | New engine pipeline status | Latest snapshot/validation/canonical/league/identity/report file metadata. |

### 2.5 Uptime Watchdog (In-Process)

| Parameter | Value | Source |
|-----------|-------|--------|
| Enabled | `UPTIME_CHECK_ENABLED` (default True) | server.py:82 |
| Target URL | `UPTIME_CHECK_URL` (default empty = disabled) | server.py:83-86 |
| Interval | `UPTIME_CHECK_INTERVAL_SEC` (default 300s / 5min) | server.py:87 |
| Timeout | `UPTIME_CHECK_TIMEOUT_SEC` (default 5s) | server.py:88 |
| Alert threshold | `UPTIME_ALERT_FAIL_THRESHOLD` (default 2 consecutive) | server.py:89 |

**Behavior**: Polls configured URL, sends email alert on consecutive failures >= threshold, sends recovery alert when service comes back. Disabled if `UPTIME_CHECK_URL` is empty.

### 2.6 Caching & Performance

| Mechanism | Details |
|-----------|---------|
| ETag | SHA1 of serialized JSON per payload view. 304 Not Modified on If-None-Match match. |
| Cache-Control | `public, max-age=30, stale-while-revalidate=300` on `/api/data`. |
| Gzip | Pre-compressed at serialize time (level 5). Served if Accept-Encoding: gzip. |
| GZip middleware | `GZipMiddleware(minimum_size=1024)` on app. |
| Payload views | Full, runtime (no playersArray), startup (minimal fields). Reduces first-paint payload. |

### 2.7 Alerting

| Alert Type | Mechanism | Trigger |
|-----------|-----------|---------|
| Scrape failure | Email via SMTP | scraper exception |
| Partial scrape | Email via SMTP | < 50% of sites returned data |
| Uptime failure | Email via SMTP | consecutive failures >= threshold |
| Uptime recovery | Email via SMTP | service recovers from down state |
| Rate limit | 1 email/hour max | `ALERT_COOLDOWN_SEC = 3600` |

**Note**: Alerting is email-only. No Slack, PagerDuty, webhook, or external monitoring integration. Requires `SMTP_*` env vars to be configured. If not configured, alerts are silently skipped.

---

## 3. What Is Automated vs Manual

### Fully Automated
1. Deploy on push to main (GitHub Actions)
2. Auto-rollback on deploy failure
3. Systemd auto-restart on process crash (RestartSec=5)
4. Scraper scheduling (every 2 hours, in-process)
5. Data promotion (immediate after scrape)
6. Last-known-good fallback (serve cached data on scrape failure)
7. Stall detection (15-minute heartbeat timeout)
8. Run timeout (2-hour asyncio.wait_for guard)
9. Orphaned state recovery (detects crashed scraper lock)
10. Uptime watchdog (5-minute polling, configurable)
11. ETag + gzip caching on /api/data
12. Jenkins CI pipeline (if triggered)
13. GitHub Actions validation job (syntax, imports, contract, deploy script)

### Manual
1. Jenkins triggering (requires running `sync.bat` or manual web trigger)
2. KTC seed CSV refresh
3. Any non-DLF source data refresh
4. Monitoring review (no dashboard, no external alerting service)
5. Log review (requires SSH to server + journalctl)
6. Performance baseline measurement
7. Canonical pipeline → production promotion (not wired)

### Mixed
1. `sync.bat` (manual trigger, but automates git push + optional Jenkins trigger)

---

## 4. Current Deploy Trigger/Flow

**Trigger**: Push-based. Every push to `main` triggers `.github/workflows/deploy.yml`.

**Flow**:
```
git push to main
  → GitHub Actions "validate" job
    → Checkout
    → Python syntax gate (server.py, Dynasty Scraper.py, data_contract.py)
    → Python import gate (fastapi, uvicorn, requests, playwright, server)
    → API contract check (if sample data exists)
    → Deploy artifacts check (deploy.sh, requirements.txt exist)
    → Deploy script syntax gate (bash -n)
  → GitHub Actions "deploy" job (needs: validate)
    → Preflight (validate all secrets present, install SSH key)
    → Validate known_hosts for target host
    → SSH preflight (connectivity + remote paths + sudo perms)
    → Remote deploy.sh execution
      → git fetch + checkout target ref
      → pip install -r requirements.txt
      → systemd restart
      → verify-deploy.sh (probe /api/status with retries, probe /api/health)
      → record success state
      → On failure: auto-rollback to pre_deploy_rev
    → Public health smoke test (optional, if PROD_PUBLIC_URL set)
```

**Rollback**: Automatic on failure. `deploy.sh` traps ERR, calls `rollback.sh` with the pre-deploy revision. Rollback does checkout → pip install → restart → verify.

---

## 5. Current Scrape/Refresh Behavior

**Schedule**: Every 2 hours, starting 3 seconds after server boot.

**Mechanism**: In-process async loop in `server.py`. No external cron or systemd timer.

**What runs**: `Dynasty Scraper.py` is imported via `importlib` and its `run()` method is called with `asyncio.wait_for()` timeout.

**Data flow**:
```
scheduler wakes up (every 2h)
  → acquire asyncio.Lock (prevent concurrent)
  → importlib.import_module("Dynasty Scraper")
  → scraper.run() via asyncio.wait_for(timeout=7200s)
  → heartbeat updates every progress step
  → on success:
    → latest_data = result (in-memory)
    → _prime_latest_payload() (pre-serialize + gzip + ETag)
    → write dynasty_data_YYYY-MM-DD.json to disk (cache)
  → on failure:
    → latest_data NOT updated (serve last good)
    → email alert
    → mark failure in scrape_status
```

**Sources scraped**: Multiple sites via the legacy `Dynasty Scraper.py` (501KB monolith). The canonical pipeline adapters (DLF CSV, KTC stub) are separate and only run in Jenkins — they do NOT run as part of this scrape cycle.

---

## 6. Current Health Checks / Smoke Checks / Monitoring

### Deploy-time
- `verify-deploy.sh`: probes `/api/status` with 20 retries (2s apart), probes `/api/health`, optionally probes public URL
- GitHub Actions: optional public health smoke test via curl

### Runtime
- `/api/health`: returns 200/503 based on error state, stall state, contract health
- `/api/status`: comprehensive scraper + contract + payload + uptime state
- Uptime watchdog: polls external URL every 5 minutes (if configured)

### What's NOT monitored
- No external uptime monitoring service (e.g., UptimeRobot, Pingdom)
- No log aggregation (ELK, CloudWatch, etc.)
- No metrics/dashboard (Grafana, Datadog)
- No disk space monitoring
- No certificate expiry monitoring
- No scrape success rate tracking over time
- No historical health data

---

## 7. Failure Handling / Last-Known-Good Findings

| Scenario | Behavior | Assessment |
|----------|----------|------------|
| **Scrape fails** | latest_data unchanged, serve cached | **Good** — no data loss |
| **Scrape times out** (>2h) | asyncio.wait_for raises TimeoutError, treated as failure | **Good** — prevents wedged scraper |
| **Scrape stalls** (no heartbeat >15min) | Stall flag set, reported in /api/health and /api/status | **Partial** — detected but no auto-kill; only flagged |
| **Server crashes** | Systemd `Restart=always RestartSec=5` | **Good** — auto-restart |
| **Deploy fails** | Auto-rollback to pre_deploy_rev | **Good** — tested path |
| **No cached data on startup** | Server starts, serves empty payload, waits for first scrape | **Acceptable** — logs warning, dashboard shows no data |
| **Partial scrape** (<50% sites) | Data published anyway + email alert | **Risky** — may overwrite good data with degraded data |
| **Orphaned scraper lock** (process crash mid-scrape) | Detected and reset on next scrape attempt | **Good** — self-healing |
| **DNS/network failure** | Scrape fails, last-known-good served | **Good** |
| **Disk full** | No handling — JSON write would fail silently | **Gap** |

---

## 8. Major Risks

### 8.1 Over-Scraping
**Risk: LOW**. 2-hour interval is reasonable. Concurrent scrapes are prevented by asyncio.Lock. No external cron could accidentally double-schedule.

### 8.2 Stale Data Promotion
**Risk: MEDIUM**. The scrape-to-promotion path is immediate and healthy. BUT: if scraping fails for an extended period (hours/days), there's no escalating alert. The server serves stale data indefinitely. The uptime watchdog checks server health, not data freshness.

### 8.3 Silent Failure
**Risk: MEDIUM-HIGH**. Email alerting depends on SMTP env vars being configured. If they're not set (or SMTP fails), all alerts are silently swallowed. There's no secondary alert channel. No external monitoring service would notice scrape failures.

### 8.4 Deploy Loops
**Risk: LOW**. GitHub Actions `concurrency: cancel-in-progress: false` prevents deploy queue from growing unbounded. Auto-rollback only runs once per deploy (ROLLBACK_ATTEMPTED flag). No retry loop.

### 8.5 Lack of Verification
**Risk: LOW** for deploy (verify-deploy.sh is thorough). **MEDIUM** for scrape quality — scrape publishes even partial results (<50% sites) which could overwrite better data.

### 8.6 Missing Observability
**Risk: HIGH**. No external monitoring, no metrics dashboards, no log aggregation, no historical health data. All monitoring is via internal endpoints that require active polling. If the server is down, there's nothing external watching it (unless uptime watchdog is configured to check an external URL — but that's self-monitoring, not external).

### 8.7 Single-Process Coupling
**Risk: MEDIUM**. Scraper and web server share the same process. A memory leak in the scraper could take down the web server. A CPU-intensive scrape could cause request latency spikes. Systemd auto-restart mitigates crash risk but doesn't prevent degradation.

### 8.8 Canonical Pipeline Disconnect
**Risk: LOW** (operationally) but **HIGH** (strategically). Jenkins runs the canonical pipeline but output is never consumed. This means Jenkins CI adds compute cost and complexity without production value. Not a reliability risk, but a wasted-work risk.

---

## 9. Unknowns That Need Verification

1. **Is SMTP configured on production?** — Cannot determine from repo. If not, all email alerts are disabled.
2. **Is UPTIME_CHECK_URL configured?** — Cannot determine from repo. If empty, watchdog is a no-op.
3. **Is Jenkins actually running on a schedule?** — Jenkinsfile has no cron trigger. It only runs when triggered by `sync.bat` or manually. Cannot verify from repo alone.
4. **What does the systemd unit look like on production?** — Only the template is in the repo. Actual deployed unit may differ.
5. **Is the production .env file complete?** — `.env.example` shows the structure but cannot verify production values.
6. **Is HTTPS/TLS configured?** — `JASON_AUTH_COOKIE_SECURE=True` suggests HTTPS intent, but no nginx/caddy config in repo.
7. **Disk space on Hetzner** — No monitoring for this.
8. **Dynasty Scraper.py reliability** — 501KB monolith, cannot assess failure rate from repo.
