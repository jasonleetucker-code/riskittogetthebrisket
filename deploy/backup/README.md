# deploy/backup — nightly state backups

Nightly local backup of every piece of production state that cannot be
regenerated from the repo or re-scraped.

## What gets backed up

| Input | How | Guarded? |
|---|---|---|
| `data/user_kv.sqlite` | SQLite online backup → `.sqlite.gz` | skip if absent |
| `data/session_store.sqlite` | SQLite online backup → `.sqlite.gz` | skip if absent |
| `data/guest_passes.sqlite` | SQLite online backup → `.sqlite.gz` | skip if absent |
| `data/public_league/` | `tar.gz` | skip if absent |
| `data/intel/` | `tar.gz` | skip if absent (does not exist yet) |
| `dlf_session.json`, `draftsharks_session.json`, `idpshow_session.json` (repo root) | copy, mode 0600 | skip if absent |
| `/var/lib/dlf-fetch/dlf_session.json`, `/var/lib/idpshow-fetch/idpshow_session.json` | copy, mode 0600 | skip if absent/unreadable |

The session cookie files are **secrets** (gitignored via `*_session.json`).
They are backed up **on-box only**, under `umask 077`, and must never be
committed to the repo or synced anywhere public.  The IDP Show session
in particular can only be re-provisioned by hand (captcha-gated login),
which is exactly why it is worth backing up.

SQLite copies use the `sqlite3.Connection.backup()` online-backup
primitive via the venv python (same approach as the existing
`deploy/backup_user_kv.sh` — the sqlite3 CLI is not installed on the
box), so they are consistent under concurrent writes (WAL).

Every artifact is integrity-checked (`gzip -t` / `tar -tzf`) before the
run reports success.

## Layout & retention

```
/var/backups/riskit-state/daily/YYYY-MM-DD/
├── sqlite/    user_kv.sqlite.gz, session_store.sqlite.gz, guest_passes.sqlite.gz
├── dirs/      public_league.tar.gz, intel.tar.gz
└── sessions/  repo.*.json, workdir.*.json   (mode 0600)
```

Rotation keeps the newest **14** dated directories (`KEEP_DAILY`).
Falls back to `/home/dynasty/backups/riskit-state` if `/var/backups`
is not writable.

## Install

```bash
sudo cp deploy/backup/riskit-state-backup.service deploy/backup/riskit-state-backup.timer /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now riskit-state-backup.timer
systemctl list-timers riskit-state-backup.timer
```

(`deploy/apply_hardening.sh` does all of this idempotently.)

Manual run / check:

```bash
sudo systemctl start riskit-state-backup.service
sudo tail -n 30 /var/log/riskit-state-backup.log
sudo ls -la /var/backups/riskit-state/daily/$(date -u +%F)/
```

## Optional off-box mirror (operator opt-in)

Local-only by default.  To mirror to another host (Hetzner Storage Box,
another VPS, …):

```bash
sudo systemctl edit riskit-state-backup.service
# add:
#   [Service]
#   Environment="OFFBOX_RSYNC_DEST=u123456@u123456.your-storagebox.de:riskit-state/"
```

Requires `rsync` on the box and non-interactive SSH auth (key in
root's `~/.ssh`, destination host key accepted once by hand).  A mirror
failure logs a warning and exits non-zero but never blocks the local
backup.  Remember the mirror includes the session **secrets** — only
mirror to storage you control.

## Relationship to `riskit-backup.timer` (existing)

`deploy/backup_user_kv.sh` (02:00 UTC) covers only the three sqlite
files but keeps 30 daily + 12 monthly generations, and has a weekly
restore test (`riskit-backup-restore-test.timer`).  This job (02:30
UTC) is a per-night superset with 14-day retention.  **Keep both
enabled**: the overlap costs a few MB per night and preserves the long
monthly sqlite history plus the exercised restore path.

## Restore

```bash
# SQLite (stop the backend first so it doesn't hold the old file):
sudo systemctl stop dynasty
gunzip -c /var/backups/riskit-state/daily/<DATE>/sqlite/user_kv.sqlite.gz \
  | sudo -u dynasty tee /home/dynasty/trade-calculator/data/user_kv.sqlite >/dev/null
sudo systemctl start dynasty

# Directory:
sudo -u dynasty tar -xzf /var/backups/riskit-state/daily/<DATE>/dirs/public_league.tar.gz \
  -C /home/dynasty/trade-calculator/data/

# Session cookies (repo copy; fix ownership + mode):
sudo install -o dynasty -g dynasty -m 0600 \
  /var/backups/riskit-state/daily/<DATE>/sessions/repo.idpshow_session.json \
  /home/dynasty/trade-calculator/idpshow_session.json
```
