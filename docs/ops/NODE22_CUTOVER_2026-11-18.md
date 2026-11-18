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
