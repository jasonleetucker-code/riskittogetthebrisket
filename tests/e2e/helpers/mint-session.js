/**
 * Mint the E2E test session, retrying ONLY a dropped connection.
 *
 * Split out of `auth-fixture.js` so it carries no `@playwright/test` import and
 * can be exercised by a plain `node` script — the fixture itself cannot be
 * required without Playwright's runner present.
 *
 * WHY THIS RETRIES — and why that is not laundering a failure.
 *
 * Every authed spec runs this in its fixture, before a single assertion.  On
 * 2026-08-05 two of them (`journey-rankings.spec.js:109` and `:152`) failed
 * with `apiRequestContext.post: read ECONNRESET` and both passed on Playwright's
 * retry, so the run reported **0 failed, 2 flaky, 140 passed** — and
 * `failOnFlakyTests` correctly turned that into a red job, blocking a PR whose
 * files were nowhere near either spec.
 *
 * The reset is a keep-alive race between Playwright's request context and
 * uvicorn recycling an idle connection.  It carries no product signal: this
 * POST is setup, not a behaviour under test, and a connection that dies before
 * it is answered says nothing about the app.
 *
 * The distinction that keeps `failOnFlakyTests` honest:
 *
 *   - a transport error (no answer)      → retry, bounded
 *   - ANY HTTP response, including 5xx   → returned as-is, never retried
 *
 * So a backend that answers wrongly still fails exactly as before, and a
 * backend that is genuinely dead still fails: every attempt gets the same reset
 * and the last error is rethrown, so `stack-death-reporter.js` still sees its
 * `CONNECTION_ERROR` and prints the stack-death banner.  What this removes is a
 * single dropped connection, which was previously indistinguishable from a real
 * defect.
 *
 * Pinned by `tests/e2e/test_auth_fixture_retry.js`.
 */

// Transport-level failures, as distinct from an HTTP response.  These mean the
// request never got an answer at all, so there is no status to reason about.
const TRANSPORT_ERROR = /ECONNRESET|ECONNREFUSED|EPIPE|socket hang up/i;

const MINT_ATTEMPTS = 3;
const MINT_BACKOFF_MS = 250;

const MINT_PATH = "/api/test/create-session";

async function mintSession(page, baseURL, secret) {
  let lastErr;
  for (let attempt = 1; attempt <= MINT_ATTEMPTS; attempt += 1) {
    try {
      return await page.request.post(`${baseURL}${MINT_PATH}`, {
        headers: { Authorization: `Bearer ${secret}` },
      });
    } catch (err) {
      // Only a transport failure is retryable.  Anything else — a bad URL, a
      // Playwright API misuse — is a real error and must surface immediately
      // rather than being tried three times and reported as a connection blip.
      if (!TRANSPORT_ERROR.test(String((err && err.message) || err))) throw err;
      lastErr = err;
      if (attempt < MINT_ATTEMPTS) {
        await new Promise((resolve) => setTimeout(resolve, MINT_BACKOFF_MS * attempt));
      }
    }
  }
  throw lastErr;
}

module.exports = { mintSession, MINT_ATTEMPTS, MINT_PATH, TRANSPORT_ERROR };
