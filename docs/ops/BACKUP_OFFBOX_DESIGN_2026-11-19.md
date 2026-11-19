# Off-box backup: destination comparison, recommendation and setup (STAB-4)

Date: 2026-11-19. Owner directive intake STAB-4. **Recommendation for an owner decision. No provider was chosen, no
account created, nothing configured or contacted, and no data left the box.** Builds on `deploy/backup/README.md`,
`docs/ops/ADMIN_ONLY_ACTIONS_RUNBOOK.md` section 5 (Path A) and `docs/ops/STATE_BACKUP_RESTORE_RUNBOOK_2026-11-07.md`.

## 1. What is backed up today

Nightly `riskit-state-backup.service` (02:30 UTC, root, root-owned copy under `/usr/local/lib/riskit/`) writes a dated
generation under `/var/backups/riskit-state/daily/<date>/` (fallback `/home/dynasty/backups/riskit-state`), promoted only
after every artifact is integrity-checked. Contents (authoritative list: `deploy/backup/README.md`, in the script):

| Group | Artifacts |
|---|---|
| SQLite online backups, `integrity_check`ed | `user_kv`, `session_store`, `guest_passes`, the retention and evidence stores, `analyst_ledger`, the intel ledger, `temporal_ledger` (OPTIONAL, the largest) |
| Directory tarballs | `public_league`, `intel`, `faab`, and the other box-local evidence directories |
| Secrets (mode 0600, never committed) | scraper sessions: `dlf_session.json`, `draftsharks_session.json`, `idpshow_session.json` (the IDP Show session is captcha-gated and can only be re-provisioned by hand) |

Retention: newest **14** dated generations (`KEEP_DAILY`). CORE failure discards the generation; an OPTIONAL store failure
keeps it with a row in `optional_stores.tsv` (exit 3). Size, from the retention register: 125 MB per generation measured on
2026-08-15; about **470 MB** estimated after the AL-P2 additions (temporal ledger 220 MB gz, intel ledger 158 MB gz, the
rest small), **not measured end to end**. Two lineages of 14 sit on one 96 GB disk (60 GB free at the last
measurement). **Measured 2026-11-18: all 14 retained generations are on the production disk; there is no off-box copy.**
Losing that disk loses every copy, including the session cookies and the user/session databases.

## 2. What already exists to build on

| Piece | State |
|---|---|
| `scripts/offbox_backup.py` | opt-in, stdlib. `copy`: restore-verify the newest generation locally, copy to `dir:`/`rsync:`/`rclone:`, re-read from the target and compare SHA-256; never passes `--delete`. `drill`: pull from the target into a temp directory, check the manifest, run the restore verification. Disabled unless `OFFBOX_BACKUP_TARGET` is set. |
| Refuses unless the owner states the target is encrypted | `OFFBOX_BACKUP_ACK_ENCRYPTED_TARGET=1`. Before this change that was the **only** encryption control. |
| `deploy/backup/offbox/*.example` | service (03:30 UTC after the 02:30 backup) and timer templates; installed by hand, never by deploy |
| `src/api/backup_health.py` | already reads `<root>/last_mirror` (`offboxMirror`: `none_recorded` / `recorded` + age / `clock_skew` / `unverifiable`) but only the old rsync mirror ever wrote it |
| `src/utils/owner_notify.py`, `NOTIFY_WEBHOOK_URL` | the box's one owner push channel (a private ntfy topic), used by `deploy/monitoring/uptime_check.sh` |
| Any destination already available | **None found.** No cloud-storage provider, bucket, remote or storage-box host is configured anywhere in the repository. `deploy/backup_user_kv.sh` mentions an optional `BACKUP_S3_BUCKET` mirror that nothing sets. The box host is Contabo (per `CLAUDE.md`); a retired deploy key titled "hetzner-riskit" suggests an earlier Hetzner box, but no usable storage account is evidenced. |

## 3. Destinations compared

Sizing used: about 0.5 GB per generation, **30 daily generations kept off-box, no deduplication** (each generation is a
full copy through `rclone copy`) = **about 15 GB stored**, 0.5 GB uploaded nightly, one 0.5 GB restore drill a month. This
is an estimate from the register's unmeasured figure. Prices are the provider's public list prices as I could read them
today; "unverified" marks any I could not.

| | Backblaze B2 | Cloudflare R2 | AWS S3 (+ Glacier / Object Lock) | Second small VPS / storage box | Contabo object storage |
|---|---|---|---|---|---|
| Price source | backblaze.com/cloud-storage/pricing, read 2026-11-19: **$6.95 per TB per month**, egress free up to 3x stored, then $0.01/GB, no minimum storage duration | developers.cloudflare.com/r2/pricing, read 2026-11-19: **$0.015 per GB-month**, first 10 GB-month free, egress free | pricing tables did not render on 2026-11-19 (page fetch), so **rates unverified**; Standard about $0.023/GB-month and Deep Archive about $0.001/GB-month are from memory; Glacier classes carry 90 to 180 day minimum-storage charges | **unverified**: typically a flat fee of a few euros per month for 1 TB (for example Hetzner Storage Box); no price page read | **unverified**, not read |
| Monthly cost at about 15 GB | **about $0.10** | **about $0.08** (5 GB billable after the free 10 GB; operations negligible) | Standard **about $0.35 (unverified)**; Deep Archive well under $0.05 but unsuitable (below) | flat, about 3 to 5 euros (unverified) | unverified |
| Reliability | multi-site vendor storage with published durability; independent of the box's host | same class; independent | highest track record | one machine and one disk unless RAID; single provider account | **same vendor as the box**: one account suspension or billing dispute removes both copies |
| Restore speed | download at line rate; drills free within 3x allowance | free egress | Standard fast; Glacier Flexible takes hours, Deep Archive up to about 12 hours and bulk retrieval fees | fast over SSH | fast |
| Client-side encryption | `rclone crypt` over the remote; the provider never holds the key | same | same | `rclone crypt` over SFTP, or `restic`/`borg` | same |
| Compatible with `offbox_backup.py` | `rclone:` target, yes | `rclone:` target, yes | `rclone:` target, yes | `rsync:` / `rclone sftp:`, yes | `rclone:` (S3-compatible), yes |
| Deletion / compromise protection | key capabilities are chosen per application key (omit delete); **Object Lock** is offered on B2 per Backblaze documentation (**not confirmed from the pricing page**) | per-bucket key scopes; bucket retention-lock support **not verified** | Object Lock (compliance or governance mode) and IAM policy with no `s3:DeleteObject`: the strongest, and the most to configure | an SSH key restricted to append-only (`rsync` forced command or `borg --append-only`) is possible but is a hand-built control, and a root compromise of the box is the threat model | as S3 if offered; unverified |
| Operational complexity | low: one bucket, one key, rclone | low | highest (IAM, lifecycle, lock modes, storage-class rules) | medium: you patch and monitor another machine | low |

Eliminated: **Glacier / Deep Archive** (retrieval hours and 90 to 180 day minimums break a monthly drill and a fast
restore), **a second VPS you operate** (a second machine to patch and watch, and its disk is one more single point),
**Contabo storage** (correlated failure with the box). Between B2 and R2 the cost is a rounding error at this size.

## 4. Recommendation: Backblaze B2, through an `rclone crypt` remote, with a write-only application key and Object Lock

**Destination:** one private Backblaze B2 bucket (`riskit-state-offbox`), created with **Object Lock enabled** (it can only
be enabled at bucket creation), reached by `OFFBOX_BACKUP_TARGET=rclone:riskitcrypt:daily-state` where `riskitcrypt` is an
`rclone crypt` remote layered over the B2 remote.

Why B2 over R2: Backblaze documents Object Lock and per-key capability scoping (so the key on the box cannot delete or
shorten retention even if the box is compromised), the provider is independent of the box's host, and the price at this
size is about ten cents a month. R2 is the fallback with the same shape at about the same price, if the owner prefers
Cloudflare and confirms its bucket-lock support.

**Client-side encryption:** `rclone crypt` with filename encryption on. The generation holds session cookies and login
state, so the provider must never see plaintext. The crypt password and salt are generated by the owner, stored in the
owner's password manager **and** in `/root/.config/rclone/rclone.conf` (root, mode 0600). **Losing the password makes every
backup unreadable** and no one can recover it, so the offline copy is part of the setup, not an option. `offbox_backup.py`
now reports `encryption_evidence: rclone_crypt_remote` when `rclone config dump` shows the target remote is type `crypt`
(parsed in memory, never printed); anything else reads `not_verified`, and the owner's acknowledgement remains required.

**Credential, least privilege:** a B2 application key restricted to that one bucket with capabilities `listBuckets`,
`listFiles`, `readFiles` and `writeFiles` only, **no `deleteFiles`** and no `writeBucketRetentions` or
`bypassGovernance`. The master key stays offline with the owner. `rclone copy` only uploads, so the box can add
generations and overwrite today's copy (a new file version, the old one stays) but not remove anything.

**Retention (set on the bucket, not by the box):** Object Lock default retention 30 days in governance mode, plus a B2
lifecycle rule that deletes versions after 45 days. Pruning is then the provider's job under rules the box key cannot edit.
Keep at least 7 generations (runbook section 5).

## 5. Isolated restore test

The point is to prove the backup restores **without the box**, using only what the owner holds.

- **Where it runs:** the owner's own machine or a throwaway VM, never the production box and **never a GitHub-hosted runner
  or any CI** (the generations carry session cookies and user data, and the crypt key must not be put in GitHub). It needs
  `python3`, `rclone` and the repository's two scripts. It authenticates with a **separate read-only** B2 application key
  (`listBuckets`, `listFiles`, `readFiles`) and the crypt password from the password manager. Doing it from a machine that
  has never held the box's `rclone.conf` also proves the key is recoverable from the owner's records alone.
- **Command:** `python3 scripts/offbox_backup.py drill --json --scratch-parent <scratch dir>` with
  `OFFBOX_BACKUP_TARGET=rclone:riskitcrypt:daily-state` and the acknowledgement variable set. The scratch directory is
  deleted afterwards; a scratch path under a protected prefix is refused.
- **What it verifies:** every file re-read from the target matches the SHA-256 in `OFFBOX_MANIFEST.json`; every SQLite
  artifact restores and passes `quick_check` (`--full` for `integrity_check`); every tarball reads end to end;
  `restore_verified > 0`. Optionally run `scripts/auction_backup_verify.py` against the restored auction data.
- **Cadence:** after the first copy, monthly, and after any change of target, key or crypt password. Record the date and
  result only (no values) in `docs/auction/LAUNCH_CHECKLIST.md` item B.

## 6. Failure monitoring

Constraint: **the box has no working notification channel yet and SMTP is firewalled**, so the existing email path
(`dynasty-signal-alerts.timer`) cannot be relied on to reach the owner.

1. **Stale-copy health (added by this change).** After a copy that passed read-back verification, `offbox_backup.py copy`
   writes `<backup root>/last_mirror` (`mirrored_at`, `generation`, destination kind only, never the host or bucket). It is
   written only on success, so a failing target makes the age grow. `src/api/backup_health.py::alert_rows` now raises an
   `offbox_copy` row when a RECORDED copy is older than **48 hours** (`OFFBOX_COPY_STALE_AFTER_HOURS`), or its timestamp is
   unreadable, and `ops_alerts` turns it into a `backup_offbox_copy` alert. Never configured (`none_recorded`) raises
   nothing, because the copy is opt-in. The state is visible now with `python -m src.api.backup_health` on the box
   (`offboxMirror`). It is deliberately **not** added to the anonymous `/api/status` block, which withholds coverage detail by
   design.
   **Shared marker, and an operator action when you stop mirroring.** `<backup root>/last_mirror` is ALSO written by the
   existing nightly rsync mirror (`deploy/backup/riskit-state-backup.sh`, the `MIRROR_MARKER="${BACKUP_ROOT%/}/last_mirror"`
   block, which re-baselines it after each successful rsync when `OFFBOX_RSYNC_DEST` is set). Removing `OFFBOX_RSYNC_DEST`
   (or disabling the rclone copy) later therefore leaves a stale marker behind, and `backup_offbox_copy` keeps firing
   until the operator deletes it: **when you deliberately stop off-box mirroring, delete `<backup root>/last_mirror`
   (`sudo rm <backup root>/last_mirror`; the root is the one `python -m src.api.backup_health` reports).** Deleting it returns the state to
   `none_recorded` (no alert) and the next sweep sends one recovery notice. A marker that is corrupt or unreadable is
   `unverifiable`: the alert, if already firing, stays active and no recovery notice is sent (`offboxChecked` false in
   `alert_rows`), as for the ledger and proof alerts.
2. **Immediate failure push (optional, in the template).** `riskit-offbox-copy.service.example` now ends with an
   `ExecStopPost` that POSTs to `NOTIFY_WEBHOOK_URL` when the unit did not succeed. Put `NOTIFY_WEBHOOK_URL` (a private ntfy
   topic; treat the URL as a secret) in `/etc/riskit/offbox.env`. This is the existing owner push channel, so it works
   without SMTP. Unset, nothing is contacted.
3. **Backstops.** A failed `riskit-offbox-copy.service` appears in the daily failed-units sweep
   (`src/api/systemd_failures.py`), and the stale-copy alert fires on the same sweep, **but both ride the email path** until
   the owner configures a working channel; item 2 is therefore the only immediate signal, and the monthly drill (section 5)
   is the owner's independent check. Until a channel works, a person must look: `python -m src.api.backup_health` and
   `journalctl -u riskit-offbox-copy.service`.

## 7. Gaps found in `offbox_backup.py` and what changed

| Gap | Change |
|---|---|
| No health signal: a stale or failing off-box copy was invisible to backup health | `record_copy_marker` writes `last_mirror` after a verified copy; `alert_rows` and `ops_alerts` alert on staleness (section 6). Tests in `tests/deploy/test_offbox_backup.py` and `tests/api/test_backup_health_irreplaceable.py`. |
| Encryption at rest was only an acknowledgement | `encryption_evidence` (`rclone_crypt_remote` or `not_verified`) is reported in the copy result. Informational: it does not block, so an `rsync` or restic setup is not refused. |
| Template had no failure notice | optional `ExecStopPost` to `NOTIFY_WEBHOOK_URL` |

Not changed (and why): the target grammar, the never-`--delete` rule, the acknowledgement requirement, pruning (stays with
the provider's lifecycle), the nightly backup writer, and any deploy or installer: the templates still ship as `.example`.
The root-owned copy of `offbox_backup.py` is installed by the owner (runbook section 5), so these fixes reach the box only
when the owner re-installs it.

## 8. Owner approval and exact setup steps

Approval to give: **"Use Backblaze B2 with client-side `rclone crypt`, a bucket-scoped no-delete key and Object Lock, for
about $0.10 per month (estimate), and I will keep the crypt password offline."** Nothing below is done by an agent.

1. Create a Backblaze account (owner identity, payment method, two-factor).
2. Create a bucket `riskit-state-offbox`, private, **Object Lock enabled, default retention 30 days (governance)**, and a
   lifecycle rule deleting versions after 45 days.
3. Create two application keys limited to that bucket: **writer** (`listBuckets`, `listFiles`, `readFiles`, `writeFiles`;
   no delete) for the box, **reader** (`listBuckets`, `listFiles`, `readFiles`) for drills. Store both in the password
   manager. Never paste a key into chat, a ticket, a PR or a workflow.
4. On the box as root: `rclone config` (hidden prompts): remote `b2` with the writer key, then remote `riskitcrypt` of type
   `crypt` over `b2:riskit-state-offbox` with filename encryption on and **a generated password and salt**. Save both in the
   password manager now. `chmod 600 /root/.config/rclone/rclone.conf`.
5. Follow runbook section 5 **Path A** steps 1 to 4 with `OFFBOX_BACKUP_TARGET=rclone:riskitcrypt:daily-state` and
   `OFFBOX_BACKUP_ACK_ENCRYPTED_TARGET=1`. Expect the first copy to print `encryption_evidence=rclone_crypt_remote` and
   `health_marker=ok`. Add `NOTIFY_WEBHOOK_URL` to `/etc/riskit/offbox.env` if you want the immediate push.
6. Run the isolated drill (section 5) from your own machine with the **reader** key. Record the date and result.
7. Enable the nightly timer (runbook section 5 Path A step 5).
8. Confirm with `python -m src.api.backup_health` that `offboxMirror` reads `recorded` with a small age.

**Rollback:** `sudo systemctl disable --now riskit-offbox-copy.timer`, delete the two unit files and
`/etc/riskit/offbox.env`, `systemctl daemon-reload`. The local backup is untouched. Deleting the B2 key removes the box's
access; objects under Object Lock stay until retention expires (that is the protection working).

**Unverified in this document:** Object Lock and key-capability behaviour on B2 and R2 (documentation not fetched), all S3
and storage-box prices, the real generation size after AL-P2, and the actual behaviour of `rclone copy` against a locked
bucket on overwrite (test step 5 on a throwaway file first).
