# Re-enabling the paused production verification workflows

**Status:** owner checklist. Nothing in this file has been executed. Both
workflows are still `disabled_manually`; this document enables nothing.

| workflow | GitHub state (read 2026-10-16) | paused since |
|---|---|---|
| `.github/workflows/v1-authenticated-verification.yml` ("V1 Authenticated Production Verification (ephemeral guest session)") | `disabled_manually` | 2026-10-08 07:51 UTC |
| `.github/workflows/prod-e2e-smoke.yml` ("Production E2E Smoke (public /league)") | `disabled_manually` | 2026-10-08 07:51 UTC |

Why they were paused: security incident 2026-10-08. This repository is
public, so its Actions logs and uploaded artifacts are public too, and a
failed prod-auth run's Playwright trace carried the guest-pass session cookie
(`jason_session`) plus private response bodies.

The fix itself (#1718, guest sessions bound to a pass identity, revocation
ends sessions) shipped in release train #1719. **Release train 4**
(`integration/train-4-2026-10-16`) adds the two units that gate re-enabling:

- **#1725** closes the remaining public-output leaks.
- **#1724** adds the production probes that prove the fix works.

Agent-OS-Receipt: `cdca1dca8385f70c0989302dece8d1bd4ce4843c`

### Precondition re-check, 2026-10-18 (read-only; nothing enabled)

| precondition | state | evidence |
|---|---|---|
| 0.1 train 4 merged | **met** | `15cbad9e42` "Merge pull request #1759 … integration/train-4-2026-10-16" is on `main` |
| 0.2 deployed | **met** | `GET https://chaseupside.com/api/status` → `build.commit` `24e218205e` (train 7, #1803), which contains `15cbad9e42` (`git merge-base --is-ancestor`) |
| 0.3 secrets / variables | unchanged by any repo change; not readable from a session | the workflow reads only the names in §0.3 — no new secret is needed |
| workflow state | both still `disabled_manually` | Actions API `list_workflows`, 2026-10-18 |

So the code side is complete and **exactly one admin step remains** — the
§2 owner actions, which change repository settings and therefore cannot be
taken from a PR:

```bash
gh workflow enable v1-authenticated-verification.yml
gh workflow run v1-authenticated-verification.yml -f suite=all -f league=dynasty_main -f pass_hours=2
# inspect per §3 and §4; only then:
gh workflow enable prod-e2e-smoke.yml
```

The stale reporter comment listed in §6 is corrected (it now describes the
v2 allowlisted report).

---

## 0. Preconditions (all four must be true)

1. Release train 4 is **merged** to `main`. It contains #1724 and #1725.
2. The `Deploy Production` run for that merge commit **succeeded**, and
   production `build.commit` equals it.
   - Reason: the census step runs `session_store.guest_session_census()` **on the
     box**. It imports the *deployed* `src/api/session_store.py`, and that
     function only exists once #1724 is deployed.
   - Reason: the revoke step calls the deployed `guest_passes.session_authority`.
   - If you run before the deploy, the census fails and is recorded as
     "unknown". The job then fails, because unknown is never a pass.
3. These secrets, variables and environment exist and are unchanged. Nothing new
   is needed; the workflow reads only these:
   - **Secrets:** `DEPLOY_SSH_PRIVATE_KEY`, `DEPLOY_KNOWN_HOSTS`, `DEPLOY_PORT`,
     `DEPLOY_HOST`, `DEPLOY_USER`. These are the same `DEPLOY_*` secrets
     `deploy.yml` uses. The job runs in the `production` environment.
   - **Variables:** `PROD_PUBLIC_URL` (required; there is no fallback),
     `PROD_APP_DIR` (default `/home/dynasty/trade-calculator`) and
     `PROD_SERVICE_NAME` (default `dynasty`).
   - `prod-e2e-smoke.yml` needs only `vars.PROD_PUBLIC_URL`. It uses no
     secrets.
4. Nobody else is mid-deploy. The verification job joins the `production-deploy`
   concurrency group (`cancel-in-progress: false`), so it queues behind a
   deploy instead of racing it.

## 1. What is now allowlisted (#1725)

Default deny: every producer that can reach a public log or artifact now
publishes only an allowlisted summary.

| producer | public sink | what it may publish now | owner |
|---|---|---|---|
| `scripts/verify_v1_authenticated.py` (API suite) | stdout (log) + `--report v1-auth-report.json` (artifact) | Only `public_verification_report` summaries: per check `id`, `row`, `status`, `denominator`, a code-authored `title`, and evidence keys from the script's `PUBLIC_EVIDENCE` allowlist with a declared kind. **`detail` is never published.** Withheld keys are counted in `evidenceWithheld`. A `<label>:crash` check publishes only the exception class name. The full report is written nowhere on the runner. | `scripts/public_verification_report.py` |
| `scripts/verify_lane4_production.py --mode remote --public-report lane4-remote.json` | stdout (log) + `lane4-remote.json` (artifact) | The same public summary schema (`public-verification-report/v1`). The workflow no longer uses `tee lane4-remote.txt`, and `lane4-remote.txt` is no longer uploaded. | same |
| workflow C8/C9 step | log | Only `C8/C9 free agent picked from the deployed board (name not logged)`. The player name is no longer echoed. | workflow |
| prod-auth Playwright suite | stdout (log) + `tests/e2e/prod-auth-results.json` (artifact) | Schema `prod-auth-safe-report/v2`. Per test: project, file, fixed title, status, duration, and an `errorClass` enum on failure (never the message), plus (since the V1 failure classifier) a closed-vocabulary `failureSignal` and a `startedAt` instant (see `docs/ops/V1_VERIFICATION_TAXONOMY.md`). Annotations appear only when `tests/e2e/prod-auth-annotation-allowlist.js` allows that type for that spec file and the value has the declared kind. `withheldCount` / `annotationsWithheld` count what was dropped. Cookie text is scrubbed. The only reporter is `prod-auth-safe-reporter.js`, with trace, screenshot and video all `off` (`tests/e2e/prod-auth.config.js`). | `tests/e2e/prod-auth-safe-reporter.js` + allowlist |
| `scripts/verify_v1_authenticated.py security-probe` / `security-summary` (#1724) | stdout (log), `security-acceptance.json` (artifact), job summary | Fixed keys only. Probe values are ints, bools or null. Census values are counts or bools. Check `detail` text is code-authored and interpolates only those ints and bools. | `build_security_summary` |
| `production-route-baselines.json` | artifact | Unchanged. Already classified safe: fixed-enum states, timings, byte counts, pathname only. Produced only on a manual `suite=baseline` run. | — |

Upload list (`Upload the reports` step), exactly:
`production-route-baselines.json`, `v1-auth-report.json`,
`security-acceptance.json`, `lane4-remote.json` and
`tests/e2e/prod-auth-results.json`.

Pinned by:
- `tests/ops/test_public_verification_reports.py` (it also runs the node test
  `tests/e2e/prod-auth-safe-reporter.test.js`);
- `tests/ops/test_security_acceptance_probes.py`;
- `tests/e2e/test_prod_auth_artifact_safety.py`. This one forbids uploading
  `test-results-prod-auth/`, an HTML report, a trace, a video or a screenshot.

`prod-e2e-smoke.yml` was **not changed** by #1725, which classified it safe:
- It runs only the anonymous `tests/e2e/specs/public-league.spec.js`.
- `tests/e2e/playwright.config.js` turns trace, screenshot and video `off`
  for any non-loopback `E2E_BASE_URL`.
- On failure it uploads only `tests/e2e/playwright-report/`, the HTML report
  of an anonymous public-page run.

It was paused as a precaution together with the authenticated workflow.

## 2. Owner actions, in order

Do these in a browser on GitHub. Equivalent `gh` commands are shown for
reference only.

1. **Enable the authenticated workflow:** GitHub → Actions → "V1 Authenticated
   Production Verification (ephemeral guest session)" → "…" → **Enable
   workflow**. (`gh workflow enable v1-authenticated-verification.yml`)
   - Once it is enabled, the `workflow_run` trigger runs it automatically
     after **every** successful `Deploy Production` on `main`. That is the
     "TEMP Week-1 proof bridge", which runs the security steps and the browser
     suite.
   - So enable it only after step 0.2 is true. Otherwise the next deploy
     triggers a run that can still pass but has not been inspected yet.
2. **Dispatch one manual run first** and inspect it before relying on the
   automatic runs: Actions → that workflow → **Run workflow** with
   `league=dynasty_main`, `suite=all`, `pass_hours=2`. Leave the baseline
   inputs at their defaults.
   (`gh workflow run v1-authenticated-verification.yml -f suite=all -f league=dynasty_main -f pass_hours=2`)
   - `pass_hours` must be a number ≥ 1. The mint step refuses anything else
     before it mints a pass.
3. Inspect the run (§3 and §4). Do not move on until both pass.
4. **Enable the smoke workflow:** Actions → "Production E2E Smoke (public
   /league)" → **Enable workflow**. (`gh workflow enable prod-e2e-smoke.yml`)
   - It then runs on cron `17 */4 * * *`. Optionally press **Run workflow**
     once to get an immediate observation.

## 3. What the first authenticated run must show — security acceptance (#1724)

Open the run's **job summary**. It shows a "Security acceptance — incident
2026-10-08-guest-session-cookie-exposure" table, and the artifact carries
`security-acceptance.json`. Required:

| check | must be | meaning |
|---|---|---|
| `SEC-REVOKE` | `pass` | `guest_passes.revoke(pass_id)` newly marked the pass **and** `session_authority(pass_id)` is false afterwards. Otherwise the revoke step itself fails the run. |
| `SEC-POST-REVOKE` | `pass` | The **same** session was probed twice. In the step immediately before the revoke it was accepted: `/api/auth/status` HTTP 200 with `authenticated:true`, and `GET /api/user/state` HTTP 200. After the revoke it was rejected: `/api/auth/status` HTTP 200 with `authenticated:false`, and `GET /api/user/state` **HTTP 401**. If the pre-revoke control was not accepted, the result is `inconclusive`, and that **fails** the run, because a session that died for another reason is not revoke proof. The post-login probe is reported for context only. |
| `SEC-SCHEMA` | `pass` | `schemaHasGuestColumns: true`: the session store carries `expires_at_epoch` and `guest_pass_id`. |
| `SEC-LEGACY` | `pass` | `guestSessionsMissingPassIdentity` is an **observed 0**. |
| `SEC-INACTIVE-PASS` | `pass` | `guestSessionsPassRevoked` and `guestSessionsLiveWithInactivePass` are both an **observed 0**. |
| `verdict` | `pass` | Any other value makes `security_exit` 2, and the "Fail the job on API/lane4/browser verdicts" step fails the job. |

- `null` in any census field means **unknown**, and unknown fails. Missing is
  never zero. Examples: an unreadable store, or a census step that failed and
  left no file.
- `guestSessionsExpiredAwaitingCleanup` is informational. Rows past their own
  expiry are refused at request time and purged later.
- `passStoreReadable` must be `true`.
- The one deliberate definition #1724 flags for the owner: a guest session
  whose pass **expired**, but whose own row is also past expiry, is counted
  in `guestSessionsExpiredAwaitingCleanup`, not as a failure. A session on a
  **revoked** pass always fails. To make expired rows fail as well, add the
  key to the `must_be_zero(...)` call in
  `scripts/verify_v1_authenticated.py::check_session_census`. That is an owner
  decision; it is not made here.

The other suites keep their existing meaning in the verdict step:
- exit 0 is pass;
- exit 2 is fail, and fails the job;
- exit 3 means the suite proved nothing. It is visible but does not fail
  the job.

On a `workflow_run` (automatic) run, the API and Lane 4 suites are skipped by
design. Only the browser suite and the security steps run.

## 4. How to confirm nothing private reached a public surface

Do this on the first manual run, and again on the first automatic run.

1. **Download the artifact** (`v1-authenticated-report`, retention 30 days):
   `gh run download <run-id> -n v1-authenticated-report -D /tmp/v1-report`
   Expected files: `v1-auth-report.json`, `lane4-remote.json`,
   `security-acceptance.json`, `tests/e2e/prod-auth-results.json`. A
   baseline run also has `production-route-baselines.json`. **Any other file
   is a finding.**
2. **Download the log:** `gh run view <run-id> --log > /tmp/v1-run.log`
3. Scan both. **Every command below must print nothing:**
   ```bash
   grep -rniE 'jason_session=[^\[]|set-cookie|"token"|password|"cookie"' /tmp/v1-report /tmp/v1-run.log
   grep -rniE 'ownerId|owner_id|rosterId|"detail"|sample_missing|offenders|nulledDespiteVoters|"standard"|"aggressive"|"clearing"' /tmp/v1-report/v1-auth-report.json /tmp/v1-report/lane4-remote.json
   grep -niE 'C8/C9 free agent: ' /tmp/v1-run.log
   ```
   - The guest-pass token and session cookie are `::add-mask::`ed, so in the
     log they appear as `***`. Any unmasked long opaque string next to "token"
     or "cookie" is a finding.
   - `jason_session=[REDACTED]` is the reporter's scrub marker. It is expected
     only if a spec tried to emit cookie text, and in that case it is itself
     worth reading.
4. **Check the schemas:**
   - `v1-auth-report.json` and `lane4-remote.json` both have
     `"schema": "public-verification-report/v1"`. Each check has only the keys
     `id`, `row`, `status`, `denominator`, `title`, `evidence` and
     `evidenceWithheld`. No check has a `detail` key.
   - `prod-auth-results.json` has `"schema": "prod-auth-safe-report/v2"` and
     `"sanitized": true`. A failing test carries `errorClass`
     (`assertion` / `timeout` / `error`) and **no message**. Annotation
     descriptions are only booleans, counts, HTTP statuses, years, enum
     states, league keys or fixed code strings. A player, team or manager name,
     or a Sleeper id, is a finding.
   - `security-acceptance.json`: every probe and census value is an int, a
     bool or `null`.
5. Check the browser step's log lines. Each line is
   `ok|FAIL|skip [project] file › title (ms)`, optionally followed by
   `[errorClass]`, plus one summary line. A Playwright `Received:` / `Expected:`
   block, a call log or a code frame is a finding: it would mean a second
   reporter was added.

If any check above finds something, go to §5 immediately.

## 5. Rollback

1. **Stop new runs:** Actions → workflow → "…" → **Disable workflow**
   (`gh workflow disable v1-authenticated-verification.yml`, and likewise for
   `prod-e2e-smoke.yml`). Disabling changes no code and is the first move.
2. **Remove a public leak:** delete the affected artifact, or the whole run,
   from the run page (`gh run delete <run-id>`). A log cannot be edited, only
   deleted with its run.
3. **Kill any live verification session.** The pass is revoked in an
   `always()` step. If that step failed (red "Revoke failed"), revoke the pass
   named in the log (`Minted guest pass id=<n>`) through the admin UI
   (`POST /api/admin/guest-pass/<n>/revoke`). Since #1718, revocation ends
   the sessions that pass created. Pass ids are not secrets.
4. **Code:** reverting #1724 returns the workflow to revoke-only, with no
   post-probe and no census, and leaves #1718's fix intact. Reverting #1725
   brings back the leaks this checklist exists to prevent. **Do not revert
   #1725 to "fix" a run; disable the workflow instead.**

## 6. Known gaps (recorded, not fixed here)

- ~~`tests/e2e/prod-auth.config.js`'s reporter comment still says the safe
  report keeps "every annotation … and the FIRST LINE of any failure".~~
  Fixed 2026-10-18: the comment now describes the v2 allowlisted report.
- Prod-auth specs other than the eight #1725 converted keep their existing
  annotations only where those were already statuses, counts or fixed states.
  Anything else is withheld and counted, not published. A new prod-auth spec
  publishes no annotations until it is added to
  `tests/e2e/prod-auth-annotation-allowlist.js`.
- The `workflow_run` trigger is labelled "TEMP Week-1 proof bridge" in the
  workflow, to be removed once W1-30 evidence is recorded. Removing it is a
  separate decision, and re-enabling does not settle it.
- The census needs the deployed code. A run against an older production
  build reports the census as unknown and fails. That is correct, not a
  flake.
- **First automatic run, 2026-10-19 (run 39221318435, deployed `b08f7230d1`):
  `SEC-POST-REVOKE` was inconclusive because the session died mid-suite.**
  - Production's public `/api/status` showed `build.process_started_at`
    `2026-10-19T08:42:49Z` on the same commit. So the backend restarted
    about 28 minutes into the suite; it was not a deploy.
  - Before the restart, several specs hit 45 s timeouts on `/api/auth/status`.
  - On restart, `session_store.hydrate` also applied
    `PRIVATE_APP_ALLOWED_USERNAMES` to guest rows. The guest username `guest`
    is never on that list, so every live guest session was deleted (census
    `guestSessions=0`).
  - Fixed on `claude/v1-verification-session-survival`:
    - a bounded guest row now survives the restart, and its pass decides
      whether it is still valid;
    - an unreadable pass store refuses the request but no longer ends the
      session;
    - the workflow waits (bounded) for a warm backend and reports a mid-run
      restart;
    - the safe reporter's `errorClass` strips ANSI colour before it
      classifies. Playwright colours value-matcher failures (`toBe` /
      `toEqual` / `toContain`), so the reporter had been publishing them as
      `error` rather than `assertion`.
  - Public evidence does not say why the backend restarted. The box's
    `journalctl -u dynasty -u dynasty-healthcheck` and its OOM log for
    08:36–08:43 UTC would.
