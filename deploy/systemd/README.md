# systemd units — Risk It platform

## Install (on the VPS)

```bash
# Copy units into /etc/systemd/system/
sudo cp deploy/systemd/*.service deploy/systemd/*.timer /etc/systemd/system/
sudo systemctl daemon-reload

# Enable + start the timers (the .service units are triggered by them).
sudo systemctl enable --now riskit-backup.timer
sudo systemctl enable --now riskit-backup-restore-test.timer

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
