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
const {
  desktopOnly,
  attachConsoleGuards,
  pageUrl,
  SEL,
  pageHeading,
  titleFor,
} = require("../helpers/journey");

test.describe("journey: trade surfaces", () => {
  test.beforeEach(async ({}, testInfo) => desktopOnly(test, testInfo));

  test("/trade renders the builder with working controls", async ({ authedPage: page }) => {
    const guard = attachConsoleGuards(page);
    await page.goto(pageUrl("/trade"), { waitUntil: "domcontentloaded" });

    // Header renders, then the player pool finishes loading (the
    // "Loading player pool..." sentinel clears once /api/data lands).
    // Was `body` + /Trade Builder/i: loose on a nav label present on
    // every authed page (so it passed with <main> deleted — see
    // docs/e2e-assertion-audit.md) AND wrong after the #625 rename.
    // The page's own <h1>, anchored to the canon, fixes both.
    await expect(pageHeading(page, titleFor("/trade"))).toBeVisible({
      timeout: 30_000,
    });
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

    // R4 replaced the "Loading trade data..." sentinel with a skeleton,
    // so waiting for that string to vanish is now vacuous — and the
    // page title renders immediately, which would make the old
    // assertion pass before any data landed.  Wait for real settled
    // content instead: either a ledger entry or the explicit empty
    // state.  Both are data-driven; neither exists mid-load.
    const settled = page
      .locator(SEL.tradeLedgerEntry)
      .or(page.getByText(/No trades found/i));
    await expect(settled.first()).toBeVisible({ timeout: 60_000 });

    guard.assertClean();
  });

  test("/finder renders the arbitrage board with result rows", async ({ authedPage: page }) => {
    const guard = attachConsoleGuards(page);
    await page.goto(pageUrl("/finder"), { waitUntil: "domcontentloaded" });

    await expect(page.locator("body")).toContainText(/Finder/i, { timeout: 30_000 });

    // Data-driven: the results table materializes once /api/data lands.
    // Accepts the legacy `.table-wrap` and the ds `DataTable` wrapper the
    // redesign moves these pages onto, so this spec spans the rebuild
    // instead of needing a flag-day edit the day R3 lands.
    const rows = page.locator(
      ".table-wrap table tbody tr, .ds-table-wrap table tbody tr",
    );
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
    // Was `test.skip(teams.length === 0, ...)`.  The committed snapshot
    // carries 12 Sleeper teams (verified 2026-07-27), so the gate never
    // fired — and it masked exactly the documented multi-league failure
    // mode (`sleeperDataReady: false`), reporting an empty roster
    // pipeline as "nothing to test" inside a green run.  Assert the
    // precondition instead so that regression fails loudly.
    expect(
      teams.length,
      "contract served no Sleeper rosters — the finder cannot be exercised, " +
        "and this is the sleeperDataReady:false regression, not an absent fixture",
    ).toBeGreaterThan(0);

    const myTeam = teams[0].name;
    const res = await page.request.post("/api/trade/finder", {
      data: { myTeam, opponentTeams: ["all"] },
    });
    expect(res.status(), await res.text().catch(() => "")).toBe(200);
    const body = await res.json();

    expect(Array.isArray(body.trades), "finder response must carry a trades array").toBeTruthy();
    expect(body).toHaveProperty("metadata");
    expect(body).toHaveProperty("leagueKey");

    // Without this, the loop below never executes on an empty array and
    // a test named "returns arbitrage trades for a real roster" passes
    // when the engine returns none — which is exactly the regression
    // #556 fixed (the finder silently dropping every IDP asset).  The
    // structural check has to come before the per-trade checks.
    expect(
      body.trades.length,
      "finder returned zero trades for a real roster — the engine is dropping assets",
    ).toBeGreaterThan(0);

    // Each has both sides populated with valued assets.
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
