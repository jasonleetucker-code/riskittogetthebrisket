/**
 * Shared signed-in session fixture for Playwright tests.
 *
 * Usage:
 *   const { test, expect } = require('./helpers/auth-fixture');
 *
 *   test.describe('some suite', () => {
 *     test.use({ storageState: 'test-session.json' });  // optional
 *     test('authed flow', async ({ authedPage }) => { ... });
 *   });
 *
 * The fixture calls the test-only /api/test/create-session endpoint
 * to obtain a session cookie without going through the Sleeper
 * flow.  The endpoint 404's unless E2E_TEST_MODE=1 + E2E_TEST_SECRET
 * are set in the server env — prod is never exposed.
 *
 * Skip policy: if the env var E2E_TEST_SECRET isn't set on the
 * test-runner side, the fixture calls test.skip() — better than
 * a silent 404 cascade.
 */
const base = require("@playwright/test");

exports.test = base.test.extend({
  authedPage: async ({ page, baseURL }, use) => {
    const secret = process.env.E2E_TEST_SECRET;
    if (!secret) {
      base.test.skip(true, "E2E_TEST_SECRET not set — skipping signed-in tests");
      return;
    }
    const resp = await page.request.post(`${baseURL}/api/test/create-session`, {
      headers: { Authorization: `Bearer ${secret}` },
    });
    if (!resp.ok()) {
      base.test.skip(
        true,
        `test-session endpoint returned ${resp.status()} — likely E2E_TEST_MODE not set on server`,
      );
      return;
    }
    // The fixture page inherits the cookies from page.request — it's
    // the same browser context.  Reload so subsequent nav uses them.
    await page.goto("/");
    await use(page);
  },
});

exports.expect = base.expect;
