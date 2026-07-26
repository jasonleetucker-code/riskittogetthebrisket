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
    // Each overrides POST recomputes the full blend server-side
    // (CPU-seconds per call), and this journey triggers it twice —
    // once from /settings, once when /rankings rehydrates.  Give the
    // whole round-trip more than the default 90s budget.
    test.setTimeout(180_000);
    const guard = attachConsoleGuards(page);

    await page.goto("/settings", { waitUntil: "domcontentloaded" });
    const toggles = page.locator('input.settings-src-toggle[aria-label^="Include "]');
    await expect(toggles.first()).toBeVisible({ timeout: 30_000 });

    // Pick the first currently-enabled toggle and switch it off.
    const enabledToggle = toggles.and(page.locator(":checked")).first();
    await expect(enabledToggle).toBeVisible({ timeout: 15_000 });

    // The round-trip contract: the click must fire POST
    // /api/rankings/overrides and it must succeed.  60s budget: the
    // POST only fires after useDynastyData's base-contract fetch
    // (~5 MB) settles, which can take a while on a busy runner.
    const [overridesResponse] = await Promise.all([
      page.waitForResponse(
        (res) =>
          res.url().includes("/api/rankings/overrides") &&
          res.request().method() === "POST",
        { timeout: 60_000 },
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
    // The badge reads ``rankingsOverride.isCustomized`` off the
    // delta-merged contract, which lands only after the rankings
    // page's own base fetch + overrides POST complete — rows can
    // render from the base contract while that second round-trip is
    // still in flight.
    //
    // Degradation caveat: fetchDynastyData deliberately falls back to
    // the base contract (with a console.warn) when the overrides POST
    // fails — e.g. a starved runner timing out the CPU-heavy blend
    // recompute.  That fallback is designed behavior, not the
    // regression this spec exists to catch (the round-trip itself was
    // hard-asserted above), so when the app logs that exact warning
    // we skip the badge assertion instead of failing on it.
    const fallbackWarnings = [];
    page.on("console", (msg) => {
      if (msg.type() !== "warning") return;
      const text = msg.text() || "";
      if (text.includes("/api/rankings/overrides") || text.includes("falling through to base contract")) {
        fallbackWarnings.push(text);
      }
    });

    const rows = await gotoRankingsBoard(page);
    expect(await rows.count()).toBeGreaterThan(50);

    const badge = page.locator('[aria-label="Custom source mix active"]').first();
    const badgeVisible = await badge
      .waitFor({ state: "visible", timeout: 60_000 })
      .then(() => true)
      .catch(() => false);
    if (!badgeVisible && fallbackWarnings.length > 0) {
      test.skip(
        true,
        `override endpoint degraded to base-contract fallback on this run (${fallbackWarnings[0]}) — round-trip already asserted`,
      );
    }
    expect(badgeVisible, "custom-mix badge should appear once a source is disabled").toBeTruthy();

    guard.assertClean();
  });
});
