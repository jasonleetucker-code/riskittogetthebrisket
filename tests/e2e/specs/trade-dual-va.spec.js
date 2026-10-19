/**
 * /trade — dual Value Adjustment comparison (owner directive 2026-10-19,
 * parts 2–3), desktop (1366) and phone (390).
 *
 *   - the decision area carries ONE compact comparison: Chase Upside's
 *     adjustment beside the KTC adjustment method, on the page's own canonical
 *     values; its calculation opens on demand;
 *   - Second Opinions has ONE "Compare adjustments" control: a KTC-method
 *     line under each source name, the same on desktop and phone;
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

/**
 * The Second Opinions table's geometry with its scroll region at the left
 * edge: how wide the table is against its visible box, how many rows' verdict
 * (Leader) and Margin cells end past the visible right edge, and how many
 * compare lines have text past it (measured on the TEXT, via a Range, not on
 * the block) or overflow their own box.
 */
async function sourceTableGeometry(card) {
  return card.evaluate((root) => {
    const wrap = root.querySelector("#source-breakdown-body");
    const table = wrap.querySelector("table.source-breakdown-table");
    wrap.scrollLeft = 0;
    const box = wrap.getBoundingClientRect();
    const visibleRight = Math.min(box.right, document.documentElement.clientWidth);
    const rows = [...table.querySelectorAll("tbody > tr[data-state]")];
    const past = (el) => el.getBoundingClientRect().right > visibleRight + 1;
    const lines = [...table.querySelectorAll('[data-testid="second-opinions-compare-line"]')];
    const textRight = (el) => {
      const range = document.createRange();
      range.selectNodeContents(el);
      return range.getBoundingClientRect().right;
    };
    return {
      viewport: document.documentElement.clientWidth,
      visibleWidth: Math.round(visibleRight - box.left),
      tableScrollWidth: wrap.scrollWidth,
      rows: rows.length,
      leaderClipped: rows.filter((r) => past(r.children[r.children.length - 2])).length,
      marginClipped: rows.filter((r) => past(r.children[r.children.length - 1])).length,
      // The pre-existing coverage meta line under each source name.
      metaClipped: rows.filter((r) => {
        const meta = r.children[0].querySelector("span.muted");
        return meta && textRight(meta) > visibleRight + 1;
      }).length,
      lines: lines.length,
      linesClipped: lines.filter(
        (l) => textRight(l) > visibleRight + 1 || l.scrollWidth > l.clientWidth + 1,
      ).length,
    };
  });
}

/**
 * Compare ON must never make the table wider, never clip a verdict cell that
 * was visible with it OFF, and never clip its own line.  Returns both
 * measurements so the run records the pre-existing state.
 */
async function compareDoesNotClip(card, compare, label, testInfo) {
  if ((await compare.getAttribute("aria-pressed")) === "true") await compare.click();
  await expect(compare).toHaveAttribute("aria-pressed", "false");
  const off = await sourceTableGeometry(card);
  await compare.click();
  await expect(compare).toHaveAttribute("aria-pressed", "true");
  await expect(card.getByTestId("second-opinions-compare-line").first()).toBeVisible();
  const on = await sourceTableGeometry(card);
  await testInfo.attach(`second-opinions-geometry-${label}`, {
    body: JSON.stringify({ off, on }, null, 2),
    contentType: "application/json",
  });
  console.log(`[second-opinions geometry ${label}] off=${JSON.stringify(off)} on=${JSON.stringify(on)}`);
  expect(on.lines, `${label}: one compare line per row`).toBe(on.rows);
  expect(on.tableScrollWidth, `${label}: compare must not widen the table`).toBeLessThanOrEqual(
    off.tableScrollWidth + 1,
  );
  expect(on.leaderClipped, `${label}: verdict cells clipped`).toBeLessThanOrEqual(off.leaderClipped);
  expect(on.marginClipped, `${label}: margin cells clipped`).toBeLessThanOrEqual(off.marginClipped);
  expect(on.metaClipped, `${label}: coverage lines clipped`).toBeLessThanOrEqual(off.metaClipped);
  expect(on.linesClipped, `${label}: compare-line text clipped`).toBe(0);
  return { off, on };
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
  await expect(card.getByTestId("second-opinions-compare-line")).toHaveCount(0);
  await compare.click();
  await expect(compare).toHaveAttribute("aria-pressed", "true");
  await expect(card.getByTestId("second-opinions-compare-note")).toContainText(
    "not that source's own calculator",
  );
  await expect(card.getByTestId("second-opinions-compare-count")).toHaveText(
    /^(Same leader on all \d+|Leader differs on \d+ of \d+|No source has a numeric verdict)/,
  );
  // One line under each source name, the same at every width (the shell caps
  // /trade at 1320 px and this table already fills its column, so no extra
  // column is added to pan to).
  const lines = card.getByTestId("second-opinions-compare-line");
  await expect(lines.first()).toBeVisible();
  await expect(lines.first()).toHaveText(/^KTC method: /);
  await expect(card.locator("table.source-breakdown-table > thead th")).toHaveText([
    "Source",
    "Side A",
    "Side B",
    "Leader",
    "Margin",
  ]);
  // The terse line ("KTC method: A by 58%") never widens or clips the table.
  await compareDoesNotClip(card, compare, testInfo.project.name, testInfo);
  // Neither the independent tally nor the official decision moved.
  await expect(tally).toHaveText(tallyBefore);
  await expect(headline).toHaveText(CONSOLIDATION.analysis.decision.headlineText);
  await noPageOverflow(page, "compare adjustments on");
  await axeClean(page, ".source-breakdown-card", "second opinions, compare on");
  const soShot = testInfo.outputPath("second-opinions-compare.png");
  await card.screenshot({ path: soShot });
  await testInfo.attach("second-opinions-compare", { path: soShot, contentType: "image/png" });

  // The narrowest supported phone width as well.
  if (testInfo.project.name !== "desktop-1366") {
    await page.setViewportSize({ width: 375, height: 812 });
    await compareDoesNotClip(card, compare, "375", testInfo);
    await noPageOverflow(page, "compare adjustments on at 375");
  }

  await compare.click();
  await expect(compare).toHaveAttribute("aria-pressed", "false");
  await expect(tally).toHaveText(tallyBefore);
  expect(errors).toEqual([]);
});
