# Administrator-only actions runbook

**Status:** operator checklist (owner directive 2026-10-18, D18 / D19 / D20). Nothing in this file has been
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
| 4 | Install Tesseract on the VPS, then verify recognition | D19 | Yes: screenshot import (C3-IMPORT-IMAGE) reports unavailable until then |
| 5 | Off-host encrypted backup for the official rookie auction | D20 | Not for mocks; required (or a documented risk acceptance) before the official auction |
| 6 | Re-enable authenticated production verification | Part 9 item 9 | Yes for proof: many rows stay DEPLOYED_NOT_PRODUCTION_VERIFIED until it runs |

---

## 1. Protected PR-based merging, no routine administrator bypass (D18)

**Decision:** `main` is merged through protected pull requests. Required independent checks, exact-head release
validation, review requirements and production-deployment verification stay. There is no routine administrator
bypass.

**Payload:** `deploy/github/main-protection-ruleset.json`, applied by `deploy/github/apply-branch-protection.sh`.
It is pinned by `tests/deploy/test_main_protection_ruleset.py`. The rationale is in
`docs/audit/STABILIZATION_2026-10-07.md` §3.

### What to check before applying

| setting | expected value | why |
|---|---|---|
| ruleset `enforcement` | `active` | inert otherwise |
| target | `~DEFAULT_BRANCH` | `main` |
| rules | `deletion`, `non_fast_forward`, `pull_request` (0 approvals), `required_status_checks` = `Validate PR`, `strict: false` | 0 approvals because this is a solo repo; strict would chase the 2-hourly data refresh |
| admin role bypass | **`pull_request`**, not `always` | `always` would give every agent session, which pushes as the same account, direct-main authority. `pull_request` blocks direct pushes. |
| `DeployKey` bypass | `always` | the box timers (DLF, IDP Show, player context) push data commits with the write deploy key |
| `Integration 15368` (GitHub Actions) bypass | `always` | scheduled-refresh, refit, Sharp verification and narratives push with `GITHUB_TOKEN`; deploy dispatch keys on those commits (CLAUDE.md W31-F001) |

**Emergency path.** The admin can still merge a PR whose checks are red: `gh pr merge --admin`. Treat it as an
exception, not routine. Each use is written down (PR comment: why, which check, follow-up).

### Commands (admin-scoped token; run right after a box push at :27 / :32 past an even hour)

```bash
# 0. Rollback copy of the existing ruleset
gh api repos/jasonleetucker-code/riskittogetthebrisket/rulesets/19976839 > ruleset-19976839-backup.json
# 1. Dry run: validates the payload locally, sends nothing
bash deploy/github/apply-branch-protection.sh --dry-run
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

**Hardening, later (not decided):** move the four `GITHUB_TOKEN` pushers onto a dedicated deploy key and drop the
`Integration` bypass. That is a separate change with its own review.

---

## 3. Rotate `JASON_LOGIN_PASSWORD` (D18)

**Why:** a literal value once sat in public git history. `server.py` now requires the value from the environment
and fails fast without it.

```bash
# On the box. Edit the value in your editor; never echo it, never paste it into a terminal log or chat.
sudo -u dynasty bash -lc 'cp /home/dynasty/trade-calculator/.env /home/dynasty/trade-calculator/.env.bak.$(date -u +%F)'
sudo -u dynasty ${EDITOR:-nano} /home/dynasty/trade-calculator/.env    # set JASON_LOGIN_PASSWORD to a new long random value
sudo systemctl restart dynasty
```

**Verify without revealing it:**

- sign in at the site with the new password, and confirm the old one is refused;
- `sudo journalctl -u dynasty -n 50` shows a clean start, with no startup refusal about a missing password;
- existing signed-in sessions behave as expected (sign out and back in once).

**Record:** only the rotation date, in the security record (the completion row
`C10-CLOSE-06/credential-rotation`). Never the value. Remove the `.env.bak.*` copy once you have signed in
successfully, because it contains the old secret.

---

## 4. Tesseract OCR install and post-install verification (D19)

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

The recommended path reuses the existing opt-in mirror (no new service, no paid storage required):

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
