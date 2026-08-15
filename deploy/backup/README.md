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

Every artifact is integrity-checked before the run reports success:
SQLite copies get `PRAGMA integrity_check` (run against the *copied*
database — `gzip -t` alone only proves the compressed stream is
intact, while structural corruption copies page-for-page through
`Connection.backup()`), then `gzip -t`; tarballs get `tar -tzf`.  A
failed check rejects the artifact like any other error — and when the
artifact is required, it blocks promotion entirely.

## Layout & retention

```
/var/backups/riskit-state/
├── last_generation                        ← machine-readable pointer
└── daily/YYYY-MM-DD/
    ├── sqlite/    user_kv.sqlite.gz, session_store.sqlite.gz, guest_passes.sqlite.gz
    ├── files/     rank_history.jsonl.gz
    ├── dirs/      public_league.tar.gz, intel.tar.gz, faab.tar.gz, …
    └── sessions/  repo.*.json, workdir.*.json   (mode 0600)
```

Rotation keeps the newest **14** dated directories (`KEEP_DAILY`).
Falls back to `/home/dynasty/backups/riskit-state` if `/var/backups`
is not writable.

### Where the backup actually went

`BACKUP_ROOT` is what was *requested*. The effective root can be the
fallback, so **nothing may re-derive the location** — it is resolved once,
by `backup_root_lib.sh`, which owns the requested primary, the writability
determination and the fallback for every caller.

After a successful promotion the writer records what it did:

```
schema=1
effective_root=/home/dynasty/backups/riskit-state
generation=/home/dynasty/backups/riskit-state/daily/2026-08-15
date_stamp=2026-08-15
artifacts=14
promoted_at=2026-08-15T02:31:07Z
```

at `<effective_root>/last_generation`, and additionally at
`$BACKUP_RESULT_FILE` when a caller sets it. `promoted_at` is fixed-width
ISO-8601 UTC, so string order is chronological order.

`retention_backup_restore_proof.sh` reads that pointer rather than
guessing, which is what holds the invariant *the location that received
the promoted backup is the location the proof inspects*. Before the shared
owner existed, the two disagreed the first time the fallback fired:
production proof run **31872681688** reported "no backup generation under
/var/backups/riskit-state/daily" for a backup that had succeeded in the
fallback. Pinned by `tests/deploy/test_backup_root_resolution.py`, which
runs both shipped scripts end to end.

Log lines are for humans and are not an API — do not parse them.

> **Two copies of the writer exist, deliberately.** The nightly systemd
> job runs the root-owned copy at `/usr/local/lib/riskit/` (see the
> security note in `riskit-state-backup.service`), which only
> `apply_hardening.sh` updates; the backup+restore proof runs the
> checkout copy as the deploy user. A deploy therefore updates what the
> proof exercises but **not** what the nightly runs — re-run
> `sudo bash deploy/apply_hardening.sh` to move a script change into the
> nightly. The installer ships `backup_root_lib.sh` beside the root copy
> for exactly this reason.

Destructive steps run strictly last: artifacts are written into a
hidden staging dir, integrity-checked, and only a fully validated
snapshot is promoted into `daily/`, mirrored off-box, or allowed to
trigger pruning.  A failing run discards its own staging dir and
leaves every prior generation (including an earlier same-day
snapshot) untouched — consecutive failures can never erode the
retained history.

A snapshot must also contain the CORE state to count: `BACKUP_REQUIRED`
(default `user_kv.sqlite session_store.sqlite`) lists the items that
must be written and verified before promotion.  This closes the
partial-snapshot hole where an unmounted/mistyped `DATA_DIR` with a
stray session JSON still produced a nonzero artifact count.  Add dir
names to require them too, via a service drop-in:
`Environment="BACKUP_REQUIRED=user_kv.sqlite session_store.sqlite public_league"`.

**Security note**: the systemd unit runs the ROOT-OWNED copy of the
script installed at `/usr/local/lib/riskit/riskit-state-backup.sh` by
`deploy/apply_hardening.sh` — never the checkout copy (a root unit
executing a deploy-user-writable file would be a privilege-escalation
path).  After changing the script in the repo, re-run
`sudo bash deploy/apply_hardening.sh` to roll it out.

## Install

```bash
# Root-owned script copy OUTSIDE the checkout (the unit executes this):
sudo install -o root -g root -m 0755 -D deploy/backup/riskit-state-backup.sh /usr/local/lib/riskit/riskit-state-backup.sh
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

Local-only by default.  To mirror to another host (an object-storage or Storage Box target,
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
