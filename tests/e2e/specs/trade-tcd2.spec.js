/**
 * /trade TC-D2 journeys, desktop (1366) and phone (390), on the real stack.
 *
 *   - no "Market / My league" control (TCM-D09);
 *   - CSV / JSON / Copy KTC URL sit in the toolbar's "More" group;
 *   - phones add through one bottom sheet per side (desktop keeps the inline
 *     search), every builder control at least 44 px tall on the phone;
 *   - Supporting intelligence is five drilldown tabs; Value shows the package
 *     breakdown (stacked bars + Quick Trade Facts), Roster holds Simulate
 *     impact's surface, Reasoning states why there is no decision without a
 *     team;
 *   - a 3-team trade keeps a persistent summary (the phone's bottom bar);
 *   - no horizontal page scroll at any step.
 *
 * Players are derived from the seeded contract, never hardcoded, and only
 * from rows /trade will actually PRICE: the seeded contract follows the real
 * sources, so "the first three valued rows" can include a row whose value the
 * page withholds (quarantined, or a stale freshness axis) — and a 3-team
 * trade carrying one reads "not determinable", which is a different journey
 * (the withheld path is pinned by trade-multi-team.spec.js F2).  #1918.  Auth:
 * the test-only session fixture.  Screenshots go to the test's output dir
 * (never a tracked file).
 */
const { test, expect } = require("../helpers/auth-fixture");
const { pageUrl, awaitStreamSettled, contractFixture } = require("../helpers/journey");
const { closeTradeSheet, openTradeSearch } = require("../helpers/trade-builder");
const { TRADE_DATA_VIEW, boardRow, isTradeableRow } = require("../helpers/trade-board");

test.use({ serviceWorkers: "block" });

const PICK_TOKEN = /\d{4}/;

// Priced AND trusted: a positive canonical value the page does not withhold
// (helpers/trade-board.js mirrors the page's own withheld rule).
function pricedPlayers(contract, playerNames, n) {
  const out = [];
  for (const name of playerNames) {
    if (PICK_TOKEN.test(name)) continue;
    if (isTradeableRow(boardRow(contract, name))) out.push(name);
    if (out.length >= n) break;
  }
  return out;
}

async function noSidewaysScroll(page, step) {
  const widths = await page.evaluate(() => ({
    document: document.documentElement.scrollWidth,
    viewport: window.innerWidth,
  }));
  expect(widths.document, `no horizontal page scroll (${step})`).toBeLessThanOrEqual(widths.viewport + 1);
}

async function addToSide(page, sideLabel, name) {
  const input = await openTradeSearch(page, sideLabel);
  await input.fill(name);
  const escaped = name.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
  const result = page
    .locator(".trade-side-search-result")
    .filter({ has: page.locator(".trade-side-search-result-name", { hasText: new RegExp(`^${escaped}$`) }) })
    .first();
  await expect(result).toBeVisible({ timeout: 15_000 });
  await result.click();
  await closeTradeSheet(page);
  await expect(page.getByRole("button", { name: `Remove ${name} from Side ${sideLabel}` })).toBeVisible();
}

test("trade TC-D2: toolbar, builder sheets, drilldown tabs, 3-team summary, no sideways scroll", async ({
  authedPage: page,
}, testInfo) => {
  const phone = testInfo.project.name.startsWith("mobile");
  // The view /trade itself reads, so the rows chosen are the rows it prices.
  const { contract, playerNames } = await contractFixture(page, { view: TRADE_DATA_VIEW });
  const [a, b, c] = pricedPlayers(contract, playerNames, 3);
  test.skip(!c, "seeded contract carries fewer than three priced, trusted players");

  await page.goto(pageUrl("/trade"), { waitUntil: "domcontentloaded" });
  await awaitStreamSettled(page);
  await expect(page.getByRole("heading", { level: 1, name: /^Trade Calculator$/ })).toBeVisible({
    timeout: 60_000,
  });
  await page.waitForFunction(() => !document.body.innerText.includes("Loading player pool..."), null, {
    timeout: 90_000,
  });
  await page.getByRole("button", { name: "Clear Trade", exact: true }).click();

  // D09: the withdrawn lens has no control.
  await expect(page.getByText("My league", { exact: true })).toHaveCount(0);

  // Builder: the phone shows one "Add to Side" button per side, no inline search.
  if (phone) {
    await expect(page.getByRole("button", { name: "Add to Side A", exact: true })).toBeVisible();
    await expect(page.locator('input[aria-label="Search to add a player to Side A"]')).toHaveCount(0);
  } else {
    await expect(page.getByLabel("Search to add a player to Side A")).toBeVisible();
  }
  await addToSide(page, "A", a);
  await addToSide(page, "B", b);
  await noSidewaysScroll(page, "two-team trade");

  // Toolbar: exports live in the More group.
  const toolbar = page.locator(".trade-controls");
  await expect(toolbar.getByRole("button", { name: "Download CSV" })).toHaveCount(0);
  await toolbar.getByRole("button", { name: "More", exact: true }).click();
  const more = page.getByRole("group", { name: "More trade actions" });
  await expect(more.getByRole("button")).toHaveText(["Copy KTC URL", "Download CSV", "Download JSON"]);
  await toolbar.getByRole("button", { name: "More", exact: true }).click();
  await expect(more).toHaveCount(0);
  if (phone) {
    for (const btn of await toolbar.getByRole("button").all()) {
      const box = await btn.boundingBox();
      if (box) expect(box.height, "toolbar target >= 44 px").toBeGreaterThanOrEqual(43.5);
    }
  }

  // Supporting intelligence: five tabs, Value open by default.
  const intel = page.locator("#trade-intelligence");
  await expect(intel.getByRole("tab")).toHaveText(["Value", "Roster", "Season", "Market", "Reasoning"]);
  await expect(intel.getByTestId("package-breakdown")).toBeVisible({ timeout: 30_000 });
  await expect(intel.getByTestId("package-bar-A")).toBeVisible();
  await expect(intel.getByRole("table", { name: /Quick trade facts/ })).toBeVisible();
  await page.screenshot({ path: testInfo.outputPath("tcd2-value-tab.png"), fullPage: true });
  await intel.getByRole("tab", { name: "Roster" }).click();
  await expect(intel.getByRole("tabpanel")).toBeVisible();
  await intel.getByRole("tab", { name: "Reasoning" }).click();
  await expect(intel.getByRole("tabpanel")).toContainText(/decision|team|Analy/i, { timeout: 30_000 });
  if (phone) {
    const tab = await intel.getByRole("tab", { name: "Market" }).boundingBox();
    expect(tab.height, "tab target >= 44 px").toBeGreaterThanOrEqual(43.5);
  }
  await noSidewaysScroll(page, "intelligence tabs");

  // 3-team: a persistent summary of the meter's own reading.
  await page.getByRole("button", { name: "Add Team", exact: true }).click();
  await addToSide(page, "C", c);
  const summary = page.getByTestId("trade-multi-summary");
  await expect(summary).toHaveCount(1);
  // The meter's own per-team reading, labelled PRELIMINARY and pointing at
  // the War Room for the final per-team answer (no team is bound here, so no
  // War Room answer exists and the bar must not claim a final result).
  const NET = "[+\u2212]?\\d[\\d,]*";
  const reading = new RegExp(
    `^A (${NET})B (${NET})C (${NET})Preliminary \u00b7 (FAIR|SLIGHT EDGE|UNFAIR|LOPSIDED) \u00b7 widest gap Side ([ABC]) (${NET}) \u00b7 final result in the War Room$`,
  );
  await expect(summary).toHaveText(reading);
  const m = reading.exec((await summary.textContent()).replace(/\s+/g, " ").trim());
  expect(m, "summary text parses").not.toBeNull();
  // The widest gap it names is that side's own net, as shown beside it.
  expect(m[6]).toBe(m[1 + "ABC".indexOf(m[5])]);
  await expect(summary).not.toContainText(/Final:|reliable YES \/ NO unavailable/);
  if (phone) await expect(summary).toBeVisible();
  await page.screenshot({ path: testInfo.outputPath("tcd2-three-team.png"), fullPage: false });
  await noSidewaysScroll(page, "three-team trade");
});
