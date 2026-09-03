/**
 * V1-123 Phase 2 — Insider Trading (`/league/insider-trading`), on
 * production.
 *
 * No local spec exists to port from — zero coverage anywhere before this.
 * Written fresh against frontend/app/league/insider-trading/page.jsx.
 * States are read from production as they naturally occur (no snapshot
 * yet / stale / populated / no tracked activity), never manufactured.
 */
const { test, expect, prodUrl, annotate } = require("./helpers");

test.describe("V1-123 Phase 2: Insider Trading (production)", () => {
  test("the intel table renders real activity or an explicit named empty/staleness state on production", async ({
    prodPage: page,
  }, testInfo) => {
    await page.goto(prodUrl("/league/insider-trading"), { waitUntil: "domcontentloaded" });

    await expect(page.getByRole("heading", { level: 1, name: "Insider Trading" })).toBeVisible({
      timeout: 60_000,
    });

    const noSnapshot = page.getByText(/No intel snapshot yet/i);
    const staleBanner = page.getByText(/Stale intel:/i);
    const noActivity = page.getByText(/No tracked activity yet/i);
    const couldntLoad = page.getByText(/Couldn't load insider activity/i);
    const table = page.getByRole("table");

    const settled = table.or(noSnapshot).or(noActivity).or(couldntLoad);
    await expect(settled.first()).toBeVisible({ timeout: 60_000 });

    const hasTable = await table.isVisible().catch(() => false);
    const isStale = await staleBanner.isVisible().catch(() => false);

    if (hasTable) {
      const rows = table.locator("tbody tr");
      const rowCount = await rows.count();
      expect(rowCount, "insider table rendered but has no rows").toBeGreaterThan(0);
      annotate(
        testInfo,
        "states-observed",
        `insider-trading: populated (${rowCount} rows)${isStale ? ", stale banner shown" : ""}`,
      );

      // Row expansion: clicking the top asset row must reveal its evidence tab.
      await rows.first().click();
      await expect(page.getByText(/League-mate/i).or(page.getByText(/Loading member exposure/i))).toBeVisible({
        timeout: 30_000,
      });
    } else {
      const empty = (await noSnapshot.isVisible().catch(() => false))
        ? "no-snapshot-yet"
        : (await noActivity.isVisible().catch(() => false))
          ? "no-tracked-activity"
          : "couldnt-load";
      annotate(testInfo, "states-observed", `insider-trading: ${empty}`);
    }
  });
});
