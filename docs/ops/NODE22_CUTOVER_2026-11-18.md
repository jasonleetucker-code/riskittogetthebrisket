# Node 20 to 22 migration (CI side done, box cutover is OWNER ACTION)

Audit-remediation Task 16, owner directive 2026-11-18.

## Current state
- Node 20 reached end of life 2026-04-30.
- Before this change: all CI workflows pinned Node 20 and `frontend/package.json` `engines.node` was `>=20 <21`.
- The production box's Node version is not known from the repository. `deploy/deploy.sh` and `deploy/rollback.sh` record `node --version` in the release manifest, so the manifest of the latest release answers it.
- The box runs `npm ci --prefix frontend` on every deploy (artifact path and legacy path). The repo has no `.npmrc` with `engine-strict`, so an engines mismatch would only warn. We still keep `engines` wide enough that a Node 20 box is never outside the declared range.

## What this PR changes
- Every workflow `actions/setup-node` pin moves from 20 to 22 (deploy, e2e, pr-validation, prod-e2e-smoke, release-candidate, v1-authenticated-verification). Step names that said "Node 20" now say "Node 22"; `config/ci/release_gate_classification.json` and `tests/deploy/test_production_baseline_workflow.py` are updated to match (categories unchanged).
- `.nvmrc`: `20` -> `22`.
- `frontend/package.json` and `package-lock.json` `engines.node`: `>=20 <21` -> `>=20 <23`. Accepts the current box (20) and 22, so a Node 20 box keeps deploying until the cutover.
- The jest-dom comment in the dependabot config is updated; the ignore entry itself stays until the follow-up below.
- No `deploy/*.sh` behaviour changes. No dependency bumps.

Trade-off to know: CI now validates on Node 22 while the box still runs Node 20. The frontend dependency set is valid on both lines, but a Node-22-only regression is theoretically possible between this PR and the cutover. Keep the window short.

## Local validation (Node v22.23.4)
- `npm ci`: ok. `npx vitest run`: 446 files, 5795 passed, 3 expected fail.
- `npm run build` (next build --webpack + bundle-size + privacy + advisor bundle checks): pass; all 19 budgeted pages under budget. The first attempt hit Next's build-time advisory `SecurityFatalError`; the retry succeeded.
- A `MODULE_TYPELESS_PACKAGE_JSON` warning for `lib/auction-power.js` appears on 22 (informational, not an error).

## Owner box cutover steps
1. Confirm current version: `node --version` on the box and the latest release manifest.
2. Install Node 22 LTS (distro package or NodeSource `setup_22.x`); if nvm is used, `nvm install 22` and make sure the deploy script's resolver (highest `versions/node/*/bin`) picks it. Verify `node --version` prints v22.x and `npm --version` works for the service user.
3. Rebuild: trigger a normal deploy (it runs `npm ci` and builds `.next`), or manually `npm ci --prefix frontend && npm run build --prefix frontend`.
4. `sudo systemctl restart dynasty-frontend.service`; check `systemctl status` and the journal.
5. Verify `curl -I https://<host>/` and `/trade` respond (200, or 307 to `/login` when anonymous).
6. Verify the new release manifest records `node` v22.

## Rollback
Reinstall Node 20 (or switch the nvm default back), then redeploy the previous artifact with `deploy/rollback.sh`, restart `dynasty-frontend.service`, re-verify `/` and `/trade`. `engines` accepts 20, so no repo change is needed.

## Follow-up PR after the cutover is verified
- Raise `engines.node` to `>=22` in `frontend/package.json` and the lockfile; drop Node 20 wording in docs.
- Remove the jest-dom ignore entry in the dependabot config.
- Then take the blocked upgrades in this order: (1) `@testing-library/jest-dom` 7 (#1467), (2) jsdom 31 (#2181), (3) vitest 5.1.0 (#2180), (4) `@axe-core/playwright` 4.14 (needs Node >=22.12; CI already satisfies it, and the box should be 22.12+ before the engines bump).

## Correction 2026-11-18 — the cutover is ONE coordinated change

#2252 moved every workflow to Node 22 while the box still ran Node 20. The next Deploy Production run (`79c60f26`,
run 44330192334) failed at artifact staging: `scripts/stage_release_artifact.py` refuses an artifact built on a
different Node major ("release Node major version differs from production") and the deploy auto-rolled back to
`f5e06111`. Production kept serving; every later deploy would have failed the same way.

The fix restores Node 20 on every lane that builds, validates or exercises what production runs — `deploy.yml`,
`release-candidate.yml`, `pr-validation.yml`, `e2e.yml` — and pins it in
`tests/deploy/test_deploy_node_matches_production.py` (`PRODUCTION_NODE_MAJOR`). `prod-e2e-smoke.yml` and
`v1-authenticated-verification.yml` only run test tooling against the live site and stay on 22.

The cutover is therefore one change window, in this order:
1. Install Node 22 LTS on the box (steps above); confirm `node --version`.
2. In ONE PR: set those four workflows to `"22"`, set `PRODUCTION_NODE_MAJOR = "22"`, raise `engines.node` to
   `>=22 <23`; merge it right after step 1 so the next deploy builds and stages on 22.
3. Verify the release manifest records v22 and `/` and `/trade` respond.
Rollback: reinstall Node 20 on the box and revert that PR (both together).

## Cutover window 2026-11-19 (STAB-6) — exact sequence

Prepared PR: branch `claude/serene-shannon-7lsrm9-s06-node22-cutover`. It moves the four production-runtime lanes
(deploy, release candidate, PR validation, E2E) to 22, sets `PRODUCTION_NODE_MAJOR = "22"`, and raises `engines.node`
to `>=22.12 <23`. Optional rolldown native bindings in the lockfile require 22.12+. Its own CI validates the build and
the tests on Node 22. **Merge it only in step 3 below.**

Facts:
- The box runs Node 20 from a system install. The frontend unit runs `/usr/bin/npm`. Proof: the deploy log line
  "Frontend systemd unit ExecStart binary resolved to: /usr/bin/npm", and the staging refusal of the Node-22
  artifact in run 44330192334.

1. **Pre-check (owner, on the box, read-only):** `bash /home/dynasty/trade-calculator/deploy/node22_box_check.sh`.
   Keep the output: it records the current `nodejs` package version for rollback.
2. **Install Node 22 (owner, root).** Use the NodeSource 22.x repository (the same mechanism a `/usr/bin/node`
   system install normally comes from), following NodeSource's current instructions for the box's Ubuntu release:
   ```bash
   curl -fsSL https://deb.nodesource.com/setup_22.x -o /tmp/nodesource_setup_22.sh   # read it before running
   sudo bash /tmp/nodesource_setup_22.sh
   sudo apt-get install -y nodejs
   bash /home/dynasty/trade-calculator/deploy/node22_box_check.sh --require 22.12
   ```
   The running services keep serving: Next.js and the backend are not restarted by this. If the box's Node came from
   somewhere other than NodeSource (the pre-check shows the apt source), tell me before step 2.
3. **Merge the prepared PR immediately** (I do this when you say "Node 22 installed"). Any deploy between steps 2 and
   3 is refused at staging: no production change, the site keeps serving. That is why the window should be minutes.
4. **The next deploy builds and stages on 22.** I then verify:
   - the deploy log shows the artifact accepted at staging;
   - `/api/status` `build.commit` is the merge;
   - `/` and `/trade` respond;
   - the post-deploy authenticated verification passes.

Rollback (both halves together):
1. On the box: `sudo apt-get install -y --allow-downgrades nodejs=<version recorded in step 1>`, after pointing the
   NodeSource list back at `node_20.x` (`/etc/apt/sources.list.d/nodesource.list`) and running `apt-get update`.
2. Revert the merged PR, so CI builds on 20 again.
3. Redeploy (normal deploy, or `deploy/rollback.sh <previous release>`).
4. Re-run `node22_box_check.sh`.
