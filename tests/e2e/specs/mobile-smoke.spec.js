/**
 * Mobile viewport smoke — 390x844 (mobile-chromium project).
 *
 * The redesign safety net's mobile layer: proves the core surfaces
 * stay USABLE on a phone-sized viewport, not just technically
 * rendered.  Coverage:
 *
 *   - rankings board renders real rows at 390px
 *   - player popup opens and closes
 *   - bottom navigation is visible and actually navigates
 *
 * Runs only on the mobile-chromium project (chromium with a 390x844
 * viewport — see playwright.config.js).  The webkit device projects
 * (mobile-390/mobile-430) also match this file if explicitly run,
 * but the spec skips there so a missing webkit install can't fail
 * the suite.
 *
 * Auth: test-only session fixture (skips when E2E_TEST_SECRET unset).
 */
const { test, expect } = require("../helpers/auth-fixture");
const {
  SEL,
  mobileOnly,
  gotoRankingsBoard,
  boardRowCount,
  attachConsoleGuards,
  pageUrl,
  pageHeading,
  titleFor,
} = require("../helpers/journey");

test.describe("mobile smoke (390x844)", () => {
  test.beforeEach(async ({}, testInfo) => mobileOnly(test, testInfo));

  test("rankings board renders rows on a phone viewport", async ({ authedPage: page }) => {
    const guard = attachConsoleGuards(page);
    const rows = await gotoRankingsBoard(page);
    // The board HOLDS >= 50 rows; it MOUNTS however many the window
    // needs.  Counting <tr> here asserted the two together, and the
    // board is windowed now — see the note in journey.js::gotoRankingsBoard.
    // Both halves are still checked, because "1,109 rows and none of them
    // painted" and "40 rows painted out of 40" are different failures.
    expect(await boardRowCount(page)).toBeGreaterThanOrEqual(50);
    expect(await rows.count(), "no rows mounted on a phone viewport").toBeGreaterThan(0);

    // No horizontal overflow of the page body — the board must scroll
    // inside its own container, not stretch the viewport.
    const overflow = await page.evaluate(
      () => document.documentElement.scrollWidth - document.documentElement.clientWidth,
    );
    expect(overflow, "page should not overflow horizontally on mobile").toBeLessThanOrEqual(24);

    guard.assertClean();
  });

  test("player popup opens and closes on mobile", async ({ authedPage: page }) => {
    await gotoRankingsBoard(page);

    await page.locator(SEL.playerName).first().click();
    const sheet = page.locator(SEL.overlaySheet).first();
    await expect(sheet).toBeVisible({ timeout: 15_000 });
    await expect(sheet).toContainText(/Our Value/i);

    await page.getByRole("button", { name: /close player details/i }).click();
    await expect(sheet).not.toBeVisible();
  });

  test("bottom navigation is visible and navigates between tabs", async ({ authedPage: page }) => {
    // Through the Next origin, like every other page navigation — the
    // backend's page proxy serves a different (logged-out) shell for
    // some routes, which makes tab-navigation assertions test the
    // wrong chrome.  See pageUrl() in helpers/journey.js.
    await page.goto(pageUrl("/rankings"), { waitUntil: "domcontentloaded" });

    // R1 shell: the mobile tab bar is the .shell-tabbar navigation
    // (labelled "Primary", same IA model as desktop).
    const nav = page.locator(".shell-tabbar");
    await expect(nav).toBeVisible({ timeout: 30_000 });

    // The auth-gated tabs (Ranks/Trade/News) only render once the
    // client auth check resolves — wait for the last one with a
    // generous budget, then assert the full set (+ the Menu drawer
    // button that replaces the legacy More hub).
    await expect(nav.getByText("News", { exact: true })).toBeVisible({ timeout: 30_000 });
    for (const label of ["Home", "Ranks", "Trade", "News", "Menu"]) {
      await expect(nav.getByText(label, { exact: true })).toBeVisible();
    }

    // Tapping Trade navigates to the trade builder.
    await nav.getByText("Trade", { exact: true }).click();
    await expect(page).toHaveURL(/\/trade/, { timeout: 15_000 });
    await expect(pageHeading(page, titleFor("/trade"))).toBeVisible({
      timeout: 30_000,
    });

    // Tapping Ranks navigates back to the board.
    await nav.getByText("Ranks", { exact: true }).click();
    await expect(page).toHaveURL(/\/rankings/, { timeout: 15_000 });
    await expect(page.locator(SEL.boardRow).first()).toBeVisible({ timeout: 60_000 });
  });
});
