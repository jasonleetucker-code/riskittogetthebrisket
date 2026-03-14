# Failure Handling and Fallbacks

_Last updated: 2026-03-14_

How every failure scenario is handled, what falls back to what, and what the owner needs to do (if anything).

---

## Failure Matrix

| Scenario | Automatic Response | Data Impact | Owner Action Needed |
|----------|-------------------|-------------|-------------------|
| Scrape fails (network/source error) | Serve last-known-good data | None — old data stays live | None (alert sent) |
| Scrape times out (>2h) | Treated as failure, timeout error logged | None — old data stays live | None (alert sent) |
| Scrape stalls (no heartbeat >15min) | Stall flag set, reported in /api/health | None — old data stays live | None (visible in /api/status) |
| Partial scrape (<50% sites) | **Not promoted** — old data stays live | None — blocked by guard | None (alert sent with "NOT PROMOTED") |
| Server process crashes | Systemd restarts in 5 seconds | Brief gap, then loads from disk cache | None |
| Deploy fails | Auto-rollback to previous version | None — old version runs | Check GitHub Actions log |
| Disk space low (<500MB) | Data served from memory, disk write skipped | None — memory serving continues | Free disk space on server |
| Data stale (>6 hours old) | /api/health returns 503 (degraded) | Stale data still served | Investigate why scrapes are failing |
| External site blocks scraper | That site's data missing from scrape | Partial data (may trigger partial guard) | Monitor; may need scraper update |
| SMTP not configured | Alerts silently skipped | None | Configure SMTP env vars |
| Total server down | External monitor alerts (if configured) | Site unavailable | SSH to server, check systemd |
| GitHub Actions fails | Marked as failed in Actions tab | None — production unaffected | Check Actions tab |

---

## Last-Known-Good Behavior

The core safety principle: **never replace good data with bad data**.

### How It Works

1. **On startup**: Server loads the most recent `dynasty_data_*.json` from disk. Dashboard is immediately usable with cached data.

2. **On scrape success**: New data replaces old data in memory. New data is also written to disk (if disk space permits).

3. **On scrape failure**: `latest_data` is NOT updated. The server continues serving whatever was last successfully loaded.

4. **On partial scrape**: If fewer than 50% of sites returned data, the result is blocked from promotion. An alert is sent, but the live data stays intact.

5. **On disk full**: Data is served from memory but not written to disk. An alert is sent. If the server restarts before disk space is freed, it will load the last file that was successfully written.

### Data Flow Diagram

```
Scrape attempt
  │
  ├─ Success (≥50% sites)
  │   ├─ Check disk space
  │   │   ├─ OK: write to disk + serve from memory
  │   │   └─ LOW: serve from memory only + alert
  │   └─ Update in-memory cache (latest_data)
  │
  ├─ Partial (<50% sites)
  │   ├─ DO NOT update in-memory cache
  │   ├─ Send "NOT PROMOTED" alert
  │   └─ Continue serving last-known-good
  │
  └─ Failure (exception/timeout)
      ├─ DO NOT update in-memory cache
      ├─ Send failure alert
      └─ Continue serving last-known-good
```

---

## Deploy Failure Recovery

### Automatic Rollback

When a deploy fails at any step, the deploy script automatically:

1. Detects the error (via bash `ERR` trap)
2. Reads the `pre_deploy_rev` saved at deploy start
3. Checks out the previous commit
4. Reinstalls Python dependencies
5. Restarts the systemd service
6. Verifies the rollback succeeded (probes /api/status and /api/health)
7. Records the rollback

**Safety guards**:
- Rollback is only attempted once per deploy (ROLLBACK_ATTEMPTED flag)
- If rollback itself fails, the error is logged and manual intervention is flagged
- AUTO_ROLLBACK can be disabled via environment variable if needed

### Deploy State Files

The deploy system maintains these state files on the server:

| File | Purpose |
|------|---------|
| `pre_deploy_rev` | Git commit hash before current deploy started |
| `last_successful_rev` | Git commit hash of last successful deploy |
| `last_successful_at_utc` | Timestamp of last successful deploy |

These are used by both deploy and rollback to know where to go back to.

---

## Stall Detection

**What counts as a stall**: If the scraper doesn't update its heartbeat for 900 seconds (15 minutes), it's considered stalled.

**What happens**:
- The `stalled` flag is set in scrape_status
- `/api/health` reports the stall
- External monitors (if configured) see the degraded health

**What doesn't happen**: The stalled scraper is NOT automatically killed. It runs under a 2-hour `asyncio.wait_for` timeout, so it will eventually be cleaned up. The stall detection is for visibility, not automatic intervention.

---

## Alerting Chain

```
Event occurs
  │
  ├─ Check ALERT_ENABLED env var
  │   └─ If false/missing: silently skip (logged locally)
  │
  ├─ Check ALERT_COOLDOWN_SEC (default 3600 = 1 hour)
  │   └─ If last alert was within cooldown: skip (prevents alert storms)
  │
  └─ Send email via SMTP
      ├─ To: ALERT_TO
      ├─ From: ALERT_FROM
      └─ Via: Gmail SMTP (ALERT_PASSWORD)
```

**Alert types**:

| Alert | Subject Pattern | Sent When |
|-------|----------------|-----------|
| Scrape failure | `Scrape failed: {ErrorType}` | Any scrape exception |
| Partial scrape | `PARTIAL SCRAPE NOT PROMOTED: only N/M sites` | <50% site coverage |
| Uptime failure | `Uptime check failed` | 2+ consecutive failures |
| Uptime recovery | `Uptime check recovered` | Service comes back after failure |
| Disk space low | `DISK SPACE CRITICALLY LOW: NMB free` | <500MB available |

---

## Monitoring Layers

The platform has three monitoring layers, each catching different failure modes:

### Layer 1: Self-Monitoring (Always Active)
- In-process uptime watchdog (5-minute checks)
- Scrape status tracking with success rate history
- Health endpoint with data freshness check
- Stall detection (15-minute heartbeat timeout)

**Catches**: Scrape failures, data staleness, internal errors

**Cannot catch**: Total server outage

### Layer 2: GitHub Actions (Always Active)
- Scheduled health check (every 6 hours)
- Daily smoke test (code + endpoints + contract)

**Catches**: Prolonged health degradation, data contract violations, code quality issues

**Cannot catch**: Issues between check intervals

### Layer 3: External Monitoring (Requires Setup)
- UptimeRobot or similar (recommended, 5-minute checks)

**Catches**: Total server outage, network unreachability

**Setup**: Free tier, one-time manual configuration

---

## Recovery Procedures

### "Site is down" (External monitor alert)

1. SSH to server: `ssh dynasty@<hetzner-ip>`
2. Check service: `sudo systemctl status dynasty`
3. Check logs: `sudo journalctl -u dynasty -n 200 --no-pager`
4. If service is stopped: `sudo systemctl start dynasty`
5. If service keeps crashing: check logs for the error, may need a code fix + deploy

### "Data is stale" (Health check shows degraded)

1. Check `/api/status` — look at `scrape_success_rate_24h` and `last_n_scrapes`
2. If all recent scrapes failed: check if source sites are up, may be a scraper bug
3. Try a manual scrape: POST to `/api/scrape` (requires login)
4. Check logs: `sudo journalctl -u dynasty -n 200 --no-pager | grep SCRAPE`

### "Deploy failed and didn't auto-rollback"

1. Check GitHub Actions log for the error
2. SSH to server
3. Run manual rollback: `bash /home/dynasty/trade-calculator/deploy/rollback.sh`
4. Verify: `curl http://127.0.0.1:8000/api/health`

### "Disk space is low"

1. SSH to server
2. Check usage: `df -h`
3. Clean old data files: `ls -la /home/dynasty/trade-calculator/data/dynasty_data_*.json`
4. Remove old files (keep last 5-7 days): `rm dynasty_data_2026-03-0*.json`
5. Check logs: `sudo journalctl --vacuum-size=100M`
