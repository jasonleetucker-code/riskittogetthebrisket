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
- **Correction from independent review (2026-11-19):** the old guards skip the ancestry check when the SSH read of
  the box baseline FAILS. `… || true` leaves `LAST_DEPLOYED` empty, which reads as "no baseline". So a zombie that
  GitHub started during an SSH blip could still ship its old commit. #2266 closes that for future runs (a failed
  read refuses), but it cannot bind an already-queued run.
- **Neutralization (2026-11-19 ~10:30 UTC):** `DELETE /actions/runs/{id}`.
  - 32212914036 (August, `1d9a001c`): **deleted**; the run now answers 404.
  - 43096180672 (November push of `44a0d573`): **403 "Could not delete the workflow run"**; it is still `queued`
    with zero jobs.
  - Residual risk for that one needs both events at once: GitHub starting an 8-day-old zero-job run, and the SSH
    read failing at that moment. Otherwise its own guard refuses it as backwards.
  - Owner action: delete or cancel it from the Actions UI, or ask GitHub support to purge it.

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

Findings (2026-11-19):
- **Box runtime is Node 20.** The box stages with `scripts/stage_release_artifact.py`, which refuses an artifact whose
  Node major differs from the box's. Deploy 44330192334 (artifact built on 22) was refused, and every deploy built on
  20 since (#2256) has been accepted.
- **The box uses a system install, not nvm.** The frontend unit runs `/usr/bin/npm` (deploy 44455009771 log:
  "Frontend systemd unit ExecStart binary resolved to: /usr/bin/npm"). `deploy/deploy.sh::resolve_node_toolchain`
  tries PATH before nvm.
- **Compatibility.**
  - Next.js 16.4.x declares `engines.node >=20.9.0`.
  - Optional native bindings in the lockfile (rolldown) declare `^20.19.0 || >=22.12.0`, so the box needs 22.12 or
    later. The current 22 LTS line (v22.23.4 used here) meets that.
  - `frontend/package.json` `engines` is already `>=20 <23`, and `.nvmrc` is already `22`.
  - The CI pins on the four production lanes (deploy, release-candidate, pr-validation, e2e) are 20, pinned by
    `tests/deploy/test_deploy_node_matches_production.py`.
  - The full local build and vitest on 22 passed in #2252.
- **The cutover has to be ONE window, box first.**
  1. The owner installs Node 22 (≥22.12) on the box.
  2. Immediately merge the prepared lane PR: the four lanes to 22, `PRODUCTION_NODE_MAJOR = "22"`, `engines`
     `>=22 <23`.
  3. The next deploy builds and stages on 22.
  4. Verify the release manifest and `/`, `/trade`.

  Any deploy that runs between steps 1 and 2 is refused at staging (no production change; the running site keeps
  serving), so the window should be minutes. The lane PR is prepared after worker A's deploy-workflow PRs merge
  (same files).

### 7. Public-repository data exposure

### 8. Browser-test skip accounting

### 9. Real-device and mobile verification

### 10. CI housekeeping and observability

- **Stale workflow registrations: DONE (2026-11-19 ~10:30 UTC).** The list was re-derived live rather than taken from
  the Task 15 doc: 113 registered workflows; 57 whose file is not on `main`, excluding the two GitHub-managed
  `dynamic/dependabot/*`. The most recent run of any of them was 2026-10-19 (`zz-enable-prod-verification.yml`); none
  ran in the last 14 days. All 57 were set to `disabled_manually` with
  `PUT /actions/workflows/{id}/disable`: 57 ok, 0 failed. After: 56 active, 57 disabled.
  - Reversible: `PUT …/enable`. Run history is kept, and no workflow file or definition was deleted.
  - Several were production-touching one-shot repair or proof jobs (`_tmp_chatgpt_v1_27_prod_proof`,
    `zz-enable-prod-verification`) that any branch still carrying the file could have dispatched.
- **Rank-form drift (#898): resolved as a tripwire, not silenced.**
  - Since T15 (`67f19166`), the standing drift recorded in `config/ci/rank_form_drift_accepted.json` is green with
    a warning and a summary. New or worse drift is still RED and comments on the issue.
  - The owner closed #898 on 2026-11-18 14:58 UTC ("completed"). The last run (dispatch, 2026-11-18 17:47) passed.
  - The constants were deliberately not re-pinned: that is a valuation methodology change. Measured standing drift
    (2026-11-17): offense excess RMSE +96.5, IDP +181.8, against a 25.0 threshold.
- **Sharp verification honesty: in place since T15.**
  - `Verify Sharp Production Population` publishes `measured` and runs its `verdict` job only when production was
    actually measured.
  - Today `/api/sharp/cohort` answers 401, so every run reports `unverifiable_unauthenticated` on #1727 ("green, and
    it has not measured anything"). It never claims a pass.
  - Measuring it needs `SHARP_SMOKE_TOKEN`. That is a production credential (a repository secret plus the same value
    in the box `.env`), so it is owner action 11.
- **Ubuntu runner apt failures:** #2268 (`scripts/ci/install_apt_packages.sh`: retry plus a mirror fallback).
- **Cold-start verification:** #2269 (readiness probe; worst case 360 s, inside the 480 s cap).
- **Post-deploy observation of bot deploys:** #2272. Deploy Production now dispatches the shadow observer and the
  authenticated verification for bot-started deploys. GitHub never fires `workflow_run` for them (see §12).

### 11. 2027 draft-pick policy

Precise difference (`src/identity/pick_lifecycle.py`):
- **Board (prices picks):** `board_pick_horizon` ends at the latest PROVEN-completed draft + 3. This is owner decision
  2026-10-19: "let's not add 2030 until the 2027 draft is complete, because I think that's when we're issued our
  2030 picks".
- **League (displays owned picks):** `league_draft_years` spans `OWNED_PICK_HORIZON_CLASSES` = 4 classes from the
  calendar anchor `max(calendar year, Sleeper league.season)`, minus retired classes.
- **Today (2026-11-19):** both show 2027–2029; 2026 is retired.
- **From 2027-01-01 until the 2027 rookie draft is proven complete:**
  - the league anchor becomes 2027, so the league lists 2027–2030;
  - the board still ends at 2029;
  - a 2030 pick appears in league views and the trade tools as unpriced (never 0), pinned by
    `test_documented_divergence_league_window_reaches_one_class_past_the_board_horizon`.
- Sleeper issues class N+3 only when class N's draft completes (the code's own rule). So until the 2027 draft those
  2030 rows are default-ownership placeholders that Sleeper has not issued and that cannot be traded.

Recommendation: end the league window at the same issuance rule (the board-horizon function fed this league's own
completion evidence). The league then never lists an unissued class, and every pick it shows is one the board prices.
2030 appears in both scopes the moment the 2027 draft is proven complete. Values do not change.

Prototype (NOT a PR, awaiting the decision): branch `claude/serene-shannon-7lsrm9-s11-league-pick-window` (`d5b8161d`),
an 8-line change in `league_draft_years`. Measured effects:
- 8 tests that pin today's behaviour would be updated with the decision (listed in the commit message). The full
  related run was 2491 passed / 9 failed; 8 failures are those pins, and 1 was a load flake that passes alone.
- Side effect to decide: a league with NO completion evidence would show 3 future classes instead of 4. That is the
  board's fail-closed floor, which applies to the leagues outside `dynasty_main`.

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
  read-only). Results (2026-11-19 ~09:45 UTC):

  | Deploy run | Base → target | Classification | Full gate | Fast path would ship | Outcome | Full gate runner-min / wall | Shadow wall |
  |---|---|---|---|---|---|---|---|
  | 44411720980 | `9ec8e076` → `6535a836` | DATA_ONLY (code tree identical, 96 data paths) | pass | yes | AGREE_SHIP | 123.8 / 19.4 min | 6.0 min |
  | 44315967974 | `bd17e684` → `3922bc9f` | DATA_ONLY (85 data paths) | pass | yes | AGREE_SHIP | 143.4 / 49.8 min | 9.1 min |
  | 44455009771 | `6535a836` → `93c6813c` | CODE (3 `config/model_registry/` paths) | pass | — (code delta) | — | — | — |

**Full evidence (2026-11-19 ~11:50 UTC).** Method:
- The observer was dispatched against every non-cancelled Deploy Production run since 2026-11-05: 40 retrospective
  runs, 4 at a time, plus the 3 above. The observer is read-only and decides nothing.
- All `data-delivery-shadow` artifacts were downloaded and folded with the repository's own
  `python scripts/data_delivery_shadow.py aggregate`.
- All comparisons ran under one rule set (`rulesDigest` `aa32d06b…`). Raw receipts: `shadow_art/` in the session
  scratchpad. The aggregate output is quoted below.

| Measure | Value |
|---|---|
| Distinct deploys evaluated | 49 (2026-11-05 → 2026-11-19) |
| Classification | 35 CODE · 15 DATA_ONLY |
| DATA_ONLY outcomes | 9 `AGREE_SHIP` · 6 `UNSAFE_DISAGREEMENT` · 0 conservative · 0 `FAST_PATH_NOT_RUN` |
| Compared window | 10.3 days (2026-11-08 → 2026-11-18) |
| Runner time the fast path would have saved | 1,071.7 runner-min over the 9 agreed ships (median 118.9 per delivery; shadow job 5–9 min wall) |
| `activationEvidenceMet` | **false** (≥30 compared: no; ≥14 days: no; zero unsafe: no; zero not-run: yes; one rule set: yes) |

Every `UNSAFE_DISAGREEMENT` was triaged. In each case the full gate refused a data-only delivery because of a
hard-gate test that read the live board or the newest archive, or in one case the CI process's own memory. Each
test has since been pinned:

| Deploy | Date | Failing hard-gate test | Cause | Fixed by |
|---|---|---|---|---|
| 42496066177 | 11-08 | `test_w30_f008_hill_denominator_research::test_c0_rebuild_structure_on_the_pinned_archive` | read today's CSVs | #2172, `1be5e247` |
| 42821399496 | 11-10 | `test_audit_cw40_batch_m1_regression::test_w02_f003_no_idp_row_is_snapped…` | live board: 1 IDP row fell within ±1 of an anchor multiple | #2208/#2209 (pinned audit board) |
| 43075102338 | 11-11 | `test_idp_hampel_n3_challenger::test_on_changes_the_drop_decision…` | needed 3-voter IDP rows on the live board | #2208 |
| 43333485414 | 11-13 | `test_chase_upside_mcp_tools::test_roster…picks…` and `test_heap_report::test_heap_loop_releases…` | newest board's team 0 had traded every pick; CI process RSS > 1 GiB | #2199 |
| 43741547744 | 11-15 | `test_hill_alignment_audit::test_identity_csv_override…` | identity CSVs copied from today's tree | #2213 |
| 43935057527 | 11-16 | `test_bdvm_saturation_study::test_outcome_evaluation_numbers…` | newest outcome archive | `c9a3d02f` (2026-11-17 14:30 UTC) |

- None of the six showed a defect in the delivered data. The contract FULL lane, runtime import and tracked-data
  privacy (the fast path's blocking gates) passed on every one.
- Since the last fix (`c9a3d02f`) there have been 3 DATA_ONLY comparisons, all `AGREE_SHIP`, with no disagreement.

**Safety assessment.**
1. Agreement is now expected **by construction**:
   - Since #2208/#2209/#2213/`c9a3d02f`, no blocking hard-gate test reads a data root; the hermetic-input guard
     enforces this.
   - On a DATA_ONLY delivery the code tree is byte-identical to a base that already passed, so the full gate can only
     disagree if hermeticity breaks.
   - Further comparisons therefore mainly prove that hermeticity holds in practice and that the classifier is right.
     They are not independent evidence that a given data delivery is good.
   - Data content is guarded by the same checks on both paths: the contract FULL lane, the box-side
     `verify-deploy.sh`, the post-deploy smoke and the live health check.
2. Two advisory gates carry no signal today. `source_health` and `livedata_tests` failed on all 15 DATA_ONLY
   deliveries: the stale private Signals sources, plus the live-data lane. An advisory gate that is always red cannot
   warn, so activation should wait until both are normally green, or are made specific.
3. The DATA_ONLY population is smaller than the data-deploy population:
   - 28 of the 43 bot data deploys classified CODE.
   - 15 of those 28 did so only because of `config/model_registry/` (Hill Autopilot run records riding with the data
     refresh).
   - That is correct, because a scope-masters change alters production values. It caps the saving until the
     deferred record-only-registry rule (design §7) is decided.
4. `classify_deploy_delta.py` saw no inputs that would have needed a guess: 0 classifier input errors and 0 diverged
   bases in 49 runs.

**Activation and rollback procedure.**
- Owner-gated and NOT built: `docs/ops/DATA_ONLY_DELIVERY_DESIGN_2026-11-18.md` §8 (phase C1, the
  `DATA_DELIVERY_FAST_PATH` variable, box-side re-classification, separate receipts) and §9 (the exact Agent OS
  amendment text).
- Rollback: unset `DATA_DELIVERY_FAST_PATH`, and the next deploy takes the full gate. A data rollback is
  non-fast-forward, which is always CODE, so it always takes the full gate.

**Recommendation: do NOT activate yet.**
- Evidence is 15 of 30 compared deliveries over 10.3 of 14 days, and 6 historical unsafe disagreements (all triaged
  and fixed).
- Observation is now automatic: #2272 dispatches the observer after every bot data deploy.
- At about 1.4 DATA_ONLY deliveries per day, 30 compared over ≥14 days is reachable:
  - **around 2026-11-30** if the 15 retrospective comparisons count;
  - **around 2026-12-10** if only comparisons after `c9a3d02f` count.

  I recommend the stricter rule, because only those comparisons reflect today's hermetic gate.
- Revisit then, together with point 2 above. No variable has been set, and nothing deploys differently.

## Integration log

**Train S12 (2026-11-19).** Eight PRs, validated as one tree, then merged in order with `expectedHeadSha`.

- Release candidate 44511704167 on `trainS12@512f473a`, built from `origin/main@3c07f519` plus every PR head. HEAD-FREEZE: 0 class-A, 0 class-B and 0 class-C commits outstanding — "the validated tree IS the tree that will merge". Result: 11 of 11 jobs green (build/plan, static/contract/frontend, hard gate 8/8, verdict).
- Merged 11:30 UTC, in this order:

  | PR | Unit | Merge commit |
  |---|---|---|
  | #2264 | STAB-4 off-box backups | `5cdb4565` |
  | #2263 | STAB-5 credentials | `13738971` |
  | #2262 | STAB-7 data governance | `9bbba4ae` |
  | #2267 | STAB-2 alert routing | `54cf594d` |
  | #2266 | STAB-1 deploy guard | `c0e41a15` |
  | #2268 | STAB-10 apt | `0ca4b1c0` |
  | #2269 | STAB-10 cold start | `c1c60f6b` |
  | #2272 | STAB-10/12 bot-deploy observation | `ecc3464e` |

- `git diff 512f473a ecc3464e` is empty: `main` equals the validated tree.
- The per-PR `Validate PR` runs for #2266, #2267, #2269 and #2272 were cancelled while queued, to free runners for the release candidate, which tests the stricter exact merged tree. Each PR carries a comment saying so.
  - #2267's earlier real failure (`tests/test_explicit_text_encoding.py`: a `write_text` without `encoding=`) was fixed in `4bf3cbe9` before the train was rebuilt.
- Deploys:
  - The seven intermediate push deploys were superseded by the group.
  - The first (`5cdb4565`, #2264 alone) had already started its pre-deploy gate. My request to cancel it was refused by the session's permission policy, so it runs and the final deploy follows it.
  - `5cdb4565` is a fast-forward ancestor of `ecc3464e`, so this costs one extra restart and nothing else.

## Owner actions (consolidated, priority order)

Each item says what to do, why, the risk, what is prepared, how I verify, and the rollback. Items 1–4 are the
immediate-safety set.

1. **Turn on alerts (STAB-2), after the alert-routing PR #2267 deploys.**
   - Do: follow `docs/ops/OWNER_ALERT_CHANNEL_SETUP_2026-11-19.md` steps 1–4:
     - install the ntfy app and choose an unguessable topic;
     - add `NOTIFY_WEBHOOK_URL` to the box `.env` and restart `dynasty`;
     - add two `systemctl edit` drop-ins;
     - add the repo secret.
   - Why: today no production alert reaches you. 0 reconnect-notice sends in ~400 h, and SMTP 465 is firewalled.
   - Risk: low. Alert text passes through ntfy.sh, and the topic name is a secret.
   - Verify: I run the probe (`alertRouting.*` true), then `notify-test` (5 TEST pushes) and the health-check
     `owner_push_test` (1 push). You confirm 6 arrived.
   - Rollback: remove the line and the drop-ins, delete the secret.
2. **Reconnect Signals (STAB-2).**
   - Do: on the box, `python scripts/signals_connect.py reconnect`; it emails you one code. Then provision again
     (`docs/sources/SIGNALS_ACCOUNT_CONNECTION.md`).
   - Why: `signalsSf` is ~400 h stale and its votes are withheld.
   - Verify: I re-run the probe (session healthy, `lastOutcome` ok), watch the next collection, the source
     freshness and the contract `sourceVotingStatus`, and confirm SLO issue #2258 closes.
   - Rollback: none needed; a reconnect only replaces an expired session.
3. **Apply branch protection (STAB-3).**
   - Do: `GH_TOKEN=<admin token> bash deploy/github/apply-branch-protection.sh` (the dry run is already reviewed
     above).
   - Why: `main` has no required checks today.
   - Risk: reviewed. Every automated pusher keeps its bypass (deploy key, GitHub Actions); people merge only through
     green PRs; admin keeps a PR-only bypass.
   - Verify: I read the live ruleset, check that PR #2231 (red) shows `blocked`, and watch the next refresh commit land.
   - Rollback: re-run the script with the saved previous payload (runbook §1).
4. **Remove the last zombie deploy run (STAB-1).**
   - Do: Actions → Deploy Production → run 43096180672 → Cancel or Delete. The API refuses both. If the UI also
     refuses, ask GitHub support to purge it.
   - Why: it carries a guard that fails open on an SSH-read failure.
5. **Install Node 22 on the box (STAB-6).**
   - Do: `docs/ops/NODE22_CUTOVER_2026-11-18.md` §"Cutover window 2026-11-19" steps 1–2, then tell me
     "Node 22 installed". I merge the HOLD PR #2271 at once.
   - Why: Node 20 is past end of life.
   - Risk: deploys in the minutes between the install and the merge are refused at staging (no production change).
   - Verify: `node22_box_check.sh --require 22.12`, the first 22-staged deploy, and post-deploy verification.
   - Rollback: in the doc (downgrade the package and revert the PR together).
6. **Rotate `JASON_LOGIN_PASSWORD` (STAB-5).**
   - Do: follow `docs/ops/CREDENTIAL_INVENTORY_2026-11-19.md` (from #2263): generate the password on your machine,
     set it in `.env`, restart.
   - Verify: `scripts/check_login_status.py` prints only the HTTP status. The old password must fail.
   - Rollback: the `.env` backup.
   - Also in the same doc: run the secret-name comparison; approve deleting the unused `DLF_*`,
     `IDPSHOW_SESSION_JSON` and `ANTHROPIC_API_KEY` if unused; decide `claude.yml` permissions and `production`
     environment reviewers.
7. **Off-box backups (STAB-4).**
   - Do: approve Backblaze B2 with `rclone crypt`, a bucket-scoped no-delete key and Object Lock (estimate about
     $0.10/month at ~15 GB). Create the account, bucket and key per `docs/ops/BACKUP_OFFBOX_DESIGN_2026-11-19.md`
     §8, keep the crypt password offline, and run the first restore drill.
   - Why: every backup generation is on the production disk.
8. **Data-exposure policy (STAB-7).** Sign the five-point decision in
   `docs/security/DATA_EXPOSURE_POLICY_RECOMMENDATION_2026-11-19.md` §9: stay public; move paid-vendor and owner-id
   files to a private data repo; no history rewrite.
9. **2030 pick policy (STAB-11).** Approve or decline capping the league pick window at Sleeper's issuance rule
   (§11 above; prototype branch `claude/serene-shannon-7lsrm9-s11-league-pick-window`).
10. **Physical-device checks (STAB-9).** Work through `docs/qa/REAL_DEVICE_CHECKLIST_2026-11-19.md` (from #2270) on
    an iPhone.
11. **Sharp smoke token (STAB-10).** Provision `SHARP_SMOKE_TOKEN` (#1727): one random value, set both as the repo
    secret and in the box `.env`, then restart `dynasty`. Until then the Sharp check honestly reports "not measured".
    #898 is already closed by you; re-pinning the rank-form constants stays optional (the tripwire catches worse
    drift).
12. **Data-only deploy activation (STAB-12), later.** Decide whether retrospective comparisons count toward the
    ≥30 / ≥14-day bar, then approve or decline the Agent OS §3 amendment once the bar is met.
