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

### 2. Signals and production alert delivery

Baseline from the previous program: `signalsSf` `auth_unavailable` x66, last success ~400 h; session
`reconnect_required`; 0 reconnect-notice sends recorded on any channel; SMTP to `smtp.gmail.com:465` firewalled on
the VPS.

### 3. Branch protection

### 4. Off-box backups and disaster recovery

### 5. Credential rotation and deploy-key hardening

### 6. Node 22 production migration

### 7. Public-repository data exposure

### 8. Browser-test skip accounting

### 9. Real-device and mobile verification

### 10. CI housekeeping and observability

### 11. 2027 draft-pick policy

### 12. Data-only deploy shadow evidence

## Integration log

## Owner actions (consolidated, priority order)
