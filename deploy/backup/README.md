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
| `data/intel/ledger.sqlite3` | **OPTIONAL** SQLite online backup → `intel_ledger.sqlite3.gz` | skip if absent |
| `data/intel/` | `tar.gz` — excludes the live `ledger.sqlite3*` only when the online copy above succeeded; otherwise the raw ledger files ride in the tar (pre-AL-P2 path, corruption tolerant) | skip if absent |
| C1A retention + AL-0 stores | SQLite online backup / `tar.gz` (CORE) | skip if absent |
| AL-P2 evidence stores | SQLite online backup / `tar.gz` (**OPTIONAL**) — the authoritative list is the script itself, each line justified in place; per-store retention and rebuildability in `docs/retention/RETENTION_REGISTER.md` | skip if absent |
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

### CORE and OPTIONAL stores

Every store that predates AL-P2 is **CORE**: if its online copy, integrity
check, gzip or tar fails, the whole generation is discarded and the run exits
1 — prior generations stay untouched. The AL-P2 additions (wrapped in
`optional` in the script) are **OPTIONAL**: a failure is a `[WARN]`, a row in
`<generation>/optional_stores.tsv` (`name<TAB>status<TAB>detail`, status
`failed` / `skipped_low_space` / `skipped_space_unmeasurable` /
`skipped_requested`), and the generation is **kept**. A failed store's partial
artifact is removed *before* the row is written, and the row append itself is
failure-tolerant: if it cannot be written (disk full) the run WARNs and keeps
the generation — failing to record an optional failure never discards CORE. One corrupt optional store (the intel ledger has a corruption history
on the box) can therefore never stop `user_kv` / `session_store` being backed
up.

Exit codes: **0** everything that exists was backed up · **1** hard failure
(no generation, a CORE failure, required state missing, mirror failed) · **3**
generation promoted with every CORE store but an OPTIONAL store failed or was
shed. The unit maps 3 to success (`SuccessExitStatus=3`) so it does not mark
the box failed every night; it stays visible as `ExecMainStatus=3`, in the
log and in `optional_stores.tsv`.

Where a **nightly** exit 3 actually surfaces: the post-deploy proof
(`deploy/diagnostics/retention_backup_restore_proof.sh`) reads the unit's last
`Result` / `ExecMainStatus` with an unprivileged `systemctl show
riskit-state-backup.service` and emits a `::warning::` annotation when it is 3
(or a failure). That is the next deploy, not 02:30 — nothing pages in between.
The proof's *own* backup run is a different run: it skips
`temporal_ledger.sqlite` and `intel_ledger.sqlite3` on purpose, so its own
exit 3 can only reflect the small optional stores. The deploy user cannot read
the root-only generation, so the store name comes from
`sudo journalctl -u riskit-state-backup` or the generation's
`optional_stores.tsv`.

**Free space.** Before writing anything the run needs
`max(2 × newest generation, BACKUP_MIN_FREE_KB)` free (default 5 GiB), and each
optional store `2 × (its source + its -wal) + BACKUP_STORE_MARGIN_KB` (default
1 GiB). Short → every OPTIONAL store is shed (`skipped_low_space`, exit 3) and
CORE is still written. Unmeasurable — `df` or `du` fails or prints nothing
numeric, run-wide or for one store — is treated as short, not roomy
(`skipped_space_unmeasurable`, exit 3); a failing measurement never exits the
run. CORE runs first and the 1.5 GB temporal ledger last.

`BACKUP_SKIP_OPTIONAL="name ..."` leaves named optional artifacts out on
purpose (`skipped_requested`, not a warning). The post-deploy proof uses it for
`temporal_ledger.sqlite intel_ledger.sqlite3` — see the proof script header.

**Bounded runs.** `TimeoutStartSec=2h` on the unit. An EXIT/INT/TERM trap removes
the run's own staging directory, and each run holds an `flock` on
`daily/.staging-<date>-<pid>.lock`; the start-of-run sweep removes every staging
directory no live process holds (PID check for lock-less ones) rather than
waiting a day. A run whose own staging name already exists (a SIGKILLed run
whose PID was reused the same day) removes it before writing, so a dead run's
partial artifacts can never ride into a new generation.

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
> security note in `riskit-state-backup.service`); the backup+restore
> proof runs the checkout copy as the deploy user. Since AL-P2
> (2026-10-01) every deploy refreshes the root copy on content drift:
> `deploy/install-systemd-service.sh::refresh_state_backup_line` sources
> `install_state_backup.sh` (the one installer) and rewrites only what
> differs, via `sudo -n install`. Before that only `apply_hardening.sh`
> updated it, and production's nightly ran the 2026-08-16 copy until
> 2026-10-01 — missing acquisition, auction and `game_day`. The installer
> ships `backup_root_lib.sh` beside the root copy, library first.

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
`deploy/backup/install_state_backup.sh` — never the checkout copy (a root
unit executing a deploy-user-writable file would be a privilege-escalation
path).  A merged script change reaches it on the next deploy (drift-aware
refresh, see above); `bash deploy/backup/install_state_backup.sh` does the
same on demand.

## Install

```bash
# The sourced resolver FIRST — the writer hard-fails without it, and the
# timer fires at 02:30 UTC, so the reverse order can cost a whole night's
# backup. Sourced, never executed: 0644.
sudo install -o root -g root -m 0644 -D deploy/backup/backup_root_lib.sh /usr/local/lib/riskit/backup_root_lib.sh
# Root-owned script copy OUTSIDE the checkout (the unit executes this):
sudo install -o root -g root -m 0755 -D deploy/backup/riskit-state-backup.sh /usr/local/lib/riskit/riskit-state-backup.sh
sudo cp deploy/backup/riskit-state-backup.service deploy/backup/riskit-state-backup.timer /etc/systemd/system/
sudo systemctl daemon-reload
# Arms the 02:30 schedule only — the timer carries no Requires= on the
# service, so this does not run a backup now.
sudo systemctl enable riskit-state-backup.timer
sudo systemctl start riskit-state-backup.timer
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

**First check what the generation does NOT hold.** If
`<DATE>/optional_stores.tsv` exists, every store it lists is absent from that
generation (with the reason); take that store from an older generation.

**Labelled artifacts restore under a different name.** Artifact names are
unique inside a generation, so some do not match the live file name. Stop the
writer of each store first (the backend for most; the named timer otherwise),
then restore to the live path:

| artifact in the generation | live path | stop first |
|---|---|---|
| `sqlite/intel_ledger.sqlite3.gz` | `data/intel/ledger.sqlite3` | `dynasty` + the `dynasty-sharp-*` timers |
| `sqlite/market_trades_archive.sqlite.gz` | `data/market_trades/archive.sqlite` | `dynasty-ktc-trades.timer` |
| `sqlite/source_archive_boards.sqlite.gz` | `data/source_archive/boards.sqlite` | `dynasty` (scrape) |
| `sqlite/dfs_workspace.sqlite.gz` | `data/dfs/workspace.sqlite` | `dynasty` + `dynasty-dfs-auto-refresh.timer` |
| `sqlite/consensus_edge.sqlite.gz` | `data/consensus_edge.sqlite` | `dynasty-consensus-edge-snapshot.timer` |
| `sqlite/own_league_format_captures.sqlite.gz` | `data/leagues/own_league_format_captures.sqlite` | the `dynasty-sharp-transactions` timer |
| `sqlite/temporal_ledger.sqlite.gz` | `data/temporal_ledger.sqlite` | `dynasty` (live recorder) |
| `dirs/market_trades_reports.tar.gz` | `data/market_trades/reports/` | — |
| `dirs/playerctx_history.tar.gz` | `data/playerctx/history/` | — |
| `dirs/bdvm.tar.gz`, `forecast_archive`, `pick_forecast_snapshots`, `sparse_evidence_shadow`, `robust_filter_shadow` | `data/<name>/` | — |

```bash
# A labelled SQLite artifact — remove the old WAL/SHM first, or SQLite will
# replay a stale WAL onto the restored file:
sudo systemctl stop dynasty
sudo -u dynasty rm -f /home/dynasty/trade-calculator/data/intel/ledger.sqlite3-wal \
                      /home/dynasty/trade-calculator/data/intel/ledger.sqlite3-shm
gunzip -c /var/backups/riskit-state/daily/<DATE>/sqlite/intel_ledger.sqlite3.gz \
  | sudo -u dynasty tee /home/dynasty/trade-calculator/data/intel/ledger.sqlite3 >/dev/null
sudo systemctl start dynasty

# A labelled directory — the tar MEMBER is the real directory name, so extract
# into the parent of the live directory:
sudo -u dynasty tar -xzf /var/backups/riskit-state/daily/<DATE>/dirs/market_trades_reports.tar.gz \
  -C /home/dynasty/trade-calculator/data/market_trades/
```

When `sqlite/intel_ledger.sqlite3.gz` is absent (listed in
`optional_stores.tsv`, or a pre-AL-P2 generation), the ledger is inside
`dirs/intel.tar.gz` as raw `ledger.sqlite3*` files: extract it into `data/` and
run `PRAGMA integrity_check` before starting the crawlers.

**What the post-deploy proof restore-checks.** `retention_backup_restore_proof.sh`
restores and verifies every CORE artifact and the small AL-P2 ones (KTC archive,
own-league captures, format boards, Consensus Edge, DFS workspace, the AL-P2
directories). It deliberately does **not** restore the temporal ledger
(1.5 GB) or the intel-ledger online copy (0.7 GB) on every deploy — its backup
run skips writing them — so those two are verified by hand against a nightly
generation: restore with the commands above into a scratch path and run
`PRAGMA integrity_check`.
