const { test, expect } = require("@playwright/test");
const {
  attachConsoleGuards,
  gotoApp,
  openTab,
  openMobilePrimary,
  isMobileProject,
  getSamplePlayerNames,
  addAssetViaGlobalSearch,
} = require("../utils/app");

test.describe("rankings + more mobile controls parity", () => {
  test("rankings layout remains stable across desktop/mobile breakpoints", async ({ page, request }, testInfo) => {
    const guard = attachConsoleGuards(page, { allow: ["due to access control checks."] });
    await gotoApp(page, request);
    await page.goto("/rankings", { waitUntil: "domcontentloaded" });
    await page.waitForFunction(
      () => {
        const runtimeData =
          window.loadedData ||
          (typeof loadedData !== "undefined" ? loadedData : null);
        return (
          !!runtimeData &&
          !!runtimeData.players &&
          Object.keys(runtimeData.players).length > 50
        );
      },
      undefined,
      { timeout: 90_000 }
    );
    await page.waitForFunction(
      () => document.querySelector(".tab-panel.active")?.id === "tab-rookies",
      undefined,
      { timeout: 10_000 }
    );

    if (isMobileProject(testInfo)) {
      await page.waitForTimeout(300);

      const mobileLayout = await page.evaluate(() => {
        const desktopTable = document.getElementById("rankingsDesktopTable");
        const mobileList = document.getElementById("rankingsMobileList");
        const rookieLabel = document.querySelector('#tab-rookies label[for="rankingsRookieToggle"]');
        const myRosterLabel = document.querySelector('#tab-rookies label[for="rankingsMyRosterToggle"]');
        const controls = document.querySelector(".rankings-mobile-controls");
        return {
          powerModeEnabled:
            typeof window.getMobilePowerModeEnabled === "function"
              ? window.getMobilePowerModeEnabled()
              : null,
          desktopTableDisplay: desktopTable ? getComputedStyle(desktopTable).display : null,
          mobileListDisplay: mobileList ? getComputedStyle(mobileList).display : null,
          mobileCardCount: document.querySelectorAll("#rankingsMobileList .mobile-row-card").length,
          rookieLabelDisplay: rookieLabel ? getComputedStyle(rookieLabel).display : null,
          myRosterLabelDisplay: myRosterLabel ? getComputedStyle(myRosterLabel).display : null,
          controlsPosition: controls ? getComputedStyle(controls).position : null,
          viewportOverflowPx:
            Math.max(document.body.scrollWidth, document.documentElement.scrollWidth) -
            document.documentElement.clientWidth,
        };
      });

      expect(mobileLayout.powerModeEnabled).toBeFalsy();
      expect(mobileLayout.desktopTableDisplay).toBe("none");
      expect(mobileLayout.mobileListDisplay).not.toBe("none");
      expect(mobileLayout.mobileCardCount).toBeGreaterThan(0);
      expect(mobileLayout.rookieLabelDisplay).toBe("none");
      expect(mobileLayout.myRosterLabelDisplay).toBe("none");
      expect(mobileLayout.controlsPosition).toBe("sticky");
      expect(mobileLayout.viewportOverflowPx).toBeLessThan(3);

      await page.evaluate(() => window.scrollTo(0, 900));
      await page.waitForTimeout(150);
      const stickyTop = await page.evaluate(() => {
        const controls = document.querySelector(".rankings-mobile-controls");
        if (!controls) return null;
        return Math.round(controls.getBoundingClientRect().top);
      });
      expect(stickyTop).toBeGreaterThanOrEqual(50);
      expect(stickyTop).toBeLessThanOrEqual(64);
    } else {
      await page.waitForTimeout(250);

      const desktopLayout = await page.evaluate(() => {
        const desktopTable = document.getElementById("rankingsDesktopTable");
        const mobileList = document.getElementById("rankingsMobileList");
        const firstHeader = document.querySelector("#rookieHeader th:first-child");
        return {
          desktopTableDisplay: desktopTable ? getComputedStyle(desktopTable).display : null,
          mobileListDisplay: mobileList ? getComputedStyle(mobileList).display : null,
          stickyFirstHeaderPosition: firstHeader ? getComputedStyle(firstHeader).position : null,
          viewportOverflowPx:
            Math.max(document.body.scrollWidth, document.documentElement.scrollWidth) -
            document.documentElement.clientWidth,
        };
      });

      expect(desktopLayout.desktopTableDisplay).toBe("block");
      expect(desktopLayout.mobileListDisplay).toBe("none");
      expect(desktopLayout.stickyFirstHeaderPosition).toBe("sticky");
      expect(desktopLayout.viewportOverflowPx).toBeLessThan(3);
    }

    guard.assertClean();
  });

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

      const yahooConfigured = await page.evaluate(() => {
        const runtimeData =
          window.loadedData ||
          (typeof loadedData !== "undefined" ? loadedData : null) ||
          {};
        const sites = Array.isArray(runtimeData.sites) ? runtimeData.sites : [];
        const yahoo = sites.find((s) => String(s?.key || "").toLowerCase() === "yahoo");
        return !!yahoo && Number(yahoo.playerCount || 0) > 0;
      });
      if (yahooConfigured) {
        const hasYahooHeader = await page.evaluate(() =>
          Array.from(document.querySelectorAll("#rookieHeader th"))
            .some((th) => /yahoo/i.test(String(th.textContent || "")))
        );
        expect(hasYahooHeader).toBeTruthy();
      }

      const dynastyNerdsConfigured = await page.evaluate(() => {
        const runtimeData =
          window.loadedData ||
          (typeof loadedData !== "undefined" ? loadedData : null) ||
          {};
        const sites = Array.isArray(runtimeData.sites) ? runtimeData.sites : [];
        const dn = sites.find((s) => String(s?.key || "").toLowerCase() === "dynastynerds");
        return !!dn && Number(dn.playerCount || 0) > 0;
      });
      if (dynastyNerdsConfigured) {
        const hasDynastyNerdsHeader = await page.evaluate(() =>
          Array.from(document.querySelectorAll("#rookieHeader th"))
            .some((th) => /dyn(?:asty)?\.?\s*nerds/i.test(String(th.textContent || "")))
        );
        expect(hasDynastyNerdsHeader).toBeTruthy();
      }
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

  test("rankings, player card, and trade rows stay in backend parity", async ({ page, request }, testInfo) => {
    const guard = attachConsoleGuards(page);
    await gotoApp(page, request);

    if (isMobileProject(testInfo)) {
      await openMobilePrimary(page, "rookies");
    } else {
      await openTab(page, "rookies");
    }

    await page.evaluate(() => {
      if (typeof window.filterRankingsPos === "function") window.filterRankingsPos("ALL");
      const basis = document.getElementById("rankingsSortBasis");
      if (basis) {
        basis.value = "full";
        basis.dispatchEvent(new Event("change", { bubbles: true }));
      }
      if (typeof window.buildFullRankings === "function") window.buildFullRankings();
    });

    await page.waitForFunction(
      () => !!(window.__frontendBackendParity && window.__frontendBackendParity.rankings),
      undefined,
      { timeout: 20_000 },
    );

    const rankingsParity = await page.evaluate(() =>
      (window.__frontendBackendParity && window.__frontendBackendParity.rankings) ||
      window.__rankingsBackendParity ||
      null,
    );
    expect(rankingsParity).toBeTruthy();
    expect(Number(rankingsParity?.summary?.mismatchCount || 0)).toBe(0);
    expect(Number(rankingsParity?.values?.summary?.mismatchCount || 0)).toBe(0);
    expect(Number(rankingsParity?.sourceColumns?.mismatchCount || 0)).toBe(0);
    expect(Number(rankingsParity?.renderedSortParity?.mismatchCount || 0)).toBe(0);

    const sourceCoverage = rankingsParity?.sources?.bySource || {};
    for (const sourceKey of ["yahoo", "dynastyNerds", "idpTradeCalc"]) {
      const row = sourceCoverage[sourceKey];
      if (!row) continue;
      if (Number(row?.expected?.TOTAL || 0) > 0) {
        expect(Number(row?.actual?.TOTAL || 0), `${sourceKey} coverage should remain visible in rankings`).toBeGreaterThan(0);
      }
      expect(Number(row?.mismatchBucketCount || 0), `${sourceKey} position-bucket coverage drift`).toBe(0);
    }
    const idpCoverage = sourceCoverage.idpTradeCalc;
    if (idpCoverage && Number(idpCoverage?.expected?.TOTAL || 0) > 0) {
      for (const bucket of ["QB", "RB", "WR", "TE", "DL", "LB", "DB"]) {
        if (Number(idpCoverage?.expected?.[bucket] || 0) > 0) {
          expect(Number(idpCoverage?.actual?.[bucket] || 0), `IDPTradeCalc ${bucket} coverage should render`).toBeGreaterThan(0);
        }
      }
      if (Number(idpCoverage?.expected?.OFF || 0) > 0) {
        expect(Number(idpCoverage?.actual?.OFF || 0), "IDPTradeCalc offensive coverage should render").toBeGreaterThan(0);
      }
      if (Number(idpCoverage?.expected?.IDP || 0) > 0) {
        expect(Number(idpCoverage?.actual?.IDP || 0), "IDPTradeCalc IDP coverage should render").toBeGreaterThan(0);
      }
    }

    await page.evaluate(() => {
      if (typeof window.filterRankingsPos === "function") window.filterRankingsPos("QB");
      const basis = document.getElementById("rankingsSortBasis");
      if (basis) {
        basis.value = "raw";
        basis.dispatchEvent(new Event("change", { bubbles: true }));
      }
      if (typeof window.buildFullRankings === "function") window.buildFullRankings();
    });
    await page.waitForTimeout(250);
    const rawSortParity = await page.evaluate(() => {
      const parity = (window.__frontendBackendParity && window.__frontendBackendParity.rankings) || window.__rankingsBackendParity || {};
      return Number(parity?.renderedSortParity?.mismatchCount || 0);
    });
    expect(rawSortParity).toBe(0);

    const popupParity = await page.evaluate(() => {
      const rows = Array.from(document.querySelectorAll("#rookieBody tr"));
      let candidate = "";
      for (const row of rows) {
        const link = row.querySelector("td:nth-child(2) a");
        const name = String(link?.textContent || "").trim();
        if (!name) continue;
        if (typeof window.parsePickToken === "function" && window.parsePickToken(name)) continue;
        candidate = name;
        break;
      }
      if (!candidate) return { ok: false, reason: "no_candidate" };
      const base = window.computeMetaValueForPlayer?.(candidate, { rawOnly: true });
      if (!base) return { ok: false, reason: "missing_base", candidate };
      const pos = String(
        window.getPlayerPosition?.(candidate) ||
        window.getRookiePosHint?.(candidate) ||
        "",
      ).toUpperCase();
      const raw = Math.max(1, Math.min(9999, Math.round(Number(base.rawMarketValue ?? base.metaValue) || 0)));
      const bundle = window.computeFinalAdjustedValue?.(raw, pos, candidate);
      if (!bundle) return { ok: false, reason: "missing_bundle", candidate };
      window.openPlayerPopup?.(candidate);
      const renderedRaw = String(document.querySelector("#playerPopupContent .pp-composite")?.textContent || "");
      window.closePlayerPopup?.();
      const renderedFinal = Math.round(Number(renderedRaw.replace(/[^\d.-]/g, "") || 0));
      const expectedFinal = Math.round(Number(bundle.finalAdjustedValue || 0));
      return {
        ok: true,
        candidate,
        expectedFinal,
        renderedFinal,
        diff: renderedFinal - expectedFinal,
      };
    });
    expect(Boolean(popupParity?.ok), `player popup parity failed: ${popupParity?.reason || "unknown"}`).toBeTruthy();
    expect(Math.abs(Number(popupParity?.diff || 0))).toBeLessThanOrEqual(1);

    if (isMobileProject(testInfo)) {
      await openMobilePrimary(page, "calculator");
    } else {
      await openTab(page, "calculator");
    }
    const [p1, p2, p3] = await getSamplePlayerNames(page);
    expect(p1).toBeTruthy();
    expect(p2).toBeTruthy();
    await page.evaluate(() => window.clearPlayers?.());
    await addAssetViaGlobalSearch(page, "A", p1);
    await addAssetViaGlobalSearch(page, "B", p2);
    if (p3) await addAssetViaGlobalSearch(page, "A", p3);
    await page.waitForTimeout(350);
    const tradeParity = await page.evaluate(() =>
      (window.__frontendBackendParity && window.__frontendBackendParity.tradeCalculator) ||
      window.__tradeCalculatorParity ||
      null,
    );
    expect(tradeParity).toBeTruthy();
    expect(Number(tradeParity?.compared || 0)).toBeGreaterThan(0);
    expect(Number(tradeParity?.mismatchCount || 0)).toBe(0);

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
