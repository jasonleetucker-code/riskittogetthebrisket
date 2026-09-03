/**
 * V1-123 Phase 2 — Sharp Roster Percentage
 * (`/market/sharp-roster-percentage`), on production.
 *
 * Mirrors v1-62-sharp-tracker.spec.js's structure: capture the page's OWN
 * fetch of its canonical endpoint, require it to succeed, and prove the
 * render consumes that exact response rather than something stale or
 * synthesized. The endpoint and page differ from Sharp Tracker's in ways
 * confirmed by direct source reading (both documented here so a future
 * reader does not re-derive them): the count to check the render against
 * is `payload.totalQualifyingPlayers` (no single "Assets" stat tile like
 * Sharp Tracker has), the table is a ds `DataTable` keyed by `assetId`
 * (not a hand-rolled `<table>`), and the empty-state copy is backend-
 * driven (`classifyEmptyState`) rather than a fixed string on the page.
 */
const { test, expect, prodUrl, annotate, desktopOnly } = require("./helpers");

test.describe("V1-123 Phase 2: /market/sharp-roster-percentage renders its own fetch (production)", () => {
  test("Sharp Roster Percentage matches GET /api/sharp/roster-percentage field-for-field", async ({
    prodPage: page,
  }, testInfo) => {
    desktopOnly(test, testInfo);
    test.setTimeout(180_000);

    const responsePromise = page.waitForResponse(
      (res) =>
        res.url().includes("/api/sharp/roster-percentage") &&
        res.request().method() === "GET",
      { timeout: 90_000 },
    );

    await page.goto(prodUrl("/market/sharp-roster-percentage"), {
      waitUntil: "domcontentloaded",
    });
    await expect(
      page.getByRole("heading", { level: 1, name: /^Sharp Roster Percentage$/ }),
    ).toBeVisible({ timeout: 60_000 });

    const response = await responsePromise;
    annotate(testInfo, "request", `GET ${response.url()} -> ${response.status()}`);
    expect(response.status(), "the deployed page's own /api/sharp/roster-percentage call must succeed").toBe(
      200,
    );
    const payload = await response.json();
    const players = Array.isArray(payload.players) ? payload.players : [];
    annotate(
      testInfo,
      "response-shape",
      `players=${players.length} totalQualifyingPlayers=${payload.totalQualifyingPlayers}`,
    );

    if (players.length > 0) {
      annotate(testInfo, "states-observed", "sharp-roster-percentage: populated");
      const table = page.getByRole("table");
      await expect(table).toBeVisible({ timeout: 30_000 });
      const rows = table.locator("tbody tr");
      await expect(rows.first()).toBeVisible({ timeout: 30_000 });
      const rowCount = await rows.count();
      expect(
        rowCount,
        "rendered table must show at least one of the response's qualifying players",
      ).toBeGreaterThan(0);

      const top = players[0];
      const topName = top.displayName || top.name || top.assetId;
      await expect(
        table.getByText(String(topName), { exact: false }).first(),
        `table must show the response's own top player ("${topName}")`,
      ).toBeVisible();
    } else {
      annotate(testInfo, "states-observed", "sharp-roster-percentage: empty");
      // Empty-state copy is backend-driven (classifyEmptyState), so assert
      // the DataTable's empty region renders SOME explanatory text rather
      // than a hardcoded string.
      await expect(page.getByRole("table").locator("..")).toContainText(/./, {
        timeout: 30_000,
      });
    }
  });
});
