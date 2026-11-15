# Signals IDP round 2: how the on-box runs are dispatched

Operational companion to `PREREGISTRATION.md` (not frozen). Every run uses the merged
`main` script (`--ref main`): a branch dispatch would let unreviewed code reach the
production SSH key and the paid session. Dispatch one run at a time and wait for it to
finish: the workflow's concurrency group keeps only the newest PENDING run, so a third
dispatch silently replaces a queued one. The workflow refuses to start while a `deploy.yml`
run is in progress or queued, and the script voids a run if the checkout, its config tree or
the backend receipt moved underneath it.

Gate evidence is read from the uploaded ARTIFACT (`signals-onbox-report`), never from the
log: Actions masking corrupts digits. Only the artifact's public projection may be copied
into `RESULTS.md`. The full report, the frozen input tree and the standard-error log stay
0600 in `data/sources/signals/reports/` on the box.

| Step (plan §5.6) | When | Dispatch |
|---|---|---|
| Tier 1a | after this verifier merges | `gh workflow run signals-onbox-verification.yml --ref main -f mode=native-offline` |
| D1, served board (premises P1–P3) | after this verifier merges | `gh workflow run signals-onbox-verification.yml --ref main -f mode=diagnose` |
| D1, round-1 reproduction | after the served-board D1 finishes | `gh workflow run signals-onbox-verification.yml --ref main -f mode=diagnose -f payload_ref=f9d1994e59` |
| D1 artifact of round 1 (run 39066961689) | before it expires on 2026-11-16 | `gh run download 39066961689 -n signals-onbox-report` |
| E1 | the implementation unit deployed, R1 published | `gh workflow run signals-onbox-verification.yml --ref main -f mode=gate -f release_role=R1` |
| E2 | R2 published | `gh workflow run signals-onbox-verification.yml --ref main -f mode=gate -f release_role=R2 -f r1_release=<R1 12-hex>` |
| Download any run | after it finishes | `gh run download <run-id> -n signals-onbox-report` |

What each mode does on the box:

* `native-offline` reads the private IDP release JSONs only: no network, no build.
* `diagnose` copies every build input into a frozen 0700 tree with sha256 pins, renders the
  Signals IDP boards from release `6ec7bff6bd11`, reads the served flags from the local
  `/api/status`, and builds 14 variants, each in its own `nice`/`ionice` subprocess: served,
  no Signals, A (all and per family), N0, the no-retention and Hampel-off pairs, and the
  leave-Draft-Sharks-out builds. It never builds Candidate F.
* `gate` builds F per family, F combined, F with the deep-tail challenger, N0 priced as F and
  the leave-Draft-Sharks-out builds, then the negative controls and the verdicts. Until the
  implementation unit's flags are registered in the deployed code, every F build is refused
  and every verdict is VOID.

A run that cannot read `/api/status` fails closed (the verifier never guesses the served
flags, and never reads `.env`). A run with less than 1.5 GB of available memory refuses each
build rather than risk the production box. If the matrix would exceed the 30-minute job
limit, split it across dispatches with `-f matrix_part=core` and then `-f matrix_part=extra`
(the served build runs in both); never raise the limit. Builds also stop starting after 25
minutes, so an over-long run still prints and uploads a partial report, with the remaining
variants marked `time_budget_exhausted`.
