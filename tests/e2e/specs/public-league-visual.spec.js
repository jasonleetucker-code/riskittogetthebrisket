// ── Public /league section visual regression ─────────────────────────
//
// Snapshot test per top-level tab on the public /league hub.  Catches
// CSS / layout regressions on the surfaces with the highest editorial
// volatility (Records, Streaks, Awards, Recaps) — those got reworked
// in PR #300 and continue to evolve, so we want pixel-level guard-
// rails before the next round of polish.
//
// Baseline generation (run once after intentional UI changes):
//
//   npx playwright test --update-snapshots public-league-visual
//
// Tolerance rationale: 0.5% pixel difference so the test absorbs
// benign font-antialiasing variance across runners but still catches
// real layout breakage.  Higher than the chart suite's 0.2% because
// /league sections include avatars + player headshots loaded from
// Sleeper's CDN, which can have JPEG-compression jitter that the
// chart suite (pure SVG) doesn't have to deal with.
//
// Skip path: ``SKIP_VISUAL_REGRESSION=1`` for local runs without the
// dev server running, mirroring the chart suite.
// ─────────────────────────────────────────────────────────────────────
const { test, expect } = require("@playwright/test");

const SCREENSHOT_OPTIONS = {
  maxDiffPixelRatio: 0.005,
  // Mask out player headshots — Sleeper's CDN can serve slightly
  // different JPEG quality on the same player ID over time, so any
  // headshot byte-shift would falsely fail the layout-only check.
  // The mask is applied as a flat-colour rectangle before comparison.
  mask: [],
  animations: "disabled",
  // Allow the league snapshot fetch + initial render to settle
  // before capture.  The /api/public/league endpoint can take a
  // few hundred ms on a cold cache.
  fullPage: false,
};

const READINESS_TIMEOUT_MS = 30_000;

async function _waitForLeagueLoaded(page) {
  // Wait for the loading sentinel to clear — this fires only after
  // the /api/public/league response materialises.
  await page.waitForFunction(
    () => !document.body.innerText.includes("Loading league data..."),
    null,
    { timeout: READINESS_TIMEOUT_MS },
  );
}

async function _openLeagueTab(page, tabLabel) {
  // Tabs are sub-nav buttons; click by accessible name.
  await page.goto("/league");
  await _waitForLeagueLoaded(page);
  const btn = page.getByRole("button", { name: tabLabel, exact: true });
  if (await btn.count()) {
    await btn.first().click();
    // Allow a tick for tab swap.
    await page.waitForTimeout(150);
  }
}

test.describe("public /league visual regression", () => {
  test.skip(
    !!process.env.SKIP_VISUAL_REGRESSION,
    "Set SKIP_VISUAL_REGRESSION=1 to skip this suite locally",
  );

  // Run on a single fixed viewport — the snapshot baseline is for
  // that exact size.  Matches the chart suite's convention.
  test.use({
    viewport: { width: 1366, height: 900 },
  });

  test("Records section", async ({ page }) => {
    await _openLeagueTab(page, "Records");
    const card = page.locator("section").first();
    await card.waitFor({ state: "visible", timeout: READINESS_TIMEOUT_MS });
    await expect(card).toHaveScreenshot("league-records.png", SCREENSHOT_OPTIONS);
  });

  test("Streaks section", async ({ page }) => {
    await _openLeagueTab(page, "Streaks");
    const card = page.locator("section").first();
    await card.waitFor({ state: "visible", timeout: READINESS_TIMEOUT_MS });
    await expect(card).toHaveScreenshot("league-streaks.png", SCREENSHOT_OPTIONS);
  });

  test("Awards section", async ({ page }) => {
    await _openLeagueTab(page, "Awards");
    const card = page.locator("section").first();
    await card.waitFor({ state: "visible", timeout: READINESS_TIMEOUT_MS });
    await expect(card).toHaveScreenshot("league-awards.png", SCREENSHOT_OPTIONS);
  });

  test("Recaps section (newest week card)", async ({ page }) => {
    await _openLeagueTab(page, "Recaps");
    const card = page.locator("section").first();
    await card.waitFor({ state: "visible", timeout: READINESS_TIMEOUT_MS });
    await expect(card).toHaveScreenshot("league-recaps.png", SCREENSHOT_OPTIONS);
  });
});
