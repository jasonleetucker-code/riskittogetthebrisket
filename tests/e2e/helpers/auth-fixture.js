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
const { pageUrl } = require("./journey");

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
    //
    // Through pageUrl(), NOT bare "/".  Cookies are host-scoped and
    // ignore the port, so :3000 sees the session minted against :8000
    // just the same — but the DOCUMENT matters.  Served through the
    // backend page proxy, "/" hydrates the anonymous shell against an
    // authenticated client, and React reports the mismatch as a #418
    // page error *asynchronously*, on the MessagePort scheduler, after
    // goto() has already resolved.
    //
    // By then the test body has attached its console guards, so the
    // fixture's hydration error lands in the NEXT test's bucket —
    // "/trade renders the builder with working controls" failing with
    // a stack full of :8000 chunk URLs it never requested.  It is a
    // race, so it presents as an intermittent failure on whichever
    // authed spec happens to lose it.
    //
    // (The proxy's mismatched shell is a real defect too. It is
    // tracked in #555 and being deleted; this line is about not
    // misattributing it.)
    await page.goto(pageUrl("/"));
    await use(page);
  },
});

exports.expect = base.expect;
