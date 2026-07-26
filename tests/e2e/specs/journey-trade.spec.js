/**
 * Critical journey: trade surfaces.
 *
 *   - /trade   — the trade builder (calculator) renders and accepts input
 *   - /trades  — trade history page renders (cards or explicit empty state)
 *   - /finder  — the arbitrage-finder board renders result rows
 *   - POST /api/trade/finder — the KTC arbitrage engine returns trades
 *     for a real roster (API-level: no UI consumes this endpoint today,
 *     but the engine is a product surface the redesign must not break)
 *
 * Auth: test-only session fixture (skips when E2E_TEST_SECRET unset).
 */
const { test, expect } = require("../helpers/auth-fixture");
const { desktopOnly, attachConsoleGuards, pageUrl } = require("../helpers/journey");

test.describe("journey: trade surfaces", () => {
  test.beforeEach(async ({}, testInfo) => desktopOnly(test, testInfo));

  test("/trade renders the builder with working controls", async ({ authedPage: page }) => {
    const guard = attachConsoleGuards(page);
    await page.goto(pageUrl("/trade"), { waitUntil: "domcontentloaded" });

    // Header renders, then the player pool finishes loading (the
    // "Loading player pool..." sentinel clears once /api/data lands).
    await expect(page.locator("body")).toContainText(/Trade Builder/i, { timeout: 30_000 });
    await page.waitForFunction(
      () => !document.body.innerText.includes("Loading player pool..."),
      null,
      { timeout: 60_000 },
    );

    // Core builder controls exist once data is ready.
    await expect(page.getByRole("button", { name: /Swap Sides|Rotate Sides/ })).toBeVisible();
    await expect(page.getByRole("button", { name: /Clear Trade/ })).toBeVisible();

    guard.assertClean();
  });

  test("/trades renders history (real trades or explicit empty state)", async ({ authedPage: page }) => {
    const guard = attachConsoleGuards(page);
    await page.goto(pageUrl("/trades"), { waitUntil: "domcontentloaded" });

    await page.waitForFunction(
      () => !document.body.innerText.includes("Loading trade data..."),
      null,
      { timeout: 60_000 },
    );

    // Either populated history or the explicit empty state — never a
    // blank page or a crash.
    await expect(page.locator("body")).toContainText(/Trade History|No trades found/i, {
      timeout: 15_000,
    });

    guard.assertClean();
  });

  test("/finder renders the arbitrage board with result rows", async ({ authedPage: page }) => {
    const guard = attachConsoleGuards(page);
    await page.goto(pageUrl("/finder"), { waitUntil: "domcontentloaded" });

    await expect(page.locator("body")).toContainText(/Finder/i, { timeout: 30_000 });

    // Data-driven: the results table materializes once /api/data lands.
    const rows = page.locator(".table-wrap table tbody tr");
    await expect(rows.first(), "finder should render result rows").toBeVisible({
      timeout: 60_000,
    });
    expect(await rows.count()).toBeGreaterThan(5);

    // The match-count line reflects a populated board.
    await expect(page.locator("body")).toContainText(/\d[\d,]* players? match/i);

    guard.assertClean();
  });

  test("POST /api/trade/finder returns arbitrage trades for a real roster", async ({ authedPage: page }) => {
    // Pull a real team name from the live contract — no hardcoded names.
    const dataRes = await page.request.get("/api/data?view=app");
    expect(dataRes.status()).toBe(200);
    const contract = await dataRes.json();
    const teams = contract?.sleeper?.teams || [];
    test.skip(teams.length === 0, "no sleeper rosters in the loaded contract");

    const myTeam = teams[0].name;
    const res = await page.request.post("/api/trade/finder", {
      data: { myTeam, opponentTeams: ["all"] },
    });
    expect(res.status(), await res.text().catch(() => "")).toBe(200);
    const body = await res.json();

    expect(Array.isArray(body.trades), "finder response must carry a trades array").toBeTruthy();
    expect(body).toHaveProperty("metadata");
    expect(body).toHaveProperty("leagueKey");

    // When trades exist, each has both sides populated with valued assets.
    for (const trade of body.trades.slice(0, 5)) {
      expect(Array.isArray(trade.give)).toBeTruthy();
      expect(Array.isArray(trade.receive)).toBeTruthy();
      expect(trade.give.length).toBeGreaterThan(0);
      expect(trade.receive.length).toBeGreaterThan(0);
      for (const asset of [...trade.give, ...trade.receive]) {
        expect(String(asset.name || "").length).toBeGreaterThan(0);
      }
    }
  });
});
