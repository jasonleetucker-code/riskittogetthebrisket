const { test, expect } = require("@playwright/test");
const {
  attachConsoleGuards,
  gotoApp,
  openTab,
  openMobilePrimary,
  isMobileProject,
  getSamplePlayerNames,
  addAssetViaGlobalSearch,
  getTradeAssets,
  setTradeModeThreeTeam,
  clickSwap,
  clickClear,
} = require("../utils/app");

test.describe("trade calculator parity workflows", () => {
  test("search add/remove flow, swap, clear, and 3-team mode", async ({ page, request }, testInfo) => {
    const guard = attachConsoleGuards(page);
    await gotoApp(page, request);

    if (isMobileProject(testInfo)) {
      await openMobilePrimary(page, "calculator");
    } else {
      await openTab(page, "calculator");
    }

    const [p1, p2, p3] = await getSamplePlayerNames(page);
    expect(p1).toBeTruthy();
    expect(p2).toBeTruthy();
    expect(p3).toBeTruthy();

    await addAssetViaGlobalSearch(page, "A", p1);
    await addAssetViaGlobalSearch(page, "B", p2);

    let sides = await getTradeAssets(page);
    expect(sides.A).toContain(p1);
    expect(sides.B).toContain(p2);

    if (isMobileProject(testInfo)) {
      const removeBtn = page.locator("#mobileTradeSideA .chip-remove-btn").first();
      await expect(removeBtn).toBeVisible();
      await removeBtn.click();
      await page.waitForFunction(
        (name) => !(window.getTradeSideAssets?.("A") || []).some((r) => (r.name || "").toLowerCase() === name.toLowerCase()),
        p1
      );
    } else {
      await page.evaluate((name) => {
        const rows = window.getTradeSideAssets?.("A", { includeRowIndex: true }) || [];
        const exact = rows.find((r) => (r.name || "").toLowerCase() === String(name).toLowerCase());
        if (exact) window.removeAssetFromTrade?.("A", exact.name, exact.rowIndex);
      }, p1);
      await page.waitForFunction(
        (name) => !(window.getTradeSideAssets?.("A") || []).some((r) => (r.name || "").toLowerCase() === name.toLowerCase()),
        p1
      );
    }

    await addAssetViaGlobalSearch(page, "A", p1);
    await addAssetViaGlobalSearch(page, "B", p2);

    const beforeSwap = await getTradeAssets(page);
    await clickSwap(page, testInfo);
    await page.waitForFunction(
      (before) => {
        const nowA = (window.getTradeSideAssets?.("A") || []).map((r) => r.name).sort();
        const nowB = (window.getTradeSideAssets?.("B") || []).map((r) => r.name).sort();
        const prevA = [...(before.A || [])].sort();
        const prevB = [...(before.B || [])].sort();
        return JSON.stringify(nowA) === JSON.stringify(prevB) && JSON.stringify(nowB) === JSON.stringify(prevA);
      },
      beforeSwap
    );

    await setTradeModeThreeTeam(page, true, testInfo);
    await addAssetViaGlobalSearch(page, "C", p3);
    sides = await getTradeAssets(page);
    expect(sides.C).toContain(p3);

    await clickClear(page, testInfo);
    await page.waitForFunction(() => {
      const a = (window.getTradeSideAssets?.("A") || []).length;
      const b = (window.getTradeSideAssets?.("B") || []).length;
      const c = (window.getTradeSideAssets?.("C") || []).length;
      return a === 0 && b === 0 && c === 0;
    });

    await setTradeModeThreeTeam(page, false, testInfo);
    guard.assertClean();
  });

  test("value basis, side filters, analyze/impact toggles, and save/load/delete", async ({ page, request }, testInfo) => {
    const guard = attachConsoleGuards(page);
    await gotoApp(page, request);

    if (isMobileProject(testInfo)) {
      await openMobilePrimary(page, "calculator");
    } else {
      await openTab(page, "calculator");
    }

    const [p1, p2] = await getSamplePlayerNames(page);
    expect(p1).toBeTruthy();
    expect(p2).toBeTruthy();
    await addAssetViaGlobalSearch(page, "A", p1);
    await addAssetViaGlobalSearch(page, "B", p2);

    if (isMobileProject(testInfo)) {
      await page.selectOption("#mobileCalculatorValueBasis", "raw");
      await expect(page.locator("#calculatorValueBasis")).toHaveValue("raw");
      await page.selectOption("#mobileCalculatorValueBasis", "full");
      await expect(page.locator("#calculatorValueBasis")).toHaveValue("full");
    } else {
      await page.selectOption("#calculatorValueBasis", "raw");
      await expect(page.locator("#calculatorValueBasis")).toHaveValue("raw");
      await page.selectOption("#calculatorValueBasis", "full");
      await expect(page.locator("#calculatorValueBasis")).toHaveValue("full");
    }

    const sideFilterApplied = await page.evaluate((mobile) => {
      const targetId = mobile ? "mobileTeamFilterA" : "teamFilterA";
      const el = document.getElementById(targetId);
      if (!el || !el.options || el.options.length < 2) return { applied: false };
      const nextOpt = Array.from(el.options).find((opt) => opt.value);
      if (!nextOpt) return { applied: false };
      el.value = nextOpt.value;
      if (mobile && typeof window.setMobileTeamFilter === "function") {
        window.setMobileTeamFilter("A", nextOpt.value);
      } else if (typeof window.updateTeamFilter === "function") {
        window.updateTeamFilter();
      }
      return {
        applied: true,
        selected: String(nextOpt.value || ""),
        desktopValue: String(document.getElementById("teamFilterA")?.value || ""),
      };
    }, isMobileProject(testInfo));
    if (sideFilterApplied.applied) {
      expect(sideFilterApplied.desktopValue).toBe(sideFilterApplied.selected);
    }

    if (isMobileProject(testInfo)) {
      const analyzeBtn = page.locator("#mobileTradeAnalyzeBtn");
      const beforeText = String((await analyzeBtn.textContent()) || "").trim();
      await analyzeBtn.click();
      await page.waitForTimeout(200);
      const afterOpenText = String((await analyzeBtn.textContent()) || "").trim();
      expect(afterOpenText).not.toBe(beforeText);
      await analyzeBtn.click();
      await page.waitForTimeout(200);
      const afterCloseText = String((await analyzeBtn.textContent()) || "").trim();
      expect(afterCloseText).toBe(beforeText);

      const impactReady = await page.evaluate(() => {
        const a = document.getElementById("teamFilterA");
        const b = document.getElementById("teamFilterB");
        if (!a || !b || a.options.length < 2 || b.options.length < 2) return false;
        const aOpt = Array.from(a.options).find((o) => o.value);
        const bOpt = Array.from(b.options).find((o) => o.value && o.value !== aOpt?.value) || aOpt;
        if (!aOpt || !bOpt) return false;
        a.value = aOpt.value;
        b.value = bOpt.value;
        if (typeof window.updateTeamFilter === "function") window.updateTeamFilter();
        return true;
      });
      if (impactReady) {
        const impactBtn = page.locator("#mobileTradeImpactBtn");
        await impactBtn.click();
        await expect(impactBtn).toContainText(/Hide Impact|Impact/);
      }
    }

    await page.evaluate(() => {
      window.prompt = () => "PW Regression Trade";
      window.saveTrade?.();
    });
    const savedCount = await page.evaluate(() => {
      try {
        return JSON.parse(localStorage.getItem("dynasty_saved_trades") || "[]").length;
      } catch {
        return 0;
      }
    });
    expect(savedCount).toBeGreaterThan(0);

    await clickClear(page, testInfo);
    await page.evaluate(() => window.loadSavedTrade?.("0"));
    await page.waitForFunction(() => {
      const a = (window.getTradeSideAssets?.("A") || []).length;
      const b = (window.getTradeSideAssets?.("B") || []).length;
      return a + b > 0;
    });

    await page.evaluate(() => {
      window.confirm = () => true;
      const desktop = document.getElementById("savedTradesSelect");
      const mobile = document.getElementById("mobileSavedTradesSelect");
      if (desktop) desktop.value = "0";
      if (mobile) mobile.value = "0";
      window.deleteSavedTrade?.();
    });
    const savedAfterDelete = await page.evaluate(() => {
      try {
        return JSON.parse(localStorage.getItem("dynasty_saved_trades") || "[]").length;
      } catch {
        return 0;
      }
    });
    expect(savedAfterDelete).toBe(0);

    guard.assertClean();
  });
});
