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

// Minting the session is a network call made before every signed-in test,
// and it used to be a SINGLE attempt whose every non-ok answer became
// `test.skip()`.  Both halves were wrong, in the way this repo keeps
// finding (ORCHESTRATION.md §6.15 — a guard whose stated purpose and
// actual predicate differ):
//
//   * The skip claimed "likely E2E_TEST_MODE not set on server", but it
//     fired on ANY non-2xx.  A 429 from the rate limiter or a transient
//     5xx under suite load silently skipped the test — and a skip reads
//     as "fine" in every summary this repo prints.  e2e.yml's own header
//     already records that "create-session 429 makes signed-in specs
//     skip", i.e. the hole was known and described as an aside.  NINE
//     specs use this fixture, so one blip could quietly retire most of
//     the signed-in suite.
//   * The bare `post()` had no timeout and no retry, so a dropped
//     connection threw straight out of the fixture.  That is the
//     observed first-attempt failure of run 31025224262 — the throw is
//     at this call, not at an assertion.
//
// So: retry only what is genuinely transient, skip only the one status
// that actually means "not configured", and FAIL loudly on everything
// else rather than reporting a skip.
const SESSION_MINT_ATTEMPTS = 3;
const SESSION_MINT_TIMEOUT_MS = 15_000;

const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));

async function mintSession(page, baseURL, secret) {
  let lastStatus = null;
  let lastError = null;

  for (let attempt = 1; attempt <= SESSION_MINT_ATTEMPTS; attempt += 1) {
    try {
      const resp = await page.request.post(`${baseURL}/api/test/create-session`, {
        headers: { Authorization: `Bearer ${secret}` },
        timeout: SESSION_MINT_TIMEOUT_MS,
      });
      if (resp.ok()) return { ok: true };
      lastStatus = resp.status();

      // 404 is the ONLY status that means what the old skip message
      // claimed: the route is not mounted, because E2E_TEST_MODE is off.
      // It is deterministic — retrying cannot change it, and skipping is
      // the documented, intended behaviour.
      if (lastStatus === 404) return { ok: false, skip: true, status: 404 };

      // 429 (rate limiter) and 5xx (server busy) are the transient ones.
      // Anything else — 401/403 on a wrong secret, say — is a real
      // misconfiguration that must not masquerade as a skip.
      if (lastStatus !== 429 && lastStatus < 500) {
        return { ok: false, skip: false, status: lastStatus };
      }
    } catch (err) {
      lastError = err;
    }
    if (attempt < SESSION_MINT_ATTEMPTS) await sleep(500 * 2 ** (attempt - 1));
  }

  return { ok: false, skip: false, status: lastStatus, error: lastError };
}

exports.test = base.test.extend({
  authedPage: async ({ page, baseURL }, use) => {
    const secret = process.env.E2E_TEST_SECRET;
    if (!secret) {
      base.test.skip(true, "E2E_TEST_SECRET not set — skipping signed-in tests");
      return;
    }
    const minted = await mintSession(page, baseURL, secret);
    if (minted.skip) {
      base.test.skip(
        true,
        "test-session endpoint returned 404 — E2E_TEST_MODE not set on server",
      );
      return;
    }
    if (!minted.ok) {
      throw new Error(
        `Could not mint a test session after ${SESSION_MINT_ATTEMPTS} attempts: ` +
          (minted.status !== null
            ? `last status ${minted.status}.`
            : `last error ${minted.error && minted.error.message}.`) +
          " This is a REAL failure, not a skip — the server answered, so" +
          " E2E_TEST_MODE is on and the secret or the server is at fault.",
      );
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
