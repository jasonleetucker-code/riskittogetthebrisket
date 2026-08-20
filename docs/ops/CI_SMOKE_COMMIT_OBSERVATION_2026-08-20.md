# #948 — the smoke-commit reduction is an OBSERVATION, not a merge claim

**#948 merged `9e83509607736f0419dddf3ac00da4110b569f6b`, 2026-08-20 ~07:45 UTC.**
Integration record, opened at merge.

#948's design intent is that `verify-sharp-production.yml` writes
`data/ops/sharp-production-smoke.json` **on state change or day rollover** rather
than once per run, taking `main` from tens of bot commits a day to ≤ 1.

**That result is not claimed here, and merging did not establish it.** A design
that should reduce commits and a measured reduction are different statements, and
the PR itself said so ("Not claimed, pending a real run"). This file exists so the
later measurement has a fixed baseline to be measured against, instead of being
recalled approximately.

## Baseline — measured at merge, before any post-merge run

Window: **2026-08-19T07:45Z → 2026-08-20T07:45Z** (the 24 h ending at merge).
Counted on `origin/main` by commit subject `chore(ops): record Sharp production smoke`.

| quantity | value |
|---|---|
| smoke commits in the 24 h window | **48** |
| first / last in window | 2026-08-19T09:45:09Z / 2026-08-20T07:15:09Z |
| mean interval | ~27 min |
| design target after #948 | **≤ 1 / day** |

Reproduce exactly:

```bash
git log origin/main --since="2026-08-19T07:45:00Z" --until="2026-08-20T07:45:00Z" \
  --pretty='%cI %s' | grep -c "record Sharp production smoke"
```

(#948's own audit reported 42 of 66 bot commits over its 24 h window. The two
numbers are independent measurements over different windows and agree in
magnitude; neither supersedes the other.)

## What the follow-up must establish

Not "the number went down" — that is also what a **broken or disabled workflow**
looks like, and #948 deliberately made silence meaningful (0 commits is the signal
that the workflow stopped). So the observation needs both halves:

1. **Volume fell** — re-run the command above over a full post-merge 24 h window.
2. **The workflow still ran** — `verify-sharp-production.yml` runs are present and
   green across that window, and `lastObservedOn` in
   `data/ops/sharp-production-smoke.json` advanced even on days the file was not
   committed. Volume alone cannot distinguish success from the workflow dying.

Second half first if they disagree. A quiet workflow is not a fixed one — the same
distinction §7 of the #946 closure record draws between *unverifiable* and *passing*.

## Status

`OBSERVATION OPEN` — earliest meaningful read is **2026-08-21T07:45Z**.
Nothing about the ≤ 1/day result may be reported as achieved before then.

---

## First post-merge run — 2026-08-20T07:40Z, `Verify Sharp Production Population` run `32345039816`

Ran on the merge commit itself and completed **success**. It wrote **one** commit,
`65bfca4d2`.

**That one commit is expected and is not a failure of the design.** The tracked
record moved from schema 1 to `schema: 2`, so the `stateFingerprint` necessarily
differs from the previous record — a genuine state change, which is precisely the
condition #948 says must write. Reading "it committed again" as "the fix did not
work" would be wrong, and is the reason this is recorded now rather than
reconstructed later.

The claim under test is therefore sharper than "fewer commits": **the *second* and
subsequent same-state runs must write nothing.**

### What the record itself already demonstrates, in production

The post-merge `data/ops/sharp-production-smoke.json` on `main`:

```json
"status": "unverifiable_unauthenticated",
"measured": false,
"cohort": {},
"credentialRegression": false,
"lastError": {"type": "Unauthenticated",
              "message": "401 from https://chaseupside.com/api/sharp/cohort"},
"lastObservedOn": "2026-08-20",
"stateSince":     "2026-08-20T07:40:06.649789+00:00",
"lastRun": {"deployConclusion": "pending",
            "deployHeadSha": "9e83509607736f0419dddf3ac00da4110b569f6b"}
```

Four of the properties Integration verified by mutation before merge are now
observed **live**, which is stronger evidence than the mutations alone:

| property | live evidence |
|---|---|
| unmeasurable reported as UNVERIFIABLE, never healthy | `status: unverifiable_unauthenticated`, `measured: false` |
| the 401 is not turned into success, and no cohort data is fabricated | `lastError` names the 401 verbatim; `cohort: {}` |
| enqueue/pending is not converted into completion | `deployConclusion: "pending"`, recorded as pending |
| `lastObservedOn` and `stateSince` are distinct concepts, both populated | both present, answering *still checking* and *how long* separately |

`credentialRegression: false` shows the regression tooth is wired and not
misfiring: the record has never held a measured cohort, so losing one is not being
claimed.

### Status

`OBSERVATION OPEN`, one data point in. Next checkpoint: the following run of
`verify-sharp-production.yml` must leave `data/ops/sharp-production-smoke.json`
byte-identical and produce **no** commit. Full-window read still due
2026-08-21T07:45Z.

---

## Checkpoint 2026-08-20T08:58Z — the commit suppression works; a different write does not

Window: **07:40:12Z → 08:58:24Z** (78 min), starting from the first post-merge
write `65bfca4d2`.

### The claim under test: PASSES, at this scale

| quantity | value |
|---|---|
| smoke commits written | **0** |
| `verify-sharp-production.yml` runs in the window | **3** — `32348365941`, `32348564167`, `32350502359` |
| their conclusions | **success, success, success** |
| expected at the pre-merge rate (~27 min mean) | ~3 |

**Both halves hold.** Volume fell to zero *and* the workflow demonstrably kept
running green — so this is suppression, not the silence of a dead workflow, which
is the distinction that makes the number mean anything.

The mechanism is visible in the run's own environment: run `32350502359` carried
`STATE_SINCE: 2026-08-20T07:40:06.649789+00:00` — the timestamp written by the
*first* post-merge run, carried forward unchanged across three subsequent runs.
The state is being read from the tracked record, recognised as identical, and not
rewritten. `LAST_MEASURED_ON:` is empty, which is honest: it has never measured.

The warning fires every run and is not suppressed:

> `##[warning]/api/sharp/* requires a session and this workflow holds no credential, so population health was NOT measured.`

**This does not yet establish the ≤ 1/day result.** 78 minutes is not a day, and
the day-rollover write has not been exercised. Full-window read still due
**2026-08-21T07:45Z**.

### DEFECT FOUND — the tracker duplicates, one issue per run

The commit churn is gone. **An issue churn replaced it, in a different medium.**

| issue | created |
|---|---|
| #951 | 07:40:12Z |
| #953 | 08:21:20Z |
| #955 | 08:25:44Z |
| #957 | 08:47:10Z |

Four **open, identical** issues — same title, same author (`github-actions`), same
`sharp-unverifiable` label — **one per run, 1:1**. At the observed rate that is
roughly **85 issues/day**, against the ~48 commits/day it removed.

This is precisely the outcome #948 listed as unproven — *"that the tracker opens
once and comments rather than duplicating"* — and it is now measured as **failing**.
It is also the F-23 failure mode the step's own comment cites (*"pinning one of
them is what left 14 undrained trackers behind in `e2e.yml`"*), reproduced by the
code written to prevent it.

**What is established about the cause, and what is not:**

* The lookup **did not error**. The `if !` fallback prints
  `::error title=Tracker lookup failed::` and that line is **absent** from all 634
  log lines of run `32350502359`. So `gh issue list` exited 0 and `EXISTING`
  came back empty or `null` — it silently found nothing.
* **The jq filter is not the bug.** Reconstructing the exact program bash hands to
  `gh` (`.github/workflows/verify-sharp-production.yml:437-440`) and running it under
  jq 1.7 against a faithful two-issue fixture returns `951`. The YAML→bash escaping
  resolves correctly to the regex `\[bot\]$`, and the author normalisation is a
  no-op on `github-actions`, which is the login the API reports.

So the fault is in **what the lookup receives or how it is invoked at runtime**,
not in the filter — which is as far as this can be narrowed without a run that
echoes the raw `gh issue list` output. That one-line debug is the next step and it
belongs to the CI lane.

**The four duplicates are deliberately NOT drained yet.** Closing them now is
pointless churn while the workflow still opens one per run; drain once the fix
lands, as F-23 did.

Routed to the CI reliability lane. Under the anti-thrashing rule this is a
demonstrated causal defect in #948, which is the condition that unfreezes it.

### Also confirmed this checkpoint

`Deploy Production` run `32345039692` for the #948 merge
(`9e83509607736f0419dddf3ac00da4110b569f6b`) **completed success** at 08:20:57Z.
