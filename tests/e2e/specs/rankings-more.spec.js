const { test, expect } = require("@playwright/test");
const {
  attachConsoleGuards,
  gotoApp,
  openTab,
  openMobilePrimary,
  isMobileProject,
  getSamplePlayerNames,
} = require("../utils/app");

test.describe("rankings + more mobile controls parity", () => {
  test("rankings search, position filter, sort basis, and source-column visibility", async ({ page, request }, testInfo) => {
    const guard = attachConsoleGuards(page);
    await gotoApp(page, request);

    if (isMobileProject(testInfo)) {
      await openMobilePrimary(page, "rookies");
    } else {
      await openTab(page, "rookies");
    }

    const [sampleName] = await getSamplePlayerNames(page);
    const queryToken = String(sampleName || "").split(" ").slice(0, 1).join(" ");
    await expect(page.locator("#rankingsSearch")).toBeVisible();
    await page.locator("#rankingsSearch").fill(queryToken);
    await page.waitForTimeout(300);
    await page.locator("#rankingsSearch").fill("");
    await page.waitForTimeout(150);

    if (isMobileProject(testInfo)) {
      await page.locator(".rankings-mobile-controls .mobile-chip-btn").filter({ hasText: "Filters" }).first().click();
      await expect(page.locator("#rankingsFilterSheetOverlay")).toHaveClass(/active/);
      await page.selectOption("#sheetFilterPos", "QB");
      const toggle = page.locator("#sheetShowSourceCols");
      await expect(toggle).toBeVisible();
      if (!(await toggle.isChecked())) await toggle.click();
      await page.locator("#rankingsFilterSheetOverlay .mobile-chip-btn.primary").filter({ hasText: "Apply" }).click();
      await expect(page.locator("#rankingsFilterSheetOverlay")).not.toHaveClass(/active/);
    } else {
      const qbBtn = page.locator("#posFilters .pos-filter-btn[data-pos='QB']").first();
      await qbBtn.click();
    }
    await page.waitForFunction(() => {
      const active =
        (typeof currentRankingsFilter !== "undefined" ? currentRankingsFilter : null) ||
        window.currentRankingsFilter ||
        "";
      return String(active) === "QB";
    });

    await page.evaluate(() => {
      const basis = document.getElementById("rankingsSortBasis");
      if (!basis) return;
      basis.value = "raw";
      basis.dispatchEvent(new Event("change", { bubbles: true }));
    });
    await page.waitForFunction(() => String(document.getElementById("rankingsSortBasis")?.value || "") === "raw");
    await page.evaluate(() => {
      const basis = document.getElementById("rankingsSortBasis");
      if (!basis) return;
      basis.value = "full";
      basis.dispatchEvent(new Event("change", { bubbles: true }));
    });
    await page.waitForFunction(() => String(document.getElementById("rankingsSortBasis")?.value || "") === "full");

    if (isMobileProject(testInfo)) {
      await page.waitForTimeout(250);
      const mobileSourceCount = await page.locator("#rankingsMobileList .mobile-rank-sources").count();
      expect(mobileSourceCount).toBeGreaterThan(0);
    } else {
      const toggle = page.locator("#rankingsShowSiteColsQuick");
      if (!(await toggle.isChecked())) await toggle.check();
      await expect(toggle).toBeChecked();
      await page.waitForTimeout(250);
      const thCount = await page.locator("#rookieHeader th").count();
      expect(thCount).toBeGreaterThan(6);
    }

    const hasBadValueTokens = await page.evaluate(() => {
      const cells = [
        ...Array.from(document.querySelectorAll("#rookieBody tr td:nth-child(4)")),
        ...Array.from(document.querySelectorAll("#rankingsMobileList .mobile-row-value")),
      ];
      return cells.some((el) => /nan|undefined/i.test(String(el.textContent || "")));
    });
    expect(hasBadValueTokens).toBeFalsy();

    guard.assertClean();
  });

  test("mobile More surfaces and advanced settings persistence", async ({ page, request }, testInfo) => {
    const guard = attachConsoleGuards(page);
    await gotoApp(page, request);

    if (isMobileProject(testInfo)) {
      await openMobilePrimary(page, "more");
    } else {
      await openTab(page, "more");
    }

    const sectionChecks = [
      { key: "rosters", title: "Team Value Board" },
      { key: "league", title: "League" },
      { key: "trades", title: "Trade Activity" },
      { key: "settings", title: "Mobile Settings" },
    ];

    for (const section of sectionChecks) {
      const btn = page.locator(`#moreSectionNav [data-more-section="${section.key}"]`).first();
      await expect(btn).toBeVisible();
      await btn.click();
      await expect(page.locator("#moreSectionTitle")).toContainText(section.title);
      const bodyHasText = await page.evaluate(() => {
        const el = document.getElementById("moreSectionBody");
        return !!el && String(el.textContent || "").trim().length > 0;
      });
      expect(bodyHasText).toBeTruthy();
    }

    const matrixBtn = page.locator("#moreSectionBody .mobile-chip-btn.primary").filter({ hasText: "Edit Site Matrix" }).first();
    await expect(matrixBtn).toBeVisible();
    await matrixBtn.click();
    await expect(page.locator("#mobileSiteMatrixOverlay")).toHaveClass(/active/);

    const editableSite = await page.evaluate(() => {
      const cfg = typeof window.getSiteConfig === "function" ? window.getSiteConfig() : [];
      const pick = cfg.find((s) => !s.lockWeight && !!document.getElementById(`mobileSiteMatrix_weight_${s.key}`));
      return pick ? pick.key : null;
    });
    expect(editableSite).toBeTruthy();

    const weightInput = page.locator(`#mobileSiteMatrix_weight_${editableSite}`);
    await expect(weightInput).toBeVisible();
    await weightInput.fill("1.37");
    await page.locator("#mobileSiteMatrixOverlay .mobile-chip-btn.primary").filter({ hasText: "Apply Matrix" }).click();
    await expect(page.locator("#mobileSiteMatrixOverlay")).not.toHaveClass(/active/);

    await page.waitForFunction((key) => {
      const target = document.getElementById(`weight_${key}`);
      const n = Number(target?.value || 0);
      return Number.isFinite(n) && Math.abs(n - 1.37) < 0.001;
    }, editableSite);

    guard.assertClean();
  });
});
