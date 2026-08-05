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
  pageUrl,
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

    await page.goto(pageUrl("/settings"), { waitUntil: "domcontentloaded" });
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

    // Collect the app's base-contract fallback warnings from the START of
    // the journey.  This listener used to be attached further down, after
    // the first round-trip had already been asserted — so it watched an
    // arbitrary window that began once the thing it was diagnosing had
    // already succeeded.  Its output is now folded into the badge failure
    // message below, which is the only place it is read.
    const fallbackWarnings = [];
    page.on("console", (msg) => {
      if (msg.type() !== "warning") return;
      const text = msg.text() || "";
      if (text.includes("/api/rankings/overrides") || text.includes("falling through to base contract")) {
        fallbackWarnings.push(text);
      }
    });

    await page.goto(pageUrl("/settings"), { waitUntil: "domcontentloaded" });
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
    // This block used to `test.skip` when the badge never appeared AND
    // the app had logged its base-contract fallback warning.  That reads
    // as honest — the first round-trip IS hard-asserted above — but
    // docs/e2e-assertion-audit.md measured the skip firing ROUTINELY,
    // reason "...Failed to fetch".  A product degradation that reports as
    // a green skip is the one thing tests/e2e/README.md's convention 5
    // forbids: "Skip cleanly on absent INFRA — never on absent DATA."  A
    // degraded overrides endpoint is the product failing, not absent
    // infrastructure.
    //
    // The audit's own remedy was "a floor on consecutive skips, or
    // removal once the endpoint is reliable".  Playwright keeps no
    // cross-run state, so a consecutive-skip floor means a new counter
    // in e2e.yml — more machinery than the thing it guards, firing a day
    // late, and a second place where "green" gets computed.
    //
    // So: removal, with a MORE specific assertion in its place rather
    // than a weaker one.  /rankings fires its OWN overrides POST during
    // hydration; that second round-trip is what the badge depends on and
    // what the skip was silently forgiving.  Assert it directly, so a
    // failure says "the second overrides POST returned 503" instead of
    // "badge missing, cause unknown".  The underlying fragility is
    // docs/e2e-assertion-audit.md §3.3 — the Next proxy routes' hard 3s
    // abort — which is product-side and not this spec's to hide.
    //
    // Note this also restores guard.assertClean() below: test.skip()
    // throws, so on the skip path every browser console error collected
    // on this journey was discarded too.
    const rehydrateOverrides = page
      .waitForResponse(
        (res) =>
          res.url().includes("/api/rankings/overrides") &&
          res.request().method() === "POST",
        { timeout: 90_000 },
      )
      .catch(() => null);

    const rows = await gotoRankingsBoard(page);
    expect(await rows.count()).toBeGreaterThan(50);

    const rehydrateResponse = await rehydrateOverrides;
    expect(
      rehydrateResponse,
      "/rankings should re-fire the overrides POST on hydration — without it the custom mix is never applied",
    ).not.toBeNull();
    expect(
      rehydrateResponse.status(),
      "the /rankings-side overrides round-trip should also recompute successfully",
    ).toBe(200);

    const badge = page.locator('[aria-label="Custom source mix active"]').first();
    const badgeVisible = await badge
      .waitFor({ state: "visible", timeout: 60_000 })
      .then(() => true)
      .catch(() => false);
    expect(
      badgeVisible,
      `custom-mix badge should appear once a source is disabled${
        fallbackWarnings.length > 0
          ? ` — the app logged a base-contract fallback: ${fallbackWarnings[0]}`
          : ""
      }`,
    ).toBeTruthy();

    guard.assertClean();
  });
});
