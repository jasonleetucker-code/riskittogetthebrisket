/**
 * Critical journey: /news tab.
 *
 * This spec used to skip itself when /news returned 404, because the
 * page had not shipped yet.  It shipped in #533 — and at that moment
 * the guard inverted from useful to harmful: a route regression back
 * to 404 would have been reported as a SKIP, not a failure, and a
 * skipped test is invisible in a green run.
 *
 * The route existing is now part of what this spec asserts.
 *
 * Auth: test-only session fixture (skips when E2E_TEST_SECRET unset).
 */
const { test, expect } = require("../helpers/auth-fixture");
const { desktopOnly, attachConsoleGuards, pageUrl } = require("../helpers/journey");

test.describe("journey: /news tab", () => {
  test.beforeEach(async ({}, testInfo) => desktopOnly(test, testInfo));

  test("/news renders", async ({ authedPage: page }) => {
    // The route must exist.  Checked before navigating so a 404 is
    // reported as "the route is gone" rather than as a render failure.
    const probe = await page.request.get(pageUrl("/news"), { maxRedirects: 0 });
    expect(
      probe.status(),
      "/news must exist — it shipped in #533; a 404 here is a route regression",
    ).toBeLessThan(400);

    const guard = attachConsoleGuards(page);
    const res = await page.goto(pageUrl("/news"), { waitUntil: "domcontentloaded", timeout: 30_000 });
    expect(res?.status(), "/news should not error").toBeLessThan(400);

    // Behavior-level assertion only: the page renders a news surface
    // with non-trivial content.  We deliberately don't pin layout —
    // the page is brand new and will evolve.
    await expect(page.locator("body")).toContainText(/news/i, { timeout: 30_000 });
    await expect
      .poll(async () => (await page.locator("body").innerText()).trim().length, {
        message: "/news should render real content, not a blank shell",
        timeout: 30_000,
      })
      .toBeGreaterThan(200);

    guard.assertClean();
  });
});
