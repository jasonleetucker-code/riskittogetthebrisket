# CI failure matrix — 2026-08-20

**Lane:** CI reliability (`claude/ci-reliability-hardening`).
**Method:** every claim below is measured against the live GitHub Actions API
and the live issue list on 2026-08-20, not against screenshots or the previous
incident record.

**Headline, stated before the detail:** the seven named failure families are
**not seven defects**, and they are also not one. Four are correctly red or
already resolved and this lane changes none of them. What this lane found and
repaired is a different class the 2026-08-18 triage did not look at — **CI's own
side effects**: a verification workflow writing to `main` 42 times a day,
superseded automation still holding production credentials, and three gates that
render green while asserting nothing.

---

## 1. The seven named families

| # | Workflow | Live state | Class | This lane |
|---|---|---|---|---|
| 1 | **Bootstrap Sharp Records** | **0 green / 19 concluded.** Latest `32333756888` @ `72835abf`, step `Install units and populate the Sharp cohort` | `PRODUCT_DEFECT` — externally blocked | **Routed.** Guard only, §3.5 |
| 2 | **Verify Sharp Production Population** | Green on every run while recording `unverifiable_unauthenticated`; pushes to `main` every run; never binds to a deployed SHA | `CONFIG_OR_SECRET_DEFECT` + `WORKFLOW_DEFECT` | **Repaired**, §3.1–3.4 |
| 3 | **Retention health (read-only)** | 0 green / 8 ever. `32227648487` @ `4c208e5b`: `ok=7 stale=1`; `C1-RET-07` stale **2891.6 h** | `EXPECTED_ACTIONABLE_FAILURE` | **Untouched.** Correctly red |
| 4 | **Audit Rank-Form Curve Drift** | Failed `32114681240` @ `541e7bf8` on real drift (offense excess +49.5, IDP +100.5 vs threshold 25) | `EXPECTED_ACTIONABLE_FAILURE` | **Stays red.** Only its issue-tracking repaired, §3.6 |
| 5 | **PR Validation** | 2 failures in 60, **both real**. Zero in the newest 30 | working correctly | **Untouched.** One gap routed, §4 |
| 6 | **Scheduled Data Refresh** | **23 consecutive greens** since `32123775865` | resolved | **Untouched** |
| 7 | **E2E Safety Net** | Fails when Playwright reports `1 flaky` under the deliberate `failOnFlakyTests` policy | `FLAKY_OR_RACE` | **Another lane's.** Not duplicated |

### Detail on the four this lane does not repair

**Bootstrap Sharp Records.** On production, `*-ffpc-sharp.service` is
`Type=oneshot` with `TimeoutStartSec=1800`;
`deploy/bootstrap-sharp-records.sh::run_oneshot` calls a blocking
`systemctl start`, the unit burns ~29 min 53 s of CPU, systemd `SIGTERM`s it,
and the workflow exits 1. Diagnosed in `CI_INCIDENT_2026-08-18.md` §5 and
unchanged since. **Owner action.** Needs the production host.

**Retention health.** `C1-RET-07` identity-resolution reports last written
`identity_report_20260420T194828Z.json` — a collector dead ~4 months. The probe
reaches production, measures correctly, and refuses. **Owner action.**

> Correction to an intermediate finding: this workflow was flagged mid-audit as
> "stopped firing". **False alarm.** Its cron is `40 6 * * *`, GitHub delays it
> 35–57 minutes, and the check was made at 05:30 UTC — before that day's slot.
> Recorded so nobody re-hunts it. It is worth noting *why* it was plausible: a
> workflow that silently stops firing and one that is merely late look identical
> from the outside, which is the same indistinguishability §3.3 addresses.

**Audit Rank-Form Curve Drift.** The constants are still `65.4 / 0.910` and
`64.6 / 0.900`; the values the workflow printed (`67.4 / 0.875`, `63.4 / 0.834`)
have not been applied. ADR-008 makes that a human act — an automated patch that
also re-baselined its own guard would be green by construction. **Owner action.**

**E2E Safety Net.** Commit `1af1d2b3` (merged 2026-08-20 00:32) repaired the
readiness gate; PR #762 is open on the rotating-flake root cause. Two known
defects are **routed, not fixed here**: `e2e.yml` uses `npm install` for both
root and frontend while `pr-validation.yml` uses `npm ci`, so the E2E runner
ignores both lockfiles.

---

## 2. What the shared causes actually were

The 2026-08-18 record tested "is there one shared cause?" against those seven
failures and correctly answered no. Asked of the CI *system* rather than of that
day's red ticks, there are two, and both are about what CI does rather than what
it reports.

**A — CI writes to `main`, and that manufactures the drift the repo spends
effort bounding.** `verify-sharp-production.yml` committed and pushed on every
run because `checkedAt` is a timestamp. Measured over 24 hours: **42 of 66 bot
commits to `main`**, every one recording the same status, which has not changed
once in the file's recorded history. Each moves `main` under every open PR —
class-C drift under the repo's own HEAD FREEZE policy.

Worth being precise about the irony: this is a *consequence of the 2026-08-18
repair*. Before it, the commit step failed at exit 128 on every run, so nothing
was ever pushed. Fixing the step did exactly what it said and revealed that the
step should not have been running unconditionally in the first place.

**B — absent, skipped and unmeasurable all render as green.** Four distinct
mechanisms, one appearance:

| mechanism | where | rendered as |
|---|---|---|
| `exit 0` on missing secrets | `trigger-sharp-no-environment.yml:63` | success |
| job-level `if` skips the only job | `health-check.yml`, `smoke-test.yml` | neutral → success |
| a gate with no credential warns and exits 0 forever | `verify-sharp-production.yml` | success |
| a tracker that cannot find its own issue | `audit-rank-form-drift.yml`, `refit-hill-curves.yml` | duplicates, then silence |

---

## 3. Repairs

### 3.1 Four superseded Sharp workflows removed (~594 lines)

`check-sharp-production-now.yml`, `force-sharp-production-now.yml`,
`trigger-sharp-now-via-merge.yml`, `trigger-sharp-no-environment.yml`.

Two trigger **only** on `push` to their own file path — written to be fired by
editing the file — carry no `concurrency:` block, and `git push origin HEAD:main`.
All four hold production SSH secrets and/or `contents: write`. Their function is
served by `sharp-records-bootstrap.yml` (the action) and
`verify-sharp-production.yml` (the gate).

`trigger-sharp-no-environment.yml:63` was the confirmed unconditional-success
path. Guard: `tests/deploy/test_no_workflow_exits_green_on_missing_secrets.py`,
deliberately narrow — `exit 0` is used correctly in fourteen steps across this
repo, so it fires only on an `exit 0` reached from a branch whose *condition*
tests a secret-derived variable for emptiness.

> **Corrected during the audit:** `force-sharp-production-now.yml` was initially
> reported as able to "succeed having started nothing". It cannot — line 178
> gates on `BOOTSTRAP_CODE` / `FFPC_CODE`. It is removed as superseded
> credential-holding automation, not as a false green.

**Kept:** `data/ops/sharp-{force-production-live,merge-trigger-result,no-environment-result}.json`.
They are no longer written so they cause no churn, and they are cited as evidence —
`sharp-force-production-live.json` by `docs/claude-dispatch/V1_CLOSABILITY_QUEUE.json`
(a Lane 4 row) and all three by the 2026-08-04 audit registry. Deleting cited
evidence to tidy up is not in this lane's remit.

### 3.2 The Sharp gate grades this run, not the committed record

`Enforce healthy population` read `data/ops/sharp-production-smoke.json` from
disk. That file is tracked and survives between runs, so once the write became
conditional (§3.3) the gate would have graded a record written days earlier — a
stale `healthy` passing a run that measured nothing, and invisible in review
because the diff that arms it only *removes* a write.

The smoke step now writes its result twice, to two things that are not the same
kind of thing: `$RUNNER_TEMP/sharp-smoke-current.json` is this run's **evidence**
and is what the gate reads; the tracked file is a durable **record** and is never
a gate input. `RUNNER_TEMP` is indexed rather than defaulted, so a runner that
does not provide it fails loudly instead of grading a file in the working
directory.

### 3.3 The record records state, not one row per run

`scripts/sharp_smoke_record.py` owns the decision, in a module rather than a YAML
heredoc so it can be unit-tested — this is the decision that was quietly wrong 42
times a day.

Two fields, because one cannot answer both questions:

```
lastObservedOn   are we still checking?      advances daily
stateSince       how long has it been this?  advances on change
```

A write happens when the state changed **or** the day rolled over: ≤ 1 commit/day
instead of 42, and **0** when the workflow stops — which is itself the signal.
Commit-only-on-change was rejected precisely because it freezes the record and
makes a workflow that stopped firing indistinguishable from one reporting a
stable state (see the retention-health correction in §1). Every run still writes
its full result to `$GITHUB_STEP_SUMMARY`, in the run ledger, where a stale file
cannot fake it.

`stateFingerprint` covers `(status, cohort, ffpcMarket, lastError.type)` and
excludes every clock-derived field **by construction**. `measured` is an explicit
boolean and `cohort` / `ffpcMarket` stay `{}` when nothing was read — never
zeroed counters, because "0 qualified managers" and "we could not ask" are
opposite claims.

### 3.4 The unmeasurable gate is tracked, and has one tooth

The per-run disposition is unchanged: `::warning` and `exit 0`. Failing ~12× a
day for a credential CI was never issued is how a gate gets deleted, and
`test_unverifiable_is_reported_as_a_warning_not_a_pass_or_a_failure` still passes
unmodified.

But the cumulative claim differs from any single run's. Each run is honest; the
series is not — the workflow has shown a green tick through every run in its
recorded history while measuring nothing. So the finding goes to a tracking issue
that names the one action which fixes it (provision a token per
`_SELF_AUTHED_API_EXACT`) and drains itself on the first `healthy` run. Shape
copied from `e2e.yml`, including the `[bot]` suffix normalisation it paid for in
AUDIT F-23.

**The tooth:** `unverifiable_unauthenticated` *after* a run that did measure is a
credential **regression**, and that is red. Computable only because the record
carries `lastMeasuredOn` forward. It can only add a failure condition, so it
cannot manufacture a green.

### 3.5 Bootstrap's exit-status invariant, pinned — no behaviour change

`systemctl start --no-block` returns 0 when the job is *enqueued*. Switching to
it would leave the CPU burn and the `SIGTERM` exactly as they are and turn
Bootstrap Sharp Records 19/19 **green** with the production incident invisible.
It is an easy mistake to make in good faith, because `--no-block` **is** correct
two files over — `deploy/install-systemd-service.sh` uses it for these same units
and `tests/deploy/test_sharp_population_jobs.py` pins that. The difference is
what the caller claims: a deploy kicks a collector; this workflow's entire output
*is* the assertion that it finished.

The guard pins the invariant, not the flag: blocking `start`, **or** `--no-block`
followed by a completion poll. Proven by mutant — `--no-block` with a poll
**passes**, so the owner's real fix stays open.

### 3.6 The calibration trackers can find their own issues

The `calibration` label **did not exist** (verified against the live API today).
Run `32114681240` logged `could not add label: 'calibration' not found`, so
`gh issue create --label` failed, the fallback filed #898 unlabelled, and the
drift audit's dedup — which filtered on that label — could never find it again.
The close step matches on *title*, so the two halves of one tracker were keyed
differently and the half that files used the key that did not resolve.

Not hypothetical: `refit-hill-curves.yml` shares the label and had no dedup at
all. Its promotion request is open **twice** — #777 (2026-08-11) and #895
(2026-08-18), seven days apart, neither labelled.

Both workflows now create the label idempotently (the pattern
`scheduled-refresh.yml` already carries, comment included) and dedup on the exact
title. `refit-hill-curves.yml` still has **no auto-close**, deliberately and now
pinned: its issue is a promotion request awaiting a human, and silently closing
one is worse than leaving it open (ADR-008).

### 3.7 Unrun production checks fail loudly

`health-check.yml` (its **only** job) and `smoke-test.yml`'s production job gated
on `if: ${{ vars.PROD_PUBLIC_URL != '' }}`. A skipped job reports neutral, which
renders as success — so an unset or renamed variable would have retired the
always-on external check of production without a red tick.

**Latent, not live:** the variable is set today (`prod-e2e-smoke.yml` refuses when
it is empty and ran green at 04:53Z). This hardens against a configuration
regression. The condition is not deleted; it moves into a step that annotates and
exits 1 — which is what `prod-e2e-smoke.yml`, `intel-refresh.yml`,
`public-league-warmup.yml` and `deploy.yml` all already do. These two were the
stragglers.

---

## 4. Deliberately not done, and who owns it

| | Why | Owner |
|---|---|---|
| Rank-form constants (`67.4/0.875`, `63.4/0.834`) | ADR-008: a model may not rewrite production constants and re-baseline its own guard | owner |
| `dynasty-ffpc-sharp.service` CPU burn | Needs the production host; guessing a fix for a runaway service is what this lane must not produce | owner |
| `C1-RET-07` identity collector | Halted on the box since 2026-04-20 | owner |
| A credential for `/api/sharp/*` | Repository secret; now tracked by an issue that names the exact pattern | owner |
| **Branch-protection ruleset requiring `Validate PR`** | The scariest gap found and **not fixable by a PR**: a PR in `mergeable_state: dirty` never gets `refs/pull/N/merge`, so **zero check runs are scheduled** — which on the merge page reads identically to green | repo admin |
| Binding production verification to a deployed SHA | Needs a build-identifier endpoint in `server.py` **and** a deploy-time write in `deploy.yml`; `deploy.yml` is claim-blocked. `DEPLOY_CONCURRENCY_2026-08-20.md` §"The related gap" already records it | owner + Lane 5 |
| `npm install` → `npm ci` in `e2e.yml` | Real defect (the E2E runner ignores both lockfiles), but that file has an active lane and PR #762 open | E2E lane |
| Bootstrap trigger cadence (fires ~12×/day) | The 2026-08-18 record ruled on it explicitly; not reopened | owner |
| Piping `bootstrap-sharp-records.sh` from the runner | Correct diagnosis — the workflow runs the *production host's* copy, unlike `retention-health.yml` which pipes over stdin for exactly this reason — but it changes what executes on production, from a CI PR, while an incident on that unit is open | owner |
| A shared concurrency group for `main`-pushers | Removes **zero** false signals and adds one: `cancel-in-progress: true` creates a new false-not-run, and `false` reproduces the queue starvation `DEPLOY_CONCURRENCY_2026-08-20.md` documents. §3.1 and §3.3 remove the cause instead | — |
| Composite action / pip lockfile / two-pip-pattern unification | Touches `requirements*.txt` and `package.json` against five open dependabot PRs and a named custodial file | — |

---

## 5. Validation

```bash
pytest tests/deploy/ tests/ops/ -q          # 412 passed, 4 skipped
python3 -c "import yaml,glob; [yaml.safe_load(open(f)) for f in glob.glob('.github/workflows/*.yml')]"
ruff format --check . && ruff check .
python3 scripts/audit_status.py             # no drift
```

Every workflow change was additionally executed, not only parsed: the Python
heredocs were extracted from the YAML and run against a temp `RUNNER_TEMP`, and
the tracker steps against a `gh` stub. Results are in the commit messages.

**Mutation discipline.** Every guard was proven to fail against the change it
forbids. Two guards did **not** catch their mutant on the first attempt and were
strengthened:

* the fingerprint test folded `checkedAt` in and still passed — the fixtures had
  no `checkedAt` key at all, so `.get` returned `None` on both sides;
* the `[bot]`-normalisation test asserted a needle that could never match, because
  the shell escaping puts backslashes *inside* the bracket expression.

Both are the failure `test_sharp_smoke_commit_order.py` already documents — *a
guard that cannot fail is decoration* — hit again while writing guards against
it. Recorded rather than quietly fixed.

**Not claimed, pending a real run:** that the commit volume actually falls to
≤ 1/day; that the tracker opens once and comments rather than duplicating; that
`health-check.yml` fails loudly with `PROD_PUBLIC_URL` unset; that the next
weekly drift run comments on #898 instead of opening #899.

**Unprovable without production access:** anything about the FFPC collector's CPU
burn, whether the Sharp cohort is populated (no credential exists — that is the
point of §3.4), and whether the production host's copy of
`bootstrap-sharp-records.sh` matches `main`.

**No false-green mechanism was introduced.** No `continue-on-error`, no skip, no
weakened assertion, no swallowed exit code, no retry, no deleted test, and no
trigger removed from a live detector. Flaky retries added: **zero**.
