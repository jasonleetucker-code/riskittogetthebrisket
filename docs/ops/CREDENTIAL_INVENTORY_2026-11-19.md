# Credential and deploy-key inventory, least-privilege review, and login-password rotation (STAB-5)

Date: 2026-11-19. Owner directive intake STAB-5. **Names only: no secret value was read and none appears here. Nothing
was rotated, revoked, created or changed.** Extends `docs/ops/ACCESS_INVENTORY_2026-11-18.md` (which this file does not
replace; read it for the ruleset payload diff and the box-side key identities) with counts, per-secret findings, a
least-privilege recommendation for each, and a complete rotation procedure for `JASON_LOGIN_PASSWORD`.

## 1. What could and could not be read today

| Source | Result | Consequence |
|---|---|---|
| `GET /repos/<repo>/rulesets` and `/rulesets/19976839` | readable | bypass actors and rules in section 5 |
| `GET /repos/<repo>` | readable | public, `allow_forking: true`, ~883 MB |
| `GET /repos/<repo>/actions/secrets` | **not permitted through this proxy** | secret **names present in GitHub are not verified**; section 2 lists names the workflows REFERENCE |
| `GET /repos/<repo>/actions/variables` | not permitted | variable names present not verified (section 2 lists those referenced) |
| `GET /repos/<repo>/environments` (the `production` environment's secrets and protection rules) | not permitted | **whether the `DEPLOY_*` values are repository or environment secrets, and whether `production` requires a reviewer, is unknown** |
| `GET /repos/<repo>/keys` (deploy keys) | not permitted | deploy-key ids, titles and `read_only` flags **not verified today** |
| `GET /repos/<repo>/collaborators`, `/hooks`, `/actions/permissions[/workflow]` | not permitted | collaborator roles, webhooks and the repository's default `GITHUB_TOKEN` permission **not verified** |
| `GET /repos/<repo>/branches/main/protection` | 403 (integration token) | legacy branch protection not verified; the ruleset is the live control |
| `.github/workflows/*.yml` | readable | every `secrets.` / `vars.` reference, counted below |

## 2. Secrets and variables the workflows reference (counted from 54 workflow files)

Fourteen distinct non-automatic secret names are referenced, plus the automatic `GITHUB_TOKEN`; fourteen distinct
variable names. All 14 secrets are used only at **step** level (`env:` or `with:` of one step), none at job or workflow
level, and no workflow uses `secrets: inherit`. No workflow triggers on `pull_request_target`; the 27 SSH-key workflows
trigger only on `push` to `main`, `workflow_dispatch`, `workflow_run` or `schedule`, never on `pull_request`.

| Secret | Workflows (count) | What it unlocks | Finding |
|---|---|---|---|
| `DEPLOY_SSH_PRIVATE_KEY`, `DEPLOY_HOST`, `DEPLOY_USER`, `DEPLOY_PORT`, `DEPLOY_KNOWN_HOSTS` | 27, all with `environment: production` | login to the production VPS as `DEPLOY_USER` (sudo-capable by design) | **F1** one key for 27 workflows |
| `DLF_USERNAME`, `DLF_PASSWORD` | `scheduled-refresh.yml` (1) | Dynasty League Football paid account | **F2** passed to a step that does not use them |
| `IDPSHOW_SESSION_JSON` | `scheduled-refresh.yml` (1) | replayable logged-in session of a paid account | **F3** optional; the box timer is the producer |
| `DRAFTSHARKS_EMAIL`, `DRAFTSHARKS_PASSWORD` | `scheduled-refresh.yml`, `draftsharks-diagnostic.yml` (2) | Draft Sharks paid account | **F4** required today; retires with STAB-7 stage 5 |
| `ANTHROPIC_API_KEY` | `weekly-narratives.yml` (1) | paid API spend | **F5** only the optional `generate` mode needs it |
| `CLAUDE_CODE_OAUTH_TOKEN` | `claude.yml` (1) | Claude Code action acting as the repository | **F6** write scopes on a public-repository comment trigger |
| `INTEL_REFRESH_TOKEN` | `intel-refresh.yml` (1) | bearer for one backend refresh route | narrow; keep |
| `SHARP_SMOKE_TOKEN` | `verify-sharp-production.yml` (1) | bearer for a read-only Sharp smoke route | narrow; keep |
| `GITHUB_TOKEN` (automatic) | 6 workflows name it explicitly; `contents: write` declared in 6 files | per-run repository token | **F7**, **F8** |

Variables referenced (non-secret configuration): `PROD_APP_DIR` (35 uses), `PROD_PUBLIC_URL` (20), `PROD_SERVICE_NAME`
(12), `PROD_PYTHON_BIN` (8), `PROD_VENV_DIR` (6), `PROD_DEPLOY_STATE_DIR` (4), `PROD_LAST_SUCCESSFUL_DEPLOY_COMMIT_FILE`
(3), and one use each of `PROD_APP_HOST`, `PROD_APP_NAME`, `PROD_APP_PORT`, `PROD_APP_USER`, `PROD_AUTO_ROLLBACK`,
`PROD_DEPLOY_BRANCH`, `PROD_STRICT_LOCAL_HEALTH`. None is secret; `PROD_APP_HOST` and `PROD_APP_USER` do reveal where the
box is if a workflow logs them (they are workflow inputs, not a finding).

**Not determinable from the repository: secrets that exist in GitHub but that no workflow references** (the secret list
is unreadable). The owner's one-command check, printing only names that match nothing:

```bash
# Run on the owner's machine with an admin gh login. Prints names only, never values.
gh secret list --repo jasonleetucker-code/riskittogetthebrisket --json name -q '.[].name' | sort > /tmp/gh_secret_names
grep -rhoE 'secrets\.[A-Z_][A-Z0-9_]*' .github/workflows | sed 's/secrets\.//' | sort -u > /tmp/wf_secret_names
comm -23 /tmp/gh_secret_names /tmp/wf_secret_names     # in GitHub, referenced by no workflow: delete candidates
comm -13 /tmp/gh_secret_names /tmp/wf_secret_names     # referenced, not set: a workflow that cannot work
rm -f /tmp/gh_secret_names /tmp/wf_secret_names
```

Repeat with `gh secret list --env production` for the environment secrets, and `gh variable list` for variables.

## 3. Findings

**F1. One production-shell key serves 27 workflows.** 26 of them are diagnostics, proofs or verifiers
(`dlf-diagnostics`, `signals-health-probe`, `retention-health`, ...); only `deploy.yml` needs to change the box. A leaked
key or a bad edit to any of the 27 has full shell reach as a sudo-capable user. Recommendation: a second key, restricted
by `command=` forced-command or limited sudoers to the read-only probes, for the 26; the full key stays for `deploy.yml`
only. It needs box changes (owner-reserved infrastructure), so it is a recommendation, not done.

**F2. `DLF_USERNAME` / `DLF_PASSWORD` reach a CI step that does not use them.** `scheduled-refresh.yml` exports them to
the "Run scraper" step, but its own comment (lines ~389 to 403) says DLF is **not fetched in CI** (Cloudflare 403s the
GitHub runner range) and the production timer (`deploy/dlf_fetch_and_push.sh`) does it from the box `.env`. The only
reader of those variables in the repository is `scripts/fetch_dlf.py`, which the workflow does not invoke. Recommendation:
delete both GitHub secrets and the two `env:` lines in a reviewed PR. Verify first with
`grep -rn "DLF_USERNAME\|DLF_PASSWORD" "Dynasty Scraper.py" scripts` and the box timer's last success. Reduces the
paid-account password's exposure surface by one system.

**F3. `IDPSHOW_SESSION_JSON` is optional and duplicated.** The step skips when it is empty and says "the prod timer
remains its producer". A session cookie is a replayable login. Recommendation: delete the GitHub secret unless a CI
IDP Show fetch is wanted; the box already holds the session (`/var/lib/idpshow-fetch/idpshow_session.json`).

**F4. `DRAFTSHARKS_*` are genuinely used** by the CI scrape. Keep, but note STAB-7 stage 5 moves vendor scraping off the
public pipeline; retire the secrets then. `draftsharks-diagnostic.yml` is a second consumer; decide whether it is still
needed.

**F5. `ANTHROPIC_API_KEY` is only needed by the optional `generate` mode** of `weekly-narratives.yml`; the two scheduled
fires run `--action export` with zero API calls (the workflow says so in its header). A spend-capable key sitting in
Actions for an unused mode. Recommendation: delete it; if `generate` is wanted later, create a dedicated key with a
provider-side monthly spend cap.

**F6. `claude.yml` grants `contents: write`, `pull-requests: write`, `issues: write`, `id-token: write` on triggers anyone
can start by commenting `@claude`** on a public repository. The action's own default is to require a write-access actor;
that default was not verified here and the workflow sets no `allowed_non_write_users`. Recommendation: drop
`contents: write` (and `id-token: write` unless the action needs OIDC) unless the owner wants Claude to push from that
path; keep the actor check at its default.

**F7. `deploy.yml` has no top-level `permissions:` and its `validate` and `deploy` jobs set none.** They inherit the
repository default, which was unreadable. If that default is "read and write", both jobs hold a write token.
Recommendation: read the default (`gh api repos/<repo>/actions/permissions/workflow`), set it to read-only, and add
explicit `permissions:` to those two jobs. Editing `deploy.yml` is a strict-L3 change, so it needs its own PR.

**F8. Six workflows can push or write with `GITHUB_TOKEN`** (`contents: write`): `claude.yml`, `class-b-model-branch.yml`,
`refit-hill-curves.yml`, `scheduled-refresh.yml`, `verify-sharp-production.yml`, `weekly-narratives.yml`. Four of them push
to `main` and are covered by the `Integration 15368` bypass in the prepared ruleset. Keep it at those four; the repository
test `tests/deploy/test_main_protection_ruleset.py` fails when a new direct-to-main pusher appears.

**F9. The live `main` ruleset protects almost nothing.** Rule set: `deletion` and `non_fast_forward` only. No
`pull_request` rule, no required checks. Bypass actors, all `always`: `DeployKey`, `RepositoryRole 4`, `RepositoryRole 5`
(5 is admin; 4 is the write role, per the 2026-11-18 inventory). **`DeployKey always` means every deploy key on the
repository, whatever its title, can push straight to `main`.** The prepared payload
(`deploy/github/main-protection-ruleset.json`, applied by `deploy/github/apply-branch-protection.sh`) is an owner action
that is **not authorized for an agent to apply** (execution plan, 2026-11-18); see runbook section 1.

**F10. Deploy keys: unverified.** The 2026-10-07 audit named two GitHub deploy keys as retirement candidates: 145025388
"hetzner-riskit" (last used 2026-03-09) and 148579683 "dynasty-prod-deploy" (last used 2026-06-24). That is second-hand,
four to eight weeks old, and their `read_only` flags are unknown. Given F9, **a write-capable deploy key is also a
branch-protection bypass**, so each unused key is more than clutter. Follow runbook section 2 to fingerprint and compare
before retiring anything.

## 4. Least-privilege recommendations (none applied)

| # | Action | Owner-only? | Rollback |
|---|---|---|---|
| 1 | Run the section 2 comparison; delete secrets no workflow references | yes (settings) | re-add the secret from the source of truth |
| 2 | Delete `DLF_USERNAME` / `DLF_PASSWORD` and `IDPSHOW_SESSION_JSON` from GitHub (F2, F3), then a PR removing their `env:` lines | secret deletion yes; PR no | re-add the secret |
| 3 | Delete `ANTHROPIC_API_KEY` or replace with a capped dedicated key (F5) | yes | re-add |
| 4 | Set the repository default `GITHUB_TOKEN` to read-only; add `permissions:` to `deploy.yml`'s `validate` and `deploy` (F7) | setting yes; PR no (strict L3, own PR) | revert |
| 5 | Narrow `claude.yml` permissions (F6) | no (reviewed PR) | revert |
| 6 | Add required reviewers to the `production` environment if absent (it gates 27 workflows that hold the box key); read its protection first | yes | remove the rule |
| 7 | Split the diagnostics key from the deploy key (F1) | yes (box change) | keep both keys until the new one is proven |
| 8 | Fingerprint deploy keys, make fetch-only keys `read_only: true`, retire unused ones (F10, runbook section 2) | yes | re-add the public key |
| 9 | Apply the prepared `main` ruleset (F9, runbook section 1) | yes | the script saves a rollback copy of the existing ruleset first; runbook section 1 "Rollback" |
| 10 | STAB-7 stage 5 retires `DRAFTSHARKS_*` from Actions (F4) | yes | re-add |

Order matters for 7 to 9: **confirm replacement access before revoking anything.** Never delete a deploy key or a ruleset
bypass while it is the only path the box timers or deploys use (runbook section 2 steps 2 to 4 prove which).

## 5. Rotating `JASON_LOGIN_PASSWORD` safely

`JASON_LOGIN_PASSWORD` is **not** a GitHub secret (no workflow references it; `deploy.yml` and `pr-validation.yml` only set a
CI-local value so `server.py` can import). It lives in the box `.env`, in the owner's password manager and possibly a
browser. So the rotation touches only the box and the owner's records. The box edit, backup, startup-guard check and
restart are runbook section 3 (unchanged); this section adds the parts it lacked: generation, the **no-reveal login test**
(`scripts/check_login_status.py`, which prints only an HTTP status), the old-value refusal check and the ordered rollback.

**Why rotate:** a literal value once sat in public history (runbook section 3). A rotation closes that; it does not need
anything else rotated. Bearer tokens (`SIGNAL_ALERT_CRON_TOKEN`, `INTEL_REFRESH_TOKEN`, `SHARP_SMOKE_TOKEN`) rotate only if
believed leaked.

**Precondition: replacement access confirmed first.** Before changing anything, have all of:

1. a second terminal already logged in to the box as an admin, with `sudo -n true` succeeding, kept open to the end;
2. the box `.env` backup made in step 2 below;
3. confirmation that the OLD password logs in today (step 1), so a later failure is attributable;
4. a password manager entry ready to receive the new value.

Steps (owner's machine unless stated; `SITE` is the site origin, `OWNER` is the login username):

```bash
# 0. Generate the new value in your password manager: 28 random characters from A-Z a-z 0-9 . _ -  (the runbook's
#    allowed set; no spaces, quotes, #, $ or backslash). Do NOT type it into a chat, ticket, PR or shell history.

# 1. Baseline: the old password works today. The script prompts with no echo and prints only a status.
python3 scripts/check_login_status.py --url "$SITE" --username "$OWNER" --expect ok --label old-before
#    expect:  login HTTP 200 (old-before)      exit 0

# 2. On the box (second terminal stays open): back up .env, set the new value, check, restart.
#    This is runbook section 3 steps 1 to 5 exactly; paste the new value at its hidden `read -rs` prompt.

# 3. New value works (hidden prompt again; paste the new value):
python3 scripts/check_login_status.py --url "$SITE" --username "$OWNER" --expect ok --label new
#    expect:  login HTTP 200 (new)             exit 0

# 4. Old value is refused (hidden prompt; paste the OLD value from your password manager history):
python3 scripts/check_login_status.py --url "$SITE" --username "$OWNER" --expect refused --label old-after
#    expect:  login HTTP 401 (old-after)       exit 0
```

Reading the results:

- `new` 200 and `old-after` 401: success. Continue to the cleanup in runbook section 3 step 6 (it shreds the `.env`
  backup, which holds the old value). **After that step there is no path back to the old value, by design.**
- `old-after` 200: the old value still works. The service did not restart with the new `.env`, or another credential
  (an active guest pass) matches. Do not delete the backup; check `sudo systemctl status dynasty` and
  `sudo journalctl -u dynasty -n 50 --no-pager` in the second terminal.
- `429`: the login throttle is holding you (each refused attempt counts, `src/api/rate_limit.py`). Wait for the
  `Retry-After` period; do not loop the script. A 429 proves nothing either way.
- `new` is not 200: stop. Roll back (below) before doing anything else.

**Also verify** the other signed-in sessions behave as expected (runbook section 3) and that the next deploy's box `.env`
guard step passes (the independent proof the file is not a placeholder).

**Rollback** (before runbook step 6 deleted the backup): restore the backup and restart:
`sudo -u dynasty bash -lc 'cd /home/dynasty/trade-calculator && cp -p .env.bak.<date> .env' && sudo systemctl restart dynasty`,
then run step 1 again and expect `login HTTP 200 (old-before)`. If step 6 already ran, set a fresh value by repeating
steps 0, 2 and 3; there is no path back to the old one.

**Record** the rotation date only (for example "rotated 2026-11-19") in the security record
(`C10-CLOSE-06/credential-rotation`); never the value or a hash. The script writes nothing and sends nothing but the login
request; it accepts the password only through a hidden prompt or an environment variable, never as an argument, and
`tests/scripts/test_check_login_status.py` pins that.

## 6. Decisions the owner needs to make

1. Run the section 2 comparison and the deploy-key commands (runbook section 2): the repository and environment secret
   lists, the deploy keys, the collaborator list and the default `GITHUB_TOKEN` permission were all unreadable.
2. Approve deleting `DLF_*`, `IDPSHOW_SESSION_JSON` and `ANTHROPIC_API_KEY` from GitHub (F2, F3, F5), or say which are
   still wanted.
3. Decide whether `claude.yml` should keep `contents: write` (F6) and whether to add required reviewers to `production`.
4. Schedule the `JASON_LOGIN_PASSWORD` rotation, with the replacement-access precondition met.
5. The diagnostics-key split (F1) and the ruleset (F9) remain separate owner decisions; this inventory does not make them.
