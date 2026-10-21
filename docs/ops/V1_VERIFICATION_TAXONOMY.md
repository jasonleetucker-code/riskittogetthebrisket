# V1 authenticated verification: failure causes, taxonomy, concurrency design

**Status:** analysis + report-only tooling are implemented in this PR. Anything that changes a
required gate or release policy is **drafted only** in section 5 and needs owner approval; none of it
is applied. Product authority is unchanged (`docs/EXECUTION_PLAN.md` governs what is authorized).

**Scope of evidence:** the 40 most recent runs of `v1-authenticated-verification.yml`
(2026-10-06 .. 2026-10-21, `gh run list` / `gh run view --log` / job annotations, all read-only), the
60 most recent `Deploy Production` runs, and the repository's own fix commits. Run ids are real.

## 1. What actually failed

Window 2026-10-19 08:14Z .. 2026-10-21 12:28Z: **15 failed**, 3 passed, 4 cancelled, 8 skipped
(skipped = the triggering Deploy Production did not succeed on `main`; not a failure).

| # | Runs | Failing specs | Root cause | Evidence | Class |
|---|---|---|---|---|---|
| A | 39221318435 | 43 failures; 22 mobile specs failed in 479-572 ms after ~27.6 min | The guest session was lost when the backend process restarted at 08:42:49Z on the same commit (not a deploy). `session_store.hydrate` applied the admin allowlist to guest rows and deleted them. | Fix commit `b66d4369e` reads the cause from production's public `/api/status` (`build.process_started_at`); the log shows the 0.5 s burst. A stall began ~08:28Z and the backend restarted at 08:42:49Z (watchdog 3-strike restart is the documented candidate; `prod-restart-diagnostics.yml` was written for it) | `auth_session` (consequence of a restart) |
| B | 39235281344, 39246683950, 39264005779, 39286923273, 39297875229, 39311556615 | The **same 12 specs** every time (draft-capital, `/arbitrage` x2, trade-stack, War Room, pick-lifecycle, train2 Droppable; both viewports) | Specs lagged deliberate product changes (draft-capital per-class budget, `/arbitrage` "tools first" layout, TC-D1 tray). Deterministic: identical failures across six different deploys over 11 hours. | `b66d4369e` "prod-auth specs brought to approved current behaviour" | `product_assertion` (spec/product skew) |
| C | 39345164050, 39352593915, 39366890899 | `/arbitrage` scan + research-panel, both viewports (31.5 s / 21.5 s) | A hydration race **in the spec**: the click landed on server-rendered markup before React attached `onClick`; the next assertion ran out its 30 s / 20 s budget. | `251d913d2` names runs 39311556615 and 39345164050 and reproduces it with delayed chunks | `product_assertion` by reporter; actually a spec race (see the classifier note below) |
| C2 | 39352593915 (same run) | mobile game-day-median-race, team-switch, 2 x 180 s timeouts in `w1-16-game-day` | **Not determined.** Backend was warm, desktop passed, no restart in the run. No evidence in the sanitized log separates a UI fault from a data-window fault. | none | `unknown` |
| D | 39380287586, 39397865866 | v1-111 premium rankings (both viewports), v1-62 sharp tracker (desktop), 4-8 s | The product markup was correct: #1849 added a visually hidden disclosure `<button>` whose text leaked into `innerText`, so the spec parsed `"Source breakdown for X1"` as NaN and a text match hit two nodes. | `4d13b170d` cites run 39380287586 | `product_assertion` (spec maintenance) |
| E | 39457047208 (desktop), 39552411042 (mobile), and the mobile case inside 39561535837 | `v1-123-public-league-matrix` ("mobile League tabs"), 12-17 s | **Not determined.** Intermittent: green in 39411707779, 39472497541, 39498005341. Fails early in a 13-tab loop with an assertion (not a 20 s budget). The sanitized reporter withholds which of five assertions fired (HTTP >= 400, "Section unavailable", tab mismatch, empty body, missing heading). | none; this is the gap `failureSignal` closes | `unknown` today |
| F | 39561535837 | Desktop: Sharp Tracker 91 s timeout, three `w1-12-public-pregame` failures (64 s, 64 s, 180 s) | A backend stall, then a restart. The first three failures (07:48:35-07:52:17) **precede** the restart at 07:53:55Z by 3-6 minutes; only the Home-card test (07:52:17-07:55:17) contains it. Mobile passed the same specs at 08:00. The same stall-then-restart shape as run A. | Restart instants come from `process_started_at` (07:17:42Z -> 07:53:55Z), test times from the log's own timestamps | `backend_timeout` (restart is a consequence, not the cause) |

Counts: B 6 + A 1 + C 3 + D 2 + E 2 (+1 inside F) + F 1 = 15 failed runs. Seven distinct causes; five are
test/spec maintenance (B, C, D) or unknown (C2, E), two are production availability (A, F).

### Cancellations (4) and skips (8): not product failures

All four cancellations (39592500560, 39545078157, 39433335744, 39401129952) have **no log** and carry one
GitHub annotation: `Canceling since a higher priority waiting request for production-deploy exists`.
They sat pending for 12-41 minutes in the `production-deploy` group and were displaced by a newer
pending request (a newer deploy, in at least 39592500560: Deploy 39593954750 was created 11:42:35Z, the
V1 was cancelled 11:42:36Z). No verification of the deploy they were for ever ran.

### Wrong deployed revision (queue skew)

`workflow_run` V1 checks out the **triggering deploy's** SHA but runs against **whatever production serves
when the job finally starts**. Queue waits of 66-86 minutes behind the next deploy happen:

| Run | Spec SHA (from its log) | Queued | Production process started | Reading |
|---|---|---|---|---|
| 39552411042 | `85ee0562` | 86 min | 07:17:42Z, i.e. the *next* deploy `9e3c52fd` | specs from one revision, product from another |
| 39472497541 | `52769c7b` | 66 min | 19:11:57Z, i.e. deploy 39467914112 (`c2b44022`) | **passed**, but verified a different revision than it was named for |

Only the 11 runs whose logs carry `process_started_at` can be checked this way (older runs predate the
instrumentation); two of the 11 show the skew. Nothing in the workflow compared the served commit to the spec commit, although
`/api/status` publishes `build.commit` and the deploy's own smoke test already compares it.

### Not causes (checked)

* **Playwright browser download**: run 39561535837's log shows `getaddrinfo ENOTFOUND
  playwright.download.prss.microsoft.com` and then a successful download from `cdn.playwright.dev`. A
  recovered mirror fallback, not a failure.
* **Auth vs guest**: login and both security controls succeeded in every run that reached the browser
  suite except A (session lost mid-run).
* **Backend restart as a blanket explanation**: 10 of the 11 runs with restart instrumentation report
  `backend restart during run: none`. Only F has a mid-run restart, and only one of its failures
  contains it. (Run A's restart is established from its fix commit, not from run-log instrumentation.)

## 2. What was added to make this diagnosable

* `tests/e2e/prod-auth-safe-reporter.js` publishes two extra fields per test: `failureSignal`, one word
  from a closed 11-word vocabulary derived from the message (never the message), and `startedAt`.
  Before this, `errorClass: assertion` covered both "value wrong" and "UI never appeared in 60 s": F's
  three 64 s failures were published as assertions.
* `scripts/v1_failure_classifier.py` maps a run to nine categories with a confidence and fixed
  evidence codes. **Report-only**: it never changes a verdict and `unknown` is a valid answer.

| Category | Needs, at minimum |
|---|---|
| `product_assertion` | an assertion that did not run out a clock; high if the same test failed in the previous run |
| `auth_session` | a *received* 401/403, or a burst of >= 3 sub-2 s errors **and** a pre-revoke control showing the session already gone |
| `backend_timeout` | a 5xx / network / API-request signal, an API-contract test timing out, a timeout cluster with one, or a restart instant **inside** that test |
| `frontend_timeout` | a clock ran out, no API timeout in the run, backend healthy afterwards (low confidence, by design) |
| `browser_infra` | launch failure, closed/crashed browser, or the browser step dying before any test reported |
| `deployment_revision_mismatch` | served `build.commit` differs from the spec commit (before or after the suite) |
| `resource_exhaustion` | out-of-memory signal, or runner OOM/disk pressure reported |
| `cancellation` | job annotation (`classify_run_record`) |
| `unknown` | anything else |

Redaction: output is closed vocabularies, SHAs, ISO instants, counts and the fixed spec titles the
reporter already published. Unknown keys and wrong-kind values are dropped; any string containing the
session cookie/token or `jason_session=` is replaced. Pinned by `tests/ops/test_v1_failure_classifier.py`
(hostile messages, titles and env values) and the existing artifact allowlist test, which now lists
`v1-failure-classification.json`.

Run on the real logs, the classifier reproduces the hand analysis of F: the Sharp Tracker and the first
two pregame failures are `backend_timeout` (medium) with `restart_followed_this_failure`, the third is
`backend_timeout` (high) with `backend_restart_instant_inside_test`, and the mobile League-tabs failure
stays a medium `product_assertion` rather than being blamed on the restart.

## 3. Verification taxonomy

Four labels, each with the evidence that earns it. A higher label never follows from a lower one.

| Label | Earned by | Proves | Does **not** prove |
|---|---|---|---|
| **deployed** | `Deploy Production` deploy job finished for SHA *S* | the box was told to run *S* | that it is serving *S*, or that it works |
| **smoke passed** | the deploy's post-deploy smoke test: public endpoints 200, `/api/status` `build.commit == S`, artifact/backend identity | production was reachable and identified as *S* at that moment | any authenticated flow, any UI journey, data correctness |
| **authenticated verification passed** | a V1 run that (1) is green, (2) served `build.commit` equals the spec SHA before and after, (3) saw no backend restart, (4) passed the security acceptance (post-revocation rejection) | guest-session journeys and the browser specs behave on revision *S*. `v1-failure-classification.json` states this as `authenticatedVerification.level == authenticated_verification_passed` | admin surfaces (no admin credential exists here); on `workflow_run` only the **browser** suite and security acceptance run, the API and Lane-4 suites run on manual dispatch only |
| **independently verified** | an attestation by a party other than the implementer and other than the CI run: reviewer or owner, naming the SHA, the evidence, the time | that someone who could reject the claim checked it | it is never produced by a green workflow |

`authenticatedVerification.level` has two more honest values: `authenticated_checks_passed_unattributed`
(green, but the revision or restart state is unknown, e.g. run 39472497541) and `not_established`.
Mapping to the Agent OS ladder (`docs/AGENT_OPERATING_SYSTEM.md` section 4): DEPLOYED = deployed +
smoke; VERIFIED needs authenticated verification passed on the right revision, plus independent
verification wherever the contract says "independently VERIFIED". A cancelled, skipped, mismatched or
restart-interrupted V1 earns nothing above smoke.

## 4. Browser load on production, from existing logs only

No request was sent to production for this. Inputs: per-test timestamps in 18 logs, spec source.

* **Concurrency is 1.** `workers: 1`, desktop project then mobile project, one Chromium at a time. Peak
  = one page + its XHRs; it is a serial stream, not a burst.
* **Duration:** first-to-last test result 10.5-14.6 min on green runs (median 14.0), 11.9-29.3 min on red
  ones (median of the 15 red ~14.7; the 29.3 and 23.0 minute runs are A and F). 100-117 of 125-134 tests
execute per run.
* **Frequency:** 9 executed browser runs on 2026-10-20 (about 2.1 browser-hours of single-stream load
  that day); 7 more on the 19th from 08:14Z. Each deploy triggers one, and 11 of the last 60 deploys
  (18%) were DLF refresh commits.
* **Weight is in a few endpoints, not in page count.** Twelve tests are ~40% of test time (median ms
  across runs): War Room 65 s desktop / 32 s mobile, Sharp Roster Percentage 41 s, `/arbitrage` scan 31 s
  per viewport, `POST /api/trade/finder` 16-18 s (max 79 s), train2 verdicts 24 s, trade-stack 17 s.
  Those are server-computed. Static count: 54 `goto` call sites in 29 specs (the League matrix loops
  13 tabs), 11 direct API call sites; XHR fan-out per page is **not in the logs**, so a request-rate
  estimate is unavailable.
* **Overlap with instability (correlation only).** Both observed stalls (2026-10-19 ~08:28-08:42, run A;
  2026-10-21 ~07:48-07:53, run F) began 6-14 minutes into a V1 browser run, within the heavy
  Sharp / trade tests. Nine browser runs on 2026-10-20 saw no restart. That does **not** show V1 load
  caused either stall; the baseline stall rate with no V1 running is unknown. To settle it, run
  `prod-restart-diagnostics.yml` (read-only, count-only) for 2026-10-21 07:40-08:00 and compare against a
  quiet window; do not add load to find out.

## 5. Concurrency redesign: DRAFT, not applied

### Why the current shape fails

`Deploy Production` (workflow-level `production-deploy`) and the V1 **job** (also `production-deploy`)
share a group that holds one running and one pending member. Deploys last a median of 90 minutes
(p90 130; this includes queueing). So:

1. A V1 that has to wait is the pending member and is cancelled by the next arrival (4 times).
2. A V1 that waits 66-86 minutes runs against a newer deploy (queue skew, above).
3. 18% of deploys are DLF refresh commits. They touch `CSVs/site_raw/*.csv`, which is not in
   `deploy.yml`'s `paths-ignore` (only `data/**` and `exports/**` are), so each one runs the 120-minute
   validate job and a deploy, occupies the group, and pushes real deploys and V1s behind it.

### Target properties and how each is met

| Property | Mechanism | Gate / policy change? |
|---|---|---|
| Deploy stays serialized | `deploy.yml` unchanged: group `production-deploy`, `cancel-in-progress: false` | no |
| Commit-to-verification attribution | `run-name` carries deploy run id + SHA; V1 records served `build.commit` before/after, restart instant, queue wait; classification JSON ties them together | no (**implemented here**, report-only) |
| Real regressions stay blocking | a failure with a matching revision and no restart inside it stays red; the classifier cannot turn red green | no |
| One V1 per deployment window | V1 leaves `production-deploy` for its own group `production-verify` (`cancel-in-progress: false`); at most the newest pending V1 survives and the displaced one is *named* as superseded rather than silently cancelled | **yes** (OA-1) |
| A V1 verifies the revision it names | pre-flight compares served `build.commit` to the spec SHA; if production already runs a newer descendant the run is `superseded` (neutral, with the superseding SHA), if it is a non-descendant it is `mismatch` | **yes** (OA-2) |
| Data-only refreshes do not displace code verification | data-only deploys get a separate lower-priority group `production-verify-data`; and/or `CSVs/site_raw/**` joins `paths-ignore` | **yes** (OA-3) |
| In-flight verification is not poisoned by a restart | tests whose interval contains a restart are reported `inconclusive` (not red) | **yes** (OA-4) |

### Draft (documentation only; do not copy into `.github/workflows` without OA-1/2)

```yaml
# v1-authenticated-verification.yml -- DRAFT
jobs:
  plan:                       # no concurrency group: runs at once, cannot displace anything
    runs-on: ubuntu-latest
    timeout-minutes: 5
    outputs:
      verdict: ${{ steps.plan.outputs.verdict }}         # verify | superseded | mismatch
      change_class: ${{ steps.plan.outputs.change_class }} # code | data_only
    steps:
      - uses: actions/checkout@v7
        with: { fetch-depth: 0, ref: <deploy head_sha> }
      - id: plan
        run: |
          # change_class: reuse scripts/check_release_candidate.py classes (A/B inert|source, C data)
          # verdict: GET /api/status build.commit vs EXPECTED; if a newer successful main deploy
          #          exists, verdict=superseded and name it in the step summary.
  v1-authenticated:
    needs: plan
    if: needs.plan.outputs.verdict == 'verify'
    concurrency:
      group: production-verify-${{ needs.plan.outputs.change_class }}   # NOT production-deploy
      cancel-in-progress: false
    # ... existing steps; the revision pre-flight repeats at start and end of the suite.
```

Trade-off of leaving the deploy group: V1 could then overlap a deploy's restart. The pre-flight check and
the restart-overlap rule are what replace the serialization, and they are only as good as
`build.commit`/`process_started_at`. An alternative that keeps one group but removes the skew: make V1
exit immediately (neutral) when a newer deploy is pending or running, instead of waiting behind it.

### OWNER APPROVAL REQUIRED (nothing below is applied by this PR)

* **OA-1, own concurrency group for V1.** Changes `tests/deploy/test_production_deploy_concurrency.py::
  test_v1_verification_serialises_at_job_level`, which pins V1 in `production-deploy`. Weakens
  deploy/verification mutual exclusion in exchange for removing displacement.
* **OA-2, superseded V1 as neutral.** Today every successful deploy is meant to be verified; this would
  let deploy *N* rely on deploy *N+1*'s verification. That is a change to what "verified" means for *N*.
  Recommendation: record `superseded_by` and count *N* as **not verified** in any coverage ledger.
* **OA-3, deploy `paths-ignore` for `CSVs/site_raw/**`.** A release-policy change to what triggers a
  production deploy. Unverified here: whether production consumes the committed CSVs directly (the box
  timers that produce them already hold the data). Needs the owner's call before anyone touches it.
* **OA-4, `inconclusive` for restart-overlapped tests.** Turns some red results neutral. The repo's
  config forbids retries so a flake cannot launder into a pass; this would be an exception and needs the
  same explicit decision. Recommendation: neutral only when the overlap is proven by the restart instant
  and a clean re-run of exactly those specs passes.
* **OA-5, making a revision mismatch fail the job.** Stricter, not weaker, but it can turn runs red that
  are green today (e.g. 39472497541). This PR only emits a `::warning`.

### Not changed by this PR

Required gates, `timeout-minutes: 50`, the job's concurrency group, the verdict step, the security
acceptance step, the deploy workflow, release policy, `docs/EXECUTION_PLAN.md`, `docs/WORK_CLAIMS.md`,
`docs/OWNER_REQUESTED_TODO.md`.

## 6. Open items

* Run E and C2 stay `unknown` until a run is made with `failureSignal` in place. The reporter now
  publishes it; the next occurrence will classify itself.
* The login step does not record its HTTP status, so a failed login classifies as `unknown`
  (`login_failed_status_not_captured`) rather than guessing "backend down".
* Restart cause is not established for A or F; use `prod-restart-diagnostics.yml` on those windows.
* A coverage ledger (deploy SHA -> V1 verdict or "none") is the natural next tool once run-names carry
  the deploy SHA; not built here.
