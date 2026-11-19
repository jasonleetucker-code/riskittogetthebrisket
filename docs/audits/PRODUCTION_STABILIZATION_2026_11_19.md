# Production stabilization and closeout — 2026-11-19

**What this is.** The live record of the owner directive "PRODUCTION STABILIZATION, OPERATIONAL HARDENING & FINAL
CLOSEOUT" (2026-11-19): finish the operational work left by the 2026-11-18 audit implementation
(`docs/audits/AUDIT_IMPLEMENTATION_2026_11_18.md`). A future session resumes from this file plus
`docs/WORK_CLAIMS.md`.

**Authority.** Intake STAB-1 … STAB-12 (`docs/OWNER_REQUESTED_TODO.md`), authorized in `docs/EXECUTION_PLAN.md`
(same date). Owner-only gates: credentials, backup destination and spend, repository visibility and history, applying
branch protection, security-policy decisions, the production Node cutover, deploy-path activation, the 2030 pick
policy.

**Statuses.** NOT STARTED · IN PROGRESS · PR OPEN · MERGED · DEPLOYED · VERIFIED COMPLETE · PREPARED — OWNER ACTION ·
PREPARED — OWNER DECISION · BLOCKED — EXTERNAL / TIME. Set only from evidence, never from intent.

## Starting state (measured 2026-11-19 ~09:05 UTC)

- `origin/main` `109c5e8d`; production `/api/status` `build.commit` `93c6813c` (process started 04:20 UTC);
  three data-refresh deploys overnight, all green (44391224274, 44411720980, 44455009771).
- `freshness_slo`: measured; top-200 stale 0; priced withheld 2; board age 0.54 h; private sources stale 4 of 4.
- Deploy runs 32212914036 (`workflow_dispatch` of `1d9a001c`, created 2026-08-19) and 43096180672 (`push` of
  `44a0d573`, created 2026-11-11): both still `queued`.

## Summary table

| # | Workstream | Status | PR / commit | CI | Production evidence | Remaining blocker |
|---|---|---|---|---|---|---|
| 1 | Obsolete deploys / stale-deploy safeguard | IN PROGRESS | — | — | — | — |
| 2 | Signals + alert delivery | IN PROGRESS | — | — | — | owner reconnect; notification destination |
| 3 | Branch protection | IN PROGRESS | — | — | — | owner approval to apply |
| 4 | Off-box backups | IN PROGRESS | — | — | — | owner destination choice |
| 5 | Credentials and deploy keys | IN PROGRESS | — | — | — | owner rotation |
| 6 | Node 22 production | IN PROGRESS | — | — | — | owner cutover approval |
| 7 | Public-repo data exposure | IN PROGRESS | — | — | — | owner policy decision |
| 8 | Browser-test skip accounting | IN PROGRESS | — | — | — | — |
| 9 | Real-device and mobile verification | IN PROGRESS | — | — | — | physical device (owner) |
| 10 | CI housekeeping and observability | IN PROGRESS | — | — | — | — |
| 11 | 2027 draft-pick policy | IN PROGRESS | — | — | — | owner decision |
| 12 | Data-only deploy shadow evidence | IN PROGRESS | — | — | — | elapsed time (≥14 days) |

## Per-workstream record

### 1. Obsolete deployments and the stale-deploy safeguard

Findings (2026-11-19):
- Both runs still `queued`. 32212914036 targets `1d9a001c` (2026-08-19 data refresh), which is NOT an ancestor of
  current `main` (diverged history); 43096180672 targets `44a0d573` (2026-11-11), an ancestor 447 commits behind.
- A queued run executes the `deploy.yml` of its OWN commit, and that workflow's remote command replaces the box's
  `deploy/deploy.sh` with the target commit's copy before running it. So no guard added today — in the workflow or on
  the box — can bind an already-queued run. Only cancellation, or the run's own guards, can.
- Both old workflow versions already contain the ancestry guard (read the box's last-successful-deploy commit; refuse
  a backwards or diverged target). It is defeated only by a `workflow_dispatch` with `allow_non_fast_forward=true`,
  whose input the API does not expose for the August run.
- Cancellation (2026-11-19 ~09:20 UTC): `POST …/runs/{id}/cancel` → 409 "Cannot cancel a workflow run that is not
  in progress"; `POST …/runs/{id}/force-cancel` → 409 for both ("not in progress" / "has not been queued yet"). The
  runs are GitHub-side zombies: 32212914036 has one job ("Validate Build Inputs") queued since 2026-08-19T03:39:40Z
  that never started; 43096180672 has zero jobs. `updated_at` equals `created_at` for both.
- Why neither can replace production even if GitHub ever starts it:
  - 32212914036 was dispatched by the August `scheduled-refresh.yml` as `gh workflow run deploy.yml --ref main` —
    no inputs, so `allow_non_fast_forward` is its default `false`. Its target `1d9a001c` is not in `main`'s
    history, so its own guard refuses with "DIVERGED".
  - 43096180672 is a `push` run (no inputs possible); its target `44a0d573` is an ancestor of the production commit,
    so its own guard refuses with "move production BACKWARDS".
  - Both read the same box file the current guard reads (`LAST_SUCCESSFUL_DEPLOY_COMMIT_FILE`).
- Remaining hygiene (optional owner action): delete the two run records from the Actions UI; the API offers no cancel.

### 2. Signals and production alert delivery

Baseline from the previous program: `signalsSf` `auth_unavailable` x66, last success ~400 h; session
`reconnect_required`; 0 reconnect-notice sends recorded on any channel; SMTP to `smtp.gmail.com:465` firewalled on
the VPS.

### 3. Branch protection

Dry run (2026-11-19, `bash deploy/github/apply-branch-protection.sh --dry-run`, read-only token): would `PUT`
ruleset 19976839. Live today: rules `deletion` + `non_fast_forward` only; bypass DeployKey always, RepositoryRole 4
(write) always, RepositoryRole 5 (admin) always — so **no required checks protect `main`**. After applying:
- Adds rule `pull_request` (0 approvals) and `required_status_checks` `Validate PR` + `Receipt check`
  (integration 15368 = GitHub Actions; `strict` off, consistent with the HEAD-FREEZE release candidate).
- Bypass: DeployKey always (kept), GitHub Actions integration 15368 always (added), admin role 5 only through a PR,
  write role 4 removed.

Safety checks done before recommending it:
- **Who lands commits on `main`** (first-parent, 2026-10-20 → 2026-11-19):
  - `github-actions[bot]` 362 (refresh / stamp / ops commits): bypass via integration 15368.
  - Box timers "IDP Show Fetch (prod)" 297, "DLF Fetch (prod)" 285 and "playerctx History (prod)" 4: all push over
    SSH with `~/.ssh/github_deploy_key` (`deploy/{dlf,idpshow}_fetch_and_push.sh`,
    `deploy/playerctx_history_push.sh`), so the DeployKey bypass covers them.
  - PR merges 294 and Dependabot merges 4: allowed when the two checks are green.
  - No person or agent pushed directly to `main` in that window, so nothing that ships today is blocked.
- **The required checks always report.** `pr-validation.yml` and `pr-verification-receipt.yml` run on every
  `pull_request` to `main` with no path filters. Dependabot PRs get both (#2229 and #2255 green; #2231's
  `Validate PR` is red, so it will correctly be blocked).
- **No dependency cycle.** The checks run on PRs; pushes by the bypass actors do not wait on them.
- **No lockout.** The admin keeps a PR-only bypass for an emergency merge.

Applying needs `administration: write`; this session's token has read access only. Owner action: run the
apply script (see Owner actions). Verification after apply, done by me:
- `gh api repos/…/rulesets/19976839` matches the payload;
- PR #2231 (red `Validate PR`) reports `mergeable_state` `blocked`;
- the next refresh commit lands on `main` (bypass works).

### 4. Off-box backups and disaster recovery

### 5. Credential rotation and deploy-key hardening

### 6. Node 22 production migration

### 7. Public-repository data exposure

### 8. Browser-test skip accounting

### 9. Real-device and mobile verification

### 10. CI housekeeping and observability

### 11. 2027 draft-pick policy

### 12. Data-only deploy shadow evidence

**Structural gap found (2026-11-19).**
- The observer had produced 13 runs: 7 completed and 6 skipped (superseded deploys).
- All 7 classified CODE: every one followed a PR-merge `push` deploy. DATA_ONLY comparisons so far: **0 of 30**.
- The data deploys themselves are never observed. Deploy Production runs started by `github-actions[bot]` via
  `workflow_dispatch` (the scheduled-refresh data deploys 44315967974, 44411720980 and 44455009771, all green) have
  NO `data-delivery-shadow.yml` run.
- Cause: GitHub does not create `workflow_run` runs for workflows started by `GITHUB_TOKEN`, so the observer's
  only trigger never fires for exactly the population it measures. The evidence bar could never be met as built.
- The same gap hides post-deploy verification. `v1-authenticated-verification.yml` (trade smoke, browser suite,
  security acceptance) never runs after a data deploy, which is the majority of deploys.
- Fix routed to worker A as unit A4: the deploy workflow dispatches both workflows (dispatch events from
  `GITHUB_TOKEN` do start runs) only for bot-started deploys, so human deploys are not double-run.
- Backfill now: the three missed data deploys were dispatched to the observer manually (`deploy_run_id` input,
  read-only).

## Integration log

## Owner actions (consolidated, priority order)
