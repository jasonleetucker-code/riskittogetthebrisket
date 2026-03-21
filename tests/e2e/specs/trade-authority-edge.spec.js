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

async function openCalculatorTab(page, testInfo) {
  if (isMobileProject(testInfo)) {
    await openMobilePrimary(page, "calculator");
  } else {
    await openTab(page, "calculator");
  }
}

function getTruthSummaryId(testInfo) {
  return isMobileProject(testInfo) ? "mobileTradeTruthSummary" : "tradeTruthSummary";
}

async function addTwoSides(page, playerA, playerB) {
  await page.evaluate(() => window.clearPlayers?.());
  await addAssetViaGlobalSearch(page, "A", playerA);
  await addAssetViaGlobalSearch(page, "B", playerB);
  await page.waitForFunction(() => {
    const diag = window.__tradeCalculatorPackageDiagnostics || null;
    return !!diag && !!diag.sides && Number(diag.sides.A?.weightedTotal || 0) >= 0;
  });
}

test.describe("trade authority edge hardening", () => {
  test("stale async backend responses do not overwrite latest recalculation", async ({ page, request }, testInfo) => {
    const guard = attachConsoleGuards(page, {
      allow: ["Failed to load resource: the server responded with a status of 503"],
    });
    await gotoApp(page, request);
    await openCalculatorTab(page, testInfo);

    const [p1, p2, p3] = await getSamplePlayerNames(page);
    expect(p1).toBeTruthy();
    expect(p2).toBeTruthy();
    expect(p3).toBeTruthy();

    const runtimeContractVersion = await page.evaluate(
      () =>
        String(
          window.loadedData?.version ||
            window.loadedData?.contractVersion ||
            window.loadedData?.contract?.version ||
            "",
        ).trim(),
    );

    let callCount = 0;
    await page.route("**/api/trade/score", async (route) => {
      callCount += 1;
      const nth = callCount;
      const payload =
        nth === 1
          ? {
              ok: true,
              authority: "backend_trade_scoring_v1",
              contractVersion: runtimeContractVersion,
              summary: { inputItems: 2, backendResolved: 2, fallbackUsed: 0, quarantinedExcluded: 0, unresolvedExcluded: 0 },
              sides: {
                A: { weightedTotal: 9200, packageDeltaPct: 3.5 },
                B: { weightedTotal: 800, packageDeltaPct: -2.1 },
                C: { weightedTotal: 0, packageDeltaPct: 0.0 },
              },
            }
          : {
              ok: true,
              authority: "backend_trade_scoring_v1",
              contractVersion: runtimeContractVersion,
              summary: { inputItems: 3, backendResolved: 3, fallbackUsed: 0, quarantinedExcluded: 0, unresolvedExcluded: 0 },
              sides: {
                A: { weightedTotal: 700, packageDeltaPct: -1.9 },
                B: { weightedTotal: 9300, packageDeltaPct: 4.2 },
                C: { weightedTotal: 0, packageDeltaPct: 0.0 },
              },
            };
      const delayMs = nth === 1 ? 900 : 40;
      await new Promise((resolve) => setTimeout(resolve, delayMs));
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify(payload),
      });
    });

    await page.evaluate(() => window.clearPlayers?.());
    await addAssetViaGlobalSearch(page, "A", p1);
    await addAssetViaGlobalSearch(page, "B", p2);
    await addAssetViaGlobalSearch(page, "B", p3);

    await expect.poll(() => callCount, { timeout: 20_000 }).toBeGreaterThanOrEqual(2);
    await page.waitForFunction(
      () => {
        const diag = window.__tradeCalculatorPackageDiagnostics || null;
        return (
          !!diag &&
          Number(diag.sides?.B?.weightedTotal || 0) === 9300 &&
          Number(diag.sides?.A?.weightedTotal || 0) === 700
        );
      },
      undefined,
      { timeout: 20_000 },
    );

    const diag = await page.evaluate(() => window.__tradeCalculatorPackageDiagnostics || null);
    expect(Number(diag?.fallback?.usedCount || 0)).toBe(0);
    expect(Boolean(diag?.fallback?.whileBackendHealthy)).toBeFalsy();
    expect(Number(diag?.sides?.B?.weightedTotal || 0)).toBe(9300);
    expect(Number(diag?.sides?.A?.weightedTotal || 0)).toBe(700);

    guard.assertClean();
  });

  test("backend-healthy payload gaps never fall back to local package totals", async ({ page, request }, testInfo) => {
    const guard = attachConsoleGuards(page, {
      allow: ["Backend trade scoring payload missing side totals; package totals withheld"],
    });
    await gotoApp(page, request);
    await openCalculatorTab(page, testInfo);

    const [p1, p2] = await getSamplePlayerNames(page);
    expect(p1).toBeTruthy();
    expect(p2).toBeTruthy();

    const runtimeContractVersion = await page.evaluate(() => {
      if (typeof window.resolveRuntimeContractVersion === "function") {
        return String(window.resolveRuntimeContractVersion() || "").trim() || "unknown";
      }
      return (
        String(window.loadedData?.contractVersion || window.loadedData?.contract?.version || "").trim() ||
        "unknown"
      );
    });

    await page.route("**/api/trade/score", async (route) => {
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({
          ok: true,
          authority: "backend_trade_scoring_v1",
          contractVersion: runtimeContractVersion,
          summary: { inputItems: 2, backendResolved: 2, fallbackUsed: 0, quarantinedExcluded: 0, unresolvedExcluded: 0 },
          sides: {
            A: { weightedTotal: 5200, packageDeltaPct: 1.2 },
            // Missing weightedTotal is a backend payload integrity failure.
            B: { packageDeltaPct: -1.1 },
            C: { weightedTotal: 0, packageDeltaPct: 0.0 },
          },
        }),
      });
    });

    await addTwoSides(page, p1, p2);

    const truthSummaryId = getTruthSummaryId(testInfo);
    await page.waitForFunction(
      (summaryId) => {
        const diag = window.__tradeCalculatorPackageDiagnostics || null;
        const authority = window.__tradeCalculatorAuthorityState || null;
        const text = String(document.getElementById(summaryId)?.textContent || "").toLowerCase();
        return (
          !!diag &&
          String(diag.authority || "") === "backend_trade_scoring_invalid_payload" &&
          Number(diag.fallback?.backendPayloadIssueCount || 0) > 0 &&
          Number(diag.fallback?.usedCount || 0) === 0 &&
          !!authority &&
          String(authority.level || "") === "error" &&
          text.includes("payload")
        );
      },
      truthSummaryId,
      { timeout: 20_000 },
    );

    const snapshot = await page.evaluate((summaryId) => ({
      diagnostics: window.__tradeCalculatorPackageDiagnostics || null,
      authority: window.__tradeCalculatorAuthorityState || null,
      truth: window.__tradeCalculatorTruthState || null,
      truthText: String(document.getElementById(summaryId)?.textContent || "").trim(),
      totals: {
        a: String(document.getElementById("totalA")?.textContent || "").trim(),
        b: String(document.getElementById("totalB")?.textContent || "").trim(),
        decision: String(document.getElementById("decision")?.textContent || "").trim(),
      },
    }), truthSummaryId);

    expect(String(snapshot.authority?.message || "")).toContain("incomplete");
    expect(String(snapshot.truth?.headline || "")).toContain("payload incomplete");
    expect(snapshot.truthText.toLowerCase()).toContain("payload");
    expect(Number(snapshot.diagnostics?.fallback?.usedCount || 0)).toBe(0);
    expect(Number(snapshot.diagnostics?.fallback?.backendPayloadIssueCount || 0)).toBeGreaterThan(0);
    expect(Boolean(snapshot.diagnostics?.fallback?.whileBackendHealthy)).toBeFalsy();
    expect(Boolean(snapshot.diagnostics?.fallback?.bySide?.B?.payloadIssue)).toBeTruthy();
    expect(Boolean(snapshot.diagnostics?.fallback?.bySide?.A?.totalsWithheldByIntegrityGate)).toBeTruthy();
    expect(Boolean(snapshot.diagnostics?.fallback?.bySide?.B?.totalsWithheldByIntegrityGate)).toBeTruthy();
    expect(snapshot.totals.a).toBe("–");
    expect(snapshot.totals.b).toBe("–");
    expect(snapshot.totals.decision).toBe("–");

    guard.assertClean();
  });

  test("backend unavailable with fallback allowed is disclosed as partial authority", async ({ page, request }, testInfo) => {
    const guard = attachConsoleGuards(page, {
      allow: ["Failed to load resource: the server responded with a status of 503"],
    });
    await gotoApp(page, request);
    await openCalculatorTab(page, testInfo);

    const [p1, p2] = await getSamplePlayerNames(page);
    expect(p1).toBeTruthy();
    expect(p2).toBeTruthy();

    await page.route("**/api/trade/score", async (route) => {
      await route.fulfill({
        status: 503,
        contentType: "application/json",
        body: JSON.stringify({ ok: false, error: "forced-outage" }),
      });
    });

    await addTwoSides(page, p1, p2);

    const truthSummaryId = getTruthSummaryId(testInfo);
    await page.waitForFunction(
      (summaryId) => {
        const diag = window.__tradeCalculatorPackageDiagnostics || null;
        const state = window.__tradeCalculatorAuthorityState || null;
        const truthText = String(document.getElementById(summaryId)?.textContent || "").trim();
        return (
          !!diag &&
          !diag.backendHealthy &&
          Number(diag.fallback?.usedCount || 0) > 0 &&
          !!state &&
          state.visible === true &&
          String(state.level || "") === "warning" &&
          truthText.length > 0
        );
      },
      truthSummaryId,
      { timeout: 20_000 },
    );

    const runtimeSnapshot = await page.evaluate((summaryId) => ({
      authorityState: window.__tradeCalculatorAuthorityState || null,
      diagnostics: window.__tradeCalculatorPackageDiagnostics || null,
      truthState: window.__tradeCalculatorTruthState || null,
      truthText: String(document.getElementById(summaryId)?.textContent || "").trim(),
      totals: {
        a: String(document.getElementById("totalA")?.textContent || "").trim(),
        b: String(document.getElementById("totalB")?.textContent || "").trim(),
      },
    }), truthSummaryId);

    expect(String(runtimeSnapshot.authorityState?.message || "")).toContain("Using frontend fallback totals");
    expect(Number(runtimeSnapshot.diagnostics?.fallback?.usedCount || 0)).toBeGreaterThan(0);
    expect(runtimeSnapshot.totals.a !== "–" || runtimeSnapshot.totals.b !== "–").toBeTruthy();
    expect(String(runtimeSnapshot.truthState?.headline || "")).toContain("partial");
    expect(runtimeSnapshot.truthText).toContain("local fallback totals");

    guard.assertClean();
  });

  test("fallback disallow blocks totals when backend scoring is unavailable", async ({ page, request }, testInfo) => {
    const guard = attachConsoleGuards(page, {
      allow: [
        "Fallback disallowed while backend trade scoring unavailable",
        "Failed to load resource: the server responded with a status of 503",
      ],
    });
    await gotoApp(page, request);
    await openCalculatorTab(page, testInfo);

    const [p1, p2] = await getSamplePlayerNames(page);
    expect(p1).toBeTruthy();
    expect(p2).toBeTruthy();

    await page.evaluate(() => {
      window.__tradeFallbackPolicy = "disallow";
    });

    await page.route("**/api/trade/score", async (route) => {
      await route.fulfill({
        status: 503,
        contentType: "application/json",
        body: JSON.stringify({ ok: false, error: "forced-outage" }),
      });
    });

    await addTwoSides(page, p1, p2);

    const truthSummaryId = getTruthSummaryId(testInfo);
    await page.waitForFunction(
      (summaryId) => {
        const diag = window.__tradeCalculatorPackageDiagnostics || null;
        const state = window.__tradeCalculatorAuthorityState || null;
        const truthText = String(document.getElementById(summaryId)?.textContent || "").trim();
        return (
          !!diag &&
          Number(diag.fallback?.blockedCount || 0) > 0 &&
          String(diag.authority || "") === "backend_trade_scoring_required_fallback_disallowed" &&
          !!state &&
          state.visible === true &&
          String(state.level || "") === "error" &&
          truthText.length > 0
        );
      },
      truthSummaryId,
      { timeout: 20_000 },
    );

    const uiState = await page.evaluate((summaryId) => ({
      totalA: String(document.getElementById("totalA")?.textContent || "").trim(),
      totalB: String(document.getElementById("totalB")?.textContent || "").trim(),
      decision: String(document.getElementById("decision")?.textContent || "").trim(),
      authority: window.__tradeCalculatorAuthorityState || null,
      truthState: window.__tradeCalculatorTruthState || null,
      truthText: String(document.getElementById(summaryId)?.textContent || "").trim(),
    }), truthSummaryId);

    expect(uiState.totalA).toBe("–");
    expect(uiState.totalB).toBe("–");
    expect(uiState.decision).toBe("–");
    expect(String(uiState.authority?.message || "")).toContain("required");
    expect(String(uiState.truthState?.headline || "")).toContain("totals withheld");
    expect(uiState.truthText).toContain("blocked totals");

    guard.assertClean();
  });

  test("contract mismatch is surfaced as hard authority error", async ({ page, request }, testInfo) => {
    const guard = attachConsoleGuards(page, {
      allow: ["Calculator/runtime contract version mismatch detected"],
    });
    await gotoApp(page, request);
    await openCalculatorTab(page, testInfo);

    const [p1, p2] = await getSamplePlayerNames(page);
    expect(p1).toBeTruthy();
    expect(p2).toBeTruthy();

    await page.route("**/api/trade/score", async (route) => {
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({
          ok: true,
          authority: "backend_trade_scoring_v1",
          contractVersion: "mismatch-contract-v0",
          summary: { inputItems: 2, backendResolved: 2, fallbackUsed: 0, quarantinedExcluded: 0, unresolvedExcluded: 0 },
          sides: {
            A: { weightedTotal: 5100, packageDeltaPct: 1.0 },
            B: { weightedTotal: 5000, packageDeltaPct: 1.2 },
            C: { weightedTotal: 0, packageDeltaPct: 0.0 },
          },
        }),
      });
    });

    await addTwoSides(page, p1, p2);

    const mismatchState = await page.evaluate(() => {
      const diag = window.__tradeCalculatorPackageDiagnostics || null;
      const authority = window.__tradeCalculatorAuthorityState || null;
      return {
        mismatch: Boolean(diag?.contract?.mismatch),
        runtimeVersion: String(diag?.contract?.runtimeVersion || ""),
        backendVersion: String(diag?.contract?.backendVersion || ""),
        authority,
      };
    });

    expect(mismatchState.mismatch).toBeTruthy();
    expect(mismatchState.runtimeVersion).not.toBe("");
    expect(mismatchState.backendVersion).toBe("mismatch-contract-v0");
    expect(String(mismatchState.authority?.level || "")).toBe("error");
    expect(String(mismatchState.authority?.message || "")).toContain("contract mismatch");

    guard.assertClean();
  });

  test("truth summary surfaces fallback/exclusion/manual/low-confidence counts", async ({ page, request }, testInfo) => {
    const guard = attachConsoleGuards(page);
    await gotoApp(page, request);
    await openCalculatorTab(page, testInfo);

    const [p1, p2] = await getSamplePlayerNames(page);
    expect(p1).toBeTruthy();
    expect(p2).toBeTruthy();

    const runtimeContractVersion = await page.evaluate(() => {
      if (typeof window.resolveRuntimeContractVersion === "function") {
        return String(window.resolveRuntimeContractVersion() || "").trim() || "unknown";
      }
      return (
        String(window.loadedData?.contractVersion || window.loadedData?.contract?.version || "").trim() ||
        "unknown"
      );
    });

    await page.route("**/api/trade/score", async (route) => {
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({
          ok: true,
          authority: "backend_trade_scoring_v1",
          contractVersion: runtimeContractVersion,
          summary: {
            inputItems: 3,
            backendResolved: 1,
            fallbackUsed: 1,
            quarantinedExcluded: 1,
            unresolvedExcluded: 1,
          },
          sides: {
            A: {
              weightedTotal: 5200,
              packageDeltaPct: 1.5,
              unresolvedEntries: [{ label: "Mystery Asset", reason: "quarantined_from_final_authority" }],
            },
            B: {
              weightedTotal: 5100,
              packageDeltaPct: 1.0,
              unresolvedEntries: [{ label: "Unknown Asset", reason: "unresolved_unresolved" }],
            },
            C: { weightedTotal: 0, packageDeltaPct: 0.0, unresolvedEntries: [] },
          },
        }),
      });
    });

    await page.evaluate(() => {
      if (typeof window.computeFinalAdjustedValue !== "function") return;
      const original = window.computeFinalAdjustedValue;
      window.computeFinalAdjustedValue = function patchedComputeFinalAdjustedValue(...args) {
        const result = original.apply(this, args);
        if (!result || typeof result !== "object") return result;
        result.marketReliability = {
          ...(result.marketReliability || {}),
          score: 0.42,
          label: "low",
        };
        result.marketReliabilityScore = 0.42;
        return result;
      };
    });

    await page.evaluate(() => window.clearPlayers?.());
    await addAssetViaGlobalSearch(page, "A", p1);
    await addAssetViaGlobalSearch(page, "B", p2);

    await page.evaluate(() => {
      const row = document.querySelector("#sideABody tr");
      if (!row) return;
      const firstSite = row.querySelector(".site-input");
      if (firstSite) {
        firstSite.value = "1200";
        firstSite.dispatchEvent(new Event("input", { bubbles: true }));
      }
    });

    const truthSummaryId = getTruthSummaryId(testInfo);
    await page.waitForFunction(
      (summaryId) => {
        const text = String(document.getElementById(summaryId)?.textContent || "").toLowerCase();
        const diag = window.__tradeCalculatorPackageDiagnostics || null;
        return !!diag && text.includes("manual overrides") && text.includes("quarantined excluded");
      },
      truthSummaryId,
      { timeout: 20_000 },
    );

    const snapshot = await page.evaluate((summaryId) => ({
      truthText: String(document.getElementById(summaryId)?.textContent || "").trim(),
      truthState: window.__tradeCalculatorTruthState || null,
      resolution: window.__tradeCalculatorPackageDiagnostics?.resolution || null,
    }), truthSummaryId);

    expect(snapshot.truthText).toContain("fallback rows 1");
    expect(snapshot.truthText).toContain("quarantined excluded 1");
    expect(snapshot.truthText).toContain("unresolved excluded 1");
    expect(snapshot.truthText).toContain("manual overrides");
    expect(snapshot.truthText).toContain("low confidence");
    expect(String(snapshot.truthState?.title || "")).toContain("Mystery Asset");
    expect(String(snapshot.truthState?.title || "")).toContain("Unknown Asset");
    expect(Number(snapshot.resolution?.manualOverrideRows || 0)).toBeGreaterThan(0);
    expect(Number(snapshot.resolution?.lowConfidenceRows || 0)).toBeGreaterThan(0);

    guard.assertClean();
  });

  test("best-ball assumption is explicit in authority diagnostics", async ({ page, request }, testInfo) => {
    const guard = attachConsoleGuards(page);
    await gotoApp(page, request);
    await openCalculatorTab(page, testInfo);

    const [p1, p2] = await getSamplePlayerNames(page);
    expect(p1).toBeTruthy();
    expect(p2).toBeTruthy();

    await page.evaluate(() => {
      const runtimeData = window.loadedData || null;
      if (runtimeData) {
        if (!runtimeData.sleeper || typeof runtimeData.sleeper !== "object") runtimeData.sleeper = {};
        if (!runtimeData.sleeper.leagueSettings || typeof runtimeData.sleeper.leagueSettings !== "object") {
          runtimeData.sleeper.leagueSettings = {};
        }
        delete runtimeData.sleeper.leagueSettings.best_ball;
      }
      window.__tradeBestBallDefault = true;
    });

    const runtimeContractVersion = await page.evaluate(() => {
      if (typeof window.resolveRuntimeContractVersion === "function") {
        return String(window.resolveRuntimeContractVersion() || "").trim() || "unknown";
      }
      if (typeof resolveRuntimeContractVersion === "function") {
        return String(resolveRuntimeContractVersion() || "").trim() || "unknown";
      }
      return (
        String(window.loadedData?.contractVersion || window.loadedData?.contract?.version || "").trim() ||
        "unknown"
      );
    });

    await page.route("**/api/trade/score", async (route) => {
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({
          ok: true,
          authority: "backend_trade_scoring_v1",
          contractVersion: runtimeContractVersion,
          summary: { inputItems: 2, backendResolved: 2, fallbackUsed: 0, quarantinedExcluded: 0, unresolvedExcluded: 0 },
          sides: {
            A: { weightedTotal: 5100, packageDeltaPct: 1.0 },
            B: { weightedTotal: 5000, packageDeltaPct: 1.2 },
            C: { weightedTotal: 0, packageDeltaPct: 0.0 },
          },
        }),
      });
    });

    await addTwoSides(page, p1, p2);

    const snapshot = await page.evaluate(() => ({
      diagnostics: window.__tradeCalculatorPackageDiagnostics || null,
      authorityState: window.__tradeCalculatorAuthorityState || null,
      explicitFlag: window.loadedData?.sleeper?.leagueSettings?.best_ball,
    }));

    expect(snapshot.diagnostics).toBeTruthy();
    expect(snapshot.diagnostics.bestBallContext).toBeTruthy();
    expect(typeof snapshot.diagnostics.bestBallContext.assumed).toBe("boolean");
    expect(String(snapshot.diagnostics.bestBallContext.source || "")).not.toBe("");
    expect(Number(snapshot.diagnostics?.fallback?.usedCount || 0)).toBe(0);
    if (snapshot.diagnostics.bestBallContext.assumed) {
      expect(String(snapshot.authorityState?.level || "")).toBe("warning");
      expect(String(snapshot.authorityState?.message || "")).toContain("Best-ball context is assumed");
    }

    guard.assertClean();
  });
});
