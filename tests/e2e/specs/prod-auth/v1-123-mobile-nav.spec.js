/**
 * V1-123 Phase 1 — mobile bottom-navigation tab bar on the DEPLOYED
 * production site.
 *
 * Ports the one behavior from ../mobile-smoke.spec.js not already
 * covered by an existing prod-auth spec: the R1 shell's mobile tab bar
 * (.shell-tabbar) is visible and actually navigates between tabs. The
 * other two mobile-smoke assertions (rankings board renders rows on a
 * phone viewport; player popup opens/closes) are already exercised on
 * production by v1-123-rankings-journeys.spec.js, which runs on both
 * the prod-desktop and prod-mobile projects — porting them again here
 * would be a duplicate, not new coverage.
 *
 * mobile-viewport only (prod-mobile project); skips cleanly on
 * prod-desktop via the shared mobileOnly() helper.
 */
const { test, expect, prodUrl, mobileOnly, annotate } = require("./helpers");

const BOARD_ROW = ".ds-table-wrap table tbody tr.rankings-row-clickable";

test.describe("V1-123 Phase 1: mobile bottom navigation (production)", () => {
  test.beforeEach(async ({}, testInfo) => mobileOnly(test, testInfo));

  test("bottom navigation is visible and navigates between tabs on production", async ({
    prodPage: page,
  }, testInfo) => {
    await page.goto(prodUrl("/rankings"), { waitUntil: "domcontentloaded" });

    const nav = page.locator(".shell-tabbar");
    await expect(nav, "mobile tab bar should render on production").toBeVisible({
      timeout: 30_000,
    });

    // Auth-gated tabs render once the client auth check resolves.
    await expect(nav.getByText("News", { exact: true })).toBeVisible({ timeout: 30_000 });
    for (const label of ["Home", "Ranks", "Trade", "News", "Menu"]) {
      await expect(nav.getByText(label, { exact: true })).toBeVisible();
    }
    annotate(testInfo, "tabbar", "all five tabs (Home/Ranks/Trade/News/Menu) rendered");

    await nav.getByText("Trade", { exact: true }).click();
    await expect(page).toHaveURL(/\/trade/, { timeout: 15_000 });

    await nav.getByText("Ranks", { exact: true }).click();
    await expect(page).toHaveURL(/\/rankings/, { timeout: 15_000 });
    await expect(page.locator(BOARD_ROW).first()).toBeVisible({ timeout: 60_000 });
    annotate(testInfo, "tab-navigation", "Trade -> Ranks round trip landed on the real board");
  });
});
