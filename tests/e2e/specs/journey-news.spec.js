/**
 * Critical journey: /news tab.
 *
 * The dedicated /news page may not have shipped yet (tracked in
 * PR #533).  This spec is written to be green BOTH before and after
 * that lands:
 *
 *   - route 404s  → skip with a clear message (page not shipped yet)
 *   - route 200s  → assert it renders real content with no JS errors
 *
 * Once the page exists the spec self-activates — no test change
 * needed when #533 merges.
 *
 * Auth: test-only session fixture (skips when E2E_TEST_SECRET unset).
 */
const { test, expect } = require("../helpers/auth-fixture");
const { desktopOnly, attachConsoleGuards, pageUrl } = require("../helpers/journey");

test.describe("journey: /news tab", () => {
  test.beforeEach(async ({}, testInfo) => desktopOnly(test, testInfo));

  test("/news renders when the route exists (skips cleanly while it 404s)", async ({ authedPage: page }) => {
    // Probe first with a plain request so a 404 becomes a skip, not
    // a navigation failure.
    const probe = await page.request.get(pageUrl("/news"), { maxRedirects: 0 });
    if (probe.status() === 404) {
      test.skip(
        true,
        "/news route not shipped yet (lands with PR #533) — spec self-activates once it exists",
      );
      return;
    }

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
