# Automation Runbook

> **⚠ STALE — March 2026 snapshot.**  Several knobs documented
> here (notably `CANONICAL_DATA_MODE`) have been retired.  For the
> current automation surface, refer to `CLAUDE.md` plus the
> ``.github/workflows/`` files directly.  Kept for historical
> context; the schedule + responsibility table at the top is still
> mostly accurate.

_Last updated: 2026-03-14_

This document describes every automated process in the Risk It to Get the Brisket platform. It is written for Jason (the site owner) — no code knowledge required.

---

## What Runs Automatically

### 1. Data Scraping (Every 2 Hours)

**What it does**: The server scrapes multiple dynasty fantasy football ranking sites and combines their data into a single unified dataset.

**Schedule**: Every 2 hours, starting 3 seconds after the server boots.

**Where it runs**: Inside the server process on Hetzner.

**What happens on success**: New player values appear on the site immediately. The data is also saved to disk so it survives a server restart.

**What happens on failure**:
- The site keeps showing the last good data (nothing breaks).
- An email alert is sent (if SMTP is configured).
- The failure is logged and visible at `/api/status`.

**What happens on partial failure** (fewer than half the sites respond):
- The partial data is **NOT** promoted — the site keeps showing the last complete dataset.
- An email alert is sent with subject "PARTIAL SCRAPE NOT PROMOTED".
- This prevents your trade calculator from showing wrong values.

### 2. Deploy on Push to Main (Automatic)

**What it does**: When code is pushed to the `main` branch on GitHub, a deploy pipeline runs automatically.

**Steps**:
1. GitHub Actions validates the code (syntax, imports, contract checks)
2. Connects to the Hetzner server via SSH
3. Pulls the new code
4. Reinstalls Python dependencies
5. Restarts the server
6. Verifies the server is healthy (checks `/api/status` and `/api/health`)
7. Records the successful deploy

**What happens on failure**: The server automatically rolls back to the previous working version. No manual intervention needed.

### 3. Server Auto-Restart on Crash

**What it does**: If the server process crashes for any reason, systemd automatically restarts it within 5 seconds.

**Where**: Managed by the `dynasty` systemd service on Hetzner.

### 4. Uptime Watchdog (Every 5 Minutes)

**What it does**: The server checks its own public URL every 5 minutes.

**What happens on failure**: After 2 consecutive failures, an email alert is sent. When the service recovers, a recovery email is sent.

**Limitation**: This is self-monitoring. If the entire server is down, this watchdog can't alert. That's why external monitoring (UptimeRobot) is also recommended — see "External Monitoring" below.

### 5. Scheduled Health Checks (Every 6 Hours)

**What it does**: A GitHub Actions workflow checks the production `/api/health` and `/api/status` endpoints every 6 hours.

**Where it runs**: GitHub Actions (free tier).

**What it checks**:
- Server responds with HTTP 200
- Data is not stale (loaded within the last 6 hours)
- Scrape success rate is acceptable

**What happens on failure**: The GitHub Actions run is marked as failed. You can see failed runs in the "Actions" tab on GitHub.

### 6. Daily Smoke Test (Once per Day)

**What it does**: A GitHub Actions workflow runs a comprehensive check every day at 06:15 UTC.

**What it checks**:
- All production endpoints respond (/, /api/health, /api/status, /api/data, /league, /api/uptime)
- Data contract shape is valid (has players, has sites, has version)
- Code compiles correctly
- All unit tests pass
- Deploy scripts have valid syntax

**Where it runs**: GitHub Actions (free tier).

### 7. Jenkins Canonical Pipeline (Every 6 Hours)

**What it does**: Runs the new data engine pipeline: ingest sources, validate data, resolve player identities, build canonical values, generate reports.

**Schedule**: Every 6 hours (Jenkins cron trigger).

**Current status**: Pipeline runs and validates data quality, but output is **not yet** promoted to production. It runs in parallel with the legacy scraper for validation purposes.

---

## Status Endpoints (Where to Check)

| URL | What It Shows | When to Check |
|-----|--------------|---------------|
| `/api/health` | Quick health check (ok/degraded) | External monitors poll this |
| `/api/status` | Full scraper status, success rates, data info | When you want to see if everything is working |
| `/api/metrics` | Server uptime, request counts, disk space, data age | Dashboard / monitoring |
| `/api/uptime` | Uptime watchdog state | To verify watchdog is running |
| `/api/scaffold/status` | Canonical pipeline latest outputs | To check new engine status |

---

## External Monitoring Setup (Recommended)

Sign up for a free account at [UptimeRobot](https://uptimerobot.com) (or similar).

**Configure a monitor**:
- URL: `https://riskittogetthebrisket.org/api/health`
- Check interval: 5 minutes
- Alert contacts: Your email + phone (SMS)
- Expected response: HTTP 200

This gives you alerts if the site goes completely down — something the internal watchdog can't detect.

---

## How to Manually Trigger Things

| Action | How |
|--------|-----|
| Force a data scrape | POST to `/api/scrape` (requires login) |
| Force a deploy | Go to GitHub Actions > "Deploy Production" > "Run workflow" |
| Force a health check | Go to GitHub Actions > "Scheduled Health Check" > "Run workflow" |
| Force a smoke test | Go to GitHub Actions > "Scheduled Smoke Test" > "Run workflow" |
| View server logs | SSH to Hetzner, run `sudo journalctl -u dynasty -f` |
| Restart the server | SSH to Hetzner, run `sudo systemctl restart dynasty` |
| Check service status | SSH to Hetzner, run `sudo systemctl status dynasty` |

---

## Environment Variables That Control Automation

| Variable | Default | What It Does |
|----------|---------|-------------|
| `SCRAPE_INTERVAL_HOURS` | 2 | How often the scraper runs |
| `CANONICAL_DATA_MODE` | off | Canonical pipeline mode (off/shadow/primary) |
| `DISK_SPACE_MIN_MB` | 500 | Minimum free disk (MB) before skipping writes |
| `UPTIME_CHECK_ENABLED` | true | Enable/disable uptime watchdog |
| `UPTIME_CHECK_URL` | (empty) | URL the watchdog monitors |
| `UPTIME_CHECK_INTERVAL_SEC` | 300 | Watchdog poll interval (seconds) |
| `ALERT_ENABLED` | false | Enable email alerts |
| `ALERT_TO` | (empty) | Alert recipient email |
| `LOG_FORMAT` | text | Log format: "text" (human) or "json" (structured) |
