# State-backup truthfulness: what the app can and cannot see (A2, 2026-10-27)

**Status:** code changes are in a DRAFT PR. Nothing on this page has been
deployed or verified in production. The production actions at the end are for
the owner or operator. No agent has run them.

## What production reports

From a read-only `curl https://chaseupside.com/api/status` on 2026-10-27:

```
backup_health.stateBackup = {state: "unverifiable", reason: "permission_denied",
  directoryRole: "canonical", inspectionReason: "canonical_root_unreadable",
  roots: [ {canonical:       unverifiable / permission_denied},
           {writer_fallback: healthy, 0.79 h, 14 generations} ] }
backup_health.newestBackupAgeHours = 6.92   # LEGACY riskit-backup.timer only
```

## The expected layout, from code and unit files

| Item | Value | Source |
|---|---|---|
| Nightly state backup | `riskit-state-backup.service`, 02:30 UTC, runs as **root** from `/usr/local/lib/riskit/riskit-state-backup.sh` | `deploy/backup/riskit-state-backup.service` |
| Canonical root | `/var/backups/riskit-state`: the writer sets `umask 077` and runs `chmod 700`, so it is root-only | `deploy/backup/riskit-state-backup.sh:189,221` |
| Writer fallback | `/home/dynasty/backups/riskit-state`. It is used when the canonical root is not writable, and by the post-deploy backup+restore proof, which runs the checkout copy as the deploy user and skips the temporal and intel ledgers | `backup_root_lib.sh`, `deploy/diagnostics/retention_backup_restore_proof.sh` |
| What it covers | `user_kv`, `session_store`, `guest_passes`, the retention and evidence stores, the temporal and intel ledgers (OPTIONAL), and the scraper session cookies (secrets, 0600) | `deploy/backup/README.md` |
| App process user | `dynasty` (`User=__APP_USER__` in `dynasty.service.template`) | `deploy/systemd/dynasty.service.template` |
| Legacy SQLite backup | `riskit-backup.timer` / `deploy/backup_user_kv.sh`, writing to `/var/backups/riskit/daily` or `/home/dynasty/backups/riskit/daily` | `src/api/backup_health.py` |

**So the `permission_denied` is correct.** The app runs as `dynasty`. It cannot
list a 0700 root-owned directory written by a root job. The healthy
writer-fallback root is almost certainly the post-deploy proof's own run, made
at deploy time. It is not the nightly backup. Promoting it to "the state backup
is healthy" would certify a run that leaves out the ledgers.

## Does the app ever report unknown as healthy?

`src/api/backup_health.py` does not. When a root exists but cannot be read, the
whole answer is `unverifiable`, even if another root is healthy, because a newer
generation may sit behind the closed door. `tests/api/test_backup_health.py`
pins this.

**The monitor that reads it did.** `.github/workflows/health-check.yml` judged
only the legacy top-level keys. It printed `SQLite backup freshness OK.` and
never read `stateBackup`. That step is fixed in this PR:

| Served `stateBackup` | Meaning (A2 vocabulary) | health-check.yml now |
|---|---|---|
| `healthy` plus `evidenceSource: directory_listing` | healthy, measured | prints `State backup: healthy, measured` |
| `healthy` with no evidence source | never measured | `::warning State backup NOT MEASURED` |
| `stale` | stale | `::error`, exit 1 |
| `missing` (`directory_not_found` / `no_generations`) | unavailable | `::error`, exit 1 |
| `unverifiable` / `permission_denied` | unauthenticated: the app may not look | `::warning State backup NOT MEASURED` (today's production state) |
| `unverifiable` / `probe_error` or `age_unknown`, or the block is absent | never measured | `::warning State backup NOT MEASURED` |
| unit **failed** (`ExecMainStatus` not 0 or 3) | failed | **not observable by the app.** Only the post-deploy proof reads it (`systemctl show`), and only as a `::warning` |

The legacy line now reads `Legacy SQLite backup freshness OK.`, so the OK is
about the legacy backup and nothing more. Pinned by
`tests/deploy/test_monitoring_truthfulness.py`.

The stale-backup e-mail in `/api/health` still watches only the legacy backup.
It was not changed: alerting on a state the app cannot measure would page every
five minutes.

## Owner decision needed (NEEDS_OWNER_DECISION)

Making the nightly measurable from the app needs a production change. Pick one:

1. **Group-readable canonical root.** For example `root:dynasty 0750` on
   `/var/backups/riskit-state` and `daily/`, with the writer's `chmod 700`
   changed to match. This is a permission change. The generation contains
   session-cookie secrets, so the `dynasty` user would gain read access to the
   0600 copies only if their modes change as well. Usually they would not.
2. **A path-free status marker written by the root job.** For example
   `/var/lib/riskit-state-backup/status` (0644) holding `promoted_at`, the exit
   status, and the artifact count, which `backup_health.py` would read as a new
   `evidenceSource`. This changes the root-run script and adds one
   world-readable file. It touches no permissions on the backup itself.
   **Recommended.**
3. **Accept `unverifiable`.** Keep the warning. Verify the backup with the
   commands below after each deploy.

## Production-only actions (owner or operator; agents have no box access)

Read-only confirmation commands. Each one changes nothing:

```bash
sudo ls -ld /var/backups/riskit-state /var/backups/riskit-state/daily
sudo ls -1 /var/backups/riskit-state/daily | tail -3
sudo cat /var/backups/riskit-state/last_generation
systemctl show riskit-state-backup.service -p Result -p ExecMainStatus -p ExecMainExitTimestamp
systemctl list-timers riskit-state-backup.timer --no-pager
sudo tail -n 30 /var/log/riskit-state-backup.log
id dynasty; systemctl show dynasty.service -p User -p Group
ls -ld /home/dynasty/backups/riskit-state /home/dynasty/backups/riskit-state/daily
cat /home/dynasty/backups/riskit-state/last_generation
sudo -u dynasty python3 -m src.api.backup_health   # run from the app dir: the app's own view
sudo python3 -m src.api.backup_health              # run from the app dir: root's full view
```

Mutating actions belong to the owner and run only after the decision above:
change the permissions (option 1), deploy the status-marker change (option 2),
or record option 3.
