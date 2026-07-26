/**
 * Critical journey: settings source-toggle round-trip.
 *
 * The single-source-of-truth override path (see CLAUDE.md):
 * toggling a source on /settings must fire POST
 * /api/rankings/overrides (the backend recomputes the blend — there
 * is NO frontend ranking engine) and the rankings board must
 * re-render from the delta with the custom-mix indicator visible.
 *
 * Auth: test-only session fixture (skips when E2E_TEST_SECRET unset).
 * State: settings live in localStorage — each test gets a fresh
 * browser context, so toggles never leak between tests.
 */
const { test, expect } = require("../helpers/auth-fixture");
const {
  desktopOnly,
  gotoRankingsBoard,
  attachConsoleGuards,
} = require("../helpers/journey");

test.describe("journey: settings source toggles", () => {
  test.beforeEach(async ({}, testInfo) => desktopOnly(test, testInfo));

  test("settings lists every registered ranking source with a toggle", async ({ authedPage: page }) => {
    // Authoritative registry size from the backend.
    const regRes = await page.request.get("/api/rankings/sources");
    expect(regRes.status()).toBe(200);
    const registry = await regRes.json();
    const sources = registry.sources || registry;
    const registeredCount = Array.isArray(sources)
      ? sources.length
      : Object.keys(sources).length;
    expect(registeredCount).toBeGreaterThan(3);

    await page.goto("/settings", { waitUntil: "domcontentloaded" });
    await expect(page.locator("body")).toContainText(/Ranking Sources/i, { timeout: 30_000 });

    // One include-in-blend toggle per registered dynasty source.
    const toggles = page.locator('input.settings-src-toggle[aria-label^="Include "]');
    await expect(toggles.first()).toBeVisible({ timeout: 30_000 });
    expect(await toggles.count()).toBeGreaterThanOrEqual(registeredCount);
  });

  test("toggling a source fires the overrides request and updates the board", async ({ authedPage: page }) => {
    const guard = attachConsoleGuards(page);

    await page.goto("/settings", { waitUntil: "domcontentloaded" });
    const toggles = page.locator('input.settings-src-toggle[aria-label^="Include "]');
    await expect(toggles.first()).toBeVisible({ timeout: 30_000 });

    // Pick the first currently-enabled toggle and switch it off.
    const enabledToggle = toggles.and(page.locator(":checked")).first();
    await expect(enabledToggle).toBeVisible({ timeout: 15_000 });

    // The round-trip contract: the click must fire POST
    // /api/rankings/overrides and it must succeed.
    const [overridesResponse] = await Promise.all([
      page.waitForResponse(
        (res) =>
          res.url().includes("/api/rankings/overrides") &&
          res.request().method() === "POST",
        { timeout: 30_000 },
      ),
      enabledToggle.click(),
    ]);
    expect(
      overridesResponse.status(),
      "overrides endpoint should recompute the blend successfully",
    ).toBe(200);
    const delta = await overridesResponse.json();
    // The delta payload carries recomputed per-player fields.
    const playerBlock = delta.players || delta.playersDelta || delta;
    expect(Object.keys(playerBlock).length).toBeGreaterThan(0);

    // The board must re-render from the recomputed blend and surface
    // the custom-mix indicator so the user knows they're off-default.
    const rows = await gotoRankingsBoard(page);
    expect(await rows.count()).toBeGreaterThan(50);
    await expect(
      page.locator('[aria-label="Custom source mix active"]').first(),
      "custom-mix badge should appear once a source is disabled",
    ).toBeVisible({ timeout: 30_000 });

    guard.assertClean();
  });
});
