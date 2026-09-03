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

    // "Draft Capital" also exists as a hidden selected <option> in the
    // League tab picker, so it cannot be the populated-state signal.
    // "Pick Values" is rendered by the actual draft-capital section only.
    const populatedSignal = page.getByText("Pick Values", { exact: true }).first();
    const unavailable = page.getByText(/Draft capital unavailable/i);
    const settled = populatedSignal.or(unavailable);
    await expect(settled.first()).toBeVisible({ timeout: 60_000 });

    const populated = await populatedSignal.isVisible().catch(() => false);
    if (populated) {
      await expect(page.getByText(/draft ·.*teams ·.*rounds ·.*total budget/i)).toBeVisible({
        timeout: 30_000,
      });
      annotate(testInfo, "states-observed", "draft-capital: populated");
    } else {
      annotate(testInfo, "states-observed", "draft-capital: unavailable (explicit)");
    }
  });
});
