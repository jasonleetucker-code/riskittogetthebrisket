# Consensus Edge weekly re-validation: why it was red for ten weeks

**Date:** 2026-10-26 (diagnosis, read-only).
**Audit item:** RPA-COL-006 (and the two store observations under RPA-COL-005).
**Authority:** none. This is an evidence record. It changes no gate, threshold,
model, or flag. `consensus_edge` stays OFF in production, and the committed
verdict (`do not ship yet` at both horizons) is untouched.

Agent-OS-Receipt: cb64f74cf4d2763aa16d55ba0d6350f585a2a42f

## 1. Answer

| Question | Answer |
|---|---|
| Real model degradation? | **No.** The study finished and printed its verdict in all ten red runs. |
| Environment or data failure? | **No.** Install and the 55-test self-test were green in all ten. |
| A gate that cannot pass by construction? | **No.** The same job went green on 2026-10-14 and 2026-10-21 with no change to the study, the gate, or the committed measurements. |
| Actual cause | **A harness crash after the verdict was computed.** `scripts/validate_consensus_edge_board.py` logged its output path with `out.relative_to(REPO)`; the workflow passes `--out /tmp/ce-rerun/...`, which is outside the checkout, so `Path.relative_to` raised `ValueError` after the JSON was already written. `set -e` aborted the horizon loop and the compare step was skipped. |
| Still red now? | **No.** The last two scheduled runs (2026-10-14, 2026-10-21) are green. Next scheduled run: Wednesday 2026-10-28. |
| Fixed on `main`? | **Yes**, since 2026-10-07: `b4e984bc0` (CLEANUP-3, PR #1680) added `display_path()` and its tests. The 2026-10-07 red run started 11:59Z, before that fix (committed 15:52Z). |

Correction to the CLEANUP-3 commit message: it says the job was "red every week
since at least 2026-09-02". The logs show the identical traceback in **all ten**
runs from 2026-08-05.

## 2. Log evidence

All runs are `consensus-edge-revalidate.yml`, event `schedule`, branch `main`.
`h14 ran` means the second horizon of the loop executed at all.

| Run id | Started (UTC) | Conclusion | compare step | h7 top-20 median, folds, beat-random | h7 verdict | h14 ran |
|---|---|---|---|---|---|---|
| 30987738943 | 2026-08-05 08:07 | failure | skipped | -0.59%, 12, 0/12 | do not ship yet | no |
| 31572024400 | 2026-08-12 06:57 | failure | skipped | -0.51%, 13, 1/13 | do not ship yet | no |
| 32221684118 | 2026-08-19 06:01 | failure | skipped | -0.50%, 14, 1/14 | do not ship yet | no |
| 32936611967 | 2026-08-26 06:04 | failure | skipped | -0.11%, 17, 5/17 | do not ship yet | no |
| 33616604199 | 2026-09-02 09:53 | failure | skipped | -0.10%, 18, 6/18 | do not ship yet | no |
| 34338482496 | 2026-09-09 10:07 | failure | skipped | -0.09%, 19, 6/19 | do not ship yet | no |
| 35084199512 | 2026-09-16 10:17 | failure | skipped | +0.26%, 20, 6/20 | do not ship yet | no |
| 35847841574 | 2026-09-23 10:16 | failure | skipped | +0.21%, 21, 6/21 | do not ship yet | no |
| 36708000268 | 2026-09-30 11:21 | failure | skipped | +0.21%, 22, 7/22 | do not ship yet | no |
| 37617836143 | 2026-10-07 11:59 | failure | skipped | +0.20%, 23, 8/23 | do not ship yet | no |
| 38550697569 | 2026-10-14 10:35 | **success** | success | +0.25%, 24, 9/24 | do not ship yet | yes |
| 39585633029 | 2026-10-21 10:34 | **success** | success | +0.06%, 25, 10/25 | do not ship yet | yes |

Verbatim, run 30987738943 (the first red run):

```
[ce-validate] DECISION: do not ship yet
Traceback (most recent call last):
  File ".../scripts/validate_consensus_edge_board.py", line 744, in <module>
    raise SystemExit(main())
  File ".../scripts/validate_consensus_edge_board.py", line 739, in main
    log(f"wrote {out.relative_to(REPO)}")
ValueError: '/tmp/ce-rerun/board-validation-h7.json' is not in the subpath of '/home/runner/work/riskittogetthebrisket/riskittogetthebrisket'
##[error]Process completed with exit code 1.
```

Run 35084199512 (2026-09-16), same traceback at line 746 after:

```
[ce-validate] TOP-20 BUYS: median +0.26% cohort-excess over 20 folds (2/20 positive), beat random in 6/20
[ce-validate] DECISION: do not ship yet
```

Run 37617836143 (2026-10-07, last red run), same traceback after:

```
[ce-validate] DECISION: do not ship yet
[ce-validate]   top-20 buys returned a median +0.20% cohort-excess across 23 folds and beat a random-20 draw in 8/23.
ValueError: '/tmp/ce-rerun/board-validation-h7.json' is not in the subpath of '/home/runner/work/riskittogetthebrisket/riskittogetthebrisket'
```

Latest run, 39585633029 (2026-10-21, green):

```
[ce-validate] wrote /tmp/ce-rerun/board-validation-h7.json
[ce-validate] DECISION: do not ship yet
[ce-validate] wrote /tmp/ce-rerun/board-validation-h14.json
h14: fresh   'do not ship yet' (median -0.003849964753115879)
h14: consensus-edge-board-validation-2026-08-04-h14.json 'do not ship yet' (median -0.010111744488608203)
h7: fresh   'do not ship yet' (median 0.0006484280584078708)
h7: consensus-edge-board-validation-2026-08-04-h7.json 'do not ship yet' (median -0.005547900767773905)
Committed verdicts still describe the code.
```

The log line `wrote /tmp/ce-rerun/...` (absolute path) in the green runs is the
visible effect of the fix.

## 3. Consequences of the crash

* Drift was **not checked** for ten weeks. In every red run the study's own
  verdict equalled the committed one, so the compare would have passed.
* The h14 horizon never ran in those ten runs (`set -e` ended the shell loop
  after h7).
* The fresh h7 JSON was still uploaded (`if: always()`) as a 30-day artifact.
  Most of those artifacts have expired, but two have not (checked read-only
  against the Actions artifacts API on 2026-10-26):
  * run 36708000268 (2026-09-30): artifact **not expired**, expires
    2026-10-30T11:23Z;
  * run 37617836143 (2026-10-07): artifact **not expired**, expires
    2026-11-06T12:02Z.

  These are the only artifacts that could still confirm the red-run JSON
  itself; the medians, fold counts and verdicts in the table above come from
  the run logs, not from the artifacts. They were not downloaded for this
  record. Preserving them before they expire is an owner/ops option; nothing in
  this PR does it.

## 4. A residual reporting defect, fixed in this PR

The job summary had two branches: compare succeeded, or "**The committed
measurement no longer describes the code.**" When the re-run crashed, the
compare step was skipped, so the second branch fired. Each of the ten red runs
therefore told its reader the committed measurement was stale, when no verdict
had been compared. This PR makes it three-way (match, re-run or compare did not
complete, real drift). Drift is reported only when the compare step itself
failed after a successful re-run; a compare step that was skipped, cancelled or
never reported is "did not complete", not drift. It keeps every step name
(they are keyed in `config/ci/release_gate_classification.json`), and adds
`tests/consensus_edge/test_revalidate_workflow_summary.py`, which runs the real
summary script for each outcome combination (POSIX bash only) and statically
checks that the drift message is guarded on a compare failure (all platforms).
Study, gate, thresholds and comparison logic are unchanged.

A follow-up closes the remaining gap. The compare step also exits 1 on an
uncaught error, so it now prints `CE_REVALIDATE_RESULT=verdict_drift` as its
last line before exiting on drift. The summary claims drift only when that
whole line is in `compare.txt`. A compare failure without it (after a
successful re-run) is reported as "**The comparison crashed, so no verdict was
compared.**", in the same style as the "did not complete" message.

## 5. What a green run does and does not say

(Carried over from the audit, verified against the workflow.)

* The compare step compares only the **verdict string** against
  `docs/measurements/consensus-edge-board-validation-2026-08-04-h{7,14}.json`.
  Green means "still do not ship yet", not "healthy".
* The committed measurements are frozen at 2026-08-04 by design (the workflow
  never commits a re-run). Fresh numbers live in 30-day artifacts.
* The workflow reads the git-history panel. It does not read the box store.
* A red scheduled run raises no issue or notification. Nothing alerted on the
  ten-week streak. That gap is unchanged.

## 6. `hours_stale` is not the build age (RPA-COL-005)

Not a reporting bug. The column is correct and means something different from
what its name suggests.

**Definition (code):**

* Per row, `board_snapshots.hours_stale` is `board.inputs.hoursStale`
  (`snapshot._row_values`), which is `service.resolve_hours_stale(contract)`.
* That returns the **maximum** `ageHours` over the two market anchors
  (`ktcCrowdTradesSfTep` for offense, `idpTradeCalc` for IDP): the oldest
  anchor, deliberately ("the weakest link").
* `ageHours` comes from `data_contract._build_source_timestamps`:
  `payload scrapeTimestamp - data/scrape_state/{source}_last_success`
  (CSV mtime only when no stamp exists), read from the box checkout's own
  `data/scrape_state`. It is a **fetch-success clock**, not a content-change
  clock (the audit inferred "source-content based"; the code reads the
  fetch-success stamp instead). That the stamp advances on every successful
  fetch even when the CSV is byte-identical is **documented** (`CLAUDE.md`,
  "Content staleness is not fetch freshness"), not verified in code for this
  record.
* The build age is a different pair of columns in the same row:
  `written_at - contract_scraped_at`.

**Verified reproduction (2026-10-26 row, hours_stale 17.765, contract_scraped_at
05:49Z, both from the audit's direct read of the box store):**

* Both anchors' stamp at `main` commit `34bc0dee` is `1792929817` =
  2026-10-25T12:03:37Z.
* 12:03:37Z + 17.765 h = 2026-10-26T05:49:31Z, the audit's `contract_scraped_at`.
* `main` committed no newer anchor stamp until `e8b8788f` at 2026-10-26T12:53Z,
  a 24.8 h gap, the longest in October. So that 17.8 h is a real gap in anchor
  fetch successes, not a build delay (the same row's build age is about 1.7 h).

**2026-10-13 / 10-14 (80.4 h and 95.1 h): the 10-13 value is consistent with a
failed-deploy streak; the 10-14 row is partially explained, and the 95.1 h value
is not reproduced.**

* Every `Deploy Production` run from 2026-10-10T02:01Z to 2026-10-14T14:27Z
  failed. Example, run 38361328867 (2026-10-13T07:13Z):
  `Validate Build Inputs` failed, `Deploy To Production` skipped. The next
  success was 2026-10-14T16:58Z.
* The last good deploy before the streak (2026-10-09T21:25Z, commit `e0a4de98`)
  carries anchor stamps of 2026-10-09T21:21:33Z.
* 21:21:33Z + 80.4 h = 2026-10-13T05:45:33Z, about when the box builds its board
  (05:49Z on 10-26). So the box's stamps were frozen at the last good deploy
  while its board kept advancing.
* UNVERIFIED: 21:21:33Z + 95.1 h = 2026-10-13T20:27:33Z. If the 10-14 row was
  built from a board scraped at 20:27Z on 10-13, that explains 95.1 h with the
  same frozen stamp. The repo cannot confirm which export the 10-14 run read;
  `written_at` / `contract_scraped_at` in the store would settle it.

**Effect:** `hours_stale` feeds the freshness factor of confidence
(`exp(-ln2 * h / 48)`: 0.31 at 80.4 h, 0.25 at 95.1 h). So those two days were
correctly marked low-freshness. The store keeps both clocks, so nothing is lost.
Whether stale-input snapshots should be excluded from outcome labelling is an
analysis choice (see section 8), not something changed here.

## 7. The missing 2026-10-05 row (RPA-COL-005)

Not a reporting bug. The job most likely wrote nothing because it could not
build a board.

* **Inferred cause (timing plus shared code path; the box journal was not
  read):** the 2026-10-05 07:30Z run fell inside the "Rankings outage". Per
  hotfix `b452fbe95`: "every contract build since the Signals collector's first
  real run failed with `IndexError: list index out of range`" at
  `data_contract.py:12914`. `scripts/snapshot_consensus_edge.py::_load_contract`
  calls the same `build_api_data_contract(raw)` and wraps only the file read in
  try/except, so a builder exception ends the process (traceback, exit 1)
  before any write. The bug needs a provisioned private Signals store, which
  only the box has, so CI never saw it.
* **Timeline:** the Signals Fantasy commit `7bb4ed2e` (offense ACTIVE, IDP
  collected) deployed at 2026-10-04T18:18Z;
  deploys from 10-04T19:55Z to 10-05T09:09Z failed; the first deploy carrying
  the hotfix to succeed was 10-05T11:39Z (push) and 15:24Z (dispatch). The
  07:30Z snapshot ran in the gap. 10-06 ran normally.
* **Why nothing retried:** `Persistent=true` only catches up a run missed
  because the box was off; it does not retry a unit that ran and failed. No
  alert watches the unit or the date sequence.
* **Why it is not backfilled:** `--as-of` on a past date is refused without
  `--backfill`, because today's board under a past date is a fabricated history
  entry. A git-panel replay is a different quantity. The gap is permanent.
* **Blast radius is small:** `label_outcomes` snaps the horizon FORWARD, so the
  origins whose horizon landed on 10-05 (h7 from 09-28, h14 from 09-21, h30
  from 09-05) resolve against 10-06 with a one-day-longer hold. No row is
  corrupted.
* **To confirm on the box (read-only):**
  `journalctl -u dynasty-consensus-edge-snapshot --since 2026-10-05 --until 2026-10-06`
  should show the `IndexError` traceback and `Result=exit-code`.

## 8. Decisions this record does not take

These are owner or lead decisions. Nothing here pre-empts them.

1. **Commit a newer measurement?** The workflow's design says a human commits
   the fresh re-run alongside whatever decision it implies. The committed files
   still date from 2026-08-04 and the 2026-10-21 artifact expires about
   mid-November. Verdict would be unchanged (`do not ship yet`).
2. **Alerting.** Ten red weekly runs and one skipped snapshot day produced no
   notification. Whether to add a tracker issue for this workflow (the
   CLEANUP-3 pattern used by other workflows) and a skipped-day alert for the
   snapshot timer is a separate change; none is made here.
3. **Stale-input snapshots.** Whether days with `hours_stale` above a threshold
   (10-13, 10-14, 10-23, 10-26 in the audit) are excluded from outcome
   labelling is an analysis decision.
4. **The gate itself.** The pre-registered gate is untouched. On 2026-10-21 the
   h7 median was +0.06% but the top-20 beat random in only 10 of 25 folds
   (not a majority) and h14 was -0.38%; both horizons stay `do not ship yet`.
