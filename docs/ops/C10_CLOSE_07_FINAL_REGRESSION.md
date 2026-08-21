# C10-CLOSE-07 — Final V1 regression (V1-126)

**Status: DEFINITION ONLY. This has NOT been run as a claim of closure, and running it does not
by itself close V1-126.** Per explicit instruction: "Do not attempt final V1 regression closure
early. Instead define the deterministic final command/matrix that will be run when the
denominator is otherwise complete. No numerator claim yet."

**Target level: L1** — "RED→GREEN test at exact head, plus green CI on the merge tree," per
`docs/VERSION_1_COMPLETION_CONTRACT.md` §2.

## The command

```
bash scripts/run_final_v1_regression.sh
```

A pure composition of gates that already exist and already run somewhere in this repo's CI — no
new test logic, no new gate invented for this row. The script's own header explains why no single
existing command already does this: `release-candidate.yml` is the closest match, but it
deliberately does **not** include Playwright/E2E (that lives in the separately-triggered,
path-filtered `e2e.yml`), while `docs/C_SERIES_REPLAN_AND_COMPLETION_CONTRACT.md` §13.7 explicitly
requires "all blocking backend/frontend/contract/lint/audit/**E2E** gates."

## What it runs, in order

1. Python format + lint (`ruff format --check`, `ruff check`)
2. Governance + planning gates (`check_planning_integrity.py`, `check_product_plan_governance.py`,
   `check_decision_coercions.py`, `audit_status.py`)
3. Backend unit tests (`pytest tests/ -x -q -m "not livedata"`)
4. The V1-121 release-gate classification test (`test_release_gate_classification.py`)
5. API data contract check, **full lane** (not the PR-time structural-only lane — this is the
   final gate, so the full source-health-inclusive check runs, per CLAUDE.md's "CI has two lanes"
   distinction)
6. Source health — advisory, recorded to `${FINAL_REGRESSION_RECORD_DIR}/source-health.log`, never
   gating (same structural/advisory split `release-candidate.yml` already uses)
7. Dependency graph (`pip check`) + environment preflight (`check_env.py`)
8. Python syntax + runtime import gates
9. Deploy script syntax gate (`bash -n` over every `deploy/*.sh`)
10. Frontend unit tests (`npm test`) + build + bundle-size budget
11. **The full Playwright suite, unconditionally** — both CI-run projects (`desktop-1366`,
    `mobile-chromium`) plus the two WebKit-only projects (`mobile-390`, `mobile-430`) that
    `e2e.yml` never runs in CI. This is the one thing this script has that
    `release-candidate.yml` does not.
12. The V1-125 duplicate-owner census — recorded to
    `${FINAL_REGRESSION_RECORD_DIR}/duplicate-owners.log`, not gating. Open `DUPLICATED` rows are
    real, out-of-scope implementation work per that row's own closure record, not a regression
    this script should block on.

## Decisions this document makes explicit rather than leaves implicit

- **WebKit is included by default.** `docs/ops/C10_CLOSE_03_BROWSER_WORKFLOW_MATRIX.md`'s viewport
  table already recorded that CI has zero WebKit/Safari coverage today. If WebKit is genuinely out
  of V1 scope, that is an owner decision — comment out the `WEBKIT_PROJECTS` line in the script and
  record the decision here, rather than silently dropping the coverage on execution day.
- **Source health and the duplicate-owner census are recorded, not gating.** Both measure real,
  currently-open conditions (upstream data staleness; 5 of 8 genuinely live duplicate
  implementations per `docs/WORK_CLAIMS.md`'s C10-CLOSE-02 entry) that are not regressions
  introduced by whatever change triggered this run. Gating on them would block every future run
  on pre-existing, separately-tracked debt — the same reasoning `check_decision_coercions.py`'s
  own baseline-ratchet design already uses.
- **The V1-121 classification test is included as a named step (4/12), not folded silently into
  the general pytest run (3/12).** It IS collected by that same `pytest tests/` invocation, so
  listing it twice is redundant for coverage — it is listed separately so a failure there reads
  immediately as "a CI check went unclassified" rather than getting lost in a general test-suite
  failure count.

## Spot-verification performed while writing this (not a claimed full run)

The individual gates this script composes were spot-checked directly in this session (not via the
script itself, which was not run end-to-end — see "What this is not" above): `ruff format --check`
(found and fixed 4 files this batch's own earlier steps had left unformatted — see the
`fix: ruff format...` commit), `ruff check`, `check_planning_integrity.py`,
`check_product_plan_governance.py`, `check_decision_coercions.py`, `audit_status.py`, `pip check`,
and the relevant `pytest` slices for this batch's own new tests — all clean. `check_env.py` fails
in THIS sandbox on `playwright`, `openpyxl`, `curl_cffi`, `anthropic` — packages this constrained
research/documentation session's environment does not have installed (this repo's own
`requirements.txt` install fails here on an unrelated native-build error, noted repeatedly
elsewhere in this session's own history). That is a sandbox limitation, not a defect this batch
introduced, and is expected to pass in a properly provisioned CI/deploy environment. The frontend
build/test steps and the full Playwright suite were not run in this pass (would require booting a
full stack + browser, and are not needed to validate that the SCRIPT composes real, already-passing
gates correctly).

## What "running this and it passes" would mean, and would not mean

Per §2's L1 definition and the owner's explicit instruction, a green run of this script at V1's
closure moment is the **L1 evidence** for V1-126 — not a standalone claim that V1 itself is done.
V1-126 sits behind V1-121 through V1-125 (and the rest of C10's rows) in the denominator; this
script becomes meaningful only once those are otherwise closed. Running it today, before that
point, would prove nothing about V1-126 specifically — every gate it composes already runs
elsewhere, so a green result today only restates "the gates that already pass, still pass."
