/**
 * V1-123 Phase 2 — Source Disagreement (`/edge`), on production.
 *
 * frontend/app/edge/page.jsx: stat tiles, a scatter chart, and three
 * signal-panel tabs (Market gaps / Agreement / Data caution). Asserts
 * real board content, not just that the route is reachable — reachability
 * of the LINK to this page is already proven by v1-131-nav-gating.spec.js.
 */
const { test, expect, prodUrl, annotate } = require("./helpers");

test.describe("V1-123 Phase 2: Source Disagreement /edge (production)", () => {
  test("stat tiles and the default Market gaps tab render real signal panels on production", async ({
    prodPage: page,
  }, testInfo) => {
    await page.goto(prodUrl("/edge"), { waitUntil: "domcontentloaded" });

    await expect(page.getByRole("heading", { level: 1, name: "Source Disagreement" })).toBeVisible({
      timeout: 60_000,
    });

    const analyzed = page.getByText("Analyzed", { exact: false }).first();
    await expect(analyzed).toBeVisible({ timeout: 60_000 });

    const gapsPanel = page.getByRole("tabpanel", { name: "Market gaps" });
    await expect(gapsPanel).toBeVisible({ timeout: 30_000 });
    const sellSignals = gapsPanel.getByText("Sell signals", { exact: false });
    await expect(sellSignals).toBeVisible({ timeout: 15_000 });

    const agreementTab = page.getByRole("tab", { name: "Agreement" });
    await agreementTab.click();
    const agreementPanel = page.getByRole("tabpanel", { name: "Agreement" });
    await expect(agreementPanel).toBeVisible({ timeout: 15_000 });
    await expect(agreementPanel.getByText("Consensus assets", { exact: false })).toBeVisible({
      timeout: 15_000,
    });

    const cautionTab = page.getByRole("tab", { name: "Data caution" });
    await cautionTab.click();
    const cautionPanel = page.getByRole("tabpanel", { name: "Data caution" });
    await expect(cautionPanel).toBeVisible({ timeout: 15_000 });
    await expect(cautionPanel.getByText("Flagged anomalies", { exact: false })).toBeVisible({
      timeout: 15_000,
    });

    annotate(testInfo, "edge-tabs", "gaps/agreement/caution all rendered on production");
  });
});
