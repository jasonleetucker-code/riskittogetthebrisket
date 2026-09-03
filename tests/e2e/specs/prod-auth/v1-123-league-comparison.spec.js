/**
 * V1-123 Phase 2 — League Comparison (`/league-comparison`), on
 * production.
 *
 * No local spec exists to port from — zero coverage anywhere before this.
 * Written fresh against frontend/app/league-comparison/page.jsx +
 * sections/HeaderCard.jsx. The first hit can take 30+ seconds (documented
 * in the page's own loading copy — historical NFL stats download on a
 * cold cache), so this test's timeout is generous by design, not padding.
 */
const { test, expect, prodUrl, annotate } = require("./helpers");

test.describe("V1-123 Phase 2: League Comparison (production)", () => {
  test("the summary tab renders real league metadata or an explicit unavailable state on production", async ({
    prodPage: page,
  }, testInfo) => {
    test.setTimeout(120_000);
    await page.goto(prodUrl("/league-comparison"), { waitUntil: "domcontentloaded" });

    await expect(page.getByRole("heading", { level: 1, name: "Scoring Comparison" })).toBeVisible({
      timeout: 60_000,
    });

    const myLeague = page.getByText("My League", { exact: false });
    const unavailable = page.getByText(/League comparison unavailable/i);
    const settled = myLeague.or(unavailable);
    await expect(settled.first()).toBeVisible({ timeout: 90_000 });

    const populated = await myLeague.isVisible().catch(() => false);
    if (populated) {
      await expect(page.getByText("Standard Baseline", { exact: false })).toBeVisible({
        timeout: 15_000,
      });
      const tabs = ["Positional", "Flex", "Year-by-Year", "Methodology"];
      for (const label of tabs) {
        const tab = page.getByRole("button", { name: label }).or(page.getByRole("link", { name: label }));
        if (await tab.first().isVisible().catch(() => false)) {
          await tab.first().click();
          await expect(page.locator("body")).not.toContainText(/League comparison unavailable/i);
        }
      }
      annotate(testInfo, "states-observed", "league-comparison: populated, tabs navigable");
    } else {
      annotate(testInfo, "states-observed", "league-comparison: unavailable (explicit)");
    }
  });
});
