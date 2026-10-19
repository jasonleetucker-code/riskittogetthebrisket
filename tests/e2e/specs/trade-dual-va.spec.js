/**
 * /trade — dual Value Adjustment comparison (owner directive 2026-10-19,
 * parts 2–3), desktop (1366) and phone (390).
 *
 *   - the decision area carries ONE compact comparison: Chase Upside's
 *     adjustment beside the KTC adjustment method, on the page's own canonical
 *     values; its calculation opens on demand;
 *   - Second Opinions has ONE "Compare adjustments" control: a column on
 *     desktop, a line under each source name on a phone;
 *   - neither changes the official decision or the independent tally;
 *   - axe (WCAG 2.0/2.1 A + AA) is clean on both, populated and expanded;
 *     the page never scrolls sideways.
 *
 * `POST /api/trade/analyze` is answered from the real-output fixtures (as in
 * trade-war-room.spec.js); everything else is the seeded stack.  The trade is a
 * two-for-one so a package adjustment exists under both methods.
 */
const fs = require("fs");
const path = require("path");
const { test, expect } = require("../helpers/auth-fixture");
const { pageUrl, awaitStreamSettled, contractFixture } = require("../helpers/journey");
const AxeBuilder = require("@axe-core/playwright").default;
const { closeTradeSheet, openTradeSearch } = require("../helpers/trade-builder");

test.use({ serviceWorkers: "block" });

const TAGS = ["wcag2a", "wcag2aa", "wcag21a", "wcag21aa"];
const FIXTURES = path.resolve(__dirname, "../../../frontend/__tests__/fixtures/trade-war-room");
const CONSOLIDATION = JSON.parse(fs.readFileSync(path.join(FIXTURES, "consolidation.json"), "utf-8"));
const PICK_TOKEN = /\d{4}/;

async function noPageOverflow(page, label) {
  const sizes = await page.evaluate(() => ({
    document: document.documentElement.scrollWidth,
    viewport: document.documentElement.clientWidth,
  }));
  expect(sizes.document, `no sideways page scroll (${label})`).toBeLessThanOrEqual(sizes.viewport + 1);
}

async function axeClean(page, selector, label) {
  const results = await new AxeBuilder({ page }).withTags(TAGS).include(selector).analyze();
  expect(
    results.violations.map((v) => `${v.id}: ${v.nodes.map((n) => n.target.join(" ")).slice(0, 3).join(" | ")}`),
    `axe violations (${label})`,
  ).toEqual([]);
}

/** A team, two of its board-resolvable players, and one player from another team. */
async function pickTwoForOne(page) {
  const { teams, playerNames } = await contractFixture(page);
  const board = new Set(playerNames);
  for (const [idx, team] of teams.entries()) {
    const mine = (team.players || []).filter((p) => p && !PICK_TOKEN.test(p) && board.has(p));
    const other = teams.find((t) => t !== team);
    const receive = (other?.players || []).find(
      (p) => p && !PICK_TOKEN.test(p) && board.has(p) && !(team.players || []).includes(p),
    );
    if (mine.length >= 2 && receive) return { idx, give: mine.slice(0, 2), receive };
  }
  throw new Error("no team with two board-resolvable players on the seeded contract");
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

test("dual VA: compact comparison in the decision area and Compare adjustments in Second Opinions", async ({
  authedPage: page,
}, testInfo) => {
  const phone = testInfo.project.name !== "desktop-1366";
  const errors = [];
  page.on("pageerror", (e) => errors.push(e.message));
  await page.route(
    (url) => url.pathname === "/api/trade/analyze",
    async (route) => {
      const body = route.request().postDataJSON() || {};
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        headers: { "Cache-Control": "no-store" },
        body: JSON.stringify({ ...CONSOLIDATION, leagueKey: body.leagueKey || CONSOLIDATION.leagueKey }),
      });
    },
  );

  const trade = await pickTwoForOne(page);
  await page.goto(pageUrl("/trade"), { waitUntil: "domcontentloaded" });
  await awaitStreamSettled(page);
  await expect(page.getByRole("heading", { level: 1, name: /^Trade Calculator$/ })).toBeVisible({
    timeout: 60_000,
  });
  await page.waitForFunction(() => !document.body.innerText.includes("Loading player pool..."), null, {
    timeout: 90_000,
  });
  await page.selectOption("#suggest-team", String(trade.idx));
  for (const name of trade.give) await addToSide(page, "A", name);
  await addToSide(page, "B", trade.receive);

  // The official decision, before anything is compared.
  const headline = page.locator('[data-war-room="ok"]').getByTestId("decision-headline");
  await expect(headline).toHaveText(CONSOLIDATION.analysis.decision.headlineText, { timeout: 30_000 });

  // ── Decision area: the compact comparison ──
  const vac = page.getByTestId("va-comparison");
  await expect(vac).toBeVisible({ timeout: 30_000 });
  await expect(vac.getByTestId("va-comparison-summary")).toHaveText(
    /^(Both methods agree|The methods disagree|No package adjustment under either method)/,
  );
  // A two-for-one carries a package adjustment under the geometric model.
  await expect(vac).not.toHaveAttribute("data-tone", "none");
  await expect(vac.getByTestId("va-comparison-gaps")).toContainText("KTC adjustment method");
  const show = vac.getByRole("button", { name: "Show the calculation" });
  await expect(show).toHaveAttribute("aria-expanded", "false");
  await show.click();
  const table = vac.getByTestId("va-comparison-table");
  await expect(table).toBeVisible();
  await expect(table.getByRole("columnheader")).toHaveText([
    "Measure",
    "Chase Upside adjustment (used)",
    "KTC adjustment method",
  ]);
  await expect(vac).toContainText("These are not KTC's own player values.");
  await expect(headline).toHaveText(CONSOLIDATION.analysis.decision.headlineText);
  await noPageOverflow(page, "comparison open");
  await axeClean(page, '[data-testid="va-comparison"]', "va comparison, expanded");
  const vacShot = testInfo.outputPath("va-comparison.png");
  await vac.screenshot({ path: vacShot });
  await testInfo.attach("va-comparison", { path: vacShot, contentType: "image/png" });

  // ── Second Opinions: one Compare adjustments control ──
  const intel = page.locator("#trade-intelligence");
  await intel.getByRole("tab", { name: "Value" }).click();
  await intel.getByRole("button", { name: "Second opinions" }).click();
  const card = intel.locator(".source-breakdown-card");
  await expect(card).toBeVisible({ timeout: 30_000 });
  const tally = card.getByTestId("second-opinions-tally");
  await expect(tally).toBeVisible();
  const tallyBefore = await tally.textContent();
  const compare = card.getByRole("button", { name: "Compare adjustments" });
  await expect(compare).toHaveAttribute("aria-pressed", "false");
  await expect(card.getByTestId("second-opinions-compare-col")).toHaveCount(0);
  await compare.click();
  await expect(compare).toHaveAttribute("aria-pressed", "true");
  await expect(card.getByTestId("second-opinions-compare-note")).toContainText(
    "not that source's own calculator",
  );
  await expect(card.getByTestId("second-opinions-compare-count")).toHaveText(
    /^(Same leader on all \d+|Leader differs on \d+ of \d+|No source has a numeric verdict)/,
  );
  if (phone) {
    // Phone: no extra column to pan to; the answer reads under each source name.
    await expect(card.getByTestId("second-opinions-compare-col")).toBeHidden();
    await expect(card.getByTestId("second-opinions-compare-inline").first()).toBeVisible();
  } else {
    await expect(card.getByTestId("second-opinions-compare-col")).toBeVisible();
    await expect(card.getByTestId("second-opinions-compare-inline").first()).toBeHidden();
  }
  // Neither the independent tally nor the official decision moved.
  await expect(tally).toHaveText(tallyBefore);
  await expect(headline).toHaveText(CONSOLIDATION.analysis.decision.headlineText);
  await noPageOverflow(page, "compare adjustments on");
  await axeClean(page, ".source-breakdown-card", "second opinions, compare on");
  const soShot = testInfo.outputPath("second-opinions-compare.png");
  await card.screenshot({ path: soShot });
  await testInfo.attach("second-opinions-compare", { path: soShot, contentType: "image/png" });

  await compare.click();
  await expect(compare).toHaveAttribute("aria-pressed", "false");
  await expect(tally).toHaveText(tallyBefore);
  expect(errors).toEqual([]);
});
