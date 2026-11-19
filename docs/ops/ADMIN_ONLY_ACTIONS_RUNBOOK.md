# Administrator-only actions runbook

**Status:** operator checklist (owner directive 2026-10-18, D18 / D19 / D20; §1, §2, §3, §5 and the new §8 checklist revised 2026-11-18 by the audit-remediation admin pack, Task 4). Nothing in this file has been
executed by an agent, and no agent changes repository settings, deploy keys, secrets or system packages.
Each section says what to check, the exact command, how to verify it, and how to roll back.

**Never put a secret value in this repository, an issue, a PR, a workflow log or a chat.** Record only that an
action happened and when (for example "rotated 2026-10-19"), never the value.

Decision record: `docs/owner/OWNER_DECISION_CLOSEOUT_2026-10-18.md`. Live status of each item:
`docs/owner/OWNER_DECISION_REGISTER.md`.

| § | action | decision | blocks an authorized production feature? |
|---|---|---|---|
| 1 | Protected PR-based merging on `main` | D18 | No; it closes a review-bypass risk |
| 2 | Deploy-key inventory and retirement | D18 | No; retiring the wrong key WOULD break the box pushers |
| 3 | Rotate `JASON_LOGIN_PASSWORD` | D18 | No; it closes a credential-exposure risk |
| 4 | ~~Install Tesseract on the VPS~~ **done** (owner reported 5.3.4 installed, 2026-10-18); keep the post-install recognition checks | D19 | No longer blocking; recognition quality tracked by the full-page fix lane |
| 5 | Off-host encrypted backup for the official rookie auction | D20 | Not for mocks; required (or a documented risk acceptance) before the official auction |
| 6 | Re-enable authenticated production verification | Part 9 item 9 | Yes for proof: many rows stay DEPLOYED_NOT_PRODUCTION_VERIFIED until it runs |
| 7 | Immediate failure notice for the 38 `dynasty-*` timers (`OnFailure=`) | MD-103 / Priority 8 | No; the daily ops sweep already reports failed units (below). This makes it immediate |
| 8 | **Consolidated owner checklist, one line per action (2026-11-18)** | Task 4 | start here |

---

## 1. Protected PR-based merging, no routine administrator bypass (D18)

**Decision:** `main` is merged through protected pull requests. Required independent checks, exact-head release
validation, review requirements and production-deployment verification stay. There is no routine administrator
bypass.

**Payload:** `deploy/github/main-protection-ruleset.json`, applied by `deploy/github/apply-branch-protection.sh`.
It is pinned by `tests/deploy/test_main_protection_ruleset.py`. The rationale is in
`docs/audit/STABILIZATION_2026-10-07.md` §3.

### Validated 2026-11-18 (read-only; nothing applied)

- **Live state.** Ruleset 19976839 is `active` but carries only `deletion` + `non_fast_forward` (last updated 2026-07-29):
  no `pull_request` rule, no required checks, bypass `always` for `RepositoryRole 4`, `RepositoryRole 5` and the
  `DeployKey`. Today any of those can push straight to `main`.
- **Required-check names match what CI emits.** A merged PR's head commit (#2228, `1a867caa`) reported `Validate PR`
  and `Receipt check`, both from app 15368 (GitHub Actions), among 13 other jobs that must stay NON-required
  (shards, `Detect changed systems`, advisory jobs). No name is wrong, so the payload was not edited. The pin is
  `tests/deploy/test_ruleset_required_checks_pinned.py`: it fails CI if either job is renamed, made conditional
  (other than `always()`), duplicated by another workflow, or stops running on every PR.
- **Bypass actors in the payload:** `RepositoryRole 5` (admin) `pull_request`; `DeployKey` `always` (box timers);
  `Integration 15368` `always` (`refit-hill-curves`, `scheduled-refresh`, `verify-sharp-production`,
  `weekly-narratives` push with `GITHUB_TOKEN`). The Integration flow merges green PRs through the PR path, which
  the rules allow without any bypass.
- **One behavior change to confirm:** the payload drops the live `RepositoryRole 4` (write) `always` bypass. It only
  matters if a non-admin collaborator with the write role pushes directly (the collaborator list was unreadable to
  the agent; check it in §2).
- **Receipt check is required.** A PR whose body lacks a filled verification receipt cannot merge until the body is
  edited (editing re-runs the check in seconds). Drop it from the payload first if you do not want that.

### What to check before applying

| setting | expected value | why |
|---|---|---|
| ruleset `enforcement` | `active` | inert otherwise |
| target | `~DEFAULT_BRANCH` | `main` |
| rules | `deletion`, `non_fast_forward`, `pull_request` (0 approvals), `required_status_checks` = `Validate PR` + `Receipt check`, `strict: false` | 0 approvals because this is a solo repo; strict would chase the 2-hourly data refresh |
| admin role bypass | **`pull_request`**, not `always` | `always` would give every agent session, which pushes as the same account, direct-main authority. `pull_request` blocks direct pushes. |
| `DeployKey` bypass | `always` | the box timers (DLF, IDP Show, player context) push data commits with the write deploy key |
| `Integration 15368` (GitHub Actions) bypass | `always` | scheduled-refresh, refit, Sharp verification and narratives push with `GITHUB_TOKEN`; deploy dispatch keys on those commits (CLAUDE.md W31-F001) |

**Emergency path.** The admin can still merge a PR whose checks are red: `gh pr merge --admin`. Treat it as an
exception, not routine. Each use is written down (PR comment: why, which check, follow-up).

### Commands (admin-scoped token; run right after a box push at :27 / :32 past an even hour)

```bash
# 0. Rollback copy of the existing ruleset
gh api repos/jasonleetucker-code/riskittogetthebrisket/rulesets/19976839 > ruleset-19976839-backup.json
# 1. Dry run: reads the live ruleset (no token needed), prints the exact call it WOULD make and the
#    diff vs live (- live only, + payload only, ~ changed). Sends nothing.
bash deploy/github/apply-branch-protection.sh --dry-run
#    Expected today: WOULD CALL: PUT .../rulesets/19976839; + rule pull_request; + rule required_status_checks;
#    + bypass Integration id=15368 mode=always; admin always -> pull_request; - bypass RepositoryRole id=4.
# 2. Apply (updates ruleset 19976839 in place). Supply the token from your own shell; never paste it anywhere.
GH_TOKEN="$ADMIN_TOKEN" bash deploy/github/apply-branch-protection.sh
```

### Verify

```bash
# The applied ruleset matches the payload (bypass actors and rules)
gh api repos/jasonleetucker-code/riskittogetthebrisket/rulesets/19976839 \
  --jq '{enforcement, bypass: [.bypass_actors[] | {actor_type, bypass_mode}], rules: [.rules[].type]}'
# The next DLF / IDP Show push and the next github-actions[bot] push show "bypass"
gh api repos/jasonleetucker-code/riskittogetthebrisket/rulesets/rule-suites --jq '.[0:5]'
# A direct push from a normal session is refused (try on a throwaway commit only if you want proof)
```

Also confirm the next `scheduled-refresh.yml` run and the next two box timer pushes land on `main`. If any is
refused, roll back immediately.

### Rollback

```bash
gh api --method PUT repos/jasonleetucker-code/riskittogetthebrisket/rulesets/19976839 \
  --input ruleset-19976839-backup.json
```

---

## 2. Deploy-key inventory; retire unused write access only after confirming the deploy path (D18)

**Read first:** `docs/ops/ACCESS_INVENTORY_2026-11-18.md` (what the repository shows, what the agent could not read, and the excess-privilege findings). The deploy-key and collaborator endpoints returned 403 to the agent, so steps 1 to 4 below are the owner's to run.

**Decision:** inventory every write-capable deploy key. Retire unused write access **only after** independently
confirming that removal will not break the legitimate deployment path.

**What the deploy path uses (from the repo, 2026-10-18):**

- The box's checkout (`/home/dynasty/trade-calculator`) runs `git fetch origin` during every deploy
  (`deploy/deploy.sh`). Its `core.sshCommand` pins a key.
- The box timers push data commits to `main` over SSH as the app user. `deploy/playerctx_history_push.sh`
  records (measured 2026-08-15) that `~/.ssh/config` supplies `IdentityFile ~/.ssh/github_push` for
  `github.com`. The `-i ~/.ssh/github_deploy_key` the scripts pass was absent on the box at that time.
- GitHub Actions deploys over SSH to the box with `DEPLOY_SSH_PRIVATE_KEY`. That is an SSH key for the VPS, not a
  GitHub deploy key. Do not confuse the two.

**Retirement candidates named by the 2026-10-07 audit:** 145025388 "hetzner-riskit" (last used 2026-03-09) and
148579683 "dynasty-prod-deploy" (last used 2026-06-24). Neither may be removed until step 3 below proves it is
not the key the box uses today.

### Procedure

```bash
# 1. List the repository's deploy keys (id, title, read_only, created_at, last_used)
gh api repos/jasonleetucker-code/riskittogetthebrisket/keys \
  --jq '.[] | {id, title, read_only, created_at, last_used}'
# 2. On the box, as the app user: fingerprint every key that can reach GitHub
sudo -u dynasty bash -lc 'for k in ~/.ssh/*.pub; do ssh-keygen -lf "$k"; done; git -C /home/dynasty/trade-calculator config core.sshCommand; cat ~/.ssh/config'
# 3. Compare: fingerprint each GitHub key's public half (the "key" field of step 1) the same way
gh api repos/jasonleetucker-code/riskittogetthebrisket/keys/<id> --jq .key | ssh-keygen -lf -
# 4. Prove which identity the box authenticates as, non-mutatingly
sudo -u dynasty bash -lc 'ssh -T git@github.com; git -C /home/dynasty/trade-calculator ls-remote origin HEAD'
```

Record the inventory (key id, title, read/write, fingerprint, which box file or workflow uses it, last used)
in a dated note, with **public fingerprints only**.

**Retire a key only when every one of these is true:**

- its fingerprint matches no file the box's fetch or push uses;
- no workflow or other host is recorded as using it;
- its `last_used` is older than the most recent box push.

Prefer **making it read-only or deleting it** right after a successful box push, then watch the next 2-hourly
DLF / IDP Show push and the next deploy:

```bash
gh api --method DELETE repos/jasonleetucker-code/riskittogetthebrisket/keys/<id>
```

**Rollback:** re-add the public key with `gh api --method POST .../keys` (title, key, `read_only: false`). This
needs the public half, so save it from step 1 first. Deletion cannot be undone without it.

**Also check (unreadable to the agent):** `gh api repos/jasonleetucker-code/riskittogetthebrisket/collaborators --jq '.[]|{login,role_name}'` and Settings, Actions, General, Workflow permissions (should be read-only by default).

**Hardening, later (not decided):** move the four `GITHUB_TOKEN` pushers onto a dedicated deploy key and drop the
`Integration` bypass. That is a separate change with its own review.

---

## 3. Rotate `JASON_LOGIN_PASSWORD` (D18; checked against PR #2240, 2026-11-18)

**Why:** a literal value once sat in public history. `server.py` requires the value from the environment.

**Full procedure, 2026-11-19 (STAB-5):** `docs/ops/CREDENTIAL_INVENTORY_2026-11-19.md` section 5 wraps the steps below
with the replacement-access precondition, a no-reveal login test of the new AND the old value
(`scripts/check_login_status.py`, prints only an HTTP status) and the ordered rollback. The inventory also lists every
secret the workflows reference, with least-privilege findings.

**Which secrets this covers.** `JASON_LOGIN_PASSWORD` is the only login secret this runbook names. The other
box-side tokens (`SIGNAL_ALERT_CRON_TOKEN`, `INTEL_REFRESH_TOKEN`, `SHARP_SMOKE_TOKEN`) are bearer tokens; rotate them
the same way, plus the matching GitHub Actions secret, only if you believe they leaked.

**Interaction with PR #2240 (startup guard; open at the time of writing).** Once it merges and deploys:

- a placeholder or empty `JASON_LOGIN_PASSWORD` (for example `changeme`, case-insensitive) refuses startup unless
  `ALLOW_DEFAULT_LOGIN_DEV` is set, and `RISKIT_ENV=production` (set by the unit after `EnvironmentFile=`) refuses
  startup if `E2E_TEST_MODE` or `ALLOW_DEFAULT_LOGIN_DEV` is on;
- `deploy/deploy.sh` runs the same check against the box `.env` BEFORE touching the working tree and refuses the
  deploy (printing variable names only), so a bad value stops a deploy instead of a restart.

So choose a real value: at least 20 characters from `A-Z a-z 0-9 - _ .` (no spaces, quotes, `#`, `$` or backslash;
systemd parses `.env` as an `EnvironmentFile=`).

**Preconditions:** you are on the box as an admin; you can log in to the site today (so you can compare before and after).

```bash
# 1. Backup of the CURRENT file (it holds the old secret: you delete it in step 6).
sudo -u dynasty bash -lc 'cd /home/dynasty/trade-calculator && umask 077 && cp -p .env ".env.bak.$(date -u +%F)"'

# 2. Type the new value WITHOUT echo and without it entering shell history or process arguments.
#    `read -s` does not echo; the value reaches python through the environment only.
read -rs -p 'new JASON_LOGIN_PASSWORD: ' NEW_PW; echo
export NEW_PW

# 3. Replace only that line (adds it if missing); the value is never printed.
sudo --preserve-env=NEW_PW -u dynasty python3 -I - <<'PY'
import os, re
p = "/home/dynasty/trade-calculator/.env"
pw = os.environ["NEW_PW"]
assert len(pw) >= 20 and re.fullmatch(r"[A-Za-z0-9._-]+", pw), "use >=20 chars of A-Za-z0-9._-"
lines = open(p).read().splitlines()
out, hit = [], False
for ln in lines:
    if re.match(r"\s*(export\s+)?JASON_LOGIN_PASSWORD\s*=", ln):
        if not hit:
            out.append("JASON_LOGIN_PASSWORD=" + pw)
        hit = True
    else:
        out.append(ln)
if not hit:
    out.append("JASON_LOGIN_PASSWORD=" + pw)
open(p, "w").write("\n".join(out) + "\n")
print("JASON_LOGIN_PASSWORD line updated")
PY
unset NEW_PW

# 4. Check the file with the SAME rule the deploy and the server use (prints names only).
#    Needs PR #2240 deployed; skip this step before then.
sudo -u dynasty bash -lc 'cd /home/dynasty/trade-calculator && python3 -E -s src/api/startup_guards.py --check-env-file .env --production'

# 5. Restart.
sudo systemctl restart dynasty
```

**Verify without revealing it:**

- sign in at the site with the new password; confirm the old one is refused;
- `sudo journalctl -u dynasty -n 50 --no-pager` shows a clean start (no refusal naming `JASON_LOGIN_PASSWORD`);
- sign out and back in once; other signed-in sessions behave as expected;
- the next deploy's box `.env` guard step passes (the independent proof the file is not a placeholder).

```bash
# 6. Only after you have signed in successfully: delete the backup (it contains the OLD secret).
sudo -u dynasty bash -lc 'shred -u /home/dynasty/trade-calculator/.env.bak.* 2>/dev/null || rm -f /home/dynasty/trade-calculator/.env.bak.*'
```

**Record:** the rotation DATE only (for example "rotated 2026-11-19"), in the security record (completion row
`C10-CLOSE-06/credential-rotation`). Never the value, never a hash.

**Rollback (new password does not work):** restore the backup before step 6 and restart:
`sudo -u dynasty bash -lc 'cd /home/dynasty/trade-calculator && cp -p .env.bak.<date> .env' && sudo systemctl restart dynasty`.
If you already ran step 6, set a new value by repeating steps 2, 3 and 5; there is no path back to the old one by design.

---

## 4. Tesseract OCR install and post-install verification (D19)

**Status 2026-10-18:** the owner reports Tesseract 5.3.4 installed on the VPS and the backend active. The install steps below stay for rebuilds; the post-install checks still apply.

**Decision:** free local Tesseract stays the engine. There is no paid vision service and no new credential. A
guessed player identity is never imported automatically. Details: `docs/ops/SCREENSHOT_IMPORT_RUNBOOK.md`.

```bash
sudo apt-get update && sudo apt-get install -y tesseract-ocr
tesseract --version          # expect 5.x
tesseract --list-langs       # must include eng
sudo systemctl restart dynasty
```

**Verify:**

1. Signed in: `GET /api/trade/import-screenshot/status` returns
   `{"available": true, "engine": "tesseract", "version": "5.…", "enabled": true}`, and no longer
   `reason: "tesseract_not_installed"`.
2. The backend start log no longer carries the "tesseract not installed" warning:
   `sudo journalctl -u dynasty -n 200 | grep -i tesseract`.
3. On the box: `pytest -m tesseract tests/trade/screenshot_import`. These real-binary tests are skipped where
   the binary is absent.
4. **Recognition on real, permitted screenshots.** Use your own screenshots. Do not commit them if they show
   other managers' private data. Cover each of these cases:
   - a dark-mode screenshot;
   - an offense-only trade;
   - a trade with IDP players;
   - draft picks;
   - an ambiguous name, such as two players with one surname.

   Pass means:
   - clearly recognised assets land on the correct side;
   - an ambiguous name asks for confirmation and is never auto-picked;
   - anything unrecognised is listed, never silently dropped;
   - the values shown are ours, never the screenshot's.

   Record the per-case outcome and make no universal accuracy claim.

**Rollback:** `RISKIT_FEATURE_TRADE_SCREENSHOT_IMPORT=0` in the service environment, then
`sudo systemctl restart dynasty`.

---

## 5. Off-host encrypted backup for the official rookie auction (D20)

**For mocks:** the existing hourly on-host backup with restore verification (`dynasty-auction-backup` timer,
`scripts/auction_backup_verify.py`) is sufficient.

**For the official auction (recommendation):** before launch, have a **validated, encrypted, off-host recovery
copy**, or a separately documented risk acceptance. On-host copies bound a process or database fault to about
1 hour, but do not survive losing the disk.

**Measured 2026-11-18:** all 14 retained generations live on the production disk; there is no off-box copy yet.

**Destination comparison and recommendation (2026-11-19, STAB-4):** `docs/ops/BACKUP_OFFBOX_DESIGN_2026-11-19.md`
compares B2, R2, S3, a second host and the box's own vendor, recommends Backblaze B2 behind `rclone crypt` with a
no-delete key and Object Lock, and specifies the isolated drill and the stale-copy alert. It is a recommendation; no
provider is chosen until you approve it.

Two opt-in paths exist, both disabled until you configure them. This repository picks no provider.

**Path A (2026-11-18, recommended): `scripts/offbox_backup.py`, provider-independent, hash-verified.** It restore-verifies the newest generation locally, copies it to a target you choose (`dir:/mount/path`, `rsync:user@host:path`, or `rclone:remote:path`), then re-reads every file from the target and requires the SHA-256 to match. It never deletes anything on the target and refuses a target you have not declared encrypted. `scripts/offbox_backup.py drill` restores the newest copy into a fresh temp directory (never a production path), checks the manifest hashes and runs the same restore verification. Procedure at the end of this section.

**Path B (existing): the rsync mirror,** which uses `--delete` and therefore replicates local history; it reuses the existing opt-in:

1. Choose storage you control: a free tier, another host you own, or a personal disk reachable over SSH.
2. Encrypt before it leaves the box. The mirror also carries session secrets (`deploy/backup/README.md`), so use
   an encrypted target such as `restic`/`borg` with a passphrase you keep offline, or a gpg-encrypted archive.
   Never rsync plaintext to a third party.
3. Enable the existing mirror:

   ```bash
   sudo systemctl edit riskit-state-backup.service
   #   [Service]
   #   Environment="OFFBOX_RSYNC_DEST=<you@your-host>:riskit-state/"
   ```

   Also include `data/auction/` copies in what leaves the box.
4. **Validate:** restore the newest off-host copy onto a scratch directory and run
   `python scripts/auction_backup_verify.py` against it, which replays every room and checks invariants. Record
   the date and the result.
5. Record the choice, or the documented risk acceptance, in `docs/auction/LAUNCH_CHECKLIST.md` (item B,
   disaster-recovery window).

This is a pre-launch item. It does not block development or mocks, and per D20 it is not raised again before the
official launch is being prepared.

---

### Path A procedure (owner; the agent configured and contacted nothing)

```bash
# 0. Choose a target you control that is encrypted at rest (an rclone `crypt` remote, a restic/borg-backed mount,
#    an encrypted disk). The generation holds session cookies and login state.
# 1. Install the ROOT-OWNED copies (never run the checkout copy as root; same rule as riskit-state-backup):
sudo install -o root -g root -m 0755 -D scripts/offbox_backup.py /usr/local/lib/riskit/offbox_backup.py
sudo install -o root -g root -m 0755 -D scripts/verify_state_backup_restore.py /usr/local/lib/riskit/verify_state_backup_restore.py
# 2. Root-only config (edit the file; never paste a credential into a terminal or chat):
sudo install -d -m 0700 /etc/riskit && sudo install -m 0600 /dev/null /etc/riskit/offbox.env
sudo "${EDITOR:-nano}" /etc/riskit/offbox.env
#      OFFBOX_BACKUP_TARGET=rclone:myremote:riskit-state      # or dir:/mnt/x  or  rsync:user@host:riskit-state
#      OFFBOX_BACKUP_ACK_ENCRYPTED_TARGET=1                   # your statement that the target is encrypted
# 3. First manual copy (expect exit 0 and "ok=True ... files=N"):
sudo bash -c 'set -a; . /etc/riskit/offbox.env; set +a; /usr/bin/python3 /usr/local/lib/riskit/offbox_backup.py copy --json'
# 4. Restore drill into a temp dir (expect exit 0, "ok": true, restore_verified > 0):
sudo bash -c 'set -a; . /etc/riskit/offbox.env; set +a; /usr/bin/python3 /usr/local/lib/riskit/offbox_backup.py drill --json --scratch-parent /var/tmp'
# 5. Optional nightly: the templates are NOT installed by any deploy (they end in .example):
sudo cp deploy/backup/offbox/riskit-offbox-copy.service.example /etc/systemd/system/riskit-offbox-copy.service
sudo cp deploy/backup/offbox/riskit-offbox-copy.timer.example   /etc/systemd/system/riskit-offbox-copy.timer
sudo systemctl daemon-reload && sudo systemctl enable --now riskit-offbox-copy.timer
```

**Exit codes:** 0 ok or disabled (no target set), 1 failure (source failed local verification, copy did not verify,
tampered or incomplete restore, protected scratch path), 2 no generation / nothing on the target. **Disk:** the
read-back downloads the generation once into a temp directory, so allow roughly one generation of free space
under `/tmp`.

**Verify:** the drill passing is the evidence. Record the date and result (no values) in
`docs/auction/LAUNCH_CHECKLIST.md` item B. Re-run the drill monthly, and after any change of target.

**Rollback:** `sudo systemctl disable --now riskit-offbox-copy.timer`, delete the two unit files and
`/etc/riskit/offbox.env`, `sudo systemctl daemon-reload`. Nothing else changes: the local backup is untouched.
Retention on the target is yours (the tool never prunes); keep at least 7 generations.

---

## 6. Re-enable authenticated production verification

Follow `docs/ops/AUTH_VERIFICATION_REENABLE.md` exactly. It covers:

- the four preconditions;
- what #1725 allowlists;
- the census and revoke steps;
- the order: `prod-e2e-smoke.yml` first, then `v1-authenticated-verification.yml`;
- how to stop again.

The release-train-4 preconditions are met: #1759 merged 2026-10-16, and its deploy was verified.

```bash
# Read the current state first (expect disabled_manually for both)
gh api repos/jasonleetucker-code/riskittogetthebrisket/actions/workflows \
  --jq '.workflows[] | select(.path | test("v1-authenticated-verification|prod-e2e-smoke")) | {path, state}'
```

Enabling a workflow is a repository action reserved for the owner. Agents only read the state.

---

## 7. Immediate failure notice for the `dynasty-*` timers (`OnFailure=`) (MD-103)

**Status:** not applied. It is a production infrastructure change, so it is written up here and kept out of the
engineering PR (owner directive 2026-11-08, Priorities 8 and 18: root-level infrastructure is owner-reserved).

### Why this is not a repository change

None of the 38 `dynasty-*` timers has `OnFailure=` (40 shipped `*.service.template` files, none carries it). The
natural fix, adding `OnFailure=` to the service templates, would reach production **by itself** on the next deploy:

- `deploy/deploy.sh::ensure_systemd_service` runs `deploy/install-systemd-service.sh` on every deploy whenever any
  `*.timer.template` ships (it always does), without `FORCE_SERVICE_INSTALL`, so no service is restarted by that step;
- the installer (`reconcile_timer_units`) renders each service and timer template, compares it with the installed
  unit, **rewrites it on any content difference** and runs `daemon-reload`.

So an edit to a service template is a live change to 38 production units the moment it merges. A new notifier
template would not install at all, because the installer only pairs `dynasty-<stem>.service.template` with
`dynasty-<stem>.timer.template`; a template that references a unit nobody installed would be worse than nothing.

### What the repository already does without any operator action

After the next deploy the daily ops-alert sweep (`dynasty-signal-alerts.timer`, 15:00 UTC, the existing SMTP path with
a per-category 4 h cooldown and a recovery notice) reads `systemctl list-units --failed` (an unprivileged read) and
emails one alert per shipped `dynasty-*` / `riskit-*` service whose **latest run failed** (`src/api/systemd_failures.py`,
`src/api/ops_alerts.py::_check_failed_units`). It also alerts on an irreplaceable store missing from the newest backup
generation and on a failed post-deploy restore proof (`src/api/backup_health.py::alert_rows`). Worst-case latency is
one sweep interval (up to 24 h). If `systemctl` cannot be asked from the backend's sandbox the check reads *not
checked*, never *no failures*; confirm it can:

```bash
sudo -u dynasty systemctl list-units --failed --type=service --plain --no-legend --no-pager
# Expect: exit 0 (an empty list is fine). A "Failed to connect to bus" error means the check cannot see failures here.
```

The sweep needs `ALERT_TO` / SMTP configured (`.env.example`) and `SIGNAL_ALERT_CRON_TOKEN`; without them it sends
nothing and says so (`opsAlerts.deliveryConfigured: false` in the sweep result).

### Optional: make it immediate (one prefix drop-in, no template edits)

This reuses the existing alert path by starting the existing sweep right after a unit fails. It touches no repository
template, so the deploy installer cannot overwrite it, and it is one file rather than 38.

**Read first.** Starting `dynasty-signal-alerts.service` runs the whole sweep (per-user signal digests plus the ops
checks), not only the ops checks. Confirm the user digests are idempotent within a day (they record a per-signal
`notifiedAt`; read the `POST /api/signal-alerts/run` handler in `server.py`) before you accept extra sweeps. If you would rather not run
them more than once a day, skip this section: the daily sweep above already reports every failed unit.

```bash
# 1. The notifier. Root, a FIXED command, and a name that does NOT start with "dynasty-", so the drop-in below
#    cannot attach OnFailure= to the notifier itself (a notifier that fails must not trigger itself).
sudo tee /etc/systemd/system/riskit-failure-notify.service >/dev/null <<'EOF'
[Unit]
Description=Start the ops-alert sweep after a dynasty-* unit failed

[Service]
Type=oneshot
ExecStart=/usr/bin/systemctl start --no-block dynasty-signal-alerts.service
EOF

# 2. One prefix drop-in: applies to every dynasty-*.service (not to dynasty.service, which has no dash; the backend is
#    covered by dynasty-healthcheck.timer).
sudo install -d -m 0755 /etc/systemd/system/dynasty-.service.d
sudo tee /etc/systemd/system/dynasty-.service.d/10-onfailure.conf >/dev/null <<'EOF'
[Unit]
OnFailure=riskit-failure-notify.service
EOF

sudo systemctl daemon-reload
```

### Verify

```bash
systemctl show dynasty-ktc-trades.service -p OnFailure                  # expect riskit-failure-notify.service
systemctl show riskit-failure-notify.service -p OnFailure               # expect empty (no self-trigger)
# Harmless end-to-end probe: a transient unit that fails on purpose, under the dynasty- prefix.
sudo systemd-run --unit=dynasty-zz-onfailure-probe --wait /bin/false || true
journalctl -u riskit-failure-notify.service -n 5 --no-pager             # expect one start
sudo systemctl reset-failed dynasty-zz-onfailure-probe.service
```

The ops alert is rate-limited, so one probe may be the only email in 4 h.

### Rollback

```bash
sudo rm -f /etc/systemd/system/dynasty-.service.d/10-onfailure.conf /etc/systemd/system/riskit-failure-notify.service
sudo rmdir /etc/systemd/system/dynasty-.service.d 2>/dev/null || true
sudo systemctl daemon-reload
```

---

## 8. Consolidated owner checklist (2026-11-18, one line per action)

Order matters only where stated. Every item is the owner's to run; no agent executes any of them.

| # | action | command / where | precondition | verify | rollback |
|---|---|---|---|---|---|
| 1 | Back up the live ruleset | `gh api repos/jasonleetucker-code/riskittogetthebrisket/rulesets/19976839 > ruleset-19976839-backup.json` | admin `gh` login | file is non-empty JSON | n/a |
| 2 | Review the diff | `bash deploy/github/apply-branch-protection.sh --dry-run` | none (read-only) | shows PUT 19976839 and `+ rule required_status_checks` | n/a |
| 3 | Confirm the write-role bypass drop | `gh api repos/jasonleetucker-code/riskittogetthebrisket/collaborators --jq '.[] \| {login, role_name}'` | admin | nobody but you needs direct push | edit the JSON to keep role 4, re-run step 2 |
| 4 | Apply protection (§1) | `GH_TOKEN="$ADMIN_TOKEN" bash deploy/github/apply-branch-protection.sh` | right after a box push (:27/:32 past an even hour) | `gh api .../rulesets/19976839 --jq '{enforcement, rules: [.rules[].type]}'` shows `pull_request` + `required_status_checks`; next `scheduled-refresh` and box pushes still land | `gh api --method PUT .../rulesets/19976839 --input ruleset-19976839-backup.json` |
| 5 | Inventory deploy keys and fingerprints (§2) | steps 1 to 4 of §2 | box access | every GitHub key matched to a box file or workflow | none (read-only) |
| 6 | Retire an unused write key (§2), only if step 5 proves it unused | `gh api --method DELETE .../keys/<id>` | step 5 done, public half saved | next DLF/IDP Show push and next deploy succeed | re-POST the saved public key |
| 7 | Check repo default workflow token | Settings, Actions, General, Workflow permissions | admin | "Read repository contents" is selected | set it back |
| 8 | Rotate `JASON_LOGIN_PASSWORD` (§3) | steps 1 to 6 of §3 | can log in today; PR #2240 deployed for step 4 | new password works, old refused, clean `journalctl` | restore `.env.bak.<date>` before step 6 |
| 9 | Record the rotation DATE only | security record row `C10-CLOSE-06/credential-rotation` | step 8 verified | date present, no value | n/a |
| 10 | Choose an encrypted off-box target (§5 step 0) | your call; no provider is chosen in the repo | storage you control | n/a | n/a |
| 11 | Install the off-box tool and config (§5 Path A steps 1 to 2) | `install ... offbox_backup.py`, `/etc/riskit/offbox.env` | step 10 | files root-owned, env file `0600` | delete them |
| 12 | First off-box copy | §5 Path A step 3 | step 11 | exit 0, `ok=True` | delete the copy on the target |
| 13 | Restore drill | §5 Path A step 4 | step 12 | exit 0, `restore_verified > 0`; record date in `docs/auction/LAUNCH_CHECKLIST.md` item B | n/a (temp dir deleted) |
| 14 | Enable the nightly off-box timer (optional) | §5 Path A step 5 | step 13 green | `systemctl list-timers riskit-offbox-copy.timer`; next-morning log in `/var/log/riskit-offbox-backup.log` | `systemctl disable --now riskit-offbox-copy.timer` |
| 15 | Re-run the drill monthly | §5 Path A step 4 | step 14 | exit 0 | n/a |
