# systemd units — Risk It platform

## Install (on the VPS)

```bash
# Copy units into /etc/systemd/system/
sudo cp deploy/systemd/*.service deploy/systemd/*.timer /etc/systemd/system/
sudo systemctl daemon-reload

# Enable + start the timers (the .service units are triggered by them).
sudo systemctl enable --now riskit-backup.timer
sudo systemctl enable --now riskit-backup-restore-test.timer
sudo systemctl enable --now dynasty-healthcheck.timer

# Optional: logrotate (uses Linux's own logrotate cron, NOT a timer here).
sudo cp deploy/logrotate.conf /etc/logrotate.d/riskit
sudo chmod 644 /etc/logrotate.d/riskit

# Verify next-fire times:
systemctl list-timers riskit-*
```

## Units

| Unit | Purpose | Cadence |
|---|---|---|
| `riskit-backup.service`+ `.timer` | Nightly online SQLite backup of user_kv + session_store | Daily 02:00 UTC |
| `riskit-backup-restore-test.service` + `.timer` | Integrity check of the latest backup | Weekly Mon 03:30 UTC |
| `dynasty-healthcheck.service` + `.timer` + `.sh` | Backend LIVENESS watchdog: probes `/api/health`, restarts `dynasty` after 3 consecutive no-response probes; app-degraded 503s (stale data / failed scrape) are log-only and never restart | Every 1 min |

Related units living elsewhere in deploy/:

- `deploy/backup/riskit-state-backup.*` — nightly full-state backup
  (sqlite + public_league/ + intel/ + scraper session secrets), 02:30 UTC.
- `deploy/monitoring/riskit-uptime.*` — public-URL uptime probe, 5 min.

`deploy/apply_hardening.sh` installs/refreshes all of the above
idempotently (see docs/PROD-HARDENING.md).

**Root-run scripts execute from `/usr/local/lib/riskit/`, not the
checkout.**  `dynasty-healthcheck.sh` and
`deploy/backup/riskit-state-backup.sh` run as root, so the apply
script installs root:root 0755 copies outside the deploy-user-writable
repo and the units point there — a root unit executing a
checkout-writable file would let a compromised deploy account escalate
to root.  Re-run the apply script to roll out script changes; the
repo copies are the source of truth but are inert at runtime.

`dynasty.service.template` / `dynasty-frontend.service.template` are
rendered (placeholder substitution) by `deploy/install-systemd-service.sh`
— do not copy them into /etc/systemd/system verbatim.

## Manual runs

```bash
# Force a backup now.
sudo systemctl start riskit-backup.service

# Verify latest backup manually.
sudo -u dynasty /home/dynasty/trade-calculator/deploy/backup_user_kv.sh --restore-test
```

## Observability

Backups write to `/var/log/riskit-backup.log`.  Successful run ends
with `nightly backup complete: <ISO timestamp>`.  Failed restore-
test exits non-zero and logs `ERROR`.

Logrotate config (`deploy/logrotate.conf`) keeps 14 days of
backup logs + application logs (`/var/log/dynasty.log`,
`/var/log/dynasty-frontend.log`).
