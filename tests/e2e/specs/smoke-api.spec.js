const { test, expect } = require("@playwright/test");
const {
  attachConsoleGuards,
  gotoApp,
  openTab,
  openMobilePrimary,
  isMobileProject,
} = require("../utils/app");

test.describe("startup + API sanity", () => {
  test("app boots, API contract fields exist, critical tabs render", async ({ page, request }, testInfo) => {
    const guard = attachConsoleGuards(page);
    await gotoApp(page, request);

    const statusResp = await request.get("/api/status");
    expect(statusResp.ok()).toBeTruthy();
    const status = await statusResp.json();
    const runningFlag =
      Object.prototype.hasOwnProperty.call(status, "running")
        ? status.running
        : status.is_running;
    expect(typeof runningFlag).toBe("boolean");

    if (status.frontend_runtime && typeof status.frontend_runtime === "object") {
      expect(String(status.frontend_runtime.active || "").length).toBeGreaterThan(0);
    } else {
      expect(status).toHaveProperty("has_data");
    }

    if (status.contract && typeof status.contract === "object") {
      expect(status.contract).toHaveProperty("version");
      expect(status.contract).toHaveProperty("health");
    }

    const dataResp = await request.get("/api/data?view=app");
    expect(dataResp.ok()).toBeTruthy();
    const data = await dataResp.json();
    expect(data).toHaveProperty("players");
    expect(data).toHaveProperty("sites");
    expect(data).toHaveProperty("maxValues");
    if (Array.isArray(data.playersArray)) {
      expect(data).toHaveProperty("contractVersion");
    }

    const playerNames = Object.keys(data.players || {});
    expect(playerNames.length).toBeGreaterThan(100);

    if (Array.isArray(data.playersArray) && data.playersArray.length) {
      const firstRow = data.playersArray[0];
      expect(firstRow).toHaveProperty("canonicalName");
      expect(firstRow).toHaveProperty("position");
      expect(firstRow).toHaveProperty("values");
      expect(firstRow.values).toHaveProperty("overall");
      expect(firstRow.values).toHaveProperty("rawComposite");
      expect(firstRow).toHaveProperty("canonicalSiteValues");
    }

    if (isMobileProject(testInfo)) {
      await openMobilePrimary(page, "calculator");
      await expect(page.locator("#tab-calculator")).toHaveClass(/active/);
      await openMobilePrimary(page, "rookies");
      await expect(page.locator("#tab-rookies")).toHaveClass(/active/);
      await openMobilePrimary(page, "more");
      await expect(page.locator("#tab-more")).toHaveClass(/active/);
    } else {
      await openTab(page, "calculator");
      await expect(page.locator("#tab-calculator")).toHaveClass(/active/);
      await openTab(page, "rookies");
      await expect(page.locator("#tab-rookies")).toHaveClass(/active/);
      await openTab(page, "trades");
      await expect(page.locator("#tab-trades")).toHaveClass(/active/);
      await openTab(page, "settings");
      await expect(page.locator("#tab-settings")).toHaveClass(/active/);
    }

    guard.assertClean();
  });
});
