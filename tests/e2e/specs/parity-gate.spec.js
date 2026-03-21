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

async function openPrimaryTab(page, testInfo, tabId) {
  if (isMobileProject(testInfo)) {
    await openMobilePrimary(page, tabId);
  } else {
    await openTab(page, tabId);
  }
}

test.describe("@parity-gate release parity authority", () => {
  test("rankings values/source columns/player card stay backend-authoritative", async ({ page, request }, testInfo) => {
    const guard = attachConsoleGuards(page);
    await gotoApp(page, request);

    await openPrimaryTab(page, testInfo, "rookies");

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
    expect(Boolean(rankingsParity?.skipped)).toBeFalsy();
    expect(Number(rankingsParity?.summary?.mismatchCount || 0)).toBe(0);
    expect(Number(rankingsParity?.values?.summary?.mismatchCount || 0)).toBe(0);
    expect(Number(rankingsParity?.sourceColumns?.mismatchCount || 0)).toBe(0);
    expect(Number(rankingsParity?.renderedSortParity?.mismatchCount || 0)).toBe(0);

    const sourceCoverage = rankingsParity?.sources?.bySource || {};
    for (const sourceKey of ["yahoo", "dynastyNerds", "idpTradeCalc"]) {
      const row = sourceCoverage[sourceKey];
      if (!row) continue;
      if (Number(row?.expected?.TOTAL || 0) > 0) {
        expect(
          Number(row?.actual?.TOTAL || 0),
          `${sourceKey} coverage should remain visible in rankings`,
        ).toBeGreaterThan(0);
      }
      expect(
        Number(row?.mismatchBucketCount || 0),
        `${sourceKey} position-bucket coverage drift`,
      ).toBe(0);
    }

    const idpCoverage = sourceCoverage.idpTradeCalc;
    if (idpCoverage && Number(idpCoverage?.expected?.TOTAL || 0) > 0) {
      for (const bucket of ["QB", "RB", "WR", "TE", "DL", "LB", "DB"]) {
        if (Number(idpCoverage?.expected?.[bucket] || 0) > 0) {
          expect(
            Number(idpCoverage?.actual?.[bucket] || 0),
            `IDPTradeCalc ${bucket} coverage should render`,
          ).toBeGreaterThan(0);
        }
      }
      if (Number(idpCoverage?.expected?.OFF || 0) > 0) {
        expect(
          Number(idpCoverage?.actual?.OFF || 0),
          "IDPTradeCalc offensive coverage should render",
        ).toBeGreaterThan(0);
      }
      if (Number(idpCoverage?.expected?.IDP || 0) > 0) {
        expect(
          Number(idpCoverage?.actual?.IDP || 0),
          "IDPTradeCalc IDP coverage should render",
        ).toBeGreaterThan(0);
      }
    }

    const rankingsAuthority = await page.evaluate(() => {
      const rows = Array.from(document.querySelectorAll("#rookieBody tr"));
      const runtimeData =
        window.loadedData ||
        (typeof loadedData !== "undefined" ? loadedData : null);
      let compared = 0;
      const mismatches = [];
      const backendMissing = [];
      const parseNumeric = (value) =>
        Math.round(Number(String(value || "").replace(/[^\d.-]/g, "") || 0) || 0);

      for (const row of rows) {
        const name = String(row.querySelector("td:nth-child(2) a")?.textContent || "").trim();
        if (!name) continue;
        if (typeof window.parsePickToken === "function" && window.parsePickToken(name)) continue;

        const canonicalName =
          typeof window.resolveCanonicalPlayerName === "function"
            ? window.resolveCanonicalPlayerName(name)
            : name;
        const sourceData =
          (runtimeData && runtimeData.players && runtimeData.players[canonicalName]) ||
          null;
        if (!sourceData || typeof sourceData !== "object") {
          if (backendMissing.length < 10) backendMissing.push(name);
          continue;
        }

        const expected = Math.round(
          Number(
            sourceData?.valueBundle?.fullValue ??
              sourceData?._finalAdjusted ??
              sourceData?.values?.finalAdjusted ??
              sourceData?.values?.overall ??
              0,
          ) || 0,
        );
        const renderedCell = row.querySelector("td:nth-child(4)")?.textContent || "";
        const actual = Math.round(
          Number(row.dataset.adjustedComposite || row.dataset.sortValue || parseNumeric(renderedCell) || 0) || 0,
        );
        if (expected <= 0 || actual <= 0) continue;

        compared += 1;
        const diff = actual - expected;
        if (Math.abs(diff) > 1 && mismatches.length < 12) {
          mismatches.push({
            name,
            expected,
            actual,
            diff,
          });
        }
      }

      return {
        compared,
        mismatchCount: mismatches.length,
        mismatches,
        backendMissing,
      };
    });

    expect(Number(rankingsAuthority?.compared || 0)).toBeGreaterThan(25);
    expect(Number(rankingsAuthority?.mismatchCount || 0)).toBe(0);

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
        window.getPlayerPosition?.(candidate) || window.getRookiePosHint?.(candidate) || "",
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

    guard.assertClean();
  });

  test("trade rows remain backend-authoritative for known assets", async ({ page, request }, testInfo) => {
    const guard = attachConsoleGuards(page);
    await gotoApp(page, request);

    await openPrimaryTab(page, testInfo, "calculator");

    await page.evaluate(() => {
      const desktop = document.getElementById("calculatorValueBasis");
      if (desktop) {
        desktop.value = "full";
        desktop.dispatchEvent(new Event("change", { bubbles: true }));
      }
      const mobile = document.getElementById("mobileCalculatorValueBasis");
      if (mobile) {
        mobile.value = "full";
        mobile.dispatchEvent(new Event("change", { bubbles: true }));
      }
      if (typeof window.recalculate === "function") window.recalculate();
    });

    const [p1, p2, p3] = await getSamplePlayerNames(page);
    expect(p1).toBeTruthy();
    expect(p2).toBeTruthy();

    await page.evaluate(() => window.clearPlayers?.());
    await addAssetViaGlobalSearch(page, "A", p1);
    await addAssetViaGlobalSearch(page, "B", p2);
    if (p3) await addAssetViaGlobalSearch(page, "A", p3);

    await page.waitForFunction(
      () => {
        const parity =
          (window.__frontendBackendParity && window.__frontendBackendParity.tradeCalculator) ||
          window.__tradeCalculatorParity ||
          null;
        return !!parity && !parity.skipped && Number(parity.compared || 0) > 0;
      },
      undefined,
      { timeout: 20_000 },
    );

    const tradeParity = await page.evaluate(() =>
      (window.__frontendBackendParity && window.__frontendBackendParity.tradeCalculator) ||
      window.__tradeCalculatorParity ||
      null,
    );

    expect(tradeParity).toBeTruthy();
    expect(Boolean(tradeParity?.skipped)).toBeFalsy();
    expect(Number(tradeParity?.compared || 0)).toBeGreaterThan(0);
    expect(Number(tradeParity?.mismatchCount || 0)).toBe(0);

    const packageDiagnostics = await page.evaluate(() =>
      window.__tradeCalculatorPackageDiagnostics || null,
    );
    expect(packageDiagnostics).toBeTruthy();
    expect(Boolean(packageDiagnostics?.backendHealthy), "backend trade scoring should be healthy").toBeTruthy();
    expect(
      Number(packageDiagnostics?.fallback?.usedCount || 0),
      "calculator should not use frontend fallback totals while backend is healthy",
    ).toBe(0);
    expect(
      Boolean(packageDiagnostics?.fallback?.whileBackendHealthy),
      "fallback while backend healthy should fail parity",
    ).toBeFalsy();
    expect(
      String(packageDiagnostics?.authority || ""),
      "calculator authority marker",
    ).toBe("backend_trade_scoring_v1");

    const tradeAuthority = await page.evaluate(() => {
      const runtimeData =
        window.loadedData ||
        (typeof loadedData !== "undefined" ? loadedData : null);
      const sideBodies = ["A", "B", "C"].map((side) => ({
        side,
        tbody: document.getElementById(side === "A" ? "sideABody" : side === "B" ? "sideBBody" : "sideCBody"),
      }));

      let compared = 0;
      const valueMismatches = [];
      const authorityMismatches = [];

      for (const { side, tbody } of sideBodies) {
        if (!tbody) continue;
        const rows = Array.from(tbody.querySelectorAll("tr"));
        for (const row of rows) {
          const rawName = String(
            row.querySelector(".player-name-input")?.value ||
              row.querySelector('input[type="text"]')?.value ||
              row.querySelector("td:first-child")?.textContent ||
              "",
          )
            .replace(/\s*×\s*$/, "")
            .trim();
          if (!rawName) continue;
          if (typeof window.parsePickToken === "function" && window.parsePickToken(rawName)) continue;

          const canonicalName =
            typeof window.resolveCanonicalPlayerName === "function"
              ? window.resolveCanonicalPlayerName(rawName)
              : rawName;
          const sourceData =
            (runtimeData && runtimeData.players && runtimeData.players[canonicalName]) ||
            null;
          if (!sourceData || typeof sourceData !== "object") continue;

          const expected = Math.round(
            Number(
              sourceData?.valueBundle?.fullValue ??
                sourceData?._finalAdjusted ??
                sourceData?.values?.finalAdjusted ??
                sourceData?.values?.overall ??
                0,
            ) || 0,
          );
          const renderedCell = row.querySelector("td:last-child")?.textContent || "";
          const actual = Math.round(
            Number(
              row.dataset.metaValue ||
                String(renderedCell).replace(/[^\d.-]/g, "") ||
                0,
            ) || 0,
          );
          if (expected <= 0 || actual <= 0) continue;

          compared += 1;
          const diff = actual - expected;
          if (Math.abs(diff) > 1 && valueMismatches.length < 12) {
            valueMismatches.push({
              side,
              name: rawName,
              expected,
              actual,
              diff,
            });
          }

          const authority = String(row.dataset.valueAuthority || "");
          if (!authority.startsWith("backend_trade_item") && authorityMismatches.length < 12) {
            authorityMismatches.push({
              side,
              name: rawName,
              authority,
            });
          }
        }
      }

      return {
        compared,
        valueMismatchCount: valueMismatches.length,
        valueMismatches,
        authorityMismatchCount: authorityMismatches.length,
        authorityMismatches,
      };
    });

    expect(Number(tradeAuthority?.compared || 0)).toBeGreaterThanOrEqual(2);
    expect(Number(tradeAuthority?.valueMismatchCount || 0)).toBe(0);
    expect(Number(tradeAuthority?.authorityMismatchCount || 0)).toBe(0);

    guard.assertClean();
  });

  test("historical trade analysis stays backend-authoritative", async ({ page, request }, testInfo) => {
    const guard = attachConsoleGuards(page);
    await gotoApp(page, request);

    if (isMobileProject(testInfo)) {
      await openMobilePrimary(page, "more");
      await page.evaluate(() => {
        if (typeof setMobileMoreSection === "function") {
          setMobileMoreSection("trades", { persist: true, refresh: true });
        } else if (typeof buildTradeHistoryPage === "function") {
          void buildTradeHistoryPage({ renderMobilePreview: true });
        }
      });
    } else {
      await openTab(page, "trades");
    }

    await page.waitForFunction(
      () => !!window.__tradeHistoryScoringDiagnostics,
      undefined,
      { timeout: 30_000 },
    );

    const historyAuthority = await page.evaluate(() => {
      const diagnostics = window.__tradeHistoryScoringDiagnostics || null;
      const rows =
        typeof tradeHistoryRenderCache !== "undefined" && Array.isArray(tradeHistoryRenderCache)
          ? tradeHistoryRenderCache
          : [];
      const firstRow = rows[0] || null;
      const firstResolution = firstRow?.sides?.[0]?.packageResolution || null;
      return {
        diagnostics,
        renderCount: rows.length,
        firstResolution,
      };
    });

    expect(historyAuthority?.diagnostics).toBeTruthy();
    expect(
      Boolean(historyAuthority?.diagnostics?.localFormulaUsed),
      "historical trade analysis must not use frontend package formula",
    ).toBeFalsy();
    expect(
      String(historyAuthority?.diagnostics?.authority || ""),
      "historical scoring authority marker",
    ).toContain("backend_trade_scoring_v1");

    if (Number(historyAuthority?.diagnostics?.tradesAnalyzed || 0) > 0) {
      expect(
        historyAuthority?.firstResolution && typeof historyAuthority.firstResolution === "object",
        "historical sides should carry backend resolution diagnostics",
      ).toBeTruthy();
    }

    guard.assertClean();
  });
});
