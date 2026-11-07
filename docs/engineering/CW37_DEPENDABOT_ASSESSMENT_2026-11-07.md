# CW-37 — Dependabot PR assessment (2026-11-07)

Scope: owner directive 2026-11-07 §5, "group safe updates; no major bumps without
regression evidence". Read-only assessment: nothing was merged, approved, closed,
commented on or re-run. Assessed against `main` at `6f3b0e3b99`.

## Headline

12 open Dependabot PRs. **0 are mergeable as-is today.** The single systemic
blocker is the Node runtime split:

- CI and `frontend/package.json` `engines` pin **Node 20** (`">=20 <21"`; every
  `setup-node` uses `"20"`).
- `jsdom@30.1.3` requires `^22.22.2 || ^24.15.0 || >=26`; `vitest@5.0.5` requires
  `^22.12.0 || ^24 || >=26`; `@axe-core/playwright@4.14.0` requires `>=22.12.0`.
  None can run on the Node 20 that CI uses.
- So the three Node-tooling bumps (#2056, #1660, #2033) are blocked on a separate,
  deliberate "move CI/engines to Node 22" decision, not on test results.

| PR | Change | Head CI | Behind main | Recommendation |
|---|---|---|---|---|
| #2056 | jsdom 25.0.1 -> 30.1.3 (major) | Validate PR **failed**, e2e **failed** | 232 | **HOLD** |
| #2034 | 4 GitHub Action bumps (group) | Validate PR success (Nov 1) | 286 | **HOLD** (deploy.yml hunk unprovable in PR CI); rebase first |
| #2033 | `@playwright/test` ^1.64.1, `@axe-core/playwright` ^4.14.0 | Validate PR success, e2e never ran | 286 | **HOLD** |
| #1660 | vitest 4.1.12 -> 5.0.5 (major) | green on Oct 27, stale | 477 | **HOLD** (needs Node 22) |
| #1920 | setuptools 84.0.0 -> 84.1.0 (build lock, hashes) | Validate PR + wheel proofs success | 714 | **MERGE_AFTER_REBASE** |
| #1688 | sharp 0.35.4 -> 0.35.5 (lockfile only) | Validate PR success (Oct 7) | 2424 | **MERGE_AFTER_REBASE** (group with #1687) |
| #1687 | source-map-js 1.2.1 -> 1.2.2 (lockfile only) | not individually checked | 2424 | **MERGE_AFTER_REBASE** (group with #1688) |
| #1663 | fastapi ~=0.141.1 -> ~=0.142.2 | not checked | 2566 | **HOLD** (stale; re-run on current requirements) |
| #1662 | anthropic ~=1.8.0 -> ~=1.11.0 | not checked | 2566 | **HOLD** (stale) |
| #1661 | numpy ~=2.0 -> ~=2.5 | Validate PR success (Oct 5) | 2566 | **HOLD** (stale; lock/wheelhouse not updated) |
| #1508 | uvicorn ~=0.53.0 -> ~=0.54.0 | not checked | 3344 | **HOLD** (stale) |
| #1506 | tzdata ~=2026.1 -> ~=2026.4 (win32 only) | Validate PR success (Sep 28) | 3344 | **CLOSE_SUPERSEDED** candidate / low value (see below) |

Owner-facing note: the "CI success" on old Python/npm-lock PRs ran against a base
hundreds to thousands of commits old; per the HEAD-FREEZE rules that proves
nothing about the current tree, so the Dependabot rebase (`@dependabot rebase`,
which is a PR comment and so outside this task) must precede any merge.

## The three known PRs

### #2056 — jsdom 25.0.1 -> 30.1.3 (major, `frontend/` devDependency)

1. Changes: `frontend/package.json` (`^25.0.1` -> `^30.1.3`) plus a lockfile that
   shrinks by about 300 lines (jsdom 30 drops many transitive packages).
2. CI on head `df43ef44bf` (Nov 2): **Validate PR failed; "Boot stack + run
   journeys" (e2e) failed.** The Validate PR log shows the vitest summary
   `Test Files 185 passed, Tests 3254 passed, Errors 211 errors`, with the cause
   `[vitest-pool] Failed to start forks worker ... TypeError: Cannot read properties
   of undefined (reading 'bind') at node_modules/undici/lib/interceptor/decompress.js`
   — undici (jsdom 30's dependency) uses a Node 22+ API that Node 20 lacks.
   The e2e job's tail log held only teardown output; its failure cause was not
   isolated, and it is likely the same Node 20 incompatibility but unproven.
   Branch is 232 commits behind main.
3. Upstream: jsdom 30.1.3 engines `^22.22.2 || ^24.15.0 || >=26`, vs. repo
   `engines.node ">=20 <21"` and CI `node-version: "20"`. Incompatible by
   declaration, and CI confirms it. (Release notes were not fetched; the engines
   field and CI log already decide it.)
4. Local regression evidence (Node 22.23.4, `npm ci && npx vitest run`, JSON reporter).
   Three detached worktrees: PR head, its merge-base `7f86b2adb0` (jsdom 25,
   identical test set), and current main.

   | tree | tests | passed | failed |
   |---|---|---|---|
   | merge-base (jsdom 25) | 5286 | 5286 | 0 |
   | PR head (jsdom 30) | 5286 | 5270 | **16** |
   | current main (jsdom 25, newer tests) | 5415 | 5414 | 1 |

   Comparing PR head against its own merge-base, 16 tests flip passed to failed,
   in 3 component files: `trade-screenshot-import.test.jsx` (11),
   `trade-screenshot-import-page.test.jsx` (4), `second-opinions-dual-va.test.jsx`
   (1). Errors are accessibility-query misses (`role="region" name "Side A"`,
   `role="combobox"`, `columnheader /^Total under /`, missing banner text) —
   i.e. jsdom 30 changes DOM/accessible-name behaviour or timing these tests rely
   on. A further 18 entries under `route-gate-no-player-data-transitive.test.js`
   differ only by dynamic test names (present in one run, absent in the other)
   and are not counted as regressions. The one failure on current main
   (`RankingsBoard.test.jsx` NFL team filter combines...) is unrelated to jsdom
   and is the pre-existing local Node 22 difference class noted in
   `docs/agent-operating-system/SESSION_HANDOFF.md`; main was not re-run on Node 20.
5. Recommendation: **HOLD.** Two independent blockers: (a) Node 20 engine/CI
   incompatibility (proven by CI), (b) 16 real component-test regressions even on
   Node 22. Missing evidence to unblock: a Node 22 migration decision for
   CI/engines, and the 16 tests either repaired against jsdom 30 or shown to be
   test-side fixtures; then rebase and re-run. Do not group with others.

### #2034 — GitHub Actions group (4 updates)

1. Changes (5 workflow files, tag-pinned):
   - `actions/upload-artifact@v4 -> v7` (backend-wheelhouse-proof x2,
     class-b-model-branch, deploy)
   - `actions/download-artifact@v4 -> v8` (class-b-model-branch, deploy)
   - `anthropics/claude-code-action@v1.0.233 -> v1.0.264` (claude.yml)
   - `actions/setup-node@v6 -> v7` (v1-authenticated-verification)
   Pinning convention: **no workflow pins by SHA**; all use version tags
   (`actions/checkout@v7` x44, `upload-artifact@v7` x19, `setup-python@v7` x18,
   `setup-node@v7` x5; `claude-code-action` pins an exact patch tag). The PR keeps
   that convention. Note main already runs `upload-artifact@v7` in 19 places, so
   v7 is proven on these runners; only 4 v4 stragglers remain, and `setup-node@v7`
   is already used 5 times.
2. CI on head `894f0d5e57` (Nov 1): Validate PR, prove-linux-wheels,
   prove-runtime-wheels, Credential-free model proposal all success. 286 behind
   main. These runs cannot exercise `deploy.yml` (push-to-main) or
   `class-b-model-branch.yml`.
3. Upstream notes (from the actions release pages): upload-artifact v6 moved to
   Node 24 runtime (runner >= 2.327.1; hosted runners fine); v7 adds opt-in
   `archive: false` and ESM, nothing breaking for default usage.
   download-artifact v8 is the notable one: **a digest/hash mismatch now fails the
   run by default**, and **non-zipped downloads are no longer unzipped** (new
   `skip-decompress` input). v5 changed single-artifact-by-ID extraction layout
   (these jobs download by name, unchanged). The deploy flow uploads and downloads
   a tested release tarball by name, so default behaviour should be compatible,
   but this is inference, not evidence.
4. Regression evidence: none obtainable locally; the risky hunk is the deploy
   path. What would prove it: a branch run of the class-b workflow
   (`workflow_dispatch`) and a deploy dry-run or first-deploy observation with the
   rollback ready.
5. Recommendation: **HOLD** the group as one PR because the production deploy
   path (`deploy.yml` upload v7 / download v8) is unprovable in PR CI and deploy
   is an owner-reserved boundary. The other hunks (claude-code-action patch bump,
   setup-node v7, wheelhouse upload v7) are low risk; the safe resolution is to
   ask Dependabot to ignore/split, or the owner/integration lane to land the
   non-deploy files in an ordinary PR and take `deploy.yml` with deploy evidence.
   Rebase before any merge (286 commits behind, and 17 workflows changed since).

### #2033 — e2e-harness group (root `package.json`)

1. Changes: `@playwright/test ^1.63.0 -> ^1.64.1`, `@axe-core/playwright
   ^4.13.0 -> ^4.14.0` (`axe-core` stays `^4.13.0`); lockfile 43 lines.
2. CI on head `18d7855f84` (Nov 1): only Validate PR (success, 1.5 min). **286
   behind main.**
3. Upstream engines: `@playwright/test@1.64.1` `>=20` (fine on Node 20);
   **`@axe-core/playwright@4.14.0` requires Node `>=22.12.0`** while `e2e.yml`
   installs with `node-version: "20"` and the root `npm install` would only
   print EBADENGINE. Release notes not fetched.
4. Does e2e run in PR CI? Only conditionally. `e2e.yml` runs on `pull_request`
   with a `paths:` filter (`frontend/package.json`, `frontend/next.config.*`,
   `frontend/middleware.js`, `tests/e2e/**`, `.github/workflows/e2e.yml`, shell
   files) plus nightly and `workflow_dispatch`. **Root `package.json` and
   `package-lock.json` are not in the filter**, so this PR never triggered the
   e2e job (confirmed: one check run). Hence green Validate PR proves nothing
   about Playwright/axe behaviour.
   What would prove it safe: `workflow_dispatch` of `e2e.yml` on the rebased PR
   branch (all projects incl. WebKit) and a green nightly; separately resolving
   the axe Node 22 requirement. Dispatching was out of scope here (do not
   trigger runs).
5. Recommendation: **HOLD**, same Node 22 blocker. Suggest adding the root
   `package.json`/`package-lock.json` to the `e2e.yml` path filter so harness
   bumps prove themselves (separate change).

## Other open Dependabot PRs

- **#1660 vitest 4.1.12 -> 5.0.5 (major):** vitest 5.0.5 engines need Node
  `^22.12`; CI is Node 20. Its green runs (Oct 27) predate the 5.0.5 pin; the
  branch is 477 behind. Same blocker and same Node 22 decision as #2056; vitest
  5 and jsdom 30 should be evaluated together after the Node migration, since
  both touch the jsdom project. HOLD.
- **#1920 setuptools 84.0.0 -> 84.1.0:** single line in
  `requirements-build.lock.txt` with two hashes; Validate PR and both wheel-proof
  jobs passed on Oct 24; 714 behind. Patch-level build tool, covered by the wheel
  proofs. MERGE_AFTER_REBASE.
- **#1688 sharp 0.35.5 and #1687 source-map-js 1.2.2:** lockfile-only patch bumps
  under `frontend/`; Validate PR success (#1688 checked, #1687 not individually
  checked), 2424 behind. Group them in one lockfile refresh after rebase
  (`engines` permits Node 20; not independently verified for sharp 0.35.5).
  MERGE_AFTER_REBASE; run frontend L1/L2 once on the grouped result.
- **#1661 numpy ~=2.0 -> ~=2.5, #1663 fastapi ~=0.141.1 -> ~=0.142.2, #1662
  anthropic ~=1.8.0 -> ~=1.11.0, #1508 uvicorn ~=0.53.0 -> ~=0.54.0:** each edits
  only the `requirements.txt` range. The repo installs from hashed locks
  (`requirements.lock.txt`, `python_lock.py check`, wheelhouse proof), so a
  range change without regenerated lock/hashes does not change what CI installs
  and proves nothing; numpy is a minor-range jump (2.0 to 2.5) used by the
  scipy/HiGHS optimizer. All 2566-3344 commits behind. HOLD: re-run as a single
  grouped python-runtime bump with regenerated locks and the wheelhouse/L2 proof;
  not checked for #1663, #1662, #1508 beyond the diff.
- **#1506 tzdata ~=2026.1 -> ~=2026.4:** win32-only marker, nothing on Linux CI or
  production; Windows dev only. CLOSE_SUPERSEDED candidate (or leave for a
  Windows-dev refresh); 3344 behind.

## Grouping proposal

1. **Group A (safe, after rebase):** #1920, #1688, #1687.
2. **Group B (Node 22 programme, one decision):** #2056, #1660, #2033 (and the
   axe-core requirement). Prerequisite: owner-approved move of `engines`, every
   `setup-node` pin and the e2e/deploy runners to Node 22; then vitest 5 + jsdom
   30 together with the 16 failing component tests repaired, then e2e harness.
3. **Group C (Python runtime):** #1661, #1663, #1662, #1508 as one PR with
   regenerated hashed locks.
4. **Group D (workflows):** #2034 split into non-deploy files (landable now) and
   `deploy.yml` (needs deploy evidence).

## Evidence and limits

- Local runs: Node v22.23.4; commands `npm ci && npx vitest run --reporter=json`
  in `frontend/` of detached worktrees (merge-base, PR head, main), all removed.
- Check runs read via the GitHub API; CI results quoted are from Nov 2 (#2056),
  Nov 1 (#2034, #2033) and older for the rest.
- Not examined: release notes for jsdom, vitest, sharp, fastapi, numpy,
  anthropic, uvicorn, setuptools, playwright and axe (engines fields and CI
  evidence were decisive); CI for #1687, #1663, #1662, #1508.
- No PR was approved, merged, closed, commented on or re-run.

UNRESOLVED: Node 22 migration decision (owner); the 16 jsdom-30 component test
failures; e2e failure cause on #2056 (log tail only); deploy-path proof for
download-artifact v8.
