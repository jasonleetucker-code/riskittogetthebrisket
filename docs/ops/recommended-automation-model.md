# Recommended Automation Model

_Generated: 2026-03-14_

---

## Design Principles

1. **Event-driven where practical** — don't poll when you can react
2. **Light on external sources** — respect rate limits, stagger requests
3. **Validation-gated** — never promote data that fails quality checks
4. **Observable** — every automated action should leave a trace
5. **Simple for a non-technical owner** — Jason should be able to understand what's running without reading code

---

## Recommended Model

### Tier 1: Keep As-Is (Working Well)

These are already correctly automated and need no changes:

| Component | Current State | Recommendation |
|-----------|--------------|----------------|
| Deploy on push to main | GitHub Actions → SSH → deploy.sh → verify → rollback | **Keep** — event-driven, validated, auto-recoverable |
| Systemd auto-restart | `Restart=always, RestartSec=5` | **Keep** — correct crash recovery |
| In-process scrape scheduling | 2-hour asyncio loop | **Keep for now** — works well for single-server setup |
| Scrape concurrency guard | asyncio.Lock | **Keep** — prevents over-scraping |
| Run timeout | 2h asyncio.wait_for | **Keep** — prevents wedged scraper |
| Orphaned lock recovery | Detect and reset on next attempt | **Keep** — self-healing |
| ETag + gzip caching | Pre-computed per payload view | **Keep** — reduces bandwidth and client load |
| Last-known-good on failure | Serve cached data, don't overwrite | **Keep** — correct behavior |

### Tier 2: Small Changes (High Impact, Low Effort)

#### R-1: Add data freshness check to /api/health

**Current**: `/api/health` checks error state and stall state but not data age.

**Recommended**: Add a `data_stale` flag. If `latest_data` is older than `SCRAPE_INTERVAL_HOURS * 3` (6 hours), mark health as degraded. This way external monitors can detect persistent scrape failures.

```
data_age_hours = (now - data_date).total_seconds() / 3600
data_stale = data_age_hours > SCRAPE_INTERVAL_HOURS * 3
```

**Why**: External uptime monitors (UptimeRobot, free tier) can check `/api/health` and alert if it returns 503 due to stale data.

#### R-2: Add external uptime monitoring

**Current**: Self-monitoring via uptime watchdog (if configured). No external check.

**Recommended**: Register `https://riskittogetthebrisket.org/api/health` with a free external monitor (UptimeRobot, BetterUptime, Cronitor, or similar). Configure to check every 5 minutes. Alert via email + SMS/push.

**Why**: If the server is completely down, nothing internal can alert. External monitoring is the only way to detect total outages.

#### R-3: Guard against partial scrape data promotion

**Current**: If < 50% of sites return data, the partial result is still published (with an email alert).

**Recommended**: Do not promote scrape results with < 50% site coverage. Keep serving last-known-good. Still send the alert, but add `"PARTIAL SCRAPE NOT PROMOTED"` to the subject.

**Why**: Partial data can drop player values to zero, causing confusion in the trade calculator. Better to serve slightly stale but complete data.

#### R-4: Add scrape success rate to /api/status

**Current**: `/api/status` shows current scrape state but no historical success rate.

**Recommended**: Track last N scrape results (success/failure/partial) in a rolling list. Add `scrape_success_rate_24h` and `last_N_scrapes` to `/api/status`.

**Why**: Lets Jason see at a glance whether scraping is healthy over time, not just right now.

### Tier 3: Medium Changes (Strategic Value)

#### R-5: Separate scraper from web server (Eventually)

**Current**: Scraper runs in the same process as the web server.

**Recommended** (when ready): Run scraper as a separate systemd service or systemd timer. Write results to `dynasty_data_*.json`. Web server watches for file changes (inotify/polling) and reloads.

**Why**: Isolates scraper memory/CPU from web serving. Prevents scraper crashes from taking down the site. Allows independent scaling and debugging.

**When**: Not urgent. Current coupling is acceptable for a single-server setup. Do this when scraper complexity increases or if memory issues appear.

#### R-6: Wire canonical pipeline to production (with gate)

**Current**: Jenkins runs the canonical pipeline, but output isn't consumed.

**Recommended**: Add a validation gate between canonical pipeline output and production data:

```
canonical_build.py produces canonical_snapshot_*.json
  → validate: ≥ N players, ≥ 2 sources, no value jumps > threshold
  → if valid: copy to data/dynasty_data_canonical_*.json
  → server.py: add CANONICAL_DATA_MODE env var (off/shadow/primary)
    - off: current behavior
    - shadow: load canonical, log comparison, serve legacy
    - primary: serve canonical, fallback to legacy
```

**Why**: This is the bridge between the new engine and production. Shadow mode lets you compare without risk. The gate prevents bad canonical data from reaching users.

#### R-7: Add Jenkins scheduling (if Jenkins is kept)

**Current**: Jenkins only runs when manually triggered via `sync.bat`.

**Recommended**: If Jenkins continues to be used, add a cron trigger:

```groovy
triggers {
    cron('H H/6 * * *')  // every 6 hours, randomized minute
}
```

**Why**: Ensures the canonical pipeline runs regularly even if Jason doesn't run `sync.bat`. Six-hour interval is low-load and sufficient for validation purposes.

**Alternative**: If Jenkins is not needed beyond CI, move the canonical pipeline stages to GitHub Actions as a scheduled workflow.

### Tier 4: Future Enhancements (When Needed)

#### R-8: Structured logging

**Current**: `print()` and `log()` statements. No structured format.

**Recommended**: Use Python `logging` module with JSON formatter. Write to stdout (captured by journalctl). Makes log analysis possible without SSH.

#### R-9: Metrics endpoint

**Current**: No Prometheus/StatsD/OpenTelemetry metrics.

**Recommended**: Add a `/metrics` endpoint with basic counters: scrape_total, scrape_failures, scrape_duration_seconds, request_count, data_age_seconds. This enables Grafana dashboards if desired later.

#### R-10: Disk space guard

**Current**: No disk space monitoring. If disk fills, JSON writes fail silently.

**Recommended**: Before writing dynasty_data_*.json, check available disk space. If < 500MB, skip write and alert.

---

## Implementation Priority

| Priority | Item | Effort | Impact |
|----------|------|--------|--------|
| **Do now** | R-2: External uptime monitoring | 10 min (free service signup) | Catches total outages |
| **Do now** | R-1: Data freshness in /api/health | 15 min code change | Enables R-2 to detect stale data |
| **Do soon** | R-3: Block partial scrape promotion | 30 min code change | Prevents bad data from reaching users |
| **Do soon** | R-4: Scrape success rate tracking | 1 hour code change | Gives Jason visibility into scraper reliability |
| **Plan** | R-6: Canonical pipeline wiring | Multi-session | Connects new engine to production |
| **Plan** | R-7: Jenkins scheduling | 5 min config change | Regular canonical pipeline runs |
| **Later** | R-5: Separate scraper process | Half-day | Better isolation |
| **Later** | R-8: Structured logging | 2 hours | Better debugging |
| **Later** | R-9: Metrics endpoint | 2 hours | Enables dashboards |
| **Later** | R-10: Disk space guard | 30 min | Prevents silent disk-full failures |

---

## What This Looks Like to Jason

**Today**: "The site scrapes every 2 hours. If a scrape fails, it keeps showing the last good data. Deploys happen automatically when code is pushed. If something breaks during deploy, it rolls back."

**After Tier 2 changes**: "Same as above, plus you'll get a text/email if the site goes down or if data hasn't refreshed in 6+ hours. Bad scrapes won't replace good data anymore."

**After Tier 3 changes**: "The new value engine runs alongside the old scraper. You can see both sets of values compared. When the new engine is ready, it replaces the old one with a config change."

---

## Conservative Automation Model Summary

```
┌─────────────────────────────────────────────────┐
│                  PRODUCTION                      │
│                                                  │
│  server.py (Hetzner)                            │
│  ├─ Serves /api/data (last-known-good)          │
│  ├─ Scrapes every 2h (in-process)               │
│  ├─ /api/health (error + stall + data freshness)│
│  ├─ Uptime watchdog (self-check)                │
│  └─ Systemd: Restart=always                     │
│                                                  │
│  External Monitor (UptimeRobot)                  │
│  └─ Polls /api/health every 5min                │
│  └─ Alerts on 503 (error/stale/down)            │
│                                                  │
├─────────────────────────────────────────────────┤
│                  DEPLOY                          │
│                                                  │
│  Push to main                                    │
│  → GitHub Actions validate                       │
│  → GitHub Actions deploy (SSH)                   │
│    → deploy.sh → verify → record state           │
│    → On failure: auto-rollback                   │
│                                                  │
├─────────────────────────────────────────────────┤
│              CI / QUALITY GATE                   │
│                                                  │
│  Jenkins (or GitHub Actions scheduled)           │
│  → Canonical pipeline (every 6h)                 │
│  → Ingest → Validate → Identity → Canonical      │
│  → Ops report                                    │
│  → Contract validation                           │
│  → Frontend build + E2E regression               │
│                                                  │
├─────────────────────────────────────────────────┤
│              DATA PROMOTION RULES                │
│                                                  │
│  Legacy scraper:                                 │
│  → Promote if ≥ 50% sites returned              │
│  → Otherwise: keep last-known-good              │
│                                                  │
│  Canonical pipeline (future):                    │
│  → Promote if: ≥ N players, ≥ 2 sources,        │
│    no value jumps > threshold                    │
│  → Shadow mode first, then primary               │
│                                                  │
└─────────────────────────────────────────────────┘
```
