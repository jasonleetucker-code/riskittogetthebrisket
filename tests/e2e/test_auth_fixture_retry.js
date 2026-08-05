/**
 * `mintSession` retries a dropped connection, and nothing else.
 *
 * WHY THIS FILE EXISTS
 *
 * The E2E session mint runs in the `authedPage` fixture before every authed
 * spec.  A single `ECONNRESET` there failed the spec outright; Playwright's
 * retry then passed it, and `failOnFlakyTests` turned the retried green into a
 * red job.  On 2026-08-05 that is exactly what happened to PR #741 — **0
 * failed, 2 flaky, 140 passed** — on two specs the PR did not touch.
 *
 * Retrying setup is only safe if it cannot also hide a real failure, so the
 * boundary is asserted here rather than left to the comment:
 *
 *   - transport error (no HTTP answer)  → retried, bounded at 3
 *   - ANY HTTP response, 5xx included   → returned untouched, never retried
 *   - a non-transport throw             → propagates on the FIRST attempt
 *   - all attempts reset                → rethrows, so stack-death still fires
 *
 * Run: node tests/e2e/test_auth_fixture_retry.js  (exit 0 = pass)
 * Also executed by tests/e2e/test_e2e_harness_guards.py.
 */

const assert = require("node:assert");
const { mintSession } = require("./helpers/mint-session");

/** A stand-in for Playwright's `page`, scripting one outcome per attempt. */
function fakePage(outcomes) {
  const calls = [];
  return {
    calls,
    request: {
      post: async (url, opts) => {
        calls.push({ url, opts });
        const next = outcomes.shift();
        if (next instanceof Error) throw next;
        return next;
      },
    },
  };
}

const okResponse = { ok: () => true, status: () => 200 };

async function main() {
  // 1. A clean mint calls once and returns the response.
  {
    const page = fakePage([okResponse]);
    const resp = await mintSession(page, "http://x", "s");
    assert.strictEqual(resp, okResponse);
    assert.strictEqual(page.calls.length, 1, "a clean mint must not retry");
    assert.strictEqual(
      page.calls[0].opts.headers.Authorization,
      "Bearer s",
      "the bearer secret must still be sent",
    );
  }

  // 2. One reset, then success — the case that was failing whole jobs.
  {
    const page = fakePage([new Error("apiRequestContext.post: read ECONNRESET"), okResponse]);
    const resp = await mintSession(page, "http://x", "s");
    assert.strictEqual(resp, okResponse);
    assert.strictEqual(page.calls.length, 2, "a reset must be retried exactly once here");
  }

  // 3. An HTTP response is NEVER retried — not even a 500.  This is the
  //    property that keeps the retry from laundering a real backend failure.
  {
    const five00 = { ok: () => false, status: () => 500 };
    const page = fakePage([five00, okResponse]);
    const resp = await mintSession(page, "http://x", "s");
    assert.strictEqual(resp, five00, "a 500 must be returned, not retried away");
    assert.strictEqual(page.calls.length, 1, "an HTTP answer must not trigger a retry");
  }

  // 4. A non-transport throw surfaces immediately, undisguised.
  {
    const boom = new TypeError("page.request.post is not a function");
    const page = fakePage([boom, okResponse]);
    await assert.rejects(() => mintSession(page, "http://x", "s"), /not a function/);
    assert.strictEqual(page.calls.length, 1, "a real error must not be retried");
  }

  // 5. A genuinely dead stack still fails, and still looks like a connection
  //    error, so stack-death-reporter.js keeps matching it.
  {
    const reset = () => new Error("apiRequestContext.post: read ECONNRESET");
    const page = fakePage([reset(), reset(), reset()]);
    await assert.rejects(() => mintSession(page, "http://x", "s"), /ECONNRESET/);
    assert.strictEqual(page.calls.length, 3, "must stop at the attempt bound");
  }

  console.log("auth-fixture mintSession: 5 assertions passed");
}

main().catch((err) => {
  console.error(err);
  process.exit(1);
});
