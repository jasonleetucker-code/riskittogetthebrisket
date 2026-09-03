/**
 * V1-123 Phase 2 — `/draft-capital`, on production.
 *
 * `/draft-capital` itself redirects to `/league?tab=draft-capital`
 * (confirmed by public-league.spec.js's existing redirect-only test,
 * which never asserts page content). This spec follows the redirect and
 * asserts real content from frontend/app/league/sections/draft-capital.jsx.
 * That component uses no CSS classes or test-ids anywhere (plain inline-
 * styled markup), so assertions here are necessarily text-content-based.
 */
const { test, expect, prodUrl, annotate } = require("./helpers");

test.describe("V1-123 Phase 2: /draft-capital (production)", () => {
  test("draft capital redirects to the league tab and renders real team totals or an explicit unavailable state", async ({
    prodPage: page,
  }, testInfo) => {
    const response = await page.goto(prodUrl("/draft-capital"), { waitUntil: "domcontentloaded" });
    expect(response, "production navigation returned no response for /draft-capital").toBeTruthy();

    const current = new URL(page.url());
    expect(
      current.pathname + current.search,
      "/draft-capital must redirect to /league?tab=draft-capital",
    ).toContain("tab=draft-capital");

    // The league tab picker's own <select> carries an <option>Draft
    // Capital</option> entry with the same text as the section's real
    // title -- getByText().first() picked that (hidden, since <option>
    // renders nothing visible outside an open native dropdown) instead of
    // the real on-page title. Filter to the visible match.
    const header = page
      .getByText("Draft Capital", { exact: false })
      .and(page.locator(":visible"))
      .first();
    const unavailable = page.getByText(/Draft capital unavailable/i);
    const settled = header.or(unavailable);
    await expect(settled.first()).toBeVisible({ timeout: 60_000 });

    const populated = await header.isVisible().catch(() => false);
    if (populated) {
      await expect(page.getByText(/draft ·.*teams ·.*rounds ·.*total budget/i)).toBeVisible({
        timeout: 30_000,
      });
      await expect(page.getByText("Pick Values", { exact: false })).toBeVisible({ timeout: 30_000 });
      annotate(testInfo, "states-observed", "draft-capital: populated");
    } else {
      annotate(testInfo, "states-observed", "draft-capital: unavailable (explicit)");
    }
  });
});
