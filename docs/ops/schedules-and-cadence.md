# Schedules and Cadence

_Last updated: 2026-03-14_

All automated schedules for the Risk It to Get the Brisket platform, organized by frequency.

---

## Schedule Overview

```
Every 2 hours     Data scrape (in-process, server.py)
Every 5 minutes   Uptime watchdog self-check (in-process, server.py)
Every 6 hours     GitHub Actions health check (health-check.yml)
Every 6 hours     Jenkins canonical pipeline (Jenkinsfile cron)
Daily at 06:15    GitHub Actions smoke test (smoke-test.yml)
On push to main   Deploy pipeline (deploy.yml)
On crash          Systemd auto-restart (5-second delay)
```

---

## Detailed Schedule

### High-Frequency (Minutes)

| Job | Interval | Mechanism | Stagger | Notes |
|-----|----------|-----------|---------|-------|
| Uptime watchdog | 5 min | asyncio loop in server.py | N/A | Self-monitoring; polls UPTIME_CHECK_URL |

### Medium-Frequency (Hours)

| Job | Interval | Mechanism | Stagger | Notes |
|-----|----------|-----------|---------|-------|
| Data scrape | 2 hours | asyncio loop in server.py | 3s delay on startup | Concurrency-guarded (asyncio.Lock) |
| Health check | 6 hours | GitHub Actions cron (`:17 */6 * * *`) | 17-min offset | Checks /api/health and /api/status |
| Canonical pipeline | 6 hours | Jenkins cron (`H H/6 * * *`) | Jenkins `H` randomizes minute | Full pipeline: ingest → validate → identity → canonical → report |

### Low-Frequency (Daily+)

| Job | Interval | Mechanism | Stagger | Notes |
|-----|----------|-----------|---------|-------|
| Smoke test | Daily 06:15 UTC | GitHub Actions cron (`:15 6 * * *`) | Fixed time, low-traffic window | Code validation + production endpoint checks + contract validation |

### Event-Driven (Not Scheduled)

| Job | Trigger | Mechanism | Notes |
|-----|---------|-----------|-------|
| Deploy | Push to main | GitHub Actions deploy.yml | Validate → SSH → deploy.sh → verify → record |
| Auto-rollback | Deploy failure | deploy.sh ERR trap | Rolls back to pre_deploy_rev |
| Auto-restart | Process crash | systemd Restart=always | 5-second delay between restarts |
| Scrape alert | Scrape failure | Email via SMTP | 1 email/hour rate limit |
| Partial scrape block | <50% site coverage | server.py guard | Keeps last-known-good data |
| Disk space alert | <500MB free | server.py guard | Skips disk write, keeps serving from memory |

---

## Cadence Design Principles

### Source-Aware Cadence
- **Scraping runs every 2 hours** — balanced between freshness and anti-bot risk. Dynasty rankings don't change more than a few times per day.
- **Concurrency lock** prevents overlapping scrapes. If a scrape takes >2 hours, it times out (7200s guard) and the next one starts on the next cycle.
- **No external cron for scraping** — the in-process loop is simpler and self-managing for a single-server setup.

### Staggered Jobs
- GitHub Actions health check runs at minute `:17` (not `:00`) to avoid thundering herd.
- Jenkins uses `H` (hash-based) minute randomization.
- Smoke test runs at 06:15 UTC — outside peak US traffic hours.
- Uptime watchdog is internal and doesn't compete for external resources.

### Anti-Bot Protections
- 2-hour scrape interval is conservative (12 requests/day per source).
- Concurrent scrapes are impossible (asyncio.Lock).
- Run timeout (2h) prevents indefinite connections.
- Partial results are blocked from promotion, reducing incentive to retry aggressively.

---

## Job Interdependencies

```
Data scrape (2h)
  └─ On success: promote data → prime ETag cache → write to disk (if disk space OK)
  └─ On partial: block promotion → alert → keep last-known-good
  └─ On failure: keep last-known-good → alert → log to history
  └─ After any outcome: reload canonical snapshot (if shadow/primary mode)

Health check (6h)
  └─ Reads /api/health (depends on data freshness from last scrape)
  └─ Reads /api/status (depends on scrape history from last 24h)
  └─ No write side effects

Smoke test (daily)
  └─ Reads /api/data (depends on promoted scrape data)
  └─ Validates contract shape (depends on data pipeline output)
  └─ Independent of scrape timing

Deploy (on push)
  └─ Restarts server → triggers startup scrape (3s delay)
  └─ Health verification depends on /api/status and /api/health
  └─ Rollback depends on deploy state files

Jenkins pipeline (6h)
  └─ Produces canonical snapshots in data/canonical/
  └─ Server loads these on startup and after each scrape (if shadow/primary mode)
  └─ No direct impact on live data (unless CANONICAL_DATA_MODE=primary)
```

---

## Timeline: What Happens in a Typical Day

```
00:00  Scrape runs (scheduled)
00:17  Health check (GitHub Actions)
02:00  Scrape runs (scheduled)
04:00  Scrape runs (scheduled)
06:00  Scrape runs (scheduled)
06:15  Smoke test (GitHub Actions — full validation suite)
06:17  Health check (GitHub Actions)
08:00  Scrape runs (scheduled)
10:00  Scrape runs (scheduled)
12:00  Scrape runs (scheduled)
12:17  Health check (GitHub Actions)
14:00  Scrape runs (scheduled)
16:00  Scrape runs (scheduled)
18:00  Scrape runs (scheduled)
18:17  Health check (GitHub Actions)
20:00  Scrape runs (scheduled)
22:00  Scrape runs (scheduled)

Jenkins pipeline runs at ~00:00, ~06:00, ~12:00, ~18:00 (randomized minute)
Uptime watchdog checks every 5 minutes (288 checks/day)
```
