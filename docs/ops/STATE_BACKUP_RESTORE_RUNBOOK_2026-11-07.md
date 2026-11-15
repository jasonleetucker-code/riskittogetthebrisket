# State backup / restore verification — operator runbook (2026-11-07)

Owner directive 2026-11-07 §6 (intake MD-63, work item CW-05). Agents cannot run these steps: they need root on the
production box. This runbook is exact; paste the evidence lines it asks for into the CW-05 row (or a PR comment) and
the record can then say VERIFIED. Until then the restore half stays **HUMAN_ACTION_REQUIRED**.

Never restore into the live `data/` directory. Never delete backup history to clear a warning. Everything below is
read-only against production state except the nightly backup run in step 2 (which writes a new generation).

## 0. What is already verified from public endpoints (no box access)

`GET https://chaseupside.com/api/status` → `backup_health` at 2026-11-07 ~10:15Z:

- `stateBackup.state: healthy`, `reason: within_threshold`, 14 generations, evidence `directory_listing`;
  the **canonical** root (`directoryRole: canonical`) is now listable by the backend (newest generation 7.5 h old,
  matching the 02:30 UTC timer), so #2064's group-list fix is installed and effective (it reported
  `unverifiable / permission_denied / canonical_root_unreadable` on 2026-11-06).
- `legacySqliteBackup.state: healthy` (8.3 h); `dbCount: 4`; filesystem paths withheld (as designed).

That proves installation, generation, group-level visibility and backend observability. It does **not** prove a
restore works — that is steps 3–4.

## 1. Preconditions

```bash
cd /home/dynasty/trade-calculator && git pull --ff-only origin main
systemctl status riskit-state-backup.timer --no-pager
systemctl list-timers 'riskit-state-backup*' --no-pager
```
Expected: timer `active (waiting)`, next run 02:30 UTC.

## 2. (Only if step 0 ever regresses) re-install and run once

```bash
sudo bash deploy/backup/install_state_backup.sh
sudo systemctl start riskit-state-backup.service
sudo journalctl -u riskit-state-backup --since "-15 min" --no-pager | tail -40
sudo ls -ld /var/backups/riskit-state /var/backups/riskit-state/daily
```
Expected: exit status 0 (or 3 = an OPTIONAL store shed/failed — read `optional_stores.tsv`); root and `daily/` are
`drwxr-x--- root dynasty`.

## 3. Restore verification into an isolated scratch directory (the step that matters)

```bash
sudo python3 scripts/verify_state_backup_restore.py --scratch-dir /var/tmp --full --json \
  | tee /var/tmp/restore-verify-$(date -u +%Y%m%dT%H%M%SZ).json
echo "exit=${PIPESTATUS[0]}"   # the script's exit status, not tee's
```
- Restores the newest generation's SQLite artifacts into a temporary directory under `/var/tmp` (deleted after),
  runs `PRAGMA integrity_check` (`--full`), and reads every tarball. It never touches `data/`.
- Exit codes: `0` all restored artifacts pass; `1` any artifact fails or the generation has none (missing is never a
  pass); `2` no backup root/generation found.
- To check one store quickly: `--only temporal_ledger --only intel_ledger` (substring filters).
- Two roots can hold generations: the canonical root and a writer-fallback root (`/api/status` reports
  `writer_fallback_root_newer` when the fallback is newer — seen 2026-11-07). The script picks the newest generation
  across its default roots; record which root and generation id it restored, and if the canonical root is the one
  that matters for retention, re-run with `--root <canonical root>` so both are verified.

**Evidence to record:** the exit code, the generation id, and the per-artifact `ok` lines from the JSON (no paths or
contents are needed).

## 4. Store coverage

Compare the restored artifact list with the store list in `deploy/backup/README.md` ("What gets backed up") and
`docs/retention/RETENTION_REGISTER.md`. CORE stores (`user_kv.sqlite`, `session_store.sqlite`; `BACKUP_REQUIRED`)
must be present; each OPTIONAL store is either present or named in that generation's `optional_stores.tsv` with a
reason. Record any store that is neither.

## 5. Related timers (no change requested)

```bash
systemctl list-timers '*weekly-projection-capture*' '*pre-auction-snapshot*' '*forecast-calibration-ledger*' \
  '*dfs-auto-refresh*' --no-pager
```
Expected: all `active`. `dynasty-dfs-auto-refresh` keeps running by owner decision `ODR-DFS-TIMER-KEEP` (DD-14) —
do **not** disable it.

## 6. Port 8000 is not reachable externally

On the box: `sudo ss -ltnp | grep ':8000'` → the backend must listen on `127.0.0.1:8000` (loopback), not
`0.0.0.0:8000`. From any host OUTSIDE the box (a laptop, not the agent sandbox — its egress proxy only allows web
ports, so a failed probe from there proves nothing): `nc -vz -w 5 chaseupside.com 8000` → must time out or be refused.
`tests/deploy/test_loopback_bind.py` pins the loopback bind in the repo.

## 7. Done criteria

- Step 3 exit `0` with `--full`, on a generation ≤ 26 h old.
- Step 4: every CORE store restored; every OPTIONAL store restored or explained.
- Step 6: loopback-only listener and a failed external probe.

Record the evidence lines; only then mark CW-05 / MD-63 VERIFIED.
