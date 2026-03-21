const { expect } = require("@playwright/test");

function isMobileProject(testInfo) {
  const projectName = String(testInfo?.project?.name || "");
  return projectName.startsWith("mobile-") || projectName.startsWith("tablet-");
}

function attachConsoleGuards(page, { allow = [] } = {}) {
  const consoleErrors = [];
  const pageErrors = [];

  page.on("console", (msg) => {
    if (msg.type() !== "error") return;
    const text = msg.text() || "";
    if (allow.some((frag) => text.includes(frag))) return;
    consoleErrors.push(text);
  });

  page.on("pageerror", (err) => {
    const text = String(err && err.stack ? err.stack : err);
    if (allow.some((frag) => text.includes(frag))) return;
    pageErrors.push(text);
  });

  return {
    assertClean() {
      expect.soft(consoleErrors, "unexpected browser console errors").toEqual([]);
      expect.soft(pageErrors, "unexpected page errors").toEqual([]);
    },
    consoleErrors,
    pageErrors,
  };
}

async function ensureApiDataReady(page, request) {
  let okPayload = null;
  for (let i = 0; i < 45; i += 1) {
    const resp = await request.get("/api/data?view=app", { timeout: 20_000 });
    if (resp.ok()) {
      const data = await resp.json();
      const count = Object.keys(data.players || {}).length;
      if (count > 50) {
        okPayload = data;
        break;
      }
    }
    await page.waitForTimeout(1_500);
  }
  expect(okPayload, "expected /api/data?view=app to become available").not.toBeNull();
  return okPayload;
}

async function gotoApp(page, request) {
  const username = process.env.E2E_JASON_USERNAME || "jasonleetucker";
  const password = process.env.E2E_JASON_PASSWORD || "e2e-local-password";
  // Keep parity runs deterministic: do not reuse prior local/session state.
  await page.addInitScript(() => {
    try {
      window.localStorage.clear();
      window.sessionStorage.clear();
    } catch (_) {}
  });
  try {
    await page.request.post("/api/auth/login", {
      data: { username, password, next: "/app" },
    });
  } catch (_) {}
  await page.goto("/app", { waitUntil: "domcontentloaded" });
  await ensureApiDataReady(page, request);
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
}

async function openTab(page, tabId) {
  await page.evaluate((id) => {
    if (typeof window.switchTab === "function") window.switchTab(id);
  }, tabId);
  await page.waitForFunction(
    (id) => {
      const el = document.getElementById(`tab-${id}`);
      return !!el && el.classList.contains("active");
    },
    tabId
  );
}

async function openMobilePrimary(page, tabId) {
  const btn = page.locator(`.mobile-nav-btn[data-mobile-tab="${tabId}"]`);
  if (await btn.count()) {
    await btn.first().click();
  } else {
    await openTab(page, tabId);
  }
}

async function getSamplePlayerNames(page) {
  return await page.evaluate(() => {
    const runtimeData =
      window.loadedData ||
      (typeof loadedData !== "undefined" ? loadedData : null);
    const names = Object.keys(runtimeData?.players || {});
    const nonPicks = names.filter((name) => {
      if (typeof window.parsePickToken === "function" && window.parsePickToken(name)) return false;
      return !/\b20\d{2}\b\s+(pick|round|[1-6]\.)/i.test(name);
    });
    const uniq = [...new Set(nonPicks)];
    return uniq.slice(0, 6);
  });
}

async function addAssetViaGlobalSearch(page, side, playerName) {
  await page.evaluate(
    ({ targetSide }) => {
      if (typeof window.openGlobalSearchForTrade === "function") window.openGlobalSearchForTrade(targetSide);
    },
    { targetSide: side }
  );
  await expect(page.locator("#globalSearchOverlay")).toHaveClass(/active/);

  const input = page.locator("#globalSearchInput");
  await input.fill(playerName);
  await page.waitForTimeout(250);

  const addBtn = page.locator("#globalSearchBody .gs-actions .mobile-chip-btn.primary").first();
  await expect(addBtn).toBeVisible();
  await addBtn.click();

  await page.waitForFunction(
    ({ targetSide, name }) => {
      if (typeof window.getTradeSideAssets !== "function") return false;
      const rows = window.getTradeSideAssets(targetSide) || [];
      return rows.some((r) => String(r?.name || "").toLowerCase() === String(name).toLowerCase());
    },
    { targetSide: side, name: playerName }
  );
}

async function getTradeAssets(page) {
  return await page.evaluate(() => ({
    A: (window.getTradeSideAssets?.("A") || []).map((r) => r.name),
    B: (window.getTradeSideAssets?.("B") || []).map((r) => r.name),
    C: (window.getTradeSideAssets?.("C") || []).map((r) => r.name),
  }));
}

async function setTradeModeThreeTeam(page, enable, testInfo) {
  if (isMobileProject(testInfo)) {
    const toggle = page.locator("#mobileMultiTeamToggle");
    if (await toggle.count()) {
      const checked = await toggle.isChecked();
      if (checked !== enable) await toggle.click();
    }
  } else {
    const toggle = page.locator("#multiTeamToggle");
    const checked = await toggle.isChecked();
    if (checked !== enable) await toggle.click();
  }
  await page.waitForFunction((flag) => {
    const c = document.getElementById("tileSideC");
    return !!c && ((c.style.display !== "none") === !!flag);
  }, enable);
}

async function clickSwap(page, testInfo) {
  if (isMobileProject(testInfo)) {
    await page.locator("#mobileTradeWorkspace button").filter({ hasText: "Swap" }).first().click();
  } else {
    await page.locator("button").filter({ hasText: "⇄ Swap" }).first().click();
  }
}

async function clickClear(page, testInfo) {
  if (isMobileProject(testInfo)) {
    await page.locator("#mobileTradeWorkspace button").filter({ hasText: "Clear" }).first().click();
  } else {
    await page.locator("button").filter({ hasText: "⟳ Clear" }).first().click();
  }
}

module.exports = {
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
};
