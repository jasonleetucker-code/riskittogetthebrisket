# Access and credential inventory (read-only), 2026-11-18

**Scope:** what could be established from the repository and from public-readable GitHub endpoints in the
agent's session. **Names only. No secret value was read, and none appears here.** Nothing was changed.
The owner completes the unreadable rows with the commands in `docs/ops/ADMIN_ONLY_ACTIONS_RUNBOOK.md` §2.

## 1. What the agent could and could not read

| source | result | consequence |
|---|---|---|
| `GET /repos/<repo>/rulesets` and `/rulesets/19976839` | readable | live bypass actors and rules recorded in §2 |
| `GET /repos/<repo>/keys` (deploy keys) | **403** ("not permitted through this proxy") | key ids, titles, `read_only` flags **not verified today**; use runbook §2 step 1 |
| `GET /repos/<repo>/collaborators` | **403** | roles/collaborators **not verified**; use `gh api repos/<repo>/collaborators --jq '.[]|{login,role_name}'` |
| `GET /repos/<repo>/actions/permissions/workflow`, `/actions/secrets` | **403** | repo default `GITHUB_TOKEN` permission and the secret list **not verified** |
| `.github/workflows/*.yml` | readable | secret NAMES and write-capable workflows in §3 and §4 |

## 2. Live `main` ruleset (id 19976839, `active`, last updated 2026-07-29)

Rules: `deletion`, `non_fast_forward` only. **No `pull_request` rule and no required status checks**, so any
actor allowed to push can push straight to `main`.

Bypass actors (all `always`): `DeployKey`, `RepositoryRole 4` (write), `RepositoryRole 5` (admin).

The prepared payload (`deploy/github/main-protection-ruleset.json`) differs as follows
(`bash deploy/github/apply-branch-protection.sh --dry-run`, run 2026-11-18, sent nothing):

```
- bypass RepositoryRole id=4 mode=always        (write role loses direct-push)
- bypass RepositoryRole id=5 mode=always
+ bypass RepositoryRole id=5 mode=pull_request  (admin: PR path only; red-check merge stays possible)
+ bypass Integration id=15368 mode=always       (GitHub Actions app: refresh workflows keep pushing)
+ rule pull_request                             (0 approvals)
+ rule required_status_checks                   (Validate PR, Receipt check; strict=false)
```

`DeployKey always` is unchanged. Dropping the **write-role** bypass is the one behavior change the owner should
confirm: any collaborator with the write role (other than the deploy key and the admin) loses direct push.

## 3. Secrets referenced by workflows (names only; values unknowable here)

| secret | used by | what it is | write capability |
|---|---|---|---|
| `DEPLOY_SSH_PRIVATE_KEY`, `DEPLOY_HOST`, `DEPLOY_USER`, `DEPLOY_PORT`, `DEPLOY_KNOWN_HOSTS` | 27 workflows (deploy.yml and 26 diagnostic / proof / verification workflows) | SSH login to the **production VPS** (not a GitHub deploy key) | **full shell as `DEPLOY_USER` on prod** (sudo-capable by design: the deploy and proof scripts run `sudo -n`) |
| `GITHUB_TOKEN` (automatic) | audit-*, e2e, health-check, intel-refresh, scheduled-refresh | per-run token | write only where the workflow declares `contents: write` |
| `ANTHROPIC_API_KEY` | weekly-narratives.yml | paid API key | spend |
| `CLAUDE_CODE_OAUTH_TOKEN` | claude.yml | Claude Code action auth | acts as the repo (`contents: write`) |
| `DLF_USERNAME`, `DLF_PASSWORD`, `DRAFTSHARKS_EMAIL`, `DRAFTSHARKS_PASSWORD`, `IDPSHOW_SESSION_JSON` | scheduled-refresh.yml (+ draftsharks-diagnostic.yml) | third-party source logins | none on GitHub |
| `INTEL_REFRESH_TOKEN` | intel-refresh.yml | bearer for a backend refresh route | triggers a backend job |
| `SHARP_SMOKE_TOKEN` | verify-sharp-production.yml | bearer for a Sharp smoke route | read-only smoke |

Workflows that declare `contents: write` (can push to `main`/branches with `GITHUB_TOKEN`): `class-b-model-branch.yml`,
`claude.yml`, `refit-hill-curves.yml`, `scheduled-refresh.yml`, `verify-sharp-production.yml`, `weekly-narratives.yml`.
The four that run `git push` (refit-hill-curves, scheduled-refresh, verify-sharp-production, weekly-narratives) push to `main` (pinned by
`tests/deploy/test_main_protection_ruleset.py`, which requires the Actions bypass).

Trigger shape of the 27 `DEPLOY_SSH_PRIVATE_KEY` workflows: 21 `workflow_dispatch` only; 3 `workflow_dispatch` +
`workflow_run` (retention-backup-proof, sharp-records-bootstrap, v1-authenticated-verification); `deploy.yml` and
`lane4-onbox-verification.yml` on `push` (+ dispatch); `retention-health.yml` on `schedule`. None triggers on
`pull_request`, so fork PRs cannot reach these secrets.

## 4. Deploy keys on the box (from repository scripts; GitHub side unreadable today)

| identity | where | use | write needed? |
|---|---|---|---|
| `~/.ssh/github_push` (via `~/.ssh/config` `IdentityFile`; measured 2026-08-15 in `deploy/playerctx_history_push.sh`) | production box, user `dynasty` | box timers push data commits to `main` (`dlf_fetch_and_push.sh`, `idpshow_fetch_and_push.sh`, `playerctx_history_push.sh`) and the deploy `git fetch origin` | **yes** (pushes) |
| `~/.ssh/github_deploy_key` (default in the three push scripts) | production box | recorded as **absent** on the box (2026-08-15) | n/a |
| GitHub deploy keys 145025388 "hetzner-riskit" (last used 2026-03-09), 148579683 "dynasty-prod-deploy" (last used 2026-06-24) | GitHub side | named retirement candidates by the 2026-10-07 audit; current state **not readable by the agent** | unknown |

## 5. Excess-privilege findings

1. **No `main` protection of substance is live.** `deletion` / `non_fast_forward` only. The prepared ruleset
   closes it (runbook §1). Severity: high; cure is one owner command.
2. **One SSH key to the prod VPS is shared by 27 workflows**, most of which are read-only diagnostics or proofs.
   A leak or a bad workflow edit has full prod-shell reach. Hardening (not decided): a second, forced-command or
   read-only key for diagnostics, keeping the full key for `deploy.yml` only. Not done here; it needs box changes.
3. **Write-capable GitHub deploy key also serves the box's read-only `git fetch`.** If the same key does both,
   the fetch path carries write power it does not need. Confirm with runbook §2 steps 2 to 4; if two keys exist,
   make the fetch-only one `read_only: true`.
4. **`GITHUB_TOKEN` pushers are a blanket `Integration 15368` bypass.** Any workflow granted `contents: write`
   can push to `main`. Today that is the four refresh/evidence workflows by design. Keep the list at four;
   `tests/deploy/test_main_protection_ruleset.py` fails when a new direct-to-main pusher appears without a bypass.
5. **Retention candidates** (two named deploy keys) may be unused write access. Retire only per runbook §2.
6. **Unverifiable today:** repo default workflow `GITHUB_TOKEN` permission (Settings, Actions, General; should be
   read-only with per-workflow `permissions:`), the collaborator list, and secret presence. Owner checks them.
